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


# ── dated R04 revenue: contract start/end inside a reporting row, independent per-day oracle ─────
def _book(technology, cod, life_end, *, a, b, pm=55.0):
    """a/b = (start, end_exclusive, GWh/yr, EUR/MWh).  Merchant = physical residual over the whole life."""
    def ppa(sid, start, end, gwh, price):
        return {"id": sid, "type": "ppa", "start_date": start.isoformat(), "end_date": end.isoformat(), "volume_share": None,
                "annual_quantity": {"mode": "ABSOLUTE_ANNUAL", "amount": str(gwh), "unit": "GWh"},
                "price_eur_mwh": price, "indexation_rate": 0.0, "settlement": "SAME_PERIOD", "source_ref": "ORACLE_" + sid}
    return json.dumps({"version": 2, "technology": technology, "indexation_basis": "OPERATING_YEAR", "streams": [
        ppa("ppa_a", *a[:2], a[2], a[3]), ppa("ppa_b", *b[:2], b[2], b[3]),
        {"id": "merchant", "type": "merchant", "start_date": cod.isoformat(), "end_date": life_end.isoformat(), "volume_share": None,
         "price_eur_mwh": pm, "indexation_rate": 0.0, "settlement": "SAME_PERIOD", "source_ref": "ORACLE_M", "capture_rate": 1.0}]},
        separators=(",", ":"))


def _oracle_row(cod, horizon, start_incl, end_excl, t, contracts, pm):
    """Per-day physical allocation and cash for one row: contracts deliver Q/ydays per active day, merchant takes the residual."""
    end_life = _add_years(cod, horizon)
    annual = Decimal(repr(t.capacity_mw)) * Decimal(repr(t.operating_hours_p50)) * Decimal(repr(t.combined_availability))
    out = {c[0]: [Decimal(0), Decimal(0)] for c in contracts}   # id -> [mwh, keur]
    merch = [Decimal(0), Decimal(0)]
    day, stop = max(start_incl, cod), min(end_excl, end_life)
    while day < stop:
        k = 0
        while _add_years(cod, k + 1) <= day:
            k += 1
        ydays = Decimal(366 if calendar.isleap(day.year) else 365)
        gen = annual * (Decimal(1) - Decimal(repr(t.pv_degradation))) ** k / ydays
        used = Decimal(0)
        for cid, c_start, c_end, gwh, price in contracts:
            if c_start <= day < c_end:
                q = Decimal(gwh) * 1000 / ydays
                out[cid][0] += q
                out[cid][1] += q * Decimal(repr(price)) / 1000
                used += q
        assert used <= gen, "oracle scenario must be physically feasible"
        res = gen - used
        merch[0] += res
        merch[1] += res * Decimal(repr(pm)) / 1000
        day += timedelta(days=1)
    return out, merch


@pytest.mark.parametrize("technology", ["solar", "wind"])
@pytest.mark.parametrize("cod", [date(2031, 3, 1), date(2031, 5, 15)])
def test_dated_revenue_with_contract_dates_inside_rows_matches_daily_oracle(technology, cod):
    from finco_core.revenue.generation import revenue_decomposition_schedule

    pi = _project(technology, cod)
    life_end = _add_years(cod, 20)
    a = (date(2031, 9, 10), date(2041, 2, 20), "25", 72.0)      # starts and ends inside reporting rows
    b = (cod, date(2036, 5, 15), "15", 68.0)                      # independent price, different term
    pm = 55.0
    book = _book(technology, cod, life_end, a=a, b=b, pm=pm)
    pi = apply_config(pi, book, project_type=technology)
    eng = _build_period_engine(from_project_inputs(pi))
    dec = revenue_decomposition_schedule(pi, eng)
    contracts = [("ppa_a", a[0], a[1], a[2], a[3]), ("ppa_b", b[0], b[1], b[2], b[3])]
    prev_end, total_rev, tot_oracle = None, 0.0, Decimal(0)
    for p in eng.periods():
        if not p.is_operation:
            continue
        start_incl = cod if prev_end is None else prev_end + timedelta(days=1)
        per, merch = _oracle_row(cod, 20, start_incl, p.end_date + timedelta(days=1), pi.technical, contracts, pm)
        row = dec[p.index]
        exp_ppa_mwh = per["ppa_a"][0] + per["ppa_b"][0]
        exp_ppa_keur = per["ppa_a"][1] + per["ppa_b"][1]
        assert float(exp_ppa_mwh) == pytest.approx(row["ppa_generation_mwh"], rel=1e-9, abs=1e-6), (technology, cod, p.index)
        assert float(exp_ppa_keur) == pytest.approx(row["ppa_revenue_keur"], rel=1e-9, abs=1e-6), (technology, cod, p.index)
        assert float(merch[0]) == pytest.approx(row["merchant_generation_mwh"], rel=1e-9, abs=1e-6), (technology, cod, p.index)
        assert float(merch[1]) == pytest.approx(row["gross_merchant_revenue_keur"], rel=1e-9, abs=1e-6), (technology, cod, p.index)
        # conservation: contracts + merchant == generation of the row
        assert row["generation_mwh"] == pytest.approx(row["ppa_generation_mwh"] + row["merchant_generation_mwh"], rel=1e-9)
        tot_oracle += exp_ppa_keur + merch[1]
        prev_end = p.end_date
    assert float(tot_oracle) > 0


def test_missing_merchant_price_and_ambiguous_merchants_fail_closed():
    pi = _project("solar", date(2031, 3, 1))
    life_end = _add_years(date(2031, 3, 1), 20)
    book = json.loads(_book("solar", date(2031, 3, 1), life_end, a=(date(2031, 3, 1), date(2036, 3, 1), "10", 72.0),
                            b=(date(2031, 3, 1), date(2036, 3, 1), "10", 68.0)))
    book["streams"][2]["volume_share"] = 0.5
    with pytest.raises(ValueError):
        pi2 = apply_config(pi, json.dumps(book), project_type="solar")
        from finco_core.revenue.generation import revenue_decomposition_schedule
        revenue_decomposition_schedule(pi2, _build_period_engine(from_project_inputs(pi2)))


@pytest.mark.parametrize("technology", ["solar", "wind"])
def test_p90_shortfall_on_the_dated_grid_refuses_the_run_without_invented_settlement(technology):
    """Same dated calendar: the P50 cap admits the book, the selected P90 case cannot deliver the fixed quantity -> typed refusal, no haircut."""
    from finco_core.revenue.generation import revenue_decomposition_schedule

    cod = date(2031, 5, 15)
    pi = _project(technology, cod)
    life_end = _add_years(cod, 20)
    # fixed 30 GWh/yr: below P50 (80 GWh*avail) and above the P90 share only if hours drop enough -> use a tight P90 case
    tight = replace(pi.technical, operating_hours_p90_10y=300.0)          # 40 MW * 300 h * avail ~ 11 GWh/yr << 30 GWh
    pi = replace(pi, technical=tight)
    book = _book(technology, cod, life_end, a=(cod, date(2036, 5, 15), "30", 72.0), b=(cod, date(2036, 5, 15), "0", 68.0))
    p50 = apply_config(pi, book, project_type=technology)
    eng = _build_period_engine(from_project_inputs(p50))
    revenue_decomposition_schedule(p50, eng)                                   # feasible under P50
    p90 = replace(p50, technical=replace(p50.technical, yield_scenario="P90-10y"))
    with pytest.raises(Exception) as exc:
        revenue_decomposition_schedule(p90, eng)
    assert "R04_PHYSICAL_SHORTFALL_NO_SETTLEMENT_CONTRACT" in str(exc.value)


# ── STRICT per-period OPEX and accounting-depreciation oracles on the production operating model ─────────
def _opex_oracle(items, cod, start_incl, end_excl, horizon):
    end_life = _add_years(cod, horizon)
    total = Decimal(0)
    day, stop = max(start_incl, cod), min(end_excl, end_life)
    while day < stop:
        k = 0
        while _add_years(cod, k + 1) <= day:
            k += 1
        ydays = Decimal(366 if calendar.isleap(day.year) else 365)
        fixed = sum((Decimal(repr(i.y1_amount_keur)) * (Decimal(1) + Decimal(repr(i.annual_inflation))) ** k
                     for i in items if i.percentage_of_opex <= 0), Decimal(0))
        pct = sum((Decimal(repr(i.percentage_of_opex)) * fixed for i in items if i.percentage_of_opex > 0), Decimal(0))
        total += (fixed + pct) / ydays
        day += timedelta(days=1)
    return total


def _dep_oracle(dep, cod, rows):
    """rows: list of (start_incl, end_excl).  Straight line over each asset's actual in-service life, single final residual."""
    from finco_core.inputs import AssetClass, ASSET_CLASS_USEFUL_LIFE

    out = [Decimal(0)] * len(rows)
    for item in dep.book_capex_items_for_depreciation:
        basis = Decimal(repr(item.amount_keur))
        if basis <= 0:
            continue
        ac = AssetClass(item.asset_class_code)
        if item.useful_life_override is not None:
            life = int(item.useful_life_override)
        elif ac == AssetClass.FINANCIAL_COSTS:
            life = int(dep.financial_cost_useful_life_years)
        else:
            life = int(ASSET_CLASS_USEFUL_LIFE.get(ac, 14))
        if life <= 0:
            continue
        life_end = _add_years(cod, life)
        d_life = (life_end - cod).days
        overlaps = []
        for i, (a, b) in enumerate(rows):
            lo, hi = max(a, cod), min(b, life_end)
            if hi > lo:
                overlaps.append((i, (hi - lo).days))
        completes = sum(d for _, d in overlaps) == d_life
        cum = Decimal(0)
        for pos, (i, d) in enumerate(overlaps):
            dep_i = basis - cum if (completes and pos == len(overlaps) - 1) else min(basis * d / d_life, basis - cum)
            out[i] += dep_i
            cum += dep_i
    return out


@pytest.mark.parametrize("technology", ["solar", "wind"])
@pytest.mark.parametrize("cod", [date(2031, 1, 1), date(2031, 3, 1), date(2031, 5, 15), date(2031, 7, 1)])
def test_dated_opex_and_depreciation_match_independent_per_period_oracles(technology, cod):
    from financial_engine.orchestrator import run_operating_model

    pi = _with_r04(_project(technology, cod), technology)
    op_in = from_project_inputs(pi)
    res = run_operating_model(op_in)
    assert not any(i.step_changes for i in pi.opex)
    ops = [p for p in res.periods if p.is_operation]
    rows, prev = [], None
    for p in ops:
        rows.append((cod if prev is None else prev + timedelta(days=1), p.period_end + timedelta(days=1)))
        prev = p.period_end
    assert rows[-1][1] == _add_years(cod, 20)                                  # final stub ends exactly at COD + 20 years
    dep_expected = _dep_oracle(op_in.depreciation, cod, rows)
    tot_opex = tot_dep = Decimal(0)
    for (a, b), p, d in zip(rows, ops, dep_expected):
        e_opex = _opex_oracle(pi.opex, cod, a, b, 20)
        assert abs(float(e_opex) - p.opex_keur) <= 0.01, (technology, cod, p.period_index, float(e_opex), p.opex_keur)
        assert abs(float(d) - p.book_depreciation_keur) <= 0.01, (technology, cod, p.period_index, float(d), p.book_depreciation_keur)
        tot_opex += e_opex
        tot_dep += d
    assert abs(float(tot_opex) - sum(p.opex_keur for p in ops)) <= 0.01 * len(ops)
    assert abs(float(tot_dep) - sum(p.book_depreciation_keur for p in ops)) <= 0.01 * len(ops)
