"""FABLE-SEC-01 integration matrix (FINCO 34 batch 1, on top of tests/test_fable_pr1_legacy_csrf.py).

Covers the acceptance cases the original #462 suite did not exercise, against the canonical
session+project+operation-bound token (app.workbook.financing_csrf + app.auth.validate_csrf_token):

* wrong-operation tokens (create <-> discard <-> capital-stack purpose) are refused;
* expired tokens (older than the canonical 24 h validator window) are refused;
* malformed token shapes are refused with the generic 403 and no internals;
* a denial leaves the WHOLE database byte-identical (full sqlite dump hash), for create and discard;
* the canonical contract is NOT one-time: a token is reusable inside its session/operation/window,
  and is refused once the session changes (logout/login) -- documented, not over-claimed;
* anonymous and demo actors: anon is redirected/401 before any token logic, a demo session's own
  token works for its own create, a demo token is refused for another actor, and CSRF denials do
  not consume the demo creation rate budget;
* a validation re-render carries a fresh, working token (both create forms);
* the legacy workspace page renders a working discard token into #main-form;
* both FINCO_MOUNT_RADAR settings (#475 boundary) keep the enforcement identical.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _finco47_legacy_ssr_rollback(monkeypatch):
    """Scoped to this legacy SSR test module; default production flag stays React ON."""
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")

REPO = Path(__file__).resolve().parents[1]
TOKEN_RE = re.compile(r'name="csrf_token" value="([^"]*)"')
DENIAL = {"error": "Invalid or missing security token. Reload the page and try again."}
FORM = {"project_name": "SEC01 Matrix Project", "project_type": "Wind",
        "country_market": "Generic Market A", "capacity_mw": "12", "target_dscr": "1.20"}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "sec01.db")
    monkeypatch.setenv("FINCO_DB_PATH", db_path)
    monkeypatch.setenv("FINCO_APP_MODE", "development")
    import app.persistence.db as _db
    monkeypatch.setattr(_db, "DB_PATH", db_path)
    return db_path


def _client():
    from starlette.testclient import TestClient
    import main_web
    return TestClient(main_web.app, base_url="https://sec01.local", raise_server_exceptions=False)


def _login(c):
    token = TOKEN_RE.search(c.get("/login").text).group(1)
    r = c.post("/login", data={"username": "admin", "password": "FINCO Model2026!", "csrf_token": token})
    assert r.status_code in (200, 302, 303), r.status_code


def _db_hash(db_path: str) -> str:
    conn = sqlite3.connect(db_path)
    try:
        return hashlib.sha256("\n".join(conn.iterdump()).encode("utf-8")).hexdigest()
    finally:
        conn.close()


def _issue(c, project: str, purpose: str) -> str:
    from fastapi import Request
    import main_web
    cookie = "; ".join(f"{k}={v}" for k, v in c.cookies.items()).encode("latin-1")
    req = Request({"type": "http", "method": "POST", "path": "/", "query_string": b"",
                   "headers": [(b"cookie", cookie)]})
    return main_web._csrf_issue_token(req, project, purpose=purpose)


def _form_token(c, path="/projects/new") -> str:
    page = c.get(path)
    assert page.status_code == 200, page.status_code
    return TOKEN_RE.search(page.text).group(1)


def _assert_denied(r):
    assert r.status_code == 403, r.status_code
    assert r.json() == DENIAL
    low = r.text.lower()
    for leak in ("traceback", "exception", "financing_csrf", "csrf_secret", "signature", "itsdangerous"):
        assert leak not in low


# ── wrong operation ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("purpose", ["workspace-draft-discard-v1", "capital-stack-save-v1", "projects-create-v2"])
def test_create_refuses_tokens_bound_to_another_operation(env, purpose):
    with _client() as c:
        _login(c)
        before = _db_hash(env)
        _assert_denied(c.post("/projects/create", data={**FORM, "csrf_token": _issue(c, "", purpose)},
                              headers={"HX-Request": "true"}))
        assert _db_hash(env) == before


@pytest.mark.parametrize("purpose", ["projects-create-v1", "capital-stack-save-v1"])
def test_discard_refuses_tokens_bound_to_another_operation(env, purpose):
    with _client() as c:
        _login(c)
        before = _db_hash(env)
        token = _issue(c, "generic_wind_reference", purpose)
        _assert_denied(c.post("/scenarios/state/discard",
                              data={"active_project": "generic_wind_reference", "csrf_token": token}))
        assert _db_hash(env) == before


def test_create_token_bound_to_a_project_is_refused_for_the_unbound_create(env):
    with _client() as c:
        _login(c)
        token = _issue(c, "generic_wind_reference", "projects-create-v1")
        _assert_denied(c.post("/projects/create", data={**FORM, "csrf_token": token}))


# ── expiry ───────────────────────────────────────────────────────────────────

def test_expired_tokens_are_refused_for_create_and_discard(env, monkeypatch):
    import time
    from itsdangerous import TimestampSigner
    with _client() as c:
        _login(c)
        real = time.time()
        monkeypatch.setattr(TimestampSigner, "get_timestamp", lambda self: int(real - 86400 - 120))
        old_create = _issue(c, "", "projects-create-v1")
        old_discard = _issue(c, "generic_wind_reference", "workspace-draft-discard-v1")
        monkeypatch.undo()
        before = _db_hash(env)
        _assert_denied(c.post("/projects/create", data={**FORM, "csrf_token": old_create}))
        _assert_denied(c.post("/scenarios/state/discard",
                              data={"active_project": "generic_wind_reference", "csrf_token": old_discard}))
        assert _db_hash(env) == before
        # Control: the same issuance inside the window is accepted.
        assert c.post("/projects/create", data={**FORM, "csrf_token": _form_token(c)},
                      headers={"HX-Request": "true"}).status_code == 200


# ── malformed shapes ─────────────────────────────────────────────────────────

def _malformed(valid: str):
    token, _, digest = valid.rpartition(".")
    flipped = ("0" if digest[0] != "0" else "1") + digest[1:]
    return ["", ".", "x" * 4096, valid + "0", token, "." + digest, token + "." + flipped,
            token[:-1] + ("A" if token[-1] != "A" else "B") + "." + digest, valid.upper(),
            token + "." + digest[:-1] + "g", " " + valid, valid + " "]


def test_malformed_tokens_are_refused_and_mutate_nothing(env):
    with _client() as c:
        _login(c)
        create_valid = _form_token(c)
        discard_valid = _issue(c, "generic_wind_reference", "workspace-draft-discard-v1")
        before = _db_hash(env)
        for bad in _malformed(create_valid):
            _assert_denied(c.post("/projects/create", data={**FORM, "csrf_token": bad}))
        for bad in _malformed(discard_valid):
            _assert_denied(c.post("/scenarios/state/discard",
                                  data={"active_project": "generic_wind_reference", "csrf_token": bad}))
        # A token submitted as a query string is not a token.
        _assert_denied(c.post("/projects/create?csrf_token=" + create_valid, data=FORM))
        assert _db_hash(env) == before


# ── reuse / session semantics (canonical contract: NOT one-time) ─────────────

def test_token_reuse_semantics_are_session_and_window_bound_not_one_time(env):
    with _client() as c:
        _login(c)
        token = _form_token(c)
        r1 = c.post("/projects/create", data={**FORM, "project_name": "SEC01 reuse 1", "csrf_token": token},
                    headers={"HX-Request": "true"})
        r2 = c.post("/projects/create", data={**FORM, "project_name": "SEC01 reuse 2", "csrf_token": token},
                    headers={"HX-Request": "true"})
        # The canonical signed token is not single-use; the contract binds actor/session/operation/time.
        assert (r1.status_code, r2.status_code) == (200, 200)
        c.get("/logout")
        c.cookies.clear()
        _login(c)  # new session cookie => the old binding no longer verifies
        before = _db_hash(env)
        _assert_denied(c.post("/projects/create", data={**FORM, "project_name": "SEC01 reuse 3",
                                                         "csrf_token": token}))
        assert _db_hash(env) == before


# ── anonymous / demo actors ──────────────────────────────────────────────────

def test_anonymous_requests_never_reach_the_mutation(env):
    from starlette.testclient import TestClient
    import main_web
    with TestClient(main_web.app, base_url="https://sec01.local", raise_server_exceptions=False,
                    cookies=None) as c:
        before = _db_hash(env)
        # No session cookie at all on a POST (the demo provisioning middleware sets a cookie on the
        # response only), so the route treats the actor as unauthenticated.
        r = c.post("/projects/create", data={**FORM, "csrf_token": "anything"}, follow_redirects=False)
        assert r.status_code in (302, 303, 401, 403), r.status_code
        r = c.post("/scenarios/state/discard", data={"active_project": "generic_wind_reference"},
                   follow_redirects=False)
        assert r.status_code in (401, 403), r.status_code
        assert _db_hash(env) == before


def test_demo_session_token_is_actor_bound_and_denials_do_not_consume_rate_budget(env, monkeypatch):
    import app.auth as auth
    monkeypatch.setitem(auth.DEMO_RATE_LIMITS, "project_create", (1, 3600))
    auth._shared_limits.reset_for_tests()
    with _client() as demo, _client() as admin:
        demo.get("/")  # middleware provisions a demo session cookie
        assert auth.DEMO_COOKIE_NAME in demo.cookies
        demo_token = _form_token(demo)
        assert demo_token
        _login(admin)
        before = _db_hash(env)
        # Another actor (admin session) cannot use the demo session's token.
        _assert_denied(admin.post("/projects/create", data={**FORM, "csrf_token": demo_token}))
        # Several CSRF denials for the demo actor ...
        for _ in range(3):
            _assert_denied(demo.post("/projects/create", data={**FORM, "csrf_token": "bogus.token"}))
        assert _db_hash(env) == before
        # ... do not consume its single allowed creation (limit 1/h for this test).
        ok = demo.post("/projects/create", data={**FORM, "csrf_token": demo_token},
                       headers={"HX-Request": "true"})
        assert ok.status_code == 200, ok.status_code
        # The rate limiter still applies to valid-token requests after that: nothing is created.
        # NOTE (pre-existing on main d4c1ed0, recorded as an open defect, not in this batch's scope):
        # the limit branch renders a missing "errors.html" template, so the refusal surfaces as a
        # 500 instead of the intended 429. The security property (no mutation) is what is asserted.
        after_ok = _db_hash(env)
        limited = demo.post("/projects/create", data={**FORM, "project_name": "SEC01 demo 2",
                                                       "csrf_token": demo_token},
                            headers={"HX-Request": "true"})
        assert limited.status_code != 200 and not limited.headers.get("HX-Redirect"), limited.status_code
        assert _db_hash(env) == after_ok
    auth._shared_limits.reset_for_tests()


# ── validation re-render refresh (both forms) ────────────────────────────────

@pytest.mark.parametrize("form_path", ["/projects/new", "/projects/new/prefill"])
def test_validation_rerender_carries_a_fresh_working_token(env, form_path):
    with _client() as c:
        _login(c)
        token = _form_token(c, form_path)
        bad = c.post("/projects/create", data={**FORM, "template_source": "generic_solar_reference",
                                               "csrf_token": token}, headers={"HX-Request": "true"})
        # App-level validation (Wind type + Solar template) re-renders the form with HTTP 400.
        assert bad.status_code == 400, bad.status_code
        assert "Solar templates require project type Solar." in bad.text
        m = TOKEN_RE.search(bad.text)
        assert m and m.group(1), "validation re-render must carry a bound token"
        ok = c.post("/projects/create", data={**FORM, "project_name": "SEC01 corrected " + form_path,
                                              "csrf_token": m.group(1)}, headers={"HX-Request": "true"})
        assert ok.status_code == 200, ok.status_code
        assert ok.headers.get("HX-Redirect")


# ── legacy workspace page → discard round trip ───────────────────────────────

def test_rendered_workspace_discard_token_round_trip(env):
    with _client() as c:
        _login(c)
        created = c.post("/projects/create", data={**FORM, "project_name": "SEC01 workspace",
                                                   "csrf_token": _form_token(c)},
                         headers={"HX-Request": "true"})
        assert created.status_code == 200
        target = created.headers["HX-Redirect"]
        m = re.search(r"project=([^&]+)", target)
        assert m, target
        code = m.group(1)
        page = c.get("/?project=" + code)
        if page.status_code != 200 or 'id="main-form"' not in page.text:
            # The legacy index may route to the workbook surface; the issuance primitive is then
            # exercised directly (static client contract asserted in test_fable_pr1_legacy_csrf.py).
            token = _issue(c, code, "workspace-draft-discard-v1")
        else:
            form_html = page.text.split('id="main-form"', 1)[1].split("</form>", 1)[0]
            token = TOKEN_RE.search(form_html).group(1)
        assert token
        _assert_denied(c.post("/scenarios/state/discard",
                              data={"active_project": "generic_wind_reference", "csrf_token": token}))
        ok = c.post("/scenarios/state/discard", data={"active_project": code, "csrf_token": token})
        assert ok.status_code == 200, (ok.status_code, ok.text[:300])
        assert "snapshot" in ok.json()


# ── #475 boundary: identical enforcement under both FINCO_MOUNT_RADAR values ─

_PROBE = r"""
import json, re, sys
from starlette.testclient import TestClient
import main_web
R = re.compile(r'name="csrf_token" value="([^"]*)"')
out = {}
with TestClient(main_web.app, base_url="https://sec01.local", raise_server_exceptions=False) as c:
    t = R.search(c.get("/login").text).group(1)
    c.post("/login", data={"username": "admin", "password": "FINCO Model2026!", "csrf_token": t})
    form = {"project_name": "SEC01 flag", "project_type": "Wind", "country_market": "Generic Market A",
            "capacity_mw": "12"}
    out["create_missing"] = c.post("/projects/create", data=form).status_code
    out["discard_missing"] = c.post("/scenarios/state/discard", data={"active_project": "x"}).status_code
    tok = R.search(c.get("/projects/new").text).group(1)
    out["create_valid"] = c.post("/projects/create", data={**form, "csrf_token": tok},
                                 headers={"HX-Request": "true"}).status_code
    out["introspect_public"] = c.post("/internal/v1/auth/introspect", json={}).status_code
    out["radar_mounted"] = any(getattr(r, "path", "") == "/radar" for r in main_web.app.routes)
print(json.dumps(out))
"""


@pytest.mark.parametrize("flag", ["1", "0"])
def test_enforcement_is_identical_under_both_radar_mount_flags(tmp_path, flag):
    env = os.environ.copy()
    env.update(FINCO_MOUNT_RADAR=flag, FINCO_RLIVE_WARMING_ENABLED="0", PYTHONPATH=str(REPO),
               FINCO_DB_PATH=str(tmp_path / f"flag{flag}.db"), FINCO_APP_MODE="development")
    env.pop("FINCO_INTERNAL_AUTH_TOKEN", None)
    out = subprocess.check_output([sys.executable, "-c", _PROBE], cwd=str(REPO), env=env, text=True)
    res = json.loads(out.strip().splitlines()[-1])
    assert res["create_missing"] == 403
    assert res["discard_missing"] == 403
    assert res["create_valid"] == 200
    # #475 internal introspect stays fail-closed (never a 2xx from a public, untokened caller).
    assert res["introspect_public"] >= 400
    assert res["radar_mounted"] is (flag == "1")
