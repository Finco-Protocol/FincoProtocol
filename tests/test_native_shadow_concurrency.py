"""Serialised lifecycle of the executor-owned V10 shadow observer under concurrency, the integrated
application shutdown coordinator (#346 background services + V10 shadow), and fail-closed candidate
resource limits. Deterministic: ordering is forced with events / barriers, never with sleeps.
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from app.runtime import model_execution as me
from app.runtime import native_shadow as ns
from app.runtime.model_execution import ModelExecutionConfig, ModelExecutor


def _shadow_threads():
    return [t for t in threading.enumerate() if t.name == ns.THREAD_NAME and t.is_alive()]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in (ns.ENV_SHADOW, ns.ENV_LOG, ns.ENV_QUEUE, ns.ENV_TIMEOUT, ns.ENV_MAX_INPUT_BYTES):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(ns, "SHADOWED", ns.SHADOWED | {("builtins", "len"), ("tests.native_v10_support", "sleep_for")})
    yield
    assert _shadow_threads() == []


@pytest.fixture
def executor():
    ex = ModelExecutor(ModelExecutionConfig(mode="thread", concurrency=1))
    yield ex
    assert ex.shutdown_and_join() == []


def _gated_shutdown(monkeypatch):
    """ShadowObserver.shutdown that, after moving the observer to STOPPING, waits for ``release``."""
    entered, release = threading.Event(), threading.Event()
    real = ns.ShadowObserver.shutdown

    def shutdown(self, timeout=30.0):
        entered.set()
        assert release.wait(30)
        return real(self, timeout)

    monkeypatch.setattr(ns.ShadowObserver, "shutdown", shutdown)
    return entered, release


def test_concurrent_shutdown_and_replacement_never_overlap(executor, monkeypatch):
    old = executor._native_shadow_reconcile("stage1")
    entered, release = _gated_shutdown(monkeypatch)
    created_while = []
    real_factory = ns.observer_from_environment

    def factory(mode):
        created_while.append((old.state, len(_shadow_threads())))
        return real_factory(mode)

    monkeypatch.setattr(ns, "observer_from_environment", factory)
    stopper = threading.Thread(target=executor.shutdown_native_shadow)
    stopper.start()
    assert entered.wait(10)                         # old observer is retired (owned) and stopping
    assert executor.native_shadow_observer() is None and executor.native_shadow_owned()
    result = {}
    replacer = threading.Thread(target=lambda: result.update(new=executor._native_shadow_reconcile("stage2")))
    replacer.start()
    replacer.join(0.5)
    assert replacer.is_alive() and created_while == []   # blocked on the transition: no replacement yet
    release.set()
    stopper.join(30)
    replacer.join(30)
    assert old.state == ns.STOPPED
    assert created_while == [(ns.STOPPED, 0)]       # created only after the old one stopped completely
    assert result["new"] is not None and result["new"].mode == "stage2"


def test_simultaneous_mode_changes_leave_exactly_one_observer(executor):
    barrier = threading.Barrier(4)
    seen = []

    def change(mode):
        barrier.wait(10)
        seen.append(executor._native_shadow_reconcile(mode))

    threads = [threading.Thread(target=change, args=(m,)) for m in ("stage1", "stage2", "stage1", "stage2")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    survivors = [o for o in seen if o is not None and o.state == ns.RUNNING]
    assert len({id(o) for o in survivors}) == 1 and executor.native_shadow_observer() is survivors[0]
    assert len(_shadow_threads()) == 1 and not executor._shadow_retired
    assert all(o.state == ns.STOPPED for o in seen if o is not None and o is not survivors[0])


def test_shutdown_during_an_active_native_worker_reaps_it(executor):
    from tests.native_v10_support import sleep_for

    observer = executor._native_shadow_reconcile("stage1")
    started = threading.Event()
    real_set = observer._set_proc

    def set_proc(proc):
        real_set(proc)
        if proc is not None:
            started.set()

    observer._set_proc = set_proc
    snap = observer.snapshot(sleep_for, (600.0,), {})
    observer.observe(snap, (600.0,), {}, value=600.0)
    assert started.wait(60)
    proc = observer._worker_proc
    executor.shutdown_native_shadow(30)
    assert not proc.is_alive() and observer.state == ns.STOPPED and not executor.native_shadow_owned()
    assert observer.records()[-1]["outcome"] == "CANDIDATE_CANCELLED"


def _stuck_observer(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def evaluate(self, isolation, snapshot, canonical, t_enq):
        entered.set()
        release.wait(60)                            # ignores the stop event: an unkillable survivor

    monkeypatch.setattr(ns.ShadowObserver, "_evaluate", evaluate)
    return entered, release


def test_shutdown_timeout_then_another_run_is_canonical_and_never_replaces(executor, monkeypatch):
    entered, release = _stuck_observer(monkeypatch)
    monkeypatch.setenv(ns.ENV_SHADOW, "stage1")
    try:
        assert asyncio.run(executor.run_process(len, (1, 2))) == 2
        assert entered.wait(10)
        with pytest.raises(ns.ShadowShutdownIncomplete):
            executor.shutdown_native_shadow(0.2)
        assert executor.native_shadow_owned() and executor.native_shadow_observer() is None
        assert asyncio.run(executor.run_process(len, (1, 2, 3))) == 3    # canonical unaffected
        assert executor.native_shadow_observer() is None and len(_shadow_threads()) == 1
        assert executor.stats()["native_shadow"]["retired"] == 1
    finally:
        release.set()
    executor.shutdown_native_shadow(10)
    assert not executor.native_shadow_owned()


def test_application_shutdown_after_incomplete_observer_shutdown(monkeypatch):
    import main_web

    calls = []

    async def stop_demo():
        calls.append("demo")

    async def stop_rlive():
        calls.append("rlive")
        raise RuntimeError("r-live stop failed (test)")

    monkeypatch.setattr(main_web, "_stop_demo_cleanup", stop_demo)
    monkeypatch.setattr(main_web, "_stop_r_live_snapshot_warmer", stop_rlive)
    entered, release = _stuck_observer(monkeypatch)
    monkeypatch.setattr(me, "NATIVE_SHADOW_SHUTDOWN_TIMEOUT_SECONDS", 0.2)
    ex = ModelExecutor(ModelExecutionConfig(mode="thread", concurrency=1))
    assert me.reset_model_executor_for_tests(ex) == []
    monkeypatch.setenv(ns.ENV_SHADOW, "stage1")
    try:
        assert asyncio.run(ex.run_process(len, (1,))) == 1
        assert entered.wait(10)
        with pytest.raises(ns.ShadowShutdownIncomplete):
            ex.shutdown_native_shadow(0.2)                      # first, incomplete
        with pytest.raises(BaseException) as group:             # application shutdown: all services attempted
            asyncio.run(main_web._shutdown_background_services())
        errors = group.value.exceptions
        assert calls == ["demo", "rlive"]
        assert {type(e).__name__ for e in errors} == {"RuntimeError", "ShadowShutdownIncomplete"}
        assert ex.native_shadow_owned()                         # survivor stays owned, no replacement
    finally:
        release.set()
    asyncio.run(main_web._stop_native_v10_shadow())             # survivor ended: complete now
    assert not ex.native_shadow_owned()
    assert me.reset_model_executor_for_tests(None) == []


def test_one_coordinated_shutdown_registration():
    import main_web

    names = [getattr(h, "__name__", "") for h in main_web.app.router.on_shutdown]
    assert names.count("_shutdown_background_services") == 1
    assert "_stop_native_v10_shadow" not in names              # coordinated, not a competing handler


def test_candidate_without_resource_limits_is_never_a_match(executor, monkeypatch):
    from financial_engine.native_v10 import isolation
    from tests.native_v10_support import FailingLimits

    monkeypatch.setattr(isolation, "WorkerLimits", FailingLimits)
    observer = executor._native_shadow_reconcile("stage1")
    snap = observer.snapshot(len, ((1, 2),), {})
    observer.observe(snap, ((1, 2),), {}, value=2)
    assert observer.drain(60)
    (record,) = observer.records()
    assert record["outcome"] == "CANDIDATE_LIMITS_FAILED" and record["candidate"] is None
    assert observer.stats().get("MATCH", 0) == 0


@pytest.mark.parametrize("limits", ["FailingLimits", "SetrlimitRefusedLimits"])
def test_limits_failure_through_the_executor_keeps_the_canonical_result(executor, monkeypatch, limits):
    """End to end: a refused RLIMIT declines the candidate with explicit evidence; the canonical value is returned
    unchanged, nothing is a MATCH and no candidate worker survives."""
    import multiprocessing

    import tests.native_v10_support as support
    from financial_engine.native_v10 import isolation

    monkeypatch.setattr(isolation, "WorkerLimits", getattr(support, limits))
    monkeypatch.setenv(ns.ENV_SHADOW, "stage1")
    assert asyncio.run(executor.run_process(len, (1, 2, 3))) == 3            # canonical, unchanged
    observer = executor.native_shadow_observer()
    assert observer is not None and observer.drain(60)
    (record,) = observer.records()
    assert record["outcome"] == "CANDIDATE_LIMITS_FAILED" and record["candidate"] is None
    assert observer.stats().get("MATCH", 0) == 0
    assert [p for p in multiprocessing.active_children() if p.is_alive()] == []


class _Survivor:
    """A retired observer that consumes every budget it is given and survives (or, once freed, stops)."""

    def __init__(self, budgets):
        self.state, self.mode, self.stuck, self.budgets = ns.RUNNING, "stage1", True, budgets

    def shutdown(self, timeout=30.0):
        self.budgets.append(timeout)
        if self.stuck:
            import time
            time.sleep(timeout)
            raise ns.ShadowShutdownIncomplete("survivor (test)")
        self.state = ns.STOPPED


def test_one_total_deadline_is_shared_never_multiplied_across_survivors(executor):
    import time

    budgets: list = []
    survivors = [_Survivor(budgets) for _ in range(3)]
    executor._shadow_retired = list(survivors)
    started = time.monotonic()
    with pytest.raises(ns.ShadowShutdownIncomplete):
        executor.shutdown_native_shadow(0.3)
    elapsed = time.monotonic() - started
    assert len(budgets) == 3 and budgets[0] <= 0.3 and budgets[1] <= 0.05 and budgets[2] <= 0.05   # remaining budget only
    assert elapsed < 0.6                                        # bounded by ONE total timeout, not 3 x 0.3
    assert executor.native_shadow_owned() and executor.native_shadow_observer() is None
    for survivor in survivors:
        survivor.stuck = False
    executor.shutdown_native_shadow(1)
    assert not executor.native_shadow_owned()


def test_a_survivor_blocks_replacement_until_application_shutdown_completes(executor, monkeypatch):
    budgets: list = []
    survivor = _Survivor(budgets)
    executor._shadow_retired = [survivor]
    executor._shadow_disabled_reason = "survivor (test)"
    monkeypatch.setenv(ns.ENV_SHADOW, "stage1")
    assert asyncio.run(executor.run_process(len, (1,))) == 1               # canonical, never shadowed
    assert executor.native_shadow_observer() is None and _shadow_threads() == []
    survivor.stuck = False
    executor.shutdown_native_shadow(1)
    assert not executor.native_shadow_owned()
