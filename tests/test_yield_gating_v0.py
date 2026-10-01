"""Crypto Utility V0 integration — Yield server/API gating contract.

These tests intentionally inject Agent A ResourceAccessDecision objects at the
B enforcement boundary. Agent A's own suite separately proves deployment,
balance and entitlement evaluation. Together they prove one authority chain.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import os
import tempfile

import pytest


def _uid() -> str:
    from finco_yield.registry import load_bundled_registry
    return load_bundled_registry().all()[0].uid


@pytest.fixture()
def client(monkeypatch):
    os.environ["FINCO_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "yield-gate.db")
    from app.persistence import db
    db.DB_PATH = os.environ["FINCO_DB_PATH"]
    db.init_db()
    monkeypatch.setenv("FINCO_YIELD_ENABLED", "1")
    monkeypatch.delenv("FINCO_YIELD_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("FINCO_TOKEN_GATING_ENABLED", raising=False)
    monkeypatch.delenv("FINCO_ENTITLEMENT_POLICIES_JSON", raising=False)
    monkeypatch.delenv("FINCO_ENTITLEMENT_MAX_AGE_SECONDS", raising=False)

    from fastapi.testclient import TestClient
    import main_web
    from app.auth import COOKIE_NAME, create_session_token

    user_id = "yield-gate-user"
    c = TestClient(main_web.app)
    c.cookies.update({COOKIE_NAME: create_session_token(user_id=user_id, username="yield-gate")})
    return c, user_id


def _decision(resource, verdict, reason, *, wallet=None, observed=None, chain_id=None, token=None):
    from app.protocol.entitlement_evaluator import ResourceAccessDecision
    return ResourceAccessDecision(
        resource_key=resource,
        decision=verdict,
        reason_code=reason,
        access_mode="FINCO_HOLDER",
        wallet_address=wallet,
        chain_id=chain_id,
        token_address=token,
        entitlement_state="ACTIVE" if getattr(verdict, "value", verdict) == "ALLOW" else None,
        observed_balance=observed,
        minimum_balance=None,
        observed_at=datetime.now(timezone.utc) if observed is not None else None,
    )


def _patch_agent_a(monkeypatch, verdict, reason):
    from finco_yield import access as access_mod

    async def fake(resource_key, wallet):
        return _decision(resource_key, verdict, reason, wallet=wallet.address)

    monkeypatch.setattr(access_mod, "evaluate_resource_access", fake)


def test_default_inactive_gate_preserves_history_and_compare(client):
    """Production defaults must not lock existing Yield before $FINCO activation."""
    c, _ = client
    h = c.get(f"/yield/{_uid()}/history.json")
    assert h.status_code == 200
    assert h.json()["schema"] == "YIELD_HISTORY_V1"
    comp = c.get(f"/yield/compare?uid={_uid()}")
    assert comp.status_code == 200
    assert "YIELD_PREMIUM_REQUIRED" not in comp.text


def test_inactive_is_access_allowed_but_not_token_entitled():
    from app.protocol.entitlement_evaluator import Decision
    from finco_yield.access import YieldResource, _from_resource_decision
    upstream = _decision("yield.history", Decision.INACTIVE, "TOKEN_GATING_OFF")
    mapped = _from_resource_decision(YieldResource.HISTORY, upstream)
    assert mapped.access_allowed is True
    assert mapped.token_entitled is False
    assert mapped.entitled is False
    assert mapped.gate_active is False
    assert mapped.state.value == "TOKEN_ENTITLEMENT_FEATURE_INACTIVE"


def test_active_below_threshold_fails_closed_without_payload(client, monkeypatch):
    from app.protocol.entitlement_evaluator import Decision
    c, _ = client
    _patch_agent_a(monkeypatch, Decision.DENY, "BALANCE_BELOW_THRESHOLD")
    r = c.get(f"/yield/{_uid()}/history.json")
    assert r.status_code == 403
    assert r.json()["access_state"] == "ENTITLEMENT_NOT_SATISFIED"
    assert "observations" not in r.json()


@pytest.mark.parametrize("reason", [
    "RPC_UNAVAILABLE", "BALANCE_STALE", "BALANCE_IDENTITY_MISMATCH",
    "BALANCE_EVIDENCE_UNAVAILABLE",
])
def test_active_authority_unavailable_fails_closed(client, monkeypatch, reason):
    from app.protocol.entitlement_evaluator import Decision
    c, _ = client
    _patch_agent_a(monkeypatch, Decision.DENY, reason)
    r = c.get(f"/yield/{_uid()}/history.json")
    assert r.status_code == 403
    assert r.json()["access_state"] == "ENTITLEMENT_AUTHORITY_UNAVAILABLE"
    assert "observations" not in r.json()


@pytest.mark.parametrize("reason", [
    "NO_APPROVED_DEPLOYMENT", "NO_APPROVED_DEPLOYMENT_ON_CHAIN",
    "TOKEN_CONFIGURATION_UNAVAILABLE",
])
def test_active_no_deployment_maps_typed_denial(client, monkeypatch, reason):
    from app.protocol.entitlement_evaluator import Decision
    c, _ = client
    _patch_agent_a(monkeypatch, Decision.DENY, reason)
    r = c.get(f"/yield/{_uid()}/history.json")
    assert r.status_code == 403
    assert r.json()["access_state"] == "TOKEN_DEPLOYMENT_NOT_CONFIGURED"
    assert "observations" not in r.json()


@pytest.mark.parametrize("reason,state", [
    ("WALLET_NOT_CONNECTED", "WALLET_UNAVAILABLE"),
    ("WALLET_NOT_VERIFIED", "WALLET_UNVERIFIED"),
    ("WALLET_IDENTITY_UNAVAILABLE", "WALLET_UNVERIFIED"),
])
def test_wallet_reason_mapping(client, monkeypatch, reason, state):
    from app.protocol.entitlement_evaluator import Decision
    c, _ = client
    _patch_agent_a(monkeypatch, Decision.DENY, reason)
    r = c.get(f"/yield/{_uid()}/history.json")
    assert r.status_code == 403
    assert r.json()["access_state"] == state


def test_unknown_deny_reason_fails_closed(client, monkeypatch):
    from app.protocol.entitlement_evaluator import Decision
    c, _ = client
    _patch_agent_a(monkeypatch, Decision.DENY, "FUTURE_DENY_REASON")
    r = c.get(f"/yield/{_uid()}/history.json")
    assert r.status_code == 403
    assert r.json()["access_state"] == "ENTITLEMENT_AUTHORITY_UNAVAILABLE"


def test_allow_proceeds(client, monkeypatch):
    from app.protocol.entitlement_evaluator import Decision
    c, _ = client
    _patch_agent_a(monkeypatch, Decision.ALLOW, "BALANCE_AT_OR_ABOVE_THRESHOLD")
    r = c.get(f"/yield/{_uid()}/history.json")
    assert r.status_code == 200


def test_admin_override_path_is_not_an_authority(client, monkeypatch):
    """Legacy ACTIVE ADMIN_OVERRIDE can never grant a holder resource."""
    from app.protocol.entitlement_evaluator import Decision
    from app.verified import entitlement as legacy
    c, _ = client
    calls = {"legacy": 0}

    async def legacy_resolver(session):
        calls["legacy"] += 1
        raise AssertionError("legacy admin override must never be consulted")

    monkeypatch.setattr(legacy, "resolve_verified_entitlement_for_request", legacy_resolver)
    _patch_agent_a(monkeypatch, Decision.DENY, "BALANCE_BELOW_THRESHOLD")
    for path in (
        f"/yield/{_uid()}/history.json",
        f"/yield/compare?uid={_uid()}",
        f"/yield/{_uid()}/plan",
    ):
        method = c.post if path.endswith("/plan") else c.get
        r = method(path)
        assert r.status_code == 403
    assert calls["legacy"] == 0


def test_authenticated_subject_id_is_preserved_in_agent_a_wallet(client, monkeypatch):
    from app.protocol.entitlement_evaluator import Decision
    from app.protocol import wallet_auth
    from finco_yield import access as access_mod
    c, user_id = client
    address = "0x" + "11" * 20
    monkeypatch.setattr(wallet_auth, "get_verified_wallet", lambda uid: {
        "wallet_address": address, "verified_at": "2026-10-01T00:00:00Z"})
    seen = {}

    async def fake(resource_key, wallet):
        seen["wallet"] = wallet
        return _decision(resource_key, Decision.ALLOW, "BALANCE_AT_OR_ABOVE_THRESHOLD", wallet=address)

    monkeypatch.setattr(access_mod, "evaluate_resource_access", fake)
    assert c.get(f"/yield/{_uid()}/history.json").status_code == 200
    assert seen["wallet"].address == address
    assert seen["wallet"].verified is True
    assert seen["wallet"].subject_id == user_id


def test_wallet_monitor_is_not_alerts(client, monkeypatch):
    c, _ = client
    from finco_yield import web

    async def no_positions(*args, **kwargs):
        return []

    monkeypatch.setattr(web, "detect_positions", no_positions)
    r = c.get("/yield/monitor", follow_redirects=False)
    assert r.status_code == 200
    assert "YIELD_PREMIUM_REQUIRED" not in r.text


def test_entitled_preflight_still_execution_disabled(client, monkeypatch):
    from app.protocol.entitlement_evaluator import Decision
    c, _ = client
    _patch_agent_a(monkeypatch, Decision.ALLOW, "BALANCE_AT_OR_ABOVE_THRESHOLD")
    r = c.post(f"/yield/{_uid()}/plan")
    assert r.status_code == 409
    assert r.json()["code"] == "EXECUTION_DISABLED"


def test_no_legacy_or_math_authority_in_access_adapter():
    import inspect
    from finco_yield import access
    source = inspect.getsource(access)
    assert "resolve_verified_entitlement_for_request" not in source
    assert "ADMIN_OVERRIDE" in source  # documented only as forbidden
    for banned in ("underwriting", "decompose", "erc4626", "apy"):
        assert banned not in source.lower()
