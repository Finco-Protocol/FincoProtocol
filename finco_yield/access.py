"""FINCO Crypto Utility V0 — Yield server/API enforcement adapter.

Agent A (app.protocol.entitlement_evaluator) is the single resource-access
authority.  This module does not evaluate balances, deployments, token truth,
admin privileges, or token economics.  It only translates Agent A's typed
ResourceAccessDecision into the stable Yield HTTP access contract.

Important semantic split:
- token_entitled: true only for an Agent A ALLOW on a holder resource;
- access_allowed: true for PUBLIC/ALLOW and also for INACTIVE, because
  INACTIVE means token gating is not active and existing ungated product
  behaviour must continue.

Legacy ADMIN_OVERRIDE / verified_asset_detail entitlement is never consulted.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.protocol.entitlement_evaluator import (
    Decision,
    ResourceAccessDecision,
    evaluate_resource_access,
    wallet_context_for_session,
)

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
    YieldResource.ALERTS: YieldResourceKind.PREMIUM,
    YieldResource.EXECUTION_PREFLIGHT: YieldResourceKind.PREMIUM_VERIFIED_WALLET,
}


@dataclass(frozen=True)
class YieldAccessDecision:
    resource: YieldResource
    state: YieldAccessState
    access_allowed: bool
    token_entitled: bool
    gate_active: bool
    reason: str
    wallet_address: str | None = None
    upstream: ResourceAccessDecision | None = None

    @property
    def entitled(self) -> bool:
        """Compatibility name: entitlement truth only, never gate bypass."""
        return self.token_entitled


_DEPLOYMENT_REASONS = frozenset({
    "NO_APPROVED_DEPLOYMENT",
    "NO_APPROVED_DEPLOYMENT_ON_CHAIN",
    "TOKEN_CONFIGURATION_UNAVAILABLE",
})
_AUTHORITY_REASONS = frozenset({
    "RPC_UNAVAILABLE",
    "BALANCE_EVIDENCE_UNAVAILABLE",
    "BALANCE_STALE",
    "BALANCE_IDENTITY_MISMATCH",
})
_WALLET_UNVERIFIED_REASONS = frozenset({
    "WALLET_NOT_VERIFIED",
    "WALLET_IDENTITY_UNAVAILABLE",
})


def _map_deny_reason(reason: str) -> YieldAccessState:
    if reason == "WALLET_NOT_CONNECTED":
        return YieldAccessState.WALLET_UNAVAILABLE
    if reason in _WALLET_UNVERIFIED_REASONS:
        return YieldAccessState.WALLET_UNVERIFIED
    if reason in _DEPLOYMENT_REASONS:
        return YieldAccessState.TOKEN_DEPLOYMENT_NOT_CONFIGURED
    if reason in _AUTHORITY_REASONS:
        return YieldAccessState.ENTITLEMENT_AUTHORITY_UNAVAILABLE
    if reason == "BALANCE_BELOW_THRESHOLD":
        return YieldAccessState.ENTITLEMENT_NOT_SATISFIED
    # Misconfiguration, conflicting/ambiguous identity, unknown resource and
    # future DENY reasons all fail closed without pretending the wallet merely
    # has an insufficient balance.
    return YieldAccessState.ENTITLEMENT_AUTHORITY_UNAVAILABLE


def _from_resource_decision(
    resource: YieldResource,
    decision: ResourceAccessDecision,
) -> YieldAccessDecision:
    verdict = decision.decision
    if verdict is Decision.ALLOW:
        is_public = decision.reason_code == "PUBLIC_RESOURCE"
        return YieldAccessDecision(
            resource=resource,
            state=YieldAccessState.PUBLIC if is_public else YieldAccessState.ENTITLED,
            access_allowed=True,
            token_entitled=not is_public,
            gate_active=not is_public,
            reason=decision.reason_code,
            wallet_address=decision.wallet_address,
            upstream=decision,
        )
    if verdict is Decision.INACTIVE:
        return YieldAccessDecision(
            resource=resource,
            state=YieldAccessState.TOKEN_ENTITLEMENT_FEATURE_INACTIVE,
            access_allowed=True,
            token_entitled=False,
            gate_active=False,
            reason=decision.reason_code,
            wallet_address=decision.wallet_address,
            upstream=decision,
        )
    # Anything other than canonical ALLOW/INACTIVE is denied.  Agent A's enum
    # currently makes that Decision.DENY; the defensive branch keeps future
    # unknowns fail-closed.
    return YieldAccessDecision(
        resource=resource,
        state=_map_deny_reason(decision.reason_code),
        access_allowed=False,
        token_entitled=False,
        gate_active=True,
        reason=decision.reason_code or "ENTITLEMENT_AUTHORITY_UNAVAILABLE",
        wallet_address=decision.wallet_address,
        upstream=decision,
    )


async def resolve_yield_access(request: Any, resource: YieldResource) -> YieldAccessDecision:
    """Resolve access inside the protected endpoint through Agent A only."""
    if RESOURCE_REQUIREMENTS[resource] is YieldResourceKind.PUBLIC:
        return YieldAccessDecision(
            resource=resource,
            state=YieldAccessState.PUBLIC,
            access_allowed=True,
            token_entitled=False,
            gate_active=False,
            reason="PUBLIC_RESOURCE",
        )

    from app.auth import resolve_request_session

    session = resolve_request_session(request)
    # Canonical helper preserves authenticated subject_id and obtains the
    # verified wallet binding; no display string is substituted for identity.
    wallet = wallet_context_for_session(session)
    decision = await evaluate_resource_access(resource.value, wallet)
    return _from_resource_decision(resource, decision)


def denial_payload(decision: YieldAccessDecision) -> dict:
    """Typed sanitized denial body — never contains protected payload."""
    return {
        "error": "YIELD_PREMIUM_REQUIRED",
        "resource": decision.resource.value,
        "access_state": decision.state.value,
        "reason": decision.reason,
    }
