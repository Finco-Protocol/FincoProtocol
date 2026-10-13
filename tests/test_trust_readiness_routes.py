"""WF-10A: the Trust pages are public and read-only, and the existing authentication is unchanged."""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.trust_readiness.router import PAGES


@pytest.fixture
def app():
    import main_web

    return main_web.app


@pytest.fixture
def fresh(app):
    return TestClient(app)


def test_every_trust_page_is_public_html_and_sets_no_cookie(fresh):
    for p in PAGES:
        r = fresh.get(p.path, follow_redirects=False)
        assert r.status_code == 200, p.path
        assert r.headers["content-type"].startswith("text/html"), p.path
        assert "set-cookie" not in r.headers, p.path
        assert f"<h1>{p.title}</h1>" in r.text
    assert not fresh.cookies, "visiting the Trust pages must not create any cookie"


def test_trust_pages_ignore_existing_sessions(fresh):
    fresh.get("/roadmap")  # a normal public page issues the anonymous demo cookie
    before = dict(fresh.cookies)
    assert "finco_demo" in before
    r = fresh.get("/trust/security")
    assert "set-cookie" not in r.headers
    assert dict(fresh.cookies) == before


def test_trust_routes_are_get_only_and_exactly_the_expected_set(app):
    expected = {p.path for p in PAGES} | {"/trust/registry.json"}
    seen = {}
    for r in app.routes:
        if getattr(r, "path", "").startswith("/trust"):
            seen.setdefault(r.path, set()).update(r.methods or set())
    assert set(seen) == expected
    assert all(m <= {"GET", "HEAD"} for m in seen.values())


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_trust_pages_reject_state_changing_methods(fresh, method):
    for path in ("/trust", "/trust/legal", "/trust/registry.json"):
        assert getattr(fresh, method)(path).status_code in (403, 405), (method, path)


def test_trust_pages_do_not_read_the_database(fresh, monkeypatch):
    from app.persistence import db

    def boom(*a, **k):
        raise AssertionError("trust pages must not open the database")

    monkeypatch.setattr(db, "get_connection", boom)
    for p in PAGES:
        assert fresh.get(p.path).status_code == 200


# ── Protected routes remain protected ───────────────────────────────────────

def test_no_protected_route_exposure(fresh):
    assert fresh.get("/health").status_code == 401
    assert fresh.post("/logout", follow_redirects=False).status_code in (302, 303, 307, 401, 403, 405)
    # Nothing under /trust links to, embeds or proxies a protected area.
    body = "".join(fresh.get(p.path).text for p in PAGES)
    assert not re.search(r'href="/(?:library|v2|workbook|projects|admin|ops)', body)
    registry = fresh.get("/trust/registry.json").text
    assert not re.search(r"\bdemo_[A-Za-z0-9_-]{32}\b", registry), "a demo identity leaked into the registry"


def test_trust_prefix_does_not_widen_the_public_surface(app):
    from app.trust_readiness.router import TRUST_PREFIX

    stray = [r.path for r in app.routes if getattr(r, "path", "").startswith(TRUST_PREFIX)
             and r.path not in {p.path for p in PAGES} | {"/trust/registry.json"}]
    assert not stray


# ── Demo and operator authentication unchanged ──────────────────────────────

def test_demo_session_is_still_provisioned_on_first_visit(fresh):
    r = fresh.get("/roadmap")
    assert "finco_demo=" in r.headers.get("set-cookie", "")
    cookie = fresh.cookies.get("finco_demo")
    from app.auth import decode_demo_session_token

    session = decode_demo_session_token(cookie)
    assert session is not None and session.session_type == "demo"
    assert session.user_id.startswith("demo_")


def test_demo_session_reaches_the_workspace_while_anonymous_does_not_need_login(fresh):
    fresh.get("/roadmap")
    r = fresh.get("/", follow_redirects=False)
    assert r.status_code in (200, 302)
    assert not r.headers.get("location", "").endswith("/login")


def test_tampered_demo_cookie_is_not_accepted(fresh):
    from app.auth import decode_demo_session_token

    fresh.get("/roadmap")
    token = fresh.cookies.get("finco_demo")
    assert decode_demo_session_token(token + "x") is None
    assert decode_demo_session_token("not-a-token") is None


def test_operator_login_still_works(fresh, monkeypatch):
    from app import auth

    monkeypatch.setattr(auth, "_rate_limit_store", {})
    monkeypatch.setattr(auth, "ADMIN_PASSWORD_HASH_ENV", None)
    monkeypatch.setattr(auth, "ADMIN_PASSWORD_PLAIN", "test-only-operator-pw-123")
    page = fresh.get("/login", follow_redirects=False)
    token = re.search(r'name="csrf_token"\s+value="([^"]+)"', page.text).group(1)
    ok = fresh.post("/login", data={"username": auth.ADMIN_USERNAME, "password": "test-only-operator-pw-123",
                                    "csrf_token": token}, follow_redirects=False)
    assert ok.status_code == 302 and "finco_session=" in ok.headers.get("set-cookie", "")
    bad = fresh.post("/login", data={"username": auth.ADMIN_USERNAME, "password": "wrong-password-xyz",
                                     "csrf_token": token}, follow_redirects=False)
    assert bad.status_code == 401


def test_skip_list_contains_exactly_one_new_prefix():
    import main_web

    prefixes = set(main_web._DEMO_PROVISION_SKIP_PREFIXES)
    assert "/trust" in prefixes
    assert {"/static", "/login", "/logout", "/public-health", "/readyz", "/health", "/favicon",
            "/api", "/protocol/finco", "/verify/run"} <= prefixes
    assert len(prefixes) == 11
    # The unchanged prefixes keep their meaning: /roadmap and /docs are still provisioned.
    assert not any("/roadmap".startswith(p) or "/docs".startswith(p) for p in prefixes)
