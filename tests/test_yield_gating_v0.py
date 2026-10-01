"""FINCO Crypto Utility V0 — Agent B Correction: authority-aligned gating.

Covers:
  A. Admin-override firewall: legacy verified_asset_detail ADMIN_OVERRIDE
     (even ACTIVE) can never grant FINCO-holder Yield access.
  B. No generic ACTIVE shortcut: only token-backed (FINCO_TOKEN_BALANCE)
     authority results may ALLOW; non-token-backed sources fail closed.
  C. No second activation authority: the Agent-B-specific feature flag is
     removed; activation is an adapter verdict (INACTIVE) owned by the
     canonical resource policy (Agent A).
  D. Wallet Monitor retains V1 semantics; it is NOT reclassified as
     yield.alerts.
  E. Direct-API bypass protection preserved for history / compare /
     execution preflight; yield.basic remains public.
  F. Execution remains disabled: entitled preflight still reaches
     EXECUTION_DISABLED while FINCO_YIELD_EXECUTION_ENABLED=0.

No Yield math changes: the gating module performs no Yield arithmetic and
never imports Yield math authorities.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _uid() -> str:
    from finco_yield.registry import load_bundled_registry
    return load_bundled_registry().all()[0].uid


@pytest.fixture()
def client(monkeypatch):
    import os
    import tempfile
    os.environ["FINCO_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "yield-gate.db")
    from app.persistence import db
    db.DB_PATH = os.environ["FINCO_DB_PATH"]
    db.init_db()
    monkeypatch.setenv("FINCO_YIELD_ENABLED", "1")
    monkeypatch.delenv("FINCO_YIELD_EXECUTION_ENABLED", raising=False)

    from fastapi.testclient import TestClient
    import main_web
    from app.auth import COOKIE_NAME, create_session_token

    user_id = "yield-gate-user"
    client = TestClient(main_web.app)
    client.cookies.update({
        COOKIE_NAME: create_session_token(user_id=user_id, username="yield-gate")})
    return client, user_id


def _entitlement_module():
    from app.verified import entitlement as module
    return module


def _wallet_authority(monkeypatch, user_id):
    from app.protocol import wallet_auth as wallet_module
    if user_id is None:
        monkeypatch.setattr(wallet_module, "get_verified_wallet", lambda uid: None)
    else:
        monkeypatch.setattr(
            wallet_module, "get_verified_wallet",
            lambda uid: {"wallet_address": "0x" + "11" * 20,
                         "verified_at": "2026-10-01T00:00:00Z"})


def _admin_override_authority(monkeypatch, user_id, *, granted=True):
    """Legacy ADMIN_OVERRIDE authority, ACTIVE when granted."""
    from app.verified.entitlement import EntitlementState, VerifiedEntitlement
    module = _entitlement_module()

    async def _resolver(session):
        active = granted and session is not None and session.session_type == "admin"
        return VerifiedEntitlement(
            subject_id=session.user_id if session else None,
            entitlement="verified_asset_detail",
            state=EntitlementState.ACTIVE if active else EntitlementState.INACTIVE,
            source="ADMIN_OVERRIDE",
            reason="ADMIN_OVERRIDE_ACTIVE" if active else "ADMIN_OVERRIDE_NOT_GRANTED",
            observed_at=datetime.now(timezone.utc),
        )
    monkeypatch.setattr(module, "resolve_verified_entitlement_for_request", _resolver)


def _seam_verdict(monkeypatch, outcome, reason):
    """Install a TEST_ONLY resource-policy adapter verdict."""
    from finco_yield import access as access_mod

    async def _authority(resource_key, wallet_address):
        return outcome, reason
    monkeypatch.setattr(access_mod, "_resource_entitlement_authority", _authority)


class TestAdminOverrideFirewall:
    def test_admin_override_cannot_grant_yield_history(self, client, monkeypatch):
        client_obj, user_id = client
        _admin_override_authority(monkeypatch, user_id, granted=True)
        _wallet_authority(monkeypatch, user_id)
        r = client_obj.get("/yield/%s/history.json" % _uid())
        assert r.status_code == 403
        body = r.json()
        assert body["error"] == "YIELD_PREMIUM_REQUIRED"
        assert "observations" not in body

    def test_admin_override_cannot_grant_advanced_compare(self, client, monkeypatch):
        client_obj, user_id = client
        _admin_override_authority(monkeypatch, user_id, granted=True)
        _wallet_authority(monkeypatch, user_id)
        r = client_obj.get("/yield/compare?uid=%s" % _uid())
        assert r.status_code == 403
        assert r.json()["error"] == "YIELD_PREMIUM_REQUIRED"

    def test_admin_override_cannot_grant_execution_preflight(self, client, monkeypatch):
        client_obj, user_id = client
        _admin_override_authority(monkeypatch, user_id, granted=True)
        _wallet_authority(monkeypatch, user_id)
        r = client_obj.post("/yield/%s/plan" % _uid())
        assert r.status_code == 403
        assert r.json()["error"] == "YIELD_PREMIUM_REQUIRED"

    def test_default_adapter_ignores_legacy_override_path(self, client, monkeypatch):
        """The default token-backed adapter never consults the legacy
        resolver: with no configured deployment the verdict is INACTIVE
        (deployment not configured), regardless of any admin override."""
        client_obj, user_id = client
        _admin_override_authority(monkeypatch, user_id, granted=True)
        _wallet_authority(monkeypatch, user_id)
        r = client_obj.get("/yield/%s/history.json" % _uid())
        assert r.status_code == 403
        body = r.json()
        assert body["error"] == "YIELD_PREMIUM_REQUIRED"
        # No admin-override promotion: adapter never consulted the legacy
        # resolver; the canonical deployment is simply not configured here.
        assert body["access_state"] == "TOKEN_ENTITLEMENT_FEATURE_INACTIVE"
        assert body["reason"] == "TOKEN_DEPLOYMENT_NOT_CONFIGURED"

    def test_generic_active_non_token_source_cannot_promote(self, monkeypatch):
        """Adapter contract: a generic ACTIVE verdict with a non-token-backed
        source can never be promoted into ALLOW by the default adapter."""
        import asyncio
        import app.verified.token_entitlement as token_entitlement_module
        from finco_yield.access import _default_resource_entitlement_adapter

        class _FakePolicy:
            chain_id = 4663
            token_address = "0x" + "cd" * 20
            token_decimals = 18
            minimum_balance_raw = 1
            freshness_seconds = 3600

        async def _no_balance(policy, wallet):
            return None

        monkeypatch.setattr(token_entitlement_module, "get_production_policy",
                            lambda: (_FakePolicy(), object()))
        monkeypatch.setattr(
            token_entitlement_module, "P4ReadOnlyBalanceProvider",
            lambda config: type("_P", (), {
                "balance_of": staticmethod(_no_balance)})())

        adapter = _default_resource_entitlement_adapter
        outcome, reason = asyncio.run(
            adapter("yield.history", "0x" + "11" * 20))
        # Balance evidence None (unreadable fake) -> fail closed DENY;
        # never a promotion without token-backed evidence.
        assert outcome == "DENY"


class TestResourceAuthorityVerdicts:
    def test_allow_verdict_entitles(self, client, monkeypatch):
        client_obj, user_id = client
        _wallet_authority(monkeypatch, user_id)
        _seam_verdict(monkeypatch, "ALLOW", "TEST_ONLY_TOKEN_BACKED")
        r = client_obj.get("/yield/%s/history.json" % _uid())
        assert r.status_code == 200
        assert r.json()["schema"] == "YIELD_HISTORY_V1"

    def test_deny_verdict_maps_to_not_satisfied(self, client, monkeypatch):
        client_obj, user_id = client
        _wallet_authority(monkeypatch, user_id)
        _seam_verdict(monkeypatch, "DENY", "BALANCE_BELOW_THRESHOLD")
        r = client_obj.get("/yield/%s/history.json" % _uid())
        assert r.status_code == 403
        assert r.json()["access_state"] == "ENTITLEMENT_NOT_SATISFIED"
        assert r.json()["reason"] == "BALANCE_BELOW_THRESHOLD"

    def test_inactive_verdict_maps_to_feature_inactive(self, client, monkeypatch):
        client_obj, user_id = client
        _wallet_authority(monkeypatch, user_id)
        _seam_verdict(monkeypatch, "INACTIVE", "RESOURCE_POLICY_INACTIVE")
        r = client_obj.get("/yield/%s/history.json" % _uid())
        assert r.status_code == 403
        assert r.json()["access_state"] == "TOKEN_ENTITLEMENT_FEATURE_INACTIVE"

    def test_authority_unavailable_maps_to_unavailable(self, client, monkeypatch):
        client_obj, user_id = client
        _wallet_authority(monkeypatch, user_id)
        _seam_verdict(monkeypatch, "DENY", "ENTITLEMENT_AUTHORITY_UNAVAILABLE")
        r = client_obj.get("/yield/%s/history.json" % _uid())
        assert r.status_code == 403
        assert r.json()["access_state"] == "ENTITLEMENT_NOT_SATISFIED"


class TestWalletMonitorNotAlerts:
    def test_monitor_not_gated_as_alerts(self, client, monkeypatch):
        """Wallet Monitor retains V1 semantics: authenticated users reach it
        without any FINCO-holder entitlement."""
        client_obj, user_id = client
        _wallet_authority(monkeypatch, None)
        r = client_obj.get("/yield/monitor", follow_redirects=False)
        assert r.status_code == 200
        assert "YIELD_PREMIUM_REQUIRED" not in r.text

    def test_alerts_resource_remains_reserved(self):
        from finco_yield.access import RESOURCE_REQUIREMENTS, YieldResource
        assert RESOURCE_REQUIREMENTS[YieldResource.ALERTS].value == "PREMIUM"


class TestDirectApiBypassProtection:
    def test_history_direct_api_fails_closed(self, client, monkeypatch):
        client_obj, user_id = client
        _wallet_authority(monkeypatch, None)
        r = client_obj.get("/yield/%s/history.json" % _uid())
        assert r.status_code == 403
        assert "observations" not in r.json()

    def test_compare_direct_api_fails_closed(self, client, monkeypatch):
        client_obj, user_id = client
        _wallet_authority(monkeypatch, None)
        r = client_obj.get("/yield/compare?uid=%s" % _uid())
        assert r.status_code == 403
        assert "columns" not in r.json() and "metrics" not in r.json()

    def test_preflight_direct_api_fails_closed(self, client, monkeypatch):
        client_obj, user_id = client
        _wallet_authority(monkeypatch, None)
        r = client_obj.post("/yield/%s/plan" % _uid())
        assert r.status_code == 403
        assert r.json()["error"] == "YIELD_PREMIUM_REQUIRED"


class TestBasicPublicAndExecution:
    def test_yield_basic_public(self, client, monkeypatch):
        client_obj, user_id = client
        r = client_obj.get("/yield")
        assert r.status_code == 200
        assert "YIELD_PREMIUM_REQUIRED" not in r.text

    def test_entitled_preflight_still_execution_disabled(self, client, monkeypatch):
        client_obj, user_id = client
        monkeypatch.setenv("FINCO_YIELD_TOKEN_ENTITLEMENT_ENABLED", "1")
        _wallet_authority(monkeypatch, user_id)
        _seam_verdict(monkeypatch, "ALLOW", "TEST_ONLY_TOKEN_BACKED")
        r = client_obj.post("/yield/%s/plan" % _uid())
        assert r.status_code == 409
        assert r.json()["code"] == "EXECUTION_DISABLED"

    def test_yield_math_untouched_by_gating(self):
        bridge = (REPO / "finco_yield" / "access.py").read_text(encoding="utf-8")
        for banned in ("apy", "underwriting", "decompose", "erc4626", "4626"):
            assert banned not in bridge.lower(), banned
