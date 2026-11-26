"""P0-B x D-029 — executor recovery with REAL spawned worker processes, the real Run route and real SQLite.

A broken pool restores availability for later, deliberately submitted Runs. It never re-executes a reserved intent:
a terminal FAILED intent stays FAILED, a committed intent is replayed from the ledger without touching the executor,
and no Run History row is duplicated. Authorization, CSRF, protected-reference checks and the final CAS are the
route's own and are exercised unchanged (security gates precede the ledger in every request below).
"""
from __future__ import annotations

import os
import signal
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.test_d029_run_idempotency_http import intent_state, intents, post, run_form
from tests.test_model_credit_decision_v3_real_runs import history
from tests.test_model_decision_workspace_v2 import env as _env, tokens  # noqa: F401  (fixture re-export)

env = _env


@pytest.fixture(autouse=True)
def _process_executor(monkeypatch):
    from app.runtime import model_execution as me
    monkeypatch.setenv("FINCO_MODEL_EXECUTION_MODE", "process")
    monkeypatch.setenv("FINCO_MODEL_EXECUTION_CONCURRENCY", "2")
    monkeypatch.setenv("FINCO_NATIVE_V10_RUN", "off")
    monkeypatch.setenv("FINCO_NATIVE_V11_RUN", "off")
    me.reset_model_executor_for_tests(None)
    yield
    me.reset_model_executor_for_tests(None)


def executor():
    from app.runtime.model_execution import get_model_executor
    return get_model_executor()


def worker_pids(ex):
    pool = ex._process_pool                                       # noqa: SLF001
    return list(getattr(pool, "_processes", {}) or {}) if pool is not None else []


def kill_all(ex):
    pids = worker_pids(ex)
    assert pids, "no worker to kill"
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 10
    while any(os.path.exists(f"/proc/{p}") and "Z" not in open(f"/proc/{p}/stat").read().rsplit(")", 1)[1][:3] for p in pids) \
            and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(0.5)


def commit(env, record):
    key = str(uuid.uuid4())
    response = post(env, run_form(env, record, key))
    assert response.status_code == 200 and response.json()["outcome"] == "COMMITTED", response.text
    return key, response.json()


def test_idle_workers_killed_then_new_intents_commit_and_failed_intent_is_terminal(env):
    record = env.create("solar")
    ex = executor()
    key_a, first = commit(env, record)
    kill_all(ex)
    key_b = str(uuid.uuid4())
    form_b = run_form(env, record, key_b)
    failed = post(env, form_b)                                     # the call that observes the broken pool fails, typed
    assert failed.status_code == 409 and failed.json()["outcome"] == "FAILED"
    assert intent_state(key_b)["state"] == "FAILED" and len(history(record)) == 1
    admitted = ex.stats()["admitted"]
    again = post(env, dict(form_b, csrf_token=run_form(env, record, key_b)["csrf_token"]))
    assert again.json()["outcome"] == "FAILED"                    # same key: terminal, never silently recalculated
    assert ex.stats()["admitted"] == admitted and len(history(record)) == 1
    key_c, third = commit(env, record)                            # recovery: a deliberate new Run is served
    assert third["history_id"] != first["history_id"]
    rows = history(record)
    assert len(rows) == 2 and len({r["id"] if isinstance(r, dict) and "id" in r else repr(r) for r in rows}) == 2
    states = {i["run_intent_id"]: i["state"] for i in intents()}
    assert states[key_a] == "COMMITTED" and states[key_b] == "FAILED" and states[key_c] == "COMMITTED"
    stats = ex.stats()
    assert stats["active"] == 0 and stats["admitted"] == stats["completed"] + stats["failed"] and stats["pools_created"] == 2


def _wait_for(predicate, what, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


def _is_dead(pid):
    try:
        return "Z" in open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1][:3]
    except (FileNotFoundError, ProcessLookupError):
        return True


def test_worker_killed_during_calculation_leaves_a_terminal_intent_and_no_history(env, monkeypatch, tmp_path):
    """Deterministic: the REAL worker is held INSIDE the calculation (before it can return or commit), then that exact pid is SIGKILLed."""
    import app.api.project_runner as project_runner
    from functools import partial
    from tests.d029_executor_hold import held_run_project

    record = env.create("solar")
    ex = executor()
    commit(env, record)                                            # spawn and warm the pool with the canonical calculation
    rows_before = len(history(record))
    key_b = str(uuid.uuid4())
    form_b = run_form(env, record, key_b)
    form_b2 = dict(form_b, csrf_token=run_form(env, record, key_b)["csrf_token"])    # prepared before the Run starts
    real = project_runner.run_project
    hold = tmp_path / "hold"
    hold.mkdir()
    monkeypatch.setattr(project_runner, "run_project", partial(held_run_project, str(hold)))
    pid = None
    try:
        with ThreadPoolExecutor(1) as pool:
            running = pool.submit(post, env, form_b)
            marker = _wait_for(lambda: next(iter(hold.glob("reached.*")), None), "the worker to enter the calculation")
            pid = int(marker.read_text(encoding="utf-8"))
            # positive evidence: this pid is a live worker of the pool, the intent is unresolved and nothing was committed
            assert pid in worker_pids(ex) and not _is_dead(pid) and pid != os.getpid()
            assert intent_state(key_b)["state"] not in ("COMMITTED", "FAILED") and len(history(record)) == rows_before
            # an unresolved intent is visible to a concurrent request and is NOT started a second time
            admitted = ex.stats()["admitted"]
            second = post(env, form_b2)
            assert second.status_code == 409 and second.json()["outcome"] == "IN_PROGRESS"
            assert ex.stats()["admitted"] == admitted and len(list(hold.glob("reached.*"))) == 1
            assert not running.done()
            os.kill(pid, signal.SIGKILL)                           # the actual in-flight child, before it can return
            _wait_for(lambda: _is_dead(pid), f"worker {pid} to die", timeout=10)
            outcome = running.result(60).json()
    finally:
        (hold / "release").write_text("1", encoding="utf-8")        # bounded teardown even if an assertion failed
        if pid is not None and not _is_dead(pid):
            os.kill(pid, signal.SIGKILL)
        monkeypatch.setattr(project_runner, "run_project", real)
    assert outcome["outcome"] == "FAILED" and intent_state(key_b)["state"] == "FAILED"
    assert len(history(record)) == rows_before                      # nothing committed for the killed calculation
    retry = post(env, dict(form_b, csrf_token=run_form(env, record, key_b)["csrf_token"])).json()
    assert retry["outcome"] == "FAILED" and ex.stats()["admitted"] == admitted     # not re-executed after recovery
    commit(env, record)
    assert len(history(record)) == rows_before + 1 and ex.stats()["active"] == 0
    assert len(list(hold.glob("reached.*"))) == 1                   # the held calculation ran exactly once; the fresh key used the real one


def test_lost_response_after_commit_is_replayed_without_touching_a_broken_executor(env):
    record = env.create("solar")
    ex = executor()
    key, first = commit(env, record)                               # the client never saw this response
    kill_all(ex)
    admitted, created = ex.stats()["admitted"], ex.stats()["pools_created"]
    replay = post(env, run_form(env, record, key)).json()
    assert replay["outcome"] == "REPLAYED" and replay["history_id"] == first["history_id"]
    stats = ex.stats()
    assert stats["admitted"] == admitted and stats["pools_created"] == created      # no submission, no recovery needed
    assert len(history(record)) == 1


def test_repeated_crashes_never_duplicate_history_and_recovery_stays_available(env):
    record = env.create("solar")
    ex = executor()
    commit(env, record)
    for _ in range(3):
        kill_all(ex)
        broken = post(env, run_form(env, record, str(uuid.uuid4())))
        assert broken.json()["outcome"] == "FAILED"
        commit(env, record)
    assert len(history(record)) == 4
    ids = [i["run_intent_id"] for i in intents()]
    assert len(ids) == len(set(ids)) == 7
    assert ex.stats()["active"] == 0
