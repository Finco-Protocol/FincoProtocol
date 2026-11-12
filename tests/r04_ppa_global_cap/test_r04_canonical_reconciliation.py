"""R04 reconciliation with the RELEASED technical-production authority (test-level adapter; the isolated core never imports product code).

The authority is ``finco_core.revenue.generation.period_generation``: capacity x selected yield hours (P50 / P90-10y) x period day_fraction x
plant/grid availability x (1 - degradation)^(operating year - 1). The adapter below turns the released PeriodEngine's operating rows into
authoritative availability segments, so the ceiling is checked against exactly the energy the released Run would generate.
"""
from __future__ import annotations

from datetime import date, timedelta
from fractions import Fraction as Fr

import pytest

from research.r04_ppa_global_cap import core as C

TOL = Fr(1, 10**9)       # explicit, documented float64 noise allowance of the released engine's arithmetic; real breaches are >> 1e-9


def _engine():
    from finco_core.engine.period_engine import PeriodEngine
    return PeriodEngine(financial_close=date(2025, 1, 1), construction_months=6, horizon_years=25, ppa_years=15, cod_date=date(2025, 7, 1))


def _tech(case="P50", degradation=0.005):
    from finco_core.inputs._models import TechnicalParams
    return TechnicalParams(capacity_mw=50.0, yield_scenario=case, operating_hours_p50=2000.0, operating_hours_p90_10y=1800.0,
                           pv_degradation=degradation)


def availability(tech, case):
    from finco_core.revenue.generation import period_generation
    segs, first = [], True
    for p in _engine().periods():
        if not p.is_operation:
            continue
        mwh = Fr(str(period_generation(tech, [p], p.year_index, case)))
        # Released engine convention: a row's ``start_date`` is the PREVIOUS row's closing date label, so the row covers the calendar days
        # (start_date, end_date] (inclusive end); only the COD row starts on its own start_date. ``days_in_period`` confirms it.
        start = p.start_date if first else p.start_date + timedelta(days=1)
        end = p.end_date + timedelta(days=1)
        assert (end - start).days == p.days_in_period
        segs.append(C.AvailabilitySegment(start, end, mwh))
        first = False
    return C.AvailabilitySource("released-period-engine", "proj-1", "scn-1", case, "released", "PERIOD_ENGINE", tuple(segs))


def test_segments_equal_the_released_generation_and_follow_the_selected_case():
    from finco_core.revenue.generation import period_generation
    tech = _tech()
    p50, p90 = availability(tech, "P50"), availability(tech, "P90-10y")
    ops = [p for p in _engine().periods() if p.is_operation]
    for p, a, b in zip(ops, p50.segments, p90.segments):
        assert float(a.mwh) == pytest.approx(period_generation(tech, [p], p.year_index, "P50"), rel=1e-12)
        assert float(b.mwh) == pytest.approx(period_generation(tech, [p], p.year_index, "P90-10y"), rel=1e-12)
        assert b.mwh < a.mwh                                          # the selected case is the maximum, never assumed P50
    assert p50.case_id == "P50" and p90.case_id == "P90-10y" and p50.basis == "PERIOD_ENGINE"


def _op_year_mwh(source, k):
    """Energy of released OPERATING year k (two semiannual rows; degradation steps on operating years, not calendar years)."""
    return sum((g.mwh for g in source.segments[2 * (k - 1):2 * k]), Fr(0))


def test_ceiling_tracks_the_released_degradation_and_case_year_by_year():
    s = availability(_tech(degradation=0.02), "P50")
    y1, y3 = _op_year_mwh(s, 1), _op_year_mwh(s, 3)
    assert y1 > y3
    cod, end = date(2025, 7, 1), date(2028, 7, 1)                     # three operating years, anniversaries = operating years
    pct = [C.Contract("A", cod, end, C.PERCENT_OF_AVAILABLE, Fr(80, 100)), C.Contract("B", cod, end, C.PERCENT_OF_AVAILABLE, Fr(20, 100))]
    rep = C.allocate(s, pct, rel_tolerance=TOL)                                           # percentages follow the degrading production: always within the cap
    assert rep.status == "WITHIN_CAP" and all(r.residual_mwh == 0 for r in rep.intervals)
    book_abs = [C.Contract("A", cod, end, C.ABSOLUTE_ANNUAL_MWH, y1 * Fr(8, 10)), C.Contract("B", cod, end, C.ABSOLUTE_ANNUAL_MWH, y1 * Fr(2, 10))]
    with pytest.raises(C.GlobalCapExceeded) as e:                      # an absolute volume sized to year 1 does NOT shrink with degradation
        C.allocate(s, book_abs, rel_tolerance=TOL)
    starts = [v.start for v in e.value.violations]
    assert min(starts) == date(2026, 7, 1) and e.value.violations[0].case_id == "P50"    # operating year 1 fits exactly; years 2 and 3 breach
    assert all(v.excess_mwh > 0 for v in e.value.violations)


def test_selected_case_binds_the_ceiling_and_a_p50_sized_book_breaks_under_p90():
    tech = _tech()
    p50, p90 = availability(tech, "P50"), availability(tech, "P90-10y")
    y1 = _op_year_mwh(p50, 1)
    book = [C.Contract("A", date(2025, 7, 1), date(2026, 7, 1), C.ABSOLUTE_ANNUAL_MWH, y1)]
    assert C.allocate(p50, book, expected_case_id="P50", rel_tolerance=TOL).status == "WITHIN_CAP"
    with pytest.raises(C.GlobalCapExceeded):
        C.allocate(p90, book, expected_case_id="P90-10y", rel_tolerance=TOL)
    with pytest.raises(C.R04Error) as e:
        C.allocate(p90, book, expected_case_id="P50")                 # a source for another case is never accepted as the selected one
    assert e.value.code == "WRONG_TECHNICAL_CASE"


def test_partial_first_year_follows_the_released_semiannual_rows():
    s = availability(_tech(), "P50")
    first = s.segments[0]                                              # COD 2025-07-01: a half-year row
    assert (first.start, first.end) == (date(2025, 7, 1), date(2026, 1, 1))                   # 184 days: Jul 1 .. Dec 31 inclusive
    rep = C.allocate(s, [C.Contract("A", date(2025, 7, 1), date(2026, 1, 1), C.PERCENT_OF_AVAILABLE, Fr(1))], rel_tolerance=TOL)
    assert rep.calendar_years[2025]["available_mwh"] == first.mwh and rep.calendar_years[2025]["residual_mwh"] == 0
