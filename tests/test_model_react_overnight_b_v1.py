"""Overnight B — React Institutional Model MVP correction: source and projection contracts.

Fast, browser-free guards for the corrections whose real-Chromium acceptance lives in
``tests/model_react_overnight_b_acceptance.py``: presentation-only projections of the React
workspace router, the Run-identity contract (Python mirror vs the real TypeScript module), the
no-demo-fallback rule for a live statement identity, and the absence of literal escapes / engineering
copy in the live React source.  No financial engine, writer or ledger is imported or changed.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import react_run_identity as py

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "frontend" / "src" / "app"
WORKBOOK = ROOT / "frontend" / "src" / "finco" / "_workbook"

SNAPSHOTS = [
    "20261027T004939.123456+0000",
    "20261027T004939.123457+0000",      # same second, different microsecond
    "20261027T004939+0000",             # no fraction
    "20261027T235959.000001Z",
    "20261027T010203.5+0200",
    "snapshot-contract-123",            # not canonical: shown verbatim, never shortened
    "20261301T004939.1+0000",           # impossible month: not canonical
    "",
]


def test_the_truncated_snapshot_prefix_is_not_an_identity_but_the_presented_identity_is():
    a, b = SNAPSHOTS[0], SNAPSHOTS[1]
    assert a[:12] == b[:12] == "20261027T004"
    assert py.text(a) != py.text(b)
    assert py.text(a) == "2026-10-27 00:49:39 UTC · 123456"
    assert py.text("20261027T004939+0000") == "2026-10-27 00:49:39 UTC"
    assert py.text("20261027T010203.5+0200") == "2026-10-27 01:02:03 UTC+02:00 · 5"
    assert py.text("snapshot-contract-123") == "snapshot-contract-123"
    assert py.text("") == "No persisted Run"


@pytest.mark.skipif(shutil.which("node") is None or not (ROOT / "frontend/node_modules/.bin/esbuild").exists(),
                    reason="needs node and the frontend dev dependencies (esbuild)")
def test_the_python_mirror_equals_the_real_typescript_run_identity_module(tmp_path):
    script = tmp_path / "parity.mjs"
    bundle = tmp_path / "runIdentity.mjs"
    subprocess.run([str(ROOT / "frontend/node_modules/.bin/esbuild"), str(APP / "runIdentity.tsx"), "--bundle", "--format=esm",
                    "--platform=node", "--jsx=automatic", f"--outfile={bundle}"],
                   check=True, capture_output=True, cwd=ROOT / "frontend")
    script.write_text(
        "import { runIdentityText } from %s;\nconst ids = JSON.parse(process.argv[2]);\n"
        "console.log(JSON.stringify(ids.map(runIdentityText)));\n" % json.dumps(bundle.as_uri()))
    result = subprocess.run(["node", str(script), json.dumps(SNAPSHOTS)], check=True, capture_output=True, text=True,
                            cwd=ROOT / "frontend", env={"NODE_PATH": str(ROOT / "frontend/node_modules"), "PATH": "/usr/bin:/bin:/usr/local/bin"})
    assert json.loads(result.stdout) == [py.text(i) for i in SNAPSHOTS]


@pytest.mark.skipif(shutil.which("node") is None or not (ROOT / "frontend/node_modules/.bin/esbuild").exists(),
                    reason="needs node and the frontend dev dependencies (esbuild)")
def test_label_and_unit_are_rendered_exactly_once(tmp_path):
    bundle = tmp_path / "fieldLabel.mjs"
    subprocess.run([str(ROOT / "frontend/node_modules/.bin/esbuild"), str(APP / "fieldLabel.ts"), "--bundle", "--format=esm",
                    f"--outfile={bundle}"], check=True, capture_output=True, cwd=ROOT / "frontend")
    cases = [["IT Capacity (MW)", "MW"], ["Installed Charging Capacity (MW)", "MW"], ["Gearing", "%"], ["Capacity Factor (P50)", "%"],
             ["Tariff (EUR/MWh)", "EUR/MWh"], ["Site (MW) area", "MW"], ["Label", None]]
    script = tmp_path / "labels.mjs"
    script.write_text("import { labelWithUnit } from %s;\nconsole.log(JSON.stringify(JSON.parse(process.argv[2]).map(([l,u]) => labelWithUnit(l,u))));\n"
                      % json.dumps(bundle.as_uri()))
    out = subprocess.run(["node", str(script), json.dumps(cases)], check=True, capture_output=True, text=True).stdout
    assert json.loads(out) == ["IT Capacity (MW)", "Installed Charging Capacity (MW)", "Gearing (%)", "Capacity Factor (P50) (%)",
                              "Tariff (EUR/MWh)", "Site (MW) area (MW)", "Label"]


# ── live React source rules ───────────────────────────────────────────────────────────────────────────────────

def test_live_react_text_has_no_literal_unicode_escapes():
    offenders = []
    for path in list(APP.rglob("*.tsx")) + [WORKBOOK / "StatementWorkbook.tsx"]:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r">[^<{]*\\u[0-9a-fA-F]{4}", line):                 # JSX text never processes an escape
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert offenders == []


def test_a_canonical_statement_never_falls_back_to_the_demo_project_context():
    source = (WORKBOOK / "StatementWorkbook.tsx").read_text(encoding="utf-8")
    assert 'status.dataOrigin ?? "synthetic-demo") === "canonical-run"' in source
    assert "canonicalOrigin" in source and "identityMissing" in source and 'data-statement-identity="missing"' in source
    # the demo context is only reachable for non-canonical origins
    assert re.search(r"canonicalOrigin\s*\n?\s*\?\s*\{ id: projectIdentity", source)
    assert ": readProjectContext();" in source
    view = (APP / "WorkspaceView.tsx").read_text(encoding="utf-8")
    assert "projectIdentity={{ code: workspace.project.code, name: workspace.project.name, type: workspace.project.project_type }}" in view
    assert "history.replaceState" not in view or "params.set(\"project\"" not in view, "the workspace no longer writes identity into the URL"
    assert "statementsConflict" in view and "StatementIdentityConflict" in view


def test_the_react_workspace_does_not_write_project_identity_into_the_query_string():
    view = (APP / "WorkspaceView.tsx").read_text(encoding="utf-8")
    for key in ('params.set("projectId"', 'params.set("technology"', 'params.set("project"'):
        assert key not in view


def test_engineering_copy_is_not_in_routine_react_text():
    banned = ("out of this PR", "composite CAS", "a stale value answers 409", "RuntimeResult.", "PARTIAL path", "R8/N02")
    for path in APP.rglob("*.tsx"):
        text = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                         if not line.lstrip().startswith(("//", "*", "/*")))       # developer comments may name internals
        for token in banned:
            assert token not in text, f"{path.name}: {token}"


# ── router projections (presentation only) ───────────────────────────────────────────────────────────────────

def _record(**kwargs):
    return SimpleNamespace(project_type=kwargs.get("project_type", ""), template_source=kwargs.get("template_source", ""))


@pytest.mark.parametrize("record,key,tier,runnable", [
    (_record(project_type="Solar", template_source="generic_solar_reference"), "solar", "PILOT_CANDIDATE", True),
    (_record(project_type="Wind", template_source="generic_wind_reference"), "wind", "PILOT_CANDIDATE", True),
    (_record(project_type="Data Center", template_source="generic_data_center_reference"), "data_center", "PREVIEW", True),
    (_record(project_type="EV Charging", template_source="generic_ev_charging_reference"), "ev_charging", "PREVIEW", True),
    (_record(project_type="Storage", template_source="generic_storage_reference"), "storage", "RELEASE_CLOSED", False),
])
def test_vertical_scope_is_read_from_the_capability_registry(record, key, tier, runnable):
    from app.product_capability import capability_by_key
    from app.v2.react_workspace_router import _vertical_scope

    scope = _vertical_scope(record)
    cap = capability_by_key(key)
    assert scope["key"] == key and scope["pilot_tier"] == tier and scope["runnable"] is runnable is cap.runnable
    assert scope["limitations"] == list(cap.limitations) and scope["registry_status"] == cap.status.value


def test_an_unrecognised_project_type_is_never_presented_as_released():
    from app.v2.react_workspace_router import _vertical_scope

    scope = _vertical_scope(_record(project_type="Hydrogen"))
    assert scope["pilot_tier"] == "UNCLASSIFIED" and scope["runnable"] is False and scope["key"] == ""


def test_lender_metrics_are_unavailable_never_zero_and_plcr_is_never_produced():
    from app.v2.react_workspace_router import _lender_metrics

    run = SimpleNamespace(runtime_summary={"min_dscr": 1.31, "avg_dscr": 1.4}, debt_schedule={"summary": {"min_llcr": None}},
                          sponsor_schedule={})
    rows = {r["key"]: r for r in _lender_metrics(run)}
    assert rows["min_dscr"]["available"] and rows["min_dscr"]["display"] == "1.31x"
    for key in ("min_llcr", "project_npv_keur", "equity_npv_keur", "plcr"):
        assert rows[key]["available"] is False and rows[key]["display"] is None and rows[key]["reason"]
    zero = SimpleNamespace(runtime_summary={"project_npv_keur": 0.0}, debt_schedule={}, sponsor_schedule={})
    assert {r["key"]: r for r in _lender_metrics(zero)}["project_npv_keur"]["available"], "a genuine zero is a value, not an absence"


def test_lender_metrics_fail_closed_when_the_run_cannot_be_read():
    from app.v2.react_workspace_router import _lender_metrics

    rows = _lender_metrics(object())
    assert rows and all(not r["available"] for r in rows)


def test_cost_line_boundary_note_is_accurate_and_the_authority_flag_is_unchanged():
    source = (ROOT / "app/v2/react_workspace_router.py").read_text(encoding="utf-8")
    assert "out of this PR's scope" not in source
    assert "edited and saved in the" in source and '"capex_opex_editable": False' in source
