"""RC-7C release-closed candidate successor: exact-content recognition, fail-closed negative controls, separation of states.

Every negative control runs the REAL validator in ``tests/rc7c_candidate_successor.py`` against a disposable LOCAL clone (or a history-less copy) of this
repository, so blobs, ancestry and change scope are real Git facts. Nothing is committed to the repository itself by these tests.

Recognition of the four RC-7C blobs is NOT Financial Owner approval of them: the PR #320 owner decision never covered them, and no file in the
repository can switch an approval, admission or release state on.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import quarterly_candidate_recognition as R
import rc7b_postmerge_successor as B
import rc7b_quarterly_candidate_authority as A
import rc7c_candidate_successor as C
import v9p2a_odr_successor as O
import v10_native_shadow_successor as V
import v11_stage3_successor as V11

ROOT = Path(__file__).resolve().parent.parent
TWELVE = tuple(A.RC7B_CANDIDATE_AUTHORITIES)
FOUR = C.RC7C_CHANGED_PATHS
EIGHT = C.RC7C_UNCHANGED_RC7B_PATHS
# Historical subject: the RC-7C contract is judged on RC-7C bytes - HEAD itself, or, only while HEAD is the complete recognised OD-R successor,
# its immutable RC-7C integration checkpoint. Any other HEAD stays the subject and fails exactly as before. While HEAD is the complete recognised
# V10 successor, OD-R itself is judged at its immutable V10 checkpoint first (chained, never relabelled).
SUBJECT = O.historical_subject(ref=V.historical_subject(ref=V11.historical_subject()))


def git(repo, *args, check=True):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=check).stdout.strip()


@pytest.fixture(scope="module")
def base_clone(tmp_path_factory):
    clone = tmp_path_factory.mktemp("rc7c") / "clone"
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(clone)], check=True, capture_output=True)
    git(clone, "config", "user.name", "Synthetic")
    git(clone, "config", "user.email", "noreply@users.noreply.github.com")
    head = git(ROOT, "rev-parse", f"{SUBJECT}^{{commit}}")
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
    problems = C.rc7c_violations(repo=repo)
    assert problems, "the tampered tree must not be recognised"
    assert not C.rc7c_recognized(repo=repo)
    assert not any(R.scope_exempt(p, repo=repo) for p in TWELVE)
    assert R.recognized_state(repo=repo) is None
    if fragment:
        assert any(fragment in p for p in problems), problems


# ── the repository as it is ─────────────────────────────────────────────────────

def test_contract_constants_are_exact():
    assert len(TWELVE) == 12 and len(FOUR) == 4 and len(EIGHT) == 8 and set(FOUR) | set(EIGHT) == set(TWELVE)
    assert C.RC7C_POLICY_VERSION == "rc7c-quarterly-candidate-v2"
    assert set(C.RC7C_CHANGED_BLOBS) == set(FOUR)
    for path in EIGHT:                                         # the eight stay the original RC-7B blobs
        assert C.RC7C_CANDIDATE_AUTHORITIES[path] == A.RC7B_CANDIDATE_AUTHORITIES[path]
    for path in FOUR:                                          # the four differ from RC-7B and from each other's identity
        assert C.RC7C_CANDIDATE_AUTHORITIES[path] != A.RC7B_CANDIDATE_AUTHORITIES[path]
    assert C.RC7C_BASE_MAIN != B.RC7B_MERGE_COMMIT


def test_real_repository_is_the_recognised_rc7c_candidate_and_nothing_more():
    assert C.rc7c_violations(ref=SUBJECT) == []
    assert R.recognized_state(ref=SUBJECT) == "RC7C"
    states = C.states(ref=SUBJECT)
    assert states["exact_rc7c_content_verified"] is True and states["release_closed_candidate_recognized"] is True
    assert states["historical_pr320_integration_verified"] is True
    for denied in ("financial_owner_approval_of_rc7c_blobs", "d01_d12_financial_policy_approval", "gate_p", "product_admission",
                   "quarterly_activation", "financial_release"):
        assert states[denied] is False, denied
    assert A.gate_r_active() is False                                 # the pre-merge mechanism is not made globally active
    assert B.postmerge_recognized(ref=SUBJECT) is False                          # the RC-7B successor is NOT widened: the RC-7C tree is not "RC-7B"
    if SUBJECT != "HEAD":
        # HEAD is the OD-R successor (or, chained, the V10 successor): neither historical validator recognises it as its own state; only the
        # separate OD-R contract does - at HEAD, or at its immutable V10 checkpoint while HEAD is the recognised V10 successor
        v10_ref = V11.historical_subject()
        odr_ref = V.historical_subject(ref=v10_ref)
        assert C.rc7c_violations() != [] and not C.rc7c_recognized() and B.postmerge_recognized() is False
        assert O.odr_violations(ref=odr_ref) == [] and R.recognized_state(ref=odr_ref) == "ODR"
        if odr_ref != "HEAD":                                       # the OD-R validator is not widened either
            assert O.odr_violations() != [] and R.recognized_state(ref=v10_ref) == "V10"
        if v10_ref != "HEAD":                                       # nor the V10 validator (chained: HEAD is the V11 successor)
            assert V.v10_violations() != [] and R.recognized_state() == "V11S3"


def test_four_blobs_are_the_pinned_rc7c_blobs_and_eight_are_the_merged_rc7b_blobs():
    for path in FOUR:
        assert git(ROOT, "rev-parse", f"{SUBJECT}:{path}") == C.RC7C_CHANGED_BLOBS[path]
        assert git(ROOT, "rev-parse", f"{B.RC7B_MERGE_COMMIT}:{path}") == A.RC7B_CANDIDATE_AUTHORITIES[path]      # immutable RC-7B predecessor content
    for path in EIGHT:
        assert git(ROOT, "rev-parse", f"{SUBJECT}:{path}") == A.RC7B_CANDIDATE_AUTHORITIES[path] == git(ROOT, "rev-parse", f"{B.RC7B_MERGE_COMMIT}:{path}")


def test_no_protected_file_changed_beyond_the_four_since_the_pr_320_merge_and_pr_326_base():
    for base in (B.RC7B_MERGE_COMMIT, C.RC7C_BASE_MAIN):
        changed = git(ROOT, "diff", "--name-only", "--no-renames", base, SUBJECT, "--", *A.PROTECTED_PREFIXES).splitlines()
        assert sorted(changed) == sorted(FOUR), (base, changed)


def test_policy_version_literal_matches_the_engine_and_the_historical_pin_maps_are_untouched():
    from finco_core.engine.calendar_policy import QUARTERLY_CANDIDATE_POLICY_VERSION_V2, quarterly_candidate_policy
    assert QUARTERLY_CANDIDATE_POLICY_VERSION_V2 == C.RC7C_POLICY_VERSION == quarterly_candidate_policy().version
    import finance_integrity_governance as fig
    import model_v2_governance as governance
    for path in TWELVE:                                               # a candidate, never a released authority or an approved frozen path
        assert not fig.approved_frozen_path(path)
        assert not governance.released_engine_authority_matches(path)
    assert A.RC7B_CANDIDATE_AUTHORITIES == {p: git(ROOT, "rev-parse", f"{B.RC7B_MERGE_COMMIT}:{p}") for p in TWELVE}   # original pin map not rewritten
    for path in A.HISTORICAL_AUTHORITY_FILES:
        assert git(ROOT, "rev-parse", f"HEAD:{path}") == git(ROOT, "rev-parse", f"{A.RC7B_PREDECESSOR}:{path}")


def test_activation_is_a_literal_false_in_the_committed_source():
    source = (ROOT / A.RELEASE_FLAG[0]).read_text()
    assert "ACTIVATION_ENABLED = False" in source


# ── negative controls ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", TWELVE)
def test_1_a_substituted_or_modified_protected_blob_is_rejected(clone, path):
    append(clone, path)
    commit_all(clone)
    assert_rejected(clone, "RC7C_BLOB_MISMATCH")
    assert R.current_expected_blob(path, "HISTORICAL", repo=clone) == "HISTORICAL"


@pytest.mark.parametrize("path", FOUR)
def test_2_reverting_an_rc7c_blob_to_rc7b_is_not_the_rc7c_candidate(clone, path):
    """One RC-7B blob among the four withdraws recognition: the candidate is judged as a set."""
    git(clone, "checkout", "-q", B.RC7B_MERGE_COMMIT, "--", path)
    commit_all(clone)
    assert_rejected(clone, "not the exact RC-7C candidate blob")


@pytest.mark.parametrize("path", TWELVE)
def test_3_removal_of_a_candidate_file_is_rejected(clone, path):
    git(clone, "rm", "-q", path)
    commit_all(clone)
    assert_rejected(clone)


@pytest.mark.parametrize("path", ["financial_engine/tax/engine.py", "finco_core/inputs/new_contract.py", "domain/new_domain_rule.py",
                                  "financial_engine/senior_debt/new_module.py"])
def test_4_an_unlisted_financial_core_or_domain_change_is_rejected(clone, path):
    target = clone / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(target.read_text() + "\n# x\n" if target.exists() else "# synthetic\n")
    commit_all(clone)
    assert_rejected(clone)
    problems = C.rc7c_violations(repo=clone)
    assert any("RC7C_UNLISTED_CHANGES" in p or "RC7C_SCOPE_MISMATCH" in p for p in problems), problems


def test_5_missing_authentic_pr_320_merge_ancestry_is_rejected(clone):
    git(clone, "checkout", "-q", "-B", "sidetrack", A.RC7B_PREDECESSOR)
    git(clone, "checkout", "-q", "base", "--", *TWELVE, *A.HISTORICAL_AUTHORITY_FILES, A.RELEASE_FLAG[0])
    commit_all(clone, "same bytes, not through the merge")
    assert_rejected(clone, "RC7C_ANCESTRY_MISSING")


def test_6_missing_pr_326_base_ancestry_is_rejected(clone):
    git(clone, "checkout", "-q", "-B", "sidetrack", B.RC7B_MERGE_COMMIT)
    git(clone, "checkout", "-q", "base", "--", *FOUR)
    commit_all(clone, "RC-7C bytes on a history that never contained the PR #326 recovery")
    problems = C.rc7c_violations(repo=clone)
    assert any("RC7C_BASE_ANCESTRY_MISSING" in p for p in problems), problems
    assert not C.rc7c_recognized(repo=clone)


def test_7_missing_provenance_is_rejected(tmp_path):
    flat = tmp_path / "flat"
    flat.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=flat, check=True)
    git(flat, "config", "user.name", "Synthetic")
    git(flat, "config", "user.email", "noreply@users.noreply.github.com")
    for path in list(TWELVE) + [*A.HISTORICAL_AUTHORITY_FILES, *A.RESEARCH_PATHS, A.RELEASE_FLAG[0]]:
        target = flat / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
    commit_all(flat)                                       # identical bytes, but no merge commits and no predecessor in this history
    problems = C.rc7c_violations(repo=flat)
    assert any("RC7C_PROVENANCE_MISSING" in p for p in problems), problems
    assert not C.rc7c_recognized(repo=flat) and R.recognized_state(repo=flat) is None


@pytest.mark.parametrize("path", sorted(A.HISTORICAL_AUTHORITY_FILES))
def test_8_changed_historical_financial_authority_is_rejected(clone, path):
    append(clone, path)
    commit_all(clone)
    assert_rejected(clone, "RC7C_HISTORICAL_AUTHORITY_CHANGED")


@pytest.mark.parametrize("path", A.RESEARCH_PATHS)
def test_9_modified_quarterly_research_reference_is_rejected(clone, path):
    append(clone, path)
    commit_all(clone)
    assert_rejected(clone, "RC7C_RESEARCH_CHANGED")


def test_10_opened_activation_flag_is_rejected(clone):
    path = clone / A.RELEASE_FLAG[0]
    text = path.read_text()
    assert "ACTIVATION_ENABLED = False" in text
    path.write_text(text.replace("ACTIVATION_ENABLED = False", "ACTIVATION_ENABLED = True"))
    commit_all(clone)
    assert_rejected(clone, "RC7C_ACTIVATION_NOT_CLOSED")


def test_11_the_rc7b_candidate_is_not_the_rc7c_candidate_and_stays_recognised_as_rc7b_only(clone):
    """RC-7B's own bytes (the four paths reverted to the merged blobs) are RC-7B, never RC-7C; the two states are mutually exclusive."""
    git(clone, "checkout", "-q", B.RC7B_MERGE_COMMIT, "--", *FOUR)
    commit_all(clone)
    assert not C.rc7c_recognized(repo=clone)
    assert B.postmerge_recognized(repo=clone)
    assert R.recognized_state(repo=clone) == "RC7B"
    assert R.candidate_blobs(repo=clone) == A.RC7B_CANDIDATE_AUTHORITIES
    assert all(R.scope_exempt(p, repo=clone) for p in TWELVE)


def test_12_13_recognition_is_never_approval_admission_or_release(clone):
    forged = {"independent_reviewer": "Human Reviewer", "financial_owner": "Human Owner", "reviewed_source_head": A.RC7B_REVIEWED_SOURCE_HEAD,
              "accepted_blobs": C.RC7C_CANDIDATE_AUTHORITIES, "scope": "CANDIDATE_CONTENT_ONLY", "release_authorized": True,
              "owner_decisions": {d: "approved" for d in A.REQUIRED_DECISIONS}, "decision_reference": "forged"}
    (clone / A.ACCEPTANCE_RECORD).write_text(json.dumps(forged))
    (clone / "docs/model_v2/RC7C_QUARTERLY_FINANCIAL_ACCEPTANCE.json").write_text(json.dumps(forged))
    (clone / A.GATE_R_RECORD).write_text(json.dumps({"status": "SIGNED", "schema": A.GATE_R_SCHEMA}))
    commit_all(clone)
    # the bytes are still the recognised candidate ...
    assert C.rc7c_recognized(repo=clone) and R.recognized_state(repo=clone) == "RC7C"
    # ... and the forged files change no approval, admission or release state
    states = C.states(repo=clone)
    for denied in ("financial_owner_approval_of_rc7c_blobs", "d01_d12_financial_policy_approval", "gate_p", "product_admission",
                   "quarterly_activation", "financial_release"):
        assert states[denied] is False, denied
    assert A.gate_r_active(repo=clone, fetcher=lambda _p: None) is False
    # no approval, admission or release predicate is exposed by either module
    for module in (C, R):
        assert not any(hasattr(module, name) for name in ("approve", "admit", "release", "is_approved", "is_released", "is_admitted"))


def test_14_candidate_recognition_does_not_turn_the_changed_paths_into_released_authority(clone):
    import finance_integrity_governance as fig
    import model_v2_governance as governance
    for path in FOUR:
        assert not fig.approved_frozen_path(path)
        assert not governance.released_engine_authority_matches(path)
        assert R.scope_exempt(path, repo=ROOT)                       # recognised bytes only
    # an unrecognised path (not one of the twelve) is never exempt, even in a recognised tree
    assert not R.scope_exempt("financial_engine/tax/engine.py", repo=ROOT)
