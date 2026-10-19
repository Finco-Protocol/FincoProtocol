"""Negative controls for the immutable historical stream-scope proofs (tests/stream_scope_proof.py).

The module must prove a HISTORICAL fact about ONE landed stream and must fail closed on any doubt. It must never turn into an exemption: a
stream that really changed a protected path, a tampered range, a missing commit or a non-ancestor of main all produce a non-empty result.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import stream_scope_proof as S

ROOT = Path(__file__).resolve().parent.parent
NAMESPACES = ("financial_engine", "finco_core", "domain", "finco_radar/venues")


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True).stdout.strip()


@pytest.mark.parametrize("key", sorted(S.STREAM_RANGES))
def test_every_registered_range_has_verified_provenance_and_no_protected_delta(key):
    assert S.provenance_violations(key) == []
    assert S.protected_delta(key, *NAMESPACES) == []


def test_unknown_stream_is_never_an_empty_delta():
    result = S.protected_delta("test_not_a_registered_stream", "financial_engine")
    assert result and all(S.UNVERIFIED in line for line in result)


@pytest.mark.parametrize("tamper", ["base", "head", "merge"])
def test_a_tampered_range_fails_closed(monkeypatch, tamper):
    key = "test_rwa_integrity"
    good = S.STREAM_RANGES[key]
    bogus = "1" * 40
    mutated = good._replace(**{tamper: bogus})
    monkeypatch.setitem(S.STREAM_RANGES, key, mutated)
    result = S.protected_delta(key, "financial_engine", "finco_core")
    assert result and all(S.UNVERIFIED in line for line in result)


def test_swapping_in_another_streams_commits_fails_closed(monkeypatch):
    a, b = S.STREAM_RANGES["test_rwa_integrity"], S.STREAM_RANGES["test_yield_alerts_core"]
    monkeypatch.setitem(S.STREAM_RANGES, "test_rwa_integrity", a._replace(head=b.head))          # head is not the landing merge's second parent
    assert any(S.UNVERIFIED in line for line in S.protected_delta("test_rwa_integrity", "financial_engine"))
    monkeypatch.setitem(S.STREAM_RANGES, "test_rwa_integrity", a._replace(base=b.base))          # base is not the merge base of the parents
    assert any(S.UNVERIFIED in line for line in S.protected_delta("test_rwa_integrity", "financial_engine"))


def test_a_merge_that_is_not_on_main_fails_closed():
    result = S.protected_delta("test_rwa_integrity", "financial_engine", main_ref="HEAD~100000")
    assert result and all(S.UNVERIFIED in line for line in result)
    assert S.protected_delta("test_rwa_integrity", "financial_engine", main_ref="refs/does/not/exist")


def test_a_stream_that_really_changed_a_protected_path_is_reported(tmp_path, monkeypatch):
    repo = tmp_path / "synthetic"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    for key, value in (("user.name", "Synthetic"), ("user.email", "noreply@users.noreply.github.com"), ("core.autocrlf", "false")):
        git(repo, "config", key, value)
    (repo / "README.md").write_text("x")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "stream")
    (repo / "financial_engine").mkdir()
    (repo / "financial_engine" / "sneaky.py").write_text("x = 1\n")
    (repo / "docs.md").write_text("ok")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "stream edits frozen engine")
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    (repo / "main_only.txt").write_text("main side")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "main advances")
    git(repo, "merge", "-q", "--no-ff", "-m", "land stream", "stream")
    merge = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    monkeypatch.setitem(S.STREAM_RANGES, "synthetic", S.StreamRange(base, head, merge))
    assert S.provenance_violations("synthetic", repo=repo) == []
    assert S.protected_delta("synthetic", "financial_engine", repo=repo) == ["financial_engine/sneaky.py"]       # a real change is still seen
    assert S.protected_delta("synthetic", "finco_core", repo=repo) == []                                         # other namespaces are unaffected


def test_main_side_changes_after_the_stream_diverged_never_count_as_stream_changes(tmp_path, monkeypatch):
    repo = tmp_path / "synthetic2"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    for key, value in (("user.name", "Synthetic"), ("user.email", "noreply@users.noreply.github.com"), ("core.autocrlf", "false")):
        git(repo, "config", key, value)
    (repo / "README.md").write_text("x")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "stream")
    (repo / "app.py").write_text("ok")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "benign stream")
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    (repo / "financial_engine").mkdir()
    (repo / "financial_engine" / "later_main_change.py").write_text("y = 2\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "someone else changes the engine on main")
    git(repo, "merge", "-q", "--no-ff", "-m", "land stream", "stream")
    merge = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    monkeypatch.setitem(S.STREAM_RANGES, "synthetic2", S.StreamRange(base, head, merge))
    assert S.protected_delta("synthetic2", "financial_engine", repo=repo) == []


def test_the_module_is_not_an_authority_and_exempts_nothing():
    source = (ROOT / "tests" / "stream_scope_proof.py").read_text(encoding="utf-8")
    for forbidden in ("approved_frozen_path", "released_engine_authority_matches", "unapproved_engine_changes", "strictly_frozen_changes",
                      "ACTIVATION_ENABLED", "rc3_historical_anchor"):
        assert forbidden not in source.replace("# ", ""), forbidden


def test_verified_delta_raises_instead_of_returning_a_marker_that_a_filter_could_drop(monkeypatch):
    with pytest.raises(AssertionError):
        S.verified_delta("test_not_a_registered_stream", "financial_engine")
    key = "test_rwa_integrity"
    monkeypatch.setitem(S.STREAM_RANGES, key, S.STREAM_RANGES[key]._replace(head="1" * 40))
    with pytest.raises(AssertionError):
        S.verified_delta(key, "financial_engine")
    monkeypatch.undo()
    assert S.verified_delta(key, "financial_engine") == []
