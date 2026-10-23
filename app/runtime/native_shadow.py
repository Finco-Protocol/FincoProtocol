"""V10 native candidate - DORMANT authoritative-shadow observer (research; default OFF).

Activation: environment variable ``FINCO_NATIVE_V10_SHADOW`` = ``stage1`` | ``stage2`` (anything else,
including unset, means OFF). OFF is a single dictionary lookup per model call and nothing else.

Authority model (unchanged financial authority):
* The canonical calculation runs exactly as today in the production ``ModelExecutor`` and is the only
  value returned to the caller, persisted (``v2_atomic_run_commit``), written to Run History, and used
  for Integrity. The observer never mutates, delays-on-failure, replaces or annotates that value.
* After the canonical call returns (or raises), the observer fingerprints the canonical outcome and
  enqueues ONE shadow evaluation. A dedicated background thread runs the same picklable call in a
  fresh, spawned, resource-limited (RLIMIT_AS / RLIMIT_CPU / wall timeout) single-use worker with
  ``NativeConfig(mode="candidate")`` and receives only evidence: outcome fingerprint + native counters.
  A native crash, hang or memory exhaustion kills only that worker (``CANDIDATE_*`` evidence).
* Evidence goes to an in-memory bounded ring and, optionally, a JSONL file
  (``FINCO_NATIVE_V10_SHADOW_LOG``). Nothing is written to the application database.
* Backpressure: at most ``FINCO_NATIVE_V10_SHADOW_QUEUE`` (default 2) pending shadows; excess is
  dropped and counted, never blocking or slowing the user's Run beyond the fingerprint.
* The observer never raises into the request path (all failures are counted).
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import enum
import hashlib
import json
import logging
import os
import queue
import threading
import time
from collections import Counter, deque
from typing import Any, Callable

LOG = logging.getLogger("finco.native_v10.shadow")
ENV_SHADOW = "FINCO_NATIVE_V10_SHADOW"
ENV_LOG = "FINCO_NATIVE_V10_SHADOW_LOG"
ENV_QUEUE = "FINCO_NATIVE_V10_SHADOW_QUEUE"
ENV_TIMEOUT = "FINCO_NATIVE_V10_SHADOW_TIMEOUT_SECONDS"
MODES = {"stage1": {"stage2_experimental": False}, "stage2": {"stage2_experimental": True}}
SHADOWED = frozenset({("app.api.project_runner", "run_project")})


def shadow_mode(environ=None) -> str | None:
    value = (environ if environ is not None else os.environ).get(ENV_SHADOW, "").strip().lower()
    return value if value in MODES else None


# ------------------------------------------------------------------ deterministic outcome fingerprint
class _Opaque(Exception):
    pass


def _canon(obj, depth=0):
    if depth > 200:
        raise _Opaque("DEPTH")
    if obj is None or isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return ["f", obj.hex()]                      # exact bits incl. -0.0 / nan payload class
    if isinstance(obj, int):
        return ["i", str(obj)]
    if isinstance(obj, str):
        return ["s", obj]
    if isinstance(obj, enum.Enum):
        return ["e", type(obj).__qualname__, obj.name]
    if isinstance(obj, (_dt.date, _dt.datetime, _dt.time)):
        return ["d", type(obj).__name__, obj.isoformat()]
    if isinstance(obj, dict):
        items = [[_canon(k, depth + 1), _canon(v, depth + 1)] for k, v in obj.items()]
        items.sort(key=lambda kv: json.dumps(kv[0], sort_keys=True))
        return ["m", items]
    if isinstance(obj, (list, tuple)):
        return ["l" if isinstance(obj, list) else "t", [_canon(v, depth + 1) for v in obj]]
    if isinstance(obj, (set, frozenset)):
        return ["S", sorted((_canon(v, depth + 1) for v in obj), key=lambda x: json.dumps(x, sort_keys=True))]
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return ["c", type(obj).__qualname__,
                [[f.name, _canon(getattr(obj, f.name), depth + 1)] for f in dataclasses.fields(obj)]]
    to_dict = getattr(obj, "to_dict", None)                # e.g. pandas objects, if ever present
    if callable(to_dict):
        return ["o", type(obj).__qualname__, _canon(to_dict(), depth + 1)]
    raise _Opaque(type(obj).__qualname__)


def fingerprint(value=None, error: BaseException | None = None) -> dict:
    """Exact, process-independent fingerprint of a model call outcome (value or exception)."""
    try:
        if error is not None:
            # normalised exactly like the executor's worker envelope (_process_entry: type name and
            # 500-char text fields), so a canonical ModelWorkerError and a raw candidate exception compare
            if hasattr(error, "error_type") and hasattr(error, "message"):
                etype, msg = error.error_type, error.message
                rc, det = getattr(error, "reason_code", None), getattr(error, "detail", None)
            else:
                etype, msg = type(error).__name__, str(error)[:500]
                rc, det = getattr(error, "reason_code", None), getattr(error, "detail", None)
            norm = lambda v: "" if v is None else str(v)[:500]  # noqa: E731
            body = ["raise", etype, msg, norm(rc), norm(det)]
        else:
            body = ["return", _canon(value)]
        blob = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return {"kind": body[0], "sha256": hashlib.sha256(blob).hexdigest()}
    except _Opaque as exc:
        return {"kind": "OPAQUE", "sha256": None, "opaque_type": str(exc)}
    except Exception as exc:  # noqa: BLE001 - never raise into the request path
        return {"kind": "FINGERPRINT_ERROR", "sha256": None, "error": type(exc).__name__}


# ------------------------------------------------------------------ worker-side task (spawned process)
def _shadow_task(fn_module: str, fn_name: str, args: tuple, kwargs: dict, native: dict) -> dict:
    from financial_engine.native_v10.config import NativeConfig, native_run

    fn = getattr(__import__(fn_module, fromlist=[fn_name]), fn_name)
    started = time.perf_counter()
    with native_run(NativeConfig(mode="candidate", **native)) as stats:
        try:
            outcome = fingerprint(value=fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001 - the canonical comparison includes exceptions
            outcome = fingerprint(error=exc)
    return {"verdict": outcome["kind"], "digests": {"outcome": outcome}, "native": stats.as_dict(),
            "error": None, "engine_wall": time.perf_counter() - started}


# ------------------------------------------------------------------ parent-side observer
class ShadowObserver:
    def __init__(self, mode: str, *, max_pending: int = 2, timeout_seconds: float = 300.0,
                 log_path: str | None = None, ring: int = 256) -> None:
        self.mode = mode
        self.native = dict(MODES[mode])
        self.timeout_seconds = timeout_seconds
        self.log_path = log_path
        self._queue: queue.Queue = queue.Queue(maxsize=max(1, max_pending))
        self._records: deque = deque(maxlen=ring)
        self._counters: Counter = Counter()
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._inflight = 0
        self._thread = threading.Thread(target=self._loop, name="finco-native-shadow", daemon=True)
        self._thread.start()

    # request path ------------------------------------------------------------
    def observe(self, fn: Callable, args: tuple, kwargs: dict, *, value=None, error=None) -> None:
        try:
            key = (getattr(fn, "__module__", None), getattr(fn, "__qualname__", None))
            if key not in SHADOWED:
                return
            canonical = fingerprint(value=value, error=error)
            with self._lock:
                self._inflight += 1
            try:
                self._queue.put_nowait((key, args, kwargs, canonical, time.time()))
                self._count("enqueued")
            except queue.Full:
                with self._lock:
                    self._inflight -= 1
                    self._idle.notify_all()
                self._count("dropped_backpressure")
        except Exception:  # noqa: BLE001
            self._count("observer_error")

    # background --------------------------------------------------------------
    def _loop(self) -> None:
        from financial_engine.native_v10 import isolation

        while True:
            key, args, kwargs, canonical, t_enq = self._queue.get()
            try:
                limits = isolation.WorkerLimits(timeout_seconds=self.timeout_seconds)
                ev = isolation.run_in_worker(
                    "app.runtime.native_shadow._shadow_task",
                    {"fn_module": key[0], "fn_name": key[1], "args": args, "kwargs": kwargs, "native": self.native},
                    limits=limits)
                cand = (ev.digests or {}).get("outcome") if ev.status == "OK" else None
                if ev.status != "OK":
                    outcome = ev.status
                elif canonical.get("sha256") is None or cand is None or cand.get("sha256") is None:
                    outcome = "UNCOMPARABLE"
                else:
                    outcome = "MATCH" if cand == canonical else "MISMATCH"
                record = {"ts": t_enq, "call": f"{key[0]}.{key[1]}", "mode": self.mode, "outcome": outcome,
                          "canonical": canonical, "candidate": cand, "native": ev.native,
                          "worker_status": ev.status, "worker_exitcode": ev.exitcode,
                          "worker_wall_s": round(ev.wall_seconds, 3), "candidate_error": (ev.error or "")[:300]}
                self._record(record)
                self._count(outcome)
                if outcome == "MISMATCH":
                    LOG.error("native_v10 shadow MISMATCH call=%s canonical=%s candidate=%s",
                              record["call"], canonical.get("sha256"), (cand or {}).get("sha256"))
            except Exception as exc:  # noqa: BLE001
                self._count("shadow_error")
                LOG.warning("native_v10 shadow failure: %s", type(exc).__name__)
            finally:
                with self._lock:
                    self._inflight -= 1
                    self._idle.notify_all()

    def _record(self, record: dict) -> None:
        with self._lock:
            self._records.append(record)
        if self.log_path:
            try:
                with open(self.log_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, sort_keys=True) + "\n")
            except OSError:
                self._count("log_write_error")

    def _count(self, name: str) -> None:
        with self._lock:
            self._counters[name] += 1

    # observability / tests ----------------------------------------------------
    def stats(self) -> dict:
        with self._lock:
            return {"mode": self.mode, "inflight": self._inflight, **dict(self._counters)}

    def records(self) -> list:
        with self._lock:
            return list(self._records)

    def drain(self, timeout: float = 600.0) -> bool:
        deadline = time.monotonic() + timeout
        with self._lock:
            while self._inflight:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._idle.wait(remaining)
        return True


_OBSERVER: ShadowObserver | None = None
_OBSERVER_LOCK = threading.Lock()


def get_observer() -> ShadowObserver | None:
    """The process observer, created lazily only when the environment enables shadow mode."""
    global _OBSERVER
    mode = shadow_mode()
    if mode is None:
        return None
    with _OBSERVER_LOCK:
        if _OBSERVER is None or _OBSERVER.mode != mode:
            try:
                pending = int(os.environ.get(ENV_QUEUE, "2"))
                timeout = float(os.environ.get(ENV_TIMEOUT, "300"))
            except ValueError:
                pending, timeout = 2, 300.0
            _OBSERVER = ShadowObserver(mode, max_pending=pending, timeout_seconds=timeout,
                                       log_path=os.environ.get(ENV_LOG) or None)
        return _OBSERVER


def observe(fn: Callable, args: tuple, kwargs: dict, *, value: Any = None, error: BaseException | None = None) -> None:
    """Executor hook. OFF (default): one environment lookup, no import of native code, no work."""
    if os.environ.get(ENV_SHADOW) is None:
        return
    try:
        observer = get_observer()
        if observer is not None:
            observer.observe(fn, args, kwargs, value=value, error=error)
    except Exception:  # noqa: BLE001 - never into the request path
        LOG.warning("native_v10 shadow observe failed")
