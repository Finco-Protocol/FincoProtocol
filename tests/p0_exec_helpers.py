"""Importable helpers for spawned model-executor workers (must live in an importable module)."""
from __future__ import annotations

import os
import time


def spin(seconds: float) -> int:
    """CPU-bound pure Python that holds the GIL (like the financial engine) for ``seconds``."""
    deadline = time.perf_counter() + seconds
    n = 0
    while time.perf_counter() < deadline:
        n += 1
    return os.getpid()


def add(a: int, b: int) -> int:
    return a + b


class WeirdError(Exception):
    """An exception whose constructor differs from its args (would not survive pickling)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.reason_code, self.detail = code, detail


def raise_weird() -> None:
    raise WeirdError("ENGINE_EXPLODED", "kaboom")


def die_hard() -> None:
    """Kill the worker process abruptly (simulates an OOM kill / crash)."""
    os._exit(9)


import threading  # noqa: E402

RELEASE = threading.Event()


def hold_until_released() -> int:
    """Occupy an execution slot until the test releases it (thread mode only)."""
    RELEASE.wait(timeout=120)
    return os.getpid()
