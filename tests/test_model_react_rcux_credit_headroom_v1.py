"""RC-UX (GAP-R12) — the React covenant-headroom JSON equals the Legacy Credit V5 JSON for the same committed Runs and hypothetical thresholds,
never runs the model, never persists a threshold, and fails closed."""
from __future__ import annotations

import sqlite3

import pytest

from tests.test_model_decision_workspace_v2 import env  # noqa: F401  (fixture)
from tests.test_model_financing_f2 import run

PATH = "/v2/model-react/analysis/credit-headroom"


@pytest.fixture
def henv(env, monkeypatch):  # noqa: F811
    from app.v2.credit_v5_router import router as legacy
    from app.v2.react_credit_headroom import router
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    env.client.app.include_router(legacy, prefix="/v2")
    env.client.app.include_router(router, prefix="/v2")
    return env


def db_dump():
    from app.persistence import db
    with sqlite3.connect(db.DB_PATH) as conn:
        return "\n".join(conn.iterdump())


def test_router_is_mounted_before_the_project_catch_all():
    from app.v2.router import router
    paths = [getattr(r, "path", "") for r in router.routes]
    assert paths.count("/model-react/analysis/credit-headroom") == 1 and paths.index("/model-react/analysis/credit-headroom") < paths.index("/model-react/{project_code}")


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_the_json_equals_the_legacy_v5_json_and_never_runs_or_writes(henv, monkeypatch, kind):
    record = henv.create(kind)
    run(henv, record)

    def forbidden(*a, **k):
        pytest.fail("Credit headroom must never execute a financial Run")
    monkeypatch.setattr("app.services.production_financial_authority.run_clean_production", forbidden)
    monkeypatch.setattr("app.api.project_runner.run_project", forbidden)
    params = {"project": record.project_code, "min_dscr": "1.25", "min_llcr": "1.4", "max_gearing": "0.8"}
    before = db_dump()
    body = henv.client.get(PATH, params=params).json()
    assert db_dump() == before                                                         # thresholds are hypothetical: nothing is persisted
    legacy = henv.client.get("/v2/credit-decision/v5", params={**params, "format": "json"}).json()
    assert body["ok"] and body["state"] == legacy["state"] == "AVAILABLE"
    assert body["data"] == legacy["data"]
    assert body["thresholds"]["min_dscr"] == 1.25 and body["thresholds"]["min_equity_keur"] is None


def test_no_run_unknown_run_invalid_thresholds_and_isolation(henv):
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    record = henv.create("solar")
    empty = henv.client.get(PATH, params={"project": record.project_code}).json()
    assert empty["ok"] and empty["state"] == "NO_COMMITTED_RUN" and empty["data"] is None
    run(henv, record)
    assert henv.client.get(PATH, params={"project": record.project_code, "run": "nope"}).json()["code"] == "RUN_NOT_FOUND"
    for value in ("nan", "inf", "-1", "0", "x"):
        assert henv.client.get(PATH, params={"project": record.project_code, "min_dscr": value}).status_code == 422
    over = henv.client.get(PATH, params={"project": record.project_code, "max_gearing": "1.5"})
    assert over.status_code == 422 and "fraction" in over.json()["message"]
    assert henv.client.get(PATH, params=[("project", record.project_code), ("min_dscr", "1.2"), ("min_dscr", "1.3")]).status_code == 422
    stranger = TestClient(henv.client.app)
    stranger.cookies.set(COOKIE_NAME, create_session_token(user_id="other-decision-user", username="admin"))
    assert stranger.get(PATH, params={"project": record.project_code}).status_code == 404
    assert TestClient(henv.client.app).get(PATH, params={"project": record.project_code}).status_code == 401
    assert henv.client.get(PATH).status_code == 400
