"""Opus M-9 — authoritative full-history governance acceptance."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


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
