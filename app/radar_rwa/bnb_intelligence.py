"""B1.3 presentation of B1.0 authority, gated by B1.2 exact identity.

This module never calculates a premium or an execution gap.  In particular,
the B1.1 CoinGecko observation is not an authority input.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from finco_radar.assets.contracts import AssetKey
from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.registry import RegistrySnapshot
from finco_radar.authority.contracts import (
    AuthorityPolicy, AuthoritySnapshot, AuthorityState, IndependentTokenReference,
)
from finco_radar.authority.cross_chain import CrossChainIdentityBinding
from finco_radar.authority.engine import build_authority_snapshot
from finco_radar.gap.contracts import BoundReferencePrice
from finco_radar.quotes.contracts import ExecutionQuote


@dataclass(frozen=True)
class BnbAuthorityEvidence:
    """Explicit inputs; no market-observation or symbol-based fallback."""

    registry: RegistrySnapshot | None
    underlying_reference: BoundReferencePrice | None
    token_reference: IndependentTokenReference | None
    execution_quote: ExecutionQuote | None
    policy: AuthorityPolicy


EvidenceResolver = Callable[[AssetKey, CrossChainIdentityBinding], BnbAuthorityEvidence | None]


def _number(value) -> str | None:
    return str(value) if value is not None else None


def _time(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def unavailable_intelligence(state: AuthorityState, reason: str) -> dict:
    """Fail-closed shape shared by API, UI, and history reads."""
    return {
        "state": state.value, "reason": reason,
        "robinhood_basis": {"state": state.value, "price_usd_per_token": None,
                             "source": None, "observed_at": None, "reason": reason},
        "independent_token_reference": {"state": state.value, "price_usd_per_token": None,
                                        "source": None, "observed_at": None, "reason": reason},
        "reference_premium": {"state": state.value, "value_bps": None,
                              "formula": None, "sources": [], "observed_at": [], "reason": reason},
        "execution": {"state": state.value, "side": None, "effective_price_usd_per_token": None,
                      "requested_notional_usd": None, "provider": None, "route": None,
                      "fee_cost_usd": None, "gas_cost_usd": None, "observed_at": None,
                      "reason": reason},
        "execution_gap": {"state": state.value, "reference_premium_bps": None,
                          "execution_impact_bps": None, "effective_gap_bps": None,
                          "fee_treatment": "EVIDENCE_ONLY_INCLUSION_UNRESOLVED", "reason": reason},
    }


def serialize_authority(snapshot: AuthoritySnapshot) -> dict:
    underlying, token = snapshot.underlying, snapshot.token
    premium, execution, gap = snapshot.premium, snapshot.execution, snapshot.execution_gap
    return {
        "state": premium.state.value, "reason": premium.reason,
        "robinhood_basis": {"state": underlying.state.value,
                            "price_usd_per_token": _number(underlying.price_usd_per_token),
                            "source": underlying.source, "observed_at": _time(underlying.observed_at),
                            "reason": underlying.reason},
        "independent_token_reference": {"state": token.state.value,
                                        "price_usd_per_token": _number(token.price_usd_per_token),
                                        "source": token.source, "observed_at": _time(token.observed_at),
                                        "reason": token.reason},
        "reference_premium": {"state": premium.state.value, "value_bps": _number(premium.value_bps),
                              "formula": premium.formula, "sources": list(premium.sources),
                              "observed_at": [_time(t) for t in premium.observed_at],
                              "reason": premium.reason},
        "execution": {"state": execution.state.value,
                      "side": execution.side.value if execution.side else None,
                      "effective_price_usd_per_token": _number(execution.effective_price_usd_per_token),
                      "requested_notional_usd": _number(execution.requested_notional_usd),
                      "provider": execution.provider, "route": execution.route,
                      "fee_cost_usd": _number(execution.fee_cost_usd),
                      "gas_cost_usd": _number(execution.gas_cost_usd),
                      "observed_at": _time(execution.observed_at), "reason": execution.reason},
        "execution_gap": {"state": gap.state.value,
                          "reference_premium_bps": _number(gap.reference_premium_bps),
                          "execution_impact_bps": _number(gap.execution_impact_bps),
                          "effective_gap_bps": _number(gap.effective_gap_bps),
                          "fee_treatment": gap.fee_treatment, "reason": gap.reason},
    }


def compose_bnb_intelligence(
    key: AssetKey | None, binding: CrossChainIdentityBinding | None,
    evidence: BnbAuthorityEvidence | None, *, as_of: datetime | None = None,
) -> dict:
    """B1.2 is the first gate; B1.0 remains the sole arithmetic authority."""
    if key is None or binding is None or binding.state is not AuthorityState.AVAILABLE:
        state = binding.state if binding is not None else AuthorityState.IDENTITY_UNAVAILABLE
        return unavailable_intelligence(state, binding.reason if binding and binding.reason else "CANONICAL_IDENTITY_UNAVAILABLE")
    if binding.external_asset_key != key or binding.economic_asset_uid is None or key not in binding.canonical_deployments:
        return unavailable_intelligence(AuthorityState.IDENTITY_UNAVAILABLE, "CANONICAL_IDENTITY_MISMATCH")
    if evidence is None:
        return unavailable_intelligence(AuthorityState.UNAVAILABLE, "AUTHORITY_EVIDENCE_UNAVAILABLE")
    if (evidence.registry is None
            or evidence.registry.source != RobinhoodAssetRegistryAdapter.source_name
            or binding.authority_source not in (
                f"{RobinhoodAssetRegistryAdapter.source_name}:LIVE",
                f"{RobinhoodAssetRegistryAdapter.source_name}:RETAINED",
            )
            or evidence.registry.observed_at != binding.observed_at
            or evidence.registry.get_by_key(key) is None
            or evidence.registry.require_by_key(key).asset_uid != binding.economic_asset_uid
            or evidence.registry.require_by_key(key).deployments != binding.canonical_deployments):
        return unavailable_intelligence(AuthorityState.IDENTITY_UNAVAILABLE, "CANONICAL_REGISTRY_IDENTITY_MISMATCH")
    result = build_authority_snapshot(
        registry=evidence.registry, key=key, underlying_reference=evidence.underlying_reference,
        token_reference=evidence.token_reference, execution_quote=evidence.execution_quote,
        as_of=as_of or datetime.now(timezone.utc), policy=evidence.policy,
    )
    if result.economic_asset_uid != binding.economic_asset_uid:
        return unavailable_intelligence(AuthorityState.IDENTITY_UNAVAILABLE, "CANONICAL_REGISTRY_IDENTITY_MISMATCH")
    return serialize_authority(result)
