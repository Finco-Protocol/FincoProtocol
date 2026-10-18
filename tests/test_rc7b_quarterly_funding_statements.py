"""RC-7B Workstream B: construction funding handoff, statements and returns on 3/3.

Every expected quarterly value comes from ``tests/rc7b_quarterly_oracle.py``
(Decimal, from inputs) or from the RELEASED six-month run of the same project
for frequency-independent construction quantities (proved identical below).
Tolerances are the existing approved constants, never new or widened ones:

* G2A_SERVICE_BUDGET_ACCEPTANCE_TOLERANCE_KEUR (1e-6) and the statements
  ``_TOLERANCE_KEUR`` (1e-6) for funding/Sources & Uses/Balance Sheet identities;
* the clean Senior policy ``convergence_tolerance_keur`` (1e-4) for quantities
  that come out of the existing tax-interest fixed point;
* the project-return ``_TOL`` (1e-7).

Nothing here approves a candidate convention; admission stays closed.
"""
from __future__ import annotations

import dataclasses
from datetime import date, timedelta
from decimal import Decimal

import pytest
from dateutil.relativedelta import relativedelta

import rc7b_quarterly_oracle as oracle
from finco_core.engine.calendar_policy import quarterly_candidate_policy
from financial_engine.financing.project import G2A_SERVICE_BUDGET_ACCEPTANCE_TOLERANCE_KEUR as FUNDING_TOL
from financial_engine.financial_statements.assembly import _TOLERANCE_KEUR as STATEMENT_TOL
from financial_engine.project_returns.model import _TOL as RETURN_TOL

SOLVER_TOL = Decimal("1e-4")  # clean Senior policy convergence_tolerance_keur
OPERATING_TOL = Decimal("1e-9")  # non-iterated float arithmetic vs 60-digit Decimal


def dec(x):
    return Decimal(repr(float(x)))


def build(kind="solar", frequency="Q", fc=date(2030, 1, 31), months=None, **financing):
    """Supported quarterly fixture: actual-COD on a quarter end, equity-only, no reserve."""
    from app import project_factories as pf
    from finco_core.inputs import PeriodFrequency, SponsorFundingMode
    from finco_core.inputs._models import QuarterlyProjectInfo
    pi = getattr(pf, "create_generic_" + kind + "_reference")()
    months = months or pi.info.construction_months
    cod = fc + relativedelta(months=months)
    fin = dataclasses.replace(pi.financing, sponsor_funding_mode=SponsorFundingMode.EQUITY_ONLY,
                              shl_amount_keur=0.0, clean_shl_principal_keur=0.0, dsra_months=0, **financing)
    timeline = dict(financial_close=fc, construction_months=months, cod_date=cod)
    if frequency == "Q":
        values = {f.name: getattr(pi.info, f.name) for f in dataclasses.fields(pi.info)}
        values.update(timeline, period_frequency=PeriodFrequency.QUARTERLY)
        info = QuarterlyProjectInfo(**values, operating_calendar_policy=quarterly_candidate_policy())
    else:
        info = dataclasses.replace(pi.info, **timeline)
    return dataclasses.replace(pi, info=info, financing=fin)


_RUNS: dict = {}


def canonical_run(pi, source_id="rc7b_quarterly_acceptance"):
    """The canonical engine path exactly as the production authority composes it.

    Generic financing policy -> shareholder waterfall (G2C) -> decision-complete
    statements. Product admission is an application gate and is not part of the
    engine under test here; the app-level refusal is covered by Workstream C.
    """
    from types import SimpleNamespace
    from financial_engine.financial_statements import assemble_decision_complete_financial_statements
    from financial_engine.financing.generic_product_policy import (
        DEFAULT_GENERIC_FINANCING_POLICY, run_with_generic_financing_policy,
    )
    from financial_engine.run_scope import engine_run_scope
    from financial_engine.shareholder_waterfall import run_project_shareholder_waterfall_model
    with engine_run_scope():
        g2c, applied, evidence = run_with_generic_financing_policy(
            pi, lambda a: run_project_shareholder_waterfall_model(a, source_id=source_id),
            DEFAULT_GENERIC_FINANCING_POLICY)
    statements = assemble_decision_complete_financial_statements(g2c, applied)
    return SimpleNamespace(g2c_result=g2c, project_inputs=applied, financial_statements_result=statements,
                           policy_evidence=evidence)


def run(kind, frequency):
    key = (kind, frequency)
    if key not in _RUNS:
        _RUNS[key] = canonical_run(build(kind, frequency))
    return _RUNS[key]


def test_canonical_composition_equals_the_released_production_authority_for_six_months():
    """The test composition is the production composition (proved on the released 6/6 run)."""
    import dataclasses as dc
    from app.services import production_financial_authority as authority
    authority._POLICY_RUN_CACHE.clear()
    released = authority.run_clean_production(build("solar", "S"))
    composed = canonical_run(build("solar", "S"), source_id="pr8_clean_production_authority")
    assert dc.asdict(composed.g2c_result) == dc.asdict(released.g2c_result)
    assert composed.financial_statements_result == released.financial_statements_result


def reference(kind):
    """Independent oracle; construction/Uses taken from the RELEASED 6/6 run."""
    from financial_engine.adapters.project_inputs import from_project_inputs
    semi = run(kind, "S")
    financing = semi.g2c_result.financing_result
    dep = from_project_inputs(semi.project_inputs).depreciation
    pi = build(kind, "Q")
    debt = oracle.senior(pi, total_project_uses_keur=financing.project_uses.total_project_uses_keur,
                         dep_items=dep.tax_capex_items_for_depreciation,
                         financial_cost_life=dep.financial_cost_useful_life_years)
    return pi, debt, financing, dep


def operating_slice(result):
    model = result.g2c_result.financing_result.project_model_result
    first = next(i for i, p in enumerate(model.periods) if p.is_operation)
    return model, first


KINDS = ["solar", "wind"]


# ── construction / funding handoff ───────────────────────────────────────────

@pytest.mark.parametrize("kind", KINDS)
def test_construction_funding_and_uses_are_identical_under_both_frequencies(kind):
    semi, quarter = run(kind, "S"), run(kind, "Q")
    a, b = semi.g2c_result.financing_result, quarter.g2c_result.financing_result
    assert a.construction_financing == b.construction_financing  # dates, draws, IDC, fees
    assert a.construction_funding == b.construction_funding
    assert a.project_uses == b.project_uses
    assert a.final_senior_commitment_keur == b.final_senior_commitment_keur
    fs_a, fs_b = semi.financial_statements_result, quarter.financial_statements_result
    assert fs_a.construction_funding_rows == fs_b.construction_funding_rows
    assert fs_a.non_construction_fc_row == fs_b.non_construction_fc_row
    # Construction model columns are identical as well (no frequency-driven dates).
    cons = lambda r: [p for p in r.g2c_result.financing_result.project_model_result.periods if p.is_construction]
    assert [(p.period_start, p.period_end) for p in cons(semi)] == [(p.period_start, p.period_end) for p in cons(quarter)]


@pytest.mark.parametrize("kind", KINDS)
def test_opening_operational_senior_equals_actual_project_funding(kind):
    quarter = run(kind, "Q")
    financing = quarter.g2c_result.financing_result
    fs = quarter.financial_statements_result
    draws = sum(dec(r.senior_draw_keur) for r in fs.construction_funding_rows)
    if fs.non_construction_fc_row is not None:
        draws += dec(fs.non_construction_fc_row.senior_draw_keur)
    opening = dec(financing.project_model_result.senior_debt.senior_debt_opening_keur[0])
    assert opening > 0  # the research zero-opening simplification is not in the Run
    assert abs(opening - draws) <= Decimal(repr(FUNDING_TOL))
    assert abs(opening - dec(financing.final_senior_commitment_keur)) <= Decimal(repr(FUNDING_TOL))
    for row in fs.construction_funding_rows:
        assert abs(row.sources_uses_difference_keur) <= FUNDING_TOL


# ── quarterly operating, tax, CFADS and Senior against the oracle ────────────

@pytest.mark.parametrize("kind", KINDS)
def test_operating_schedules_match_independent_decimal_reference(kind):
    pi, debt, financing_semi, dep = reference(kind)
    model, first = operating_slice(run(kind, "Q"))
    rows = oracle.operating_rows(pi.info, int(pi.revenue.ppa_term_years))
    ops = oracle.operating(pi, rows, "P50")
    # Book basis (hard CAPEX + capitalised IDC/fees) is the released construction
    # result of the 6/6 run; it is identical for the quarterly run.
    basis = financing_semi.book_depreciable_asset_basis
    assert run(kind, "Q").g2c_result.financing_result.book_depreciable_asset_basis == basis
    book = oracle.depreciation(basis.components, dep.financial_cost_useful_life_years, pi.info.horizon_years, rows)
    engine_ops = model.periods[first:]
    assert len(engine_ops) == len(rows) == 4 * pi.info.horizon_years
    for p, r, o, dep_value, book_value in zip(engine_ops, rows, ops, debt.tax_dep, book):
        assert (p.period_start, p.period_end, p.days_in_period) == (r.start, r.end, r.days)
        assert abs(dec(p.production_mwh) - o["mwh"]) <= OPERATING_TOL * 1000
        for field, expected in (("revenue_keur", o["revenue"]), ("opex_keur", o["opex"]),
                                ("ebitda_keur", o["ebitda"]), ("tax_depreciation_keur", dep_value),
                                ("book_depreciation_keur", book_value)):
            assert abs(dec(getattr(p, field)) - expected) <= OPERATING_TOL, (field, p.period_index)


@pytest.mark.parametrize("kind", KINDS)
def test_tax_is_one_annual_calendar_year_payment_not_divided_by_four(kind):
    pi, debt, _, _ = reference(kind)
    model, first = operating_slice(run(kind, "Q"))
    tax = model.tax_and_cfads
    cash = [dec(x) for x in tax.corporate_tax_cash_keur[first:]]
    rows = oracle.operating_rows(pi.info, int(pi.revenue.ppa_term_years))
    for value, expected, r in zip(cash, debt.base_cash_tax, rows):
        assert abs(value - expected) <= SOLVER_TOL
        last_day = r.end - timedelta(days=1)
        is_payment_row = last_day.month == 12 or r is rows[-1]
        if not is_payment_row:
            assert value == 0  # never 1/4 of an annual liability per quarter
    assert abs(dec(tax.terminal_unpaid_tax_keur)) <= Decimal(repr(STATEMENT_TOL))


@pytest.mark.parametrize("kind", KINDS)
def test_cfads_and_senior_schedule_match_independent_decimal_reference(kind):
    pi, debt, _, _ = reference(kind)
    model, first = operating_slice(run(kind, "Q"))
    senior, sizing = model.senior_debt, model.debt_sizing
    assert abs(dec(senior.debt_size_keur) - debt.debt) <= SOLVER_TOL
    assert senior.binding_constraint in ("GEARING", "DSCR", "BOTH")
    expected_binding = "GEARING" if debt.gearing_capacity < debt.dscr_capacity else "DSCR"
    assert senior.binding_constraint == expected_binding
    assert abs(dec(model.tax_and_cfads.cfads_keur[first + 5]) - debt.base_cfads[5]) <= SOLVER_TOL
    for k, row in enumerate(debt.rows):
        for field, key in (("senior_debt_opening_keur", "opening"), ("senior_interest_keur", "interest"),
                           ("senior_principal_keur", "principal"), ("senior_debt_service_keur", "service"),
                           ("senior_debt_closing_keur", "closing")):
            assert abs(dec(getattr(senior, field)[k]) - row[key]) <= SOLVER_TOL, (field, k)
        assert abs(dec(sizing.bank_cfads_keur[first + k]) - debt.bank_cfads[k]) <= SOLVER_TOL
        assert abs(dec(model.tax_and_cfads.cfads_keur[first + k]) - debt.base_cfads[k]) <= SOLVER_TOL
        if row["service"] > 0:
            dscr = senior.base_dscr[k]
            assert abs(dec(dscr) - debt.base_cfads[k] / row["service"]) <= Decimal("1e-6")


@pytest.mark.parametrize("kind", KINDS)
def test_interest_accrues_on_actual_quarter_dates_with_contractual_day_count(kind):
    pi = build(kind, "Q")
    model, first = operating_slice(run(kind, "Q"))
    senior = model.senior_debt
    rate = dec(pi.financing.senior_debt_interest_config.rate_schedule.explicit_all_in_rates[0])
    basis = 360 if pi.financing.senior_debt_interest_config.day_count.name == "ACT_360" else 365
    periods = {p.period_index: p for p in model.periods}
    for idx, opening, interest in zip(senior.period_indices, senior.senior_debt_opening_keur, senior.senior_interest_keur):
        p = periods[idx]
        expected = dec(opening) * rate * Decimal((p.period_end - p.period_start).days) / Decimal(basis)
        assert abs(dec(interest) - expected) <= OPERATING_TOL
        assert not (91 * dec(opening) * rate / 360 < dec(interest) / 2)  # never a half-year accrual


@pytest.mark.parametrize("kind", KINDS)
def test_maturity_is_a_quarterly_service_endpoint_and_debt_is_fully_repaid(kind):
    pi = build(kind, "Q")
    model, first = operating_slice(run(kind, "Q"))
    senior = model.senior_debt
    rows = oracle.operating_rows(pi.info, int(pi.revenue.ppa_term_years))
    tenor_rows = pi.financing.senior_tenor_years * 4
    assert len(senior.period_indices) == tenor_rows
    periods = {p.period_index: p for p in model.periods}
    assert periods[senior.period_indices[-1]].period_end == rows[tenor_rows - 1].end
    assert abs(senior.senior_debt_closing_keur[-1]) <= FUNDING_TOL
    total = sum(dec(x) for x in senior.senior_principal_keur)
    assert abs(total - dec(senior.debt_size_keur)) <= Decimal(repr(FUNDING_TOL))
    for opening, principal, closing in zip(senior.senior_debt_opening_keur, senior.senior_principal_keur,
                                           senior.senior_debt_closing_keur):
        assert abs(dec(opening) - dec(principal) - dec(closing)) <= OPERATING_TOL


# ── statements ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", KINDS)
def test_statements_are_complete_and_reconcile_on_quarterly_dates(kind):
    from financial_engine.financial_statements.contracts import StatementStatus
    from financial_engine.financing.generic_product_policy import build_sources_and_uses
    quarter = run(kind, "Q")
    fs = quarter.financial_statements_result
    model, first = operating_slice(quarter)
    for status in (fs.status, fs.income_statement_status, fs.tax_bridge_status, fs.cash_flow_status,
                   fs.fixed_asset_status, fs.retained_earnings_status, fs.balance_sheet_status):
        assert status is StatementStatus.OK
    assert fs.unavailable_reasons == {}
    assert len(fs.balance_sheet_periods) == len(model.periods)
    checks = [p.balance_check_keur for p in fs.balance_sheet_periods if p.balance_check_keur is not None]
    assert len(checks) >= 4 * build(kind, "Q").info.horizon_years
    assert max(abs(x) for x in checks) <= STATEMENT_TOL  # Assets = Liabilities + Equity
    sources_uses = build_sources_and_uses(quarter.g2c_result.financing_result)
    assert sources_uses.difference_keur == 0.0
    assert sources_uses.initial_dsra_funding_keur == 0.0 and sources_uses.shareholder_loan_cash_keur == 0.0
    # Income statement dates are the quarterly axis; flows roll into stocks.
    income = fs.income_statement_periods
    assert [p.period_end for p in income] == [p.period_end for p in model.periods]
    cumulative = Decimal(0)
    for p, fa in zip(income, fs.fixed_asset_periods):
        cumulative += dec(p.book_depreciation_keur)
        assert abs(dec(fa.accumulated_book_depreciation_keur) - cumulative) <= Decimal(repr(STATEMENT_TOL))
    for bs, waterfall in zip(fs.balance_sheet_periods, fs.pf_cash_waterfall_periods):
        if bs.senior_debt_balance_keur is not None:
            assert bs.senior_debt_balance_keur >= -STATEMENT_TOL
        assert abs(waterfall.fcf_banks_keur - waterfall.senior_debt_service_keur - waterfall.post_senior_cash_keur) <= STATEMENT_TOL


@pytest.mark.parametrize("kind", KINDS)
def test_project_return_matches_independent_dated_xirr(kind):
    pi, _, financing_semi, dep = reference(kind)
    construction = financing_semi.construction_financing  # released 6/6 authority (proved identical)
    hard_capex = list(zip(construction.period_end_dates, construction.hard_capex_uses_keur))
    dates, flows = oracle.unlevered_project_flows(pi, hard_capex_rows=hard_capex, dep_items=dep.tax_capex_items_for_depreciation,
                                                  financial_cost_life=dep.financial_cost_useful_life_years)
    expected = oracle.xirr(dates, flows)
    project = run(kind, "Q").g2c_result.return_summary.project
    assert project.project_xirr_status.value == "OK"
    assert abs(dec(project.project_xirr) - expected) <= Decimal(repr(RETURN_TOL))
    engine_rows = project.cashflows
    assert [r.cashflow_date for r in engine_rows] == dates
    for row, flow in zip(engine_rows, flows):
        assert abs(dec(row.net_unlevered_project_cashflow_keur) - flow) <= SOLVER_TOL


@pytest.mark.parametrize("kind", KINDS)
def test_sponsor_return_arithmetic_on_quarterly_dates_is_disclosed_pending_d08(kind):
    """Sponsor XIRR recomputed in Decimal from the engine's dated sponsor flows.

    This verifies return arithmetic and cash conservation only; the quarterly
    distribution eligibility policy (D-08) remains OPEN and is disclosed in Run
    evidence, so Sponsor returns are not relied upon for release.
    """
    g2c = run(kind, "Q").g2c_result
    assert g2c.total_sponsor_xirr_status.value == "OK"
    dated = {}
    for row in g2c.waterfall_periods:
        dated[row.cashflow_date] = dated.get(row.cashflow_date, Decimal(0)) + dec(row.total_sponsor_net_cashflow_keur)
    dates = sorted(dated)
    expected = oracle.xirr(dates, [dated[d] for d in dates])
    assert abs(dec(g2c.total_sponsor_xirr) - expected) <= Decimal(repr(RETURN_TOL))
    # Cash conservation: every post-Senior quarter is distributed, locked or retained.
    operating = [r for r in g2c.waterfall_periods if not r.is_construction]
    model, first = operating_slice(run(kind, "Q"))
    assert [r.cashflow_date for r in operating] == [p.period_end for p in model.periods[first:]]
    assert g2c.return_summary.total_sponsor.xirr == g2c.total_sponsor_xirr


# ── refusals: everything outside the candidate scope fails before calculation ─

def _scope(pi):
    from financial_engine.financing.quarterly_scope import require_supported_quarterly_project
    require_supported_quarterly_project(pi)


def test_supported_fixture_is_inside_scope():
    _scope(build("solar"))
    _scope(build("wind"))


@pytest.mark.parametrize("change,code", [
    (lambda pi: _fin(pi, sponsor_funding_mode=_sfm().SHARE_CAPITAL_THEN_SHL), "QUARTERLY_SHL_UNSUPPORTED"),
    (lambda pi: _fin(pi, shl_amount_keur=100.0), "QUARTERLY_SHL_UNSUPPORTED"),
    (lambda pi: _fin(pi, dsra_months=6), "QUARTERLY_RESERVE_POLICY_PENDING_D09"),
    (lambda pi: _fin(pi, debt_service_reserve_requirement_keur=10.0), "QUARTERLY_RESERVE_POLICY_PENDING_D09"),
    (lambda pi: _fin(pi, junior_or_other_project_funding_keur=10.0), "QUARTERLY_FACILITY_COMBINATION_UNSUPPORTED"),
    (lambda pi: _rev(pi, first_merchant_operating_period_index=4), "QUARTERLY_LEGACY_PERIOD_VECTOR_UNSUPPORTED"),
    (lambda pi: _rev(pi, ppa_tariff_by_operating_period=(50.0,) * 10), "QUARTERLY_LEGACY_PERIOD_VECTOR_UNSUPPORTED"),
    (lambda pi: _rev(pi, co2_sales_schedule=_sched(semiannual_values=(1.0, 2.0))), "QUARTERLY_LEGACY_PERIOD_VECTOR_UNSUPPORTED"),
    (lambda pi: _rev(pi, balancing_cost_schedule=_sched(semiannual_values=(1.0,))), "QUARTERLY_LEGACY_PERIOD_VECTOR_UNSUPPORTED"),
    (lambda pi: _rev(pi, market_price_calendar_start_year=2031, market_prices_by_calendar_year_eur_mwh=(50.0,)),
     "QUARTERLY_REVENUE_CONTRACT_HANDOFF_REQUIRED"),
    (lambda pi: _rev(pi, ppa_indexation_start_date=date(2032, 1, 1)), "QUARTERLY_PPA_INDEXATION_HANDOFF_REQUIRED"),
    (lambda pi: _rev(pi, ppa_term_years=10.5), "QUARTERLY_PPA_TERM_UNSUPPORTED"),
    (lambda pi: _tax(pi, atad_enabled=True), "QUARTERLY_TAX_POLICY_UNSUPPORTED"),
    (lambda pi: _tax(pi, thin_cap_enabled=True), "QUARTERLY_TAX_POLICY_UNSUPPORTED"),
    (lambda pi: dataclasses.replace(pi, technical=dataclasses.replace(pi.technical, bess_enabled=True)),
     "QUARTERLY_TECHNOLOGY_UNSUPPORTED"),
])
def test_out_of_scope_quarterly_configurations_are_refused(change, code):
    from financial_engine.financing.quarterly_scope import QuarterlyScopeUnsupported
    with pytest.raises(QuarterlyScopeUnsupported, match=code):
        _scope(change(build("solar")))


def test_intra_quarter_ppa_expiry_is_refused_not_split():
    from financial_engine.financing.quarterly_scope import QuarterlyScopeUnsupported
    # FC 31 Dec 2029 + 14 months = COD 28 Feb 2031; the PPA anniversary is mid-quarter.
    with pytest.raises(QuarterlyScopeUnsupported, match="QUARTERLY_INTRAPERIOD_PPA_EXPIRY_UNSUPPORTED"):
        _scope(build("solar", fc=date(2029, 12, 31)))


def test_periodic_valuation_rate_is_refused():
    from finco_core.inputs.valuation import (
        CoverageCalculationDatePolicy, DebtCoverageValuationPolicy, DiscountConvention, ValuationPolicies,
    )
    from financial_engine.financing.quarterly_scope import QuarterlyScopeUnsupported
    pi = build("solar")
    coverage = DebtCoverageValuationPolicy(annual_discount_rate=0.06, cfads_case=None,
                                           calculation_date_policy=list(CoverageCalculationDatePolicy)[0],
                                           discount_convention=DiscountConvention.PERIODIC_COMPOUNDING,
                                           authority_label="test")
    with pytest.raises(QuarterlyScopeUnsupported, match="QUARTERLY_VALUATION_CONVENTION_UNSUPPORTED"):
        _scope(dataclasses.replace(pi, valuation=ValuationPolicies(coverage=coverage)))


def test_six_month_authored_senior_vectors_are_refused_not_regridded():
    from finco_core.inputs.senior_rate_schedule import SeniorRateSchedule
    pi = build("solar")
    cfg = pi.financing.senior_debt_interest_config
    stepped = dataclasses.replace(cfg, rate_schedule=dataclasses.replace(
        cfg.rate_schedule, explicit_all_in_rates=(0.05,) * 15 + (0.06,) * 15))
    with pytest.raises(Exception, match="QUARTERLY_SENIOR_RATE_VECTOR_REGRID_UNSUPPORTED"):
        _run_financing(_fin(pi, senior_debt_interest_config=stepped))
    sculpt = dataclasses.replace(pi.financing.senior_sculpting_config, target_dscr_schedule=(1.3,) * 30)
    with pytest.raises(Exception, match="QUARTERLY_SENIOR_PERIOD_VECTOR_UNSUPPORTED"):
        _run_financing(_fin(pi, senior_sculpting_config=sculpt))
    assert SeniorRateSchedule  # imported type exists


def test_canonical_engine_entry_refuses_out_of_scope_quarterly_project():
    from financial_engine.financing.quarterly_scope import QuarterlyScopeUnsupported
    with pytest.raises(QuarterlyScopeUnsupported, match="QUARTERLY_RESERVE_POLICY_PENDING_D09"):
        canonical_run(_fin(build("solar"), dsra_months=6))
    with pytest.raises(QuarterlyScopeUnsupported, match="QUARTERLY_SHL_UNSUPPORTED"):
        canonical_run(_fin(build("solar"), sponsor_funding_mode=_sfm().SHARE_CAPITAL_THEN_SHL,
                           shl_amount_keur=500.0, clean_shl_principal_keur=500.0))


def test_direct_financing_entry_is_gated_too():
    with pytest.raises(Exception, match="QUARTERLY_RESERVE_POLICY_PENDING_D09"):
        _run_financing(_fin(build("solar"), dsra_months=6))


def _run_financing(pi):
    from financial_engine.financing.generic_product_policy import DEFAULT_GENERIC_FINANCING_POLICY, apply_generic_financing_policy
    from financial_engine.financing.project import run_project_financing_model
    try:
        applied, _, _ = apply_generic_financing_policy(pi, DEFAULT_GENERIC_FINANCING_POLICY)
    except Exception:
        applied = pi
    return run_project_financing_model(applied)


def _sfm():
    from finco_core.inputs import SponsorFundingMode
    return SponsorFundingMode


def _sched(**kw):
    from finco_core.inputs._models import RevenueAdjustmentSchedule
    return RevenueAdjustmentSchedule(**kw)


def _fin(pi, **kw):
    return dataclasses.replace(pi, financing=dataclasses.replace(pi.financing, **kw))


def _rev(pi, **kw):
    return dataclasses.replace(pi, revenue=dataclasses.replace(pi.revenue, **kw))


def _tax(pi, **kw):
    return dataclasses.replace(pi, tax=dataclasses.replace(pi.tax, **kw))
