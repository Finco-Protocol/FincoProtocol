"""Importable helpers for spawned model-executor workers used by the P0-B recovery tests."""
from __future__ import annotations

import os
import time


def light_init() -> None:
    """Worker initializer without the engine import graph (keeps pool lifecycles fast in recovery tests)."""


def failing_init() -> None:
    raise RuntimeError("initializer failure (test)")


def worker_pid() -> int:
    return os.getpid()


def sleep_pid(seconds: float) -> int:
    time.sleep(seconds)
    return os.getpid()


def crash_now() -> None:
    os._exit(9)


def light_probe() -> dict:
    return {"engine_version": "test", "warm": True, "pid": os.getpid()}


def slow_probe() -> dict:
    time.sleep(2.0)
    return {"engine_version": "test", "warm": True, "pid": os.getpid()}
