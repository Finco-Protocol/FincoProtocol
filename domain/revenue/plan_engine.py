"""Revenue V2 plan evaluation — volume allocation, stream composition, results.

Period evaluation of a validated ``RevenuePlan``. All price resolution reuses
the existing domain authorities (``PPAParams.price_at_year``,
``MerchantParams.price_at_year`` + capture rates,
``FeedInTariffParams.price_at_year``, ``CfDParams.cfd_payment_at_year``);
this module orchestrates volume allocation and composition and never
re-implements their formulas.

Economic invariants (deterministic, tested):

- Total Revenue = Σ active stream revenues for every period.
- Σ allocated primary generation + unallocated generation
  = eligible generation (within tolerance).
- Overlay streams (CfD, premium) add ONLY their settlement/support payment;
  the underlying market revenue on the settled volume is displayed as a
  component, never counted twice.
- A residual (share=None) merchant stream receives exactly the unallocated
  volume of its group, floor zero.
- INACTIVE / EXPIRED / DISABLED streams contribute nothing but carry their
  typed status; UNAVAILABLE carries revenue=None (never a silent zero).
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

# Generation identity tolerance (MWh).
_ALLOCATION_TOLERANCE_MWH = 1e-9


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
    HAS_UNAVAILABLE_STREAMS = "has_unavailable_streams"


@dataclass(frozen=True)
class RevenueStreamPeriodResult:
    """One stream's typed result for one period."""

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
    underlying_market_revenue_keur: float
    # CfD settlement / premium support payment (kEUR; signed for CfD).
    support_or_settlement_keur: float
    # The stream's economic addition for the period (kEUR); None when
    # unavailable — never a silent zero.
    stream_revenue_keur: float | None


@dataclass(frozen=True)
class RevenuePlanPeriodResult:
    """One period's aggregated plan result."""

    year: int
    total_eligible_generation_mwh: float
    stream_results: tuple[RevenueStreamPeriodResult, ...]  # ordered by stream_id
    total_revenue_keur: float
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


def _stream_volume_mwh(
    stream: RevenueStream,
    eligible_generation_mwh: float,
    explicit_primary_shares: dict[str, float],
) -> float:
    """Contracted volume for this stream/period.

    Primary residual merchant: eligible − Σ explicit primary shares, floor 0.
    Primary explicit share: eligible × share.
    Overlay: eligible × share (contractual settlement volume; consumes no
    allocation capacity).
    """
    if stream.contract_role is ContractRole.PRIMARY_ALLOCATION:
        if stream.volume_share is None:
            explicit = explicit_primary_shares.get(stream.allocation_group, 0.0)
            return max(0.0, eligible_generation_mwh - explicit * eligible_generation_mwh)
        return max(0.0, eligible_generation_mwh * float(stream.volume_share))
    # Overlay
    return max(0.0, eligible_generation_mwh * float(stream.volume_share or 0.0))


def _period_status(stream: RevenueStream, year: int) -> StreamPeriodStatus:
    if not stream.enabled:
        return StreamPeriodStatus.DISABLED
    if year < stream.start_year:
        return StreamPeriodStatus.NOT_STARTED
    if stream.term_years is not None and year > stream.start_year + stream.term_years - 1:
        return StreamPeriodStatus.EXPIRED
    return StreamPeriodStatus.ACTIVE


def _evaluate_primary_stream(
    stream: RevenueStream,
    year: int,
    status: StreamPeriodStatus,
    volume_mwh: float,
    technology: str,
) -> RevenueStreamPeriodResult:
    if status is not StreamPeriodStatus.ACTIVE:
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
            stream_revenue_keur=None if status is StreamPeriodStatus.UNAVAILABLE else 0.0,
        )

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
            eligible_generation_mwh=volume_mwh,  # refined by caller
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
            eligible_generation_mwh=volume_mwh,  # refined by caller
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
            eligible_generation_mwh=volume_mwh,  # refined by caller
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
            return RevenueStreamPeriodResult(
                stream_id=stream.stream_id,
                stream_type=stream.stream_type,
                contract_role=stream.contract_role,
                year=year,
                status=StreamPeriodStatus.UNAVAILABLE,
                allocated_generation_mwh=volume_mwh,
                eligible_generation_mwh=volume_mwh,  # refined by caller
                price_eur_mwh=None,
                underlying_market_revenue_keur=0.0,
                support_or_settlement_keur=0.0,
                stream_revenue_keur=None,
            )
        price = stream.indexed_fit_base_tariff_eur_mwh * stream.indexed_fit_index_factors[idx]
        revenue_keur = volume_mwh * price / 1000.0
        return RevenueStreamPeriodResult(
            stream_id=stream.stream_id,
            stream_type=stream.stream_type,
            contract_role=stream.contract_role,
            year=year,
            status=status,
            allocated_generation_mwh=volume_mwh,
            eligible_generation_mwh=volume_mwh,  # refined by caller
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
) -> RevenueStreamPeriodResult:
    if status is not StreamPeriodStatus.ACTIVE:
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
            stream_revenue_keur=None if status is StreamPeriodStatus.UNAVAILABLE else 0.0,
        )

    reference = _reference_price_eur_mwh(plan, stream, year)
    if reference is None:
        return RevenueStreamPeriodResult(
            stream_id=stream.stream_id,
            stream_type=stream.stream_type,
            contract_role=stream.contract_role,
            year=year,
            status=StreamPeriodStatus.UNAVAILABLE,
            allocated_generation_mwh=volume_mwh,
            eligible_generation_mwh=volume_mwh,  # refined by caller
            price_eur_mwh=None,
            underlying_market_revenue_keur=0.0,
            support_or_settlement_keur=0.0,
            stream_revenue_keur=None,
        )

    if stream.stream_type is RevenueStreamType.CFD:
        # Reuse the existing CfD settlement formula authority: derive a
        # CfDParams carrying THIS period's contractual volume and call the
        # existing two-way/one-way payment math unchanged.
        period_cfd = CfDParams(
            cfd_enabled=True,
            strike_price_eur_mwh=stream.cfd.strike_price_eur_mwh,
            reference_price_type=stream.cfd.reference_price_type,
            cfd_term_years=stream.cfd.cfd_term_years,
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
            eligible_generation_mwh=volume_mwh,  # refined by caller
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
            eligible_generation_mwh=volume_mwh,  # refined by caller
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

    ``year`` is the 1-based model year used by the existing domain revenue
    math; ``eligible_generation_mwh`` is the group generation for the year.
    Re-validates the plan (fail closed) before any arithmetic.
    """
    plan.validate()
    if not math.isfinite(eligible_generation_mwh) or eligible_generation_mwh < 0.0:
        raise ValueError(
            f"REVENUE_PLAN_ELIGIBLE_GENERATION_INVALID: {eligible_generation_mwh!r}"
        )

    # Explicit primary shares per group (enabled streams only) — the residual
    # merchant and the unallocated volume both derive from this sum, so the
    # result is independent of stream declaration order.
    explicit_primary_shares: dict[str, float] = {}
    for stream in plan.streams:
        if (
            stream.contract_role is ContractRole.PRIMARY_ALLOCATION
            and stream.enabled
            and stream.volume_share is not None
        ):
            explicit_primary_shares[stream.allocation_group] = (
                explicit_primary_shares.get(stream.allocation_group, 0.0)
                + float(stream.volume_share)
            )

    results: list[RevenueStreamPeriodResult] = []
    allocated_by_group: dict[str, float] = {}
    eligible_by_group: dict[str, float] = {}
    for stream in plan.streams:
        status = _period_status(stream, year)
        volume = _stream_volume_mwh(
            stream, eligible_generation_mwh, explicit_primary_shares
        )
        if stream.contract_role is ContractRole.PRIMARY_ALLOCATION:
            if status is StreamPeriodStatus.ACTIVE:
                allocated_by_group[stream.allocation_group] = (
                    allocated_by_group.get(stream.allocation_group, 0.0) + volume
                )
            eligible_by_group.setdefault(stream.allocation_group, eligible_generation_mwh)
            result = _evaluate_primary_stream(stream, year, status, volume, technology)
        else:
            eligible_by_group.setdefault(stream.allocation_group, eligible_generation_mwh)
            result = _evaluate_overlay_stream(plan, stream, year, status, volume)

        # Fill the group-eligible context on active results.
        if status is StreamPeriodStatus.ACTIVE:
            group_eligible = eligible_by_group.get(stream.allocation_group, eligible_generation_mwh)
            result = RevenueStreamPeriodResult(
                stream_id=result.stream_id,
                stream_type=result.stream_type,
                contract_role=result.contract_role,
                year=result.year,
                status=result.status,
                allocated_generation_mwh=result.allocated_generation_mwh,
                eligible_generation_mwh=group_eligible,
                price_eur_mwh=result.price_eur_mwh,
                underlying_market_revenue_keur=result.underlying_market_revenue_keur,
                support_or_settlement_keur=result.support_or_settlement_keur,
                stream_revenue_keur=result.stream_revenue_keur,
            )
        results.append(result)

    ordered = sorted(results, key=lambda r: r.stream_id)
    total_revenue = sum(
        r.stream_revenue_keur for r in ordered if r.stream_revenue_keur is not None
    )
    total_allocated = sum(allocated_by_group.values())
    unallocated = max(0.0, eligible_generation_mwh - total_allocated)
    # Generation identity guard (float safety, fail loud on a real breach).
    if abs(total_allocated + unallocated - eligible_generation_mwh) > _ALLOCATION_TOLERANCE_MWH:
        raise ValueError(
            "REVENUE_ALLOCATION_IDENTITY_BROKEN: allocated + unallocated != eligible"
        )

    if any(r.status is StreamPeriodStatus.UNAVAILABLE for r in ordered):
        status = PlanPeriodStatus.HAS_UNAVAILABLE_STREAMS
    elif unallocated > _ALLOCATION_TOLERANCE_MWH:
        status = PlanPeriodStatus.PARTIALLY_UNALLOCATED
    else:
        status = PlanPeriodStatus.OK

    return RevenuePlanPeriodResult(
        year=year,
        total_eligible_generation_mwh=eligible_generation_mwh,
        stream_results=tuple(ordered),
        total_revenue_keur=total_revenue,
        unallocated_generation_mwh=unallocated,
        status=status,
    )
