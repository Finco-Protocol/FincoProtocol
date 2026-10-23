"""Owned lifecycle of the dormant V10 shadow observer.

* start / cooperative shutdown with bounded joins; idempotent;
* queued (not started) evaluations are cancelled and counted on shutdown;
* an in-flight candidate worker process is killed and reaped on shutdown (no abandoned subprocess);
* a mode change replaces the observer only after the previous one stopped completely; switching the
  environment off stops it;
* an observer that does not stop within the bound is SHUTDOWN_INCOMPLETE: the shutdown raises, the
  executor refuses any replacement (fail closed, shadow disabled) while canonical calls keep working,
  and the condition is visible in executor stats until the survivor really ended;
* repeated application lifespans leave no observer thread behind;
* executor shutdown leaves no shadow thread and no child process.
"""
from __future__ import annotations

import asyncio
import multiprocessing
import threading
import time

import pytest

from app.runtime import model_execution as me
from app.runtime import native_shadow as ns
from app.runtime.model_execution import ModelExecutionConfig, ModelExecutor
from tests.native_v10_support import sleep_for

SLEEP_KEY = ("tests.native_v10_support", "sleep_for")


def _shadow_threads():
    return [t for t in threading.enumerate() if t.name == ns.THREAD_NAME and t.is_alive()]


def _children():
    return [p for p in multiprocessing.active_children() if p.is_alive()]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (ns.ENV_SHADOW, ns.ENV_LOG, ns.ENV_QUEUE, ns.ENV_TIMEOUT, ns.ENV_MAX_INPUT_BYTES):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(ns, "SHADOWED", ns.SHADOWED | {SLEEP_KEY, ("builtins", "len")})
    yield
    assert _shadow_threads() == []


def _blocking_evaluate(monkeypatch, *, cooperative: bool):
    """Replace candidate evaluation with a controllable block (cooperative = honours the stop event)."""
    entered, release = threading.Event(), threading.Event()

    def evaluate(self, isolation, snapshot, canonical, t_enq):
        entered.set()
        while not release.is_set():
            if cooperative and self._stop.is_set():
                return
            time.sleep(0.01)

    monkeypatch.setattr(ns.ShadowObserver, "_evaluate", evaluate)
    return entered, release


def test_start_and_shutdown_join_the_thread_and_are_idempotent():
    obs = ns.ShadowObserver("stage1").start()
    assert obs.state == ns.RUNNING and len(_shadow_threads()) == 1
    with pytest.raises(RuntimeError, match="NOT_STARTABLE"):
        obs.start()
    obs.shutdown(5)
    assert obs.state == ns.STOPPED and _shadow_threads() == []
    obs.shutdown(5)                                           # idempotent
    assert obs.state == ns.STOPPED
    obs.observe(obs.snapshot(len, ((1,),), {}), ((1,),), {}, value=1)
    assert obs.stats()["rejected_not_running"] == 1           # a stopped observer accepts nothing


def test_shutdown_cancels_queued_work(monkeypatch):
    entered, _release = _blocking_evaluate(monkeypatch, cooperative=True)
    obs = ns.ShadowObserver("stage1", max_pending=4).start()
    snap = obs.snapshot(len, ((1, 2),), {})
    for _ in range(3):
        obs.observe(snap, ((1, 2),), {}, value=2)
    assert entered.wait(5)
    obs.shutdown(5)
    stats = obs.stats()
    assert obs.state == ns.STOPPED and stats["inflight"] == 0
    assert stats["enqueued"] == 3 and stats["cancelled_shutdown"] == 2


def test_shutdown_kills_and_reaps_an_inflight_candidate_worker():
    obs = ns.ShadowObserver("stage1", timeout_seconds=600).start()
    snap = obs.snapshot(sleep_for, (600.0,), {})
    obs.observe(snap, (600.0,), {}, value=600.0)
    deadline = time.monotonic() + 60
    while obs._worker_proc is None and time.monotonic() < deadline:
        time.sleep(0.05)
    proc = obs._worker_proc
    assert proc is not None and proc.is_alive()
    started = time.monotonic()
    obs.shutdown(30)
    assert time.monotonic() - started < 15
    assert obs.state == ns.STOPPED and not proc.is_alive() and proc not in _children()
    (record,) = obs.records()
    assert record["outcome"] == "CANDIDATE_CANCELLED"


def test_mode_change_replaces_only_after_complete_shutdown_and_off_stops(monkeypatch):
    ex = ModelExecutor(ModelExecutionConfig(mode="thread", concurrency=1))
    try:
        monkeypatch.setenv(ns.ENV_SHADOW, "stage1")
        assert asyncio.run(ex.run_process(len, (1, 2, 3))) == 3
        first = ex.native_shadow_observer()
        assert first.mode == "stage1" and first.state == ns.RUNNING
        monkeypatch.setenv(ns.ENV_SHADOW, "stage2")
        assert asyncio.run(ex.run_process(len, (1, 2))) == 2
        second = ex.native_shadow_observer()
        assert second is not first and second.mode == "stage2"
        assert first.state == ns.STOPPED and len(_shadow_threads()) == 1
        monkeypatch.delenv(ns.ENV_SHADOW)
        assert asyncio.run(ex.run_process(len, (1,))) == 1
        assert ex.native_shadow_observer() is None and second.state == ns.STOPPED
        assert _shadow_threads() == []
    finally:
        assert ex.shutdown_and_join() == []


def test_incomplete_shutdown_fails_closed_and_is_visible(monkeypatch):
    entered, release = _blocking_evaluate(monkeypatch, cooperative=False)
    monkeypatch.setattr(me, "NATIVE_SHADOW_SHUTDOWN_TIMEOUT_SECONDS", 0.3)
    ex = ModelExecutor(ModelExecutionConfig(mode="thread", concurrency=1))
    try:
        monkeypatch.setenv(ns.ENV_SHADOW, "stage1")
        assert asyncio.run(ex.run_process(len, (1, 2))) == 2
        stuck = ex.native_shadow_observer()
        assert entered.wait(5)
        monkeypatch.setenv(ns.ENV_SHADOW, "stage2")                  # replacement requested
        assert asyncio.run(ex.run_process(len, (1, 2, 3))) == 3      # canonical service unaffected
        assert ex.native_shadow_observer() is None                   # no replacement while it survives
        assert stuck.state == ns.SHUTDOWN_INCOMPLETE
        shadow = ex.stats()["native_shadow"]
        assert shadow["retired"] == 1 and "shutdown incomplete" in shadow["disabled_reason"]
        assert asyncio.run(ex.run_process(len, (1,))) == 1
        assert ex.native_shadow_observer() is None                   # stays disabled (fail closed)
        with pytest.raises(ns.ShadowShutdownIncomplete):
            ex.shutdown_native_shadow(0.2)
        release.set()
        ex.shutdown_native_shadow(5)                                 # the survivor ended: now complete
        assert stuck.state == ns.STOPPED and ex.stats()["native_shadow"]["retired"] == 0
    finally:
        release.set()
        assert ex.shutdown_and_join() == []


def test_executor_shutdown_reports_a_surviving_observer_as_straggler(monkeypatch):
    entered, release = _blocking_evaluate(monkeypatch, cooperative=False)
    ex = ModelExecutor(ModelExecutionConfig(mode="thread", concurrency=1))
    monkeypatch.setenv(ns.ENV_SHADOW, "stage1")
    try:
        assert asyncio.run(ex.run_process(len, (1, 2))) == 2
        assert entered.wait(5)
        monkeypatch.setattr(ex, "shutdown_native_shadow", lambda timeout=0: ex._shadow_observer.shutdown(0.2))
        stragglers = ex.shutdown_and_join(timeout=1)
        assert any(s.startswith("native shadow:") for s in stragglers)
    finally:
        release.set()
        obs = ex._shadow_observer
        if obs is not None:
            obs.shutdown(5)


def test_repeated_application_lifespans_leave_no_observer(monkeypatch):
    from fastapi.testclient import TestClient

    try:
        import main_web
    except ImportError as exc:   # pre-existing on main: the web app needs Python >= 3.11 (enum.StrEnum)
        pytest.skip(f"web application not importable on this interpreter: {exc}")

    previous = me.reset_model_executor_for_tests(ModelExecutor(ModelExecutionConfig(mode="thread", concurrency=1)))
    assert previous == []
    monkeypatch.setenv(ns.ENV_SHADOW, "stage1")
    try:
        for _ in range(2):
            with TestClient(main_web.app):
                ex = me.get_model_executor()
                assert asyncio.run(ex.run_process(len, (1, 2))) == 2
                assert ex.native_shadow_observer() is not None and len(_shadow_threads()) == 1
            assert ex.native_shadow_observer() is None and _shadow_threads() == []
    finally:
        assert me.reset_model_executor_for_tests(None) == []


def test_executor_shutdown_leaves_no_thread_or_child_process(monkeypatch):
    monkeypatch.setenv(ns.ENV_SHADOW, "stage1")
    ex = ModelExecutor(ModelExecutionConfig(mode="thread", concurrency=1))
    asyncio.run(ex.run_process(len, (1,)))
    obs = ex.native_shadow_observer()
    assert ex.shutdown_and_join() == []
    assert obs.state == ns.STOPPED and _shadow_threads() == []
    assert not [p for p in _children() if p.name.startswith("SpawnProcess")]
