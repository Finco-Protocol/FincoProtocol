"""UX-07 — contract tests for scenario management/compare projections and the
revenue editor surface.  All mutations stay on the canonical form routes;
the compare projection is assumption-level and never computes KPIs."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.persistence import db

OWNER = "ux07-owner"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "ux07.db"))
    db.init_db()
    from app.auth import COOKIE_NAME, create_session_token
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.services.reference_seed_service import create_reference_seeded_project
    from fastapi import FastAPI
    from app.v2.grid_router import router as grid_router
    from app.v2.react_poc_router import router as poc_router
    from app.v2.react_workspace_router import router as workspace_router
    from app.v2.router import router as v2_router

    monkeypatch.delenv("FINCO_MODEL_REACT_V1", raising=False)
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    app.include_router(grid_router, prefix="/v2")
    app.include_router(workspace_router, prefix="/v2")
    app.include_router(poc_router, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))

        def create(kind="solar", user=OWNER, name=None):
            return create_reference_seeded_project(
                user_id=user, requested_name=name or f"UX07 {kind}",
                template_source=f"generic_{kind}_reference", capacity_mw=16)

        yield SimpleNamespace(client=client, create=create)
    reset_model_executor_for_tests()


def flag_on(monkeypatch):
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")


def test_scenarios_projection_lists_base_case_and_mutations(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    payload = env.client.get("/v2/model-react/scenarios", params={"project": record.project_code}).json()
    assert payload["ok"] is True and isinstance(payload["scenarios"], list)
    assert payload["mutations"]["create"]["url"] == "/v2/workbook/scenarios/create"
    assert "NEVER" in payload["mutations"]["note"]


def test_scenario_compare_reports_assumption_differences_not_kpis(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    # create a scenario through the canonical form route, then override one field
    created = env.client.post("/v2/workbook/scenarios/create",
                              data={"project": record.project_code, "scenario_name": "Downside"})
    assert created.status_code in (200, 303)
    scenarios = env.client.get("/v2/model-react/scenarios", params={"project": record.project_code}).json()
    child = next((s for s in scenarios["scenarios"] if not s["is_base_case"]), None)
    assert child is not None, "the canonical create must be visible in the projection"
    compare = env.client.get("/v2/model-react/scenario-compare",
                             params={"project": record.project_code, "scenario_id": child["scenario_id"]}).json()
    assert compare["ok"] is True
    assert compare["scenario"]["label"] == "Downside"
    assert isinstance(compare["differences"], list)
    assert compare["kpi_compare"]["available"] is False, "KPI deltas are not computed in the browser"


def test_scenario_compare_unknown_scenario_fails_closed(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    response = env.client.get("/v2/model-react/scenario-compare",
                              params={"project": record.project_code, "scenario_id": "no-such"})
    assert response.status_code == 404 and response.json()["code"] == "SCENARIO_NOT_FOUND"


def test_revenue_projection_exposes_the_editor_payload(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    payload = env.client.get("/v2/model-react/revenue", params={"project": record.project_code}).json()
    assert payload["ok"] is True
    for key in ("active", "raw", "scope", "technology", "rows", "products"):
        assert key in payload["contracts"], f"the editor payload must carry {key}"
    assert payload["save"]["url"] == "/v2/workbook/revenue/contracts"
    assert payload["save"]["csrf_token"]


def test_surfaces_disabled_without_the_flag(env):
    for path in ("/v2/model-react/scenarios", "/v2/model-react/scenario-compare"):
        response = env.client.get(path, params={"project": "x"})
        assert response.status_code == 404 and response.json()["code"] == "REACT_POC_DISABLED"
