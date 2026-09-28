"""Pure deterministic composition of FINCO authority evidence into Reflex state."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from finco_radar.authority.contracts import AuthoritySnapshot, AuthorityState

from .contracts import ReflexProvenance, RwaReflexContext, RwaReflexState

_Z_QUANT = Decimal("0.0001")


def _is_fresh(observed_at: datetime, as_of: datetime, max_age_seconds: int) -> bool:
    age = (as_of - observed_at).total_seconds()
    return 0 <= age <= max_age_seconds


def _unique_sources(*sources: str | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(source for source in sources if source and source.strip()))


def _provenance(authority: AuthoritySnapshot, context: RwaReflexContext) -> ReflexProvenance:
    history = context.basis_history
    liquidity = context.liquidity
    return ReflexProvenance(
        registry_source=authority.registry_source,
        registry_observed_at=authority.registry_observed_at,
        history_source=history.source if history else None,
        history_observed_at=history.observed_at if history else None,
        history_window=history.window if history else None,
        history_sample_count=history.sample_count if history else None,
        history_mean_bps=history.mean_bps if history else None,
        history_std_bps=history.std_bps if history else None,
        history_median_bps=history.median_bps if history else None,
        history_methodology_version=history.methodology_version if history else None,
        liquidity_source=liquidity.source if liquidity else None,
        liquidity_observed_at=liquidity.observed_at if liquidity else None,
        liquidity_methodology_version=liquidity.methodology_version if liquidity else None,
        liquidity_venue_id=liquidity.venue_id if liquidity else None,
        session_source=context.session_source,
        session_resolver_version=context.session_resolver_version,
    )


def _unavailable(
    authority: AuthoritySnapshot,
    context: RwaReflexContext,
    state: AuthorityState,
    reason: str,
) -> RwaReflexState:
    return RwaReflexState(
        economic_asset_uid=authority.economic_asset_uid,
        canonical_token=authority.canonical_token,
        state=state,
        reason=reason,
        market_session=context.market_session,
        underlying_reference_usd=None,
        token_reference_usd=None,
        reference_premium_bps=None,
        execution_impact_bps=None,
        effective_gap_bps=None,
        basis_z_score=None,
        liquidity_usd=None,
        depth_1pct_usd=None,
        observed_at=None,
        evidence_sources=_unique_sources(authority.registry_source),
        provenance=_provenance(authority, context),
    )


def build_reflex_state(
    authority: AuthoritySnapshot,
    *,
    as_of: datetime,
    context: RwaReflexContext | None = None,
    max_context_age_seconds: int = 300,
) -> RwaReflexState:
    """Build state without changing FINCO authority conclusions.

    Canonical identity, references and premium are consumed exactly from
    ``AuthoritySnapshot``.  Any canonical upstream state other than AVAILABLE,
    including STALE, fails closed. Optional stale context is merely omitted.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if max_context_age_seconds <= 0:
        raise ValueError("max_context_age_seconds must be positive")
    context = context or RwaReflexContext()

    premium = authority.premium
    if authority.economic_asset_uid is None:
        return _unavailable(authority, context, AuthorityState.IDENTITY_UNAVAILABLE,
                            premium.reason or "CANONICAL_IDENTITY_UNAVAILABLE")
    if premium.state is not AuthorityState.AVAILABLE:
        return _unavailable(authority, context, premium.state,
                            premium.reason or "REFERENCE_PREMIUM_UNAVAILABLE")
    # RWA_REFLEX_CANONICAL_STALE_FAILS_CLOSED: every canonical reference must itself
    # be AVAILABLE; a stale canonical layer can never be rescued by optional context.
    if authority.underlying.state is not AuthorityState.AVAILABLE:
        return _unavailable(authority, context, authority.underlying.state,
                            authority.underlying.reason or "UNDERLYING_REFERENCE_NOT_AVAILABLE")
    if authority.token.state is not AuthorityState.AVAILABLE:
        return _unavailable(authority, context, authority.token.state,
                            authority.token.reason or "TOKEN_REFERENCE_NOT_AVAILABLE")
    if (authority.underlying.price_usd_per_token is None
            or authority.token.price_usd_per_token is None
            or premium.value_bps is None
            or not premium.observed_at):
        return _unavailable(authority, context, AuthorityState.UNAVAILABLE,
                            "AUTHORITY_SNAPSHOT_INCOMPLETE")

    warnings: list[str] = []
    basis_z_score = None
    liquidity_usd = None
    depth_1pct_usd = None
    structural_premium = None
    extra_sources: list[str] = []

    history = context.basis_history
    if history is not None:
        if _is_fresh(history.observed_at, as_of, max_context_age_seconds):
            extra_sources.append(history.source)
            structural_premium = history.median_bps
            if history.std_bps > 0:
                basis_z_score = ((premium.value_bps - history.mean_bps) / history.std_bps).quantize(_Z_QUANT)
            else:
                warnings.append("BASIS_HISTORY_ZERO_VARIANCE")
        else:
            warnings.append("BASIS_HISTORY_STALE")

    liquidity = context.liquidity
    if liquidity is not None:
        if _is_fresh(liquidity.observed_at, as_of, max_context_age_seconds):
            liquidity_usd = liquidity.liquidity_usd
            depth_1pct_usd = liquidity.depth_1pct_usd
            extra_sources.append(liquidity.source)
        else:
            warnings.append("LIQUIDITY_CONTEXT_STALE")

    execution_impact = None
    effective_gap = None
    if authority.execution_gap.state is AuthorityState.AVAILABLE:
        execution_impact = authority.execution_gap.execution_impact_bps
        effective_gap = authority.execution_gap.effective_gap_bps
        if authority.execution.provider:
            extra_sources.append(authority.execution.provider)

    observed_at = max(t for t in premium.observed_at if t is not None)
    sources = _unique_sources(
        authority.registry_source,
        authority.underlying.source,
        authority.token.source,
        *premium.sources,
        *extra_sources,
    )
    deviation = None if structural_premium is None else premium.value_bps - structural_premium
    return RwaReflexState(
        economic_asset_uid=authority.economic_asset_uid,
        canonical_token=authority.canonical_token,
        state=AuthorityState.AVAILABLE,
        reason=None,
        market_session=context.market_session,
        underlying_reference_usd=authority.underlying.price_usd_per_token,
        token_reference_usd=authority.token.price_usd_per_token,
        reference_premium_bps=premium.value_bps,
        execution_impact_bps=execution_impact,
        effective_gap_bps=effective_gap,
        basis_z_score=basis_z_score,
        liquidity_usd=liquidity_usd,
        depth_1pct_usd=depth_1pct_usd,
        observed_at=observed_at,
        evidence_sources=sources,
        structural_premium_bps=structural_premium,
        premium_deviation_bps=deviation,
        provenance=_provenance(authority, context),
        context_warnings=tuple(warnings),
    )
