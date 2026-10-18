"""WF-09 CSRF-inventory SUCCESSOR PROPOSAL (exact content), not independent approval.

``tests/test_trust_readiness_controls.py::test_known_gap_state_changing_posts_have_no_csrf_token`` pins the set of files that call
``validate_csrf_token(``.  WF-09 adds exactly one: ``app/v2/capex_profile_router.py``, the CSRF-protected preview POST of the
read-only CAPEX spending-profile planner.  Like M6 and M7 it is admitted ONLY while its own exact content holds:

  * the router file is byte-identical to the reviewed blob pinned below (any edit fails closed until re-reviewed);
  * its structure proves the endpoint is safe: one validator call site, in the one POST handler, authenticated and
    owner/project-bound before the token is read, the token required and checked before the form is read or a plan is built,
    a failed token answering 403; no other state-changing HTTP method; no persistence, Run or writer reference.

This is a REVIEW PROPOSAL.  It does not authorise a merge; the independent reviewer must still approve it (and re-pin it if the
router changes).  Nothing here weakens the CSRF inventory for any other file.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTER = "app/v2/capex_profile_router.py"
# LITERAL REVIEW PIN of the router's git blob (not computed at runtime from a mutable baseline).
ROUTER_BLOB = "289a8471b140ba157c09e788ac0d57060a92803c"
HANDLER = "capex_spending_profiles_preview"
PREVIEW_PATH = "/spending-profiles/preview"
FORBIDDEN_TOKENS = (".execute(", "INSERT", "UPDATE ", "DELETE ", "apply_batch_draft_update", "run_project", "create_sub_line(",
                    "update_sub_line(", "schedule_json =", "save_workspace", "set_workspace")
STATE_CHANGING = frozenset({"post", "put", "patch", "delete"})


def source_blob(source: str) -> str:
    data = source.encode("utf-8")
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def _is_validator_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "validate_csrf_token"


def _route_calls(tree: ast.Module) -> list[tuple[str, str, str]]:
    """(function, http method, path) for every ``@profile_router.<method>(path)`` decorator."""
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and isinstance(dec.func.value, ast.Name)
                        and dec.func.value.id == "profile_router" and dec.args and isinstance(dec.args[0], ast.Constant)):
                    out.append((node.name, dec.func.attr, dec.args[0].value))
    return out


def violations(source: str, *, check_pin: bool = True) -> list[str]:
    """[] means the exact reviewed router content and structure hold; it does NOT mean released or approved."""
    errors: list[str] = []
    try:
        if check_pin and source_blob(source) != ROUTER_BLOB:
            errors.append("router content is not the exact reviewed blob")
        tree = ast.parse(source)
        sites = [n for n in ast.walk(tree) if _is_validator_call(n)]
        if len(sites) != 1:
            errors.append(f"expected exactly one validate_csrf_token call site, found {len(sites)}")
        routes = _route_calls(tree)
        state_changing = [r for r in routes if r[1] in STATE_CHANGING]
        if state_changing != [(HANDLER, "post", PREVIEW_PATH)]:
            errors.append(f"state-changing routes differ from the one reviewed preview POST: {state_changing}")
        if sorted(r for r in routes if r[1] not in STATE_CHANGING) != [("capex_spending_profiles_page", "get", "/spending-profiles")]:
            errors.append("unexpected additional route")
        handlers = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and any(_is_validator_call(c) for c in ast.walk(n))}
        if handlers != {HANDLER}:
            errors.append(f"CSRF handler authority changed: {sorted(handlers)}")
        fn = next((n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == HANDLER), None)
        if fn is None:
            errors.append("preview handler missing")
        else:
            defaults = dict(zip((a.arg for a in fn.args.args[len(fn.args.args) - len(fn.args.defaults):]), fn.args.defaults))
            default = defaults.get("csrf_token")
            if not (any(a.arg == "csrf_token" for a in fn.args.args) and isinstance(default, ast.Call)
                    and isinstance(default.func, ast.Name) and default.func.id == "Form" and default.args
                    and isinstance(default.args[0], ast.Constant) and default.args[0].value is Ellipsis):
                errors.append("csrf_token must be a required Form(...) parameter")
            guard = next((n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_guard"), None)
            check = next((n for n in ast.walk(fn) if _is_validator_call(n)), None)
            form = next((n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                         and n.func.attr == "form"), None)
            plan = next((n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "build_plan"), None)
            if guard is None or check is None or guard.lineno > check.lineno:
                errors.append("authentication/project-ownership guard must run before the CSRF check")
            for label, later in (("form read", form), ("plan build", plan)):
                if later is None or check is None or check.lineno > later.lineno:
                    errors.append(f"CSRF check must precede the {label}")
            gate = next((n for n in fn.body if isinstance(n, ast.If) and _is_validator_call(getattr(n.test, "operand", None))
                         and isinstance(n.test, ast.UnaryOp) and isinstance(n.test.op, ast.Not)), None)
            if gate is None:
                errors.append("CSRF failure must be an explicit `if not validate_csrf_token(...)` gate")
            else:
                rejects = [n for n in ast.walk(gate) if isinstance(n, ast.keyword) and n.arg == "status_code"
                           and isinstance(n.value, ast.Constant) and n.value.value == 403]
                if not rejects or not any(isinstance(n, ast.Return) for n in gate.body):
                    errors.append("a failed CSRF token must return 403")
        guard_fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_guard"), None)
        names = {c.func.id for c in ast.walk(guard_fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)} if guard_fn else set()
        if not {"resolve_request_session", "resolve_accessible_project"} <= names:
            errors.append("_guard must authenticate the session and resolve owner/project access")
        for needle in FORBIDDEN_TOKENS:
            if needle in source:
                errors.append(f"forbidden write/Run reference: {needle}")
    except (SyntaxError, ValueError, TypeError, AttributeError, IndexError):
        errors.append("router source evidence incomplete or malformed")
    return errors


def current_wf09_successor_valid() -> bool:
    """True only while the working-tree router is exactly the reviewed content (fail closed on any evidence problem)."""
    try:
        return not violations((ROOT / ROUTER).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - any evidence failure is not an authorization
        return False
