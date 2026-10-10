"""Statements & Debt output workspace: read-only presentation of the persisted Last Run."""
from __future__ import annotations

import html as htmllib
import re
from types import SimpleNamespace

import pytest

from app.workbook import multisenior_config as config
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401  (fixture)
from tests.test_model_financing_f2 import run, save
from tests.test_model_financing_f3_workspace import collection_for_inputs, state

OWNER = "decision-user"


def get_outputs(env, record):
    response = env.client.get("/v2/workbook/outputs", params={"project": record.project_code})
    assert response.status_code == 200, response.text[:500]
    return response.text


def activate_f3(env, record):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.input_set import ProjectInputSet
    ws = get_workspace_state(OWNER, record.project_id)
    pi = ProjectInputSet.from_snapshot(ws.draft_snapshot).to_projectinputs()
    response = save(env, record, state(active=True, collection=collection_for_inputs(pi)), field=config.FIELD_ID)
    assert "field-error-banner" not in response.text, response.text[:1500]


def tables(page: str) -> dict[str, dict]:
    """{table_id|caption: {row_label: [raw floats or None]}} parsed from the rendered HTML only."""
    out: dict[str, dict] = {}
    for match in re.finditer(r'<table class="out-table" data-out-table="([^"]*)">(.*?)</table>', page, re.S):
        key = match.group(1)
        body = match.group(2)
        suffix = 0
        while key in out:
            suffix += 1
            key = f"{match.group(1)}#{suffix}"
        rows: dict[str, list] = {"__dates__": re.findall(r'<th scope="col" class="out-num"[^>]*title="([^"]*)"', body)}
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
            label = re.search(r'<th scope="row" class="out-label">(.*?)(?:<small>|</th>)', tr, re.S)
            if not label:
                continue
            cells = re.findall(r'<td [^>]*data-raw="([^"]*)"', tr)
            rows[htmllib.unescape(re.sub(r"<[^>]+>", "", label.group(1))).strip()] = [float(c) if c != "" else None for c in cells]
        out[key] = rows
    return out


def persisted_rows(rr, section, key):
    from app.workbook.runtime_projection import thaw_runtime_payload
    fs = thaw_runtime_payload(rr.financial_statements)
    return [p.get(key) for p in fs[section]["periods"]]


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_f3_two_senior_output_reconciles_to_run_evidence(env, monkeypatch, kind):
    monkeypatch.setattr(config, "ACTIVATION_ENABLED", True)
    record = env.create(kind)
    activate_f3(env, record)
    ws, rr = run(env, record)
    page = get_outputs(env, record)
    assert 'data-testid="outputs-state" data-state="CURRENT"' in page
    evidence = rr.runtime_summary["financing_evidence"]
    schedules = evidence["facility_schedules"]
    assert len(schedules) == 2 and page.count('data-testid="out-facility"') == 2
    parsed = tables(page)
    # Statements: every rendered cell equals the persisted value (None stays unavailable, never zero).
    for table_id, section, key, label in (
        ("pnl", "pnl", "revenues_keur", "Revenues"), ("pnl", "pnl", "net_income_keur", "Net Income"),
        ("balance_sheet", "balance_sheet", "senior_balance_keur", "Senior Balance"),
        ("balance_sheet", "balance_sheet", "total_assets_keur", "Total Assets"),
        ("cash_flow", "pf_cash_waterfall", "fcf_banks_keur", "FCF to Banks"),
        ("cash_flow", "pf_cash_waterfall", "senior_total_ds_keur", "Senior Total DS"),
    ):
        expected = persisted_rows(rr, section, key)
        got = parsed[table_id][label]
        assert len(got) == len(expected)
        for g, e in zip(got, expected):
            assert (g is None) == (e is None)
            if e is not None:
                assert g == pytest.approx(e, abs=1e-9)
    # Facilities are separate and reconcile to the persisted facility evidence.
    for position, schedule in enumerate(schedules, start=1):
        op = parsed["debt-%d" % position]
        for label, key in (("Interest", "interest_keur"), ("Principal", "principal_keur"),
                           ("Opening balance", "opening_keur"), ("Closing balance", "closing_keur"),
                           ("Debt service", "debt_service_keur")):
            assert op[label] == pytest.approx(schedule[key], abs=1e-9)
        assert schedule["instrument_id"] in page
    assert page.count('data-testid="out-maturity"') == 2
    # Terminal status follows the PERSISTED closing balance at each facility's maturity (never its rounding).
    expected = []
    for sched in schedules:
        closing = sched["closing_keur"][sched["period_indices"].index(sched["maturity_period_index"])]
        expected.append("REPAID" if closing == 0 else "OUTSTANDING" if closing >= 0.005 else "OUTSTANDING_BELOW_DISPLAY")
    assert re.findall(r'data-testid="out-repayment-status" data-status="(\w+)"', page) == expected
    # Σ facility service equals the PF waterfall Senior service (persisted-vs-persisted cross-check).
    assert 'data-testid="outputs-reconciliation" data-state="RECONCILED"' in page
    # CFADS section is the PF waterfall's fcf_banks_keur.
    assert parsed["cfads"]["CFADS to Senior"] == pytest.approx(persisted_rows(rr, "pf_cash_waterfall", "fcf_banks_keur"), abs=1e-9)
    assert "Run Integrity PASS" in page


@pytest.mark.parametrize("kind", ["data_center", "ev_charging", "solar"])
def test_legacy_single_senior_output_is_truthful_about_unexposed_terms(env, kind):
    record = env.create(kind)
    ws, rr = run(env, record)
    page = get_outputs(env, record)
    assert 'data-testid="outputs-state" data-state="CURRENT"' in page
    assert page.count('data-testid="out-facility"') == 1 and "Senior debt (aggregate)" in page
    assert "Fees and construction draws are not persisted" in page
    assert "(not exposed)" in page            # opening balance is not persisted for the aggregate schedule
    from app.workbook.runtime_projection import thaw_runtime_payload
    periods = thaw_runtime_payload(rr.debt_schedule)["periods"]
    senior = tables(page)["debt-1"]
    assert senior["Closing balance"] == pytest.approx([p["senior_balance_keur"] for p in periods], abs=1e-9)
    assert all(v is None for v in senior["Opening balance"])


# ───────────────────────── freshness, integrity, authority ─────────────────────────

def test_not_run_shows_no_tables_and_no_fabricated_zero(env):
    record = env.create("solar")
    page = get_outputs(env, record)
    assert 'data-testid="outputs-state" data-state="NOT_RUN"' in page
    assert "<table" not in page and 'data-raw="0' not in page
    assert "No Run has been committed" in page


def test_stale_view_identifies_the_previous_run_and_keeps_its_values(env):
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create("solar")
    ws, rr = run(env, record)
    before = tables(get_outputs(env, record))
    prior_snapshot = ws.last_runtime_snapshot_id
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    changed = env.client.post("/v2/workbook/update", headers={"HX-Request": "true"}, data=dict(
        project=record.project_code, field_id="debt.senior.target_dscr", value="1.35", sheet_id="debt", **tokens(page.text)))
    assert changed.status_code == 200 and "field-error" not in changed.text, changed.text[:800]
    assert get_workspace_state(OWNER, record.project_id).dirty
    stale = get_outputs(env, record)
    assert 'data-testid="outputs-state" data-state="STALE"' in stale
    assert "STALE — showing the PRIOR Last Run" in stale and prior_snapshot[:22] in stale
    assert tables(stale) == before            # exactly the prior Run's values, nothing recomputed


def test_current_run_can_coexist_with_integrity_fail(env, monkeypatch):
    import app.api.v1_1.institutional as institutional
    record = env.create("solar")
    run(env, record)
    real = institutional.get_run_integrity_checks

    def failing(*args, **kwargs):
        state, report = real(*args, **kwargs)
        report = dict(report)
        report["overall"] = "FAIL"
        report["checks"] = [dict(report["checks"][0], status="FAIL", title="Synthetic integrity break")] + list(report["checks"][1:])
        return state, report

    monkeypatch.setattr(institutional, "get_run_integrity_checks", failing)
    page = get_outputs(env, record)
    assert 'data-testid="outputs-state" data-state="CURRENT"' in page
    assert 'data-testid="outputs-integrity" data-state="FAIL"' in page
    assert 'data-testid="outputs-integrity-fail"' in page and "Synthetic integrity break" in page
    assert "<table" in page                       # evidence still shown unchanged


def test_unavailable_values_are_not_rendered_as_zero(env):
    record = env.create("solar")
    ws, rr = run(env, record)
    page = get_outputs(env, record)
    parsed = tables(page)
    persisted = persisted_rows(rr, "balance_sheet", "total_assets_keur")
    assert any(v is None for v in persisted), "reference run is expected to leave some BS totals unavailable"
    rendered = parsed["balance_sheet"]["Total Assets"]
    assert [v is None for v in rendered] == [v is None for v in persisted]
    assert 'class="out-num out-na"' in page and "not available</span>" in page
    # A row that is unavailable in every period is disclosed in words, not only as dashes.
    assert 'data-testid="out-unavailable-balance_sheet"' in page and "Total Assets" in page.split('data-testid="out-unavailable-balance_sheet"')[1][:400]


def test_get_is_read_only_runs_no_engine_and_is_owner_scoped(env, monkeypatch):
    from app.persistence.workspace_repository import get_workspace_state
    from financial_engine import orchestrator
    record = env.create("solar")
    run(env, record)
    before = get_workspace_state(OWNER, record.project_id)

    def forbidden(*args, **kwargs):
        pytest.fail("Opening the output workspace executed a model")
    monkeypatch.setattr(orchestrator, "run_operating_model", forbidden)
    monkeypatch.setattr(orchestrator, "run_senior_debt_model", forbidden)
    for _ in range(2):
        get_outputs(env, record)
    after = get_workspace_state(OWNER, record.project_id)
    assert after == before
    foreign = env.client.get("/v2/workbook/outputs", params={"project": "does-not-exist"})
    assert foreign.status_code == 404
    env.client.cookies.clear()
    assert env.client.get("/v2/workbook/outputs", params={"project": record.project_code}).status_code == 401


def test_navigation_and_lazy_panel_are_additive(env):
    record = env.create("solar")
    page = env.client.get("/v2/workbook", params={"project": record.project_code}).text
    assert 'id="tab-outputs"' in page and 'id="panel-outputs"' in page and "Statements &amp; Debt" in page
    assert 'hx-get="/v2/workbook/outputs?project=' in page
    # The lazy panel carries no statement data until the tab is opened.
    panel = page[page.index('id="panel-outputs"'):page.index('id="panel-trust"')]
    assert "<table" not in panel


# ───────────────────────── accessibility (static contract) ─────────────────────────

def test_tables_are_keyboard_and_screen_reader_accessible(env):
    record = env.create("solar")
    run(env, record)
    page = get_outputs(env, record)
    n_tables = page.count('<table class="out-table"')
    assert n_tables >= 7
    assert page.count("<caption") == n_tables
    assert page.count('role="region"') == n_tables and page.count('tabindex="0"') >= n_tables
    assert page.count('aria-labelledby="out-cap-') >= n_tables
    assert 'scope="col"' in page and 'scope="row"' in page
    assert all(' scope="row"' in row for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S)[1:3])
    assert 'aria-label="Decimal precision"' in page and "<legend" in page
    assert page.count('<h3') >= 6 and 'aria-label="Output sections"' in page
    # Year 0 column headers are announced, not just styled.
    assert "Year 0 / opening" in page
    # Unavailable cells are announced.
    assert "not available</span>" in page


# ───────────────────────── Returns / distributions ─────────────────────────

def test_returns_and_distributions_equal_persisted_sponsor_and_distribution_evidence(env):
    from app.workbook.runtime_projection import thaw_runtime_payload
    record = env.create("solar")
    ws, rr = run(env, record)
    page = get_outputs(env, record)
    parsed = tables(page)
    dist = thaw_runtime_payload(rr.distribution_schedule)["periods"]
    assert parsed["distributions"]["Distribution"] == pytest.approx([p["distribution_keur"] for p in dist], abs=1e-9)
    sponsor = thaw_runtime_payload(rr.sponsor_schedule)["periods"]
    assert parsed["sponsor"]["Legal equity distribution"] == pytest.approx(
        [p["legal_equity_distribution_keur"] for p in sponsor], abs=1e-9)
    summary = rr.runtime_summary
    assert f"{summary['project_irr'] * 100:,.2f}%" in page
    # The Sponsor net cash flow is not persisted by the canonical sponsor schedule: stays "NOT AVAILABLE".
    assert "Sponsor Net Cash Flow" in page and "NOT AVAILABLE" in page


# ───────────────────────── XLSX parity ─────────────────────────

XLSX_MAP = {
    "P&L": {"Revenue": ("pnl", "revenues_keur"), "OPEX": ("pnl", "operating_expenses_keur"),
            "Depreciation": ("pnl", "depreciation_keur"), "EBIT": ("pnl", "ebit_keur"),
            "Senior Interest": ("pnl", "senior_interest_expense_keur")},
    "Cash Flow": {"Revenue Cash": ("pf_cash_waterfall", "revenue_cash_keur"), "OPEX Cash": ("pf_cash_waterfall", "opex_cash_keur"),
                  "EBITDA Cash": ("pf_cash_waterfall", "ebitda_cash_keur"), "Cash Tax": ("pf_cash_waterfall", "cash_tax_keur"),
                  "FCF Banks": ("pf_cash_waterfall", "fcf_banks_keur"),
                  "Senior Debt Service": ("pf_cash_waterfall", "senior_total_ds_keur")},
    "Balance Sheet": {"Net Fixed Assets": ("balance_sheet", "net_fixed_assets_keur"),
                      "Senior Debt Balance": ("balance_sheet", "senior_balance_keur")},
}
SECTION_TABLE = {"P&L": "pnl", "Cash Flow": "cash_flow", "Balance Sheet": "balance_sheet"}
UI_LABEL = {"pnl": {"revenues_keur": "Revenues", "operating_expenses_keur": "Operating Expenses",
                    "depreciation_keur": "Depreciation", "ebit_keur": "EBIT",
                    "senior_interest_expense_keur": "Senior Interest"},
            "pf_cash_waterfall": {"revenue_cash_keur": "Revenue Cash", "opex_cash_keur": "OPEX Cash",
                                  "ebitda_cash_keur": "EBITDA Cash", "cash_tax_keur": "Cash Tax",
                                  "fcf_banks_keur": "FCF to Banks", "senior_total_ds_keur": "Senior Total DS"},
            "balance_sheet": {"net_fixed_assets_keur": "Net Fixed Assets", "senior_balance_keur": "Senior Balance"}}


@pytest.mark.parametrize("kind,f3", [("solar", True), ("wind", True), ("data_center", False), ("ev_charging", False)])
def test_xlsx_export_parity_with_the_output_workspace(env, monkeypatch, kind, f3):
    import io
    import openpyxl
    monkeypatch.setattr(config, "ACTIVATION_ENABLED", True)
    record = env.create(kind)
    if f3:
        activate_f3(env, record)
    ws, rr = run(env, record)
    page = get_outputs(env, record)
    parsed = tables(page)
    exported = env.client.post("/v2/workbook/export", params={"project": record.project_code}, data={"project": record.project_code})
    assert exported.status_code == 200
    book = openpyxl.load_workbook(io.BytesIO(exported.content), data_only=True)
    compared = 0
    for sheet, rows in XLSX_MAP.items():
        sh = book[sheet]
        header = next(r for r in sh.iter_rows(values_only=True) if r and r[0] == "Metric")
        dates = [str(d) for d in header[1:]]
        by_label = {r[0]: r[1:] for r in sh.iter_rows(values_only=True) if r and isinstance(r[0], str)}
        ui = parsed[SECTION_TABLE[sheet]]
        ui_dates = ui["__dates__"]
        for xlsx_label, (section, key) in rows.items():
            ui_row = ui[UI_LABEL[section][key]]
            ui_by_date = {}
            for d, v in zip(ui_dates, ui_row):
                ui_by_date.setdefault(d, []).append(v)
            for d, xv in zip(dates, by_label[xlsx_label]):
                values = ui_by_date.get(d)
                if values is None or xv is None:
                    continue
                if all(v is not None for v in values):
                    assert any(v == pytest.approx(float(xv), abs=0.0051) for v in values), (sheet, xlsx_label, d, values, xv)
                    compared += 1
    assert compared >= 100, compared


def test_f3_facility_service_equals_the_xlsx_senior_debt_service_row(env, monkeypatch):
    import io
    import openpyxl
    monkeypatch.setattr(config, "ACTIVATION_ENABLED", True)
    record = env.create("solar")
    activate_f3(env, record)
    ws, rr = run(env, record)
    page = get_outputs(env, record)
    parsed = tables(page)
    exported = env.client.post("/v2/workbook/export", params={"project": record.project_code}, data={"project": record.project_code})
    book = openpyxl.load_workbook(io.BytesIO(exported.content), data_only=True)
    row = next(r for r in book["Senior Debt"].iter_rows(values_only=True) if r and r[0] == "Senior Debt Service")
    xlsx_nonzero = [float(v) for v in row[1:] if isinstance(v, (int, float)) and v]
    service_a, service_b = parsed["debt-1"]["Debt service"], parsed["debt-2"]["Debt service"]
    # Facilities schedule different tenors: pair by the persisted period index through the evidence.
    schedules = rr.runtime_summary["financing_evidence"]["facility_schedules"]
    total = {}
    for sched in schedules:
        for index, service in zip(sched["period_indices"], sched["debt_service_keur"]):
            total[index] = total.get(index, 0.0) + service
    assert len(service_a) == len(schedules[0]["period_indices"]) and len(service_b) == len(schedules[1]["period_indices"])
    assert sorted(round(v, 2) for v in total.values()) == pytest.approx(sorted(round(v, 2) for v in xlsx_nonzero), abs=0.0101)


# ───────────────────────── projection contract (no workspace needed) ─────────────────────────

def test_projection_fails_closed_and_never_substitutes_zero():
    from app.v2.output_workspace_projection import build_output_workspace, build_output_workspace_safe
    freshness = SimpleNamespace(state=SimpleNamespace(value="CURRENT"))
    assert build_output_workspace(runtime_result=None, workspace=None, freshness=freshness, last_run_scenario=None)["state"] == "NOT_RUN"
    rr = SimpleNamespace(
        financial_statements={"pnl": {"periods": [{"period": 0, "date": "2030-01-01", "revenues_keur": None},
                                                    {"period": 1, "date": "2030-07-01", "revenues_keur": 5.0}]}},
        runtime_summary={}, debt_schedule={}, distribution_schedule={}, sponsor_schedule={},
        ran_at="2030-01-01T00:00:00", snapshot_id="S")
    ws = SimpleNamespace(last_runtime_identity={}, last_runtime_composite_hash="h", dirty=False)
    out = build_output_workspace(runtime_result=rr, workspace=ws, freshness=freshness, last_run_scenario="Base Case")
    pnl = out["statements"][0]
    revenue = next(r for r in pnl["rows"] if r["key"] == "revenues_keur")
    assert [c["v"] for c in revenue["cells"]] == [None, 5.0]
    assert revenue["cells"][0]["text"] == "—"
    # Absent statements are "not available", not empty-zero tables.
    assert out["statements"][1]["available"] is False and out["statements"][2]["available"] is False
    assert out["reconciliation"]["overall"] == "UNVERIFIED"
    broken = build_output_workspace_safe(runtime_result=object(), workspace=ws, freshness=freshness, last_run_scenario=None)
    assert broken["state"] == "UNAVAILABLE" and not broken["statements"]


def test_stale_state_requires_the_prior_run_identity_in_the_banner():
    from app.v2.output_workspace_projection import build_output_workspace
    freshness = SimpleNamespace(state=SimpleNamespace(value="STALE"))
    rr = SimpleNamespace(financial_statements={}, runtime_summary={}, debt_schedule={}, distribution_schedule={},
                         sponsor_schedule={}, ran_at="2031-05-06T07:08:09", snapshot_id="20310506T070809.000000+0000")
    ws = SimpleNamespace(last_runtime_identity={"scenario_name": "Upside"}, last_runtime_composite_hash="h", dirty=True)
    out = build_output_workspace(runtime_result=rr, workspace=ws, freshness=freshness, last_run_scenario="Upside")
    assert out["state"] == "STALE"
    assert "PRIOR Last Run" in out["banner"] and "2031-05-06 07:08:09" in out["banner"] and "Upside" in out["banner"]
    assert "20310506T070809.000000" in out["banner"]


def test_refresh_is_a_plain_listener_not_a_csp_blocked_trigger_filter():
    """An hx-trigger filter expression is evaluated with eval, which the page CSP forbids; a failed filter fires on
    every request and ping-pongs with other sheets. The output workspace must not use one."""
    from pathlib import Path
    template = Path("app/templates/v2/partials/sheet_outputs.html").read_text(encoding="utf-8")
    script = Path("static/js/model_outputs_workspace.js").read_text(encoding="utf-8")
    assert "htmx:afterRequest[" not in template and 'hx-trigger="click from:#tab-outputs"' in template
    assert "addEventListener('htmx:afterRequest'" in script and "'post'" in script


# ───────────────────── committed Run scenario identity (P1) ─────────────────────

def _q3_scenario(env, record) -> str:
    html = env.client.get("/v2/workbook", params={"project": record.project_code}).text
    context = re.search(r'data-testid="q3-context">(.*?)</div>', html, re.S)
    assert context, "Q3 Findings context missing"
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", context.group(1))).strip()
    return re.search(r"Scenario: (.*?) · Run ", text).group(1)


def _outputs_scenario(page: str):
    match = re.search(r'data-out-scenario="([^"]*)"', page)
    return htmllib.unescape(match.group(1)) if match else None


def _create_scenario(env, record, name):
    response = env.client.post("/v2/workbook/scenarios/create", data={"project": record.project_code, "scenario_name": name},
                               headers={"HX-Request": "true"})
    assert response.status_code == 200
    from app.persistence.scenarios_repository import list_scenarios
    return next(sc for sc in list_scenarios(user_id=OWNER, project_id=record.project_id) if sc.scenario_name == name)


def test_base_case_identity_is_proven_and_equals_q3_findings(env):
    record = env.create("solar")
    assert _outputs_scenario(get_outputs(env, record)) is None            # NOT_RUN: no committed identity at all
    run(env, record)
    page = get_outputs(env, record)
    assert _outputs_scenario(page) == "Base Case (Decision solar)" == _q3_scenario(env, record)
    assert "UNAVAILABLE" not in re.search(r'data-testid="outputs-identity">(.*?)</span>', page).group(1)


def test_named_scenario_stale_and_switch_keep_the_committed_identity(env):
    from app.persistence.scenarios_repository import get_base_case_scenario
    record = env.create("solar")
    run(env, record)
    base_snapshot = re.search(r'data-out-snapshot="([^"]+)"', get_outputs(env, record)).group(1)
    upside = _create_scenario(env, record, "Upside")
    not_run = get_outputs(env, record)                                      # selecting cleared the Last Run
    assert 'data-state="NOT_RUN"' in not_run and _outputs_scenario(not_run) is None and "Upside" not in not_run
    run(env, record)
    current = get_outputs(env, record)
    assert _outputs_scenario(current) == "Upside" == _q3_scenario(env, record)
    # STALE: the PRIOR Run's identity, not the edited Working Copy.
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    env.client.post("/v2/workbook/update", headers={"HX-Request": "true"}, data=dict(
        project=record.project_code, field_id="debt.senior.target_dscr", value="1.33", sheet_id="debt", **tokens(page.text)))
    stale = get_outputs(env, record)
    assert 'data-state="STALE"' in stale and _outputs_scenario(stale) == "Upside" == _q3_scenario(env, record)
    assert "Upside" in re.search(r'data-testid="outputs-stale-banner">(.*?)</p>', stale, re.S).group(1)
    # Switching back restores the Base Case's OWN committed Run; the previously selected name is never substituted.
    env.client.post("/v2/workbook/scenarios/select", headers={"HX-Request": "true"},
                    data={"project": record.project_code, "scenario_id": get_base_case_scenario(OWNER, record.project_id).scenario_id})
    back = get_outputs(env, record)
    assert _outputs_scenario(back).startswith("Base Case") and "Upside" not in back
    assert re.search(r'data-out-snapshot="([^"]+)"', back).group(1) == base_snapshot == re.search(
        r'data-out-snapshot="([^"]+)"', get_outputs(env, record)).group(1)
    assert _outputs_scenario(back) == _q3_scenario(env, record)
    assert upside.scenario_id


def test_archived_scenario_still_resolves_the_committed_name(env):
    from app.persistence.db import get_cursor
    record = env.create("solar")
    upside = _create_scenario(env, record, "Archived later")
    run(env, record)
    from app.persistence.scenarios_repository import get_base_case_scenario
    base_id = get_base_case_scenario(OWNER, record.project_id).scenario_id
    with get_cursor() as cur:
        # Plant the legacy shape: the committed Last Run belongs to the (now archived) scenario while another is selected.
        cur.execute("UPDATE workspace_states SET active_scenario_id=? WHERE project_id=?", (base_id, record.project_id))
        cur.execute("UPDATE scenarios SET archived=1 WHERE scenario_id=?", (upside.scenario_id,))
    page = get_outputs(env, record)
    assert 'data-out-state="UNAVAILABLE"' not in page, page[-600:]
    assert _outputs_scenario(page) == "Archived later"


def test_unresolvable_or_foreign_scenario_id_is_unavailable_never_base_case(env):
    from app.persistence.db import get_cursor
    from app.services.reference_seed_service import create_reference_seeded_project
    record = env.create("solar")
    run(env, record)
    # (a) dangling id (foreign keys relaxed only to plant the impossible state)
    with get_cursor() as cur:
        cur.execute("PRAGMA foreign_keys=OFF")
        cur.execute("UPDATE workspace_states SET last_runtime_scenario_id='0123456789abcdef' WHERE project_id=?", (record.project_id,))
    page = get_outputs(env, record)
    assert _outputs_scenario(page) == "UNAVAILABLE" and "Base Case" not in re.search(r'data-testid="outputs-identity">(.*?)</span>', page).group(1)
    # (b) a scenario that belongs to ANOTHER project of the same owner is not this project's scenario
    other = create_reference_seeded_project(user_id=OWNER, template_source="generic_solar_reference", requested_name="Other project", capacity_mw=16)
    foreign = _create_scenario(env, other, "Other project scenario")
    with get_cursor() as cur:
        cur.execute("UPDATE workspace_states SET last_runtime_scenario_id=? WHERE project_id=?", (foreign.scenario_id, record.project_id))
    page = get_outputs(env, record)
    assert _outputs_scenario(page) == "UNAVAILABLE" and "Other project scenario" not in page


def test_identity_label_is_not_read_from_the_run_identity_blob():
    from app.v2.output_workspace_projection import build_output_workspace
    freshness = SimpleNamespace(state=SimpleNamespace(value="CURRENT"))
    rr = SimpleNamespace(financial_statements={}, runtime_summary={}, debt_schedule={}, distribution_schedule={},
                         sponsor_schedule={}, ran_at="2031-05-06T07:08:09", snapshot_id="S")
    ws = SimpleNamespace(last_runtime_identity={"scenario_name": "Blob name"}, last_runtime_composite_hash="h")
    for label, expected in (("Proven name", "Proven name"), (None, "UNAVAILABLE"), ("  ", "UNAVAILABLE")):
        out = build_output_workspace(runtime_result=rr, workspace=ws, freshness=freshness, last_run_scenario=label)
        assert out["identity"]["scenario"] == expected and out["identity"]["scenario_proven"] is (expected != "UNAVAILABLE")


# ───────────────────── terminal Senior debt truth (P1) ─────────────────────

@pytest.mark.parametrize("closing,status", [
    (0.0, "REPAID"), (3e-9, "OUTSTANDING_BELOW_DISPLAY"), (0.004999, "OUTSTANDING_BELOW_DISPLAY"),
    (0.005, "OUTSTANDING"), (12.5, "OUTSTANDING"), (-1e-13, "NEGATIVE_BALANCE"), (None, "UNAVAILABLE")])
def test_repayment_status_follows_the_persisted_balance_not_its_rounding(closing, status):
    from app.v2.output_workspace_projection import _repayment
    result = _repayment(closing, "test basis")
    assert result["status"] == status
    assert result["balance"]["v"] == closing                       # the persisted value is never altered
    if status == "OUTSTANDING_BELOW_DISPLAY":
        assert result["balance"]["text"] == "0.00" and result["exact_text"] == f"{closing:.6g}" and "REPAID" not in result["label"]
    assert (status == "REPAID") == ("FULLY REPAID" in result["label"])


def _debt(summary, debt_schedule=None, sponsor=None):
    from app.v2.output_workspace_projection import _debt_section
    return _debt_section(summary, debt_schedule, None, None, sponsor)


def _facility(closing, *, maturity=5, indices=(3, 4, 5)):
    n = len(indices)
    return {"instrument_id": "f", "commitment_keur": 100.0, "maturity_period_index": maturity, "period_indices": list(indices),
            "opening_keur": [0.0] * n, "interest_keur": [0.0] * n, "principal_keur": [0.0] * n, "debt_service_keur": [0.0] * n,
            "closing_keur": closing, "construction_draws_keur": [], "construction_idc_keur": [],
            "upfront_fees_keur": [], "construction_commitment_fees_keur": []}


def test_f3_facilities_report_independent_terminal_status():
    summary = {"financing_evidence": {"facility_schedules": [_facility([5.0, 2.0, 0.0]), _facility([5.0, 2.0, 4e-13]),
                                                             _facility([5.0, 2.0, 9.75]), _facility([5.0, 2.0, None])],
                                      "construction_funding": {"periods": []}}}
    statuses = [f["repayment"]["status"] for f in _debt(summary)["facilities"]]
    assert statuses == ["REPAID", "OUTSTANDING_BELOW_DISPLAY", "OUTSTANDING", "UNAVAILABLE"]
    # A maturity period that is not in the schedule cannot establish repayment.
    no_maturity = _debt({"financing_evidence": {"facility_schedules": [_facility([0.0, 0.0, 0.0], maturity=9)],
                                                "construction_funding": {"periods": []}}})
    assert no_maturity["facilities"][0]["repayment"]["status"] == "UNAVAILABLE"


def test_legacy_aggregate_uses_canonical_maturity_and_terminal_state():
    periods = [{"period": i, "date": f"2040-0{i}-01", "senior_balance_keur": v} for i, v in
               ((20, 40.0), (21, 23.0), (22, 0.0), (23, None))]
    outstanding = {"summary": {"terminal_financial_state": {"senior": {
        "status": "OUTSTANDING_AT_MATURITY", "contractual_maturity_period_index": 21,
        "contractual_maturity_date": "2040-02-01", "balance_at_contractual_maturity_keur": 23.0}}}}
    result = _debt({}, {"periods": periods}, outstanding)
    facility = result["facilities"][0]
    # Maturity is period 21 (balance 23.0); the later zero period must not be mistaken for settlement.
    assert facility["repayment"]["status"] == "OUTSTANDING" and facility["repayment"]["balance"]["v"] == 23.0
    assert result["canonical_terminal"]["status"] == "OUTSTANDING_AT_MATURITY" and facility["maturity_index"] == 21
    # Without canonical evidence the last persisted closing balance is used and labelled as such.
    plain = _debt({}, {"periods": periods})["facilities"][0]["repayment"]
    assert plain["status"] == "REPAID" and "last persisted period" in plain["basis"]
    missing = _debt({}, {"periods": [{"period": 1, "date": "2040-01-01", "senior_balance_keur": None}]})["facilities"][0]
    assert missing["repayment"]["status"] == "UNAVAILABLE"


def test_template_never_claims_repaid_for_a_nonzero_balance(env):
    from app.v2.output_workspace_projection import build_output_workspace
    freshness = SimpleNamespace(state=SimpleNamespace(value="CURRENT"))
    summary = {"financing_evidence": {"facility_schedules": [_facility([5.0, 2.0, 4e-13])], "construction_funding": {"periods": []}}}
    rr = SimpleNamespace(financial_statements={}, runtime_summary=summary, debt_schedule={}, distribution_schedule={},
                         sponsor_schedule={}, ran_at="2031-05-06T07:08:09", snapshot_id="S")
    out = build_output_workspace(runtime_result=rr, workspace=SimpleNamespace(last_runtime_identity={}, last_runtime_composite_hash="h"),
                                 freshness=freshness, last_run_scenario="Base Case")
    from app.v2.router import _templates
    page = _templates.get_template("partials/sheet_outputs.html").render(outputs=out, project_code="p")
    assert "OUTSTANDING BELOW DISPLAY PRECISION" in page and "FULLY REPAID" not in page
    assert 'data-testid="out-exact-balance"' in page and "4e-13" in page and 'data-status="OUTSTANDING_BELOW_DISPLAY"' in page


# ───────────────────── four-vertical statement integrity ─────────────────────

FOUR = [("solar", True), ("wind", True), ("data_center", False), ("ev_charging", False)]


@pytest.mark.parametrize("kind,f3", FOUR)
def test_four_vertical_statement_integrity_against_the_persisted_run(env, monkeypatch, kind, f3):
    from financial_engine import orchestrator
    from app.workbook.runtime_projection import FS_BS_ROW_DEFS, FS_PF_CF_ROW_DEFS, FS_PNL_ROW_DEFS
    monkeypatch.setattr(config, "ACTIVATION_ENABLED", True)
    record = env.create(kind)
    if f3:
        activate_f3(env, record)
    ws, rr = run(env, record)

    def forbidden(*a, **k):
        pytest.fail("the output workspace recomputed financials")
    monkeypatch.setattr(orchestrator, "run_operating_model", forbidden)
    monkeypatch.setattr(orchestrator, "run_senior_debt_model", forbidden)
    page = get_outputs(env, record)
    parsed = tables(page)
    # P&L, Balance Sheet and PF cash waterfall: EVERY persisted line, EVERY period; missing stays unavailable.
    for table_id, section, defs in (("pnl", "pnl", FS_PNL_ROW_DEFS), ("balance_sheet", "balance_sheet", FS_BS_ROW_DEFS),
                                    ("cash_flow", "pf_cash_waterfall", FS_PF_CF_ROW_DEFS)):
        for key, label, _total, _stock in defs:
            expected = persisted_rows(rr, section, key)
            got = parsed[table_id][label]
            assert [v is None for v in got] == [e is None or isinstance(e, bool) for e in expected], (table_id, label)
            assert got == pytest.approx([e for e in expected if e is not None and not isinstance(e, bool)] and
                                        [e if e is not None else None for e in expected], abs=1e-9) or all(
                g is None or abs(g - e) <= 1e-9 for g, e in zip(got, expected) if e is not None)
    # Labelling: the cash waterfall is not a CFS; BS totals / Sponsor Net Cash Flow are never synthesised.
    assert "Cash Flow (PF waterfall)" in page and "not an indirect-method cash flow statement" in page
    assert all(v is None for v in parsed["balance_sheet"]["Total Assets"]) == all(
        e is None for e in persisted_rows(rr, "balance_sheet", "total_assets_keur"))
    assert "Sponsor Net Cash Flow" in page and "NOT AVAILABLE" in page
    # CFADS retains its definition: the PF waterfall's cash available to Senior debt service.
    assert "fcf_banks_keur" in page and parsed["cfads"]["CFADS to Senior"] == pytest.approx(
        persisted_rows(rr, "pf_cash_waterfall", "fcf_banks_keur"), abs=1e-9)
    assert parsed["cfads"]["Senior debt service"] == pytest.approx(persisted_rows(rr, "pf_cash_waterfall", "senior_total_ds_keur"), abs=1e-9)
    # Debt: F3 A/B separate and reconciling; legacy aggregate otherwise.
    schedules = (rr.runtime_summary.get("financing_evidence") or {}).get("facility_schedules") or []
    if f3:
        assert page.count('data-testid="out-facility"') == 2 == len(schedules)
        ids = re.findall(r'data-facility-id="([^"]+)"', page)
        assert len(set(ids)) == 2 and set(ids) == {s["instrument_id"] for s in schedules}
        assert 'data-testid="outputs-reconciliation" data-state="RECONCILED"' in page
    else:
        assert page.count('data-testid="out-facility"') == 1 and "Senior debt (aggregate)" in page
    # Returns and sponsor distributions come from persisted evidence.
    summary = rr.runtime_summary
    assert f"{summary['project_irr'] * 100:,.2f}%" in page
    # Freshness and Integrity are independent badges.
    assert 'data-testid="outputs-state" data-state="CURRENT"' in page and 'data-testid="outputs-integrity"' in page


@pytest.mark.parametrize("kind,f3", FOUR)
def test_stale_and_integrity_fail_are_independent_in_every_vertical(env, monkeypatch, kind, f3):
    import app.api.v1_1.institutional as institutional
    monkeypatch.setattr(config, "ACTIVATION_ENABLED", True)
    record = env.create(kind)
    if f3:
        activate_f3(env, record)
    run(env, record)
    real = institutional.get_run_integrity_checks

    def verdict(overall, status):
        def wrapped(*a, **k):
            state, report = real(*a, **k)
            report = dict(report, overall=overall)
            report["checks"] = [dict(report["checks"][0], status=status, title="Synthetic")] + list(report["checks"][1:])
            return state, report
        return wrapped
    for overall, status in (("FAIL", "FAIL"), ("PASS", "PASS")):
        monkeypatch.setattr(institutional, "get_run_integrity_checks", verdict(overall, status))
        page = get_outputs(env, record)
        assert 'data-testid="outputs-state" data-state="CURRENT"' in page and f'data-testid="outputs-integrity" data-state="{overall}"' in page
    edit = env.client.get("/v2/workbook", params={"project": record.project_code})
    if f3:
        from dataclasses import replace
        from finco_core.inputs.financing_instruments import FinancingCollection
        from app.persistence.workspace_repository import get_workspace_state
        from app.workbook.input_set import ProjectInputSet
        pi = ProjectInputSet.from_snapshot(get_workspace_state(OWNER, record.project_id).draft_snapshot).to_projectinputs()
        base = collection_for_inputs(pi)
        first = replace(base.instruments[0], interest=replace(base.instruments[0].interest, fixed_rate=base.instruments[0].interest.fixed_rate + 0.005))
        data = dict(field_id=config.FIELD_ID, value=state(active=True, collection=FinancingCollection((first,) + tuple(base.instruments[1:]))))
    else:
        data = dict(field_id="debt.senior.target_dscr", value="1.37")
    response = env.client.post("/v2/workbook/update", headers={"HX-Request": "true"}, data=dict(
        project=record.project_code, sheet_id="debt", **data, **tokens(edit.text)))
    assert response.status_code == 200 and "field-error" not in response.text
    for overall, status in (("FAIL", "FAIL"), ("PASS", "PASS")):
        monkeypatch.setattr(institutional, "get_run_integrity_checks", verdict(overall, status))
        page = get_outputs(env, record)
        assert 'data-testid="outputs-state" data-state="STALE"' in page and f'data-testid="outputs-integrity" data-state="{overall}"' in page
