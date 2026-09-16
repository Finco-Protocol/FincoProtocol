"""R5 composition engine over frozen R3 and R4 authorities."""
from __future__ import annotations

from decimal import Decimal

from finco_radar.liquidity.contracts import CostTreatmentState, LiquiditySnapshot
from finco_radar.quotes.contracts import QuoteSide
from finco_radar.reference_state.contracts import ReferenceStateSnapshot
from .contracts import (
    GapDirection, SideAssessment, SignalAuthorityState, SignalComputationError,
    SignalEvent, SignalEventKind, SignalPolicy, SignalSnapshot, SignalStatus,
    SizePersistenceState, SpreadState,
)


def _direction(value: Decimal, threshold: Decimal) -> GapDirection:
    if not value.is_finite():
        raise SignalComputationError("GAP must be finite", SignalStatus.NON_FINITE_SIGNAL_ECONOMICS)
    if value >= threshold:
        return GapDirection.PREMIUM
    if value <= -threshold:
        return GapDirection.DISCOUNT
    return GapDirection.WITHIN_THRESHOLD


def _persistence(small: GapDirection, large: GapDirection) -> SizePersistenceState:
    neutral = GapDirection.WITHIN_THRESHOLD
    if small is neutral and large is neutral:
        return SizePersistenceState.NO_MATERIAL_DISLOCATION
    if small is neutral:
        return SizePersistenceState.EMERGES_AT_SIZE
    if large is neutral:
        return SizePersistenceState.DECAYS
    if small is large:
        return SizePersistenceState.PERSISTS
    return SizePersistenceState.REVERSES


def _spread(value: Decimal, maximum: Decimal) -> SpreadState:
    if not value.is_finite():
        raise SignalComputationError("spread must be finite", SignalStatus.NON_FINITE_SIGNAL_ECONOMICS)
    if value < 0:
        return SpreadState.CROSSED
    return SpreadState.WITHIN_POLICY if value <= maximum else SpreadState.WIDE


def _validate_identity(r3: LiquiditySnapshot, r4: ReferenceStateSnapshot) -> None:
    if (r3.asset_uid != r4.asset_uid or r3.canonical_key != r4.canonical_key or r3.symbol != r4.symbol):
        raise SignalComputationError("R3/R4 canonical identity or symbol metadata mismatch", SignalStatus.SIGNAL_IDENTITY_MISMATCH)


def _validate_lineage(r3: LiquiditySnapshot, r4: ReferenceStateSnapshot) -> None:
    observations = (r3.buy.small_gap_observation, r3.buy.large_gap_observation,
                    r3.sell.small_gap_observation, r3.sell.large_gap_observation)
    for obs in observations:
        expected = (r4.raw_ask if obs.side is QuoteSide.BUY else r4.raw_bid) * r4.current_multiplier
        if obs.reference_generated_at != r4.reference_generated_at:
            raise SignalComputationError("R3/R4 reference timestamp mismatch", SignalStatus.R3_R4_LINEAGE_MISMATCH)
        if obs.reference_is_trading_halt != r4.is_trading_halt:
            raise SignalComputationError("R3/R4 halt evidence mismatch", SignalStatus.R3_R4_LINEAGE_MISMATCH)
        if obs.reference_price_usd_per_token != expected:
            raise SignalComputationError("R3/R4 reconstructed reference price mismatch", SignalStatus.R3_R4_LINEAGE_MISMATCH)


def _side(side, policy: SignalPolicy) -> SideAssessment:
    small_gap, large_gap = side.small_gap_observation.gap_bps, side.large_gap_observation.gap_bps
    small_dir, large_dir = _direction(small_gap, policy.min_abs_gap_bps), _direction(large_gap, policy.min_abs_gap_bps)
    return SideAssessment(
        side=side.side, small_gap_bps=small_gap, large_gap_bps=large_gap,
        small_gap_direction=small_dir, large_gap_direction=large_dir,
        size_persistence_state=_persistence(small_dir, large_dir),
        r0_size_impact_bps=side.r0_size_impact_bps,
        directional_gap_delta_bps=side.directional_gap_delta_bps,
        adverse_size_impact=side.r0_size_impact_bps > policy.max_adverse_size_impact_bps,
        small_route_signature=side.small_route_signature.canonical_form(),
        large_route_signature=side.large_route_signature.canonical_form(),
        route_changed=side.route_changed,
    )


def build_signal_snapshot(*, r3: LiquiditySnapshot, r4: ReferenceStateSnapshot,
                          policy: SignalPolicy) -> SignalSnapshot:
    _validate_identity(r3, r4)
    _validate_lineage(r3, r4)
    if r3.lineage.produced_at.tzinfo is None or r4.as_of.tzinfo is None:
        raise SignalComputationError("R3/R4 time evidence must be timezone-aware", SignalStatus.SIGNAL_EVIDENCE_TIME_MISMATCH)
    skew = Decimal(str(abs((r3.lineage.produced_at - r4.as_of).total_seconds())))
    if skew > policy.max_input_skew_seconds:
        raise SignalComputationError("R3/R4 input skew exceeds SignalPolicy", SignalStatus.SIGNAL_EVIDENCE_TIME_MISMATCH)
    buy, sell = _side(r3.buy, policy), _side(r3.sell, policy)
    active = r4.reference_usable
    events = () if not active else tuple(
        SignalEvent(SignalEventKind.REFERENCE_DISLOCATION, a.side, a.small_gap_direction,
                    a.large_gap_direction, a.size_persistence_state)
        for a in (buy, sell) if a.material
    )
    unresolved = any(c.cost_treatment_state is CostTreatmentState.EVIDENCE_ONLY_INCLUSION_UNRESOLVED for c in r3.cost_evidence)
    return SignalSnapshot(
        status=SignalStatus.SIGNALS_OK, asset_uid=r3.asset_uid, canonical_key=r3.canonical_key,
        symbol=r3.symbol, observed_at=max(r3.lineage.produced_at, r4.as_of),
        signals_active=active,
        authority_state=(SignalAuthorityState.ACTIVE if active else SignalAuthorityState.SUPPRESSED_REFERENCE_UNUSABLE),
        suppression_reasons=(() if active else r4.blocking_reasons),
        buy_assessment=buy, sell_assessment=sell,
        spread_small_state=_spread(r3.spread_small.execution_spread_bps, policy.max_execution_spread_bps),
        spread_large_state=_spread(r3.spread_large.execution_spread_bps, policy.max_execution_spread_bps),
        signal_events=events, policy=policy, input_skew_seconds=skew,
        net_economics_authority=("COST_INCLUSION_UNRESOLVED" if unresolved else "UPSTREAM_COST_TREATMENT_APPLIED"),
        upstream_r3_evidence=r3.to_evidence_dict(), upstream_r4_evidence=r4.to_evidence_dict(),
    )
