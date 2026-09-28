"""B2.2 deterministic access fixtures; no production token deployment is implied."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.protocol.token_config import TokenConfig
from app.verified.entitlement import EntitlementState, resolve_verified_entitlement_for_request
from app.verified.token_entitlement import (
    APPROVED_FINCO_DEPLOYMENTS, ApprovedFincoDeployment, BalanceEvidenceState,
    FincoEntitlementPolicy, TokenBalanceEvidence, evaluate_token_entitlement,
    get_production_policy,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
TOKEN = "0x" + "a" * 40
WALLET = "0x" + "b" * 40
OTHER = "0x" + "c" * 40
POLICY = FincoEntitlementPolicy(56, TOKEN, 18, 10**18, 60, "TEST_ONLY")


def evidence(raw=10**18, **changes):
    value = TokenBalanceEvidence(56, TOKEN, WALLET, 18, raw, NOW,
                                 "TEST_READ_ONLY", BalanceEvidenceState.AVAILABLE)
    return replace(value, **changes)


def decide(balance=None, *, policy=POLICY, wallet=WALLET, at=NOW):
    return evaluate_token_entitlement(subject_id="user-1", wallet_address=wallet,
                                      policy=policy, evidence=balance, as_of=at)


def test_production_has_no_approved_token_or_inferred_deployment(monkeypatch):
    assert APPROVED_FINCO_DEPLOYMENTS == ()
    monkeypatch.setenv("FINCO_TOKEN_RPC_URL", "https://example.invalid")
    monkeypatch.setenv("FINCO_TOKEN_CHAIN_ID", "56")
    monkeypatch.setenv("FINCO_TOKEN_ADDRESS", TOKEN)
    monkeypatch.setenv("FINCO_TOKEN_DECIMALS", "18")
    monkeypatch.setenv("FINCO_ACCESS_MIN_BALANCE", "1")
    monkeypatch.setenv("FINCO_ENTITLEMENT_MAX_AGE_SECONDS", "60")
    assert get_production_policy() is None
    assert decide(evidence(), policy=None).state is EntitlementState.TOKEN_CONFIGURATION_UNAVAILABLE


def test_synthetic_policy_requires_exact_approved_deployment_and_integer_base_units(monkeypatch):
    import app.verified.token_entitlement as module
    deployment = ApprovedFincoDeployment(56, TOKEN, "ERC-20", 18, "TEST_ONLY")
    monkeypatch.setattr(module, "APPROVED_FINCO_DEPLOYMENTS", (deployment,))
    monkeypatch.setattr(module, "get_token_config", lambda: TokenConfig(
        "https://example.invalid", 56, TOKEN, Decimal("1.000000000000000001"), 18))
    monkeypatch.setenv("FINCO_ENTITLEMENT_MAX_AGE_SECONDS", "60")
    policy, _ = get_production_policy()
    assert policy.minimum_balance_raw == 10**18 + 1
    assert decide(evidence(10**18), policy=policy).state is EntitlementState.INACTIVE
    assert decide(evidence(10**18 + 1), policy=policy).state is EntitlementState.ACTIVE
    monkeypatch.setattr(module, "get_token_config", lambda: TokenConfig(
        "https://example.invalid", 1, TOKEN, Decimal("1"), 18))
    assert get_production_policy() is None


@pytest.mark.parametrize("raw,expected", [
    (0, EntitlementState.INACTIVE), (10**18 - 1, EntitlementState.INACTIVE),
    (10**18, EntitlementState.ACTIVE), (10**60, EntitlementState.ACTIVE),
])
def test_exact_raw_threshold_and_large_balance(raw, expected):
    assert decide(evidence(raw)).state is expected


@pytest.mark.parametrize("changes,expected", [
    ({"chain_id": 1}, EntitlementState.UNAVAILABLE),
    ({"token_address": OTHER}, EntitlementState.UNAVAILABLE),
    ({"wallet_address": OTHER}, EntitlementState.UNAVAILABLE),
    ({"token_decimals": 6}, EntitlementState.UNAVAILABLE),
    ({"state": BalanceEvidenceState.UNAVAILABLE}, EntitlementState.UNAVAILABLE),
    ({"state": BalanceEvidenceState.STALE}, EntitlementState.STALE),
    ({"observed_at": None}, EntitlementState.STALE),
])
def test_wrong_or_unavailable_evidence_fails_closed(changes, expected):
    assert decide(evidence(**changes)).state is expected


def test_freshness_and_missing_identity_fail_closed():
    assert decide(evidence(), at=NOW + timedelta(seconds=60)).state is EntitlementState.ACTIVE
    assert decide(evidence(), at=NOW + timedelta(seconds=61)).state is EntitlementState.STALE
    assert decide(evidence(), at=NOW - timedelta(seconds=1)).state is EntitlementState.STALE
    assert decide(None).state is EntitlementState.UNAVAILABLE
    assert decide(evidence(), wallet=None).state is EntitlementState.IDENTITY_UNAVAILABLE
    assert decide(evidence(), wallet="0xinvalid").state is EntitlementState.IDENTITY_UNAVAILABLE


def test_malformed_evidence_cannot_grant_access():
    with pytest.raises(ValueError):
        evidence(-1)
    with pytest.raises(ValueError):
        evidence(True)
    with pytest.raises(ValueError):
        evidence(observed_at=datetime(2026, 1, 1))
    with pytest.raises(ValueError):
        FincoEntitlementPolicy(56, TOKEN, 18, 0, 60, "TEST_ONLY")


def test_request_uses_server_linked_wallet_and_administrative_override(monkeypatch):
    import app.verified.entitlement as entitlement
    import app.verified.token_entitlement as token
    import app.protocol.wallet_auth as wallet_auth

    session = SimpleNamespace(user_id="user-1", session_type="user")
    monkeypatch.setattr(token, "get_production_policy", lambda: (POLICY, object()))
    monkeypatch.setattr(wallet_auth, "get_verified_wallet",
                        lambda subject: {"wallet_address": WALLET} if subject == "user-1" else None)

    class Provider:
        def __init__(self, config):
            pass

        async def balance_of(self, policy, wallet):
            assert wallet == WALLET
            return evidence()

    monkeypatch.setattr(token, "P4ReadOnlyBalanceProvider", Provider)
    assert asyncio.run(resolve_verified_entitlement_for_request(session)).state is EntitlementState.STALE
    # The fixed fixture timestamp is stale in live time; no replay of old evidence.
    monkeypatch.setattr(Provider, "balance_of", lambda self, policy, wallet: _fresh_balance(wallet))
    assert asyncio.run(resolve_verified_entitlement_for_request(session)).state is EntitlementState.ACTIVE
    monkeypatch.setattr(wallet_auth, "get_verified_wallet", lambda subject: None)
    assert asyncio.run(resolve_verified_entitlement_for_request(session)).state is EntitlementState.IDENTITY_UNAVAILABLE
    monkeypatch.setenv("FINCO_VERIFIED_DETAIL_SUBJECT_IDS", "admin-1")
    admin = SimpleNamespace(user_id="admin-1", session_type="admin")
    override = asyncio.run(resolve_verified_entitlement_for_request(admin))
    assert override.state is EntitlementState.ACTIVE
    assert override.source == "ADMIN_OVERRIDE"
    demo = SimpleNamespace(user_id="admin-1", session_type="demo")
    assert asyncio.run(resolve_verified_entitlement_for_request(demo)).state is EntitlementState.IDENTITY_UNAVAILABLE


async def _fresh_balance(wallet):
    return evidence(wallet_address=wallet, observed_at=datetime.now(timezone.utc))


def test_entitlement_never_changes_authoritative_verification():
    from tests.test_b2_1_verified_authority import _bundle, _result
    before = _result(_bundle())
    assert before == ("VERIFIED", None)
    for access in (decide(evidence(0)), decide(evidence()), decide(None)):
        assert access.state in {EntitlementState.ACTIVE, EntitlementState.INACTIVE,
                                EntitlementState.UNAVAILABLE}
        assert _result(_bundle()) == before


def test_dossier_http_gate_does_not_change_public_verification(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import app.auth as auth
    import app.verified.entitlement as entitlement
    import app.verified.router as verified_router

    session = SimpleNamespace(user_id="user-1", session_type="user")
    monkeypatch.setattr(auth, "resolve_request_session", lambda request: session)
    record = {
        "schema": "TEST", "asset_id": "fixture", "display_name": "Fixture",
        "asset_type": "Test", "description": "fixture", "status": "MODEL_ONLY",
        "status_display": "Model only", "verification": {
            "status": "MODEL_ONLY", "reason": "MODEL_MARKET_BINDING_UNAVAILABLE",
        }, "model": {"project_irr": "0.1"},
        "verify": {"certificate_id": "cert-1", "committed_at": "2026-01-01"},
        "certificate": {"certificate_digest_sha256": "a" * 64},
        "identity": {"economic_asset_uid": "test-uid"},
        "market_observation": {"state": "UNAVAILABLE"},
    }
    monkeypatch.setattr(verified_router, "_load_verified_asset",
                        lambda asset_id: {"found": True, "asset_id": asset_id, "record": record})
    app = FastAPI()
    app.include_router(verified_router.router)
    client = TestClient(app)

    async def inactive(_):
        return decide(evidence(0))

    async def active(_):
        return decide(evidence())

    monkeypatch.setattr(entitlement, "resolve_verified_entitlement_for_request", inactive)
    public_before = client.get("/verified/fixture.json")
    assert public_before.status_code == 200
    assert client.get("/verified/fixture/dossier.json").status_code == 403
    monkeypatch.setattr(entitlement, "resolve_verified_entitlement_for_request", active)
    public_after = client.get("/verified/fixture.json")
    dossier = client.get("/verified/fixture/dossier.json")
    assert public_after.status_code == dossier.status_code == 200
    assert dossier.json()["certificate"] == record["certificate"]
    assert dossier.json()["status"] == record["status"]
    assert {k: v for k, v in public_before.json().items() if k != "entitlement"} == {
        k: v for k, v in public_after.json().items() if k != "entitlement"}
    assert "wallet_address" not in public_after.text
    assert "balance_raw" not in public_after.text


def test_b2_2_token_authority_firewall():
    """B2_2_TOKEN_AUTHORITY_FIREWALL: access imports only in presentation."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    frozen = [root / name for name in ("financial_engine", "finco_core", "finco_radar")]
    frozen += [root / "app" / "verify", root / "app" / "verified" / "authority.py",
               root / "app" / "verified" / "composer.py"]
    for path in frozen:
        files = path.rglob("*.py") if path.is_dir() else (path,)
        for source in files:
            text = source.read_text(encoding="utf-8")
            assert "app.verified.token_entitlement" not in text, source
            assert "resolve_verified_entitlement_for_request" not in text, source
