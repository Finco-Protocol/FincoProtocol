"""FINCO crypto utility V0 — wallet/$FINCO access PRESENTATION adapter
(Agent C).  Thin, deterministic, pure with respect to access authority.

Authority chain (owned elsewhere — this module NEVER evaluates it):

    verified wallet/session            app.protocol.wallet_auth (existing)
      -> approved $FINCO deployment    Agent A deployment registry
      -> canonical balance evidence    Agent A balance observation
      -> canonical token entitlement   Agent A entitlement authority
      -> resource policy               Agent A RESOURCE_KEYS / policies
      -> ResourceAccessDecision        ALLOW | DENY | INACTIVE + reason
      -> THIS MODULE                   presentation mapping only
      -> UI / JSON

This adapter deliberately does NOT know (and must never grow the
knowledge of) how RPC was called, how deployment provenance was
established, how balance evidence was obtained, how a minimum balance was
evaluated, or how token entitlement was computed.  It consumes an
authoritative ``ResourceAccessDecision``-shaped object per resource key
(duck-typed: ``decision``, ``reason_code``, ``observed_balance``,
``chain_id``, ``token_address`` — Agent A's dataclass plugs in directly)
plus wallet presentation state from the existing session/wallet authority.

Presentation states are deliberately DISTINCT — never collapsed:

    wallet  : DISCONNECTED | UNVERIFIED | VERIFIED
    resource: PUBLIC | NOT_CONFIGURED | LOCKED | UNAVAILABLE | UNLOCKED
              | NOT_ACTIVATED

Mapping (decision/reason → presentation):

    ALLOW + PUBLIC_RESOURCE                  → PUBLIC
    ALLOW + BALANCE_AT_OR_ABOVE_THRESHOLD    → UNLOCKED
    DENY  + BALANCE_BELOW_THRESHOLD          → LOCKED
    DENY  + WALLET_NOT_CONNECTED /
            WALLET_NOT_VERIFIED /
            WALLET_IDENTITY_UNAVAILABLE      → LOCKED (reason retained)
    DENY  + RPC_UNAVAILABLE /
            BALANCE_EVIDENCE_UNAVAILABLE /
            BALANCE_STALE /
            BALANCE_IDENTITY_MISMATCH        → UNAVAILABLE
    DENY  + NO_APPROVED_DEPLOYMENT /
            NO_APPROVED_DEPLOYMENT_ON_CHAIN /
            TOKEN_CONFIGURATION_UNAVAILABLE  → NOT_CONFIGURED
    INACTIVE + TOKEN_GATING_OFF /
            POLICY_DISABLED                  → NOT_ACTIVATED
    decisions unavailable at all             → UNAVAILABLE
                                               (ACCESS_DECISION_UNAVAILABLE —
                                               honest, never guessed)

MISSING ≠ ZERO: a numeric balance is shown only when the authoritative
decision carries an actually-observed balance (``observed_balance`` not
None) — including an explicit zero.  No deployment, RPC failure, stale or
missing evidence, unsupported chain or identity mismatch NEVER produce a
number.  Thresholds (``minimum_balance``) are never surfaced.  Multi-chain
balances are never aggregated: chain/deployment identity travels with the
value or no balance is shown.

Display metadata (names/descriptions/notes, product-delivery state) lives
here; access policy lives in Agent A's resource registry.  ``yield.alerts``
stays NOT_ACTIVATED until alert delivery actually ships (watchlist is
shipped; the Wallet Monitor stays the Wallet Monitor).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Optional

# ── Canonical resource keys (display metadata; access policy = Agent A) ──────
# These strings are permanent public resource identifiers and MUST match the
# Agent A resource registry.  Do NOT rename them.

YIELD_BASIC = "yield.basic"
YIELD_HISTORY = "yield.history"
YIELD_ADVANCED_COMPARE = "yield.advanced_compare"
YIELD_ALERTS = "yield.alerts"
YIELD_EXECUTION_PREFLIGHT = "yield.execution_preflight"


@dataclass(frozen=True)
class ResourceDisplayMeta:
    """PRESENTATION METADATA ONLY — never an access-policy authority."""

    key: str
    display_name: str
    description: str
    activated: bool = True     # False → NOT_ACTIVATED (delivery not shipped)
    note: str | None = None


RESOURCE_DISPLAY: dict[str, ResourceDisplayMeta] = {
    YIELD_BASIC: ResourceDisplayMeta(
        key=YIELD_BASIC,
        display_name="Basic Yield",
        description="Public read-only Yield opportunity table.",
    ),
    YIELD_HISTORY: ResourceDisplayMeta(
        key=YIELD_HISTORY,
        display_name="Yield History",
        description="Historical Yield evidence ranges for tracked opportunities.",
    ),
    YIELD_ADVANCED_COMPARE: ResourceDisplayMeta(
        key=YIELD_ADVANCED_COMPARE,
        display_name="Advanced Compare",
        description="Side-by-side comparison of tracked Yield opportunities.",
    ),
    YIELD_ALERTS: ResourceDisplayMeta(
        key=YIELD_ALERTS,
        display_name="Alerts",
        description="Saved-opportunity alerting. Foundation (watchlist) is "
                    "shipped; alert delivery is not.",
        activated=False,
        note="Watchlist is available; alert delivery is not shipped yet.",
    ),
    YIELD_EXECUTION_PREFLIGHT: ResourceDisplayMeta(
        key=YIELD_EXECUTION_PREFLIGHT,
        display_name="Execution Preflight",
        description="Entitlement status surface for future preflight planning.",
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

REASON_NO_SESSION = "WALLET_NOT_CONNECTED"
REASON_ALERTS_NOT_SHIPPED = "ALERT_DELIVERY_NOT_SHIPPED"
REASON_DECISION_UNAVAILABLE = "ACCESS_DECISION_UNAVAILABLE"

# DENY reason codes that mean "token authority could not be read" — never
# zero, never guessed.
_UNAVAILABLE_REASONS = frozenset({
    "RPC_UNAVAILABLE",
    "BALANCE_EVIDENCE_UNAVAILABLE",
    "BALANCE_STALE",
    "BALANCE_IDENTITY_MISMATCH",
})
# DENY reason codes that mean "no approved production deployment exists".
_NOT_CONFIGURED_REASONS = frozenset({
    "NO_APPROVED_DEPLOYMENT",
    "NO_APPROVED_DEPLOYMENT_ON_CHAIN",
    "TOKEN_CONFIGURATION_UNAVAILABLE",
})
# DENY reason codes that mean "the gate applies and access is not granted".
_LOCKED_REASONS = frozenset({
    "BALANCE_BELOW_THRESHOLD",
    "WALLET_NOT_CONNECTED",
    "WALLET_NOT_VERIFIED",
    "WALLET_IDENTITY_UNAVAILABLE",
})


def get_wallet_state(user_id: str | None) -> tuple[str, Optional[dict]]:
    """Wallet presentation state from the EXISTING wallet/session authority.

    DISCONNECTED — no authenticated session; UNVERIFIED — session without a
    verified wallet binding; VERIFIED — the EIP-191 verification store has
    a row.  Ownership ≠ entitlement: this never grants access.
    """
    if not user_id:
        return WALLET_DISCONNECTED, None
    from app.protocol.wallet_auth import get_verified_wallet
    record = get_verified_wallet(user_id)
    if record is None:
        return WALLET_UNVERIFIED, None
    return WALLET_VERIFIED, record


def _decision_fields(decision: Any) -> tuple[str, str]:
    """Extract (decision, reason_code) from an Agent A decision object."""
    return str(getattr(decision, "decision", "")), str(
        getattr(decision, "reason_code", "") or "")


def present_resource(
    meta: ResourceDisplayMeta,
    decision: Any | None, *,
    wallet_state: str | None = None,
) -> dict:
    """Deterministically map ONE authoritative decision to presentation.

    Pure: same inputs → same output; no authority is computed here.  A
    missing decision is an honest typed UNAVAILABLE — access is never
    guessed.
    """
    if not meta.activated:
        # Product-delivery state, independent of any token authority.
        return _view(meta, RESOURCE_NOT_ACTIVATED, REASON_ALERTS_NOT_SHIPPED)

    if decision is None:
        return _view(meta, RESOURCE_UNAVAILABLE, REASON_DECISION_UNAVAILABLE)

    verdict, reason = _decision_fields(decision)
    if verdict == "INACTIVE":
        # No active token gate denied the user — never present as LOCKED.
        return _view(meta, RESOURCE_NOT_ACTIVATED, reason or "TOKEN_GATING_OFF")
    if verdict == "ALLOW":
        if reason == "PUBLIC_RESOURCE":
            return _view(meta, RESOURCE_PUBLIC, reason, decision=decision)
        return _view(meta, RESOURCE_UNLOCKED, reason or "BALANCE_AT_OR_ABOVE_THRESHOLD",
                     decision=decision)
    if verdict == "DENY":
        if reason in _NOT_CONFIGURED_REASONS:
            return _view(meta, RESOURCE_NOT_CONFIGURED, reason)
        if reason in _UNAVAILABLE_REASONS:
            return _view(meta, RESOURCE_UNAVAILABLE, reason)
        if reason in _LOCKED_REASONS:
            return _view(meta, RESOURCE_LOCKED, reason, decision=decision)
        # Unknown DENY reason: fail closed honestly, never guess.
        return _view(meta, RESOURCE_UNAVAILABLE, reason or REASON_DECISION_UNAVAILABLE)
    return _view(meta, RESOURCE_UNAVAILABLE, reason or REASON_DECISION_UNAVAILABLE)


def _balance_presentation(decision: Any | None) -> Optional[dict]:
    """Authoritative balance display — MISSING ≠ ZERO.

    A number appears ONLY when the decision carries an actually-observed
    balance (explicit zero included).  Chain/deployment identity travels
    with the value; no aggregation, no threshold, no guesses.
    """
    if decision is None:
        return None
    observed = getattr(decision, "observed_balance", None)
    if not isinstance(observed, Decimal):
        return None
    chain_id = getattr(decision, "chain_id", None)
    token_address = getattr(decision, "token_address", None)
    if chain_id is None or not token_address:
        # Identity not explicit → report unavailable rather than a bare number.
        return None
    return {
        "observed_balance": str(observed),
        "chain_id": chain_id,
        "token_address": token_address,
    }


def _view(meta: ResourceDisplayMeta, state: str, reason: str | None, *,
          decision: Any | None = None) -> dict:
    view = {
        "key": meta.key,
        "display_name": meta.display_name,
        "description": meta.description,
        "state": state,
        "reason": reason,
        "note": meta.note,
        # MISSING ≠ ZERO: numeric only for an authoritative observation.
        "balance": _balance_presentation(decision),
    }
    return view


def build_crypto_access_snapshot(
    wallet_state: str, *,
    resource_decisions: Mapping[str, Any] | None = None,
    resources: Mapping[str, ResourceDisplayMeta] | None = None,
) -> dict:
    """Deterministic presentation bundle.

    ``wallet_state`` comes from :func:`get_wallet_state` (existing
    session/wallet authority).  ``resource_decisions`` are authoritative
    Agent A ``ResourceAccessDecision`` objects keyed by resource key —
    Agent D supplies them at integration (``await evaluate_all_resources``);
    when they are unavailable every authority-dependent resource presents
    typed UNAVAILABLE.  No fallback ever computes access here.
    """
    meta_map = resources if resources is not None else RESOURCE_DISPLAY
    decisions = resource_decisions or {}
    resources_view = {}
    for key, meta in meta_map.items():
        decision = decisions.get(key)
        resources_view[key] = present_resource(
            meta, decision, wallet_state=wallet_state)
    return {
        "schema_version": "FINCO_CRYPTO_ACCESS_PRESENTATION_V0",
        "wallet": {"state": wallet_state},
        "resources": resources_view,
    }
