"""Bounded, opt-in execution of unchanged financial calls, never a result cache."""
from __future__ import annotations

import atexit
from concurrent.futures import ProcessPoolExecutor
from contextvars import ContextVar
from functools import wraps
import hashlib
import importlib.metadata
import math
import multiprocessing
from multiprocessing.util import Finalize
import os
from pathlib import Path, PurePosixPath
import pickle
import platform
import sys
import threading
import time


_ROOT = Path(__file__).resolve().parents[2]
_SESSION = ContextVar("finco_speculative_g2a", default=None)
_LOCK = threading.Lock()
_POOL = None
_FINALIZER = None
_WORKER_IDENTITY = None
_PARENT_IDENTITY = None
_REPLAY = object()


def source_identity():
    """Execution identity, not financial approval or an exact-content release pin."""
    digest = hashlib.sha256()
    for package in ("financial_engine", "finco_core", "domain", "app"):
        paths = sorted((_ROOT / package).rglob("*.py"))
        if not paths:
            raise FileNotFoundError("G2A_HELPER_SOURCE_EVIDENCE_MISSING")
        for path in paths:
            digest.update(path.relative_to(_ROOT).as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    for required in ("financial_engine/financing/project.py",
                     "financial_engine/financing/speculative.py",
                     "financial_engine/orchestrator.py", "finco_core/inputs/_models.py"):
        if not (_ROOT / required).is_file():
            raise FileNotFoundError("G2A_HELPER_SOURCE_EVIDENCE_MISSING")
    for path in sorted(_ROOT.glob("requirements*.txt")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    versions = sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions())
    numeric_env = tuple((key, os.environ.get(key)) for key in (
        "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS", "PYTHONHASHSEED"))
    return (digest.hexdigest(), sys.version, platform.machine(), tuple(versions), numeric_env)


def effective_cpus():
    count = os.cpu_count() or 1
    if hasattr(os, "sched_getaffinity"):
        count = min(count, len(os.sched_getaffinity(0)))
    if sys.platform == "linux":
        try:
            entries = Path("/proc/self/cgroup").read_text().splitlines()
        except OSError:
            return 1
        directories = set()
        for entry in entries:
            try:
                _, controllers, relative = entry.split(":", 2)
                parts = PurePosixPath(relative).parts[1:]
                if ".." in parts:
                    return 1
                roots = ((Path("/sys/fs/cgroup"), True),) if not controllers else (
                    ((Path("/sys/fs/cgroup/cpu"), False),
                     (Path("/sys/fs/cgroup/cpu,cpuacct"), False))
                    if "cpu" in controllers.split(",") else ())
                for root, v2 in roots:
                    current = root.joinpath(*parts)
                    while True:
                        directories.add((current, v2))
                        if current == root:
                            break
                        current = current.parent
            except ValueError:
                return 1
        known = False
        for directory, v2 in directories:
            try:
                if v2:
                    quota, period = (directory / "cpu.max").read_text().split()
                else:
                    quota = (directory / "cpu.cfs_quota_us").read_text()
                    period = (directory / "cpu.cfs_period_us").read_text()
                denominator = int(period)
                if denominator <= 0:
                    return 1
                if quota.strip() == "max":
                    known = True
                else:
                    numerator = int(quota)
                    if numerator > 0:
                        count = min(count, max(1, numerator // denominator))
                        known = True
                    elif numerator == -1 and not v2:
                        known = True
                    else:
                        return 1
            except FileNotFoundError:
                continue
            except (OSError, ValueError):
                return 1
        if not known:
            return 1
    return count


def configured_workers():
    try:
        requested = int(os.environ.get("FINCO_G2A_WORKERS", "0"))
        if requested == 0:
            return 0
        web = int(os.environ.get("FINCO_WEB_WORKERS", "2"))
        runs = int(os.environ.get("FINCO_MODEL_EXECUTION_CONCURRENCY", "2"))
        if requested not in (0, 1, 2, 3) or web < 1 or runs < 1:
            return 0
        if multiprocessing.current_process().daemon:
            return 0
        # Conservatively reserve a parent CPU as well as every helper, across
        # all configured web/Run workers; never infer a host-global admission slot.
        return min(requested, max(0, effective_cpus() // (web * runs) - 1))
    except (OSError, ValueError):
        return 0


def _watch_parent(sentinel):
    from multiprocessing.connection import wait
    wait([sentinel])
    # The owning Run worker died (including forced termination). Do not leave
    # an orphan helper alive waiting for work from a dead executor manager.
    os._exit(71)


def _worker_init(owner_pid):
    global _WORKER_IDENTITY
    parent = multiprocessing.parent_process()
    if parent is None or parent.pid != owner_pid:
        raise RuntimeError("G2A_HELPER_PARENT_IDENTITY_MISMATCH")
    threading.Thread(target=_watch_parent, args=(parent.sentinel,),
                     name="g2a-parent-watch", daemon=True).start()
    from financial_engine.orchestrator import run_senior_debt_model  # noqa: F401
    _WORKER_IDENTITY = source_identity()


def _peak_memory():
    if sys.platform != "win32":
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ("peak", "working", "paged_peak", "paged",
                "nonpaged_peak", "nonpaged", "pagefile", "pagefile_peak")]
    value = Counters()
    value.cb = ctypes.sizeof(value)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    query = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
    query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    if not query(kernel.GetCurrentProcess(), ctypes.byref(value), value.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(value.peak)


def _worker_call(fn, snapshot, expected_identity):
    # Exceptions never cross the process boundary as financial decisions.
    if _WORKER_IDENTITY != expected_identity:
        return (False, None, _WORKER_IDENTITY, {})
    cpu, wall = time.process_time(), time.perf_counter()
    accepted, result = False, None
    try:
        from financial_engine.run_scope import engine_run_scope
        with engine_run_scope():
            result = fn(pickle.loads(snapshot))
        accepted = True
    except BaseException:
        pass
    metrics = {"cpu_s": time.process_time() - cpu, "wall_s": time.perf_counter() - wall,
               "pid": os.getpid(), "peak_bytes": _peak_memory(),
               "process_cpu_total_s": time.process_time()}
    return (accepted, result, _WORKER_IDENTITY, metrics)


class SpeculativePool:
    """One process owner's helpers; no user, input or result retained between batches."""

    def __init__(self, workers, identity, timeout):
        self.workers, self.identity, self.timeout = workers, identity, timeout
        self.executor = ProcessPoolExecutor(max_workers=workers,
            mp_context=multiprocessing.get_context("spawn"), initializer=_worker_init,
            initargs=(os.getpid(),))
        self.broken = False
        self.last_failure = None
        self.metrics = {"submitted": 0, "accepted": 0, "replayed": 0,
                        "worker_cpu_s": 0., "worker_wall_s": 0., "worker_peak_bytes": {},
                        "worker_process_cpu_total_s": {}}

    def submit(self, fn, model_input):
        if self.broken:
            return None
        try:
            snapshot = pickle.dumps(model_input, protocol=5)
            future = self.executor.submit(_worker_call, fn, snapshot, self.identity)
            self.metrics["submitted"] += 1
            return future
        except Exception as error:
            self.last_failure = type(error).__name__
            self.abort()
            return None

    def outcome(self, future):
        if future is None or self.broken:
            return _REPLAY
        try:
            accepted, result, identity, metrics = future.result(timeout=self.timeout)
            if identity != self.identity:
                self.last_failure = "SOURCE_IDENTITY_MISMATCH"
                self.abort()
                return _REPLAY
            self.metrics["worker_cpu_s"] += metrics["cpu_s"]
            self.metrics["worker_wall_s"] += metrics["wall_s"]
            self.metrics["worker_peak_bytes"][metrics["pid"]] = metrics["peak_bytes"]
            self.metrics["worker_process_cpu_total_s"][metrics["pid"]] = metrics["process_cpu_total_s"]
            if accepted is True and identity == self.identity:
                self.metrics["accepted"] += 1
                return result
        except Exception as error:
            self.last_failure = type(error).__name__
            self.abort()
        return _REPLAY

    def result_or_replay(self, future, fn, model_input):
        try:
            result = self.outcome(future)
        except BaseException:
            self.abort()
            raise
        # Outside the worker exception handler: preserve the native cause chain.
        if result is _REPLAY:
            self.metrics["replayed"] += 1
            return fn(model_input)
        return result

    def discard(self, future):
        if future is not None and not future.cancel():
            self.outcome(future)

    def abort(self):
        if self.broken:
            return
        self.broken = True
        # Python 3.12 has no public terminate_workers API. Match the existing
        # application executor's bounded process cleanup, never kill Run workers.
        children = list(getattr(self.executor, "_processes", {}).values())
        for process in children:
            if process.is_alive():
                process.terminate()
        for process in children:
            process.join(5)
            if process.is_alive():
                process.kill()
                process.join(5)
        self.executor.shutdown(wait=True, cancel_futures=True)

    def shutdown(self):
        if not self.broken:
            self.executor.shutdown(wait=True, cancel_futures=True)
            self.broken = True


def shutdown_helpers():
    global _POOL
    pool, _POOL = _POOL, None
    if pool is not None:
        pool.shutdown()


def _acquire_pool(workers, timeout):
    global _POOL, _FINALIZER, _PARENT_IDENTITY
    if _PARENT_IDENTITY is None:
        _PARENT_IDENTITY = source_identity()
    # Source is immutable for an executor owner's lifetime. Replacement requires
    # restarting the Run worker, exactly as the existing application's import graph.
    # Each newly spawned helper independently fingerprints the complete source tree.
    identity = _PARENT_IDENTITY
    if (_POOL is None or _POOL.broken or _POOL.workers != workers
            or _POOL.identity != identity or _POOL.timeout != timeout):
        shutdown_helpers()
        _POOL = SpeculativePool(workers, identity, timeout)
        if _FINALIZER is None:
            # ProcessPool Run workers do not run normal interpreter atexit hooks.
            # Close helpers BEFORE multiprocessing's automatic child-join phase.
            _FINALIZER = Finalize(None, shutdown_helpers, exitpriority=20)
    return _POOL


class _Batch:
    def __init__(self, session, capacity, funded_builder, strict_builder, solver):
        self.session, self.solver = session, solver
        self.future = {}
        self.funded_builder = funded_builder
        self.funded_input = _REPLAY
        self.funded_error = None
        self.strict_builder = strict_builder
        self.strict_value = _REPLAY
        self.strict_error = None
        if session is None:
            return
        self.future["capacity"] = session.pool.submit(solver, capacity)
        try:
            self.funded_input = funded_builder()
        except Exception as error:
            # Its canonical position is AFTER the capacity verdict.
            self.funded_error = error
            return
        self.future["funded"] = session.pool.submit(solver, self.funded_input)
        if session.strict_seen and session.pool.workers >= 3:
            try:
                self.strict_value = strict_builder(self.funded_input)
            except Exception as error:
                self.strict_error = error
                return
            self.future["strict"] = session.pool.submit(solver, self.strict_value)

    def solve(self, role, model_input):
        if self.session is None:
            return self.solver(model_input)
        future = self.future.pop(role, None)
        return self.session.pool.result_or_replay(future, self.solver, model_input)

    def funded(self):
        if self.funded_error is not None:
            raise self.funded_error
        if self.funded_input is _REPLAY:
            return self.funded_builder()
        return self.funded_input

    def strict_input(self, funded):
        if self.strict_error is not None:
            raise self.strict_error
        if self.strict_value is not _REPLAY:
            return self.strict_value
        return self.strict_builder(funded)

    def strict(self):
        if self.session is not None:
            self.session.strict_seen = True

    def close(self):
        if self.session is not None:
            for future in self.future.values():
                self.session.pool.discard(future)
        self.future.clear()
        self.funded_input = _REPLAY
        self.funded_builder = None
        self.funded_error = None
        self.strict_value = _REPLAY
        self.strict_builder = None
        self.strict_error = None


class _Session:
    def __init__(self, pool):
        self.pool, self.batch, self.strict_seen = pool, None, False

    def close(self):
        if self.batch is not None:
            self.batch.close()
        self.batch = None


def begin_iteration(capacity, funded_builder, strict_builder, solver):
    session = _SESSION.get()
    if session is not None:
        session.close()
        # Instrumented/replaced financial calls must execute in their original
        # process, not silently bypass the caller's execution dependency.
        from financial_engine.orchestrator import run_senior_debt_model
        if solver is not run_senior_debt_model:
            session = None
    try:
        batch = _Batch(session, capacity, funded_builder, strict_builder, solver)
    except BaseException:
        if session is not None:
            session.pool.abort()
        raise
    if session is not None:
        session.batch = batch
    return batch


def financing_execution_scope(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        workers = configured_workers()
        if not workers or _SESSION.get() is not None:
            return fn(*args, **kwargs)
        if not _LOCK.acquire(blocking=False):
            return fn(*args, **kwargs)
        session = token = None
        try:
            try:
                timeout = float(os.environ.get("FINCO_G2A_TASK_TIMEOUT_SECONDS", "30"))
                if not math.isfinite(timeout) or not 0 < timeout <= 180:
                    raise ValueError("G2A_HELPER_TIMEOUT_CONFIG_INVALID")
                session = _Session(_acquire_pool(workers, timeout))
                token = _SESSION.set(session)
            except Exception:
                # Executor/source/OS failure is operational, never a financial refusal.
                session = None
            return fn(*args, **kwargs)
        finally:
            try:
                if session is not None:
                    session.close()
            finally:
                if token is not None:
                    _SESSION.reset(token)
                _LOCK.release()
    return wrapped


atexit.register(shutdown_helpers)
