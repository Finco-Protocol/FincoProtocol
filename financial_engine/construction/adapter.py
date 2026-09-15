"""financial_engine.construction.adapter — Build ConstructionRuntimeConfig from typed PR-9 inputs.

Bridges ConstructionFinancingInput (typed contract, finco_core) to
ConstructionRuntimeConfig (canonical runtime, finco_core.construction.stage_b2).
No project-name dispatch. No identity-based branches.
"""
from __future__ import annotations

from finco_core._numeric import require_finite_real
from finco_core.construction.stage_b2 import (
    ConstructionRuntimeConfig,
    TimelinePeriod,
    CapexPaymentItem,
    CapexScheduleSet,
    FinancingCostFundingPolicy,
)
from finco_core.inputs.construction_financing import (
    ConstructionFinancingInput,
    ConstructionCapexTimingInput,
)
from finco_core.inputs.senior_rate_schedule import SeniorRateMode, SeniorDayCountConvention


def _compute_interest_fraction(
    start_date: object,
    end_date: object,
    day_count: SeniorDayCountConvention,
    period_index: int,
    explicit_period_fractions: tuple[float, ...],
) -> float:
    """Derive period interest fraction from dates and day-count convention."""
    from datetime import date as _date
    if day_count == SeniorDayCountConvention.EXPLICIT_FRACTIONS:
        return explicit_period_fractions[period_index]
    if not isinstance(start_date, _date) or not isinstance(end_date, _date):
        raise ValueError(f"Day count {day_count.value} requires date objects")
    days = (end_date - start_date).days + 1  # inclusive day count (canonical: same as senior_period_fraction)
    if day_count == SeniorDayCountConvention.ACT_360:
        return days / 360.0
    if day_count == SeniorDayCountConvention.ACT_365:
        return days / 365.0
    if day_count == SeniorDayCountConvention.FIXED_SEMIANNUAL:
        return 0.5
    raise ValueError(f"Unsupported day count: {day_count}")


def build_construction_runtime_config(
    construction: ConstructionFinancingInput,
    senior_commitment_keur: float,
    equity_available_keur: float,
    shl_available_keur: float,
    capex_amounts_keur: dict[str, float] | None = None,
    share_premium_keur: float = 0.0,
    other_committed_equity_keur: float = 0.0,
    additional_equity_keur: float = 0.0,
    junior_keur: float = 0.0,
) -> ConstructionRuntimeConfig:
    """Build a ConstructionRuntimeConfig from typed ConstructionFinancingInput + funding amounts.

    capex_amounts_keur: dict mapping capex_item.code → amount_keur.
    Required when construction.capex_items is non-empty.
    Pass None only when capex_items is empty.
    """
    n = len(construction.periods)
    pricing = construction.senior_pricing
    day_count = pricing.day_count if pricing is not None else SeniorDayCountConvention.ACT_360
    explicit_fracs = pricing.explicit_period_fractions if pricing is not None else ()

    vat = construction.vat_facility
    vat_periods = vat.periods if vat is not None and vat.enabled else ()
    timeline_rows: list[TimelinePeriod] = []
    for i in range(max(n, len(vat_periods))):
        if i < n:
            p = construction.periods[i]
            timeline_rows.append(TimelinePeriod(
                index=i,
                start_date=p.start_date,
                end_date=p.end_date,
                interest_fraction=_compute_interest_fraction(
                    p.start_date, p.end_date, day_count, i, explicit_fracs
                ),
                active_construction=p.active_construction,
                capex_payment_eligible=p.capex_payment_eligible,
                senior_idc_active=p.senior_idc_active,
                vat_facility_active=p.vat_facility_active,
            ))
        else:
            p = vat_periods[i]
            timeline_rows.append(TimelinePeriod(
                index=i,
                start_date=p.start_date,
                end_date=p.end_date,
                interest_fraction=0.0,
                active_construction=False,
                capex_payment_eligible=False,
                senior_idc_active=False,
                vat_facility_active=p.vat_facility_active,
            ))
    timeline = tuple(timeline_rows)

    # Resolve amounts from the canonical CapexStructure-owned lookup. Missing
    # keys are configuration errors; they must never become zero-cost items.
    if construction.capex_items and capex_amounts_keur is None:
        raise ValueError(
            "PR9_CAPEX_AMOUNTS_REQUIRED: capex_amounts_keur is required when capex_items exist"
        )
    resolved_amounts = capex_amounts_keur or {}
    for item in construction.capex_items:
        if item.code not in resolved_amounts:
            raise ValueError(f"PR9_CAPEX_AMOUNT_MISSING: {item.code!r}")
        require_finite_real(
            f"capex_amounts_keur[{item.code!r}]",
            resolved_amounts[item.code],
            minimum=0.0,
            error_code="PR9_INVALID_CAPEX_AMOUNT",
        )
    items = tuple(
        CapexPaymentItem(
            code=item.code,
            name=item.name,
            amount_keur=resolved_amounts[item.code],
            payment_weights=item.payment_weights,
            vat_rate=item.vat_rate,
            provenance_classification=item.provenance_classification,
            vat_classification=item.vat_classification,
        )
        for item in construction.capex_items
    )
    capex_schedule = CapexScheduleSet(items=items)

    # Non-zero structuring fees require explicit timing at the typed boundary.
    # A zero-cost contract uses a first-period neutral schedule because no cash
    # amount is allocated and therefore no economic timing assumption is made.
    if construction.structuring_fee and construction.structuring_fee.payment_weights:
        struct_weights = construction.structuring_fee.payment_weights
    else:
        struct_weights = tuple(1.0 if index == 0 else 0.0 for index in range(n))
    funding_policy = FinancingCostFundingPolicy(structuring_fee_payment_schedule=struct_weights)

    # Build rate parameters from ConstructionSeniorPricingInput
    senior_interest_rate = 0.0
    base_rate = 0.0
    hedge_coverage = 0.0
    swap_margin = 0.0
    forward_swap_margin = 0.0
    cva = 0.0
    external_curve_buffer = 0.0
    euribor_fixings: tuple[float, ...] = ()
    rate_schedule: tuple[float, ...] = ()

    if pricing is not None:
        if pricing.mode == SeniorRateMode.FLAT_ALL_IN:
            senior_interest_rate = pricing.flat_all_in_rate
        elif pricing.mode == SeniorRateMode.FIXED_PLUS_MARGIN:
            senior_interest_rate = pricing.fixed_base_rate + pricing.margin_rate
        elif pricing.mode == SeniorRateMode.FLOATING_PLUS_MARGIN:
            senior_interest_rate = pricing.margin_rate
            euribor_fixings = pricing.floating_base_rate_curve
            external_curve_buffer = pricing.floating_curve_buffer_pct
        elif pricing.mode == SeniorRateMode.HEDGE_BLEND:
            senior_interest_rate = pricing.margin_rate  # margin component
            base_rate = pricing.fixed_base_rate
            hedge_coverage = pricing.hedge_pct
            swap_margin = pricing.swap_margin
            forward_swap_margin = pricing.forward_swap_adjustment
            cva = pricing.cva
            external_curve_buffer = pricing.floating_curve_buffer_pct
            euribor_fixings = pricing.floating_base_rate_curve
        elif pricing.mode == SeniorRateMode.EXPLICIT_ALL_IN_SCHEDULE:
            rate_schedule = pricing.explicit_all_in_schedule

    # Commitment fee
    commitment_fee_rate = 0.0
    commitment_fee_basis = "OPENING_UNDRAWN"
    commitment_fee_timing = "SAME_PERIOD"
    if construction.commitment_fee is not None:
        commitment_fee_rate = construction.commitment_fee.rate
        commitment_fee_basis = construction.commitment_fee.balance_basis
        commitment_fee_timing = construction.commitment_fee.capitalization_timing

    # Structuring fee
    structuring_fee_rate = 0.0
    structuring_fee_basis = 0.0
    structuring_fee_basis_mode = "EXPLICIT_AMOUNT"
    if construction.structuring_fee is not None:
        structuring_fee_rate = construction.structuring_fee.rate
        structuring_fee_basis = construction.structuring_fee.basis_keur
        structuring_fee_basis_mode = construction.structuring_fee.basis_mode.value

    # Map IDC balance basis to stage_b2 constants
    idc_balance_basis = construction.idc_balance_basis
    if idc_balance_basis == "CLOSING_DRAWN":
        idc_balance_basis = "CURRENT_CLOSING_DRAWN"

    # Map commitment fee balance basis
    if commitment_fee_basis == "CLOSING_UNDRAWN":
        commitment_fee_basis = "CURRENT_CLOSING_UNDRAWN"

    vat_interest_fractions: tuple[float, ...] = ()
    vat_financing_weights: tuple[float, ...] = ()
    vat_interest_rate = 0.0
    vat_commitment_fee_rate = 0.0
    vat_commitment = 0.0
    vat_commitment_mode = "DERIVED_PEAK_REQUIREMENT"
    vat_lag = 6
    vat_horizon = 0
    vat_commitment_periods = 0
    if vat is not None and vat.enabled:
        vat_interest_fractions = tuple(
            _compute_interest_fraction(
                period.start_date, period.end_date, vat.day_count, index, ()
            )
            for index, period in enumerate(vat.periods)
        )
        vat_financing_weights = vat.financing_cost_payment_weights
        vat_interest_rate = vat.interest_rate
        vat_commitment_fee_rate = vat.commitment_fee_rate
        vat_commitment_mode = vat.commitment_mode.value
        vat_commitment = vat.fixed_commitment_keur or 0.0
        vat_lag = vat.reimbursement_lag_periods
        vat_horizon = len(vat.periods)
        vat_commitment_periods = vat.commitment_fee_active_periods

    return ConstructionRuntimeConfig(
        timeline=timeline,
        capex_schedule=capex_schedule,
        funding_policy=funding_policy,
        source_total_uses_validation_keur=(),
        equity_available_keur=equity_available_keur,
        share_premium_keur=share_premium_keur,
        other_committed_equity_keur=other_committed_equity_keur,
        additional_equity_keur=additional_equity_keur,
        junior_keur=junior_keur,
        shl_available_keur=shl_available_keur,
        senior_commitment_keur=senior_commitment_keur,
        senior_interest_rate=senior_interest_rate,
        senior_commitment_fee_rate=commitment_fee_rate,
        senior_interest_rate_schedule=rate_schedule,
        base_rate=base_rate,
        hedge_coverage=hedge_coverage,
        swap_margin=swap_margin,
        forward_swap_margin=forward_swap_margin,
        cva=cva,
        external_curve_buffer=external_curve_buffer,
        euribor_1m_fixings=euribor_fixings,
        senior_idc_balance_basis=idc_balance_basis,
        senior_commitment_fee_balance_basis=commitment_fee_basis,
        senior_idc_capitalization_timing=construction.idc_capitalization_timing,
        senior_commitment_fee_capitalization_timing=commitment_fee_timing,
        structuring_fee_rate=structuring_fee_rate,
        structuring_fee_basis_keur=structuring_fee_basis,
        structuring_fee_basis_mode=structuring_fee_basis_mode,
        vat_facility_interest_rate=vat_interest_rate,
        vat_facility_commitment_fee_rate=vat_commitment_fee_rate,
        vat_facility_commitment_keur=vat_commitment,
        vat_facility_commitment_mode=vat_commitment_mode,
        vat_facility_enabled=bool(vat is not None and vat.enabled),
        vat_interest_period_fractions=vat_interest_fractions,
        vat_reimbursement_lag_periods=vat_lag,
        vat_schedule_horizon_periods=vat_horizon,
        vat_commitment_fee_active_periods=vat_commitment_periods,
        vat_financing_cost_spending_profile=vat_financing_weights,
        convergence_tolerance_keur=construction.convergence_tolerance_keur,
        max_iterations=construction.max_iterations,
    )


def resolve_capex_amounts_from_capex_structure(
    capex_items: "tuple[ConstructionCapexTimingInput, ...]",
    capex_structure: object,
) -> dict[str, float]:
    """Build capex_amounts_keur dict by matching item.code to CapexStructure field names.

    capex_structure: CapexStructure instance with field names matching item.code values.
    """
    amounts: dict[str, float] = {}
    missing = object()
    for item in capex_items:
        field_val = getattr(capex_structure, item.code, missing)
        if field_val is missing:
            raise ValueError(f"PR9_CAPEX_AMOUNT_MISSING: {item.code!r}")
        amounts[item.code] = require_finite_real(
            f"capex_structure.{item.code}",
            getattr(field_val, "amount_keur", field_val),
            minimum=0.0,
            error_code="PR9_INVALID_CAPEX_AMOUNT",
        )
    return amounts
