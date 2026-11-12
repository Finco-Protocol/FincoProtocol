"""R04 isolated global PPA ceiling: policy matrix, independent day-by-day oracle, property tests, isolation."""
from __future__ import annotations

import ast
import random
from datetime import date
from fractions import Fraction as Fr
from pathlib import Path

import pytest

from research.r04_ppa_global_cap import core as C
from tests.r04_ppa_global_cap import oracle as O

ROOT = Path(__file__).resolve().parents[2]


def ct(cid, start, end, value, unit="GWh"):
    return C.contract_from_mapping({"id": cid, "start_date": start, "end_date": end, "volume": {"value": value, "unit": unit}})


def src(annual_mwh, first=2027, last=2036, case="P50", basis="FLAT_DAY_PRORATA_FALLBACK", project="proj-1"):
    years = {y: annual_mwh[y] if isinstance(annual_mwh, dict) else annual_mwh for y in range(first, last)}
    return C.AvailabilitySource("src-1", project, "scn-1", case, "v1", basis,
                                C.flat_day_prorata_segments(years, date(first, 1, 1), date(last, 1, 1)))


def oracle_segments(source):
    return [(s.start, s.end, s.mwh) for s in source.segments]


def oracle_contracts(cs):
    return [(c.start, c.end, "PERCENT" if c.basis == C.PERCENT_OF_AVAILABLE else "MWH", c.value) for c in cs]


def assert_matches_oracle(source, cs):
    report = C.allocate(source, cs, raise_on_violation=False)
    years, breaches = O.run(oracle_segments(source), oracle_contracts(cs))
    assert sorted(report.calendar_years) == sorted(years)
    for y, row in years.items():
        got = report.calendar_years[y]
        assert got["available_mwh"] == row["available"] and got["committed_mwh"] == row["committed"], y
        assert got["residual_mwh"] == row["available"] - row["committed"], y
        for i, c in enumerate(cs):
            assert got.get(c.contract_id, Fr(0)) == row["per"][i], (y, c.contract_id)
    assert (report.status == "OVERSUBSCRIBED") == bool(breaches)
    for row in report.intervals:                                   # conservation on EVERY exact interval
        assert row.committed_mwh + row.residual_mwh == row.available_mwh
        assert sum(row.per_contract_mwh.values(), Fr(0)) == row.committed_mwh
    return report


# ---------------------------------------------------------------- 100 GWh headline policy
def test_80_plus_20_accepted_and_80_plus_21_refused_with_the_full_breach_detail():
    s = src(100_000)
    ok = assert_matches_oracle(s, [ct("A", "2027-01-01", "2032-01-01", 80), ct("B", "2027-01-01", "2032-01-01", 20)])
    assert ok.status == "WITHIN_CAP" and all(r.residual_mwh == 0 for r in ok.intervals)
    with pytest.raises(C.GlobalCapExceeded) as e:
        C.allocate(s, [ct("A", "2027-01-01", "2032-01-01", 80)], candidate=ct("B", "2027-01-01", "2032-01-01", 21))
    v = e.value.violations[0]
    assert e.value.code == "GLOBAL_PPA_CAP_EXCEEDED"
    assert (v.available_mwh, v.existing_mwh, v.requested_mwh, v.excess_mwh, v.max_additional_mwh) == (Fr(100000), Fr(80000), Fr(21000), Fr(1000), Fr(20000))
    assert str(v.start) == "2027-01-01" and v.case_id == "P50"
    for text in ("available=100.000000 GWh", "existing=80.000000 GWh", "requested=21.000000 GWh", "excess=1.000000 GWh", "max_additional=20.000000 GWh"):
        assert text in str(e.value)


def test_three_contracts_60_20_20_accepted_and_one_more_mwh_refused():
    s = src(100_000)
    book = [ct("A", "2027-01-01", "2030-01-01", 60), ct("B", "2027-01-01", "2030-01-01", 20), ct("C", "2027-01-01", "2030-01-01", 20)]
    assert_matches_oracle(s, book)
    with pytest.raises(C.GlobalCapExceeded):
        C.allocate(s, book[:2], candidate=ct("C", "2027-01-01", "2030-01-01", 20.001))


@pytest.mark.parametrize("raw,code", [
    ({"id": "A", "start_date": "2027-01-01", "end_date": "2028-01-01", "volume": {"value": "-1", "unit": "GWh"}}, "NEGATIVE_VALUE"),
    ({"id": "A", "start_date": "2027-01-01", "end_date": "2028-01-01", "volume": {"value": "1", "unit": "EUR/MWh"}}, "UNKNOWN_UNIT"),
    ({"id": "A", "start_date": "2027-01-01", "end_date": "2028-01-01", "volume": {"value": "1", "unit": "GW"}}, "UNKNOWN_UNIT"),
    ({"id": "A", "start_date": "2028-01-01", "end_date": "2027-01-01", "volume": {"value": "1", "unit": "GWh"}}, "REVERSED_OR_EMPTY_WINDOW"),
    ({"id": "A", "start_date": "2027-01-01", "end_date": "2027-01-01", "volume": {"value": "1", "unit": "GWh"}}, "REVERSED_OR_EMPTY_WINDOW"),
    ({"id": "A", "start_date": "2027-01-01", "end_date": "2028-01-01", "volume": {"value": "101", "unit": "PERCENT"}}, "PERCENT_OUT_OF_RANGE"),
    ({"id": "A", "start_date": "2027-01-01", "end_date": "2028-01-01", "volume": {"value": "NaN", "unit": "GWh"}}, "NON_FINITE"),
    ({"id": "A", "start_date": "2027-01-01", "end_date": "2028-01-01", "volume": {"value": "abc", "unit": "GWh"}}, "MALFORMED_NUMBER"),
    ({"id": "A", "start_date": "2027-02-30", "end_date": "2028-01-01", "volume": {"value": "1", "unit": "GWh"}}, "MALFORMED_DATE"),
    ({"id": "A", "start_date": "2027-01-01", "end_date": "2028-01-01", "volume_share": 0.5}, "MALFORMED_CONTRACT"),   # legacy key never accepted silently
    ({"id": "", "start_date": "2027-01-01", "end_date": "2028-01-01", "volume": {"value": "1", "unit": "GWh"}}, "MALFORMED_CONTRACT_ID"),
])
def test_malformed_contracts_are_typed_refusals(raw, code):
    with pytest.raises(C.R04Error) as e:
        C.contract_from_mapping(raw)
    assert e.value.code == code


def test_duplicate_contract_id_and_wrong_project_or_case_refused():
    s = src(100_000)
    with pytest.raises(C.R04Error) as e:
        C.allocate(s, [ct("A", "2027-01-01", "2028-01-01", 1), ct("A", "2027-01-01", "2028-01-01", 1)])
    assert e.value.code == "DUPLICATE_CONTRACT_ID"
    with pytest.raises(C.R04Error) as e:
        C.allocate(s, [ct("A", "2027-01-01", "2028-01-01", 1)], expected_project_id="other")
    assert e.value.code == "WRONG_PROJECT"
    with pytest.raises(C.R04Error) as e:
        C.allocate(s, [ct("A", "2027-01-01", "2028-01-01", 1)], expected_case_id="P90-10Y")
    assert e.value.code == "WRONG_TECHNICAL_CASE"


def test_negative_production_and_missing_forecast_refused():
    with pytest.raises(C.R04Error) as e:
        C.allocate(C.AvailabilitySource("s", "p", "sc", "P50", "v", "PERIOD_ENGINE", (C.AvailabilitySegment(date(2027, 1, 1), date(2028, 1, 1), Fr(-1)),)),
                   [ct("A", "2027-01-01", "2028-01-01", 0)])
    assert e.value.code == "NEGATIVE_PRODUCTION"
    with pytest.raises(C.R04Error) as e:
        C.allocate(C.AvailabilitySource("s", "p", "sc", "P50", "v", "PERIOD_ENGINE", ()), [ct("A", "2027-01-01", "2028-01-01", 1)])
    assert e.value.code == "MISSING_TECHNICAL_FORECAST"
    with pytest.raises(C.R04Error) as e:
        C.flat_day_prorata_segments({2027: 100_000}, date(2027, 1, 1), date(2029, 1, 1))
    assert e.value.code == "MISSING_TECHNICAL_FORECAST"


# ---------------------------------------------------------------- degradation: a book valid in year 1 breaks later
def test_degradation_100_98_95_refuses_year_2_and_3_at_save_and_at_run():
    s = src({2027: 100_000, 2028: 98_000, 2029: 95_000}, 2027, 2030)
    book = [ct("A", "2027-01-01", "2030-01-01", 80)]
    cand = ct("B", "2027-01-01", "2030-01-01", 20)
    with pytest.raises(C.GlobalCapExceeded) as save:               # write boundary
        C.check_new_contract(s, book, cand)
    with pytest.raises(C.GlobalCapExceeded) as run:                # Run revalidates the effective book against the effective projection
        C.allocate(s, book + [cand])
    for exc in (save.value, run.value):
        got = {(str(v.start), str(v.end)): (v.available_mwh, v.excess_mwh) for v in exc.violations}
        assert got == {("2028-01-01", "2029-01-01"): (Fr(98000), Fr(2000)), ("2029-01-01", "2030-01-01"): (Fr(95000), Fr(5000))}
    assert save.value.violations[0].max_additional_mwh == Fr(18000)
    rep = C.allocate(s, book + [cand], raise_on_violation=False)    # an old invalid book is CLASSIFIED, never mutated
    assert rep.status == "OVERSUBSCRIBED" and len(rep.violations) == 2
    assert_matches_oracle(s, book + [cand])


# ---------------------------------------------------------------- dates: windows, anniversaries, leap years
CASES = [
    ("simultaneous", [("A", "2027-01-01", "2030-01-01", 50), ("B", "2027-01-01", "2030-01-01", 30)]),
    ("sequential", [("A", "2027-01-01", "2028-01-01", 80), ("B", "2028-01-01", "2030-01-01", 80)]),
    ("partial_overlap", [("A", "2027-01-01", "2029-07-01", 55), ("B", "2028-04-15", "2030-04-15", 40)]),
    ("midyear_cod_30_june", [("A", "2027-06-30", "2029-06-30", 78), ("B", "2027-06-30", "2029-06-30", 20)]),
    ("two_year_anniversary_midyear", [("A", "2027-06-30", "2029-06-30", 70)]),
    ("leap_2028", [("A", "2027-03-01", "2029-03-01", 90), ("B", "2028-02-01", "2028-03-15", 9)]),
    ("feb_29_start", [("A", "2028-02-29", "2031-02-28", 75), ("B", "2028-02-29", "2030-03-01", 20)]),
    ("midmonth", [("A", "2027-01-17", "2029-11-09", 55), ("B", "2027-08-03", "2028-09-21", 35)]),
]


@pytest.mark.parametrize("name,rows", CASES)
def test_true_date_ranges_match_the_day_by_day_oracle_without_losing_or_duplicating_energy(name, rows):
    s = src(100_000)
    cs = [ct(*r) for r in rows]
    report = assert_matches_oracle(s, cs)
    assert report.status == "WITHIN_CAP", name
    for c in cs:                                                     # whole-contract energy equals the exact day-weighted anniversary sum
        total = sum(y.get(c.contract_id, Fr(0)) for y in report.calendar_years.values())
        years, _ = O.run(oracle_segments(s), oracle_contracts([c]))
        assert total == sum(v["committed"] for v in years.values())


def test_full_subscription_across_a_leap_day_with_a_midyear_start_is_a_real_breach_of_the_flat_day_basis():
    """Documented, owner-open: with a flat annual profile spread by calendar-year days (the released engine's day_fraction basis), a
    100 GWh-per-anniversary-year book that starts mid-year and crosses Feb 29 commits slightly more than the calendar-day availability."""
    s = src(100_000)
    book = [ct("A", "2027-06-30", "2029-06-30", 80), ct("B", "2027-06-30", "2029-06-30", 20)]
    rep = assert_matches_oracle(s, book)
    assert rep.status == "OVERSUBSCRIBED" and {v.start.year for v in rep.violations} == {2028}
    assert all(Fr(0) < v.excess_mwh < Fr(1000) for v in rep.violations)
    # the same book anchored to a calendar-year start is exact (no breach): full anniversary years coincide with the availability years
    assert C.allocate(s, [ct("A", "2027-01-01", "2029-01-01", 80), ct("B", "2027-01-01", "2029-01-01", 20)]).status == "WITHIN_CAP"


def test_half_year_window_gets_the_labeled_flat_prorata_40_10_illustration():
    s = src(100_000)
    # 2027-01-01..2027-07-02 is 182 of 365 days: ~49.86 GWh of the flat 100 GWh/yr; 80/20 -> ~39.89 / ~9.97 (illustrative, not seasonal)
    rep = C.allocate(s, [ct("A", "2027-01-01", "2027-07-02", 80), ct("B", "2027-01-01", "2027-07-02", 20)])
    row = rep.calendar_years[2027]
    assert row["available_mwh"] == Fr(100000) * 182 / 365 and row["A"] == Fr(80000) * 182 / 365
    assert rep.availability_basis == "FLAT_DAY_PRORATA_FALLBACK"
    assert row["A"] / row["B"] == 4


def test_nonuniform_monthly_profile_differs_from_uniform_and_missing_coverage_is_typed():
    months = [(date(2027, m, 1), date(2027, m + 1, 1) if m < 12 else date(2028, 1, 1)) for m in range(1, 13)]
    weights = [2, 3, 6, 9, 12, 14, 15, 13, 9, 6, 3, 2]            # a synthetic solar-like shape summing to 94 -> scaled to 100 GWh
    segs = tuple(C.AvailabilitySegment(a, b, Fr(100_000) * w / sum(weights)) for (a, b), w in zip(months, weights))
    monthly = C.AvailabilitySource("s", "p", "sc", "P50", "v", "MONTHLY_PROFILE", segs)
    uniform = src(100_000, 2027, 2028)
    book = [ct("A", "2027-01-01", "2027-07-01", 50, "GWh")]        # first half-year: 50 GWh per year pro rata
    m, u = C.allocate(monthly, [ct("A", "2027-01-01", "2027-07-01", 10)]), C.allocate(uniform, [ct("A", "2027-01-01", "2027-07-01", 10)])
    assert m.calendar_years[2027]["available_mwh"] != u.calendar_years[2027]["available_mwh"]     # seasonality is not flat
    assert m.availability_basis == "MONTHLY_PROFILE"
    with pytest.raises(C.R04Error) as e:
        C.allocate(monthly, [ct("A", "2027-01-01", "2028-06-01", 1)])
    assert e.value.code == "OUTSIDE_TECHNICAL_HORIZON"
    assert_matches_oracle(monthly, [ct("A", "2027-02-10", "2027-10-20", 8), ct("B", "2027-02-10", "2027-10-20", 2)])
    del book


# ---------------------------------------------------------------- representations never interchange
def test_absolute_percent_and_legacy_share_are_distinct_and_follow_the_selected_case():
    p50, low = src(100_000), src(95_000)
    absolute = ct("A", "2027-01-01", "2028-01-01", 80)
    percent = ct("P", "2027-01-01", "2028-01-01", 80, "PERCENT")
    assert C.allocate(p50, [absolute]).calendar_years[2027]["A"] == C.allocate(p50, [percent]).calendar_years[2027]["P"] == Fr(80000)
    assert C.allocate(low, [percent]).calendar_years[2027]["P"] == Fr(76000)               # a percentage follows the case ...
    assert C.allocate(low, [absolute]).calendar_years[2027]["A"] == Fr(80000)               # ... an absolute volume does not
    with pytest.raises(C.GlobalCapExceeded):
        C.allocate(low, [absolute, ct("B", "2027-01-01", "2028-01-01", 16)])
    C.allocate(low, [percent, ct("B", "2027-01-01", "2028-01-01", 19)])
    assert absolute.basis != percent.basis


def test_zero_full_and_no_contracts_and_zero_availability():
    s = src(100_000)
    assert C.allocate(s, []).status == "WITHIN_CAP"
    assert_matches_oracle(s, [ct("A", "2027-01-01", "2028-01-01", 0, "PERCENT")])
    full = assert_matches_oracle(s, [ct("A", "2027-01-01", "2028-01-01", 100, "PERCENT")])
    assert full.calendar_years[2027]["residual_mwh"] == 0
    zero = src(0)
    assert C.allocate(zero, [ct("A", "2027-01-01", "2028-01-01", 0)]).status == "WITHIN_CAP"
    with pytest.raises(C.GlobalCapExceeded):
        C.allocate(zero, [ct("A", "2027-01-01", "2028-01-01", 0.001)])


def test_expired_beyond_lifetime_contract_is_outside_the_technical_horizon():
    s = src(100_000, 2027, 2032)
    for start, end in (("2020-01-01", "2024-01-01"), ("2030-01-01", "2034-01-01")):
        with pytest.raises(C.R04Error) as e:
            C.allocate(s, [ct("A", start, end, 1)])
        assert e.value.code == "OUTSIDE_TECHNICAL_HORIZON"


def test_residual_is_uncontracted_only_never_priced_or_zero_filled_and_cfd_is_not_a_second_sale():
    rep = C.allocate(src(100_000), [ct("A", "2027-01-01", "2028-01-01", 30)])
    row = rep.intervals[0]
    assert row.residual_mwh == Fr(70000) and row.residual_status == "UNCONTRACTED_RESIDUAL" and row.price_status == "EVIDENCE_REQUIRED"
    assert not hasattr(row, "price") and not hasattr(row, "revenue")
    assert not hasattr(C, "cfd") and "settle" not in "".join(dir(C)).lower()


def test_independent_indexation_per_contract_year_by_year_against_the_canonical_tariff_function():
    from datetime import date as d
    from financial_engine.ppa_indexation import PpaIndexationStartPolicy as Pol, compute_ppa_tariff
    cod = d(2027, 7, 1)
    for year_index, period_end in enumerate((d(2027, 12, 31), d(2028, 12, 31), d(2029, 12, 31), d(2030, 12, 31))):
        a = compute_ppa_tariff(70.0, 0.02, Pol.FIRST_FULL_CALENDAR_YEAR_AS_BASE, cod, period_end)
        b = compute_ppa_tariff(45.0, 0.005, Pol.FIRST_FULL_CALENDAR_YEAR_AS_BASE, cod, period_end)
        n = max(0, period_end.year - 2028)                           # first full calendar year (2028) is the index base year
        assert a == pytest.approx(float(Fr(70) * (Fr(102, 100) ** n)), rel=1e-12)
        assert b == pytest.approx(float(Fr(45) * (Fr(1005, 1000) ** n)), rel=1e-12)
        assert a != b


# ---------------------------------------------------------------- determinism and properties
def _random_book(rng, n):
    book = []
    for i in range(n):
        start = date(2027, 1, 1).toordinal() + rng.randrange(0, 1500)
        end = start + rng.randrange(30, 1200)
        s, e = date.fromordinal(start), date.fromordinal(min(end, date(2035, 12, 31).toordinal()))
        if e <= s:
            continue
        if rng.random() < .5:
            book.append(C.Contract(f"C{i}", s, e, C.PERCENT_OF_AVAILABLE, Fr(rng.randrange(0, 31), 100)))
        else:
            book.append(C.Contract(f"C{i}", s, e, C.ABSOLUTE_ANNUAL_MWH, Fr(rng.randrange(0, 31_000))))
    return book


@pytest.mark.parametrize("seed", range(12))
def test_properties_conservation_order_independence_and_oracle_agreement(seed):
    rng = random.Random(seed)
    s = src({y: 90_000 + 1_000 * ((y + seed) % 7) for y in range(2027, 2036)}, 2027, 2036)
    book = _random_book(rng, rng.randrange(1, 5))
    if not book:
        return
    rep = assert_matches_oracle(s, book)
    shuffled = book[:]
    rng.shuffle(shuffled)
    rep2 = C.allocate(s, shuffled, raise_on_violation=False)
    assert rep2.calendar_years == rep.calendar_years and rep2.status == rep.status
    for row in rep.intervals:
        assert row.available_mwh >= 0 and all(v >= 0 for v in row.per_contract_mwh.values())
        if rep.status == "WITHIN_CAP":
            assert row.committed_mwh <= row.available_mwh and row.residual_mwh >= 0


def test_headroom_gives_the_year_by_year_remaining_volume_for_the_early_hint():
    s = src({2027: 100_000, 2028: 98_000}, 2027, 2029)
    rows = C.headroom(s, [ct("A", "2027-01-01", "2029-01-01", 80)], date(2027, 1, 1), date(2029, 1, 1))
    assert [(str(r.start.year), r.residual_mwh) for r in rows] == [("2027", Fr(20000)), ("2028", Fr(18000))]


def test_float_tolerance_is_explicit_default_exact_and_never_masks_a_real_breach():
    s = src(100_000)
    edge = [ct("A", "2027-01-01", "2028-01-01", "100.0001")]       # 0.0001 GWh = 0.1 MWh over a 100 GWh year (1e-6 relative)
    with pytest.raises(C.GlobalCapExceeded):
        C.allocate(s, edge)
    with pytest.raises(C.GlobalCapExceeded):
        C.allocate(s, edge, rel_tolerance=Fr(1, 10**9))
    assert C.allocate(s, [ct("A", "2027-01-01", "2028-01-01", 100)], rel_tolerance=Fr(1, 10**9)).status == "WITHIN_CAP"


def test_check_is_atomic_and_never_mutates_the_existing_book():
    s = src(100_000)
    book = [ct("A", "2027-01-01", "2028-01-01", 80)]
    before = tuple(book)
    with pytest.raises(C.GlobalCapExceeded):
        C.check_new_contract(s, book, ct("B", "2027-01-01", "2028-01-01", 25))
    assert tuple(book) == before and len(book) == 1


# ---------------------------------------------------------------- isolation
def test_the_candidate_is_isolated_not_wired_and_not_active():
    assert C.STATUS == {"active": False, "approved_for_finco": False, "wired_into_save_or_run": False}
    tree = ast.parse((ROOT / "research/r04_ppa_global_cap/core.py").read_text())
    imported = {n.module.split(".")[0] if isinstance(n, ast.ImportFrom) else a.name.split(".")[0]
                for n in ast.walk(tree) for a in (n.names if isinstance(n, ast.Import) else [None]) if (isinstance(n, ast.Import) or isinstance(n, ast.ImportFrom))}
    assert not imported & {"app", "financial_engine", "finco_core", "domain", "main_web", "frontend"}
    import subprocess
    out = subprocess.run(["git", "grep", "-l", "r04_ppa_global_cap", "--", "*.py", "*.ts", "*.tsx", "*.js", "*.html"], cwd=ROOT,
                         capture_output=True).stdout.decode().split()
    assert all(p.startswith(("research/r04_ppa_global_cap/", "tests/r04_ppa_global_cap/", "tests/r04_ppa_scope.py", "tests/test_r04_ppa_scope.py")) for p in out), out
