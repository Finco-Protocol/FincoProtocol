"""JEV Radar Intelligence service: exact identity -> features -> typed Jev judgments.

Read-only. No history write, no engine/Model/Verify/certificate call, no canonical mutation.
``evaluate_intelligence`` never raises: every failure is a typed, honest state.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Mapping, Protocol

from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID

from .cache import IntelligenceCache, cache_key
from .config import JevIntelligenceConfig, api_key
from .contracts import (PROVIDER, QUESTION_SCHEMA_VERSION, Diagnostics, IntelligenceResult,
                        IntelligenceState, JevMode)
from .features import POINT_LIMIT, FeatureUnavailable, build_feature_state
from .questions import build_request, parse_response
from .telemetry import TELEMETRY, Telemetry, TelemetryRecord, now_iso
from .transport import JevHttpConfig, JevTransportError, TypeSafeJevTransport

CurrentProvider = Callable[[str], "tuple[str, Mapping[str, object]]"]
RangesProvider = Callable[[str, datetime], Mapping[str, object]]
PointsProvider = Callable[[str], list]


class JevTransport(Protocol):
    def evaluate(self, request: Mapping[str, object]) -> Mapping[str, object]: ...


class _RateLimiter:
    """Process-wide fixed-window limiter protecting spend from unauthenticated read traffic.

    Scope is ONE Python process. It is not host-global: with N web workers the theoretical
    provider-call ceiling is about N x ``max_evaluations_per_minute`` until a shared limiter exists.
    """

    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._per_minute = per_minute
        self._clock = clock
        self._lock = threading.Lock()
        self._window_start = clock()
        self._count = 0

    def allow(self) -> bool:
        with self._lock:
            now = self._clock()
            if now - self._window_start >= 60:
                self._window_start, self._count = now, 0
            if self._count >= self._per_minute:
                return False
            self._count += 1
            return True


_CACHE = IntelligenceCache()
_LIMITERS: dict[int, _RateLimiter] = {}
_LIMITER_LOCK = threading.Lock()


def _limiter(per_minute: int) -> _RateLimiter:
    with _LIMITER_LOCK:
        return _LIMITERS.setdefault(per_minute, _RateLimiter(per_minute))


def default_current_provider(canonical_id: str) -> tuple[str, Mapping[str, object]]:
    """Canonical current observation via the existing read-only R-LIVE service (no writes)."""
    from app.api.v1_1 import institutional
    return institutional.get_r_live(canonical_id)


def default_ranges_provider(canonical_id: str, as_of: datetime) -> Mapping[str, object]:
    from app.radar_rwa.r_live_service import read_r_live_ranges
    return read_r_live_ranges(canonical_id, as_of=as_of)


def default_points_provider(canonical_id: str) -> list:
    from app.radar_rwa.r_live_service import read_r_live_history
    return read_r_live_history(canonical_id, limit=POINT_LIMIT)


def _result(state: IntelligenceState, canonical_id: str, reason: str, *, mode: JevMode,
            uid: str | None = None, config: JevIntelligenceConfig | None = None,
            diagnostics: Diagnostics | None = None, **extra) -> IntelligenceResult:
    return IntelligenceResult(
        state=state, canonical_id=canonical_id, economic_asset_uid=uid, reason=reason,
        requested_model=config.model if config else None, mode=mode,
        evaluated_at=datetime.now(timezone.utc),
        diagnostics=diagnostics or Diagnostics(cache_status="NOT_APPLICABLE"), **extra)


def _record(telemetry: Telemetry, result: IntelligenceResult) -> IntelligenceResult:
    d = result.diagnostics
    telemetry.record(TelemetryRecord(
        recorded_at=now_iso(), canonical_id=result.canonical_id, mode=result.mode.value,
        outcome=result.state.value if result.reason is None else result.reason,
        cache_status=d.cache_status, latency_ms=None if d.latency_ms is None else str(d.latency_ms),
        requested_model=result.requested_model, resolved_model=result.resolved_model,
        provider_request_id=d.provider_request_id, usage=d.usage, failure_category=d.failure_category))
    return result


def _meta(response: Mapping[str, object]) -> tuple[Decimal | None, int | None, str | None, tuple]:
    meta = response.get("_transport_meta")
    meta = meta if isinstance(meta, Mapping) else {}
    latency = None
    try:
        latency = Decimal(str(meta["latency_ms"])) if meta.get("latency_ms") is not None else None
        if latency is not None and (not latency.is_finite() or latency < 0):
            latency = None
    except Exception:
        latency = None
    attempts = meta.get("attempt_count")
    attempts = attempts if isinstance(attempts, int) and not isinstance(attempts, bool) and attempts > 0 else None
    request_id = meta.get("provider_request_id")
    request_id = request_id if isinstance(request_id, str) else None
    usage_raw = response.get("usage")
    usage: list[tuple[str, str]] = []
    if isinstance(usage_raw, Mapping):
        for key in sorted(usage_raw):
            item = usage_raw[key]
            if isinstance(key, str) and key.strip() and isinstance(item, (str, int, float)) \
                    and not isinstance(item, bool):
                usage.append((key, str(item)))
    return latency, attempts, request_id, tuple(usage)


def evaluate_intelligence(
    canonical_id: str, *, config: JevIntelligenceConfig | None = None,
    transport: JevTransport | None = None,
    current_provider: CurrentProvider = default_current_provider,
    ranges_provider: RangesProvider = default_ranges_provider,
    points_provider: PointsProvider = default_points_provider,
    cache: IntelligenceCache | None = None, telemetry: Telemetry | None = None,
    environ: Mapping[str, str] | None = None,
) -> IntelligenceResult:
    """Evaluate one exact approved identity. Never raises; never fabricates intelligence."""
    config = config or JevIntelligenceConfig.from_env(environ)
    telemetry = telemetry or TELEMETRY
    cache = cache or _CACHE
    mode = config.mode

    if not config.enabled:  # zero Jev calls, zero canonical reads
        return _result(IntelligenceState.DISABLED, canonical_id, "JEV_INTELLIGENCE_DISABLED",
                       mode=mode, config=config)

    policy = APPROVED_BY_CANONICAL_ID.get(canonical_id) if isinstance(canonical_id, str) else None
    if policy is None:  # exact identity only: no ticker, name or fuzzy fallback
        return _record(telemetry, _result(IntelligenceState.UNAVAILABLE, str(canonical_id)[:128],
                                          "ASSET_UID_INVALID", mode=mode, config=config))
    uid = policy.economic_asset_uid

    def fail(reason: str, **kwargs) -> IntelligenceResult:
        return _record(telemetry, _result(IntelligenceState.UNAVAILABLE, canonical_id, reason,
                                          mode=mode, uid=uid, config=config, **kwargs))

    try:
        current_state, current = current_provider(canonical_id)
    except Exception:
        return fail("CANONICAL_CURRENT_UNAVAILABLE")
    if not isinstance(current, Mapping):
        return fail("CANONICAL_CURRENT_UNAVAILABLE")
    if current_state == "AVAILABLE":  # identity substitution guard on the returned evidence
        exact = current.get("exact_asset_key")
        if (not isinstance(exact, Mapping) or exact.get("canonical_id") != canonical_id
                or current.get("economic_asset_uid") != uid):
            return fail("CANONICAL_IDENTITY_MISMATCH")

    try:
        freshness = current.get("freshness") if isinstance(current.get("freshness"), Mapping) else {}
        retrieved = freshness.get("retrieved_at") if freshness else None
        as_of = datetime.fromisoformat(retrieved) if isinstance(retrieved, str) else None
        ranges = ranges_provider(canonical_id, as_of) if as_of and current_state == "AVAILABLE" else None
        points = points_provider(canonical_id) if ranges is not None else None
    except Exception:
        return fail("HISTORY_UNAVAILABLE")

    try:
        features = build_feature_state(current_state=current_state, current=current,
                                       ranges=ranges, points=points)
    except FeatureUnavailable as exc:
        return fail(exc.reason)

    key = cache_key(uid, features.input_fingerprint, QUESTION_SCHEMA_VERSION, config.model,
                    features.observation_digest)

    def compute() -> IntelligenceResult:
        key_value = api_key(environ)
        jev = transport
        if jev is None:
            if key_value is None:
                return _result(IntelligenceState.UNAVAILABLE, canonical_id, "JEV_API_KEY_NOT_CONFIGURED",
                               mode=mode, uid=uid, config=config,
                               observation_digest=features.observation_digest,
                               input_fingerprint=features.input_fingerprint, as_of=features.as_of)
            jev = TypeSafeJevTransport(key_value, config=JevHttpConfig())
        if not _limiter(config.max_evaluations_per_minute).allow():
            return _result(IntelligenceState.UNAVAILABLE, canonical_id, "JEV_RATE_LIMITED",
                           mode=mode, uid=uid, config=config,
                           observation_digest=features.observation_digest,
                           input_fingerprint=features.input_fingerprint, as_of=features.as_of)
        common = dict(mode=mode, uid=uid, config=config,
                      observation_digest=features.observation_digest,
                      input_fingerprint=features.input_fingerprint, as_of=features.as_of,
                      sources=features.sources)
        try:
            response = jev.evaluate(build_request(features, model=config.model))
        except Exception as exc:
            category = getattr(exc, "failure_category", "NETWORK")
            diag = Diagnostics(cache_status="MISS",
                               latency_ms=getattr(exc, "latency_ms", None) if isinstance(
                                   getattr(exc, "latency_ms", None), Decimal) else None,
                               attempt_count=getattr(exc, "attempt_count", None) if isinstance(
                                   getattr(exc, "attempt_count", None), int) else None,
                               failure_category=category if isinstance(category, str) else "NETWORK")
            return _result(IntelligenceState.UNAVAILABLE, canonical_id, "JEV_TRANSPORT_UNAVAILABLE",
                           diagnostics=diag, **common)
        if not isinstance(response, Mapping):
            return _result(IntelligenceState.INVALID_RESPONSE, canonical_id, "JEV_RESPONSE_NOT_MAPPING",
                           diagnostics=Diagnostics(cache_status="MISS", failure_category="INVALID_RESPONSE"),
                           **common)
        latency, attempts, request_id, usage = _meta(response)
        diag = Diagnostics(cache_status="MISS", latency_ms=latency, attempt_count=attempts,
                           provider_request_id=request_id, usage=usage)
        try:
            regime, attention, resolved = parse_response(response)
        except (ValueError, TypeError) as exc:
            from dataclasses import replace
            return _result(IntelligenceState.INVALID_RESPONSE, canonical_id,
                           str(exc) or "JEV_RESPONSE_INVALID",
                           diagnostics=replace(diag, failure_category="INVALID_RESPONSE"), **common)
        return IntelligenceResult(
            state=IntelligenceState.AVAILABLE, canonical_id=canonical_id, economic_asset_uid=uid,
            observation_digest=features.observation_digest, input_fingerprint=features.input_fingerprint,
            market_regime=regime, attention=attention, requested_model=config.model,
            resolved_model=resolved, evaluated_at=datetime.now(timezone.utc), as_of=features.as_of,
            sources=features.sources, mode=mode, diagnostics=diag)

    try:
        result, _status = cache.get_or_compute(key, features.ttl_seconds, compute)
    except Exception:
        return fail("JEV_EVALUATION_FAILED")
    return _record(telemetry, result)


def evaluate_shadow(canonical_id: str, **kwargs) -> IntelligenceResult:
    """Operator/job entry point for SHADOW mode: evaluate and record telemetry only.

    The caller must not publish the result. ``evaluate_intelligence`` already records sanitized
    telemetry; this wrapper refuses to run unless the mode is SHADOW.
    """
    config = kwargs.get("config") or JevIntelligenceConfig.from_env(kwargs.get("environ"))
    if config.mode is not JevMode.SHADOW:
        return _result(IntelligenceState.DISABLED, canonical_id, "JEV_SHADOW_MODE_NOT_ACTIVE",
                       mode=config.mode, config=config)
    return evaluate_intelligence(canonical_id, **kwargs)
