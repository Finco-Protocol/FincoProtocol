"""FINCO Crypto Utility V0 — Yield premium server/API gating (Agent B).

Server-side access authority for Yield premium resources.  The decision is
enforced INSIDE each endpoint, so direct API invocation cannot bypass token
gating by skipping frontend buttons.

Resource keys (V0):
    yield.basic               PUBLIC — no $FINCO, no wallet, no authority lookup
    yield.history             FINCO_HOLDER capable
    yield.advanced_compare    FINCO_HOLDER capable
    yield.alerts              FINCO_HOLDER capable — RESERVED for the actual
                              Alerts/Watchlist surface (Agent C); the legacy
                              Wallet Monitor is NOT this resource.
    yield.execution_preflight FINCO_HOLDER capable + verified wallet required

AUTHORITY FIREWALL (Correction):
    admin privilege  != $FINCO ownership
    admin privilege  != FINCO_HOLDER entitlement
    verified_asset_detail != yield premium entitlement
    VerifiedEntitlement(state=ACTIVE) alone is NEVER sufficient: only
    token-backed evidence (source ``FINCO_TOKEN_BALANCE``) evaluated against
    the configured deployment may ALLOW, and only through the resource-policy
    adapter seam.  The legacy ADMIN_OVERRIDE path is never consulted.
    Agent A owns canonical resource entitlement truth; this module owns
    endpoint enforcement and never queries balances, deployments or
    thresholds itself.

Safe access states (missing != 0; ownership != balance != entitlement !=
execution != metering != staking != burn):
    ENTITLED
    WALLET_UNAVAILABLE
    WALLET_UNVERIFIED
    TOKEN_ENTITLEMENT_FEATURE_INACTIVE   (adapter verdict INACTIVE)
    TOKEN_DEPLOYMENT_NOT_CONFIGURED
    ENTITLEMENT_NOT_SATISFIED
    ENTITLEMENT_AUTHORITY_UNAVAILABLE
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

# Canonical resource keys.
YIELD_BASIC = "yield.basic"
YIELD_HISTORY = "yield.history"
YIELD_ADVANCED_COMPARE = "yield.advanced_compare"
YIELD_ALERTS = "yield.alerts"
YIELD_EXECUTION_PREFLIGHT = "yield.execution_preflight"


class YieldResource(str, Enum):
    BASIC = YIELD_BASIC
    HISTORY = YIELD_HISTORY
    ADVANCED_COMPARE = YIELD_ADVANCED_COMPARE
    ALERTS = YIELD_ALERTS
    EXECUTION_PREFLIGHT = YIELD_EXECUTION_PREFLIGHT


class YieldAccessState(str, Enum):
    PUBLIC = "PUBLIC"
    ENTITLED = "ENTITLED"
    WALLET_UNAVAILABLE = "WALLET_UNAVAILABLE"
    WALLET_UNVERIFIED = "WALLET_UNVERIFIED"
    TOKEN_ENTITLEMENT_FEATURE_INACTIVE = "TOKEN_ENTITLEMENT_FEATURE_INACTIVE"
    TOKEN_DEPLOYMENT_NOT_CONFIGURED = "TOKEN_DEPLOYMENT_NOT_CONFIGURED"
    ENTITLEMENT_NOT_SATISFIED = "ENTITLEMENT_NOT_SATISFIED"
    ENTITLEMENT_AUTHORITY_UNAVAILABLE = "ENTITLEMENT_AUTHORITY_UNAVAILABLE"


class YieldResourceKind(str, Enum):
    PUBLIC = "PUBLIC"
    PREMIUM = "PREMIUM"
    PREMIUM_VERIFIED_WALLET = "PREMIUM_VERIFIED_WALLET"


RESOURCE_REQUIREMENTS: dict[YieldResource, YieldResourceKind] = {
    YieldResource.BASIC: YieldResourceKind.PUBLIC,
    YieldResource.HISTORY: YieldResourceKind.PREMIUM,
    YieldResource.ADVANCED_COMPARE: YieldResourceKind.PREMIUM,
    # RESERVED for the actual Alerts/Watchlist surface (Agent C / integration).
    # The legacy Wallet Monitor is NOT this resource.
    YieldResource.ALERTS: YieldResourceKind.PREMIUM,
    YieldResource.EXECUTION_PREFLIGHT: YieldResourceKind.PREMIUM_VERIFIED_WALLET,
}


@dataclass(frozen=True)
class YieldAccessDecision:
    resource: YieldResource
    state: YieldAccessState
    entitled: bool
    reason: str
    # Decision metadata only — never protected payload.
    wallet_address: str | None = None


def _denied(resource: YieldResource, state: YieldAccessState, reason: str) -> YieldAccessDecision:
    return YieldAccessDecision(resource=resource, state=state, entitled=False, reason=reason)


# ---------------------------------------------------------------------------
# Resource-policy adapter seam (Agent A integration point)
# ---------------------------------------------------------------------------
#
# Agent A owns canonical token/resource entitlement truth.  Agent D connects
# the canonical authority to this seam during integration.  The seam answers
# one question for one (resource_key, verified wallet) pair:
#
#     ALLOW    — canonical resource policy entitles this wallet
#     DENY     — evaluated and not satisfied
#     INACTIVE — canonical resource policy itself is inactive
#
# The default adapter reuses the EXISTING token-backed authority, but only
# accepts source ``FINCO_TOKEN_BALANCE`` results: legacy ADMIN_OVERRIDE and
# other non-token-backed ACTIVE results fail closed.  The legacy
# ``resolve_verified_entitlement_for_request`` path (which can return an
# ACTIVE ADMIN_OVERRIDE without $FINCO ownership) is NEVER consulted.

MAX_ADAPTER_VALUE_LEN = 512


async def _default_resource_entitlement_adapter(
    resource_key: str, wallet_address: str,
) -> tuple[str, str]:
    """Token-backed-only adapter over the existing entitlement authority.

    Evaluates the configured FINCO token deployment for the verified wallet
    (read-only balance evidence).  Returns (outcome, reason) with outcome in
    ALLOW / DENY / INACTIVE.  Only source ``FINCO_TOKEN_BALANCE`` results can
    ALLOW; everything else fails closed.
    """
    from datetime import datetime as _dt

    from app.verified.entitlement import EntitlementState
    from app.verified.token_entitlement import (
        P4ReadOnlyBalanceProvider, evaluate_token_entitlement, get_production_policy,
    )

    context = get_production_policy()
    if context is None:
        return "INACTIVE", "TOKEN_DEPLOYMENT_NOT_CONFIGURED"
    policy, config = context
    evidence = None
    try:
        evidence = await P4ReadOnlyBalanceProvider(config).balance_of(
            policy, wallet_address)
    except Exception:
        evidence = None
    entitlement = evaluate_token_entitlement(
        subject_id=f"wallet:{wallet_address.lower()}",
        wallet_address=wallet_address, policy=policy,
        evidence=evidence, as_of=_dt.now(timezone.utc),
    )
    state = entitlement.state
    if state is EntitlementState.ACTIVE:
        # Source is always FINCO_TOKEN_BALANCE from this pure evaluator.
        return "ALLOW", entitlement.reason or "TOKEN_BALANCE_AT_OR_ABOVE_THRESHOLD"
    if state is EntitlementState.INACTIVE:
        return "DENY", entitlement.reason or "ENTITLEMENT_NOT_SATISFIED"
    if state is EntitlementState.TOKEN_CONFIGURATION_UNAVAILABLE:
        return "INACTIVE", "TOKEN_DEPLOYMENT_NOT_CONFIGURED"
    if state is EntitlementState.STALE:
        return "DENY", entitlement.reason or "ENTITLEMENT_AUTHORITY_UNAVAILABLE"
    return "DENY", entitlement.reason or "ENTITLEMENT_AUTHORITY_UNAVAILABLE"


# Module-level seam (Agent A integration point).  Signature:
#     async (resource_key: str, wallet_address: str) -> (outcome, reason)
# outcome in {"ALLOW", "DENY", "INACTIVE"}.
_resource_entitlement_authority = _default_resource_entitlement_adapter


def set_resource_entitlement_authority(
    authority: Callable[[str, str], Any],
) -> None:
    """Integration seam: install the canonical resource entitlement
    authority (Agent A).  Receives ``(resource_key, wallet_address)`` and
    returns ``(outcome, reason)`` with outcome in ALLOW / DENY / INACTIVE."""
    global _resource_entitlement_authority
    _resource_entitlement_authority = authority


async def _resource_entitlement(resource_key: str, wallet_address: str) -> tuple[str, str]:
    return await _resource_entitlement_authority(resource_key, wallet_address)


async def resolve_yield_access(
    request: Any, resource: YieldResource
) -> YieldAccessDecision:
    """Server-side access decision for one Yield resource.

    Trust boundary: called INSIDE the endpoint, before any protected payload
    is serialized.  ``yield.basic`` never consults the entitlement authority.
    """
    kind = RESOURCE_REQUIREMENTS[resource]
    if kind is YieldResourceKind.PUBLIC:
        return YieldAccessDecision(
            resource=resource, state=YieldAccessState.PUBLIC, entitled=True,
            reason="public resource; no $FINCO entitlement required")

    from app.auth import resolve_request_session

    user = resolve_request_session(request)
    if user is None:
        return _denied(resource, YieldAccessState.WALLET_UNAVAILABLE,
                       "authentication required")

    from app.protocol.wallet_auth import get_verified_wallet

    wallet = get_verified_wallet(user.user_id)
    if wallet is None or not wallet.get("wallet_address"):
        return _denied(resource, YieldAccessState.WALLET_UNVERIFIED,
                       "verified wallet required for this resource")
    wallet_address = wallet["wallet_address"]

    outcome, reason = await _resource_entitlement(resource.value, wallet_address)
    if outcome == "ALLOW":
        return YieldAccessDecision(
            resource=resource, state=YieldAccessState.ENTITLED, entitled=True,
            reason=reason or "ENTITLED", wallet_address=wallet_address)
    if outcome == "INACTIVE":
        return _denied(resource, YieldAccessState.TOKEN_ENTITLEMENT_FEATURE_INACTIVE,
                       reason or "resource policy inactive")
    return _denied(resource, YieldAccessState.ENTITLEMENT_NOT_SATISFIED,
                   reason or "resource entitlement not satisfied")


def denial_payload(decision: YieldAccessDecision) -> dict:
    """Typed sanitized denial body — never contains protected payload."""
    return {
        "error": "YIELD_PREMIUM_REQUIRED",
        "resource": decision.resource.value,
        "access_state": decision.state.value,
        "reason": decision.reason,
    }
