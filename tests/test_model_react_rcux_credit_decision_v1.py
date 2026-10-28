"""RC-UX (GAP-R12) — the React Credit decision JSON equals the payload the Legacy ``/v2/credit-decision`` page embeds, and is read-only and isolated."""
from __future__ import annotations

import json
import re
import sqlite3

import pytest

from tests.test_model_decision_workspace_v2 import env  # noqa: F401  (fixture)
from tests.test_model_financing_f2 import run

PATH = "/v2/model-react/analysis/credit-decision"
USER = "decision-user"


@pytest.fixture
def cenv(env, monkeypatch):  # noqa: F811
    from app.v2.credit_decision_router import router as legacy
    from app.v2.react_credit_decision import router
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    env.client.app.include_router(legacy, prefix="/v2")
    env.client.app.include_router(router, prefix="/v2")
    return env


def db_dump():
    from app.persistence import db
    with sqlite3.connect(db.DB_PATH) as conn:
        return "\n".join(conn.iterdump())


def legacy_payload(env, record, *runs):
    page = env.client.get("/v2/credit-decision", params=[("project", record.project_code)] + [("run", r) for r in runs])
    match = re.search(r'<script type="application/json" data-cd-payload>(.*?)</script>', page.text, re.S)
    assert match, page.text[:300]
    return json.loads(match.group(1))


def test_router_is_mounted_before_the_project_catch_all():
    from app.v2.router import router
    paths = [getattr(r, "path", "") for r in router.routes]
    assert paths.count("/model-react/analysis/credit-decision") == 1
    assert paths.index("/model-react/analysis/credit-decision") < paths.index("/model-react/{project_code}")


def test_flag_and_session_are_required(env, monkeypatch):  # noqa: F811
    from app.v2.react_credit_decision import router
    env.client.app.include_router(router, prefix="/v2")
    assert env.client.get(PATH, params={"project": "x"}).json()["code"] == "REACT_POC_DISABLED"
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    from fastapi.testclient import TestClient
    assert TestClient(env.client.app).get(PATH, params={"project": "x"}).status_code == 401


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_the_json_equals_the_legacy_embedded_payload_for_every_vertical_and_writes_nothing(cenv, kind):
    record = cenv.create(kind)
    run(cenv, record)
    before = db_dump()
    body = cenv.client.get(PATH, params={"project": record.project_code}).json()
    assert db_dump() == before
    assert body["ok"] and body["project"]["code"] == record.project_code and body["freshness"] in ("CURRENT", "STALE")
    assert body["data"] == legacy_payload(cenv, record)                              # one authority, two presentations
    assert body["requested"] and body["history_rows"][0]["selected"] is True
    assert db_dump() == before


def test_two_runs_compare_with_the_first_as_reference_and_a_foreign_run_fails_closed(cenv):
    record = cenv.create("solar")
    run(cenv, record)
    run(cenv, record)
    from app.persistence.run_history_repository import get_run_history
    ids = [e.history_id for e in get_run_history(USER, record.project_id)]
    assert len(ids) >= 2
    body = cenv.client.get(PATH, params=[("project", record.project_code), ("run", ids[0]), ("run", ids[1])]).json()
    assert body["ok"] and [r["identity"]["history_id"] for r in body["data"]["runs"]] == [ids[0], ids[1]]
    assert body["data"] == legacy_payload(cenv, record, ids[0], ids[1])
    missing = cenv.client.get(PATH, params=[("project", record.project_code), ("run", "not-a-run")])
    assert missing.status_code == 404 and missing.json()["code"] == "RUN_NOT_FOUND" and "data" not in missing.json()
    too_many = cenv.client.get(PATH, params=[("project", record.project_code)] + [("run", f"r{i}") for i in range(4)])
    assert too_many.status_code == 422 and too_many.json()["code"] == "TOO_MANY_RUNS"


def test_a_project_without_a_run_has_no_data_and_no_invented_evidence(cenv):
    record = cenv.create("solar")
    body = cenv.client.get(PATH, params={"project": record.project_code}).json()
    assert body["ok"] and body["data"] is None and body["history_rows"] == [] and body["requested"] == []


def test_stranger_unknown_and_template_are_refused(cenv):
    record = cenv.create("solar")
    run(cenv, record)
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    stranger = TestClient(cenv.client.app)
    stranger.cookies.set(COOKIE_NAME, create_session_token(user_id="other-decision-user", username="admin"))
    assert stranger.get(PATH, params={"project": record.project_code}).status_code == 404
    assert cenv.client.get(PATH, params={"project": "no-such-project"}).status_code == 404
    assert cenv.client.get(PATH).status_code == 400
