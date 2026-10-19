"""RC-7B post-merge release-closed successor: fail-closed negative controls and the separation of states.

Every negative control runs the REAL validator in ``tests/rc7b_postmerge_successor.py`` against a disposable LOCAL clone (or a history-less copy)
of this repository, so blobs, ancestry and change scope are real Git facts. Nothing is ever committed to the repository itself by these tests.

The successor recognises ONE thing: the tree is exactly the release-closed RC-7B candidate that PR #320 integrated. It never grants Financial
Owner approval, D-01..D-12 approval, Gate P, product admission, activation or a release, and it leaves the pre-merge Gate R machinery untouched
(Gate R is still not active here).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import rc7b_postmerge_successor as S
import rc7b_quarterly_candidate_authority as A

ROOT = Path(__file__).resolve().parent.parent
TWELVE = tuple(A.RC7B_CANDIDATE_AUTHORITIES)
RC7C_PATHS = ("finco_core/engine/calendar_policy.py", "finco_core/engine/period_engine.py",
              "financial_engine/orchestrator.py", "financial_engine/senior_debt/project_adapter.py")


def git(repo, *args, check=True):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=check).stdout.strip()


@pytest.fixture(scope="module")
def base_clone(tmp_path_factory):
    clone = tmp_path_factory.mktemp("postmerge") / "clone"
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(clone)], check=True, capture_output=True)
    git(clone, "config", "user.name", "Synthetic")
    git(clone, "config", "user.email", "noreply@users.noreply.github.com")
    head = git(ROOT, "rev-parse", "HEAD")
    git(clone, "checkout", "-q", "-B", "base", head)
    return clone, head


@pytest.fixture()
def clone(base_clone):
    repo, head = base_clone
    git(repo, "checkout", "-q", "-B", "work", head)
    git(repo, "reset", "-q", "--hard", head)
    git(repo, "clean", "-q", "-fd")
    return repo


def commit_all(repo, message="synthetic change"):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def append(repo, path, text="\n# synthetic edit\n"):
    target = repo / path
    target.write_text(target.read_text() + text)


def assert_rejected(repo, fragment=None):
    problems = S.postmerge_violations(repo=repo)
    assert problems, "the successor must reject this tree"
    assert not S.postmerge_recognized(repo=repo)
    assert not any(S.scope_exempt(p, repo=repo) for p in TWELVE)
    if fragment:
        assert any(fragment in p for p in problems), problems


# ── the repository as it is ─────────────────────────────────────────────────────

def test_real_repository_is_the_recognised_release_closed_candidate_and_nothing_more():
    assert S.postmerge_violations() == []
    states = S.states()
    assert states["historical_pr320_integration_verified"] is True
    assert states["exact_rc7b_content_verified"] is True
    assert states["release_closed_candidate_recognized"] is True
    for denied in ("financial_owner_approval", "gate_r_active", "d01_d12_financial_policy_approval", "gate_p", "product_admission",
                   "quarterly_activation", "financial_release"):
        assert states[denied] is False, denied
    assert A.gate_r_active() is False                                # the pre-merge mechanism is NOT made globally active
    assert A.gate_r_violations(fetcher=lambda _p: None) != []          # no signed Financial Owner record / authentic review exists


def test_the_twelve_blobs_equal_the_merged_pr_320_blobs_and_are_never_released_authority():
    assert len(TWELVE) == 12
    for path, pin in A.RC7B_CANDIDATE_AUTHORITIES.items():
        assert git(ROOT, "rev-parse", f"HEAD:{path}") == pin
        assert git(ROOT, "rev-parse", f"{S.RC7B_MERGE_COMMIT}:{path}") == pin
        assert git(ROOT, "rev-parse", f"{S.RC7B_MERGED_PR_HEAD}:{path}") == pin
        assert S.scope_exempt(path)
    import finance_integrity_governance as fig
    import model_v2_governance as governance
    for path in TWELVE:
        assert not fig.approved_frozen_path(path)
        assert not governance.released_engine_authority_matches(path)


def test_historical_merge_facts_are_pinned():
    assert git(ROOT, "show", "-s", "--format=%P", S.RC7B_MERGE_COMMIT).split() == [A.RC7B_PREDECESSOR, S.RC7B_MERGED_PR_HEAD]
    assert S.RC7B_POSTMERGE_RELEASE_CLOSED_SUCCESSOR == "RC7B_POSTMERGE_RELEASE_CLOSED_SUCCESSOR"


# ── negative controls ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", TWELVE)
def test_1_modification_of_any_protected_blob_is_rejected(clone, path):
    append(clone, path)
    commit_all(clone)
    assert_rejected(clone, "not the exact reviewed candidate blob")
    assert not S.scope_exempt(path, repo=clone)
    assert S.current_expected_blob(path, "HISTORICAL", repo=clone) == "HISTORICAL"


@pytest.mark.parametrize("path", TWELVE)
def test_2_removal_of_a_candidate_file_is_rejected(clone, path):
    git(clone, "rm", "-q", path)
    commit_all(clone)
    assert_rejected(clone)


def test_3_an_unexpected_protected_file_is_rejected(clone):
    for extra in ("financial_engine/extra_unreviewed.py", "finco_core/extra_unreviewed.py", "domain/extra_unreviewed.py"):
        (clone / extra).write_text("VALUE = 1\n")
        commit_all(clone)
        assert_rejected(clone, "unlisted financial/core/domain changes")
        git(clone, "reset", "-q", "--hard", "HEAD~1")


def test_4_missing_candidate_provenance_is_rejected(tmp_path):
    bare = tmp_path / "flat"
    bare.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=bare, check=True)
    git(bare, "config", "user.name", "Synthetic")
    git(bare, "config", "user.email", "noreply@users.noreply.github.com")
    for path in list(TWELVE) + [*A.HISTORICAL_AUTHORITY_FILES, *A.RESEARCH_PATHS, A.RELEASE_FLAG[0]]:
        target = bare / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
    commit_all(bare)                                   # identical bytes, but no merge commit and no predecessor in this history
    problems = S.postmerge_violations(repo=bare)
    assert any("POSTMERGE_PROVENANCE_MISSING" in p for p in problems), problems
    assert not S.postmerge_recognized(repo=bare)


def test_5_missing_authentic_pr_320_merge_ancestry_is_rejected(clone):
    git(clone, "checkout", "-q", "-B", "sidetrack", A.RC7B_PREDECESSOR)
    git(clone, "checkout", "-q", "base", "--", *TWELVE, *A.HISTORICAL_AUTHORITY_FILES, A.RELEASE_FLAG[0], "tests/rc7b_postmerge_successor.py")
    commit_all(clone, "same bytes, not through the merge")
    problems = S.postmerge_violations(repo=clone)
    assert any("POSTMERGE_ANCESTRY_MISSING" in p for p in problems), problems
    assert not S.postmerge_recognized(repo=clone)


@pytest.mark.parametrize("path", sorted(A.HISTORICAL_AUTHORITY_FILES))
def test_6_7_modified_historical_authority_maps_and_m7_evidence_are_rejected(clone, path):
    append(clone, path)
    commit_all(clone)
    assert_rejected(clone, "historical financial authority maps changed")


@pytest.mark.parametrize("path", A.RESEARCH_PATHS)
def test_8_modified_quarterly_research_reference_is_rejected(clone, path):
    append(clone, path)
    commit_all(clone)
    assert_rejected(clone, "isolated research reference")


def test_9_opened_activation_flag_is_rejected(clone):
    flag = clone / A.RELEASE_FLAG[0]
    text = flag.read_text()
    assert "ACTIVATION_ENABLED = False" in text
    flag.write_text(text.replace("ACTIVATION_ENABLED = False", "ACTIVATION_ENABLED = True", 1))
    commit_all(clone)
    assert_rejected(clone, "activation is not a literal release-closed False")
    assert S.states(repo=clone)["quarterly_activation"] is True


@pytest.mark.parametrize("path", ["financial_engine/tax/engine.py", "finco_core/tax/engine.py", "financial_engine/senior_debt/solver.py"])
def test_10_unrelated_financial_engine_or_core_changes_are_rejected(clone, path):
    append(clone, path)
    commit_all(clone)
    assert_rejected(clone, "unlisted financial/core/domain changes")


def test_11_12_recognition_is_never_approval_admission_or_release(clone):
    forged = {"independent_reviewer": "Human Reviewer", "financial_owner": "Human Owner", "reviewed_source_head": A.RC7B_REVIEWED_SOURCE_HEAD,
              "accepted_blobs": A.RC7B_CANDIDATE_AUTHORITIES, "scope": "CANDIDATE_CONTENT_ONLY", "release_authorized": True,
              "owner_decisions": {d: "approved" for d in A.REQUIRED_DECISIONS}, "decision_reference": "forged"}
    (clone / A.ACCEPTANCE_RECORD).write_text(json.dumps(forged))
    (clone / A.GATE_R_RECORD).write_text(json.dumps({"status": "SIGNED", "schema": A.GATE_R_SCHEMA}))
    commit_all(clone)
    # the bytes are still the recognised candidate ...
    assert S.postmerge_recognized(repo=clone)
    # ... and the forged files neither activate Gate R nor change what recognition means; the real states stay in the denied column
    assert A.gate_r_active(repo=clone, fetcher=lambda _p: None) is False
    states = S.states(repo=clone)
    assert states["gate_r_active"] is False
    assert states["d01_d12_financial_policy_approval"] is False and states["gate_p"] is False
    assert states["quarterly_activation"] is False
    # the successor exposes no approval, admission or release predicate at all
    assert not any(hasattr(S, name) for name in ("approve", "admit", "release", "is_approved", "is_released"))


@pytest.mark.parametrize("path", RC7C_PATHS)
def test_13_a_later_rc7c_blob_substituted_for_an_rc7b_blob_is_rejected(clone, path):
    """A newer quarterly blob for one of the four paths RC-7C touches is a different candidate and needs its own reviewed successor."""
    append(clone, path, "\n# RC-7C style horizon change\n")
    commit_all(clone)
    assert_rejected(clone, "not the exact reviewed candidate blob")
    assert not S.scope_exempt(path, repo=clone)
    assert S.current_expected_blob(path, "HISTORICAL", repo=clone) == "HISTORICAL"
    # the other eleven stay judged as a set: one substituted blob withdraws recognition from all twelve
    assert not any(S.scope_exempt(other, repo=clone) for other in TWELVE)
