"""Crypto utility V0 (Agent C) — wallet/$FINCO access PRESENTATION mapping.

Agent C is a thin, deterministic presentation adapter over AUTHORITATIVE
Agent A resource decisions (``ResourceAccessDecision``-shaped objects —
duck-typed here).  These tests prove the mapping and its invariants:

  - presentation maps authority; it never computes authority (no
    policy/entitlement/evaluation primitives are imported or called);
  - every Agent A decision/reason maps to exactly one typed state
    (PUBLIC / UNLOCKED / LOCKED / UNAVAILABLE / NOT_CONFIGURED /
    NOT_ACTIVATED) and they are never collapsed;
  - MISSING ≠ ZERO: a balance number appears ONLY when the authority
    actually observed one (explicit zero included); unavailable/stale/
    missing/deployment-less states carry no number and no threshold;
  - absent decisions are honest typed UNAVAILABLE — access is never guessed.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

TEST_TOKEN_ADDRESS = "0x" + "ab" * 20
TEST_WALLET = "0x" + "cd" * 20


def _decision(decision="DENY", reason="BALANCE_BELOW_THRESHOLD", *,
              observed_balance=None, chain_id=None, token_address=None):
    """Agent A ResourceAccessDecision stand-in (duck-typed fields only)."""
    return SimpleNamespace(
        decision=decision, reason_code=reason,
        observed_balance=observed_balance, chain_id=chain_id,
        token_address=token_address,
    )


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "test.db"))
    # get_connection reads the frozen module constant — patch both
    import app.persistence.db as _db
    monkeypatch.setattr(_db, "DB_PATH", str(tmp_path / "test.db"))


@pytest.fixture()
def presentation_module():
    """The presentation module must not import forbidden authority.

    Prove-the-negative: policy/entitlement/evaluation primitives appear
    nowhere in the presentation adapter — it only maps decisions.
    """
    import inspect
    from app import crypto_access
    source = inspect.getsource(crypto_access)
    for banned in ("get_production_policy", "evaluate_token_entitlement",
                   "EntitlementState", "TokenBalanceEvidence",
                   "FincoEntitlementPolicy", "TokenConfig"):
        assert banned not in source, banned
    return crypto_access


# ── Mapping: Agent A decision/reason → presentation state ─────────────────────

def test_allow_public_resource_maps_to_public(presentation_module):
    from app.crypto_access import RESOURCE_PUBLIC, YIELD_BASIC
    view = presentation_module.present_resource(
        presentation_module.RESOURCE_DISPLAY[YIELD_BASIC],
        _decision("ALLOW", "PUBLIC_RESOURCE"))
    assert view["state"] == RESOURCE_PUBLIC
    assert view["reason"] == "PUBLIC_RESOURCE"


def test_allow_at_threshold_maps_to_unlocked(presentation_module):
    from app.crypto_access import RESOURCE_UNLOCKED, YIELD_HISTORY
    view = presentation_module.present_resource(
        presentation_module.RESOURCE_DISPLAY[YIELD_HISTORY],
        _decision("ALLOW", "BALANCE_AT_OR_ABOVE_THRESHOLD"))
    assert view["state"] == RESOURCE_UNLOCKED
    assert view["reason"] == "BALANCE_AT_OR_ABOVE_THRESHOLD"


def test_deny_below_threshold_maps_to_locked(presentation_module):
    from app.crypto_access import RESOURCE_LOCKED, YIELD_HISTORY
    view = presentation_module.present_resource(
        presentation_module.RESOURCE_DISPLAY[YIELD_HISTORY],
        _decision("DENY", "BALANCE_BELOW_THRESHOLD"))
    assert view["state"] == RESOURCE_LOCKED
    assert view["reason"] == "BALANCE_BELOW_THRESHOLD"


@pytest.mark.parametrize("reason", [
    "WALLET_NOT_CONNECTED", "WALLET_NOT_VERIFIED", "WALLET_IDENTITY_UNAVAILABLE",
])
def test_deny_wallet_reasons_map_to_locked(presentation_module, reason):
    from app.crypto_access import RESOURCE_LOCKED, YIELD_HISTORY
    view = presentation_module.present_resource(
        presentation_module.RESOURCE_DISPLAY[YIELD_HISTORY],
        _decision("DENY", reason))
    assert view["state"] == RESOURCE_LOCKED
    assert view["reason"] == reason  # exact safe typed reason retained


@pytest.mark.parametrize("reason", [
    "RPC_UNAVAILABLE", "BALANCE_EVIDENCE_UNAVAILABLE",
    "BALANCE_STALE", "BALANCE_IDENTITY_MISMATCH",
])
def test_deny_authority_unavailable_maps_to_unavailable(
        presentation_module, reason):
    from app.crypto_access import RESOURCE_UNAVAILABLE, YIELD_HISTORY
    view = presentation_module.present_resource(
        presentation_module.RESOURCE_DISPLAY[YIELD_HISTORY],
        _decision("DENY", reason))
    assert view["state"] == RESOURCE_UNAVAILABLE
    assert view["reason"] == reason


@pytest.mark.parametrize("reason", [
    "NO_APPROVED_DEPLOYMENT", "NO_APPROVED_DEPLOYMENT_ON_CHAIN",
    "TOKEN_CONFIGURATION_UNAVAILABLE",
])
def test_deny_no_deployment_maps_to_not_configured(presentation_module, reason):
    from app.crypto_access import RESOURCE_NOT_CONFIGURED, YIELD_HISTORY
    view = presentation_module.present_resource(
        presentation_module.RESOURCE_DISPLAY[YIELD_HISTORY],
        _decision("DENY", reason))
    assert view["state"] == RESOURCE_NOT_CONFIGURED
    assert view["reason"] == reason


@pytest.mark.parametrize("reason", ["TOKEN_GATING_OFF", "POLICY_DISABLED"])
def test_inactive_gating_maps_to_not_activated_never_locked(
        presentation_module, reason):
    """No active token gate denied the user — inactive gating is presented
    as NOT_ACTIVATED, never as LOCKED."""
    from app.crypto_access import RESOURCE_NOT_ACTIVATED, YIELD_HISTORY
    view = presentation_module.present_resource(
        presentation_module.RESOURCE_DISPLAY[YIELD_HISTORY],
        _decision("INACTIVE", reason))
    assert view["state"] == RESOURCE_NOT_ACTIVATED
    assert view["reason"] == reason


def test_yield_alerts_follows_canonical_decision_like_other_holders(
        presentation_module):
    """``yield.alerts`` has NO presentation-only delivery override: it is
    mapped from its canonical decision exactly like other holder
    resources.  Alerts BACKEND availability is a separate, gateway-owned
    concept rendered in the Alerts panel."""
    from app.crypto_access import (
        RESOURCE_LOCKED, RESOURCE_NOT_ACTIVATED, RESOURCE_NOT_CONFIGURED,
        RESOURCE_UNAVAILABLE, RESOURCE_UNLOCKED, YIELD_ALERTS,
    )
    present = presentation_module.present_resource
    meta = presentation_module.RESOURCE_DISPLAY[YIELD_ALERTS]

    # canonical INACTIVE (gating off) → NOT_ACTIVATED
    view = present(meta, _decision("INACTIVE", "TOKEN_GATING_OFF"))
    assert view["state"] == RESOURCE_NOT_ACTIVATED
    assert view["reason"] == "TOKEN_GATING_OFF"
    # canonical ALLOW → UNLOCKED
    view = present(meta, _decision("ALLOW", "BALANCE_AT_OR_ABOVE_THRESHOLD"))
    assert view["state"] == RESOURCE_UNLOCKED
    assert view["reason"] == "BALANCE_AT_OR_ABOVE_THRESHOLD"
    # canonical DENY below threshold → LOCKED
    view = present(meta, _decision("DENY", "BALANCE_BELOW_THRESHOLD"))
    assert view["state"] == RESOURCE_LOCKED
    # no deployment → NOT_CONFIGURED
    view = present(meta, _decision("DENY", "NO_APPROVED_DEPLOYMENT"))
    assert view["state"] == RESOURCE_NOT_CONFIGURED
    # authority unavailable → UNAVAILABLE
    view = present(meta, _decision("DENY", "RPC_UNAVAILABLE"))
    assert view["state"] == RESOURCE_UNAVAILABLE
    # missing decision → UNAVAILABLE (never guessed)
    view = present(meta, None)
    assert view["state"] == RESOURCE_UNAVAILABLE
    assert view["reason"] == "ACCESS_DECISION_UNAVAILABLE"
    # neutral access-specific metadata: no delivery claims either way
    assert "not shipped" not in view["note"].lower()
    assert "delivery" not in view["note"].lower()
    assert "shown separately" in view["note"]


def test_no_resource_carries_a_delivery_override(presentation_module):
    """The presentation-only activated override is gone entirely: no
    display metadata can turn a canonical ALLOW into NOT_ACTIVATED."""
    import json
    from app.crypto_access import RESOURCE_DISPLAY
    assert not hasattr(list(RESOURCE_DISPLAY.values())[0], "activated")
    for meta in RESOURCE_DISPLAY.values():
        payload = json.dumps(meta.__dict__)
        assert "ALERT_DELIVERY_NOT_SHIPPED" not in payload


def test_unknown_deny_reason_fails_closed_to_unavailable(presentation_module):
    from app.crypto_access import RESOURCE_UNAVAILABLE, YIELD_HISTORY
    view = presentation_module.present_resource(
        presentation_module.RESOURCE_DISPLAY[YIELD_HISTORY],
        _decision("DENY", "SOME_FUTURE_REASON"))
    assert view["state"] == RESOURCE_UNAVAILABLE


# ── Snapshot assembly: absent decisions are honest UNAVAILABLE ────────────────

def test_missing_decisions_present_unavailable_never_guessed(
        presentation_module):
    from app.crypto_access import (
        RESOURCE_NOT_ACTIVATED, RESOURCE_UNAVAILABLE, YIELD_ADVANCED_COMPARE,
        YIELD_ALERTS, YIELD_BASIC, YIELD_EXECUTION_PREFLIGHT, YIELD_HISTORY,
        WALLET_DISCONNECTED, build_crypto_access_snapshot,
    )
    snapshot = build_crypto_access_snapshot(WALLET_DISCONNECTED)
    assert snapshot["wallet"]["state"] == WALLET_DISCONNECTED
    assert snapshot["schema_version"] == "FINCO_CRYPTO_ACCESS_PRESENTATION_V0"
    assert snapshot["resources"][YIELD_BASIC]["state"] == RESOURCE_UNAVAILABLE
    assert snapshot["resources"][YIELD_BASIC]["reason"] == "ACCESS_DECISION_UNAVAILABLE"
    assert snapshot["resources"][YIELD_HISTORY]["state"] == RESOURCE_UNAVAILABLE
    assert snapshot["resources"][YIELD_ADVANCED_COMPARE]["state"] == RESOURCE_UNAVAILABLE
    assert snapshot["resources"][YIELD_EXECUTION_PREFLIGHT]["state"] == RESOURCE_UNAVAILABLE
    # alerts follows canonical authority like every other holder resource
    assert snapshot["resources"][YIELD_ALERTS]["state"] == RESOURCE_UNAVAILABLE
    assert snapshot["resources"][YIELD_ALERTS]["reason"] == "ACCESS_DECISION_UNAVAILABLE"


def test_snapshot_maps_full_authoritative_bundle(presentation_module):
    from app.crypto_access import (
        RESOURCE_NOT_ACTIVATED, RESOURCE_PUBLIC, RESOURCE_UNLOCKED,
        YIELD_ADVANCED_COMPARE, YIELD_ALERTS, YIELD_BASIC, YIELD_HISTORY,
        WALLET_VERIFIED, build_crypto_access_snapshot,
    )
    decisions = {
        YIELD_BASIC: _decision("ALLOW", "PUBLIC_RESOURCE"),
        YIELD_HISTORY: _decision("ALLOW", "BALANCE_AT_OR_ABOVE_THRESHOLD"),
        YIELD_ADVANCED_COMPARE: _decision("DENY", "BALANCE_BELOW_THRESHOLD"),
        YIELD_ALERTS: _decision("INACTIVE", "TOKEN_GATING_OFF"),
    }
    snapshot = build_crypto_access_snapshot(WALLET_VERIFIED,
                                            resource_decisions=decisions)
    assert snapshot["resources"][YIELD_BASIC]["state"] == RESOURCE_PUBLIC
    assert snapshot["resources"][YIELD_HISTORY]["state"] == RESOURCE_UNLOCKED
    assert snapshot["resources"][YIELD_ADVANCED_COMPARE]["state"] == "LOCKED"
    assert snapshot["resources"][YIELD_ALERTS]["state"] == RESOURCE_NOT_ACTIVATED


# ── Balance presentation: MISSING ≠ ZERO ──────────────────────────────────────

def test_no_observed_balance_means_no_number(presentation_module):
    from app.crypto_access import YIELD_HISTORY
    for decision in (_decision("DENY", "BALANCE_BELOW_THRESHOLD"),
                     _decision("DENY", "BALANCE_EVIDENCE_UNAVAILABLE"),
                     _decision("DENY", "BALANCE_STALE"),
                     _decision("ALLOW", "PUBLIC_RESOURCE"),
                     None):
        view = presentation_module.present_resource(
            presentation_module.RESOURCE_DISPLAY[YIELD_HISTORY], decision)
        assert view["balance"] is None  # no number, ever, without observation


def test_explicit_observed_zero_is_shown_exactly_as_zero(presentation_module):
    """Authoritative observation of zero → the number 0 may be displayed —
    with explicit chain/deployment identity."""
    from app.crypto_access import YIELD_HISTORY
    view = presentation_module.present_resource(
        presentation_module.RESOURCE_DISPLAY[YIELD_HISTORY],
        _decision("DENY", "BALANCE_BELOW_THRESHOLD", observed_balance=Decimal(0),
                  chain_id=8453, token_address=TEST_TOKEN_ADDRESS))
    assert view["balance"] is not None
    assert view["balance"]["observed_balance"] == "0"
    assert view["balance"]["chain_id"] == 8453
    assert view["balance"]["token_address"] == TEST_TOKEN_ADDRESS


def test_positive_observed_balance_shown_with_identity(presentation_module):
    from app.crypto_access import YIELD_HISTORY
    view = presentation_module.present_resource(
        presentation_module.RESOURCE_DISPLAY[YIELD_HISTORY],
        _decision("ALLOW", "BALANCE_AT_OR_ABOVE_THRESHOLD",
                  observed_balance=Decimal("12.5"), chain_id=8453,
                  token_address=TEST_TOKEN_ADDRESS))
    assert view["balance"]["observed_balance"] == "12.5"


def test_balance_without_explicit_identity_not_shown(presentation_module):
    """A number without chain/deployment identity is never displayed bare."""
    from app.crypto_access import YIELD_HISTORY
    view = presentation_module.present_resource(
        presentation_module.RESOURCE_DISPLAY[YIELD_HISTORY],
        _decision("ALLOW", "BALANCE_AT_OR_ABOVE_THRESHOLD",
                  observed_balance=Decimal("5")))
    assert view["balance"] is None


def test_threshold_never_leaks_into_presentation(presentation_module):
    """minimum_balance / thresholds / tokenomics never appear in any view."""
    from app.crypto_access import YIELD_HISTORY
    decision = SimpleNamespace(
        decision="DENY", reason_code="BALANCE_BELOW_THRESHOLD",
        observed_balance=Decimal("1"), minimum_balance=Decimal("1000"),
        chain_id=8453, token_address=TEST_TOKEN_ADDRESS)
    import json
    payload = json.dumps(presentation_module.present_resource(
        presentation_module.RESOURCE_DISPLAY[YIELD_HISTORY], decision))
    assert "minimum" not in payload.lower()
    assert "1000" not in payload  # the fixture threshold value never leaks
    # the observed number IS the authority's, never a threshold echo
    assert '"observed_balance": "1"' in payload
    assert "to unlock" not in payload.lower()
    assert "Hold" not in payload


# ── Wallet presentation state (existing session/wallet authority) ─────────────

def test_wallet_states_from_existing_authority():
    from app.crypto_access import (
        WALLET_DISCONNECTED, WALLET_UNVERIFIED, get_wallet_state,
    )
    assert get_wallet_state(None)[0] == WALLET_DISCONNECTED
    assert get_wallet_state("user-1")[0] == WALLET_UNVERIFIED


def test_wallet_verified_state_from_existing_store():
    from app.crypto_access import WALLET_VERIFIED, get_wallet_state
    from app.persistence.db import get_connection
    from app.protocol.wallet_auth import _ensure_wallet_table
    conn = get_connection()
    try:
        _ensure_wallet_table(conn)
        with conn:
            conn.execute(
                "INSERT INTO user_wallets (user_id, wallet_address, verified_at) "
                "VALUES ('user-1', ?, ?)",
                (TEST_WALLET, "2026-01-01T00:00:00+00:00"))
    finally:
        conn.close()
    state, record = get_wallet_state("user-1")
    assert state == WALLET_VERIFIED
    assert record["wallet_address"] == TEST_WALLET
