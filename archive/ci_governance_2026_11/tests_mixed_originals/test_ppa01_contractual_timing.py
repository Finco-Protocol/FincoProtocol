"""Calendar PPA candidate: independent Decimal oracle on the real Solar/Wind axis."""
from __future__ import annotations

import copy
from dataclasses import replace
from datetime import date
from decimal import Decimal
import json

import pytest

from app.workbook.revenue_multistream import apply_config
from domain.revenue.multistream_runtime import parse_config
from tests.test_ppa01_index_series_revenue import _project, _operating, _payload, _run


def project(kind, partial=False):
    pi = _project(kind)
    cod = date(2031, 4, 15) if partial else date(2030, 12, 31)
    return replace(pi, info=replace(pi.info, cod_date=cod, financial_close=date(cod.year-1, cod.month, cod.day), construction_months=12))


def terms(rule="SIGNATURE", *, anchor="2028-12-31", method="ANNUAL_FIXED"):
    out = dict(method=method, price_base_date="2028-07-01", start_rule=rule,
               resolved_start_date=anchor, first_review_date=f"{int(anchor[:4])+1}{anchor[4:]}",
               review_frequency="ANNUAL", mid_period_policy="PERIOD_BOUNDARY_ONLY")
    if rule == "SIGNATURE":
        out["signing_date"] = anchor
    if rule == "CUSTOM":
        out["custom_start_date"] = anchor
    return out


def book(pi, kind, timing=None, *, start=0, end=None, rate=.02):
    op = _operating(pi)
    return _payload(kind, op, start=start, end=end, rate=rate,
                    extra={"indexation_timing": timing or terms()})


def dated(timing, end):
    """Independent fixture: explicit December reviews/references, not runtime-derived."""
    t = copy.deepcopy(timing)
    t["method"] = "DATED_INDEX_LEVELS"
    t["index_base_date"] = "2028-12-01"
    t["observations"] = [dict(reference_date="2028-12-01", level=100, basis="OBSERVED",
                              publication_date="2028-12-20", source_ref="synthetic-base")]
    t["reviews"] = []
    for year in range(2029, int(end[:4]) + 1):
        review = f"{year}-12-31"
        if review >= end:
            break
        reference = f"{year}-12-01"
        t["observations"].append(dict(reference_date=reference, level=100 + (year-2028)*3,
                                      basis="FORECAST", publication_date=None, source_ref="synthetic-assumption"))
        t["reviews"].append(dict(effective_date=review, reference_date=reference))
    return t


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("rule,anchor,delay", [
    ("SIGNATURE", "2028-12-31", False), ("COD", "2030-12-31", False),
    ("CUSTOM", "2029-12-31", False), ("PPA_START", "2031-12-31", True),
])
def test_four_anchors_reconcile_every_period_without_double_inflation(kind, rule, anchor, delay):
    pi = project(kind); op = _operating(pi)
    start = next(i for i, p in enumerate(op) if p.start_date == date(2031, 12, 31)) if delay else 0
    raw = book(pi, kind, terms(rule, anchor=anchor), start=start)
    out = _run(pi, raw, kind)
    max_price_residual = max_revenue_residual = 0.0
    for p in op:
        evidence = out[p.index]["multistream_evidence"]
        rows = {r["id"]: r for r in evidence["streams"]}
        ppa, merchant = rows["ppa-1"], rows["market"]
        assert sum(r["quantity_mwh"] for r in rows.values()) == pytest.approx(out[p.index]["generation_mwh"], abs=1e-8)
        if p.start_date < date.fromisoformat(raw["streams"][0]["start_date"]):
            assert ppa["quantity_mwh"] == 0
            continue
        n = sum(date(y, 12, 31) <= p.start_date for y in range(int(anchor[:4])+1, p.start_date.year+1))
        expected = Decimal("60") * Decimal("1.02") ** n
        expected_revenue = float(Decimal(str(ppa["quantity_mwh"])) * expected / 1000)
        max_price_residual = max(max_price_residual, abs(ppa["price_eur_mwh"]-float(expected)))
        max_revenue_residual = max(max_revenue_residual, abs(ppa["revenue_keur"]-expected_revenue))
        assert ppa["price_eur_mwh"] == pytest.approx(float(expected), rel=0, abs=1e-12)
        assert ppa["revenue_keur"] == pytest.approx(expected_revenue, rel=0, abs=1e-8)
        assert merchant["price_eur_mwh"] == 80 and merchant["capture_rate"] == .8
        assert merchant["revenue_keur"] == pytest.approx(merchant["quantity_mwh"] * 80 * .8 / 1000, abs=1e-8)
    print(f"{kind}/{rule}: max_price_residual={max_price_residual:.17g}; max_revenue_residual_keur={max_revenue_residual:.17g}")


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("shape", ["rising", "flat", "falling"])
def test_dated_pre_cod_levels_with_explicit_references_and_partial_first_period(kind, partial, shape):
    pi = project(kind, partial); op = _operating(pi)
    t = dated(terms(), op[-1].end_date.isoformat())
    step = {"rising": 3, "flat": 0, "falling": -2}[shape]
    for i, point in enumerate(t["observations"]):
        point["level"] = 100 + i * step
    raw = book(pi, kind, t, rate=0)
    out = _run(pi, raw, kind)
    for p in op:
        row = next(r for r in out[p.index]["multistream_evidence"]["streams"] if r["id"] == "ppa-1")
        n = sum(date(y, 12, 31) <= p.start_date for y in range(2029, p.start_date.year+1))
        expected = Decimal("60") * (Decimal(100) + Decimal(n) * step) / 100
        assert row["price_eur_mwh"] == pytest.approx(float(expected), rel=0, abs=1e-12)
        assert row["revenue_keur"] == pytest.approx(float(Decimal(str(row["quantity_mwh"])) * expected / 1000), rel=0, abs=1e-8)
    assert raw == json.loads(parse_config(json.dumps(raw)).canonical_json)


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_mid_period_review_is_refused_without_rounding(kind):
    pi = project(kind, partial=True)
    t = terms("COD", anchor="2031-04-15")
    raw = book(pi, kind, t)
    parse_config(json.dumps(raw))  # structurally valid dates are not axis authority
    with pytest.raises(ValueError, match="REVENUE_V2_REVIEW_PERIOD_ALIGNMENT.*2032-04-15"):
        apply_config(pi, json.dumps(raw), project_type=kind)


@pytest.mark.parametrize("mutate,code", [
    (lambda t: t.pop("signing_date"), "TIMING_SCHEMA"),
    (lambda t: t.update(signing_date="2030-01-01"), "TIMING_ORDER"),
    (lambda t: t.update(price_base_date="2030-01-01"), "TIMING_ORDER"),
    (lambda t: t.update(first_review_date="2030-04-15"), "TIMING_ORDER"),
    (lambda t: t.update(mid_period_policy="WEIGHTED"), "REVIEW_POLICY"),
    (lambda t: t.update(review_frequency="MONTHLY"), "REVIEW_POLICY"),
    (lambda t: t.update(resolved_start_date="20290101"), "TIMING_DATE"),
    (lambda t: t.update(start_rule="CONSTRUCTION_START"), "TIMING_RULE"),
])
def test_incomplete_or_invented_contract_terms_fail_closed(mutate, code):
    pi = project("solar"); t = terms(); mutate(t)
    with pytest.raises(ValueError, match=code):
        parse_config(json.dumps(book(pi, "solar", t)))


@pytest.mark.parametrize("mutate,code", [
    (lambda t: t["reviews"].pop(0), "INDEX_COVERAGE"),
    (lambda t: t["reviews"].pop(), "INDEX_COVERAGE"),
    (lambda t: t["observations"].pop(1), "INDEX_COVERAGE"),
    (lambda t: t["observations"].pop(), "INDEX_COVERAGE"),
    (lambda t: t["observations"][0].update(publication_date="2029-02-01"), "INDEX_PUBLICATION"),
    (lambda t: t["observations"][1].update(basis="OBSERVED", publication_date="2030-02-01"), "INDEX_PUBLICATION"),
    (lambda t: t["observations"][1].update(level=0), "INDEX_LEVEL"),
    (lambda t: t["observations"][1].update(level=-1), "INDEX_LEVEL"),
    (lambda t: t["observations"][1].update(level=float("nan")), "INDEX_LEVEL"),
    (lambda t: t["observations"][1].update(level=float("inf")), "INDEX_LEVEL"),
])
def test_missing_pre_cod_future_or_unavailable_levels_fail_closed(mutate, code):
    pi = project("solar"); op = _operating(pi); t = dated(terms(), op[-1].end_date.isoformat()); mutate(t)
    with pytest.raises(ValueError, match=code):
        parse_config(json.dumps(book(pi, "solar", t, rate=0)))


def test_checked_cod_and_mixed_bases_cannot_override_authority():
    pi = project("solar")
    with pytest.raises(ValueError, match="TIMING_COD"):
        apply_config(pi, json.dumps(book(pi, "solar", terms("COD", anchor="2030-01-01"))), project_type="solar")
    raw = book(pi, "solar"); raw["streams"][0]["index_series"] = [{"operating_year": 1, "level": 100, "basis": "FORECAST"}]
    raw["streams"][0]["indexation_rate"] = 0
    with pytest.raises(ValueError, match="TIMING_MIXED_BASIS"):
        parse_config(json.dumps(raw))
    t = dated(terms(), _operating(pi)[-1].end_date.isoformat())
    with pytest.raises(ValueError, match="TIMING_MIXED_BASIS"):
        parse_config(json.dumps(book(pi, "solar", t, rate=.02)))


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_expiration_hands_all_energy_to_residual_merchant(kind):
    pi = project(kind); op = _operating(pi)
    end = next(i for i, p in enumerate(op) if p.start_date == date(2034, 12, 31))
    out = _run(pi, book(pi, kind, end=end), kind)
    rows = {r["id"]: r for r in out[op[end].index]["multistream_evidence"]["streams"]}
    assert rows["ppa-1"]["status"] == "expired" and rows["ppa-1"]["quantity_mwh"] == 0
    assert rows["market"]["quantity_mwh"] == out[op[end].index]["generation_mwh"]


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_actual_non_boundary_signing_reviews_before_cod_need_no_operating_alignment(kind):
    pi = project(kind)
    pi = replace(pi, info=replace(pi.info, cod_date=date(2031,6,30), financial_close=date(2030,6,30)))
    op = _operating(pi)
    raw = book(pi,kind,terms(anchor="2029-04-15"),end=1)
    out = _run(pi,raw,kind)
    row = next(r for r in out[op[0].index]["multistream_evidence"]["streams"] if r["id"]=="ppa-1")
    assert row["price_eur_mwh"] == pytest.approx(float(Decimal(60)*Decimal("1.02")**2), rel=0, abs=1e-12)


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_cod_bridge_uses_project_timeline_not_the_first_operating_boundary(kind):
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import _build_period_engine
    from finco_core.revenue.generation import revenue_decomposition_schedule
    pi = project(kind)
    pi = replace(pi,info=replace(pi.info,cod_date=date(2031,12,29),financial_close=date(2030,12,29)))
    op = _operating(pi)
    assert op[0].start_date == date(2031,12,31) != pi.info.cod_date
    raw = book(pi,kind,terms("COD",anchor="2031-12-29"),end=1)
    out = _run(pi,raw,kind)
    row = next(r for r in out[op[0].index]["multistream_evidence"]["streams"] if r["id"]=="ppa-1")
    assert row["price_eur_mwh"] == 60
    with pytest.raises(ValueError,match="TIMING_COD"):
        parse_config(json.dumps(raw)).validate_axis(op)  # absent Timeline context is not inferred
    changed = replace(pi,info=replace(pi.info,cod_date=date(2031,12,28),financial_close=date(2030,12,28)))
    assert _operating(changed)[0].start_date == op[0].start_date
    with pytest.raises(ValueError,match="TIMING_COD"):
        _run(changed,raw,kind)
    raw["streams"][0]["indexation_timing"] = terms("COD",anchor="2031-12-28")
    assert _run(changed,raw,kind)
    active = apply_config(changed,json.dumps(raw),project_type=kind)
    wrong_engine = _build_period_engine(from_project_inputs(pi))
    with pytest.raises(ValueError,match="TIMELINE_COD"):
        revenue_decomposition_schedule(active,wrong_engine)


def test_future_base_price_cannot_be_back_applied_to_earlier_sales():
    pi = project("solar")
    timing = terms("CUSTOM",anchor="2033-12-31")
    timing["price_base_date"] = "2032-07-01"
    with pytest.raises(ValueError,match="TIMING_ORDER"):
        parse_config(json.dumps(book(pi,"solar",timing)))


@pytest.mark.parametrize("base_price,base_level,review_level,expected", [
    (60,1e308,1e308,60), (1e-308,1e-308,1e308,1e308), (0,1e-308,1e308,0),
])
def test_finite_dated_price_is_not_refused_for_an_intermediate_overflow(base_price,base_level,review_level,expected):
    pi = project("solar"); op = _operating(pi)
    timing = dated(terms(),op[-1].end_date.isoformat())
    timing["observations"][0]["level"] = base_level
    for observation in timing["observations"][1:]:
        observation["level"] = review_level
    raw = book(pi,"solar",timing,rate=0)
    raw["streams"][0]["price_eur_mwh"] = base_price
    cfg = parse_config(json.dumps(raw))
    stream = next(s for s in cfg.plan_at(op[0].start_date,1).streams if s.stream_id=="ppa-1")
    assert stream.ppa.price_at_year(1) == expected


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_inactive_full_financial_results_equal_the_immutable_pre_bridge_authority(kind,monkeypatch):
    from dataclasses import asdict
    from pathlib import Path
    import subprocess
    import types
    from app import project_factories
    from app.services import production_financial_authority as authority
    from finco_core.revenue import generation
    repo = Path(__file__).resolve().parents[1]
    ref = "540e1f4bb54d53ad6d2c1628074b94fdb0c9eb06:finco_core/revenue/generation.py"
    assert subprocess.check_output(["git","rev-parse",ref],cwd=repo,text=True).strip() == "35670dc7b5ab4ce01177f9df817a4776c10569ab"
    source = subprocess.check_output(["git","show",ref],cwd=repo)
    original = types.ModuleType("_ppa01_original_generation")
    exec(compile(source,ref,"exec"),original.__dict__)
    pi = getattr(project_factories,"create_generic_"+kind+"_reference")()
    project_type = {"data_center":"Data Center","ev_charging":"EV Charging"}.get(kind,kind)
    assert not getattr(pi.revenue,"multistream_config_json","")
    # Force two genuine executions; the application memo must not manufacture parity.
    authority._POLICY_RUN_CACHE.clear()
    try:
        candidate = authority.run_clean_production(pi,"Base",project_type=project_type)
        authority._POLICY_RUN_CACHE.clear()
        with monkeypatch.context() as reference:
            reference.setattr(generation,"revenue_decomposition_schedule",original.revenue_decomposition_schedule)
            baseline = authority.run_clean_production(pi,"Base",project_type=project_type)
        assert asdict(candidate.g2c_result) == asdict(baseline.g2c_result)
        assert asdict(candidate.financial_statements_result) == asdict(baseline.financial_statements_result)
    finally:
        authority._POLICY_RUN_CACHE.clear()
