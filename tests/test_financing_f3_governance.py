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
    "finco_core/engine/period_engine.py", "finco_radar/new_contract.py",
])
def test_unrelated_paths_never_acquire_f3_authorization(path):
    assert not governance.released_engine_authority_matches(path)
    assert not approved_frozen_path(path)
    assert strictly_frozen_changes([path]) == [path]


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
