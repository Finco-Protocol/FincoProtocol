"""Tiny last-known-good helper for the Radar surface TTL caches.

Correction A: several dashboard services fail closed INTERNALLY — a real
provider failure returns a typed ``{"state": "UNAVAILABLE", ...}`` payload
instead of raising. Last-known-good fallback must therefore cover BOTH the
exception path and the typed-UNAVAILABLE path, and the served last-known-good
payload must never be presentable as fresh/current (stale != current).

Semantics (identical for every surface; module-local caches remain):
- a successfully fetched, non-UNAVAILABLE payload is the last-known-good;
- within TTL the cached payload is returned unchanged;
- after TTL a refresh is attempted (single-flight on the fetch lock):
  * refresh succeeds with a cacheable payload  -> store and return it;
  * refresh returns a FULLY typed UNAVAILABLE  -> return the last-known-good
    payload within the stale-grace window as an explicit stale presentation
    projection (original evidence, values and canonical timestamps untouched;
    only presentation-level state/reason markers are added to a COPY);
    the UNAVAILABLE result is never stored over the last-known-good;
  * refresh raises                              -> same stale projection
    within the grace window, otherwise the exception propagates (existing
    fail-closed route behavior);
- with no valid last-known-good, typed UNAVAILABLE passes through and
  exceptions propagate exactly as before this helper existed.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

LAST_KNOWN_GOOD_REASON = "LAST_KNOWN_GOOD_FALLBACK"


def is_fully_unavailable(value: Any) -> bool:
    """FULLY unavailable only: a partial dashboard with some unavailable rows
    is current data and must never be replaced by stale last-known-good."""
    return isinstance(value, dict) and value.get("state") == "UNAVAILABLE"


def stale_projection(payload: dict) -> dict:
    """Presentation copy of a last-known-good payload.

    Original economic values, source timestamps and retrieved/observed clocks
    are preserved byte-for-byte; only presentation-level markers are added so
    the observation can never be mistaken for current live data. The cached
    canonical payload itself is never mutated.

    ``state`` becomes the visible STALE badge each dashboard template already
    renders. ``reason`` is deliberately NOT set — templates render that key
    as a "data unavailable" error panel, which would misdescribe preserved
    observations. The fallback is declared via ``last_known_good`` plus the
    machine-readable ``lkg_reason``, which the templates surface as an
    explicit "Last-known-good fallback" note.
    """
    projected = dict(payload)
    projected["state"] = "STALE"
    projected["last_known_good"] = True
    projected["lkg_reason"] = LAST_KNOWN_GOOD_REASON
    return projected


def _cached_at(cache: dict) -> tuple[float | None, dict | None]:
    return cache.get("at"), cache.get("value")


def _fresh(cache: dict, ttl: float, now: float) -> dict | None:
    at, value = _cached_at(cache)
    if value is not None and at is not None and (now - at) < ttl:
        return value
    return None


def _last_known_good(cache: dict, grace: float, now: float) -> dict | None:
    at, value = _cached_at(cache)
    if value is not None and at is not None and (now - at) < grace:
        return value
    return None


def read_with_last_known_good(
    *, cache: dict, lock: threading.Lock, fetch_lock: threading.Lock,
    fetch: Callable[[], dict], ttl: float, grace: float,
) -> dict:
    """TTL-cached, single-flight dashboard read with typed LKG fallback.

    ``cache`` is the owning module's ``{"at": None, "value": None}`` record;
    ``lock`` guards it, ``fetch_lock`` coalesces identical misses. Provider
    I/O runs outside ``lock``.
    """
    now = time.monotonic()
    with lock:
        hit = _fresh(cache, ttl, now)
    if hit is not None:
        return hit
    with fetch_lock:
        now = time.monotonic()
        with lock:
            hit = _fresh(cache, ttl, now)
            prior = _last_known_good(cache, grace, now)
        if hit is not None:
            return hit
        try:
            value = fetch()
        except Exception:
            if prior is not None:
                return stale_projection(prior)
            raise
        if is_fully_unavailable(value):
            # Never store a fully UNAVAILABLE result over the last-known-good.
            if prior is not None:
                return stale_projection(prior)
            return value
        with lock:
            cache["at"] = now
            cache["value"] = value
        return value
