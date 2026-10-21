"""Quarterly institutional acceptance — Scenario C: Senior interest, sculpting, DSCR, repayment calendar, maturity and distributable cash.

Three independent layers are used and none is read back to form its own expectation:

1. the Decimal Senior oracle (``rc7b_quarterly_oracle.senior``) re-solves sizing, the tax-interest fixed point and the sculpted roll-forward from the inputs;
2. arithmetic identities between the engine's own debt rows and the independent date axis (interest = opening * rate * actual days / basis, ...);
3. cross-ledger identities (debt service in the waterfall, balance sheet, statements).
"""
from __future__ import annotations

import pytest

import quarterly_acceptance_support as Q
import rc7b_quarterly_oracle as oracle

D = Q.D


@pytest.fixture(params=Q.IDS)
def sid(request):
    return request.param


def _senior_oracle(pi, result):
    from financial_engine.adapters.project_inputs import from_project_inputs
    dep = from_project_inputs(result.project_inputs).depreciation
    return oracle.senior(pi, total_project_uses_keur=result.g2c_result.financing_result.project_uses.total_project_uses_keur,
                         dep_items=dep.tax_capex_items_for_depreciation, financial_cost_life=dep.financial_cost_useful_life_years)


def test_senior_size_and_every_service_row_equal_the_decimal_oracle(sid):
    pi, result = Q.run(Q.scenario(sid), "Q")
    ref = _senior_oracle(pi, result)
    rows = Q.senior_rows(result)
    financing = result.g2c_result.financing_result
    assert abs(Q.d(financing.final_senior_commitment_keur) - ref.debt) < Q.SOLVER_TOL
    assert len(rows) == len(ref.rows)
    for want, got in zip(ref.rows, rows):
        for key in ("opening", "interest", "principal", "service", "closing"):
            assert abs(want[key] - got[key]) < Q.SOLVER_TOL, (sid, got["period"].period_end, key, want[key], got[key])


def test_interest_accrues_on_actual_days_of_each_quarter_and_the_stub_row(sid):
    pi, result = Q.run(Q.scenario(sid), "Q")
    rate, basis = Q.senior_rate(pi), Q.day_count_basis(pi)
    for row in Q.senior_rows(result):
        p = row["period"]
        want = row["opening"] * rate * D((p.period_end - p.period_start).days) / D(basis)
        assert abs(row["interest"] - want) < Q.SOLVER_TOL, (p.period_start, p.period_end)


def test_roll_forward_identities_hold_on_every_row(sid):
    _, result = Q.run(Q.scenario(sid), "Q")
    rows = Q.senior_rows(result)
    debt = Q.d(result.g2c_result.financing_result.final_senior_commitment_keur)
    assert abs(rows[0]["opening"] - debt) < Q.IDENTITY_TOL
    for k, row in enumerate(rows):
        assert abs(row["service"] - (row["interest"] + row["principal"])) < Q.IDENTITY_TOL
        assert abs(row["closing"] - (row["opening"] - row["principal"])) < Q.IDENTITY_TOL
        assert row["principal"] >= -Q.IDENTITY_TOL and row["closing"] >= -Q.IDENTITY_TOL and row["interest"] >= 0
        if k:
            assert abs(row["opening"] - rows[k - 1]["closing"]) < Q.IDENTITY_TOL                # no balance created or lost between quarters
    assert abs(sum(r["principal"] for r in rows) - debt) < Q.SOLVER_TOL                         # the whole commitment is repaid, no balloon, no residual


def test_repayment_calendar_is_the_quarterly_axis_up_to_the_matched_six_month_maturity(sid):
    pi, result = Q.run(Q.scenario(sid), "Q")
    expected = [r for r in Q.calendar_oracle(pi.info.cod_date, pi.info.horizon_years)
                if r.end <= Q.senior_maturity_oracle(pi.info.cod_date, pi.financing.senior_tenor_years)]
    rows = Q.senior_rows(result)
    assert [(r["period"].period_start, r["period"].period_end) for r in rows] == [(e.start, e.end) for e in expected]
    ends = [r["period"].period_end for r in rows]
    assert ends == sorted(set(ends))                                                           # strictly increasing, none duplicated at a year boundary
    assert ends[-1] == Q.senior_maturity_oracle(pi.info.cod_date, pi.financing.senior_tenor_years)
    model = Q.model_of(result)
    for p in model.periods:                                                                    # nothing after maturity, nothing during construction
        if p.period_end > ends[-1] or p.is_construction:
            assert p.period_index not in model.senior_debt.period_indices


def test_dscr_is_computed_from_the_cfads_of_the_same_period_and_respects_the_target(sid):
    pi, result = Q.run(Q.scenario(sid), "Q")
    model = Q.model_of(result)
    cfads = dict(zip(model.tax_and_cfads.period_indices, model.tax_and_cfads.cfads_keur))
    target = Q.d(pi.financing.target_dscr)
    for row in Q.senior_rows(result):
        if row["service"] <= Q.IDENTITY_TOL:
            continue
        index = row["period"].period_index
        assert abs(Q.d(row["dscr"]) - Q.d(cfads[index]) / row["service"]) < D("1e-9") * max(D(1), Q.d(row["dscr"]))
        assert Q.d(row["dscr"]) >= target - D("1e-6"), (row["period"].period_end, row["dscr"])  # the base case never falls below the sculpting target


@pytest.mark.parametrize("sid", Q.DSCR_BOUND_IDS)
def test_sculpted_service_equals_bank_cfads_over_target_while_debt_remains(sid):
    pi, result = Q.run(Q.scenario(sid), "Q")
    assert Q.model_of(result).senior_debt.binding_constraint == "DSCR"
    ref = _senior_oracle(pi, result)
    target = Q.d(pi.financing.target_dscr)
    rows = Q.senior_rows(result)
    for k, (want, got) in enumerate(zip(ref.rows, rows)):
        allowed = max(D(0), ref.bank_cfads[k] / target)
        assert got["service"] <= allowed + Q.SOLVER_TOL                                       # never above the sculpted capacity
        if got["closing"] > Q.SOLVER_TOL and k < len(rows) - 1:
            assert abs(got["service"] - allowed) < Q.SOLVER_TOL                                 # full sculpting while a balance remains
    assert rows[-1]["closing"] < Q.SOLVER_TOL                                                   # capacity sizing retires the loan exactly at maturity


@pytest.mark.parametrize("sid", Q.GEARING_BOUND_IDS)
def test_gearing_bound_loans_retire_early_and_service_stops_without_a_balloon(sid):
    pi, result = Q.run(Q.scenario(sid), "Q")
    assert Q.model_of(result).senior_debt.binding_constraint == "GEARING"
    ref = _senior_oracle(pi, result)
    assert ref.gearing_capacity < ref.dscr_capacity                                          # the independent oracle agrees that sculpting is not binding
    rows = Q.senior_rows(result)
    first_zero = next(k for k, r in enumerate(rows) if r["closing"] <= Q.SOLVER_TOL)
    assert first_zero < len(rows) - 1
    assert all(r["service"] <= Q.SOLVER_TOL for r in rows[first_zero + 1:])


def test_senior_balance_on_the_balance_sheet_follows_the_debt_schedule(sid):
    _, result = Q.run(Q.scenario(sid), "Q")
    rows = {r["period"].period_index: r for r in Q.senior_rows(result)}
    last = max(rows)
    for line in result.financial_statements_result.balance_sheet_periods:
        if line.period_index in rows:
            assert abs(Q.d(line.senior_debt_balance_keur) - rows[line.period_index]["closing"]) < Q.IDENTITY_TOL
        elif line.period_index > last:
            assert abs(Q.d(line.senior_debt_balance_keur)) < Q.SOLVER_TOL      # solver residue (<= convergence_tolerance_keur) only; no balloon


def test_distributable_cash_is_cfads_less_senior_service_and_is_distributed_once(sid):
    _, result = Q.run(Q.scenario(sid), "Q")
    model = Q.model_of(result)
    post = model.post_senior_cash
    cfads = dict(zip(model.tax_and_cfads.period_indices, model.tax_and_cfads.cfads_keur))
    service = dict(zip(model.senior_debt.period_indices, model.senior_debt.senior_debt_service_keur))
    waterfall = {line.period_index: line for line in result.financial_statements_result.pf_cash_waterfall_periods}
    distributed = D(0)
    construction = {p.period_index for p in Q.construction_periods(result)}
    for k, index in enumerate(post.period_indices):
        if index in construction:
            continue                                   # construction columns carry funding rows, not operating cash (identical to 6/6)
        want = Q.d(cfads[index]) - Q.d(service.get(index, 0.0))
        assert abs(Q.d(post.cash_after_senior_before_reserves_keur[k]) - want) < Q.IDENTITY_TOL
        line = waterfall[index]
        assert abs(Q.d(line.senior_debt_service_keur) - Q.d(service.get(index, 0.0))) < Q.IDENTITY_TOL
        assert abs(Q.d(line.post_senior_cash_keur) - want) < Q.IDENTITY_TOL
        distributed += Q.d(line.legal_equity_distribution_keur)
    # EQUITY_ONLY, no reserves, lock-up never triggered in these fixtures: every euro of post-senior cash reaches the sponsor exactly once
    assert result.g2c_result.periods_locked_by_dscr == 0
    assert abs(distributed - Q.d(result.g2c_result.total_legal_equity_distributions_keur)) < Q.IDENTITY_TOL
    operating_post = sum(Q.d(x) for i, x in zip(post.period_indices, post.cash_after_senior_before_reserves_keur) if i not in construction)
    assert abs(distributed - operating_post) < Q.D("1e-4")


def test_total_debt_service_is_conserved_across_model_senior_waterfall_and_statements(sid):
    _, result = Q.run(Q.scenario(sid), "Q")
    model = Q.model_of(result)
    total = sum(Q.d(x) for x in model.senior_debt.senior_debt_service_keur)
    assert abs(total - sum(Q.d(l.senior_debt_service_keur) for l in result.financial_statements_result.pf_cash_waterfall_periods)) < Q.IDENTITY_TOL
    interest = sum(Q.d(x) for x in model.senior_debt.senior_interest_keur)
    assert abs(interest - sum(Q.d(l.senior_cash_interest_keur) for l in result.financial_statements_result.pf_cash_waterfall_periods)) < Q.IDENTITY_TOL
