"""Revenue V2 plan evaluation — volume allocation, stream composition, results.

Period evaluation of a validated ``RevenuePlan``. All price resolution reuses
the existing domain authorities (``PPAParams.price_at_year``,
``MerchantParams.price_at_year`` + capture rates,
``FeedInTariffParams.price_at_year``, ``CfDParams.cfd_payment_at_year``);
this module orchestrates volume allocation and composition and never
re-implements their formulas.

Lifecycle authority: ``RevenueStream.start_year`` / ``term_years`` exclusively
decide activity. The legacy nested CfD term clock is neutralized by evaluating
the existing settlement formula with a term that covers the stream's own
active window — the CfD formula keeps owning strike-reference settlement and
two-way/one-way direction; the stream owns start/term.

Economic invariants (deterministic, tested):

- Time-aware primary allocation: only primary streams ACTIVE in the evaluated
  year consume (or free) allocation capacity, so a residual merchant holds
  100% before a delayed PPA starts and after it expires.
- Total revenue semantics: when any stream is UNAVAILABLE the canonical
  ``total_revenue_keur`` is None (MISSING != ZERO); the sum of available
  streams is exposed separately as ``available_revenue_subtotal_keur`` and is
  never presented as the complete total. Unknown component economics
  (underlying market revenue, support/settlement) are None, never 0.0.
  Inactive / disabled / expired streams keep their explicit zero
  contribution, distinct from unavailable.
- Σ allocated primary generation + unallocated generation
  = eligible generation (within tolerance).
- Overlay streams (CfD, premium) add ONLY their settlement/support payment;
  the underlying market revenue on the settled volume is displayed as a
  component, never counted twice.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from domain.revenue.plan import (
    ContractRole,
    RevenuePlan,
    RevenueStream,
    RevenueStreamType,
)
from domain.revenue.revenue_config import CfDParams

# Generation identity tolerance policy (Correction B §8): share-space and
# MWh-space are different units and never share one raw numeric tolerance.
#   - SHARE_ALLOCATION_TOLERANCE (dimensionless, in plan.py) bounds share-sum
#     validation;
#   - the runtime MWh identity tolerance is an absolute float-safety floor
#     OR the validated share epsilon scaled by the period's eligible
#     generation, whichever is larger — so a plan accepted by share
#     validation can never fail its MWh identity merely because the
#     tolerated epsilon was multiplied by generation.
MWH_IDENTITY_TOLERANCE_ABSOLUTE = 1e-9  # MWh floor for float noise


def _mwh_identity_tolerance(eligible_generation_mwh: float) -> float:
    from domain.revenue.plan import SHARE_ALLOCATION_TOLERANCE

    return max(
        MWH_IDENTITY_TOLERANCE_ABSOLUTE,
        SHARE_ALLOCATION_TOLERANCE * eligible_generation_mwh,
    )

# Neutralized nested-CfD term: the RevenueStream owns lifecycle; this bound
# simply makes the legacy nested clock a no-op inside the stream's active
# window (the stream status gates NOT_STARTED / EXPIRED before evaluation).
_CFD_NESTED_TERM_NEUTRALIZED = 10_000_000


class StreamPeriodStatus(str, Enum):
    """Typed per-period stream status. MISSING/UNAVAILABLE are never ZERO."""

    ACTIVE = "active"
    DISABLED = "disabled"                # enabled=False (INACTIVE != UNAVAILABLE)
    NOT_STARTED = "not_started"          # year < start_year (INACTIVE)
    EXPIRED = "expired"                  # year beyond term (EXPIRED != INVALID)
    UNAVAILABLE = "unavailable"          # price/data authority missing (!= ZERO)


class PlanPeriodStatus(str, Enum):
    """Typed per-period plan status."""

    OK = "ok"
    PARTIALLY_UNALLOCATED = "partially_unallocated"  # generation left unsold
    HAS_UNAVAILABLE_STREAMS = "has_unavailable_streams"  # total revenue is None


@dataclass(frozen=True)
class RevenueStreamPeriodResult:
    """One stream's typed result for one period.

    ``underlying_market_revenue_keur`` and ``support_or_settlement_keur`` are
    None when their economics are unknown (UNAVAILABLE) — unknown is never
    encoded as economic 0.0. Inactive/disabled/expired periods carry explicit
    0.0 contributions and a typed status.
    """

    stream_id: str
    stream_type: RevenueStreamType
    contract_role: ContractRole
    year: int
    status: StreamPeriodStatus
    # Volume actually contracted by this stream in this period (MWh).
    # Overlays report their contractual settlement volume (no capacity use).
    allocated_generation_mwh: float
    # The full eligible generation of the stream's allocation group (MWh).
    eligible_generation_mwh: float
    # Resolved contract/reference price (EUR/MWh); None when unavailable.
    price_eur_mwh: float | None
    # Market revenue on the contracted volume before support (kEUR).
    underlying_market_revenue_keur: float | None
    # CfD settlement / premium support payment (kEUR; signed for CfD).
    support_or_settlement_keur: float | None
    # The stream's economic addition for the period (kEUR); None when
    # unavailable — never a silent zero.
    stream_revenue_keur: float | None


@dataclass(frozen=True)
class RevenuePlanPeriodResult:
    """One period's aggregated plan result.

    ``total_revenue_keur`` is None when any stream is UNAVAILABLE in this
    period (the total is unknown, not zero). ``available_revenue_subtotal_keur``
    sums only the available streams and is never a substitute for the total.
    """

    year: int
    total_eligible_generation_mwh: float
    stream_results: tuple[RevenueStreamPeriodResult, ...]  # ordered by stream_id
    total_revenue_keur: float | None
    available_revenue_subtotal_keur: float
    unallocated_generation_mwh: float
    status: PlanPeriodStatus


def _reference_price_eur_mwh(
    plan: RevenuePlan,
    stream: RevenueStream,
    year: int,
) -> float | None:
    """Resolve the overlay reference market price (no capture adjustment —
    this is the market price the settlement references)."""
    if stream.reference_stream_id is not None:
        ref = plan.stream_by_id(stream.reference_stream_id)
        if ref is None or ref.merchant is None or not ref.merchant.merchant_enabled:
            return None
        return ref.merchant.price_at_year(year)
    if plan.market_price is not None:
        return plan.market_price.price_at_year(year)
    return None


def _active_explicit_primary_shares(
    plan: RevenuePlan,
    year: int,
) -> dict[str, float]:
    """Sum of explicit shares per group, counting ONLY primary streams that
    are ACTIVE in the evaluated year (time-aware allocation)."""
    shares: dict[str, float] = {}
    for stream in plan.streams:
        if (
            stream.contract_role is ContractRole.PRIMARY_ALLOCATION
            and stream.enabled
            and stream.volume_share is not None
            and stream.is_active(year)
        ):
            shares[stream.allocation_group] = (
                shares.get(stream.allocation_group, 0.0) + float(stream.volume_share)
            )
    return shares


def _stream_volume_mwh(
    stream: RevenueStream,
    eligible_generation_mwh: float,
    active_explicit_shares: dict[str, float],
) -> float:
    """Contracted volume for this stream/period.

    Primary residual merchant: eligible − Σ ACTIVE explicit primary shares,
    floor zero (a dormant PPA frees its share back to the merchant).
    Primary explicit share: eligible × share.
    Overlay: eligible × share (contractual settlement volume; consumes no
    allocation capacity).
    """
    if stream.contract_role is ContractRole.PRIMARY_ALLOCATION:
        if stream.volume_share is None:
            explicit = active_explicit_shares.get(stream.allocation_group, 0.0)
            return max(0.0, (1.0 - explicit) * eligible_generation_mwh)
        return max(0.0, eligible_generation_mwh * float(stream.volume_share))
    # Overlay
    return max(0.0, eligible_generation_mwh * float(stream.volume_share or 0.0))


def _period_status(stream: RevenueStream, year: int) -> StreamPeriodStatus:
    if not stream.enabled:
        return StreamPeriodStatus.DISABLED
    if year < stream.start_year:
        return StreamPeriodStatus.NOT_STARTED
    if not stream.is_active(year):
        return StreamPeriodStatus.EXPIRED
    return StreamPeriodStatus.ACTIVE


def _inactive_result(
    stream: RevenueStream,
    year: int,
    status: StreamPeriodStatus,
) -> RevenueStreamPeriodResult:
    """Explicit zero contribution for a known-inactive period (NOT unavailable)."""
    return RevenueStreamPeriodResult(
        stream_id=stream.stream_id,
        stream_type=stream.stream_type,
        contract_role=stream.contract_role,
        year=year,
        status=status,
        allocated_generation_mwh=0.0,
        eligible_generation_mwh=0.0,
        price_eur_mwh=None,
        underlying_market_revenue_keur=0.0,
        support_or_settlement_keur=0.0,
        stream_revenue_keur=0.0,
    )


def _unavailable_result(
    stream: RevenueStream,
    year: int,
    volume_mwh: float,
    group_eligible: float,
) -> RevenueStreamPeriodResult:
    """Typed unavailable result — every unknown economic component is None."""
    return RevenueStreamPeriodResult(
        stream_id=stream.stream_id,
        stream_type=stream.stream_type,
        contract_role=stream.contract_role,
        year=year,
        status=StreamPeriodStatus.UNAVAILABLE,
        allocated_generation_mwh=volume_mwh,
        eligible_generation_mwh=group_eligible,
        price_eur_mwh=None,
        underlying_market_revenue_keur=None,
        support_or_settlement_keur=None,
        stream_revenue_keur=None,
    )


def _evaluate_primary_stream(
    stream: RevenueStream,
    year: int,
    status: StreamPeriodStatus,
    volume_mwh: float,
    group_eligible: float,
    technology: str,
) -> RevenueStreamPeriodResult:
    if status is StreamPeriodStatus.UNAVAILABLE:
        return _unavailable_result(stream, year, volume_mwh, group_eligible)
    if status is not StreamPeriodStatus.ACTIVE:
        return _inactive_result(stream, year, status)

    if stream.stream_type is RevenueStreamType.PPA:
        price = stream.ppa.price_at_year(year)
        gross_keur = volume_mwh * price / 1000.0
        # Existing balancing-cost convention: net = gross × (1 − pct).
        net_keur = gross_keur * (1.0 - stream.ppa.balancing_cost_pct)
        return RevenueStreamPeriodResult(
            stream_id=stream.stream_id,
            stream_type=stream.stream_type,
            contract_role=stream.contract_role,
            year=year,
            status=status,
            allocated_generation_mwh=volume_mwh,
            eligible_generation_mwh=group_eligible,
            price_eur_mwh=price,
            underlying_market_revenue_keur=gross_keur,
            support_or_settlement_keur=0.0,
            stream_revenue_keur=net_keur,
        )

    if stream.stream_type is RevenueStreamType.MERCHANT:
        price = stream.merchant.price_at_year(year)
        capture = stream.merchant.capture_rate_for_tech(technology)
        revenue_keur = volume_mwh * price * capture / 1000.0
        return RevenueStreamPeriodResult(
            stream_id=stream.stream_id,
            stream_type=stream.stream_type,
            contract_role=stream.contract_role,
            year=year,
            status=status,
            allocated_generation_mwh=volume_mwh,
            eligible_generation_mwh=group_eligible,
            price_eur_mwh=price,
            underlying_market_revenue_keur=revenue_keur,
            support_or_settlement_keur=0.0,
            stream_revenue_keur=revenue_keur,
        )

    if stream.stream_type in (RevenueStreamType.FIT_FIXED, RevenueStreamType.AUCTION_AWARDED_TARIFF):
        price = stream.fit.price_at_year(year)  # fixed_fit branch (with index)
        revenue_keur = volume_mwh * price / 1000.0
        return RevenueStreamPeriodResult(
            stream_id=stream.stream_id,
            stream_type=stream.stream_type,
            contract_role=stream.contract_role,
            year=year,
            status=status,
            allocated_generation_mwh=volume_mwh,
            eligible_generation_mwh=group_eligible,
            price_eur_mwh=price,
            underlying_market_revenue_keur=revenue_keur,
            support_or_settlement_keur=0.0,
            stream_revenue_keur=revenue_keur,
        )

    if stream.stream_type is RevenueStreamType.INDEXED_FIT:
        idx = year - 1
        if idx >= len(stream.indexed_fit_index_factors):
            # Missing index authority for this year: typed unavailable, never
            # a silent extrapolation or zero.
            return _unavailable_result(stream, year, volume_mwh, group_eligible)
        price = stream.indexed_fit_base_tariff_eur_mwh * stream.indexed_fit_index_factors[idx]
        revenue_keur = volume_mwh * price / 1000.0
        return RevenueStreamPeriodResult(
            stream_id=stream.stream_id,
            stream_type=stream.stream_type,
            contract_role=stream.contract_role,
            year=year,
            status=status,
            allocated_generation_mwh=volume_mwh,
            eligible_generation_mwh=group_eligible,
            price_eur_mwh=price,
            underlying_market_revenue_keur=revenue_keur,
            support_or_settlement_keur=0.0,
            stream_revenue_keur=revenue_keur,
        )

    raise ValueError(
        f"REVENUE_PRIMARY_STREAM_TYPE_UNHANDLED: {stream.stream_type!r}"
    )


def _evaluate_overlay_stream(
    plan: RevenuePlan,
    stream: RevenueStream,
    year: int,
    status: StreamPeriodStatus,
    volume_mwh: float,
    group_eligible: float,
) -> RevenueStreamPeriodResult:
    if status is StreamPeriodStatus.UNAVAILABLE:
        return _unavailable_result(stream, year, volume_mwh, group_eligible)
    if status is not StreamPeriodStatus.ACTIVE:
        return _inactive_result(stream, year, status)

    reference = _reference_price_eur_mwh(plan, stream, year)
    if reference is None:
        return _unavailable_result(stream, year, volume_mwh, group_eligible)

    if stream.stream_type is RevenueStreamType.CFD:
        # Reuse the existing CfD settlement formula authority: derive a
        # CfDParams carrying THIS period's contractual volume and a
        # neutralized nested term (the RevenueStream owns lifecycle; the
        # formula owns strike-reference settlement and two-way/one-way
        # direction — unchanged).
        period_cfd = CfDParams(
            cfd_enabled=True,
            strike_price_eur_mwh=stream.cfd.strike_price_eur_mwh,
            reference_price_type=stream.cfd.reference_price_type,
            cfd_term_years=_CFD_NESTED_TERM_NEUTRALIZED,
            cfd_volume_mwh_annual=volume_mwh,
            two_way_cfd=stream.cfd.two_way_cfd,
            cfd_counterparty=stream.cfd.cfd_counterparty,
            cfd_guarantee=stream.cfd.cfd_guarantee,
        )
        settlement_keur = period_cfd.cfd_payment_at_year(year, reference) / 1000.0
        underlying_keur = volume_mwh * reference / 1000.0
        return RevenueStreamPeriodResult(
            stream_id=stream.stream_id,
            stream_type=stream.stream_type,
            contract_role=stream.contract_role,
            year=year,
            status=status,
            allocated_generation_mwh=volume_mwh,
            eligible_generation_mwh=group_eligible,
            price_eur_mwh=stream.cfd.strike_price_eur_mwh,
            underlying_market_revenue_keur=underlying_keur,
            support_or_settlement_keur=settlement_keur,
            # Overlay economic addition = settlement only; the underlying
            # market sale belongs to the volume-owning primary stream.
            stream_revenue_keur=settlement_keur,
        )

    if stream.stream_type is RevenueStreamType.FIT_PREMIUM:
        supported_price = stream.fit.price_at_year(year, reference)  # premium clip branch
        support_keur = volume_mwh * (supported_price - reference) / 1000.0
        underlying_keur = volume_mwh * reference / 1000.0
        return RevenueStreamPeriodResult(
            stream_id=stream.stream_id,
            stream_type=stream.stream_type,
            contract_role=stream.contract_role,
            year=year,
            status=status,
            allocated_generation_mwh=volume_mwh,
            eligible_generation_mwh=group_eligible,
            price_eur_mwh=supported_price,
            underlying_market_revenue_keur=underlying_keur,
            support_or_settlement_keur=support_keur,
            # Overlay economic addition = support payment only.
            stream_revenue_keur=support_keur,
        )

    raise ValueError(
        f"REVENUE_OVERLAY_STREAM_TYPE_UNHANDLED: {stream.stream_type!r}"
    )


def evaluate_revenue_plan(
    plan: RevenuePlan,
    year: int,
    eligible_generation_mwh: float,
    *,
    technology: str = "solar",
) -> RevenuePlanPeriodResult:
    """Evaluate the plan for one model year. Deterministic and order-safe.

    ``year`` must be a positive integer (1-based model year, per the existing
    domain revenue math) and ``eligible_generation_mwh`` a finite
    non-negative generation scalar for the plan's single effective
    allocation group. Re-validates the plan (fail closed) first.
    """
    plan.validate()
    if not isinstance(year, int) or isinstance(year, bool) or year < 1:
        raise ValueError(
            f"REVENUE_PLAN_YEAR_INVALID: year must be a positive integer "
            f"(1-based model year), got {year!r}"
        )
    if not math.isfinite(eligible_generation_mwh) or eligible_generation_mwh < 0.0:
        raise ValueError(
            f"REVENUE_PLAN_ELIGIBLE_GENERATION_INVALID: {eligible_generation_mwh!r}"
        )

    active_explicit_shares = _active_explicit_primary_shares(plan, year)

    results: list[RevenueStreamPeriodResult] = []
    allocated_total = 0.0
    for stream in plan.streams:
        status = _period_status(stream, year)
        volume = _stream_volume_mwh(stream, eligible_generation_mwh, active_explicit_shares)
        if stream.contract_role is ContractRole.PRIMARY_ALLOCATION:
            if status is StreamPeriodStatus.ACTIVE:
                allocated_total += volume
            result = _evaluate_primary_stream(
                stream, year, status, volume, eligible_generation_mwh, technology)
        else:
            result = _evaluate_overlay_stream(
                plan, stream, year, status, volume, eligible_generation_mwh)
        results.append(result)

    ordered = sorted(results, key=lambda r: r.stream_id)
    available_subtotal = sum(
        r.stream_revenue_keur for r in ordered if r.stream_revenue_keur is not None
    )
    has_unavailable = any(
        r.status is StreamPeriodStatus.UNAVAILABLE for r in ordered
    )
    total_revenue: float | None = None if has_unavailable else available_subtotal

    unallocated = max(0.0, eligible_generation_mwh - allocated_total)
    # Generation identity guard (float safety, fail loud on a real breach).
    identity_tolerance = _mwh_identity_tolerance(eligible_generation_mwh)
    if abs(allocated_total + unallocated - eligible_generation_mwh) > identity_tolerance:
        raise ValueError(
            "REVENUE_ALLOCATION_IDENTITY_BROKEN: allocated + unallocated != eligible"
        )

    if has_unavailable:
        status = PlanPeriodStatus.HAS_UNAVAILABLE_STREAMS
    elif unallocated > identity_tolerance:
        status = PlanPeriodStatus.PARTIALLY_UNALLOCATED
    else:
        status = PlanPeriodStatus.OK

    return RevenuePlanPeriodResult(
        year=year,
        total_eligible_generation_mwh=eligible_generation_mwh,
        stream_results=tuple(ordered),
        total_revenue_keur=total_revenue,
        available_revenue_subtotal_keur=available_subtotal,
        unallocated_generation_mwh=unallocated,
        status=status,
    )
