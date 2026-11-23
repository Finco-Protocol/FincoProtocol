"""RC-3 Diagnostics V2 exact-content successor (PROPOSAL awaiting independent review - it is NOT an approval).

The accepted RC-2 content is judged by tests/test_rc2_integration_manifest.py against its own checkpoint commit. This file
governs ONLY what Diagnostics V2 adds on top of that checkpoint:

* the exact RC-3 base is the RC-2 checkpoint (commit and tree), and it must be an ancestor of the candidate;
* the candidate diff against that base may contain ONLY the listed paths, each with its exact status;
* the five reviewed application paths are pinned by exact Git blob SHA (added vs modified);
* every other listed path (templates, CSS/JS, tests, documentation) is an exact path with an exact status; its content is
  presentation / evidence and is not a protected authority;
* no wildcard for ``app/``, ``financial_engine/``, ``finco_core/`` or ``domain/``; any unlisted path, any changed protected blob, a new CSRF
  call site, a changed activation flag, a changed router, workflow or Diagnostics V1 integrity authority fails closed.

Any change to a pinned blob or to the allowed path set needs a new exact-content review: the successor never accepts a future HEAD silently.
"""
import ast
import copy
import re
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
# RC-3 integration: the reviewed Diagnostics V2 source head (an ancestor of the integrated HEAD). This proof is anchored to it;
# tests/test_rc3_integration_inventory.py separately binds the integrated HEAD to that reviewed content.
RC3_REF = "5c6963879d8bdf0a16458011a5cfe6011fd36021"

# The five reviewed application paths: exact status and exact Git blob SHA-1.
RC3_APP_CHANGES = {
    "app/v2/diagnostics_dx_checks.py": ("A", "4984dfb5f906012b6768a0f9f208e1199cf876eb"),
    "app/v2/diagnostics_v2_projection.py": ("A", "74b43d7d313aff9eb56b821f308270da57be1798"),
    "app/v2/diagnostics_run_compare.py": ("A", "fc17236fcceb2d725325b1f539781efc0ee28931"),
    "app/v2/diagnostics_projection.py": ("M", "12a77491fed4e912b942807db7514ee4c4d6b873"),
    "app/v2/insight_quality_projection.py": ("M", "f0157c465983b48c3ed9ee450389785c24481772"),
}
# Every other path of the candidate: exact path + exact status, content NOT pinned (presentation, evidence, documentation).
RC3_OTHER_PATHS = {
    "app/templates/v2/partials/sheet_diagnostics.html": "M",
    "app/templates/v2/workbook.html": "M",
    "static/css/model_diagnostics_v2.css": "A",
    "static/js/model_diagnostics_v2.js": "A",
    "tests/model_diagnostics_v2_browser_acceptance.py": "A",
    "tests/test_model_diagnostics_v2.py": "A",
    "tests/test_model_diagnostics_v2_real_runs.py": "A",
    "tests/test_model_workspace_consolidation_browser.py": "M",
    "docs/model_v2/MODEL_DIAGNOSTICS_V2.md": "A",
    "docs/model_v2/MODEL_DIAGNOSTICS_V2_TRUST_PROPOSAL.md": "A",
    # Governance PROPOSALS: the reviewer must approve their exact content; they are listed so they cannot widen anything.
    "tests/test_rc2_integration_manifest.py": "M",
    "tests/test_rc3_diagnostics_manifest.py": "A",
}
# Areas that must be byte-identical to the RC-3 base (reported separately from the allow-list for a precise diagnosis).
RC3_PROTECTED_PREFIXES = (
    "financial_engine", "finco_core", "domain", "finco_radar", "app/model_quality", "app/run_integrity", ".github",
    "app/persistence", "app/auth.py", "app/workbook", "app/api", "main_web.py", "tools", "app/v2/router.py",
    "app/v2/whatif.py", "app/v2/whatif_router.py", "app/services/goal_seek.py", "tests/model_v2_governance.py",
)
RC3_V1_PERIOD_VALIDATORS = frozenset({"QM-ACC-001", "QM-SU-001", "QM-SD-001", "QM-SD-002", "QM-SD-003", "QM-SD-004", "QM-CASH-001"})
RC3_V1_PATH = "app/v2/diagnostics_projection.py"


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def rc3_v1_authority_violations(source: str) -> list[str]:
    """Diagnostics V1 integrity authority must survive the V2 hook: same validators, same Integrity call, no engine/persistence."""
    problems = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ["Diagnostics V1 source is not parseable"]
    validators = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PERIOD_VALIDATORS" for t in node.targets):
            if isinstance(node.value, ast.Dict) and all(isinstance(k, ast.Constant) for k in node.value.keys):
                validators = {k.value: ast.unparse(v) for k, v in zip(node.value.keys, node.value.values)}
    if validators is None or set(validators) != RC3_V1_PERIOD_VALIDATORS or not all(v.startswith("integrity.check_") for v in validators.values()):
        problems.append("Diagnostics V1 period validators are not the seven original Run Integrity validators")
    if not any(isinstance(n, ast.ImportFrom) and n.module == "app.run_integrity" and any(a.name == "checks" and a.asname == "integrity" for a in n.names)
               for n in tree.body):
        problems.append("Diagnostics V1 no longer imports the Run Integrity checks")
    build = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build_diagnostics"), None)
    if build is None:
        return problems + ["build_diagnostics is missing"]
    calls = [ast.unparse(n.func) for n in ast.walk(build) if isinstance(n, ast.Call)]
    if "integrity.run_integrity_checks" not in calls:
        problems.append("build_diagnostics no longer runs the Run Integrity report")
    hook = [n for n in ast.walk(build) if isinstance(n, ast.Try) and any(isinstance(c, ast.Call) and ast.unparse(c.func) == "build_diagnostics_v2"
                                                                         for c in ast.walk(n))]
    if not hook or not all(t.handlers for t in hook):
        problems.append("the V2 hook is not fail-closed (it must sit inside try/except)")
    for node in ast.walk(tree):
        mods = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                [node.module] if isinstance(node, ast.ImportFrom) and node.module and node.level == 0 else [])
        for mod in mods:
            if mod.split(".")[0] in ("financial_engine", "finco_core", "domain") or mod.startswith("app.persistence"):
                problems.append(f"Diagnostics V1 imports a forbidden module: {mod}")
            if mod.startswith("app.model_quality") and mod != "app.model_quality.contracts":
                problems.append(f"Diagnostics V1 imports a second Quality authority: {mod}")
    return problems


def _grep_csrf(ref):
    proc = subprocess.run(["git", "grep", "-lP", r"(?<!def )validate_csrf_token\(", ref, "--", "app/*.py", "main_web.py"],
                          cwd=ROOT, capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        raise subprocess.CalledProcessError(proc.returncode, proc.args)
    return {line.split(":", 1)[1] for line in proc.stdout.splitlines() if not line.split(":", 1)[1].startswith("app/trust_readiness/")}


# ── the real candidate ─────────────────────────────────────────────────────────────────────────────────────────


def test_the_successor_has_no_wildcard_for_protected_namespaces():
    for path in (*RC3_APP_CHANGES, *RC3_OTHER_PATHS):
        assert not path.startswith(("financial_engine/", "finco_core/", "domain/", ".github/", "app/model_quality/", "app/run_integrity/"))
        assert "*" not in path
    assert all(p.startswith("app/v2/") for p in RC3_APP_CHANGES) and len(RC3_APP_CHANGES) == 5
    assert all(re.fullmatch(r"[0-9a-f]{40}", blob) for _s, blob in RC3_APP_CHANGES.values())


# ── negative mutation tests ────────────────────────────────────────────────────────────────────────────────────


