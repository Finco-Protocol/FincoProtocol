"""Quarterly institutional acceptance — Scenario A: calendar and period axis.

The expected axis is derived from dates only (``quarterly_acceptance_support.calendar_oracle``) and is cross-checked against the independent
Decimal oracle of RC-7B/RC-7C. Nothing is read back from the engine to form an expectation.
"""
from __future__ import annotations

import calendar as pycal
from datetime import date

import pytest

import quarterly_acceptance_support as Q
import rc7b_quarterly_oracle as oracle

QUARTER_ENDS = {(3, 31), (6, 30), (9, 30), (12, 31)}


@pytest.fixture(params=Q.IDS)
def sid(request):
    return request.param


def _axis(sid):
    scn = Q.scenario(sid)
    pi, result = Q.run(scn, "Q")
    expected = Q.calendar_oracle(pi.info.cod_date, pi.info.horizon_years)
    return pi, result, expected, Q.operating_periods(result)


def test_engine_axis_equals_the_date_oracle(sid):
    pi, _, expected, actual = _axis(sid)
    assert len(actual) == len(expected)
    for want, got in zip(expected, actual):
        assert (got.period_start, got.period_end) == (want.start, want.end)
        assert got.days_in_period == want.days
        assert got.year_index == want.model_year and got.period_in_year == want.period_in_year
        assert abs(Q.d(got.day_fraction) - want.fraction) < Q.OPERATING_TOL


def test_date_oracle_agrees_with_the_independent_decimal_oracle(sid):
    """Two independently written calendars (this module's and RC-7B's) must produce the same rows."""
    pi, _, expected, _ = _axis(sid)
    other = oracle.operating_rows(pi.info, int(pi.revenue.ppa_term_years))
    assert [(r.start, r.end, r.days, r.fraction, r.year) for r in other] == [(r.start, r.end, r.days, r.fraction, r.model_year) for r in expected]


def test_rows_are_contiguous_non_overlapping_and_complete(sid):
    pi, result, _, actual = _axis(sid)
    assert actual[0].period_start == pi.info.cod_date
    for earlier, later in zip(actual, actual[1:]):
        assert earlier.period_end == later.period_start            # no gap, no overlap, no duplicated day at a year boundary
    assert sum(p.days_in_period for p in actual) == (actual[-1].period_end - pi.info.cod_date).days
    assert len({(p.period_start, p.period_end) for p in actual}) == len(actual)


def test_every_row_ends_on_a_calendar_quarter_end_and_never_exceeds_a_quarter(sid):
    _, _, _, actual = _axis(sid)
    for p in actual:
        assert (p.period_end.month, p.period_end.day) in QUARTER_ENDS
        assert 0 < p.days_in_period <= 92


def test_only_the_first_row_may_be_short_and_the_axis_ends_on_a_half_year_end(sid):
    _, _, _, actual = _axis(sid)
    assert all(p.days_in_period >= 90 for p in actual[1:])           # every later row is a whole quarter (90..92 days)
    assert (actual[-1].period_end.month, actual[-1].period_end.day) in {(6, 30), (12, 31)}


def test_construction_to_operation_boundary_is_exact(sid):
    pi, result, _, actual = _axis(sid)
    construction = Q.construction_periods(result)
    assert construction[-1].period_end == pi.info.cod_date == actual[0].period_start
    assert not any(p.is_construction and p.is_operation for p in Q.model_of(result).periods)
    assert [p.period_index for p in Q.model_of(result).periods] == list(range(len(Q.model_of(result).periods)))


def test_economic_end_date_and_model_years_equal_the_matched_six_month_project(sid):
    scn = Q.scenario(sid)
    _, six = Q.run(scn, "S")
    _, quarterly = Q.run(scn, "Q")
    s_ops, q_ops = Q.operating_periods(six), Q.operating_periods(quarterly)
    assert s_ops[-1].period_end == q_ops[-1].period_end
    assert s_ops[0].period_start == q_ops[0].period_start
    assert {p.year_index for p in s_ops} == {p.year_index for p in q_ops}
    # each quarter lies inside exactly one six-month row of the matched project and inherits its model year
    for q in q_ops:
        parents = [s for s in s_ops if s.period_start <= q.period_start and q.period_end <= s.period_end]
        assert len(parents) == 1 and parents[0].year_index == q.year_index


def test_actual_day_fractions_use_the_end_year_denominator_and_sum_to_the_year(sid):
    """Leap years: a quarter's fraction is days/366 in a leap end-year; a complete calendar year sums to exactly one."""
    _, _, _, actual = _axis(sid)
    by_calendar_year: dict = {}
    for p in actual:
        denom = 366 if pycal.isleap(p.period_end.year) else 365
        assert abs(Q.d(p.day_fraction) - Q.D(p.days_in_period) / Q.D(denom)) < Q.OPERATING_TOL
        by_calendar_year.setdefault(p.period_end.year, []).append(p)
    for year, rows in by_calendar_year.items():
        if rows[0].period_start <= date(year - 1, 12, 31) and rows[-1].period_end == date(year, 12, 31):
            total = sum(Q.d(p.day_fraction) for p in rows)
            assert abs(total - 1) < Q.OPERATING_TOL, (year, total)


def test_leap_february_is_counted_once(sid):
    """The Dec31->Mar31 row carries 29 February exactly once (91 days in a leap year, 90 otherwise)."""
    _, _, _, actual = _axis(sid)
    for p in actual:
        if (p.period_start.month, p.period_start.day) == (12, 31) and (p.period_end.month, p.period_end.day) == (3, 31):
            assert p.days_in_period == (91 if pycal.isleap(p.period_end.year) else 90)


def test_model_year_layout_has_four_rows_except_the_first_year(sid):
    _, _, expected, actual = _axis(sid)
    counts: dict = {}
    for p in actual:
        counts[p.year_index] = counts.get(p.year_index, 0) + 1
    years = sorted(counts)
    assert years == list(range(1, len(years) + 1))
    assert all(counts[y] == 4 for y in years[1:])
    first_year_rows = counts[1]
    assert 1 <= first_year_rows <= 4 + 1
    # the first model year is the stub six-month row (plus the half-year after it when COD is in the first half)
    assert sum(1 for r in expected if r.model_year == 1) == first_year_rows


def test_construction_columns_are_identical_to_the_six_month_project(sid):
    scn = Q.scenario(sid)
    _, six = Q.run(scn, "S")
    _, quarterly = Q.run(scn, "Q")
    a, b = Q.construction_periods(six), Q.construction_periods(quarterly)
    assert [(p.period_start, p.period_end, p.days_in_period) for p in a] == [(p.period_start, p.period_end, p.days_in_period) for p in b]
    fa, fb = six.g2c_result.financing_result, quarterly.g2c_result.financing_result
    if fa.final_senior_commitment_keur == fb.final_senior_commitment_keur:
        assert fa.construction_financing == fb.construction_financing    # monthly IDC schedule is untouched by the operating frequency
        assert fa.project_uses == fb.project_uses
    else:
        # A DSCR-capacity-bound Senior is sized from operating cash flow, which legitimately moves with the operating frequency (earlier,
        # smaller debt-service dates); IDC then follows the commitment. Never a calendar defect: the construction dates above are identical.
        assert Q.model_of(six).senior_debt.binding_constraint == "DSCR" or Q.model_of(quarterly).senior_debt.binding_constraint == "DSCR"
        assert abs(fb.project_uses.total_project_uses_keur / fa.project_uses.total_project_uses_keur - 1) < 0.01


def test_senior_maturity_date_equals_the_six_month_maturity(sid):
    scn = Q.scenario(sid)
    pi, six = Q.run(scn, "S")
    _, quarterly = Q.run(scn, "Q")
    expected = Q.senior_maturity_oracle(pi.info.cod_date, pi.financing.senior_tenor_years)
    assert Q.senior_rows(six)[-1]["period"].period_end == expected
    assert Q.senior_rows(quarterly)[-1]["period"].period_end == expected
    assert len(Q.senior_rows(quarterly)) == sum(1 for r in Q.calendar_oracle(pi.info.cod_date, pi.info.horizon_years) if r.end <= expected)


def test_first_of_month_cod_excludes_the_cod_day_under_the_half_open_rule():
    """D-02 (documented, contractual): COD 1 Jan 2032 gives 90 days Jan1->Mar31 (the half-open rule does not count the COD day); the released
    six-month axis adds that day back. A year starting on 1 Jan therefore sums to 365/366, not one."""
    scn = Q.scenario("solar-jan1")
    _, quarterly = Q.run(scn, "Q")
    first_year = [p for p in Q.operating_periods(quarterly) if p.period_end.year == 2032]
    assert first_year[0].days_in_period == 90
    assert sum(p.days_in_period for p in first_year) == 365
    assert abs(sum(Q.d(p.day_fraction) for p in first_year) - Q.D(90 + 91 + 92 + 92) / Q.D(366)) < Q.OPERATING_TOL
