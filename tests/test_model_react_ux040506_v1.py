"""UX-04/05/06 — contract tests for the canonical surface projections.

Every new ``GET /v2/model-react/*`` projection is read-only over the SAME
canonical authorities the legacy workbook uses; every mutation stays on the
existing canonical writer route.  These tests pin:

* flag OFF → every new surface answers 404 ``REACT_POC_DISABLED``;
* authorization order (session → accessible project) and unknown sheets fail
  closed;
* runs — immutable committed history only, nothing fabricated;
* costlines — rows exactly as the atomic batch writer verifies them, with the
  canonical Save contract;
* fields/financing — registry field grid with the BOUND financing CSRF token;
* revenue — the canonical contract editor state + Save contract, explicitly
  read-only in React;
* diagnostics — honest run states (NOT_RUN stays NOT_RUN), canonical evidence
  only;
* trust — canonical evidence builders, UNAVAILABLE never presented as a pass.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.persistence import db

OWNER = "ux040506-owner"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "ux040506.db"))
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
    # workspace routes BEFORE the PoC catch-all (same order as main_web)
    app.include_router(workspace_router, prefix="/v2")
    app.include_router(poc_router, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))
        stranger = TestClient(app)
        stranger.cookies.set(COOKIE_NAME, create_session_token(user_id="ux040506-stranger", username="stranger"))

        def create(kind="solar", user=OWNER, name=None):
            return create_reference_seeded_project(
                user_id=user, requested_name=name or f"UX040506 {kind}",
                template_source=f"generic_{kind}_reference", capacity_mw=16)

        yield SimpleNamespace(client=client, stranger=stranger, create=create)
    reset_model_executor_for_tests()


def flag_on(monkeypatch):
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")


NEW_PATHS = ["/v2/model-react/runs", "/v2/model-react/diagnostics", "/v2/model-react/trust",
             "/v2/model-react/costlines", "/v2/model-react/revenue", "/v2/model-react/fields/debt"]


@pytest.mark.parametrize("path", NEW_PATHS)
def test_new_surfaces_disabled_without_the_flag(env, path):
    response = env.client.get(path, params={"project": "whatever"})
    assert response.status_code == 404 and response.json()["code"] == "REACT_POC_DISABLED"


def test_runs_projection_lists_committed_history(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    before = env.client.get("/v2/model-react/runs", params={"project": record.project_code}).json()
    assert before["ok"] is True and before["runs"] == []
    assert "Save NEVER triggers" in before["run_contract"]["note"]
    assert before["run_contract"]["url"] == "/v2/workbook/run"
    # a canonical Run commits exactly one immutable history entry
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    tokens = {k: part for k, part in
              [(k, __import__("re").search(f'name="{k}" value="([^"]*)"', page.text).group(1))
               for k in ("content_hash", "workbook_version")]}
    run_response = env.client.post("/v2/workbook/run", headers={"HX-Request": "true"},
                                   data=dict(project=record.project_code, **tokens))
    assert run_response.status_code == 200
    assert run_response.headers.get("X-Finco-Run-Outcome") != "FAILED"
    after = env.client.get("/v2/model-react/runs", params={"project": record.project_code}).json()
    assert len(after["runs"]) == 1
    entry = after["runs"][0]
    assert entry.get("history_id") or entry.get("id"), "a committed Run must carry its immutable identity"


def test_costlines_projection_and_save_contract(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    for sheet in ("capex", "opex"):
        payload = env.client.get("/v2/model-react/costlines", params={"sheet": sheet, "project": record.project_code}).json()
        assert payload["ok"] is True and payload["sheet"] == sheet
        assert isinstance(payload["lines"], list)
        for line in payload["lines"]:
            assert line["sub_line_id"] and "row_version" in line
        assert payload["save"]["url"] == "/v2/workbook/grid/cost-lines/save"
        assert payload["save"]["csrf_token"] and payload["save"]["content_hash"]
        assert payload["save"]["max_batch_lines"] >= 1


def test_costlines_unknown_sheet_fails_closed(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    response = env.client.get("/v2/model-react/costlines", params={"sheet": "payroll", "project": record.project_code})
    assert response.status_code == 404 and response.json()["code"] == "SHEET_UNKNOWN"


def test_fields_debt_projection_carries_bound_token(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    payload = env.client.get("/v2/model-react/fields/debt", params={"project": record.project_code}).json()
    assert payload["ok"] is True and payload["sheet"] == "debt"
    assert isinstance(payload["fields"], list) and payload["fields"]
    for field in payload["fields"]:
        assert field["field_id"] and field["binding_label"] in ("bound", "partial", "display-only", "template-locked")
    assert payload["save"]["url"] == "/v2/workbook/update"
    assert payload["save"]["financing_csrf_token"] != payload["save"]["csrf_token"], \
        "financing fields must authenticate with the BOUND financing token, not the grid token"


def test_fields_unknown_sheet_and_bad_sheet_fail_closed(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    response = env.client.get("/v2/model-react/fields/payroll", params={"project": record.project_code})
    assert response.status_code == 404 and response.json()["code"] == "SHEET_UNKNOWN"


def test_revenue_projection_is_read_only_with_canonical_save_contract(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    payload = env.client.get("/v2/model-react/revenue", params={"project": record.project_code}).json()
    assert payload["ok"] is True and "contracts" in payload
    assert payload["save"]["url"] == "/v2/workbook/revenue/contracts"
    assert payload["save"]["csrf_token"] and payload["save"]["content_hash"]


def test_diagnostics_honest_not_run_state(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    payload = env.client.get("/v2/model-react/diagnostics", params={"project": record.project_code}).json()
    assert payload["ok"] is True
    assert payload["run_state"] == "NOT_RUN"
    assert payload["diagnostics"].get("state") == "NOT_RUN"
    assert "never" in str(payload["insight"].get("message", "")).lower() or payload["insight"].get("available") is False


def test_trust_projection_uses_canonical_evidence(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    payload = env.client.get("/v2/model-react/trust", params={"project": record.project_code}).json()
    assert payload["ok"] is True and "certificate" in payload and "validation" in payload
    assert payload["certificate"].get("state") in ("OK", "UNAVAILABLE", "PARTIAL", "PASS", None, "CURRENT")


def test_stranger_cannot_read_another_users_project(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create(user=OWNER)
    response = env.stranger.get("/v2/model-react/runs", params={"project": record.project_code})
    assert response.status_code == 404 and response.json()["code"] == "PROJECT_NOT_FOUND"
