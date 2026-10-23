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
