"""Research-only composition over dated inputs and existing financial primitives.

No production orchestrator is patched, rebound, copied or invoked on a different
calendar. This module has no persistence, project funding or return authority.
Private production helpers below are reused read-only as assembly primitives;
their exact dependency and parity are tested, not claimed to be a public API.
"""
from dataclasses import replace
import math

from finco_core.ebitda import calculate_ebitda_keur
from finco_core.engine.axis_contract import CanonicalAxisContract
from finco_core.inputs import PeriodFrequency
from finco_core.opex.projections import opex_schedule_period
from finco_core.revenue.generation import full_generation_schedule, full_revenue_schedule
from financial_engine import orchestrator as core
from financial_engine.cfads import calculate_canonical_cfads
from financial_engine.dsra.model import run_cash_dsra_model
from financial_engine.provenance import (
    DerivationEvidence, EngineProvenance, compute_input_fingerprint,
    compute_senior_debt_fingerprint,
)
from financial_engine.results import (
    OperatingPeriodResult, OperatingSchedules, ProjectModelResult, SeniorDebtSchedules,
)
from financial_engine.senior_debt.models import SeniorDebtNonConvergenceError
from financial_engine.senior_debt.solver import solve_senior_debt
from financial_engine.tax.engine import calculate_cfads_and_cash_tax, calculate_tax
from financial_engine.validation import (
    has_errors, validate_operating_model_input, validate_tax_calculation_input,
)
from financial_engine.version import ENGINE_VERSION
from tools.quarterly_research.calendar import QuarterlyCandidateAxis, QuarterlyOperatingModelInput


def _provenance(inputs, stage, fingerprint):
    return EngineProvenance(ENGINE_VERSION,
        f"tools.quarterly_research.{stage}.QUARTERLY_CANDIDATE_NOT_RELEASED", fingerprint(inputs),
        (DerivationEvidence("research_result", __name__, stage, ("explicit_research_inputs",),
            ("RESEARCH_ONLY", "RELEASE_CLOSED", "NOT_A_PROJECT_RUN",
             "Existing generation/OPEX/depreciation/tax/CFADS/Senior primitives; no funding or returns.")),))


def run_operating_research(inputs):
    from tools.quarterly_research.runtime import validate_operating_candidate
    if type(inputs) is not QuarterlyOperatingModelInput:
        raise ValueError("QUARTERLY_CANDIDATE_ENTRY_REQUIRED")
    validate_operating_candidate(inputs)
    issues = validate_operating_model_input(inputs)
    if has_errors(issues):
        raise ValueError("QUARTERLY_OPERATING_INPUT_INVALID: " + repr(issues))
    axis = QuarterlyCandidateAxis.build(inputs.calendar)
    periods = axis.periods()
    indices = tuple(p.index for p in periods)
    tariff = core._build_ppa_tariff_schedule(inputs, periods)
    proxy = core._build_project_inputs_proxy(inputs, tariff)
    # Only a local research proxy is changed, never production inputs or globals.
    proxy = replace(proxy, info=replace(proxy.info, period_frequency=PeriodFrequency.QUARTERLY))
    generation = full_generation_schedule(proxy, axis)
    revenue = full_revenue_schedule(proxy, axis)
    opex = opex_schedule_period(proxy, axis)
    book, tax = core._compute_depreciation(inputs, periods)
    for label, vector in (("production", generation), ("revenue", revenue), ("opex", opex),
                          ("book_depreciation", book), ("tax_depreciation", tax)):
        core._validate_schedule_axis(indices, vector, label=label)
    rows = []
    for p in periods:
        i = p.index
        ebitda = calculate_ebitda_keur(revenue[i], opex[i])
        rows.append(OperatingPeriodResult(period_index=i, period_start=p.start_date, period_end=p.end_date,
            year_index=float(p.year_index), period_in_year=float(p.period_in_year),
            is_construction=p.is_construction, is_operation=p.is_operation, is_ppa_active=p.is_ppa_active,
            days_in_period=p.days_in_period, day_fraction=p.day_fraction, production_mwh=generation[i],
            revenue_keur=revenue[i], opex_keur=opex[i], ebitda_keur=ebitda,
            book_depreciation_keur=book[i], tax_depreciation_keur=tax[i], ebit_keur=ebitda - book[i]))
    rows = tuple(rows)
    schedules = OperatingSchedules(period_indices=indices, **{
        name: tuple(getattr(p, name) for p in rows) for name in (
            "production_mwh", "revenue_keur", "opex_keur", "ebitda_keur", "book_depreciation_keur",
            "tax_depreciation_keur", "ebit_keur")})
    return ProjectModelResult(_provenance(inputs, "operating", compute_input_fingerprint), rows,
        schedules, core._PHASE_2A_UNAVAILABLE, issues, ())


def _tax_schedules(operating, inputs):
    issues = validate_tax_calculation_input(inputs, frozenset(p.period_index for p in operating.periods))
    if has_errors(issues):
        raise ValueError("QUARTERLY_TAX_INPUT_INVALID: " + repr(issues))
    result = calculate_tax(operating.periods, inputs)
    cfads = calculate_canonical_cfads(operating.periods, result.period_results)
    return core._assemble_tax_cfads_schedules(operating, result, result.period_results, cfads), issues


def run_senior_research(inputs):
    from tools.quarterly_research.runtime import validate_debt_candidate
    validate_debt_candidate(inputs)
    base = run_operating_research(inputs.operating)
    _, tax_issues = _tax_schedules(base, inputs.tax)
    bank = run_operating_research(core.derive_debt_sizing_operating_input(inputs.operating, inputs.debt_sizing_case))
    policy = inputs.senior_debt_policy
    debt_periods = tuple(p for p in bank.periods if p.is_operation and
        policy.repayment_start_period_index <= p.period_index <= policy.maturity_period_index)
    contract = CanonicalAxisContract.from_periods_and_policy(base.periods, policy)

    def bank_tax(interest):
        merged = core._merge_financing_tax_input(inputs.tax, interest,
            tax_periodisation_mode_override=inputs.debt_sizing_case.tax_periodisation_mode_override)
        return calculate_cfads_and_cash_tax(bank.periods, merged)

    solved = solve_senior_debt(policy=policy, inputs=inputs.senior_debt_inputs,
                              periods=debt_periods, tax_cfads_fn=bank_tax)
    if not solved.diagnostics.is_authoritative:
        raise SeniorDebtNonConvergenceError("Quarterly research Senior result is not authoritative")
    interest = core._strict_period_map(solved.period_indices, solved.senior_interest_keur,
        label="research.final_senior_interest", expected_indices=contract.senior_axis)
    final_base_tax = core._merge_financing_tax_input(inputs.tax, interest)
    final_tax, _ = _tax_schedules(base, final_base_tax)
    final_bank_tax = core._merge_financing_tax_input(inputs.tax, interest,
        tax_periodisation_mode_override=inputs.debt_sizing_case.tax_periodisation_mode_override)
    bank_tax_result = calculate_tax(bank.periods, final_bank_tax)
    bank_cfads = calculate_canonical_cfads(bank.periods, bank_tax_result.period_results)
    debt_sizing = core._build_debt_sizing_schedules_from_bank(bank_phase2a_result=bank,
        final_bank_tax_result=bank_tax_result, final_bank_cfads_results=bank_cfads,
        senior_debt_result=solved, senior_axis=contract.senior_axis, base_periods=base.periods)
    base_cfads = core._strict_period_map(final_tax.period_indices, final_tax.cfads_keur,
        label="research.base_cfads", expected_indices=contract.full_axis)
    service = core._strict_period_map(solved.period_indices, solved.senior_debt_service_keur,
        label="research.senior_service", expected_indices=contract.senior_axis)
    dscr = tuple(base_cfads[i] / service[i] if service[i] > 0 and math.isfinite(base_cfads[i])
                 else None for i in solved.period_indices)
    diagnostics = {name: getattr(solved.diagnostics, name) for name in (
        "converged", "is_authoritative", "iteration_count", "initial_debt_guess_keur", "final_debt_size_keur",
        "maximum_absolute_difference_keur", "maximum_relative_difference", "binding_constraint",
        "termination_reason", "dscr_debt_capacity_keur", "gearing_debt_capacity_keur")}
    senior = SeniorDebtSchedules(period_indices=solved.period_indices,
        senior_debt_opening_keur=solved.senior_debt_opening_keur, senior_interest_keur=solved.senior_interest_keur,
        senior_principal_keur=solved.senior_principal_keur, senior_debt_service_keur=solved.senior_debt_service_keur,
        senior_debt_closing_keur=solved.senior_debt_closing_keur, base_dscr=dscr,
        debt_size_keur=solved.debt_size_keur, binding_constraint=solved.binding_constraint,
        diagnostics=diagnostics)
    post_senior = core._assemble_post_senior_cash_schedules(base.periods, final_tax, solved,
                                                         senior_axis=contract.senior_axis)
    cash_dsra = run_cash_dsra_model(post_senior, None, base.periods)
    issues = base.validation_issues + tax_issues
    return ProjectModelResult(provenance=_provenance(inputs, "senior", compute_senior_debt_fingerprint),
        periods=base.periods, operating_schedules=base.operating_schedules,
        tax_and_cfads=final_tax, senior_debt=senior, debt_sizing=debt_sizing,
        post_senior_cash=post_senior, cash_dsra=cash_dsra, axis_contract=contract,
        unavailable_sections=core._PHASE_2C_UNAVAILABLE, validation_issues=issues,
        warnings=tuple(f"{i.code} {i.path}: {i.message}" for i in issues if i.severity.value == "WARNING"))
