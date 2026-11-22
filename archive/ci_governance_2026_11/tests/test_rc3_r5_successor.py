"""R5 (Tokenized Signal Lifecycle) exact-content successor, re-homed for the RC-3 integration.

Ported from PR #279's ``tests/test_rc2_integration_manifest.py`` (same constants, same verifier, same negatives). The historical RC-2
manifest is now anchored to the immutable accepted RC-2 head, so R5's rules live here and are anchored to the reviewed R5 source
head (an ancestor of the integrated HEAD). ``tests/test_rc3_integration_inventory.py`` binds the integrated HEAD to this content.
This is a REVIEW PROPOSAL, not an approval.
"""
import copy
import subprocess
from pathlib import Path

import pytest

from tests.test_rc2_integration_manifest import RC2_BASE_MAIN, RC2_MERGE_COMMIT, rc2_violations

ROOT = Path(__file__).resolve().parent.parent
R5_REVIEWED_HEAD = "9f93dc843eed8f2f2cf7f11cf409fffd003ce70f"
RC2_MERGE_PARENTS = (RC2_BASE_MAIN, "2155a76bfff4acc3a4e15f7cf35012933ce1a10c")
RC2_MERGED_TREE_BLOB = "4fdcd03b5e0ed3c4b87d9016f2522bfe50bf0d05"
RC3_R5_EXACT_PATH = "app/crypto_terminal/tokenized_signal_lifecycle.py"
RC3_R5_EXACT_BLOB = "6f3cb95782426dee5ed7dfa1a5bac71b29388014"
RC3_R5_ALLOWED_BRANCH_DELTA = frozenset({
    ("A", RC3_R5_EXACT_PATH),
    ("A", "tests/test_radar_tokenized_signal_lifecycle.py"),
    ("A", "docs/radar/R5_TOKENIZED_SIGNAL_LIFECYCLE_V1.md"),
    ("M", "tests/test_rc2_integration_manifest.py"),
})


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def rc3_r5_successor_violations(f) -> list[str]:
    """The sole proposed R5 delta: ONE added file at ONE exact Git blob (plus its declared support files)."""
    try:
        problems = []
        status = f["status"]
        if frozenset(f["rc3_branch_status"]) != RC3_R5_ALLOWED_BRANCH_DELTA or (
                len(f["rc3_branch_status"]) != len(RC3_R5_ALLOWED_BRANCH_DELTA)):
            problems.append("RC-3 successor contains an unexpected or missing branch-owned path/status")
        if [item for item in status if item[1] == RC3_R5_EXACT_PATH] != [("A", RC3_R5_EXACT_PATH)]:
            problems.append(f"{RC3_R5_EXACT_PATH}: successor requires exactly one A status")
        if f["rc3_r5_worktree_blob"] != RC3_R5_EXACT_BLOB:
            problems.append(f"{RC3_R5_EXACT_PATH}: not the exact reviewed candidate blob")
        if f["rc3_r5_head_blob"] != RC3_R5_EXACT_BLOB:
            problems.append(f"{RC3_R5_EXACT_PATH}: committed HEAD blob differs from reviewed candidate")
        if tuple(f["rc2_merge_parents"]) != (RC2_MERGE_COMMIT, *RC2_MERGE_PARENTS):
            problems.append("RC-2 merge commit parents are not the reviewed main/integration HEAD")
        if f["rc2_merge_tree"] != RC2_MERGED_TREE_BLOB:
            problems.append("RC-2 merged tree differs from the exact original authority")
        if f["rc2_merge_ancestor"] is not True:
            problems.append("RC-2 merged commit is not an ancestor of candidate HEAD")
        return problems
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        return [f"RC-3 successor facts incomplete or malformed: {exc!r}"]


def collect(ref=R5_REVIEWED_HEAD):
    branch = [tuple(line.split("\t", 1)) for line in _git("diff", "--name-status", "--no-renames", RC2_MERGE_COMMIT, ref).splitlines()]
    blob = _git("rev-parse", f"{ref}:{RC3_R5_EXACT_PATH}")
    return {
        "rc3_branch_status": branch,
        "status": branch,
        "rc3_r5_worktree_blob": blob, "rc3_r5_head_blob": blob,
        "rc2_merge_parents": _git("rev-list", "--parents", "-n", "1", RC2_MERGE_COMMIT).split(),
        "rc2_merge_tree": _git("rev-parse", f"{RC2_MERGE_COMMIT}^{{tree}}"),
        "rc2_merge_ancestor": subprocess.run(["git", "merge-base", "--is-ancestor", RC2_MERGE_COMMIT, ref], cwd=ROOT).returncode == 0
        and subprocess.run(["git", "merge-base", "--is-ancestor", ref, "HEAD"], cwd=ROOT).returncode == 0,
    }


@pytest.fixture(scope="module")
def facts():
    return collect()


def test_r5_reviewed_head_matches_the_exact_content_successor(facts):
    assert rc3_r5_successor_violations(facts) == []
    assert facts["rc2_merge_parents"] == [RC2_MERGE_COMMIT, *RC2_MERGE_PARENTS]


@pytest.mark.parametrize("mutation,reason", (
    ({"rc3_r5_worktree_blob": "0" * 40}, "exact reviewed candidate blob"),
    ({"rc3_r5_head_blob": "1" * 40}, "committed HEAD blob differs"),
    ({"rc2_merge_parents": ["0" * 40, *RC2_MERGE_PARENTS]}, "merge commit parents"),
    ({"rc2_merge_tree": "0" * 40}, "merged tree differs"),
    ({"rc2_merge_ancestor": False}, "not an ancestor"),
))
def test_r5_mutated_exact_provenance_rejected(facts, mutation, reason):
    changed = copy.deepcopy(facts)
    changed.update(mutation)
    assert any(reason in p for p in rc3_r5_successor_violations(changed))


def test_r5_actual_byte_mutation_rejected(facts):
    source = subprocess.run(["git", "show", f"{R5_REVIEWED_HEAD}:{RC3_R5_EXACT_PATH}"], cwd=ROOT, capture_output=True, check=True).stdout
    changed = subprocess.run(["git", "hash-object", "--stdin"], input=source + b"x", capture_output=True, cwd=ROOT,
                             check=True).stdout.decode().strip()
    assert changed != RC3_R5_EXACT_BLOB
    mutated = copy.deepcopy(facts)
    mutated["rc3_r5_worktree_blob"] = changed
    assert any("exact reviewed candidate blob" in p for p in rc3_r5_successor_violations(mutated))


@pytest.mark.parametrize("replacement", ([], [("M", RC3_R5_EXACT_PATH)], [("D", RC3_R5_EXACT_PATH)],
                                          [("A", RC3_R5_EXACT_PATH), ("A", RC3_R5_EXACT_PATH)]))
def test_r5_missing_modified_deleted_or_duplicate_status_rejected(facts, replacement):
    mutated = copy.deepcopy(facts)
    mutated["status"] = [item for item in facts["status"] if item[1] != RC3_R5_EXACT_PATH] + replacement
    assert any("requires exactly one A status" in p for p in rc3_r5_successor_violations(mutated))


@pytest.mark.parametrize("extra", (("A", "docs/radar/unreviewed_successor.md"), ("A", "tests/test_unreviewed_successor.py"),
                                    ("M", "app/crypto_terminal/tokenized_read.py"), ("M", "domain/revenue/multistream_runtime.py"),
                                    ("A", "app/crypto_terminal/unreviewed_signal.py")))
def test_r5_only_exact_declared_branch_files_are_permitted(facts, extra):
    changed = copy.deepcopy(facts)
    changed["rc3_branch_status"].append(extra)
    assert any("unexpected or missing branch-owned path" in p for p in rc3_r5_successor_violations(changed))


def test_r5_explicit_support_file_status_mutation_rejected(facts):
    for status, path in RC3_R5_ALLOWED_BRANCH_DELTA:
        changed = copy.deepcopy(facts)
        changed["rc3_branch_status"] = [row for row in facts["rc3_branch_status"] if row[1] != path]
        assert rc3_r5_successor_violations(changed), path
        changed["rc3_branch_status"].append(("M" if status == "A" else "A", path))
        assert rc3_r5_successor_violations(changed), path


def test_r5_malformed_or_missing_facts_never_authorise(facts):
    assert rc3_r5_successor_violations({})
    for key in facts:
        assert rc3_r5_successor_violations({k: v for k, v in facts.items() if k != key}), key


def test_duplicate_status_rows_are_malformed_evidence_in_the_historical_rc2_verifier():
    """Ported from #279: a real name-status diff lists each path once; duplicates are never deduplicated."""
    from tests.test_rc2_integration_manifest import _collect
    f = _collect()
    assert len({p for _, p in f["status"]}) == len(f["status"])
    dup = copy.deepcopy(f)
    dup["status"] = [*f["status"], *f["status"]]
    assert any("duplicate" in p for p in rc2_violations(dup))
