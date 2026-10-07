"""One bounded admission boundary for expensive FINCO model computation.

REQUEST -> ADMISSION -> BOUNDED EXECUTOR -> CALCULATION -> RESULT -> existing persistence / CAS

Why: the financial engine is CPU-heavy pure Python (one product run is ~20 s). Running it inside an
``async`` handler blocks the Uvicorn event loop for the whole run; running it in a thread keeps the
loop alive but serialises concurrent runs on the GIL (measured: two runs take 43 s each in threads,
20 s each in processes; see ``tools/bench_model_execution.py`` and the review dossier). So:

- picklable, pure calls (workbook run, sensitivity grid, API run) execute in a bounded pool of
  spawned worker processes;
- closure-bound legacy routes that cannot be pickled use a bounded thread offload behind the SAME
  admission gate, so total concurrent expensive computation is one number, not two.

This module changes WHEN and WHERE a calculation runs, never WHAT it calculates. It never touches
``financial_engine`` internals and never cancels a calculation midway: once admitted a calculation
runs to completion; if the client goes away the result is discarded and the slot is released when
the calculation actually finishes (so capacity reflects real CPU use and can never leak).

Scope: the bound is PROCESS-LOCAL. Each Uvicorn worker owns its own gate and pool, so the host-wide
ceiling is ``workers x FINCO_MODEL_EXECUTION_CONCURRENCY``. No shared/global limiter is built.
"""
from __future__ import annotations

import asyncio
import atexit
import logging
import multiprocessing
import os
import threading
import time
from collections import deque
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any, Callable

LOG = logging.getLogger("finco.model_execution")

ENV_CONCURRENCY = "FINCO_MODEL_EXECUTION_CONCURRENCY"
ENV_MODE = "FINCO_MODEL_EXECUTION_MODE"          # process (default) | thread (dev/test fallback)
ENV_TIMEOUT = "FINCO_MODEL_EXECUTION_TIMEOUT_SECONDS"

DEFAULT_CONCURRENCY = 2
MAX_CONCURRENCY = 8
DEFAULT_TIMEOUT_SECONDS = 180
MAX_TIMEOUT_SECONDS = 900
RETRY_AFTER_SECONDS = 5

BUSY_CODE = "MODEL_EXECUTION_BUSY"
BUSY_MESSAGE = "Calculation capacity is currently busy. Please retry."
FAILED_CODE = "MODEL_EXECUTION_FAILED"
TIMEOUT_CODE = "MODEL_EXECUTION_TIMEOUT"
CONFIG_INVALID_CODE = "MODEL_EXECUTION_CONFIG_INVALID"


class ModelExecutionBusy(RuntimeError):
    """Admission rejected: all execution slots are in use. Not a calculation failure."""

    code = BUSY_CODE
    retry_after_seconds = RETRY_AFTER_SECONDS

    def __init__(self) -> None:
        super().__init__(BUSY_CODE)


class ModelExecutionFailed(RuntimeError):
    """The executor itself failed (not the model). No internals are exposed."""

    code = FAILED_CODE

    def __init__(self) -> None:
        super().__init__(FAILED_CODE)


class ModelExecutionTimeout(RuntimeError):
    """The caller stopped waiting. The calculation may still be finishing; its slot stays held."""

    code = TIMEOUT_CODE

    def __init__(self) -> None:
        super().__init__(TIMEOUT_CODE)


class ModelExecutionConfigError(ValueError):
    """Invalid configuration. Carries only the variable name, never a value."""

    code = CONFIG_INVALID_CODE


def _int_env(env: dict[str, str], name: str, default: int, *, maximum: int) -> int:
    raw = env.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(str(raw).strip())
    except ValueError:
        raise ModelExecutionConfigError(f"{CONFIG_INVALID_CODE}: {name} must be an integer") from None
    if value < 1 or value > maximum:
        raise ModelExecutionConfigError(f"{CONFIG_INVALID_CODE}: {name} must be between 1 and {maximum}")
    return value


class ModelExecutionConfig:
    __slots__ = ("concurrency", "mode", "timeout_seconds")

    def __init__(self, concurrency: int = DEFAULT_CONCURRENCY, mode: str = "process",
                 timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        if not 1 <= concurrency <= MAX_CONCURRENCY:
            raise ModelExecutionConfigError(f"{CONFIG_INVALID_CODE}: concurrency")
        if mode not in ("process", "thread"):
            raise ModelExecutionConfigError(f"{CONFIG_INVALID_CODE}: {ENV_MODE}")
        if not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise ModelExecutionConfigError(f"{CONFIG_INVALID_CODE}: timeout")
        self.concurrency, self.mode, self.timeout_seconds = concurrency, mode, timeout_seconds

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "ModelExecutionConfig":
        env = dict(os.environ if environ is None else environ)
        mode = str(env.get(ENV_MODE, "process")).strip().lower() or "process"
        return cls(_int_env(env, ENV_CONCURRENCY, DEFAULT_CONCURRENCY, maximum=MAX_CONCURRENCY),
                   mode, _int_env(env, ENV_TIMEOUT, DEFAULT_TIMEOUT_SECONDS, maximum=MAX_TIMEOUT_SECONDS))


def validate_model_execution_config(environ: dict[str, str] | None = None) -> ModelExecutionConfig:
    """Fail fast at startup on an invalid setting (typed error, no values)."""
    return ModelExecutionConfig.from_env(environ)


class ModelWorkerError(RuntimeError):
    """The calculation raised inside the worker. Carries only closed, picklable fields.

    Exceptions are never pickled across the process boundary: a custom exception whose
    constructor differs from its ``args`` can fail to unpickle and would mark the whole pool
    broken. The worker therefore returns a plain envelope and the parent re-raises this type.
    """

    def __init__(self, error_type: str, message: str, reason_code: str | None = None,
                 detail: str | None = None) -> None:
        super().__init__(error_type)
        self.error_type, self.message = error_type, message
        self.reason_code, self.detail = reason_code, detail


class _WorkerFailure:
    __slots__ = ("error_type", "message", "reason_code", "detail")

    def __init__(self, error_type: str, message: str, reason_code, detail) -> None:
        self.error_type, self.message = error_type, message
        self.reason_code, self.detail = reason_code, detail


def _process_entry(fn: Callable[..., Any], args: tuple, kwargs: dict) -> Any:
    """Runs in the worker. Converts any failure into a plain, always-picklable envelope."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        def _text(value: object) -> str | None:
            return None if value is None else str(value)[:500]

        return _WorkerFailure(type(exc).__name__, _text(exc) or "", _text(getattr(exc, "reason_code", None)),
                              _text(getattr(exc, "detail", None)))


def _unwrap(value: Any) -> Any:
    if isinstance(value, _WorkerFailure):
        raise ModelWorkerError(value.error_type, value.message, value.reason_code, value.detail)
    return value


def _worker_init() -> None:
    """Warm the worker once: pay the import cost at pool start, not on the first request."""
    import app.api.project_runner  # noqa: F401


def _worker_warmup_probe() -> dict:
    """Runtime V2 prewarm probe — NON-FINANCIAL.

    Executed once per worker process at application startup.  Forces the
    worker to spawn and complete the import graph the canonical Run needs
    (engine orchestration, tax engine, production authority) WITHOUT
    executing any project model.  Returns a small readiness payload.
    """
    import app.api.project_runner  # noqa: F401  (canonical run entry)
    from financial_engine.orchestrator import run_operating_model  # noqa: F401
    from financial_engine.tax.engine import (  # noqa: F401
        calculate_cfads_and_cash_tax,
        calculate_tax,
    )
    from financial_engine.senior_debt.solver import solve_senior_debt  # noqa: F401
    from app.services.production_financial_authority import (  # noqa: F401
        classify_production_authority,
    )
    from financial_engine.version import ENGINE_VERSION

    return {"engine_version": ENGINE_VERSION, "warm": True}


class ModelExecutor:
    """Admission gate + bounded process pool + bounded thread pool (shared gate, no queue)."""

    def __init__(self, config: ModelExecutionConfig | None = None) -> None:
        self.config = config or ModelExecutionConfig.from_env()
        self._gate = threading.BoundedSemaphore(self.config.concurrency)
        self._lock = threading.Lock()
        self._process_pool: ProcessPoolExecutor | None = None
        self._thread_pool: ThreadPoolExecutor | None = None
        self._active = 0
        self._counters = {"admitted": 0, "busy_rejected": 0, "completed": 0, "failed": 0, "timed_out": 0}
        self._durations: deque[float] = deque(maxlen=100)
        self._warm = False
        self._warmup_duration_s: float | None = None
        self._warm_workers: int = 0

    # ── admission ─────────────────────────────────────────────────────────────────────
    def _admit(self) -> None:
        if not self._gate.acquire(blocking=False):
            with self._lock:
                self._counters["busy_rejected"] += 1
            LOG.warning("model_execution busy_rejected limit=%s", self.config.concurrency)
            raise ModelExecutionBusy()
        with self._lock:
            self._active += 1
            self._counters["admitted"] += 1

    def _finish(self, started: float, future: Future) -> None:
        elapsed = time.monotonic() - started
        failed = future.cancelled() or future.exception() is not None or isinstance(
            future.result(), _WorkerFailure)
        with self._lock:
            self._active -= 1
            self._counters["failed" if failed else "completed"] += 1
            self._durations.append(elapsed)
        self._gate.release()  # ALWAYS released when the calculation actually ends
        LOG.info("model_execution %s duration_s=%.1f", "failed" if failed else "completed", elapsed)

    # ── startup prewarm (Runtime V2) ──────────────────────────────────────────────
    def warm_up(self) -> dict:
        """Spawn every configured worker and complete its import warmup NOW.

        Runtime V2: the pool was previously created lazily on the first user
        Run, so the first request paid process spawn + the full canonical
        import graph.  ``warm_up`` runs at application startup: it creates
        the process pool, submits the dedicated NON-FINANCIAL
        ``_worker_warmup_probe`` to every configured worker and waits for
        completion, so the first user Run never pays spawn/import cost.

        Preserved semantics: admission gating is bypassed ONLY for this
        internal pre-serving operation (user admission slots, counters and
        failure semantics untouched); no project model is executed; a
        warmup failure logs a warning and leaves the executor cold — the
        lazy path then serves the first Run exactly as before.
        """
        if self.config.mode != "process" or self._warm:
            return self.warm_state()
        started = time.monotonic()
        workers = max(1, self.config.concurrency)
        try:
            pool = self._pool("process")
            futures = [pool.submit(_worker_warmup_probe) for _ in range(workers)]
            results = [f.result(timeout=self.config.timeout_seconds) for f in futures]
            with self._lock:
                self._warm = True
                self._warmup_duration_s = round(time.monotonic() - started, 3)
                self._warm_workers = workers
            LOG.info("model_execution prewarm complete workers=%s duration_s=%.3f versions=%s",
                     workers, self._warmup_duration_s,
                     sorted({r.get("engine_version") for r in results}))
        except Exception as exc:  # noqa: BLE001 — never block startup on prewarm
            with self._lock:
                self._warm = False
                self._warmup_duration_s = round(time.monotonic() - started, 3)
            LOG.warning("model_execution prewarm failed — first Run will warm lazily: %s", exc)
            self._discard_broken_process_pool()
        return self.warm_state()

    def warm_state(self) -> dict:
        with self._lock:
            return {
                "warm": self._warm,
                "mode": self.config.mode,
                "warm_workers": self._warm_workers,
                "warmup_duration_s": self._warmup_duration_s,
            }

    @property
    def is_warm(self) -> bool:
        with self._lock:
            return self._warm

    # ── pools ─────────────────────────────────────────────────────────────────────────
    def _pool(self, kind: str):
        with self._lock:
            if kind == "process" and self.config.mode == "process":
                if self._process_pool is None:
                    self._process_pool = ProcessPoolExecutor(
                        max_workers=self.config.concurrency,
                        mp_context=multiprocessing.get_context("spawn"), initializer=_worker_init)
                return self._process_pool
            if self._thread_pool is None:
                self._thread_pool = ThreadPoolExecutor(
                    max_workers=self.config.concurrency, thread_name_prefix="finco-model")
            return self._thread_pool

    def _discard_broken_process_pool(self) -> None:
        with self._lock:
            pool, self._process_pool = self._process_pool, None
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)

    def _submit(self, kind: str, fn: Callable[..., Any], args: tuple, kwargs: dict) -> Future:
        self._admit()
        started = time.monotonic()
        try:
            pool = self._pool(kind)
            if pool is self._process_pool:
                future = pool.submit(_process_entry, fn, args, kwargs)
            else:
                future = pool.submit(fn, *args, **kwargs)
        except BaseException:
            with self._lock:
                self._active -= 1
                self._counters["failed"] += 1
            self._gate.release()
            raise ModelExecutionFailed() from None
        future.add_done_callback(lambda f, s=started: self._finish(s, f))
        return future

    def _translate(self, exc: BaseException) -> BaseException:
        if isinstance(exc, BrokenProcessPool):
            self._discard_broken_process_pool()
            return ModelExecutionFailed()
        return exc

    # ── public API ────────────────────────────────────────────────────────────────────
    async def run_process(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Picklable pure call in a worker process (falls back to a thread in thread mode)."""
        return await self._await(self._submit("process", fn, args, kwargs))

    async def run_thread(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Closure-bound legacy call in a bounded thread behind the same admission gate."""
        return await self._await(self._submit("thread", fn, args, kwargs))

    def run_process_sync(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """For plain ``def`` routes (already off the event loop): same gate, same pool."""
        future = self._submit("process", fn, args, kwargs)
        try:
            return _unwrap(future.result(timeout=self.config.timeout_seconds))
        except TimeoutError:
            with self._lock:
                self._counters["timed_out"] += 1
            raise ModelExecutionTimeout() from None
        except BaseException as exc:  # noqa: BLE001
            raise self._translate(exc) from None

    def admit_inline(self):
        """Admission only, for plain ``def`` routes whose work touches request-bound state (DB).

        The work stays in the calling threadpool thread (already off the event loop) but counts
        against the same gate, so it cannot exceed the process-wide bound. Released on exit.
        """
        executor = self

        class _Admission:
            def __enter__(self_inner):
                executor._admit()
                self_inner._started = time.monotonic()
                return self_inner

            def __exit__(self_inner, exc_type, exc, tb):
                elapsed = time.monotonic() - self_inner._started
                with executor._lock:
                    executor._active -= 1
                    executor._counters["failed" if exc_type else "completed"] += 1
                    executor._durations.append(elapsed)
                executor._gate.release()
                return False

        return _Admission()

    async def _await(self, future: Future) -> Any:
        wrapped = asyncio.wrap_future(future)
        try:
            return _unwrap(await asyncio.wait_for(wrapped, timeout=self.config.timeout_seconds))
        except asyncio.TimeoutError:
            with self._lock:
                self._counters["timed_out"] += 1
            raise ModelExecutionTimeout() from None
        except asyncio.CancelledError:
            # Client disconnected / task cancelled: the calculation is NOT interrupted. The slot is
            # released by the done-callback when it finishes; the result is simply discarded.
            raise
        except BaseException as exc:  # noqa: BLE001
            raise self._translate(exc) from None

    # ── observability / lifecycle ─────────────────────────────────────────────────────
    def stats(self) -> dict:
        with self._lock:
            durations = sorted(self._durations)
            return {
                "scope": "PROCESS_LOCAL", "mode": self.config.mode,
                "concurrency": self.config.concurrency, "active": self._active,
                **self._counters,
                "duration_p50_s": round(durations[len(durations) // 2], 2) if durations else None,
                "warm": self._warm,
                "warmup_duration_s": self._warmup_duration_s,
            }

    def shutdown(self) -> None:
        with self._lock:
            process, thread = self._process_pool, self._thread_pool
            self._process_pool = self._thread_pool = None
        for pool in (process, thread):
            if pool is not None:
                pool.shutdown(wait=False, cancel_futures=True)


_EXECUTOR: ModelExecutor | None = None
_EXECUTOR_LOCK = threading.Lock()


def get_model_executor() -> ModelExecutor:
    global _EXECUTOR
    with _EXECUTOR_LOCK:
        if _EXECUTOR is None:
            _EXECUTOR = ModelExecutor()
        return _EXECUTOR


def reset_model_executor_for_tests(executor: ModelExecutor | None = None) -> None:
    global _EXECUTOR
    with _EXECUTOR_LOCK:
        old, _EXECUTOR = _EXECUTOR, executor
    if old is not None:
        old.shutdown()


atexit.register(lambda: _EXECUTOR.shutdown() if _EXECUTOR is not None else None)


async def run_model_process(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return await get_model_executor().run_process(fn, *args, **kwargs)


async def run_model_thread(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return await get_model_executor().run_thread(fn, *args, **kwargs)


def run_model_process_sync(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return get_model_executor().run_process_sync(fn, *args, **kwargs)
