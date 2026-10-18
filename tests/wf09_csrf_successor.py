"""WF-09 / RC-7 CSRF-inventory SUCCESSOR PROPOSAL (exact content), not independent approval.

``tests/test_trust_readiness_controls.py::test_known_gap_state_changing_posts_have_no_csrf_token`` pins the set of files that call
``validate_csrf_token(``.  The CAPEX spending-profile planner adds exactly one file, ``app/v2/capex_profile_router.py``, with exactly two
CSRF-protected POST routes: the read-only PREVIEW (WF-09) and the Working Copy SAVE/RESET (RC-7).  Like M6 and M7 it is admitted ONLY while
its own exact content holds:

  * the router file is byte-identical to the reviewed blob pinned below (any edit fails closed until re-reviewed);
  * its structure proves each endpoint is safe: one validator call site per POST handler, authenticated and owner/project-bound
    before the token is read, the token a required form field checked before the form is read, a plan is built or anything is
    written, a failed token answering 403; the SAVE additionally carries the composite-identity CAS token as a required form field and
    reaches persistence ONLY through ``save_profiles`` (exclusive transaction, ownership, protected-reference, CAS, dirty flag, no Run);
    no other state-changing HTTP method; no SQL, Run or direct workspace-writer reference.

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
ROUTER_BLOB = "0721758d7f9163013dfd71169a326617e01a86f0"
PREVIEW_HANDLER = "capex_spending_profiles_preview"
SAVE_HANDLER = "capex_spending_profiles_save"
PREVIEW_PATH = "/spending-profiles/preview"
SAVE_PATH = "/spending-profiles/save"
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


def _call(fn, name):
    return next((n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name), None)


def _form_default(fn, arg):
    defaults = dict(zip((a.arg for a in fn.args.args[len(fn.args.args) - len(fn.args.defaults):]), fn.args.defaults))
    return defaults.get(arg)


def _required_form(fn, arg) -> bool:
    d = _form_default(fn, arg)
    return (any(a.arg == arg for a in fn.args.args) and isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "Form"
            and bool(d.args) and isinstance(d.args[0], ast.Constant) and d.args[0].value is Ellipsis)


def _check_handler(fn, label, errors, *, later: dict):
    """Structure every state-changing handler must have: required CSRF Form token, guard first, CSRF gate before ``later`` calls."""
    if not _required_form(fn, "csrf_token"):
        errors.append(f"{label}: csrf_token must be a required Form(...) parameter")
    guard, check = _call(fn, "_guard"), next((n for n in ast.walk(fn) if _is_validator_call(n)), None)
    form = next((n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "form"), None)
    if guard is None or check is None or guard.lineno > check.lineno:
        errors.append(f"{label}: authentication/project-ownership guard must run before the CSRF check")
    for what, node in {"form read": form, **later}.items():
        if node is None or check is None or check.lineno > node.lineno:
            errors.append(f"{label}: CSRF check must precede the {what}")
    gate = next((n for n in fn.body if isinstance(n, ast.If) and isinstance(n.test, ast.UnaryOp) and isinstance(n.test.op, ast.Not)
                 and _is_validator_call(n.test.operand)), None)
    if gate is None:
        errors.append(f"{label}: CSRF failure must be an explicit `if not validate_csrf_token(...)` gate")
    else:
        rejects = [n for n in ast.walk(gate) if isinstance(n, ast.keyword) and n.arg == "status_code"
                   and isinstance(n.value, ast.Constant) and n.value.value == 403]
        if not rejects or not any(isinstance(n, ast.Return) for n in gate.body):
            errors.append(f"{label}: a failed CSRF token must return 403")


def violations(source: str, *, check_pin: bool = True) -> list[str]:
    """[] means the exact reviewed router content and structure hold; it does NOT mean released or approved."""
    errors: list[str] = []
    try:
        if check_pin and source_blob(source) != ROUTER_BLOB:
            errors.append("router content is not the exact reviewed blob")
        tree = ast.parse(source)
        sites = [n for n in ast.walk(tree) if _is_validator_call(n)]
        if len(sites) != 2:
            errors.append(f"expected exactly two validate_csrf_token call sites (preview, save), found {len(sites)}")
        routes = _route_calls(tree)
        state_changing = sorted(r for r in routes if r[1] in STATE_CHANGING)
        if state_changing != sorted([(PREVIEW_HANDLER, "post", PREVIEW_PATH), (SAVE_HANDLER, "post", SAVE_PATH)]):
            errors.append(f"state-changing routes differ from the two reviewed POSTs: {state_changing}")
        if sorted(r for r in routes if r[1] not in STATE_CHANGING) != [("capex_spending_profiles_page", "get", "/spending-profiles")]:
            errors.append("unexpected additional route")
        handlers = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and any(_is_validator_call(c) for c in ast.walk(n))}
        if handlers != {PREVIEW_HANDLER, SAVE_HANDLER}:
            errors.append(f"CSRF handler authority changed: {sorted(handlers)}")
        fns = {n.name: n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)}
        preview, save = fns.get(PREVIEW_HANDLER), fns.get(SAVE_HANDLER)
        if preview is None or save is None:
            errors.append("preview/save handler missing")
        else:
            _check_handler(preview, "preview", errors, later={"plan build": _call(preview, "build_plan")})
            _check_handler(save, "save", errors, later={"persistence write": _call(save, "save_profiles")})
            if not _required_form(save, "content_hash"):
                errors.append("save: the composite-identity CAS token content_hash must be a required Form(...) parameter")
            if _call(preview, "save_profiles") is not None:
                errors.append("preview must never reach the writer")
            if len([n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "save_profiles"]) != 1:
                errors.append("save_profiles must be called exactly once, from the save handler")
            gate = next((n for n in save.body if isinstance(n, ast.If) and "can_edit" in ast.unparse(n.test)), None)
            write = _call(save, "save_profiles")
            if gate is None or write is None or gate.lineno > write.lineno:
                errors.append("save: the can_edit (owner / Base / not read-only) gate must precede the write")
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
