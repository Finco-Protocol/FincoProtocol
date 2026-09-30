"""SHADOW runtime: evaluate the canonical observation just served, without exposing anything.

Contract:
- Called best-effort after the canonical R-LIVE response has been computed. It never raises and
  never blocks the canonical request: it only enqueues to a bounded, lazily created single worker.
- The evaluation reuses the exact observation that was served (no second RPC, no re-read of the
  canonical source), so canonical behaviour and latency are unchanged.
- Results go to a bounded in-memory log of sanitized summaries plus the usual telemetry. They are
  never returned by any public route, never written to a ledger, and SHADOW never promotes itself
  to VISIBLE.
- Provider construction is lazy (first eligible observation in SHADOW mode); an outage or missing
  key cannot affect application startup or the canonical response.
"""
from __future__ import annotations

import copy
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Mapping

from .config import JevIntelligenceConfig
from .contracts import JevMode
from .telemetry import now_iso

MAX_QUEUE = 8
LOG_MAXLEN = 200

_lock = threading.Lock()
_runner: ThreadPoolExecutor | None = None
_pending = 0
_dropped = 0
SHADOW_LOG: deque[dict] = deque(maxlen=LOG_MAXLEN)


def _summary(result) -> dict:
    """Sanitized, non-public summary. No features, no evidence values, no provider payload."""
    d = result.diagnostics
    return {
        "recorded_at": now_iso(), "visibility": "SHADOW_NOT_PUBLIC",
        "canonical_id": result.canonical_id, "state": result.state.value, "reason": result.reason,
        "input_fingerprint": result.input_fingerprint, "observation_digest": result.observation_digest,
        "market_regime": result.market_regime.choice if result.market_regime else None,
        "attention": result.attention.state if result.attention else None,
        "requested_model": result.requested_model, "resolved_model": result.resolved_model,
        "cache_status": d.cache_status, "failure_category": d.failure_category,
        "latency_ms": None if d.latency_ms is None else str(d.latency_ms),
    }


def _run(canonical_id: str, state: str, data: Mapping[str, object], config) -> None:
    global _pending
    try:
        from .service import evaluate_intelligence
        result = evaluate_intelligence(canonical_id, config=config,
                                       current_provider=lambda _cid: (state, data))
        SHADOW_LOG.append(_summary(result))
    except Exception:  # noqa: BLE001 - shadow is best-effort by contract
        SHADOW_LOG.append({"recorded_at": now_iso(), "visibility": "SHADOW_NOT_PUBLIC",
                           "canonical_id": str(canonical_id)[:128], "state": "UNAVAILABLE",
                           "reason": "SHADOW_EVALUATION_ERROR"})
    finally:
        with _lock:
            _pending -= 1


def observe(canonical_id: str, state: str, data: Mapping[str, object] | None, *,
            environ: Mapping[str, str] | None = None) -> str:
    """Enqueue one served canonical observation for SHADOW evaluation. Never raises, never blocks."""
    global _runner, _pending, _dropped
    try:
        config = JevIntelligenceConfig.from_env(environ)
        if config.mode is not JevMode.SHADOW:
            return "SKIPPED_MODE"
        if state != "AVAILABLE" or not isinstance(data, Mapping):
            return "SKIPPED_NOT_ELIGIBLE"
        snapshot = copy.deepcopy(dict(data))  # decouple from the response object
        with _lock:
            if _pending >= MAX_QUEUE:
                _dropped += 1
                return "DROPPED_QUEUE_FULL"
            if _runner is None:
                _runner = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jev-shadow")
            _pending += 1
            runner = _runner
        runner.submit(_run, canonical_id, state, snapshot, config)
        return "QUEUED"
    except Exception:  # noqa: BLE001
        return "ERROR_IGNORED"


def drain(timeout: float = 10.0) -> bool:
    """Wait until the queue is empty (tests and operator scripts only)."""
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _lock:
            if _pending == 0:
                return True
        time.sleep(0.01)
    return False


def stats() -> dict:
    with _lock:
        return {"pending": _pending, "dropped": _dropped, "log_size": len(SHADOW_LOG),
                "runner_started": _runner is not None}


def reset_for_tests() -> None:
    global _runner, _pending, _dropped
    with _lock:
        runner, _runner, _pending, _dropped = _runner, None, 0, 0
    if runner is not None:
        runner.shutdown(wait=True)
    SHADOW_LOG.clear()
