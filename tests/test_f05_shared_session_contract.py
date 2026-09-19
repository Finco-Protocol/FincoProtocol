"""F05 — shared session contract acceptance matrix.

Pins the canonical session resolution contract (app.auth.resolve_request_session /
resolve_admin_session) at two levels:

1. Resolver level — every identity class (admin, demo, provisioned demo,
   anonymous, tampered, expired) resolves identically no matter which surface
   asks, and tampered/expired material fails closed.
2. Route level — the same session cookie must authenticate the same way on
   Library and Workbook V2. A demo session that opens /library must not be
   bounced to /login by /v2/workbook; both surfaces go through the identical
   resolver and route-level authorization (ownership, redirects) applies
   downstream of the shared identity.

All session material is generated in-process with the documented dev fallback
key; nothing here touches real credentials.
"""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _admin_cookie_value() -> str:
    from app.auth import create_session_token, make_session_cookie
    return make_session_cookie(create_session_token())["value"]


def _demo_cookie_value(user_id: str | None = None) -> str:
    from app.auth import create_demo_session_token, new_demo_user_id
    return create_demo_session_token(user_id or new_demo_user_id())


def _dummy_request(cookies: dict | None = None, state_token: str | None = None):
    return SimpleNamespace(
        cookies=cookies or {},
        state=SimpleNamespace(demo_session_token=state_token),
    )


def _client():
    import main_web
    from starlette.testclient import TestClient
    with TestClient(main_web.app, raise_server_exceptions=False) as c:
        yield c


def _create_project(user_id: str, project_code: str):
    from app.persistence.repository import create_project_record
    return create_project_record(
        user_id=user_id,
        project_code=project_code,
        project_name=f"F05 test {project_code}",
        project_type="Solar",
        project_origin="user",
        template_source="",
        baseline_snapshot={},
    )


def _delete_projects(user_id: str) -> None:
    from app.persistence.db import get_connection
    conn = get_connection()
    conn.execute("DELETE FROM projects WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Resolver-level matrix — one authority, every identity class
# ---------------------------------------------------------------------------

def test_resolver_admin_cookie_yields_admin_session():
    from app.auth import COOKIE_NAME, resolve_request_session
    session = resolve_request_session(_dummy_request({COOKIE_NAME: _admin_cookie_value()}))
    assert session is not None and not session.is_demo


def test_resolver_demo_cookie_yields_demo_session():
    from app.auth import DEMO_COOKIE_NAME, resolve_request_session
    session = resolve_request_session(_dummy_request({DEMO_COOKIE_NAME: _demo_cookie_value()}))
    assert session is not None and session.is_demo


def test_resolver_provisioned_state_token_yields_demo_session():
    from app.auth import resolve_request_session
    session = resolve_request_session(_dummy_request({}, state_token=_demo_cookie_value()))
    assert session is not None and session.is_demo


def test_resolver_no_material_yields_none():
    from app.auth import resolve_request_session
    assert resolve_request_session(_dummy_request()) is None


def test_resolver_admin_precedence_over_demo():
    from app.auth import COOKIE_NAME, DEMO_COOKIE_NAME, resolve_request_session
    session = resolve_request_session(_dummy_request({
        COOKIE_NAME: _admin_cookie_value(),
        DEMO_COOKIE_NAME: _demo_cookie_value(),
    }))
    assert session is not None and not session.is_demo


def test_resolver_tampered_admin_cookie_fails_closed():
    from app.auth import COOKIE_NAME, resolve_request_session
    assert resolve_request_session(_dummy_request({COOKIE_NAME: "tampered-" + uuid.uuid4().hex})) is None


def test_resolver_tampered_demo_cookie_fails_closed():
    from app.auth import DEMO_COOKIE_NAME, resolve_request_session
    assert resolve_request_session(_dummy_request({DEMO_COOKIE_NAME: "tampered-" + uuid.uuid4().hex})) is None


def test_resolver_tampered_admin_falls_through_to_valid_demo():
    from app.auth import COOKIE_NAME, DEMO_COOKIE_NAME, resolve_request_session
    session = resolve_request_session(_dummy_request({
        COOKIE_NAME: "tampered-" + uuid.uuid4().hex,
        DEMO_COOKIE_NAME: _demo_cookie_value(),
    }))
    assert session is not None and session.is_demo


def test_resolver_expired_admin_token_fails_closed(monkeypatch):
    import app.auth as auth
    from app.auth import COOKIE_NAME, resolve_request_session
    token = auth.create_session_token()
    monkeypatch.setattr(auth, "SESSION_MAX_AGE_HOURS", 0)
    time.sleep(1.2)  # itsdangerous truncates to whole seconds — cross the boundary
    assert resolve_request_session(_dummy_request({COOKIE_NAME: token})) is None


def test_resolver_expired_demo_token_fails_closed(monkeypatch):
    import app.auth as auth
    from app.auth import DEMO_COOKIE_NAME, resolve_request_session
    token = auth.create_demo_session_token(auth.new_demo_user_id())
    monkeypatch.setattr(auth, "DEMO_TTL_HOURS", 0)
    time.sleep(1.2)  # itsdangerous truncates to whole seconds — cross the boundary
    assert resolve_request_session(_dummy_request({DEMO_COOKIE_NAME: token})) is None


def test_admin_resolver_rejects_demo_identity():
    from app.auth import DEMO_COOKIE_NAME, resolve_admin_session, resolve_request_session
    demo = _demo_cookie_value()
    assert resolve_request_session(_dummy_request({DEMO_COOKIE_NAME: demo})).is_demo
    assert resolve_admin_session(_dummy_request({DEMO_COOKIE_NAME: demo})) is None


def test_admin_resolver_accepts_admin_identity():
    from app.auth import COOKIE_NAME, resolve_admin_session
    session = resolve_admin_session(_dummy_request({COOKIE_NAME: _admin_cookie_value()}))
    assert session is not None and not session.is_demo


# ---------------------------------------------------------------------------
# Route-level matrix — Library and Workbook V2 obey the same contract
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    yield from _client()


def _demo_headers() -> dict[str, str]:
    from app.auth import DEMO_COOKIE_NAME
    return {"Cookie": f"{DEMO_COOKIE_NAME}={_demo_cookie_value()}"}


def test_anonymous_first_visit_gets_provisioned_demo_session(client):
    resp = client.get("/library")  # provisioning skip-list does not include /library
    assert resp.status_code == 200
    assert "finco_demo" in resp.headers.get("set-cookie", ""), (
        "first visit must be auto-provisioned a demo session"
    )


def test_demo_session_authenticates_library(client):
    resp = client.get("/library", headers=_demo_headers(), follow_redirects=False)
    assert resp.status_code == 200, (
        f"a valid demo session must open the Library, got {resp.status_code}"
    )


def test_demo_session_authenticates_v2_gate_not_bounced_to_login(client):
    """Core F05 pin: the demo session that opens /library must pass the
    Workbook V2 authentication gate. Without a project the V2 route's
    downstream policy redirects to /library — never to /login."""
    resp = client.get("/v2/workbook", headers=_demo_headers(), follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("/library"), (
        f"demo session must resolve on /v2/workbook (got redirect to {resp.headers['location']})"
    )


def test_admin_session_authenticates_v2_gate(client):
    from app.auth import COOKIE_NAME
    resp = client.get(
        "/v2/workbook",
        headers={"Cookie": f"{COOKIE_NAME}={_admin_cookie_value()}"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("/library")


def test_demo_session_denied_other_users_project(client):
    """Authorization stays route-level: a demo identity may not open another
    user's project even though the session now resolves on V2."""
    demo_id = "f05demo_" + uuid.uuid4().hex[:12]
    victim_id = "f05victim_" + uuid.uuid4().hex[:12]
    code = "f05_" + uuid.uuid4().hex[:10]
    try:
        _create_project(victim_id, code)
        from app.auth import DEMO_COOKIE_NAME
        resp = client.get(
            f"/v2/workbook?project={code}",
            headers={"Cookie": f"{DEMO_COOKIE_NAME}={_demo_cookie_value(demo_id)}"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"].startswith("/library"), (
            "cross-user project access must be denied by route policy, not /login-bounced "
            "(the session itself must still resolve)"
        )
    finally:
        _delete_projects(victim_id)
        _delete_projects(demo_id)


def test_tampered_session_fails_closed_on_v2(client):
    from app.auth import COOKIE_NAME
    resp = client.get(
        "/v2/workbook",
        headers={"Cookie": f"{COOKIE_NAME}=tampered-{uuid.uuid4().hex}"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("/login"), "tampered session must fail closed"


def test_tampered_demo_session_fails_closed_on_library(client):
    from app.auth import DEMO_COOKIE_NAME
    resp = client.get(
        "/library",
        headers={"Cookie": f"{DEMO_COOKIE_NAME}=tampered-{uuid.uuid4().hex}"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("/login"), (
        "tampered demo cookie must fail closed (no re-provisioning while a cookie exists)"
    )


def test_demo_redirect_chain_never_touches_login(client):
    """Redirect-chain proof: /v2/workbook with a valid demo session and no
    project follows its documented policy redirect to /library, which accepts
    the same demo identity — the chain must end 200 on /library."""
    resp = client.get("/v2/workbook", headers=_demo_headers(), follow_redirects=True)
    assert resp.status_code == 200
    chain_urls = [str(r.url) for r in getattr(resp, "history", [])] + [str(resp.url)]
    assert not any("/login" in u for u in chain_urls), (
        f"demo session chain must never hit /login: {chain_urls}"
    )
