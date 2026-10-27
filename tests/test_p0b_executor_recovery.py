"""P0-B — ModelExecutor process-pool recovery (generation-aware replacement). Real spawned OS processes.

Root cause fixed: ``_submit`` converted a ``BrokenProcessPool`` raised by ``pool.submit()`` (idle worker died) into
``ModelExecutionFailed`` WITHOUT invalidating the pool, so every later Run failed; ``_translate`` discarded whatever pool
was current (possibly a newer healthy one); warm evidence kept PIDs of destroyed workers. Recovery is demand-driven and
never retries a submitted calculation.
"""
from __future__ import annotations

import os
import signal
import threading
import time

import pytest

import p0b_recovery_helpers as h
from app.runtime import model_execution as me
from app.runtime.model_execution import ModelExecutionConfig, ModelExecutionFailed, ModelExecutor


@pytest.fixture(autouse=True)
def _isolation(monkeypatch):
    monkeypatch.setattr(me, "_worker_init", h.light_init)
    yield
    me.reset_model_executor_for_tests(None)


def make(concurrency=2, timeout=60) -> ModelExecutor:
    ex = ModelExecutor(ModelExecutionConfig(concurrency, "process", timeout))
    me.reset_model_executor_for_tests(ex)
    return ex


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:                                   # a zombie that was not reaped yet is not alive
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def kill_and_wait(pid: int) -> None:
    os.kill(pid, signal.SIGKILL)
    deadline = time.monotonic() + 10
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not alive(pid)


def assert_accounting(ex: ModelExecutor) -> None:
    """Every admitted calculation released its slot exactly once."""
    stats = ex.stats()
    assert stats["active"] == 0
    assert stats["admitted"] == stats["completed"] + stats["failed"]
    assert ex._gate._value == ex.config.concurrency          # noqa: SLF001 - the semaphore is back at full capacity


def pool_pids(ex: ModelExecutor) -> list[int]:
    pool = ex._process_pool                                      # noqa: SLF001
    return list(getattr(pool, "_processes", {}) or {}) if pool is not None else []


# 1 — idle worker killed before any Run ──────────────────────────────────────────────────────────────
def test_idle_worker_killed_before_any_run_recovers_for_the_next_run():
    ex = make(1)
    pid = ex.run_process_sync(h.worker_pid)
    kill_and_wait(pid)
    with pytest.raises(ModelExecutionFailed):
        ex.run_process_sync(h.worker_pid)                        # the call that observes the break fails, typed
    assert ex._process_pool is None                              # noqa: SLF001 - the broken generation was invalidated
    new_pid = ex.run_process_sync(h.worker_pid)                  # a deliberately submitted later Run is served
    assert new_pid != pid and alive(new_pid)
    assert ex.run_process_sync(h.worker_pid) == new_pid
    assert ex.stats()["pools_created"] == 2
    assert_accounting(ex)


def test_old_behaviour_would_fail_forever_new_behaviour_recovers_after_three_attempts():
    ex = make(1)
    pid = ex.run_process_sync(h.worker_pid)
    kill_and_wait(pid)
    outcomes = []
    for _ in range(3):
        try:
            outcomes.append(ex.run_process_sync(h.worker_pid))
        except ModelExecutionFailed:
            outcomes.append("failed")
    assert outcomes[0] == "failed" and isinstance(outcomes[1], int) and isinstance(outcomes[2], int)
    assert_accounting(ex)


def test_real_warm_up_then_idle_kill_clears_warm_evidence_and_recovers():
    ex = make(1)
    monkey_init = me._worker_init                                # noqa: SLF001 - light init stays; the real probe runs
    assert monkey_init is h.light_init
    state = ex.warm_up()
    assert state["warm"] is True and len(state["warm_pids"]) == 1
    dead = state["warm_pids"][0]
    kill_and_wait(dead)
    with pytest.raises(ModelExecutionFailed):
        ex.run_process_sync(h.worker_pid)
    state = ex.warm_state()
    assert state["warm"] is False and state["warm_pids"] == [] and state["warm_workers"] == 0   # destroyed worker not warm
    assert ex.run_process_sync(h.worker_pid) != dead
    assert_accounting(ex)


# 2 — worker killed during calculation ─────────────────────────────────────────────────────────────────
def test_worker_killed_during_calculation_fails_that_run_only_and_releases_the_slot():
    ex = make(1)
    ex.run_process_sync(h.worker_pid)
    result: dict = {}

    def run():
        try:
            result["value"] = ex.run_process_sync(h.sleep_pid, 30)
        except BaseException as exc:                              # noqa: BLE001
            result["error"] = exc

    t = threading.Thread(target=run)
    t.start()
    deadline = time.monotonic() + 10
    while ex.stats()["active"] < 1 and time.monotonic() < deadline:
        time.sleep(0.02)
    time.sleep(0.5)
    victim = pool_pids(ex)[0]
    os.kill(victim, signal.SIGKILL)
    t.join(30)
    assert not t.is_alive() and isinstance(result.get("error"), ModelExecutionFailed)
    assert ex.run_process_sync(h.worker_pid) != victim
    assert_accounting(ex)


# 3 — pool broken before submit(): the path that used to bypass invalidation ───────────────────────────
def test_broken_pool_detected_directly_by_submit_is_invalidated():
    ex = make(1)
    pid = ex.run_process_sync(h.worker_pid)
    kill_and_wait(pid)
    time.sleep(0.5)                                              # let the pool's management thread notice
    old = ex._process_pool                                       # noqa: SLF001
    with pytest.raises(ModelExecutionFailed):
        ex._submit("process", h.worker_pid, (), {})              # noqa: SLF001
    assert ex._process_pool is None and ex._pool_generation == 1  # noqa: SLF001
    with pytest.raises(RuntimeError):                            # the retired pool accepts no new submission
        old.submit(h.worker_pid)
    assert ex.run_process_sync(h.worker_pid) != pid and ex._pool_generation == 2   # noqa: SLF001
    assert_accounting(ex)


# 4 — multiple simultaneous callers on the same broken pool ────────────────────────────────────────────
def test_simultaneous_callers_replace_a_broken_pool_exactly_once():
    ex = make(8)
    pids = {ex.run_process_sync(h.sleep_pid, 0.0)}
    ex.run_process_sync(h.worker_pid)
    for pid in pool_pids(ex):
        kill_and_wait(pid)
    time.sleep(0.5)
    barrier = threading.Barrier(8)
    outcomes: list = []
    lock = threading.Lock()

    def call():
        barrier.wait()
        try:
            value = ex.run_process_sync(h.worker_pid)
        except ModelExecutionFailed:
            value = "failed"
        with lock:
            outcomes.append(value)

    threads = [threading.Thread(target=call) for _ in range(8)]
    [t.start() for t in threads]
    [t.join(60) for t in threads]
    assert len(outcomes) == 8 and not any(t.is_alive() for t in threads)
    assert "failed" in outcomes                                  # at least the caller that observed the break
    assert ex.stats()["pools_created"] <= 3                      # original + one replacement per broken generation
    final = ex.run_process_sync(h.worker_pid)
    assert alive(final) and final not in pids
    assert_accounting(ex)


# 5/6 — replacement pool fails during startup / prewarm ────────────────────────────────────────────────
def test_replacement_pool_failing_at_startup_does_not_wedge_the_executor(monkeypatch):
    ex = make(1)
    pid = ex.run_process_sync(h.worker_pid)
    kill_and_wait(pid)
    with pytest.raises(ModelExecutionFailed):
        ex.run_process_sync(h.worker_pid)
    monkeypatch.setattr(me, "_worker_init", h.failing_init)       # the replacement pool's workers cannot start
    with pytest.raises(ModelExecutionFailed):
        ex.run_process_sync(h.worker_pid)
    assert ex._process_pool is None                              # noqa: SLF001 - the failed generation is retired too
    monkeypatch.setattr(me, "_worker_init", h.light_init)
    assert alive(ex.run_process_sync(h.worker_pid))
    assert_accounting(ex)


def test_failed_prewarm_retires_its_pool_and_creates_no_competing_pool(monkeypatch):
    ex = make(1)
    monkeypatch.setattr(me, "_worker_init", h.failing_init)
    state = ex.warm_up()
    assert state["warm"] is False and state["warm_pids"] == []
    assert ex._process_pool is None and ex.stats()["pools_created"] == 1    # noqa: SLF001
    monkeypatch.setattr(me, "_worker_init", h.light_init)
    assert alive(ex.run_process_sync(h.worker_pid))
    assert ex.stats()["pools_created"] == 2
    assert_accounting(ex)


def test_prewarm_does_not_publish_readiness_for_a_pool_retired_meanwhile(monkeypatch):
    ex = make(1)
    monkeypatch.setattr(me, "_worker_warmup_probe", h.slow_probe)
    holder: dict = {}
    t = threading.Thread(target=lambda: holder.setdefault("state", ex.warm_up()))
    t.start()
    deadline = time.monotonic() + 10
    while ex._process_pool is None and time.monotonic() < deadline:   # noqa: SLF001
        time.sleep(0.01)
    time.sleep(0.5)
    assert ex._retire_process_pool(ex._process_pool)             # noqa: SLF001
    t.join(60)
    assert not t.is_alive()
    assert ex.warm_state()["warm"] is False and ex.warm_state()["warm_pids"] == []


# 7 — concurrent replacement attempts never discard a newer healthy pool ───────────────────────────────
def test_retirement_is_per_generation_and_never_discards_a_newer_pool():
    ex = make(1)
    first = ex._pool("process")                                  # noqa: SLF001
    results = []
    barrier = threading.Barrier(8)

    def retire():
        barrier.wait()
        results.append(ex._retire_process_pool(first))           # noqa: SLF001

    threads = [threading.Thread(target=retire) for _ in range(8)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert results.count(True) == 1                              # exactly one retirement per generation
    second = ex._pool("process")                                 # noqa: SLF001
    assert second is not first and ex._pool_generation == 2      # noqa: SLF001
    assert ex._retire_process_pool(first) is False               # a stale observer cannot touch the new pool
    assert ex._process_pool is second                            # noqa: SLF001
    assert alive(ex.run_process_sync(h.worker_pid))
    assert_accounting(ex)


def test_a_stale_broken_pool_failure_does_not_retire_the_replacement():
    ex = make(1)
    pid = ex.run_process_sync(h.worker_pid)
    old_future = ex._submit("process", h.sleep_pid, (5,), {})    # noqa: SLF001
    time.sleep(0.5)
    kill_and_wait(pid)
    with pytest.raises(Exception):
        old_future.result(30)
    with pytest.raises(ModelExecutionFailed):                    # translate retires the generation of THAT future
        raise ex._translate(old_future.exception(), old_future)  # noqa: SLF001
    replacement = ex._pool("process")                            # noqa: SLF001
    ex._translate(old_future.exception(), old_future)            # noqa: SLF001 - late duplicate observation
    assert ex._process_pool is replacement                       # noqa: SLF001
    assert alive(ex.run_process_sync(h.worker_pid))
    assert_accounting(ex)


# 12 — repeated crashes: bounded replacement (circuit breaker) ─────────────────────────────────────────
def test_repeated_crashes_cannot_create_an_unbounded_restart_loop(monkeypatch):
    monkeypatch.setattr(me, "MAX_POOL_RETIREMENTS", 3)
    monkeypatch.setattr(me, "POOL_RETIREMENT_WINDOW_SECONDS", 3.0)
    ex = make(1)
    for _ in range(12):
        with pytest.raises(ModelExecutionFailed):
            ex.run_process_sync(h.crash_now)
    assert ex.stats()["pools_created"] <= 3                      # the breaker stopped further spawning
    deadline = time.monotonic() + 15
    while True:                                                  # after the window, availability returns
        try:
            assert alive(ex.run_process_sync(h.worker_pid))
            break
        except ModelExecutionFailed:
            assert time.monotonic() < deadline
            time.sleep(0.25)
    assert_accounting(ex)


# 11 — graceful shutdown during recovery ───────────────────────────────────────────────────────────────
def test_shutdown_during_recovery_leaves_no_orphan_and_no_new_pool():
    ex = make(2)
    seen: set[int] = set()
    stop = threading.Event()

    def churn():
        while not stop.is_set():
            try:
                seen.add(ex.run_process_sync(h.worker_pid))
                for pid in pool_pids(ex):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            except ModelExecutionFailed:
                pass
            except Exception:                                    # noqa: BLE001
                pass

    t = threading.Thread(target=churn)
    t.start()
    time.sleep(3)
    stragglers = ex.shutdown_and_join()
    stop.set()
    t.join(30)
    assert not t.is_alive()
    with pytest.raises(ModelExecutionFailed):                    # nothing may create a pool after shutdown
        ex.run_process_sync(h.worker_pid)
    assert ex._process_pool is None                              # noqa: SLF001
    deadline = time.monotonic() + 15
    while any(alive(p) for p in seen) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not any(alive(p) for p in seen), "orphan model worker survived shutdown"
    assert isinstance(stragglers, list)
    assert_accounting(ex)


# ── structural guard: the preserved admission/lifecycle gates and the recovery invariants stay in the source ─────────────────
import ast
from pathlib import Path

EXECUTOR_SOURCE = Path(me.__file__)


def executor_violations(source: str) -> list[str]:
    """Independent of any byte pin: drift that removes a preserved gate or a recovery invariant is reported."""
    errors: list[str] = []
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ModelExecutor")
    fn = {n.name: n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    text = {name: ast.unparse(node) for name, node in fn.items()}

    def need(name: str, *needles: str) -> None:
        for needle in needles:
            if name not in text or needle not in text[name]:
                errors.append(f"{name}: missing {needle!r}")

    need("_admit", "self._gate.acquire(blocking=False)", "raise ModelExecutionBusy()")      # non-blocking admission, typed Busy
    need("_finish", "self._gate.release()")                                                    # slot released when the work ends
    need("_submit", "self._admit()", "self._pool_locked(kind)", "except BrokenProcessPool", "self._retire_process_pool(pool)",
         "raise ModelExecutionFailed() from None", "self._gate.release()")
    if text.get("_submit", "").count("pool.submit(") != 2:                                     # one process, one thread submission
        errors.append("_submit: submission sites changed (no resubmission is allowed)")
    need("_retire_process_pool", "self._process_pool is not pool", "pool.shutdown(wait=False, cancel_futures=True)")
    need("_translate", "getattr(future, 'finco_pool', None)", "return ModelExecutionFailed()")
    need("_pool_locked", "self._closed", "len(recent) >= MAX_POOL_RETIREMENTS")
    need("shutdown", "self._closed = True", "cancel_futures=True")
    need("shutdown_and_join", "self._closed = True")
    need("_await", "asyncio.wait_for", "raise ModelExecutionTimeout() from None", "self._translate(exc, future)")
    return errors


def test_real_executor_keeps_every_preserved_gate_and_recovery_invariant():
    assert executor_violations(EXECUTOR_SOURCE.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("old,new", [
    ("self._gate.acquire(blocking=False)", "self._gate.acquire()"),                           # admission became blocking
    ("raise ModelExecutionBusy()", "pass"),                                                   # Busy contract removed
    ("            self._retire_process_pool(pool)\n            with self._lock:\n                self._active -= 1",
     "            with self._lock:\n                self._active -= 1"),                       # submit-time break no longer invalidates
    ("if self._process_pool is not pool:", "if False:"),                                      # retirement no longer per generation
    ("self._retire_process_pool(getattr(future, \"finco_pool\", None))", "self._retire_process_pool(self._process_pool)"),
    ("pool.shutdown(wait=False, cancel_futures=True)\n        LOG.warning", "LOG.warning"),     # old pool would stay usable
    ("if self._closed:\n                    raise ModelExecutionFailed()", "if False:\n                    raise ModelExecutionFailed()"),
    ("len(recent) >= MAX_POOL_RETIREMENTS", "False"),                                         # unbounded replacement
])
def test_drift_or_removed_gate_is_reported_without_any_byte_pin(old, new):
    source = EXECUTOR_SOURCE.read_text(encoding="utf-8")
    assert old in source, old
    assert executor_violations(source.replace(old, new, 1)), old
