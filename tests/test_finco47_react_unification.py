"""FINCO47 React-only unification, unified shell navigation, Save->Run guard, cutover redirects, GET purity, and CSRF."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def test_react_host_page_has_no_legacy_workbook_link():
    html = (ROOT / "app" / "templates" / "v2" / "react_poc.html").read_text(encoding="utf-8")
    assert "open the legacy workbook" not in html.lower()
    assert "data-legacy-url" not in html
    assert "/v2/workbook?" not in html


def test_react_shell_and_app_expose_unified_routes():
    shell = (ROOT / "frontend" / "src" / "finco" / "_shared" / "FincoShell.tsx").read_text(encoding="utf-8")
    for route in ("/v2/model-react/", "/v2/model-react/#new-project", "/v2/model-react/#compare-projects",
                  "/v2/model-react/#guide", "/v2/model-react/#platform", "/v2/model-react/#account"):
        assert route in shell, f"missing unified shell route {route}"
    app_tsx = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    for comp in ("GuideMethodologyView", "PlatformApiVerifyView", "AccountSessionView"):
        assert comp in app_tsx


def test_save_to_run_race_guard_blocks_run_while_identity_refreshing():
    ws = (ROOT / "frontend" / "src" / "app" / "WorkspaceView.tsx").read_text(encoding="utf-8")
    wb = (ROOT / "frontend" / "src" / "app" / "workflow" / "WorkflowBar.tsx").read_text(encoding="utf-8")
    assert 'useReportPending("grid-save", busy)' in ws
    assert "identityRefreshing={identityReads > 0 || busy}" in ws
    assert "identityRefreshing" in wb
    assert "Refreshing saved project state before Run" in wb


def test_flag_authority_defaults_to_on_everywhere(monkeypatch):
    monkeypatch.delenv("FINCO_MODEL_REACT_V1", raising=False)
    from app.v2.react_poc_router import react_poc_enabled
    import main_web
    assert react_poc_enabled() is True
    assert main_web._finco_model_react_flag(SimpleNamespace()) == {"finco_model_react": True}

    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")
    assert react_poc_enabled() is False
    assert main_web._finco_model_react_flag(SimpleNamespace()) == {"finco_model_react": False}


@pytest.fixture()
def cutover_env(tmp_path, monkeypatch):
    from app.persistence import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "finco47.db"))
    monkeypatch.delenv("FINCO_MODEL_REACT_V1", raising=False)
    db.init_db()
    from app.auth import COOKIE_NAME, create_session_token
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.services.reference_seed_service import create_reference_seeded_project
    import main_web

    owner = "finco47-owner"
    stranger = "finco47-stranger"
    rec = create_reference_seeded_project(
        user_id=owner, requested_name="Cutover Solar",
        template_source="generic_solar_reference", capacity_mw=16,
    )
    client = TestClient(main_web.app)
    client.cookies.set(COOKIE_NAME, create_session_token(user_id=owner, username="admin"))
    other = TestClient(main_web.app)
    other.cookies.set(COOKIE_NAME, create_session_token(user_id=stranger, username="stranger"))
    anon = TestClient(main_web.app)
    yield SimpleNamespace(client=client, other=other, anon=anon, record=rec, owner=owner, stranger=stranger)
    reset_model_executor_for_tests(None)


def test_legacy_get_routes_redirect_to_canonical_react_destinations(cutover_env):
    code = cutover_env.record.project_code
    cases = [
        ("/library", "/v2/model-react/"),
        ("/projects", "/v2/model-react/"),
        ("/projects/browse", "/v2/model-react/"),
        ("/home", "/v2/model-react/"),
        ("/projects/new", "/v2/model-react/#new-project"),
        ("/projects/new/minimal", "/v2/model-react/#new-project"),
        (f"/?project={code}", f"/v2/model-react/{code}"),
        (f"/v2/workbook?project={code}", f"/v2/model-react/{code}"),
        (f"/v2/workbook?project={code}&sheet=capex", f"/v2/model-react/{code}#inputs/capex"),
        (f"/scenarios?project={code}", f"/v2/model-react/{code}#scenarios"),
        ("/pilot-guide", "/v2/model-react/#guide"),
        ("/help", "/v2/model-react/#guide"),
    ]
    for src, expected in cases:
        resp = cutover_env.client.get(src, follow_redirects=False)
        assert resp.status_code == 302, f"{src} returned {resp.status_code}"
        assert resp.headers["location"] == expected, f"{src} -> {resp.headers['location']} != {expected}"

    # Unauthenticated protected routes fail closed: with demo mode active, anonymous callers
    # receive an isolated demo session that cannot resolve another owner's project;
    # with FINCO_DEMO_ENABLED=0, protected routes redirect to /login.
    assert cutover_env.anon.get(f"/v2/workbook?project={code}", follow_redirects=False).headers["location"] == "/v2/model-react/?notice=project-unavailable"
    cutover_env.anon.cookies.clear()
    lib_anon = cutover_env.anon.get("/library", follow_redirects=False)
    assert lib_anon.status_code == 302
    assert lib_anon.headers["location"] in ("/login", "/v2/model-react/")
    assert cutover_env.anon.get("/public-health").status_code == 200
    cutover_env.anon.cookies.clear()
    assert cutover_env.anon.get("/health").status_code == 401
    assert cutover_env.client.get("/health").status_code == 200

    # Foreign / unknown project cannot probe or redirect to project workspace.
    foreign = cutover_env.other.get(f"/v2/workbook?project={code}", follow_redirects=False)
    assert foreign.status_code == 302
    assert foreign.headers["location"] == "/v2/model-react/?notice=project-unavailable"


def test_get_workbook_never_mutates_sqlite_for_missing_revenue_keys(cutover_env, monkeypatch):
    import json
    from app.persistence.db import get_connection
    from app.persistence.workspace_repository import get_workspace_state

    rec = cutover_env.record
    conn = get_connection()
    ws = get_workspace_state(cutover_env.owner, rec.project_id)
    snap = dict(ws.draft_snapshot)
    snap.pop("rev_co2_price_eur_mwh", None)
    snap["rev_co2_enabled"] = False
    snap["rev_merchant_balancing_pct"] = 0.0
    conn.execute(
        "UPDATE workspace_states SET draft_snapshot_json=? WHERE user_id=? AND project_id=?",
        (json.dumps(snap), cutover_env.owner, rec.project_id),
    )
    conn.commit()
    before_raw = conn.execute(
        "SELECT draft_snapshot_json FROM workspace_states WHERE user_id=? AND project_id=?",
        (cutover_env.owner, rec.project_id),
    ).fetchone()[0]

    # Even with flag OFF (direct template render), GET /v2/workbook MUST NOT write to SQLite.
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")
    t1 = cutover_env.client.get(f"/v2/workbook?project={rec.project_code}")
    assert t1.status_code == 200
    after_raw = conn.execute(
        "SELECT draft_snapshot_json FROM workspace_states WHERE user_id=? AND project_id=?",
        (cutover_env.owner, rec.project_id),
    ).fetchone()[0]
    assert after_raw == before_raw

    # Two-tab tokens remain identical with flag ON too.
    monkeypatch.delenv("FINCO_MODEL_REACT_V1", raising=False)
    tab1 = cutover_env.client.get("/v2/model-react/revenue", params={"project": rec.project_code}).json()
    tab2 = cutover_env.client.get("/v2/model-react/revenue", params={"project": rec.project_code}).json()
    assert tab1["save"]["content_hash"] == tab2["save"]["content_hash"]


def test_inputs_slice1_update_enforces_scoped_operation_csrf(cutover_env):
    from app.workbook.mutation_csrf import mutation_token
    from app.workbook.registry import WORKBOOK

    rec = cutover_env.record
    ws_meta = cutover_env.client.get("/v2/model-react/workspace", params={"project": rec.project_code}).json()
    base_form = {
        "field_id": "project_setup.technical.p50_hours",
        "value": "1950",
        "project": rec.project_code,
        "workbook_version": WORKBOOK.version,
        "content_hash": ws_meta["workbook"]["composite_hash"],
    }

    # Missing CSRF -> 403
    r_missing = cutover_env.client.post("/v2/workbook/inputs-slice1/update", data=base_form)
    assert r_missing.status_code == 403 and r_missing.json()["code"] == "CSRF_INVALID"

    # Wrong scope (workbook-update / grid-save token) -> 403
    wrong_scope = mutation_token(
        SimpleNamespace(cookies=dict(cutover_env.client.cookies), state=SimpleNamespace()),
        rec.project_code,
        "workbook-update",
    )
    r_wrong_scope = cutover_env.client.post("/v2/workbook/inputs-slice1/update", data={**base_form, "csrf_token": wrong_scope})
    assert r_wrong_scope.status_code == 403

    # Wrong project token -> 403
    wrong_proj = mutation_token(
        SimpleNamespace(cookies=dict(cutover_env.client.cookies), state=SimpleNamespace()),
        "other-project",
        "inputs-slice1-update",
    )
    r_wrong_proj = cutover_env.client.post("/v2/workbook/inputs-slice1/update", data={**base_form, "csrf_token": wrong_proj})
    assert r_wrong_proj.status_code == 403

    # Foreign owner -> 404 (undisclosed)
    foreign_tok = mutation_token(
        SimpleNamespace(cookies=dict(cutover_env.other.cookies), state=SimpleNamespace()),
        rec.project_code,
        "inputs-slice1-update",
    )
    r_foreign = cutover_env.other.post("/v2/workbook/inputs-slice1/update", data={**base_form, "csrf_token": foreign_tok})
    assert r_foreign.status_code == 404

    # Valid scoped token -> 200
    valid_tok = mutation_token(
        SimpleNamespace(cookies=dict(cutover_env.client.cookies), state=SimpleNamespace()),
        rec.project_code,
        "inputs-slice1-update",
    )
    r_ok = cutover_env.client.post(
        "/v2/workbook/inputs-slice1/update",
        data={**base_form, "csrf_token": valid_tok},
        headers={"HX-Request": "true"},
    )
    assert r_ok.status_code == 200
