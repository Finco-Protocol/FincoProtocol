"""FABLE-SEC-01 (C1-Q-07 / D07b / D07c) — legacy mutating routes enforce scoped CSRF.

Regression for the two legacy POST routes that previously accepted a request
with no CSRF token while every V2 mutation route enforces the session+project+
operation-bound token (Fable C1 code-security audit 2026-11-14, D07b/D07c):

- POST /projects/create — no token / wrong token / another session's token /
  wrong-operation token => HTTP 403 and ZERO project mutation;
  exact valid token from the rendered form => same successful create as before.
- POST /scenarios/state/discard — no token / wrong token / token bound to
  another project => HTTP 403 and zero state mutation; valid token => same
  successful discard payload as before.

No 500 responses and no internal exception strings in denial output.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from fastapi import Request

import pytest


@pytest.fixture(autouse=True)
def _finco47_legacy_ssr_rollback(monkeypatch):
    """Scoped to this legacy SSR test module; default production flag stays React ON."""
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "pr1_csrf.db"))
    monkeypatch.setenv("FINCO_APP_MODE", "development")
    import app.persistence.db as _db
    monkeypatch.setattr(_db, "DB_PATH", str(tmp_path / "pr1_csrf.db"))
    from starlette.testclient import TestClient
    import main_web
    # HTTPS base url: session cookies are marked Secure and httpx must send
    # them back, matching real browser behaviour over TLS.
    with TestClient(main_web.app, base_url="https://pr1-csrf.local",
                    raise_server_exceptions=False) as c:
        yield c


def _login(client):
    page = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    r = client.post("/login", data={
        "username": "admin", "password": "FINCO Model2026!", "csrf_token": token})
    assert r.status_code in (200, 302, 303), r.status_code


def _user_project_codes(client):
    """All project codes visible to the logged-in session's identity."""
    from app.auth import resolve_request_session
    from app.persistence.projects_repository import list_projects_paged
    scope = {
        "type": "http", "method": "GET", "path": "/", "query_string": b"",
        "headers": [
            (b"cookie", ("; ".join(
                f"{k}={v}" for k, v in client.cookies.items())).encode("latin-1")),
        ],
    }
    session = resolve_request_session(Request(scope))
    records, _total = list_projects_paged(user_id=session.user_id, page_size=200)
    return sorted(r.project_code for r in records if r.project_origin == "user_created")


def _issue(client, project: str, purpose: str) -> str:
    """Issue a bound token the way the route does (same session cookie)."""
    from fastapi import Request
    import main_web
    scope = {
        "type": "http", "method": "POST", "path": "/", "query_string": b"",
        "headers": [
            (b"cookie", ("; ".join(
                f"{k}={v}" for k, v in client.cookies.items())).encode("latin-1")),
        ],
    }
    request = Request(scope)
    return main_web._csrf_issue_token(request, project, purpose=purpose)


_CREATE_FORM = {
    "project_name": "PR1 CSRF Regression Project",
    "project_type": "Wind",
    "country_market": "Generic Market A",
    "capacity_mw": "12",
    "target_dscr": "1.20",
}


# ── POST /projects/create ────────────────────────────────────────────────────

def test_create_renders_bound_token_in_form(client):
    _login(client)
    page = client.get("/projects/new")
    assert page.status_code == 200
    m = re.search(r'name="csrf_token" value="([^"]*)"', page.text)
    assert m and m.group(1), "minimal create form must render a bound csrf_token"
    page2 = client.get("/projects/new/prefill")
    assert page2.status_code == 200
    m2 = re.search(r'name="csrf_token" value="([^"]*)"', page2.text)
    assert m2 and m2.group(1), "prefilled create form must render a bound csrf_token"


def test_create_without_token_is_denied_and_mutates_nothing(client):
    _login(client)
    before = _user_project_codes(client)
    r = client.post("/projects/create", data=dict(_CREATE_FORM),
                    headers={"HX-Request": "true"})
    assert r.status_code == 403, r.status_code
    assert "PR1 CSRF Regression Project" not in r.text  # no echo of success
    assert _user_project_codes(client) == before, "no project must be created"


def test_create_with_bogus_token_is_denied(client):
    _login(client)
    before = _user_project_codes(client)
    r = client.post("/projects/create", data={**_CREATE_FORM, "csrf_token": "bogus.token"},
                    headers={"HX-Request": "true"})
    assert r.status_code == 403
    assert _user_project_codes(client) == before


def test_create_with_other_session_token_is_denied(client):
    _login(client)
    # Token issued for a DIFFERENT session (fresh cookie jar) must be refused.
    from starlette.testclient import TestClient
    import main_web
    with TestClient(main_web.app, base_url="https://pr1-csrf.local") as other:
        page = other.get("/login")
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        other.post("/login", data={
            "username": "admin", "password": "FINCO Model2026!", "csrf_token": token})
        foreign = _issue(other, "", "projects-create-v1")
    before = _user_project_codes(client)
    r = client.post("/projects/create", data={**_CREATE_FORM, "csrf_token": foreign},
                    headers={"HX-Request": "true"})
    assert r.status_code == 403
    assert _user_project_codes(client) == before


def test_create_with_valid_bound_token_succeeds(client):
    _login(client)
    before = _user_project_codes(client)
    # Positive client path: the exact token the server rendered into the form.
    page = client.get("/projects/new")
    token = re.search(r'name="csrf_token" value="([^"]*)"', page.text).group(1)
    r = client.post("/projects/create", data={**_CREATE_FORM, "csrf_token": token},
                    headers={"HX-Request": "true"})
    assert r.status_code == 200, r.status_code
    after = _user_project_codes(client)
    assert len(after) == len(before) + 1, (before, after)
    # HX-Redirect (workspace reload) contract preserved on success.
    assert r.headers.get("HX-Redirect") or "HX-Redirect" in str(r.headers)


def test_create_denial_has_no_internal_detail(client):
    _login(client)
    r = client.post("/projects/create", data=_CREATE_FORM, headers={"HX-Request": "true"})
    body = r.text.lower()
    assert r.status_code == 403
    assert "traceback" not in body and "exception" not in body
    assert "financing_csrf" not in body and "csrf_secret" not in body


# ── POST /scenarios/state/discard ────────────────────────────────────────────


def test_discard_without_token_is_denied(client):
    _login(client)
    r = client.post("/scenarios/state/discard",
                    data={"active_project": "generic_wind_reference"})
    assert r.status_code == 403
    body = r.json()
    assert set(body) == {"error"}, body  # fixed generic denial contract


def test_discard_with_bogus_token_is_denied(client):
    _login(client)
    r = client.post("/scenarios/state/discard",
                    data={"active_project": "generic_wind_reference",
                          "csrf_token": "bogus.token"})
    assert r.status_code == 403


def test_discard_with_foreign_session_token_is_denied(client):
    _login(client)
    from starlette.testclient import TestClient
    import main_web
    with TestClient(main_web.app, base_url="https://pr1-csrf.local") as other:
        page = other.get("/login")
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        other.post("/login", data={
            "username": "admin", "password": "FINCO Model2026!", "csrf_token": token})
        foreign = _issue(other, "generic_wind_reference", "workspace-draft-discard-v1")
    r = client.post("/scenarios/state/discard",
                    data={"active_project": "generic_wind_reference",
                          "csrf_token": foreign})
    assert r.status_code == 403


def test_discard_with_wrong_project_token_is_denied(client):
    _login(client)
    # Token bound to a DIFFERENT project than the submitted active_project.
    token = _issue(client, "generic_solar_reference", "workspace-draft-discard-v1")
    assert token
    r = client.post("/scenarios/state/discard",
                    data={"active_project": "generic_wind_reference",
                          "csrf_token": token})
    assert r.status_code == 403


def test_discard_with_valid_token_succeeds(client):
    _login(client)
    # The legacy workspace index render is broken on this baseline for an
    # unrelated pre-existing template reason (500 with the workbook flag off,
    # verified on pristine main), so the positive path issues the token through
    # the exact route issuance primitive with the same session cookie. The
    # client-supply contract (hidden input inside #main-form) is asserted
    # statically by test_workspace_main_form_carries_discard_token.
    token = _issue(client, "generic_wind_reference", "workspace-draft-discard-v1")
    assert token
    r = client.post("/scenarios/state/discard",
                    data={"active_project": "generic_wind_reference",
                          "csrf_token": token})
    assert r.status_code == 200, r.status_code
    payload = r.json()
    # Pre-existing successful-discard contract preserved (characterized quirks).
    assert payload.get("message") == (
        "Unsaved edits discarded. Workspace restored to the last "
        "saved runtime boundary.")
    assert "snapshot" in payload


def test_workspace_main_form_carries_discard_token():
    """Client-supply contract: the hidden persistence form posts the bound token."""
    shell = (REPO / "app/templates/partials/workspace_shell.html").read_text(encoding="utf-8")
    assert 'id="main-form"' in shell
    assert 'name="csrf_token" value="{{ workspace_csrf_token' in shell
    index = (REPO / "app/templates/index.html").read_text(encoding="utf-8")
    assert 'workspace_shell.html' in index
    # The discard JS posts the whole FormData of #main-form, so the token travels.
    js = (REPO / "static/app.js").read_text(encoding="utf-8")
    assert "new FormData(form)" in js and "'/scenarios/state/discard'" in js


def test_issuance_fault_fails_closed_and_is_logged(client, monkeypatch, caplog):
    """A real server-side token-issuance fault must never render a usable
    form or silently vanish: the page shows no token, the POST is denied 403
    with zero mutation, and the fault is logged by TYPE (no token/session
    material in the log record)."""
    import logging as _logging
    import main_web

    def _boom(request, project, purpose):
        raise RuntimeError("simulated issuance fault")

    monkeypatch.setattr(main_web, "_csrf_issue_token", _boom)
    with caplog.at_level(_logging.ERROR, logger="main_web"):
        page = client.get("/projects/new")
        assert page.status_code == 200
        m = re.search(r'name="csrf_token" value="([^"]*)"', page.text)
        assert m is not None and m.group(1) == "", "fail-closed: no token rendered on issuance fault"
        r = client.post("/projects/create", data=dict(_CREATE_FORM),
                        headers={"HX-Request": "true"})
        assert r.status_code == 403
        assert _user_project_codes(client) == []
    records = [rec for rec in caplog.records if "LEGACY_ROUTE_CSRF_ISSUE_FAILED" in rec.getMessage()]
    assert records, "the issuance fault must be logged"
    line = records[0].getMessage()
    assert "simulated issuance fault" not in line, "no exception text in the log"
    assert "RuntimeError" in line and "token" not in line.split("exc=")[1]
