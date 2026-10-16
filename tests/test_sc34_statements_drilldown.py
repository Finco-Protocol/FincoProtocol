"""SC-09: Statements V2 drill-down over the immutable Run evidence (Last Run and one historical Run)."""
from __future__ import annotations

import json
import re

import pytest

from app.v2 import statement_drilldown as D
from app.v2.workspace_destinations import DESTINATIONS
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401  (fixture)
from tests.test_model_financing_f2 import run

OWNER = "decision-user"
TAB_IDS = {d.tab_id for d in DESTINATIONS}
HASHES = {"#" + d.tab_id.replace("tab-", "", 1) for d in DESTINATIONS}


def outputs(env, record):
    r = env.client.get("/v2/workbook/outputs", params={"project": record.project_code})
    assert r.status_code == 200
    return r.text


def drilldown(rr, ws, state="CURRENT"):
    from types import SimpleNamespace
    from app.v2.output_workspace_projection import build_output_workspace
    freshness = SimpleNamespace(state=SimpleNamespace(value=state))
    return build_output_workspace(runtime_result=rr, workspace=ws, freshness=freshness, last_run_scenario="Base")


# ───────────────────────────── structure and values ─────────────────────────────
def test_every_destination_is_a_real_manifest_tab_and_provenance_is_a_manifest_tab():
    assert D.PROVENANCE_TAB in TAB_IDS
    for table in (D._INPUT_DESTINATION, D._EXPLANATION_DESTINATION):
        assert set(table.values()) <= TAB_IDS


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_tree_never_drops_changes_or_derives_a_persisted_value(env, kind):
    record = env.create(kind)
    ws, rr = run(env, record)
    out = drilldown(rr, ws)
    statements = {t["id"]: t for t in out["statements"]}
    assert {s["id"] for s in out["drilldown"]["statements"]} == {"pnl", "balance_sheet", "cash_flow"}
    for st in out["drilldown"]["statements"]:
        table = statements[st["id"]]
        for basis, source in (("model", table), ("annual", table["annual"])):
            view = st["views"][basis]
            flat = {r["key"]: r for r in source["rows"]}
            valued = [n for n in view["nodes"] if n["kind"] == "line"]
            assert {n["key"] for n in valued} == set(flat), "no persisted line may be dropped or invented"
            for n in valued:
                assert n["cells"] == flat[n["key"]]["cells"], "a node shows exactly the persisted cells"
                assert [c["v"] for c in n["cells"]] == [c["v"] for c in flat[n["key"]]["cells"]]
            for n in view["nodes"]:
                if n["kind"] == "group":
                    assert n["cells"] is None and n["value_source"] == "GROUP_HEADER_NO_VALUE"
                if n["parent"] is not None:
                    assert n["depth"] >= 1 and any(p["key"] == n["parent"] for p in view["nodes"])


def test_unavailable_cells_stay_unavailable_never_zero(env):
    record = env.create("solar")
    ws, rr = run(env, record)
    out = drilldown(rr, ws)
    for st in out["drilldown"]["statements"]:
        for view in st["views"].values():
            for n in view["nodes"]:
                for c in n["cells"] or ():
                    assert c["v"] is None or isinstance(c["v"], float)
                    if c["v"] is None:
                        assert c["text"] == "—"


def test_pnl_ebit_hierarchy_and_destinations(env):
    record = env.create("solar")
    ws, rr = run(env, record)
    nodes = {n["key"]: n for n in next(s for s in drilldown(rr, ws)["drilldown"]["statements"] if s["id"] == "pnl")["views"]["model"]["nodes"]}
    assert nodes["ebit_keur"]["children"] == ["revenues_keur", "operating_expenses_keur", "depreciation_keur"]
    assert nodes["operating_expenses_keur"]["destination"]["tab_id"] == "tab-opex" and nodes["operating_expenses_keur"]["destination"]["kind"] == "input"
    assert nodes["revenues_keur"]["destination"]["tab_id"] == "tab-revenue"
    assert nodes["depreciation_keur"]["destination"]["tab_id"] == "tab-capex"
    assert nodes["senior_interest_expense_keur"]["destination"]["tab_id"] == "tab-debt"
    assert nodes["cit_accrual_keur"]["destination"]["tab_id"] == "tab-tax"
    # derived totals have no one-to-one input: read-only provenance, honestly labelled
    for derived in ("ebit_keur", "earnings_before_tax_keur", "net_income_keur"):
        assert nodes[derived]["destination"]["kind"] == "provenance" and nodes[derived]["destination"]["tab_id"] == D.PROVENANCE_TAB
    assert "No one-to-one editable input" in nodes["net_income_keur"]["destination"]["title"]


def test_cash_flow_destinations_cover_debt_tax_and_distributions(env):
    record = env.create("solar")
    ws, rr = run(env, record)
    nodes = {n["key"]: n for n in next(s for s in drilldown(rr, ws)["drilldown"]["statements"] if s["id"] == "cash_flow")["views"]["model"]["nodes"]}
    assert nodes["senior_total_ds_keur"]["destination"]["tab_id"] == "tab-debt"
    assert nodes["cash_tax_keur"]["destination"]["tab_id"] == "tab-tax"
    assert nodes["net_dividends_keur"]["destination"] == {**nodes["net_dividends_keur"]["destination"], "tab_id": "tab-returns", "kind": "explanation"}
    assert nodes["opex_cash_keur"]["destination"]["tab_id"] == "tab-opex"


def test_revenue_streams_are_persisted_detail_in_the_model_view_only(env):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.input_set import ProjectInputSet
    from tests.test_wf07_revenue_multistream import contracts
    from tests.test_wf07_revenue_workspace import contract_tokens
    record = env.create("solar")
    pi = ProjectInputSet.from_snapshot(get_workspace_state(OWNER, record.project_id).draft_snapshot).to_projectinputs()
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    r = env.client.post("/v2/workbook/revenue/contracts", headers={"HX-Request": "true"}, data={
        "project": record.project_code, **contract_tokens(page.text), "contracts": json.dumps(contracts(pi, "solar", price=95, merchant_price=90))})
    assert r.status_code == 200
    ws, rr = run(env, record)
    pnl = next(s for s in drilldown(rr, ws)["drilldown"]["statements"] if s["id"] == "pnl")
    streams = [n for n in pnl["views"]["model"]["nodes"] if n["kind"] == "stream"]
    assert {n["key"] for n in streams} == {"stream:ppa-1", "stream:market-1"}
    assert all(n["parent"] == "revenues_keur" and n["value_source"] == "PERSISTED_STREAM_DETAIL" for n in streams)
    assert not [n for n in pnl["views"]["annual"]["nodes"] if n["kind"] == "stream"]       # no re-aggregation in the annual view
    audit = {e["period_index"]: e for e in rr.runtime_summary["revenue_multistream_audit"]}
    columns = pnl["views"]["model"]["columns"]
    for n in streams:
        sid = n["key"].split(":", 1)[1]
        for col, cell in zip(columns, n["cells"]):
            entry = audit.get(col["index"])
            expected = next((s["revenue_keur"] for s in (entry or {}).get("streams", ()) if s["id"] == sid), None)
            assert cell["v"] == expected          # persisted value or None; never a sum, never zero


# ───────────────────────────── rendered markup, ARIA and input context ─────────────────────────────
def test_markup_has_independent_toggle_and_link_with_consistent_aria(env):
    record = env.create("solar")
    run(env, record)
    page = outputs(env, record)
    assert page.count('role="treegrid"') == 6                          # three statements x model/annual
    ids = set(re.findall(r'<tr role="row" id="([^"]+)"', page))
    toggles = re.findall(r'<button type="button" class="st-toggle"[^>]*>', page)
    assert toggles
    for t in toggles:
        assert 'aria-expanded="' in t and 'aria-label="' in t
        controls = re.search(r'aria-controls="([^"]*)"', t).group(1).split()
        assert controls and set(controls) <= ids                        # every controlled row exists
    links = re.findall(r'<a class="st-link[^"]*" href="([^"]*)"', page)
    assert links and set(links) <= HASHES                               # destinations come from the navigation manifest
    assert all('aria-level="' in r for r in re.findall(r'<tr role="row" id="st-[^>]*>', page))
    # the expand control is a <button>, the navigation control is an <a>: two separate interactive elements
    first_row = re.search(r'<th scope="row" role="rowheader".*?</th>', page, re.S).group(0)
    assert "<button" in first_row and "<a " in first_row


def test_last_run_links_say_when_they_open_a_working_copy_that_differs(env):
    record = env.create("solar")
    run(env, record)
    current = outputs(env, record)
    assert 'data-st-context="RUN_MATCHES_WORKING_COPY"' in current and "(current Working Copy)" in current
    page = env.client.get("/v2/workbook", params={"project": record.project_code}).text
    env.client.post("/v2/workbook/update", headers={"HX-Request": "true"}, data=dict(
        project=record.project_code, sheet_id="project_setup", field_id="project_setup.technical.p50_hours", value="1700", **tokens(page)))
    stale = outputs(env, record)
    assert 'data-st-context="WORKING_COPY_DIFFERS"' in stale
    assert "The Working Copy has changed since this Run" in stale and "may differ from this Run" in stale


def test_alternative_scenario_selection_never_presents_the_base_run_as_its_own(env):
    from app.persistence.scenarios_repository import list_scenarios
    record = env.create("solar")
    run(env, record)
    env.client.post("/v2/workbook/scenarios/create", headers={"HX-Request": "true"}, data={"project": record.project_code, "scenario_name": "Alt"})
    scenarios = list_scenarios(OWNER, record.project_id)
    alt = next(s for s in scenarios if not s.is_base_case)
    base = next(s for s in scenarios if s.is_base_case)
    env.client.post("/v2/workbook/scenarios/select", headers={"HX-Request": "true"}, data={"project": record.project_code, "scenario_id": alt.scenario_id})
    page = outputs(env, record)
    # The Base Run is not the child scenario's Run: no statements, no drill-down, no links into the child's inputs.
    assert 'data-out-state="NOT_RUN"' in page and 'role="treegrid"' not in page and "st-link" not in page
    env.client.post("/v2/workbook/scenarios/select", headers={"HX-Request": "true"}, data={"project": record.project_code, "scenario_id": base.scenario_id})
    back = outputs(env, record)
    assert 'data-st-context="RUN_MATCHES_WORKING_COPY"' in back


def test_drilldown_get_is_read_only_and_adds_no_engine_call(env, monkeypatch):
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.workspace_repository import get_workspace_state
    from app.services import production_financial_authority as P
    record = env.create("solar")
    run(env, record)
    before = (json.dumps(get_workspace_state(OWNER, record.project_id).last_runtime_summary, sort_keys=True, default=str),
              [h.history_id for h in get_run_history(OWNER, record.project_id)])
    monkeypatch.setattr(P, "run_clean_production", lambda *a, **k: pytest.fail("engine executed on GET"))
    outputs(env, record)
    after = (json.dumps(get_workspace_state(OWNER, record.project_id).last_runtime_summary, sort_keys=True, default=str),
             [h.history_id for h in get_run_history(OWNER, record.project_id)])
    assert before == after


def test_flat_statement_tables_are_unchanged_and_tree_values_match_them_cell_for_cell(env):
    record = env.create("solar")
    run(env, record)
    page = outputs(env, record)
    flat = {}
    for table_id, body in re.findall(r'<table class="out-table" data-out-table="([^"]*)">(.*?)</table>', page, re.S):
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
            label = re.search(r'<th scope="row" class="out-label">(.*?)(?:<small>|</th>)', tr, re.S)
            if label:
                flat[(table_id, re.sub(r"<[^>]+>", "", label.group(1)).strip())] = re.findall(r'data-raw="([^"]*)"', tr)
    checked = 0
    for statement, basis, body in re.findall(r'data-st-tree="([^"]*)" data-st-basis="([^"]*)"[^>]*>(.*?)</table>', page, re.S):
        table_id = statement + ("-annual" if basis == "annual" else "")
        for tr in re.findall(r"<tr role=\"row\" id=.*?</tr>", body, re.S):
            m = re.search(r'class="st-link[^"]*"[^>]*>([^<]*)</a>', tr)
            if not m or 'data-st-source="PERSISTED_LINE"' not in tr:
                continue
            raw = re.findall(r'data-raw="([^"]*)"', tr)
            assert flat[(table_id, m.group(1).strip())] == raw
            checked += 1
    assert checked > 20


# ───────────────────────────── historical Run (isolated router) ─────────────────────────────
@pytest.fixture
def hist_env(env):
    from app.v2.statements_drilldown_router import router
    env.client.app.include_router(router, prefix="/v2")
    return env


def history(record):
    from app.persistence.run_history_repository import get_run_history
    return sorted(get_run_history(OWNER, record.project_id), key=lambda h: h.created_at)


def hist_page(env, record, history_id):
    return env.client.get("/v2/workbook/run-history/statements", params={"project": record.project_code, "history_id": history_id})


def test_historical_statements_use_the_entry_not_the_current_working_copy(hist_env):
    from app.persistence.workspace_repository import get_workspace_state
    env = hist_env
    record = env.create("solar")
    run(env, record)
    tariff = float(get_workspace_state(OWNER, record.project_id).draft_snapshot.get("rev_ppa_base_tariff")
                   or get_workspace_state(OWNER, record.project_id).draft_snapshot["tariff_eur_mwh"])
    page = env.client.get("/v2/workbook", params={"project": record.project_code}).text
    r = env.client.post("/v2/workbook/update", headers={"HX-Request": "true"}, data=dict(
        project=record.project_code, sheet_id="revenue", field_id="revenue.ppa.base_tariff", value=str(tariff * 1.5), **tokens(page)))
    assert '"workbook-field-error"' not in r.headers.get("HX-Trigger", "")
    run(env, record)
    first, second = history(record)[:2]
    assert first.history_id != second.history_id
    expected = [p["revenues_keur"] for p in first.financial_statements["pnl"]["periods"]]
    other = [p["revenues_keur"] for p in second.financial_statements["pnl"]["periods"]]
    assert expected != other                                   # the two Runs genuinely differ
    html = hist_page(env, record, first.history_id).text
    assert 'data-testid="historical-badge"' in html and 'data-state="HISTORICAL_RUN"' in html
    assert "Historical Run. Links open the CURRENT Working Copy, which is not the inputs this Run used." in html
    model = re.search(r'data-st-tree="pnl" data-st-basis="model".*?</table>', html, re.S).group(0)
    revenues = re.search(r'data-st-key="revenues_keur".*?</tr>', model, re.S).group(0)
    shown = [float(v) if v != "" else None for v in re.findall(r'data-raw="([^"]*)"', revenues)]
    assert shown == pytest.approx(expected, abs=1e-9)          # the first entry's persisted values ...
    assert shown != pytest.approx(other, abs=1e-9)             # ... not the second Run's or the edited Working Copy's
    assert re.search(r'data-snapshot|data-out-snapshot="%s"' % re.escape(first.runtime_snapshot_id), html)


def test_historical_input_links_say_they_open_the_current_working_copy(hist_env, monkeypatch):
    from app.workbook import runtime_authority as RA
    env = hist_env
    record = env.create("solar")
    run(env, record)
    entry = history(record)[0]
    monkeypatch.setattr(RA, "current_engine_version", lambda: entry.engine_version + "_next")
    html = hist_page(env, record, entry.history_id).text
    assert re.search(r'data-testid="outputs-dim-engine" data-state="ENGINE_SUPERSEDED"', html)
    assert re.search(r'data-testid="outputs-dim-inputs" data-state="CURRENT"', html)      # same inputs as the Working Copy
    anchors = re.findall(r'<a class="st-link st-link--input"[^>]*>', html)
    assert anchors
    assert all("this historical Run&#39;s own inputs are not shown here" in a for a in anchors)
    assert "Working Copy</small>" in html


def test_historical_view_is_owner_scoped_and_fails_closed(hist_env):
    env = hist_env
    record = env.create("solar")
    run(env, record)
    other = env.create("wind")
    run(env, other)
    entry = history(record)[0]
    assert hist_page(env, other, entry.history_id).status_code == 404              # foreign project's id
    assert hist_page(env, record, "does-not-exist").status_code == 404
    assert env.client.get("/v2/workbook/run-history/statements", params={"project": record.project_code}).status_code == 400
    assert env.client.get("/v2/workbook/run-history/statements", params={"project": "no-such-project", "history_id": entry.history_id}).status_code == 404


def test_historical_view_is_immutable_and_never_runs_the_engine(hist_env, monkeypatch):
    from app.services import production_financial_authority as P
    env = hist_env
    record = env.create("solar")
    run(env, record)
    entry = history(record)[0]
    before = entry.to_dict()
    monkeypatch.setattr(P, "run_clean_production", lambda *a, **k: pytest.fail("engine executed on GET"))
    for _ in range(2):
        assert hist_page(env, record, entry.history_id).status_code == 200
    assert history(record)[0].to_dict() == before


def test_run_detail_links_to_statements_only_when_the_hook_is_wired(env):
    record = env.create("solar")
    run(env, record)
    entry = history(record)[0]
    r = env.client.get("/v2/workbook/run-history/detail", params={"project": record.project_code, "history_id": entry.history_id})
    assert r.status_code == 200 and "run-detail-open-statements" not in r.text      # inert until the integration hook sets the flag
