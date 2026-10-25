"""RC-SEC Run/Clone CSRF inventory successor. Review proposal, NOT financial release authority.

Admits the exact reviewed Run and Clone validator sites only if their
complete source blobs, immutable ancestry, and security structure are intact.
A newly edited route needs an independent new source review and pin.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE_HEAD = "e775769c5d02e0b2cff5aba46c577d5ecc5c7ea3"
CLONE_ROUTER = "app/library/router.py"
RUN_ROUTER = "app/v2/router.py"
BINDING_MODULE = "app/workbook/financing_csrf.py"
POSITIVE_HELPER = "tests/run_clone_csrf.py"
RUN_HANDLER = "v2_workbook_run"
CLONE_HANDLER = "project_library_clone"
BLOBS = {
    CLONE_ROUTER: "2b9a0bdc2ccfbde2f1b6e9401ee6ad935382e6b5",
    RUN_ROUTER: "a5a3874acd71074863e38036ed18951fd7dd6297",
    BINDING_MODULE: "ab96d84d1639e83c532c66c6fa3e8276b72824e5",
    POSITIVE_HELPER: "07731bc839b3ea8f78dfd361432ac2200b0c14b5",
}


def git_blob(content: str) -> str:
    raw = content.encode("utf-8")
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def _function(tree: ast.AST, name: str):
    matches = [n for n in tree.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if len(matches) != 1:
        raise ValueError(f"missing/duplicate handler {name}")
    return matches[0]


def _call(fn: ast.AST, name: str):
    return [n for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name]


def _route(fn, path: str) -> bool:
    return any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
               and isinstance(d.func.value, ast.Name) and d.func.value.id == "router"
               and d.func.attr == "post" and len(d.args) == 1
               and isinstance(d.args[0], ast.Constant) and d.args[0].value == path
               for d in fn.decorator_list)


def _reject(fn, validator, code: int) -> bool:
    # The validator must be inside a top-level If gate whose first action
    # returns exactly the expected HTTP error, never a truthy bypass.
    for node in fn.body:
        if not isinstance(node, ast.If) or validator not in list(ast.walk(node.test)):
            continue
        if not node.body or not isinstance(node.body[0], ast.Return):
            continue
        ret = node.body[0].value
        if not isinstance(ret, ast.Call) or not isinstance(ret.func, ast.Name) or ret.func.id != "JSONResponse":
            continue
        if any(k.arg == "status_code" and isinstance(k.value, ast.Constant) and k.value.value == code
               for k in ret.keywords):
            return True
    return False


def _line_after(a, b):
    return bool(a and b and max(n.lineno for n in a) < min(n.lineno for n in b))


def violations(sources: dict[str, str], *, check_pin: bool = True) -> list[str]:
    errors = []
    trees = {}
    for path, expected in BLOBS.items():
        source = sources.get(path)
        if not isinstance(source, str):
            errors.append(f"{path}: missing source")
            continue
        if check_pin and git_blob(source) != expected:
            errors.append(f"{path}: unreviewed blob")
        try:
            trees[path] = ast.parse(source)
        except (SyntaxError, TypeError, ValueError, UnicodeError):
            errors.append(f"{path}: unparsable source")
    if len(trees) != len(BLOBS):
        return errors

    run = _function(trees[RUN_ROUTER], RUN_HANDLER)
    clone = _function(trees[CLONE_ROUTER], CLONE_HANDLER)
    if not _route(run, "/workbook/run") or not _route(clone, "/library/clone/{source_project_id}"):
        errors.append("Run/Clone POST route identity changed")

    # Both handlers must retain one explicit validator, scoped to their
    # respective purposes. Additional/moved validators are not admitted.
    for fn, label, purpose, earlier, later in (
        (run, "Run", "workbook-run-v1", ("_get_current_user", "resolve_accessible_project"),
         ("get_workspace_state", "assemble_consistent_for_get", "run_project", "v2_atomic_run_commit")),
        (clone, "Clone", "library-clone-v1", ("_get_current_user",),
         ("get_canonical_reference_by_id", "create_working_copy")),
    ):
        validators = _call(fn, "validate_csrf_token")
        binding = _call(fn, "extract_bound_token")
        if len(validators) != 1 or len(binding) != 1:
            errors.append(f"{label}: validator or scoped binding missing/duplicated")
            continue
        validate, scoped = validators[0], binding[0]
        if scoped not in list(ast.walk(validate)):
            errors.append(f"{label}: validator does not consume scoped token")
        if not any(k.arg == "purpose" and isinstance(k.value, ast.Constant)
                   and k.value.value == purpose for k in scoped.keywords):
            errors.append(f"{label}: operation domain mismatch")
        if not _reject(fn, validate, 403):
            errors.append(f"{label}: missing immediate HTTP 403 reject")
        for name in earlier:
            if not _line_after(_call(fn, name), [validate]):
                errors.append(f"{label}: {name} must precede validator")
        for name in later:
            if not _line_after([validate], _call(fn, name)):
                errors.append(f"{label}: validator must precede {name}")
        if not any(isinstance(n, ast.If) and ast.unparse(n.test) == "not user"
                   and any(isinstance(x, ast.Return) for x in n.body)
                   for n in fn.body):
            errors.append(f"{label}: missing unauthenticated rejection")
    if not _line_after(_call(run, "resolve_accessible_project"), _call(run, "validate_csrf_token")):
        errors.append("Run: owner resolution before CSRF required")
    run_body = ast.unparse(run)
    clone_body = ast.unparse(clone)
    if 'Project not found' not in run_body or 'status_code=404' not in run_body:
        errors.append("Run: private/unknown project non-disclosure lost")
    if 'Project not found' not in clone_body or 'status_code=404' not in clone_body:
        errors.append("Clone: private/unknown reference non-disclosure lost")
    if "get_canonical_reference_by_id(source_project_id) is None" not in clone_body:
        errors.append("Clone: canonical-reference guard removed")
    reference_gates = [n for n in run.body if isinstance(n, ast.If)
                       and ast.unparse(n.test) == "is_protected_reference(project_record)"
                       and any(isinstance(x, ast.Return) for x in n.body)]
    if len(reference_gates) != 1 or not _line_after(reference_gates, _call(run, "run_project")):
        errors.append("Run: protected reference guard must precede engine")
    if "current_identity.composite_hash != content_hash" not in run_body:
        errors.append("Run: content-hash CAS guard removed")
    if not _line_after(_call(run, "assemble_consistent_for_get"), _call(run, "run_project")):
        errors.append("Run: composite CAS must precede engine")
    if "csrf_token and run_csrf_token and (csrf_token != run_csrf_token)" not in run_body:
        errors.append("Run: contradictory dual tokens must fail closed")
    if "not validate_csrf_token(extract_bound_token(" not in run_body:
        errors.append("Run: scoped CSRF must fail closed")
    if "not validate_csrf_token(extract_bound_token(" not in clone_body:
        errors.append("Clone: scoped CSRF must fail closed")
    if _call(clone, "create_working_copy") and not _line_after(
            _call(clone, "get_canonical_reference_by_id"), _call(clone, "create_working_copy")):
        errors.append("Clone: canonical-reference guard after mutation")
    bound = ast.unparse(trees[BINDING_MODULE])
    if ("purpose: str='capital-stack-save-v1'" not in bound
            or 'hmac.compare_digest' not in bound
            or 'auth.decode_session_token' not in bound
            or 'auth.decode_demo_session_token' not in bound
            or "return (session.user_id, cookie, project)" not in bound):
        errors.append("CSRF binding or released Capital Stack default changed")
    helper = ast.unparse(trees[POSITIVE_HELPER])
    if "def post_valid_csrf(" not in helper or "client.post(" not in helper:
        errors.append("Explicit positive caller helper missing")
    if any(forbidden in helper for forbidden in ("TestClient.post =", "patch.object(TestClient", "validate_csrf_token =")):
        errors.append("Global client or validator bypass detected")
    return errors


def current_rc_sec_csrf_successor_valid(*, repo=None) -> bool:
    root = Path(repo) if repo is not None else ROOT
    try:
        sources = {name: (root / name).read_text(encoding="utf-8") for name in BLOBS}
        if violations(sources):
            return False
        for path, blob in BLOBS.items():
            pinned = subprocess.run(["git", "rev-parse", f"{SOURCE_HEAD}:{path}"],
                                    cwd=root, check=True, capture_output=True, text=True).stdout.strip()
            if pinned != blob:
                return False
        subprocess.run(["git", "merge-base", "--is-ancestor", SOURCE_HEAD, "HEAD"],
                       cwd=root, check=True, capture_output=True)
        return True
    except (OSError, subprocess.SubprocessError, SyntaxError, ValueError,
            TypeError, UnicodeError, AttributeError):
        return False
