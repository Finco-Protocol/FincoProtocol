"""PPA-01: explicit CPI/PPI index series on a Revenue V2 PPA stream, through the real canonical revenue adapter.

Independent oracle: every expected price and revenue is computed here with Decimal from the user's index levels and the engine's own period axis
(operating year, generation). Nothing is derived by calling the code under test, and no tolerance is looser than the existing Revenue V2 suites.
Convention (reconciled with the existing OPERATING_YEAR indexation): the series is keyed by MODEL OPERATING YEAR (year 1 = first operating year
from COD, the engine's ``year_index``); price = price_eur_mwh x level[year] / level[base], base = first observation.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
import subprocess
import sys
import types
from datetime import date
from decimal import Decimal, localcontext

import pytest

from app import project_factories as factories
from app.workbook.revenue_commercial_stress import changed_book
from app.workbook.revenue_multistream import apply_config
from domain.revenue.multistream_runtime import parse_config
from financial_engine.adapters.project_inputs import from_project_inputs
from financial_engine.orchestrator import _build_period_engine
from finco_core.revenue.generation import revenue_decomposition_schedule

PRICE_ABS = 1e-12            # same tolerances as tests/test_revenue_v2_advanced_curves.py
REVENUE_ABS = 1e-8


def _project(kind, mid_period_cod=False):
    pi = getattr(factories, "create_generic_" + kind + "_reference")()
    if mid_period_cod:        # non-calendar COD: the first operating period is partial (day_fraction < 1)
        pi = dataclasses.replace(pi, info=dataclasses.replace(
            pi.info, cod_date=date(2031, 4, 15), financial_close=date(2030, 2, 15), construction_months=14))
    return pi


def _operating(pi):
    return tuple(p for p in _build_period_engine(from_project_inputs(pi)).periods() if p.is_operation)


def _n(op):
    return op[-1].year_index          # operating years in the model (25 for Solar, 27 for Wind reference)


def _series(levels, first_year=1, basis="FORECAST"):
    return [{"operating_year": first_year + i, "level": level, "basis": basis} for i, level in enumerate(levels)]


def _payload(kind, operating, *, series=None, rate=0.0, start=0, end=None, share=0.6, price=60.0, extra=None):
    end_date = (operating[-1] if end is None else operating[end - 1]).end_date.isoformat()
    common = dict(settlement="SAME_PERIOD", source_ref="synthetic-independent-contract")
    ppa = dict(common, id="ppa-1", type="ppa", volume_share=share, price_eur_mwh=price, indexation_rate=rate,
               start_date=operating[start].start_date.isoformat(), end_date=end_date)
    if series is not None:
        ppa["index_series"] = series
    ppa.update(extra or {})
    market = dict(common, id="market", type="merchant", volume_share=None, price_eur_mwh=80.0, indexation_rate=0,
                  capture_rate=0.8, start_date=operating[0].start_date.isoformat(), end_date=operating[-1].end_date.isoformat())
    return {"version": 2, "technology": kind, "indexation_basis": "OPERATING_YEAR", "streams": [ppa, market]}


def _run(pi, payload, kind):
    project = apply_config(pi, json.dumps(payload), project_type=kind)
    return revenue_decomposition_schedule(project, _build_period_engine(from_project_inputs(project)))


def _expected_price(base, levels_by_year, year, base_year=1):
    return Decimal(str(base)) * Decimal(str(levels_by_year[year])) / Decimal(str(levels_by_year[base_year]))


def _assert_ppa_revenue(out, operating, expected_price_for_year, *, start=0, end=None, share="0.6"):
    last = len(operating) if end is None else end
    checked = 0
    for i, period in enumerate(operating):
        row = {s["id"]: s for s in out[period.index]["multistream_evidence"]["streams"]}["ppa-1"]
        if start <= i < last:
            price = expected_price_for_year(period.year_index)
            production = Decimal(str(out[period.index]["generation_mwh"]))
            assert row["price_eur_mwh"] == pytest.approx(float(price), abs=PRICE_ABS), (i, period.year_index)
            assert row["revenue_keur"] == pytest.approx(float(production * Decimal(share) * price / 1000), abs=REVENUE_ABS), i
            checked += 1
        else:
            assert row["status"] in ("not_started", "expired")
    assert checked


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_constant_index_leaves_the_price_unchanged_and_equals_a_fixed_ppa(kind):
    pi = _project(kind); op = _operating(pi)
    flat = _series([100.0] * _n(op))
    out = _run(pi, _payload(kind, op, series=flat), kind)
    fixed = _run(pi, _payload(kind, op), kind)
    _assert_ppa_revenue(out, op, lambda y: Decimal("60"))
    for period in op:                                         # full precision parity with the unindexed contract
        assert out[period.index]["multistream_evidence"]["streams"] == fixed[period.index]["multistream_evidence"]["streams"]


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("shape", ["increasing", "decreasing"])
def test_index_levels_rescale_the_base_price_by_operating_year(kind, shape):
    pi = _project(kind); op = _operating(pi)
    n = _n(op)
    levels = ([100.0, 102.5, 105.1] + [105.1 + 2.3 * i for i in range(1, n - 2)] if shape == "increasing"      # the user's example start
              else [100.0, 98.4, 97.0] + [97.0 - 0.9 * i for i in range(1, n - 2)])                              # deflation
    by_year = {i + 1: lvl for i, lvl in enumerate(levels)}
    out = _run(pi, _payload(kind, op, series=_series(levels)), kind)
    _assert_ppa_revenue(out, op, lambda y: _expected_price(60.0, by_year, y))


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_a_mid_period_cod_with_a_partial_first_period_uses_the_operating_year(kind):
    pi = _project(kind, mid_period_cod=True); op = _operating(pi)
    assert op[0].day_fraction < 0.3 and op[0].year_index == op[1].year_index == 1     # partial first period shares year 1's index
    levels = [100.0 + 2.5 * i for i in range(_n(op))]
    by_year = {i + 1: lvl for i, lvl in enumerate(levels)}
    out = _run(pi, _payload(kind, op, series=_series(levels)), kind)
    _assert_ppa_revenue(out, op, lambda y: _expected_price(60.0, by_year, y))


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_a_contract_beginning_after_cod_reads_its_own_operating_years(kind):
    pi = _project(kind); op = _operating(pi)
    start, end = 4, 40                                        # starts in operating year 3, ends before the horizon
    levels = [100.0 + 3.0 * i for i in range(_n(op))]
    by_year = {i + 1: lvl for i, lvl in enumerate(levels)}
    out = _run(pi, _payload(kind, op, series=_series(levels), start=start, end=end), kind)
    _assert_ppa_revenue(out, op, lambda y: _expected_price(60.0, by_year, y), start=start, end=end)
    # the base may also sit at the first priced year: then the stated price IS the price of that year
    first = op[start].year_index
    rebased = _series([150.0 + 3.0 * i for i in range(_n(op) - first + 1)], first_year=first)
    by_year2 = {r["operating_year"]: r["level"] for r in rebased}
    out2 = _run(pi, _payload(kind, op, series=rebased, start=start, end=end), kind)
    _assert_ppa_revenue(out2, op, lambda y: _expected_price(60.0, by_year2, y, base_year=first), start=start, end=end)
    row = {s["id"]: s for s in out2[op[start].index]["multistream_evidence"]["streams"]}["ppa-1"]
    assert row["price_eur_mwh"] == pytest.approx(60.0, abs=PRICE_ABS)


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_an_annual_percentage_expressed_as_levels_matches_legacy_rate_indexation(kind):
    pi = _project(kind); op = _operating(pi)
    levels = [100.0 * 1.02 ** i for i in range(_n(op))]
    out = _run(pi, _payload(kind, op, series=_series(levels)), kind)
    legacy = _run(pi, _payload(kind, op, rate=0.02), kind)
    for period in op:
        a = {s["id"]: s for s in out[period.index]["multistream_evidence"]["streams"]}["ppa-1"]
        b = {s["id"]: s for s in legacy[period.index]["multistream_evidence"]["streams"]}["ppa-1"]
        assert a["price_eur_mwh"] == pytest.approx(b["price_eur_mwh"], rel=1e-12)
        assert a["revenue_keur"] == pytest.approx(b["revenue_keur"], rel=1e-12, abs=1e-9)


def test_legacy_contracts_are_byte_for_byte_unchanged():
    pi = _project("solar"); op = _operating(pi)
    payload = _payload("solar", op, rate=0.015)
    cfg = parse_config(json.dumps(payload))
    assert json.loads(cfg.canonical_json) == payload and all(not s.index_series for s in cfg.streams)
    assert "index_series" not in cfg.canonical_json


@pytest.mark.parametrize("missing_year", [None, True, 1.0, "1", 0, -1])
def test_active_index_pricing_without_a_typed_operating_year_fails_closed(missing_year):
    op = _operating(_project("solar"))
    cfg = parse_config(json.dumps(_payload("solar", op, series=_series([100.0 + i for i in range(_n(op))]))))
    with pytest.raises(ValueError, match="REVENUE_V2_INDEX_YEAR_CONTEXT"):
        cfg.plan_at(op[0].start_date, missing_year)


def test_structural_validation_cannot_be_mistaken_for_a_financial_price_plan():
    op = _operating(_project("solar"))
    # Parsing validates allocation even though the runtime axis/year is not supplied yet.
    cfg = parse_config(json.dumps(_payload("solar", op, series=_series([100.0, 106.0, 115.0]))))
    assert cfg.validate_structure_at(op[0].start_date) is None
    with pytest.raises(ValueError, match="REVENUE_V2_INDEX_YEAR_CONTEXT"):
        cfg.plan_at(op[0].start_date)
    third = next(p for p in op if p.year_index == 3)
    resolved = cfg.plan_at(third.start_date, third.year_index)
    assert resolved.streams[0].ppa.ppa_base_price_eur_mwh == pytest.approx(float(Decimal("60") * Decimal("115") / Decimal("100")), abs=PRICE_ABS)
    with pytest.raises(ValueError, match="REVENUE_V2_INDEX_COVERAGE"):
        cfg.validate_axis(op)


def test_structural_validation_still_rejects_volume_double_allocation():
    op = _operating(_project("solar"))
    raw = _payload("solar", op, series=_series([100.0, 106.0]), share=0.7)
    raw["streams"][1]["volume_share"] = 0.4
    with pytest.raises(ValueError):
        parse_config(json.dumps(raw))


def test_inactive_index_contract_does_not_require_an_irrelevant_pricing_year():
    op = _operating(_project("solar"))
    first = op[4].year_index
    cfg = parse_config(json.dumps(_payload("solar", op, series=_series([100.0, 110.0], first_year=first), start=4, end=8)))
    plan = cfg.plan_at(op[0].start_date)
    assert not plan.streams[0].enabled and plan.streams[1].enabled


def test_legacy_unindexed_pricing_remains_available_without_year_context():
    op = _operating(_project("solar"))
    cfg = parse_config(json.dumps(_payload("solar", op, rate=.015)))
    assert cfg.plan_at(op[0].start_date) == cfg.plan_at(op[0].start_date, 1)


@pytest.fixture(scope="module")
def released_runtime():
    """Immutable pre-PPA-01 implementation, not a regenerated golden or a runtime input."""
    repo = Path(__file__).resolve().parents[1]
    ref = "540e1f4bb54d53ad6d2c1628074b94fdb0c9eb06:domain/revenue/multistream_runtime.py"
    blob = subprocess.run(["git", "rev-parse", ref], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
    assert blob == "83beda4eb296b02baf2ebd6659fec243ab196206"
    source = subprocess.run(["git", "show", ref], cwd=repo, check=True, capture_output=True).stdout
    name = "_ppa01_released_runtime_reference"
    module = types.ModuleType(name)
    sys.modules[name] = module
    try:
        exec(compile(source, ref, "exec"), module.__dict__)
        yield module
    finally:
        sys.modules.pop(name, None)


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("mid_period_cod", [False, True])
@pytest.mark.parametrize("contract", ["fixed", "annual_index", "cfd", "scheduled_ppa", "scheduled_merchant"])
def test_legacy_full_revenue_schedule_is_bit_exact_against_released_content(kind, mid_period_cod, contract, released_runtime, monkeypatch):
    from domain.revenue import multistream_runtime

    pi = _project(kind, mid_period_cod=mid_period_cod)
    op = _operating(pi)
    payload = _payload(kind, op, rate=.02 if contract == "annual_index" else 0)
    payload["version"] = 1
    if contract.startswith("scheduled_"):
        payload["version"] = 2
        row = payload["streams"][0 if contract == "scheduled_ppa" else 1]
        row["price_curve"] = [{"period_start": p.start_date.isoformat(), "price_eur_mwh": 52.0 if i < 4 else 81.0}
                              for i, p in enumerate(op)]
    if contract == "cfd":
        payload["streams"].append(dict(id="settlement", type="cfd", volume_share=.4, price_eur_mwh=75.0,
            indexation_rate=0, reference_stream_id="market", start_date=op[0].start_date.isoformat(),
            end_date=op[-1].end_date.isoformat(), settlement="SAME_PERIOD", source_ref="synthetic-settlement"))
    active = apply_config(pi, json.dumps(payload), project_type=kind)
    axis = _build_period_engine(from_project_inputs(active))
    candidate = revenue_decomposition_schedule(active, axis)
    with monkeypatch.context() as reference:
        reference.setattr(multistream_runtime, "parse_config", released_runtime.parse_config)
        original = revenue_decomposition_schedule(active, axis)
    assert candidate == original


def test_floor_and_cap_still_apply_to_the_series_price():
    pi = _project("solar"); op = _operating(pi)
    levels = [100.0 + 10.0 * i for i in range(_n(op))]
    cfg = parse_config(json.dumps(_payload("solar", op, series=_series(levels))))
    ppa = cfg.streams[0]
    capped = dataclasses.replace(ppa, stream=dataclasses.replace(ppa.stream, ppa=dataclasses.replace(ppa.stream.ppa, ppa_price_cap=75.0)))
    cfg_capped = dataclasses.replace(cfg, streams=(capped, cfg.streams[1]))
    deflating = [100.0 - 2.0 * i for i in range(_n(op))]
    cfg2 = parse_config(json.dumps(_payload("solar", op, series=_series(deflating))))
    p2 = cfg2.streams[0]
    floored = dataclasses.replace(p2, stream=dataclasses.replace(p2.stream, ppa=dataclasses.replace(p2.stream.ppa, ppa_price_floor=55.0)))
    cfg_floored = dataclasses.replace(cfg2, streams=(floored, cfg2.streams[1]))
    late = next(p for p in op if p.year_index == 10)
    price = lambda config, period: {r.stream_id: r for r in config.evaluate(period, 1000.0).stream_results}["ppa-1"].price_eur_mwh  # noqa: E731
    assert price(cfg, late) == pytest.approx(60.0 * 190.0 / 100.0, abs=PRICE_ABS)            # uncapped series price: 114
    assert price(cfg_capped, late) == 75.0                                                     # the existing cap still bounds it
    assert price(cfg_floored, late) == 55.0                                                    # 60 x 82/100 = 49.2 -> floored


@pytest.mark.parametrize("bad, code", [
    ([], "REVENUE_V2_INDEX_POINTS"),                                                     # an empty series is not a series
    ([{"operating_year": 1, "level": 100.0, "basis": "FORECAST"}, {"operating_year": 1, "level": 101.0, "basis": "FORECAST"}], "REVENUE_V2_INDEX_ORDER"),
    ([{"operating_year": 2, "level": 100.0, "basis": "FORECAST"}, {"operating_year": 1, "level": 101.0, "basis": "FORECAST"}], "REVENUE_V2_INDEX_ORDER"),
    ([{"operating_year": 1, "level": 100.0, "basis": "FORECAST"}, {"operating_year": 3, "level": 101.0, "basis": "FORECAST"}], "REVENUE_V2_INDEX_GAP"),
    (_series([100.0, 0.0]), "REVENUE_V2_INDEX_LEVEL"),
    (_series([100.0, -5.0]), "REVENUE_V2_INDEX_LEVEL"),
    (_series([0.0, 100.0]), "REVENUE_V2_INDEX_LEVEL"),
    (_series([100.0, True]), "REVENUE_V2_INDEX_LEVEL"),
    (_series([100.0, "101"]), "REVENUE_V2_INDEX_LEVEL"),
    ([{"operating_year": 1, "level": 100.0, "basis": "GUESS"}, {"operating_year": 2, "level": 101.0, "basis": "FORECAST"}], "REVENUE_V2_INDEX_BASIS"),
    ([{"operating_year": 0, "level": 100.0, "basis": "FORECAST"}, {"operating_year": 1, "level": 101.0, "basis": "FORECAST"}], "REVENUE_V2_INDEX_YEAR"),
    ([{"operating_year": 1, "level": 100.0}, {"operating_year": 2, "level": 101.0}], "REVENUE_V2_SCHEMA"),
])
def test_malformed_series_fail_closed_at_parse(bad, code):
    op = _operating(_project("solar"))
    with pytest.raises(ValueError, match=code):
        parse_config(json.dumps(_payload("solar", op, series=bad)))


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_levels_are_rejected_even_in_raw_json(literal):
    op = _operating(_project("solar"))
    raw = json.dumps(_payload("solar", op, series=_series([100.0, 101.0]))).replace('"level": 101.0', f'"level": {literal}')
    with pytest.raises(ValueError, match="REVENUE_V2_INDEX_LEVEL"):
        parse_config(raw)


def test_an_unsupported_or_mixed_basis_is_refused_not_resolved():
    op = _operating(_project("solar"))
    with pytest.raises(ValueError, match="REVENUE_V2_INDEX_MIXED_BASIS"):                    # annual rate AND index levels
        parse_config(json.dumps(_payload("solar", op, series=_series([100.0, 101.0]), rate=0.02)))
    curve = [{"period_start": p.start_date.isoformat(), "price_eur_mwh": 60.0} for p in op]
    with pytest.raises(ValueError, match="REVENUE_V2_INDEX_MIXED_BASIS"):                    # explicit prices AND index levels
        parse_config(json.dumps(_payload("solar", op, series=_series([100.0, 101.0]), extra={"price_curve": curve})))
    p = _payload("solar", op, series=_series([100.0, 101.0])); p["version"] = 1
    with pytest.raises(ValueError, match="REVENUE_V2_INDEX_UNSUPPORTED"):
        parse_config(json.dumps(p))
    p = _payload("solar", op, series=_series([100.0, 101.0])); p["streams"][0]["type"] = "merchant"
    with pytest.raises(ValueError, match="REVENUE_V2_INDEX_UNSUPPORTED"):
        parse_config(json.dumps(p))


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_missing_future_observations_are_never_extrapolated(kind):
    pi = _project(kind); op = _operating(pi)
    with pytest.raises(ValueError, match="REVENUE_V2_INDEX_COVERAGE"):
        apply_config(pi, json.dumps(_payload(kind, op, series=_series([100.0 + i for i in range(12)]))), project_type=kind)   # later years unobserved
    with pytest.raises(ValueError, match="REVENUE_V2_INDEX_BASE"):                          # base after the first priced year
        apply_config(pi, json.dumps(_payload(kind, op, series=_series([100.0 + i for i in range(20)], first_year=3))), project_type=kind)
    # A contract that ends earlier needs only the years it prices
    apply_config(pi, json.dumps(_payload(kind, op, series=_series([100.0 + i for i in range(12)]), end=24)), project_type=kind)


def test_commercial_stress_scales_a_series_price_proportionally_without_touching_the_levels():
    pi = _project("solar"); op = _operating(pi)
    levels = [100.0 + 2.5 * i for i in range(_n(op))]
    raw = apply_config(pi, json.dumps(_payload("solar", op, series=_series(levels))), project_type="solar").revenue.multistream_config_json
    shocked = json.loads(changed_book(raw, "ppa_down", 10))
    assert shocked["streams"][0]["index_series"] == json.loads(raw)["streams"][0]["index_series"]
    assert shocked["streams"][0]["price_eur_mwh"] == pytest.approx(54.0)


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("price,level", [(60.0, 1e308), (1e-200, 1e-200), (1e-300, 1e-200),
                                      (1e-320, 1e-300), (1e200, 1e200), (0.0, 1e308)])
def test_model_year_base_identity_survives_extreme_index_scales(kind, price, level):
    pi = _project(kind); op = _operating(pi)
    raw = _payload(kind, op, price=price, series=_series([level] * _n(op)))
    out = _run(pi, raw, kind)
    cfg = parse_config(json.dumps(raw))
    for period in op:
        row = next(r for r in out[period.index]["multistream_evidence"]["streams"] if r["id"] == "ppa-1")
        with localcontext() as context:
            context.prec = 80
            expected = Decimal(str(price)) * Decimal(str(level)) / Decimal(str(level))
        assert row["price_eur_mwh"] == float(expected) == price
        if price > 0:
            assert row["revenue_keur"] > 0
        else:
            assert row["revenue_keur"] == 0
    controlled = next(r for r in cfg.evaluate(op[0], 1000).stream_results if r.stream_id == "ppa-1")
    with localcontext() as context:
        context.prec = 80
        # The unchanged revenue kernel rounds EUR multiplication before kEUR conversion.
        gross_eur = float(Decimal(600) * Decimal.from_float(price))
        expected_revenue = float(Decimal.from_float(gross_eur) / Decimal(1000))
    assert controlled.stream_revenue_keur == expected_revenue
    if price == 1e-200:
        assert controlled.stream_revenue_keur == 6e-201


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("base_level,later_level", [(1e-308, 1e308), (1e308, 1e-308)])
def test_genuine_zero_base_price_is_not_rejected_for_an_extreme_index_ratio(kind, base_level, later_level):
    pi = _project(kind); op = _operating(pi)
    raw = _payload(kind, op, price=0, series=_series([base_level] + [later_level] * (_n(op) - 1)))
    for row in _run(pi, raw, kind).values():
        assert row["ppa_revenue_keur"] == 0
        if row["is_operation"]:
            assert row["ppa_tariff_eur_mwh"] == 0


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("scale", ["1e-300", "1e-200", "1", "1e200", "1e300"])
def test_model_year_index_scale_invariance_uses_the_canonical_schedule(kind, scale):
    pi = _project(kind); op = _operating(pi)
    unscaled = [100, 125, 80] + [110] * (_n(op) - 3)
    levels = [float(Decimal(level) * Decimal(scale)) for level in unscaled]
    out = _run(pi, _payload(kind, op, series=_series(levels)), kind)
    for period in op:
        row = next(r for r in out[period.index]["multistream_evidence"]["streams"] if r["id"] == "ppa-1")
        with localcontext() as context:
            context.prec = 80
            expected = Decimal("60") * Decimal(str(levels[period.year_index - 1])) / Decimal(str(levels[0]))
        assert row["price_eur_mwh"] == float(expected)
        assert row["price_eur_mwh"] == 60 * unscaled[period.year_index - 1] / 100


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("price,base_level,later_level", [(60.0, 1e-308, 1e308), (1e-200, 1e308, 1e-308)])
def test_unrepresentable_final_model_year_price_refuses_the_production_schedule(kind, price, base_level, later_level):
    pi = _project(kind); op = _operating(pi)
    levels = [base_level] + [later_level] * (_n(op) - 1)
    with localcontext() as context:
        context.prec = 80
        expected = Decimal(str(price)) * Decimal(str(later_level)) / Decimal(str(base_level))
    converted = float(expected)
    assert expected > 0 and (converted == float("inf") or converted == 0)
    raw = _payload(kind, op, price=price, series=_series(levels))
    # Valid observations and full axis coverage do not authorize an unrepresentable price.
    parse_config(json.dumps(raw)).validate_axis(op)
    with pytest.raises(ValueError, match="REVENUE_V2_INDEX_PRICE"):
        _run(pi, raw, kind)
