"""Independent Decimal oracles through the existing canonical Revenue V2 path."""
import copy
from dataclasses import replace
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP, localcontext
import json

import pytest

from domain.revenue.multistream_runtime import parse_config
from domain.revenue.revenue_config import PPAContractPriceRounding
from tests.test_ppa01_index_series_revenue import _project, _operating, _payload, _series, _n, _run
from tests.test_ppa01_contractual_timing import project, terms, dated, book


def policy(places=2, method="HALF_UP", enabled=True):
    return dict(enabled=enabled, decimal_places=places, method=method)


def rounded(value, places=2, method="HALF_UP"):
    with localcontext() as context:
        context.prec = 100
        return Decimal(value).quantize(Decimal(1).scaleb(-places),
            rounding=ROUND_HALF_UP if method == "HALF_UP" else ROUND_HALF_EVEN)


def with_policy(raw, selected=None):
    raw = copy.deepcopy(raw)
    raw["streams"][0]["price_rounding"] = policy() if selected is None else selected
    return raw


def ppa_row(out, period):
    return next(r for r in out[period.index]["multistream_evidence"]["streams"] if r["id"] == "ppa-1")


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("places", [2, 3, 4, 6])
@pytest.mark.parametrize("method", ["HALF_UP", "HALF_EVEN"])
def test_precisions_apply_only_after_the_base_observation_and_never_recurse(kind, places, method):
    pi = _project(kind); op = _operating(pi)
    levels = [100, 102, 105] + [110] * (_n(op) - 3)
    raw = with_policy(_payload(kind, op, price=62.3456785, series=_series(levels)), policy(places, method))
    out = _run(pi, raw, kind)
    for period in op:
        row = ppa_row(out, period)
        unrounded = Decimal("62.3456785") * Decimal(levels[period.year_index - 1]) / 100
        expected = unrounded if period.year_index == 1 else rounded(unrounded, places, method)
        assert row["price_eur_mwh"] == float(expected)
        assert row["revenue_keur"] == pytest.approx(float(Decimal(str(row["quantity_mwh"])) * expected / 1000), rel=0, abs=1e-8)
    assert ppa_row(out, op[0])["price_eur_mwh"] == ppa_row(out, op[1])["price_eur_mwh"] == 62.3456785


@pytest.mark.parametrize("indexed,method,expected", [
    ("62.345", "HALF_UP", "62.35"), ("62.345", "HALF_EVEN", "62.34"),
    ("62.355", "HALF_UP", "62.36"), ("62.355", "HALF_EVEN", "62.36"),
    ("63.07404", "HALF_UP", "63.07"),
])
def test_real_decimal_ties_and_revenue_are_resolved_in_the_canonical_kernel(indexed, method, expected):
    pi = _project("solar"); op = _operating(pi)
    base = Decimal(50)
    level = float(Decimal(indexed) * 10000 / base)
    raw = with_policy(_payload("solar", op, price=50, share=1,
        series=_series([10000] + [level] * (_n(op) - 1))), policy(method=method))
    cfg = parse_config(json.dumps(raw))
    second_year = next(p for p in op if p.year_index == 2)
    row = next(r for r in cfg.evaluate(second_year, 1000).stream_results if r.stream_id == "ppa-1")
    assert row.price_eur_mwh == float(expected)
    assert row.stream_revenue_keur == float(expected)
    assert rounded(base * Decimal(str(level)) / 10000, method=method) == Decimal(expected)
    assert ppa_row(_run(pi, raw, "solar"), second_year)["price_eur_mwh"] == float(expected)


@pytest.mark.parametrize("raw_price,floor,cap,method,expected", [
    (62.355, 0, 62.345, "HALF_UP", 62.35),
    (62.335, 62.345, 0, "HALF_EVEN", 62.34),
])
def test_post_floor_cap_rounding_can_cross_the_nominal_bound_without_a_hidden_reclamp(raw_price, floor, cap, method, expected):
    pi = _project("solar"); op = _operating(pi)
    cfg = parse_config(json.dumps(with_policy(_payload("solar", op, price=raw_price,
        series=_series([100] * _n(op))), policy(method=method))))
    dated_stream = cfg.streams[0]
    ppa = replace(dated_stream.stream.ppa, ppa_price_floor=floor, ppa_price_cap=cap)
    cfg = replace(cfg, streams=(replace(dated_stream, stream=replace(dated_stream.stream, ppa=ppa)), cfg.streams[1]))
    period = next(p for p in op if p.year_index == 2)
    quote = cfg.price_details(period.start_date, period.year_index)["ppa-1"]
    assert Decimal(quote["price_after_floor_cap"]) == Decimal("62.345")
    assert quote["effective_price"] == expected
    row = next(r for r in cfg.evaluate(period, 1000).stream_results if r.stream_id == "ppa-1")
    assert row.price_eur_mwh == expected
    assert row.stream_revenue_keur == 600 * expected / 1000
    assert (cap and expected > cap) or (floor and expected < floor)


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("rule,anchor,start", [
    ("SIGNATURE", "2028-12-31", 0), ("COD", "2030-12-31", 0),
    ("CUSTOM", "2029-12-31", 0), ("PPA_START", "2031-12-31", 2),
])
@pytest.mark.parametrize("method", ["ANNUAL_FIXED", "DATED_INDEX_LEVELS"])
def test_rounding_keeps_four_anchors_pre_cod_and_delayed_sales(kind, rule, anchor, start, method):
    pi = project(kind); op = _operating(pi)
    timing = terms(rule, anchor=anchor)
    if method == "DATED_INDEX_LEVELS":
        # Supply exactly the annual reviews for this explicit anchor.
        timing = dated(timing, op[-1].end_date.isoformat())
        timing["reviews"] = [r for r in timing["reviews"] if r["effective_date"] > anchor]
    raw = with_policy(book(pi, kind, timing, start=start, rate=0 if method == "DATED_INDEX_LEVELS" else .02))
    raw["streams"][0]["price_eur_mwh"] = 60.005
    out = _run(pi, raw, kind)
    levels = {p["reference_date"]: Decimal(str(p["level"])) for p in timing.get("observations", [])}
    references = {r["effective_date"]: r["reference_date"] for r in timing.get("reviews", [])}
    for period in op:
        row = ppa_row(out, period)
        if period.start_date < date.fromisoformat(raw["streams"][0]["start_date"]):
            assert row["quantity_mwh"] == row["revenue_keur"] == 0
            continue
        completed = [date(y, 12, 31) for y in range(int(anchor[:4]) + 1, period.start_date.year + 1)
                     if date(y, 12, 31) <= period.start_date]
        expected = Decimal("60.005")
        if completed:
            if method == "ANNUAL_FIXED":
                expected *= Decimal("1.02") ** len(completed)
            else:
                expected *= levels[references[completed[-1].isoformat()]] / levels[timing["index_base_date"]]
            expected = rounded(expected)
        assert row["price_eur_mwh"] == float(expected)


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("selected", [{"enabled": False}, policy(enabled=False)])
def test_absent_and_disabled_are_bit_exact_for_legacy_and_all_indexing_methods(kind, partial, selected):
    pi = project(kind, partial); op = _operating(pi)
    books = [_payload(kind, op), _payload(kind, op, rate=.025),
             _payload(kind, op, series=_series([100 + y for y in range(_n(op))])),
             book(pi, kind), book(pi, kind, dated(terms(), op[-1].end_date.isoformat()), rate=0)]
    for raw in books:
        assert _run(pi, raw, kind) == _run(pi, with_policy(raw, selected), kind)


@pytest.mark.parametrize("price,base,later", [(1e-200, 1e-200, 1e-200), (0, 1e-308, 1e308), (60, 1e308, 1e308)])
def test_intentionally_rounded_zero_is_not_arithmetic_underflow(price, base, later):
    pi = _project("solar"); op = _operating(pi)
    raw = with_policy(_payload("solar", op, price=price, series=_series([base] + [later] * (_n(op) - 1))))
    out = _run(pi, raw, "solar")
    expected = float(rounded(Decimal(str(price)) * Decimal(str(later)) / Decimal(str(base))))
    assert ppa_row(out, op[0])["price_eur_mwh"] == price
    assert ppa_row(out, next(p for p in op if p.year_index == 2))["price_eur_mwh"] == expected


@pytest.mark.parametrize("invalid", [None, [], {}, {"enabled": 1}, {"enabled": "false"},
    {"enabled": True}, policy(places=True), policy(places=2.0), policy(places="2"),
    policy(places=5), policy(method="DOWN"), {**policy(), "extra": 1}])
def test_rounding_schema_is_strict(invalid):
    pi = _project("solar"); op = _operating(pi)
    raw = with_policy(_payload("solar", op, rate=.02), invalid) if invalid is not None else _payload("solar", op, rate=.02)
    raw["streams"][0]["price_rounding"] = invalid
    with pytest.raises(ValueError):
        parse_config(json.dumps(raw))


def test_rounding_cannot_be_enabled_for_other_streams_versions_or_scheduled_prices():
    pi = _project("solar"); op = _operating(pi)
    raw = with_policy(_payload("solar", op, rate=.02))
    raw["version"] = 1
    with pytest.raises(ValueError, match="PRICE_ROUNDING"):
        parse_config(json.dumps(raw))
    raw["version"] = 2
    raw["streams"][1]["price_rounding"] = policy()
    with pytest.raises(ValueError, match="PRICE_ROUNDING"):
        parse_config(json.dumps(raw))
    del raw["streams"][1]["price_rounding"]
    raw["streams"][0]["indexation_rate"] = 0
    raw["streams"][0]["price_curve"] = [{"period_start": p.start_date.isoformat(), "price_eur_mwh": 60} for p in op]
    with pytest.raises(ValueError, match="PRICE_ROUNDING"):
        parse_config(json.dumps(raw))


def test_true_unrepresentable_rounded_price_still_fails_closed():
    pi = _project("solar"); op = _operating(pi)
    raw = with_policy(_payload("solar", op, price=60, series=_series([1e-308] + [1e308] * (_n(op) - 1))))
    with pytest.raises(ValueError, match="ROUNDING_PRICE"):
        _run(pi, raw, "solar")


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("selected", [None, {"enabled": False}, policy()])
def test_dated_decimal_underflow_is_rejected_unless_explicit_rounding_makes_zero(kind, selected):
    pi = project(kind); op = _operating(pi)
    timing = dated(terms(), op[-1].end_date.isoformat())
    timing["observations"][0]["level"] = 1e308
    for point in timing["observations"][1:]:
        point["level"] = 1e-308
    raw = book(pi, kind, timing, rate=0)
    raw["streams"][0]["price_eur_mwh"] = 1e-200
    if selected is not None:
        raw = with_policy(raw, selected)
    expected = Decimal("1e-200") * Decimal("1e-308") / Decimal("1e308")
    assert expected == Decimal("1e-816") and expected > 0 and float(expected) == 0
    if selected and selected["enabled"]:
        out = _run(pi, raw, kind)
        assert all(ppa_row(out, p)["price_eur_mwh"] == 0 for p in op)
    else:
        with pytest.raises(ValueError, match="REVENUE_V2_TIMING_PRICE:.*underflow to zero"):
            _run(pi, raw, kind)


@pytest.mark.parametrize("base,level,expected", [(1e-200, 1e-120, Decimal("1e-320")),
    (1e-200, 5e-124, Decimal("5e-324")), (0, 1e-308, Decimal(0))])
def test_dated_disabled_preserves_representable_subnormals_and_genuine_zero(base, level, expected):
    pi = project("solar"); op = _operating(pi)
    timing = dated(terms(), op[-1].end_date.isoformat())
    timing["observations"][0]["level"] = 1
    for point in timing["observations"][1:]:
        point["level"] = level
    raw = book(pi, "solar", timing, rate=0)
    raw["streams"][0]["price_eur_mwh"] = base
    oracle = Decimal(str(base)) * Decimal(str(level))
    assert oracle == expected
    out = _run(pi, raw, "solar")
    assert all(ppa_row(out, p)["price_eur_mwh"] == float(oracle) for p in op)
    if expected > 0:
        assert float(oracle) > 0


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("strike", [40, 100])
def test_enabled_ppa_rounding_does_not_change_merchant_or_signed_cfd(kind, strike):
    from tests.test_wf07_revenue_multistream import contracts
    pi = _project(kind); op = _operating(pi)
    raw = contracts(pi, kind, price=62.345, strike=strike, index=.02)
    raw['version'] = 2
    before = _run(pi, raw, kind)
    after = _run(pi, with_policy(raw), kind)
    for p in op:
        rows = lambda result: {r['id']: r for r in result[p.index]['multistream_evidence']['streams']}
        assert rows(before)['market-1'] == rows(after)['market-1']
        assert rows(before)['cfd-1'] == rows(after)['cfd-1']
        assert rows(after)['cfd-1']['settlement_keur'] * (strike - 70) >= 0
