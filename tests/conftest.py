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
import re
import sys
import threading
import time

import pytest

_LIFECYCLE_PROBLEMS: list[str] = []

# V10 native candidate: one session-scoped, provenance-checked artifact install (see the module docstring)
from tests.native_v10_support import native_artifacts  # noqa: E402,F401
# V11 Stage 3 candidate: same rule, its own artifact and manifest
from tests.native_v11_support import stage3_artifacts  # noqa: E402,F401


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
    # V10 shadow observer threads are owned by the executor and joined by its shutdown: none may survive
    model_threads = [t for t in threading.enumerate()
                     if t.name.startswith(("finco-model", "finco-native-shadow")) and t.is_alive()]
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


def _close_owned_acquisition_services(owned):
    """Close only fixture-owned services and join their actual pool threads."""
    deadline = time.monotonic() + 5
    problems = []
    for service, pool in owned:
        try:
            service.close()
            if pool is not None:
                pool.shutdown(wait=False)  # drain admitted work; never cancel it
        except Exception as error:
            problems.append(f"service shutdown: {type(error).__name__}: {error}")
    for _, pool in owned:
        for thread in list(pool._threads) if pool is not None else []:
            thread.join(max(0, deadline - time.monotonic()))
            if thread.is_alive():
                problems.append(f"provider work did not stop: {thread.name}")
    assert not problems, "\n".join(problems)


@pytest.fixture(scope="module", autouse=True)
def _suite_acquisition_service_lifecycle():
    # Test modules construct offline AcquisitionServices, sometimes retain them
    # in clients/tracebacks and often omit their executor shutdown. Own those
    # instances until module teardown, independently of worker partition order.
    module = sys.modules.get("app.radar_runtime.service")
    if module is None:
        yield
        return
    service_class = module.AcquisitionService
    original = service_class.__init__
    owned = []
    from functools import wraps

    @wraps(original)
    def construct(service, *args, **kwargs):
        original(service, *args, **kwargs)
        owned.append((service, service._provider_pool))

    patch = pytest.MonkeyPatch()
    patch.setattr(service_class, "__init__", construct)
    try:
        yield
    finally:
        try:
            _close_owned_acquisition_services(owned)
        finally:
            router = sys.modules.get("app.radar_ui.router")
            if router is not None and any(router._service_instance is service for service, _ in owned):
                router.set_service(None)
            patch.undo()


# ── Model CI: a missing dependency is a failure, never a silent skip ────────────────────────────────────────────────────
# With FINCO_CI_STRICT_SKIPS=1 (set by .github/workflows/model_ci.yml) a test or module skipped because a Python
# package, Playwright/Chromium or axe-core is absent fails instead (optional external tools such as LibreOffice stay
# visible SKIPPED). Ordinary, intentional skips (documented reasons) are unaffected and are
# still reported as SKIPPED, never as passed.
_MISSING_DEPENDENCY = re.compile(
    r"could not import|no module named|playwright|chromium|executable doesn't exist|axe-core|FINCO_AXE_CORE_PATH",
    re.IGNORECASE,
)


def _strict_skips() -> bool:
    return os.environ.get("FINCO_CI_STRICT_SKIPS") == "1"


def _skip_reason(report) -> str:
    longrepr = getattr(report, "longrepr", None)
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2])
    return str(longrepr or "")


def _fail_missing_dependency(report) -> None:
    reason = _skip_reason(report)
    if _MISSING_DEPENDENCY.search(reason):
        report.outcome = "failed"
        report.longrepr = "MISSING_DEPENDENCY (strict CI skips): %s" % reason


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if _strict_skips() and report.skipped and not hasattr(report, "wasxfail"):
        _fail_missing_dependency(report)


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    outcome = yield
    report = outcome.get_result()
    if _strict_skips() and report.skipped:
        _fail_missing_dependency(report)


# ── Model CI: per-group collection accounting (FINCO_CI_COUNTS=<path>) ─────────────────────────────────────────────────
# The aggregate job checks that every group saw the same full collection and that the groups' selections add up to it
# (minus the explicitly listed known defects), so no test can silently fall between groups.
_CI_COUNTS = {}


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(session, config, items):
    if os.environ.get("FINCO_CI_COUNTS"):
        import hashlib
        ids = sorted(item.nodeid for item in items)
        _CI_COUNTS.update(collected=len(ids), collected_digest=hashlib.sha256("\n".join(ids).encode()).hexdigest())


def pytest_collection_finish(session):
    path = os.environ.get("FINCO_CI_COUNTS")
    if path:
        import json
        _CI_COUNTS["selected"] = sorted(item.nodeid for item in session.items)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(_CI_COUNTS, handle)
