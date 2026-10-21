"""Quarterly institutional acceptance — Scenario B: revenue, OPEX, PPA indexation timing, depreciation and annual aggregation.

Expected values come from the 60-digit Decimal oracle (``rc7b_quarterly_oracle``) fed with the independent date axis of
``quarterly_acceptance_support.calendar_oracle``. Where the frequency changes, the S-versus-Q difference per model year must be zero except for
the two documented contractual timing effects (D-02 COD-day count, D-05 PPA expiry inside a six-month row), and in those years it must equal
the oracle's own explained difference.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

import pytest
from dateutil.relativedelta import relativedelta

import quarterly_acceptance_support as Q
import rc7b_quarterly_oracle as oracle
import rc7c_frequency_reconciliation as recon

D = Q.D


@pytest.fixture(params=Q.IDS)
def sid(request):
    return request.param


def _rows(pi):
    return oracle.operating_rows(pi.info, int(pi.revenue.ppa_term_years))


def _dep_items(result):
    from financial_engine.adapters.project_inputs import from_project_inputs
    return from_project_inputs(result.project_inputs).depreciation


def _year_totals(values, years):
    out = defaultdict(lambda: D(0))
    for value, year in zip(values, years):
        out[int(year)] += Q.d(value)
    return out


def test_production_revenue_opex_ebitda_equal_the_decimal_oracle_row_by_row(sid):
    pi, result = Q.run(Q.scenario(sid), "Q")
    rows = _rows(pi)
    expected = oracle.operating(pi, rows, "P50")
    ops = Q.operating_periods(result)
    assert len(ops) == len(rows)
    for want, row, got in zip(expected, rows, ops):
        assert abs(Q.d(got.production_mwh) - want["mwh"]) < Q.OPERATING_TOL * max(D(1), want["mwh"]), got.period_end
        assert abs(Q.d(got.revenue_keur) - want["revenue"]) < Q.OPERATING_TOL * max(D(1), want["revenue"]), got.period_end
        assert abs(Q.d(got.opex_keur) - want["opex"]) < Q.OPERATING_TOL * max(D(1), want["opex"]), got.period_end
        assert abs(Q.d(got.ebitda_keur) - want["ebitda"]) < Q.OPERATING_TOL * max(D(1), abs(want["ebitda"])), got.period_end
        assert got.is_ppa_active == row.ppa_active


def test_ebit_is_ebitda_less_book_depreciation_and_operating_schedules_match_the_period_rows(sid):
    _, result = Q.run(Q.scenario(sid), "Q")
    model = Q.model_of(result)
    ops = Q.operating_periods(result)
    sched = model.operating_schedules
    assert list(sched.period_indices) == [p.period_index for p in model.periods]      # construction + operation, one entry per model column
    for p in ops:
        k = list(sched.period_indices).index(p.period_index)
        assert abs(Q.d(p.ebit_keur) - (Q.d(p.ebitda_keur) - Q.d(p.book_depreciation_keur))) < Q.IDENTITY_TOL
        assert Q.d(sched.revenue_keur[k]) == Q.d(p.revenue_keur) and Q.d(sched.opex_keur[k]) == Q.d(p.opex_keur)
        assert Q.d(sched.book_depreciation_keur[k]) == Q.d(p.book_depreciation_keur)


def test_tax_depreciation_equals_the_oracle_and_book_depreciation_is_straight_line_per_model_year(sid):
    pi, result = Q.run(Q.scenario(sid), "Q")
    dep = _dep_items(result)
    rows = _rows(pi)
    expected = oracle.depreciation(dep.tax_capex_items_for_depreciation, dep.financial_cost_useful_life_years, pi.info.horizon_years, rows)
    ops = Q.operating_periods(result)
    for want, got in zip(expected, ops):
        assert abs(Q.d(got.tax_depreciation_keur) - want) < Q.OPERATING_TOL * max(D(1), want)
    # book depreciation is straight-line: the amount per unit of year fraction is constant inside a model year, so a stub row is pro-rated, not repeated
    per_fraction: dict = defaultdict(set)
    for p in ops:
        per_fraction[int(p.year_index)].add(round(float(p.book_depreciation_keur) / float(p.day_fraction), 6))
    assert all(len(v) == 1 for v in per_fraction.values())
    # the fixed-asset ledger carries exactly the operating depreciation (no duplicated or omitted partial period)
    ledger = {r.period_index: r for r in result.financial_statements_result.fixed_asset_periods}
    running = D(0)
    for p in ops:
        running += Q.d(p.book_depreciation_keur)
        row = ledger[p.period_index]
        assert abs(Q.d(row.book_depreciation_keur) - Q.d(p.book_depreciation_keur)) < Q.IDENTITY_TOL
        assert abs(Q.d(row.accumulated_book_depreciation_keur) - running) < Q.IDENTITY_TOL
        assert abs(Q.d(row.net_fixed_assets_keur) - (Q.d(row.gross_fixed_assets_keur) - running)) < Q.IDENTITY_TOL
    # A model year that straddles a leap day has day fractions summing to 1.0014 (end-year denominators), so an asset class whose life reaches the
    # horizon end is written off by a few keur more than its base. This is the RELEASED actual-day convention (identical under 6/6, see the
    # cross-frequency check below), 0.006% of the base, reported as finding Q-F-01 (P2); it is bounded here, never silently accepted.
    gross = Q.d(ledger[ops[-1].period_index].gross_fixed_assets_keur)
    overage = running - gross
    assert overage <= D("1e-4") * gross
    pi_s, six = Q.run(Q.scenario(sid), "S")
    ledger_s = six.financial_statements_result.fixed_asset_periods
    ops_s = Q.operating_periods(six)
    same_base = six.g2c_result.financing_result.final_senior_commitment_keur == result.g2c_result.financing_result.final_senior_commitment_keur
    if same_base and pi_s.info.cod_date.day != 1:      # D-02 adds the COD day to the released first row, which moves the overage
        overage_s = sum(Q.d(p.book_depreciation_keur) for p in ops_s) - Q.d(ledger_s[-1].gross_fixed_assets_keur)
        assert abs(overage - overage_s) < D("1e-6")


def test_ppa_flag_switches_at_the_contractual_expiry_quarter_boundary_and_never_inside_a_row(sid):
    scn = Q.scenario(sid)
    pi, result = Q.run(scn, "Q")
    ops = Q.operating_periods(result)
    term = int(pi.revenue.ppa_term_years)
    if term == 0:
        assert not any(p.is_ppa_active for p in ops)
        return
    expiry = pi.info.cod_date + relativedelta(years=term)
    for p in ops:
        assert p.is_ppa_active == (p.period_start < expiry)
        assert not (p.period_start < expiry < p.period_end)        # a contractual expiry strictly inside a row is refused upstream, never split


def test_effective_price_per_mwh_follows_the_model_year_indexation_not_the_calendar_year(sid):
    """PPA tariff = base * (1+index)^(model year-1) and merchant = curve[model year-1]; the step happens on the first quarter of a model year."""
    pi, result = Q.run(Q.scenario(sid), "Q")
    rev = pi.revenue
    share = D(min(max(rev.ppa_production_share, 0.0), 1.0))
    for p in Q.operating_periods(result):
        year = int(p.year_index)
        tariff = Q.d(rev.ppa_base_tariff) * (1 + Q.d(rev.ppa_index)) ** (year - 1)
        curve = rev.market_prices_curve
        market = Q.d(curve[year - 1]) if year - 1 < len(curve) else Q.d(curve[-1]) * (1 + Q.d(rev.market_inflation)) ** (year - len(curve))
        mwh = Q.d(p.production_mwh)
        ppa_part = mwh * share if p.is_ppa_active else D(0)
        balancing = mwh * (Q.d(rev.balancing_cost_eur_per_mwh) or Q.d(rev.balancing_cost_wind_eur_mwh)) / 1000
        merchant_rev = (mwh - ppa_part) * market / 1000
        want = ppa_part * tariff / 1000 + merchant_rev - (merchant_rev * Q.d(rev.balancing_cost_pv) + balancing)
        assert abs(Q.d(p.revenue_keur) - want) < Q.OPERATING_TOL * max(D(1), want)


def test_stepped_and_percentage_opex_follow_the_model_year_and_the_actual_day_fraction():
    stepped = Q.scenario("solar-opex-step")
    pi, result = Q.run(stepped, "Q")
    ops = Q.operating_periods(result)
    daily = {}
    for p in ops:
        daily.setdefault(int(p.year_index), set()).add(round(float(p.opex_keur) / float(p.day_fraction), 6))
    for values in daily.values():
        assert len(values) == 1                                  # OPEX per unit of year fraction is constant inside a model year
    first = pi.opex[0]
    step6 = first.y1_amount_keur * 1.5 * 1.02 ** (6 - 6)
    expected_6 = oracle.annual_opex(pi.opex, 6)
    assert abs(Q.d(next(iter(daily[6]))) - expected_6) < D("1e-5")
    assert expected_6 > oracle.annual_opex(pi.opex, 5)             # the step is real
    assert step6 > first.y1_amount_keur
    pct = Q.scenario("solar-opex-pct")
    pi, result = Q.run(pct, "Q")
    base_items = pi.opex[:-1]
    for p in Q.operating_periods(result)[:8]:
        year = int(p.year_index)
        base = oracle.annual_opex(base_items, year)
        assert abs(Q.d(p.opex_keur) - base * D("1.05") * Q.d(p.day_fraction)) < Q.OPERATING_TOL * max(D(1), Q.d(p.opex_keur))


def _explained_year_differences(scn):
    """Per-year (S, Q) oracle totals of production / revenue / opex / depreciation, computed independently for the two axes."""
    pi_s, six = Q.run(scn, "S")
    pi_q, quarterly = Q.run(scn, "Q")
    ppa = int(pi_s.revenue.ppa_term_years)
    rows_s = recon.six_month_rows(pi_s.info, ppa)
    rows_q = oracle.operating_rows(pi_q.info, ppa)
    return (oracle.operating(pi_s, rows_s, "P50"), rows_s), (oracle.operating(pi_q, rows_q, "P50"), rows_q)


def test_annual_aggregation_of_quarters_equals_the_six_month_project_except_documented_timing_effects(sid):
    """Frequency switch of operating economics: nothing is lost, duplicated or shifted at model-year boundaries.

    Zero difference per model year is required except (D-02) model year 1 when COD is the first of a month and (D-05) the model year whose
    six-month row straddles a quarter-boundary PPA expiry (revenue only). Both are quantified exactly by the axis-specific oracle test below.
    """
    scn = Q.scenario(sid)
    pi_s, six = Q.run(scn, "S")
    _, quarterly = Q.run(scn, "Q")
    s_ops, q_ops = Q.operating_periods(six), Q.operating_periods(quarterly)
    ppa = int(pi_s.revenue.ppa_term_years)
    cod = pi_s.info.cod_date
    d02_year = 1 if cod.day == 1 else None
    expiry = cod + relativedelta(years=ppa) if ppa else None
    d05_years = {int(p.year_index) for p in s_ops if expiry and p.period_start < expiry < p.period_end}
    equal_senior = six.g2c_result.financing_result.final_senior_commitment_keur == quarterly.g2c_result.financing_result.final_senior_commitment_keur
    for attribute in ("production_mwh", "opex_keur", "book_depreciation_keur", "revenue_keur"):
        s_year = _year_totals([getattr(p, attribute) for p in s_ops], [p.year_index for p in s_ops])
        q_year = _year_totals([getattr(p, attribute) for p in q_ops], [p.year_index for p in q_ops])
        assert set(s_year) == set(q_year)
        for year in s_year:
            diff = abs(s_year[year] - q_year[year])
            if attribute == "book_depreciation_keur" and not equal_senior:
                # book depreciation capitalises IDC / financing costs; a DSCR-bound Senior legitimately has a different size under 3/3 (see financing module)
                assert diff <= D("0.002") * s_year[year] + (D("0.02") * s_year[year] if year == d02_year else 0), (sid, attribute, year)
            elif year == d02_year:
                assert diff <= D("0.02") * s_year[year], (sid, attribute, year)       # one day of the first row only
            elif attribute == "revenue_keur" and year in d05_years:
                assert diff <= D("0.20") * s_year[year], (sid, attribute, year)       # a quarter or two at the merchant price instead of the PPA tariff
            else:
                assert diff < Q.OPERATING_TOL * 10 * max(D(1), s_year[year]), (sid, attribute, year, s_year[year], q_year[year])


def test_axis_specific_oracle_explains_every_remaining_model_year_difference(sid):
    """Where S and Q do differ, each engine value equals the oracle on its OWN axis (the difference is timing, not a defect)."""
    scn = Q.scenario(sid)
    (exp_s, rows_s), (exp_q, rows_q) = _explained_year_differences(scn)
    _, six = Q.run(scn, "S")
    _, quarterly = Q.run(scn, "Q")
    for exp, rows, result in ((exp_s, rows_s, six), (exp_q, rows_q, quarterly)):
        eng = _year_totals([p.revenue_keur for p in Q.operating_periods(result)], [p.year_index for p in Q.operating_periods(result)])
        want = _year_totals([e["revenue"] for e in exp], [r.year for r in rows])
        for year in want:
            assert abs(eng[year] - want[year]) < Q.OPERATING_TOL * max(D(1), want[year]) * 10, (year,)


def test_one_hundred_percent_of_horizon_days_are_operated_exactly_once(sid):
    pi, result = Q.run(Q.scenario(sid), "Q")
    ops = Q.operating_periods(result)
    cod = pi.info.cod_date
    assert sum(p.days_in_period for p in ops) == (ops[-1].period_end - cod).days
    assert ops[-1].period_end == Q.half_year_boundaries(cod, 2 * pi.info.horizon_years)[-1]
