"""Acquisition service: one acquisition -> one immutable snapshot (P6).

Core invariant: **one refresh operation = at most one acquisition
snapshot**.  All downstream reads consume that exact snapshot by id and
never call providers (P14: the read path is network-free).

- P7  single-flight: identical concurrent requests share exactly one
      provider acquisition and one resulting snapshot_id.
- P10 bounded external work: explicit per-provider timeout and total
      acquisition budget; no infinite/blocking call.
- P11 bounded concurrency: independent providers run in a bounded pool;
      causal chains are the caller's composition concern; partial
      acquisition is preserved honestly.
- P5  the runtime classifies transport/runtime state only; financial and
      market authority remain owned by the frozen R0-R12 packages.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .cache import AcquisitionCache, default_cache_ttl_seconds
from .contracts import (
    SCHEMA_VERSION,
    AcquisitionRequest,
    AcquisitionSnapshot,
    AcquisitionState,
    ProviderResult,
    ProviderResultState,
    RuntimeContractError,
    SnapshotNotFoundError,
    ensure_canonical_evidence,
)
from .observability import AcquisitionEvent, RuntimeEventLogger
from .snapshot_store import SnapshotStore

# Provider callables receive the immutable AcquisitionRequest and return a
# mapping: {"evidence": <Mapping, required>, "observedAt": <str|None>}.
# They are wired at composition time to the FROZEN R0-R12 provider
# adapters; the runtime never re-parses or re-implements provider parsers
# and never depends on private live_proof orchestration (P1/P5).
ProviderCallable = Callable[[AcquisitionRequest], Mapping[str, Any]]


def _env_float(name: str, default: str) -> float:
    raw = os.getenv(name, default)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value <= 0:
        raise ValueError(f"{name} must be > 0")
    return value


@dataclass(frozen=True)
class ServiceConfig:
    """Explicit, documented runtime-only configuration (P10).  These
    values are transport bounds ONLY — no financial/freshness authority is
    encoded in them."""

    per_provider_timeout_seconds: float = 10.0
    total_budget_seconds: float = 25.0
    max_concurrent_providers: int = 8

    @classmethod
    def from_env(cls) -> "ServiceConfig":
        return cls(
            per_provider_timeout_seconds=_env_float(
                "RADAR_RUNTIME_PROVIDER_TIMEOUT_SECONDS", "10"),
            total_budget_seconds=_env_float(
                "RADAR_RUNTIME_TOTAL_BUDGET_SECONDS", "25"),
            max_concurrent_providers=int(
                os.getenv("RADAR_RUNTIME_MAX_CONCURRENT_PROVIDERS", "8")),
        )


@dataclass(frozen=True)
class ProviderExecutionOutcome:
    """N02: internal execution envelope produced INSIDE the provider
    worker.  ``completed_mono`` is captured immediately when the provider
    callable returns/raises, so the coordinator's collection time can
    never decide whether a provider met its deadline."""

    provider: str
    dispatch_mono: float
    completed_mono: float
    observation: "Any" = None
    error: "BaseException | None" = None


class _Flight:
    """One in-flight acquisition shared by single-flight waiters (P7)."""

    __slots__ = ("done", "snapshot", "error")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.snapshot: "AcquisitionSnapshot | None" = None
        self.error: "BaseException | None" = None


def _deadline_outcome(provider_deadline: float, total_deadline: float,
                      completed_mono: "float | None",
                      decision_mono: float) -> "tuple[bool, str | None]":
    """N02: the authoritative deadline decision for one provider result.

    Returns ``(timed_out, error_class)``.  The decision compares the
    WORKER-CAPTURED completion time against the limiting deadline
    (``min(provider_deadline, total_deadline)``) — never the coordinator's
    observation time and never ``future.done()`` alone.  A still-running
    provider is timed out at its limiting deadline; the classification
    names the deadline that was actually limiting."""
    limiting = min(provider_deadline, total_deadline)
    effective = completed_mono if completed_mono is not None else decision_mono
    if effective <= limiting:
        return (False, None)
    return (True,
            "TOTAL_BUDGET_EXHAUSTED" if total_deadline <= provider_deadline
            else "PER_PROVIDER_TIMEOUT")


class AcquisitionService:
    """One acquisition -> one immutable snapshot -> one snapshot_id."""

    def __init__(
        self,
        store: SnapshotStore,
        providers: "Mapping[str, ProviderCallable] | None" = None,
        *,
        cache: "AcquisitionCache | None" = None,
        config: "ServiceConfig | None" = None,
        event_logger: "RuntimeEventLogger | None" = None,
        clock: "Any" = None,
        monotonic: "Any" = None,
    ) -> None:
        self._store = store
        self._providers = dict(providers or {})
        self._cache = cache or AcquisitionCache(
            ttl_seconds=default_cache_ttl_seconds())
        self._config = config or ServiceConfig.from_env()
        self._events = event_logger or RuntimeEventLogger()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or time.monotonic
        self._inflight: "dict[str, _Flight]" = {}
        self._inflight_lock = threading.Lock()
        # N01: ONE service-owned provider execution pool with bounded
        # admission.  ``max_concurrent_providers`` bounds the WHOLE
        # service, not each acquisition.  Capacity (the bounded
        # semaphore) is held from dispatch until the provider callable
        # actually returns/raises inside the worker — coordinator
        # timeouts NEVER release capacity for still-running work, so
        # repeated timed-out acquisitions cannot accumulate active
        # threads.  The executor queue therefore never grows beyond the
        # admitted work items.
        self._provider_pool = ThreadPoolExecutor(
            max_workers=max(1, self._config.max_concurrent_providers),
            thread_name_prefix="radar-provider")
        self._provider_capacity = threading.BoundedSemaphore(
            max(1, self._config.max_concurrent_providers))
        self._closed = False

    def close(self) -> None:
        """Release the service-owned provider executor.  Idempotent.

        Already-running provider callables CANNOT be force-killed in
        Python; shutdown() stops accepting new work and cancels pending
        (not-yet-started) items.  Bounded admission (the capacity
        semaphore) continues to guarantee that in-flight work cannot
        accumulate beyond the configured capacity."""
        if getattr(self, "_provider_pool", None) is not None:
            self._provider_pool.shutdown(wait=False, cancel_futures=True)
            self._provider_pool = None

    # ------------------------------------------------------------------
    # read path — network-free (P14)
    # ------------------------------------------------------------------
    def get_snapshot(self, snapshot_id: str) -> AcquisitionSnapshot:
        """Read one snapshot by exact id.  Performs ZERO provider/network
        calls; reads only from the durable immutable store."""
        snapshot = self._store.get(snapshot_id)
        if snapshot is None:
            raise SnapshotNotFoundError(
                f"no acquisition snapshot for id {snapshot_id!r}")
        return snapshot

    # ------------------------------------------------------------------
    # acquisition path
    # ------------------------------------------------------------------
    def acquire(self, request: AcquisitionRequest) -> AcquisitionSnapshot:
        fingerprint = request.fingerprint

        # P9: cache HIT reuses the exact persisted snapshot; the cache
        # never alters snapshot contents or freshness semantics.
        cached_id = self._cache.get(fingerprint)
        if cached_id is not None:
            snapshot = self._store.get(cached_id)
            if snapshot is not None:
                self._events.record(AcquisitionEvent(
                    event="acquisition.cache_hit",
                    request_fingerprint=fingerprint,
                    snapshot_id=snapshot.snapshot_id,
                    cache="HIT"))
                return snapshot
            # Persisted snapshot missing -> fall through to reacquire;
            # correctness never depends on the cache.

        # P7: single-flight — one provider acquisition per fingerprint.
        with self._inflight_lock:
            flight = self._inflight.get(fingerprint)
            reused = flight is not None
            if flight is None:
                flight = _Flight()
                self._inflight[fingerprint] = flight
        if reused:
            flight.done.wait()
            if flight.error is not None:
                raise flight.error
            self._events.record(AcquisitionEvent(
                event="acquisition.single_flight_reused",
                request_fingerprint=fingerprint,
                snapshot_id=flight.snapshot.snapshot_id,
                cache="MISS", single_flight="reused"))
            return flight.snapshot  # type: ignore[return-value]

        try:
            snapshot = self._execute(request, fingerprint)
            flight.snapshot = snapshot
            return snapshot
        except BaseException as exc:  # noqa: BLE001 - published to waiters
            flight.error = exc
            raise
        finally:
            with self._inflight_lock:
                self._inflight.pop(fingerprint, None)
            flight.done.set()

    # ------------------------------------------------------------------
    def _execute(self, request: AcquisitionRequest,
                 fingerprint: str) -> AcquisitionSnapshot:
        correlation_id = uuid.uuid4().hex
        started = self._clock()
        started_mono = self._monotonic()
        self._events.record(AcquisitionEvent(
            event="acquisition.start",
            correlation_id=correlation_id,
            request_fingerprint=fingerprint,
            cache="MISS", single_flight="new"))

        results = self._acquire_providers(request, correlation_id,
                                          fingerprint, started_mono)

        completed_mono = self._monotonic()
        successful = [r for r in results
                      if r.state is ProviderResultState.SUCCESS]
        if len(successful) == len(results) and results:
            state = AcquisitionState.COMPLETE
        elif successful:
            state = AcquisitionState.PARTIAL
        else:
            state = AcquisitionState.UNAVAILABLE

        snapshot = AcquisitionSnapshot(
            request_fingerprint=fingerprint,
            request=request.payload(),
            chain_id=request.chain_id,
            contract_address=request.contract_address,
            started_at=started.isoformat(),
            completed_at=self._clock().isoformat(),
            state=state,
            providers=tuple(results),
            runtime_metadata={
                "runtimeSchemaVersion": SCHEMA_VERSION,
                "correlationId": correlation_id,
                "elapsedMs": round((completed_mono - started_mono) * 1000, 3),
                "config": {
                    "perProviderTimeoutSeconds":
                        self._config.per_provider_timeout_seconds,
                    "totalBudgetSeconds": self._config.total_budget_seconds,
                    "maxConcurrentProviders":
                        self._config.max_concurrent_providers,
                },
            },
            economic_asset_uid=request.economic_asset_uid,
        )

        # P8: durable append-only persistence; correctness never depends
        # on the cache or single-flight.
        self._store.put(snapshot)
        self._cache.put(fingerprint, snapshot.snapshot_id)
        self._events.record(AcquisitionEvent(
            event="acquisition.complete",
            correlation_id=correlation_id,
            request_fingerprint=fingerprint,
            snapshot_id=snapshot.snapshot_id,
            result_state=state.value,
            elapsed_ms=round((completed_mono - started_mono) * 1000, 3),
            cache="MISS", single_flight="new"))
        return snapshot

    # ------------------------------------------------------------------
    def _acquire_providers(
        self, request: AcquisitionRequest, correlation_id: str,
        fingerprint: str, started_mono: float,
    ) -> "list[ProviderResult]":
        """Run the requested provider acquisitions against the SERVICE-OWNED
        bounded pool (N01) with worker-side completion capture (N02).

        - ``max_concurrent_providers`` bounds the WHOLE service: capacity
          (a bounded semaphore) is acquired before dispatch and released
          only when the provider callable actually returns/raises inside
          the worker.  Coordinator timeouts NEVER release capacity for
          still-running work.
        - When no capacity is available the provider fails closed with
          the stable typed result ``PROVIDER_CAPACITY_EXHAUSTED`` —
          never an unbounded queue and never an indefinite block.
        - N02: the worker records its completion monotonic time
          immediately; ``completed_mono`` vs the immutable deadlines
          (provider window, total budget) decides TIMEOUT vs success —
          never the coordinator's observation order.
        - Providers are independent observations; one slow/failed
          provider never fabricates or discards another's preserved
          evidence (P5)."""
        names = sorted(request.sources)
        missing = [n for n in names if n not in self._providers]
        results: "list[ProviderResult]" = []
        per_timeout = self._config.per_provider_timeout_seconds
        total_deadline = started_mono + self._config.total_budget_seconds

        pool = getattr(self, "_provider_pool", None)
        if pool is None:
            # closed service: every provider fails closed
            for name in names:
                results.append(ProviderResult(
                    provider=name,
                    state=ProviderResultState.PROVIDER_ERROR,
                    elapsed_ms=0.0,
                    error_class="SERVICE_CLOSED"))
            return results

        futures: "dict[str, Any]" = {}
        provider_deadlines: "dict[str, float]" = {}
        if names:
            dispatch_mono = self._monotonic()
            for name in names:
                if name in missing:
                    continue
                # N01 bounded admission: non-blocking capacity check;
                # exhausted capacity fails closed instead of queueing.
                if not self._provider_capacity.acquire(blocking=False):
                    continue
                futures[name] = pool.submit(
                    self._run_provider_work, name, request,
                    dispatch_mono)
                provider_deadlines[name] = dispatch_mono + per_timeout
            for name in names:
                if name in missing:
                    results.append(ProviderResult(
                        provider=name,
                        state=ProviderResultState.PROVIDER_ERROR,
                        elapsed_ms=0.0,
                        error_class="PROVIDER_NOT_CONFIGURED"))
                    self._events.record(AcquisitionEvent(
                        event="acquisition.provider_result",
                        correlation_id=correlation_id,
                        request_fingerprint=fingerprint,
                        provider=name,
                        result_state="PROVIDER_ERROR",
                        error_class="PROVIDER_NOT_CONFIGURED"))
                    continue
                if name not in futures:
                    results.append(ProviderResult(
                        provider=name,
                        state=ProviderResultState.TIMEOUT,
                        elapsed_ms=0.0,
                        error_class="PROVIDER_CAPACITY_EXHAUSTED"))
                    self._events.record(AcquisitionEvent(
                        event="acquisition.provider_result",
                        correlation_id=correlation_id,
                        request_fingerprint=fingerprint,
                        provider=name,
                        result_state="TIMEOUT",
                        error_class="PROVIDER_CAPACITY_EXHAUSTED"))
                    continue
                future = futures[name]
                now = self._monotonic()
                limiting_deadline = min(provider_deadlines[name],
                                        total_deadline)
                envelope = None
                timed_out = False
                timeout_code = None
                if future.done():
                    # N02: the envelope carries the worker-captured
                    # completion time; the deadline decision below uses it
                    # (not future.done()) to accept or reject.
                    envelope = future.result()
                else:
                    remaining = limiting_deadline - now
                    if remaining <= 0:
                        timed_out = True
                        timeout_code = (
                            "TOTAL_BUDGET_EXHAUSTED"
                            if total_deadline <= provider_deadlines[name]
                            else "PER_PROVIDER_TIMEOUT")
                    else:
                        try:
                            envelope = future.result(timeout=remaining)
                        except FutureTimeoutError:
                            timed_out = True
                            timeout_code = (
                                "TOTAL_BUDGET_EXHAUSTED"
                                if total_deadline <= provider_deadlines[name]
                                else "PER_PROVIDER_TIMEOUT")
                if timed_out:
                    # N01: capacity stays held for still-running work;
                    # N02: the elapsed value is the authoritative deadline
                    # decision time, never delayed coordinator collection.
                    decision_mono = self._monotonic()
                    results.append(ProviderResult(
                        provider=name,
                        state=ProviderResultState.TIMEOUT,
                        elapsed_ms=round(
                            (decision_mono - dispatch_mono) * 1000, 3),
                        error_class=timeout_code))
                else:
                    # N02: the worker-captured completion time (inside the
                    # envelope) decides — a completion after the limiting
                    # deadline is a TIMEOUT even when future.done().
                    completed = envelope.completed_mono
                    if completed > limiting_deadline:
                        budget_limited = (
                            total_deadline <= provider_deadlines[name])
                        results.append(ProviderResult(
                            provider=name,
                            state=ProviderResultState.TIMEOUT,
                            elapsed_ms=round(
                                (completed - dispatch_mono) * 1000, 3),
                            error_class=(
                                "TOTAL_BUDGET_EXHAUSTED" if budget_limited
                                else "PER_PROVIDER_TIMEOUT")))
                    else:
                        results.append(self._classify_envelope(
                            name, envelope))
                result = results[-1]
                self._events.record(AcquisitionEvent(
                    event="acquisition.provider_result",
                    correlation_id=correlation_id,
                    request_fingerprint=fingerprint,
                    provider=result.provider,
                    result_state=result.state.value,
                    elapsed_ms=result.elapsed_ms,
                    error_class=result.error_class))
        return results

    def _run_provider_work(self, name: str, request: AcquisitionRequest,
                           dispatch_mono: float) -> ProviderExecutionOutcome:
        """Worker-side execution envelope (N02): runs one provider
        callable, captures the completion monotonic time IMMEDIATELY on
        return/raise, and releases the service capacity slot only when
        the real work is finished (never on coordinator timeout)."""
        completed_mono = None
        observation = None
        error = None
        try:
            observation = self._providers[name](request)
            completed_mono = self._monotonic()
        except BaseException as exc:  # noqa: BLE001 - captured in envelope
            completed_mono = self._monotonic()
            error = exc
        finally:
            self._provider_capacity.release()
        return ProviderExecutionOutcome(
            provider=name,
            dispatch_mono=dispatch_mono,
            completed_mono=completed_mono
            if completed_mono is not None else self._monotonic(),
            observation=observation,
            error=error,
        )

    def _classify_envelope(self, name: str,
                           envelope: ProviderExecutionOutcome) -> ProviderResult:
        """Classify a completed execution envelope into a typed
        provider result (P5/P12 vocabulary; A2/A3 rules preserved)."""
        elapsed = round(
            (envelope.completed_mono - envelope.dispatch_mono) * 1000, 3)
        observation = envelope.observation
        if envelope.error is not None:
            return ProviderResult(
                provider=name, state=ProviderResultState.TRANSPORT_ERROR,
                elapsed_ms=elapsed,
                error_class=type(envelope.error).__name__)
        if not isinstance(observation, Mapping):
            return ProviderResult(
                provider=name, state=ProviderResultState.INVALID_RESPONSE,
                elapsed_ms=elapsed, error_class="OBSERVATION_NOT_A_MAPPING")
        observed_at = observation.get("observedAt")
        if observed_at is not None and not isinstance(observed_at, str):
            return ProviderResult(
                provider=name, state=ProviderResultState.INVALID_RESPONSE,
                elapsed_ms=elapsed,
                error_class="OBSERVED_AT_MALFORMED")
        declared_error = observation.get("error")
        evidence = observation.get("evidence")
        # B3: classify the provider error field explicitly — absent/None is
        # valid no-error; a non-empty string is a declared provider failure
        # (PROVIDER_ERROR with the closed code PROVIDER_DECLARED_ERROR; the
        # raw provider-controlled text is never logged); anything else is
        # INVALID_RESPONSE with the stable code ERROR_FIELD_MALFORMED —
        # never ignored because evidence happens to be valid.
        if declared_error is not None:
            if (not isinstance(declared_error, str)
                    or not declared_error.strip()):
                return ProviderResult(
                    provider=name,
                    state=ProviderResultState.INVALID_RESPONSE,
                    elapsed_ms=elapsed, error_class="ERROR_FIELD_MALFORMED")
            if isinstance(evidence, Mapping):
                try:
                    ensure_canonical_evidence(evidence)
                except RuntimeContractError:
                    evidence = None  # malformed evidence rejected wholesale
            return ProviderResult(
                provider=name, state=ProviderResultState.PROVIDER_ERROR,
                elapsed_ms=elapsed, evidence=evidence,
                observed_at=observed_at,
                error_class="PROVIDER_DECLARED_ERROR")
        if not isinstance(evidence, Mapping):
            return ProviderResult(
                provider=name, state=ProviderResultState.INVALID_RESPONSE,
                elapsed_ms=elapsed, error_class="EVIDENCE_MISSING_OR_MALFORMED")
        # A2: the entire nested evidence must satisfy the shared canonical
        # contract before SUCCESS — non-canonical values become a typed
        # INVALID_RESPONSE with the stable EVIDENCE_NOT_CANONICAL code.
        try:
            ensure_canonical_evidence(evidence)
        except RuntimeContractError:
            return ProviderResult(
                provider=name, state=ProviderResultState.INVALID_RESPONSE,
                elapsed_ms=elapsed, error_class="EVIDENCE_NOT_CANONICAL")
        return ProviderResult(
            provider=name, state=ProviderResultState.SUCCESS,
            elapsed_ms=elapsed, evidence=evidence,
            observed_at=observed_at)
