"""V10 native candidate - DORMANT authoritative-shadow observer (default OFF).

Activation: environment variable ``FINCO_NATIVE_V10_SHADOW`` = ``stage1`` | ``stage2`` (anything else,
including unset, means OFF). OFF is a single environment lookup per model call and nothing else: this
module is not even imported.

Authority model (unchanged financial authority):
* The canonical calculation runs exactly as today in the production ``ModelExecutor`` and is the only
  value returned to the caller, persisted (``v2_atomic_run_commit``), written to Run History, and used
  for Integrity. The observer never mutates, delays-on-failure, replaces or annotates that value.
* Before the canonical call is submitted, the call's inputs are serialised into an independently owned,
  immutable ``InputSnapshot`` (pickle bytes + sha256). After the canonical call returns (or raises) the
  inputs are serialised again: if the digest differs, the inputs were mutated while the canonical Run
  was in flight, the shadow is NOT evaluated and the outcome is ``INPUT_MUTATED`` (never a false MATCH or
  MISMATCH). Otherwise the canonical outcome is fingerprinted and ONE shadow evaluation of exactly the
  snapshot bytes is queued. The candidate worker re-verifies the snapshot digest before running.
* A background thread OWNED by one ``ShadowObserver`` (itself owned by one ``ModelExecutor``) runs the
  call in a fresh, spawned, resource-limited (RLIMIT_AS / RLIMIT_CPU / wall timeout) single-use worker
  with ``NativeConfig(mode="candidate")`` and receives only evidence: outcome fingerprint + counters.
  A native crash, hang or memory exhaustion kills only that worker (``CANDIDATE_*`` evidence).
* Lifecycle: ``start()`` -> RUNNING; ``shutdown(timeout)`` stops cooperatively (queued work is cancelled
  and counted, an in-flight candidate worker is killed and reaped) and joins the thread within the bound.
  A thread or worker that survives the bound leaves the observer ``SHUTDOWN_INCOMPLETE`` and raises
  ``ShadowShutdownIncomplete``; the owning executor then refuses to create a replacement (fail closed:
  shadow disabled, canonical service unaffected).
* Evidence goes to an in-memory bounded ring and, optionally, a JSONL file
  (``FINCO_NATIVE_V10_SHADOW_LOG``). Nothing is written to the application database.
* Backpressure: at most ``FINCO_NATIVE_V10_SHADOW_QUEUE`` (default 2) pending shadows and at most
  ``FINCO_NATIVE_V10_SHADOW_MAX_INPUT_BYTES`` (default 64 MiB) per snapshot; excess is dropped and
  counted, never blocking the user's Run beyond snapshot + fingerprint.
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
import pickle
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
ENV_MAX_INPUT_BYTES = "FINCO_NATIVE_V10_SHADOW_MAX_INPUT_BYTES"
MODES = {"stage1": {"stage2_experimental": False}, "stage2": {"stage2_experimental": True}}
SHADOWED = frozenset({("app.api.project_runner", "run_project")})
THREAD_NAME = "finco-native-shadow"
DEFAULT_MAX_INPUT_BYTES = 64 * 1024 * 1024

# lifecycle states
NEW, RUNNING, STOPPING, STOPPED, SHUTDOWN_INCOMPLETE = "NEW", "RUNNING", "STOPPING", "STOPPED", "SHUTDOWN_INCOMPLETE"


class ShadowShutdownIncomplete(RuntimeError):
    """The observer thread or a candidate worker outlived the bounded shutdown."""


def shadow_mode(environ=None) -> str | None:
    value = (environ if environ is not None else os.environ).get(ENV_SHADOW, "").strip().lower()
    return value if value in MODES else None


def _env_number(name: str, default, cast):
    try:
        return cast(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


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


# ------------------------------------------------------------------ immutable input snapshot
@dataclasses.dataclass(frozen=True)
class InputSnapshot:
    """Independently owned serialisation of one call's inputs, taken before canonical submission."""

    fn_module: str
    fn_name: str
    payload: bytes            # pickle of (args, kwargs); immutable, shares no object with the caller
    sha256: str


def _serialise(args: tuple, kwargs: dict) -> bytes:
    return pickle.dumps((tuple(args), dict(kwargs)), protocol=pickle.HIGHEST_PROTOCOL)


def snapshot_inputs(fn: Callable, args: tuple, kwargs: dict, *, max_bytes: int) -> InputSnapshot | str:
    """An ``InputSnapshot`` for a shadowed call, or the reason (str) why none is taken."""
    key = (getattr(fn, "__module__", None), getattr(fn, "__qualname__", None))
    if key not in SHADOWED:
        return "NOT_SHADOWED"
    try:
        payload = _serialise(args, kwargs)
    except Exception:  # noqa: BLE001
        return "SNAPSHOT_UNSERIALISABLE"
    if len(payload) > max_bytes:
        return "SNAPSHOT_TOO_LARGE"
    return InputSnapshot(key[0], key[1], payload, hashlib.sha256(payload).hexdigest())


def inputs_unchanged(snapshot: InputSnapshot, args: tuple, kwargs: dict) -> bool:
    """True iff the caller's live inputs still serialise to exactly the snapshot bytes."""
    try:
        return hashlib.sha256(_serialise(args, kwargs)).hexdigest() == snapshot.sha256
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------ worker-side task (spawned process)
def _shadow_task(fn_module: str, fn_name: str, payload: bytes, payload_sha256: str, native: dict) -> dict:
    from financial_engine.native_v10.config import NativeConfig, native_run

    if hashlib.sha256(payload).hexdigest() != payload_sha256:
        raise RuntimeError("SHADOW_SNAPSHOT_DIGEST_MISMATCH")
    args, kwargs = pickle.loads(payload)
    fn = getattr(__import__(fn_module, fromlist=[fn_name]), fn_name)
    started = time.perf_counter()
    with native_run(NativeConfig(mode="candidate", **native)) as stats:
        try:
            outcome = fingerprint(value=fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001 - the canonical comparison includes exceptions
            outcome = fingerprint(error=exc)
    return {"verdict": outcome["kind"], "digests": {"outcome": outcome, "input_sha256": payload_sha256},
            "native": stats.as_dict(), "error": None, "engine_wall": time.perf_counter() - started}


# ------------------------------------------------------------------ parent-side observer
class ShadowObserver:
    """One owned shadow evaluator: bounded queue, one thread, at most one live candidate worker."""

    def __init__(self, mode: str, *, max_pending: int = 2, timeout_seconds: float = 300.0,
                 log_path: str | None = None, ring: int = 256,
                 max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES) -> None:
        if mode not in MODES:
            raise ValueError(f"NATIVE_V10_SHADOW_UNKNOWN_MODE: {mode!r}")
        self.mode = mode
        self.native = dict(MODES[mode])
        self.timeout_seconds = timeout_seconds
        self.log_path = log_path
        self.max_input_bytes = max_input_bytes
        self._queue: queue.Queue = queue.Queue(maxsize=max(1, max_pending))
        self._records: deque = deque(maxlen=ring)
        self._counters: Counter = Counter()
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._inflight = 0
        self._state = NEW
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._worker_proc = None            # the live candidate process, if any (owned by our thread)
        self._incomplete_reason: str | None = None

    # lifecycle ----------------------------------------------------------------
    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def start(self) -> "ShadowObserver":
        with self._lock:
            if self._state != NEW:
                raise RuntimeError(f"NATIVE_V10_SHADOW_NOT_STARTABLE: {self._state}")
            self._thread = threading.Thread(target=self._loop, name=THREAD_NAME, daemon=True)
            self._state = RUNNING
        self._thread.start()
        return self

    def shutdown(self, timeout: float = 30.0) -> None:
        """Stop cooperatively within ``timeout``; raise ``ShadowShutdownIncomplete`` if anything survives.

        Idempotent. Queued (not yet started) evaluations are cancelled and counted; an in-flight
        candidate worker is killed and reaped by the observer thread before it exits.
        """
        with self._lock:
            if self._state in (NEW, STOPPED):
                self._state = STOPPED
                return
            # SHUTDOWN_INCOMPLETE: re-check the survivors (they may have ended since); never restart
            self._state = STOPPING if self._state == RUNNING else self._state
        self._stop.set()
        self._cancel_queued()                               # work that never started
        thread = self._thread
        if thread is not None:
            thread.join(max(0.0, timeout))
        self._cancel_queued()                               # an observe() racing the state change
        survivors = []
        if thread is not None and thread.is_alive():
            survivors.append(f"thread {thread.name}")
        proc = self._worker_proc
        if proc is not None and proc.is_alive():
            survivors.append(f"candidate worker pid={proc.pid}")
        with self._lock:
            if survivors:
                self._state = SHUTDOWN_INCOMPLETE
                self._incomplete_reason = "native shadow shutdown incomplete: " + ", ".join(survivors)
                reason = self._incomplete_reason
            else:
                self._state = STOPPED
                reason = None
        if reason:
            LOG.error(reason)
            raise ShadowShutdownIncomplete(reason)

    def _cancel_queued(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return
            self._count("cancelled_shutdown")
            self._release_inflight()

    # request path ------------------------------------------------------------
    def snapshot(self, fn: Callable, args: tuple, kwargs: dict) -> InputSnapshot | None:
        """Take the immutable input snapshot BEFORE the canonical call is submitted (None: not shadowed)."""
        try:
            snap = snapshot_inputs(fn, args, kwargs, max_bytes=self.max_input_bytes)
        except Exception:  # noqa: BLE001
            self._count("observer_error")
            return None
        if isinstance(snap, str):
            if snap != "NOT_SHADOWED":
                self._count("dropped_" + snap.lower())
            return None
        return snap

    def observe(self, snapshot: InputSnapshot, args: tuple, kwargs: dict, *, value=None, error=None) -> None:
        """After the canonical call: verify input stability, fingerprint the canonical outcome, enqueue."""
        try:
            if self.state != RUNNING:
                self._count("rejected_not_running")
                return
            if not inputs_unchanged(snapshot, args, kwargs):
                self._record({"ts": time.time(), "call": f"{snapshot.fn_module}.{snapshot.fn_name}",
                              "mode": self.mode, "outcome": "INPUT_MUTATED", "input_sha256": snapshot.sha256,
                              "canonical": None, "candidate": None, "native": {}, "worker_status": None,
                              "worker_exitcode": None, "worker_wall_s": 0.0, "candidate_error": ""})
                self._count("INPUT_MUTATED")
                LOG.error("native_v10 shadow INPUT_MUTATED call=%s.%s (inputs changed during the canonical Run; "
                          "not evaluated)", snapshot.fn_module, snapshot.fn_name)
                return
            canonical = fingerprint(value=value, error=error)
            with self._lock:
                self._inflight += 1
            try:
                self._queue.put_nowait((snapshot, canonical, time.time()))
                self._count("enqueued")
            except queue.Full:
                self._release_inflight()
                self._count("dropped_backpressure")
        except Exception:  # noqa: BLE001
            self._count("observer_error")

    # background --------------------------------------------------------------
    def _set_proc(self, proc) -> None:
        self._worker_proc = proc

    def _loop(self) -> None:
        from financial_engine.native_v10 import isolation

        while not self._stop.is_set():
            try:
                snapshot, canonical, t_enq = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if self._stop.is_set():
                    self._count("cancelled_shutdown")
                    continue
                self._evaluate(isolation, snapshot, canonical, t_enq)
            except Exception as exc:  # noqa: BLE001
                self._count("shadow_error")
                LOG.warning("native_v10 shadow failure: %s", type(exc).__name__)
            finally:
                self._release_inflight()

    def _evaluate(self, isolation, snapshot: InputSnapshot, canonical: dict, t_enq: float) -> None:
        ev = isolation.run_in_worker(
            "app.runtime.native_shadow._shadow_task",
            {"fn_module": snapshot.fn_module, "fn_name": snapshot.fn_name, "payload": snapshot.payload,
             "payload_sha256": snapshot.sha256, "native": self.native},
            limits=isolation.WorkerLimits(timeout_seconds=self.timeout_seconds),
            cancel=self._stop, on_process=self._set_proc)
        if not ev.reaped:
            self._count("worker_not_reaped")
        cand = (ev.digests or {}).get("outcome") if ev.status == "OK" else None
        if ev.status != "OK":
            outcome = ev.status
        elif (ev.digests or {}).get("input_sha256") != snapshot.sha256:
            outcome = "UNCOMPARABLE"
        elif canonical.get("sha256") is None or cand is None or cand.get("sha256") is None:
            outcome = "UNCOMPARABLE"
        else:
            outcome = "MATCH" if cand == canonical else "MISMATCH"
        record = {"ts": t_enq, "call": f"{snapshot.fn_module}.{snapshot.fn_name}", "mode": self.mode,
                  "outcome": outcome, "input_sha256": snapshot.sha256, "canonical": canonical, "candidate": cand,
                  "native": ev.native, "worker_status": ev.status, "worker_exitcode": ev.exitcode,
                  "worker_wall_s": round(ev.wall_seconds, 3), "candidate_error": (ev.error or "")[:300]}
        self._record(record)
        self._count(outcome)
        if outcome == "MISMATCH":
            LOG.error("native_v10 shadow MISMATCH call=%s canonical=%s candidate=%s",
                      record["call"], canonical.get("sha256"), (cand or {}).get("sha256"))

    def _release_inflight(self) -> None:
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
            return {"mode": self.mode, "state": self._state, "inflight": self._inflight, **dict(self._counters)}

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


def observer_from_environment(mode: str) -> ShadowObserver:
    """A NEW (not started) observer configured from the environment."""
    return ShadowObserver(mode, max_pending=_env_number(ENV_QUEUE, 2, int),
                          timeout_seconds=_env_number(ENV_TIMEOUT, 300.0, float),
                          log_path=os.environ.get(ENV_LOG) or None,
                          max_input_bytes=_env_number(ENV_MAX_INPUT_BYTES, DEFAULT_MAX_INPUT_BYTES, int))
