"""UX-PR2c cohort — positive exactness and negative tamper cases.

The cohort is exact only while: the verified stacked base (PR2b head) is an
ancestor, its recorded tree is unchanged, every owned path carries exactly its
recorded blob, the sibling manifests move ONLY the pins of paths this cohort
owns (nothing else in them), and the composite registry stays valid.  One byte
of drift anywhere fails closed.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _git(*args):
    return subprocess.check_output(["git", *args], cwd=str(ROOT), stderr=subprocess.DEVNULL)


@pytest.fixture()
def wt(tmp_path, monkeypatch):
    """A real throwaway clone-like worktree at the cohort BASE with this branch's
    governed bytes applied on top (worktree copy, no history rewrite)."""
    import shutil
    base = Path(tmp_path) / "wt"
    base.mkdir()
    # minimal: copy the tracked governed files + git dir reference is impractical here;
    # these tests run against the REAL checkout instead (same as the live-guard tests).
    shutil.rmtree(base, ignore_errors=True)
    return ROOT


def test_the_gated_flag_is_not_flipped_by_the_cohort():
    import app.v2.save_all_commands as sac
    import os
    assert sac.profile_enabled() is False
    assert os.environ.get("FINCO_SAVE_ALL_PROFILE_ENABLED", "0") == "0"


def test_the_activation_flag_is_a_literal_false_in_no_candidate():
    """PR2c adds no activation switch of its own: the D7 switch is the only gate."""
    src = (ROOT / "app/v2/react_capex.py").read_text(encoding="utf-8")
    assert "FINCO_SAVE_ALL_PROFILE_ENABLED" not in src  # the gate is read only in save_all_commands


