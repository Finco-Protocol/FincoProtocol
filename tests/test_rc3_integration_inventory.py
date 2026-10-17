"""RC-3 combined integration inventory (REVIEW PROPOSAL - not an approval of any financial authority).

Binds the integrated HEAD to the union of the five reviewed source heads. The oracle is live Git state of the pinned source commits
and the pinned base, NOT values generated from the current tree:

 1. exact integration base (commit + tree) and the historical RC-1/RC-2 checkpoints;
 2. the five pinned source heads, present and ancestors of HEAD;
 3. the five ordered ``--no-ff`` merge commits: first parent chain from the base, second parent == the pinned source head;
 4. inclusion of every source tree: each path a source changed carries that source's blob at HEAD, unless it is a DOCUMENTED shared
    path (auto-merge paths must equal an independent ``git merge-file`` of the sources; hand-resolved paths are pinned);
 5. exact integrated path/status inventory == union of the source diffs + the explicit INTEGRATION_ADDED / INTEGRATION_EDITED lists;
 6. exact financial / security / model-authority blobs: every change under a frozen namespace is a source-owned M7 path whose blob
    equals the reviewed M7 head, and the eleven protected blobs of the M7 candidate manifest match;
 7. no unexplained source-content replacement (the multi-source overlap set must equal the documented shared set);
 8. documented shared-file resolutions keep every source's distinguishing markers;
 9. protected workflows, test selection, tolerances and goldens are byte-identical to the base;
10. release-closed flags are literal ``False`` and the M7 candidate manifest stays ``release_approved:false``.

Passing this file is NOT a financial approval: M7 candidate acceptance and production activation are separate decisions that are
still pending (see docs/rc3/RC3_INTEGRATION_CORRECTION_A.md). The owner gates over financial authority stay red until then.
"""
import copy
import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.test_rc2_integration_manifest import (
    RC2_ACCEPTED_HEAD, RC2_ACTIVATION_FLAG_FILES, RC2_BASE_MAIN, RC2_CI_WORKFLOW, RC2_CI_WORKFLOW_CANDIDATE_BLOB, RC2_MERGE_COMMIT,
    activation_state,
)
from tests.test_trust_readiness_registry import RC1_BASE_MAIN, RC1_MERGED_CHECKPOINT, RC1_MERGED_PARENTS

ROOT = Path(__file__).resolve().parent.parent
BASE = RC2_MERGE_COMMIT                                    # 6fc77de - the integration base (current main)
BASE_TREE = "4fdcd03b5e0ed3c4b87d9016f2522bfe50bf0d05"
SOURCES = (                                                # merge order; PR number -> reviewed head
    (280, "8378e5df30ec10b4de2b2f5330491837a7cd1ffb"),
    (279, "9f93dc843eed8f2f2cf7f11cf409fffd003ce70f"),
    (281, "5c6963879d8bdf0a16458011a5cfe6011fd36021"),
    (282, "63f1ded39ab90db24f3503c9fe62e9d7029ea017"),
    (283, "62424a8b777133631f4253d75848ba8c846f83e6"),
)
M7_PR = 283
# Post-merge anchoring (PR #284 is on main): the integrated candidate is judged as this pinned, immutable commit; HEAD is then bound to it.
INTEGRATION_HEAD = "b17d3341336fed89624662360c4164184476e7a2"
PR_MERGE = "4527ceadea7a5b9a8c3e2e63eb9fb3395ef9b66e"            # the normal two-parent merge of PR #284 into main
STREAM_TIP = "f2a1e386481b11a0a2b5fb8a73206403c839a480"   # merge of #282: every non-financial stream, not M7
FROZEN_PREFIXES = ("financial_engine/", "finco_core/", "domain/", "finco_radar/", "finco_yield/", "app/radar_rwa/")
GUARDED_PREFIXES = (".github/",)
GUARDED_FILES = ("pytest.ini", "requirements.txt", "requirements-ci-tests.txt", "constraints.txt", "pyproject.toml")
GUARDED_NAME_PARTS = ("tolerance", "golden")                # financial tolerances / goldens: byte-identical to the base
M7_MANIFEST = "docs/model_v2/M7_BESS_FINANCIAL_CANDIDATE_MANIFEST.json"
from tests.m7_rc3_candidate_successor import M7_RC3_CANDIDATE_AUTHORITIES as M7_PROTECTED_BLOBS  # noqa: E402
FLAG_FILES = {**RC2_ACTIVATION_FLAG_FILES, "app/workbook/bess_config.py": "ACTIVATION_ENABLED",
              "app/model_v2/acquisition/economics.py": "ACTIVATION_ENABLED"}

# Paths touched by two or more sources whose union is produced by an independent three-way merge (no hand edits allowed).
AUTO_MERGED = {
    "app/api/project_runner.py": (282, 283),
    "app/v2/router.py": (282, 283),
    "app/templates/v2/workbook.html": (281, 283),
}
# Paths that needed a hand resolution. Their final content is a reviewed literal pin plus mandatory markers of every source.
HAND_RESOLVED = {
    "tests/test_rc2_integration_manifest.py": {
        "markers": ("R4_REVIEWED_HEAD", "R4_SUCCESSOR_BLOBS", "RC2_ACCEPTED_HEAD", "duplicate cumulative diff entry"),
    },
    "tests/test_trust_readiness_controls.py": {
        "markers": ("current_m6_successor_valid", "current_m7_successor_valid", "app/v2/acquisition_router.py", "CSRF_PROPOSAL"),
    },
    "tests/test_trust_readiness_registry.py": {
        "markers": ("_m6_exact_successor_valid", "_m7_successor_valid", "_csrf_call_sites_at", "_rc1_collect_post"),
    },
}
# Markers every auto-merged file must keep from EACH side (both sources' distinguishing content).
AUTO_MARKERS = {
    "app/api/project_runner.py": ("acquisition_source_candidate_v1", "bess_operating_audit"),
    "app/v2/router.py": ("bind_acquisition_source", "bess_candidate_router", "bess_workspace_router"),
    "app/templates/v2/workbook.html": ("model_diagnostics_v2.js", "model_bess_workspace.js"),
}
# Files the INTEGRATION itself added (not in any source) or edited on top of the sources. Literal reviewed blobs; the two files
# that cannot pin themselves (this test and its helper) are listed by path and reviewed as exact commit files.
INTEGRATION_ADDED = frozenset({
    "tests/test_rc3_r5_successor.py",
    "tests/rc3_historical_anchor.py",
    "tests/test_rc3_integration_inventory.py",
    "docs/rc3/RC3_INTEGRATION_CORRECTION_A.md",
    "docs/rc3/RC3_CORRECTION_B_M7_REVIEW_AND_CI_BUDGET.md",
    "tests/m7_rc3_candidate_successor.py",
    "tests/test_m7_rc3_candidate_successor.py",
})
INTEGRATION_SELF = frozenset({"tests/test_rc3_integration_inventory.py", "tests/rc3_historical_anchor.py"})


# ── RC-3 CI budget successor (owner-authorised budget only; NOT a financial approval) ───────────────────────────────────────
# Exactly two values of .github/workflows/ci_public_job.yml differ from the accepted RC-2 workflow (the file on the base):
#   FINCO_CI_PYTEST_BUDGET_S '4200' -> '4800'   and   timeout-minutes 90 -> 100.
# Everything else (grace, stall, selection, full unsharded run, artifacts, evidence, every other job step) must be byte-identical.
RC3_CI_WORKFLOW = RC2_CI_WORKFLOW
RC3_CI_WORKFLOW_BLOB = "036a5aef7cf9738b8bf7bf2f6294f24a998a928c"
RC3_CI_EDITS = (("timeout-minutes: 90", "timeout-minutes: 100"),
                ("FINCO_CI_PYTEST_BUDGET_S: '4200'", "FINCO_CI_PYTEST_BUDGET_S: '4800'"))


def workflow_successor_violations(base_text: str, head_text: str) -> list[str]:
    """Pure verifier: ``head_text`` must equal ``base_text`` with exactly the two authorised values replaced, and must still fit."""
    import re
    try:
        bad = []
        expected = base_text
        for old, new in RC3_CI_EDITS:
            if expected.count(old) != 1:
                bad.append(f"the accepted RC-2 workflow does not contain exactly one {old!r}")
                continue
            expected = expected.replace(old, new, 1)
        if head_text != expected:
            bad.append("the workflow differs from the accepted RC-2 workflow in more (or other) than the two authorised budget values")
        budget = int(re.search(r"FINCO_CI_PYTEST_BUDGET_S: '(\d+)'", head_text).group(1))
        grace = int(re.search(r"FINCO_CI_EXIT_GRACE_S: '(\d+)'", head_text).group(1))
        stall = int(re.search(r"FINCO_CI_STALL_S: '(\d+)'", head_text).group(1))
        timeout = int(re.search(r"timeout-minutes: (\d+)", head_text).group(1))
        if (budget, timeout) != (4800, 100) or grace != 180 or stall != 300:
            bad.append("budget/timeout/grace/stall are not the authorised 4800 s / 100 min / 180 s / 300 s")
        if budget + grace + 15 * 60 > timeout * 60:
            bad.append("the job timeout cannot accommodate budget + exit grace + job overhead")
        for needle in ("--junitxml=artifacts/results.xml", "tools/ci_pytest_runner.py", "FULL, UNSHARDED, EXACT HEAD",
                       "if-no-files-found: error", "public-verification-results"):
            if needle not in head_text:
                bad.append(f"required evidence/selection element is missing: {needle}")
        if "continue-on-error" in head_text or "--deselect" in head_text or "-k " in head_text:
            bad.append("test selection or failure handling was altered")
        return bad
    except (AttributeError, TypeError, ValueError) as exc:
        return [f"workflow facts incomplete or malformed: {exc!r}"]


# ── RC-5 CI runtime successor (owner-authorised limits only; NOT a financial approval) ──────────────────────────────────────────
# The FULL UNSHARDED suite outgrew the RC-3 budget (main at 97de3833 already used 4739 of 4800 s; the RC-5 integration needs 12,395 tests).
# Exactly three values of the accepted RC-3 workflow may differ, to the owner-approved limits below. Everything else (stall, selection,
# full unsharded run, artifacts, evidence, every other step and job) must stay byte-identical, and the job timeout must still contain
# budget + exit grace + job overhead, so a genuine timeout still ends in a non-zero exit.
RC5_CI_WORKFLOW_BLOB = "0fa7e2bec303bb94053fe7799186e666dd1e06a9"
RC5_CI_EDITS = (("timeout-minutes: 100", "timeout-minutes: 130"),
                ("FINCO_CI_PYTEST_BUDGET_S: '4800'", "FINCO_CI_PYTEST_BUDGET_S: '6000'"),
                ("FINCO_CI_EXIT_GRACE_S: '180'", "FINCO_CI_EXIT_GRACE_S: '240'"))


def rc5_workflow_successor_violations(rc3_text: str, head_text: str) -> list[str]:
    """Pure verifier: ``head_text`` must equal the accepted RC-3 workflow with exactly the three authorised values replaced, and must still fit."""
    import re
    try:
        bad = []
        expected = rc3_text
        for old, new in RC5_CI_EDITS:
            if expected.count(old) != 1:
                bad.append(f"the accepted RC-3 workflow does not contain exactly one {old!r}")
                continue
            expected = expected.replace(old, new, 1)
        if head_text != expected:
            bad.append("the workflow differs from the accepted RC-3 workflow in more (or other) than the three authorised limit values")
        budget = int(re.search(r"FINCO_CI_PYTEST_BUDGET_S: '(\d+)'", head_text).group(1))
        grace = int(re.search(r"FINCO_CI_EXIT_GRACE_S: '(\d+)'", head_text).group(1))
        stall = int(re.search(r"FINCO_CI_STALL_S: '(\d+)'", head_text).group(1))
        timeout = int(re.search(r"timeout-minutes: (\d+)", head_text).group(1))
        if (budget, timeout, grace, stall) != (6000, 130, 240, 300):
            bad.append("budget/timeout/grace/stall are not the authorised 6000 s / 130 min / 240 s / 300 s")
        if budget + grace + 15 * 60 > timeout * 60:
            bad.append("the job timeout cannot accommodate budget + exit grace + job overhead")
        for needle in ("--junitxml=artifacts/results.xml", "tools/ci_pytest_runner.py", "FULL, UNSHARDED, EXACT HEAD",
                       "if-no-files-found: error", "public-verification-results"):
            if needle not in head_text:
                bad.append(f"required evidence/selection element is missing: {needle}")
        if "continue-on-error" in head_text or "--deselect" in head_text or "-k " in head_text:
            bad.append("test selection or failure handling was altered")
        return bad
    except (AttributeError, TypeError, ValueError) as exc:
        return [f"workflow facts incomplete or malformed: {exc!r}"]


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def _tree(ref):
    """path -> blob for every file at ``ref`` (one Git call)."""
    out = {}
    for line in git("ls-tree", "-r", ref).splitlines():
        meta, path = line.split("\t", 1)
        out[path] = meta.split()[2]
    return out


def _status(a, b):
    rows = {}
    for line in git("diff", "--name-status", "--no-renames", a, b).splitlines():
        status, path = line.split("\t", 1)
        rows.setdefault(path, []).append(status)
    return rows


def _show(ref, path):
    return git("show", f"{ref}:{path}")


def _auto_merge_blob(path, a_pr, b_pr, heads):
    with tempfile.TemporaryDirectory() as tmp:
        files = {}
        for name, ref in (("a", heads[a_pr]), ("base", BASE), ("b", heads[b_pr])):
            target = Path(tmp) / name
            target.write_bytes(subprocess.run(["git", "show", f"{ref}:{path}"], cwd=ROOT, capture_output=True, check=True).stdout)
            files[name] = str(target)
        merged = subprocess.run(["git", "merge-file", "-p", files["a"], files["base"], files["b"]], cwd=ROOT, capture_output=True)
        if merged.returncode != 0:
            return None                                          # a conflict: no clean independent merge exists
        return subprocess.run(["git", "hash-object", "--stdin"], cwd=ROOT, input=merged.stdout, capture_output=True,
                              check=True).stdout.decode().strip()


POST_MERGE_PROTECTED = frozenset({M7_MANIFEST, *FLAG_FILES, "app/workbook/bess_config.py", ".github/workflows/ci_public_job.yml"})


def _blob_or_none(ref, path):
    proc = subprocess.run(["git", "rev-parse", f"{ref}:{path}"], cwd=ROOT, capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _pr_merge_parents(head):
    """Parents of the PR #284 merge commit, or None when it is not (yet) part of this history (pre-merge branch)."""
    if subprocess.run(["git", "merge-base", "--is-ancestor", PR_MERGE, head], cwd=ROOT).returncode != 0:
        return None
    return tuple(git("rev-list", "--parents", "-n", "1", PR_MERGE).split()[1:])


def collect(ref=INTEGRATION_HEAD, head="HEAD"):
    heads = dict(SOURCES)
    trees = {pr: _tree(sha) for pr, sha in SOURCES}
    head_tree, base_tree = _tree(ref), _tree(BASE)
    source_status = {pr: {p: s[0] for p, s in _status(BASE, sha).items()} for pr, sha in SOURCES}
    merge_rows = [r.split() for r in git("rev-list", "--first-parent", "--merges", "--reverse", "--parents", f"{BASE}..{ref}").splitlines()]
    return {
        "base": git("rev-parse", f"{BASE}^{{commit}}"), "base_tree": git("rev-parse", f"{BASE}^{{tree}}"),
        "base_parents": tuple(git("rev-list", "--parents", "-n", "1", BASE).split()[1:]),
        "rc1_parents": tuple(git("rev-list", "--parents", "-n", "1", RC1_MERGED_CHECKPOINT).split()[1:]),
        "heads": heads,
        "head_resolves": {pr: subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=ROOT).returncode == 0
                          for pr, sha in SOURCES},
        "ancestors": {pr: subprocess.run(["git", "merge-base", "--is-ancestor", sha, head], cwd=ROOT).returncode == 0
                      for pr, sha in SOURCES},
        "merges": merge_rows,                                   # [merge, parent0, parent1] oldest first
        "source_status": source_status,
        "source_blobs": {pr: {p: trees[pr].get(p) for p in source_status[pr]} for pr, _ in SOURCES},
        "head_status": {p: s[0] for p, s in _status(BASE, ref).items()},
        "head_blobs": head_tree, "base_blobs": base_tree,
        "m7_manifest": json.loads(_show(ref, M7_MANIFEST)),
        "m7_manifest_at_source": json.loads(_show(heads[M7_PR], M7_MANIFEST)),
        "auto_merge_oracle": {p: _auto_merge_blob(p, a, b, heads) for p, (a, b) in AUTO_MERGED.items()},
        "texts": {p: _show(ref, p) for p in {**AUTO_MARKERS, **HAND_RESOLVED}},
        "flag_sources": {p: _show(head, p) + "\n" for p in FLAG_FILES},             # flags are judged at the CURRENT head
        "integration_head": git("rev-parse", f"{ref}^{{commit}}"),
        "integration_head_ancestor": subprocess.run(["git", "merge-base", "--is-ancestor", INTEGRATION_HEAD, head], cwd=ROOT).returncode == 0,
        "pr_merge_parents": _pr_merge_parents(head),
        "post_merge_protected_delta": sorted(
            p for p in git("diff", "--name-only", INTEGRATION_HEAD, head).splitlines()
            if p in POST_MERGE_PROTECTED and not (
                p == RC3_CI_WORKFLOW and _blob_or_none(head, p) == RC5_CI_WORKFLOW_BLOB
                and not rc5_workflow_successor_violations(_show(ref, p) + "\n", _show(head, p) + "\n"))),
        "ci_workflow_current_text": _show(head, RC3_CI_WORKFLOW) + "\n",
        "m7_blobs_at_head": {p: _blob_or_none(head, p) for p in M7_PROTECTED_BLOBS},
        "stream_tip_status": {p: s[0] for p, s in _status(BASE, STREAM_TIP).items()},
        "ci_workflow_base_text": git("show", f"{BASE}:{RC3_CI_WORKFLOW}") + "\n",
        "ci_workflow_head_text": git("show", f"{ref}:{RC3_CI_WORKFLOW}") + "\n",
    }


def inventory_violations(f) -> list[str]:
    """Pure, fail-closed verifier over injected facts. [] means HEAD is exactly the documented union of the five sources."""
    try:
        bad = []
        # 1. base + historical checkpoints
        if f["base"] != BASE or f["base_tree"] != BASE_TREE:
            bad.append("integration base is not the exact reviewed main commit/tree")
        if f["base_parents"] != (RC2_BASE_MAIN, RC2_ACCEPTED_HEAD):
            bad.append("historical RC-2 merge provenance changed")
        if f["rc1_parents"] != RC1_MERGED_PARENTS or RC1_MERGED_CHECKPOINT != RC2_BASE_MAIN or RC1_BASE_MAIN not in RC1_MERGED_PARENTS:
            bad.append("historical RC-1 checkpoint provenance changed")
        # 2. sources
        if tuple(sorted(f["heads"].items())) != tuple(sorted(SOURCES)):
            bad.append("source head pins differ from the reviewed set")
        for pr, _ in SOURCES:
            if not f["head_resolves"].get(pr):
                bad.append(f"#{pr}: reviewed source head is missing from this checkout")
            if f["ancestors"].get(pr) is not True:
                bad.append(f"#{pr}: reviewed source head is not an ancestor of HEAD")
        # 3. ordered --no-ff merges
        merges = f["merges"]
        if len(merges) < len(SOURCES):
            bad.append("fewer first-parent merge commits than reviewed sources")
        else:
            previous = BASE
            for (pr, sha), row in zip(SOURCES, merges):
                if len(row) != 3 or row[2] != sha:
                    bad.append(f"#{pr}: merge second parent is not the pinned source head or merge is not a two-parent merge")
                if len(row) == 3 and row[1] != previous:
                    bad.append(f"#{pr}: merge first parent breaks the ordered --no-ff chain")
                previous = row[0]
        # 5/7. exact path+status inventory == union of sources + explicit integration lists
        owners = {}
        for pr, rows in f["source_status"].items():
            for path, status in rows.items():
                owners.setdefault(path, {})[pr] = status
        multi = {p for p, o in owners.items() if len(o) > 1}
        undocumented = multi - set(AUTO_MERGED) - set(HAND_RESOLVED)
        if undocumented:
            bad.append(f"paths changed by several sources without a documented resolution: {sorted(undocumented)}")
        expected_status = {}
        for path, o in owners.items():
            statuses = set(o.values())
            if statuses - {"A", "M"}:
                bad.append(f"{path}: source status {sorted(statuses)} is not an addition/modification")
            expected_status[path] = "A" if statuses == {"A"} else "M"
        for path in INTEGRATION_ADDED:
            if path in expected_status:
                bad.append(f"{path}: listed as integration-added but also changed by a source")
            expected_status[path] = "A"
        expected_status.setdefault(RC3_CI_WORKFLOW, "M")         # the single owner-authorised CI budget successor
        for path in PINNED_INTEGRATION_EDITS:                    # integration edits on top of main files or source files
            expected_status.setdefault(path, "M" if path in f["base_blobs"] else "A")
        actual = f["head_status"]
        for path in sorted(set(actual) - set(expected_status)):
            bad.append(f"{path}: not part of the reviewed union (unauthorized file)")
        for path in sorted(set(expected_status) - set(actual)):
            bad.append(f"{path}: reviewed path is missing from HEAD")
        for path, status in expected_status.items():
            if path in actual and actual[path] != status:
                bad.append(f"{path}: status {actual[path]} differs from reviewed {status}")
        # 4/7. content inclusion
        shared = set(AUTO_MERGED) | set(HAND_RESOLVED)
        for path, o in owners.items():
            if path in shared or path in PINNED_INTEGRATION_EDITS:
                continue
            blobs = {f["source_blobs"][pr].get(path) for pr in o}
            if len(blobs) != 1 or None in blobs:
                bad.append(f"{path}: source blobs disagree or are missing")
            elif f["head_blobs"].get(path) not in blobs:
                bad.append(f"{path}: source content replaced or altered at HEAD")
        for path in AUTO_MERGED:
            oracle = f["auto_merge_oracle"].get(path)
            if oracle is None:
                bad.append(f"{path}: no clean independent three-way merge exists (needs a documented resolution)")
            elif f["head_blobs"].get(path) != oracle:
                bad.append(f"{path}: differs from the independent three-way merge of its sources")
        # 8. markers
        for path, markers in {**AUTO_MARKERS, **{p: v["markers"] for p, v in HAND_RESOLVED.items()}}.items():
            for marker in markers:
                if marker not in f["texts"].get(path, ""):
                    bad.append(f"{path}: lost the marker {marker!r} of a source")
        for path, blob in PINNED_INTEGRATION_EDITS.items():
            if f["head_blobs"].get(path) != blob:
                bad.append(f"{path}: not the reviewed integration edit")
        # 6. financial / security / model-authority blobs
        m7 = f["source_status"][M7_PR]
        m7_frozen = {p for p in m7 if p.startswith(FROZEN_PREFIXES)}
        head_frozen = {p for p in actual if p.startswith(FROZEN_PREFIXES)}
        if head_frozen != m7_frozen:
            bad.append(f"frozen-namespace changes at HEAD differ from the reviewed M7 set: {sorted(head_frozen ^ m7_frozen)}")
        for path in m7_frozen:
            if f["head_blobs"].get(path) != f["source_blobs"][M7_PR].get(path):
                bad.append(f"{path}: financial blob differs from the reviewed M7 head")
        manifest = f["m7_manifest"]
        if manifest != f["m7_manifest_at_source"]:
            bad.append("M7 financial candidate manifest differs from the reviewed M7 head")
        if manifest.get("release_approved") is not False or manifest.get("status") != "CANDIDATE_REVIEW_ONLY":
            bad.append("M7 candidate manifest asserts a release it does not have")
        if len(manifest.get("protected_blobs", {})) != 11:
            bad.append("M7 candidate manifest does not list exactly the eleven protected blobs")
        for path, blob in manifest.get("protected_blobs", {}).items():
            if f["head_blobs"].get(path) != blob:
                bad.append(f"{path}: not the exact manifest-pinned M7 candidate blob")
        stream_tip_frozen = {p for p in f["stream_tip_status"] if p.startswith(FROZEN_PREFIXES)}
        if stream_tip_frozen:
            bad.append(f"the historical-stream anchor tip changes frozen namespaces: {sorted(stream_tip_frozen)}")
        # 9. protected workflows / test selection / tolerances / goldens
        guarded = [p for p in f["base_blobs"] if p.startswith(GUARDED_PREFIXES) or p in GUARDED_FILES
                   or any(part in p.lower() for part in GUARDED_NAME_PARTS)]
        for path in guarded:
            if path == RC3_CI_WORKFLOW:
                continue                                          # judged by the exact successor below, never by a general exemption
            if f["head_blobs"].get(path) != f["base_blobs"].get(path):
                bad.append(f"{path}: protected workflow/selection/tolerance/golden file differs from the base")
        for path in actual:
            if (path.startswith(GUARDED_PREFIXES) or path in GUARDED_FILES) and path not in f["base_blobs"]:
                bad.append(f"{path}: unauthorized addition to a protected workflow/selection path")
        if f["base_blobs"].get(RC3_CI_WORKFLOW) != RC2_CI_WORKFLOW_CANDIDATE_BLOB:
            bad.append("the base workflow is not the accepted RC-2 two-line successor")
        if f["head_blobs"].get(RC3_CI_WORKFLOW) != RC3_CI_WORKFLOW_BLOB:
            bad.append("the CI workflow is not the reviewed RC-3 budget successor blob")
        bad += workflow_successor_violations(f["ci_workflow_base_text"], f["ci_workflow_head_text"])
        # the CURRENT workflow is either the accepted RC-3 workflow or exactly its RC-5 limit successor; nothing in between
        if f["ci_workflow_current_text"] != f["ci_workflow_head_text"]:
            bad += rc5_workflow_successor_violations(f["ci_workflow_head_text"], f["ci_workflow_current_text"])
        # 10. release-closed flags (judged at the current head)
        for path, name in FLAG_FILES.items():
            state = activation_state(f["flag_sources"][path], name)
            if state != "CLOSED":
                bad.append(f"{path}: {name} is not a literal release-closed False ({state})")
        # 11. post-merge binding of the current head to the pinned integrated candidate
        if f["integration_head"] != INTEGRATION_HEAD:
            bad.append("the integrated candidate is not the pinned immutable commit")
        if f["integration_head_ancestor"] is not True:
            bad.append("the integrated candidate is not an ancestor of the current head")
        parents = f["pr_merge_parents"]
        if parents is not None and tuple(parents) != (BASE, INTEGRATION_HEAD):
            bad.append("PR #284 was not merged as a normal two-parent merge of the pinned candidate")
        if f["post_merge_protected_delta"]:
            bad.append(f"protected release/CI/flag files changed after the integration: {f['post_merge_protected_delta']}")
        for path, blob in M7_PROTECTED_BLOBS.items():
            if f["m7_blobs_at_head"].get(path) != blob:
                bad.append(f"{path}: the M7 candidate blob changed after the integration (or is missing)")
        return bad
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        return [f"facts incomplete or malformed: {exc!r}"]


@pytest.fixture(scope="module")
def facts():
    return collect()


def test_the_integrated_head_is_exactly_the_documented_union_of_the_five_sources(facts):
    assert inventory_violations(facts) == []


def test_the_oracle_is_live_git_not_values_derived_from_the_current_tree(facts):
    # every expected content value comes from a pinned source commit or the pinned base, never from HEAD itself
    assert facts["head_resolves"] == {pr: True for pr, _ in SOURCES}
    assert set(facts["source_status"]) == {pr for pr, _ in SOURCES} and all(facts["source_status"].values())
    assert all(facts["auto_merge_oracle"].values())


def test_m7_candidate_acceptance_is_not_asserted_here(facts):
    """Candidate-content binding only. Approval and activation stay separate and closed."""
    assert facts["m7_manifest"]["release_approved"] is False
    assert activation_state(facts["flag_sources"]["app/workbook/bess_config.py"], "ACTIVATION_ENABLED") == "CLOSED"


# ── negative mutation tests ────────────────────────────────────────────────────────────────────────────────────
def _bad(facts, **changes):
    mutated = copy.deepcopy(facts)
    mutated.update(changes)
    problems = inventory_violations(mutated)
    assert problems, changes
    return problems


def test_a_changed_blob_of_any_source_content_is_rejected(facts):
    sample = [p for p, o in facts["head_status"].items() if p not in set(AUTO_MERGED) | set(HAND_RESOLVED)
              and p not in INTEGRATION_ADDED and p not in PINNED_INTEGRATION_EDITS][:25]
    for path in sample:
        _bad(facts, head_blobs={**facts["head_blobs"], path: "1" * 40})
    for path in AUTO_MERGED:
        assert any(path in p for p in _bad(facts, head_blobs={**facts["head_blobs"], path: "2" * 40}))


def test_every_financial_blob_change_or_forged_manifest_is_rejected(facts):
    for path in facts["m7_manifest"]["protected_blobs"]:
        assert any(path in p for p in _bad(facts, head_blobs={**facts["head_blobs"], path: "3" * 40}))
    forged = copy.deepcopy(facts["m7_manifest"])
    forged["release_approved"] = True
    _bad(facts, m7_manifest=forged, m7_manifest_at_source=forged)
    shorter = copy.deepcopy(facts["m7_manifest"])
    shorter["protected_blobs"].pop("financial_engine/bess.py")
    _bad(facts, m7_manifest=shorter, m7_manifest_at_source=shorter)


def test_missing_source_wrong_ancestry_or_wrong_merge_order_is_rejected(facts):
    for pr, _ in SOURCES:
        _bad(facts, head_resolves={**facts["head_resolves"], pr: False})
        _bad(facts, ancestors={**facts["ancestors"], pr: False})
        _bad(facts, heads={**facts["heads"], pr: "4" * 40})
    swapped = [facts["merges"][1], facts["merges"][0], *facts["merges"][2:]]
    _bad(facts, merges=swapped)
    _bad(facts, merges=facts["merges"][:-1])
    wrong_parent = copy.deepcopy(facts["merges"])
    wrong_parent[2][1] = "5" * 40
    _bad(facts, merges=wrong_parent)
    squashed = copy.deepcopy(facts["merges"])
    squashed[0] = squashed[0][:2]
    _bad(facts, merges=squashed)


def test_unauthorized_forged_missing_or_restatused_inventory_entries_are_rejected(facts):
    status = facts["head_status"]
    for path in ("financial_engine/new_unreviewed.py", "finco_core/rogue.py", "domain/rogue.py", "app/v2/unreviewed_router.py",
                 ".github/workflows/rogue.yml", "tests/unreviewed_test.py"):
        assert any(path in p for p in _bad(facts, head_status={**status, path: "A"}))
    victim = next(p for p in status if p not in INTEGRATION_ADDED)
    _bad(facts, head_status={k: v for k, v in status.items() if k != victim})
    _bad(facts, head_status={**status, victim: "D"})
    # forging the SOURCE inventory to excuse an extra file is also caught by the independent oracle comparison
    forged_sources = copy.deepcopy(facts["source_status"])
    forged_sources[283]["financial_engine/new_unreviewed.py"] = "A"
    _bad(facts, source_status=forged_sources)


def test_overlapping_sources_must_have_a_documented_resolution(facts):
    forged = copy.deepcopy(facts["source_status"])
    forged[280]["app/model_v2/acquisition/economics.py"] = "M"           # a second owner without documentation
    assert any("without a documented resolution" in p for p in _bad(facts, source_status=forged))


def test_lost_source_markers_in_shared_files_are_rejected(facts):
    for path, markers in {**AUTO_MARKERS, **{p: v["markers"] for p, v in HAND_RESOLVED.items()}}.items():
        for marker in markers:
            texts = {**facts["texts"], path: facts["texts"][path].replace(marker, "")}
            assert any(marker in p for p in _bad(facts, texts=texts)), (path, marker)


def test_changed_protected_workflow_selection_tolerance_or_golden_is_rejected(facts):
    base = facts["base_blobs"]
    guarded = [p for p in base if p.startswith(GUARDED_PREFIXES) or p in GUARDED_FILES]
    assert RC2_CI_WORKFLOW in guarded and "pytest.ini" in guarded
    for path in (RC2_CI_WORKFLOW, "pytest.ini", ".github/workflows/governance_history.yml"):
        _bad(facts, head_blobs={**facts["head_blobs"], path: "6" * 40})
    _bad(facts, head_blobs={**facts["head_blobs"], ".github/workflows/public_safety_and_smoke.yml": "7" * 40})
    _bad(facts, head_blobs={k: v for k, v in facts["head_blobs"].items() if k != "pytest.ini"})


def test_opened_activation_flags_are_rejected(facts):
    for path, name in FLAG_FILES.items():
        source = facts["flag_sources"][path]
        assert f"{name} = False" in source
        for new in (f"{name} = True", f"{name} = not False", f"{name} = bool(0)"):
            _bad(facts, flag_sources={**facts["flag_sources"], path: source.replace(f"{name} = False", new, 1)})


def test_historical_checkpoint_forgery_or_a_financial_stream_anchor_is_rejected(facts):
    _bad(facts, base="7" * 40)
    _bad(facts, base_parents=(RC2_BASE_MAIN, "8" * 40))
    _bad(facts, rc1_parents=("9" * 40, RC1_MERGED_PARENTS[1]))
    _bad(facts, stream_tip_status={**facts["stream_tip_status"], "financial_engine/bess.py": "A"})


def test_missing_or_malformed_facts_never_authorise(facts):
    assert inventory_violations({})
    for key in facts:
        assert inventory_violations({k: v for k, v in facts.items() if k != key}), key
    _bad(facts, merges="not-a-list")


# ── Reviewed integration edits (literal pins; generated once from the reviewed working tree, then frozen for review) ──────────
# Re-anchored historical-stream guards (tests/rc3_historical_anchor.py) and the successor modules anchored to their source heads.
PINNED_INTEGRATION_EDITS = {
    "tests/m6_exact_content_successor.py": "355c1b180e4c3e943a52cc2fc4f4472c86b9dcec",
    "tests/m7_bess_successor_proposal.py": "68976dc3367def588db343620cf1dd2cee77f569",
    "tests/test_crypto_p0_product_reality_reset.py": "12c5b96193456b9b5a2254bfcb6be3488bc86f4d",
    "tests/test_crypto_roadmap_q4_q1.py": "10ec5772ace6a672c85e6e31428ba0355a8e1c43",
    "tests/test_data_center_a3_1.py": "99a42f79501f8f29441445c776e6dc4e2bdc5384",
    "tests/test_m3_two_driver_sensitivity.py": "2f447efd18e2198c5d6805bc43636de9c15b28e6",
    "tests/test_m6_exact_content_successor.py": "4eda2579375045442c326395b6b7ea6ecf193f4b",
    "tests/test_m7_bess_successor_proposal.py": "b0b17ae9219686c1439e361dd29248608de3a132",
    "tests/test_model_market_bridge.py": "874c4e7c3ebe2853d6fa3f6c07a82f5f6cc96108",
    "tests/test_model_v2_assumption_trace_references.py": "02a5c27e2ac2e9ca69cf177c754e03f4987383bd",
    "tests/test_model_v2_cost_templates.py": "29ff769b7841c0b9da0c34fc3f4b0759ea0ed29b",
    "tests/test_model_v2_cost_templates_cd.py": "2c001b8f6d91d1608e00c67a2be357821bdab218",
    "tests/test_model_v2_revenue_runtime_parity.py": "e200112fd0b7078175ec8c7a75ca690b15f42b5e",
    "tests/test_multi_source_evidence_v2.py": "f4f2ece723086a8c2cd2a7e4f65e616e663b07a9",
    "tests/test_opus_c1_product_truth.py": "368e25cd61bb3d88db2c5883c037e4e9e8bda979",
    "tests/test_p0a_model_execution.py": "5d93732cf91418cff42486b90aaf1a5944c01dc1",
    "tests/test_p1_2_xlsx_export_reconciliation.py": "c106feb77de7199e2174650e17c10636c9d5bf22",
    "tests/test_p1_3_institutional_validation.py": "bc56c54ad057983532b1775488d03a4cef2d45ed",
    "tests/test_p3_run_certificate_v1.py": "2757a030f71c692d5fcd6c248f9642a6eab88baa",
    "tests/test_parallel_stream_frozen_diff.py": "585a2584cb00d42a81e3c6687bff53c3105d03cd",
    "tests/test_public_product_truth_sync.py": "f031f107cc19fab25667e19b0fe93e2a1e9a7789",
    "tests/test_radar_crypto_surface_coherence.py": "543b73fa192d4590301e99f38b935cc392df5ca8",
    "tests/test_radar_r3_deepstate_composition.py": "6be748f064ec3ae62cc798c524ae191a66c2edf3",
    "tests/test_radar_r4_tokenized_monitor_v2.py": "1efeb22a69d918db12f411935f9ccc9897f2277a",
    "tests/test_radar_tokenized_signal_lifecycle.py": "6ee72e35673d88c9ba1674843f92a5ce807c80e3",
    "tests/test_rc2_integration_manifest.py": "7f6a0b7adcf3848731fbec8a66947096c73dab0c",
    "tests/test_rc3_diagnostics_manifest.py": "d059db8872ef8d264ba2f9c5e4e867ac863aeb56",
    "tests/test_rc3_r5_successor.py": "3311c43fdbbea6331094d416874d50843380b2ab",
    "tests/test_rwa_integrity.py": "fc8e80bd075ac9b6e7fefcacdd388ca5acfe1ea6",
    "tests/test_staging_product_truth.py": "e403a97e78211320098061346a4b3de59fbe0510",
    "tests/test_stock_token_oracle_rejection.py": "42f7aa35aca055aa65e9b6593919ff799f22b4e1",
    "tests/test_tokenized_access_wiring.py": "093668b5c165dcc62d8ef06ca7547d2b3eecadec",
    "tests/test_tokenized_live_intelligence_v1.py": "d73438f270222e23adcb56dd2ab03aaeee0e4f70",
    "tests/test_tokenized_markets_composition.py": "c06a294f28a71b06643e75834998e380f467e4ab",
    "tests/test_trust_readiness_controls.py": "b662615b0106976d38b431bfc29dc0f2573118f2",
    "tests/test_trust_readiness_registry.py": "8bfd684d95358f94db15302385e310bedbcaea2e",
    "tests/test_yield_alerts_core.py": "ae01affe8673fa30c2a931f94846a8d0a279a8e6",
}


# ── RC-3 CI budget successor: negative tests ──────────────────────────────────────────────────────────────────────────────────
def test_the_actual_workflow_is_exactly_the_two_authorised_values(facts):
    assert workflow_successor_violations(facts["ci_workflow_base_text"], facts["ci_workflow_head_text"]) == []
    assert facts["base_blobs"][RC3_CI_WORKFLOW] == RC2_CI_WORKFLOW_CANDIDATE_BLOB          # historical RC-2 workflow blob unchanged
    assert facts["head_blobs"][RC3_CI_WORKFLOW] == RC3_CI_WORKFLOW_BLOB
    assert facts["ci_workflow_head_text"].count("timeout-minutes: 100") == 1


def _wf_bad(facts, transform):
    head = transform(facts["ci_workflow_head_text"])
    assert head != facts["ci_workflow_head_text"]
    assert workflow_successor_violations(facts["ci_workflow_base_text"], head)


@pytest.mark.parametrize("name,transform", [
    ("timeout reduced to the old 90", lambda t: t.replace("timeout-minutes: 100", "timeout-minutes: 90")),
    ("timeout reduced below the fit", lambda t: t.replace("timeout-minutes: 100", "timeout-minutes: 95")),
    ("timeout raised further", lambda t: t.replace("timeout-minutes: 100", "timeout-minutes: 120")),
    ("budget reduced to the old 4200", lambda t: t.replace("'4800'", "'4200'")),
    ("budget raised further", lambda t: t.replace("'4800'", "'5400'")),
    ("exit grace changed", lambda t: t.replace("FINCO_CI_EXIT_GRACE_S: '180'", "FINCO_CI_EXIT_GRACE_S: '240'")),
    ("stall changed", lambda t: t.replace("FINCO_CI_STALL_S: '300'", "FINCO_CI_STALL_S: '600'")),
    ("selection narrowed", lambda t: t.replace("--junitxml=artifacts/results.xml", "--junitxml=artifacts/results.xml -k not_slow")),
    ("tests deselected", lambda t: t.replace("-q -p tools.ci_pytest_inventory", "-q --deselect tests/x.py -p tools.ci_pytest_inventory")),
    ("failure ignored", lambda t: t.replace("    runs-on: ubuntu-24.04\n", "    runs-on: ubuntu-24.04\n    continue-on-error: true\n")),
    ("junit evidence removed", lambda t: t.replace("            --junitxml=artifacts/results.xml", "")),
    ("artifact upload softened", lambda t: t.replace("if-no-files-found: error", "if-no-files-found: ignore")),
    ("full-run step renamed", lambda t: t.replace("FULL, UNSHARDED, EXACT HEAD", "PARTIAL")),
    ("unauthorised extra step", lambda t: t + "      - name: extra\n        run: echo changed\n"),
    ("a trailing byte", lambda t: t + "# x\n"),
    ("permissions widened", lambda t: t.replace("contents: read", "contents: write")),
    ("runner changed", lambda t: t.replace("ubuntu-24.04", "ubuntu-latest")),
])
def test_every_other_workflow_modification_is_rejected(facts, name, transform):
    _wf_bad(facts, transform)


def test_the_successor_is_not_a_general_workflow_exemption(facts):
    for path in (".github/workflows/public_safety_and_smoke.yml", ".github/workflows/governance_history.yml",
                 ".github/workflows/pr_compile_and_safety.yml", ".github/workflows/ci_browser_job.yml"):
        _bad(facts, head_blobs={**facts["head_blobs"], path: "8" * 40})
        _bad(facts, head_status={**facts["head_status"], path: "M"})
    _bad(facts, head_status={**facts["head_status"], ".github/workflows/new_unreviewed.yml": "A"})
    _bad(facts, head_blobs={**facts["head_blobs"], RC3_CI_WORKFLOW: "9" * 40})                   # unreviewed workflow blob
    _bad(facts, base_blobs={**facts["base_blobs"], RC3_CI_WORKFLOW: "a" * 40})                   # forged RC-2 baseline
    assert workflow_successor_violations("", "")                                                 # missing facts never authorise
    assert workflow_successor_violations(facts["ci_workflow_base_text"], facts["ci_workflow_base_text"])   # the unchanged RC-2 file is not the successor


def _rc5_bad(facts, transform):
    base = facts["ci_workflow_head_text"]                   # the accepted RC-3 workflow (judged at the pinned integration commit)
    candidate = transform(facts["ci_workflow_current_text"])
    assert candidate != facts["ci_workflow_current_text"]
    assert rc5_workflow_successor_violations(base, candidate)


def test_the_rc5_workflow_is_exactly_the_three_authorised_limits_over_the_rc3_workflow(facts):
    head, current = facts["ci_workflow_head_text"], facts["ci_workflow_current_text"]
    assert rc5_workflow_successor_violations(head, current) == []
    assert RC3_CI_WORKFLOW_BLOB == facts["head_blobs"][RC3_CI_WORKFLOW]                      # the accepted RC-3 workflow is the baseline
    assert current.count("timeout-minutes: 130") == 1 and current.count("FINCO_CI_PYTEST_BUDGET_S: '6000'") == 1
    assert facts["post_merge_protected_delta"] == []                                          # only because the successor is exact


@pytest.mark.parametrize("name,transform", [
    ("timeout back to 100", lambda t: t.replace("timeout-minutes: 130", "timeout-minutes: 100")),
    ("timeout below the fit", lambda t: t.replace("timeout-minutes: 130", "timeout-minutes: 120")),
    ("timeout raised further", lambda t: t.replace("timeout-minutes: 130", "timeout-minutes: 150")),
    ("budget back to 4800", lambda t: t.replace("'6000'", "'4800'")),
    ("budget raised further", lambda t: t.replace("'6000'", "'7200'")),
    ("grace back to 180", lambda t: t.replace("FINCO_CI_EXIT_GRACE_S: '240'", "FINCO_CI_EXIT_GRACE_S: '180'")),
    ("grace raised further", lambda t: t.replace("FINCO_CI_EXIT_GRACE_S: '240'", "FINCO_CI_EXIT_GRACE_S: '600'")),
    ("stall changed", lambda t: t.replace("FINCO_CI_STALL_S: '300'", "FINCO_CI_STALL_S: '600'")),
    ("selection narrowed", lambda t: t.replace("--junitxml=artifacts/results.xml", "--junitxml=artifacts/results.xml -k not_slow")),
    ("tests deselected", lambda t: t.replace("-q -p tools.ci_pytest_inventory", "-q --deselect tests/x.py -p tools.ci_pytest_inventory")),
    ("failure ignored", lambda t: t.replace("    runs-on: ubuntu-24.04\n", "    runs-on: ubuntu-24.04\n    continue-on-error: true\n")),
    ("junit evidence removed", lambda t: t.replace("            --junitxml=artifacts/results.xml", "")),
    ("artifact upload softened", lambda t: t.replace("if-no-files-found: error", "if-no-files-found: ignore")),
    ("full-run step renamed", lambda t: t.replace("FULL, UNSHARDED, EXACT HEAD", "PARTIAL")),
    ("unauthorised extra step", lambda t: t + "      - name: extra\n        run: echo changed\n"),
    ("a trailing byte", lambda t: t + "# x\n"),
    ("permissions widened", lambda t: t.replace("contents: read", "contents: write")),
    ("runner changed", lambda t: t.replace("ubuntu-24.04", "ubuntu-latest")),
])
def test_every_other_rc5_workflow_modification_is_rejected(facts, name, transform):
    _rc5_bad(facts, transform)


def test_the_rc5_successor_is_not_a_general_exemption(facts):
    base = facts["ci_workflow_head_text"]
    assert rc5_workflow_successor_violations(base, base)                  # the unchanged RC-3 file is not the successor
    assert rc5_workflow_successor_violations("", "")                      # missing facts never authorise
    # An edit that does not match the pinned successor blob remains a protected post-merge delta in the real collector.
    assert RC5_CI_WORKFLOW_BLOB != RC3_CI_WORKFLOW_BLOB


def test_the_rc5_budget_fits_inside_the_job_timeout():
    budget, grace, overhead, timeout_min = 6000, 240, 15 * 60, 130
    assert budget + grace + overhead <= timeout_min * 60 and timeout_min * 60 - (budget + grace + overhead) >= 120


def test_the_authorised_budget_fits_inside_the_job_timeout():
    budget, grace, overhead, timeout_min = 4800, 180, 15 * 60, 100
    assert budget + grace + overhead <= timeout_min * 60 and timeout_min * 60 - (budget + grace + overhead) >= 120


# ── post-merge negative tests ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_merged_main_state_binds_head_to_the_pinned_candidate(facts):
    assert facts["integration_head"] == INTEGRATION_HEAD and facts["integration_head_ancestor"] is True
    if facts["pr_merge_parents"] is not None:                                     # on main: a normal two-parent merge of PR #284
        assert tuple(facts["pr_merge_parents"]) == (BASE, INTEGRATION_HEAD)
    assert facts["post_merge_protected_delta"] == []
    assert facts["m7_blobs_at_head"] == dict(M7_PROTECTED_BLOBS)


@pytest.mark.parametrize("path", sorted(M7_PROTECTED_BLOBS))
def test_a_one_byte_change_or_removal_of_any_m7_blob_after_the_merge_is_rejected(facts, path):
    assert any(path in p for p in _bad(facts, m7_blobs_at_head={**facts["m7_blobs_at_head"], path: "b" * 40}))
    _bad(facts, m7_blobs_at_head={k: v for k, v in facts["m7_blobs_at_head"].items() if k != path})
    _bad(facts, m7_blobs_at_head={**facts["m7_blobs_at_head"], path: None})


def test_post_merge_forgery_wrong_ancestry_or_rewritten_merge_is_rejected(facts):
    _bad(facts, integration_head="c" * 40)
    _bad(facts, integration_head_ancestor=False)
    _bad(facts, pr_merge_parents=(BASE,))                                          # squash-like single parent
    _bad(facts, pr_merge_parents=("d" * 40, INTEGRATION_HEAD))
    _bad(facts, pr_merge_parents=(BASE, "e" * 40))
    _bad(facts, pr_merge_parents=(INTEGRATION_HEAD, BASE))
    for path in sorted(POST_MERGE_PROTECTED):
        _bad(facts, post_merge_protected_delta=[path])


def test_a_reopened_flag_or_forged_manifest_after_the_merge_is_rejected(facts):
    for path, name in FLAG_FILES.items():
        source = facts["flag_sources"][path]
        _bad(facts, flag_sources={**facts["flag_sources"], path: source.replace(f"{name} = False", f"{name} = True", 1)})
    _bad(facts, post_merge_protected_delta=[M7_MANIFEST])
    forged = copy.deepcopy(facts["m7_manifest"])
    forged["release_approved"] = True
    _bad(facts, m7_manifest=forged, m7_manifest_at_source=forged)
