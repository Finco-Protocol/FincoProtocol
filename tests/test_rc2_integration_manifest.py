"""RC-2 integration manifest: exact ancestry, exact reviewed blobs, router delta and CSRF inventory.

This is an EXACT-CONTENT PROPOSAL awaiting independent (ChatGPT) review - it is not an approval. It adds no
wildcard, no generic allow-list and no descendant rule: any byte change to a listed file, any further router
function change, any new CSRF call site or a different source head fails until a reviewer re-authorises the
new exact content. Historical RC-1 authorities stay enforced by tests/test_trust_readiness_registry.py.
"""
import ast
import copy
import hashlib
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RC2_BASE_MAIN = "5058c6b4935168241d6923676cb32955cb903185"
# IMMUTABLE reviewed RC-2 source and its two-parent, tree-identical main merge.
RC2_ACCEPTED_HEAD = "2155a76bfff4acc3a4e15f7cf35012933ce1a10c"
RC2_MERGE_COMMIT = "6fc77de98bc0562fb51efdbf96e1803a29b5b148"
# Names used by the separate RC-3 successor modules (same immutable objects, one authority).
# RC-3 integration: reviewed R4 source head; the R4 successor proof is anchored to it (tests/test_rc3_integration_inventory.py binds HEAD).
R4_REVIEWED_HEAD = "8378e5df30ec10b4de2b2f5330491837a7cd1ffb"
RC2_CHECKPOINT = RC2_MERGE_COMMIT
RC2_REVIEWED_HEAD = RC2_ACCEPTED_HEAD
RC2_CHECKPOINT_TREE = "4fdcd03b5e0ed3c4b87d9016f2522bfe50bf0d05"
RC2_SOURCE_HEADS = (                       # merge order; each the second parent of a normal two-parent merge
    ("275", "73f698705ec5d72af820974873d9be202cd57f7d"),
    ("274", "0fa0ac5e268a37decbae6bc252487aba3e6e31c9"),
    ("277", "1599aa5eb4e82463157fbae430fa227ac71bdead"),
    ("276", "6c704f4e799a9dc1a10eb4f10d4e6b9a14f0ea2f"),
)
RC2_EXACT_BLOBS = {
    "app/api/project_runner.py": "5bc8982875f87d4ee61c6e7740293d52d9acaf2f",
    "app/api/v1/crypto_router.py": "bf168e8f67c54d6cfc674c05d29af15ce028b3b7",
    "app/crypto_terminal/deepstate_composition.py": "eb3f3c71bdb8faf8e69b39c6e01c737d7ef1be11",
    "app/crypto_terminal/tokenized_read.py": "eb2641782877afaf4f499bb0cd83b8151b42f27a",
    "app/export/institutional_workbook.py": "898fc56313038ea477493efaa45ea97502aa8c6a",
    "app/input_adapter.py": "831b5a354e177bbbcff56fabc26d5a7be061b2ae",
    "app/model_v2/developer_evidence.py": "46b8d017e012a679abfc1e48bf8867d029e9ff62",
    "app/persistence/_helpers.py": "e42ebf3d465314cb68775c2f5d3250c3b4f0df70",
    "app/services/sensitivity_matrix.py": "b0dadcda8d7da65562b6ab4562300c1d2da6ab64",
    "app/v2/developer_committed_projection.py": "de61df284830d572dd6cd58870af84d383fa3e47",
    "app/v2/developer_decision_router.py": "dd288a544567151369e629efc69b6eb1db117989",
    "app/v2/sensitivity_matrix_projection.py": "d6aa0d80d4222619053f07f25beaa429481f4ca0",
    "app/v2/sensitivity_matrix_router.py": "15c77bbc84b7443c4f716185ccf9161720d40d68",
    "app/workbook/developer_economics_config.py": "e9a3f1a2eff7821e54d192a4df2ee1332aa09d42",
    "app/workbook/developer_economics_service.py": "2de4d39d85e19b0ab291bb64972eb59d3079365a",
    "app/workbook/registry.py": "4f9c5192e33e4158f8b7e4d1a35115daa94df19d",
    "tests/model_v2_governance.py": "bf197d35c79a99656821eb77c441a719415ee0a4",
    "app/workbook/revenue_multistream.py": "ec3c8c8e12acc049233a57a2b559cbb6e18acca6",
    "domain/revenue/advanced_products.py": "d4ab263422aac5571e52bee4925fe36588e853cc",
    "domain/revenue/multistream_runtime.py": "83beda4eb296b02baf2ebd6659fec243ab196206",
    "finco_core/revenue/generation.py": "35670dc7b5ab4ce01177f9df817a4776c10569ab",
}
RC2_PINNED_UNCHANGED = {                  # identical to main; verified by exact blob, not by diff
    "app/workbook/junior_debt_config.py": "ab70f8373e3f683390f4aa723e5c964d417bf81c",       # Junior activation gate (stays closed)
}
RC2_PROTECTED_FINANCIAL_CANDIDATE = frozenset({          # Revenue V3 - release-closed candidate (M2)
    "domain/revenue/multistream_runtime.py", "domain/revenue/advanced_products.py", "finco_core/revenue/generation.py",
})
RC2_ROUTER_MODIFIED_SHA256 = {
    "_build_revenue_contract_editor": "7f39d44027fd59842524e4210e0815c1381ede363d6f4b5acf008d63b1144d11",
    "v2_workbook_run": "19f1389b08e6915654c6adcbe587a28fad6da605cbefaacc68882e64a220439b",
}
RC2_ROUTER_NEW_MODULE_STATEMENTS = (      # M3 hook: the only module-level additions
    "from app.v2.sensitivity_matrix_router import router as sensitivity_matrix_router",
    "router.include_router(sensitivity_matrix_router)",
    "from app.v2.sensitivity_matrix_router import register_template_globals",
    "register_template_globals()",
)
RC2_CSRF_CALL_SITES = frozenset({
    "main_web.py", "app/v2/import_router.py", "app/v2/grid_router.py", "app/crypto_ui.py", "app/v2/router.py",
    "app/v2/investor_f4_router.py", "app/v2/developer_decision_router.py",
})
# Not an RC-2 free path: these are changed vs main but governed elsewhere or free by namespace.
RC2_GOVERNED_ELSEWHERE = frozenset({"app/trust_readiness/registry.py"})
RC2_FREE_PREFIXES = ("tests/", "docs/", "static/", "app/templates/")

RC2_CI_WORKFLOW = ".github/workflows/ci_public_job.yml"
RC2_CI_WORKFLOW_BASE_BLOB = "4c6b913605120673b626b8492a8201d5164e7b0d"
# REVIEW PROPOSAL ONLY: exact two-line CI successor (3300 -> 4200; 75 -> 90).
RC2_CI_WORKFLOW_CANDIDATE_BLOB = "29381575e1c58083613c0df854e096ba89b299be"
RC2_CI_PYTEST_OLD = "FINCO_CI_PYTEST_BUDGET_S: '3300'"
RC2_CI_PYTEST_NEW = "FINCO_CI_PYTEST_BUDGET_S: '4200'"
RC2_CI_JOB_TIMEOUT_OLD = "timeout-minutes: 75"
RC2_CI_JOB_TIMEOUT_NEW = "timeout-minutes: 90"



# CURRENT R4 successor proposal. These are exact, current HEAD Git blobs;
# they do not modify or substitute any historical RC-2 blob pin above.
R4_SUCCESSOR_BLOBS = {
    "app/api/v1/crypto_router.py": "cd6cf33285e60f1ce65000fd893682ad064bf63d",
    "app/crypto_terminal/tokenized_read.py": "b5aeb78999b522bbe316e7283910b717268c5cec",
    "app/radar_ui/tokenized_monitor_v2.py": "1f92457a8480c18fb795edf0c68d08d9eb1b82ec",
    "app/radar_ui/tokenized_router.py": "73a500c6a19ea2415b4d55527dc949191c46b22e",
}
R4_PRESENTATION_BLOBS = {
    "app/templates/radar/tokenized_markets.html": "e74ffaab6a9aebea7035a4f7fb9cb6eb1bb6b904",
    "app/templates/radar/tokenized_markets_detail.html": "d90194c500c5276dcb5661cfe75cbe12d85bf546",
    "static/css/radar-monitor-v2.css": "66c6257a467ee272b8490c43c25b3ce69de0ee03",
}
R4_SECURITY_GUARD_BLOBS = {
    # Future test/entitlement/security edits require a separate exact-content review.
    "tests/test_radar_r4_tokenized_monitor_v2.py": "40b08e2c5de0a8656c56a3406aadc196f6b9ca0c",
    "tests/test_rc2_integration_acceptance.py": "75636323ad213eb13fa6c7638d76de78daf4e440",
    "tests/test_trust_readiness_registry.py": "5d768d30e3956a1c1be90327260bc2278515d389",
    "tools/public_safety_scan.py": "b2484f8da1e71fa01ad9e4ebaf77acb289b9e392",
    "app/radar_ui/tokenized_gating.py": "5c541b08fb6b90087ea41303b8d4e0f17338f3fc",
    "app/crypto_api_access.py": "db4fb92b6ade77e96372ecc14d65b246bf5b2810",
    "app/tokenized_access.py": "d777e372aadd7be8a4ee2f646f48dd5f8f8f52d8",
}
# Every changed R4 file has an explicit path and change type; no path wildcards.
R4_EXACT_CHANGE_STATUS = {
    "app/api/v1/crypto_router.py": "M",
    "app/crypto_terminal/tokenized_read.py": "M",
    "app/radar_ui/tokenized_monitor_v2.py": "A",
    "app/radar_ui/tokenized_router.py": "M",
    "app/templates/radar/tokenized_markets.html": "M",
    "app/templates/radar/tokenized_markets_detail.html": "M",
    "static/css/radar-monitor-v2.css": "A",
    "tests/test_radar_r4_tokenized_monitor_v2.py": "A",
    "docs/radar/R4_TOKENIZED_MONITOR_V2.md": "A",
    "tests/test_rc2_integration_manifest.py": "M",
}
R4_FROZEN_PREFIXES = (
    "financial_engine/", "finco_core/", "finco_yield/",
    "finco_radar/venues/", "finco_radar/signals/", "finco_radar/history/",
    "app/radar_rwa/",
)
R4_FROZEN_PATHS = frozenset({
    "app/crypto_terminal/deepstate_composition.py",
    "tools/public_safety_scan.py",
})

RC2_ACTIVATION_FLAG_FILES = {                 # path -> flag name; both must be a single literal ``False`` assignment
    "domain/revenue/advanced_products.py": "ACTIVATION_ENABLED",
    "app/workbook/junior_debt_config.py": "ACTIVATION_ENABLED",
}


def activation_state(source: str, name: str = "ACTIVATION_ENABLED") -> str:
    """``"CLOSED"`` only when the module binds ``name`` exactly once, at module level, to the literal ``False``.

    AST based: ``True``, any expression (``not True``, ``os.environ...``, ``a or b``), a conditional or second binding,
    augmented/annotated/walrus/loop/with/global rebinding, deletion, and string-keyed dynamic writes
    (``globals()["ACTIVATION_ENABLED"]``, ``setattr(module, "ACTIVATION_ENABLED", ...)``) are all NOT closed.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "UNPARSEABLE"
    bindings = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, (ast.Store, ast.Del))]
    bindings += [n for n in ast.walk(tree) if isinstance(n, ast.Global) and name in n.names]
    if any(isinstance(n, ast.Constant) and n.value == name for n in ast.walk(tree)):
        return "DYNAMIC_REFERENCE"
    top = [n for n in tree.body if isinstance(n, (ast.Assign, ast.AnnAssign)) and (
        (isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name)
        or (isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == name))]
    if len(top) != 1 or len(bindings) != 1:
        return "NOT_A_SINGLE_TOP_LEVEL_BINDING"
    value = top[0].value
    if isinstance(value, ast.Constant) and value.value is False:
        return "CLOSED"
    return "NOT_LITERAL_FALSE"


def rc2_workflow_delta_valid(baseline: str, candidate: str) -> bool:
    """Exactly two reviewed CI substitutions; neither permits any third workflow edit."""
    return (
        isinstance(baseline, str)
        and isinstance(candidate, str)
        and baseline.count(RC2_CI_PYTEST_OLD) == 1
        and baseline.count(RC2_CI_PYTEST_NEW) == 0
        and baseline.count(RC2_CI_JOB_TIMEOUT_OLD) == 1
        and baseline.count(RC2_CI_JOB_TIMEOUT_NEW) == 0
        and candidate.count(RC2_CI_PYTEST_NEW) == 1
        and candidate.count(RC2_CI_JOB_TIMEOUT_NEW) == 1
        and candidate == baseline.replace(RC2_CI_PYTEST_OLD, RC2_CI_PYTEST_NEW, 1).replace(
            RC2_CI_JOB_TIMEOUT_OLD, RC2_CI_JOB_TIMEOUT_NEW, 1)
    )


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def _router_parts(source):
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    functions, others = {}, []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            functions[node.name] = "".join(lines[start - 1:node.end_lineno])
        else:
            others.append(ast.unparse(node))
    return functions, others


def rc2_violations(f) -> list[str]:
    """Pure fail-closed verifier over injected facts; [] means the manifest holds."""
    try:
        problems, previous = [], RC2_BASE_MAIN
        seen_paths = set()
        for _status, _path in f["status"]:                      # from #279: a real name-status diff lists each path once
            if _path in seen_paths:
                problems.append(f"{_path}: duplicate cumulative diff entry is malformed evidence")
            seen_paths.add(_path)
        if f["accepted_head"] != RC2_ACCEPTED_HEAD or f["release_merge_commit"] != RC2_MERGE_COMMIT:
            problems.append("historical RC-2 identity differs from immutable accepted commit/merge")
        if tuple(f["release_parents"]) != (RC2_BASE_MAIN, RC2_ACCEPTED_HEAD):
            problems.append("historical RC-2 main merge does not have the exact two parents")
        if not f["release_ancestor"]:
            problems.append("historical RC-2 main merge is not an ancestor of current HEAD")
        if f["accepted_tree"] != f["release_tree"]:
            problems.append("RC-2 merge tree differs from the exact accepted candidate tree")
        for pr, head in RC2_SOURCE_HEADS:
            merge = f["merges"].get(pr)
            if not f["ancestor"].get(pr) or merge is None:
                problems.append(f"#{pr}: reviewed head is not merged")
                continue
            sha, first, second = merge
            if second != head:
                problems.append(f"#{pr}: second parent is not the reviewed head")
            if first != previous:
                problems.append(f"#{pr}: first parent breaks the normal-merge chain")
            previous = sha
        for path, expected in RC2_EXACT_BLOBS.items():
            if f["blobs"].get(path) != expected:
                problems.append(f"{path}: not the exact reviewed blob")
        changed = {p for status, p in f["status"]}
        for status, path in f["status"]:
            if status not in ("A", "M"):
                problems.append(f"{path}: {status} is not permitted")
            elif not (path in RC2_EXACT_BLOBS or path == "app/v2/router.py" or path in RC2_GOVERNED_ELSEWHERE
                      or path.startswith(RC2_FREE_PREFIXES) or path == RC2_CI_WORKFLOW):
                problems.append(f"{path}: not part of the reviewed RC-2 content")
        # The sole non-default workflow exception is a proposed, byte-exact two-line CI delta.
        # Historical workflow boundaries remain closed; this is NOT reviewer authorization.
        if [status for status, path in f["status"] if path == RC2_CI_WORKFLOW] != ["M"]:
            problems.append("RC-2 CI workflow must be modified exactly once")
        if f["ci_workflow_base_blob"] != RC2_CI_WORKFLOW_BASE_BLOB:
            problems.append("RC-2 CI workflow baseline is not the reviewed main blob")
        if f["ci_workflow_head_blob"] != RC2_CI_WORKFLOW_CANDIDATE_BLOB:
            problems.append("RC-2 CI workflow has an unreviewed blob")
        if not rc2_workflow_delta_valid(f["ci_workflow_base"], f["ci_workflow_head"]):
            problems.append("RC-2 CI workflow differs from the two reviewed budget and job-timeout substitutions")
        for path, expected in RC2_PINNED_UNCHANGED.items():
            if f["blobs"].get(path) != expected:
                problems.append(f"{path}: not the exact reviewed blob")
        for path in sorted(set(RC2_EXACT_BLOBS) - changed):
            problems.append(f"{path}: reviewed change is missing")
        base_fn, base_other = _router_parts(f["router_base"])
        head_fn, head_other = _router_parts(f["router_head"])
        modified = {n for n in base_fn if n in head_fn and base_fn[n] != head_fn[n]}
        if modified != set(RC2_ROUTER_MODIFIED_SHA256) or set(head_fn) != set(base_fn):
            problems.append(f"router function delta is not the reviewed one: {sorted(modified)}")
        for name, expected in RC2_ROUTER_MODIFIED_SHA256.items():
            if name in head_fn and hashlib.sha256(head_fn[name].encode()).hexdigest() != expected:
                problems.append(f"router function {name} is not the reviewed text")
        added = [s for s in head_other if s not in base_other]
        if added != list(RC2_ROUTER_NEW_MODULE_STATEMENTS) or [s for s in base_other if s not in head_other]:
            problems.append(f"router module-level delta is not the reviewed M3 hook: {added}")
        if frozenset(f["call_sites"]) != RC2_CSRF_CALL_SITES:
            problems.append("CSRF validation call sites differ from the reviewed inventory")
        for path, flag in RC2_ACTIVATION_FLAG_FILES.items():
            state = activation_state(f["flag_sources"][path], flag)
            if state != "CLOSED":
                problems.append(f"{path}: {flag} is not a literal release-closed False ({state})")
        return problems
    except (KeyError, TypeError, ValueError, AttributeError, SyntaxError) as exc:
        return [f"facts incomplete or malformed: {exc!r}"]


def _git_text(*args):
    """Read Git object bytes as text without stripping trailing newlines."""
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def _ancestor(older, newer):
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", older, newer],
        cwd=ROOT, capture_output=True)
    if result.returncode not in (0, 1):
        raise subprocess.CalledProcessError(result.returncode, result.args)
    return result.returncode == 0


def _csrf_sites(ref):
    """Historical/current CSRF call inventory using only tracked Python commit content.

    This intentionally mirrors the original re.search semantics, including
    excluding app/trust_readiness. No mutable checkout or generic shell grep.
    Missing commit trees or required source objects fail closed.
    """
    import re
    paths = _git("ls-tree", "-r", "--name-only", ref, "--",
                 "app", "main_web.py").splitlines()
    if "main_web.py" not in paths:
        raise ValueError("CSRF proof missing canonical main_web.py")
    sites = set()
    for path in paths:
        if (path == "main_web.py" or (path.startswith("app/") and path.endswith(".py"))) \
                and not path.startswith("app/trust_readiness/"):
            contents = _git_text("show", f"{ref}:{path}")
            if re.search(r"(?<!def )validate_csrf_token\(", contents):
                sites.add(path)
    return sites


def _collect():
    """IMMUTABLE RC-2 historical proof, anchored to ACCEPTED_HEAD, never HEAD's tree.

    Missing commits, ancestry, source snapshots or grep evidence RAISE and fail CI.
    The source PR merge chain is recovered only from the pinned RC-2 candidate.
    """
    rows = [r.split() for r in _git(
        "rev-list", "--merges", "--parents",
        f"{RC2_BASE_MAIN}..{RC2_ACCEPTED_HEAD}").splitlines()]
    merges, ancestor = {}, {}
    for pr, source_head in RC2_SOURCE_HEADS:
        found = [r for r in rows if len(r) == 3 and r[2] == source_head]
        merges[pr] = tuple(found[0]) if len(found) == 1 else None
        ancestor[pr] = _ancestor(source_head, RC2_ACCEPTED_HEAD)

    status = [tuple(l.split("\t", 1)) for l in _git(
        "diff", "--name-status", "--no-renames",
        RC2_BASE_MAIN, RC2_ACCEPTED_HEAD).splitlines()]
    return {
        "accepted_head": _git("rev-parse", RC2_ACCEPTED_HEAD),
        "release_merge_commit": _git("rev-parse", RC2_MERGE_COMMIT),
        "release_parents": _git("rev-list", "-n", "1", "--parents",
                                RC2_MERGE_COMMIT).split()[1:],
        "accepted_tree": _git("rev-parse", f"{RC2_ACCEPTED_HEAD}^{{tree}}"),
        "release_tree": _git("rev-parse", f"{RC2_MERGE_COMMIT}^{{tree}}"),
        "release_ancestor": _ancestor(RC2_MERGE_COMMIT, "HEAD"),
        "merges": merges, "ancestor": ancestor, "status": status,
        "call_sites": _csrf_sites(RC2_ACCEPTED_HEAD),
        "blobs": {p: _git("rev-parse", f"{RC2_ACCEPTED_HEAD}:{p}")
                  for p in (*RC2_EXACT_BLOBS, *RC2_PINNED_UNCHANGED)},
        "ci_workflow_base_blob": _git("rev-parse", f"{RC2_BASE_MAIN}:{RC2_CI_WORKFLOW}"),
        "ci_workflow_head_blob": _git("rev-parse", f"{RC2_ACCEPTED_HEAD}:{RC2_CI_WORKFLOW}"),
        "ci_workflow_base": _git_text("show", f"{RC2_BASE_MAIN}:{RC2_CI_WORKFLOW}"),
        "ci_workflow_head": _git_text("show", f"{RC2_ACCEPTED_HEAD}:{RC2_CI_WORKFLOW}"),
        "router_base": _git_text("show", f"{RC2_BASE_MAIN}:app/v2/router.py"),
        "router_head": _git_text("show", f"{RC2_ACCEPTED_HEAD}:app/v2/router.py"),
        "flag_sources": {p: _git_text("show", f"{RC2_ACCEPTED_HEAD}:{p}")
                         for p in RC2_ACTIVATION_FLAG_FILES},
    }


def _collect_r4(ref=R4_REVIEWED_HEAD):
    """Distinct R4 successor proof, anchored to the reviewed R4 source head ``ref`` (an ancestor of the integrated HEAD)."""
    paths = (*R4_SUCCESSOR_BLOBS, *R4_PRESENTATION_BLOBS, *R4_SECURITY_GUARD_BLOBS,
             *RC2_EXACT_BLOBS, *RC2_PINNED_UNCHANGED,
             RC2_CI_WORKFLOW)
    status = [tuple(l.split("\t", 1)) for l in _git(
        "diff", "--name-status", "--no-renames", RC2_MERGE_COMMIT, ref).splitlines()]
    return {
        "rc2_ancestor": _ancestor(RC2_MERGE_COMMIT, ref),
        "accepted_ancestor": _ancestor(RC2_ACCEPTED_HEAD, ref), "ref_is_ancestor_of_head": _ancestor(ref, "HEAD"),
        "status": status,
        "blobs": {p: _git("rev-parse", f"{ref}:{p}") for p in paths},
        "call_sites": _csrf_sites(ref),
        "flag_sources": {p: _git_text("show", f"{ref}:{p}")
                         for p in RC2_ACTIVATION_FLAG_FILES},
    }


def r4_successor_violations(current, historical):
    """Exact-path successor admission; never changes RC-2 immutable review facts."""
    errors = rc2_violations(historical)
    try:
        if current["rc2_ancestor"] is not True or current["accepted_ancestor"] is not True:
            errors.append("R4 is not descended from the accepted RC-2 main merge")
        actual = current["status"]
        if not isinstance(actual, list) or len(actual) != len(R4_EXACT_CHANGE_STATUS):
            errors.append("R4 modified-file set differs from the exact reviewed inventory")
        if dict((path, status) for status, path in actual) != R4_EXACT_CHANGE_STATUS:
            errors.append("R4 changed paths/status differ from reviewed exact-file inventory")
        for path, expected in {**R4_SUCCESSOR_BLOBS, **R4_PRESENTATION_BLOBS,
                               **R4_SECURITY_GUARD_BLOBS}.items():
            if current["blobs"].get(path) != expected:
                errors.append(f"{path}: unreviewed R4 successor blob")
        for path, expected in {**RC2_EXACT_BLOBS, **RC2_PINNED_UNCHANGED}.items():
            if path not in R4_SUCCESSOR_BLOBS and current["blobs"].get(path) != expected:
                errors.append(f"{path}: original RC-2 or financial authority modified")
        if current["blobs"].get(RC2_CI_WORKFLOW) != RC2_CI_WORKFLOW_CANDIDATE_BLOB:
            errors.append("R4 changed the exact-approved Public Safety workflow")
        for status, path in actual:
            if path.startswith(R4_FROZEN_PREFIXES) or path in R4_FROZEN_PATHS:
                errors.append(f"{path}: forbidden frozen namespace/path modification")
        if frozenset(current["call_sites"]) != RC2_CSRF_CALL_SITES:
            errors.append("R4 changed the existing CSRF validation inventory")
        for path, flag in RC2_ACTIVATION_FLAG_FILES.items():
            state = activation_state(current["flag_sources"][path], flag)
            if state != "CLOSED":
                errors.append(f"{path}: CURRENT release-closed activation changed ({state})")
    except (KeyError, TypeError, ValueError, AttributeError, SyntaxError) as exc:
        errors.append(f"R4 successor proof missing or malformed: {exc!r}")
    return errors


@pytest.fixture(scope="module")
def facts():
    # No skip on a descendant: missing Git evidence is always a failure.
    return _collect()


@pytest.fixture(scope="module")
def r4_facts():
    return _collect_r4()


def test_manifest_holds_for_the_integrated_candidate_on_the_actual_observed_state(facts):
    # No replacement/normalisation of any fact: the real sources of both release-closed flags are judged.
    assert rc2_violations(facts) == []
    assert all(activation_state(facts["flag_sources"][p], n) == "CLOSED" for p, n in RC2_ACTIVATION_FLAG_FILES.items())
    assert RC2_PROTECTED_FINANCIAL_CANDIDATE <= set(RC2_EXACT_BLOBS)
    assert "app/workbook/junior_debt_config.py" in RC2_PINNED_UNCHANGED and "domain/revenue/advanced_products.py" in RC2_EXACT_BLOBS


@pytest.mark.parametrize("path", sorted(RC2_ACTIVATION_FLAG_FILES))
@pytest.mark.parametrize("mutation", [
    ("ACTIVATION_ENABLED = False", "ACTIVATION_ENABLED = True"),
    ("ACTIVATION_ENABLED = False", "ACTIVATION_ENABLED = not False"),
    ("ACTIVATION_ENABLED = False", "import os\nACTIVATION_ENABLED = os.environ.get('X') == '1'"),
    ("ACTIVATION_ENABLED = False", "ACTIVATION_ENABLED = bool(0)"),
    ("ACTIVATION_ENABLED = False", "ACTIVATION_ENABLED = False\nACTIVATION_ENABLED = True"),
    ("ACTIVATION_ENABLED = False", "ACTIVATION_ENABLED = False\nACTIVATION_ENABLED |= True"),
    ("ACTIVATION_ENABLED = False", "ACTIVATION_ENABLED = False\nglobals()['ACTIVATION_ENABLED'] = True"),
    ("ACTIVATION_ENABLED = False", "ACTIVATION_ENABLED = False\nsetattr(__import__(__name__), 'ACTIVATION_ENABLED', True)"),
    ("ACTIVATION_ENABLED = False", "if True:\n    ACTIVATION_ENABLED = True\nelse:\n    ACTIVATION_ENABLED = False"),
    ("ACTIVATION_ENABLED = False", "ACTIVATION_ENABLED: bool = True"),
    ("ACTIVATION_ENABLED = False", "ACTIVATION_ENABLED = False if False else True"),
    ("ACTIVATION_ENABLED = False", "def _on():\n    global ACTIVATION_ENABLED\n    ACTIVATION_ENABLED = True\nACTIVATION_ENABLED = False"),
])
def test_real_source_mutated_to_true_or_dynamic_activation_is_rejected_by_the_same_validator(facts, path, mutation):
    old, new = mutation
    source = facts["flag_sources"][path]
    assert old in source, "the observed source must contain the literal closed assignment"
    mutated = copy.deepcopy(facts)
    mutated["flag_sources"][path] = source.replace(old, new, 1)
    problems = rc2_violations(mutated)
    assert any("literal release-closed False" in p for p in problems), (new, problems)


def test_missing_or_unparseable_flag_source_is_rejected(facts):
    for bad in ("", "def broken(:\n", "X = 1\n"):
        mutated = copy.deepcopy(facts)
        mutated["flag_sources"]["domain/revenue/advanced_products.py"] = bad
        assert rc2_violations(mutated)
    mutated = copy.deepcopy(facts)
    del mutated["flag_sources"]["app/workbook/junior_debt_config.py"]
    assert rc2_violations(mutated)


def test_every_other_mutation_is_rejected(facts):
    base = facts
    def bad(**changes):
        f = copy.deepcopy(base)
        f.update(changes)
        assert rc2_violations(f), changes
    for pr, head in RC2_SOURCE_HEADS:
        sha, first, second = base["merges"][pr]
        bad(merges={**base["merges"], pr: (sha, first, "2" * 40)})          # replaced source head
        bad(merges={**base["merges"], pr: (sha, "3" * 40, second)})         # wrong first parent
        bad(merges={**base["merges"], pr: None})
        bad(ancestor={**base["ancestor"], pr: False})
    for path in (*RC2_EXACT_BLOBS, *RC2_PINNED_UNCHANGED):                    # incl. every financial-candidate blob
        bad(blobs={**base["blobs"], path: "1" * 40})
        bad(blobs={k: v for k, v in base["blobs"].items() if k != path})
    for status, path in (("A", "financial_engine/new.py"), ("M", "app/persistence/run_history_repository.py"),
                         ("A", "finco_radar/venues/new.py"), ("D", "tests/test_ci_acceptance.py"),
                         ("M", "app/auth.py"), ("A", "app/v2/unreviewed_save.py"), ("A", ".github/workflows/x.yml")):
        bad(status=[*base["status"], (status, path)])
    router = base["router_head"]
    bad(router_head=router + "\n\n" + chr(64) + "router.post('/rogue')\nasync def v2_rogue():\n    return None\n")
    bad(router_head=router.replace("validate_csrf_token(form.get(\"csrf_token\"))", "True", 1))
    bad(router_head=router.replace("register_template_globals()\n", "", 1))
    bad(router_head=router + "\nimport rogue_unreviewed_module\n")
    bad(call_sites=set(base["call_sites"]) | {"app/v2/sensitivity_matrix_router.py"})   # silently adding CSRF is also a change
    bad(call_sites=set(base["call_sites"]) - {"app/v2/developer_decision_router.py"})
    assert rc2_violations({})                                                 # missing facts never authorise


def test_ci_workflow_is_the_exact_two_line_timeout_delta_and_rejects_other_edits(facts):
    assert facts["ci_workflow_base_blob"] == RC2_CI_WORKFLOW_BASE_BLOB
    assert facts["ci_workflow_head_blob"] == RC2_CI_WORKFLOW_CANDIDATE_BLOB
    assert rc2_workflow_delta_valid(facts["ci_workflow_base"], facts["ci_workflow_head"])
    assert rc2_violations(facts) == []

    def rejected(**changes):
        changed = copy.deepcopy(facts)
        changed.update(changes)
        assert rc2_violations(changed), changes

    candidate = facts["ci_workflow_head"]
    for source in (
        candidate.replace(RC2_CI_PYTEST_NEW, RC2_CI_PYTEST_OLD, 1),
        candidate.replace(RC2_CI_PYTEST_NEW, "FINCO_CI_PYTEST_BUDGET_S: '4300'", 1),
        candidate.replace(RC2_CI_JOB_TIMEOUT_NEW, RC2_CI_JOB_TIMEOUT_OLD, 1),
        candidate.replace(RC2_CI_JOB_TIMEOUT_NEW, "timeout-minutes: 95", 1),
        candidate.replace("FINCO_CI_EXIT_GRACE_S: '180'", "FINCO_CI_EXIT_GRACE_S: '120'", 1),
        candidate + "\n# unrelated workflow modification",
    ):
        assert source != candidate
        rejected(ci_workflow_head=source)
    rejected(ci_workflow_head_blob="0" * 40)
    rejected(ci_workflow_base_blob="0" * 40)
    rejected(status=[item for item in facts["status"] if item[1] != RC2_CI_WORKFLOW])
    rejected(status=[*facts["status"], ("M", RC2_CI_WORKFLOW)])
    for unrelated in (".github/workflows/public_safety_and_smoke.yml", ".github/workflows/unreviewed.yml"):
        rejected(status=[*facts["status"], ("M", unrelated)])


def test_historical_rc2_release_is_the_exact_normal_two_parent_tree(facts):
    assert facts["accepted_head"] == RC2_ACCEPTED_HEAD
    assert facts["release_merge_commit"] == RC2_MERGE_COMMIT
    assert tuple(facts["release_parents"]) == (RC2_BASE_MAIN, RC2_ACCEPTED_HEAD)
    assert facts["accepted_tree"] == facts["release_tree"]
    assert facts["release_ancestor"] is True
    assert rc2_violations(facts) == []


def test_r4_successor_exact_head_proof_and_current_release_gates(facts, r4_facts):
    assert rc2_violations(facts) == []
    assert r4_successor_violations(r4_facts, facts) == []
    assert dict((path, status) for status, path in r4_facts["status"]) == R4_EXACT_CHANGE_STATUS
    assert all(r4_facts["blobs"][p] == sha for p, sha in R4_SUCCESSOR_BLOBS.items())
    for path, flag in RC2_ACTIVATION_FLAG_FILES.items():
        assert activation_state(r4_facts["flag_sources"][path], flag) == "CLOSED"


@pytest.mark.parametrize("path", sorted({**R4_SUCCESSOR_BLOBS, **R4_PRESENTATION_BLOBS,
                                        **R4_SECURITY_GUARD_BLOBS}))
def test_r4_one_byte_change_in_each_individually_pinned_production_blob_is_denied(facts, r4_facts, path):
    # Simulate an actual one-byte edit and compute its real Git SHA-1 blob id.
    source = (ROOT / path).read_bytes()
    assert source
    mutated = source[:-1] + bytes([source[-1] ^ 1])
    git_blob = hashlib.sha1(b"blob " + str(len(mutated)).encode() + b"\0" + mutated).hexdigest()
    assert git_blob != {**R4_SUCCESSOR_BLOBS, **R4_PRESENTATION_BLOBS, **R4_SECURITY_GUARD_BLOBS}[path]
    changed = copy.deepcopy(r4_facts)
    changed["blobs"][path] = git_blob
    problems = r4_successor_violations(changed, facts)
    assert any(path in problem and "successor blob" in problem for problem in problems)


def test_r4_unrelated_production_and_frozen_namespace_edits_are_all_denied(facts, r4_facts):
    for path, status in (
        ("app/radar_ui/unapproved.py", "A"),
        ("app/api/v1/crypto_access_unreviewed.py", "M"),
        ("financial_engine/orchestrator.py", "M"),
        ("finco_core/revenue/new_authority.py", "A"),
        ("finco_yield/new.py", "A"),
        ("finco_radar/venues/basis.py", "M"),
        (".github/workflows/ci_public_job.yml", "M"),
        ("tests/test_trust_readiness_registry.py", "M"),
    ):
        changed = copy.deepcopy(r4_facts)
        changed["status"].append((status, path))
        assert r4_successor_violations(changed, facts), path


def test_r4_historical_mutations_cannot_be_hidden_by_successor_proof(facts, r4_facts):
    for mutation in (
        {"blobs": {**facts["blobs"], "app/crypto_terminal/tokenized_read.py": "1" * 40}},
        {"merges": {**facts["merges"], "275": (
            facts["merges"]["275"][0], facts["merges"]["275"][1], "2" * 40)}},
        {"merges": {**facts["merges"], "274": (
            facts["merges"]["274"][0], "3" * 40, facts["merges"]["274"][2])}},
        {"release_parents": [RC2_BASE_MAIN, "4" * 40]},
        {"accepted_tree": "5" * 40},
        {"release_tree": "6" * 40},
        {"accepted_head": "7" * 40},
        {"release_merge_commit": "8" * 40},
        {"release_ancestor": False},
        {"ci_workflow_head_blob": "9" * 40},
        {"ci_workflow_head": facts["ci_workflow_head"] + "\n# unauthorized"},
    ):
        corrupted = copy.deepcopy(facts)
        corrupted.update(mutation)
        assert r4_successor_violations(r4_facts, corrupted), mutation


def test_r4_current_financial_activation_and_csrf_must_still_be_closed(facts, r4_facts):
    for path in RC2_ACTIVATION_FLAG_FILES:
        mutated = copy.deepcopy(r4_facts)
        original = mutated["flag_sources"][path]
        assert "ACTIVATION_ENABLED = False" in original
        mutated["flag_sources"][path] = original.replace(
            "ACTIVATION_ENABLED = False", "ACTIVATION_ENABLED = True", 1)
        assert r4_successor_violations(mutated, facts)
    mutated = copy.deepcopy(r4_facts)
    mutated["call_sites"].add("app/api/v1/crypto_router.py")
    assert r4_successor_violations(mutated, facts)
    mutated = copy.deepcopy(r4_facts)
    mutated["blobs"][RC2_CI_WORKFLOW] = "a" * 40
    assert r4_successor_violations(mutated, facts)


def test_r4_missing_provenance_and_missing_git_evidence_fail_closed(facts, r4_facts):
    assert r4_successor_violations({}, facts)
    assert r4_successor_violations(r4_facts, {})
    for key in ("status", "blobs", "call_sites", "flag_sources", "rc2_ancestor", "accepted_ancestor"):
        mutated = copy.deepcopy(r4_facts)
        del mutated[key]
        assert r4_successor_violations(mutated, facts), key
    for key in ("release_parents", "release_tree", "merges", "blobs"):
        mutated = copy.deepcopy(facts)
        del mutated[key]
        assert r4_successor_violations(r4_facts, mutated), key


def test_missing_git_history_is_not_an_authorisation(monkeypatch):
    import sys
    def unavailable(*args):
        raise subprocess.CalledProcessError(1, ["git", *args])
    monkeypatch.setattr(sys.modules[__name__], "_git", unavailable)
    with pytest.raises(subprocess.CalledProcessError):
        _collect()
    with pytest.raises(subprocess.CalledProcessError):
        _collect_r4()
