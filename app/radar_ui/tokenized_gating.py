"""Tokenized Markets — presentation/API-boundary access gating.

Access authority and market-data authority stay separate: this module only asks the existing Tokenized
access adapter (``app.tokenized_access`` -> ``evaluate_resource_access``) for the three canonical decisions
and strips PROTECTED premium payload from what the router hands to the template. It never reads balances,
never calls an RPC and nothing under ``finco_radar/venues`` consults it.

  tokenized.basic        PUBLIC  — identity + current market state (always shown)
  tokenized.history      holder  — basis history chart, 24h / 7d basis change
  tokenized.dislocation  holder  — cross-venue divergence and dislocation events

``access_allowed`` is True for PUBLIC / ALLOW and for INACTIVE (gating off keeps the existing ungated
behaviour), so default production behaviour is unchanged. Protected payload is removed *before* rendering,
never merely hidden by the template.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

from app.crypto_resource_access import CryptoAccessDecision, CryptoAccessState
from app.tokenized_access import TokenizedResource, resolve_tokenized_access

log = logging.getLogger(__name__)

RESTRICTED = "ACCESS_RESTRICTED"


def _fail_closed(resource: TokenizedResource) -> CryptoAccessDecision:
    return CryptoAccessDecision(
        resource=resource.value, state=CryptoAccessState.ENTITLEMENT_AUTHORITY_UNAVAILABLE,
        access_allowed=False, token_entitled=False, gate_active=True,
        reason="ACCESS_AUTHORITY_ERROR")


@dataclass(frozen=True)
class TokenizedGates:
    basic: CryptoAccessDecision
    history: CryptoAccessDecision
    dislocation: CryptoAccessDecision

    @property
    def any_premium_allowed(self) -> bool:
        return self.history.access_allowed or self.dislocation.access_allowed

    def public_view(self) -> dict[str, dict]:
        """Template context: safe fields only (no wallet, balance, RPC or threshold)."""
        def view(decision: CryptoAccessDecision) -> dict:
            return {"allowed": decision.access_allowed, "state": decision.state.value,
                    "reason": decision.reason, "resource": decision.resource}
        return {"basic": view(self.basic), "history": view(self.history),
                "dislocation": view(self.dislocation)}


async def _resolve(request: Any, resource: TokenizedResource) -> CryptoAccessDecision:
    try:
        return await resolve_tokenized_access(request, resource)
    except Exception as exc:     # a gate failure must never open premium data nor break the public page
        log.warning("tokenized access authority unavailable for %s: %s", resource.value, type(exc).__name__)
        return _fail_closed(resource)


async def resolve_tokenized_gates(request: Any) -> TokenizedGates:
    return TokenizedGates(
        basic=await _resolve(request, TokenizedResource.BASIC),
        history=await _resolve(request, TokenizedResource.HISTORY),
        dislocation=await _resolve(request, TokenizedResource.DISLOCATION))


def redact_landing_row(row: dict, gates: TokenizedGates) -> dict:
    out = dict(row)
    if not gates.history.access_allowed:
        out["basis_change_24h_bps"] = None
        out["basis_change_7d_bps"] = None
    if not gates.dislocation.access_allowed:
        out["cross_venue_divergence_bps"] = None
        out["cross_venue_state"] = RESTRICTED
    return out


def redact_intelligence(intelligence, gates: TokenizedGates):
    """Return ``intelligence`` without protected history / dislocation payload."""
    if intelligence is None:
        return None
    from finco_radar.venues.intelligence import CrossVenueDivergence

    result = intelligence
    if not gates.history.access_allowed:
        result = replace(result, representations=tuple(
            replace(item, basis_change_24h_bps=None, basis_change_7d_bps=None, points=())
            for item in result.representations))
    if not gates.dislocation.access_allowed:
        result = replace(
            result, events=(),
            cross_venue=CrossVenueDivergence(
                state=RESTRICTED, divergence_bps=None, low_venue=None, high_venue=None,
                low_price=None, high_price=None, comparison_unit=None, reason=RESTRICTED))
    return result
