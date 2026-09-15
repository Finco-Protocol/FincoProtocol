"""Pure C2 dated discounting, Project NPV, LLCR and PLCR calculations."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from numbers import Real

from finco_core.inputs.valuation import (
    CoverageCalculationDatePolicy,
    CoverageCashflowBasis,
    CoverageCfadsCase,
    CoverageDenominatorBasis,
    DebtCoverageValuationPolicy,
    DiscountConvention,
    PeriodicFirstCashflowTiming,
    PeriodicRateConversion,
    ProjectValuationPolicy,
    ValuationDatePolicy,
)
from financial_engine.project_returns.contracts import ProjectReturnStatus
from financial_engine.valuation.contracts import (
    CoverageMetric,
    CoverageRatioResult,
    CoverageStatus,
    DecisionCompleteValuationSummary,
    DiscountAuditRow,
    LenderCoverageResult,
    LlcrThresholdStatus,
    ProjectNpvResult,
    ProjectNpvStatus,
)

_TOL = 1e-9
_MAX_RATE = 10.0
_PROJECT_CASHFLOW_AUTHORITY = "C1_PROJECT_RETURN_RESULT_CASHFLOWS_EXACT"


class _DiscountError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class _DatedAmount:
    period_index: int | None
    cashflow_date: date
    amount_keur: float
    included: bool = True
    exclusion_reason: str | None = None
    raw_amount_keur: float | None = None
    eligibility_factor: float | None = None


def _validated_rate(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise _DiscountError("INVALID_DISCOUNT_RATE")
    rate = float(value)
    if not math.isfinite(rate) or rate <= -1.0 or rate > _MAX_RATE:
        raise _DiscountError("INVALID_DISCOUNT_RATE")
    return rate


def discount_dated_cashflows(
    *,
    valuation_date: date,
    cashflows: tuple[_DatedAmount, ...],
    annual_discount_rate: object,
    convention: DiscountConvention,
    periodic_rate_conversion: PeriodicRateConversion | None = None,
    periods_per_year: int | None = None,
    first_cashflow_timing: PeriodicFirstCashflowTiming | None = None,
) -> tuple[tuple[DiscountAuditRow, ...], float]:
    """Discount one vector once under one explicit date/period convention."""
    rate = _validated_rate(annual_discount_rate)
    if convention is DiscountConvention.PERIODIC_COMPOUNDING:
        if (
            periodic_rate_conversion
            is not PeriodicRateConversion.AS_QUOTED_PER_MODEL_PERIOD
            or isinstance(periods_per_year, bool)
            or not isinstance(periods_per_year, int)
            or periods_per_year <= 0
            or first_cashflow_timing
            is not PeriodicFirstCashflowTiming.END_OF_FIRST_PERIOD
        ):
            raise _DiscountError("UNSUPPORTED_DISCOUNT_CONVENTION")
        effective_periodic_rate = rate
    elif convention is DiscountConvention.ACT_365_FIXED:
        effective_periodic_rate = None
    else:
        raise _DiscountError("UNSUPPORTED_DISCOUNT_CONVENTION")
    rows: list[DiscountAuditRow] = []
    total = 0.0
    included_sequence = 0
    for cashflow in cashflows:
        raw_amount = (
            float(cashflow.raw_amount_keur)
            if cashflow.raw_amount_keur is not None
            else float(cashflow.amount_keur)
        )
        eligibility = (
            float(cashflow.eligibility_factor)
            if cashflow.eligibility_factor is not None else 1.0
        )
        if not cashflow.included:
            rows.append(DiscountAuditRow(
                period_index=cashflow.period_index,
                cashflow_date=cashflow.cashflow_date,
                undiscounted_cashflow_keur=cashflow.amount_keur,
                included=False,
                exclusion_reason=cashflow.exclusion_reason,
                year_fraction=None,
                discount_factor=None,
                discounted_cashflow_keur=None,
                raw_selected_cashflow_keur=raw_amount,
                eligibility_factor=eligibility,
                eligible_cashflow_keur=float(cashflow.amount_keur),
                discount_exponent=None,
            ))
            continue
        included_sequence += 1
        if convention is DiscountConvention.ACT_365_FIXED:
            days = (cashflow.cashflow_date - valuation_date).days
            if days < 0:
                raise _DiscountError("CASHFLOW_BEFORE_UNSUPPORTED_VALUATION_DATE")
            year_fraction = days / 365.0
            discount_exponent = year_fraction
            discount_factor = (1.0 + rate) ** year_fraction
        else:
            year_fraction = included_sequence / float(periods_per_year)
            discount_exponent = float(included_sequence)
            discount_factor = (1.0 + effective_periodic_rate) ** included_sequence
        discounted = float(cashflow.amount_keur) / discount_factor
        if not all(math.isfinite(v) for v in (year_fraction, discount_factor, discounted)):
            raise _DiscountError("NON_FINITE_RESULT")
        total += discounted
        rows.append(DiscountAuditRow(
            period_index=cashflow.period_index,
            cashflow_date=cashflow.cashflow_date,
            undiscounted_cashflow_keur=float(cashflow.amount_keur),
            included=True,
            exclusion_reason=None,
            year_fraction=year_fraction,
            discount_factor=discount_factor,
            discounted_cashflow_keur=discounted,
            raw_selected_cashflow_keur=raw_amount,
            eligibility_factor=eligibility,
            eligible_cashflow_keur=float(cashflow.amount_keur),
            discount_exponent=discount_exponent,
        ))
    if not math.isfinite(total):
        raise _DiscountError("NON_FINITE_RESULT")
    return tuple(rows), total


def calculate_project_npv(project_return, policy: ProjectValuationPolicy | None) -> ProjectNpvResult:
    if policy is None:
        return ProjectNpvResult(
            status=ProjectNpvStatus.NOT_CONFIGURED,
            npv_keur=None,
            valuation_date=None,
            annual_discount_rate=None,
            discount_convention=None,
            discount_authority=None,
            cashflow_identity_authority=_PROJECT_CASHFLOW_AUTHORITY,
            periods=(),
        )
    if policy.annual_discount_rate is None:
        return ProjectNpvResult(
            status=ProjectNpvStatus.NOT_CONFIGURED,
            npv_keur=None,
            valuation_date=None,
            annual_discount_rate=None,
            discount_convention=policy.discount_convention,
            discount_authority=policy.authority_label,
            cashflow_identity_authority=_PROJECT_CASHFLOW_AUTHORITY,
            periods=(),
        )
    if project_return.project_xirr_status is not ProjectReturnStatus.OK:
        return ProjectNpvResult(
            status=ProjectNpvStatus.UPSTREAM_PROJECT_RETURN_UNAVAILABLE,
            npv_keur=None,
            valuation_date=None,
            annual_discount_rate=policy.annual_discount_rate,
            discount_convention=policy.discount_convention,
            discount_authority=policy.authority_label,
            cashflow_identity_authority=_PROJECT_CASHFLOW_AUTHORITY,
            periods=(),
            upstream_project_return_status=project_return.project_xirr_status.value,
        )
    cashflows = tuple(project_return.cashflows)
    valuation_date = (
        cashflows[0].cashflow_date
        if policy.valuation_date_policy is ValuationDatePolicy.FIRST_PROJECT_CASHFLOW_DATE
        and cashflows
        else policy.explicit_valuation_date
    )
    if valuation_date is None:
        return ProjectNpvResult(
            status=ProjectNpvStatus.VALUATION_DATE_UNAVAILABLE,
            npv_keur=None,
            valuation_date=None,
            annual_discount_rate=policy.annual_discount_rate,
            discount_convention=policy.discount_convention,
            discount_authority=policy.authority_label,
            cashflow_identity_authority=_PROJECT_CASHFLOW_AUTHORITY,
            periods=(),
        )
    dated = tuple(
        _DatedAmount(
            period_index=None,
            cashflow_date=row.cashflow_date,
            amount_keur=row.net_unlevered_project_cashflow_keur,
        )
        for row in cashflows
    )
    try:
        rows, npv = discount_dated_cashflows(
            valuation_date=valuation_date,
            cashflows=dated,
            annual_discount_rate=policy.annual_discount_rate,
            convention=policy.discount_convention,
        )
    except _DiscountError as exc:
        status = {
            "INVALID_DISCOUNT_RATE": ProjectNpvStatus.INVALID_DISCOUNT_RATE,
            "CASHFLOW_BEFORE_UNSUPPORTED_VALUATION_DATE": (
                ProjectNpvStatus.CASHFLOW_BEFORE_UNSUPPORTED_VALUATION_DATE
            ),
        }.get(exc.code, ProjectNpvStatus.NON_FINITE_RESULT)
        return ProjectNpvResult(
            status=status,
            npv_keur=None,
            valuation_date=valuation_date,
            annual_discount_rate=policy.annual_discount_rate,
            discount_convention=policy.discount_convention,
            discount_authority=policy.authority_label,
            cashflow_identity_authority=_PROJECT_CASHFLOW_AUTHORITY,
            periods=(),
        )
    return ProjectNpvResult(
        status=ProjectNpvStatus.OK,
        npv_keur=npv,
        valuation_date=valuation_date,
        annual_discount_rate=float(policy.annual_discount_rate),
        discount_convention=policy.discount_convention,
        discount_authority=policy.authority_label,
        cashflow_identity_authority=_PROJECT_CASHFLOW_AUTHORITY,
        periods=rows,
        upstream_project_return_status=project_return.project_xirr_status.value,
    )


def _coverage_failure(
    metric: CoverageMetric,
    status: CoverageStatus,
    policy: DebtCoverageValuationPolicy | None,
) -> CoverageRatioResult:
    cashflow_basis = None
    if policy is not None:
        cashflow_basis = (
            policy.llcr_cashflow_basis
            if metric is CoverageMetric.LLCR
            else policy.plcr_cashflow_basis
        )
    return CoverageRatioResult(
        metric=metric,
        status=status,
        calculation_date=None,
        cfads_case=None if policy is None else policy.cfads_case,
        annual_discount_rate=None if policy is None else policy.annual_discount_rate,
        discount_convention=None if policy is None else policy.discount_convention,
        discount_authority=None if policy is None else policy.authority_label,
        cashflow_basis=cashflow_basis,
        denominator_basis=None if policy is None else policy.denominator_basis,
        periodic_rate_conversion=(
            None if policy is None else policy.periodic_rate_conversion
        ),
        periods_per_year=None if policy is None else policy.periods_per_year,
        first_cashflow_timing=(
            None if policy is None else policy.first_cashflow_timing
        ),
        effective_periodic_discount_rate=None,
        debt_balance_denominator_keur=None,
        pv_cfads_numerator_keur=None,
        ratio=None,
        periods=(),
    )


def _coverage_metric(
    *,
    metric: CoverageMetric,
    model,
    senior_terminal,
    policy: DebtCoverageValuationPolicy | None,
    senior_eligibility_schedule: tuple[float, ...] | None,
) -> CoverageRatioResult:
    senior = model.senior_debt
    if senior is None or float(senior.debt_size_keur) <= _TOL:
        return _coverage_failure(metric, CoverageStatus.NOT_APPLICABLE_NO_SENIOR, policy)
    if policy is None or policy.cfads_case is None:
        return _coverage_failure(
            metric, CoverageStatus.COVERAGE_CFADS_CASE_NOT_CONFIGURED, policy
        )
    if policy.annual_discount_rate is None:
        return _coverage_failure(
            metric, CoverageStatus.COVERAGE_DISCOUNT_RATE_NOT_CONFIGURED, policy
        )
    cashflow_basis = (
        policy.llcr_cashflow_basis
        if metric is CoverageMetric.LLCR else policy.plcr_cashflow_basis
    )
    if cashflow_basis is None:
        return _coverage_failure(
            metric, CoverageStatus.COVERAGE_CASHFLOW_BASIS_NOT_CONFIGURED, policy
        )
    if (
        metric is CoverageMetric.PLCR
        and cashflow_basis is CoverageCashflowBasis.SENIOR_ELIGIBLE_CFADS
    ):
        return _coverage_failure(
            metric,
            CoverageStatus.COVERAGE_CASHFLOW_BASIS_UNSUPPORTED_FOR_METRIC,
            policy,
        )
    if (
        policy.calculation_date_policy
        is not CoverageCalculationDatePolicy.FIRST_SENIOR_PERIOD_OPENING
    ):
        return _coverage_failure(
            metric,
            CoverageStatus.COVERAGE_CALCULATION_DATE_POLICY_UNSUPPORTED,
            policy,
        )
    if policy.denominator_basis is not CoverageDenominatorBasis.SENIOR_OPENING_BALANCE:
        return _coverage_failure(
            metric, CoverageStatus.COVERAGE_DENOMINATOR_AUTHORITY_UNAVAILABLE, policy
        )
    if senior_terminal.contractual_maturity_period_index is None:
        return _coverage_failure(metric, CoverageStatus.SENIOR_MATURITY_UNAVAILABLE, policy)

    periods = tuple(model.periods)
    indices = tuple(period.period_index for period in periods)
    if len(indices) != len(set(indices)):
        return _coverage_failure(metric, CoverageStatus.PERIOD_AXIS_MISMATCH, policy)
    period_by_index = {period.period_index: period for period in periods}
    senior_indices = tuple(senior.period_indices)
    if len(senior_indices) != len(set(senior_indices)) or any(
        index not in period_by_index for index in senior_indices
    ):
        return _coverage_failure(metric, CoverageStatus.PERIOD_AXIS_MISMATCH, policy)
    senior_opening = dict(zip(senior_indices, senior.senior_debt_opening_keur))
    measurement_index = next(
        (index for index in senior_indices if senior_opening[index] > _TOL), None
    )
    if measurement_index is None:
        return _coverage_failure(metric, CoverageStatus.DEBT_BALANCE_ZERO, policy)
    measurement_period = period_by_index[measurement_index]
    calculation_date = measurement_period.period_start

    eligibility_by_index: dict[int, float] = {}
    if cashflow_basis is CoverageCashflowBasis.SENIOR_ELIGIBLE_CFADS:
        if (
            senior_eligibility_schedule is None
            or len(senior_eligibility_schedule) != len(senior_indices)
        ):
            return _coverage_failure(
                metric,
                CoverageStatus.COVERAGE_ELIGIBILITY_AUTHORITY_UNAVAILABLE,
                policy,
            )
        for index, factor in zip(senior_indices, senior_eligibility_schedule):
            if (
                isinstance(factor, bool)
                or not isinstance(factor, Real)
                or not math.isfinite(float(factor))
                or not 0.0 <= float(factor) <= 1.0
            ):
                return _coverage_failure(
                    metric,
                    CoverageStatus.COVERAGE_ELIGIBILITY_AUTHORITY_UNAVAILABLE,
                    policy,
                )
            eligibility_by_index[index] = float(factor)

    if policy.cfads_case is CoverageCfadsCase.BASE:
        schedules = model.tax_and_cfads
        cfads_indices = () if schedules is None else tuple(schedules.period_indices)
        cfads_values = () if schedules is None else tuple(schedules.cfads_keur)
    else:
        schedules = model.debt_sizing
        cfads_indices = () if schedules is None else tuple(schedules.period_indices)
        cfads_values = () if schedules is None else tuple(schedules.bank_cfads_keur)
    if cfads_indices != indices or len(cfads_values) != len(indices):
        return _coverage_failure(metric, CoverageStatus.PERIOD_AXIS_MISMATCH, policy)
    cfads_by_index = dict(zip(cfads_indices, cfads_values))

    operating = tuple(period for period in periods if period.is_operation)
    if not operating:
        return _coverage_failure(
            metric, CoverageStatus.PROJECT_LIFE_HORIZON_UNAVAILABLE, policy
        )
    horizon = (
        senior_terminal.contractual_maturity_period_index
        if metric is CoverageMetric.LLCR
        else operating[-1].period_index
    )
    dated: list[_DatedAmount] = []
    for period in operating:
        included = measurement_index <= period.period_index <= horizon
        reason = None
        if period.period_index < measurement_index:
            reason = "BEFORE_CALCULATION_PERIOD"
        elif period.period_index > horizon:
            reason = (
                "AFTER_SENIOR_CONTRACTUAL_MATURITY"
                if metric is CoverageMetric.LLCR
                else "AFTER_PROJECT_LIFE"
            )
        raw_cfads = float(cfads_by_index[period.period_index])
        eligibility_factor = (
            eligibility_by_index.get(period.period_index, 0.0)
            if cashflow_basis is CoverageCashflowBasis.SENIOR_ELIGIBLE_CFADS
            else 1.0
        )
        eligible_cfads = raw_cfads * eligibility_factor
        dated.append(_DatedAmount(
            period_index=period.period_index,
            cashflow_date=period.period_end,
            amount_keur=eligible_cfads,
            included=included,
            exclusion_reason=reason,
            raw_amount_keur=raw_cfads,
            eligibility_factor=eligibility_factor,
        ))
    try:
        audit_rows, numerator = discount_dated_cashflows(
            valuation_date=calculation_date,
            cashflows=tuple(dated),
            annual_discount_rate=policy.annual_discount_rate,
            convention=policy.discount_convention,
            periodic_rate_conversion=policy.periodic_rate_conversion,
            periods_per_year=policy.periods_per_year,
            first_cashflow_timing=policy.first_cashflow_timing,
        )
    except _DiscountError as exc:
        status = (
            CoverageStatus.INVALID_DISCOUNT_RATE
            if exc.code == "INVALID_DISCOUNT_RATE"
            else CoverageStatus.COVERAGE_DISCOUNT_CONVENTION_UNSUPPORTED
            if exc.code == "UNSUPPORTED_DISCOUNT_CONVENTION"
            else CoverageStatus.NON_FINITE_RESULT
        )
        return _coverage_failure(metric, status, policy)
    denominator = float(senior_opening[measurement_index])
    if denominator <= _TOL:
        return _coverage_failure(metric, CoverageStatus.DEBT_BALANCE_ZERO, policy)
    ratio = numerator / denominator
    if not math.isfinite(ratio):
        return _coverage_failure(metric, CoverageStatus.NON_FINITE_RESULT, policy)
    return CoverageRatioResult(
        metric=metric,
        status=CoverageStatus.OK,
        calculation_date=calculation_date,
        cfads_case=policy.cfads_case,
        annual_discount_rate=float(policy.annual_discount_rate),
        discount_convention=policy.discount_convention,
        discount_authority=policy.authority_label,
        cashflow_basis=cashflow_basis,
        denominator_basis=policy.denominator_basis,
        periodic_rate_conversion=policy.periodic_rate_conversion,
        periods_per_year=policy.periods_per_year,
        first_cashflow_timing=policy.first_cashflow_timing,
        effective_periodic_discount_rate=(
            float(policy.annual_discount_rate)
            if policy.discount_convention is DiscountConvention.PERIODIC_COMPOUNDING
            else None
        ),
        debt_balance_denominator_keur=denominator,
        pv_cfads_numerator_keur=numerator,
        ratio=ratio,
        periods=audit_rows,
    )


def calculate_lender_coverage(
    *,
    model,
    senior_terminal,
    policy: DebtCoverageValuationPolicy | None,
    minimum_llcr: float | None,
    senior_eligibility_schedule: tuple[float, ...] | None = None,
) -> LenderCoverageResult:
    llcr = _coverage_metric(
        metric=CoverageMetric.LLCR,
        model=model,
        senior_terminal=senior_terminal,
        policy=policy,
        senior_eligibility_schedule=senior_eligibility_schedule,
    )
    plcr = _coverage_metric(
        metric=CoverageMetric.PLCR,
        model=model,
        senior_terminal=senior_terminal,
        policy=policy,
        senior_eligibility_schedule=senior_eligibility_schedule,
    )
    if llcr.status is not CoverageStatus.OK:
        threshold_status = LlcrThresholdStatus.NOT_APPLICABLE
        headroom = None
    elif minimum_llcr is None or not math.isfinite(float(minimum_llcr)):
        threshold_status = LlcrThresholdStatus.NOT_CONFIGURED
        headroom = None
    else:
        headroom = float(llcr.ratio) - float(minimum_llcr)
        threshold_status = (
            LlcrThresholdStatus.PASS if headroom >= -_TOL else LlcrThresholdStatus.FAIL
        )
    return LenderCoverageResult(
        llcr=llcr,
        plcr=plcr,
        minimum_llcr=None if minimum_llcr is None else float(minimum_llcr),
        llcr_headroom=headroom,
        llcr_threshold_status=threshold_status,
    )


def build_decision_complete_valuation_summary(
    *,
    project_inputs,
    financing,
    project_return,
    senior_terminal,
) -> DecisionCompleteValuationSummary:
    policies = project_inputs.valuation
    return DecisionCompleteValuationSummary(
        project_npv=calculate_project_npv(project_return, policies.project),
        lender_coverage=calculate_lender_coverage(
            model=financing.project_model_result,
            senior_terminal=senior_terminal,
            policy=policies.coverage,
            minimum_llcr=project_inputs.financing.min_llcr,
            senior_eligibility_schedule=(
                project_inputs.financing.senior_sculpting_config
                .debt_service_availability_schedule
            ),
        ),
    )
