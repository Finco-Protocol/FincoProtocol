"""Containment of the candidate worker (V10-04): a native crash, a hang and memory exhaustion end only the
spawned, resource-limited worker; the evidence names the failure, the worker is always reaped and the
caller's (canonical) process is unaffected."""
from __future__ import annotations

import multiprocessing
import os
import time

from financial_engine.native_v10 import isolation


def _alive_children():
    return [p for p in multiprocessing.active_children() if p.is_alive()]


def test_native_crash_is_contained():
    ev = isolation.run_in_worker("tests.native_v10_support.crash_task", {})
    assert ev.status == "CANDIDATE_CRASH" and ev.exitcode not in (0, None) and ev.reaped
    assert _alive_children() == []


def test_hang_is_killed_at_the_wall_timeout():
    started = time.monotonic()
    ev = isolation.run_in_worker("tests.native_v10_support.sleep_for", {"seconds": 600.0},
                                 limits=isolation.WorkerLimits(timeout_seconds=1.0))
    assert ev.status == "CANDIDATE_TIMEOUT" and ev.reaped
    assert time.monotonic() - started < 30
    assert _alive_children() == []


def test_memory_limit_is_contained():
    ev = isolation.run_in_worker("tests.native_v10_support.allocate_task", {"gib": 4},
                                 limits=isolation.WorkerLimits(address_space_bytes=2 * 1024 ** 3))
    assert ev.status == "CANDIDATE_EXCEPTION" and "MemoryError" in (ev.error or "") and ev.reaped
    assert _alive_children() == []


def test_cooperative_cancel_kills_the_worker():
    import threading

    cancel = threading.Event()
    seen = []
    timer = threading.Timer(0.5, cancel.set)
    timer.start()
    ev = isolation.run_in_worker("tests.native_v10_support.sleep_for", {"seconds": 600.0}, cancel=cancel,
                                 on_process=seen.append)
    timer.join()
    assert ev.status == "CANDIDATE_CANCELLED" and ev.reaped
    assert seen[0] is not None and seen[-1] is None and not seen[0].is_alive()
    assert _alive_children() == []


def test_a_task_result_that_is_not_evidence_is_reported_never_raised():
    pid = os.getpid()
    ev = isolation.run_in_worker("tests.native_v10_support.sleep_for", {"seconds": 0.0})   # returns a float
    assert ev.status == "CANDIDATE_EXCEPTION" and ev.error == "CANDIDATE_RESULT_NOT_EVIDENCE: float"
    assert os.getpid() == pid and ev.reaped and _alive_children() == []


def test_resource_limit_setup_failure_never_runs_the_candidate(tmp_path):
    """Fail closed: when the mandatory RLIMITs cannot be installed the task body never executes."""
    from tests.native_v10_support import FailingLimits

    marker = tmp_path / "ran"
    ev = isolation.run_in_worker("tests.native_v10_support.touch_task", {"path": str(marker)},
                                 limits=FailingLimits(timeout_seconds=60))
    assert ev.status == "CANDIDATE_LIMITS_FAILED" and "setrlimit refused" in (ev.error or "")
    assert not marker.exists() and ev.reaped and _alive_children() == []


def test_default_limits_are_installed_and_verified(tmp_path):
    marker = tmp_path / "ran"
    ev = isolation.run_in_worker("tests.native_v10_support.touch_task", {"path": str(marker)})
    assert ev.status == "OK" and marker.exists() and ev.reaped


def test_limits_apply_verifies_by_read_back(monkeypatch):
    import resource

    monkeypatch.setattr(resource, "setrlimit", lambda *_a: None)            # refused silently
    monkeypatch.setattr(resource, "getrlimit", lambda *_a: (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    import pytest
    with pytest.raises(OSError, match="not in effect"):
        isolation.WorkerLimits().apply()


def test_injected_setrlimit_failure_in_the_real_apply_never_runs_the_candidate(tmp_path):
    """The real ``WorkerLimits.apply`` with ``setrlimit`` refused in the worker: explicit evidence, no task execution, reaped."""
    from tests.native_v10_support import SetrlimitRefusedLimits

    marker = tmp_path / "ran"
    pid = os.getpid()
    ev = isolation.run_in_worker("tests.native_v10_support.touch_task", {"path": str(marker)},
                                 limits=SetrlimitRefusedLimits(timeout_seconds=60))
    assert ev.status == "CANDIDATE_LIMITS_FAILED" and "setrlimit refused (injected)" in (ev.error or "")
    assert ev.verdict is None and ev.digests == {} and not marker.exists()
    assert os.getpid() == pid and ev.reaped and _alive_children() == []
