"""WF-React-1 — canonical statement/chart row-unit integrity (post-#376 integration).

Runs the real statements route on a real persisted Run while spying the canonical
output projection, so every projected row can be compared with the canonical unit
and numeric cell values the projection itself assigned.  The route forwards each
row's ``unit`` and numeric ``v`` (aligned with the display text), and the React
classifier (``frontend/src/app/units.ts``, executed here under the CI Node runtime
through the repository TypeScript transpile) must therefore resolve EVERY row from
canonical metadata, never from a label.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.persistence import db

REPO = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

#: With canonical row units propagated no row may depend on label inference.
EXPECTED_LABEL_DEPENDENT: set = set()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "wf1-unit.db"))
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    db.init_db()
    from app.auth import COOKIE_NAME, create_session_token
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.v2.react_workspace_router import router as react_router
    from app.v2.router import router as v2_router
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    app.include_router(react_router, prefix="/v2")
    record = create_reference_seeded_project(user_id="wf1-unit", requested_name="WF1 Units", capacity_mw=16,
                                             template_source="generic_solar_reference")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id="wf1-unit", username="admin"))
        page = client.get("/v2/workbook", params={"project": record.project_code})
        from bs4 import BeautifulSoup
        form = BeautifulSoup(page.text, "html.parser").select_one("#v2-canonical-run-form")
        tokens = {f["name"]: f.get("value", "") for f in form.select("input[name]")}
        response = client.post("/v2/workbook/run", headers={"HX-Request": "true"},
                               data={"project": record.project_code, **tokens})
        assert response.status_code == 200 and response.headers.get("X-Finco-Run-Outcome") != "FAILED"
        yield SimpleNamespace(client=client, record=record)
    reset_model_executor_for_tests()


def _canonical_units(outputs):
    """(sheet id, row id) -> canonical unit assigned by the projection itself."""
    units = {}
    statements = outputs.get("statements") or []
    for index, sheet in enumerate(("pl", "balance", "cashflow")):
        for row in (statements[index].get("rows") or []) if index < len(statements) else []:
            units[(sheet, row["key"])] = row["unit"]
    for row in (outputs.get("cfads") or {}).get("rows") or []:
        units[("cfads", row["key"])] = row["unit"]
    for facility in (outputs.get("debt") or {}).get("facilities") or []:
        for row in (facility.get("operating") or {}).get("rows") or []:
            units.setdefault(("debt", row["key"]), row["unit"])
    for row in ((outputs.get("returns") or {}).get("distributions") or {}).get("rows") or []:
        units[("sponsor", row["key"])] = row["unit"]
    return units


def _classify(payload):
    script = """
import { loadUnits } from './frontend/transfer/scripts/loadUnits.mjs';
import fs from 'node:fs';
const { classifyRowUnit } = await loadUnits();
const payload = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
const out = [];
for (const sheet of payload.snapshot.sheets) for (const row of sheet.rows) {
  const { format, source } = classifyRowUnit(row.label, row.unit, sheet.unit);
  out.push({ sheet: sheet.id, row: row.id, label: row.label, kind: format.kind, base: format.base ?? null, source });
}
console.log(JSON.stringify(out));
"""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle)
    try:
        result = subprocess.run(["node", "--input-type=module", "-e", script, handle.name], cwd=REPO,
                                capture_output=True, text=True, timeout=120)
    finally:
        Path(handle.name).unlink(missing_ok=True)
    assert result.returncode == 0, result.stderr[-800:]
    return json.loads(result.stdout)


def test_every_statement_row_classification_matches_the_canonical_row_unit(env, monkeypatch):
    import app.v2.output_workspace_projection as projection
    captured = []
    original = projection.build_output_workspace_safe

    def spy(**kwargs):
        outputs = original(**kwargs)
        captured.append(outputs)
        return outputs

    monkeypatch.setattr(projection, "build_output_workspace_safe", spy)
    payload = env.client.get("/v2/model-react/statements", params={"project": env.record.project_code}).json()
    assert payload["state"] == "CURRENT" and captured, "statements must come from the persisted Run projection"
    canonical = _canonical_units(captured[-1])
    rows = _classify(payload)
    assert len(rows) >= 40, "all six statement destinations must be covered"
    assert {r["sheet"] for r in rows} == {"pl", "balance", "cashflow", "cfads", "debt", "sponsor"}

    payload_rows = {(sh["id"], r["id"]): r for sh in payload["snapshot"]["sheets"] for r in sh["rows"]}
    mismatches, label_dependent = [], set()
    for row in rows:
        unit = canonical.get((row["sheet"], row["row"]))
        assert unit is not None, f"no canonical unit found for {row['sheet']}.{row['row']}"
        expected = {"keur": ("money", "kEUR"), "x": ("ratio", None)}.get(unit)
        assert expected is not None, f"unsupported canonical unit {unit!r} on {row['sheet']}.{row['row']}"
        # projection -> API carries the canonical unit itself
        assert payload_rows[(row["sheet"], row["row"])]["unit"] == unit, (row["sheet"], row["row"])
        if (row["kind"], row["base"]) != expected:
            mismatches.append((row["sheet"], row["row"], unit, row["kind"]))
        if row["source"] == "label-inference":
            label_dependent.add((row["sheet"], row["row"]))
        assert row["source"] == "canonical-row-unit", (row["sheet"], row["row"], row["source"])
    assert mismatches == [], mismatches
    # the statement projection carries ONLY kEUR money and "x" ratios: no percentage rows exist
    assert set(canonical.values()) <= {"keur", "x"}
    assert label_dependent == EXPECTED_LABEL_DEPENDENT, label_dependent
    # sheet metadata lists exactly the canonical units of its rows
    for sheet in payload["snapshot"]["sheets"]:
        assert sheet["units"] == sorted({r["unit"] for r in sheet["rows"]}), sheet["id"]


def test_numeric_values_text_and_periods_are_aligned_with_the_canonical_source(env, monkeypatch):
    import app.v2.output_workspace_projection as projection
    captured = []
    original = projection.build_output_workspace_safe
    monkeypatch.setattr(projection, "build_output_workspace_safe",
                        lambda **kw: captured.append(original(**kw)) or captured[-1])
    payload = env.client.get("/v2/model-react/statements", params={"project": env.record.project_code}).json()
    outputs = captured[-1]
    snapshot = payload["snapshot"]
    tables = {"cfads": (outputs["cfads"], None),
              **{s: (outputs["statements"][i], outputs["statements"][i].get("annual"))
                 for i, s in enumerate(("pl", "balance", "cashflow"))}}
    sheets = {s["id"]: s for s in snapshot["sheets"]}
    checked_unavailable = checked_values = 0
    for sheet_id, (table, annual) in tables.items():
        annual_rows = {r["key"]: r for r in (annual or {}).get("rows", [])} if annual and annual.get("available") else {}
        for row in table["rows"]:
            projected = next(r for r in sheets[sheet_id]["rows"] if r["id"] == row["key"])
            assert len(projected["model"]) == len(projected["model_v"]) == len(row["cells"]) == len(snapshot["modelPeriods"])
            for cell, text, value in zip(row["cells"], projected["model"], projected["model_v"]):
                if cell["v"] is None:
                    assert text == "—" and value is None, (sheet_id, row["key"], text, value)
                    checked_unavailable += 1
                else:
                    assert text != "—" and value == cell["v"] and text == cell["text"], (sheet_id, row["key"])
                    checked_values += 1
            if sheet_id in ("pl", "balance", "cashflow"):
                counterpart = annual_rows.get(row["key"])
                assert counterpart is not None, (sheet_id, row["key"])
                assert len(projected["annual"]) == len(projected["annual_v"]) == len(snapshot["annualPeriods"])
                for cell, text, value in zip(counterpart["cells"], projected["annual"], projected["annual_v"]):
                    assert (value == cell["v"]) and ((text == "—") == (cell["v"] is None)), (sheet_id, row["key"])
                    checked_values += 1
    assert checked_unavailable > 0, "the Run must contain at least one unavailable statement cell to prove the rule"
    assert checked_values > 200
    # the F3 / aggregate facility rows (when present) carry the same metadata
    for rows in snapshot["debtRowsByFacility"].values():
        for row in rows:
            assert row["unit"] in ("keur", "x") and len(row["model_v"]) == len(row["model"])
