"""Sanitized operational telemetry (bounded, in-memory + structured log line).

Records only closed fields: counts, cache status, latency, models, provider request id,
provider-reported usage scalars and the failure category. Never keys, request bodies,
provider error text or identity beyond the canonical id. No monetary cost is invented; the
estimate helper is explicitly an ESTIMATE from the vendor's published input rate.
"""
from __future__ import annotations

import logging
import threading
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

_LOG = logging.getLogger("finco.jev_intelligence")
ESTIMATED_INPUT_USD_PER_MILLION_TOKENS = Decimal("0.042")  # vendor-published, unverified here


@dataclass(frozen=True)
class TelemetryRecord:
    recorded_at: str
    canonical_id: str
    mode: str
    outcome: str  # closed state or reason code
    cache_status: str
    latency_ms: str | None
    requested_model: str | None
    resolved_model: str | None
    provider_request_id: str | None
    usage: tuple[tuple[str, str], ...]
    failure_category: str | None


class Telemetry:
    def __init__(self, maxlen: int = 500) -> None:
        self._lock = threading.Lock()
        self._records: deque[TelemetryRecord] = deque(maxlen=maxlen)
        self._counters: Counter[str] = Counter()

    def record(self, rec: TelemetryRecord) -> None:
        with self._lock:
            self._records.append(rec)
            self._counters["requests"] += 1
            self._counters[f"outcome:{rec.outcome}"] += 1
            self._counters[f"cache:{rec.cache_status}"] += 1
            if rec.cache_status == "MISS" and (
                    rec.outcome in ("AVAILABLE", "INVALID_RESPONSE") or rec.failure_category):
                self._counters["provider_calls"] += 1
            if rec.failure_category:
                self._counters[f"failure:{rec.failure_category}"] += 1
        _LOG.info("jev_intelligence outcome=%s cache=%s mode=%s model=%s->%s failure=%s",
                  rec.outcome, rec.cache_status, rec.mode, rec.requested_model,
                  rec.resolved_model, rec.failure_category)

    def snapshot(self) -> dict:
        with self._lock:
            return {"counters": dict(self._counters), "recent": [r.__dict__ for r in self._records]}

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._counters.clear()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def estimate_request_cost_usd(approx_input_tokens: int) -> Decimal:
    """ESTIMATE only (vendor input rate x supplied tokens); never reported as measured cost."""
    return (Decimal(approx_input_tokens) * ESTIMATED_INPUT_USD_PER_MILLION_TOKENS
            / Decimal(1_000_000))


TELEMETRY = Telemetry()
