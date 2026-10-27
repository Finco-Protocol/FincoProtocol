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
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_CHANGING = frozenset({"post", "put", "patch", "delete"})
COMMON_FORBIDDEN = (".execute(", "get_cursor", "INSERT", "UPDATE ", "DELETE ", "save_workspace", "set_workspace",
                    "record_workspace_runtime", "save_run", "ModelExecutor", "apply_batch_draft_update")

# LITERAL REVIEW PINS of each module's git blob (not computed at runtime from a mutable baseline).
SPECS = {
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
    errors: list[str] = []
    try:
        if check_pin and source_blob(source) != spec["blob"]:
            errors.append("module content is not the exact reviewed blob")
        tree = ast.parse(source)
        if len([n for n in ast.walk(tree) if _is_validator_call(n)]) != 1:
            errors.append("expected exactly one validate_csrf_token call site")
        routes = _routes(tree)
        if sorted(r for r in routes if r[1] in STATE_CHANGING) != [(spec["handler"], "post", spec["path"])]:
            errors.append("state-changing routes differ from the one reviewed POST")
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


def current_rcm_adapter_valid(path: str, *, repo=None) -> bool:
    root = Path(repo) if repo is not None else ROOT
    try:
        return violations(path, (root / path).read_text(encoding="utf-8")) == []
    except (OSError, UnicodeError, KeyError):
        return False
