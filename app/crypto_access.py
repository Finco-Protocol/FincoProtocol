"""FINCO crypto utility V0 — wallet / $FINCO access PRESENTATION authority.

This module derives typed, human-facing states from AUTHORITATIVE backend
inputs only.  It never decides entitlement from a frontend balance, never
reads an RPC itself, and never invents token economics:

    backend entitlement state  →  presentation state

Consumed authorities (read-only):
  - ``app.protocol.token_config.get_token_config``  — ``None`` means the
    production token deployment is NOT CONFIGURED (never guessed);
  - ``app.protocol.wallet_auth.get_verified_wallet`` — the existing
    wallet-verification store (ownership ≠ entitlement);
  - ``app.verified.token_entitlement.get_production_policy`` /
    ``evaluate_token_entitlement`` — the B2.2 typed entitlement evaluator
    (ACTIVE / INACTIVE / STALE / UNAVAILABLE / IDENTITY_UNAVAILABLE /
    TOKEN_CONFIGURATION_UNAVAILABLE).

Presentation states are deliberately coarse and DISTINCT — they are never
collapsed into one another:

    wallet : DISCONNECTED | UNVERIFIED | VERIFIED
    resource: PUBLIC | NOT_CONFIGURED | LOCKED | UNAVAILABLE | UNLOCKED
              | NOT_ACTIVATED

  NOT_CONFIGURED  the production $FINCO deployment/entitlement policy does
                  not exist yet (normal state today) — nothing is gated;
  LOCKED          gating applies and the current wallet/entitlement state
                  does not grant access (no amounts are ever shown);
  UNAVAILABLE     gating applies but an authoritative input (e.g. balance
                  observation) could not be obtained — missing ≠ zero;
  UNLOCKED        the authoritative evaluator returned ACTIVE (reachable
                  only with a real configured deployment; tests use
                  TEST_ONLY fixtures);
  PUBLIC          the resource is public (Basic Yield);
  NOT_ACTIVATED   the capability is planned but its delivery is not
                  shipped (Yield alerts) — never implied as gated-and-working.

MISSING ≠ ZERO: a numeric balance/amount is only ever surfaced when an
authoritative observation explicitly succeeded; unavailable observations
stay typed states with reason codes.  No thresholds, quantities, prices,
or tokenomics appear anywhere in this module or its output.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

# ── Canonical resource registry ──────────────────────────────────────────────
# These strings are permanent public resource identifiers.  Do NOT rename
# them.  (Mirrors app.protocol.utility_registry's permanent-string rule.)

YIELD_BASIC = "yield.basic"
YIELD_HISTORY = "yield.history"
YIELD_ADVANCED_COMPARE = "yield.advanced_compare"
YIELD_ALERTS = "yield.alerts"
YIELD_EXECUTION_PREFLIGHT = "yield.execution_preflight"


@dataclass(frozen=True)
class CryptoResource:
    """One canonical gated/public capability in the crypto utility surface."""

    key: str
    display_name: str
    description: str
    public: bool                    # True → always PUBLIC while the surface exists
    activated: bool = True          # False → NOT_ACTIVATED (delivery not shipped)
    note: str | None = None         # invariant caption, shown as-is


YIELD_RESOURCE_REGISTRY: dict[str, CryptoResource] = {
    YIELD_BASIC: CryptoResource(
        key=YIELD_BASIC,
        display_name="Basic Yield",
        description="Public read-only Yield opportunity table.",
        public=True,
    ),
    YIELD_HISTORY: CryptoResource(
        key=YIELD_HISTORY,
        display_name="Yield History",
        description="Historical Yield evidence ranges for tracked opportunities.",
        public=False,
    ),
    YIELD_ADVANCED_COMPARE: CryptoResource(
        key=YIELD_ADVANCED_COMPARE,
        display_name="Advanced Compare",
        description="Side-by-side comparison of tracked Yield opportunities.",
        public=False,
    ),
    YIELD_ALERTS: CryptoResource(
        key=YIELD_ALERTS,
        display_name="Alerts",
        description="Saved-opportunity alerting. Foundation (watchlist) is "
                    "shipped; alert delivery is not.",
        public=False,
        activated=False,
        note="Watchlist is available; alert delivery is not shipped yet.",
    ),
    YIELD_EXECUTION_PREFLIGHT: CryptoResource(
        key=YIELD_EXECUTION_PREFLIGHT,
        display_name="Execution Preflight",
        description="Entitlement status surface for future preflight planning.",
        public=False,
        note="Entitlement status only — execution itself is not enabled.",
    ),
}


# ── Typed presentation states ────────────────────────────────────────────────

WALLET_DISCONNECTED = "DISCONNECTED"
WALLET_UNVERIFIED = "UNVERIFIED"
WALLET_VERIFIED = "VERIFIED"

RESOURCE_PUBLIC = "PUBLIC"
RESOURCE_NOT_CONFIGURED = "NOT_CONFIGURED"
RESOURCE_LOCKED = "LOCKED"
RESOURCE_UNAVAILABLE = "UNAVAILABLE"
RESOURCE_UNLOCKED = "UNLOCKED"
RESOURCE_NOT_ACTIVATED = "NOT_ACTIVATED"

# Reason codes (stable uppercase tokens, safe for UI and logs).
REASON_NO_SESSION = "WALLET_NOT_CONNECTED"
REASON_WALLET_UNVERIFIED = "WALLET_OWNERSHIP_UNVERIFIED"
REASON_TOKEN_NOT_CONFIGURED = "TOKEN_CONFIGURATION_UNAVAILABLE"
REASON_BALANCE_UNAVAILABLE = "BALANCE_EVIDENCE_UNAVAILABLE"
REASON_BALANCE_BELOW_THRESHOLD = "BALANCE_BELOW_THRESHOLD"
REASON_BALANCE_AT_THRESHOLD = "BALANCE_AT_OR_ABOVE_THRESHOLD"
REASON_BALANCE_STALE = "BALANCE_STALE"
REASON_BALANCE_IDENTITY_UNAVAILABLE = "WALLET_IDENTITY_UNAVAILABLE"
REASON_ALERTS_NOT_SHIPPED = "ALERT_DELIVERY_NOT_SHIPPED"


def get_wallet_state(user_id: str | None) -> tuple[str, Optional[dict]]:
    """Authoritative wallet presentation state from the existing store.

    DISCONNECTED — no authenticated session (no user to verify a wallet);
    UNVERIFIED   — session exists but no verified wallet is bound;
    VERIFIED     — the existing EIP-191 verification store has a row.
    """
    if not user_id:
        return WALLET_DISCONNECTED, None
    from app.protocol.wallet_auth import get_verified_wallet
    record = get_verified_wallet(user_id)
    if record is None:
        return WALLET_UNVERIFIED, None
    return WALLET_VERIFIED, record


def _entitlement_state_for_wallet(
    *, subject_id: str, wallet_address: str, as_of: datetime,
    evidence: Any = None,
):
    """Authoritative B2.2 entitlement evaluation for presentation only.

    ``evidence`` is an ALREADY-OBTAINED authoritative ``TokenBalanceEvidence``
    (or None — never triggers an RPC here).  Returns the typed
    (EntitlementState, reason) pair from the canonical evaluator.
    """
    from app.verified.token_entitlement import (
        evaluate_token_entitlement, get_production_policy,
    )
    policy_bundle = get_production_policy()
    policy = policy_bundle[0] if policy_bundle is not None else None
    entitlement = evaluate_token_entitlement(
        subject_id=subject_id,
        wallet_address=wallet_address,
        policy=policy,
        evidence=evidence,
        as_of=as_of,
    )
    return entitlement.state, entitlement.reason


def resource_presentation_state(
    resource: CryptoResource, *,
    wallet_state: str,
    entitlement_state: Any = None,
    entitlement_reason: str | None = None,
) -> tuple[str, str | None]:
    """Map authoritative inputs to ONE typed presentation state.

    Precedence:
      public resource                       → PUBLIC
      not yet activated                     → NOT_ACTIVATED
      production policy unconfigured        → NOT_CONFIGURED
      wallet disconnected / unverified      → LOCKED (typed reason)
      entitlement ACTIVE                    → UNLOCKED
      entitlement INACTIVE                  → LOCKED (below threshold;
                                                never shows any amount)
      entitlement STALE/UNAVAILABLE/*       → UNAVAILABLE
    """
    if resource.public:
        return RESOURCE_PUBLIC, None
    if not resource.activated:
        return RESOURCE_NOT_ACTIVATED, REASON_ALERTS_NOT_SHIPPED

    from app.verified.entitlement import EntitlementState
    from app.verified.token_entitlement import get_production_policy

    if get_production_policy() is None:
        return RESOURCE_NOT_CONFIGURED, REASON_TOKEN_NOT_CONFIGURED
    if wallet_state == WALLET_DISCONNECTED:
        return RESOURCE_LOCKED, REASON_NO_SESSION
    if wallet_state == WALLET_UNVERIFIED:
        return RESOURCE_LOCKED, REASON_WALLET_UNVERIFIED

    if entitlement_state is None:
        return RESOURCE_UNAVAILABLE, REASON_BALANCE_UNAVAILABLE
    state = EntitlementState(entitlement_state)
    if state is EntitlementState.ACTIVE:
        return RESOURCE_UNLOCKED, entitlement_reason or REASON_BALANCE_AT_THRESHOLD
    if state is EntitlementState.INACTIVE:
        return RESOURCE_LOCKED, entitlement_reason or REASON_BALANCE_BELOW_THRESHOLD
    if state is EntitlementState.STALE:
        return RESOURCE_UNAVAILABLE, entitlement_reason or REASON_BALANCE_STALE
    if state is EntitlementState.IDENTITY_UNAVAILABLE:
        return RESOURCE_LOCKED, entitlement_reason or REASON_BALANCE_IDENTITY_UNAVAILABLE
    if state is EntitlementState.TOKEN_CONFIGURATION_UNAVAILABLE:
        return RESOURCE_NOT_CONFIGURED, entitlement_reason or REASON_TOKEN_NOT_CONFIGURED
    return RESOURCE_UNAVAILABLE, entitlement_reason or REASON_BALANCE_UNAVAILABLE


def get_crypto_access_snapshot(
    user_id: str | None, *,
    evidence: Any = None,
    as_of: datetime | None = None,
) -> dict:
    """One authoritative presentation bundle for the crypto utility surface.

    Consumes ONLY existing authorities (wallet store, token config, B2.2
    entitlement evaluator).  Output contains typed states and reason codes
    only — no balances, thresholds, quantities, prices, or tokenomics.
    """
    from app.verified.token_entitlement import get_production_policy

    moment = as_of or datetime.now(timezone.utc)
    wallet_state, wallet_record = get_wallet_state(user_id)

    entitlement_state = None
    entitlement_reason = None
    if get_production_policy() is not None and wallet_state == WALLET_VERIFIED:
        state, reason = _entitlement_state_for_wallet(
            subject_id=user_id or "",
            wallet_address=wallet_record["wallet_address"],
            as_of=moment,
            evidence=evidence,
        )
        entitlement_state = state.value
        entitlement_reason = reason

    resources = {}
    for key, resource in YIELD_RESOURCE_REGISTRY.items():
        state, reason = resource_presentation_state(
            resource,
            wallet_state=wallet_state,
            entitlement_state=entitlement_state,
            entitlement_reason=entitlement_reason,
        )
        resources[key] = {
            "key": key,
            "display_name": resource.display_name,
            "description": resource.description,
            "state": state,
            "reason": reason,
            "note": resource.note,
        }

    return {
        "schema_version": "FINCO_CRYPTO_ACCESS_PRESENTATION_V0",
        "wallet": {
            "state": wallet_state,
            "verified_at": wallet_record["verified_at"] if wallet_record else None,
            # Address shown only when verified (read-only context, as on
            # /yield/monitor today).  Never used for access decisions here.
            "wallet_address": wallet_record["wallet_address"] if wallet_record else None,
        },
        "token": {
            "state": entitlement_state,
            "reason": entitlement_reason,
            # MISSING ≠ ZERO: no balance number is ever emitted by this
            # presentation layer.  Unavailable/absent observations stay typed.
        },
        "resources": resources,
    }
