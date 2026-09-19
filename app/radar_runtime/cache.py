"""Runtime acquisition cache (P9).

Answers exactly one question: *can this exact request fingerprint reuse a
recent acquisition?*  It is a runtime acquisition OPTIMIZATION only.

- Key: the exact canonical request fingerprint.
- Value: ``snapshot_id`` + runtime expiry metadata.
- TTL is explicit, injectable clock, testable configuration.
- The cache NEVER changes historical snapshot contents and MUST NOT and
  CANNOT redefine R4/R5/R7/R11 freshness authority: a cache HIT returns
  the persisted immutable snapshot with its ORIGINAL provider
  observedAt/timestamps — stale source evidence never becomes fresh
  because the cache says HIT.
- Cache correctness never gates correctness of the persisted store.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any


def default_cache_ttl_seconds() -> float:
    raw = os.getenv("RADAR_RUNTIME_CACHE_TTL_SECONDS", "30")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "RADAR_RUNTIME_CACHE_TTL_SECONDS must be a number") from exc
    if value < 0:
        raise ValueError("RADAR_RUNTIME_CACHE_TTL_SECONDS must be >= 0")
    return value


class AcquisitionCache:
    """Small thread-safe TTL cache keyed by exact request fingerprint."""

    def __init__(self, ttl_seconds: "float | None" = None,
                 clock: "Any" = time.monotonic) -> None:
        self._ttl = (default_cache_ttl_seconds()
                     if ttl_seconds is None else float(ttl_seconds))
        if self._ttl < 0:
            raise ValueError("cache ttl_seconds must be >= 0")
        self._clock = clock
        self._entries: "dict[str, tuple[str, float]]" = {}
        self._lock = threading.Lock()

    def get(self, request_fingerprint: str) -> "str | None":
        """Return the cached snapshot_id for an exact fingerprint, or None
        on MISS/expiry.  Expiry is a runtime decision only."""
        with self._lock:
            entry = self._entries.get(request_fingerprint)
            if entry is None:
                return None
            snapshot_id, expires_at = entry
            if self._clock() >= expires_at:
                del self._entries[request_fingerprint]
                return None
            return snapshot_id

    def put(self, request_fingerprint: str, snapshot_id: str) -> None:
        with self._lock:
            self._entries[request_fingerprint] = (
                snapshot_id, self._clock() + self._ttl)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
