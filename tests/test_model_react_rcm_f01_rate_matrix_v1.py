"""RC-M x FIN-VAL F01 — Wizard -> Create -> Open -> Financing -> Save -> Reload -> Run for the four verticals and the four reviewed rates.

The React wizard creates through the canonical, request-keyed creation authority, so the new Working Copy must carry F01's ``human_percent_v1`` contract
(0.056 % -> 0.00056, 0.56 % -> 0.0056, 5.60 % -> 0.056, 9.00 % -> 0.09, converted exactly once at the typed engine boundary).  Nothing here
reimplements a rate conversion: the assertions read the F01 authority (``senior_rate_authority`` / ``RATE_UNIT``) and the real canonical Save and Run.
A Run that the model honestly refuses (a Data Center case, as in F01's own lifecycle matrix) must leave no history row.  Synthetic data only.
"""
from __future__ import annotations

import json
import sqlite3
import uuid

import pytest
from bs4 import BeautifulSoup

from app.input_adapter import RATE_UNIT, RATE_UNIT_KEY, senior_rate_authority
from app.workbook.input_set import ProjectInputSet
from tests.test_finval_rate_contract import KINDS, RATE_FIELD, _save
from tests.test_fin_val_b2_c1_recovery_finite_opex import USER, _prime, _snapshot, _ws, env  # noqa: F401

BASE = "/v2/model-react/new-project"
HDR = {"X-Finco-React-Request": "1"}
RATES = (0.056, 0.56, 5.6, 9.0)
RATIO = {0.056: 0.00056, 0.56: 0.0056, 5.6: 0.056, 9.0: 0.09}
COUNTRY = {"solar": "XA", "wind": "XB", "data_center": "XD", "ev_charging": "XE"}


def _wizard_create(env, kind):
    opts = env.client.get(f"{BASE}/options").json()
    body = {"request_id": opts["request_id"], "csrf_token": opts["csrf_token"], "name": f"RCM F01 {kind}", "technology": kind,
            "country": COUNTRY[kind], "capacity_mw": 20.0, "acknowledge_preview": True}
    response = env.client.post(f"{BASE}/create", json=body)
    assert response.status_code == 200 and response.json()["ok"], response.text
    code = response.json()["project"]["code"]
    from app.persistence.projects_repository import get_project_by_code
    return get_project_by_code(USER, code)


def _history(env, record):
    with sqlite3.connect(env.db_path) as c:
        return c.execute("SELECT COUNT(*) FROM model_run_history WHERE project_id=?", (record.project_id,)).fetchone()[0]


@pytest.mark.parametrize("kind", KINDS)
def test_a_wizard_created_working_copy_carries_the_f01_rate_contract(env, kind):
    record = _wizard_create(env, kind)
    snapshot = _snapshot(record)
    assert snapshot[RATE_UNIT_KEY] == RATE_UNIT                                  # explicit unit provenance, never inferred from magnitude
    typed = ProjectInputSet.from_snapshot(snapshot).to_projectinputs()
    assert float(snapshot["interest_rate_pct"]) == pytest.approx(senior_rate_authority(typed)[1] * 100, abs=1e-12)
    workspace = env.client.get("/v2/model-react/workspace", params={"project": record.project_code}).json()
    assert workspace["ok"] and workspace["freshness"]["state"] == "NOT_RUN" and _history(env, record) == 0     # creation never Runs
    studio = env.client.get("/v2/model-react/financing/studio", params={"project": record.project_code}).json()
    assert studio["ok"] and studio["editable"] is True and studio["freshness"] == "NOT_RUN"


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("human", RATES)
def test_wizard_to_financing_save_reload_and_run_keeps_one_exact_unit(env, kind, human, monkeypatch):
    record = _wizard_create(env, kind)
    _prime(env, record)
    # Financing: the Debt terms editor shows the percentage the user will type, with no magnitude inference
    before = {r["field_id"]: r for r in env.client.get("/v2/model-react/fields/debt", params={"project": record.project_code}).json()["fields"]}
    assert before[RATE_FIELD]["display_value"].endswith("%")
    _save(env, record, human, "single")                                          # the canonical per-field Save (CAS + CSRF)
    snapshot = _snapshot(record)
    assert float(snapshot["interest_rate_pct"]) == human and snapshot[RATE_UNIT_KEY] == RATE_UNIT
    # Reload: the projection and the typed inputs agree on the exact figure
    row = next(r for r in env.client.get("/v2/model-react/fields/debt", params={"project": record.project_code}).json()["fields"]
               if r["field_id"] == RATE_FIELD)
    assert row["value"] == human and row["display_value"] == f"{human:.12g}%"
    typed = ProjectInputSet.from_snapshot(snapshot).to_projectinputs()
    assert senior_rate_authority(typed)[1] == pytest.approx(RATIO[human], abs=1e-17)
    assert _ws(record).last_runtime_snapshot_id in (None, "") and _history(env, record) == 0           # Save is not a Run
    # Run: the canonical Run route receives exactly that effective rate
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    form = BeautifulSoup(page.text, "html.parser").select_one("#v2-canonical-run-form")
    data = {i["name"]: i.get("value", "") for i in form.select("input[name]")}
    data["csrf_token"] = data.pop("run_csrf_token")
    data["run_intent_id"] = str(uuid.uuid4())
    import app.api.project_runner as runner

    original, captured = runner.run_project, []

    def observed(*args, **kwargs):
        captured.append(kwargs["project_inputs_override"])
        return original(*args, **kwargs)

    monkeypatch.setattr(runner, "run_project", observed)
    response = env.client.post("/v2/workbook/run", headers={"Accept": "application/json", "HX-Request": "true"}, data=data, follow_redirects=False)
    assert len(captured) == 1 and senior_rate_authority(captured[0])[1] == pytest.approx(RATIO[human], abs=1e-17)
    outcome = response.json()["outcome"]
    assert outcome in ("COMMITTED", "FAILED")                                    # an honest model refusal is typed, never a silent number
    assert _history(env, record) == (1 if outcome == "COMMITTED" else 0)
    monkeypatch.undo()


@pytest.mark.parametrize("kind", ("solar", "wind"))
def test_previews_after_a_committed_run_never_change_history_or_the_last_run(env, kind, monkeypatch):
    """Sensitivity and Goal Seek read the same F01 rate authority and stay non-mutating previews."""
    record = _wizard_create(env, kind)
    _prime(env, record)
    _save(env, record, 5.6, "single")
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    form = BeautifulSoup(page.text, "html.parser").select_one("#v2-canonical-run-form")
    data = {i["name"]: i.get("value", "") for i in form.select("input[name]")}
    data["csrf_token"] = data.pop("run_csrf_token")
    data["run_intent_id"] = str(uuid.uuid4())
    assert env.client.post("/v2/workbook/run", headers={"Accept": "application/json", "HX-Request": "true"}, data=data,
                           follow_redirects=False).json()["outcome"] == "COMMITTED"
    last_run, rows = _ws(record).last_runtime_snapshot_id, _history(env, record)
    draft = json.dumps(_snapshot(record), sort_keys=True, default=str)
    strip = env.client.get("/v2/model-react/analysis/sensitivity/strip", params={"project": record.project_code, "driver": "interest_rate"}, headers=HDR)
    assert strip.status_code == 200 and strip.json()["ok"]
    base_rate = strip.json()["base"]
    assert base_rate["status"] == "OK"
    matrix = env.client.get("/v2/model-react/analysis/sensitivity/matrix", params={
        "project": record.project_code, "driver_a": "interest_rate", "driver_b": "tariff" if kind in ("solar", "wind") else "capex",
        "metric": "project_irr"}, headers=HDR)
    assert matrix.status_code == 200 and matrix.json()["ok"] and matrix.json()["matrix"]["counts"]["OK"] == 9
    catalog = env.client.get("/v2/model-react/analysis/goal-seek/catalog", params={"project": record.project_code}, headers=HDR).json()
    solve = env.client.get("/v2/model-react/analysis/goal-seek/solve", params={
        "project": record.project_code, "target_metric": "project_irr", "target_value": "9"}, headers=HDR)
    assert catalog["ok"] and solve.status_code in (200, 422)
    assert _ws(record).last_runtime_snapshot_id == last_run and _history(env, record) == rows            # previews write no Run and no history
    assert json.dumps(_snapshot(record), sort_keys=True, default=str) == draft                              # and never touch the Working Copy
