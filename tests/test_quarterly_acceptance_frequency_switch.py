"""Quarterly institutional acceptance — Scenario E: switching the same project between 6/6 and 3/3.

Separates what MUST be identical (alignment: dates, model years, cumulative operating cash at every common boundary) from what legitimately
differs because debt service and accrual dates are quarterly (Senior size, interest, DSCR path, returns). Every difference is bounded by an
explicit materiality limit and, for the operating side, explained exactly by the date-derived oracle in the operating module.
"""
from __future__ import annotations

import dataclasses
from dateutil.relativedelta import relativedelta

import pytest

import quarterly_acceptance_support as Q
import rc7b_quarterly_oracle as oracle
import rc7c_frequency_reconciliation as recon

D = Q.D


@pytest.fixture(params=Q.IDS)
def sid(request):
    return request.param


def test_only_the_calendar_frequency_and_policy_differ_between_the_two_projects(sid):
    scn = Q.scenario(sid)
    six, quarterly = Q.project(scn, "S"), Q.project(scn, "Q")
    assert quarterly.financing == six.financing and quarterly.revenue == six.revenue and quarterly.opex == six.opex
    assert quarterly.tax == six.tax and quarterly.technical == six.technical
    a, b = six.info, quarterly.info
    differing = {f.name for f in dataclasses.fields(b) if hasattr(a, f.name) and getattr(a, f.name) != getattr(b, f.name)}
    assert differing == {"period_frequency"}, differing
    assert not hasattr(a, "operating_calendar_policy") and b.operating_calendar_policy.version == "rc7c-quarterly-candidate-v2"


def test_alignment_dates_are_identical_and_every_six_month_boundary_is_a_quarter_boundary(sid):
    scn = Q.scenario(sid)
    _, six = Q.run(scn, "S")
    _, quarterly = Q.run(scn, "Q")
    q_ends = {p.period_end for p in Q.operating_periods(quarterly)}
    s_ends = [p.period_end for p in Q.operating_periods(six)]
    assert set(s_ends) <= q_ends                                                  # no six-month cash date is lost or moved when going quarterly
    assert Q.operating_periods(six)[0].period_start == Q.operating_periods(quarterly)[0].period_start
    assert len(q_ends) - len(s_ends) == len(Q.operating_periods(quarterly)) - len(Q.operating_periods(six))


def test_cumulative_operating_cash_difference_at_every_common_boundary_equals_the_oracle_explained_difference(sid):
    """EBITDA accumulated to each six-month boundary under 3/3 vs 6/6.

    Each engine curve equals the Decimal oracle on its OWN axis, so the difference between the curves is exactly the oracle's: zero unless the
    COD is the first of a month (D-02, the released axis counts the COD day) or a quarter-boundary PPA expiry falls inside a six-month row
    (D-05, the released axis keeps the PPA tariff for the whole row). Anything else would be an alignment defect.
    """
    scn = Q.scenario(sid)
    pi, six = Q.run(scn, "S")
    _, quarterly = Q.run(scn, "Q")
    ppa = int(pi.revenue.ppa_term_years)
    rows_s = recon.six_month_rows(pi.info, ppa)
    rows_q = oracle.operating_rows(Q.project(scn, "Q").info, ppa)
    want_s, want_q = oracle.operating(pi, rows_s, "P50"), oracle.operating(Q.project(scn, "Q"), rows_q, "P50")

    def cumulative(values, rows):
        total, out = D(0), {}
        for value, row in zip(values, rows):
            total += value
            out[row.end] = total
        return out

    exp_s = cumulative([w["ebitda"] for w in want_s], rows_s)
    exp_q = cumulative([w["ebitda"] for w in want_q], rows_q)
    eng_s = cumulative([Q.d(p.ebitda_keur) for p in Q.operating_periods(six)], rows_s)
    eng_q = cumulative([Q.d(p.ebitda_keur) for p in Q.operating_periods(quarterly)], rows_q)
    explained = False
    for boundary in eng_s:
        tolerance = Q.OPERATING_TOL * 10 * max(D(1), abs(eng_s[boundary]))
        assert abs(eng_s[boundary] - exp_s[boundary]) < tolerance
        assert abs(eng_q[boundary] - exp_q[boundary]) < tolerance
        assert abs((eng_s[boundary] - eng_q[boundary]) - (exp_s[boundary] - exp_q[boundary])) < tolerance
        explained = explained or abs(exp_s[boundary] - exp_q[boundary]) > tolerance
    cod = pi.info.cod_date
    expiry = cod + relativedelta(years=ppa) if ppa else None
    straddles = bool(expiry) and any(r.start < expiry < r.end for r in rows_s)
    assert explained == (cod.day == 1 or straddles), (sid, "unexplained or missing timing difference")
    assert abs(exp_s[rows_s[-1].end] - exp_q[rows_q[-1].end]) / abs(exp_s[rows_s[-1].end]) < D("0.02")      # lifetime EBITDA moves by < 2%


def test_horizon_totals_of_frequency_independent_quantities_match(sid):
    scn = Q.scenario(sid)
    pi, six = Q.run(scn, "S")
    _, quarterly = Q.run(scn, "Q")
    s, q = Q.operating_periods(six), Q.operating_periods(quarterly)
    d02 = pi.info.cod_date.day == 1
    for attribute in ("production_mwh", "opex_keur"):
        total_s, total_q = sum(Q.d(getattr(p, attribute)) for p in s), sum(Q.d(getattr(p, attribute)) for p in q)
        assert abs(total_s - total_q) <= (D("0.002") if d02 else Q.OPERATING_TOL * 10) * total_s
    assert (s[-1].period_end - s[0].period_start).days == (q[-1].period_end - q[0].period_start).days
    assert len({p.year_index for p in s}) == len({p.year_index for p in q}) == pi.info.horizon_years


def test_legitimate_financing_timing_differences_are_bounded_and_have_the_expected_sign(sid):
    """Quarterly service means earlier principal and interest dates and finer sculpting; the deltas are small and one-directional."""
    scn = Q.scenario(sid)
    _, six = Q.run(scn, "S")
    _, quarterly = Q.run(scn, "Q")
    fs_s, fs_q = six.g2c_result.financing_result, quarterly.g2c_result.financing_result
    size_s, size_q = Q.d(fs_s.final_senior_commitment_keur), Q.d(fs_q.final_senior_commitment_keur)
    binding_s = Q.model_of(six).senior_debt.binding_constraint
    if binding_s == "GEARING" and Q.model_of(quarterly).senior_debt.binding_constraint == "GEARING":
        assert size_s == size_q                                                  # same gearing, same commitment, same construction funding
    else:
        assert size_q >= size_s and (size_q - size_s) / size_s < D("0.02")      # finer sculpting never shrinks capacity and is below 2% here
    interest_s = sum(Q.d(x) for x in Q.model_of(six).senior_debt.senior_interest_keur)
    interest_q = sum(Q.d(x) for x in Q.model_of(quarterly).senior_debt.senior_interest_keur)
    assert interest_q <= interest_s * D("1.0001") or binding_s == "DSCR"       # quarterly amortisation does not accrue more interest on an equal loan
    assert abs(interest_q - interest_s) / interest_s < D("0.12")
    dscr_s = min(x for x in Q.model_of(six).senior_debt.base_dscr if x is not None)
    dscr_q = min(x for x in Q.model_of(quarterly).senior_debt.base_dscr if x is not None)
    assert dscr_q >= float(Q.d(Q.project(scn, "Q").financing.target_dscr)) - 1e-6 and dscr_s >= float(Q.d(Q.project(scn, "S").financing.target_dscr)) - 1e-6
    xs, xq = six.g2c_result.total_sponsor_xirr, quarterly.g2c_result.total_sponsor_xirr
    assert 0.0 < xq - xs < 0.01, (xs, xq)                                      # earlier cash, +0.1..0.6 points on a 14-22% IRR, never a sign flip


def test_debt_is_fully_repaid_on_the_same_maturity_date_under_both_frequencies(sid):
    scn = Q.scenario(sid)
    _, six = Q.run(scn, "S")
    _, quarterly = Q.run(scn, "Q")
    rs, rq = Q.senior_rows(six), Q.senior_rows(quarterly)
    assert rs[-1]["period"].period_end == rq[-1]["period"].period_end
    for rows, result in ((rs, six), (rq, quarterly)):
        assert abs(sum(r["principal"] for r in rows) - Q.d(result.g2c_result.financing_result.final_senior_commitment_keur)) < Q.SOLVER_TOL
    # the quarterly loan is never outstanding longer than the 6/6 loan at any common date (it repays on a finer, earlier grid)
    q_close = {r["period"].period_end: r["closing"] for r in rq}
    for r in rs:
        if binding_is_dscr(six):
            continue
        slack = Q.d(six.g2c_result.financing_result.final_senior_commitment_keur) * D("0.001") if Q.project(scn, "S").info.cod_date.day == 1 else Q.SOLVER_TOL
        assert q_close[r["period"].period_end] <= r["closing"] + slack      # D-02 (COD day counted by 6/6 only) moves the balance by < 0.1% of the loan


def binding_is_dscr(result) -> bool:
    return Q.model_of(result).senior_debt.binding_constraint == "DSCR"


def test_switching_back_and_forth_is_deterministic_and_leaves_no_state(sid):
    """S, Q, S, Q on the same inputs give bit-identical results (no cached calendar, solver warm-start or policy leakage between runs)."""
    scn = Q.scenario(sid)
    from test_rc7b_quarterly_funding_statements import canonical_run
    first_s, first_q = Q.run(scn, "S")[1], Q.run(scn, "Q")[1]
    again_q = canonical_run(Q.project(scn, "Q"), source_id="quarterly_institutional_acceptance")
    again_s = canonical_run(Q.project(scn, "S"), source_id="quarterly_institutional_acceptance")
    for first, again in ((first_s, again_s), (first_q, again_q)):
        assert dataclasses.asdict(first.g2c_result) == dataclasses.asdict(again.g2c_result)
        assert first.financial_statements_result == again.financial_statements_result
