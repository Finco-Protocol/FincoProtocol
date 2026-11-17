"""Adversarial tests for tests/ci_immutable_git_reads.py: a memoised read may only ever return what a fresh git call returns, and a fresh
git error is never turned into a result. Each test is ONE attack; none is folded into a generic mock."""
import os
import subprocess
import threading

import pytest

from tests import ci_immutable_git_reads as M


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


@pytest.fixture(autouse=True)
def _outside_any_scope():
    # The suite-wide per-test scope (tests/conftest.py) is closed here so every attack opens its own scope from a clean state.
    saved_owner, saved_memo, saved_fn = list(M._OWNER), dict(M._MEMO), subprocess.check_output
    M._OWNER.clear()
    M._MEMO.clear()
    subprocess.check_output = M._ORIGINAL
    for k in M.STATS:
        M.STATS[k] = 0
    try:
        yield
    finally:
        M._MEMO.clear()
        M._OWNER[:] = saved_owner
        M._MEMO.update(saved_memo)
        subprocess.check_output = saved_fn


def show(repo, rev, path="a.txt"):
    return subprocess.check_output(["git", "show", rev + ":" + path], cwd=repo, stderr=subprocess.DEVNULL)


# ── original attacks (audit 2026-11-17) ───────────────────────────────────────────────────────────────────────────────────────────
def test_full_sha_read_is_memoised_and_equal_to_git(repo):
    sha = _git(repo, "rev-parse", "HEAD")
    with M.scope():
        assert show(repo, sha) == b"one\n" and show(repo, sha) == b"one\n"
    assert M.STATS["hits"] == 1 and M.STATS["misses"] == 1


def test_symbolic_refs_and_worktree_are_never_memoised(repo):
    with M.scope():
        assert show(repo, "HEAD") == b"one\n"
        (repo / "a.txt").write_bytes(b"two\n")
        _git(repo, "commit", "-qam", "c2")
        assert show(repo, "HEAD") == b"two\n"
        assert subprocess.check_output(["git", "rev-parse", "HEAD:a.txt"], cwd=repo).strip() == _git(repo, "hash-object", "a.txt").encode()
    assert M.STATS["hits"] == 0


def test_abbreviated_sha_is_not_memoised(repo):
    short = _git(repo, "rev-parse", "--short", "HEAD")
    with M.scope():
        show(repo, short)
        show(repo, short)
    assert M.STATS["hits"] == 0


def test_failure_is_never_memoised_and_a_later_object_is_seen(repo):
    (repo / "a.txt").write_bytes(b"later\n")
    blob = _git(repo, "hash-object", "a.txt")
    with M.scope():
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.check_output(["git", "cat-file", "-p", blob], cwd=repo, stderr=subprocess.DEVNULL)
        _git(repo, "hash-object", "-w", "a.txt")
        assert subprocess.check_output(["git", "cat-file", "-p", blob], cwd=repo) == b"later\n"


def test_another_repository_without_the_object_still_fails(repo, tmp_path):
    sha = _git(repo, "rev-parse", "HEAD")
    other = _init(tmp_path / "other")
    with M.scope():
        assert show(repo, sha) == b"one\n"
        with pytest.raises(subprocess.CalledProcessError):
            show(other, sha)


def test_recreated_repository_at_the_same_path_is_a_different_store(repo):
    sha = _git(repo, "rev-parse", "HEAD")
    with M.scope():
        assert show(repo, sha) == b"one\n"
        subprocess.run(["rm", "-rf", str(repo / ".git")], check=True)
        _git(repo, "init", "-q")
        with pytest.raises(subprocess.CalledProcessError):
            show(repo, sha)


def test_replace_refs_disable_the_memo(repo):
    sha = _git(repo, "rev-parse", "HEAD")
    old_blob = _git(repo, "rev-parse", "HEAD:a.txt")
    (repo / "b.txt").write_bytes(b"forged\n")
    new_blob = _git(repo, "hash-object", "-w", "b.txt")
    with M.scope():
        assert show(repo, sha) == b"one\n"
        _git(repo, "replace", old_blob, new_blob)
        assert show(repo, sha) == b"forged\n"
    assert M.STATS["hits"] == 0


def test_packed_replace_ref_disables_the_memo(repo):
    sha = _git(repo, "rev-parse", "HEAD")
    old_blob = _git(repo, "rev-parse", "HEAD:a.txt")
    (repo / "b.txt").write_bytes(b"forged\n")
    new_blob = _git(repo, "hash-object", "-w", "b.txt")
    _git(repo, "replace", old_blob, new_blob)
    _git(repo, "pack-refs", "--all")
    assert not any((repo / ".git/refs/replace").iterdir()) and b"refs/replace/" in (repo / ".git/packed-refs").read_bytes()
    with M.scope():
        assert show(repo, sha) == b"forged\n" and show(repo, sha) == b"forged\n"
    assert M.STATS["hits"] == 0


def test_shallow_or_grafted_history_disables_the_memo(repo):
    sha = _git(repo, "rev-parse", "HEAD")
    (repo / ".git" / "shallow").write_text(sha + "\n")
    with M.scope():
        show(repo, sha)
        show(repo, sha)
    assert M.STATS["hits"] == 0


def test_substituted_process_layer_is_always_reached(repo, monkeypatch):
    sha = _git(repo, "rev-parse", "HEAD")
    with M.scope():
        assert show(repo, sha) == b"one\n"

        def unavailable(*a, **k):
            raise FileNotFoundError("git")
        monkeypatch.setattr(subprocess, "run", unavailable)
        with pytest.raises(FileNotFoundError):
            show(repo, sha)


def test_location_environment_disables_the_memo(repo, monkeypatch):
    sha = _git(repo, "rev-parse", "HEAD")
    with M.scope():
        show(repo, sha)
        monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(repo / "nowhere"))
        with pytest.raises(subprocess.CalledProcessError):
            show(repo, sha)


def test_ineligible_forms_are_never_memoised():
    a = "0" * 40
    assert not M._eligible(["diff", "--name-only", a])
    assert not M._eligible(["diff", "--name-only", a, "HEAD"])
    assert not M._eligible(["diff", a, a, "--stat"])
    assert M._eligible(["diff", "--name-only", a, a, "--", "x"])
    assert not M._eligible(["ls-files", "--others"])
    assert not M._eligible(["show", "HEAD:x"]) and not M._eligible(["show", ":x"]) and not M._eligible(["show", a])
    assert not M._eligible(["merge-base", a, a])
    assert M._split(["git", "-c", "core.x=y", "show", a + ":x"], None) is None
    assert M._split(["git", b"show", a + ":x"], None) is None


def test_scope_drops_everything_and_restores_the_process_layer(repo):
    sha = _git(repo, "rev-parse", "HEAD")
    with M.scope():
        with M.scope():
            show(repo, sha)
        assert M._MEMO
    assert not M._MEMO and not M._OWNER and subprocess.check_output is M._ORIGINAL


def test_a_substitute_installed_before_the_scope_is_never_bypassed(repo, monkeypatch):
    sha = _git(repo, "rev-parse", "HEAD")
    calls = []

    def fake(*a, **k):
        calls.append(a)
        raise subprocess.CalledProcessError(128, a[0])
    monkeypatch.setattr(subprocess, "check_output", fake)
    with M.scope():
        for _ in range(2):
            with pytest.raises(subprocess.CalledProcessError):
                show(repo, sha)
    assert len(calls) == 2 and subprocess.check_output is fake


# ── Correction E review attacks ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_substitute_installed_during_the_scope_is_reached_and_the_memo_returns_after_undo(repo, monkeypatch):
    sha = _git(repo, "rev-parse", "HEAD")
    with M.scope():
        assert show(repo, sha) == b"one\n"
        with monkeypatch.context() as m:
            m.setattr(subprocess, "check_output", lambda *a, **k: b"substitute")
            assert show(repo, sha) == b"substitute"
        assert show(repo, sha) == b"one\n" and subprocess.check_output is M.check_output
    assert subprocess.check_output is M._ORIGINAL


def test_exception_inside_the_scope_restores_and_drops_everything(repo):
    sha = _git(repo, "rev-parse", "HEAD")
    with pytest.raises(RuntimeError):
        with M.scope():
            show(repo, sha)
            raise RuntimeError("boom")
    assert not M._MEMO and not M._OWNER and subprocess.check_output is M._ORIGINAL


def test_other_threads_never_use_or_fill_the_memo(repo):
    sha = _git(repo, "rev-parse", "HEAD")
    results, errors = [], []

    def worker():
        try:
            for _ in range(3):
                results.append(show(repo, sha))
        except Exception as exc:          # pragma: no cover - reported below
            errors.append(exc)
    with M.scope():
        show(repo, sha)
        hits_before = M.STATS["hits"]
        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert M.STATS["hits"] == hits_before and len(M._MEMO) == 1
    assert not errors and results == [b"one\n"] * 12


def test_a_second_thread_cannot_open_or_close_the_owner_scope(repo):
    sha = _git(repo, "rev-parse", "HEAD")
    entered = threading.Event()
    release = threading.Event()

    def other():
        with M.scope():                   # nested in another thread: a no-op, never the owner, never clears the owner's memo
            entered.set()
            release.wait(5)
    with M.scope():
        show(repo, sha)
        t = threading.Thread(target=other)
        t.start()
        entered.wait(5)
        release.set()
        t.join()
        assert M._OWNER == [threading.get_ident()] and M._MEMO
        show(repo, sha)
        assert M.STATS["hits"] == 1


def test_pruned_object_is_a_fresh_git_error_not_a_memoised_pass(repo):
    (repo / "u.txt").write_bytes(b"unreachable\n")
    blob = _git(repo, "hash-object", "-w", "u.txt")
    with M.scope():
        assert subprocess.check_output(["git", "cat-file", "-p", blob], cwd=repo) == b"unreachable\n"
        _git(repo, "prune", "--expire=now")
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.check_output(["git", "cat-file", "-p", blob], cwd=repo, stderr=subprocess.DEVNULL)


def test_repacked_and_pruned_store_is_reread(repo):
    sha = _git(repo, "rev-parse", "HEAD")
    with M.scope():
        assert show(repo, sha) == b"one\n"
        _git(repo, "gc", "--quiet", "--prune=now")
        misses = M.STATS["misses"]
        assert show(repo, sha) == b"one\n" and M.STATS["misses"] == misses + 1


def test_git_config_environment_change_is_a_different_key(repo, monkeypatch):
    sha = _git(repo, "rev-parse", "HEAD")
    with M.scope():
        show(repo, sha)
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
        monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.useReplaceRefs")
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")
        misses = M.STATS["misses"]
        assert show(repo, sha) == b"one\n" and M.STATS["misses"] == misses + 1


def test_repository_and_global_config_changes_are_a_different_key(repo, tmp_path, monkeypatch):
    sha = _git(repo, "rev-parse", "HEAD")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    with M.scope():
        show(repo, sha)
        _git(repo, "config", "core.x", "1")
        m0 = M.STATS["misses"]
        show(repo, sha)
        (tmp_path / "home" / ".gitconfig").write_text("[core]\n\ty = 1\n")
        show(repo, sha)
        assert M.STATS["misses"] == m0 + 2


def test_textconv_and_filters_from_worktree_attributes_do_not_change_object_reads(repo):
    sha = _git(repo, "rev-parse", "HEAD")
    with M.scope():
        first = show(repo, sha)
        (repo / ".gitattributes").write_text("*.txt diff=up filter=f\n")
        _git(repo, "config", "diff.up.textconv", "tr a-z A-Z")
        _git(repo, "config", "filter.f.smudge", "tr a-z A-Z")
        fresh = M._ORIGINAL(["git", "show", sha + ":a.txt"], cwd=repo, stderr=subprocess.DEVNULL)
        assert first == fresh == show(repo, sha) == b"one\n"


def test_alternates_store_is_read_and_its_generation_is_bound(repo, tmp_path):
    sha = _git(repo, "rev-parse", "HEAD")
    clone = tmp_path / "shared"
    subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(repo), str(clone)], check=True)
    with M.scope():
        assert show(clone, sha) == b"one\n"
        (repo / "n.txt").write_bytes(b"new\n")
        _git(repo, "hash-object", "-w", "n.txt")               # the ALTERNATE store changes
        misses = M.STATS["misses"]
        assert show(clone, sha) == b"one\n" and M.STATS["misses"] == misses + 1


def test_linked_worktree_reads_equal_git(repo, tmp_path):
    sha = _git(repo, "rev-parse", "HEAD")
    wt = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "--detach", str(wt), sha)
    with M.scope():
        assert show(wt, sha) == show(repo, sha) == b"one\n"
        assert M.STATS["hits"] == 1         # the same object store: one fresh read, one memo answer


def test_untrusted_keywords_and_argument_forms_bypass(repo):
    sha = _git(repo, "rev-parse", "HEAD")
    with M.scope():
        for kw in ({"env": {**os.environ}}, {"input": b""}, {"shell": False}, {"executable": "git"}):
            subprocess.check_output(["git", "show", sha + ":a.txt"], cwd=repo, **kw)
        subprocess.check_output(args=["git", "show", sha + ":a.txt"], cwd=repo)
        assert M.STATS["hits"] == 0 and not M._MEMO
        assert subprocess.check_output(["git", "show", sha + ":a.txt"], cwd=repo, text=True) == "one\n"
        assert subprocess.check_output(["git", "show", sha + ":a.txt"], cwd=repo) == b"one\n"   # bytes and text are distinct keys


def test_timeout_keyword_is_honoured_and_a_failure_with_stderr_is_not_memoised(repo):
    with M.scope():
        for _ in range(2):
            with pytest.raises(subprocess.CalledProcessError) as exc:
                subprocess.check_output(["git", "show", "f" * 40 + ":a.txt"], cwd=repo, stderr=subprocess.PIPE, timeout=30)
            assert exc.value.returncode != 0
    assert M.STATS["hits"] == 0 and M.STATS["misses"] == 0


def test_the_suite_scope_is_active_for_every_test():
    import tests.conftest as conftest
    assert callable(getattr(conftest, "_immutable_git_reads_per_test", None))
