"""Gated, stateless review: canonical owner/context checks, no Save/Run sidecar."""
import copy
import json
import time

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence import db
    from app.persistence.projects_repository import save_project
    from app.persistence.workspace_repository import save_workspace_state
    from app.persistence.scenarios_repository import get_or_create_base_case_scenario
    from app.v2.bess_candidate_router import router
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "battery-review.db"))
    db.init_db()
    snapshot = dict(project_type="Storage", project_origin="user_created", template_source="generic_storage_reference",
                    active_project="battery-candidate", project_name="Battery candidate")
    record = save_project(user_id="battery-owner", project_code="battery-candidate", project_name="Battery candidate",
        source_project_template="generic_storage_reference", project_type="Storage", project_origin="user_created",
        template_source="generic_storage_reference", baseline_snapshot=snapshot, is_readonly=False,
        is_protected=False, project_role="working_copy")
    save_workspace_state(user_id="battery-owner", project_id=record.project_id, project_code=record.project_code,
        draft_snapshot=snapshot, saved_snapshot=snapshot, last_runtime_snapshot={}, last_runtime_summary={}, governance_state={})
    get_or_create_base_case_scenario("battery-owner", record.project_id, record.project_code, record.project_name,
                                   "Storage", record.template_source, snapshot, {}, {})
    app = FastAPI()
    app.include_router(router, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id="battery-owner", username="battery-owner"))
        yield SimpleNamespace(client=client, record=record)


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr("app.v2.bess_candidate_router.CANDIDATE_UI_ENABLED", True)


def state(env):
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.scenarios_repository import list_scenarios
    from app.persistence.projects_repository import get_project_by_id
    scenarios = [tuple((key, copy.deepcopy(getattr(row, key))) for key in row.__slots__)
                 for row in list_scenarios("battery-owner", env.record.project_id)]
    return copy.deepcopy((get_project_by_id(env.record.project_id),
        get_workspace_state("battery-owner", env.record.project_id), get_run_history("battery-owner", env.record.project_id),
        scenarios))


def data(env):
    from bs4 import BeautifulSoup
    from domain.bess.synthetic import example
    response = env.client.get("/v2/workbook/bess/candidate", params={"project": env.record.project_code})
    assert response.status_code == 200, response.text
    form = BeautifulSoup(response.text, "html.parser").select_one('[data-testid="bess-review-form"]')
    return {key: form.select_one('input[name="' + key + '"]')["value"] for key in ("project", "csrf_token", "content_hash")} | {"configuration": json.dumps(example())}


def test_production_ui_is_closed_and_does_not_read_storage_inputs(env, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Closed UI must stop before any identity/materialization")
    monkeypatch.setattr("app.v2.bess_candidate_router._identity", forbidden)
    before = state(env)
    response = env.client.get("/v2/workbook/bess/candidate", params={"project": env.record.project_code})
    assert response.status_code == 404
    assert env.client.post("/v2/workbook/bess/candidate/validate", data={}).status_code == 404
    assert state(env) == before


def test_review_is_real_physics_but_never_saved_or_current_financial_evidence(env, enabled, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Candidate may not call a finance engine or writer")
    monkeypatch.setattr("app.services.production_financial_authority.run_clean_production", forbidden)
    monkeypatch.setattr("app.runtime.model_execution.run_model_process", forbidden)
    before = state(env)
    response = env.client.post("/v2/workbook/bess/candidate/validate", data=data(env))
    assert response.status_code == 200, response.text
    assert 'data-testid="bess-operating-evidence"' in response.text
    assert "0.05622000" in response.text
    assert "Financial Run unavailable" in response.text
    assert 'name="action" value="save"' not in response.text
    assert 'data-testid="overview-status-current"' not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert state(env) == before


@pytest.mark.parametrize("fault", ["missing", "forged", "expired", "wrong-owner", "protected", "stale-cas", "invalid-soc", "oversize", "wrong-sector", "missing-price"])
def test_adversarial_review_never_mutates_working_scenarios_or_history(env, enabled, monkeypatch, fault):
    from app.persistence.db import get_connection
    request = data(env)
    status = 422
    if fault in ("missing", "forged", "expired"):
        status = 403
        if fault == "missing": request["csrf_token"] = ""
        elif fault == "forged": request["csrf_token"] += "forged"
        else:
            from itsdangerous import TimestampSigner
            from app.auth import generate_csrf_token
            with monkeypatch.context() as patch:
                patch.setattr(TimestampSigner, "get_timestamp", lambda self: int(time.time()) - 86401)
                request["csrf_token"] = generate_csrf_token()
    elif fault == "wrong-owner":
        from app.auth import COOKIE_NAME, create_session_token
        env.client.cookies.set(COOKIE_NAME, create_session_token(user_id="battery-other-owner", username="other"))
        status = 404
    elif fault in ("protected", "wrong-sector"):
        conn = get_connection()
        try:
            if fault == "protected": conn.execute("UPDATE projects SET is_protected=1, is_readonly=1, project_role='reference' WHERE project_id=?", (env.record.project_id,))
            else: conn.execute("UPDATE projects SET project_type='Solar' WHERE project_id=?", (env.record.project_id,))
            conn.commit()
        finally: conn.close()
        status = 409
    elif fault == "stale-cas": request["content_hash"] = "not-the-working-identity"; status = 409
    elif fault == "oversize": request["configuration"] = "x" * 2_200_000; status = 413
    else:
        raw = json.loads(request["configuration"])
        if fault == "invalid-soc": raw["dispatch"][0]["discharge_mw"] = .1
        else: del raw["dispatch"][0]["buy_price_eur_mwh"]
        request["configuration"] = json.dumps(raw)
    before = state(env)
    response = env.client.post("/v2/workbook/bess/candidate/validate", data=request)
    assert response.status_code == status, response.text
    assert state(env) == before


@pytest.mark.parametrize("mutation", ["edit", "scenario"])
def test_concurrent_edit_or_scenario_selection_discards_candidate_response(env, enabled, monkeypatch, mutation):
    from app.persistence.db import get_connection
    from app.v2 import bess_candidate_router as route
    original = route.evaluate
    from app.persistence.scenarios_repository import duplicate_scenario, list_scenarios, select_scenario
    child = duplicate_scenario("battery-owner", list_scenarios("battery-owner", env.record.project_id)[0].scenario_id)
    request = data(env)
    changed = []
    def interleave(configuration):
        result = original(configuration)
        if mutation == "scenario":
            assert select_scenario("battery-owner", env.record.project_id, child.scenario_id)
        else:
            conn = get_connection()
            try:
                snap = state(env)[1].draft_snapshot | {"project_name": "Concurrent edit"}
                conn.execute("UPDATE workspace_states SET draft_snapshot_json=? WHERE project_id=?", (json.dumps(snap), env.record.project_id))
                conn.commit()
            finally: conn.close()
        changed.append(state(env))
        return result
    monkeypatch.setattr(route, "evaluate", interleave)
    response = env.client.post("/v2/workbook/bess/candidate/validate", data=request)
    assert response.status_code == 409
    assert state(env) == changed[0]
