"""PPA-01: Indexed PPA with an explicit CPI/PPI series, end to end through the real routes.

Save (CSRF + composite CAS) -> canonical persistence -> reload -> child scenario override (Base untouched) -> canonical Run -> committed
per-period evidence reconciled with an independent Decimal calculation -> Run History -> STALE on change -> new CURRENT Run. Invalid input fails
closed with nothing persisted and the previous committed Run intact. Solar and Wind.
"""
from __future__ import annotations

import copy
import json
import re
from decimal import Decimal

import pytest

from tests.test_developer_economics_persistence_v1 import OWNER, Flow, env  # noqa: F401
from tests.test_rc2_integration_acceptance import REV_SAVE, _pi, _save_revenue
from tests.test_wf07_revenue_workspace import contract_tokens

SNAPSHOT_KEY = "rev_multistream_config_json"


def _book(flow, levels, *, basis="FORECAST", price=60.0):
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import _build_period_engine
    pi = _pi(flow)
    op = [p for p in _build_period_engine(from_project_inputs(pi)).periods() if p.is_operation]
    common = dict(settlement="SAME_PERIOD", source_ref="synthetic-independent-contract",
                  start_date=op[0].start_date.isoformat(), end_date=op[-1].end_date.isoformat())
    return {"version": 2, "technology": flow.kind, "indexation_basis": "OPERATING_YEAR", "streams": [
        dict(common, id="ppa-1", type="ppa", volume_share=0.6, price_eur_mwh=price, indexation_rate=0,
             index_series=[{"operating_year": i + 1, "level": lvl, "basis": basis} for i, lvl in enumerate(levels)]),
        dict(common, id="market", type="merchant", volume_share=None, price_eur_mwh=80.0, indexation_rate=0, capture_rate=0.8)]}


def _years(flow):
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import _build_period_engine
    return {p.index: p.year_index for p in _build_period_engine(from_project_inputs(_pi(flow))).periods() if p.is_operation}


def _levels(flow, start, step):
    return [start + step * i for i in range(max(_years(flow).values()))]


def _reconcile(summary, years, payload):
    """Every committed period: price = base x level[year] / level[1]; revenue = quantity x price / 1000 (Decimal); totals add up."""
    series = {p["operating_year"]: Decimal(str(p["level"])) for p in payload["streams"][0]["index_series"]}
    base_year = payload["streams"][0]["index_series"][0]["operating_year"]
    base_price = Decimal(str(payload["streams"][0]["price_eur_mwh"]))
    audit = summary["revenue_multistream_audit"]
    assert audit
    total = Decimal(0)
    for row in audit:
        ppa = next(s for s in row["streams"] if s["id"] == "ppa-1")
        price = base_price * series[years[row["period_index"]]] / series[base_year]
        assert ppa["price_eur_mwh"] == pytest.approx(float(price), abs=1e-12), row["period_index"]
        assert ppa["revenue_keur"] == pytest.approx(float(Decimal(str(ppa["quantity_mwh"])) * price / 1000), abs=1e-8)
        total += Decimal(str(row["net_revenue_keur"]))
    assert float(total) == pytest.approx(summary["total_revenue_keur"], rel=1e-12)


def _ws_book(flow, key=SNAPSHOT_KEY):
    return json.loads(flow.ws().draft_snapshot[key])


def _page(flow):
    return flow.env.client.get("/v2/workbook", params=flow.project).text


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_save_reload_scenario_run_history_stale_current_chain(env, kind):
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.scenarios_repository import get_scenario, list_scenarios
    flow = Flow(env, kind)
    years = _years(flow)
    base_levels = _levels(flow, 100.0, 2.5)
    base_book = _book(flow, base_levels)
    # 1-4 Save commits exactly the typed configuration; reload restores the series
    saved = _save_revenue(flow, base_book)
    assert saved.status_code == 200, saved.text[:400]
    assert _ws_book(flow) == base_book
    page = _page(flow)
    assert "&#34;index_series&#34;" in page or '"index_series"' in page
    assert re.search(r"operating_year", page) and "data-operating-years" in page
    # 7 canonical Run uses the exact series; revenue by period reconciles with an independent calculation
    base_run = flow.run()
    _reconcile(base_run, years, base_book)
    history = get_run_history(OWNER, flow.record.project_id)
    assert len(history) == 1
    frozen = copy.deepcopy(history[0].runtime_summary)
    _reconcile(frozen, years, base_book)                                     # 9 Run History retains the committed economic evidence
    assert "CURRENT" in _page(flow)
    # 6 child scenario override never mutates Base
    assert env.client.post("/v2/workbook/scenarios/create", data={**flow.project, "scenario_name": "Alt"}).status_code == 200
    scenario = next(s for s in list_scenarios(OWNER, flow.record.project_id) if not s.is_base_case)
    assert env.client.post("/v2/workbook/scenarios/select", data={**flow.project, "scenario_id": scenario.scenario_id}).status_code == 200
    alt_book = _book(flow, _levels(flow, 100.0, -0.4), basis="OBSERVED")
    assert _save_revenue(flow, alt_book).status_code == 200
    assert json.loads(get_scenario(scenario.scenario_id, OWNER).overrides[SNAPSHOT_KEY]) == alt_book
    assert _ws_book(flow) == base_book                                       # Base draft untouched
    child_run = flow.run()
    _reconcile(child_run, years, alt_book)
    assert child_run["total_revenue_keur"] < base_run["total_revenue_keur"]   # a deflating series prices below the rising base
    after = get_run_history(OWNER, flow.record.project_id)
    assert len(after) == 2 and next(h for h in after if h.history_id == history[0].history_id).runtime_summary == frozen
    # 10 a changed value makes the committed result STALE and never rewrites history
    changed = copy.deepcopy(alt_book)
    changed["streams"][0]["index_series"][3]["level"] = 99.0
    assert _save_revenue(flow, changed).status_code == 200
    assert "STALE" in _page(flow)
    assert [h.history_id for h in get_run_history(OWNER, flow.record.project_id)] == [h.history_id for h in after]
    # 11 re-running commits a new CURRENT Run reconciled to the new level
    again = flow.run()
    _reconcile(again, years, changed)
    assert again["total_revenue_keur"] != child_run["total_revenue_keur"]
    assert "CURRENT" in _page(flow) and len(get_run_history(OWNER, flow.record.project_id)) == 3


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("break_it, code", [
    (lambda b: b["streams"][0]["index_series"].pop(), "REVENUE_V2_INDEX_COVERAGE"),                   # a priced year without a level
    (lambda b: b["streams"][0]["index_series"].pop(5), "REVENUE_V2_INDEX_GAP"),                       # a missing intermediate year
    (lambda b: b["streams"][0]["index_series"][2].update(level=0.0), "REVENUE_V2_INDEX_LEVEL"),
    (lambda b: b["streams"][0]["index_series"][2].update(level=-3.0), "REVENUE_V2_INDEX_LEVEL"),
    (lambda b: b["streams"][0]["index_series"].insert(3, dict(b["streams"][0]["index_series"][2])), "REVENUE_V2_INDEX_ORDER"),
    (lambda b: b["streams"][0].update(indexation_rate=0.02), "REVENUE_V2_INDEX_MIXED_BASIS"),
], ids=["no-final-year", "gap", "zero", "negative", "duplicate", "rate-and-series"])
def test_invalid_series_is_refused_with_nothing_persisted_and_the_last_run_intact(env, kind, break_it, code):
    from app.persistence.run_history_repository import get_run_history
    flow = Flow(env, kind)
    good = _book(flow, _levels(flow, 100.0, 2.0))
    assert _save_revenue(flow, good).status_code == 200
    flow.run()
    history = [h.history_id for h in get_run_history(OWNER, flow.record.project_id)]
    before = copy.deepcopy(flow.ws().draft_snapshot)
    bad = copy.deepcopy(good)
    break_it(bad)
    r = _save_revenue(flow, bad)
    assert r.status_code == 422 and code in r.text, (r.status_code, r.text[:300])
    assert flow.ws().draft_snapshot == before and not flow.ws().dirty                  # nothing persisted, Last Run still CURRENT
    assert "CURRENT" in _page(flow)
    assert [h.history_id for h in get_run_history(OWNER, flow.record.project_id)] == history


def test_a_stale_save_does_not_overwrite_committed_inputs_and_non_finite_json_is_refused(env):
    flow = Flow(env, "solar")
    good = _book(flow, _levels(flow, 100.0, 2.0))
    assert _save_revenue(flow, good).status_code == 200
    before = copy.deepcopy(flow.ws().draft_snapshot)
    other = _book(flow, _levels(flow, 100.0, 5.0))
    page = _page(flow)
    stale = {**flow.project, **contract_tokens(page), "contracts": json.dumps(other), "content_hash": "0" * 64}
    assert env.client.post(REV_SAVE, headers={"HX-Request": "true"}, data=stale).status_code == 409
    assert flow.ws().draft_snapshot == before
    raw = json.dumps(good).replace('"level": 102.0', '"level": NaN')
    r = env.client.post(REV_SAVE, headers={"HX-Request": "true"}, data={**flow.project, **contract_tokens(page), "contracts": raw})
    assert r.status_code == 422 and "REVENUE_V2_INDEX_LEVEL" in r.text and flow.ws().draft_snapshot == before


def test_legacy_indexed_and_scheduled_contracts_still_save_and_run_unchanged(env):
    from tests.test_wf07_revenue_multistream import contracts
    flow = Flow(env, "solar")
    legacy = contracts(_pi(flow), "solar", price=95, merchant_price=90, strike=100)
    legacy["streams"][0]["indexation_rate"] = 0.02
    assert _save_revenue(flow, legacy).status_code == 200
    assert _ws_book(flow) == legacy and "index_series" not in flow.ws().draft_snapshot[SNAPSHOT_KEY]
    run = flow.run()
    assert run["revenue_multistream_audit"]
