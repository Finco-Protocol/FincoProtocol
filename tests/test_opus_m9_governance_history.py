"""Opus M-9 — authoritative full-history governance acceptance."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tools.governance_history_gate import (
    GovernanceBehindBaseError,
    GovernanceEvidenceError,
    GovernanceProtectedMutationError,
    PullRequestIdentity,
    RUNTIME_RADAR_STREAM,
    load_pr_identity,
    protected_prefixes_for_stream,
    verify_governance,
)

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "tools" / "governance_history_gate.py"
WORKFLOW = ROOT / ".github" / "workflows" / "governance_history.yml"


def _git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


def _init_repo(repo: Path) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "--quiet", "--initial-branch=main")
    _git(repo, "config", "user.name", "Governance Fixture")
    _git(repo, "config", "user.email", "governance-fixture")
    (repo / "baseline.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "base")
    return _git(repo, "rev-parse", "HEAD")


def _commit(repo: Path, relative: str, text: str = "changed\n") -> str:
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", f"change {relative}")
    return _git(repo, "rev-parse", "HEAD")


def _identity(base: str, head: str, ref: str = RUNTIME_RADAR_STREAM) -> PullRequestIdentity:
    return PullRequestIdentity(base_sha=base, head_sha=head, head_ref=ref)


def _event(path: Path, *, base: str, head: str, ref: str = RUNTIME_RADAR_STREAM) -> None:
    path.write_text(
        json.dumps({"pull_request": {"base": {"sha": base}, "head": {"sha": head, "ref": ref}}}),
        encoding="utf-8",
    )


def test_m9_exact_pr_event_base_and_head_are_authoritative(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base = _init_repo(repo)
    head = _commit(repo, "app/radar_rwa/runtime.py")
    event = tmp_path / "event.json"
    _event(event, base=base, head=head)

    identity = load_pr_identity(event)
    assert identity.base_sha == base
    assert identity.head_sha == head
    assert identity.head_ref == RUNTIME_RADAR_STREAM

    result = verify_governance(repo_root=repo, identity=identity)
    assert result.base_sha == base
    assert result.head_sha == head
    assert result.merge_base_sha == base
    assert result.checkout_sha == head


def test_m9_actual_behind_branch_fails(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    common = _init_repo(repo)
    _git(repo, "checkout", "--quiet", "-b", "feature")
    head = _commit(repo, "app/radar_rwa/feature.py")
    _git(repo, "checkout", "--quiet", "main")
    current_base = _commit(repo, "main-only.txt")
    _git(repo, "checkout", "--quiet", "feature")

    with pytest.raises(GovernanceBehindBaseError, match="authoritative pull-request base"):
        verify_governance(repo_root=repo, identity=_identity(current_base, head))
    assert common != current_base


def test_m9_runtime_radar_protected_namespace_mutation_fails(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base = _init_repo(repo)
    head = _commit(repo, "financial_engine/drift.py")

    with pytest.raises(GovernanceProtectedMutationError, match="financial_engine/drift.py"):
        verify_governance(repo_root=repo, identity=_identity(base, head))


def test_m9_freeze_is_stream_specific_not_global(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base = _init_repo(repo)
    head = _commit(repo, "financial_engine/approved_correction.py")
    other_ref = "approved/model-correction-stream"

    assert protected_prefixes_for_stream(other_ref) == ()
    result = verify_governance(repo_root=repo, identity=_identity(base, head, other_ref))
    assert result.protected_prefixes == ()


def test_m9_missing_ancestry_in_shallow_checkout_fails_closed(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    base = _init_repo(origin)
    _git(origin, "checkout", "--quiet", "-b", "feature")
    head = _commit(origin, "app/radar_rwa/feature.py")

    shallow = tmp_path / "shallow"
    clone = subprocess.run(
        [
            "git", "clone", "--quiet", "--depth", "1", "--branch", "feature",
            f"file://{origin}", str(shallow),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert clone.returncode == 0, clone.stderr
    assert _git(shallow, "rev-parse", "HEAD") == head
    assert _git(shallow, "cat-file", "-e", f"{base}^{{commit}}", check=False) == ""

    with pytest.raises(GovernanceEvidenceError, match="full ancestry is required"):
        verify_governance(repo_root=shallow, identity=_identity(base, head))


def test_m9_synthetic_merge_sha_does_not_replace_event_head(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    base = _init_repo(repo)
    _git(repo, "checkout", "--quiet", "-b", "feature")
    head = _commit(repo, "app/radar_rwa/feature.py")

    _git(repo, "checkout", "--quiet", "main")
    _commit(repo, "main-side.txt")
    _git(repo, "merge", "--quiet", "--no-ff", "feature", "-m", "synthetic merge")
    synthetic = _git(repo, "rev-parse", "HEAD")
    assert synthetic != head
    _git(repo, "checkout", "--quiet", "feature")

    event = tmp_path / "event.json"
    _event(event, base=base, head=head)
    monkeypatch.setenv("GITHUB_SHA", synthetic)
    identity = load_pr_identity(event)
    assert identity.head_sha == head
    assert identity.head_sha != os.environ["GITHUB_SHA"]


def test_m9_cli_and_library_agree_in_full_clone(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base = _init_repo(repo)
    head = _commit(repo, "app/radar_rwa/feature.py")
    event = tmp_path / "event.json"
    _event(event, base=base, head=head)

    library = verify_governance(repo_root=repo, identity=load_pr_identity(event))
    cli = subprocess.run(
        [sys.executable, str(GATE), "--event-path", str(event), "--repo-root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert cli.returncode == 0, cli.stderr
    assert f"GOVERNANCE_PR_BASE_SHA={library.base_sha}" in cli.stdout
    assert f"GOVERNANCE_PR_HEAD_SHA={library.head_sha}" in cli.stdout
    assert "GOVERNANCE_HISTORY_EVIDENCE=PASS" in cli.stdout
    assert "GOVERNANCE_REQUIRED_HISTORY_SKIPS=ZERO" in cli.stdout


def test_m9_workflow_uses_full_history_only_for_governance_job() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "fetch-depth: 0" in workflow
    assert "github.event.pull_request.head.sha" in workflow
    assert "github.event.pull_request.base.sha" in workflow
    assert "python tools/governance_history_gate.py" in workflow

    public_safety = (ROOT / ".github/workflows/public_safety_and_smoke.yml").read_text(encoding="utf-8")
    compile_gate = (ROOT / ".github/workflows/pr_compile_and_safety.yml").read_text(encoding="utf-8")
    assert "fetch-depth: 0" not in public_safety
    assert "fetch-depth: 0" not in compile_gate


def test_m9_existing_radar_scope_jobs_already_have_authoritative_history() -> None:
    for name in ("radar_r5_signals_history.yml", "radar_r6_terminal.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "fetch-depth: 0" in text
        assert "github.event.pull_request.base.sha" in text
        assert "github.event.pull_request.head.sha" in text
        assert "tools/radar_ci_scope_gate.py" in text


def test_m9_governance_gate_contains_no_history_skip_path() -> None:
    gate = GATE.read_text(encoding="utf-8")
    assert "pytest." + "skip" not in gate
    assert "importor" + "skip" not in gate
