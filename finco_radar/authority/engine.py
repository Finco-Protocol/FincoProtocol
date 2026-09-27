"""Pure Radar composition of canonical identity, reference, and execution.

No provider is queried here. A missing independent token reference remains
missing even when a Robinhood basis and an executable LI.FI quote exist.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Callable

from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.contracts import AssetKey
from finco_radar.assets.registry import RegistrySnapshot
from finco_radar.gap.contracts import BoundReferencePrice
from finco_radar.liquidity.engine import (
    build_route_signature, execution_price_usd_per_token,
)
from finco_radar.liquidity.contracts import LiquidityComputationError
from finco_radar.quotes.contracts import ExecutionQuote, QuoteSide, QuoteStatus
from finco_radar.tokenization_premium.engine import premium_bps

from .contracts import (
    AuthorityPolicy, AuthoritySnapshot, AuthorityState, BasisPointQuantity,
    ExecutionGap, ExecutionLayer, IndependentTokenReference, ReferenceLayer,
)

_PREMIUM_FORMULA = "(independent_token_reference / robinhood_token_equivalent_basis - 1) * 10000"
_FEE_TREATMENT = "EVIDENCE_ONLY_INCLUSION_UNRESOLVED"


def select_robinhood_registry(
    fetch_live: Callable[[], RegistrySnapshot],
    latest_valid_snapshot: RegistrySnapshot | None,
    *, as_of: datetime, max_age_seconds: int,
) -> RegistrySnapshot | None:
    """Live Robinhood first, then the latest valid retained in-app snapshot.

    A caller is responsible for supplying its latest persisted snapshot; this
    pure Radar layer neither guesses identity nor introduces storage authority.
    Invalid, conflicting, or stale material cannot become a fallback.
    """
    if as_of.tzinfo is None or max_age_seconds <= 0:
        raise ValueError("aware as_of and positive registry age limit required")

    def valid(candidate: RegistrySnapshot | None) -> bool:
        return (isinstance(candidate, RegistrySnapshot)
                and candidate.source == RobinhoodAssetRegistryAdapter.source_name
                and candidate.observed_at.tzinfo is not None
                and _state(candidate.observed_at, as_of, max_age_seconds)
                is AuthorityState.AVAILABLE)

    try:
        live = fetch_live()
    except Exception:  # read failure cannot authorize an alternate identity
        live = None
    if valid(live):
        return live
    return latest_valid_snapshot if valid(latest_valid_snapshot) else None


def _state(observed_at: datetime, as_of: datetime, max_age_seconds: int) -> AuthorityState:
    age = (as_of - observed_at).total_seconds()
    return AuthorityState.AVAILABLE if 0 <= age <= max_age_seconds else AuthorityState.STALE


def _missing_reference(state: AuthorityState, reason: str, *, key: AssetKey | None = None) -> ReferenceLayer:
    return ReferenceLayer(state, None, key, None, None, None, None, reason)


def _missing_execution(state: AuthorityState, reason: str, *, quote: ExecutionQuote | None = None) -> ExecutionLayer:
    return ExecutionLayer(
        state, None, quote.side if quote else None,
        quote.requested_notional_usd if quote else None, None,
        quote.source if quote else None, None,
        quote.fee_cost_usd if quote else None, quote.gas_cost_usd if quote else None,
        quote.quoted_at if quote else None, reason,
    )


def build_authority_snapshot(
    *, registry: RegistrySnapshot | None, key: AssetKey,
    underlying_reference: BoundReferencePrice | None,
    token_reference: IndependentTokenReference | None,
    execution_quote: ExecutionQuote | None,
    as_of: datetime, policy: AuthorityPolicy,
) -> AuthoritySnapshot:
    """Return independent layer states, never infer identity from a symbol.

    The registry may be live or a retained *valid* Robinhood RegistrySnapshot;
    callers choose the latest valid snapshot. No other identity provider is
    accepted. The registry UID is the economic link within Robinhood's token
    family; this does not attest equivalence to an unrelated BNB deployment.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    identity_reason = "IDENTITY_UNAVAILABLE"
    asset = None
    if registry is not None:
        if (registry.source == RobinhoodAssetRegistryAdapter.source_name
                and registry.observed_at.tzinfo is not None
                and _state(registry.observed_at, as_of, policy.max_registry_age_seconds)
                is AuthorityState.AVAILABLE):
            asset = registry.get_by_key(key)
            if asset is None:
                identity_reason = "CANONICAL_DEPLOYMENT_ABSENT"
        else:
            identity_reason = "ROBINHOOD_REGISTRY_UNAVAILABLE_OR_STALE"
    if asset is None:
        underlying = _missing_reference(AuthorityState.IDENTITY_UNAVAILABLE, identity_reason)
        token = _missing_reference(AuthorityState.IDENTITY_UNAVAILABLE, identity_reason, key=key)
        execution = _missing_execution(AuthorityState.IDENTITY_UNAVAILABLE, identity_reason, quote=execution_quote)
        uid = None
    else:
        uid = asset.asset_uid
        if (underlying_reference is None or underlying_reference.asset_uid != uid
                or underlying_reference.asset_key != key
                or underlying_reference.current_multiplier != asset.current_multiplier
                or underlying_reference.source != "ROBINHOOD_STOCK_TOKEN_BOUND_PRICE"
                or underlying_reference.is_trading_halt):
            underlying = _missing_reference(AuthorityState.UNAVAILABLE, "BOUND_REFERENCE_UNAVAILABLE_OR_MISMATCHED", key=key)
        else:
            underlying = ReferenceLayer(
                _state(underlying_reference.generated_at, as_of, policy.max_reference_age_seconds),
                uid, key, asset.token_name,
                underlying_reference.token_midpoint_usd_per_token,
                underlying_reference.source, underlying_reference.generated_at,
                "REFERENCE_STALE" if _state(underlying_reference.generated_at, as_of, policy.max_reference_age_seconds)
                is AuthorityState.STALE else None,
            )
        if token_reference is None:
            token = _missing_reference(AuthorityState.UNAVAILABLE, "INDEPENDENT_TOKEN_REFERENCE_UNAVAILABLE", key=key)
        elif token_reference.registry_asset_uid != uid or token_reference.asset_key != key:
            token = _missing_reference(AuthorityState.IDENTITY_UNAVAILABLE, "TOKEN_REFERENCE_IDENTITY_MISMATCH", key=key)
        elif (token_reference.source not in policy.approved_token_reference_sources
              or any(name in token_reference.source.casefold()
                     for name in ("coingecko", "defillama", "lifi", "execution", "robinhood"))):
            token = _missing_reference(AuthorityState.UNAVAILABLE, "TOKEN_REFERENCE_SOURCE_NOT_INDEPENDENT", key=key)
        else:
            token_state = _state(token_reference.observed_at, as_of, policy.max_reference_age_seconds)
            token = ReferenceLayer(token_state, uid, key, asset.token_name,
                                   token_reference.price_usd_per_token, token_reference.source,
                                   token_reference.observed_at,
                                   "TOKEN_REFERENCE_STALE" if token_state is AuthorityState.STALE else None)
        execution = _execution_layer(execution_quote, key, as_of, policy)

    premium_state = AuthorityState.UNAVAILABLE
    premium_reason = "REFERENCE_EVIDENCE_UNAVAILABLE"
    premium_value = None
    if underlying.state is AuthorityState.AVAILABLE and token.state is AuthorityState.AVAILABLE:
        assert underlying.price_usd_per_token is not None and token.price_usd_per_token is not None
        assert underlying.observed_at is not None and token.observed_at is not None
        skew = abs((underlying.observed_at - token.observed_at).total_seconds())
        if skew <= policy.max_evidence_skew_seconds:
            premium_state = AuthorityState.AVAILABLE
            premium_reason = None
            premium_value = premium_bps(token.price_usd_per_token, underlying.price_usd_per_token)
        else:
            premium_reason = "REFERENCE_TIME_MISMATCH"
    elif AuthorityState.IDENTITY_UNAVAILABLE in (underlying.state, token.state):
        premium_state, premium_reason = AuthorityState.IDENTITY_UNAVAILABLE, "IDENTITY_UNAVAILABLE"
    elif AuthorityState.STALE in (underlying.state, token.state):
        premium_state, premium_reason = AuthorityState.STALE, "REFERENCE_STALE"
    premium = BasisPointQuantity(
        premium_state, premium_value,
        token.price_usd_per_token if premium_value is not None else None,
        underlying.price_usd_per_token if premium_value is not None else None,
        _PREMIUM_FORMULA,
        (underlying.source, token.source) if premium_value is not None else (),
        (underlying.observed_at, token.observed_at) if premium_value is not None else (),
        premium_reason,
    )

    gap_state = AuthorityState.UNAVAILABLE
    gap_reason = "PREMIUM_OR_EXECUTION_UNAVAILABLE"
    impact = total = None
    if premium.state is AuthorityState.AVAILABLE and execution.state is AuthorityState.AVAILABLE:
        assert execution.effective_price_usd_per_token is not None
        assert underlying.price_usd_per_token is not None and token.price_usd_per_token is not None
        assert execution.observed_at is not None and token.observed_at is not None
        if abs((execution.observed_at - token.observed_at).total_seconds()) <= policy.max_evidence_skew_seconds:
            impact = ((execution.effective_price_usd_per_token - token.price_usd_per_token)
                      / underlying.price_usd_per_token) * 10000
            total = premium_bps(execution.effective_price_usd_per_token,
                                underlying.price_usd_per_token)
            assert premium.value_bps is not None and total == premium.value_bps + impact
            gap_state, gap_reason = AuthorityState.AVAILABLE, None
        else:
            gap_reason = "EXECUTION_TIME_MISMATCH"
    elif AuthorityState.IDENTITY_UNAVAILABLE in (premium.state, execution.state):
        gap_state, gap_reason = AuthorityState.IDENTITY_UNAVAILABLE, "IDENTITY_UNAVAILABLE"
    elif AuthorityState.STALE in (premium.state, execution.state):
        gap_state, gap_reason = AuthorityState.STALE, "EVIDENCE_STALE"
    gap = ExecutionGap(gap_state, premium.value_bps if total is not None else None,
                       impact, total, _FEE_TREATMENT, gap_reason)
    return AuthoritySnapshot(uid, key, registry.source if asset is not None else None,
                             registry.observed_at if asset is not None else None,
                             underlying, token, premium, execution, gap)


def _execution_layer(quote: ExecutionQuote | None, key: AssetKey,
                     as_of: datetime, policy: AuthorityPolicy) -> ExecutionLayer:
    if quote is None:
        return _missing_execution(AuthorityState.UNAVAILABLE, "EXECUTION_QUOTE_UNAVAILABLE")
    token_leg = quote.input_asset if quote.side is QuoteSide.SELL else quote.output_asset
    token_leg_key = AssetKey(token_leg.chain_id, token_leg.contract_address)
    if (quote.chain_id != key.chain_id or quote.token_address != key.contract_address
            or token_leg_key != key):
        return _missing_execution(AuthorityState.IDENTITY_UNAVAILABLE, "EXECUTION_DEPLOYMENT_MISMATCH", quote=quote)
    if quote.status is QuoteStatus.STALE_QUOTE:
        return _missing_execution(AuthorityState.STALE, "QUOTE_STALE", quote=quote)
    if quote.status is not QuoteStatus.QUOTE_OK or not quote.settlement_reference.usable:
        return _missing_execution(AuthorityState.UNAVAILABLE, "EXECUTION_QUOTE_UNAVAILABLE", quote=quote)
    if any(cost is not None and (not cost.is_finite() or cost < 0)
           for cost in (quote.fee_cost_usd, quote.gas_cost_usd)):
        return _missing_execution(AuthorityState.UNAVAILABLE, "PROVIDER_COST_EVIDENCE_INVALID", quote=quote)
    try:
        route = build_route_signature(quote).legs
        price = execution_price_usd_per_token(quote)
    except (LiquidityComputationError, ValueError):
        return _missing_execution(AuthorityState.UNAVAILABLE, "ROUTE_OR_EXECUTION_EVIDENCE_UNAVAILABLE", quote=quote)
    state = _state(quote.quoted_at, as_of, policy.max_execution_age_seconds)
    return ExecutionLayer(state, key, quote.side, quote.requested_notional_usd,
                          price, quote.source, route, quote.fee_cost_usd,
                          quote.gas_cost_usd, quote.quoted_at,
                          "QUOTE_STALE" if state is AuthorityState.STALE else None)
