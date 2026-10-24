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


try:  # Python >= 3.11: the builtin exception group itself (no behaviour change)
    LifecycleErrors = ExceptionGroup  # noqa: F821
except NameError:  # Python 3.10: minimal stand-in that keeps EVERY error observable
    class LifecycleErrors(Exception):
        """``ExceptionGroup(message, exceptions)`` equivalent for Python 3.10: ``.message`` and ``.exceptions``."""

        def __init__(self, message, exceptions):
            exceptions = tuple(exceptions)
            if not isinstance(message, str):
                raise TypeError("argument 1 must be str")
            if not exceptions:
                raise ValueError("second argument (exceptions) must be a non-empty sequence")
            if not all(isinstance(exc, Exception) for exc in exceptions):
                raise TypeError("Cannot nest BaseExceptions in an ExceptionGroup")
            super().__init__(message, exceptions)
            self.message = message
            self.exceptions = exceptions

        def __str__(self):
            count = len(self.exceptions)
            return f"{self.message} ({count} sub-exception{'s' if count > 1 else ''})"


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
