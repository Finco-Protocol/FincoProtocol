"""Suite lifecycle acceptance: model executor pools must be JOINED, not just asked to stop.

A leaked worker lets pytest print its summary and then block interpreter exit.
"""
from __future__ import annotations

import threading
import time

import pytest

from app.runtime import model_execution as me
from app.runtime.model_execution import ModelExecutionConfig, ModelExecutor


def _add(a, b):
    return a + b


def _sleep_long():
    time.sleep(120)


def _install(mode):
    ex = ModelExecutor(ModelExecutionConfig(2, mode, 60))
    me.reset_model_executor_for_tests(ex)
    return ex


@pytest.mark.parametrize("mode", ["thread", "process"])
def test_executor_reset_joins_all_workers(mode):
    ex = _install(mode)
    run = ex.run_process_sync if mode == "process" else None
    if mode == "process":
        assert run(_add, 2, 3) == 5
        own = list(ex._process_pool._processes.values())
        assert own and all(p.is_alive() for p in own)     # workers really exist
    else:
        ex._pool("thread").submit(_add, 1, 1).result(timeout=10)
        assert any(t.name.startswith("finco-model") for t in threading.enumerate())
    assert me.reset_model_executor_for_tests(None) == []   # ended on their own
    if mode == "process":
        assert not [p for p in own if p.is_alive()]         # THIS executor's workers are gone
    assert not [t for t in threading.enumerate() if t.name.startswith("finco-model") and t.is_alive()]


def test_busy_process_worker_is_reported_and_removed_not_left_to_block_exit():
    ex = _install("process")
    ex._pool("process").submit(me._process_entry, _sleep_long, (), {})
    time.sleep(1.0)                                         # worker is inside the long call
    own = list(ex._process_pool._processes.values())
    started = time.monotonic()
    stragglers = ex.shutdown_and_join(timeout=2.0)
    assert stragglers and stragglers[0].startswith("process pid=")
    assert time.monotonic() - started < 15
    assert not [p for p in own if p.is_alive()]
    me.reset_model_executor_for_tests(None)
