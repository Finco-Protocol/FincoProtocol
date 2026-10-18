"""Decimal numerical oracles for the existing solver on matched quarter dates."""
from dataclasses import fields, replace
from datetime import date, timedelta
from decimal import Decimal, localcontext

import pytest

from financial_engine.inputs import (
    CalendarInput, CapexItemForDep, DebtSizingCaseInput, DepreciationInput,
    InputProvenance, OpexInput, OpexLineInput, OperatingModelInput,
    OpeningTaxLossVintageInput, RevenueInput, SeniorDebtModelInput,
    TaxCalculationInput, TechnicalInput, YieldScenario,
)
from financial_engine.policies.tax import CashTaxTiming, TaxPolicy
from financial_engine.quarterly import ACTIVATION_ENABLED, CLASSIFICATION
from financial_engine.quarterly.calendar import (
    QuarterlyCandidateAxis, QuarterlyCandidateCalendar, RenewableTechnology,
)
from financial_engine.quarterly.runtime import (
    QuarterlyDebtStudy, build_operating_candidate, evaluate_quarterly_candidate,
)
from financial_engine.senior_debt.inputs import PeriodDscrTarget, SeniorDebtInputs
from financial_engine.senior_debt.policy import (
    DayCountConvention, SeniorDebtPolicy, SeniorDebtSizingMode,
)
from test_rc7_quarterly_calendar import explicit_policy

D = Decimal


def study(kind=RenewableTechnology.SOLAR, cod=date(2027, 12, 31),
          day_count=DayCountConvention.ACT_360, tax_rate=0.0,
          sizing=SeniorDebtSizingMode.DSCR_SCULPTED, profile=False):
    from dateutil.relativedelta import relativedelta
    cal = CalendarInput(cod - relativedelta(years=1), 12, 2, 0, cod)
    base = OperatingModelInput(
        calendar=cal,
        technical=TechnicalInput(10.0, YieldScenario.P50, 2000.0, 1600.0, 0.01, 1.0, 1.0),
        revenue=RevenueInput(75.0, 0.0, 0.0, 0.0, (75.0, 78.0), 0.0,
            0.0, 4.0 if kind is RenewableTechnology.WIND else 0.0, False, 0.0),
        opex=OpexInput((OpexLineInput("Operating cost", 100.0, 0.02, (), 0.0),)),
        depreciation=DepreciationInput((CapexItemForDep("Plant", 1000.0, "solar_panels", 10),),
            (CapexItemForDep("Plant", 1000.0, "solar_panels", 10),), 10),
        source=InputProvenance("synthetic-quarterly-candidate", ""),
    )
    candidate_cal = QuarterlyCandidateCalendar(**{
        f.name: getattr(cal, f.name) for f in fields(CalendarInput)
    }, policy=explicit_policy())
    op = build_operating_candidate(base, candidate_cal, kind)
    tax = TaxCalculationInput(TaxPolicy("synthetic-cit", "1", tax_rate, 4, 5, False,
        0.30, 3000.0, CashTaxTiming.TAX_YEAR_LAST_PERIOD), (), ())
    policy = SeniorDebtPolicy("synthetic-quarterly-senior", "1", sizing, 1.2,
        0.6 if sizing is not SeniorDebtSizingMode.DSCR_SCULPTED else None,
        0.06, 4, day_count, 1, 8, 1e-4, 1e-9, 200, False)
    targets = tuple(PeriodDscrTarget(i, 1.2 if i <= 4 else 1.4) for i in range(1, 9)) if profile else ()
    debt = SeniorDebtInputs(1000.0, 500.0, (), None, period_dscr_targets=targets)
    inputs = SeniorDebtModelInput(op, tax, policy, debt, DebtSizingCaseInput(YieldScenario.P90_10Y))
    return QuarterlyDebtStudy(inputs, QuarterlyCandidateAxis.build(candidate_cal).horizon_end)


def operating_oracle(period, hours, wind):
    year = period.period_end.year
    denominator = (date(year + 1, 1, 1) - date(year, 1, 1)).days
    fraction = D((period.period_end - period.period_start).days) / D(denominator)
    model_year = int(period.year_index)
    production = D(10) * D(hours) * D("0.99") ** (model_year - 1) * fraction
    price = (D(75), D(78))[model_year - 1]
    revenue = production * (price - (D(4) if wind else D(0))) / D(1000)
    opex = D(100) * D("1.02") ** (model_year - 1) * fraction
    return production, revenue, opex, D(100) * fraction


@pytest.mark.parametrize("kind", list(RenewableTechnology))
@pytest.mark.parametrize("cod", [date(2027, 12, 31), date(2028, 4, 17)])
@pytest.mark.parametrize("dc", list(DayCountConvention))
@pytest.mark.parametrize("profile", [False, True])
def test_quarterly_solver_vs_independent_decimal_backward_and_forward(kind, cod, dc, profile):
    case = study(kind, cod, dc, profile=profile)
    result = evaluate_quarterly_candidate(case)
    model, policy = result.model, case.inputs.senior_debt_policy
    senior, bank = model.senior_debt, model.debt_sizing
    bank_cfads = dict(zip(bank.period_indices, bank.bank_cfads_keur))
    bank_dscr = dict(zip(bank.period_indices, bank.bank_sizing_dscr))
    assert result.classification == CLASSIFICATION and ACTIVATION_ENABLED is False
    assert model.provenance.run_path_id.endswith("QUARTERLY_CANDIDATE_NOT_RELEASED")
    assert senior.diagnostics["is_authoritative"]
    assert model.axis_contract == QuarterlyCandidateAxis.build(case.inputs.operating.calendar).canonical_contract(policy)
    op = tuple(p for p in model.periods if p.is_operation)
    with localcontext() as ctx:
        ctx.prec = 50
        service, multipliers = [], []
        for p in op:
            expected = operating_oracle(p, 2000, kind is RenewableTechnology.WIND)
            for actual, value in zip((p.production_mwh, p.revenue_keur, p.opex_keur, p.book_depreciation_keur), expected):
                assert abs(D(str(actual)) - value) < D("1e-7")
            bank_values = operating_oracle(p, 1600, kind is RenewableTechnology.WIND)
            target = D("1.2") if not profile or p.period_index <= 4 else D("1.4")
            service.append((bank_values[1] - bank_values[2]) / target)
            multipliers.append(1 + D("0.06") * D((p.period_end - p.period_start).days)
                               / D(360 if dc is DayCountConvention.ACT_360 else 365))
        debt = D(0)
        for payment, multiplier in reversed(list(zip(service, multipliers))):
            debt = (debt + payment) / multiplier
        assert abs(D(str(senior.debt_size_keur)) - debt) < D("1e-7")
        opening = debt
        for i, (p, payment, multiplier) in enumerate(zip(op, service, multipliers)):
            interest = opening * (multiplier - 1)
            principal = payment - interest
            closing = opening - principal
            for actual, expected in zip((senior.senior_debt_opening_keur[i], senior.senior_interest_keur[i],
                    senior.senior_principal_keur[i], senior.senior_debt_service_keur[i], senior.senior_debt_closing_keur[i]),
                    (opening, interest, principal, payment, closing)):
                assert abs(D(str(actual)) - expected) < D("1e-7")
            bank_expected = operating_oracle(p, 1600, kind is RenewableTechnology.WIND)
            assert abs(D(str(bank_cfads[p.period_index])) - (bank_expected[1] - bank_expected[2])) < D("1e-7")
            assert senior.base_dscr[i] > bank_dscr[p.period_index]
            opening = closing
        assert abs(opening) < D("1e-40")
    assert abs(sum(senior.senior_principal_keur) - senior.debt_size_keur) < 1e-7
    assert abs(senior.senior_debt_closing_keur[-1]) < 1e-7
    cash = model.post_senior_cash
    for available, cfads, debt_service in zip(cash.cash_after_senior_before_reserves_keur,
                                            cash.base_cfads_keur, cash.senior_debt_service_keur):
        assert available == cfads - debt_service
    with pytest.raises(ValueError, match="REQUIRED_CONSUMERS_BLOCKED"):
        result.require_complete_project_run()


@pytest.mark.parametrize("kind", list(RenewableTechnology))
@pytest.mark.parametrize("mode", [SeniorDebtSizingMode.GEARING_CAP, SeniorDebtSizingMode.COMBINED_MINIMUM])
def test_existing_gearing_and_minimum_authority_on_quarterly_periods(kind, mode):
    result = evaluate_quarterly_candidate(study(kind, sizing=mode)).model
    assert result.senior_debt.debt_size_keur == 600.0
    assert abs(sum(result.senior_debt.senior_principal_keur) - 600.0) < 1e-7
    assert abs(result.senior_debt.senior_debt_closing_keur[-1]) < 1e-7
    assert result.senior_debt.diagnostics["gearing_debt_capacity_keur"] == 600.0


@pytest.mark.parametrize("kind", list(RenewableTechnology))
def test_complete_year_generation_revenue_opex_and_depreciation_conservation(kind):
    result = evaluate_quarterly_candidate(study(kind)).model
    for year in (1, 2):
        rows = [p for p in result.periods if p.is_operation and p.year_index == year]
        generation = D(20000) * D("0.99") ** (year - 1)
        revenue = generation * ((D(75), D(78))[year - 1] - (D(4) if kind is RenewableTechnology.WIND else 0)) / 1000
        assert abs(D(str(sum(p.production_mwh for p in rows))) - generation) < D("1e-7")
        assert abs(D(str(sum(p.revenue_keur for p in rows))) - revenue) < D("1e-7")
        assert abs(D(str(sum(p.opex_keur for p in rows))) - D(100) * D("1.02") ** (year - 1)) < D("1e-7")
        assert abs(D(str(sum(p.book_depreciation_keur for p in rows))) - 100) < D("1e-7")


def test_calendar_year_tax_and_loss_ledger_with_independent_date_fragments():
    case = study(tax_rate=0.18)
    tax = replace(case.inputs.tax, opening_loss_vintages=(OpeningTaxLossVintageInput(2025, 300.0),))
    case = replace(case, inputs=replace(case.inputs, tax=tax))
    model = evaluate_quarterly_candidate(case).model
    interest = dict(zip(model.senior_debt.period_indices, model.senior_debt.senior_interest_keur))
    annual, last_period, fragment_weights = {}, {}, {}
    with localcontext() as ctx:
        ctx.prec = 50
        for p in model.periods:
            days = (p.period_end - p.period_start).days
            start = p.period_start
            while start < p.period_end:
                stop = min(p.period_end, date(start.year + 1, 1, 1))
                weight = D((stop - start).days) / D(days)
                subtotal = (D(str(p.ebitda_keur)) - D(str(p.tax_depreciation_keur))
                            - D(str(interest.get(p.period_index, 0.0)))) * weight
                annual[start.year] = annual.get(start.year, D(0)) + subtotal
                fragment_weights.setdefault(start.year, {})[p.period_index] = weight
                # Existing cash-tax contract uses the latest period whose last
                # covered day is in this year, not the latest tiny carry fragment.
                if (p.period_end - timedelta(days=1)).year == start.year:
                    last_period[start.year] = p.period_index
                start = stop
        loss = D(300)
        liabilities = {}
        for row in model.tax_and_cfads.annual_results:
            taxable = annual[row.tax_year]
            used = min(loss, max(D(0), taxable))
            generated = max(D(0), -taxable)
            loss = loss - used + generated
            due = max(D(0), taxable - used) * D("0.18")
            assert abs(D(str(row.taxable_income_before_lcf_keur)) - taxable) < D("1e-7")
            assert abs(D(str(row.loss_used_keur)) - used) < D("1e-7")
            assert abs(D(str(row.loss_closing_keur)) - loss) < D("1e-7")
            assert abs(D(str(row.current_tax_liability_keur)) - due) < D("1e-7")
            weights = fragment_weights[row.tax_year]
            idx = last_period.get(row.tax_year)
            if idx is None:
                idx = max(weights, key=lambda i: (weights[i], i))
            liabilities[idx] = liabilities.get(idx, D(0)) + due
        for idx, cash in zip(model.tax_and_cfads.period_indices, model.tax_and_cfads.corporate_tax_cash_keur):
            assert abs(D(str(cash)) - liabilities.get(idx, D(0))) < D("1e-7")
        assert abs(model.tax_and_cfads.terminal_unpaid_tax_keur) < 1e-7


@pytest.mark.parametrize("field,value", [("shareholder_loan", object()), ("dsra", object()),
    ("capitalisation_gate_equity", object()), ("cash_reserve_interest_policy", object())])
def test_unsupported_facilities_fail_before_solver(field, value):
    case = study()
    with pytest.raises(ValueError, match="FACILITY_COMBINATION_UNSUPPORTED"):
        replace(case, inputs=replace(case.inputs, **{field: value}))


def test_off_grid_maturity_unknown_technology_and_six_month_target_vector_refused():
    case = study()
    with pytest.raises(ValueError, match="MATURITY_OFF_GRID"):
        replace(case, contractual_maturity=case.contractual_maturity - timedelta(days=1))
    with pytest.raises(ValueError, match="TECHNOLOGY_UNSUPPORTED"):
        replace(case.inputs.operating, technology="DATA_CENTER")
    data = replace(case.inputs.senior_debt_inputs,
                   period_dscr_targets=(PeriodDscrTarget(1, 1.2), PeriodDscrTarget(2, 1.2)))
    with pytest.raises(ValueError, match="DEBT_VECTOR_AXIS_MISMATCH"):
        replace(case, inputs=replace(case.inputs, senior_debt_inputs=data))


def test_impossible_gearing_with_no_balloon_does_not_return_candidate():
    case = study(sizing=SeniorDebtSizingMode.GEARING_CAP)
    data = replace(case.inputs.senior_debt_inputs, eligible_project_cost_keur=1000000.0)
    with pytest.raises(ValueError):
        evaluate_quarterly_candidate(replace(case, inputs=replace(case.inputs, senior_debt_inputs=data)))


def test_existing_six_month_clean_input_contract_cannot_silently_request_quarterly():
    from financial_engine.orchestrator import run_operating_model
    case = study()
    candidate = case.inputs.operating
    unmarked = OperatingModelInput(**{f.name: getattr(candidate, f.name) for f in fields(OperatingModelInput)})
    with pytest.raises(ValueError, match="CANDIDATE_ENTRY_REQUIRED"):
        run_operating_model(unmarked)


def test_candidate_policy_changes_fingerprint_and_keeps_released_run_namespace_distinct():
    first = evaluate_quarterly_candidate(study()).model
    second = evaluate_quarterly_candidate(study(day_count=DayCountConvention.ACT_365)).model
    assert first.provenance.input_fingerprint != second.provenance.input_fingerprint
    assert first.provenance.run_path_id.endswith("QUARTERLY_CANDIDATE_NOT_RELEASED")


@pytest.mark.parametrize("cod", [date(2028, 3, 30), date(2028, 6, 29), date(2028, 12, 30)])
def test_one_day_initial_stub_executes_without_moving_cod_or_funding_interest(cod):
    result = evaluate_quarterly_candidate(study(cod=cod)).model
    first = result.periods[1]
    assert first.period_start == cod
    assert first.days_in_period == 1
    expected_interest = D(str(result.senior_debt.debt_size_keur)) * D("0.06") / D(360)
    assert abs(D(str(result.senior_debt.senior_interest_keur[0])) - expected_interest) < D("1e-7")
    assert result.post_senior_cash.cash_after_senior_before_reserves_keur[1] >= 0


def test_true_dated_maturity_stops_debt_while_operation_continues():
    case = study()
    policy = replace(case.inputs.senior_debt_policy, maturity_period_index=4)
    case = replace(case, inputs=replace(case.inputs, senior_debt_policy=policy), contractual_maturity=date(2028, 12, 31))
    model = evaluate_quarterly_candidate(case).model
    assert model.senior_debt.period_indices == (1, 2, 3, 4)
    assert abs(model.senior_debt.senior_debt_closing_keur[-1]) < 1e-7
    service = dict(zip(model.post_senior_cash.period_indices, model.post_senior_cash.senior_debt_service_keur))
    assert all(service[i] == 0 for i in (5, 6, 7, 8))
    from dateutil.relativedelta import relativedelta
    with pytest.raises(ValueError, match="MATURITY_OFF_GRID"):
        replace(case, contractual_maturity=case.inputs.operating.calendar.cod_date + relativedelta(months=17))


def test_boundary_aligned_legacy_ppa_and_annual_step_opex_use_existing_leaves():
    case = study()
    op = case.inputs.operating
    revenue = replace(op.revenue, ppa_term_years=2.0, ppa_production_share=1.0, ppa_index=0.02)
    opex = replace(op.opex, items=(OpexLineInput("Operating cost", 100.0, 0.02, ((2, 200.0),), 0.0),))
    op = replace(op, calendar=replace(op.calendar, ppa_years=2), revenue=revenue, opex=opex)
    model = evaluate_quarterly_candidate(replace(case, inputs=replace(case.inputs, operating=op))).model
    for row in model.periods[1:]:
        tariff = D(75) * D("1.02") ** (int(row.year_index) - 1)
        assert abs(D(str(row.revenue_keur)) - D(str(row.production_mwh)) * tariff / 1000) < D("1e-7")
    assert abs(sum(p.opex_keur for p in model.periods if p.year_index == 2) - 200) < 1e-7


@pytest.mark.parametrize("update", [{"periods_per_tax_year": 2}, {"atad_enabled": True},
    {"cash_tax_timing": CashTaxTiming.SAME_PERIOD}, {"cash_tax_payment_lag_periods": 1}])
def test_unproven_tax_policies_refused_without_tax_kernel_changes(update):
    case = study()
    tax = replace(case.inputs.tax, policy=replace(case.inputs.tax.policy, **update))
    with pytest.raises(ValueError, match="TAX_POLICY_UNSUPPORTED"):
        replace(case, inputs=replace(case.inputs, tax=tax))


def test_intraperiod_ppa_and_hierarchical_opex_are_not_silently_accepted():
    case = study(cod=date(2028, 4, 17))
    op = case.inputs.operating
    with pytest.raises(ValueError, match="INTRAPERIOD_PPA_EXPIRY"):
        op = replace(op, calendar=replace(op.calendar, ppa_years=1), revenue=replace(op.revenue, ppa_term_years=1))
        replace(case, inputs=replace(case.inputs, operating=op))
    op = case.inputs.operating
    with pytest.raises(ValueError, match="OPEX_HANDOFF_REQUIRED"):
        replace(case, inputs=replace(case.inputs, operating=replace(op, opex=replace(op.opex, hierarchical_model=object()))))


@pytest.mark.parametrize("frequency", ["Quarterly", "unknown", None])
def test_production_adapter_refuses_untyped_or_missing_frequency(frequency):
    from app.project_factories import create_generic_solar_reference
    from financial_engine.adapters.project_inputs import from_project_inputs
    pi = create_generic_solar_reference()
    with pytest.raises(ValueError, match="CLEAN_CALENDAR_FREQUENCY_UNSUPPORTED"):
        from_project_inputs(replace(pi, info=replace(pi.info, period_frequency=frequency)))


def test_candidate_has_no_application_persistence_or_release_admission():
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for path in (root / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        modules = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        modules += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert not any(m.startswith("financial_engine.quarterly") for m in modules), str(path)
