"""FINCO Yield Intelligence V1 -- a DERIVED READ MODEL over canonical history.

    source observation -> canonical history -> intelligence derivation

This module owns NO source truth, persists nothing and has no second
collector, history store or freshness classifier.  It reads history ONLY
through ``YieldHistoryStore.latest / prior / window`` and classifies freshness
ONLY through ``freshness.evaluate_freshness``.

No forecasting, no interpolation, no invented values, no recommendation
vocabulary.  ``None`` is UNAVAILABLE; a factual ``0`` is data.

Time model
----------
One evaluation uses ONE explicit, timezone-aware ``as_of`` (never read from the
clock inside a calculation).  ``as_of`` is used for freshness.  Comparison
horizons are anchored on the latest observation's own ``observed_at``:

    cutoff(H) = latest.observed_at - H            (H = 24h, 7d)

Baseline rule (exact, for each horizon H)
-----------------------------------------
The baseline is the single most recent canonical observation whose
``observed_at <= cutoff(H)``, obtained from ``YieldHistoryStore.prior`` with
``before = cutoff + 1 microsecond`` (``prior`` is strictly-before; one
microsecond is the timestamp resolution, so ``<= cutoff`` is exact).  An
observation AFTER the cutoff is never a baseline, however close; values are
never interpolated.  If none exists the horizon comparison is UNAVAILABLE
(``NO_BASELINE``), never a zero delta.

Formulas (Decimal only; APY values are fractions, 0.04 == 4 %)
-------------------------------------------------------------
    apy_delta_fraction = latest.apy_total - baseline.apy_total
    apy_delta_bps      = apy_delta_fraction * 10000
    tvl_delta_usd      = latest.tvl_usd - baseline.tvl_usd
    tvl_delta_fraction = latest.tvl_usd / baseline.tvl_usd - 1   (baseline > 0 only)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from .alerts_eval import _row_field, _row_observed_at, _source_ref_from_row
from .freshness import evaluate_freshness
from .history import YieldHistoryStore

INTELLIGENCE_SCHEMA = "YIELD_INTELLIGENCE_V1"

HORIZONS: tuple[tuple[str, timedelta], ...] = (
    ("24h", timedelta(hours=24)),
    ("7d", timedelta(days=7)),
    ("30d", timedelta(days=30)),
)

# APY volatility (sigma) requires this many numeric APY observations inside a
# window before a FINCO-computed standard deviation is exposed; below it the
# statistic stays UNAVAILABLE rather than noisy.
SIGMA_MIN_OBSERVATIONS = 10
_PRIOR_RESOLUTION = timedelta(microseconds=1)
_BPS = Decimal(10000)


class IntelligenceError(ValueError):
    """Invalid evaluation input (fail closed)."""


class IntelligenceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"   # no latest observation


class Coverage(str, Enum):
    AVAILABLE = "AVAILABLE"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"   # no baseline at/before the cutoff
    NO_NUMERIC_APY = "NO_NUMERIC_APY"               # no numeric APY in the window
    NO_NUMERIC_TVL = "NO_NUMERIC_TVL"               # no numeric TVL in the window


class DeltaState(str, Enum):
    AVAILABLE = "AVAILABLE"
    NO_BASELINE = "NO_BASELINE"
    LATEST_VALUE_MISSING = "LATEST_VALUE_MISSING"
    BASELINE_VALUE_MISSING = "BASELINE_VALUE_MISSING"
    UNDEFINED_ZERO_BASELINE = "UNDEFINED_ZERO_BASELINE"   # percentage only


class Direction(str, Enum):
    """Presentation of a factual numeric delta's sign.  Not a judgement."""

    UP = "UP"
    DOWN = "DOWN"
    UNCHANGED = "UNCHANGED"
    UNAVAILABLE = "UNAVAILABLE"


# ── result types (all frozen; serialised via evidence_v1.canonical_json) ──────

@dataclass(frozen=True)
class ObservationPoint:
    observed_at: datetime
    observation_hash: str | None
    source_authority: str | None
    apy_total: Decimal | None
    tvl_usd: Decimal | None


@dataclass(frozen=True)
class FreshnessView:
    state: str
    age_seconds: int | None
    reason: str


@dataclass(frozen=True)
class ApyDelta:
    state: DeltaState
    delta_fraction: Decimal | None
    delta_bps: Decimal | None
    direction: Direction


@dataclass(frozen=True)
class TvlDelta:
    state: DeltaState
    delta_usd: Decimal | None
    direction: Direction
    fraction_state: DeltaState
    delta_fraction: Decimal | None


@dataclass(frozen=True)
class WindowStat:
    observation_count: int
    available_count: int
    minimum: Decimal | None
    maximum: Decimal | None
    range: Decimal | None
    mean: Decimal | None = None   # plain arithmetic mean of available values


@dataclass(frozen=True)
class HorizonIntelligence:
    horizon: str
    horizon_seconds: int
    cutoff: datetime
    coverage: Coverage
    baseline: ObservationPoint | None
    baseline_offset_seconds: int | None   # cutoff - baseline.observed_at (>= 0)
    observation_count: int                # observations in [cutoff, latest]
    apy_delta: ApyDelta
    tvl_delta: TvlDelta
    apy_window: WindowStat
    tvl_window: WindowStat
    # FINCO-computed APY volatility over THIS window (population standard
    # deviation of available APY observations, APY fractions).  ``None`` =
    # UNAVAILABLE (fewer than SIGMA_MIN_OBSERVATIONS numeric points).  Source
    # label is always FINCO_HISTORICAL -- never mixed with provider-native
    # statistics.
    apy_sigma: Decimal | None = None
    apy_sigma_source: str | None = None


@dataclass(frozen=True)
class YieldIntelligence:
    schema: str
    uid: str
    as_of: datetime
    status: IntelligenceStatus
    latest: ObservationPoint | None
    freshness: FreshnessView | None
    horizons: tuple[HorizonIntelligence, ...]

    def horizon(self, name: str) -> HorizonIntelligence | None:
        return next((h for h in self.horizons if h.horizon == name), None)


# ── internals ────────────────────────────────────────────────────────────────

class _ReadOnceHistory(YieldHistoryStore):
    """The canonical store, with one file read shared by every read call of a
    single evaluation.  It only overrides ``read_all``; ``latest`` / ``prior`` /
    ``window`` are the canonical implementations.  Never used for appends."""

    def __init__(self, path):
        super().__init__(path)
        self._rows: list[dict[str, Any]] | None = None

    def read_all(self) -> list[dict[str, Any]]:
        if self._rows is None:
            self._rows = super().read_all()
        return self._rows


def _decimal(value: Any) -> Decimal | None:
    """Row value -> finite Decimal, else None (MISSING, never zero)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, (int, float, str)):
        try:
            number = Decimal(str(value).strip())
        except InvalidOperation:
            return None
    else:
        return None
    return number if number.is_finite() else None


def _point(row: dict[str, Any]) -> ObservationPoint:
    return ObservationPoint(
        observed_at=_row_observed_at(row),
        observation_hash=row.get("observation_hash") or None,
        source_authority=row.get("source_authority") or None,
        apy_total=_decimal(_row_field(row, "apy_total")),
        tvl_usd=_decimal(_row_field(row, "tvl_usd")),
    )


def _direction(delta: Decimal | None) -> Direction:
    if delta is None:
        return Direction.UNAVAILABLE
    if delta > 0:
        return Direction.UP
    if delta < 0:
        return Direction.DOWN
    return Direction.UNCHANGED


def _window_stat(points: list[ObservationPoint], field: str) -> WindowStat:
    values = [getattr(p, field) for p in points if getattr(p, field) is not None]
    if not values:
        return WindowStat(len(points), 0, None, None, None)
    lo, hi = min(values), max(values)
    mean = sum(values, Decimal(0)) / Decimal(len(values))
    return WindowStat(len(points), len(values), lo, hi, hi - lo, mean)


def _apy_delta(latest: ObservationPoint, base: ObservationPoint | None) -> ApyDelta:
    if base is None:
        return ApyDelta(DeltaState.NO_BASELINE, None, None, Direction.UNAVAILABLE)
    if latest.apy_total is None:
        return ApyDelta(DeltaState.LATEST_VALUE_MISSING, None, None, Direction.UNAVAILABLE)
    if base.apy_total is None:
        return ApyDelta(DeltaState.BASELINE_VALUE_MISSING, None, None, Direction.UNAVAILABLE)
    fraction = latest.apy_total - base.apy_total
    return ApyDelta(DeltaState.AVAILABLE, fraction, fraction * _BPS, _direction(fraction))


def _tvl_delta(latest: ObservationPoint, base: ObservationPoint | None) -> TvlDelta:
    if base is None:
        return TvlDelta(DeltaState.NO_BASELINE, None, Direction.UNAVAILABLE, DeltaState.NO_BASELINE, None)
    if latest.tvl_usd is None:
        return TvlDelta(DeltaState.LATEST_VALUE_MISSING, None, Direction.UNAVAILABLE,
                        DeltaState.LATEST_VALUE_MISSING, None)
    if base.tvl_usd is None:
        return TvlDelta(DeltaState.BASELINE_VALUE_MISSING, None, Direction.UNAVAILABLE,
                        DeltaState.BASELINE_VALUE_MISSING, None)
    delta = latest.tvl_usd - base.tvl_usd
    if base.tvl_usd > 0:
        fraction_state, fraction = DeltaState.AVAILABLE, latest.tvl_usd / base.tvl_usd - 1
    else:   # factual zero (or negative, rejected upstream) baseline: % undefined
        fraction_state, fraction = DeltaState.UNDEFINED_ZERO_BASELINE, None
    return TvlDelta(DeltaState.AVAILABLE, delta, _direction(delta), fraction_state, fraction)


def _coverage(base: ObservationPoint | None, apy: WindowStat, tvl: WindowStat) -> Coverage:
    if base is None:
        return Coverage.INSUFFICIENT_HISTORY
    if apy.available_count == 0:
        return Coverage.NO_NUMERIC_APY
    if tvl.available_count == 0:
        return Coverage.NO_NUMERIC_TVL
    return Coverage.AVAILABLE


def _apy_sigma(points: list[ObservationPoint]) -> Decimal | None:
    """Population standard deviation of available APY values in a window.

    FINCO_HISTORICAL statistic over canonical observations only; UNAVAILABLE
    below SIGMA_MIN_OBSERVATIONS (never a noisy or zero-padded value)."""
    values = [p.apy_total for p in points if p.apy_total is not None]
    if len(values) < SIGMA_MIN_OBSERVATIONS:
        return None
    count = Decimal(len(values))
    mean = sum(values, Decimal(0)) / count
    variance = sum(((v - mean) ** 2 for v in values), Decimal(0)) / count
    return variance.sqrt()


def _horizon(store: YieldHistoryStore, uid: str, latest: ObservationPoint,
             name: str, span: timedelta) -> HorizonIntelligence:
    cutoff = latest.observed_at - span
    prior = store.prior(uid, before=cutoff + _PRIOR_RESOLUTION, limit=1)
    baseline = _point(prior[-1]) if prior else None
    window_rows = store.window(uid, since=cutoff, until=latest.observed_at)
    points = [_point(r) for r in window_rows]
    apy_w, tvl_w = _window_stat(points, "apy_total"), _window_stat(points, "tvl_usd")
    offset = None if baseline is None else int((cutoff - baseline.observed_at).total_seconds())
    sigma = _apy_sigma(points)
    return HorizonIntelligence(
        horizon=name,
        horizon_seconds=int(span.total_seconds()),
        cutoff=cutoff,
        coverage=_coverage(baseline, apy_w, tvl_w),
        baseline=baseline,
        baseline_offset_seconds=offset,
        observation_count=len(points),
        apy_delta=_apy_delta(latest, baseline),
        tvl_delta=_tvl_delta(latest, baseline),
        apy_window=apy_w,
        tvl_window=tvl_w,
        apy_sigma=sigma,
        apy_sigma_source=("FINCO_HISTORICAL" if sigma is not None else None),
    )


# ── public API ───────────────────────────────────────────────────────────────

def build_intelligence(
    store: YieldHistoryStore, uid: str, *, as_of: datetime,
) -> YieldIntelligence:
    """Derive intelligence for one canonical UID from canonical history.

    ``as_of`` must be a timezone-aware datetime; it is the single time anchor
    for freshness.  Raises ``IntelligenceError`` for a naive/invalid ``as_of``
    or an empty uid; history read errors propagate to the caller (typed
    unavailability is the caller's decision, never a zero).
    """
    if not isinstance(as_of, datetime) or as_of.tzinfo is None:
        raise IntelligenceError("as_of must be a timezone-aware datetime")
    if not isinstance(uid, str) or not uid.strip():
        raise IntelligenceError("uid is required")
    if not isinstance(store, YieldHistoryStore):
        raise IntelligenceError("store must be a YieldHistoryStore")
    as_of = as_of.astimezone(timezone.utc)

    reader = _ReadOnceHistory(store.path)          # one read for the whole evaluation
    latest_row = reader.latest(uid)
    if latest_row is None:
        return YieldIntelligence(INTELLIGENCE_SCHEMA, uid, as_of,
                                 IntelligenceStatus.INSUFFICIENT_HISTORY, None, None, ())
    latest = _point(latest_row)

    source = _source_ref_from_row(latest_row)
    if source is None:
        freshness = FreshnessView("UNKNOWN", None, "observation has no recognised source authority")
    else:
        result = evaluate_freshness(source, now=as_of)
        freshness = FreshnessView(result.state, result.age_seconds, result.reason)

    horizons = tuple(_horizon(reader, uid, latest, name, span) for name, span in HORIZONS)
    return YieldIntelligence(INTELLIGENCE_SCHEMA, uid, as_of,
                             IntelligenceStatus.AVAILABLE, latest, freshness, horizons)
