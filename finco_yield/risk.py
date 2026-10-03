"""FINCO Yield Historical Risk & Persistence V2 -- a PURE DERIVED READ MODEL
over the canonical ``YieldHistoryStore``.

    source observation -> canonical history -> V2 risk/persistence context

This module owns NO source truth, persists nothing, performs no acquisition
and makes no provider calls.  It never writes.  It reuses the EXISTING
canonical authorities:

    APY sigma            finco_yield.intelligence (composed, never reimplemented)
    freshness            finco_yield.freshness via alerts_eval source refs
    APY delta semantics  unchanged -- V2 adds distribution/percentile facts,
                         it does not redefine any V1 delta
    Treasury             untouched: the CURRENT spread stays the existing
                         canonical metric; no historical Treasury series is
                         reconstructed and the current yield is never applied
                         to historical observations.

No forecasting.  No composite score.  No rating/grade/recommendation.
``None`` is UNAVAILABLE; a factual ``0`` is data.

Observation-based vs time-based
-------------------------------
All persistence/percentile facts are computed over USABLE OBSERVATIONS.  If
observations are irregularly spaced the facts remain OBSERVATION-BASED and
are explicitly labelled ``OBSERVATION_BASED`` -- they never imply
elapsed-time persistence and are never time-weighted.

Percentile semantics
--------------------
``apy_percentile`` is the rank of the CURRENT (latest canonical) APY within
the SAME pool's usable observed APY values inside the window, expressed as a
fraction 0..1 using the MIDRANK tie policy:

    percentile = (#values strictly below + 0.5 * #values equal) / count

Ties therefore resolve deterministically to the halfway rank (a current value
equal to k others sits at their shared middle).  It is a descriptive rank --
NOT an expected return, probability, forecast or cross-pool comparison.

Quartile semantics
------------------
q25/q50/q75 use the deterministic nearest-rank rule on ascending values:
``index = ceil(p * n) - 1`` (no interpolation; with even counts the median is
the upper-middle element).  The same rule defines the q50 median used by the
persistence fractions, so every published statistic is reproducible from the
sorted canonical values.

Eligibility policy (both gates required for a percentile)
---------------------------------------------------------
- ``MIN_USABLE_OBSERVATIONS`` numeric APY points inside the window, AND
- ``MIN_HISTORY_SPAN_SECONDS`` between the earliest and latest usable point.

A burst of observations collected over a few minutes never produces a
meaningful-looking percentile.  Both gates met -> AVAILABLE (or STALE when
the latest canonical observation is not CURRENT); exactly one gate met ->
PARTIAL (distribution published, percentile withheld); neither ->
INSUFFICIENT_HISTORY; no usable points -> UNAVAILABLE.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from .alerts_eval import _row_observed_at, _source_ref_from_row
from .freshness import evaluate_freshness
from .history import YieldHistoryStore
from .intelligence import SIGMA_MIN_OBSERVATIONS, build_intelligence

RISK_SCHEMA_VERSION = "YIELD_HISTORICAL_RISK_V2"

DEFAULT_WINDOW = timedelta(days=30)
MIN_USABLE_OBSERVATIONS = SIGMA_MIN_OBSERVATIONS   # 10 -- one shared bar
MIN_HISTORY_SPAN_SECONDS = 3600                    # 1h: a minutes-long burst is not history

_PERSISTENCE_BAND = Decimal("0.10")                # "within 10% of median"
_BPS = Decimal(10000)


class RiskState(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class RiskError(ValueError):
    """Invalid evaluation input (fail closed)."""


# ── row access (usable = finite numeric field on a timestamped row) ──────────

def _dec(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _usable_points(rows: list[dict[str, Any]], field: str,
                   *, since: datetime, until: datetime,
                   ) -> list[tuple[datetime, Decimal]]:
    """Usable (timestamp, Decimal value) points inside [since, until].

    Rows with an unparseable timestamp or a missing/non-numeric field are
    skipped -- never coerced to zero, never interpolated."""
    points: list[tuple[datetime, Decimal]] = []
    for row in rows:
        moment = _row_observed_at(row)
        if moment is None or moment < since or moment > until:
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        value = _dec(payload.get(field))
        if value is None:
            continue
        points.append((moment, value))
    points.sort(key=lambda item: item[0])
    return points


def _span_seconds(points: list[tuple[datetime, Decimal]]) -> int:
    if len(points) < 2:
        return 0
    return int((points[-1][0] - points[0][0]).total_seconds())


def _nearest_rank(values: list[Decimal], p: str) -> Decimal | None:
    """Deterministic nearest-rank quantile over ASCENDING values: index
    ceil(p * n) - 1, no interpolation.  ``p`` in {"25", "50", "75"}."""
    if not values:
        return None
    fraction = Decimal(p) / Decimal(100)
    index = int((fraction * len(values)).to_integral_value(rounding="ROUND_CEILING")) - 1
    index = max(0, min(index, len(values) - 1))
    return values[index]


def _midrank_percentile(values: list[Decimal], current: Decimal) -> Decimal | None:
    """Midrank of ``current`` inside ``values`` (fraction 0..1):
    (# strictly below + 0.5 * # equal) / count.  Deterministic under ties."""
    if not values:
        return None
    below = sum(1 for v in values if v < current)
    equal = sum(1 for v in values if v == current)
    count = Decimal(len(values))
    # quantized to 6 dp so the fraction is exact under Decimal division
    return ((Decimal(below) + Decimal("0.5") * Decimal(equal)) / count)         .quantize(Decimal("0.000001"))


# ── result types ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HistoryMeta:
    observation_count: int            # usable APY points in the window
    history_span_seconds: int         # span of those usable points
    window_days: int
    min_usable_observations: int = MIN_USABLE_OBSERVATIONS
    min_history_span_seconds: int = MIN_HISTORY_SPAN_SECONDS


@dataclass(frozen=True)
class ApyDistribution:
    min: Decimal | None = None
    q25: Decimal | None = None
    median: Decimal | None = None
    q75: Decimal | None = None
    max: Decimal | None = None
    percentile: Decimal | None = None   # midrank of CURRENT apy, 0..1
    percentile_policy: str | None = None


@dataclass(frozen=True)
class ApyContext:
    current_apy: Decimal | None = None
    trailing_peak_apy: Decimal | None = None
    current_vs_peak_delta_bps: Decimal | None = None
    canonical_sigma: Decimal | None = None
    canonical_sigma_source: str | None = None


@dataclass(frozen=True)
class TvlContext:
    current_tvl: Decimal | None = None
    trailing_min_tvl: Decimal | None = None
    trailing_max_tvl: Decimal | None = None
    tvl_drawdown_fraction: Decimal | None = None   # (current / trailing_max) - 1, max > 0
    baseline_change_fraction: Decimal | None = None  # (current / earliest) - 1, earliest > 0
    tvl_observation_count: int = 0


@dataclass(frozen=True)
class RewardContext:
    base_apy: Decimal | None = None
    rewards_apy: Decimal | None = None
    total_apy: Decimal | None = None
    reward_apy_share: Decimal | None = None   # rewards / total, total != 0


@dataclass(frozen=True)
class PersistenceFacts:
    methodology: str = "OBSERVATION_BASED"
    fraction_within_10pct_of_median: Decimal | None = None
    fraction_above_window_median: Decimal | None = None
    usable_observation_count: int = 0


@dataclass(frozen=True)
class HistoricalRiskContext:
    schema: str
    canonical_id: str
    as_of: datetime
    state: RiskState
    freshness: str | None
    reason: str | None
    history: HistoryMeta
    apy_distribution: ApyDistribution
    apy_context: ApyContext
    tvl_context: TvlContext
    reward_context: RewardContext
    persistence: PersistenceFacts

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe serialization.  UNAVAILABLE fields stay null -- never
        zero; Decimal values render as exact strings."""
        def num(value: Decimal | None):
            return None if value is None else format(value, "f")

        return {
            "schema": self.schema,
            "canonical_id": self.canonical_id,
            "as_of": self.as_of.isoformat(),
            "state": self.state.value,
            "freshness": self.freshness,
            "reason": self.reason,
            "history": {
                "observation_count": self.history.observation_count,
                "history_span_seconds": self.history.history_span_seconds,
                "window_days": self.history.window_days,
                "min_usable_observations": self.history.min_usable_observations,
                "min_history_span_seconds": self.history.min_history_span_seconds,
            },
            "apy_distribution": {
                "min": num(self.apy_distribution.min),
                "q25": num(self.apy_distribution.q25),
                "median": num(self.apy_distribution.median),
                "q75": num(self.apy_distribution.q75),
                "max": num(self.apy_distribution.max),
                "percentile": num(self.apy_distribution.percentile),
                "percentile_policy": self.apy_distribution.percentile_policy,
            },
            "apy_context": {
                "current_apy": num(self.apy_context.current_apy),
                "trailing_peak_apy": num(self.apy_context.trailing_peak_apy),
                "current_vs_peak_delta_bps": num(self.apy_context.current_vs_peak_delta_bps),
                "canonical_sigma": num(self.apy_context.canonical_sigma),
                "canonical_sigma_source": self.apy_context.canonical_sigma_source,
            },
            "tvl_context": {
                "current_tvl": num(self.tvl_context.current_tvl),
                "trailing_min_tvl": num(self.tvl_context.trailing_min_tvl),
                "trailing_max_tvl": num(self.tvl_context.trailing_max_tvl),
                "tvl_drawdown_fraction": num(self.tvl_context.tvl_drawdown_fraction),
                "baseline_change_fraction": num(self.tvl_context.baseline_change_fraction),
                "tvl_observation_count": self.tvl_context.tvl_observation_count,
            },
            "reward_context": {
                "base_apy": num(self.reward_context.base_apy),
                "rewards_apy": num(self.reward_context.rewards_apy),
                "total_apy": num(self.reward_context.total_apy),
                "reward_apy_share": num(self.reward_context.reward_apy_share),
            },
            "persistence": {
                "methodology": self.persistence.methodology,
                "fraction_within_10pct_of_median":
                    num(self.persistence.fraction_within_10pct_of_median),
                "fraction_above_window_median":
                    num(self.persistence.fraction_above_window_median),
                "usable_observation_count": self.persistence.usable_observation_count,
            },
        }


# ── public API ───────────────────────────────────────────────────────────────

def build_historical_risk(
    store: YieldHistoryStore, canonical_id: str, *, as_of: datetime,
    window: timedelta = DEFAULT_WINDOW,
) -> HistoricalRiskContext:
    """Derive the V2 historical risk / persistence context for ONE canonical
    UID from canonical history.  Pure read: no acquisition, no writes, no
    provider calls, no second store."""
    if not isinstance(as_of, datetime) or as_of.tzinfo is None:
        raise RiskError("as_of must be a timezone-aware datetime")
    if not isinstance(canonical_id, str) or not canonical_id.strip():
        raise RiskError("canonical_id is required")
    if not isinstance(store, YieldHistoryStore):
        raise RiskError("store must be a YieldHistoryStore")
    as_of = as_of.astimezone(timezone.utc)
    since = as_of - window

    rows = store.window(canonical_id, since=since, until=as_of)
    apy_points = _usable_points(rows, "apy_total", since=since, until=as_of)
    tvl_points = _usable_points(rows, "tvl_usd", since=since, until=as_of)
    apy_values = [value for _t, value in apy_points]

    count = len(apy_points)
    span = _span_seconds(apy_points)
    count_ok = count >= MIN_USABLE_OBSERVATIONS
    span_ok = span >= MIN_HISTORY_SPAN_SECONDS

    # freshness of the LATEST canonical observation (existing classifier)
    latest_row = rows[-1] if rows else None
    freshness, freshness_reason = None, None
    if latest_row is not None:
        source = _source_ref_from_row(latest_row)
        if source is not None:
            result = evaluate_freshness(source, now=as_of)
            freshness, freshness_reason = result.state, result.reason
        else:
            freshness, freshness_reason = "UNKNOWN", "NO_RECOGNISED_SOURCE_AUTHORITY"

    # top-level state
    reason = None
    if count == 0:
        state = RiskState.UNAVAILABLE
        reason = "NO_USABLE_OBSERVATIONS"
    elif not count_ok and not span_ok:
        state = RiskState.INSUFFICIENT_HISTORY
        reason = "INSUFFICIENT_OBSERVATIONS_AND_SPAN"
    elif count_ok != span_ok:
        state = RiskState.PARTIAL
        reason = ("HISTORY_SPAN_BELOW_POLICY" if count_ok
                  else "OBSERVATION_COUNT_BELOW_POLICY")
    elif freshness not in (None, "CURRENT"):
        state = RiskState.STALE
        reason = freshness_reason or "LATEST_OBSERVATION_NOT_CURRENT"
    else:
        state = RiskState.AVAILABLE

    # APY distribution: published whenever the count gate is met (PARTIAL
    # keeps the quartiles; the percentile needs BOTH gates).
    distribution = ApyDistribution()
    percentile_policy = None
    if count_ok:
        ordered = sorted(apy_values)
        distribution = ApyDistribution(
            min=ordered[0],
            q25=_nearest_rank(apy_points_sorted_values(apy_points), "25"),
            median=_nearest_rank(apy_points_sorted_values(apy_points), "50"),
            q75=_nearest_rank(apy_points_sorted_values(apy_points), "75"),
            max=ordered[-1],
        )
    if count_ok and span_ok:
        current = apy_values[-1]   # latest usable APY == latest canonical obs
        distribution = ApyDistribution(
            min=distribution.min, q25=distribution.q25,
            median=distribution.median, q75=distribution.q75,
            max=distribution.max,
            percentile=_midrank_percentile(apy_values, current),
            percentile_policy="MIDRANK_WITHIN_POOL_USABLE_OBSERVATIONS",
        )
        percentile_policy = distribution.percentile_policy

    # APY context: current + trailing peak + compression + REUSED sigma
    current_apy = apy_values[-1] if apy_values else None
    peak = max(apy_values) if apy_values else None
    peak_delta = (current_apy - peak) * _BPS \
        if (current_apy is not None and peak is not None) else None
    apy_context = ApyContext(
        current_apy=current_apy,
        trailing_peak_apy=peak,
        current_vs_peak_delta_bps=peak_delta,
    )

    # canonical sigma composed from the EXISTING intelligence authority
    try:
        intelligence = build_intelligence(store, canonical_id, as_of=as_of)
        horizon_30d = intelligence.horizon("30d")
        if horizon_30d is not None and horizon_30d.apy_sigma is not None:
            apy_context = ApyContext(
                current_apy=apy_context.current_apy,
                trailing_peak_apy=apy_context.trailing_peak_apy,
                current_vs_peak_delta_bps=apy_context.current_vs_peak_delta_bps,
                canonical_sigma=horizon_30d.apy_sigma,
                canonical_sigma_source=horizon_30d.apy_sigma_source
                or "FINCO_HISTORICAL",
            )
    except Exception:
        # sigma stays UNAVAILABLE -- never reimplemented, never substituted
        pass

    # TVL context (independent of APY availability)
    tvl_values = [value for _t, value in tvl_points]
    current_tvl = tvl_values[-1] if tvl_values else None
    trailing_min = min(tvl_values) if tvl_values else None
    trailing_max = max(tvl_values) if tvl_values else None
    drawdown = None
    if current_tvl is not None and trailing_max is not None and trailing_max > 0:
        drawdown = current_tvl / trailing_max - Decimal(1)
    baseline_change = None
    if current_tvl is not None and tvl_values and tvl_values[0] > 0:
        baseline_change = current_tvl / tvl_values[0] - Decimal(1)
    tvl_context = TvlContext(
        current_tvl=current_tvl,
        trailing_min_tvl=trailing_min,
        trailing_max_tvl=trailing_max,
        tvl_drawdown_fraction=drawdown,
        baseline_change_fraction=baseline_change,
        tvl_observation_count=len(tvl_values),
    )

    # Reward dependency from the LATEST canonical observation only
    latest_payload = (latest_row.get("payload") or {}) if latest_row else {}
    base_apy = _dec(latest_payload.get("apy_base"))
    rewards_apy = _dec(latest_payload.get("apy_rewards"))
    total_apy = _dec(latest_payload.get("apy_total"))
    reward_share = None
    if (rewards_apy is not None and total_apy is not None
            and total_apy != 0):
        reward_share = rewards_apy / total_apy
    reward_context = RewardContext(
        base_apy=base_apy, rewards_apy=rewards_apy, total_apy=total_apy,
        reward_apy_share=reward_share,
    )

    # Persistence (observation-based, never time-weighted)
    persistence = PersistenceFacts(usable_observation_count=count)
    if apy_values:
        median = _nearest_rank(apy_points_sorted_values(apy_points), "50")
        if median is not None:
            band = abs(median) * _PERSISTENCE_BAND
            within = sum(1 for v in apy_values if abs(v - median) <= band)
            above = sum(1 for v in apy_values if v > median)
            persistence = PersistenceFacts(
                methodology="OBSERVATION_BASED",
                fraction_within_10pct_of_median=Decimal(within) / Decimal(count),
                fraction_above_window_median=Decimal(above) / Decimal(count),
                usable_observation_count=count,
            )

    return HistoricalRiskContext(
        schema=RISK_SCHEMA_VERSION,
        canonical_id=canonical_id,
        as_of=as_of,
        state=state,
        freshness=freshness,
        reason=reason,
        history=HistoryMeta(
            observation_count=count,
            history_span_seconds=span,
            window_days=int(window.total_seconds() // 86400),
        ),
        apy_distribution=distribution,
        apy_context=apy_context,
        tvl_context=tvl_context,
        reward_context=reward_context,
        persistence=persistence,
    )


def apy_points_sorted_values(apy_points: list[tuple[datetime, Decimal]]) -> list[Decimal]:
    """Ascending APY values of the usable points (quartile input)."""
    return sorted(value for _t, value in apy_points)
