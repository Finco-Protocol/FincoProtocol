"""Quarterly institutional acceptance — Scenario D: depreciation-to-balance-sheet chain, calendar-year tax, cash-flow reconciliation, equity returns.

Independent expectations: the Decimal oracle (tax ledger, Senior, XIRR) and double-entry identities between the statements. A statement
imbalance is never tolerated away: the one family that exhibits it (financial close on 30/31 December) is declared, asserted identical under 6/6
(so it is not a quarterly defect) and carried as a strict-xfail reproduction for the owner of the shared statements code (finding Q-F-02).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

import quarterly_acceptance_support as Q
import rc7b_quarterly_oracle as oracle
from financial_engine.financial_statements.contracts import StatementStatus
from financial_engine.project_returns.model import _TOL as RETURN_TOL

D = Q.D


@pytest.fixture(params=Q.IDS)
def sid(request):
    return request.param


def year_end_close(sid) -> bool:
    fc = Q.project(Q.scenario(sid), "S").info.financial_close
    return fc.month == 12 and fc.day >= 30


YEAR_END_FC_IDS = [i for i in Q.IDS if year_end_close(i)]
BALANCED_IDS = [i for i in Q.IDS if i not in YEAR_END_FC_IDS]


def _statements(sid, frequency="Q"):
    _, result = Q.run(Q.scenario(sid), frequency)
    return result, result.financial_statements_result


def test_income_statement_lines_equal_the_model_rows_and_foot(sid):
    result, fs = _statements(sid)
    model = Q.model_of(result)
    periods = {p.period_index: p for p in model.periods}
    debt = {r["period"].period_index: r for r in Q.senior_rows(result)}
    assert [p.period_end for p in fs.income_statement_periods] == [p.period_end for p in model.periods]
    for line in fs.income_statement_periods:
        if line.is_construction:
            continue
        p = periods[line.period_index]
        assert abs(Q.d(line.revenue_keur) - Q.d(p.revenue_keur)) < Q.IDENTITY_TOL
        assert abs(Q.d(line.opex_keur) - Q.d(p.opex_keur)) < Q.IDENTITY_TOL
        assert abs(Q.d(line.ebitda_keur) - (Q.d(line.revenue_keur) - Q.d(line.opex_keur))) < Q.IDENTITY_TOL
        assert abs(Q.d(line.ebit_keur) - (Q.d(line.ebitda_keur) - Q.d(line.book_depreciation_keur))) < Q.IDENTITY_TOL
        interest = debt[line.period_index]["interest"] if line.period_index in debt else D(0)
        assert abs(Q.d(line.senior_interest_expense_keur) - interest) < Q.IDENTITY_TOL
        assert abs(Q.d(line.earnings_before_tax_keur) - (Q.d(line.ebit_keur) + Q.d(line.net_financial_result_keur))) < Q.IDENTITY_TOL
        assert abs(Q.d(line.net_income_keur) - (Q.d(line.earnings_before_tax_keur) - Q.d(line.cit_accrual_keur))) < Q.IDENTITY_TOL


def test_cash_tax_equals_the_independent_calendar_year_ledger(sid):
    pi, result = Q.run(Q.scenario(sid), "Q")
    from financial_engine.adapters.project_inputs import from_project_inputs
    dep = from_project_inputs(result.project_inputs).depreciation
    ref = oracle.senior(pi, total_project_uses_keur=result.g2c_result.financing_result.project_uses.total_project_uses_keur,
                        dep_items=dep.tax_capex_items_for_depreciation, financial_cost_life=dep.financial_cost_useful_life_years)
    tax = Q.model_of(result).tax_and_cfads
    cash = dict(zip(tax.period_indices, tax.corporate_tax_cash_keur))
    ops = Q.operating_periods(result)
    assert len(ops) == len(ref.base_cash_tax)
    for want, p in zip(ref.base_cash_tax, ops):
        assert abs(Q.d(cash[p.period_index]) - want) < Q.SOLVER_TOL, p.period_end


def test_calendar_year_tax_is_paid_once_in_the_last_row_of_the_year_never_split_by_quarter(sid):
    pi, result = Q.run(Q.scenario(sid), "Q")
    tax = Q.model_of(result).tax_and_cfads
    cash = dict(zip(tax.period_indices, tax.corporate_tax_cash_keur))
    ops = Q.operating_periods(result)
    by_year: dict = {}
    for p in ops:
        by_year[(p.period_end - timedelta(days=1)).year] = p.period_index        # the row containing the last day of the tax year pays it
    payers = set(by_year.values())
    for p in ops:
        if p.period_index not in payers:
            assert abs(Q.d(cash[p.period_index])) < Q.IDENTITY_TOL, p.period_end
    # The construction stub of the first tax year is accrued before COD and paid in the first operating payment, so the accrual side includes it.
    accrual = sum(Q.d(l.cit_accrual_keur) for l in result.financial_statements_result.income_statement_periods)
    paid = sum(Q.d(cash[p.period_index]) for p in ops)
    assert abs(accrual - paid - Q.d(result.financial_statements_result.terminal_unpaid_tax_keur)) / paid < D("0.002")      # nothing paid twice or lost
    # Q-F-05 (P2, frequency-independent): the statements' accrual differs from the solver's cash tax by a few hundredths of a percent per year
    # under 6/6 as well; bound it by the released 6/6 relationship so a quarterly-only drift would fail.
    _, six = Q.run(Q.scenario(sid), "S")
    s_tax = Q.model_of(six).tax_and_cfads
    s_paid = sum(Q.d(x) for x in s_tax.corporate_tax_cash_keur)
    s_accrual = sum(Q.d(l.cit_accrual_keur) for l in six.financial_statements_result.income_statement_periods)
    assert abs(accrual - paid) / paid <= abs(s_accrual - s_paid) / s_paid + D("0.0005")


def test_loss_carry_forward_ledger_is_continuous_across_quarters(sid):
    _, fs = _statements(sid)
    bridge = fs.tax_bridge_periods
    for earlier, later in zip(bridge, bridge[1:]):
        if later.tax_loss_opening_keur is None or earlier.tax_loss_closing_keur is None:
            continue
        assert abs(Q.d(later.tax_loss_opening_keur) - Q.d(earlier.tax_loss_closing_keur)) < Q.IDENTITY_TOL
    for line in bridge:
        if line.tax_loss_opening_keur is None:
            continue
        assert Q.d(line.tax_loss_used_keur) >= -Q.IDENTITY_TOL and Q.d(line.tax_loss_closing_keur) >= -Q.IDENTITY_TOL


def test_cash_flow_waterfall_reconciles_operating_cash_to_post_senior_cash(sid):
    result, fs = _statements(sid)
    construction = {p.period_index for p in Q.construction_periods(result)}
    for line in fs.pf_cash_waterfall_periods:
        if line.period_index in construction:
            continue
        assert abs(Q.d(line.revenue_cash_keur) - Q.d(line.opex_cash_keur) - Q.d(line.ebitda_keur)) < Q.IDENTITY_TOL
        assert abs(Q.d(line.ebitda_keur) - Q.d(line.cash_tax_keur) - Q.d(line.fcf_banks_keur)) < Q.IDENTITY_TOL
        assert abs(Q.d(line.fcf_banks_keur) - Q.d(line.senior_debt_service_keur) - Q.d(line.post_senior_cash_keur)) < Q.IDENTITY_TOL
        assert abs(Q.d(line.senior_debt_service_keur) - Q.d(line.senior_cash_interest_keur) - Q.d(line.senior_principal_keur)) < Q.IDENTITY_TOL


def test_retained_earnings_and_tax_payable_roll_forward_without_gaps(sid):
    _, fs = _statements(sid)
    re_rows = fs.retained_earnings_periods
    for earlier, later in zip(re_rows, re_rows[1:]):
        assert abs(Q.d(later.opening_retained_earnings_keur) - Q.d(earlier.closing_retained_earnings_keur)) < Q.IDENTITY_TOL
    for row in re_rows:
        closing = (Q.d(row.opening_retained_earnings_keur) + Q.d(row.net_income_keur) - Q.d(row.legal_equity_distribution_keur or 0.0)
                   - Q.d(row.legal_reserve_allocation_keur or 0.0))
        assert abs(closing - Q.d(row.closing_retained_earnings_keur)) < Q.IDENTITY_TOL
    income = {l.period_index: l for l in fs.income_statement_periods}
    cash = {l.period_index: l for l in fs.pf_cash_waterfall_periods}
    sheet = [b for b in fs.balance_sheet_periods if b.balance_check_keur is not None]
    for earlier, later in zip(sheet, sheet[1:]):
        change = Q.d(later.net_cit_payable_keur) - Q.d(earlier.net_cit_payable_keur)
        cash_tax = Q.d(cash[later.period_index].cash_tax_keur or 0.0)
        assert abs(change - (Q.d(income[later.period_index].cit_accrual_keur) - cash_tax)) < Q.IDENTITY_TOL


@pytest.mark.parametrize("sid", BALANCED_IDS)
def test_balance_sheet_balances_on_every_quarter_and_statements_are_ok(sid):
    result, fs = _statements(sid)
    for status in (fs.status, fs.income_statement_status, fs.tax_bridge_status, fs.cash_flow_status, fs.fixed_asset_status,
                   fs.retained_earnings_status, fs.balance_sheet_status):
        assert status is StatementStatus.OK
    assert fs.unavailable_reasons == {}
    checks = [b.balance_check_keur for b in fs.balance_sheet_periods if b.balance_check_keur is not None]
    assert len(checks) == len(Q.operating_periods(result))                       # one balance check per operating quarter, none omitted
    assert max(abs(x) for x in checks) <= Q.IDENTITY_TOL
    assert fs.funding_audit["total_audit_residual_keur"] == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("sid", YEAR_END_FC_IDS)
def test_year_end_financial_close_imbalance_is_fail_closed_and_not_a_frequency_effect(sid):
    """Q-F-02: a financial close on 30/31 December leaves a constant opening imbalance in the SHARED statements code under 6/6 as well.

    Asserted: the engine reports it (never fail-open), the size is identical under both frequencies, and it is constant (an opening-balance
    carry, not an accumulating quarterly error). Fixed upstream -> this test fails and must be retired together with the xfail below.
    """
    imbalance = {}
    for frequency in "SQ":
        _, fs = _statements(sid, frequency)
        assert fs.status is StatementStatus.BALANCE_SHEET_DOES_NOT_BALANCE
        assert fs.balance_sheet_status is StatementStatus.BALANCE_SHEET_DOES_NOT_BALANCE
        assert "balance_sheet_identity" in fs.unavailable_reasons
        values = [b.balance_check_keur for b in fs.balance_sheet_periods if b.balance_check_keur is not None]
        assert max(values) - min(values) < 1e-6                                   # constant offset
        assert 0.1 < abs(values[0]) < 5.0                                           # < 0.015% of the project cost, never silent
        imbalance[frequency] = values[0]
    same_loan = (Q.run(Q.scenario(sid), "S")[1].g2c_result.financing_result.final_senior_commitment_keur
                 == Q.run(Q.scenario(sid), "Q")[1].g2c_result.financing_result.final_senior_commitment_keur)
    # equal loans -> equal imbalance; a DSCR-bound loan differs in size under 3/3 and so does the capitalised IDC the imbalance scales with (< 1%)
    assert abs(imbalance["S"] - imbalance["Q"]) < (1e-6 if same_loan else 0.01 * abs(imbalance["S"]))


@pytest.mark.xfail(strict=True, reason="Q-F-02: shared statements code leaves a constant opening imbalance for a 30/31 December financial close (identical under 6/6); "
                                       "reproduction for the shared-engine owner, outside this workstream")
@pytest.mark.parametrize("sid", YEAR_END_FC_IDS[:1])
def test_year_end_financial_close_should_balance(sid):
    _, fs = _statements(sid)
    assert max(abs(b.balance_check_keur) for b in fs.balance_sheet_periods if b.balance_check_keur is not None) <= Q.IDENTITY_TOL


def test_sponsor_xirr_equals_the_independent_dated_xirr_and_distributions_are_not_duplicated(sid):
    result, fs = _statements(sid)
    g2c = result.g2c_result
    assert g2c.total_sponsor_xirr_status.value == "OK"
    dated: dict = {}
    for row in g2c.waterfall_periods:
        dated[row.cashflow_date] = dated.get(row.cashflow_date, D(0)) + Q.d(row.total_sponsor_net_cashflow_keur)
    dates = sorted(dated)
    expected = Q.xirr_independent(dates, [dated[x] for x in dates])
    assert abs(float(g2c.total_sponsor_xirr) - expected) <= RETURN_TOL
    operating_dates = [r.cashflow_date for r in g2c.waterfall_periods if not r.is_construction]
    assert operating_dates == [p.period_end for p in Q.operating_periods(result)]
    assert len(set(operating_dates)) == len(operating_dates)                      # no duplicated flow at a quarter or year boundary
    distributed = sum(Q.d(l.legal_equity_distribution_keur) for l in fs.pf_cash_waterfall_periods if not l.is_construction)
    assert abs(distributed - Q.d(g2c.total_legal_equity_distributions_keur)) < Q.IDENTITY_TOL


def test_project_xirr_is_recomputed_from_the_dated_unlevered_flows(sid):
    result, _ = _statements(sid)
    project = result.g2c_result.return_summary.project
    assert project.project_xirr_status.value == "OK"
    dated: dict = {}
    for row in project.cashflows:
        dated[row.cashflow_date] = dated.get(row.cashflow_date, D(0)) + Q.d(row.net_unlevered_project_cashflow_keur)
    dates = sorted(dated)
    assert dates == [row.cashflow_date for row in project.cashflows] or len(dates) <= len(project.cashflows)
    expected = Q.xirr_independent(dates, [dated[x] for x in dates])
    assert abs(float(project.project_xirr) - expected) <= RETURN_TOL
