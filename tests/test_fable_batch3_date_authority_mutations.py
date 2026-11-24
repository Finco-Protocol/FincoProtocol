"""FINCO 36 Correction F — mutation witnesses on the INTEGRATED production path.

The same strict independent oracles as ``test_fable_batch3_date_authority_generation`` are evaluated against the real production
functions (``revenue_decomposition_schedule`` / ``run_operating_model``).  Un-mutated they pass; each deliberately wrong
production behaviour must make the oracle fail (mismatch > tolerance, or a typed refusal).
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

import finco_core.engine.date_authority as da
import finco_core.engine.contractual_calendar as cc
from finco_core.revenue import generation as gen
from financial_engine.adapters.project_inputs import from_project_inputs
from financial_engine.orchestrator import _build_period_engine, run_operating_model
from tests.test_fable_batch3_date_authority_generation import (
    _add_years, _book, _dep_oracle, _opex_oracle, _oracle_generation, _oracle_row, _project, _with_r04,
)
from app.workbook.revenue_multistream import apply_config

COD = date(2031, 5, 15)
HORIZON = 20


def _oracle_matches(technology="solar") -> bool:
    """True iff generation, contract revenue, OPEX and depreciation of the production path equal the independent oracles."""
    pi = _project(technology, COD)
    life_end = _add_years(COD, HORIZON)
    a, b = (date(2031, 9, 10), date(2041, 2, 20), "25", 72.0), (COD, date(2036, 5, 15), "15", 68.0)
    try:
        pi = apply_config(pi, _book(technology, COD, life_end, a=a, b=b, pm=55.0), project_type=technology)
        eng = _build_period_engine(from_project_inputs(pi))
        schedule = gen.full_generation_schedule(pi, eng)
        dec = gen.revenue_decomposition_schedule(pi, eng)
        res = run_operating_model(from_project_inputs(pi))
    except Exception:       # typed refusal / mismatch of the axis is also a detected mutation
        return False
    t = pi.technical
    contracts = [("ppa_a", a[0], a[1], a[2], a[3]), ("ppa_b", b[0], b[1], b[2], b[3])]
    ops = [p for p in res.periods if p.is_operation]
    rows, prev = [], None
    for p in ops:
        rows.append((COD if prev is None else prev + timedelta(days=1), p.period_end + timedelta(days=1)))
        prev = p.period_end
    if rows[-1][1] != life_end:
        return False
    dep = _dep_oracle(from_project_inputs(pi).depreciation, COD, rows)
    for (s, e), p, d in zip(rows, ops, dep):
        mwh = _oracle_generation(COD, HORIZON, s, e, t.capacity_mw, t.operating_hours_p50, t.combined_availability, t.pv_degradation)
        per, merch = _oracle_row(COD, HORIZON, s, e, t, contracts, 55.0)
        row = dec[p.period_index]
        checks = [
            abs(float(mwh) - schedule[p.period_index]) <= 0.001,
            abs(float(per["ppa_a"][1] + per["ppa_b"][1]) - row["ppa_revenue_keur"]) <= 0.01,
            abs(float(merch[1]) - row["gross_merchant_revenue_keur"]) <= 0.01,
            abs(float(_opex_oracle(pi.opex, COD, s, e, HORIZON)) - p.opex_keur) <= 0.01,
            abs(float(d) - p.book_depreciation_keur) <= 0.01,
        ]
        if not all(checks):
            return False
    return True


def test_unmutated_production_path_satisfies_every_oracle():
    assert _oracle_matches("solar") and _oracle_matches("wind")


def _shift_start_by_one_day(monkeypatch):
    original = da.legacy_operating_intervals

    def mutated(engine, cod):
        return {k: cc.ContractualInterval(v.start + timedelta(days=1), v.end_exclusive) for k, v in original(engine, cod).items()}
    monkeypatch.setattr(da, "legacy_operating_intervals", mutated)


def _ignore_contract_expiry(monkeypatch):
    """Physical allocation keeps delivering one year past the contractual expiry (expiry ignored / moved)."""
    import dataclasses
    from domain.revenue import r04_global_p50_cap as cap
    original = cap.allocate_r04_period_deliveries

    def mutated(iv, *, contracts, **kw):
        moved = [dataclasses.replace(c, end_date=_add_years(c.end_date, 1)) for c in contracts]
        return original(iv, contracts=moved, **kw)
    monkeypatch.setattr(cap, "allocate_r04_period_deliveries", mutated)
    from domain.revenue import multistream_runtime as ms
    monkeypatch.setattr(ms.DatedRevenueStream, "active", lambda self, when: self.start_date <= when < _add_years(self.end_date, 1))


def _calendar_clock_opex(monkeypatch):
    original = da.dated_opex_schedule
    monkeypatch.setattr(da, "dated_opex_schedule", lambda inputs, engine, clock="CALENDAR_YEAR": original(inputs, engine, clock="CALENDAR_YEAR"))


def _p90_instead_of_p50(monkeypatch):
    monkeypatch.setattr(gen, "_selected_operating_hours", lambda tech, scenario=None: tech.operating_hours_p90_10y)


def _double_degradation(monkeypatch):
    original = cc.contractual_generation_for_interval

    def mutated(interval, **kw):
        kw["annual_degradation"] = 2 * kw["annual_degradation"]
        return original(interval, **kw)
    monkeypatch.setattr(da, "contractual_generation_for_interval", mutated)


def _lost_final_stub(monkeypatch):
    monkeypatch.setattr("financial_engine.orchestrator.__dict__", {}, raising=False) if False else None
    import finco_core.engine.date_authority as module
    monkeypatch.setattr(module, "dated_life_end_exclusive", lambda *a, **k: None)


def _wrong_depreciation(monkeypatch):
    original = cc.contractual_depreciation_schedule

    def mutated(*a, **k):
        summary = original(*a, **k)
        import dataclasses
        return dataclasses.replace(summary, period_depreciation_keur={i: v * 0.5 for i, v in summary.period_depreciation_keur.items()})
    monkeypatch.setattr(cc, "contractual_depreciation_schedule", mutated)


def _missing_price_as_zero(monkeypatch):
    from domain.revenue import multistream_runtime as ms
    original = ms.MultiStreamRevenue.evaluate

    def mutated(self, period, generation_mwh):
        res = original(self, period, generation_mwh)
        from dataclasses import replace
        return replace(res, stream_results=tuple(replace(r, stream_revenue_keur=0.0) if r.stream_id == "ppa_a" else r for r in res.stream_results),
                       total_revenue_keur=res.total_revenue_keur - sum(r.stream_revenue_keur or 0.0 for r in res.stream_results if r.stream_id == "ppa_a"))
    monkeypatch.setattr(ms.MultiStreamRevenue, "evaluate", mutated)


MUTATIONS = {
    "plus_one_day_lost_cod_day": _shift_start_by_one_day,
    "ignored_contract_expiry": _ignore_contract_expiry,
    "annual_step_timing_calendar_instead_of_cod_anniversary": _calendar_clock_opex,
    "p90_hours_instead_of_p50": _p90_instead_of_p50,
    "double_degradation": _double_degradation,
    "lost_final_stub": _lost_final_stub,
    "wrong_accounting_depreciation": _wrong_depreciation,
    "missing_price_treated_as_zero": _missing_price_as_zero,
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_each_mutation_of_the_production_path_fails_the_independent_oracle(name, monkeypatch):
    MUTATIONS[name](monkeypatch)
    assert _oracle_matches("solar") is False, f"mutation {name!r} was NOT detected by the oracle"
