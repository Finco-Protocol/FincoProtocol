"""Process-local concurrency limiter for A5 synchronous model-run routes.

Uses threading.BoundedSemaphore (not asyncio) because A5 route handlers are
synchronous def functions dispatched to FastAPI's threadpool.

Capacity is controlled by FINCO_MAX_CONCURRENT_RUNS — the same env var that
governs main_web.py's asyncio semaphore — so a single operational setting
covers both the browser run surface and the API run surface.

FINCO_MAX_CONCURRENT_RUNS=0 disables the limiter (dev/single-user mode).
"""
from __future__ import annotations

import os
import threading

_MAX = int(os.getenv("FINCO_MAX_CONCURRENT_RUNS", "8"))
_semaphore: threading.BoundedSemaphore | None = (
    threading.BoundedSemaphore(_MAX) if _MAX > 0 else None
)


def acquire_run_slot() -> bool:
    """Non-blocking acquire. Returns True if acquired, False if at capacity."""
    if _semaphore is None:
        return True
    return _semaphore.acquire(blocking=False)


def release_run_slot() -> None:
    """Release a previously acquired slot. Safe to call even if limiter is None."""
    if _semaphore is not None:
        _semaphore.release()
