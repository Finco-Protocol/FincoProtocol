"""CI parallel-stream frozen-diff governance regressions.

Proves the merge-base-based frozen-path boundary semantics of
``parallel_stream_frozen_changes`` against a real temporary git repository:

  A. a frozen-path file introduced ONLY on main after divergence does NOT
     fail the branch-side check;
  B. a frozen-path file actually changed by the branch DOES fail;
  C. explicit allowed-path rules still pass;
  D. ACTIVE Model V2 scope exemptions still pass;
  E. no frozen production namespace is modified by this fix.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from model_v2_governance import (
    model_v2_frozen_violations,
    parallel_stream_frozen_changes,
)

REPO = Path(__file__).resolve().parents[1]
FROZEN_DIR = "finco_radar/venues"
ALLOWED_FILE = "finco_radar/venues/registry.py"
SCOPE_EXEMPT_DIR = "financial_engine/financial_statements"
SCOPE_EXEMPT_FILE = f"{SCOPE_EXEMPT_DIR}/assembly.py"
MAIN_ONLY_FILE = f"{FROZEN_DIR}/deepstate_live.py"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


@pytest.fixture()
def diverged_repo(tmp_path: Path) -> Path:
    """A real temp git repository shaped like the parallel-stream problem:
    base commit with frozen/allowed/scope-exempt files; a feature branch
    from base; and a MAIN-side commit (after divergence) introducing a new
    frozen-path file. HEAD is left on the feature branch."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "finco-test")
    _git(repo, "config", "user.name", "Finco Test")
    (repo / FROZEN_DIR).mkdir(parents=True)
    (repo / SCOPE_EXEMPT_DIR).mkdir(parents=True)
    (repo / FROZEN_DIR / "existing.py").write_text("# frozen base\n")
    (repo / ALLOWED_FILE).write_text("# allowed registry\n")
    (repo / SCOPE_EXEMPT_FILE).write_text("# scope-exempt model file\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    _git(repo, "branch", "feature")
    _git(repo, "checkout", "feature")
    # MAIN-side commit AFTER divergence (on the main branch): introduce the
    # deepstate-style frozen-path file.
    _git(repo, "checkout", "main")
    (repo / MAIN_ONLY_FILE).write_text("# main-only radar module\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "main-only frozen-path introduction")
    _git(repo, "checkout", "feature")
    return repo


def _feature_commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


def test_a_main_only_frozen_introduction_does_not_fail_branch_check(
    diverged_repo: Path,
):
    """A: deepstate-style file introduced only on main after divergence is
    invisible to the branch-side check."""
    changed = parallel_stream_frozen_changes(
        FROZEN_DIR, main_ref="main", head_ref="feature", repo=diverged_repo)
    assert changed == []


def test_b_branch_side_frozen_change_still_fails(diverged_repo: Path):
    """B: a frozen-path file ACTUALLY changed by the feature branch is
    detected (protection not weakened)."""
    (diverged_repo / FROZEN_DIR / "existing.py").write_text("# branch edit\n")
    _feature_commit(diverged_repo, "branch-side frozen edit")
    changed = parallel_stream_frozen_changes(
        FROZEN_DIR, main_ref="main", head_ref="feature", repo=diverged_repo)
    assert changed == [f"{FROZEN_DIR}/existing.py"]


def test_cb_allowed_files_still_pass(diverged_repo: Path):
    """C: explicit allowed-path rules still pass on branch-side changes."""
    (diverged_repo / ALLOWED_FILE).write_text("# branch registry edit\n")
    _feature_commit(diverged_repo, "branch-side allowed edit")
    changed = parallel_stream_frozen_changes(
        FROZEN_DIR, main_ref="main", head_ref="feature",
        allowed={"finco_radar/venues/registry.py"}, repo=diverged_repo)
    assert changed == []


def test_cd_scope_exempt_files_still_pass(diverged_repo: Path):
    """D: ACTIVE Model V2 scope exemptions still pass (the scope authority
    is read from the real repository, independent of the temp cwd)."""
    (diverged_repo / SCOPE_EXEMPT_FILE).write_text("# branch model edit\n")
    _feature_commit(diverged_repo, "branch-side scope-exempt edit")
    changed = parallel_stream_frozen_changes(
        SCOPE_EXEMPT_DIR, main_ref="main", head_ref="feature",
        repo=diverged_repo)
    assert changed == []


def test_ce_merge_base_unresolvable_fails_closed(diverged_repo: Path):
    """Fail closed: an unresolvable merge-base raises instead of silently
    evaluating against a wrong boundary."""
    with pytest.raises(RuntimeError, match="PARALLEL_STREAM_MERGE_BASE_UNRESOLVABLE"):
        parallel_stream_frozen_changes(
            FROZEN_DIR, main_ref="nonexistent-ref-xyz",
            head_ref="feature", repo=diverged_repo)


def test_ce_real_repo_guards_green_against_current_main():
    """Live proof: the real-repo frozen guards pass with the merge-base
    boundary against current main (the original CI failure class)."""
    for frozen_path in (
        "finco_radar", "finco_core", "financial_engine",
        "app/model_validation", "app/verified",
    ):
        changed = parallel_stream_frozen_changes(
            frozen_path, main_ref="origin/main", head_ref="HEAD", repo=str(REPO))
        assert changed == [], (frozen_path, changed)


def test_ce_no_frozen_production_namespace_modified_by_this_fix():
    """E: this governance fix modifies no frozen production namespace."""
    assert model_v2_frozen_violations() == []
