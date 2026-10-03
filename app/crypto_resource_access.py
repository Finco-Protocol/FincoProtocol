"""FINCO crypto products — shared resource-access adapter (Tokenized Markets + crypto API).

``app.protocol.entitlement_evaluator.evaluate_resource_access`` is the ONE resource-access authority.
This module never reads a balance, calls an RPC, resolves a token contract, evaluates a threshold or
computes entitlement. It only translates the authority's typed ``ResourceAccessDecision`` into the same
stable product access vocabulary the Yield adapter already uses, so UI and API consumers share one meaning.

Semantic split (identical to ``finco_yield.access``):
  * ``token_entitled`` is True only for an authority ALLOW on a holder resource (never for PUBLIC/INACTIVE);
  * ``access_allowed`` is True for PUBLIC / ALLOW and for INACTIVE (token gating is not active, so the
    existing ungated product behaviour continues). INACTIVE never proves entitlement.

No wallet signing, custody, transaction or trading path exists here.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.protocol.entitlement_evaluator import (
    NO_WALLET,
    Decision,
    ResourceAccessDecision,
    evaluate_resource_access,
    wallet_context_for_session,
)
from app.protocol.entitlement_policy import AccessMode, load_policy_set


class CryptoAccessState(str, Enum):
    """Same values as the Yield adapter's state enum (one vocabulary across products)."""

    PUBLIC = "PUBLIC"
    ENTITLED = "ENTITLED"
    WALLET_UNAVAILABLE = "WALLET_UNAVAILABLE"
    WALLET_UNVERIFIED = "WALLET_UNVERIFIED"
    TOKEN_ENTITLEMENT_FEATURE_INACTIVE = "TOKEN_ENTITLEMENT_FEATURE_INACTIVE"
    TOKEN_DEPLOYMENT_NOT_CONFIGURED = "TOKEN_DEPLOYMENT_NOT_CONFIGURED"
    ENTITLEMENT_NOT_SATISFIED = "ENTITLEMENT_NOT_SATISFIED"
    ENTITLEMENT_AUTHORITY_UNAVAILABLE = "ENTITLEMENT_AUTHORITY_UNAVAILABLE"


@dataclass(frozen=True)
class CryptoAccessDecision:
    resource: str
    state: CryptoAccessState
    access_allowed: bool
    token_entitled: bool
    gate_active: bool
    reason: str
    wallet_address: str | None = None
    upstream: ResourceAccessDecision | None = None

    def safe_fields(self) -> dict:
        """Only fields safe to expose before access is granted."""
        return {"resource": self.resource, "access_state": self.state.value, "reason": self.reason}


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
_WALLET_UNVERIFIED_REASONS = frozenset({"WALLET_NOT_VERIFIED", "WALLET_IDENTITY_UNAVAILABLE"})


def map_deny_reason(reason: str) -> CryptoAccessState:
    if reason == "WALLET_NOT_CONNECTED":
        return CryptoAccessState.WALLET_UNAVAILABLE
    if reason in _WALLET_UNVERIFIED_REASONS:
        return CryptoAccessState.WALLET_UNVERIFIED
    if reason in _DEPLOYMENT_REASONS:
        return CryptoAccessState.TOKEN_DEPLOYMENT_NOT_CONFIGURED
    if reason in _AUTHORITY_REASONS:
        return CryptoAccessState.ENTITLEMENT_AUTHORITY_UNAVAILABLE
    if reason == "BALANCE_BELOW_THRESHOLD":
        return CryptoAccessState.ENTITLEMENT_NOT_SATISFIED
    # Misconfiguration, ambiguous/conflicting identity, unknown resource and any future DENY reason fail closed
    # without pretending the wallet merely holds too little.
    return CryptoAccessState.ENTITLEMENT_AUTHORITY_UNAVAILABLE


def from_resource_decision(resource: str, decision: ResourceAccessDecision) -> CryptoAccessDecision:
    verdict = decision.decision
    if verdict is Decision.ALLOW:
        is_public = decision.reason_code == "PUBLIC_RESOURCE"
        return CryptoAccessDecision(
            resource=resource,
            state=CryptoAccessState.PUBLIC if is_public else CryptoAccessState.ENTITLED,
            access_allowed=True, token_entitled=not is_public, gate_active=not is_public,
            reason=decision.reason_code, wallet_address=decision.wallet_address, upstream=decision)
    if verdict is Decision.INACTIVE:
        return CryptoAccessDecision(
            resource=resource, state=CryptoAccessState.TOKEN_ENTITLEMENT_FEATURE_INACTIVE,
            access_allowed=True, token_entitled=False, gate_active=False,
            reason=decision.reason_code, wallet_address=decision.wallet_address, upstream=decision)
    return CryptoAccessDecision(
        resource=resource, state=map_deny_reason(decision.reason_code),
        access_allowed=False, token_entitled=False, gate_active=True,
        reason=decision.reason_code or "ENTITLEMENT_AUTHORITY_UNAVAILABLE",
        wallet_address=decision.wallet_address, upstream=decision)


async def resolve_crypto_access(request: Any, resource_key: str, **evaluator_kwargs) -> CryptoAccessDecision:
    """Resolve ``resource_key`` for ``request`` through the canonical authority only.

    ``evaluator_kwargs`` (policy_set / provider / approved / environ / now) are forwarded verbatim to
    ``evaluate_resource_access`` — injection points for tests; production passes none.
    """
    policy_set = evaluator_kwargs.get("policy_set") or load_policy_set(evaluator_kwargs.get("environ"))
    policy = policy_set.get(resource_key)
    wallet = NO_WALLET
    # A public resource needs no session or wallet lookup; the authority still issues the decision.
    if policy is None or policy.access_mode is not AccessMode.PUBLIC:
        from app.auth import resolve_request_session

        session = resolve_request_session(request)
        try:
            wallet = wallet_context_for_session(session)
        except (sqlite3.Error, OSError, ValueError):
            wallet = NO_WALLET            # wallet store outage: no wallet authority, never a granted one
    decision = await evaluate_resource_access(resource_key, wallet, **{**evaluator_kwargs,
                                                                       "policy_set": policy_set})
    return from_resource_decision(resource_key, decision)
