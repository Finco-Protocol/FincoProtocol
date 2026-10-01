"""Crypto utility V0 (Agent C) — wallet/$FINCO access presentation states.

Proves the typed, DISTINCT presentation contract and the MISSING ≠ ZERO
rule: no state ever fabricates a balance number; unavailable evidence is a
typed state with a reason code; an explicit zero appears only as the
outcome of a successful authoritative observation (driving LOCKED, never
"0 FINCO available").
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest


TEST_TOKEN_ADDRESS = "0x" + "ab" * 20
TEST_WALLET = "0x" + "cd" * 20


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "test.db"))


@pytest.fixture()
def test_policy(monkeypatch):
    """TEST_ONLY fixture policy — never a production value or threshold."""
    from app.verified.token_entitlement import FincoEntitlementPolicy

    policy = FincoEntitlementPolicy(
        chain_id=8453,
        token_address=TEST_TOKEN_ADDRESS,
        token_decimals=18,
        minimum_balance_raw=10 ** 18,      # TEST_ONLY fixture value
        freshness_seconds=300,
        provenance="TEST_ONLY_FIXTURE",
    )
    monkeypatch.setattr(
        "app.verified.token_entitlement.get_production_policy",
        lambda: (policy, object()),
    )
    return policy


def _evidence(balance_raw, *, state="AVAILABLE", observed_delta_s=5):
    from app.verified.token_entitlement import BalanceEvidenceState, TokenBalanceEvidence

    now = datetime.now(timezone.utc)
    return TokenBalanceEvidence(
        chain_id=8453,
        token_address=TEST_TOKEN_ADDRESS,
        wallet_address=TEST_WALLET,
        token_decimals=18,
        balance_raw=balance_raw,
        observed_at=now - timedelta(seconds=observed_delta_s),
        source="TEST_ONLY",
        state=BalanceEvidenceState(state),
        reason=None if state == "AVAILABLE" else state,
    )


def _verified_wallet(user_id="user-1"):
    """Insert a verified-wallet row exactly like the EIP-191 verify path binds."""
    from app.persistence.db import get_connection
    from app.protocol.wallet_auth import _ensure_wallet_table
    conn = get_connection()
    try:
        _ensure_wallet_table(conn)
        with conn:
            conn.execute(
                "INSERT INTO user_wallets (user_id, wallet_address, verified_at) "
                "VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                "wallet_address=excluded.wallet_address, verified_at=excluded.verified_at",
                (user_id, TEST_WALLET, datetime.now(timezone.utc).isoformat()),
            )
    finally:
        conn.close()


# ── Wallet states ─────────────────────────────────────────────────────────────

def test_wallet_disconnected_without_session():
    from app.crypto_access import WALLET_DISCONNECTED, get_crypto_access_snapshot
    snapshot = get_crypto_access_snapshot(None)
    assert snapshot["wallet"]["state"] == WALLET_DISCONNECTED
    assert snapshot["wallet"]["wallet_address"] is None


def test_wallet_unverified_session_without_verified_wallet():
    from app.crypto_access import WALLET_UNVERIFIED, get_crypto_access_snapshot
    snapshot = get_crypto_access_snapshot("user-1")
    assert snapshot["wallet"]["state"] == WALLET_UNVERIFIED


def test_wallet_verified_with_store_row():
    from app.crypto_access import WALLET_VERIFIED, get_crypto_access_snapshot
    _verified_wallet()
    snapshot = get_crypto_access_snapshot("user-1")
    assert snapshot["wallet"]["state"] == WALLET_VERIFIED
    assert snapshot["wallet"]["wallet_address"] == TEST_WALLET
    assert snapshot["wallet"]["verified_at"]


# ── Resource states: distinct, never collapsed ────────────────────────────────

def test_production_default_premium_not_configured_basic_public():
    """Today's production truth: no approved deployment → every premium
    resource is NOT_CONFIGURED while Basic Yield stays PUBLIC."""
    from app.crypto_access import (
        RESOURCE_NOT_CONFIGURED, RESOURCE_NOT_ACTIVATED, RESOURCE_PUBLIC,
        YIELD_ADVANCED_COMPARE, YIELD_ALERTS, YIELD_BASIC, YIELD_EXECUTION_PREFLIGHT,
        YIELD_HISTORY, get_crypto_access_snapshot,
    )
    snapshot = get_crypto_access_snapshot(None)
    resources = snapshot["resources"]
    assert resources[YIELD_BASIC]["state"] == RESOURCE_PUBLIC
    for key in (YIELD_HISTORY, YIELD_ADVANCED_COMPARE, YIELD_ALERTS,
                YIELD_EXECUTION_PREFLIGHT):
        assert resources[key]["state"] in (RESOURCE_NOT_CONFIGURED,
                                           RESOURCE_NOT_ACTIVATED)
    assert resources[YIELD_HISTORY]["state"] == RESOURCE_NOT_CONFIGURED
    assert resources[YIELD_HISTORY]["reason"] == "TOKEN_CONFIGURATION_UNAVAILABLE"
    assert resources[YIELD_ALERTS]["state"] == RESOURCE_NOT_ACTIVATED
    # execution preflight never implies execution is enabled
    assert "execution itself is not enabled" in resources[YIELD_EXECUTION_PREFLIGHT]["note"]


def test_registry_has_exact_canonical_resource_keys():
    from app.crypto_access import (
        YIELD_ADVANCED_COMPARE, YIELD_ALERTS, YIELD_BASIC, YIELD_EXECUTION_PREFLIGHT,
        YIELD_HISTORY, YIELD_RESOURCE_REGISTRY,
    )
    assert set(YIELD_RESOURCE_REGISTRY) == {
        YIELD_BASIC, YIELD_HISTORY, YIELD_ADVANCED_COMPARE, YIELD_ALERTS,
        YIELD_EXECUTION_PREFLIGHT,
    }


def test_locked_when_verified_wallet_below_threshold(test_policy):
    from app.crypto_access import (
        RESOURCE_LOCKED, YIELD_HISTORY, get_crypto_access_snapshot,
    )
    _verified_wallet()
    snapshot = get_crypto_access_snapshot(
        "user-1", evidence=_evidence(1))  # successful observation, below fixture threshold
    row = snapshot["resources"][YIELD_HISTORY]
    assert row["state"] == RESOURCE_LOCKED
    assert row["reason"] == "BALANCE_BELOW_THRESHOLD"
    assert snapshot["token"]["state"] == "INACTIVE"


def test_unlocked_under_test_only_fixture(test_policy):
    from app.crypto_access import RESOURCE_UNLOCKED, YIELD_HISTORY, get_crypto_access_snapshot
    _verified_wallet()
    snapshot = get_crypto_access_snapshot(
        "user-1", evidence=_evidence(10 ** 18))  # at fixture threshold
    row = snapshot["resources"][YIELD_HISTORY]
    assert row["state"] == RESOURCE_UNLOCKED
    assert row["reason"] == "BALANCE_AT_OR_ABOVE_THRESHOLD"
    assert snapshot["token"]["state"] == "ACTIVE"


def test_unavailable_when_evidence_not_obtained(test_policy):
    """Configured + verified wallet but NO authoritative observation →
    typed UNAVAILABLE — never a fabricated zero."""
    from app.crypto_access import RESOURCE_UNAVAILABLE, YIELD_HISTORY, get_crypto_access_snapshot
    _verified_wallet()
    snapshot = get_crypto_access_snapshot("user-1", evidence=None)
    row = snapshot["resources"][YIELD_HISTORY]
    assert row["state"] == RESOURCE_UNAVAILABLE
    assert row["reason"] == "BALANCE_EVIDENCE_UNAVAILABLE"
    assert snapshot["token"]["state"] == "UNAVAILABLE"


def test_unavailable_when_evidence_rpc_unavailable_not_zero(test_policy):
    from app.crypto_access import RESOURCE_UNAVAILABLE, YIELD_HISTORY, get_crypto_access_snapshot
    _verified_wallet()
    snapshot = get_crypto_access_snapshot(
        "user-1", evidence=_evidence(None, state="UNAVAILABLE"))
    row = snapshot["resources"][YIELD_HISTORY]
    assert row["state"] == RESOURCE_UNAVAILABLE
    assert row["reason"] == "UNAVAILABLE"


def test_explicit_zero_observation_is_real_state_not_missing(test_policy):
    """A successful observation explicitly returning zero drives LOCKED
    (below threshold) — it is real observed data, never rendered as missing,
    and never rendered as an available balance."""
    from app.crypto_access import RESOURCE_LOCKED, YIELD_HISTORY, get_crypto_access_snapshot
    _verified_wallet()
    snapshot = get_crypto_access_snapshot("user-1", evidence=_evidence(0))
    row = snapshot["resources"][YIELD_HISTORY]
    assert row["state"] == RESOURCE_LOCKED
    assert row["reason"] == "BALANCE_BELOW_THRESHOLD"


def test_stale_evidence_is_unavailable_not_current(test_policy):
    from app.crypto_access import RESOURCE_UNAVAILABLE, YIELD_HISTORY, get_crypto_access_snapshot
    _verified_wallet()
    snapshot = get_crypto_access_snapshot(
        "user-1", evidence=_evidence(10 ** 18, observed_delta_s=10_000))
    row = snapshot["resources"][YIELD_HISTORY]
    assert row["state"] == RESOURCE_UNAVAILABLE
    assert row["reason"] == "BALANCE_STALE"


# ── MISSING ≠ ZERO at the output contract level ──────────────────────────────

@pytest.mark.parametrize("user_id,evidence", [
    (None, None),
    ("user-1", None),
])
def test_snapshot_never_contains_balance_numbers(user_id, evidence, test_policy):
    """The presentation payload contains NO balance/amount numbers in any
    state — unavailable/locked states are typed, not numeric."""
    from app.crypto_access import get_crypto_access_snapshot
    if user_id == "user-1":
        _verified_wallet()
    snapshot = get_crypto_access_snapshot(user_id, evidence=evidence)
    payload = json.dumps(snapshot)
    # no balance VALUE anywhere: the only "balance" occurrences are typed
    # reason codes, never a numeric field or amount
    assert "normalized_balance" not in payload
    assert not any("balance" in key.lower() for key in snapshot["token"])
    assert snapshot["token"].get("balance") is None
    assert "0 FINCO" not in payload
    assert "FINCO to unlock" not in payload
    assert "Hold" not in payload


def test_no_threshold_copy_in_any_state(test_policy):
    from app.crypto_access import get_crypto_access_snapshot
    _verified_wallet()
    for evidence in (None, _evidence(1), _evidence(10 ** 18)):
        payload = json.dumps(
            get_crypto_access_snapshot("user-1", evidence=evidence))
        # TEST_ONLY fixture values must never leak into presentation output
        assert "1000000000000000000" not in payload
        assert "to unlock" not in payload.lower()


# ── Ownership ≠ entitlement invariants ────────────────────────────────────────

def test_verified_wallet_alone_does_not_unlock(test_policy):
    """Ownership verification is necessary but never sufficient: a verified
    wallet without an authoritative ACTIVE entitlement stays locked."""
    from app.crypto_access import RESOURCE_UNAVAILABLE, YIELD_HISTORY, get_crypto_access_snapshot
    _verified_wallet()
    snapshot = get_crypto_access_snapshot("user-1")  # no evidence at all
    assert snapshot["wallet"]["state"] == "VERIFIED"
    # verified ownership alone NEVER unlocks: honest typed state instead
    assert snapshot["resources"][YIELD_HISTORY]["state"] == RESOURCE_UNAVAILABLE
    assert snapshot["resources"][YIELD_HISTORY]["reason"] == "BALANCE_EVIDENCE_UNAVAILABLE"


def test_snapshot_schema_version_present():
    from app.crypto_access import get_crypto_access_snapshot
    snapshot = get_crypto_access_snapshot(None)
    assert snapshot["schema_version"] == "FINCO_CRYPTO_ACCESS_PRESENTATION_V0"
