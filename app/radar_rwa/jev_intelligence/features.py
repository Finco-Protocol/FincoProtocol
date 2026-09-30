"""Deterministic, identity-blinded feature extraction from canonical R-LIVE evidence.

Every number is computed here in Decimal. Jev is only ever shown closed-vocabulary buckets,
never asked to compute anything. A missing input becomes ``UNAVAILABLE`` (never 0, never
inferred). Only fields the current R-LIVE authority actually provides are used: the current
B1.0 premium, its freshness, and the 1h/24h premium ranges and history points. R-LIVE does not
provide liquidity, depth, volume or wallet data, so no such feature exists.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Mapping, Sequence

from .contracts import FEATURE_SCHEMA_VERSION, UNAVAILABLE_FEATURE, FeatureState

# ── Declared policy constants (part of FEATURE_SCHEMA_VERSION) ──────────────────────────
DIRECTION_FLAT_BPS = Decimal("2")
MIN_WINDOW_COVERAGE = Decimal("0.5")          # earliest point must cover >=50% of the window
POINT_LIMIT = 100                             # read_r_live_history hard cap
LEVEL_NEAR_PARITY_BPS = Decimal("10")
LEVEL_MODERATE_BPS = Decimal("50")
LEVEL_WIDE_BPS = Decimal("150")
WIDTH_NARROW_BPS = Decimal("5")
WIDTH_MODERATE_BPS = Decimal("25")
SHAPE_COMPRESSED = Decimal("0.25")
SHAPE_INTERMEDIATE = Decimal("0.75")
DENSITY_1H = (3, 12)
DENSITY_24H = (12, 72)
ACTIVITY_BUCKETS_SECONDS = ((300, "WITHIN_5M"), (3600, "WITHIN_1H"), (21600, "WITHIN_6H"))
FEATURE_KEYS = (
    "premium_level", "position_in_1h_range", "position_in_24h_range", "direction_1h",
    "direction_24h", "short_long_agreement", "range_shape", "range_width_24h",
    "observation_density_1h", "observation_density_24h", "market_activity_age",
)


_CUR = "current B1.0 premium (bps), R-LIVE authority via get_r_live"
_RNG = "R-LIVE 1h/24h premium range summary (read_r_live_ranges, collected_at clock)"
_PTS = "R-LIVE ordered premium history points (read_r_live_history, limit 100)"
_FRS = "R-LIVE freshness evidence (market_activity_age_seconds)"

# Outbound-feature contract. Every feature sent to the provider is listed here; nothing else is.
# ``raw_value_sent`` is False for all of them: only the closed-vocabulary bucket leaves FINCO, and
# ``identity_exposed`` is False for all of them. ``evidence_for`` lists the questions a feature
# supports (a question without supporting evidence would be removed, not padded with new data).
FEATURE_CONTRACT: dict[str, dict[str, object]] = {
    "premium_level": {
        "source": _CUR, "transform": "abs(premium) bucketed; side from sign",
        "buckets": ("NEAR_PARITY", "MODERATE_PREMIUM", "MODERATE_DISCOUNT", "WIDE_PREMIUM",
                    "WIDE_DISCOUNT", "EXTREME_PREMIUM", "EXTREME_DISCOUNT"),
        "boundaries": "abs bps <10 | <50 | <150 | >=150", "missing": "call not made (fail closed)",
        "raw_value_sent": False, "identity_exposed": False, "evidence_for": ("attention",)},
    "position_in_1h_range": {
        "source": _CUR + "; " + _RNG, "transform": "position of current premium inside 1h low/high",
        "buckets": ("BELOW_RANGE", "LOWER_THIRD", "MIDDLE_THIRD", "UPPER_THIRD", "ABOVE_RANGE",
                    "FLAT_RANGE", UNAVAILABLE_FEATURE),
        "boundaries": "thirds of (high-low)", "missing": UNAVAILABLE_FEATURE,
        "raw_value_sent": False, "identity_exposed": False,
        "evidence_for": ("market_regime", "attention")},
    "position_in_24h_range": {
        "source": _CUR + "; " + _RNG, "transform": "position of current premium inside 24h low/high",
        "buckets": ("BELOW_RANGE", "LOWER_THIRD", "MIDDLE_THIRD", "UPPER_THIRD", "ABOVE_RANGE",
                    "FLAT_RANGE"),
        "boundaries": "thirds of (high-low)", "missing": "call not made (24h range required)",
        "raw_value_sent": False, "identity_exposed": False,
        "evidence_for": ("market_regime", "attention")},
    "direction_1h": {
        "source": _CUR + "; " + _PTS, "transform": "sign of (current - earliest in-window point)",
        "buckets": ("UP", "DOWN", "FLAT", UNAVAILABLE_FEATURE),
        "boundaries": "flat if abs(delta) < 2 bps; needs >=50% window coverage, untruncated read",
        "missing": UNAVAILABLE_FEATURE, "raw_value_sent": False, "identity_exposed": False,
        "evidence_for": ("market_regime",)},
    "direction_24h": {
        "source": _CUR + "; " + _PTS, "transform": "sign of (current - earliest in-window point)",
        "buckets": ("UP", "DOWN", "FLAT", UNAVAILABLE_FEATURE),
        "boundaries": "flat if abs(delta) < 2 bps; needs >=50% window coverage, untruncated read",
        "missing": UNAVAILABLE_FEATURE, "raw_value_sent": False, "identity_exposed": False,
        "evidence_for": ("market_regime",)},
    "short_long_agreement": {
        "source": "derived from direction_1h and direction_24h", "transform": "compare directions",
        "buckets": ("AGREE", "DISAGREE", "FLAT_INVOLVED", UNAVAILABLE_FEATURE),
        "boundaries": "n/a", "missing": UNAVAILABLE_FEATURE, "raw_value_sent": False,
        "identity_exposed": False, "evidence_for": ("market_regime",)},
    "range_shape": {
        "source": _RNG, "transform": "1h width / 24h width",
        "buckets": ("COMPRESSED", "INTERMEDIATE", "EXPANDED", "FLAT_RANGE", UNAVAILABLE_FEATURE),
        "boundaries": "<=0.25 | <=0.75 | >0.75", "missing": UNAVAILABLE_FEATURE,
        "raw_value_sent": False, "identity_exposed": False,
        "evidence_for": ("market_regime", "attention")},
    "range_width_24h": {
        "source": _RNG, "transform": "24h high - low (bps) bucketed",
        "buckets": ("NARROW", "MODERATE", "WIDE"), "boundaries": "<5 | <25 | >=25 bps",
        "missing": "call not made (24h range required)", "raw_value_sent": False,
        "identity_exposed": False, "evidence_for": ("market_regime", "attention")},
    "observation_density_1h": {
        "source": _RNG, "transform": "1h observation count bucketed",
        "buckets": ("SPARSE", "MODERATE", "DENSE", UNAVAILABLE_FEATURE),
        "boundaries": "<3 | <12 | >=12", "missing": UNAVAILABLE_FEATURE,
        "raw_value_sent": False, "identity_exposed": False, "evidence_for": ("attention",)},
    "observation_density_24h": {
        "source": _RNG, "transform": "24h observation count bucketed",
        "buckets": ("SPARSE", "MODERATE", "DENSE", UNAVAILABLE_FEATURE),
        "boundaries": "<12 | <72 | >=72", "missing": UNAVAILABLE_FEATURE,
        "raw_value_sent": False, "identity_exposed": False, "evidence_for": ("attention",)},
    "market_activity_age": {
        "source": _FRS, "transform": "age of last pool activity bucketed",
        "buckets": ("WITHIN_5M", "WITHIN_1H", "WITHIN_6H", "OVER_6H", UNAVAILABLE_FEATURE),
        "boundaries": "<=300s | <=3600s | <=21600s | more", "missing": UNAVAILABLE_FEATURE,
        "raw_value_sent": False, "identity_exposed": False, "evidence_for": ("attention",)},
}


class FeatureUnavailable(ValueError):
    """Canonical inputs cannot support any interpretation (fail closed)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _dec(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def premium_level(premium_bps: Decimal) -> str:
    magnitude = abs(premium_bps)
    if magnitude < LEVEL_NEAR_PARITY_BPS:
        return "NEAR_PARITY"
    side = "PREMIUM" if premium_bps > 0 else "DISCOUNT"
    if magnitude < LEVEL_MODERATE_BPS:
        return f"MODERATE_{side}"
    if magnitude < LEVEL_WIDE_BPS:
        return f"WIDE_{side}"
    return f"EXTREME_{side}"


def position_in_range(current: Decimal, low: Decimal | None, high: Decimal | None) -> str:
    if low is None or high is None or high < low:
        return UNAVAILABLE_FEATURE
    if high == low:
        return "FLAT_RANGE"
    if current < low:
        return "BELOW_RANGE"
    if current > high:
        return "ABOVE_RANGE"
    fraction = (current - low) / (high - low)
    if fraction < Decimal(1) / Decimal(3):
        return "LOWER_THIRD"
    if fraction < Decimal(2) / Decimal(3):
        return "MIDDLE_THIRD"
    return "UPPER_THIRD"


def direction_bucket(delta_bps: Decimal | None) -> str:
    if delta_bps is None:
        return UNAVAILABLE_FEATURE
    if abs(delta_bps) < DIRECTION_FLAT_BPS:
        return "FLAT"
    return "UP" if delta_bps > 0 else "DOWN"


def agreement_bucket(short: str, long: str) -> str:
    if UNAVAILABLE_FEATURE in (short, long):
        return UNAVAILABLE_FEATURE
    if "FLAT" in (short, long):
        return "FLAT_INVOLVED"
    return "AGREE" if short == long else "DISAGREE"


def _density(count: object, edges: tuple[int, int]) -> str:
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return UNAVAILABLE_FEATURE
    if count < edges[0]:
        return "SPARSE"
    return "MODERATE" if count < edges[1] else "DENSE"


def _range(summary: Mapping[str, object] | None) -> tuple[Decimal | None, Decimal | None, object]:
    if not isinstance(summary, Mapping) or summary.get("state") != "AVAILABLE":
        return None, None, (summary or {}).get("observation_count") if isinstance(summary, Mapping) else None
    low, high = _dec(summary.get("low_bps")), _dec(summary.get("high_bps"))
    if low is None or high is None:
        return None, None, summary.get("observation_count")
    return low, high, summary.get("observation_count")


def _window_direction(points: Sequence[Mapping[str, object]], current: Decimal,
                      as_of: datetime, window: timedelta) -> tuple[str, Decimal | None]:
    """Direction of (current - earliest in-window observation); UNAVAILABLE if unproven."""
    start = as_of - window
    inside: list[tuple[datetime, Decimal]] = []
    oldest_fetched: datetime | None = None
    for point in points:
        if point.get("state") != "AVAILABLE":
            continue
        collected = _utc(point.get("collected_at"))
        value = _dec(point.get("reference_premium_bps"))
        if collected is None or value is None or collected > as_of:
            continue
        if oldest_fetched is None or collected < oldest_fetched:
            oldest_fetched = collected
        if collected >= start:
            inside.append((collected, value))
    if len(inside) < 2:
        return UNAVAILABLE_FEATURE, None
    # A capped read whose oldest row is still in-window cannot prove where the window starts.
    if len(points) >= POINT_LIMIT and oldest_fetched is not None and oldest_fetched >= start:
        return UNAVAILABLE_FEATURE, None
    inside.sort(key=lambda item: item[0])
    earliest_time, earliest_value = inside[0]
    if Decimal((as_of - earliest_time).total_seconds()) < Decimal(window.total_seconds()) * MIN_WINDOW_COVERAGE:
        return UNAVAILABLE_FEATURE, None
    delta = current - earliest_value
    return direction_bucket(delta), delta


def _age_bucket(seconds: object) -> str:
    if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 0:
        return UNAVAILABLE_FEATURE
    for limit, name in ACTIVITY_BUCKETS_SECONDS:
        if seconds <= limit:
            return name
    return "OVER_6H"


def _ttl_for(activity: str) -> int:
    return {"WITHIN_5M": 30, "WITHIN_1H": 60}.get(activity, 120)


def canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def build_feature_state(
    *, current_state: str, current: Mapping[str, object] | None,
    ranges: Mapping[str, object] | None, points: Sequence[Mapping[str, object]] | None,
) -> FeatureState:
    """Build the blinded feature state or raise FeatureUnavailable (fail closed)."""
    if current_state != "AVAILABLE" or not isinstance(current, Mapping):
        raise FeatureUnavailable("CANONICAL_CURRENT_NOT_AVAILABLE")
    premium_block = current.get("b1_0_premium")
    premium = _dec(premium_block.get("value_bps")) if isinstance(premium_block, Mapping) else None
    if premium is None:
        raise FeatureUnavailable("CANONICAL_PREMIUM_NOT_AVAILABLE")
    freshness = current.get("freshness")
    freshness = freshness if isinstance(freshness, Mapping) else {}
    as_of = _utc(freshness.get("retrieved_at"))
    if as_of is None:
        raise FeatureUnavailable("CANONICAL_RETRIEVAL_TIME_UNAVAILABLE")
    if not isinstance(ranges, Mapping):
        raise FeatureUnavailable("HISTORY_UNAVAILABLE")

    low1, high1, count1 = _range(ranges.get("range_1h"))  # type: ignore[arg-type]
    low24, high24, count24 = _range(ranges.get("range_24h"))  # type: ignore[arg-type]
    if low24 is None or high24 is None:
        raise FeatureUnavailable("INSUFFICIENT_HISTORY")

    series = list(points or [])
    dir1, delta1 = _window_direction(series, premium, as_of, timedelta(hours=1))
    dir24, delta24 = _window_direction(series, premium, as_of, timedelta(hours=24))

    width24 = high24 - low24
    if low1 is None or high1 is None:
        shape = UNAVAILABLE_FEATURE
    elif width24 == 0:
        shape = "FLAT_RANGE"
    else:
        ratio = (high1 - low1) / width24
        shape = ("COMPRESSED" if ratio <= SHAPE_COMPRESSED
                 else "INTERMEDIATE" if ratio <= SHAPE_INTERMEDIATE else "EXPANDED")
    width_bucket = ("NARROW" if width24 < WIDTH_NARROW_BPS
                    else "MODERATE" if width24 < WIDTH_MODERATE_BPS else "WIDE")
    activity = _age_bucket(freshness.get("market_activity_age_seconds"))

    features = {
        "premium_level": premium_level(premium),
        "position_in_1h_range": position_in_range(premium, low1, high1),
        "position_in_24h_range": position_in_range(premium, low24, high24),
        "direction_1h": dir1,
        "direction_24h": dir24,
        "short_long_agreement": agreement_bucket(dir1, dir24),
        "range_shape": shape,
        "range_width_24h": width_bucket,
        "observation_density_1h": _density(count1, DENSITY_1H),
        "observation_density_24h": _density(count24, DENSITY_24H),
        "market_activity_age": activity,
    }
    assert tuple(features) == FEATURE_KEYS

    fingerprint = hashlib.sha256(canonical_json(
        {"feature_schema_version": FEATURE_SCHEMA_VERSION, "features": features}
    ).encode("utf-8")).hexdigest()
    evidence = {
        "premium_bps": str(premium), "as_of": as_of.isoformat(),
        "range_1h": [None if low1 is None else str(low1), None if high1 is None else str(high1), count1],
        "range_24h": [str(low24), str(high24), count24],
        "delta_1h_bps": None if delta1 is None else str(delta1),
        "delta_24h_bps": None if delta24 is None else str(delta24),
        "market_activity_age_seconds": freshness.get("market_activity_age_seconds"),
    }
    digest = hashlib.sha256(canonical_json(evidence).encode("utf-8")).hexdigest()
    return FeatureState(
        features=features, input_fingerprint=fingerprint, observation_digest=digest,
        as_of=as_of,
        sources=("R_LIVE_CURRENT_B1_0_PREMIUM", "R_LIVE_HISTORY_RANGES_1H_24H",
                 "R_LIVE_HISTORY_POINTS"),
        ttl_seconds=_ttl_for(activity),
    )
