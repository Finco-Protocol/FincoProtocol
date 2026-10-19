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
    RC-7B release-closed candidate is recognised by the separate post-merge successor (merge ancestry + twelve exact blobs + closed flag)."""
    import rc7b_postmerge_successor as successor
    assert RC7B_PATH not in APPROVED
    assert not governance.released_engine_authority_matches(RC7B_PATH)
    assert not approved_frozen_path(RC7B_PATH)
    assert successor.postmerge_recognized(repo=governance.REPO)
    assert strictly_frozen_changes([RC7B_PATH]) == []
    assert successor.states(repo=governance.REPO)["financial_release"] is False
    assert successor.states(repo=governance.REPO)["quarterly_activation"] is False


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
