"""Workflow C — Statements, Analytics & Trace presentation (projections + real pages).

Everything asserted here is presentation of already-persisted authority: raw persisted
values, typed freshness, typed integrity — no recomputation, no engine execution.
"""
from __future__ import annotations

import re

import pytest

from tests.test_cost_workspace_consistency_v1 import (  # noqa: F401
    HX, TECHNOLOGIES, _cost_workspace_executor_cleanup, _line_fields, _page, _post, _project,
    _row, _run, _seeded_line, seeded_db,
)

SRC = {
    "state": "AVAILABLE",
    "runtime_summary": {
        "project_irr": 0.1177, "equity_irr": 0.4211, "min_dscr": 1.2705, "senior_debt_keur": 16828.66,
        "actual_gearing_pct": 0.75, "project_npv_keur": None,
    },
    "sponsor_summary": {"total_sponsor_xirr": 0.1685, "total_sponsor_moic": 3.5},
    "run_scenario_name": "Base",
}


def _strip(state="CURRENT", source=SRC, **kw):
    from app.v2.kpi_strip_projection import build_kpi_strip
    return build_kpi_strip(source, runtime_state=state, **kw)


def _item(strip, key):
    return next(i for i in strip.items if i.key == key)


# ───────────────────────────── KPI strip projection ─────────────────────────────

def test_strip_values_are_raw_persisted_values_formatted_by_the_canonical_projection():
    s = _strip()
    assert _item(s, "project_irr").raw_value == 0.1177 and _item(s, "project_irr").display == "11.77%"
    assert _item(s, "equity_irr").display == "42.11%"
    assert _item(s, "min_dscr").display == "1.27x"
    assert _item(s, "senior_debt_keur").display == "16,829 kEUR"
    assert _item(s, "actual_gearing_pct").display == "75.00%"          # fraction, not a percentage point
    # sponsor metrics come from their OWN persisted summary fields
    assert _item(s, "sponsor_irr").raw_value == 0.1685
    assert _item(s, "sponsor_moic").raw_value == 3.5


def test_unavailable_is_a_dash_with_a_reason_never_zero():
    s = _strip()
    npv, cfads = _item(s, "project_npv_keur"), _item(s, "total_cfads_keur")
    for it in (npv, cfads):
        assert it.display == "—" and it.raw_value is None and it.available is False
        assert "authority gap" in it.note and "derived" in it.note
        assert "authority gap" in it.title


def test_a_genuine_persisted_zero_stays_zero():
    src = {**SRC, "runtime_summary": {**SRC["runtime_summary"], "min_dscr": 0.0, "actual_gearing_pct": 0.0}}
    s = _strip(source=src)
    assert _item(s, "min_dscr").display == "0.00x" and _item(s, "min_dscr").available is True
    assert _item(s, "actual_gearing_pct").display == "0.00%" and _item(s, "actual_gearing_pct").raw_value == 0.0


def test_strings_and_nan_are_never_accepted_as_values():
    src = {**SRC, "runtime_summary": {**SRC["runtime_summary"], "project_irr": "11.77%", "min_dscr": float("nan")}}
    s = _strip(source=src)
    assert _item(s, "project_irr").display == "—" and _item(s, "min_dscr").display == "—"


def test_stale_marks_values_as_the_prior_run_and_keeps_them_visible():
    s = _strip("STALE")
    assert s.state == "STALE" and "Prior Last Run" in s.caption
    assert _item(s, "project_irr").display == "11.77%"                  # still shown ...
    assert _item(s, "project_irr").freshness == "stale"                 # ... but marked
    assert "Prior Last Run" in _item(s, "project_irr").title


def test_not_run_shows_nothing_and_unavailable_source_degrades_to_not_run():
    for s in (_strip("NOT_RUN"), _strip("CURRENT", source={"state": "UNAVAILABLE"}), _strip("CURRENT", source=None)):
        assert s.state == "NOT_RUN" and not s.has_values
        assert all(i.display == "—" and i.raw_value is None for i in s.items)


def test_integrity_verdict_is_independent_of_freshness():
    fail = {"state": "AVAILABLE", "overall": "FAIL", "counts": {"PASS": 5, "FAIL": 1},
            "checks": [{"status": "FAIL", "reason_code": "CFADS_IDENTITY_MISMATCH"}]}
    current_fail = _strip("CURRENT", integrity=fail)
    assert current_fail.state == "CURRENT" and current_fail.integrity_value == "FAIL"   # CURRENT != PASS
    assert "CFADS_IDENTITY_MISMATCH" in current_fail.integrity_detail
    stale_pass = _strip("STALE", integrity={"state": "AVAILABLE", "overall": "PASS", "counts": {}, "checks": []})
    assert stale_pass.state == "STALE" and stale_pass.integrity_value == "PASS"          # STALE != failure
    assert _strip("NOT_RUN", integrity=fail).integrity_value == ""                       # no run, no verdict


def test_strip_module_has_no_engine_or_run_imports():
    import pathlib
    src = pathlib.Path("app/v2/kpi_strip_projection.py").read_text()
    for forbidden in ("financial_engine", "finco_core", "run_project", "project_runner", "run_model"):
        assert forbidden not in src


# ───────────────────────────── Smart Panel worklist / trace ─────────────────────────────

def _panel(**kw):
    from app.v2.smart_panel_projection import build_smart_panel_projection
    base = dict(trust_pack=None, runtime_state="CURRENT", has_runtime=True, project_key="generic_solar_reference",
                assumption_register_view={"available": True, "entry_count": 3})
    base.update(kw)
    return build_smart_panel_projection(**base)


def test_worklist_groups_keep_distinct_meanings_in_a_fixed_order():
    from app.v2.smart_panel_projection import WORKLIST_GROUPS
    p = _panel(runtime_state="STALE", trust_pack={
        "last_run": {"state": "UNAVAILABLE"},
        "integrity": {"state": "AVAILABLE", "overall": "FAIL", "counts": {"FAIL": 1},
                      "checks": [{"status": "FAIL", "reason_code": "X_CODE"}]}})
    order = [g for g, _ in WORKLIST_GROUPS]
    groups = [i.group for i in p.validation_summary]
    assert groups == sorted(groups, key=order.index)                     # grouped, fixed order
    by_key = {i.key.value: i for i in p.validation_summary}
    assert by_key["INVALID"].group == "input" and by_key["NON_EDITABLE"].group == "protected"
    assert by_key["STALE_LAST_RUN"].group == "freshness" and by_key["AUTHORITY_UNAVAILABLE"].group == "evidence"
    assert by_key["INTEGRITY_CHECK"].group == "integrity" and by_key["INTEGRITY_CHECK"].value == "FAIL"
    assert "X_CODE" in by_key["INTEGRITY_CHECK"].detail                  # typed code preserved
    assert "not an input error" in by_key["STALE_LAST_RUN"].detail       # stale is not an integrity failure


def test_integrity_pass_is_not_invented_and_current_does_not_imply_pass():
    p = _panel(runtime_state="CURRENT", trust_pack={
        "integrity": {"state": "AVAILABLE", "overall": "PASS", "counts": {}, "checks": []}})
    assert "INTEGRITY_CHECK" not in {i.key.value for i in p.validation_summary}      # only problems are listed
    p2 = _panel(runtime_state="CURRENT", trust_pack={"integrity": {"state": "UNAVAILABLE"}})
    assert "INTEGRITY_CHECK" not in {i.key.value for i in p2.validation_summary}     # unavailable != pass != fail


def test_trace_stays_typed_unavailable_while_available_evidence_is_listed_separately():
    p = _panel(trust_pack={"last_run": {"state": "AVAILABLE", "snapshot_id": "20260101T000000",
                                        "composite_hash_short": "abc123def456…",
                                        "run_at_display": "2026-01-01 00:00:00", "engine_version": "9.9"}})
    trace = p.sections[-1]
    assert trace.key == "trace" and trace.available is False and trace.link is None
    assert "not persisted after a run" in trace.empty_text
    titles = [b.title for b in trace.breakdowns]
    assert titles == ["Available evidence (not a full trace)",
                      "Authority gaps (not persisted, never derived)"]
    evidence = {r.label: r for r in trace.breakdowns[0].rows}
    assert evidence["Last Run identity"].value == "AVAILABLE"
    assert "abc123def456" in evidence["Last Run identity"].detail and "engine 9.9" in evidence["Last Run identity"].detail
    gaps = {r.label for r in trace.breakdowns[1].rows}
    assert {"Project NPV", "Total CFADS", "LCOE", "WACC", "Payback / discounted payback"} <= gaps


def test_trace_evidence_reports_missing_last_run_as_unavailable_never_available():
    p = _panel(trust_pack={"last_run": {"state": "UNAVAILABLE"}}, runtime_state="NOT_RUN", has_runtime=False)
    row = {r.label: r for r in p.sections[-1].breakdowns[0].rows}["Last Run identity"]
    assert row.value == "UNAVAILABLE" and row.tone == "warn"


# ───────────────────────────── navigation projection ─────────────────────────────

def test_navigation_bridges_terminology_and_anchors_only_existing_targets():
    from app.v2.workspace_shell_projection import workspace_nav_groups
    items = {i.label: i for g in workspace_nav_groups() for i in g.items}
    assert items["Development"].sheet_label == "CAPEX" and items["Operations"].sheet_label == "OPEX"
    assert items["Statements"].sheet_label == "Financial Statements"
    assert items["Assumptions"].anchor == "#assumption-register"
    assert items["Calculation Trace"].anchor == ""
    for it in items.values():
        if it.available:
            assert it.tab_id and it.tab_id.startswith("tab-")


# ───────────────────────────── statement number formatting ─────────────────────────────

def _fmt(v):
    from app.v2.router import _templates
    t = _templates.env.from_string(
        '{% from "partials/_money_format.html" import statement_keur %}{{ statement_keur(v) }}')
    return t.render(v=v).strip()


@pytest.mark.parametrize("value,expected", [
    (1234567.4, "1,234,567"), (-1234.4, "(1,234)"), (0, "0"), (0.0, "0"), (-0.2, "0"),
    (None, "—"), ("12", "—"), (True, "—"), (-0.5, "0"),
])
def test_statement_number_format(value, expected):
    assert _fmt(value) == expected


# ───────────────────────────── real pages (all four technologies) ─────────────────────────────

def _strip_html(pg):
    m = re.search(r'<section id="v2-kpi-strip".*?</section>', pg, re.S)
    assert m, "Key metrics strip is rendered inside the Smart Panel"
    return m.group(0)


def _strip_values(pg):
    out = {}
    for m in re.finditer(r'data-testid="kpi-strip-([a-z_]+)" data-metric="[^"]+"\s+data-available="(true|false)"'
                         r'(?:\s+data-raw="([^"]+)")?.*?<span class="v2-kpi-strip-value">([^<]*)</span>',
                         _strip_html(pg), re.S):
        out[m.group(1)] = (m.group(2) == "true", float(m.group(3)) if m.group(3) else None, m.group(4).strip())
    return out


def _ws(uid, rec):
    from app.persistence.workspace_repository import get_workspace_state
    return get_workspace_state(uid, rec.project_id)


@pytest.mark.parametrize("template", TECHNOLOGIES)
def test_strip_matches_persisted_last_run_and_freshness_follows_save_and_run(seeded_db, template, monkeypatch):
    uid = f"u-wc-strip-{template[8:12]}"
    client, rec = _project(uid, template)

    pg = client.get(f"/v2/workbook?project={rec.project_code}").text
    assert 'data-run-state="NOT_RUN"' in _strip_html(pg)
    assert all(v[2] == "—" and v[1] is None for v in _strip_values(pg).values())   # no Last Run, no values

    _run(client, rec.project_code)
    ws = _ws(uid, rec)
    rs, sp = ws.last_runtime_summary, (ws.last_sponsor_schedule or {}).get("summary") or {}
    pg = client.get(f"/v2/workbook?project={rec.project_code}").text
    assert 'data-run-state="CURRENT"' in _strip_html(pg)
    vals = _strip_values(pg)
    assert vals["project_irr"][1] == pytest.approx(rs["project_irr"])
    assert vals["equity_irr"][1] == pytest.approx(rs["equity_irr"])
    assert vals["min_dscr"][1] == pytest.approx(rs["min_dscr"])
    assert vals["senior_debt_keur"][1] == pytest.approx(rs["senior_debt_keur"])
    assert vals["actual_gearing_pct"][1] == pytest.approx(rs["actual_gearing_pct"])
    assert vals["sponsor_irr"][1] == pytest.approx(sp["total_sponsor_xirr"])
    assert vals["project_npv_keur"] == (False, None, "—")              # not persisted -> unavailable, not 0
    assert vals["total_cfads_keur"] == (False, None, "—")

    # a Save makes the SAME persisted values prior-run values, without any Run or engine call
    calls = []
    from app.runtime import model_execution as me
    orig = me.run_model_process

    async def spy(*a, **k):
        calls.append(1)
        return await orig(*a, **k)

    monkeypatch.setattr(me, "run_model_process", spy)
    before_identity = (ws.last_runtime_snapshot_id, ws.last_runtime_composite_hash, ws.last_runtime_summary)
    sid = _seeded_line(rec.project_id, "capex")
    row = _row(rec.project_id, sid, "capex")
    f = _line_fields(client, rec, "capex", sid)
    saved = client.post("/v2/capex/line/update", headers=HX, data=dict(
        f, label=row["label"], amount_keur=str(float(row["amount_keur"]) + 1), notes=""))
    assert saved.status_code == 200
    assert 'data-run-state="STALE"' in saved.text and "Prior Last Run" in saved.text   # same OOB response
    pg = client.get(f"/v2/workbook?project={rec.project_code}").text
    stale_vals = _strip_values(pg)
    assert stale_vals["project_irr"][1] == pytest.approx(rs["project_irr"])             # prior values still shown
    assert 'v2-kpi-strip-item--stale' in _strip_html(pg)
    assert calls == []                                                                   # no model Run happened
    ws2 = _ws(uid, rec)
    assert (ws2.last_runtime_snapshot_id, ws2.last_runtime_composite_hash, ws2.last_runtime_summary) == before_identity

    _run(client, rec.project_code)
    assert 'data-run-state="CURRENT"' in _strip_html(client.get(f"/v2/workbook?project={rec.project_code}").text)


@pytest.mark.parametrize("template", TECHNOLOGIES)
def test_statement_cells_equal_the_persisted_payload(seeded_db, template):
    from app.workbook.service import WorkbookService

    uid = f"u-wc-fs-{template[8:12]}"
    client, rec = _project(uid, template)
    _run(client, rec.project_code)
    ws = _ws(uid, rec)
    rr = WorkbookService.get_runtime_result(ws)
    payload = rr.financial_statements
    pg = client.get(f"/v2/workbook?project={rec.project_code}").text

    def cell(v):
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return "—"
        r = round(v)
        return f"({abs(r):,})" if r < 0 else f"{abs(r):,}"

    checked = 0
    for prefix, key, rows in (("fs-pnl", "pnl", ("revenues_keur", "ebit_keur", "net_income_keur", "cit_accrual_keur")),
                              ("fs-pf-cf", "pf_cash_waterfall", ("ebitda_cash_keur", "cash_tax_keur", "fcf_for_distribution_keur")),
                              ("fs-bs", "balance_sheet", ("total_assets_keur", "total_liabilities_equity_keur", "cash_keur"))):
        periods = payload[key]["periods"]
        assert periods, key
        m = re.search(rf'data-testid="{prefix}-table".*?</table>', pg, re.S)
        table = m.group(0)
        n_headers = len(re.findall(r'<th class="v2-statement-period-header">', table))
        assert n_headers == len(periods)                                  # the FULL period axis is shown
        for rk in rows:
            rm = re.search(rf'data-testid="{prefix}-row-{rk}".*?</tr>', table, re.S)
            shown = [c.strip() for c in re.findall(r'<td class="v2-statement-num[^"]*">([^<]*)</td>', rm.group(0))]
            assert shown == [cell(p.get(rk)) for p in periods], (prefix, rk)
            checked += len(shown)
    assert checked > 50
    assert re.search(r'data-testid="fs-bs-row-balance_check_keur"', pg)    # balance check row unchanged


@pytest.mark.parametrize("state,badge,text", [
    ("CLEAN", "CURRENT", "Outputs current"), ("STALE", "STALE · prior Last Run", "Run required"),
    ("NOT_RUN", "NOT RUN", "Not run"), ("FS_UNAVAILABLE", "UNAVAILABLE", "Output unavailable"),
])
def test_statement_state_bar_distinguishes_the_four_states(state, badge, text):
    from app.v2.router import _templates
    html = _templates.get_template("partials/_fs_runtime_bar.html").render({"fs_state": state})
    assert badge in html and text in html
    assert f'data-fs-state="{state}"' in html


def test_not_run_project_statements_show_no_fabricated_figures(seeded_db):
    client, rec = _project("u-wc-fs-notrun", "generic_solar_reference")
    pg = client.get(f"/v2/workbook?project={rec.project_code}").text
    assert "Run the model to generate the Income Statement." in pg
    assert 'data-testid="fs-pnl-table"' not in pg and 'data-fs-state="NOT_RUN"' in pg


def test_protected_reference_strip_never_shows_values_without_a_last_run(seeded_db):
    from app.persistence.projects_repository import get_reference_by_template_source

    client, _ = _project("u-wc-ref", "generic_solar_reference")
    ref = get_reference_by_template_source("generic_solar_reference")
    pg = client.get(f"/v2/workbook?project={ref.project_code}").text
    vals = _strip_values(pg)
    assert vals and all((not a) or (r is not None) for a, r, _d in vals.values())     # never an available 0 from nowhere
