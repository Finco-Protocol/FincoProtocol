"""PR #245 Correction A — F3 × grid batch Save: controlled rejection, zero mutation.

The grid route is a thin layer over the C0 canonical batch writer.  With ACTIVE F3 financing a
competing financing field must be rejected by the existing F3 gate (inside the BEGIN EXCLUSIVE
transaction) and surface as a controlled 409/422 — never an unhandled 500 — with no financial
mutation, no partial batch, an unchanged CAS hash and an untouched Last Run / Run History.
"""
from __future__ import annotations

import pytest

from app.auth import generate_csrf_token
from app.workbook.registry import WORKBOOK
from tests.test_model_ai_import_f3_integration import (  # noqa: F401  (env is a pytest fixture)
    F3_FIELD, F3_FORBIDDEN, _active, _evidence, _hash, _ws, env,
)
from tests.test_model_financing_f2 import run


@pytest.fixture
def gclient(env):
    """Same DB/session as ``env``, with the grid router mounted (raise_server_exceptions=True: a 500 fails the test)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    from app.v2.grid_router import router as grid_router
    app = FastAPI()
    app.include_router(grid_router, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id="decision-user", username="admin"))
        yield client


def _post(client, project, cells, **extra):
    body = {"project": project.project_code, "csrf_token": generate_csrf_token(),
            "workbook_version": WORKBOOK.version, "content_hash": _hash(project),
            "scenario_id": _ws(project).active_scenario_id,
            "cells": [{"field_id": f, "value": v} for f, v in cells]}
    body.update(extra)
    return client.post("/v2/workbook/grid/save", json=body)


def test_active_f3_competing_debt_field_is_a_controlled_409_with_zero_mutation(env, gclient):
    project = _active(env)
    run(env, project)                                       # a real committed Run (asserts its own success)
    before = _evidence(project)
    assert before[5], "a committed Last Run must exist for this proof"

    res = _post(gclient, project, [("revenue.ppa.index", "2"), ("capex.C.grid_connection", "1"), (F3_FORBIDDEN, "6")])
    assert res.status_code == 409, res.text
    body = res.json()
    assert body["ok"] is False and body["code"] == "F3_COMPETING_FINANCING_EDITOR_REJECTED"
    assert "nothing was saved" in body["message"]
    assert _evidence(project) == before, "no partial batch, same CAS hash, same Last Run and Run History"


def test_active_f3_collection_field_is_rejected_without_mutation(env, gclient):
    project = _active(env)
    before = _evidence(project)
    res = _post(gclient, project, [("revenue.ppa.index", "2"), (F3_FIELD, "{}")])
    assert res.status_code in (409, 422) and res.json()["ok"] is False
    assert _evidence(project) == before


def test_active_f3_unrelated_batch_still_saves_through_the_grid_route(env, gclient):
    project = _active(env)
    before_hash = _hash(project)
    res = _post(gclient, project, [("revenue.ppa.index", "3")])
    assert res.status_code == 200, res.text
    assert res.json()["ok"] and res.json()["content_hash"] != before_hash
    assert _hash(project) == res.json()["content_hash"]


def test_inactive_f3_competing_field_is_not_blocked_by_f3(env, gclient):
    project = _active(env, active=False)
    res = _post(gclient, project, [(F3_FORBIDDEN, "6")])
    assert res.status_code != 500
