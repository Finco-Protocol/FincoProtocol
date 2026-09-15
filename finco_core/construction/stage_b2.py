"""Canonical Stage B2 construction runtime.

This module owns calculation mechanics for construction source-parity runs. Source
modules may provide workbook constants and config builders, but tests and parity
reports must call :func:`run_stage_b2` for financial outputs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from finco_core._numeric import require_bool, require_finite_real, require_positive_int
from finco_core.construction.allocator import ConstructionPeriodAllocation


class FundingShortfallError(ValueError):
    """Raised when a configured construction facility is too small for required draws."""


@dataclass(frozen=True)
class TimelinePeriod:
    index: int
    start_date: date
    end_date: date
    interest_fraction: float
    active_construction: bool
    capex_payment_eligible: bool
    senior_idc_active: bool
    vat_facility_active: bool


@dataclass(frozen=True)
class CapexPaymentItem:
    code: str
    name: str
    amount_keur: float
    payment_weights: tuple[float, ...]
    vat_rate: float = 0.0
    provenance_classification: str = "DIRECT_SOURCE"
    vat_classification: str = "DIRECT_SOURCE"


@dataclass(frozen=True)
class CapexScheduleSet:
    items: tuple[CapexPaymentItem, ...]


@dataclass(frozen=True)
class FinancingCostFundingPolicy:
    structuring_fee_payment_schedule: tuple[float, ...]


@dataclass(frozen=True)
class VectorResidualAudit:
    component: str
    total_value_keur: float
    vector_residual_keur: float
    max_period_delta_keur: float
    max_period_index: int


@dataclass(frozen=True)
class FacilityPeriodState:
    period: int
    vat_payable_keur: float = 0.0
    vat_reimbursement_keur: float = 0.0
    vat_requirement_keur: float = 0.0
    vat_drawn_keur: float = 0.0
    vat_undrawn_keur: float = 0.0
    vat_idc_keur: float = 0.0
    vat_commitment_fee_keur: float = 0.0


@dataclass(frozen=True)
class CapitalizedFinancingCosts:
    senior_idc_keur: float
    senior_commitment_fee_keur: float
    structuring_fee_keur: float
    vat_idc_keur: float
    vat_commitment_fee_keur: float

    @property
    def total_keur(self) -> float:
        return (
            self.senior_idc_keur
            + self.senior_commitment_fee_keur
            + self.structuring_fee_keur
            + self.vat_idc_keur
            + self.vat_commitment_fee_keur
        )


@dataclass(frozen=True)
class ConstructionRuntimeConfig:
    timeline: tuple[TimelinePeriod, ...]
    capex_schedule: CapexScheduleSet
    funding_policy: FinancingCostFundingPolicy
    source_total_uses_validation_keur: tuple[float, ...]
    equity_available_keur: float  # share_capital (backward-compat field; see also share_premium_keur etc.)
    shl_available_keur: float
    senior_commitment_keur: float
    # Full source breakdown (Section 4 canonical allocator inputs).
    # When non-zero, these replace the aggregated equity_available_keur in allocator calls.
    share_premium_keur: float = 0.0
    other_committed_equity_keur: float = 0.0
    additional_equity_keur: float = 0.0
    junior_keur: float = 0.0
    senior_interest_rate: float = 0.0
    senior_commitment_fee_rate: float = 0.0
    senior_interest_rate_schedule: tuple[float, ...] = field(default_factory=tuple)
    base_rate: float = 0.0
    hedge_coverage: float = 0.0
    swap_margin: float = 0.0
    forward_swap_margin: float = 0.0
    cva: float = 0.0
    external_curve_buffer: float = 0.0
    euribor_1m_fixings: tuple[float, ...] = field(default_factory=tuple)
    senior_idc_balance_basis: str = "OPENING_DRAWN"
    senior_commitment_fee_balance_basis: str = "OPENING_UNDRAWN"
    senior_idc_capitalization_timing: str = "PROFILE"
    senior_commitment_fee_capitalization_timing: str = "PROFILE"
    structuring_fee_rate: float = 0.0
    structuring_fee_basis_keur: float = 0.0
    structuring_fee_basis_mode: str = "EXPLICIT_AMOUNT"
    vat_facility_interest_rate: float = 0.0
    vat_facility_commitment_fee_rate: float = 0.0
    vat_facility_commitment_keur: float = 0.0
    vat_facility_commitment_mode: str = "FIXED_COMMITMENT"
    vat_facility_enabled: bool = True  # low-level compatibility; typed adapter is explicit
    vat_interest_period_fractions: tuple[float, ...] = field(default_factory=tuple)
    vat_reimbursement_lag_periods: int = 6
    vat_schedule_horizon_periods: int = 0
    vat_commitment_fee_active_periods: int = 12
    senior_idc_spending_profile: tuple[float, ...] = field(default_factory=tuple)
    senior_commitment_fee_spending_profile: tuple[float, ...] = field(default_factory=tuple)
    vat_financing_cost_spending_profile: tuple[float, ...] = field(default_factory=tuple)
    initial_senior_idc_funded_uses_keur: tuple[float, ...] = field(default_factory=tuple)
    initial_senior_commitment_fee_funded_uses_keur: tuple[float, ...] = field(default_factory=tuple)
    initial_vat_financing_funded_uses_keur: tuple[float, ...] = field(default_factory=tuple)
    convergence_tolerance_keur: float = 1e-9
    max_iterations: int = 100


@dataclass(frozen=True)
class ConstructionRuntimeResult:
    config: ConstructionRuntimeConfig
    monthly_hard_capex_keur: tuple[float, ...]
    vat_payable_keur: tuple[float, ...]
    vat_schedule: tuple[FacilityPeriodState, ...]
    senior_idc_accrual_keur: tuple[float, ...]
    senior_idc_capitalized_uses_keur: tuple[float, ...]
    senior_commitment_fee_accrual_keur: tuple[float, ...]
    cumulative_senior_draw_keur: tuple[float, ...]
    senior_period_draw_keur: tuple[float, ...]
    total_permanent_uses_keur: tuple[float, ...]
    capitalized_financing_costs: CapitalizedFinancingCosts
    final_gfa_keur: float
    closing_senior_drawn_keur: float
    closing_senior_undrawn_keur: float
    iterations: int
    final_residual_keur: float
    residual_audit: tuple[VectorResidualAudit, ...]
    canonical_allocations: tuple[ConstructionPeriodAllocation, ...]


@dataclass(frozen=True)
class ProvisionalStageB2Result:
    """Provisional Stage B2 result for outer-loop intermediate iterations.

    NOT FINAL: unfunded_uses_keur may be > 0 when Senior is not yet fully
    sized (outer-state-lag Classification B). This result MUST NOT be returned
    to a normal production caller as a ConstructionRuntimeResult.

    unfunded_uses_keur:
    - is diagnostic state only
    - does NOT increase Senior, SHL, or any other source
    - does NOT earn Senior IDC
    - does NOT affect commitment-fee basis
    - must be >= 0 and finite

    The outer G2A fixed point must drive unfunded_uses_keur to zero at final
    convergence, then call strict run_stage_b2() for the ConstructionRuntimeResult.
    """
    authority: str  # "PR9_STAGE_B2_PROVISIONAL_OUTER_LOOP_INTERMEDIATE"
    provisional_senior_period_draw_keur: tuple[float, ...]
    actual_senior_commitment_keur: float
    total_provisional_funded_sources_keur: float
    total_construction_uses_keur: float
    unfunded_uses_keur: float  # >= 0; diagnostic; NOT a funding source
    capitalized_financing_costs: CapitalizedFinancingCosts
    iterations: int
    final_residual_keur: float
    canonical_allocations: tuple[ConstructionPeriodAllocation, ...]


def _validate_runtime_config(config: ConstructionRuntimeConfig) -> None:
    """Fail closed on invalid direct Stage-B2 numerical ingress."""
    error = "STAGE_B2_INVALID_NUMERIC"
    require_finite_real(
        "convergence_tolerance_keur",
        config.convergence_tolerance_keur,
        minimum=0.0,
        strictly_greater=True,
        error_code=error,
    )
    require_positive_int("max_iterations", config.max_iterations, error_code=error)
    require_bool(
        "vat_facility_enabled", config.vat_facility_enabled, error_code=error
    )
    if config.vat_facility_commitment_mode not in {
        "DERIVED_PEAK_REQUIREMENT",
        "FIXED_COMMITMENT",
    }:
        raise ValueError("STAGE_B2_INVALID_VAT_COMMITMENT_MODE")
    if config.structuring_fee_basis_mode not in {
        "EXPLICIT_AMOUNT",
        "SENIOR_PLUS_VAT_COMMITMENTS",
    }:
        raise ValueError("STAGE_B2_INVALID_STRUCTURING_FEE_BASIS_MODE")

    non_negative_scalars = {
        "equity_available_keur": config.equity_available_keur,
        "share_premium_keur": config.share_premium_keur,
        "other_committed_equity_keur": config.other_committed_equity_keur,
        "additional_equity_keur": config.additional_equity_keur,
        "junior_keur": config.junior_keur,
        "shl_available_keur": config.shl_available_keur,
        "senior_commitment_keur": config.senior_commitment_keur,
        "senior_commitment_fee_rate": config.senior_commitment_fee_rate,
        "structuring_fee_rate": config.structuring_fee_rate,
        "structuring_fee_basis_keur": config.structuring_fee_basis_keur,
        "vat_facility_interest_rate": config.vat_facility_interest_rate,
        "vat_facility_commitment_fee_rate": config.vat_facility_commitment_fee_rate,
        "vat_facility_commitment_keur": config.vat_facility_commitment_keur,
    }
    for name, value in non_negative_scalars.items():
        require_finite_real(name, value, minimum=0.0, error_code=error)

    signed_rate_components = {
        "senior_interest_rate": config.senior_interest_rate,
        "base_rate": config.base_rate,
        "swap_margin": config.swap_margin,
        "forward_swap_margin": config.forward_swap_margin,
        "cva": config.cva,
        "external_curve_buffer": config.external_curve_buffer,
    }
    for name, value in signed_rate_components.items():
        require_finite_real(name, value, error_code=error)
    hedge = require_finite_real(
        "hedge_coverage", config.hedge_coverage, error_code=error
    )
    if not 0.0 <= hedge <= 1.0:
        raise ValueError(
            f"{error}: hedge_coverage must be in [0, 1], got {config.hedge_coverage!r}"
        )

    for name in (
        "vat_reimbursement_lag_periods",
        "vat_schedule_horizon_periods",
        "vat_commitment_fee_active_periods",
    ):
        value = getattr(config, name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{error}: {name} must be a non-negative int")

    for index, period in enumerate(config.timeline):
        if not isinstance(period.index, int) or isinstance(period.index, bool):
            raise ValueError(f"{error}: timeline[{index}].index must be int")
        if not isinstance(period.start_date, date) or not isinstance(period.end_date, date):
            raise ValueError(f"{error}: timeline[{index}] dates must be date")
        # The canonical Stage B2 timeline may contain zero-length runoff audit
        # periods after construction. Typed construction inputs remain stricter.
        if period.end_date < period.start_date:
            raise ValueError(
                f"{error}: timeline[{index}] end_date must not precede start_date"
            )
        require_finite_real(
            f"timeline[{index}].interest_fraction",
            period.interest_fraction,
            minimum=0.0,
            error_code=error,
        )
        for flag in (
            "active_construction",
            "capex_payment_eligible",
            "senior_idc_active",
            "vat_facility_active",
        ):
            require_bool(
                f"timeline[{index}].{flag}", getattr(period, flag), error_code=error
            )

    for item_index, item in enumerate(config.capex_schedule.items):
        require_finite_real(
            f"capex_schedule.items[{item_index}].amount_keur",
            item.amount_keur,
            minimum=0.0,
            error_code=error,
        )
        require_finite_real(
            f"capex_schedule.items[{item_index}].vat_rate",
            item.vat_rate,
            minimum=0.0,
            error_code=error,
        )
        for weight_index, weight in enumerate(item.payment_weights):
            require_finite_real(
                f"capex_schedule.items[{item_index}].payment_weights[{weight_index}]",
                weight,
                minimum=0.0,
                error_code=error,
            )

    non_negative_vectors = {
        "source_total_uses_validation_keur": config.source_total_uses_validation_keur,
        "senior_interest_rate_schedule": config.senior_interest_rate_schedule,
        "vat_interest_period_fractions": config.vat_interest_period_fractions,
        "senior_idc_spending_profile": config.senior_idc_spending_profile,
        "senior_commitment_fee_spending_profile": config.senior_commitment_fee_spending_profile,
        "vat_financing_cost_spending_profile": config.vat_financing_cost_spending_profile,
        "initial_senior_idc_funded_uses_keur": config.initial_senior_idc_funded_uses_keur,
        "initial_senior_commitment_fee_funded_uses_keur": config.initial_senior_commitment_fee_funded_uses_keur,
        "initial_vat_financing_funded_uses_keur": config.initial_vat_financing_funded_uses_keur,
        "structuring_fee_payment_schedule": config.funding_policy.structuring_fee_payment_schedule,
    }
    for name, values in non_negative_vectors.items():
        for index, value in enumerate(values):
            require_finite_real(
                f"{name}[{index}]", value, minimum=0.0, error_code=error
            )
    for index, value in enumerate(config.euribor_1m_fixings):
        require_finite_real(
            f"euribor_1m_fixings[{index}]", value, error_code=error
        )

    if config.senior_idc_balance_basis not in {
        "OPENING_DRAWN",
        "CURRENT_CLOSING_DRAWN",
        "FUNDING_PERIOD_CLOSING_DRAWN",
    }:
        raise ValueError(f"STAGE_B2_INVALID_IDC_BALANCE_BASIS: {config.senior_idc_balance_basis!r}")
    if config.senior_commitment_fee_balance_basis not in {
        "OPENING_UNDRAWN",
        "CURRENT_CLOSING_UNDRAWN",
        "FUNDING_PERIOD_CLOSING_UNDRAWN",
    }:
        raise ValueError(
            "STAGE_B2_INVALID_COMMITMENT_FEE_BALANCE_BASIS: "
            f"{config.senior_commitment_fee_balance_basis!r}"
        )
    allowed_timings = {"SAME_PERIOD", "NEXT_PERIOD", "NEXT_FUNDING_PERIOD", "PROFILE"}
    if config.senior_idc_capitalization_timing not in allowed_timings:
        raise ValueError(
            f"STAGE_B2_INVALID_IDC_CAPITALIZATION_TIMING: {config.senior_idc_capitalization_timing!r}"
        )
    if config.senior_commitment_fee_capitalization_timing not in allowed_timings:
        raise ValueError(
            "STAGE_B2_INVALID_COMMITMENT_FEE_CAPITALIZATION_TIMING: "
            f"{config.senior_commitment_fee_capitalization_timing!r}"
        )


def _n_from_schedule(capex_schedule: CapexScheduleSet) -> int:
    """Derive construction period count from the first CAPEX item's payment_weights."""
    if not capex_schedule.items:
        return 0
    return len(capex_schedule.items[0].payment_weights)


def _monthly_uses(item: CapexPaymentItem, n_periods: int | None = None) -> tuple[float, ...]:
    n = len(item.payment_weights) if n_periods is None else n_periods
    if len(item.payment_weights) != n:
        raise ValueError(
            f"{item.code} must have {n} construction payment weights, got {len(item.payment_weights)}"
        )
    expected_sum = 1.0 if item.amount_keur else 0.0
    if abs(sum(item.payment_weights) - expected_sum) > 1e-9:
        raise ValueError(f"{item.code} payment weights do not sum to 100%")
    return tuple(item.amount_keur * weight for weight in item.payment_weights)


def monthly_hard_capex(capex_schedule: CapexScheduleSet) -> tuple[float, ...]:
    n = _n_from_schedule(capex_schedule)
    if n == 0:
        return ()
    return tuple(sum(_monthly_uses(item, n)[idx] for item in capex_schedule.items) for idx in range(n))


def vat_monthly_uses(capex_schedule: CapexScheduleSet) -> tuple[float, ...]:
    n = _n_from_schedule(capex_schedule)
    if n == 0:
        return ()
    return tuple(
        sum(_monthly_uses(item, n)[idx] * item.vat_rate for item in capex_schedule.items)
        for idx in range(n)
    )


def total_hard_capex(capex_schedule: CapexScheduleSet) -> float:
    return sum(item.amount_keur for item in capex_schedule.items)


def vat_bearing_base(capex_schedule: CapexScheduleSet) -> float:
    return sum(item.amount_keur for item in capex_schedule.items if item.vat_rate)


def allocate_structuring_fee(policy: FinancingCostFundingPolicy, amount_keur: float) -> tuple[float, ...]:
    schedule = policy.structuring_fee_payment_schedule
    if not schedule:
        raise ValueError("structuring fee payment schedule must not be empty")
    if abs(sum(schedule) - 1.0) > 1e-9:
        raise ValueError("structuring fee payment schedule must sum to 100%")
    return tuple(amount_keur * weight for weight in schedule)


def convergence_audit(new_vectors: dict[str, tuple[float, ...]], previous_vectors: dict[str, tuple[float, ...]]) -> tuple[float, tuple[VectorResidualAudit, ...]]:
    """Return fixed-point residual as sum of absolute period-vector deltas."""
    audits: list[VectorResidualAudit] = []
    final_residual = 0.0
    for component, new in new_vectors.items():
        prev = previous_vectors.get(component, (0.0,) * len(new))
        if len(prev) != len(new):
            raise ValueError(f"{component} vector length changed")
        deltas = [abs(a - b) for a, b in zip(new, prev)]
        residual = sum(deltas)
        max_delta = max(deltas) if deltas else 0.0
        max_index = deltas.index(max_delta) + 1 if deltas else 0
        final_residual += residual
        audits.append(VectorResidualAudit(component, sum(new), residual, max_delta, max_index))
    return final_residual, tuple(audits)


def compute_vat_schedule(
    vat_payable_keur: tuple[float, ...],
    reimbursement_lag_periods: int = 6,
    *,
    vat_facility_commitment_keur: float | None = None,
    tolerance_keur: float = 1e-9,
    horizon_periods: int | None = None,
) -> tuple[FacilityPeriodState, ...]:
    """Compute generic VAT schedule with a post-CAPEX reimbursement/runoff tail."""
    natural_horizon = len(vat_payable_keur) + reimbursement_lag_periods
    horizon = natural_horizon if horizon_periods is None else horizon_periods
    if horizon < len(vat_payable_keur):
        raise ValueError("VAT schedule horizon cannot be shorter than payable vector")
    requirement = 0.0
    raw_rows: list[tuple[int, float, float, float]] = []
    peak_requirement = 0.0
    for idx in range(horizon):
        payable = vat_payable_keur[idx] if idx < len(vat_payable_keur) else 0.0
        reimbursement_index = idx - reimbursement_lag_periods
        reimbursement = (
            vat_payable_keur[reimbursement_index]
            if 0 <= reimbursement_index < len(vat_payable_keur)
            else 0.0
        )
        requirement = max(0.0, requirement + payable - reimbursement)
        peak_requirement = max(peak_requirement, requirement)
        raw_rows.append((idx + 1, payable, reimbursement, requirement))

    commitment = peak_requirement if vat_facility_commitment_keur is None else vat_facility_commitment_keur
    if commitment < -tolerance_keur:
        raise ValueError("VAT facility commitment cannot be negative")
    if peak_requirement > commitment + tolerance_keur:
        raise FundingShortfallError(
            "VAT facility commitment breached: "
            f"peak requirement {peak_requirement:.12f} kEUR exceeds commitment {commitment:.12f} kEUR"
        )

    rows: list[FacilityPeriodState] = []
    for period, payable, reimbursement, requirement in raw_rows:
        rows.append(
            FacilityPeriodState(
                period=period,
                vat_payable_keur=payable,
                vat_reimbursement_keur=reimbursement,
                vat_requirement_keur=requirement,
                vat_drawn_keur=requirement,
                vat_undrawn_keur=max(0.0, commitment - requirement),
            )
        )
    return tuple(rows)


def _pad_n(values: tuple[float, ...], n: int) -> tuple[float, ...]:
    if not values:
        return (0.0,) * n
    if len(values) != n:
        raise ValueError(f"circular vectors must have {n} periods, got {len(values)}")
    return values


def _pad_12(values: tuple[float, ...]) -> tuple[float, ...]:
    return _pad_n(values, 12)


def _profile_n(values: tuple[float, ...], n: int, *, default_period: int | None = None) -> tuple[float, ...]:
    if not values:
        if default_period is None:
            return (0.0,) * n
        return tuple(1.0 if idx == default_period else 0.0 for idx in range(n))
    if len(values) != n:
        raise ValueError(f"financing-cost spending profiles must have {n} periods, got {len(values)}")
    if abs(sum(values) - 1.0) > 1e-9:
        raise ValueError("financing-cost spending profiles must sum to 100%")
    return values


def _profile_12(values: tuple[float, ...], *, default_period: int | None = None) -> tuple[float, ...]:
    return _profile_n(values, 12, default_period=default_period)


def _period_rates(config: ConstructionRuntimeConfig, n_periods: int = 12) -> tuple[float, ...]:
    if config.euribor_1m_fixings:
        if len(config.euribor_1m_fixings) != n_periods:
            raise ValueError(f"Euribor 1m fixing schedule must have {n_periods} periods")
        hedged_component = (
            config.base_rate * config.hedge_coverage
            + config.swap_margin
            + config.forward_swap_margin
            + config.cva
        )
        floating_weight = (1.0 - config.hedge_coverage) * (1.0 + config.external_curve_buffer)
        rates = tuple(
            hedged_component + fixing * floating_weight + config.senior_interest_rate
            for fixing in config.euribor_1m_fixings
        )
    elif config.senior_interest_rate_schedule:
        if len(config.senior_interest_rate_schedule) != n_periods:
            raise ValueError(f"Senior interest-rate schedule must have {n_periods} periods")
        rates = config.senior_interest_rate_schedule
    else:
        rates = (config.senior_interest_rate,) * n_periods
    for index, rate in enumerate(rates):
        resolved_rate = require_finite_real(
            f"senior all-in rate[{index}]",
            rate,
            error_code="STAGE_B2_INVALID_ALL_IN_RATE",
        )
        if resolved_rate < 0.0:
            raise ValueError(
                f"STAGE_B2_NEGATIVE_ALL_IN_RATE: senior rate[{index}]={rate!r} must be >= 0"
            )
    return rates


def _senior_financing_accruals(
    config: ConstructionRuntimeConfig,
    senior_period_draws: tuple[float, ...],
    senior_rates: tuple[float, ...],
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    idc_calc: list[float] = []
    fee_calc: list[float] = []
    opening_senior = 0.0
    for idx, draw in enumerate(senior_period_draws):
        closing_senior = opening_senior + draw
        if config.senior_idc_balance_basis in {"CURRENT_CLOSING_DRAWN", "FUNDING_PERIOD_CLOSING_DRAWN"}:
            idc_basis = closing_senior
        elif config.senior_idc_balance_basis == "OPENING_DRAWN":
            idc_basis = opening_senior
        else:
            raise ValueError(f"Unsupported Senior IDC balance basis: {config.senior_idc_balance_basis}")

        if config.senior_commitment_fee_balance_basis in {"CURRENT_CLOSING_UNDRAWN", "FUNDING_PERIOD_CLOSING_UNDRAWN"}:
            fee_drawn_basis = closing_senior
        elif config.senior_commitment_fee_balance_basis == "OPENING_UNDRAWN":
            fee_drawn_basis = opening_senior
        else:
            raise ValueError(
                f"Unsupported Senior commitment-fee balance basis: {config.senior_commitment_fee_balance_basis}"
            )
        fee_undrawn_basis = max(0.0, config.senior_commitment_keur - fee_drawn_basis)
        fraction = config.timeline[idx].interest_fraction
        if config.timeline[idx].senior_idc_active:
            idc_calc.append(idc_basis * senior_rates[idx] * fraction)
            fee_calc.append(fee_undrawn_basis * config.senior_commitment_fee_rate * fraction)
        else:
            idc_calc.append(0.0)
            fee_calc.append(0.0)
        opening_senior = closing_senior
    return tuple(idc_calc), tuple(fee_calc)


def _next_period_capitalized_uses(calculated: tuple[float, ...]) -> tuple[float, ...]:
    n = len(calculated)
    if n == 0:
        return ()
    return (0.0,) + calculated[: n - 1]


def _capitalized_uses(total: float, profile: tuple[float, ...], calculated: tuple[float, ...], timing: str) -> tuple[float, ...]:
    if timing in {"NEXT_PERIOD", "NEXT_FUNDING_PERIOD"}:
        return _next_period_capitalized_uses(calculated)
    if timing == "PROFILE":
        return tuple(total * weight for weight in profile)
    if timing == "SAME_PERIOD":
        return calculated
    raise ValueError(f"Unsupported capitalization timing: {timing}")


def _vat_fractions(config: ConstructionRuntimeConfig, horizon: int) -> tuple[float, ...]:
    if config.vat_interest_period_fractions:
        if len(config.vat_interest_period_fractions) != horizon:
            raise ValueError("VAT interest-period fraction vector must match VAT horizon")
        return config.vat_interest_period_fractions
    return tuple((config.timeline[idx].interest_fraction if idx < len(config.timeline) else 30 / 360) for idx in range(horizon))


def _validate_capex_timeline(
    hard_capex: tuple[float, ...],
    vat_payable: tuple[float, ...],
    timeline: tuple[TimelinePeriod, ...],
    tolerance_keur: float,
) -> None:
    if len(timeline) == 0:
        raise ValueError("construction timeline must not be empty")
    n_capex = len(hard_capex)
    if len(vat_payable) != n_capex:
        raise ValueError(
            f"CAPEX and VAT vectors must have the same length: "
            f"CAPEX={n_capex}, VAT={len(vat_payable)}"
        )
    if n_capex > len(timeline):
        raise ValueError(
            f"CAPEX period count ({n_capex}) exceeds timeline length ({len(timeline)})"
        )

    for idx, (hard, vat) in enumerate(zip(hard_capex, vat_payable)):
        period = timeline[idx]
        if hard <= tolerance_keur and vat <= tolerance_keur:
            continue

        inactive = not period.active_construction
        ineligible = not period.capex_payment_eligible
        if not inactive and not ineligible:
            continue

        reason = "inactive construction" if inactive else "ineligible CAPEX payment"
        if vat > tolerance_keur:
            raise ValueError(
                "VAT-generating CAPEX scheduled in "
                f"{reason} period {idx + 1}: VAT payable {vat:.12f} kEUR; "
                f"hard CAPEX {hard:.12f} kEUR"
            )
        raise ValueError(
            f"CAPEX scheduled in {reason} period {idx + 1}: "
            f"{hard:.12f} kEUR"
        )


def _validate_vat_facility_active(
    vat_schedule: tuple[FacilityPeriodState, ...],
    timeline: tuple[TimelinePeriod, ...],
    tolerance_keur: float,
) -> None:
    for idx, row in enumerate(vat_schedule):
        active = timeline[idx].vat_facility_active if idx < len(timeline) else False
        if not active and row.vat_requirement_keur > tolerance_keur:
            raise FundingShortfallError(
                "VAT facility inactive while VAT funding is required: "
                f"period {row.period}, requirement {row.vat_requirement_keur:.12f} kEUR"
            )


def _waterfall_senior_draws(
    period_uses: tuple[float, ...],
    equity: float,
    shl: float,
    senior_commitment_keur: float,
    tolerance_keur: float,
) -> tuple[float, ...]:
    remaining_equity = equity
    remaining_shl = shl
    cumulative_senior = 0.0
    senior_draws: list[float] = []
    for idx, uses in enumerate(period_uses):
        equity_draw = min(remaining_equity, uses)
        remaining_equity -= equity_draw
        after_equity = uses - equity_draw
        shl_draw = min(remaining_shl, after_equity)
        remaining_shl -= shl_draw
        senior_required = after_equity - shl_draw
        if cumulative_senior + senior_required > senior_commitment_keur + tolerance_keur:
            shortfall = cumulative_senior + senior_required - senior_commitment_keur
            raise FundingShortfallError(
                "Senior facility commitment breached: "
                f"period {idx + 1}, required cumulative senior "
                f"{cumulative_senior + senior_required:.12f} kEUR exceeds commitment "
                f"{senior_commitment_keur:.12f} kEUR by {shortfall:.12f} kEUR"
            )
        cumulative_senior += senior_required
        senior_draws.append(senior_required)
    return tuple(senior_draws)


def _run_stage_b2_inner(
    config: ConstructionRuntimeConfig,
    provisional: bool,
) -> tuple:
    """Shared inner computation for both strict and provisional Stage B2.

    Returns a tuple of all intermediate and final values needed by the
    two public entry points. The `provisional` flag controls whether
    the allocator raises on shortfall (False = strict) or returns
    unfunded residual (True = provisional).

    PR9_CANONICAL_LAYER_A_ALLOCATOR_SINGLE_AUTHORITY: both paths use
    allocate_construction_sources_provisional (core) for IDC iteration,
    then the strict path does a final allocate_construction_sources_per_period.
    """
    from finco_core.construction.allocator import (
        allocate_construction_sources_per_period,
        allocate_construction_sources_provisional,
    )

    _validate_runtime_config(config)
    hard_capex = monthly_hard_capex(config.capex_schedule)
    vat_payable = vat_monthly_uses(config.capex_schedule)
    n_periods = len(hard_capex) if hard_capex else len(config.timeline)
    _validate_capex_timeline(hard_capex, vat_payable, config.timeline, config.convergence_tolerance_keur)
    if config.vat_facility_enabled:
        fixed_vat_commitment = (
            config.vat_facility_commitment_keur
            if config.vat_facility_commitment_mode == "FIXED_COMMITMENT"
            else None
        )
        vat_schedule = compute_vat_schedule(
            vat_payable,
            reimbursement_lag_periods=config.vat_reimbursement_lag_periods,
            vat_facility_commitment_keur=fixed_vat_commitment,
            tolerance_keur=config.convergence_tolerance_keur,
            horizon_periods=(config.vat_schedule_horizon_periods or None),
        )
        _validate_vat_facility_active(
            vat_schedule, config.timeline, config.convergence_tolerance_keur
        )
    else:
        if any(period.vat_facility_active for period in config.timeline):
            raise ValueError(
                "VAT facility is disabled but timeline contains active facility periods"
            )
        vat_schedule = tuple(
            FacilityPeriodState(period=index + 1, vat_payable_keur=payable)
            for index, payable in enumerate(vat_payable)
        )
    effective_vat_commitment_keur = max(
        (row.vat_requirement_keur + row.vat_undrawn_keur for row in vat_schedule),
        default=0.0,
    )
    effective_structuring_fee_basis_keur = (
        config.senior_commitment_keur + effective_vat_commitment_keur
        if config.structuring_fee_basis_mode == "SENIOR_PLUS_VAT_COMMITMENTS"
        else config.structuring_fee_basis_keur
    )
    structuring = allocate_structuring_fee(
        config.funding_policy,
        config.structuring_fee_rate * effective_structuring_fee_basis_keur,
    )

    idc_profile = _profile_n(config.senior_idc_spending_profile, n_periods)
    fee_profile = _profile_n(config.senior_commitment_fee_spending_profile, n_periods)
    vat_financing_profile = _profile_n(config.vat_financing_cost_spending_profile, n_periods)
    senior_rates = _period_rates(config, n_periods)
    senior_idc_uses = _pad_n(config.initial_senior_idc_funded_uses_keur, n_periods)
    senior_fee_uses = _pad_n(config.initial_senior_commitment_fee_funded_uses_keur, n_periods)
    vat_financing_uses = _pad_n(config.initial_vat_financing_funded_uses_keur, n_periods)
    residual = float("inf")
    audit: tuple[VectorResidualAudit, ...] = ()
    senior_period_draws: tuple[float, ...] = (0.0,) * n_periods
    senior_idc_total = 0.0
    senior_fee_total = 0.0
    vat_idc = 0.0
    vat_fee = 0.0
    iter_unfunded_keur = 0.0

    for iteration in range(1, config.max_iterations + 1):
        period_uses = tuple(
            hard_capex[idx] + structuring[idx] + senior_idc_uses[idx] + senior_fee_uses[idx] + vat_financing_uses[idx]
            for idx in range(n_periods)
        )
        # Use provisional allocator for IDC iteration — does not raise on shortfall.
        # unfunded_uses_keur is diagnostic only and does NOT earn IDC.
        # PR9_ACTUAL_SENIOR_FACILITY_CAP: senior_commitment_keur is EXACT — no buffer.
        _alloc_iter, iter_unfunded_keur = allocate_construction_sources_provisional(
            period_uses=period_uses,
            share_capital_keur=config.equity_available_keur,
            share_premium_keur=config.share_premium_keur,
            other_committed_equity_keur=config.other_committed_equity_keur,
            additional_equity_keur=config.additional_equity_keur,
            shl_cash_keur=config.shl_available_keur,
            junior_keur=config.junior_keur,
            senior_commitment_keur=config.senior_commitment_keur,
            tolerance_keur=config.convergence_tolerance_keur,
        )
        senior_period_draws = tuple(a.senior_draw_keur for a in _alloc_iter)

        idc_calc, fee_calc = _senior_financing_accruals(config, senior_period_draws, senior_rates)

        senior_idc_total = sum(idc_calc)
        senior_fee_total = sum(fee_calc)
        vat_fractions = _vat_fractions(config, len(vat_schedule))
        vat_idc = sum(
            row.vat_requirement_keur * config.vat_facility_interest_rate * vat_fractions[idx]
            for idx, row in enumerate(vat_schedule)
        )
        vat_fee = sum(
            max(0.0, effective_vat_commitment_keur - row.vat_requirement_keur)
            * config.vat_facility_commitment_fee_rate
            * vat_fractions[idx]
            for idx, row in enumerate(vat_schedule[: config.vat_commitment_fee_active_periods])
        )

        new_idc_uses = _capitalized_uses(
            senior_idc_total, idc_profile, tuple(idc_calc), config.senior_idc_capitalization_timing
        )
        new_fee_uses = _capitalized_uses(
            senior_fee_total, fee_profile, tuple(fee_calc), config.senior_commitment_fee_capitalization_timing
        )
        new_vat_financing_uses = tuple((vat_idc + vat_fee) * weight for weight in vat_financing_profile)
        residual, audit = convergence_audit(
            {
                "senior_idc": new_idc_uses,
                "senior_commitment_fee": new_fee_uses,
                "vat_financing_costs": new_vat_financing_uses,
            },
            {
                "senior_idc": senior_idc_uses,
                "senior_commitment_fee": senior_fee_uses,
                "vat_financing_costs": vat_financing_uses,
            },
        )
        senior_idc_uses = new_idc_uses
        senior_fee_uses = new_fee_uses
        vat_financing_uses = new_vat_financing_uses
        if residual <= config.convergence_tolerance_keur:
            break
    else:
        raise RuntimeError(
            f"Stage B2 circular financing did not converge after {config.max_iterations} iterations; "
            f"final residual={residual:.12f} kEUR"
        )

    # Converged period_uses (with final IDC/fee vectors).
    period_uses = tuple(
        hard_capex[idx] + structuring[idx] + senior_idc_uses[idx] + senior_fee_uses[idx] + vat_financing_uses[idx]
        for idx in range(n_periods)
    )

    financing = CapitalizedFinancingCosts(
        senior_idc_keur=sum(senior_idc_uses),
        senior_commitment_fee_keur=sum(senior_fee_uses),
        structuring_fee_keur=sum(structuring),
        vat_idc_keur=vat_idc,
        vat_commitment_fee_keur=vat_fee,
    )

    # prov_alloc_out: provisional allocations for caller (None on strict path).
    # Passed through so run_stage_b2_provisional computes funded Sources directly
    # from actual draws — PR9_CANONICAL_LAYER_A_ALLOCATOR_SINGLE_AUTHORITY.
    prov_alloc_out = None
    if not provisional:
        # Strict path: final canonical allocation — raises FundingShortfallError on shortfall.
        # PR9_ACTUAL_SENIOR_FACILITY_CAP: uses exact senior_commitment_keur, no buffer.
        try:
            _alloc_final = allocate_construction_sources_per_period(
                period_uses=period_uses,
                share_capital_keur=config.equity_available_keur,
                share_premium_keur=config.share_premium_keur,
                other_committed_equity_keur=config.other_committed_equity_keur,
                additional_equity_keur=config.additional_equity_keur,
                shl_cash_keur=config.shl_available_keur,
                junior_keur=config.junior_keur,
                senior_commitment_keur=config.senior_commitment_keur,
                tolerance_keur=config.convergence_tolerance_keur,
            )
        except ValueError as exc:
            raise FundingShortfallError(str(exc)) from exc
        senior_period_draws = tuple(a.senior_draw_keur for a in _alloc_final)
        final_unfunded = 0.0
        prov_alloc_out = _alloc_final
    else:
        # Provisional path: derive final draws without raising.
        _alloc_final_prov, final_unfunded = allocate_construction_sources_provisional(
            period_uses=period_uses,
            share_capital_keur=config.equity_available_keur,
            share_premium_keur=config.share_premium_keur,
            other_committed_equity_keur=config.other_committed_equity_keur,
            additional_equity_keur=config.additional_equity_keur,
            shl_cash_keur=config.shl_available_keur,
            junior_keur=config.junior_keur,
            senior_commitment_keur=config.senior_commitment_keur,
            tolerance_keur=config.convergence_tolerance_keur,
        )
        senior_period_draws = tuple(a.senior_draw_keur for a in _alloc_final_prov)
        prov_alloc_out = _alloc_final_prov

    # Recompute raw accruals from FINAL senior_period_draws — not from capitalization-use vectors.
    # senior_idc_uses / senior_fee_uses are capitalization timing vectors (may be NEXT_FUNDING_PERIOD
    # shifted). The accrual vectors in the result must reflect actual balance-basis calculation.
    senior_idc_accruals, senior_fee_accruals = _senior_financing_accruals(
        config, senior_period_draws, senior_rates
    )

    cumulative_senior: list[float] = []
    running = 0.0
    for draw in senior_period_draws:
        running += draw
        cumulative_senior.append(running)
    closing_senior = cumulative_senior[-1] if cumulative_senior else 0.0

    return (
        hard_capex, vat_payable, vat_schedule,
        senior_idc_accruals, senior_fee_accruals,
        tuple(cumulative_senior), senior_period_draws,
        period_uses, financing, closing_senior,
        iteration, residual, audit, final_unfunded,
        prov_alloc_out,
        senior_idc_uses,
    )


def run_stage_b2(config: ConstructionRuntimeConfig) -> ConstructionRuntimeResult:
    """Run canonical strict Stage B2.

    IDC/fee circular references converge via provisional inner allocations.
    Final post-convergence allocation is strict: raises FundingShortfallError
    if construction Sources < construction Uses after convergence.

    A normal returned ConstructionRuntimeResult guarantees:
    - IDC/fee fixed point converged
    - actual Sources fund actual construction Uses
    - Senior draw <= actual Senior commitment (no buffer)
    """
    (
        hard_capex, vat_payable, vat_schedule,
        senior_idc_accruals, senior_fee_accruals,
        cumulative_senior, senior_period_draws,
        period_uses, financing, closing_senior,
        iteration, residual, audit, _unfunded, _canonical_alloc,
        senior_idc_cap_uses,
    ) = _run_stage_b2_inner(config, provisional=False)

    return ConstructionRuntimeResult(
        config=config,
        monthly_hard_capex_keur=hard_capex,
        vat_payable_keur=vat_payable,
        vat_schedule=vat_schedule,
        senior_idc_accrual_keur=senior_idc_accruals,
        senior_idc_capitalized_uses_keur=senior_idc_cap_uses,
        senior_commitment_fee_accrual_keur=senior_fee_accruals,
        cumulative_senior_draw_keur=cumulative_senior,
        senior_period_draw_keur=senior_period_draws,
        total_permanent_uses_keur=period_uses,
        capitalized_financing_costs=financing,
        final_gfa_keur=total_hard_capex(config.capex_schedule) + financing.total_keur,
        closing_senior_drawn_keur=closing_senior,
        closing_senior_undrawn_keur=max(0.0, config.senior_commitment_keur - closing_senior),
        iterations=iteration,
        final_residual_keur=residual,
        residual_audit=audit,
        canonical_allocations=_canonical_alloc,
    )


def run_stage_b2_provisional(config: ConstructionRuntimeConfig) -> ProvisionalStageB2Result:
    """Provisional Stage B2 for outer G2A fixed-point intermediate iterations.

    Used ONLY by _run_with_construction_idc (project.py outer loop) where Senior
    may not yet be fully sized for IDC. Returns ProvisionalStageB2Result with
    explicit unfunded_uses_keur — NEVER returns ConstructionRuntimeResult.

    unfunded_uses_keur is diagnostic; it does NOT increase Senior or earn IDC.
    The outer loop must drive unfunded_uses_keur to zero before calling the strict
    run_stage_b2() for the final ConstructionRuntimeResult.
    """
    (
        _hard_capex, _vat_payable, _vat_schedule,
        _idc_accruals, _fee_accruals,
        _cumul_senior, senior_period_draws,
        period_uses, financing, _closing_senior,
        iteration, residual, _audit, final_unfunded,
        alloc_final_prov, _idc_cap_uses,
    ) = _run_stage_b2_inner(config, provisional=True)

    # Derive funded Sources directly from canonical provisional allocations.
    # total_provisional_funded_sources_keur = actual drawn sources, not configured caps.
    # PR9_CANONICAL_LAYER_A_ALLOCATOR_SINGLE_AUTHORITY: one authority, no reconstruction.
    total_funded = sum(a.total_sources_keur for a in alloc_final_prov)
    total_uses = sum(period_uses)

    return ProvisionalStageB2Result(
        authority="PR9_STAGE_B2_PROVISIONAL_OUTER_LOOP_INTERMEDIATE",
        provisional_senior_period_draw_keur=senior_period_draws,
        actual_senior_commitment_keur=config.senior_commitment_keur,
        total_provisional_funded_sources_keur=total_funded,
        total_construction_uses_keur=total_uses,
        unfunded_uses_keur=final_unfunded,
        capitalized_financing_costs=financing,
        iterations=iteration,
        final_residual_keur=residual,
        canonical_allocations=alloc_final_prov,
    )


def apply_capitalized_financing_costs(capex_structure, financing: CapitalizedFinancingCosts):
    """Return a CapexStructure carrying canonical Stage B2 financing outputs.

    The adapter is generic and immutable: it maps Stage B2 financing components to
    the existing CapexStructure financing fields consumed by
    book_depreciable_capex_items().
    """
    from dataclasses import replace

    vat_costs = financing.vat_idc_keur + financing.vat_commitment_fee_keur
    return replace(
        capex_structure,
        idc_keur=financing.senior_idc_keur,
        commitment_fees_keur=financing.senior_commitment_fee_keur,
        bank_fees_keur=financing.structuring_fee_keur,
        vat_costs_keur=vat_costs,
        vat_facility_idc_keur=financing.vat_idc_keur,
        vat_facility_commitment_fee_keur=financing.vat_commitment_fee_keur,
    )


__all__ = [
    "CapexPaymentItem",
    "CapexScheduleSet",
    "CapitalizedFinancingCosts",
    "ConstructionRuntimeConfig",
    "ConstructionRuntimeResult",
    "FacilityPeriodState",
    "FundingShortfallError",
    "FinancingCostFundingPolicy",
    "ProvisionalStageB2Result",
    "TimelinePeriod",
    "VectorResidualAudit",
    "allocate_structuring_fee",
    "apply_capitalized_financing_costs",
    "compute_vat_schedule",
    "convergence_audit",
    "monthly_hard_capex",
    "run_stage_b2",
    "run_stage_b2_provisional",
    "total_hard_capex",
    "vat_bearing_base",
    "vat_monthly_uses",
]
