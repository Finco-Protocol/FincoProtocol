"""WF-React-1 Correction A — statement/chart row-unit integrity evidence.

Runs the real statements route on a real persisted Run while spying the
canonical output projection, so every displayed row can be compared with the
canonical unit the projection itself assigned.  The projection route
(``react_workspace_router``) currently forwards only the sheet-level unit and the
display text; the React classifier therefore resolves each row from the sheet
unit plus a word-boundary label fallback.  This module PROVES that classification
agrees with the canonical row units for every row of the six statement
destinations and every chart source, and RECORDS exactly which rows depend on the
label fallback (the residual limitation fixed by propagating row ``unit``/``v``
during the authorized #376 integration).
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

#: Rows whose canonical unit differs from the sheet unit (= first row's unit) and are
#: therefore classified from their label today.  Anything else is a sheet-unit money row.
EXPECTED_LABEL_DEPENDENT = {("cfads", "dscr"), ("debt", "dscr")}


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

    mismatches, label_dependent, sheet_unit_rows = [], set(), 0
    for row in rows:
        unit = canonical.get((row["sheet"], row["row"]))
        assert unit is not None, f"no canonical unit found for {row['sheet']}.{row['row']}"
        expected = {"keur": ("money", "kEUR"), "x": ("ratio", None)}.get(unit)
        assert expected is not None, f"unsupported canonical unit {unit!r} on {row['sheet']}.{row['row']}"
        if (row["kind"], row["base"]) != expected:
            mismatches.append((row["sheet"], row["row"], unit, row["kind"]))
        if row["source"] == "label-inference":
            label_dependent.add((row["sheet"], row["row"]))
        if row["source"] == "sheet-unit":
            sheet_unit_rows += 1
        assert row["source"] != "unspecified", f"ambiguous unit metadata on {row['sheet']}.{row['row']}"
    assert mismatches == [], mismatches
    # the statement projection carries ONLY kEUR money and "x" ratios: no percentage rows exist
    assert set(canonical.values()) <= {"keur", "x"}
    # exactly the documented rows rely on the label fallback today
    assert label_dependent == EXPECTED_LABEL_DEPENDENT, label_dependent
    assert sheet_unit_rows == len(rows) - len(label_dependent)


def test_unavailable_cells_are_dashes_never_zero_in_the_projection(env, monkeypatch):
    import app.v2.output_workspace_projection as projection
    captured = []
    original = projection.build_output_workspace_safe
    monkeypatch.setattr(projection, "build_output_workspace_safe",
                        lambda **kw: captured.append(original(**kw)) or captured[-1])
    payload = env.client.get("/v2/model-react/statements", params={"project": env.record.project_code}).json()
    outputs = captured[-1]
    tables = {"cfads": outputs["cfads"], **{s: (outputs["statements"][i]) for i, s in enumerate(("pl", "balance", "cashflow"))}}
    sheets = {s["id"]: s for s in payload["snapshot"]["sheets"]}
    checked_unavailable = 0
    for sheet_id, table in tables.items():
        for row in table["rows"]:
            shown = next(r for r in sheets[sheet_id]["rows"] if r["id"] == row["key"])["model"]
            for cell, text in zip(row["cells"], shown):
                if cell["v"] is None:
                    assert text == "—", (sheet_id, row["key"], text)
                    checked_unavailable += 1
                else:
                    assert text != "—"
    assert checked_unavailable > 0, "the Run must contain at least one unavailable statement cell to prove the rule"
