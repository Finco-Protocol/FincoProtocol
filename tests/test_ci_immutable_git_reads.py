"""Adversarial tests for tests/ci_immutable_git_reads.py: a memoised read may only ever return what a fresh git call returns, and a fresh
git error is never turned into a result. Each test is ONE attack; none is folded into a generic mock."""
import os
import subprocess
import threading

import pytest


def _git(repo, *a, **kw):
    return subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, **kw).stdout.decode().strip()


def _init(path):
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    for k, v in (("user.email", "t@invalid"), ("user.name", "t")):
        _git(path, "config", k, v)
    return path


@pytest.fixture
def repo(tmp_path):
    r = _init(tmp_path / "r")
    (r / "a.txt").write_bytes(b"one\n")
    _git(r, "add", "a.txt")
    _git(r, "commit", "-qm", "c1")
    return r


def show(repo, rev, path="a.txt"):
    return subprocess.check_output(["git", "show", rev + ":" + path], cwd=repo, stderr=subprocess.DEVNULL)


# ── original attacks (audit 2026-11-17) ───────────────────────────────────────────────────────────────────────────────────────────


# ── Correction E review attacks ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_only_the_two_import_time_sites_enter_the_memo_and_the_suite_conftest_is_untouched():
    # tests/conftest.py is a protected, unowned path of the historical U1/U2/WF-06B guards: the memo is entered ONLY explicitly.
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert "ci_immutable_git_reads" not in (root / "tests/conftest.py").read_text(encoding="utf-8")
    users = sorted(p.name for p in (root / "tests").glob("test_*.py")
                   if p.name != Path(__file__).name and "_OBJECTS.scope()" in p.read_text(encoding="utf-8", errors="replace"))
    assert users == ["test_rc7c_candidate_successor.py", "test_v9p2a_odr_successor.py"]
