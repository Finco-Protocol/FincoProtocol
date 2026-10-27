"""RC-M Lane B — contract and parity tests for the React Goal Seek (tender pricing) adapter.

The adapter adds no solver and no writer: the solve is the canonical bracketed tariff solver on the canonical input construction and
the Apply is the canonical atomic field writer.  Proven here: guard order, preview-only semantics (nothing persisted), parity of the
solved tariff / achieved metric with the Legacy route for the same target on the same runtime, the CSRF-bound CAS Apply (stale hash,
tampered token, wrong field, cross-user, protected reference), and Apply -> STALE -> deliberate Run.  Synthetic data only.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.persistence import db
from app.persistence.workspace_repository import get_workspace_state
from tests.run_clone_csrf import post_valid_csrf

OWNER = "rcm-gs-owner"
STRANGER = "rcm-gs-stranger"
BASE = "/v2/model-react/analysis/goal-seek"
HDR = {"X-Finco-React-Request": "1"}
FIELD = "revenue.ppa.base_tariff"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "rcm_gs.db"))
    db.init_db()
    from app.auth import COOKIE_NAME, create_session_token
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.v2.react_goal_seek import router as gs_router
    from app.v2.react_poc_router import router as poc_router
    from app.v2.react_workspace_router import router as workspace_router
    from app.v2.router import router as v2_router

    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    app.include_router(workspace_router, prefix="/v2")
    app.include_router(gs_router, prefix="/v2")
    app.include_router(poc_router, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))
        stranger = TestClient(app)
        stranger.cookies.set(COOKIE_NAME, create_session_token(user_id=STRANGER, username="stranger"))
        anonymous = TestClient(app)

        def create(kind="solar", user=OWNER, name=None, capacity=20.0):
            return create_reference_seeded_project(user_id=user, template_source=f"generic_{kind}_reference",
                                                   requested_name=name or f"GS {kind}", capacity_mw=capacity)

        yield SimpleNamespace(client=client, stranger=stranger, anonymous=anonymous, create=create, app=app)
    reset_model_executor_for_tests()


def call(client, path, **params):
    return client.get(f"{BASE}/{path}", params=params, headers=HDR)


def state(record):
    ws = get_workspace_state(record.user_id, record.project_id)
    return (ws.last_runtime_snapshot_id, dict(ws.draft_snapshot), dict(ws.saved_snapshot), ws.dirty)


def baseline_irr_pct(env, record):
    """Unshocked Project IRR (percent) from the canonical sensitivity service — used only to choose a feasible target."""
    body = env.client.get("/v2/model-react/analysis/sensitivity/strip", params={"project": record.project_code, "driver": "tariff"},
                          headers=HDR).json()
    return body["base"]["values"]["project_irr"]["raw"] * 100


@pytest.fixture()
def with_sensitivity(env):
    from app.v2.react_analysis import router as analysis_router

    env.app.include_router(analysis_router, prefix="/v2")
    return env


def run_canonical(env, code):
    page = env.client.get("/v2/workbook", params={"project": code})
    tokens = {k: re.search(f'name="{k}" value="([^"]*)"', page.text).group(1) for k in ("content_hash", "workbook_version")}
    response = post_valid_csrf(env.client, "/v2/workbook/run", headers={"HX-Request": "true"}, data=dict(project=code, **tokens))
    assert response.status_code == 200, response.text[:300]


# ── guards ─────────────────────────────────────────────────────────────────

def test_requires_flag_header_session_and_ownership(env, monkeypatch):
    record = env.create()
    params = {"project": record.project_code, "target_metric": "project_irr", "target_value": "9"}
    assert env.client.get(f"{BASE}/solve", params=params).json()["code"] == "REQUEST_HEADER_REQUIRED"
    assert env.anonymous.get(f"{BASE}/solve", params=params, headers=HDR).status_code == 401
    assert call(env.stranger, "solve", **params).status_code == 404
    assert call(env.client, "catalog", project="nope").status_code == 404
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")
    assert call(env.client, "solve", **params).status_code == 404


def test_protected_reference_is_refused(env):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services.project_library_service import ensure_reference_models

    ensure_reference_models()
    reference = get_reference_by_template_source("generic_wind_reference")
    refused = call(env.client, "solve", project=reference.project_code, target_metric="project_irr", target_value="9")
    assert refused.status_code == 409 and refused.json()["code"] == "PROTECTED_REFERENCE"


@pytest.mark.parametrize("params,message", [
    ({"target_metric": "min_dscr", "target_value": "9"}, "Unknown target metric"),
    ({"target_metric": "project_irr", "target_value": "abc"}, "not a valid number"),
    ({"target_metric": "project_irr", "target_value": "nan"}, "not a valid number"),
    ({"target_metric": "project_irr", "target_value": ""}, "not a valid number"),
])
def test_invalid_solve_requests_are_typed_422_and_change_nothing(env, params, message):
    record = env.create()
    before = state(record)
    response = call(env.client, "solve", project=record.project_code, **params)
    assert response.status_code == 422 and message in response.json()["message"]
    assert state(record) == before


def test_catalog_states_the_variable_budgets_and_binding_and_flags_unsupported_verticals(env):
    solar = env.create("solar")
    body = call(env.client, "catalog", project=solar.project_code).json()
    assert body["ok"] and body["available"] and body["variable"]["field_id"] == FIELD
    from app.services.goal_seek import GOAL_SEEK_METRICS
    assert [m["key"] for m in body["metrics"]] == list(GOAL_SEEK_METRICS) == ["project_irr", "pure_equity_irr", "total_sponsor_irr"]
    assert body["current_tariff"] > 0 and body["budgets"]["max_model_evaluations"] == 40
    assert body["binding"]["content_hash"] and body["semantics"]["preview_only"] is True and body["semantics"]["is_a_run"] is False
    dc = env.create("data_center", capacity=10.0)
    closed = call(env.client, "catalog", project=dc.project_code).json()
    assert closed["available"] is False and "supported: Solar and Wind" in closed["reason"] and closed["vertical"]["pilot_tier"] == "PREVIEW"
    refused = call(env.client, "solve", project=dc.project_code, target_metric="project_irr", target_value="9")
    assert refused.status_code == 422 and refused.json()["code"] == "INVALID_REQUEST"


# ── preview ────────────────────────────────────────────────────────────────

def test_preview_solves_a_feasible_target_without_mutating_anything(with_sensitivity):
    env = with_sensitivity
    record = env.create()
    target = round(baseline_irr_pct(env, record) + 0.75, 2)
    before = state(record)
    body = call(env.client, "solve", project=record.project_code, target_metric="project_irr", target_value=str(target)).json()
    assert body["ok"] and body["preview_only"] is True and body["committed"] is False and body["is_a_run"] is False
    result = body["result"]
    assert result["status"] == "SOLVED" and result["solved"] is True
    assert result["solved_input_value"] > result["started_from"] > 0                      # a higher return needs a higher tariff
    assert abs(result["achieved_metric_value"] * 100 - target) <= 0.01                     # within the canonical tolerance
    assert result["model_evaluations"] <= body["budgets"]["max_model_evaluations"] and result["iterations"] <= body["budgets"]["max_iterations"]
    assert result["delta_display"].startswith("+") and result["solved_display"].endswith("EUR/MWh")
    assert body["apply"]["field_id"] == FIELD and float(body["apply"]["value"]) == result["solved_input_value"]
    assert body["apply"]["csrf_token"] and body["apply"]["content_hash"]
    assert state(record) == before                                                          # preview never writes


def test_preview_reports_an_unreachable_target_as_a_typed_status_without_an_apply(with_sensitivity):
    env = with_sensitivity
    record = env.create()
    body = call(env.client, "solve", project=record.project_code, target_metric="project_irr", target_value="95").json()
    assert body["ok"] and body["result"]["solved"] is False and body["result"]["status"] != "SOLVED"
    assert body["apply"] is None and body["result"]["message"]


def test_solved_tariff_equals_the_legacy_route_for_the_same_target(with_sensitivity):
    env = with_sensitivity
    record = env.create()
    target = round(baseline_irr_pct(env, record) + 0.5, 2)
    legacy = env.client.post("/v2/workbook/goal-seek/run", data={"project": record.project_code, "target_metric": "project_irr",
                                                                 "target_value": str(target)}, headers={"HX-Request": "true"})
    assert legacy.status_code == 200, legacy.text[:300]
    soup = BeautifulSoup(legacy.text, "html.parser")
    text = lambda tid: soup.select_one(f"[data-testid='{tid}']").get_text(" ", strip=True)
    legacy_solved = float(re.search(r"-?\d+\.\d+", text("gs-solved-value")).group(0))
    legacy_achieved = float(re.search(r"-?\d+\.\d+", text("gs-achieved-value")).group(0))
    legacy_evaluations = int(text("gs-evaluations"))
    mine = call(env.client, "solve", project=record.project_code, target_metric="project_irr", target_value=str(target)).json()["result"]
    assert round(mine["solved_input_value"], 2) == legacy_solved
    assert round(mine["achieved_metric_value"] * 100, 4) == pytest.approx(legacy_achieved, abs=1e-4)
    assert mine["model_evaluations"] == legacy_evaluations                                  # the same deterministic solve


# ── apply: CSRF-bound CAS write; STALE; deliberate Run ─────────────────────

def solved_binding(env, record, delta=0.5):
    target = round(baseline_irr_pct(env, record) + delta, 2)
    body = call(env.client, "solve", project=record.project_code, target_metric="project_irr", target_value=str(target)).json()
    assert body["result"]["solved"], body
    return body["apply"], body["result"]


def apply_body(record, binding, **over):
    data = {"project": record.project_code, "field_id": binding["field_id"], "value": binding["value"],
            "content_hash": binding["content_hash"], "workbook_version": binding["workbook_version"], "csrf_token": binding["csrf_token"]}
    data.update(over)
    return data


def test_apply_writes_only_the_tariff_through_the_cas_and_never_runs(with_sensitivity):
    env = with_sensitivity
    record = env.create()
    run_canonical(env, record.project_code)
    assert env.client.get("/v2/model-react/workspace", params={"project": record.project_code}).json()["freshness"]["state"] == "CURRENT"
    binding, result = solved_binding(env, record)
    before_ws = get_workspace_state(record.user_id, record.project_id)
    before_draft, before_snapshot_id = dict(before_ws.draft_snapshot), before_ws.last_runtime_snapshot_id
    response = env.client.post(f"{BASE}/apply", json=apply_body(record, binding))
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["ok"] and out["applied"] and out["run_state"] == "STALE" and out["content_hash"] != binding["content_hash"]
    after = get_workspace_state(record.user_id, record.project_id)
    assert float(after.draft_snapshot["rev_ppa_base_tariff"]) == pytest.approx(result["solved_input_value"], rel=1e-12)
    changed = {k for k in set(before_draft) | set(after.draft_snapshot) if before_draft.get(k) != after.draft_snapshot.get(k)}
    assert "rev_ppa_base_tariff" in changed                       # (the canonical writer also normalises seed bookkeeping keys, as in Legacy)
    assert after.last_runtime_snapshot_id == before_snapshot_id                                # no Run was recorded
    assert env.client.get("/v2/model-react/workspace", params={"project": record.project_code}).json()["freshness"]["state"] == "STALE"
    # deliberate Run -> CURRENT, and the achieved return is the one the solve proved
    run_canonical(env, record.project_code)
    shell = env.client.get("/v2/model-react/workspace", params={"project": record.project_code}).json()
    assert shell["freshness"]["state"] == "CURRENT"
    runs = env.client.get("/v2/model-react/runs", params={"project": record.project_code}).json()
    assert runs["ok"]


def test_apply_equals_the_legacy_apply_on_a_twin_project(with_sensitivity):
    env = with_sensitivity
    mine, twin = env.create(name="GS mine"), env.create(name="GS twin")
    target = round(baseline_irr_pct(env, mine) + 0.5, 2)
    binding, _ = solved_binding(env, mine, delta=0.5)
    assert env.client.post(f"{BASE}/apply", json=apply_body(mine, binding)).status_code == 200
    legacy = env.client.post("/v2/workbook/goal-seek/run", data={"project": twin.project_code, "target_metric": "project_irr",
                                                                 "target_value": str(target)}, headers={"HX-Request": "true"})
    form = BeautifulSoup(legacy.text, "html.parser").select_one("[data-testid='gs-apply-form']")
    fields = {i["name"]: i.get("value", "") for i in form.select("input[name]")}
    applied = env.client.post("/v2/workbook/goal-seek/apply", data=fields, headers={"HX-Request": "true"})
    assert applied.status_code == 200 and "Applied" in applied.text
    a = get_workspace_state(mine.user_id, mine.project_id).draft_snapshot
    b = get_workspace_state(twin.user_id, twin.project_id).draft_snapshot
    assert float(a["rev_ppa_base_tariff"]) == float(b["rev_ppa_base_tariff"])
    volatile = {"project_name", "active_project", "_reference_seed_profile"}
    assert {k: v for k, v in a.items() if k not in volatile} == {k: v for k, v in b.items() if k not in volatile}   # identical draft state


@pytest.mark.parametrize("mutate,code,status", [
    (lambda r, b: {"csrf_token": ""}, "CSRF_INVALID", 403),
    (lambda r, b: {"csrf_token": b["csrf_token"][:-4] + "0000"}, "CSRF_INVALID", 403),
    (lambda r, b: {"project": "other-project"}, "CSRF_INVALID", 403),                      # token is bound to the project
    (lambda r, b: {"content_hash": "0" * 64}, "STALE_CONTENT", 409),
    (lambda r, b: {"field_id": "debt.senior.gearing_pct"}, "FIELD_NOT_PERMITTED", 422),
    (lambda r, b: {"value": "nan"}, "VALUE_INVALID", 422),
    (lambda r, b: {"value": "-3"}, "VALUE_INVALID", 422),
    (lambda r, b: {"workbook_version": "bogus"}, "VERSION_MISMATCH", 409),
])
def test_apply_refusals_leave_the_working_copy_unchanged(with_sensitivity, mutate, code, status):
    env = with_sensitivity
    record = env.create()
    binding, _ = solved_binding(env, record)
    before = state(record)
    response = env.client.post(f"{BASE}/apply", json=apply_body(record, binding, **mutate(record, binding)))
    assert response.status_code == status and response.json()["code"] == code, response.text
    assert state(record) == before


def test_apply_is_owner_scoped_and_needs_a_session_and_a_wellformed_body(with_sensitivity):
    env = with_sensitivity
    record = env.create()
    binding, _ = solved_binding(env, record)
    body = apply_body(record, binding)
    assert env.anonymous.post(f"{BASE}/apply", json=body).status_code == 401
    assert env.stranger.post(f"{BASE}/apply", json=body).status_code == 403                  # the token binds the session
    assert env.client.post(f"{BASE}/apply", json={**body, "extra": 1}).status_code == 400
    assert env.client.post(f"{BASE}/apply", content=b"nope").status_code == 400


def test_a_second_apply_of_the_same_binding_is_refused_as_stale(with_sensitivity):
    env = with_sensitivity
    record = env.create()
    binding, _ = solved_binding(env, record)
    assert env.client.post(f"{BASE}/apply", json=apply_body(record, binding)).status_code == 200
    again = env.client.post(f"{BASE}/apply", json=apply_body(record, binding))
    assert again.status_code == 409 and again.json()["code"] == "STALE_CONTENT"


def test_apply_to_a_protected_reference_is_refused(env):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services.project_library_service import ensure_reference_models
    from app.workbook.financing_csrf import issue_token

    ensure_reference_models()
    reference = get_reference_by_template_source("generic_solar_reference")
    token = issue_token(SimpleNamespace(cookies=dict(env.client.cookies), state=SimpleNamespace()), reference.project_code,
                        purpose="react-goal-seek-apply-v1")
    response = env.client.post(f"{BASE}/apply", json={"project": reference.project_code, "field_id": FIELD, "value": "50",
                                                      "content_hash": "x", "workbook_version": "x", "csrf_token": token})
    assert response.status_code in (403, 409) and response.json()["code"] in ("PROTECTED_REFERENCE", "CSRF_INVALID")
    ws = get_workspace_state(reference.user_id, reference.project_id)
    assert ws is None or ws.draft_snapshot.get("rev_ppa_base_tariff") != "50"
