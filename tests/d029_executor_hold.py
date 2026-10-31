"""Test-only hold point inside the REAL spawned model worker (D-029 executor-kill regression).

``held_run_project`` replaces ``app.api.project_runner.run_project`` only for the duration of one test (the Run route reads that attribute at call
time and pickles the callable by reference into the worker). In the worker it proves, with files and the real OS pid, that THIS process has admitted
the Run and is still inside the calculation, and it blocks there until the test releases it (or SIGKILLs the process). Nothing is stubbed: after
release it calls the unchanged canonical ``run_project``. It is inert in production because nothing but that test installs it.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

MAX_HOLD_SECONDS = 120          # a bounded hold: an abandoned worker can never block a pool for longer than this


def held_run_project(hold_dir: str, *args, **kwargs):
    directory = Path(hold_dir)
    reached = directory / f"reached.{os.getpid()}"
    tmp = directory / f".reached.{os.getpid()}.tmp"
    tmp.write_text(str(os.getpid()), encoding="utf-8")
    os.replace(tmp, reached)                                       # atomic: the test never sees a half-written marker
    deadline = time.monotonic() + MAX_HOLD_SECONDS
    release = directory / "release"
    while not release.exists():
        if time.monotonic() > deadline:
            raise TimeoutError("D-029 hold point was never released")
        time.sleep(0.02)
    from app.api.project_runner import run_project                  # the unchanged canonical calculation, imported inside the worker
    return run_project(*args, **kwargs)
