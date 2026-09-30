"""Small, bounded, process-local per-client request control for high-cost public refresh paths.

Purpose: stop one client from amplifying live-RPC or paid-provider work by hammering a refresh
route. It is NOT user tracking: keys are held only in process memory, bounded in count, expire with
the window, and are never persisted or logged. It is deliberately not distributed (no Redis); with
N Uvicorn workers a single client can reach about N x the per-process limit.

Applied only to expensive live-acquisition routes; cheap cached/static reads are never limited.
The key is the connection's client host (uvicorn applies trusted proxy headers, so behind the
loopback nginx this is the real client address). This is the last-resort operational key.
"""
from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from typing import Callable

ENV_LIMIT = "FINCO_CLIENT_REFRESH_LIMIT_PER_MINUTE"
DEFAULT_LIMIT = 30
MAX_LIMIT = 600
WINDOW_SECONDS = 60
MAX_KEYS = 4096
SCOPE = "PROCESS_LOCAL"
RATE_LIMITED = "CLIENT_RATE_LIMITED"


def _limit_from_env(environ: dict[str, str] | None = None) -> int:
    env = os.environ if environ is None else environ
    raw = env.get(ENV_LIMIT)
    if raw is None or not str(raw).strip():
        return DEFAULT_LIMIT
    try:
        value = int(str(raw).strip())
    except ValueError:
        raise ValueError(f"{ENV_LIMIT} must be an integer") from None
    if not 1 <= value <= MAX_LIMIT:
        raise ValueError(f"{ENV_LIMIT} must be between 1 and {MAX_LIMIT}")
    return value


class ClientRateLimiter:
    """Fixed-window counter per (family, client). Bounded memory; O(1) per check."""

    def __init__(self, limit: int = DEFAULT_LIMIT, window_seconds: int = WINDOW_SECONDS,
                 max_keys: int = MAX_KEYS, clock: Callable[[], float] = time.monotonic) -> None:
        if limit < 1 or window_seconds < 1 or max_keys < 1:
            raise ValueError("limiter bounds must be positive")
        self.limit, self.window, self.max_keys, self._clock = limit, window_seconds, max_keys, clock
        self._lock = threading.Lock()
        self._entries: "OrderedDict[tuple[str, str], list[float | int]]" = OrderedDict()

    def check(self, family: str, client: str) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds). Counts the call only when allowed."""
        now = self._clock()
        key = (family, client or "unknown")
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or now - entry[0] >= self.window:
                entry = [now, 0]
            if entry[1] >= self.limit:
                self._entries[key] = entry
                self._entries.move_to_end(key)
                return False, max(1, int(self.window - (now - entry[0])) + 1)
            entry[1] += 1
            self._entries[key] = entry
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_keys:
                self._entries.popitem(last=False)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._entries.clear()

    def key_count(self) -> int:
        with self._lock:
            return len(self._entries)


_LIMITER: ClientRateLimiter | None = None
_LOCK = threading.Lock()


def get_client_limiter() -> ClientRateLimiter:
    global _LIMITER
    with _LOCK:
        if _LIMITER is None:
            _LIMITER = ClientRateLimiter(limit=_limit_from_env())
        return _LIMITER


def reset_client_limiter_for_tests() -> None:
    global _LIMITER
    with _LOCK:
        _LIMITER = None


def client_key(request) -> str:
    client = getattr(request, "client", None)
    return (getattr(client, "host", None) or "unknown")[:64]


def rate_limited_response(retry_after: int):
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=429, headers={"Retry-After": str(retry_after), "Cache-Control": "no-store"},
        content={"state": "RATE_LIMITED", "reason": RATE_LIMITED},
    )


def enforce(request, family: str):
    """Return a 429 response if this client exceeded the family budget, else None."""
    allowed, retry_after = get_client_limiter().check(family, client_key(request))
    return None if allowed else rate_limited_response(retry_after)
