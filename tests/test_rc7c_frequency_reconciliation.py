"""RC-7C: switching an eligible project from 6/6 to 3/3 preserves its economics and horizon (D-01..D-04, D-10).

The comparison is the real canonical engine path in both frequencies for Solar and Wind across COD quarters, leap-year boundaries, construction
durations, horizons, Senior tenors and day counts, with merchant-only projects for arbitrary (stub) CODs. Expected values come from dates
(``tests/rc7c_frequency_reconciliation.py`` and ``tests/rc7b_quarterly_oracle.py``); nothing is rounded or forced to agree.

Nothing here is owner approval of the candidate conventions.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from dateutil.relativedelta import relativedelta

import rc7c_frequency_reconciliation as rec
from rc7c_frequency_reconciliation import Case, V1, V2

D = Decimal
REL = D("1e-9")           # float engine arithmetic vs 60-digit Decimal oracle on a non-iterated quantity


def _year_after_2030(m, d):
    return date(2031, m, d)


# Eligible PPA projects need the PPA expiry (COD + term) on a quarter end, i.e. COD on a quarter end (D-05 refuses an intra-quarter split).
PPA_CASES = [
    Case("solar", date(2031, 3, 31)),                  # COD in the second quarter of a half-year: the v1 defect case (reviewed example)
    Case("solar", date(2031, 6, 30)),                  # on a six-month boundary
    Case("solar", date(2031, 9, 30)),                  # second quarter of the second half
    Case("solar", date(2031, 12, 31)),
    Case("wind", date(2031, 3, 31)),
    Case("wind", date(2031, 6, 30)),
    Case("wind", date(2031, 9, 30)),
    Case("wind", date(2031, 12, 31)),
    Case("solar", date(2032, 6, 30), months=9),        # leap-year end and a 9-month construction
    Case("solar", date(2032, 3, 31), months=15),       # leap-year first quarter, 15-month construction
    Case("wind", date(2032, 9, 30), months=18),
    Case("solar", date(2028, 12, 31), months=24),
    Case("solar", date(2031, 3, 31), horizon=15),
    Case("solar", date(2031, 3, 31), horizon=30),
    Case("wind", date(2031, 9, 30), horizon=20),
    Case("solar", date(2031, 3, 31), tenor=8),         # DSCR-capacity-bound tenor
    Case("wind", date(2031, 9, 30), tenor=12),
    Case("solar", date(2031, 3, 31), day_count="ACT_365"),
    Case("wind", date(2031, 12, 31), day_count="ACT_360", tenor=10),
    Case("solar", date(2031, 3, 31), ppa=7.0),
    Case("wind", date(2031, 9, 30), ppa=12.0, horizon=25),
]
# Merchant-only projects admit ANY COD (no PPA expiry to place): initial stubs of 1 quarter, 2 quarters, mid-quarter, leap day, first of month.
MERCHANT_CASES = [
    Case("solar", date(2031, 4, 17), ppa=0.0),
    Case("solar", date(2031, 9, 17), ppa=0.0),
    Case("wind", date(2031, 11, 15), ppa=0.0),
    Case("solar", date(2032, 2, 29), months=13, ppa=0.0),   # leap day
    Case("wind", date(2031, 1, 10), ppa=0.0),
    Case("solar", date(2031, 5, 3), ppa=0.0, horizon=15),
    Case("wind", date(2031, 10, 24), ppa=0.0, tenor=10),
]
FIRST_OF_MONTH = [Case("solar", date(2031, 7, 1), ppa=0.0), Case("wind", date(2031, 4, 1), ppa=0.0)]
CASES = PPA_CASES + MERCHANT_CASES + FIRST_OF_MONTH
ALL = [pytest.param(c, id=c.label) for c in CASES]
NO_FIRST_DAY = [pytest.param(c, id=c.label) for c in PPA_CASES + MERCHANT_CASES]


def close(a, b, rel=REL):
    a, b = D(repr(float(a))) if not isinstance(a, D) else a, D(repr(float(b))) if not isinstance(b, D) else b
    return abs(a - b) <= rel * max(abs(a), abs(b), D(1))


# ── D-03: horizon, operating days, model years, construction ─────────────────

@pytest.mark.parametrize("case", ALL)
def test_frequency_switch_keeps_construction_start_end_days_and_model_years(case):
    s, q = rec.summary(case, "S"), rec.summary(case, "Q", V2)
    assert (q["operating_start"], q["operating_end"]) == (s["operating_start"], s["operating_end"])
    assert q["operating_days"] == s["operating_days"] - (1 if case.cod.day == 1 else 0) or q["operating_days"] == s["operating_days"]
    assert q["model_years"] == s["model_years"] == (case.horizon or rec.run(case, "S")[0].info.horizon_years)
    sc, qc = rec.run(case, "S")[1], rec.run(case, "Q", V2)[1]
    fs, fq = sc.g2c_result.financing_result, qc.g2c_result.financing_result
    assert fs.project_uses.hard_project_capex_keur == fq.project_uses.hard_project_capex_keur          # CAPEX: always the same
    if close(fs.final_senior_commitment_keur, fq.final_senior_commitment_keur):
        # Same Senior amount => the whole construction economics (dates, draws, IDC, fees, uses) is identical.
        assert q["total_project_uses_keur"] == s["total_project_uses_keur"]
        assert fs.construction_financing == fq.construction_financing and fs.construction_funding == fq.construction_funding
    else:
        # DSCR-sized Senior differs with the service timing; ONLY the amount-dependent financing costs follow it.
        diff = fq.project_uses.total_project_uses_keur - fs.project_uses.total_project_uses_keur
        assert close(diff, fq.project_uses.explicit_financing_cost_uses_keur - fs.project_uses.explicit_financing_cost_uses_keur)


@pytest.mark.parametrize("case", NO_FIRST_DAY)
def test_operating_days_are_identical_in_both_frequencies(case):
    s, q = rec.summary(case, "S"), rec.summary(case, "Q", V2)
    assert q["operating_days"] == s["operating_days"] == (s["operating_end"] - s["operating_start"]).days


# ── D-04: the anniversary clock — production, OPEX and depreciation per model year are identical ──

@pytest.mark.parametrize("case", NO_FIRST_DAY)
@pytest.mark.parametrize("attribute", ["production_mwh", "opex_keur", "book_depreciation_keur"])
def test_per_model_year_flows_that_do_not_depend_on_the_ppa_are_identical(case, attribute):
    semi, quarter = rec.run(case, "S")[1], rec.run(case, "Q", V2)[1]
    if attribute == "book_depreciation_keur":
        # Financial costs are depreciated, so depreciation can differ ONLY through the depreciable basis, i.e. when the DSCR-sized Senior amount differs.
        size = lambda r: r.g2c_result.financing_result.final_senior_commitment_keur       # noqa: E731
        if not close(size(semi), size(quarter)):
            pytest.skip("Senior size differs (timing-driven sizing): depreciation follows the financing-cost basis, reconciled in the sizing test")
    a, b = rec.engine_year_totals(semi, attribute), rec.engine_year_totals(quarter, attribute)
    assert set(a) == set(b)
    for year in a:
        assert close(a[year], b[year]), (attribute, year, a[year], b[year])


@pytest.mark.parametrize("case", ALL)
def test_each_frequency_matches_its_own_independent_date_oracle_per_model_year(case):
    expected = rec.explained_totals(case)
    for label, frequency, policy in (("S", "S", None), ("Q", "Q", V2)):
        rows, ops = expected[label]
        result = rec.run(case, frequency, policy)[1]
        for attribute, key in (("production_mwh", "mwh"), ("revenue_keur", "revenue"), ("opex_keur", "opex")):
            want = rec.per_year([o[key] for o in ops], rows)
            got = rec.engine_year_totals(result, attribute)
            assert set(want) == set(got), (label, attribute)
            for year in want:
                assert close(got[year], want[year]), (label, attribute, year, got[year], want[year])


@pytest.mark.parametrize("case", NO_FIRST_DAY)
def test_revenue_differs_only_in_the_year_the_ppa_expires_inside_a_six_month_row(case):
    """D-05: the six-month axis keeps the whole row at the PPA tariff, the 3/3 axis switches on the quarter boundary. No other revenue difference."""
    semi, quarter = rec.run(case, "S")[1], rec.run(case, "Q", V2)[1]
    a, b = rec.engine_year_totals(semi, "revenue_keur"), rec.engine_year_totals(quarter, "revenue_keur")
    differing = [y for y in a if not close(a[y], b[y])]
    pi = rec.run(case, "S")[0]
    ppa = int(pi.revenue.ppa_term_years)
    cod = pi.info.cod_date
    expiry = cod + relativedelta(years=ppa)
    six = [r for r in rec.six_month_rows(pi.info, ppa)]
    inside_six_month_row = ppa > 0 and any(r.start < expiry < r.end for r in six)
    if not inside_six_month_row:
        assert differing == [], (case.label, differing)
    else:
        assert len(differing) == 1
        year = differing[0]
        # direction: the six-month row keeps the (higher or lower) PPA tariff for the extra quarter; the difference is bounded by one quarter of revenue
        assert abs(a[year] - b[year]) < a[year] * D("0.30")


@pytest.mark.parametrize("case", FIRST_OF_MONTH)
def test_first_of_month_cod_difference_is_exactly_the_one_day_of_the_first_row_d02(case):
    s, q = rec.summary(case, "S"), rec.summary(case, "Q", V2)
    assert s["operating_days"] - q["operating_days"] == 0                                  # calendar days are the same ...
    semi, quarter = rec.run(case, "S")[1], rec.run(case, "Q", V2)[1]
    a, b = rec.engine_year_totals(semi, "production_mwh"), rec.engine_year_totals(quarter, "production_mwh")
    assert not close(a[1], b[1])                                                           # ... but the six-month rule counts the COD day (+1)
    assert all(close(a[y], b[y]) for y in a if y > 1)                                      # no other year moves
    first_days = (rec.six_month_rows(rec.run(case, "S")[0].info, 0)[0]).days
    calendar_days = (rec.oracle.six_month_ends(case.cod, 1)[0] - case.cod).days
    assert first_days == calendar_days + 1


# ── D-10: the Senior maturity date and full repayment ─────────────────────────────

@pytest.mark.parametrize("case", ALL)
def test_senior_matures_on_the_same_date_and_is_fully_repaid(case):
    s, q = rec.summary(case, "S"), rec.summary(case, "Q", V2)
    assert q["senior_final_service_date"] == s["senior_final_service_date"]
    pi, _ = rec.run(case, "S")
    tenor = pi.financing.senior_tenor_years
    assert s["senior_service_rows"] == 2 * tenor
    assert q["senior_service_rows"] == sum(1 for p in rec.run(case, "Q", V2)[1].g2c_result.financing_result.project_model_result.periods
                                          if p.is_operation and p.period_end <= q["senior_final_service_date"])
    for summary in (s, q):
        assert abs(summary["senior_principal_keur"] - summary["senior_commitment_keur"]) < 1e-3


@pytest.mark.parametrize("case", ALL)
def test_senior_interest_follows_actual_dates_not_a_forced_equality(case):
    """Interest is allowed to differ (quarterly accrual and repayment); it must stay within the economic range of the same loan."""
    s, q = rec.summary(case, "S"), rec.summary(case, "Q", V2)
    assert 0.80 < q["senior_interest_keur"] / s["senior_interest_keur"] < 1.0                # earlier repayment => no more interest
    assert s["min_dscr"] is not None and q["min_dscr"] is not None


# ── what the historical v1 did, as a measured fact ───────────────────────────────

@pytest.mark.parametrize("case", ALL)
def test_v1_added_a_quarter_exactly_when_cod_is_in_the_second_quarter_of_a_half_year(case):
    s, v1, v2 = rec.summary(case, "S"), rec.summary(case, "Q", V1), rec.summary(case, "Q", V2)
    extended = ((case.cod + relativedelta(days=1)).month - 1) // 3 % 2 == 1
    assert v2["operating_end"] == s["operating_end"]
    if extended:
        assert v1["operating_rows"] == v2["operating_rows"] + 1 and v1["operating_end"] > v2["operating_end"]
        assert v1["senior_final_service_date"] > v2["senior_final_service_date"]
        assert v1["revenue_keur"] > v2["revenue_keur"]
    else:
        assert v1["operating_rows"] == v2["operating_rows"] and v1["operating_end"] == v2["operating_end"]


def test_the_reviewed_solar_example_reproduces_the_independent_review_finding_and_v2_removes_the_horizon_effect():
    case = Case("solar", date(2031, 3, 31))
    s, v1, v2 = rec.summary(case, "S"), rec.summary(case, "Q", V1), rec.summary(case, "Q", V2)
    gap_v1 = (v1["revenue_keur"] - s["revenue_keur"]) / s["revenue_keur"]
    gap_v2 = (v2["revenue_keur"] - s["revenue_keur"]) / s["revenue_keur"]
    assert 0.0100 < gap_v1 < 0.0115                      # ~1.07 % additional revenue: the finding of the independent financial review
    assert abs(gap_v2) < 0.0025                         # what remains is the D-05 PPA-row granularity (see the per-year test), not the horizon
    assert v2["production_mwh"] == pytest.approx(s["production_mwh"], rel=1e-9)
    assert v2["opex_keur"] == pytest.approx(s["opex_keur"], rel=1e-9)


def test_table_renders_for_the_review_package():
    table = rec.report([PPA_CASES[0], MERCHANT_CASES[0]])
    assert table.count("\n") == 3 and "| solar/2031-03-31/cm12 |" in table
