"""WF-04 approves two exact blobs, never an engine/core namespace exemption."""
from pathlib import Path
import subprocess

import pytest
import model_v2_governance as governance
from finance_integrity_governance import unapproved_engine_changes, strictly_frozen_changes
from tests.test_financing_f3_governance import git


APPROVED = {
    "financial_engine/financing/project.py": "4349b4bc396cba446a0b1c473f1a466eafb12bb5",
    "financial_engine/financial_statements/assembly.py": "7b8607c719ef1d780490dfbee8107ce290508bff",
}


def test_exact_wf04_paths_and_content_only():
    assert governance.WF04_NUMERIC_PRECISION_AUTHORITIES == APPROVED
    for path, blob in APPROVED.items():
        assert git(governance.REPO, "rev-parse", "HEAD:" + path) == blob
        assert governance.released_engine_authority_matches(path)
    assert unapproved_engine_changes(list(APPROVED)) == []


@pytest.mark.parametrize("path", sorted(APPROVED))
def test_any_further_edit_loses_authorization(path, tmp_path, monkeypatch):
    repo = tmp_path / "synthetic"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "config", "user.name", "Synthetic Reviewer")
    git(repo, "config", "user.email", "noreply@users.noreply.github.com")
    original = subprocess.run(["git", "-C", str(governance.REPO), "show", "HEAD:" + path],
        check=True, capture_output=True).stdout
    target = repo / path
    target.parent.mkdir(parents=True)
    target.write_bytes(original)
    git(repo, "add", path)
    git(repo, "commit", "-m", "Synthetic exact content")
    assert governance.released_engine_authority_matches(path, repo=repo)
    target.write_bytes(original + b"\n# Unapproved change\n")
    git(repo, "add", path)
    git(repo, "commit", "-m", "Synthetic changed content")
    assert not governance.released_engine_authority_matches(path, repo=repo)
    monkeypatch.setattr(governance, "REPO", Path(repo))
    assert unapproved_engine_changes([path]) == [path]


@pytest.mark.parametrize("path", [
    "financial_engine/financial_statements/other.py", "financial_engine/financing/other.py",
    "financial_engine/financial_statements/assembly.py.bak", "financial_engine/senior_debt/other.py",
    "finco_core/inputs/other.py", "finco_radar/other.py",
])
def test_unrelated_changes_are_still_blocked(path):
    assert not governance.released_engine_authority_matches(path)
    assert not governance.approved_by_active_model_v2_scope(path)
    if path.startswith("financial_engine/"):
        assert unapproved_engine_changes([path]) == [path]
    else:
        assert strictly_frozen_changes([path]) == [path]
