"""An exact revenue authority blob is not a namespace or future-edit exemption."""
import subprocess

import pytest
import model_v2_governance as governance
from finance_integrity_governance import unapproved_engine_changes, strictly_frozen_changes, approved_frozen_path
from tests.test_financing_f3_governance import git

PATHS = {
    "financial_engine/adapters/project_inputs.py", "financial_engine/orchestrator.py",
    "financial_engine/revenue_multistream.py", "finco_core/inputs/revenue_multistream.py",
    "finco_core/inputs/serialization.py", "finco_core/revenue/generation.py",
    "domain/revenue/multistream_runtime.py",
}


def test_exact_seven_content_pins_only():
    assert set(governance.WF07_REVENUE_AUTHORITIES) == PATHS
    for path, blob in governance.WF07_REVENUE_AUTHORITIES.items():
        assert "*" not in path
        assert git(governance.REPO, "rev-parse", "HEAD:" + path) == blob
        assert governance.released_engine_authority_matches(path)
        assert approved_frozen_path(path)
    assert unapproved_engine_changes(list(PATHS)) == []
    assert strictly_frozen_changes(list(PATHS)) == []


@pytest.mark.parametrize("path", sorted(PATHS))
def test_every_further_edit_invalidates_authorization(path, tmp_path, monkeypatch):
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
    git(repo, "commit", "-m", "Exact reviewed content")
    assert governance.released_engine_authority_matches(path, repo=repo)
    target.write_bytes(original + b"\n# Unapproved change\n")
    git(repo, "add", path)
    git(repo, "commit", "-m", "Unapproved change")
    assert not governance.released_engine_authority_matches(path, repo=repo)
    monkeypatch.setattr(governance, "REPO", repo)
    assert not approved_frozen_path(path)
    if path.startswith("financial_engine/"):
        assert unapproved_engine_changes([path]) == [path]
    if path.startswith("finco_core/"):
        assert strictly_frozen_changes([path]) == [path]


@pytest.mark.parametrize("path", ["financial_engine/revenue_multistream.py.bak", "finco_core/revenue/other.py",
    "finco_core/inputs/_models.py/unapproved", "financial_engine/senior_debt/new.py", "finco_radar/other.py"])
def test_unrelated_files_remain_blocked(path):
    assert not governance.approved_by_active_model_v2_scope(path)
