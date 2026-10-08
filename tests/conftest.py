"""Suite-wide test configuration.

The model executor defaults to worker PROCESSES in production (see app/runtime/model_execution.py).
Most existing tests replace engine functions in-process with ``mock.patch``; a spawned worker
would not see those patches. The suite therefore defaults to the executor's THREAD mode, which
keeps the same admission gate and typed BUSY behaviour. The process-mode tests
(tests/test_p0a_model_execution.py) select process mode explicitly.
"""
import os

os.environ.setdefault("FINCO_MODEL_EXECUTION_MODE", "thread")


# ── Suite-owned executor / process lifecycle ────────────────────────────────────────────
# One authority for model-worker cleanup (replaces per-module reset fixtures as the safety
# net): after every test MODULE the global ModelExecutor is shut down and its workers are
# JOINED (not merely asked to stop), and at session end any model worker process still alive
# fails the session with its identity.  A leaked worker process otherwise lets pytest print
# its summary and then block interpreter exit in concurrent.futures' exit handlers.
import multiprocessing
import sys
import threading
import time

import pytest

_LIFECYCLE_PROBLEMS: list[str] = []


@pytest.fixture(scope="module", autouse=True)
def _suite_model_executor_lifecycle(request):
    yield
    from app.runtime import model_execution as me

    forced = me.reset_model_executor_for_tests(None)
    if forced:
        _LIFECYCLE_PROBLEMS.append(
            f"{request.module.__name__}: model workers did not end on their own: {', '.join(forced)}")


def _thread_stacks(thread_ids) -> str:
    frames = sys._current_frames()
    import traceback

    out = []
    for t in threading.enumerate():
        if t.ident in thread_ids and t.ident in frames:
            out.append(f"--- {t.name!r} (daemon={t.daemon})\n" + "".join(traceback.format_stack(frames[t.ident])))
    return "\n".join(out)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """Lifecycle acceptance: no leaked model worker processes / executor threads."""
    from app.runtime import model_execution as me

    forced = me.reset_model_executor_for_tests(None)
    if forced:
        _LIFECYCLE_PROBLEMS.append(f"session end: model workers did not end on their own: {', '.join(forced)}")
    # workers of a pool that was deliberately discarded (e.g. a broken-pool test) are asked
    # to stop asynchronously: give them a bounded moment before calling them leaked.
    settle = time.monotonic() + 15.0
    while time.monotonic() < settle and [p for p in multiprocessing.active_children() if p.is_alive()]:
        time.sleep(0.1)
    children = [p for p in multiprocessing.active_children() if p.is_alive()]
    if children:
        _LIFECYCLE_PROBLEMS.append(
            "child processes still alive at session end: "
            + ", ".join(f"pid={p.pid} name={p.name}" for p in children))
    model_threads = [t for t in threading.enumerate() if t.name.startswith("finco-model") and t.is_alive()]
    if model_threads:
        _LIFECYCLE_PROBLEMS.append(
            "finco-model executor threads still alive at session end:\n"
            + _thread_stacks({t.ident for t in model_threads}))
    if _LIFECYCLE_PROBLEMS:
        sys.stderr.write("\nSUITE LIFECYCLE VIOLATION (would block interpreter exit):\n  "
                         + "\n  ".join(_LIFECYCLE_PROBLEMS) + "\n")
        sys.stderr.flush()
        if session.exitstatus == 0:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
