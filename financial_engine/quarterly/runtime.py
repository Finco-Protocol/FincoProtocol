"""Bounded RC-7 entry: reuse the existing operating/tax/bank-sizing orchestrator.

No project funding, shareholder waterfall or financial statements are invented
here. Those required consumers keep the complete quarterly project Run blocked.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date

from financial_engine.inputs import OperatingModelInput, SeniorDebtModelInput, TaxCalculationInput, TechnicalInput
from financial_engine.policies.tax import CashTaxTiming, TaxBasisPeriodisation, TaxPolicy
from financial_engine.results import ProjectModelResult
from financial_engine.quarterly import CLASSIFICATION
from financial_engine.quarterly.calendar import (
    QuarterlyCandidateAxis, QuarterlyCandidateCalendar, QuarterlyOperatingModelInput,
    RenewableTechnology,
)
from financial_engine.senior_debt.inputs import SeniorDebtInputs
from financial_engine.senior_debt.policy import SeniorDebtPolicy, SeniorDebtSizingMode


BLOCKED_CONSUMERS = (
    "monthly_funding_to_quarterly_statement_bridge",
    "sources_and_uses_and_balance_sheet",
    "dsra_dsrf_policy", "contractual_covenants_and_distribution_eligibility",
    "shareholder_waterfall_and_sponsor_returns", "unlevered_project_returns",
    "production_save_run_history_and_export_admission",
)


def build_operating_candidate(
    base: OperatingModelInput,
    calendar: QuarterlyCandidateCalendar,
    technology: RenewableTechnology,
) -> QuarterlyOperatingModelInput:
    """Explicit research adaptation, not a semiannual vector interpolation."""
    if type(base) is not OperatingModelInput or type(calendar) is not QuarterlyCandidateCalendar:
        raise ValueError("QUARTERLY_EXPLICIT_CLEAN_INPUT_REQUIRED")
    for name in ("financial_close", "construction_months", "cod_date", "horizon_years", "ppa_years"):
        if getattr(base.calendar, name) != getattr(calendar, name):
            raise ValueError(f"QUARTERLY_PROJECT_TIMELINE_MISMATCH: {name}")
    result = QuarterlyOperatingModelInput(**{
        f.name: calendar if f.name == "calendar" else getattr(base, f.name)
        for f in fields(OperatingModelInput)
    }, technology=technology)
    validate_operating_candidate(result)
    return result


def validate_operating_candidate(inputs: QuarterlyOperatingModelInput) -> None:
    if type(inputs) is not QuarterlyOperatingModelInput:
        raise ValueError("QUARTERLY_CANDIDATE_ENTRY_REQUIRED")
    if type(inputs.calendar) is not QuarterlyCandidateCalendar:
        raise ValueError("QUARTERLY_TYPED_CALENDAR_REQUIRED")
    if type(inputs.technology) is not RenewableTechnology or type(inputs.technical) is not TechnicalInput:
        raise ValueError("QUARTERLY_TECHNOLOGY_UNSUPPORTED")
    rev = inputs.revenue
    if getattr(rev, "multistream_config_json", ""):
        raise ValueError("QUARTERLY_REVENUE_CONTRACT_HANDOFF_REQUIRED")
    if (rev.co2_price_semiannual_eur_mwh
            or rev.first_merchant_operating_period_index is not None):
        raise ValueError("QUARTERLY_LEGACY_PERIOD_VECTOR_UNSUPPORTED")
    if inputs.opex.hierarchical_model is not None or inputs.opex.hierarchical_external_annual_series:
        raise ValueError("QUARTERLY_HIERARCHICAL_OPEX_HANDOFF_REQUIRED")
    # D-05: only the existing model-year PPA formula, with whole-period expiry.
    # Dated contractual/index-series products belong to the revenue workstream.
    if rev.ppa_indexation_start_policy is not None or rev.ppa_indexation_start_date is not None:
        raise ValueError("QUARTERLY_PPA_INDEXATION_HANDOFF_REQUIRED")
    if rev.ppa_term_years != inputs.calendar.ppa_years:
        raise ValueError("QUARTERLY_PPA_TERM_MISMATCH")
    axis = QuarterlyCandidateAxis.build(inputs.calendar)
    from dateutil.relativedelta import relativedelta
    expiry = axis.cod + relativedelta(years=int(inputs.calendar.ppa_years))
    if any(p.start_date < expiry < p.end_date for p in axis.rows[1:]):
        raise ValueError("QUARTERLY_INTRAPERIOD_PPA_EXPIRY_UNSUPPORTED")


def validate_tax_candidate(tax) -> None:
    if type(tax) is not TaxCalculationInput or type(tax.policy) is not TaxPolicy:
        raise ValueError("QUARTERLY_TYPED_TAX_CONTRACT_REQUIRED")
    p = tax.policy
    if (type(p.periods_per_tax_year) is not int or p.periods_per_tax_year != 4
            or p.tax_basis_periodisation is not TaxBasisPeriodisation.CALENDAR_YEAR
            or p.cash_tax_timing is not CashTaxTiming.TAX_YEAR_LAST_PERIOD
            or p.cash_tax_payment_lag_periods != 0
            or p.atad_enabled or p.thin_cap_enabled
            or p.interest_limitation_policy is not None):
        raise ValueError("QUARTERLY_TAX_POLICY_UNSUPPORTED")
    if tax.period_interest or tax.period_adjustments or tax.period_financing_income:
        raise ValueError("QUARTERLY_EXOGENOUS_PERIOD_TAX_INPUT_UNSUPPORTED")


def validate_debt_candidate(inputs: SeniorDebtModelInput) -> None:
    if type(inputs) is not SeniorDebtModelInput:
        raise ValueError("QUARTERLY_TYPED_DEBT_CONTRACT_REQUIRED")
    validate_operating_candidate(inputs.operating)
    validate_tax_candidate(inputs.tax)
    if (inputs.shareholder_loan is not None or inputs.dsra is not None
            or inputs.capitalisation_gate_equity is not None
            or inputs.cash_reserve_interest_policy is not None):
        raise ValueError("QUARTERLY_FACILITY_COMBINATION_UNSUPPORTED")
    policy, data = inputs.senior_debt_policy, inputs.senior_debt_inputs
    if type(policy) is not SeniorDebtPolicy or type(data) is not SeniorDebtInputs:
        raise ValueError("QUARTERLY_SINGLE_SENIOR_CONTRACT_REQUIRED")
    if (type(policy.sizing_mode) is not SeniorDebtSizingMode
            or type(policy.repayment_start_period_index) is not int
            or type(policy.maturity_period_index) is not int
            or type(policy.periods_per_year) is not int
            or policy.sizing_mode not in (SeniorDebtSizingMode.DSCR_SCULPTED,
                                  SeniorDebtSizingMode.COMBINED_MINIMUM,
                                  SeniorDebtSizingMode.GEARING_CAP)
            or policy.repayment_start_period_index != 1 or policy.permit_terminal_balloon is not False
            or data.opening_debt_balance_keur != 0.0 or data.explicit_principal_schedule is not None
            or inputs.debt_sizing_case.tax_periodisation_mode_override is not None):
        raise ValueError("QUARTERLY_DEBT_POLICY_UNSUPPORTED")
    axis = QuarterlyCandidateAxis.build(inputs.operating.calendar)
    contract = axis.canonical_contract(policy)
    # Complete or absent explicitly keyed vectors; never stretch a 6/6 vector.
    for name in ("period_rates", "period_dscr_targets", "period_debt_service_availability"):
        vector = getattr(data, name)
        if vector and tuple(v.period_index for v in vector) != contract.senior_axis:
            raise ValueError(f"QUARTERLY_DEBT_VECTOR_AXIS_MISMATCH: {name}")


@dataclass(frozen=True)
class QuarterlyDebtStudy:
    inputs: SeniorDebtModelInput
    contractual_maturity: date

    def __post_init__(self):
        validate_debt_candidate(self.inputs)
        axis = QuarterlyCandidateAxis.build(self.inputs.operating.calendar)
        maturity_index = self.inputs.senior_debt_policy.maturity_period_index
        if type(self.contractual_maturity) is not date or axis.rows[maturity_index].end_date != self.contractual_maturity:
            raise ValueError("QUARTERLY_MATURITY_OFF_GRID_OR_MISMATCH")


@dataclass(frozen=True)
class QuarterlyFinancialCandidate:
    study: QuarterlyDebtStudy
    model: ProjectModelResult
    classification: str = CLASSIFICATION
    blocked_consumers: tuple[str, ...] = BLOCKED_CONSUMERS

    def require_complete_project_run(self):
        raise ValueError("QUARTERLY_REQUIRED_CONSUMERS_BLOCKED: " + ", ".join(BLOCKED_CONSUMERS))


def evaluate_quarterly_candidate(study: QuarterlyDebtStudy) -> QuarterlyFinancialCandidate:
    if type(study) is not QuarterlyDebtStudy:
        raise ValueError("QUARTERLY_TYPED_STUDY_REQUIRED")
    validate_debt_candidate(study.inputs)
    from financial_engine.orchestrator import run_senior_debt_model
    model = run_senior_debt_model(study.inputs)
    from financial_engine.financing.project import (
        G2A_SERVICE_BUDGET_ACCEPTANCE_TOLERANCE_KEUR, _senior_service_budget_excess,
    )
    if _senior_service_budget_excess(model, study.inputs) > G2A_SERVICE_BUDGET_ACCEPTANCE_TOLERANCE_KEUR:
        raise ValueError("QUARTERLY_SENIOR_SERVICE_BUDGET_EXCEEDED")
    if any(value < -G2A_SERVICE_BUDGET_ACCEPTANCE_TOLERANCE_KEUR
           for value in model.post_senior_cash.cash_after_senior_before_reserves_keur):
        raise ValueError("QUARTERLY_UNFUNDED_POST_SENIOR_CASH")
    if abs(model.senior_debt.senior_debt_closing_keur[-1]) > G2A_SERVICE_BUDGET_ACCEPTANCE_TOLERANCE_KEUR:
        raise ValueError("QUARTERLY_TERMINAL_SENIOR_LIABILITY_UNRESOLVED")
    if not model.provenance.run_path_id.endswith("QUARTERLY_CANDIDATE_NOT_RELEASED"):
        raise ValueError("QUARTERLY_CANDIDATE_PROVENANCE_REQUIRED")
    return QuarterlyFinancialCandidate(study, model)
