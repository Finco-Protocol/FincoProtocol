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
_IDENTITY_METRICS = {}
_PREWARM_EVIDENCE = None
_OWNER_RUN_CONCURRENCY = None
_STARTUP_DISABLED = None
_PURE_MEMO_NAMES = frozenset({
    "financial_engine.orchestrator.run_operating_model",
    "financial_engine.orchestrator.run_tax_cfads_model",
})


def source_identity():
    """Execution identity, not financial approval or an exact-content release pin."""
    global _IDENTITY_METRICS
    started, cpu = time.perf_counter(), time.process_time()
    digest = hashlib.sha256()
    prefix = _ROOT.as_posix() + "/"
    files = 0
    for package in ("financial_engine", "finco_core", "domain", "app"):
        paths = sorted((_ROOT / package).rglob("*.py"))
        if not paths:
            raise FileNotFoundError("G2A_HELPER_SOURCE_EVIDENCE_MISSING")
        for path in paths:
            name = path.as_posix()
            if not name.startswith(prefix):
                raise ValueError("G2A_HELPER_SOURCE_PATH_OUTSIDE_ROOT")
            digest.update(name[len(prefix):].encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
            files += 1
    for required in ("financial_engine/financing/project.py",
                     "financial_engine/financing/speculative.py",
                     "financial_engine/orchestrator.py", "finco_core/inputs/_models.py"):
        if not (_ROOT / required).is_file():
            raise FileNotFoundError("G2A_HELPER_SOURCE_EVIDENCE_MISSING")
    for path in sorted(_ROOT.glob("requirements*.txt")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    source_done = time.perf_counter()
    versions = []
    for distribution in importlib.metadata.distributions():
        metadata = distribution.metadata
        versions.append((metadata["Name"], metadata["Version"]))
    versions.sort()
    metadata_done = time.perf_counter()
    numeric_env = tuple((key, os.environ.get(key)) for key in (
        "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS", "PYTHONHASHSEED"))
    identity = (digest.hexdigest(), sys.version, platform.machine(), tuple(versions), numeric_env)
    _IDENTITY_METRICS = {"source_files": files, "distributions": len(versions),
        "source_hash_wall_s": source_done - started,
        "distribution_wall_s": metadata_done - source_done,
        "identity_wall_s": time.perf_counter() - started,
        "identity_cpu_s": time.process_time() - cpu}
    return identity


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
        runs = (_OWNER_RUN_CONCURRENCY if _OWNER_RUN_CONCURRENCY is not None else
                int(os.environ.get("FINCO_MODEL_EXECUTION_CONCURRENCY", "2")))
        if requested not in (0, 1, 2, 3) or web < 1 or runs < 1:
            return 0
        if multiprocessing.current_process().daemon:
            return 0
        # Conservatively reserve a parent CPU as well as every helper, across
        # all configured web/Run workers; never infer a host-global admission slot.
        if _STARTUP_DISABLED is not None:
            return 0
        return min(requested, max(0, (effective_cpus() - 1) // (web * runs) - 1))
    except (OSError, ValueError):
        return 0


def _watch_parent(sentinel):
    from multiprocessing.connection import wait
    wait([sentinel])
    # The owning Run worker died (including forced termination). Do not leave
    # an orphan helper alive waiting for work from a dead executor manager.
    os._exit(71)


def _worker_init(owner_pid, readiness=None, startup_at=None):
    global _WORKER_IDENTITY
    entered = time.perf_counter()
    parent = multiprocessing.parent_process()
    if parent is None or parent.pid != owner_pid:
        raise RuntimeError("G2A_HELPER_PARENT_IDENTITY_MISMATCH")
    threading.Thread(target=_watch_parent, args=(parent.sentinel,),
                     name="g2a-parent-watch", daemon=True).start()
    from financial_engine.orchestrator import run_senior_debt_model  # noqa: F401
    _WORKER_IDENTITY = source_identity()
    if readiness is not None:
        readiness.put({"pid": os.getpid(), "identity": _WORKER_IDENTITY,
            "bootstrap_and_import_wall_s": entered - startup_at,
            "ready_wall_s": time.perf_counter() - startup_at,
            "process_cpu_s": time.process_time(), "identity_metrics": _IDENTITY_METRICS})


def _ready_probe():
    return os.getpid()


def _memo_snapshot():
    from collections import OrderedDict
    from financial_engine.run_scope import current_run_scope
    scope = current_run_scope()
    if scope is None:
        return None
    selected = {}
    for name in _PURE_MEMO_NAMES:
        cache = scope.get(name)
        if isinstance(cache, OrderedDict) and cache:
            recent = list(cache)[-2:]
            selected[name] = OrderedDict((key, cache[key]) for key in recent)
    if not selected:
        return None
    try:
        snapshot = pickle.dumps(selected, protocol=5)
        return snapshot if len(snapshot) <= 65536 else None
    except Exception:
        return None


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


def _worker_call(fn, snapshot, expected_identity, memo_snapshot=None):
    # Exceptions never cross the process boundary as financial decisions.
    if _WORKER_IDENTITY != expected_identity:
        return (False, None, _WORKER_IDENTITY, {})
    cpu, wall = time.process_time(), time.perf_counter()
    accepted, result = False, None
    try:
        from financial_engine.run_scope import engine_run_scope, current_run_scope
        with engine_run_scope():
            if memo_snapshot is not None:
                seed = pickle.loads(memo_snapshot)
                if not isinstance(seed, dict) or not set(seed).issubset(_PURE_MEMO_NAMES):
                    raise ValueError("G2A_HELPER_MEMO_SCOPE_INVALID")
                current_run_scope().update(seed)
            result = fn(pickle.loads(snapshot))
        accepted = True
    except BaseException:
        pass
    metrics = {"cpu_s": time.process_time() - cpu, "wall_s": time.perf_counter() - wall,
               "pid": os.getpid(), "peak_bytes": _peak_memory(),
               "process_cpu_total_s": time.process_time(), "finished_at": time.perf_counter()}
    return (accepted, result, _WORKER_IDENTITY, metrics)


class SpeculativePool:
    """One process owner's helpers; no user, input or result retained between batches."""

    def __init__(self, workers, identity, timeout):
        self.workers, self.identity, self.timeout = workers, identity, timeout
        context = multiprocessing.get_context("spawn")
        self.readiness = context.Queue()
        self.startup_at = time.perf_counter()
        self.executor = ProcessPoolExecutor(max_workers=workers,
            mp_context=context, initializer=_worker_init,
            initargs=(os.getpid(), self.readiness, self.startup_at))
        self.ready = False
        self.startup = None
        self.broken = False
        self.last_failure = None
        self.metrics = {"submitted": 0, "accepted": 0, "replayed": 0,
                        "worker_cpu_s": 0., "worker_wall_s": 0., "worker_peak_bytes": {},
                        "worker_process_cpu_total_s": {}, "input_pickle_wall_s": 0.,
                        "input_bytes": 0, "memo_bytes": 0, "completed_transfer_wall_s": 0.,
                        "required_capacity": 0, "required_funded": 0, "required_strict": 0,
                        "speculative_strict": 0, "unused_strict": 0}

    def warm(self):
        if self.ready:
            return True
        if self.broken:
            return False
        started, cpu = time.perf_counter(), time.process_time()
        try:
            futures = [self.executor.submit(_ready_probe) for _ in range(self.workers)]
            deadline = started + self.timeout
            workers = {}
            while len(workers) < self.workers:
                value = self.readiness.get(timeout=max(.001, deadline - time.perf_counter()))
                if value["identity"] != self.identity:
                    raise RuntimeError("G2A_HELPER_SOURCE_IDENTITY_MISMATCH")
                workers[value["pid"]] = {k: v for k, v in value.items() if k != "identity"}
            for future in futures:
                future.result(timeout=max(.001, deadline - time.perf_counter()))
            self.ready = True
            self.startup = {"wall_s": time.perf_counter() - started,
                "parent_cpu_s": time.process_time() - cpu, "workers": workers,
                "parent_identity": dict(_IDENTITY_METRICS)}
            return True
        except Exception as error:
            self.last_failure = type(error).__name__
            self.abort()
            return False

    def submit(self, fn, model_input, memo_snapshot=None):
        if self.broken:
            return None
        try:
            if not self.warm():
                return None
            started = time.perf_counter()
            snapshot = pickle.dumps(model_input, protocol=5)
            self.metrics["input_pickle_wall_s"] += time.perf_counter() - started
            self.metrics["input_bytes"] += len(snapshot)
            self.metrics["memo_bytes"] += len(memo_snapshot or b"")
            future = self.executor.submit(_worker_call, fn, snapshot, self.identity, memo_snapshot)
            future.add_done_callback(lambda done: setattr(done, "_g2a_arrived", time.perf_counter()))
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
            self.metrics["completed_transfer_wall_s"] += max(0., getattr(
                future, "_g2a_arrived", time.perf_counter()) - metrics["finished_at"])
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
        self.readiness.close()
        self.readiness.cancel_join_thread()

    def shutdown(self):
        if not self.broken:
            self.executor.shutdown(wait=True, cancel_futures=True)
            self.broken = True
            self.readiness.close()
            self.readiness.cancel_join_thread()


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


def configure_run_owner(run_concurrency):
    global _OWNER_RUN_CONCURRENCY
    _OWNER_RUN_CONCURRENCY = run_concurrency


def prewarm_worker(run_concurrency=None):
    """Non-financial, opt-in readiness inside the existing spawned Run owner."""
    global _OWNER_RUN_CONCURRENCY, _PREWARM_EVIDENCE, _STARTUP_DISABLED
    if run_concurrency is not None:
        _OWNER_RUN_CONCURRENCY = run_concurrency
    if _STARTUP_DISABLED is not None:
        return _PREWARM_EVIDENCE
    workers = configured_workers()
    if workers < 2:
        _PREWARM_EVIDENCE = {"ready": False, "workers": 0, "reason": "SERIAL_RESOURCE_POLICY"}
        return _PREWARM_EVIDENCE
    if not _LOCK.acquire(blocking=False):
        return {"ready": False, "workers": 0, "reason": "OWNER_BUSY"}
    started, cpu = time.perf_counter(), time.process_time()
    try:
        timeout = float(os.environ.get("FINCO_G2A_TASK_TIMEOUT_SECONDS", "30"))
        if not math.isfinite(timeout) or not 0 < timeout <= 180:
            raise ValueError("G2A_HELPER_TIMEOUT_CONFIG_INVALID")
        pool = _acquire_pool(workers, timeout)
        if (pool.ready and _PREWARM_EVIDENCE is not None
                and _PREWARM_EVIDENCE.get("pool") is pool.startup):
            return _PREWARM_EVIDENCE
        if not pool.warm():
            raise RuntimeError("G2A_HELPER_PREWARM_FAILED")
        _PREWARM_EVIDENCE = {"ready": True, "workers": workers,
            "wall_s": time.perf_counter() - started, "parent_cpu_s": time.process_time() - cpu,
            "pool": pool.startup}
    except Exception as error:
        shutdown_helpers()
        _STARTUP_DISABLED = type(error).__name__
        _PREWARM_EVIDENCE = {"ready": False, "workers": 0, "reason": _STARTUP_DISABLED,
            "wall_s": time.perf_counter() - started, "parent_cpu_s": time.process_time() - cpu}
    finally:
        _LOCK.release()
    return _PREWARM_EVIDENCE


def parallel_admitted(session):
    return (session.primitive_pool or (session.workers >= 2 and session.strict_seen
            and session.binding in ("DSCR", "BOTH") and _POOL is not None
            and _POOL.ready and not _POOL.broken and _POOL.workers == session.workers))


class _Batch:
    def __init__(self, session, capacity, funded_builder, strict_builder, solver):
        self.session, self.solver = session, solver
        self.parallel = session is not None and parallel_admitted(session)
        self.future = {}
        self.funded_builder = funded_builder
        self.funded_input = _REPLAY
        self.funded_error = None
        self.strict_builder = strict_builder
        self.strict_value = _REPLAY
        self.strict_error = None
        if not self.parallel:
            return
        try:
            pool = session.pool
        except Exception:
            self.parallel = False
            return
        seed = _memo_snapshot()
        self.future["capacity"] = pool.submit(solver, capacity, seed)
        try:
            self.funded_input = funded_builder()
        except Exception as error:
            # Its canonical position is AFTER the capacity verdict.
            self.funded_error = error
            return
        self.future["funded"] = pool.submit(solver, self.funded_input, seed)
        if session.strict_seen and pool.workers >= 3 and session.strict_credit > 0:
            session.strict_credit -= 1
            try:
                self.strict_value = strict_builder(self.funded_input)
            except Exception as error:
                self.strict_error = error
                return
            pool.metrics["speculative_strict"] += 1
            self.future["strict"] = pool.submit(solver, self.strict_value, seed)

    def solve(self, role, model_input):
        if not self.parallel:
            result = self.solver(model_input)
        else:
            self.session.pool.metrics["required_" + role] += 1
            future = self.future.pop(role, None)
            result = self.session.pool.result_or_replay(future, self.solver, model_input)
        if self.session is not None and role == "funded":
            try:
                self.session.binding = result.senior_debt.binding_constraint
            except (AttributeError, TypeError):
                self.session.binding = None
        return result

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
            self.session.strict_credit += 1

    def close(self):
        if self.parallel:
            for role, future in self.future.items():
                if role == "strict":
                    self.session.pool.metrics["unused_strict"] += 1
                self.session.pool.discard(future)
        self.future.clear()
        self.funded_input = _REPLAY
        self.funded_builder = None
        self.funded_error = None
        self.strict_value = _REPLAY
        self.strict_builder = None
        self.strict_error = None


class _Session:
    def __init__(self, pool=None, *, workers=None, timeout=None):
        self._pool, self.batch, self.strict_seen = pool, None, False
        self.primitive_pool = pool is not None
        self.workers = pool.workers if pool is not None else workers
        self.timeout = timeout
        self.strict_credit = 1 if pool is not None else 0
        self.binding = None

    @property
    def pool(self):
        if self._pool is None:
            self._pool = _acquire_pool(self.workers, self.timeout)
        return self._pool

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
                session = _Session(workers=workers, timeout=timeout)
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
