"""Exact-content CSRF inventory recognition proposal; no financial release authority.

Both literal identities come from the immutable Correction C router. Recognition
does not approve quarterly economics, exempt frozen paths or activate a Run.
The complete AST pin preserves auth/owner/reference checks, token-before-write,
the canonical CAS writer, financing refusal and the exact single POST route.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE_HEAD = "8048a74e7f568a40fbcaecf185621350c8251a85"
ROUTER = "app/v2/quarterly_calendar_router.py"
ROUTER_BLOB = "7e3ea127918bfe9d9988a807a25f65b44bd4731c"
ROUTER_AST_SHA256 = "f0a89f03124dcdf672e3cb89f00596e8881191b7ee4d020db465b63cff0d093d"
ACTIVATION_PATH = "app/workbook/quarterly_frequency_config.py"


def source_blob(source: str) -> str:
    data = source.encode("utf-8")
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def violations(source: str, *, check_pin: bool = True) -> list[str]:
    errors = []
    try:
        if check_pin and source_blob(source) != ROUTER_BLOB:
            errors.append("QUARTERLY_CSRF_CONTENT_MISMATCH")
        tree = ast.parse(source)
        digest = hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()
        if digest != ROUTER_AST_SHA256:
            errors.append("QUARTERLY_CSRF_STRUCTURE_MISMATCH")
    except (SyntaxError, ValueError, TypeError, UnicodeError, AttributeError):
        errors.append("QUARTERLY_CSRF_SOURCE_INVALID")
    return errors


def current_quarterly_csrf_successor_valid(*, repo=None) -> bool:
    """Fail closed on changed bytes/structure, missing provenance or activation."""
    root = Path(repo) if repo is not None else ROOT
    try:
        source = (root / ROUTER).read_text(encoding="utf-8")
        if violations(source):
            return False
        pinned = subprocess.run(["git", "rev-parse", f"{SOURCE_HEAD}:{ROUTER}"], cwd=root,
                                check=True, capture_output=True, text=True).stdout.strip()
        if pinned != ROUTER_BLOB:
            return False
        subprocess.run(["git", "merge-base", "--is-ancestor", SOURCE_HEAD, "HEAD"],
                       cwd=root, check=True, capture_output=True)
        tree = ast.parse((root / ACTIVATION_PATH).read_text(encoding="utf-8"))
        flags = [n.value for n in tree.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "ACTIVATION_ENABLED" for t in n.targets)]
        return len(flags) == 1 and isinstance(flags[0], ast.Constant) and flags[0].value is False
    except (OSError, subprocess.SubprocessError, SyntaxError, ValueError, TypeError, UnicodeError, AttributeError):
        return False
