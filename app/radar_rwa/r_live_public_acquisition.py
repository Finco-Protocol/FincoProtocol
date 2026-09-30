"""Bounded public R-LIVE acquisition admission and in-flight coalescing.

Operational only: this module never computes market authority, changes evidence
timestamps, writes R-LIVE history, or caches completed market results.
"""
from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Iterator
from dataclasses import dataclass, field
import hashlib
import os
import threading
from typing import Generic, TypeVar


T = TypeVar("T")

R_LIVE_SERVICE_BUSY = "R_LIVE_SERVICE_BUSY"
CURRENT_CACHE = "NONE"
PER_CLIENT_RATE_LIMIT = "NOT_IMPLEMENTED"


def _positive_int_env(name: str, default: int, *, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name}_INVALID") from exc
    if value < 1 or value > maximum:
        raise RuntimeError(f"{name}_OUT_OF_RANGE")
    return value


# Process-local by design. With the default production Uvicorn worker count of
# two, the default host-wide upper bound is 2 * 2 = 4 expensive acquisitions.
PROCESS_ACQUISITION_LIMIT = _positive_int_env(
    "FINCO_RLIVE_PROCESS_ACQUISITION_LIMIT", 2, maximum=16
)
MAX_COALESCED_CALLERS = _positive_int_env(
    "FINCO_RLIVE_MAX_COALESCED_CALLERS", 32, maximum=1024
)
WEB_WORKERS = _positive_int_env("FINCO_WEB_WORKERS", 2, maximum=64)
EFFECTIVE_HOST_MAX = PROCESS_ACQUISITION_LIMIT * WEB_WORKERS


class RLiveServiceBusy(RuntimeError):
    """Operational admission rejection; not an R-LIVE market authority state."""

    reason = R_LIVE_SERVICE_BUSY


class RLiveBatchAcquisitionFailed(RuntimeError):
    """Producer failed after admission. Raw upstream errors are not exposed."""


@dataclass
class _InFlight(Generic[T]):
    condition: threading.Condition = field(default_factory=threading.Condition)
    rows: list[T] = field(default_factory=list)
    done: bool = False
    failed: bool = False
    subscribers: int = 0
    cancel_requested: bool = False


class AcquisitionSubscription(Generic[T]):
    """One read cursor over a shared in-flight acquisition."""

    def __init__(
        self,
        coordinator: "PublicAcquisitionCoordinator[T]",
        state: _InFlight[T],
    ) -> None:
        self._coordinator = coordinator
        self._state = state
        self._index = 0
        self._closed = False

    def __iter__(self) -> Iterator[T]:
        try:
            while True:
                with self._state.condition:
                    while self._index >= len(self._state.rows) and not self._state.done:
                        self._state.condition.wait()
                    if self._index < len(self._state.rows):
                        row = self._state.rows[self._index]
                        self._index += 1
                    elif self._state.failed:
                        raise RLiveBatchAcquisitionFailed("R_LIVE_BATCH_ACQUISITION_FAILED")
                    else:
                        return
                # Yield outside the condition lock so a slow client cannot block peers.
                yield row
        finally:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._coordinator._release_subscriber(self._state)


class PublicAcquisitionCoordinator(Generic[T]):
    """Process-wide admission gate plus bounded in-flight request coalescing.

    Completed results are deliberately not retained: CURRENT_CACHE = NONE.
    """

    def __init__(self, *, process_limit: int, max_coalesced_callers: int) -> None:
        if process_limit < 1:
            raise ValueError("PROCESS_LIMIT_MUST_BE_POSITIVE")
        if max_coalesced_callers < 1:
            raise ValueError("MAX_COALESCED_CALLERS_MUST_BE_POSITIVE")
        self.process_limit = process_limit
        self.max_coalesced_callers = max_coalesced_callers
        self._gate = threading.BoundedSemaphore(process_limit)
        self._lock = threading.Lock()
        self._in_flight: dict[Hashable, _InFlight[T]] = {}
        self._active = 0

    @property
    def active_expensive_acquisitions(self) -> int:
        with self._lock:
            return self._active

    @property
    def in_flight_key_count(self) -> int:
        with self._lock:
            return len(self._in_flight)

    def subscribe(
        self,
        key: Hashable,
        producer: Callable[[], Iterable[T]],
    ) -> AcquisitionSubscription[T]:
        """Join identical work or start one bounded expensive acquisition.

        New distinct work is rejected immediately when process capacity is full.
        Identical work shares the producer while it is in flight, up to a bounded
        subscriber count. No caller-controlled value can change the process limit.
        """
        with self._lock:
            existing = self._in_flight.get(key)
            if existing is not None and not existing.done:
                if existing.subscribers >= self.max_coalesced_callers:
                    raise RLiveServiceBusy(R_LIVE_SERVICE_BUSY)
                existing.subscribers += 1
                return AcquisitionSubscription(self, existing)

            if not self._gate.acquire(blocking=False):
                raise RLiveServiceBusy(R_LIVE_SERVICE_BUSY)

            state: _InFlight[T] = _InFlight(subscribers=1)
            self._in_flight[key] = state
            self._active += 1

        thread = threading.Thread(
            target=self._run_producer,
            args=(key, state, producer),
            name="finco-r-live-public-acquisition",
            daemon=True,
        )
        try:
            thread.start()
        except Exception:
            with self._lock:
                if self._in_flight.get(key) is state:
                    self._in_flight.pop(key, None)
                self._active -= 1
                self._gate.release()
            raise RLiveServiceBusy(R_LIVE_SERVICE_BUSY)
        return AcquisitionSubscription(self, state)

    def _run_producer(
        self,
        key: Hashable,
        state: _InFlight[T],
        producer: Callable[[], Iterable[T]],
    ) -> None:
        failed = False
        iterator = None
        try:
            iterator = iter(producer())
            for row in iterator:
                with state.condition:
                    if state.cancel_requested:
                        break
                    state.rows.append(row)
                    state.condition.notify_all()
        except Exception:
            failed = True
        finally:
            if iterator is not None and hasattr(iterator, "close"):
                try:
                    iterator.close()  # type: ignore[attr-defined]
                except Exception:
                    pass
            with state.condition:
                state.failed = failed
                state.done = True
                state.condition.notify_all()
            with self._lock:
                if self._in_flight.get(key) is state:
                    self._in_flight.pop(key, None)
                self._active -= 1
                self._gate.release()

    def _release_subscriber(self, state: _InFlight[T]) -> None:
        with state.condition:
            if state.subscribers > 0:
                state.subscribers -= 1
            if state.subscribers == 0 and not state.done:
                # Stop consuming the producer at its next yield. This prevents an
                # abandoned client from keeping work alive indefinitely while still
                # allowing joined peers to continue uninterrupted.
                state.cancel_requested = True
                state.condition.notify_all()


def current_acquisition_key(rpc_url: str) -> tuple[str, str]:
    """Internal coalescing key without retaining/exposing the RPC URL itself."""
    digest = hashlib.sha256(rpc_url.encode("utf-8")).hexdigest()
    return ("all-approved-current-v1", digest)


PUBLIC_RLIVE_ACQUISITION: PublicAcquisitionCoordinator[tuple[str, str, dict]] = (
    PublicAcquisitionCoordinator(
        process_limit=PROCESS_ACQUISITION_LIMIT,
        max_coalesced_callers=MAX_COALESCED_CALLERS,
    )
)
