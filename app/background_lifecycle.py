"""Owned, interruptible recurring work; successful shutdown means no live writer.

An admitted operation completes normally. A deadline reports failure and keeps
ownership, so callers cannot mistake a stop request for completed cleanup.
"""
from __future__ import annotations

import logging
import threading
import time


class ShutdownIncomplete(RuntimeError):
    """The caller still owns work/resources; replacement is unsafe."""


class RecurringService:
    def __init__(self, operation, *, name, initial_delay, interval):
        if initial_delay < 0 or interval <= 0:
            raise ValueError("invalid recurring work cadence")
        self.operation = operation
        self.name = name
        self.initial_delay = initial_delay
        self.interval = interval
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = None

    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                if self._stop.is_set():
                    raise ShutdownIncomplete(self.name + " is still stopping")
                return False
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
            try:
                self._thread.start()
            except BaseException:
                self._thread = None
                raise
            return True

    def _run(self):
        if self._stop.wait(self.initial_delay):
            return
        while not self._stop.is_set():
            try:
                self.operation()
            except Exception:
                logging.getLogger(__name__).exception("%s cycle failed", self.name)
            if self._stop.wait(self.interval):
                return

    def shutdown(self, timeout=30.0):
        if timeout < 0:
            raise ValueError("negative shutdown deadline")
        deadline = time.monotonic() + timeout
        if not self._lock.acquire(timeout=max(0, deadline - time.monotonic())):
            raise ShutdownIncomplete(self.name + " lifecycle lock deadline")
        try:
            self._stop.set()
            thread = self._thread
            if thread is not None:
                if thread is threading.current_thread():
                    raise ShutdownIncomplete(self.name + " cannot join itself")
                thread.join(max(0, deadline - time.monotonic()))
                if thread.is_alive():
                    raise ShutdownIncomplete(self.name + " did not finish before deadline")
        finally:
            self._lock.release()
