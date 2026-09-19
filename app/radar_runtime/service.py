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


class _ProviderExecutionState:
    """B1: observable worker-completion authority for one provider call.

    The worker publishes the minimal authoritative completion state —
    ``completed`` flag, ``completed_mono``, and the captured
    observation/error — ATOMICALLY (under ``lock``, followed by
    ``completed_event.set()``) at the SAME worker boundary where
    ``completed_mono`` is captured, i.e. immediately when the provider
    callable returns/raises.  The full envelope publication (and Future
    completion) may happen any time later without affecting the deadline
    decision: the coordinator reads the completion marker, not the
    Future.  Explicit Lock/Event synchronization defines the visibility
    contract; no reliance on incidental dict atomicity."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.completed_event = threading.Event()
        self.envelope_event = threading.Event()
        self.completed = False
        self.completed_mono: "float | None" = None
        self.observation: "Any" = None
        self.error: "BaseException | None" = None
        self.envelope: "ProviderExecutionOutcome | None" = None


def _resolve_deadline_outcome(
    state_completed: bool,
    completed_mono: "float | None",
    provider_deadline: float, total_deadline: float,
    decision_mono: float,
) -> "tuple[bool, str | None]":
    """A2/B1: THE one canonical production deadline-decision path.

    Returns ``(timed_out, error_class)``.  ``state_completed`` reflects
    the worker-published completion marker; ``completed_mono`` is the
    worker-captured completion time.  Future publication timing,
    ``future.done()`` and coordinator collection order are scheduling
    details only.

    - Completed provider: ``completed_mono <= limiting_deadline`` (where
      ``limiting = min(provider_deadline, total_deadline)``) means the
      deadline itself did not invalidate the result — including
      ``completed_mono == limiting_deadline``; ``>`` means timeout.
    - Still-running provider (no completion marker at decision time): the
      decision point is at/after the limiting deadline, so it is a
      TIMEOUT — ``decision_mono == limiting_deadline`` while still
      running is a different state from a completed-at-deadline one.
    - Classification names the deadline that was actually limiting.  For
      the exact tie ``provider_deadline == total_deadline`` the reviewed
      contract is preserved: ``TOTAL_BUDGET_EXHAUSTED``."""
    limiting = min(provider_deadline, total_deadline)
    timeout_code = (
        "TOTAL_BUDGET_EXHAUSTED" if total_deadline <= provider_deadline
        else "PER_PROVIDER_TIMEOUT")
    if state_completed:
        if completed_mono is not None and completed_mono <= limiting:
            return (False, None)
        return (True, timeout_code)
    if decision_mono >= limiting:
        return (True, timeout_code)
    return (False, None)


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
        # A1 lifecycle/admission protocol: ``_lifecycle_lock`` serializes
        # admission (capacity acquire + executor submit) against
        # ``close()`` so a concurrent close can never produce an
        # ambiguous admitted-but-shutdown state; ``_closed`` flips before
        # the pool shuts down.
        self._lifecycle_lock = threading.RLock()
        self._closed = False

    def close(self) -> None:
        """A1: release the service-owned provider executor.  Idempotent.

        Admission/submission is serialized against closure through
        ``_lifecycle_lock``: once ``_closed`` is set, no new provider work
        is admitted into a shutting-down executor, so a concurrent close
        can never leak a capacity slot or leak a raw executor
        ``RuntimeError``.  Admitted work is NEVER cancelled before its
        worker takes ownership (``shutdown`` is called WITHOUT
        ``cancel_futures``) — every admitted slot has exactly one owner
        (its worker) and exactly one release path (the worker's finally),
        so no slot can leak or double-release.  Already-running Python
        provider callables cannot be force-killed and keep their slot
        until natural completion."""
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
            pool = getattr(self, "_provider_pool", None)
            self._provider_pool = None
        if pool is not None:
            # No cancel_futures: admitted work is never cancelled before
            # its worker starts; queued work drains and releases its
            # capacity exactly once through the worker's finally.
            pool.shutdown(wait=False)

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

        futures: "dict[str, Any] | None" = None
        states: "dict[str, _ProviderExecutionState]" = {}
        provider_deadlines: "dict[str, float]" = {}
        if names:
            dispatch_mono = self._monotonic()
            for name in names:
                if name in missing:
                    continue
                state = _ProviderExecutionState()
                # A1: admission (capacity acquire) + executor submit are
                # serialized against close() through the lifecycle lock,
                # so an admitted slot always lands on a live executor and
                # has exactly one owner (its worker) and exactly one
                # release path (the worker's finally).
                with self._lifecycle_lock:
                    if self._closed or self._provider_pool is None:
                        results.append(ProviderResult(
                            provider=name,
                            state=ProviderResultState.PROVIDER_ERROR,
                            elapsed_ms=0.0,
                            error_class="SERVICE_CLOSED"))
                        self._events.record(AcquisitionEvent(
                            event="acquisition.provider_result",
                            correlation_id=correlation_id,
                            request_fingerprint=fingerprint,
                            provider=name,
                            result_state="PROVIDER_ERROR",
                            error_class="SERVICE_CLOSED"))
                        continue
                    # N01 bounded admission: non-blocking capacity check;
                    # exhausted capacity fails closed instead of queueing.
                    if not self._provider_capacity.acquire(blocking=False):
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
                    try:
                        future = self._provider_pool.submit(
                            self._run_provider_work, name, request,
                            dispatch_mono, state)
                    except RuntimeError:
                        # A1 submit failure after admission (executor shut
                        # down concurrently): release the slot EXACTLY ONCE
                        # here and fail closed with a typed result — no raw
                        # executor exception may escape.
                        self._provider_capacity.release()
                        results.append(ProviderResult(
                            provider=name,
                            state=ProviderResultState.PROVIDER_ERROR,
                            elapsed_ms=0.0,
                            error_class="SERVICE_CLOSED"))
                        self._events.record(AcquisitionEvent(
                            event="acquisition.provider_result",
                            correlation_id=correlation_id,
                            request_fingerprint=fingerprint,
                            provider=name,
                            result_state="PROVIDER_ERROR",
                            error_class="SERVICE_CLOSED"))
                        continue
                futures = futures or {}
                futures[name] = future
                states[name] = state
                provider_deadlines[name] = dispatch_mono + per_timeout
        else:
            futures = {}
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
            if name not in provider_deadlines:
                # admission failed closed above and already recorded
                continue
            future = futures[name]
            state = states[name]
            provider_deadline = provider_deadlines[name]
            limiting_deadline = min(provider_deadline, total_deadline)
            # A2/B1: scheduling only — the coordinator waits on the
            # worker-published completion EVENT until the limiting
            # deadline; Future publication timing is never consulted for
            # the deadline decision.
            if not state.completed_event.is_set():
                # wait AT MOST until the limiting deadline; a waiter may
                # wake slightly early (platform timer granularity), so the
                # loop re-checks instead of deciding before the deadline
                while not state.completed_event.is_set():
                    now = self._monotonic()
                    remaining = limiting_deadline - now
                    if remaining <= 0:
                        break
                    state.completed_event.wait(remaining)
            # B1/section 5: ONE canonical production deadline authority.
            timed_out, timeout_code = _resolve_deadline_outcome(
                state.completed, state.completed_mono, provider_deadline,
                total_deadline, self._monotonic())
            if timed_out:
                # B2: still-running work is timed out AT the limiting
                # deadline (elapsed = limiting - dispatch, immune to
                # coordinator processing delay); completed-late work
                # keeps its actual completion interval.
                effective_mono = (
                    state.completed_mono if state.completed
                    else limiting_deadline)
                results.append(ProviderResult(
                    provider=name,
                    state=ProviderResultState.TIMEOUT,
                    elapsed_ms=round(
                        (effective_mono - dispatch_mono) * 1000, 3),
                    error_class=timeout_code))
            elif state.completed:
                # B1.1/B1.3: the callable completed on time — classify the
                # genuine captured outcome regardless of publication delay
                # (SUCCESS / PROVIDER_ERROR / INVALID_RESPONSE /
                # TRANSPORT_ERROR according to the actual result).
                elapsed = round(
                    (state.completed_mono - dispatch_mono) * 1000, 3)
                results.append(self._classify_observation(
                    name, elapsed, state.observation, state.error))
            else:
                # B1/section 6 defensive fail-closed: completion was
                # authoritatively signaled but no observation can ever be
                # obtained (invariant violation) — typed, never fabricated
                results.append(ProviderResult(
                    provider=name,
                    state=ProviderResultState.INVALID_RESPONSE,
                    elapsed_ms=round(
                        (self._monotonic() - dispatch_mono) * 1000, 3),
                    error_class="OUTCOME_NOT_CAPTURED"))
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
                           dispatch_mono: float,
                           state: "_ProviderExecutionState") -> ProviderExecutionOutcome:
        """Worker-side execution (N02/B1): runs one provider callable and
        publishes the authoritative completion state ATOMICALLY at the
        capture boundary — ``completed_mono``, the captured
        observation/error and the completed marker become observable to
        the coordinator in the same synchronized block, BEFORE envelope
        construction, capacity release and Future completion.  A worker
        descheduled after the callable returned therefore can never hide
        an on-time completion from the deadline decision.

        The capacity slot is released exactly once by this worker, after
        the completion marker is observable."""
        try:
            observation = self._providers[name](request)
            completed_mono = self._monotonic()
            error = None
        except BaseException as exc:  # noqa: BLE001 - captured in state
            completed_mono = self._monotonic()
            observation = None
            error = exc
        # B1: authoritative completion publication at the capture boundary
        with state.lock:
            state.completed_mono = completed_mono
            state.observation = observation
            state.error = error
            state.completed = True
            state.completed_event.set()
        # A1: exactly-once capacity release — the slot's single owner is
        # this worker and its single release path is here, after the
        # completion marker is observable.
        self._provider_capacity.release()
        # Envelope publication follows; it is bookkeeping only (the
        # Future result is not the deadline authority) and may be
        # arbitrarily delayed without affecting outcomes.
        envelope = ProviderExecutionOutcome(
            provider=name,
            dispatch_mono=dispatch_mono,
            completed_mono=completed_mono,
            observation=observation,
            error=error,
        )
        with state.lock:
            state.envelope = envelope
            state.envelope_event.set()
        return envelope

    def _classify_observation(self, name: str, elapsed: float,
                              observation: "Any",
                              error: "BaseException | None") -> ProviderResult:
        """Classify a captured provider observation into a typed
        provider result (P5/P12 vocabulary; A2/A3 rules preserved)."""
        if error is not None:
            return ProviderResult(
                provider=name, state=ProviderResultState.TRANSPORT_ERROR,
                elapsed_ms=elapsed,
                error_class=type(error).__name__)
        observation = observation
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
