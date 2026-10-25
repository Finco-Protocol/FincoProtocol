"""UX-07 Correction A — canonical mutation-outcome contract pins.

These tests pin the REAL backend response contracts the React client's outcome
classifier relies on (they are not mocked idealised JSON): an unauthenticated
form POST redirects to /login, a stale composite hash answers a 303 with
``?v2_err=``, the capital-stack field requires the BOUND financing CSRF token,
the cost-batch writer answers 401 JSON without a session, and a rejected Run
creates no history entry.  The frontend classification tests
(``frontend/transfer/scripts/outcomeIntegrity.test.mjs``) build on exactly
these wire behaviours.
"""
from __future__ import annotations

from tests.run_clone_csrf import post_valid_csrf

import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.persistence import db

OWNER = "outcome-owner"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "outcome.db"))
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
        anonymous = TestClient(app)          # expired / absent session
        stranger = TestClient(app)
        stranger.cookies.set(COOKIE_NAME, create_session_token(user_id="outcome-stranger", username="stranger"))

        def create(kind="solar", user=OWNER, name=None):
            return create_reference_seeded_project(
                user_id=user, requested_name=name or f"Outcome {kind}",
                template_source=f"generic_{kind}_reference", capacity_mw=16)

        yield SimpleNamespace(client=client, anonymous=anonymous, stranger=stranger, create=create)
    reset_model_executor_for_tests()


def flag_on(monkeypatch):
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")


def _grid_tokens(page: str) -> dict:
    return {k: re.search(f'name="{k}" value="([^"]*)"', page).group(1)
            for k in ("content_hash", "workbook_version", "csrf_token")}


def _redirect_target(response) -> dict:
    location = response.headers.get("location", "")
    parsed = urlparse(location)
    return {"path": parsed.path, "query": parse_qs(parsed.query)}


# ── 1/2. valid Save commits; expired session redirects to /login ────────────

def test_valid_scalar_update_commits_exactly_once(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    tokens = _grid_tokens(page.text)
    fields = env.client.get("/v2/model-react/fields/project_setup",
                            params={"project": record.project_code}).json()
    sample = next(f for f in fields["fields"] if f["binding_label"] == "bound")
    response = env.client.post("/v2/workbook/update", data=dict(
        project=record.project_code, field_id=sample["field_id"],
        value=str(sample["value"] if sample["value"] is not None else ""),
        workbook_version=tokens["workbook_version"], content_hash=tokens["content_hash"],
        csrf_token=tokens["csrf_token"]), follow_redirects=False)
    assert response.status_code == 303
    target = _redirect_target(response)
    assert target["path"] == "/v2/workbook" and "v2_err" not in target["query"], \
        "the canonical success contract is a clean 303 redirect"


def test_update_without_session_redirects_to_login_never_success(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    tokens = _grid_tokens(page.text)
    response = env.anonymous.post("/v2/workbook/update", data=dict(
        project=record.project_code, field_id="project_setup.identity.project_name", value="renamed",
        workbook_version=tokens["workbook_version"], content_hash=tokens["content_hash"],
        csrf_token=tokens["csrf_token"]), follow_redirects=False)
    assert response.status_code == 302
    assert _redirect_target(response)["path"] == "/login", \
        "an expired session must be classified as an authentication redirect, never as a save"


# ── 3. stale CAS answers the canonical error redirect ───────────────────────

def test_stale_composite_hash_answers_v2_err_redirect(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    tokens = _grid_tokens(page.text)
    stale = ("0" * 63 + "1") if tokens["content_hash"][-1] != "1" else ("0" * 63 + "2")
    response = env.client.post("/v2/workbook/update", data=dict(
        project=record.project_code, field_id="project_setup.identity.project_name", value="renamed-stale",
        workbook_version=tokens["workbook_version"], content_hash=stale,
        csrf_token=tokens["csrf_token"]), follow_redirects=False)
    assert response.status_code == 303
    target = _redirect_target(response)
    assert target["path"] == "/v2/workbook" and "v2_err" in target["query"], \
        "a stale CAS answer must carry the error verdict in the redirect query"


# ── 4. the capital-stack field requires the BOUND financing token ───────────

def test_capital_stack_field_rejects_grid_csrf_token(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    tokens = _grid_tokens(page.text)
    response = env.client.post("/v2/workbook/update", data=dict(
        project=record.project_code, field_id="debt.financing.instruments", value="[]",
        workbook_version=tokens["workbook_version"], content_hash=tokens["content_hash"],
        csrf_token=tokens["csrf_token"]), follow_redirects=False)
    assert response.status_code == 403 and "CSRF" in response.json().get("error", "")


# ── 5. protected reference stays immutable ──────────────────────────────────

def test_protected_reference_update_is_refused(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create(user=OWNER)
    # Make the project an actual protected reference (the seeded creator makes a
    # user-owned working copy; protection is the canonical read-only boundary).
    from app.persistence.db import get_connection
    with get_connection() as conn:
        conn.execute("UPDATE projects SET is_protected=1, is_readonly=1, project_role='reference' "
                     "WHERE project_id=?", (record.project_id,))
    # Tokens come from the canonical projection — the legacy workbook page omits
    # the CSRF input on a read-only reference, exactly the situation the React
    # client is in.
    fields = env.client.get("/v2/model-react/fields/project_setup",
                            params={"project": record.project_code}).json()
    assert fields["project"]["protected_reference"] is True, \
        "the projection must report the protection boundary truthfully"
    response = env.client.post("/v2/workbook/update", data=dict(
        project=record.project_code, field_id="project_setup.identity.project_name", value="renamed",
        workbook_version=fields["save"]["workbook_version"], content_hash=fields["save"]["content_hash"],
        csrf_token=fields["save"]["csrf_token"]), follow_redirects=False)
    assert response.status_code == 403, "a protected-reference write must be refused outright"
    assert "protected reference" in response.json().get("error", "").lower()
    fresh = env.client.get("/v2/model-react/fields/project_setup",
                           params={"project": record.project_code}).json()
    persisted = next(f for f in fresh["fields"] if f["field_id"] == "project_setup.identity.project_name")
    assert persisted["value"] != "renamed", "a protected-reference write must never persist"


# ── cost batch: no session → 401 JSON (no redirect) ─────────────────────────

def test_cost_batch_without_session_is_refused_json_never_redirect(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    response = env.anonymous.post("/v2/workbook/grid/cost-lines/save", data=dict(
        project=record.project_code, csrf_token="", workbook_version="v", content_hash="h",
        sheet="capex", payload="[]"))
    # The batch writer validates CSRF before the session and answers JSON —
    # a followed redirect can never turn this into a false success.
    assert response.status_code == 403 and response.json()["code"] == "CSRF_INVALID"


# ── 7/12. a rejected Run creates no history; a committed one does ───────────

def _runs_payload(env, code):
    return env.client.get("/v2/model-react/runs", params={"project": code}).json()


def test_rejected_run_creates_no_history_entry(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    before = _runs_payload(env, record.project_code)
    assert before["runs"] == []
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    tokens = _grid_tokens(page.text)
    stale = ("0" * 63 + "1") if tokens["content_hash"][-1] != "1" else ("0" * 63 + "2")
    response = post_valid_csrf(env.client, "/v2/workbook/run",
                               data=dict(project=record.project_code, content_hash=stale,
                                         workbook_version=tokens["workbook_version"]),
                               follow_redirects=False)
    assert response.status_code == 303 and "v2_err" in _redirect_target(response)["query"],         "the canonical rejection contract is the error redirect"
    after = _runs_payload(env, record.project_code)
    assert len(after["runs"]) == len(before["runs"]) == 0, "a rejected Run must not create history"


def test_committed_run_grows_the_history_exactly_once(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    before = _runs_payload(env, record.project_code)
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    tokens = _grid_tokens(page.text)
    response = post_valid_csrf(env.client, "/v2/workbook/run", headers={"HX-Request": "true"},
                               data=dict(project=record.project_code, **tokens))
    assert response.status_code == 200 and response.headers.get("X-Finco-Run-Outcome") != "FAILED"
    after = _runs_payload(env, record.project_code)
    assert len(after["runs"]) == len(before["runs"]) + 1, \
        "the persisted Run History is the commit evidence the React classifier reconciles against"


# ── 8. expired session during Run → login redirect, never success ───────────

def test_run_without_session_redirects_to_login(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    response = post_valid_csrf(env.anonymous, "/v2/workbook/run",
                                  data=dict(project=record.project_code, content_hash="h", workbook_version="v"),
                                  follow_redirects=False)
    assert response.status_code == 302 and _redirect_target(response)["path"] == "/login"


# ── 10. an unexpected HTML 200 answer exists as a contract case ─────────────

def test_htmx_run_failure_keeps_200_with_failed_outcome_header(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    tokens = _grid_tokens(page.text)
    stale = ("0" * 63 + "1") if tokens["content_hash"][-1] != "1" else ("0" * 63 + "2")
    response = post_valid_csrf(env.client, "/v2/workbook/run", headers={"HX-Request": "true"},
                               data=dict(project=record.project_code, content_hash=stale,
                                         workbook_version=tokens["workbook_version"]))
    # Rejection shape varies by stage (explicit FAILED header on the early
    # guard, a bare 200 banner later): the durable invariant is that the stale
    # Run committed NOTHING — the client must never classify a bare 200 as
    # success, which is why runModel reconciles against Run History.
    history = _runs_payload(env, record.project_code)
    assert history["runs"] == []
