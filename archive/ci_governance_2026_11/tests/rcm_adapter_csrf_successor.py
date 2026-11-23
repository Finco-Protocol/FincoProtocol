"""RC-M React adapter CSRF-inventory SUCCESSOR PROPOSAL (exact content), not independent approval.

``tests/test_trust_readiness_controls.py::test_known_gap_state_changing_posts_have_no_csrf_token`` pins the set of files that call
``validate_csrf_token(``.  The RC-M React adapters add exactly two such files, each with exactly ONE state-changing route:

  * ``app/v2/react_new_project.py``  — ``POST /model-react/new-project/create``  (creates one working copy)
  * ``app/v2/react_goal_seek.py``    — ``POST /model-react/analysis/goal-seek/apply``  (the canonical CAS tariff write)

Like WF-09 and RC-7B each is admitted ONLY while its own exact content and structure hold:

  * the module is byte-identical to the reviewed blob pinned below (any edit fails closed until re-reviewed);
  * the single POST handler authenticates the session first, then applies ONE explicit
    ``if ... not validate_csrf_token(extract_bound_token(..., purpose=PURPOSE))`` gate that answers 403, BEFORE project resolution,
    demo rate limit, field validation and every writer (the token is a JSON field, so the body is parsed first and
    refused as 400 on any shape error without touching state);
  * the token is the signed, session-and-resource-bound one under its own purpose;
  * persistence is reached ONLY through the named writer(s) — the canonical request-keyed creator / the CAS writer —
    each called exactly once, from the POST handler, in the reviewed order (validation, demo limiter, keyed creator);
  * every other route is a GET; no SQL, cursor, workspace-writer or Run-recording reference.

This is a REVIEW PROPOSAL.  It does not authorise a merge; the independent reviewer must still approve it and re-pin a module if it
changes.  Nothing here weakens the CSRF inventory for any other file.

SUCCESSOR LAYER (WF-03, Financial Owner approved 2026-10-30; implementation only, not a merge).  ``app/v2/react_new_project.py`` grew a separate
setup-draft flow.  Its reviewed contract is no longer "one POST, one validator", so the entry for that module is now a FINITE successor:

  * HISTORICAL_SPECS keeps the previous reviewed record verbatim (blob 5abdb46a..., exactly one POST /model-react/new-project/create).  The legacy
    rules still run, unchanged, against that exact historical source (``legacy_violations``); the old meaning is preserved, not re-pinned away.
  * SPECS holds the current literal blob and the CLOSED route table: four state-changing routes (the legacy create plus the three setup-draft
    mutations below), eight read-only routes, exactly two ``validate_csrf_token`` call sites, exactly one cursor read (the ownership SELECT).
  * ``_setup_violations`` proves the setup-draft call chain structurally (``_setup_auth`` -> ``_setup_write`` -> exactly one writer) and
    tests/test_rcm_adapter_csrf_successor.py proves it at runtime with real FastAPI calls against a disposable database.

  POST   /model-react/setup-drafts                      wf03-setup:CREATE   resource ``new-setup``  -> setup_draft_repository.write(user, body, None)
  PATCH  /model-react/setup-drafts/{draft_id}           wf03-setup:UPDATE   resource ``draft_id``   -> setup_draft_repository.write(user, body, draft_id)
  POST   /model-react/setup-drafts/{draft_id}/promote   wf03-setup:PROMOTE  resource ``draft_id``   -> setup_draft_repository.promote(user, draft_id, body)

``app/v2/react_goal_seek.py`` is unchanged: same blob, same spec.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_CHANGING = frozenset({"post", "put", "patch", "delete"})
COMMON_FORBIDDEN = (".execute(", "get_cursor", "INSERT", "UPDATE ", "DELETE ", "save_workspace", "set_workspace",
                    "record_workspace_runtime", "save_run", "ModelExecutor", "apply_batch_draft_update")

# IMMUTABLE HISTORICAL RECORD of the previously reviewed react_new_project spec (provenance + legacy negative meaning). Never edited, never re-pinned.
HISTORICAL_SPECS = {
    "app/v2/react_new_project.py": {
        "blob": "5abdb46a4704277a895d256a434f7a6f510206c1",
        "handler": "react_new_project_create", "path": "/model-react/new-project/create",
        "reads": [("react_new_project_options", "get", "/model-react/new-project/options"),
                  ("react_new_project_preview", "get", "/model-react/new-project/preview"),
                  ("react_new_project_status", "get", "/model-react/new-project/status")],
        "auth": "_gate", "gate_token": "body.request_id",
        "later": {"field validation": "_validate", "demo rate limit": "check_demo_rate_limit",
                  "atomic keyed creator": "create_reference_seeded_project_once"},
        # every refusal path precedes the single canonical, request-keyed creator (the request identity is committed by its own row write)
        "order": ("_validate", "check_demo_rate_limit", "create_reference_seeded_project_once"),
        "writers": ("create_reference_seeded_project_once",),
        "forbidden": COMMON_FORBIDDEN + ("run_project",),
    },
}
HISTORICAL_BLOB = HISTORICAL_SPECS["app/v2/react_new_project.py"]["blob"]

# LITERAL REVIEW PINS of each module's git blob (not computed at runtime from a mutable baseline).
SPECS = {
    "app/v2/react_new_project.py": {
        # WF-03 successor: the CURRENT literal reviewed blob (the predecessor is HISTORICAL_BLOB; neither is ever computed at runtime).
        "blob": "3708438d53790c98fa5851b0763230b23ba0e7b2",
        "predecessor_blob": "5abdb46a4704277a895d256a434f7a6f510206c1",
        "handler": "react_new_project_create", "path": "/model-react/new-project/create",
        # The CLOSED set of state-changing routes: (handler, method, literal path). No other mutation, alias or registration form is admitted.
        "state_changing": [("react_new_project_create", "post", "/model-react/new-project/create"),
                           ("setup_draft_create", "post", "/model-react/setup-drafts"),
                           ("setup_draft_update", "patch", "/model-react/setup-drafts/{draft_id}"),
                           ("setup_draft_promote", "post", "/model-react/setup-drafts/{draft_id}/promote")],
        "validator_sites": 2,          # react_new_project_create (legacy, request-id bound) + _setup_auth (wf03-setup:<operation>, resource bound)
        "reads": [("react_new_project_options", "get", "/model-react/new-project/options"),
                  ("react_new_project_preview", "get", "/model-react/new-project/preview"),
                  ("react_new_project_status", "get", "/model-react/new-project/status"),
                  ("setup_creation_status", "get", "/model-react/setup-drafts/status"),
                  ("setup_draft_get", "get", "/model-react/setup-drafts/{draft_id}"),
                  ("setup_draft_index", "get", "/model-react/setup-drafts"),
                  ("setup_draft_status", "get", "/model-react/setup-drafts/{draft_id}/status"),
                  ("setup_readiness", "get", "/model-react/setup-drafts/{draft_id}/readiness")],
        "auth": "_gate", "gate_token": "body.request_id",
        "later": {"field validation": "_validate", "demo rate limit": "check_demo_rate_limit",
                  "atomic keyed creator": "create_reference_seeded_project_once"},
        "order": ("_validate", "check_demo_rate_limit", "create_reference_seeded_project_once"),
        "writers": ("create_reference_seeded_project_once",),
        # The setup flow's single ownership read is allowed and counted in _setup_violations (one get_cursor, one execute of ONE literal SELECT);
        # every other cursor/SQL/Run reference stays forbidden.
        "forbidden": tuple(n for n in COMMON_FORBIDDEN if n not in (".execute(", "get_cursor")) + ("run_project",),
        "setup_successor": True,
    },
    "app/v2/react_goal_seek.py": {
        "blob": "b5bf2d2a920f5b278f2a6a98dd64944e80869ceb",
        "handler": "react_goal_seek_apply", "path": "/model-react/analysis/goal-seek/apply",
        "reads": [("react_goal_seek_catalog", "get", "/model-react/analysis/goal-seek/catalog"),
                  ("react_goal_seek_solve", "get", "/model-react/analysis/goal-seek/solve")],
        "auth": "resolve_request_session",
        "gate_token": "_candidate(body.project, body.field_id, body.value, body.content_hash, body.workbook_version)",
        "later": {"project resolution": "resolve_accessible_project", "workspace read": "get_workspace_state",
                  "canonical CAS writer": "apply_draft_update"},
        "writers": ("apply_draft_update",),
        "forbidden": COMMON_FORBIDDEN,
    },
}
ROUTERS = tuple(SPECS)


def source_blob(source: str) -> str:
    data = source.encode("utf-8")
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def _is_validator_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "validate_csrf_token"


def _routes(tree: ast.Module) -> list[tuple[str, str, str]]:
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and isinstance(dec.func.value, ast.Name)
                        and dec.func.value.id == "router" and dec.args and isinstance(dec.args[0], ast.Constant)):
                    out.append((node.name, dec.func.attr, dec.args[0].value))
    return out


def _calls(fn, name):
    """Calls of ``name`` as a bare function or as a method/attribute (``Service.name(...)``)."""
    return [n for n in ast.walk(fn) if isinstance(n, ast.Call)
            and ((isinstance(n.func, ast.Name) and n.func.id == name) or (isinstance(n.func, ast.Attribute) and n.func.attr == name))]


def violations(path: str, source: str, *, check_pin: bool = True) -> list[str]:
    """[] means the exact reviewed module content and structure hold; it does NOT mean released or approved."""
    spec = SPECS[path]
    errors = _generic_violations(spec, source, check_pin)
    if spec.get("setup_successor"):
        errors += _setup_violations(source)
    return errors


def legacy_violations(path: str, source: str, *, check_pin: bool = True) -> list[str]:
    """The HISTORICAL rules (one POST, one validator, no cursor) applied unchanged to the historical source of ``path``."""
    return _generic_violations(HISTORICAL_SPECS[path], source, check_pin)


_REGISTRATION_FORMS = frozenset({"api_route", "add_api_route", "add_route", "route", "websocket", "add_websocket_route", "include_router", "mount"})


def _generic_violations(spec: dict, source: str, check_pin: bool) -> list[str]:
    errors: list[str] = []
    try:
        if check_pin and source_blob(source) != spec["blob"]:
            errors.append("module content is not the exact reviewed blob")
        tree = ast.parse(source)
        if len([n for n in ast.walk(tree) if _is_validator_call(n)]) != spec.get("validator_sites", 1):
            errors.append("expected exactly one validate_csrf_token call site" if spec.get("validator_sites", 1) == 1
                          else f"expected exactly {spec['validator_sites']} validate_csrf_token call sites")
        routes = _routes(tree)
        reviewed = sorted(spec.get("state_changing") or [(spec["handler"], "post", spec["path"])])
        if sorted(r for r in routes if r[1] in STATE_CHANGING) != reviewed:
            errors.append("state-changing routes differ from the one reviewed POST" if len(reviewed) == 1
                          else "state-changing routes differ from the closed reviewed set")
        # No alias, api_route/add_api_route/include_router form, or router verb call that is not a plain decorator on a reviewed handler.
        verb_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                      and isinstance(n.func.value, ast.Name) and n.func.value.id == "router"]
        if any(c.func.attr in _REGISTRATION_FORMS for c in verb_calls) or len(verb_calls) != len(routes):
            errors.append("unreviewed route registration form")
        if sorted(r for r in routes if r[1] not in STATE_CHANGING) != sorted(spec["reads"]):
            errors.append("unexpected additional route")
        fns = {n.name: n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)}
        fn = fns.get(spec["handler"])
        if fn is None:
            return errors + ["POST handler missing"]
        gate_if = next((n for n in fn.body if isinstance(n, ast.If) and any(_is_validator_call(c) for c in ast.walk(n.test))), None)
        check = next((n for n in ast.walk(fn) if _is_validator_call(n)), None)
        if gate_if is None or check is None:
            return errors + ["CSRF failure must be an explicit gate"]
        test = ast.unparse(gate_if.test)
        if "not validate_csrf_token(" not in test or "extract_bound_token(" not in test or "purpose=PURPOSE" not in test \
                or f"request, {spec['gate_token']}" not in test:
            errors.append("the gate must refuse an unbound token (`not validate_csrf_token(extract_bound_token(request, <resource>, ..., purpose=PURPOSE))`)")
        if not [n for n in gate_if.body if isinstance(n, ast.Return) and "403" in ast.unparse(n)]:
            errors.append("a failed CSRF token must return 403")
        auth = _calls(fn, spec["auth"])
        if not auth or auth[0].lineno > check.lineno:
            errors.append(f"authentication ({spec['auth']}) must run before the CSRF check")
        for label, name in spec["later"].items():
            nodes = _calls(fn, name)
            if not nodes or any(n.lineno < check.lineno for n in nodes):
                errors.append(f"CSRF check must precede the {label}")
        firsts = [min((n.lineno for n in _calls(fn, name)), default=0) for name in spec.get("order", ())]
        if firsts and (0 in firsts or firsts != sorted(firsts) or len(set(firsts)) != len(firsts)):
            errors.append("handler step order differs from the reviewed fence-then-claim-then-write order")
        for writer in spec["writers"]:
            elsewhere = any(len(_calls(f, writer)) for name, f in fns.items() if name != spec["handler"])
            sync_elsewhere = any(len(_calls(f, writer)) for f in tree.body if isinstance(f, ast.FunctionDef))
            if len(_calls(fn, writer)) != 1 or elsewhere or sync_elsewhere:
                errors.append(f"{writer} must be called exactly once, from the POST handler")
        if "resolve_request_session" not in {c.func.id for c in ast.walk(tree) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}:
            errors.append("the adapter must authenticate the session through resolve_request_session")
        for needle in spec["forbidden"]:
            if needle in source:
                errors.append(f"forbidden write/Run reference: {needle}")
    except (SyntaxError, ValueError, TypeError, AttributeError, IndexError):
        errors.append("module source evidence incomplete or malformed")
    return errors


# ── WF-03 setup-draft successor: the call chain, proven structurally ─────────────────────────────────────────────────────────────────────────

OWNERSHIP_SQL = "SELECT 1 FROM setup_drafts WHERE user_id=? AND draft_id=?"
SETUP_PURPOSE_PREFIX = "wf03-setup:"
# handler -> (method, literal path, the ONE statement its body may contain). Nothing else routes to a writer.
SETUP_MUTATIONS = {
    "setup_draft_create": ("post", "/model-react/setup-drafts", "return await _setup_write(request)"),
    "setup_draft_update": ("patch", "/model-react/setup-drafts/{draft_id}", "return await _setup_write(request, draft_id)"),
    "setup_draft_promote": ("post", "/model-react/setup-drafts/{draft_id}/promote", "return await _setup_write(request, draft_id, promotion=True)"),
}
SETUP_READS = ("setup_draft_index", "setup_creation_status", "setup_draft_get", "setup_readiness", "setup_draft_status")
SETUP_WRITERS = frozenset({"write", "promote"})
# function -> the names it may import from the persistence layer (a GET can never import a writer)
SETUP_IMPORTS = {"_setup_write": {"write", "promote"}, "setup_draft_index": {"list_owned"}, "setup_creation_status": {"creation_status"},
                 "setup_draft_get": {"read"}, "setup_draft_status": {"request_status"}}


def _same(node: ast.AST, expected: str, mode: str = "eval") -> bool:
    expected_node = ast.parse(expected, mode=mode)
    expected_node = expected_node.body if mode == "eval" else expected_node.body[0]
    return ast.dump(node, include_attributes=False) == ast.dump(expected_node, include_attributes=False)


def _top(tree: ast.Module, name: str):
    return next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name), None)


def _line(fn, name: str) -> int:
    return min((c.lineno for c in _calls(fn, name)), default=0)


def _setup_violations(source: str) -> list[str]:
    """The reviewed chain: handler -> _setup_write -> _setup_auth (session, ownership, origin, signed purpose/resource-bound token) -> body gates -> ONE writer."""
    errors: list[str] = []
    try:
        tree = ast.parse(source)
        auth, write = _top(tree, "_setup_auth"), _top(tree, "_setup_write")
        if not isinstance(auth, ast.FunctionDef) or not isinstance(write, ast.AsyncFunctionDef):
            return ["setup chain functions missing or of the wrong kind"]
        if ast.unparse(auth.args) != "request, resource, operation=None" or ast.unparse(write.args) != "request, draft_id=None, promotion=False":
            errors.append("setup chain signatures changed")

        # 1. _setup_auth: session first, then ownership of (user_id, draft_id), then origin + signed token. The user id is the session's, never the client's.
        sessions, validators = _calls(auth, "resolve_request_session"), [n for n in ast.walk(auth) if _is_validator_call(n)]
        cursors = _calls(auth, "get_cursor")
        executes = [n for n in ast.walk(auth) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "execute"]
        if len(sessions) != 1 or len(validators) != 1 or len(cursors) != 1 or len(executes) != 1:
            errors.append("_setup_auth must hold exactly one session resolution, one ownership read and one validator")
            return errors
        if not (sessions[0].lineno < cursors[0].lineno <= executes[0].lineno < validators[0].lineno):
            errors.append("_setup_auth order must be session, ownership read, then CSRF")
        assign = next((n for n in auth.body if isinstance(n, ast.Assign) and n.value is sessions[0]), None)
        if assign is None or ast.unparse(assign.targets[0]) != "user":
            errors.append("the acting user must be the resolved session user")
        if not (executes[0].args and isinstance(executes[0].args[0], ast.Constant) and executes[0].args[0].value == OWNERSHIP_SQL
                and len(executes[0].args) == 2 and _same(executes[0].args[1], "(user.user_id, resource)")):
            errors.append("ownership must be the one literal SELECT on (session user_id, draft_id)")
        owner_if = next((n for n in auth.body if isinstance(n, ast.If) and executes[0] in list(ast.walk(n))), None)
        if owner_if is None or not _same(owner_if.test, "resource != 'new-setup'"):
            errors.append("ownership is checked for every draft-specific resource and only for it")
        elif not any(isinstance(r, ast.Return) and "404" in ast.unparse(r) and "SETUP_DRAFT_NOT_FOUND" in ast.unparse(r) for r in ast.walk(owner_if)):
            errors.append("a wrong-owner or unknown draft must answer the same 404")
        gate_if = next((n for n in auth.body if isinstance(n, ast.If) and validators[0] in list(ast.walk(n.test))
                        or (isinstance(n, ast.If) and any(validators[0] in list(ast.walk(x)) for x in ast.walk(n)))), None)
        csrf_if = next((n for n in ast.walk(auth) if isinstance(n, ast.If) and any(_is_validator_call(c) for c in ast.walk(n.test))), None)
        outer = next((n for n in auth.body if isinstance(n, ast.If) and csrf_if is not None and csrf_if in list(ast.walk(n))), None)
        if csrf_if is None or outer is None or not _same(outer.test, "operation is not None"):
            errors.append("the CSRF gate must apply to every operation-bearing call")
        else:
            test = ast.unparse(csrf_if.test)
            origin = next((n for n in outer.body if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "origin"), None)
            if origin is None or not _same(origin.value, "request.headers.get('origin')") or outer.body.index(origin) > outer.body.index(csrf_if):
                errors.append("the setup gate must read the Origin header before the decision")
            for needle in ("origin and origin.rstrip('/') != str(request.base_url).rstrip('/')", "request.headers.get('sec-fetch-site') == 'cross-site'",
                           "not validate_csrf_token(",
                           "extract_bound_token(request, resource, request.headers.get('x-csrf-token', ''), purpose='wf03-setup:' + operation)"):
                if needle not in test:
                    errors.append(f"the setup gate must contain {needle}")
            if not [r for r in csrf_if.body if isinstance(r, ast.Return) and "403" in ast.unparse(r) and "CSRF_INVALID" in ast.unparse(r)]:
                errors.append("a refused setup request must answer 403")
        if not (auth.body and isinstance(auth.body[-1], ast.Return) and _same(auth.body[-1].value, "(user, None)")):
            errors.append("_setup_auth must end by returning the session user")

        # 2. _setup_write: operation from (draft_id, promotion), auth, body gates, then exactly one writer expression.
        resource_assign = next((n for n in write.body if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "resource"), None)
        op_assign = next((n for n in write.body if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "op"), None)
        if resource_assign is None or not _same(resource_assign.value, "draft_id or 'new-setup'"):
            errors.append("the CSRF resource must be the draft id or the literal new-setup")
        if op_assign is None or not _same(op_assign.value, "'PROMOTE' if promotion else 'UPDATE' if draft_id else 'CREATE'"):
            errors.append("the CSRF operation mapping changed")
        auth_calls = _calls(write, "_setup_auth")
        if len(auth_calls) != 1 or not _same(auth_calls[0], "_setup_auth(request, resource, op)"):
            errors.append("_setup_write must authenticate with (request, resource, op) exactly once")
        writers = [c for c in ast.walk(write) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in SETUP_WRITERS]
        if sorted(c.func.id for c in writers) != ["promote", "write"]:
            errors.append("_setup_write must call write and promote exactly once each")
        else:
            ret = [r for r in write.body if isinstance(r, ast.Try)]
            wcall = next((r for t in ret for r in ast.walk(t) if isinstance(r, ast.Return) and any(w in list(ast.walk(r)) for w in writers)), None)
            if wcall is None or not _same(wcall.value, "_json(promote(user.user_id, draft_id, data) if promotion else write(user.user_id, data, draft_id))"):
                errors.append("the writer expression changed (the acting user is the session user; data is the bounded JSON body)")
        gates = {"auth": _line(write, "_setup_auth"), "stream": _line(write, "stream"), "loads": min(
            (c.lineno for c in ast.walk(write) if isinstance(c, ast.Call) and ast.unparse(c.func) == "json.loads"), default=0)}
        ct_if = next((n for n in ast.walk(write) if isinstance(n, ast.If) and "application/json" in ast.unparse(n.test)), None)
        big_if = next((n for n in ast.walk(write) if isinstance(n, ast.If) and "200000" in ast.unparse(n.test)), None)
        if ct_if is None or not _same(ct_if.test, "request.headers.get('content-type', '').split(';')[0].strip() != 'application/json'") \
                or "INVALID_SETUP_BODY" not in ast.unparse(ct_if):
            errors.append("the JSON content type must be enforced exactly (refusal INVALID_SETUP_BODY)")
        if big_if is None or not _same(big_if.test, "len(raw) > 200000") or "SETUP_BODY_TOO_LARGE" not in ast.unparse(big_if):
            errors.append("the body bound must be exactly 200000 bytes (refusal SETUP_BODY_TOO_LARGE)")
        content_type, too_large = getattr(ct_if, "lineno", 0), getattr(big_if, "lineno", 0)
        first_writer = min((c.lineno for c in writers), default=0)
        order = [gates["auth"], content_type, gates["stream"], too_large, gates["loads"], first_writer]
        if 0 in order or order != sorted(order) or len(set(order)) != len(order):
            errors.append("order must be auth/CSRF, content type, bounded stream, JSON parse, then the writer")
        if [n for n in ast.walk(write) if _is_validator_call(n)]:
            errors.append("_setup_write must not hold a second validator (it is reached only through _setup_auth)")

        # 3. the three mutation handlers: one literal statement each, and nothing else routes to a writer.
        by_name = {r[0]: r for r in _routes(tree)}
        for handler, (method, path, statement) in SETUP_MUTATIONS.items():
            fn = _top(tree, handler)
            if fn is None or by_name.get(handler) != (handler, method, path):
                errors.append(f"{handler} is not the reviewed {method.upper()} {path}")
            elif len(fn.body) != 1 or not _same(fn.body[0], statement, mode="exec"):
                errors.append(f"{handler} must only dispatch to _setup_write with the reviewed arguments")
        for fn in (n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            if fn.name != "_setup_write" and [c for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in SETUP_WRITERS]:
                errors.append(f"{fn.name} must not call a setup writer")
            if fn.name not in SETUP_MUTATIONS and fn.name != "_setup_write" and _calls(fn, "_setup_write"):
                errors.append(f"{fn.name} must not route to _setup_write")
            imports = [n for n in ast.walk(fn) if isinstance(n, ast.ImportFrom) and (n.module or "").endswith("setup_draft_repository")]
            if len(imports) > 1 or any(a.asname for n in imports for a in n.names):
                errors.append(f"{fn.name} must import the persistence names once and without aliases")
            imported = {a.name for n in imports for a in n.names}
            if imported != SETUP_IMPORTS.get(fn.name, set()) and imported:
                errors.append(f"{fn.name} imports unreviewed persistence names {sorted(imported)}")
        if any(n.module and n.module.endswith("setup_draft_repository") for n in tree.body if isinstance(n, ast.ImportFrom)):
            errors.append("the persistence layer may only be imported inside the reviewed functions")

        # 4. reads never carry an operation (no CSRF needed, nothing to write), and the only token purposes issued are the reviewed ones.
        for name in SETUP_READS:
            fn = _top(tree, name)
            if fn is None:
                errors.append(f"read route {name} missing")
                continue
            if name != "setup_readiness":
                guard = _calls(fn, "_setup_auth")
                if len(guard) != 1 or len(guard[0].args) != 2 or guard[0].keywords:
                    errors.append(f"{name} must authenticate without an operation")
            if _calls(fn, "_setup_write") or _calls(fn, "write") or _calls(fn, "promote") or _calls(fn, "get_cursor"):
                errors.append(f"{name} must stay read-only")
        purposes = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith(SETUP_PURPOSE_PREFIX)}
        if purposes != {SETUP_PURPOSE_PREFIX, SETUP_PURPOSE_PREFIX + "CREATE"}:
            errors.append("unreviewed wf03-setup purpose")
        index = _top(tree, "setup_draft_index")
        if index is None or "issue_token(request, 'new-setup', purpose='wf03-setup:CREATE')" not in ast.unparse(index):
            errors.append("the listing must issue the CREATE token bound to new-setup")
        get = _top(tree, "setup_draft_get")
        if get is None or "issue_token(request, draft_id, purpose='wf03-setup:' + op)" not in ast.unparse(get) \
                or "for op in ('UPDATE', 'PROMOTE')" not in ast.unparse(get):
            errors.append("the draft read must issue UPDATE and PROMOTE tokens bound to that draft id only")

        # 5. exact counts: one cursor, one execute, and no other SQL/Run reference anywhere in the module.
        cursor_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func).split(".")[-1] == "get_cursor"]
        execute_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "execute"]
        cursor_refs = [n for n in ast.walk(tree) if (isinstance(n, ast.Name) and n.id == "get_cursor") or (isinstance(n, ast.Attribute) and n.attr in ("get_cursor", "execute", "executemany", "executescript"))
                       or (isinstance(n, ast.alias) and n.name == "get_cursor")]
        if len(cursor_calls) != 1 or len(execute_calls) != 1 or len(cursor_refs) != 3:     # the call, its import alias, and the one .execute
            errors.append("exactly one cursor read (the ownership SELECT) is admitted")
    except (SyntaxError, ValueError, TypeError, AttributeError, IndexError, StopIteration):
        errors.append("setup chain evidence incomplete or malformed")
    return errors


def current_rcm_adapter_valid(path: str, *, repo=None) -> bool:
    root = Path(repo) if repo is not None else ROOT
    try:
        return violations(path, (root / path).read_text(encoding="utf-8")) == []
    except (OSError, UnicodeError, KeyError):
        return False
