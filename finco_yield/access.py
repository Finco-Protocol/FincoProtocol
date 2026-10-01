"""FINCO Crypto Utility V0 — Yield premium server/API gating (Agent B).

Server-side access authority for Yield premium resources.  The decision is
enforced INSIDE each protected endpoint, so direct API invocation cannot
bypass token gating by skipping frontend buttons.

Resource keys (V0):
    yield.basic               PUBLIC — no $FINCO, no wallet
    yield.history             premium (FINCO entitlement capable)
    yield.advanced_compare    premium (FINCO entitlement capable)
    yield.alerts              premium (FINCO entitlement capable)
    yield.execution_preflight premium + verified wallet required

Safe access states (missing != 0; ownership != balance != entitlement):
    ENTITLED
    WALLET_UNAVAILABLE            (no authenticated session)
    WALLET_UNVERIFIED             (session but no verified wallet binding)
    TOKEN_ENTITLEMENT_FEATURE_INACTIVE
    TOKEN_DEPLOYMENT_NOT_CONFIGURED
    ENTITLEMENT_NOT_SATISFIED
    ENTITLEMENT_AUTHORITY_UNAVAILABLE

The entitlement decision NEVER modifies Yield math.  Entitlement is not
execution: a preflight entitlement never enables transactions, custody,
server-side signing, broadcasting or auto-invest.  ``$FINCO never touches
the math; it never determines whether evidence is true.``
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Any

# Feature gate for FINCO-token entitlement evaluation on Yield premium
# resources.  DEFAULT OFF: when inactive, protected resources deny access
# with TOKEN_ENTITLEMENT_FEATURE_INACTIVE (public resources stay public).
_YIELD_TOKEN_ENTITLEMENT_ENABLED = "FINCO_YIELD_TOKEN_ENTITLEMENT_ENABLED"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


class YieldResource(str, Enum):
    BASIC = "yield.basic"
    HISTORY = "yield.history"
    ADVANCED_COMPARE = "yield.advanced_compare"
    ALERTS = "yield.alerts"
    EXECUTION_PREFLIGHT = "yield.execution_preflight"


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
    YieldResource.ALERTS: YieldResourceKind.PREMIUM,
    YieldResource.EXECUTION_PREFLIGHT: YieldResourceKind.PREMIUM_VERIFIED_WALLET,
}


def token_entitlement_feature_enabled(environ: dict | None = None) -> bool:
    env = os.environ if environ is None else environ
    return env.get(_YIELD_TOKEN_ENTITLEMENT_ENABLED, "0").strip().lower() in _TRUTHY


@dataclass(frozen=True)
class YieldAccessDecision:
    resource: YieldResource
    state: YieldAccessState
    entitled: bool
    reason: str
    # Never contains protected payload — decision metadata only.
    wallet_address: str | None = None


def _denied(resource: YieldResource, state: YieldAccessState, reason: str) -> YieldAccessDecision:
    return YieldAccessDecision(resource=resource, state=state, entitled=False, reason=reason)


async def resolve_yield_access(
    request: Any, resource: YieldResource
) -> YieldAccessDecision:
    """Server-side access decision for one Yield resource.

    Trust boundary: called INSIDE the endpoint, before any protected payload
    is serialized.  Reuses the existing FINCO entitlement/wallet authority
    (``resolve_verified_entitlement_for_request`` + ``get_verified_wallet``);
    this module never reads balances itself and never invents thresholds.
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

    if not token_entitlement_feature_enabled():
        return _denied(
            resource, YieldAccessState.TOKEN_ENTITLEMENT_FEATURE_INACTIVE,
            "FINCO token entitlement feature is inactive in this environment")

    from app.verified.entitlement import (
        EntitlementState, resolve_verified_entitlement_for_request,
    )

    entitlement = await resolve_verified_entitlement_for_request(user)
    state = entitlement.state
    if state is EntitlementState.TOKEN_CONFIGURATION_UNAVAILABLE:
        return _denied(resource, YieldAccessState.TOKEN_DEPLOYMENT_NOT_CONFIGURED,
                       "FINCO token deployment is not configured")
    if state is EntitlementState.IDENTITY_UNAVAILABLE:
        return _denied(resource, YieldAccessState.WALLET_UNVERIFIED,
                       "verified wallet required for this resource")
    if state in (EntitlementState.UNAVAILABLE, EntitlementState.STALE):
        # Balance evidence unavailable/stale/mismatched — missing != 0.
        return _denied(resource, YieldAccessState.ENTITLEMENT_AUTHORITY_UNAVAILABLE,
                       entitlement.reason or "entitlement authority unavailable")
    if state is not EntitlementState.ACTIVE:
        return _denied(resource, YieldAccessState.ENTITLEMENT_NOT_SATISFIED,
                       entitlement.reason or "entitlement not satisfied")

    # PREMIUM_VERIFIED_WALLET resources additionally require the verified
    # wallet binding (already proven above via get_verified_wallet).
    if kind is YieldResourceKind.PREMIUM_VERIFIED_WALLET and not wallet_address:
        return _denied(resource, YieldAccessState.WALLET_UNVERIFIED,
                       "verified wallet required for this resource")

    return YieldAccessDecision(
        resource=resource, state=YieldAccessState.ENTITLED, entitled=True,
        reason=entitlement.reason or "ENTITLED", wallet_address=wallet_address,
    )


def denial_payload(decision: YieldAccessDecision) -> dict:
    """Typed sanitized denial body — never contains protected payload."""
    return {
        "error": "YIELD_PREMIUM_REQUIRED",
        "resource": decision.resource.value,
        "access_state": decision.state.value,
        "reason": decision.reason,
    }
