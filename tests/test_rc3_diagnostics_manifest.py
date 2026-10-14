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

from tests.test_rc2_integration_manifest import (
    RC2_ACTIVATION_FLAG_FILES, RC2_CHECKPOINT, RC2_CHECKPOINT_TREE, RC2_CI_WORKFLOW, RC2_CI_WORKFLOW_CANDIDATE_BLOB,
    RC2_CSRF_CALL_SITES, RC2_EXACT_BLOBS, RC2_PINNED_UNCHANGED, RC2_REVIEWED_HEAD, RC2_BASE_MAIN, activation_state,
    rc2_violations, _collect as _rc2_collect,
)

ROOT = Path(__file__).resolve().parent.parent
RC3_BASE = RC2_CHECKPOINT
# RC-3 integration: the reviewed Diagnostics V2 source head (an ancestor of the integrated HEAD). This proof is anchored to it;
# tests/test_rc3_integration_inventory.py separately binds the integrated HEAD to that reviewed content.
RC3_REF = "5c6963879d8bdf0a16458011a5cfe6011fd36021"
RC3_BASE_TREE = RC2_CHECKPOINT_TREE

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


def rc3_violations(f) -> list[str]:
    """Pure fail-closed verifier over injected facts; [] means the Diagnostics successor holds."""
    try:
        problems = []
        base = f["base"]
        if base.get("sha") != RC3_BASE or base.get("tree") != RC3_BASE_TREE:
            problems.append("RC-3 base is not the accepted RC-2 checkpoint commit and tree")
        if tuple(base.get("parents", ())) != (RC2_BASE_MAIN, RC2_REVIEWED_HEAD):
            problems.append("historical RC-2 merge provenance changed")
        if f["ancestor"] is not True:
            problems.append("the candidate does not descend from the RC-2 checkpoint")
        seen = {}
        for status, path in f["status"]:
            if path in seen:
                problems.append(f"{path}: listed twice")
            seen[path] = status
            if status not in ("A", "M"):
                problems.append(f"{path}: {status} is not permitted (no deletions, renames or type changes)")
            elif path in RC3_APP_CHANGES:
                if status != RC3_APP_CHANGES[path][0]:
                    problems.append(f"{path}: wrong status {status}")
            elif path in RC3_OTHER_PATHS:
                if status != RC3_OTHER_PATHS[path]:
                    problems.append(f"{path}: wrong status {status}")
            else:
                problems.append(f"{path}: not part of the reviewed RC-3 Diagnostics content")
        for path, (status, blob) in RC3_APP_CHANGES.items():
            if path not in seen:
                problems.append(f"{path}: reviewed change is missing")
            if f["blobs"].get(path) != blob:
                problems.append(f"{path}: not the exact reviewed blob")
        for path in sorted(set(RC3_OTHER_PATHS) - set(seen)):
            problems.append(f"{path}: reviewed path is missing")
        for path in (*RC2_EXACT_BLOBS, *RC2_PINNED_UNCHANGED):
            if f["blobs"].get(path) != {**RC2_EXACT_BLOBS, **RC2_PINNED_UNCHANGED}[path]:
                problems.append(f"{path}: RC-2 pinned blob changed")
        if f["blobs"].get("app/v2/router.py") != f["router_base_blob"]:
            problems.append("the router differs from the RC-2 checkpoint (no router change is authorised)")
        if f["blobs"].get(RC2_CI_WORKFLOW) != RC2_CI_WORKFLOW_CANDIDATE_BLOB:
            problems.append("the CI workflow differs from the RC-2 checkpoint")
        if frozenset(f["call_sites"]) != RC2_CSRF_CALL_SITES:
            problems.append("CSRF validation call sites differ from the reviewed inventory")
        for path, flag in RC2_ACTIVATION_FLAG_FILES.items():
            state = activation_state(f["flag_sources"][path], flag)
            if state != "CLOSED":
                problems.append(f"{path}: {flag} is not a literal release-closed False ({state})")
        if f["protected_changes"]:
            problems.append(f"protected paths changed after the RC-2 checkpoint: {sorted(f['protected_changes'])}")
        problems += rc3_v1_authority_violations(f["v1_source"])
        return problems
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return [f"facts incomplete or malformed: {exc!r}"]


def _grep_csrf(ref):
    proc = subprocess.run(["git", "grep", "-lP", r"(?<!def )validate_csrf_token\(", ref, "--", "app/*.py", "main_web.py"],
                          cwd=ROOT, capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        raise subprocess.CalledProcessError(proc.returncode, proc.args)
    return {line.split(":", 1)[1] for line in proc.stdout.splitlines() if not line.split(":", 1)[1].startswith("app/trust_readiness/")}


def _collect():
    parents = _git("rev-list", "--parents", "-n", "1", RC3_BASE).split()
    pinned = [*RC3_APP_CHANGES, *RC2_EXACT_BLOBS, *RC2_PINNED_UNCHANGED, "app/v2/router.py", RC2_CI_WORKFLOW]
    blobs = {}
    for path in pinned:
        try:
            blobs[path] = _git("rev-parse", f"{RC3_REF}:{path}")
        except subprocess.CalledProcessError:
            continue
    return {
        "base": {"sha": _git("rev-parse", f"{RC3_BASE}^{{commit}}"), "tree": _git("rev-parse", f"{RC3_BASE}^{{tree}}"), "parents": tuple(parents[1:])},
        "ancestor": subprocess.run(["git", "merge-base", "--is-ancestor", RC3_BASE, RC3_REF], cwd=ROOT).returncode == 0,
        "status": [tuple(line.split("\t", 1)) for line in _git("diff", "--name-status", "--no-renames", RC3_BASE, RC3_REF).splitlines()],
        "blobs": blobs, "router_base_blob": _git("rev-parse", f"{RC3_BASE}:app/v2/router.py"),
        "call_sites": _grep_csrf(RC3_REF),
        "flag_sources": {p: _git("show", f"{RC3_REF}:{p}") + "\n" for p in RC2_ACTIVATION_FLAG_FILES},
        "protected_changes": [p for p in _git("diff", "--name-only", RC3_BASE, RC3_REF, "--", *RC3_PROTECTED_PREFIXES).splitlines() if p],
        "v1_source": _git("show", f"{RC3_REF}:{RC3_V1_PATH}") + "\n",
    }


@pytest.fixture(scope="module")
def facts():
    try:
        merged = _collect()
    except subprocess.CalledProcessError:
        pytest.skip("RC-3 checkpoint history is unavailable in this checkout")
    if not merged["ancestor"]:
        pytest.skip("not a descendant of the RC-2 checkpoint")
    return merged


# ── the real candidate ─────────────────────────────────────────────────────────────────────────────────────────
def test_the_diagnostics_candidate_matches_the_exact_content_successor(facts):
    assert rc3_violations(facts) == []
    assert {p for _s, p in facts["status"]} == set(RC3_APP_CHANGES) | set(RC3_OTHER_PATHS)
    assert {p: (dict(((p2, s) for s, p2 in facts["status"]))[p]) for p in RC3_APP_CHANGES} == {p: s for p, (s, _b) in RC3_APP_CHANGES.items()}
    assert facts["protected_changes"] == [] and facts["ancestor"] is True


def test_historical_rc2_acceptance_still_holds_beside_the_successor(facts):
    assert rc2_violations(_rc2_collect()) == []                          # the RC-2 checkpoint, judged from its own objects
    assert facts["base"] == {"sha": RC2_CHECKPOINT, "tree": RC2_CHECKPOINT_TREE, "parents": (RC2_BASE_MAIN, RC2_REVIEWED_HEAD)}


def test_the_successor_has_no_wildcard_for_protected_namespaces():
    for path in (*RC3_APP_CHANGES, *RC3_OTHER_PATHS):
        assert not path.startswith(("financial_engine/", "finco_core/", "domain/", ".github/", "app/model_quality/", "app/run_integrity/"))
        assert "*" not in path
    assert all(p.startswith("app/v2/") for p in RC3_APP_CHANGES) and len(RC3_APP_CHANGES) == 5
    assert all(re.fullmatch(r"[0-9a-f]{40}", blob) for _s, blob in RC3_APP_CHANGES.values())


# ── negative mutation tests ────────────────────────────────────────────────────────────────────────────────────
def _bad(facts, **changes):
    mutated = copy.deepcopy(facts)
    mutated.update(changes)
    problems = rc3_violations(mutated)
    assert problems, changes
    return problems


def test_a_modified_diagnostics_application_blob_is_rejected(facts):
    for path in RC3_APP_CHANGES:
        problems = _bad(facts, blobs={**facts["blobs"], path: "1" * 40})
        assert any(path in p and "exact reviewed blob" in p for p in problems)
        _bad(facts, blobs={k: v for k, v in facts["blobs"].items() if k != path})
    _bad(facts, status=[s for s in facts["status"] if s[1] != "app/v2/diagnostics_dx_checks.py"])      # a reviewed file vanished
    _bad(facts, status=[("M" if p == "app/v2/diagnostics_dx_checks.py" else s, p) for s, p in facts["status"]])   # added -> modified
    _bad(facts, status=[("D" if p == "app/v2/diagnostics_run_compare.py" else s, p) for s, p in facts["status"]])


def test_an_unexpected_additional_application_module_or_path_is_rejected(facts):
    for status, path in (("A", "app/v2/unreviewed_module.py"), ("A", "app/services/rogue.py"), ("M", "app/v2/whatif.py"),
                         ("A", "tests/unreviewed_test.py"), ("A", "static/js/rogue.js"), ("A", "docs/model_v2/rogue.md"),
                         ("A", "tools/new_tool.py"), ("M", "app/templates/v2/other.html")):
        problems = _bad(facts, status=[*facts["status"], (status, path)])
        assert any(path in p for p in problems), path
    _bad(facts, status=[*facts["status"], ("A", "app/v2/diagnostics_dx_checks.py")])                  # listed twice


def test_unauthorised_financial_engine_core_domain_or_radar_changes_are_rejected(facts):
    for status, path in (("M", "financial_engine/financing/multisenior.py"), ("A", "finco_core/new_math.py"),
                         ("M", "domain/revenue/plan.py"), ("A", "finco_radar/new.py")):
        _bad(facts, status=[*facts["status"], (status, path)], protected_changes=[path])
        _bad(facts, status=[*facts["status"], (status, path)])
    _bad(facts, protected_changes=["financial_engine/x.py"])


def test_quality_registry_scorer_run_integrity_and_q4_goal_seek_mutations_are_rejected(facts):
    for path in ("app/model_quality/registry.py", "app/model_quality/scoring.py", "app/model_quality/evaluators.py",
                 "app/run_integrity/checks.py", "app/run_integrity/contracts.py", "app/v2/whatif.py", "app/v2/whatif_router.py",
                 "app/services/goal_seek.py", "app/persistence/run_history_repository.py"):
        problems = _bad(facts, status=[*facts["status"], ("M", path)], protected_changes=[path])
        assert any("protected paths changed" in p for p in problems), path


def test_a_new_csrf_validation_call_site_or_a_removed_one_is_rejected(facts):
    _bad(facts, call_sites=set(facts["call_sites"]) | {"app/v2/diagnostics_run_compare.py"})
    _bad(facts, call_sites=set(facts["call_sites"]) | {"app/v2/diagnostics_v2_projection.py"})
    _bad(facts, call_sites=set(facts["call_sites"]) - {"app/v2/developer_decision_router.py"})


@pytest.mark.parametrize("path", sorted(RC2_ACTIVATION_FLAG_FILES))
@pytest.mark.parametrize("new", ["ACTIVATION_ENABLED = True", "ACTIVATION_ENABLED = not False", "ACTIVATION_ENABLED = bool(0)",
                                 "ACTIVATION_ENABLED = False\nACTIVATION_ENABLED = True"])
def test_changed_revenue_v3_or_junior_activation_is_rejected(facts, path, new):
    source = facts["flag_sources"][path]
    assert "ACTIVATION_ENABLED = False" in source
    problems = _bad(facts, flag_sources={**facts["flag_sources"], path: source.replace("ACTIVATION_ENABLED = False", new, 1)})
    assert any("literal release-closed False" in p for p in problems)
    _bad(facts, blobs={**facts["blobs"], path: "2" * 40})                                           # the pinned flag-file blob changed


def test_changed_historical_rc2_merge_provenance_is_rejected(facts):
    base = facts["base"]
    for change in ({"sha": "3" * 40}, {"tree": "4" * 40}, {"parents": (RC2_BASE_MAIN, "5" * 40)}, {"parents": ("6" * 40, RC2_REVIEWED_HEAD)},
                   {"parents": (RC2_REVIEWED_HEAD, RC2_BASE_MAIN)}):
        _bad(facts, base={**base, **change})
    _bad(facts, ancestor=False)
    historical = _rc2_collect()
    for mutation in ({"release_parents": [RC2_BASE_MAIN, "7" * 40]},
                     {"merges": {**historical["merges"], "275": ("8" * 40, "9" * 40, "a" * 40)}}):
        assert rc2_violations({**historical, **mutation})                                         # the historical verifier also rejects


def test_a_modified_ci_workflow_or_router_is_rejected(facts):
    _bad(facts, blobs={**facts["blobs"], RC2_CI_WORKFLOW: "b" * 40})
    _bad(facts, status=[*facts["status"], ("M", RC2_CI_WORKFLOW)])
    _bad(facts, status=[*facts["status"], ("A", ".github/workflows/x.yml")])
    _bad(facts, blobs={**facts["blobs"], "app/v2/router.py": "c" * 40})
    _bad(facts, status=[*facts["status"], ("M", "app/v2/router.py")])


def test_removing_or_altering_the_diagnostics_v1_integrity_authority_is_rejected(facts):
    source = facts["v1_source"]
    assert rc3_v1_authority_violations(source) == []
    mutations = {
        "integrity call removed": source.replace("integrity.run_integrity_checks(", "integrity_disabled(", 1),
        "integrity import removed": source.replace("from app.run_integrity import checks as integrity", "integrity = None", 1),
        "validator removed": source.replace('    "QM-CASH-001": integrity.check_no_unfunded_deficit,\n', "", 1),
        "validator replaced": source.replace("integrity.check_dscr_identity", "lambda ev: None", 1),
        "engine import added": source.replace("from dataclasses import", "import financial_engine\nfrom dataclasses import", 1),
        "persistence import added": source.replace("from dataclasses import", "from app.persistence import repository\nfrom dataclasses import", 1),
        "second quality authority": source.replace("from dataclasses import", "from app.model_quality import evaluate_model_quality\nfrom dataclasses import", 1),
        "v2 hook not fail-closed": source.replace("        except Exception:  # noqa: BLE001 - fail closed to an explicit UNAVAILABLE block\n            result[\"v2\"] = {\"state\": \"UNAVAILABLE\", \"available\": False}\n", "        finally:\n            pass\n", 1),
        "function removed": source.replace("def build_diagnostics(", "def build_diagnostics_renamed(", 1),
        "unparseable": "def broken(:\n",
    }
    for name, mutated in mutations.items():
        assert mutated != source, name
        assert rc3_v1_authority_violations(mutated), name
        _bad(facts, v1_source=mutated)


def test_missing_or_malformed_facts_never_authorise(facts):
    assert rc3_violations({})
    for key in facts:
        incomplete = {k: v for k, v in facts.items() if k != key}
        assert rc3_violations(incomplete), key
    _bad(facts, status="not-a-list")
    _bad(facts, blobs=None)


def test_missing_git_history_is_not_an_authorisation(monkeypatch):
    import sys
    def unavailable(*args):
        raise subprocess.CalledProcessError(1, ["git", *args])
    monkeypatch.setattr(sys.modules[__name__], "_git", unavailable)
    with pytest.raises(subprocess.CalledProcessError):
        _collect()
