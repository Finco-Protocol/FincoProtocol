"""Short-TTL, fingerprint-keyed cache with in-flight coalescing (prevents duplicate billing)."""
from __future__ import annotations

import threading
import time
from typing import Callable

from .contracts import IntelligenceResult, IntelligenceState

MIN_TTL_SECONDS = 30
MAX_TTL_SECONDS = 120
MAX_ENTRIES = 256


def clamp_ttl(seconds: int) -> int:
    return max(MIN_TTL_SECONDS, min(MAX_TTL_SECONDS, int(seconds)))


def cache_key(economic_asset_uid: str, input_fingerprint: str, question_schema_version: str,
              requested_model: str) -> tuple[str, str, str, str]:
    return (economic_asset_uid, input_fingerprint, question_schema_version, requested_model)


class _Flight:
    __slots__ = ("event", "result", "error")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: IntelligenceResult | None = None
        self.error: BaseException | None = None


class IntelligenceCache:
    """Only AVAILABLE results are cached; failures are never replayed as answers."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[tuple, tuple[float, IntelligenceResult]] = {}
        self._flights: dict[tuple, _Flight] = {}

    def get_or_compute(self, key: tuple, ttl_seconds: int,
                       compute: Callable[[], IntelligenceResult]) -> tuple[IntelligenceResult, str]:
        now = self._clock()
        with self._lock:
            hit = self._entries.get(key)
            if hit is not None and hit[0] > now:
                return hit[1].with_cache_status("HIT"), "HIT"
            flight = self._flights.get(key)
            leader = flight is None
            if leader:
                flight = self._flights[key] = _Flight()
        if not leader:
            flight.event.wait(timeout=60)
            if flight.result is not None:
                return flight.result.with_cache_status("COALESCED"), "COALESCED"
            raise RuntimeError("COALESCED_EVALUATION_FAILED")
        try:
            result = compute()
            flight.result = result
            if result.state is IntelligenceState.AVAILABLE:
                with self._lock:
                    if len(self._entries) >= MAX_ENTRIES:
                        self._entries.pop(next(iter(self._entries)))
                    self._entries[key] = (self._clock() + clamp_ttl(ttl_seconds), result)
            return result.with_cache_status("MISS"), "MISS"
        except BaseException as exc:
            flight.error = exc
            raise
        finally:
            with self._lock:
                self._flights.pop(key, None)
            flight.event.set()

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
