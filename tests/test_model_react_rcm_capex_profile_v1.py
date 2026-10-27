"""RC-M — the React Goal Seek and Analysis adapters bind the saved monthly CAPEX profile exactly as the Legacy routes do (RC-7).

``app/v2/react_goal_seek.py`` folds CAPEX sub-lines and then binds the profile (``apply_snapshot_profiles``) before the canonical engine
evaluation; the sensitivity strip and matrix reach the same binder through ``app.services.sensitivity_matrix``.  Proven here, not assumed:
(1) the profile materially changes the numbers (so a surface that ignored it would be wrong), (2) the React result equals the Legacy route's
result on the same profiled Working Copy, and (3) the order inside the adapter is fold -> bind -> engine.  Synthetic data only.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from app.capex_profiles.runtime import leaves_for
from app.capex_profiles.service import save_profiles
from app.persistence.workspace_repository import get_workspace_state
from app.workbook.registry import WORKBOOK
from app.workbook.workbook_identity import assemble_consistent_for_get
from tests.test_model_react_rcm_goal_seek_v1 import BASE, HDR, baseline_irr_pct, call, env, with_sensitivity  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent


def _profile(record):
    """Save a FRONT_LOADED monthly profile on every CAPEX leaf through the canonical service (what the planner Save does)."""
    from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
    from app.workbook.service import WorkbookService

    ws = get_workspace_state(record.user_id, record.project_id)
    pi = WorkbookService.to_projectinputs(WorkbookService.build_draft_input_set_from_workspace(ws))
    capex = apply_user_sub_lines_replacing_base(pi.capex, project_id=record.project_id)
    leaves = [leaf for leaf in leaves_for(capex, record.project_id) if leaf.amount_keur > 0]
    assert leaves
    document = json.dumps({"version": 1, "profiles": [{"item_key": leaf.item_key, "shape": "FRONT_LOADED", "explicit_percent": [],
                                                      "milestone_month": None} for leaf in leaves]})
    identity = assemble_consistent_for_get(record.user_id, record.project_id, WORKBOOK.version).composite_hash
    save_profiles(owner=record.user_id, project_id=record.project_id, expected_hash=identity,
                  expected_scenario_id=ws.active_scenario_id or "", raw=document)


def _legacy_goal_seek(env, record, target):
    response = env.client.post("/v2/workbook/goal-seek/run", data={"project": record.project_code, "target_metric": "project_irr",
                                                                   "target_value": str(target)}, headers={"HX-Request": "true"})
    assert response.status_code == 200, response.text[:300]
    soup = BeautifulSoup(response.text, "html.parser")
    text = lambda tid: soup.select_one(f"[data-testid='{tid}']").get_text(" ", strip=True)
    return (float(re.search(r"-?\d+\.\d+", text("gs-solved-value")).group(0)), float(re.search(r"-?\d+\.\d+", text("gs-achieved-value")).group(0)),
            int(text("gs-evaluations")))


def test_goal_seek_binds_the_profile_and_equals_the_legacy_route_on_a_profiled_working_copy(with_sensitivity):
    env = with_sensitivity
    plain, profiled = env.create(name="GS plain"), env.create(name="GS profiled")
    _profile(profiled)
    target = round(baseline_irr_pct(env, plain) + 0.5, 2)
    solved = lambda record: call(env.client, "solve", project=record.project_code, target_metric="project_irr", target_value=str(target)).json()["result"]
    a, b = solved(plain), solved(profiled)
    assert a["solved"] and b["solved"]
    assert round(b["solved_input_value"], 2) != round(a["solved_input_value"], 2)         # the monthly profile is really bound (IDC timing moved the answer)
    legacy_solved, legacy_achieved, legacy_evaluations = _legacy_goal_seek(env, profiled, target)
    assert round(b["solved_input_value"], 2) == legacy_solved
    assert round(b["achieved_metric_value"] * 100, 4) == pytest.approx(legacy_achieved, abs=1e-4)
    assert b["model_evaluations"] == legacy_evaluations                                    # the same deterministic, profile-bound solve


def test_the_sensitivity_strip_and_matrix_bind_the_profile_and_equal_the_legacy_routes(with_sensitivity):
    env = with_sensitivity
    plain, profiled = env.create(name="SN plain"), env.create(name="SN profiled")
    _profile(profiled)
    strip = lambda record: env.client.get("/v2/model-react/analysis/sensitivity/strip", params={"project": record.project_code, "driver": "tariff"},
                                          headers=HDR).json()
    a, b = strip(plain), strip(profiled)
    assert b["base"]["values"]["project_irr"]["raw"] != pytest.approx(a["base"]["values"]["project_irr"]["raw"], abs=1e-9)   # bound, not ignored
    env.client.get("/v2/workbook", params={"project": profiled.project_code})
    legacy = env.client.post("/v2/workbook/scenarios/sensitivity/run", data={"project": profiled.project_code, "driver": "tariff"},
                             headers={"HX-Request": "true"})
    assert legacy.status_code == 200, legacy.text[:300]
    soup = BeautifulSoup(legacy.text, "html.parser")
    headers = [th.get_text(" ", strip=True) for th in soup.select("table.v2-sens-table thead th")]
    column = next(i for i, h in enumerate(headers) if h.startswith("Project IRR"))
    pct = lambda cell: float(re.search(r"-?\d+(?:\.\d+)?", cell.get_text(" ", strip=True).split("Δ")[0].replace(",", "")).group(0))
    legacy_irr = [pct(tr.find_all("td")[column]) for tr in soup.select("table.v2-sens-table tbody tr")]
    assert len(legacy_irr) == 5 == len(b["rows"])
    for expected, row in zip(legacy_irr, b["rows"]):
        assert expected == pytest.approx(row["values"]["project_irr"]["raw"] * 100, abs=0.006)
    matrix = lambda record: env.client.get("/v2/model-react/analysis/sensitivity/matrix", params={
        "project": record.project_code, "driver_a": "tariff", "driver_b": "capex", "metric": "project_irr"}, headers=HDR).json()
    assert matrix(profiled)["matrix"]["base"]["raw"] != pytest.approx(matrix(plain)["matrix"]["base"]["raw"], abs=1e-9)


def test_goal_seek_folds_then_binds_then_evaluates():
    """Order proof inside the adapter: sub-line fold -> financing/F3 state -> profile binder, all before the evaluator exists."""
    source = (ROOT / "app/v2/react_goal_seek.py").read_text(encoding="utf-8")
    construct = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "_construct")
    body = ast.get_source_segment(source, construct)
    assert body.index("apply_user_sub_lines_replacing_base(") < body.index("apply_user_sub_lines_to_opex(") < body.index("apply_state(") \
        < body.index("apply_snapshot_profiles(")
    solve = source[source.index("async def react_goal_seek_solve("):source.index("class ApplyBody")]
    assert solve.index("_construct(") < solve.index("make_canonical_evaluator(") < solve.index("solve_tariff_for_metric(")
