"""Opt-in V8-A worker timing must never escape into canonical model results."""
from __future__ import annotations

import time
from concurrent.futures import Future

import pytest

from app.runtime import model_execution as execution


def _multiply(value):
    return value * 3


def _raise_worker_failure():
    raise ValueError("synthetic failure")


def test_disabled_worker_returns_unwrapped_original_value():
    assert execution._process_entry(_multiply, (7,), {}) == 21
    assert execution._unwrap(21) == 21


def test_opt_in_worker_result_preserves_return_value_and_gathers_timings():
    item = execution._process_entry(_multiply, (7,), {}, True)
    assert isinstance(item, execution._ProfiledWorkerResult)
    assert item.worker_finished_ns >= item.worker_started_ns
    assert execution._unwrap(item) == 21


def test_opt_in_worker_error_preserves_model_worker_error():
    item = execution._process_entry(_raise_worker_failure, (), {}, True)
    assert isinstance(item, execution._ProfiledWorkerResult)
    with pytest.raises(execution.ModelWorkerError) as captured:
        execution._unwrap(item)
    assert captured.value.error_type == "ValueError"


def test_opt_in_profile_records_only_duration_and_releases_slot(monkeypatch):
    monkeypatch.setenv(execution.ENV_PROFILE, "1")
    executor = execution.ModelExecutor(
        execution.ModelExecutionConfig(concurrency=1, mode="process", timeout_seconds=30)
    )
    executor._admit()
    submitted = time.monotonic_ns()
    payload = execution._process_entry(_multiply, (2,), {}, True)
    finished = time.monotonic_ns()
    future = Future()
    future.set_result(payload)
    executor._finish(time.monotonic(), future, submitted_ns=submitted, dispatched_ns=submitted)
    assert executor.stats()["active"] == 0
    assert executor.stats()["completed"] == 1
    assert execution._unwrap(future.result()) == 6
    evidence = executor.profile_snapshot()
    assert evidence["enabled"] is True
    assert evidence["http_response_overhead_measured"] is False
    assert len(evidence["samples"]) == 1
    sample = evidence["samples"][0]
    assert sample["worker_execution_ms"] is not None
    assert sample["submission_to_result_ms"] >= 0
    assert not any(k in sample for k in ("project_id", "user_id", "run_id", "inputs", "results"))


def test_profile_off_has_no_envelope_or_timing_records(monkeypatch):
    monkeypatch.delenv(execution.ENV_PROFILE, raising=False)
    executor = execution.ModelExecutor(
        execution.ModelExecutionConfig(concurrency=1, mode="thread", timeout_seconds=30)
    )
    assert executor.profile_snapshot()["enabled"] is False
    assert executor.profile_snapshot()["samples"] == []


def test_real_process_mode_opt_in_returns_same_original_value(monkeypatch):
    monkeypatch.setenv(execution.ENV_PROFILE, "1")
    executor = execution.ModelExecutor(
        execution.ModelExecutionConfig(concurrency=1, mode="process", timeout_seconds=90)
    )
    try:
        assert executor.run_process_sync(_multiply, 7) == 21
        # Completion callback may run immediately after future.result returns.
        for _ in range(30):
            if executor.profile_snapshot()["samples"]:
                break
            time.sleep(0.02)
        sample = executor.profile_snapshot()["samples"]
        assert len(sample) == 1
        assert sample[0]["worker_execution_ms"] >= 0
        assert sample[0]["dispatch_ms"] >= 0
    finally:
        executor.shutdown_and_join(timeout=20)
