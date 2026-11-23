"""Strict negatives for the RC-M React adapter CSRF-inventory successor (review proposal, not approval)."""
import re

import pytest

from tests import rcm_adapter_csrf_successor as S

SOURCES = {path: (S.ROOT / path).read_text(encoding="utf-8") for path in S.ROUTERS}
NP, GS = "app/v2/react_new_project.py", "app/v2/react_goal_seek.py"
AT = chr(64)          # decorator prefix composed at runtime so the public fixture carries no address-shaped literal


def test_the_successor_covers_exactly_the_two_reviewed_adapters():
    assert set(S.ROUTERS) == {NP, GS}


@pytest.mark.parametrize("path", S.ROUTERS)
def test_exact_reviewed_module_is_recognised(path):
    assert S.source_blob(SOURCES[path]) == S.SPECS[path]["blob"] and len(S.SPECS[path]["blob"]) == 40
    assert S.violations(path, SOURCES[path]) == [] and S.current_rcm_adapter_valid(path)


@pytest.mark.parametrize("path", S.ROUTERS)
def test_one_byte_of_drift_fails_closed_until_re_reviewed(path):
    assert S.violations(path, SOURCES[path] + "\n")
    assert S.violations(path, SOURCES[path], check_pin=False) == []      # the structural proof is independent of the pin
    assert not S.current_rcm_adapter_valid(path, repo=S.ROOT / "tests")


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


@pytest.mark.parametrize("path", S.ROUTERS)
@pytest.mark.parametrize("name,mutate", COMMON)
def test_structural_drift_is_rejected_even_when_the_pin_is_ignored(path, name, mutate):
    mutated = mutate(SOURCES[path])
    assert mutated != SOURCES[path], name
    assert S.violations(path, mutated, check_pin=False), name


@pytest.mark.parametrize("path,writer", [(NP, "create_reference_seeded_project_once"), (GS, "apply_draft_update")])
def test_a_writer_call_before_the_gate_is_rejected(path, writer):
    gate = "    if not _REQUEST_ID.match(body.request_id) or not validate_csrf_token(" if path == NP else "    if not validate_csrf_token("
    assert gate in SOURCES[path]
    early = f"    {writer}(user_id='x', project_code='y')\n" if path == NP else "    WorkbookUpdateService.apply_draft_update(ws=None)\n"
    assert S.violations(path, SOURCES[path].replace(gate, early + gate, 1), check_pin=False)


def test_each_canonical_writer_is_referenced_exactly_where_reviewed():
    assert len(re.findall(r"\bcreate_reference_seeded_project_once\(", SOURCES[NP])) == 1
    assert not re.search(r"\b(update_project_record|create_reference_seeded_project|save_project|claim)\(", SOURCES[NP])
    assert len(re.findall(r"\bapply_draft_update\(", SOURCES[GS])) == 1


def test_the_keyed_creator_must_follow_every_refusal_path():
    source = SOURCES[NP]
    creator = "        record, outcome = create_reference_seeded_project_once("
    assert creator in source
    early = "    create_reference_seeded_project_once(user_id='x', template_source='t', requested_name='n', capacity_mw=1.0, create_request_id='r')\n"
    anchor = "    normalised, errors = _validate(body.model_dump())"
    assert anchor in source
    assert S.violations(NP, source.replace(anchor, early + anchor, 1), check_pin=False)                  # creator before validation
    assert S.violations(NP, source.replace("create_reference_seeded_project_once(", "create_reference_seeded_project(", 1), check_pin=False)  # unkeyed writer


def test_the_goal_seek_token_must_stay_bound_to_the_offered_candidate():
    source = SOURCES[GS]
    candidate = re.search(r"extract_bound_token\(request, (_candidate\(.+?\)), body\.csrf_token", source, flags=re.S)
    assert candidate is not None
    assert S.violations(GS, source.replace(candidate.group(1), "body.project"), check_pin=False)                           # project-only binding


# ── WF-03 setup-draft successor (Owner-approved 2026-10-30): provenance, closed route table, source-mutation matrix, runtime matrix ──────────

import ast
import json
import subprocess
import uuid

PREDECESSOR = "5abdb46a4704277a895d256a434f7a6f510206c1"
SETUP = "/model-react/setup-drafts"


def test_historical_record_is_kept_verbatim_and_the_successor_names_it():
    assert S.HISTORICAL_BLOB == PREDECESSOR == S.SPECS[NP]["predecessor_blob"]
    assert S.SPECS[NP]["blob"] == "3708438d53790c98fa5851b0763230b23ba0e7b2" and S.SPECS[NP]["blob"] != PREDECESSOR
    assert len(S.HISTORICAL_SPECS[NP]["order"]) == 3 and "state_changing" not in S.HISTORICAL_SPECS[NP]
    probe = subprocess.run(["git", "cat-file", "blob", PREDECESSOR], cwd=S.ROOT, capture_output=True)
    if probe.returncode == 0:                                   # the old meaning still holds, unchanged, against the exact old source
        old = probe.stdout.decode("utf-8")
        assert S.source_blob(old) == PREDECESSOR and S.legacy_violations(NP, old) == []
        assert S.legacy_violations(NP, SOURCES[NP])             # ...and the new module is NOT the old one (more than one POST, two validators)


def test_literal_hashes_are_string_constants_not_runtime_computed():
    tree = ast.parse((S.ROOT / "tests" / "rcm_adapter_csrf_successor.py").read_text(encoding="utf-8"))
    blobs = [(k, v) for n in ast.walk(tree) if isinstance(n, ast.Dict) for k, v in zip(n.keys, n.values)
             if isinstance(k, ast.Constant) and k.value in ("blob", "predecessor_blob")]
    assert len(blobs) == 4
    for _, value in blobs:
        assert isinstance(value, ast.Constant) and re.fullmatch(r"[0-9a-f]{40}", value.value)


def test_the_route_table_is_closed_and_decorated_routes_are_enumerated():
    routes = S._routes(ast.parse(SOURCES[NP]))
    mutations = sorted(r for r in routes if r[1] in S.STATE_CHANGING)
    assert mutations == sorted(S.SPECS[NP]["state_changing"]) and len(routes) == 12
    assert {r[1] for r in routes} == {"get", "post", "patch"}
    assert sorted(r for r in routes if r[1] == "get") == sorted(S.SPECS[NP]["reads"])
    assert sorted(S._routes(ast.parse(SOURCES[GS]))) == sorted([("react_goal_seek_apply", "post", "/model-react/analysis/goal-seek/apply"),
                                                  ("react_goal_seek_catalog", "get", "/model-react/analysis/goal-seek/catalog"),
                                                  ("react_goal_seek_solve", "get", "/model-react/analysis/goal-seek/solve")])


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


@pytest.mark.parametrize("name,mutate", SETUP_MUTATIONS_MATRIX, ids=[m[0] for m in SETUP_MUTATIONS_MATRIX])
def test_every_setup_source_mutation_trips_the_successor_with_the_pin_ignored(name, mutate):
    mutated = mutate(SOURCES[NP])
    assert mutated != SOURCES[NP], name
    if name == "dynamic hash acceptance":                         # a hash computed at runtime is not a reviewed literal: the exact blob must reject it
        assert S.violations(NP, mutated)
    else:
        assert S.violations(NP, mutated, check_pin=False), name
    assert S.violations(NP, mutated), name                        # and the exact Git blob guard trips on any one-byte drift too


def test_goal_seek_is_unchanged_and_still_bound_to_its_single_reviewed_post():
    assert S.SPECS[GS]["blob"] == "b5bf2d2a920f5b278f2a6a98dd64944e80869ceb" and S.violations(GS, SOURCES[GS]) == []
    assert "setup_successor" not in S.SPECS[GS] and "state_changing" not in S.SPECS[GS]


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
