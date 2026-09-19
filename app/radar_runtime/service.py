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
    SnapshotNotFoundError,
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


class _Flight:
    """One in-flight acquisition shared by single-flight waiters (P7)."""

    __slots__ = ("done", "snapshot", "error")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.snapshot: "AcquisitionSnapshot | None" = None
        self.error: "BaseException | None" = None


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
        """Run the requested provider acquisitions in a bounded pool (P11).
        Providers are independent observations; one slow/failed provider
        never fabricates or discards another's preserved evidence (P5)."""
        names = sorted(request.sources)
        missing = [n for n in names if n not in self._providers]
        results: "list[ProviderResult]" = []
        per_timeout = self._config.per_provider_timeout_seconds
        budget_deadline = started_mono + self._config.total_budget_seconds

        futures = {}
        if names:
            workers = min(len(names),
                          max(1, self._config.max_concurrent_providers))
            pool = ThreadPoolExecutor(max_workers=workers,
                                      thread_name_prefix="radar-acq")
            try:
                for name in names:
                    if name in missing:
                        continue
                    futures[name] = pool.submit(
                        self._providers[name], request)
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
                    future = futures[name]
                    remaining_budget = budget_deadline - self._monotonic()
                    wait = min(per_timeout, remaining_budget)
                    provider_started = self._monotonic()
                    if wait <= 0:
                        # P10: total acquisition budget exhausted — record
                        # the typed timeout instead of blocking forever.
                        future.cancel()
                        results.append(ProviderResult(
                            provider=name,
                            state=ProviderResultState.TIMEOUT,
                            elapsed_ms=0.0,
                            error_class="TOTAL_BUDGET_EXHAUSTED"))
                    else:
                        try:
                            observation = future.result(timeout=wait)
                            results.append(self._classify_success(
                                name, provider_started, observation))
                        except FutureTimeoutError:
                            results.append(ProviderResult(
                                provider=name,
                                state=ProviderResultState.TIMEOUT,
                                elapsed_ms=round(
                                    (self._monotonic() - provider_started)
                                    * 1000, 3),
                                error_class="PER_PROVIDER_TIMEOUT"))
                        except Exception as exc:  # transport boundary failure
                            results.append(ProviderResult(
                                provider=name,
                                state=ProviderResultState.TRANSPORT_ERROR,
                                elapsed_ms=round(
                                    (self._monotonic() - provider_started)
                                    * 1000, 3),
                                error_class=type(exc).__name__))
                    result = results[-1]
                    self._events.record(AcquisitionEvent(
                        event="acquisition.provider_result",
                        correlation_id=correlation_id,
                        request_fingerprint=fingerprint,
                        provider=result.provider,
                        result_state=result.state.value,
                        elapsed_ms=result.elapsed_ms,
                        error_class=result.error_class))
            finally:
                # Bounded shutdown: pending/lingering work is cancelled;
                # timeouts already recorded preserve honest partial state.
                pool.shutdown(wait=False, cancel_futures=True)
        return results

    def _classify_success(
        self, name: str, provider_started: float,
        observation: Any,
    ) -> ProviderResult:
        elapsed = round((self._monotonic() - provider_started) * 1000, 3)
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
        if isinstance(declared_error, str) and declared_error.strip():
            return ProviderResult(
                provider=name, state=ProviderResultState.PROVIDER_ERROR,
                elapsed_ms=elapsed,
                evidence=evidence if isinstance(evidence, Mapping) else None,
                observed_at=observed_at, error_class=declared_error)
        if not isinstance(evidence, Mapping):
            return ProviderResult(
                provider=name, state=ProviderResultState.INVALID_RESPONSE,
                elapsed_ms=elapsed, error_class="EVIDENCE_MISSING_OR_MALFORMED")
        return ProviderResult(
            provider=name, state=ProviderResultState.SUCCESS,
            elapsed_ms=elapsed, evidence=evidence,
            observed_at=observed_at)
