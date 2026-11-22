"""Strict negatives for the RC-M React adapter CSRF-inventory successor (review proposal, not approval)."""
import re

import pytest


NP, GS = "app/v2/react_new_project.py", "app/v2/react_goal_seek.py"
AT = chr(64)          # decorator prefix composed at runtime so the public fixture carries no address-shaped literal


COMMON = [
    ("gate removed", lambda s: s.replace("not validate_csrf_token(", "validate_csrf_token(")),
    ("gate answers 200", lambda s: re.sub(r'(_json\(\{"ok": False, "code": "CSRF_INVALID"\}), 403\)', r"\1, 200)", s)),
    ("unbound token", lambda s: re.sub(r"extract_bound_token\(request, .+?, body\.csrf_token, purpose=PURPOSE\)", "body.csrf_token", s, flags=re.S)),
    ("second validator", lambda s: s + "\n\ndef x(t):\n    return validate_csrf_token(t)\n"),
    ("extra POST", lambda s: s + '\n\n' + AT + 'router.post("/model-react/x/other")\nasync def other(request: Request):\n    return _json({})\n'),
    ("extra GET", lambda s: s + '\n\n' + AT + 'router.get("/model-react/x/other")\nasync def other(request: Request):\n    return _json({})\n'),
    ("sql reference", lambda s: s + "\n_SQL = 'INSERT INTO projects'\n"),
    ("cursor reference", lambda s: s + "\n_x = get_cursor\n"),
    ("auth removed", lambda s: s.replace("resolve_request_session", "resolve_something_else")),
]


# ── WF-03 setup-draft successor (Owner-approved 2026-10-30): provenance, closed route table, source-mutation matrix, runtime matrix ──────────

import ast
import json
import subprocess
import uuid

PREDECESSOR = "5abdb46a4704277a895d256a434f7a6f510206c1"
SETUP = "/model-react/setup-drafts"


SETUP_AUTH = '    if operation is not None:\n'
SETUP_MUTATIONS_MATRIX = [
    ("omitted gate", lambda s: s.replace(SETUP_AUTH, "    if False:\n")),
    ("validator called but response accepted", lambda s: s.replace('"CSRF_INVALID"}, 403)', '"CSRF_INVALID"}, 200)')),
    ("changed purpose", lambda s: s.replace('purpose="wf03-setup:"+operation', 'purpose="wf03-setup:CREATE"')),
    ("changed resource", lambda s: s.replace("extract_bound_token(request, resource,", 'extract_bound_token(request, "new-setup",')),
    ("origin ignored", lambda s: s.replace('origin and origin.rstrip("/") != str(request.base_url).rstrip("/")', "False")),
    ("sec-fetch-site ignored", lambda s: s.replace('request.headers.get("sec-fetch-site") == "cross-site"', "False")),
    ("ownership skipped", lambda s: s.replace('if resource != "new-setup":', "if False:")),
    ("ownership by draft only", lambda s: s.replace("WHERE user_id=? AND draft_id=?", "WHERE draft_id=?")),
    ("wrong owner answers 200", lambda s: s.replace('"SETUP_DRAFT_NOT_FOUND"},404)', '"SETUP_DRAFT_NOT_FOUND"},200)')),
    ("client-supplied owner", lambda s: s.replace("(user.user_id,resource)", "(request.headers.get('x-owner'),resource)")),
    ("operation mapping", lambda s: s.replace('op="PROMOTE" if promotion else "UPDATE" if draft_id else "CREATE"', 'op="UPDATE"')),
    ("cross-owner token (user id instead of session resource)", lambda s: s.replace("_setup_auth(request,resource,op)", "_setup_auth(request,'new-setup',op)")),
    ("changed method", lambda s: s.replace('@router.patch("/model-react/setup-drafts/{draft_id}")', '@router.put("/model-react/setup-drafts/{draft_id}")')),
    ("new unreviewed mutation", lambda s: s + "\n\n" + AT + 'router.delete("/model-react/setup-drafts/{draft_id}")\nasync def setup_draft_delete(request: Request, draft_id: str):\n    return await _setup_write(request, draft_id)\n'),
    ("additional validator", lambda s: s + "\n\ndef _extra(t):\n    return validate_csrf_token(t)\n"),
    ("additional writer", lambda s: s.replace("    user, refused=_setup_auth(request,resource,op)\n", "    user, refused=_setup_auth(request,resource,op)\n    from app.persistence.setup_draft_repository import write as _w\n    _w(user.user_id, {}, None)\n")),
    ("writer before auth", lambda s: s.replace("    user, refused=_setup_auth(request,resource,op)\n", "    write('x', {}, None)\n    user, refused=_setup_auth(request,resource,op)\n")),
    ("writer before the body gates", lambda s: s.replace("    try:\n        if request.headers.get(\"content-type\"", "    write(user.user_id, {}, None)\n    try:\n        if request.headers.get(\"content-type\"")),
    ("writer in the ownership step", lambda s: s.replace("        from app.persistence.db import get_cursor\n", "        from app.persistence.db import get_cursor\n        write(user.user_id, {}, resource)\n")),
    ("content type unchecked", lambda s: s.replace('!= "application/json"', '!= "application/json" and False')),
    ("body unbounded", lambda s: s.replace("if len(raw)>200_000: raise", "if False: raise")),
    ("GET that writes", lambda s: s.replace("draft=read(user.user_id,draft_id)", "draft=write(user.user_id,{},draft_id)")),
    ("GET with an operation", lambda s: s.replace("_setup_auth(request,draft_id)\n    if refused is not None: return refused\n    from app.persistence.setup_draft_repository import request_status",
                                                  "_setup_auth(request,draft_id,'UPDATE')\n    if refused is not None: return refused\n    from app.persistence.setup_draft_repository import request_status")),
    ("unchecked helper routing", lambda s: s + "\n\nasync def _alias(request):\n    return await _setup_write(request)\n"),
    ("handler bypasses _setup_write", lambda s: s.replace("return await _setup_write(request,draft_id,promotion=True)", "return await _setup_write(request,draft_id)")),
    ("registration alias", lambda s: s + "\nrouter.add_api_route('/model-react/setup-drafts/x', setup_draft_create, methods=['POST'])\n"),
    ("unreviewed purpose", lambda s: s.replace('purpose="wf03-setup:CREATE"', 'purpose="wf03-setup:ANY"')),
    ("extra cursor read", lambda s: s.replace("    return user, None\n", "    from app.persistence.db import get_cursor\n    with get_cursor() as cur:\n        cur.execute('SELECT 1')\n    return user, None\n")),
    ("dynamic hash acceptance", lambda s: s + "\nimport hashlib\nACCEPT = hashlib.sha1(open(__file__, 'rb').read()).hexdigest()\n"),
]


# ── runtime: real FastAPI calls, a disposable database, direct row counts ────────────────────────────────────────────────────────────────

CANONICAL = ("projects", "workspace_states", "scenarios", "model_run_history", "model_run_intents", "save_all_requests")


@pytest.fixture
def stack(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import auth
    from app.persistence import db
    from app.v2 import react_new_project

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "setup.sqlite"))
    db.init_db()
    app = FastAPI()
    app.include_router(react_new_project.router)

    def client(user):
        c = TestClient(app, base_url="http://testserver")
        if user:
            c.cookies.set(auth.DEMO_COOKIE_NAME, auth.create_demo_session_token(user))
        return c

    def counts():
        with db.get_cursor() as cur:
            return {t: cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in CANONICAL + ("setup_drafts",)}

    def draft_rows():
        with db.get_cursor() as cur:
            return [tuple(r) for r in cur.execute("SELECT * FROM setup_drafts ORDER BY draft_id").fetchall()]

    return type("Stack", (), {"client": staticmethod(client), "counts": staticmethod(counts), "rows": staticmethod(draft_rows), "db": db})


def _body(**extra):
    return {"request_id": uuid.uuid4().hex, "technology": "wind", "name": "Runtime setup", "country": "",
            "fields": {"project_setup.technical.capacity_mw": "40"}, **extra}


def _create(c):
    token = c.get(SETUP).json()["csrf_token"]
    assert token
    body = _body()
    resp = c.post(SETUP, json=body, headers={"x-csrf-token": token})
    assert resp.status_code == 200, resp.text
    return body, resp.json()["draft"]["draft_id"]


def _tokens(c, draft_id):
    return c.get(f"{SETUP}/{draft_id}").json()["tokens"]


def test_runtime_anonymous_and_cross_site_requests_fail_before_any_write(stack):
    owner = stack.client("demo_owner_a")
    token = owner.get(SETUP).json()["csrf_token"]
    anon = stack.client(None)
    before = stack.counts()
    for resp in (anon.post(SETUP, json=_body()), anon.patch(f"{SETUP}/x", json=_body()), anon.post(f"{SETUP}/x/promote", json=_body())):
        assert resp.status_code == 401
    for headers in ({"origin": "https://evil.example"}, {"sec-fetch-site": "cross-site"}):
        resp = owner.post(SETUP, json=_body(), headers={"x-csrf-token": token, **headers})
        assert resp.status_code == 403 and resp.json()["code"] == "CSRF_INVALID"
    assert stack.counts() == before and before["setup_drafts"] == 0 and not any(before[t] for t in CANONICAL)


def test_runtime_tokens_are_bound_to_session_resource_and_purpose(stack):
    a, b = stack.client("demo_owner_a"), stack.client("demo_owner_b")
    body, draft = _create(a)
    tokens = _tokens(a, draft)
    create_token = a.get(SETUP).json()["csrf_token"]
    snapshot = stack.rows()
    update = {**_body(), "draft_version": 0}
    bad = {"missing": {}, "forged": {"x-csrf-token": "forged.token"}, "empty": {"x-csrf-token": ""},
           "cross-purpose (promote token on update)": {"x-csrf-token": tokens["promote"]},
           "cross-purpose (create token on update)": {"x-csrf-token": create_token},
           "tampered": {"x-csrf-token": tokens["update"][:-1] + ("0" if tokens["update"][-1] != "0" else "1")}}
    for name, headers in bad.items():
        resp = a.patch(f"{SETUP}/{draft}", json=update, headers=headers)
        assert resp.status_code == 403 and resp.json()["code"] == "CSRF_INVALID", name
    # update token on promote, and on the creation route
    assert a.post(f"{SETUP}/{draft}/promote", json={"request_id": uuid.uuid4().hex, "draft_version": 0}, headers={"x-csrf-token": tokens["update"]}).status_code == 403
    assert a.post(SETUP, json=_body(), headers={"x-csrf-token": tokens["update"]}).status_code == 403
    # another draft of the same owner (wrong resource)
    _, other = _create(a)
    assert a.patch(f"{SETUP}/{draft}", json=update, headers={"x-csrf-token": _tokens(a, other)["update"]}).status_code == 403
    # another session: a valid-looking token of A is not B's, and B does not own the draft
    assert b.patch(f"{SETUP}/{draft}", json=update, headers={"x-csrf-token": tokens["update"]}).status_code == 404
    assert [r for r in stack.rows() if r[0] == draft or draft in r] == [r for r in snapshot if draft in r]
    assert not any(stack.counts()[t] for t in CANONICAL)


def test_runtime_owner_isolation_does_not_reveal_existence(stack):
    a, b = stack.client("demo_owner_a"), stack.client("demo_owner_b")
    _, draft = _create(a)
    b_token = b.get(SETUP).json()["csrf_token"]
    ghost = "d" * 32
    before = stack.rows()
    seen = []
    for method, suffix in (("get", ""), ("get", "/status"), ("get", "/readiness"), ("patch", ""), ("post", "/promote")):
        for target in (draft, ghost):
            kwargs = {} if method == "get" else {"json": {**_body(), "draft_version": 0}, "headers": {"x-csrf-token": b_token}}
            resp = getattr(b, method)(f"{SETUP}/{target}{suffix}", **kwargs)
            seen.append((method, suffix, resp.status_code, json.dumps(resp.json(), sort_keys=True)))
    for i in range(0, len(seen), 2):
        assert seen[i] == seen[i + 1] and seen[i][2] == 404          # a foreign draft and a missing draft are indistinguishable
    assert stack.rows() == before


def test_runtime_body_gates_leave_no_state_change(stack):
    a = stack.client("demo_owner_a")
    token = a.get(SETUP).json()["csrf_token"]
    before = stack.counts()
    json_h = {"x-csrf-token": token, "content-type": "application/json"}
    cases = {"form content type": dict(content=b"a=b", headers={"x-csrf-token": token, "content-type": "application/x-www-form-urlencoded"}),
             "malformed json": dict(content=b"{not json", headers=json_h),
             "oversized": dict(content=b'{"x":"' + b"a" * 200_100 + b'"}', headers=json_h),
             "unknown keys": dict(content=json.dumps({**_body(), "extra": 1}).encode(), headers=json_h),
             "unreviewed field": dict(content=json.dumps(_body(fields={"unreviewed.hidden.economics": "1"})).encode(), headers=json_h)}
    for name, kwargs in cases.items():
        resp = a.post(SETUP, **kwargs)
        assert resp.status_code in (400, 413, 422), (name, resp.status_code)
    assert stack.counts() == before


def test_runtime_replay_changed_body_stale_cas_and_promotion_leave_no_canonical_rows(stack):
    a = stack.client("demo_owner_a")
    token = a.get(SETUP).json()["csrf_token"]
    body = _body()
    first = a.post(SETUP, json=body, headers={"x-csrf-token": token})
    assert first.status_code == 200
    draft = first.json()["draft"]["draft_id"]
    replay = a.post(SETUP, json=body, headers={"x-csrf-token": token})
    assert replay.status_code == 200 and replay.json()["replayed"] and stack.counts()["setup_drafts"] == 1
    changed = a.post(SETUP, json={**body, "name": "Changed"}, headers={"x-csrf-token": token})
    assert changed.status_code >= 400 and "SETUP_KEY_REUSED" in changed.text and stack.counts()["setup_drafts"] == 1
    tokens = _tokens(a, draft)
    update = {**_body(), "draft_version": 0, "name": "Tab A"}
    assert a.patch(f"{SETUP}/{draft}", json=update, headers={"x-csrf-token": tokens["update"]}).status_code == 200
    assert a.patch(f"{SETUP}/{draft}", json=update, headers={"x-csrf-token": tokens["update"]}).json()["replayed"]
    stale = a.patch(f"{SETUP}/{draft}", json={**update, "request_id": uuid.uuid4().hex, "name": "Tab B"}, headers={"x-csrf-token": tokens["update"]})
    assert stale.status_code >= 400 and "SETUP_STALE" in stale.text
    assert a.get(f"{SETUP}/{draft}").json()["draft"]["name"] == "Tab A"          # the stale tab did not overwrite the draft
    promote = a.post(f"{SETUP}/{draft}/promote", json={"request_id": uuid.uuid4().hex, "draft_version": 1}, headers={"x-csrf-token": _tokens(a, draft)["promote"]})
    assert promote.status_code >= 400 and "UNSEEDED_PROMOTION_UNPROVEN" in promote.text
    counts = stack.counts()
    assert counts["setup_drafts"] == 1 and not any(counts[t] for t in CANONICAL)    # no runnable project, no financial or Run row


def test_runtime_get_routes_never_change_state(stack):
    a = stack.client("demo_owner_a")
    _, draft = _create(a)
    before_rows, before_counts = stack.rows(), stack.counts()
    with stack.db.get_cursor() as cur:
        changes = cur.connection.total_changes
    for url in (SETUP, f"{SETUP}/status", f"{SETUP}/{draft}", f"{SETUP}/{draft}/readiness", f"{SETUP}/{draft}/status"):
        assert a.get(url).status_code in (200, 404, 422), url
    assert stack.rows() == before_rows and stack.counts() == before_counts
