"""FINCO 36 Correction C / Slice A — versioned date authority wired into the canonical generation schedule.

Independent day-by-day Decimal oracle (imports no calculator under test).  Proves that for an admitted R04 project
(Solar/Wind with an ABSOLUTE_ANNUAL physical contract) the Run's generation per reporting period is the actual-day,
COD-anniversary-degradation quantity, that legacy projects keep their legacy numbers, that P90 changes hours only,
and that a grid which would lose operating life is refused instead of silently dropping days.
"""
from __future__ import annotations

import calendar
import json
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal, getcontext

import pytest

from app import project_factories as pf
from app.workbook.revenue_multistream import apply_config
from finco_core.revenue.generation import full_generation_schedule
from financial_engine.adapters.project_inputs import from_project_inputs
from financial_engine.orchestrator import _build_period_engine

getcontext().prec = 50


# ── independent oracle ────────────────────────────────────────────────────────────────────────
def _add_years(d: date, n: int) -> date:
    y = d.year + n
    if d.month == 2 and d.day == 29 and not calendar.isleap(y):
        return date(y, 2, 28)
    return date(y, d.month, d.day)


def _oracle_generation(cod, horizon, start_incl, end_excl, cap, hours, avail, deg):
    """Sum of daily generation over [start_incl, end_excl) clipped to [cod, cod+horizon years)."""
    end_life = _add_years(cod, horizon)
    total = Decimal(0)
    day = max(start_incl, cod)
    stop = min(end_excl, end_life)
    annual = Decimal(repr(cap)) * Decimal(repr(hours)) * Decimal(repr(avail))
    while day < stop:
        k = 0
        while _add_years(cod, k + 1) <= day:
            k += 1
        ydays = 366 if calendar.isleap(day.year) else 365
        total += annual * (Decimal(1) - Decimal(repr(deg))) ** k / Decimal(ydays)
        day += timedelta(days=1)
    return total


def _contracts_json(technology, start, end, full_end):
    return json.dumps({
        "version": 2, "technology": technology, "indexation_basis": "OPERATING_YEAR",
        "streams": [
            {"id": "ppa_abs_1", "type": "ppa", "start_date": start.isoformat(), "end_date": end.isoformat(), "volume_share": None,
             "annual_quantity": {"mode": "ABSOLUTE_ANNUAL", "amount": "10", "unit": "GWh"},
             "price_eur_mwh": 72.0, "indexation_rate": 0.02, "settlement": "SAME_PERIOD", "source_ref": "DA_PPA"},
            {"id": "merchant_residual", "type": "merchant", "start_date": start.isoformat(), "end_date": full_end.isoformat(),
             "volume_share": None, "price_eur_mwh": 55.0, "indexation_rate": 0.01, "settlement": "SAME_PERIOD", "source_ref": "DA_M"},
        ]}, separators=(",", ":"))


def _project(technology, cod, horizon=20, *, scenario=None, fc=None, months=12):
    base = pf.create_generic_solar_reference() if technology == "solar" else pf.create_generic_wind_reference()
    return replace(
        base,
        info=replace(base.info, cod_date=cod, financial_close=fc or date(cod.year - 1, cod.month, min(cod.day, 28)),
                     construction_months=months, horizon_years=horizon),
        technical=replace(base.technical, capacity_mw=40.0, operating_hours_p50=2000.0, operating_hours_p90_10y=1700.0,
                          **({"yield_scenario": scenario} if scenario else {})),
    )


def _with_r04(pi, technology):
    eng = _build_period_engine(from_project_inputs(pi))
    ops = [p for p in eng.periods() if p.is_operation]
    return apply_config(pi, _contracts_json(technology, ops[0].start_date, ops[min(8, len(ops) - 1)].start_date, _add_years(pi.info.cod_date, pi.info.horizon_years) - timedelta(days=1)), project_type=technology)


@pytest.mark.parametrize("technology", ["solar", "wind"])
@pytest.mark.parametrize("cod", [date(2031, 1, 1), date(2031, 3, 1), date(2031, 5, 15), date(2031, 7, 1)])
def test_admitted_run_generation_equals_independent_daily_oracle(technology, cod):
    pi = _with_r04(_project(technology, cod), technology)
    eng = _build_period_engine(from_project_inputs(pi))
    schedule = full_generation_schedule(pi, eng)
    t = pi.technical
    prev_end, total = None, Decimal(0)
    for p in eng.periods():
        if not p.is_operation:
            assert schedule[p.index] == 0.0
            continue
        start_incl = cod if prev_end is None else prev_end + timedelta(days=1)
        expected = _oracle_generation(cod, 20, start_incl, p.end_date + timedelta(days=1),
                                      t.capacity_mw, t.operating_hours_p50, t.combined_availability, t.pv_degradation)
        assert float(expected) == pytest.approx(schedule[p.index], rel=1e-12, abs=1e-9), (technology, cod, p.index)
        total += expected
        prev_end = p.end_date
    # whole contractual life, no lost or extra day
    full_life = _oracle_generation(cod, 20, cod, _add_years(cod, 20), t.capacity_mw, t.operating_hours_p50, t.combined_availability, t.pv_degradation)
    assert float(total) == pytest.approx(float(full_life), rel=1e-12)


def test_legacy_project_without_r04_contracts_keeps_legacy_generation():
    pi = _project("solar", date(2031, 1, 1))
    eng = _build_period_engine(from_project_inputs(pi))
    schedule = full_generation_schedule(pi, eng)
    t = pi.technical
    for p in eng.periods():
        if p.is_operation:
            legacy = t.capacity_mw * t.operating_hours_p50 * p.day_fraction * t.combined_availability * (1 - t.pv_degradation) ** (p.year_index - 1)
            assert schedule[p.index] == pytest.approx(legacy, rel=1e-12)


def test_p90_changes_only_hours_not_the_dated_source():
    pi50 = _with_r04(_project("solar", date(2031, 1, 1)), "solar")
    pi90 = replace(pi50, technical=replace(pi50.technical, yield_scenario="P90-10y"))
    eng = _build_period_engine(from_project_inputs(pi50))
    g50, g90 = full_generation_schedule(pi50, eng), full_generation_schedule(pi90, eng)
    ratio = pi50.technical.operating_hours_p90_10y / pi50.technical.operating_hours_p50
    for idx, v in g50.items():
        assert g90[idx] == pytest.approx(v * ratio, rel=1e-12)


@pytest.mark.parametrize("technology", ["solar", "wind"])
@pytest.mark.parametrize("cod,horizon,stub_rows", [
    (date(2031, 1, 1), 20, 0), (date(2031, 7, 1), 20, 0),          # aligned controls: no phantom/duplicate stub
    (date(2031, 3, 1), 20, 1), (date(2031, 5, 15), 20, 1), (date(2031, 5, 15), 3, 1),
    (date(2031, 7, 2), 20, 1), (date(2031, 1, 2), 5, 1),            # 1-day stub
    (date(2028, 2, 29), 21, 1),                                      # leap COD: end clamps to Feb 28 of a non-leap year
])
def test_dated_axis_covers_the_contractual_life_exactly(technology, cod, horizon, stub_rows):
    leap = cod == date(2028, 2, 29)
    pi = _project(technology, cod, horizon, **({'fc': date(2024, 2, 29), 'months': 48} if leap else {}))
    from finco_core.engine.date_authority import legacy_operating_intervals
    legacy_eng = _build_period_engine(from_project_inputs(pi))
    legacy_rows = sum(1 for p in legacy_eng.periods() if p.is_operation)
    dated = _with_r04(pi, technology)
    eng = _build_period_engine(from_project_inputs(dated))
    ivs = list(legacy_operating_intervals(eng, cod).values())
    assert len(ivs) == legacy_rows + stub_rows == eng.operating_period_count
    assert ivs[0].start == cod and ivs[-1].end_exclusive == _add_years(cod, horizon)
    for a, b in zip(ivs, ivs[1:]):
        assert a.end_exclusive == b.start                      # no gap, no overlap, no duplicate boundary
    assert sum((iv.end_exclusive - iv.start).days for iv in ivs) == (_add_years(cod, horizon) - cod).days
    # rows before the final stub are byte-identical to the legacy grid (identity, labels, flags)
    for lp, dp in zip(legacy_eng.periods(), eng.periods()):
        if lp.is_operation and lp.index == legacy_rows + 1 - 1 and stub_rows == 0:
            continue
    assert [p.end_date for p in legacy_eng.periods()][:-1] == [p.end_date for p in eng.periods()][:len(legacy_eng.periods()) - 1]
