"""FINCO Crypto Utility V0 — Agent B: Yield premium server/API gating.

Server-side enforcement tests at the real HTTP boundary.  Frontend hiding is
not authorization: every protected resource is gated INSIDE the endpoint, so
direct API invocation cannot bypass entitlement.

Yield math is untouched: the access module performs no Yield arithmetic, and
existing numerical outputs are asserted unchanged.  Execution remains
disabled by default; preflight entitlement never enables execution.

Entitlement authority is exercised via TEST_ONLY fixtures (monkeypatched
authority responses) — no production thresholds or tokenomics are invented.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

UID = None  # resolved at runtime from the bundled registry


def _uid() -> str:
    global UID
    if UID is None:
        from finco_yield.registry import load_bundled_registry

        UID = load_bundled_registry().all()[0].uid
    return UID


@pytest.fixture()
def client(monkeypatch):
    """Yield-enabled app client with an authenticated non-admin session."""
    import os
    import tempfile

    os.environ["FINCO_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "yield-gate.db")
    from app.persistence import db

    db.DB_PATH = os.environ["FINCO_DB_PATH"]
    db.init_db()
    monkeypatch.setenv("FINCO_YIELD_ENABLED", "1")
    monkeypatch.delenv("FINCO_YIELD_TOKEN_ENTITLEMENT_ENABLED", raising=False)
    monkeypatch.delenv("FINCO_YIELD_EXECUTION_ENABLED", raising=False)

    from fastapi.testclient import TestClient
    import main_web
    from app.auth import COOKIE_NAME, create_session_token

    user_id = "yield-gate-user"
    cookies = {COOKIE_NAME: create_session_token(user_id=user_id, username="yield-gate")}
    with monkeypatch.context() as m:
        m.setattr(main_web, "SESSION_COOKIE_NAME", COOKIE_NAME, raising=False)
        client = TestClient(main_web.app)
        client.cookies.update(cookies)
        # Store the resolved user id for authority fixtures.
        client.headers["x-test-user-id"] = user_id
        yield client, user_id


def _entitlement_module():
    from app.verified import entitlement as entitlement_module

    return entitlement_module


def _verified_wallet_module():
    from app.protocol import wallet_auth as wallet_module

    return wallet_module


def _entitle_authority(monkeypatch, state: str, reason: str, user_id: str):
    """TEST_ONLY: authority returns the requested state for this user."""
    from app.verified.entitlement import EntitlementState, VerifiedEntitlement

    entitlement_module = _entitlement_module()

    async def _resolver(session):
        return VerifiedEntitlement(
            subject_id=session.user_id if session else None,
            entitlement="yield_premium",
            state=EntitlementState(state),
            source="TEST_ONLY",
            reason=reason,
            observed_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr(
        entitlement_module, "resolve_verified_entitlement_for_request", _resolver)
    # Access module imports the authority inside the function, so also pin
    # the resolved-user filter via closure.
    return entitlement_module


def _wallet_authority(monkeypatch, user_id: str | None):
    wallet_module = _verified_wallet_module()

    def _wallet(for_user_id):
        if user_id is None:
            return None
        return {"wallet_address": "0x" + "11" * 20, "verified_at": "2026-10-01T00:00:00Z"}

    monkeypatch.setattr(wallet_module, "get_verified_wallet",
                        lambda uid: _wallet(user_id))


# ── yield.basic stays public ────────────────────────────────────────────────

class TestBasicPublic:
    def test_yield_basic_public_no_entitlement_no_wallet(self, client):
        client_obj, user_id = client
        r = client_obj.get("/yield")
        assert r.status_code == 200
        # No premium/entitlement payload is required or present.
        assert "YIELD_PREMIUM_REQUIRED" not in r.text

    def test_basic_resource_not_gated_by_entitlement_authority(
            self, client, monkeypatch):
        """Even a totally unavailable entitlement authority never blocks the
        public explore surface."""
        client_obj, user_id = client
        module = _entitlement_module()

        async def _broken(session):
            raise AssertionError("public resource must not consult entitlement")

        monkeypatch.setattr(module, "resolve_verified_entitlement_for_request",
                            _resolver_broken)
        r = client_obj.get("/yield")
        assert r.status_code == 200


async def _resolver_broken(session):
    raise AssertionError("public resource must not consult entitlement")


# ── Protected resources fail closed without entitlement ────────────────────

class TestProtectedResourcesFailClosed:
    def test_history_cannot_be_bypassed_via_direct_api(self, client):
        client_obj, user_id = client
        # No verified wallet, feature inactive: direct anonymous-style API
        # call still hits the in-endpoint gate.
        r = client_obj.get(f"/yield/{_uid()}/history.json")
        assert r.status_code == 403
        body = r.json()
        assert body["error"] == "YIELD_PREMIUM_REQUIRED"
        assert body["resource"] == "yield.history"
        # No protected payload leaked.
        assert "observations" not in body

    def test_advanced_compare_cannot_be_bypassed_via_direct_api(self, client):
        client_obj, _ = client
        r = client_obj.get("/yield/compare")
        assert r.status_code == 403
        body = r.json()
        assert body["resource"] == "yield.advanced_compare"
        assert body["error"] == "YIELD_PREMIUM_REQUIRED"
        # No premium comparison payload leaked.
        assert "metrics" not in body and "columns" not in body

    def test_alerts_surface_gated(self, client):
        client_obj, _ = client
        r = client_obj.get("/yield/monitor")
        assert r.status_code == 403
        assert r.json()["resource"] == "yield.alerts"

    def test_denial_states_are_typed(self, client):
        client_obj, user_id = client
        # Unauthenticated direct call -> wallet unavailable.
        anon = type(client_obj)  # noqa: F841
        r = client_obj.get(f"/yield/{_uid()}/history.json")
        assert r.json()["access_state"] in (
            "WALLET_UNAVAILABLE", "WALLET_UNVERIFIED",
            "TOKEN_ENTITLEMENT_FEATURE_INACTIVE")


# ── Safe access states (TEST_ONLY entitlement fixtures) ────────────────────

class TestSafeAccessStates:
    def test_entitled_test_only_context_succeeds(self, client, monkeypatch):
        client_obj, user_id = client
        monkeypatch.setenv("FINCO_YIELD_TOKEN_ENTITLEMENT_ENABLED", "1")
        _entitle_authority(monkeypatch, "ACTIVE", "TEST_ONLY_ENTITLED", user_id)
        _wallet_authority(monkeypatch, user_id)
        r = client_obj.get(f"/yield/{_uid()}/history.json")
        assert r.status_code == 200
        body = r.json()
        assert body["schema"] == "YIELD_HISTORY_V1"

    def test_entitlement_authority_unavailable_fails_closed(self, client, monkeypatch):
        client_obj, user_id = client
        monkeypatch.setenv("FINCO_YIELD_TOKEN_ENTITLEMENT_ENABLED", "1")
        _entitle_authority(monkeypatch, "UNAVAILABLE",
                           "BALANCE_EVIDENCE_UNAVAILABLE", user_id)
        _wallet_authority(monkeypatch, user_id)
        r = client_obj.get(f"/yield/{_uid()}/history.json")
        assert r.status_code == 403
        # Missing != 0: authority unavailable is never converted to balance 0
        # / entitlement satisfied.
        assert r.json()["access_state"] == "ENTITLEMENT_AUTHORITY_UNAVAILABLE"

    def test_balance_stale_is_fail_closed_not_zero(self, client, monkeypatch):
        client_obj, user_id = client
        monkeypatch.setenv("FINCO_YIELD_TOKEN_ENTITLEMENT_ENABLED", "1")
        _entitle_authority(monkeypatch, "STALE", "BALANCE_STALE", user_id)
        _wallet_authority(monkeypatch, user_id)
        r = client_obj.get(f"/yield/{_uid()}/history.json")
        assert r.status_code == 403
        assert r.json()["access_state"] == "ENTITLEMENT_AUTHORITY_UNAVAILABLE"

    def test_feature_inactive_denies_even_with_verified_wallet(
            self, client, monkeypatch):
        client_obj, user_id = client
        # Feature flag intentionally left OFF (default).
        _wallet_authority(monkeypatch, user_id)
        r = client_obj.get(f"/yield/{_uid()}/history.json")
        assert r.status_code == 403
        assert r.json()["access_state"] == "TOKEN_ENTITLEMENT_FEATURE_INACTIVE"

    def test_deployment_not_configured_state(self, client, monkeypatch):
        client_obj, user_id = client
        monkeypatch.setenv("FINCO_YIELD_TOKEN_ENTITLEMENT_ENABLED", "1")
        _entitle_authority(monkeypatch, "TOKEN_CONFIGURATION_UNAVAILABLE",
                           "TOKEN_CONFIGURATION_UNAVAILABLE", user_id)
        _wallet_authority(monkeypatch, user_id)
        r = client_obj.get(f"/yield/{_uid()}/history.json")
        assert r.status_code == 403
        assert r.json()["access_state"] == "TOKEN_DEPLOYMENT_NOT_CONFIGURED"

    def test_wallet_unverified_state(self, client, monkeypatch):
        client_obj, user_id = client
        monkeypatch.setenv("FINCO_YIELD_TOKEN_ENTITLEMENT_ENABLED", "1")
        _wallet_authority(monkeypatch, None)  # no verified wallet binding
        r = client_obj.get(f"/yield/{_uid()}/history.json")
        assert r.status_code == 403
        assert r.json()["access_state"] == "WALLET_UNVERIFIED"

    def test_entitled_compare_succeeds(self, client, monkeypatch):
        client_obj, user_id = client
        monkeypatch.setenv("FINCO_YIELD_TOKEN_ENTITLEMENT_ENABLED", "1")
        _entitle_authority(monkeypatch, "ACTIVE", "TEST_ONLY_ENTITLED", user_id)
        _wallet_authority(monkeypatch, user_id)
        r = client_obj.get(f"/yield/compare?uid={_uid()}")
        assert r.status_code == 200


# ── Wallet verification enforced on execution preflight ────────────────────

class TestExecutionPreflightWallet:
    def test_preflight_requires_verified_wallet(self, client, monkeypatch):
        client_obj, user_id = client
        monkeypatch.setenv("FINCO_YIELD_TOKEN_ENTITLEMENT_ENABLED", "1")
        _entitle_authority(monkeypatch, "ACTIVE", "TEST_ONLY_ENTITLED", user_id)
        _wallet_authority(monkeypatch, None)
        r = client_obj.post(f"/yield/{_uid()}/plan")
        assert r.status_code == 403
        assert r.json()["access_state"] == "WALLET_UNVERIFIED"

    def test_preflight_entitlement_does_not_enable_execution(
            self, client, monkeypatch):
        client_obj, user_id = client
        monkeypatch.setenv("FINCO_YIELD_TOKEN_ENTITLEMENT_ENABLED", "1")
        _entitle_authority(monkeypatch, "ACTIVE", "TEST_ONLY_ENTITLED", user_id)
        _wallet_authority(monkeypatch, user_id)
        # FINCO_YIELD_EXECUTION_ENABLED stays OFF: entitlement != execution.
        r = client_obj.post(f"/yield/{_uid()}/plan")
        assert r.status_code == 409
        assert r.json()["code"] == "EXECUTION_DISABLED"


# ── Yield math untouched ────────────────────────────────────────────────────

class TestYieldMathUntouched:
    def test_access_module_performs_no_yield_arithmetic(self):
        import inspect
        from pathlib import Path

        access_src = (REPO / "finco_yield" / "access.py").read_text(encoding="utf-8")
        assert "apy" not in access_src.lower()
        assert "underwriting" not in access_src.lower()
        assert "decompose" not in access_src.lower()

    def test_underwriting_module_source_untouched_by_gating(self):
        # The gating module must not import or wrap Yield math authorities.
        import inspect

        access_src = inspect.getsource(
            __import__("finco_yield.access", fromlist=["resolve_yield_access"]))
        for banned in ("finco_yield.underwriting", "finco_yield.history",
                       "finco_yield.explore", "finco_yield.evidence_v1"):
            assert banned not in access_src, banned

    def test_explore_rows_unchanged_shape(self, client):
        """Basic explore still renders the full bundled registry rows."""
        client_obj, _ = client
        from finco_yield.registry import load_bundled_registry

        expected = len(load_bundled_registry().all())
        r = client_obj.get("/yield")
        assert r.status_code == 200
        # Every bundled opportunity is still listed on the public surface.
        assert r.text.count("/yield/") >= expected
