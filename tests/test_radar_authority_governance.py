"""Content-pinned Radar authority governance regressions for PR #237."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from radar_authority_governance import (
    REPO, REVIEWED_RADAR_AUTHORITY_BLOBS, reviewed_radar_authority_matches,
)


def _git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                       text=True, check=True)
    return p.stdout.strip()


@pytest.mark.parametrize("path", sorted(REVIEWED_RADAR_AUTHORITY_BLOBS))
def test_reviewed_exact_git_blobs_match_current_head(path):
    assert reviewed_radar_authority_matches(path)
    assert _git(REPO, "rev-parse", f"HEAD:{path}") == REVIEWED_RADAR_AUTHORITY_BLOBS[path]


@pytest.mark.parametrize("path", (
    "finco_radar/new_module/something.py",
    "finco_radar/venues/relative_value_unreviewed.py",
    "finco_radar/venues/new_sibling.py",
    "app/radar_rwa/new_sibling.py",
    "app/radar_rwa/r_live_service.py/child",
    "finco_radar/venues/intelligence.py.old",
))
def test_no_sibling_directory_or_filename_prefix_grants(path):
    assert not reviewed_radar_authority_matches(path)


def test_missing_ref_or_invalid_repo_fails_closed(tmp_path):
    path = "finco_radar/venues/intelligence.py"
    assert not reviewed_radar_authority_matches(path, ref="missing-ref-no-such-commit")
    assert not reviewed_radar_authority_matches(path, repo=tmp_path)
    assert not reviewed_radar_authority_matches(path, ref="BAD REF")


def test_unreviewed_content_change_revokes_blob_grant(tmp_path):
    repo = tmp_path / "fixture"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "FINCO Governance Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    for path in REVIEWED_RADAR_AUTHORITY_BLOBS:
        dst = repo / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes((REPO / path).read_bytes())
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "reviewed baseline")
    for path in REVIEWED_RADAR_AUTHORITY_BLOBS:
        assert reviewed_radar_authority_matches(path, repo=repo)
    modified = "finco_radar/venues/intelligence.py"
    (repo / modified).write_bytes((repo / modified).read_bytes() + b"\n# unreviewed change\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "unreviewed change")
    assert not reviewed_radar_authority_matches(modified, repo=repo)
    for path in REVIEWED_RADAR_AUTHORITY_BLOBS:
        if path != modified:
            assert reviewed_radar_authority_matches(path, repo=repo)


def test_simulated_unapproved_radar_path_still_frozen():
    from finance_integrity_governance import strictly_frozen_changes, approved_frozen_path
    from model_v2_governance import model_v2_frozen_violations
    bad = "finco_radar/new_module/something.py"
    assert strictly_frozen_changes([bad]) == [bad]
    assert model_v2_frozen_violations([bad]) == [bad]
    assert not approved_frozen_path(bad)
    assert not approved_frozen_path("app/radar_rwa/new_sibling.py")


def test_existing_pr183_relative_value_treatment_remains_intact():
    from finance_integrity_governance import strictly_frozen_changes
    from model_v2_governance import model_v2_frozen_violations
    path = "finco_radar/venues/relative_value.py"
    assert strictly_frozen_changes([path]) == []
    assert model_v2_frozen_violations([path]) == []


@pytest.mark.parametrize("path", sorted(REVIEWED_RADAR_AUTHORITY_BLOBS))
def test_frozen_governance_accepts_only_pinned_content(path):
    from finance_integrity_governance import strictly_frozen_changes, approved_frozen_path
    from model_v2_governance import model_v2_frozen_violations
    assert approved_frozen_path(path)
    assert model_v2_frozen_violations([path]) == []
    if path.startswith("finco_radar/"):
        assert strictly_frozen_changes([path]) == []
