"""Exact-path, exact Git blob authorization; all other core files stay frozen."""
from pathlib import Path
import subprocess

import pytest

import model_v2_governance as governance
from finance_integrity_governance import approved_frozen_path, strictly_frozen_changes


APPROVED = {
    "finco_core/inputs/financing_instruments.py": "e1d06441763d2316af45d14ddab1716abbe4f3ca",
    "finco_core/inputs/financing_instruments_legacy.py": "f963272fb3342976a33483ffea8aaad0a6f81f2b",
}


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def test_authorization_contains_exactly_two_reviewed_paths_and_blobs():
    assert governance.F3_1_CONTRACT_AUTHORITIES == APPROVED
    assert strictly_frozen_changes(list(APPROVED)) == []
    for path, blob in APPROVED.items():
        assert git(governance.REPO, "rev-parse", f"HEAD:{path}") == blob
        assert governance.released_engine_authority_matches(path)
        assert approved_frozen_path(path)


@pytest.mark.parametrize("path", [
    "finco_core/tax/engine.py", "finco_core/inputs/new_contract.py",
    "finco_core/inputs/financing_instruments_extra.py",
    "finco_core/inputs/financing_instruments.py/extra",
    "finco_radar/new_contract.py",
])
def test_unrelated_paths_never_acquire_f3_authorization(path):
    assert not governance.released_engine_authority_matches(path)
    assert not approved_frozen_path(path)
    assert strictly_frozen_changes([path]) == [path]


RC7B_PATH = "finco_core/engine/period_engine.py"      # one of the twelve exact RC-7B candidate blobs (never an F3 path)


def test_rc7b_candidate_path_never_acquires_f3_or_released_authority_but_is_recognised_only_as_the_exact_candidate():
    """period_engine.py is NOT F3-authorised and not an approved frozen path. The global frozen-scope guard may pass it only because the whole exact
    release-closed quarterly candidate (RC-7B as merged, or RC-7C) is recognised by a separate successor (merge ancestry + exact blobs + closed flag)."""
    import quarterly_candidate_recognition as recognition
    import rc7b_postmerge_successor as rc7b_successor
    import rc7c_candidate_successor as rc7c_successor
    assert RC7B_PATH not in APPROVED
    assert not governance.released_engine_authority_matches(RC7B_PATH)
    assert not approved_frozen_path(RC7B_PATH)
    import v9p2a_odr_successor as odr_successor
    state = recognition.recognized_state(repo=governance.REPO)
    assert state in ("RC7B", "RC7C", "ODR", "V10", "V11S3")
    assert strictly_frozen_changes([RC7B_PATH]) == []
    odr_ref = "HEAD"
    v10_ref = "HEAD"
    if state == "V11S3":
        # the V11 successor carries period_engine.py as its unchanged RC-7C blob; V10 stays judged at its immutable V11 checkpoint
        import v11_stage3_successor as v11_successor
        assert recognition.candidate_blobs(repo=governance.REPO)[RC7B_PATH] == rc7c_successor.RC7C_CANDIDATE_AUTHORITIES[RC7B_PATH]
        v11_states = v11_successor.states(repo=governance.REPO)
        for denied in ("financial_release", "stage3_activation", "production_enablement", "v10_reseal", "merge_authorized"):
            assert v11_states[denied] is False, denied
        v10_ref = v11_successor.historical_subject(repo=governance.REPO)
        assert v10_ref != "HEAD" and recognition.recognized_state(repo=governance.REPO, ref=v10_ref) == "V10"
        state = "V10"
    if state == "V10":
        # the V10 successor carries period_engine.py as its unchanged RC-7C blob; OD-R stays judged at its immutable V10 checkpoint
        import v10_native_shadow_successor as v10_successor
        assert recognition.candidate_blobs(repo=governance.REPO, ref=v10_ref)[RC7B_PATH] == \
            rc7c_successor.RC7C_CANDIDATE_AUTHORITIES[RC7B_PATH]
        v10_states = v10_successor.states(repo=governance.REPO, ref=v10_ref)
        for denied in ("financial_release", "native_activation", "native_replace_mode", "merge_authorized"):
            assert v10_states[denied] is False, denied
        odr_ref = v10_successor.historical_subject(repo=governance.REPO, ref=v10_ref)
        assert odr_ref != "HEAD" and recognition.recognized_state(repo=governance.REPO, ref=odr_ref) == "ODR"
        state = "ODR"
    if state == "ODR":
        # the OD-R successor carries period_engine.py as its unchanged RC-7C blob; RC-7C itself stays judged at its immutable checkpoint
        assert recognition.candidate_blobs(repo=governance.REPO, ref=odr_ref)[RC7B_PATH] == rc7c_successor.RC7C_CANDIDATE_AUTHORITIES[RC7B_PATH]
        subject = odr_successor.historical_subject(repo=governance.REPO, ref=odr_ref)
        assert recognition.recognized_state(repo=governance.REPO, ref=subject) == "RC7C"
        odr_states = odr_successor.states(repo=governance.REPO, ref=odr_ref)
        for denied in ("financial_release", "product_activation", "merge_authorized", "od_r_default_policy"):
            assert odr_states[denied] is False, denied
        states = rc7c_successor.states(repo=governance.REPO, ref=subject)
    else:
        states = (rc7b_successor if state == "RC7B" else rc7c_successor).states(repo=governance.REPO)
    assert states["financial_release"] is False
    assert states["quarterly_activation"] is False
    assert states["product_admission"] is False


def _clone(tmp_path):
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(governance.REPO), str(clone)], check=True, capture_output=True)
    git(clone, "config", "user.name", "Synthetic Reviewer")
    git(clone, "config", "user.email", "noreply@users.noreply.github.com")
    return clone


def test_rc7b_candidate_path_is_rejected_again_when_its_blob_is_modified(tmp_path, monkeypatch):
    clone = _clone(tmp_path)
    (clone / RC7B_PATH).write_text((clone / RC7B_PATH).read_text() + "\n# modified\n")
    git(clone, "commit", "-aq", "-m", "modify candidate blob")
    monkeypatch.setattr(governance, "REPO", clone)
    assert not approved_frozen_path(RC7B_PATH)
    assert strictly_frozen_changes([RC7B_PATH]) == [RC7B_PATH]


def test_rc7b_candidate_path_is_rejected_again_without_the_original_merge_provenance(tmp_path, monkeypatch):
    flat = tmp_path / "flat"
    flat.mkdir()
    git(flat, "init")
    git(flat, "config", "user.name", "Synthetic Reviewer")
    git(flat, "config", "user.email", "noreply@users.noreply.github.com")
    target = flat / RC7B_PATH
    target.parent.mkdir(parents=True)
    target.write_bytes((Path(governance.REPO) / RC7B_PATH).read_bytes())    # exact bytes, but no merge commit/ancestry in this history
    git(flat, "add", "-A")
    git(flat, "commit", "-q", "-m", "flat copy")
    monkeypatch.setattr(governance, "REPO", flat)
    assert strictly_frozen_changes([RC7B_PATH]) == [RC7B_PATH]


@pytest.mark.parametrize("path", APPROVED)
def test_modified_approved_blob_invalidates_authorization(path, tmp_path, monkeypatch):
    repo = tmp_path / "repository"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "config", "user.name", "Synthetic Reviewer")
    git(repo, "config", "user.email", "noreply@users.noreply.github.com")
    target = repo / path
    target.parent.mkdir(parents=True)
    original = subprocess.run(["git", "-C", str(governance.REPO), "show", f"HEAD:{path}"],
                              check=True, capture_output=True).stdout
    target.write_bytes(original)
    git(repo, "add", path)
    git(repo, "commit", "-m", "Synthetic approved contract")
    assert governance.released_engine_authority_matches(path, repo=repo)

    target.write_bytes(original + b"\n# Unreviewed contract alteration.\n")
    git(repo, "add", path)
    git(repo, "commit", "-m", "Synthetic unapproved alteration")
    assert git(repo, "rev-parse", f"HEAD:{path}") != APPROVED[path]
    assert not governance.released_engine_authority_matches(path, repo=repo)
    assert governance.released_engine_authority_matches(path, repo=repo, ref="HEAD~1")
    assert not governance.released_engine_authority_matches(path, repo=repo, ref="missing-ref")
    monkeypatch.setattr(governance, "REPO", Path(repo))
    assert strictly_frozen_changes([path]) == [path]
    assert not approved_frozen_path(path)


def test_missing_approved_blob_fails_closed(tmp_path):
    git(tmp_path, "init")
    for path in APPROVED:
        assert not governance.released_engine_authority_matches(path, repo=tmp_path)
