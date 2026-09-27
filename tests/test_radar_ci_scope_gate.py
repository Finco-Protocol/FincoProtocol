"""End-to-end fixtures for PR-base Radar milestone scope governance."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "tools" / "radar_ci_scope_gate.py"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _pr_commits(repo: Path, changed: tuple[str, ...]) -> tuple[str, str]:
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.name", "Radar CI Fixture")
    _git(repo, "config", "user.email", "radar-ci-fixture")
    (repo / "baseline.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    for relative in changed:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("changed\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "pr head")
    return base, _git(repo, "rev-parse", "HEAD")


@pytest.mark.parametrize(
    ("case", "milestone", "changed", "expected_code"),
    [
        ("A", "r5", ("finco_radar/signals/engine.py", "finco_radar/liquidity/engine.py"), 1),
        ("B", "r5", ("finco_radar/signals/engine.py",), 0),
        ("C", "r5", ("finco_radar/liquidity/engine.py",), 0),
        ("D", "r6", ("finco_radar/terminal/web.py", "finco_radar/signals/engine.py",
                      "finco_radar/liquidity/engine.py"), 1),
        ("E", "r6", ("finco_radar/terminal/web.py",), 0),
    ],
)
def test_pr_base_to_head_scope_cases(
    tmp_path: Path, case: str, milestone: str,
    changed: tuple[str, ...], expected_code: int,
) -> None:
    base, head = _pr_commits(tmp_path, changed)
    result = subprocess.run(
        [sys.executable, str(GATE), milestone, "--base", base, "--head", head],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == expected_code, f"Case {case}: {result.stdout} {result.stderr}"
    if expected_code:
        assert "unrelated upstream production paths" in result.stderr
    else:
        assert "scope isolation: PASS" in result.stdout


def test_r3_only_pr_still_triggers_both_regression_workflows() -> None:
    for name in ("radar_r5_signals_history.yml", "radar_r6_terminal.yml"):
        workflow = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert '      - "finco_radar/**"' in workflow
        assert "- name: Focused" in workflow


def test_invalid_commit_identity_fails_closed(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(GATE), "r5", "--base", "not-a-sha", "--head", "not-a-sha"],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2
