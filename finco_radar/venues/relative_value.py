"""Tokenized Relative Value & Dislocation Persistence V1 (PR #183).

Own-history distribution context and truthful current dislocation
persistence for one exact tokenized representation, using the canonical
VenueMarketStore history and the existing #179 threshold authority.

Genuinely NEW metrics (not in any prior authority):
  - own-history percentile / distribution context
  - robust historical median / quartile context
  - current dislocation persistence / duration

These are NOT: probability, forecast, expected return, cross-sectional
ranking, or trading signal.  Percentile means: where the current basis
sits within THIS EXACT representation's own usable observed basis history.

Dislocation persistence uses the existing dislocation_threshold_bps()
authority and the #179 discrete-observation policy:
  - first usable observation already above threshold does NOT prove when
    the dislocation began (start time UNKNOWN / PREHISTORY_UNAVAILABLE);
  - a proven sign-consistent crossing from within-threshold anchors the
    start to the first above-threshold observation (no interpolation);
  - a sign reversal (premium→discount or discount→premium) starts a NEW
    episode — direction matters, abs() alone is insufficient;
  - missing/unusable evidence breaks provable continuity (no bridging);
  - stale current evidence is never presented as a current dislocation;
  - no predictive persistence (never "likely to persist").

Cross-asset monitor: bounded deterministic universe, include_points=True
for the bounded set only (no N×1500 problem), distribution/persistence
derived from actual points.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import TYPE_CHECKING, Callable

from finco_radar.venues.intelligence import (
    RepresentationHistory,
    dislocation_threshold_bps,
)

if TYPE_CHECKING:
    from finco_radar.venues.registry import VenueRegistry
    from finco_radar.venues.store import VenueMarketStore

MIN_USABLE_OBSERVATIONS = 8
MIN_HISTORY_SPAN_SECONDS = 3600  # 1 hour
HISTORY_WINDOW = timedelta(days=7)
DEFAULT_MONITOR_LIMIT = 60


class DistributionState(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class DislocationState(str, Enum):
    WITHIN_THRESHOLD = "WITHIN_THRESHOLD"
    PREMIUM_DISLOCATION = "PREMIUM_DISLOCATION"
    DISCOUNT_DISLOCATION = "DISCOUNT_DISLOCATION"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class DislocationStartState(str, Enum):
    PROVEN_CROSSING = "PROVEN_CROSSING"
    SIGN_REVERSAL = "SIGN_REVERSAL"
    PREHISTORY_UNAVAILABLE = "PREHISTORY_UNAVAILABLE"
    NO_DISLOCATION = "NO_DISLOCATION"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


# ── Parsing helpers ───────────────────────────────────────────────────────────

def _parse_basis(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        d = Decimal(value)
        return d if d.is_finite() else None
    except InvalidOperation:
        return None


def _parse_aware_utc(value: str | None) -> datetime | None:
    """Parse a timezone-aware ISO timestamp to UTC.  Rejects naive and
    unparseable values.  Future-timestamp rejection is the attestation
    freshness authority's concern, not a general-purpose parser concern."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None
    return dt.astimezone(timezone.utc)


# ── Own-history distribution ──────────────────────────────────────────────────

@dataclass(frozen=True)
class BasisDistribution:
    """Own-history distribution context for one exact representation."""

    state: str
    usable_observation_count: int = 0
    history_span_seconds: int | None = None
    historical_min_basis_bps: str | None = None
    historical_q25_basis_bps: str | None = None
    historical_median_basis_bps: str | None = None
    historical_q75_basis_bps: str | None = None
    historical_max_basis_bps: str | None = None
    current_basis_percentile: str | None = None
    percentile_method: str = (
        "mean-rank within own usable basis history "
        "(values strictly below + half of equal values) / total")


def _percentile_rank(sorted_values: list[Decimal], current: Decimal) -> Decimal:
    """Mean-rank percentile: (count strictly below + 0.5 × equal) / total.

    Deterministic tie handling: all equal values share the same rank.
    Returns 0–100 as a Decimal quantized to 1 decimal place.

    Note: when the current value IS the unique maximum of the sample, the
    mean-rank percentile is < 100 because one value is equal (counted as
    half).  This is the documented formula — a percentile of exactly 100
    would require a rank of ``n/n``, which only holds when all values are
    below (not equal).  Tests must match this documented semantics.
    """
    n = len(sorted_values)
    if n == 0:
        return Decimal(0)
    below = sum(1 for v in sorted_values if v < current)
    equal = sum(1 for v in sorted_values if v == current)
    rank = (Decimal(below) + Decimal(equal) / 2) / Decimal(n)
    return (rank * 100).quantize(Decimal("0.1"))


def _quartile(sorted_values: list[Decimal], q: Decimal) -> Decimal:
    n = len(sorted_values)
    if n == 0:
        return Decimal(0)
    if n == 1:
        return sorted_values[0]
    pos = q * (n - 1)
    lower = int(pos)
    upper = min(lower + 1, n - 1)
    frac = pos - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * frac


def compute_basis_distribution(
    history: RepresentationHistory, *,
    now: datetime | None = None,
    min_observations: int = MIN_USABLE_OBSERVATIONS,
    min_span_seconds: int = MIN_HISTORY_SPAN_SECONDS,
) -> BasisDistribution:
    """Own-history distribution context from persisted basis history.

    Uses ``history.latest_basis_bps`` as the canonical current basis (never
    a caller-supplied override).  Eligibility: at least ``min_observations``
    usable observations AND at least ``min_span_seconds`` elapsed span.

    Deduplication: identical (source timestamp, basis value) pairs are
    collapsed in the derived view only (storage is immutable).
    """
    # Extract usable (parsed-timestamp, basis) pairs from history points,
    # including ALL points chronologically; deduped in the derived view.
    seen: set[tuple[str, str]] = set()
    usable: list[tuple[datetime, Decimal]] = []
    for point in history.points:
        basis = _parse_basis(point.v)
        stamp = _parse_aware_utc(point.t)
        if basis is None or stamp is None:
            continue
        key = (point.t or "", str(basis))
        if key in seen:
            continue
        seen.add(key)
        usable.append((stamp, basis))

    current_basis = _parse_basis(history.latest_basis_bps)

    if not usable:
        return BasisDistribution(
            state=DistributionState.UNAVAILABLE.value,
            usable_observation_count=0)

    usable.sort(key=lambda pair: (pair[0], pair[1]))
    span_seconds = int((usable[-1][0] - usable[0][0]).total_seconds())

    if len(usable) < min_observations or span_seconds < min_span_seconds:
        return BasisDistribution(
            state=DistributionState.INSUFFICIENT_HISTORY.value,
            usable_observation_count=len(usable),
            history_span_seconds=span_seconds)

    sorted_values = sorted(v for _, v in usable)

    def _s(v: Decimal) -> str:
        return str(v)

    # Correction B: historical distribution facts may remain available even
    # when the CURRENT evidence is not.  Reuse the canonical #179
    # current_state; do not create a second freshness classifier.
    if history.current_state == "STALE":
        distribution_state = DistributionState.STALE.value
        percentile = None
    elif history.current_state != "AVAILABLE":
        distribution_state = DistributionState.UNAVAILABLE.value
        percentile = None
    elif current_basis is None:
        distribution_state = DistributionState.PARTIAL.value
        percentile = None
    else:
        distribution_state = DistributionState.AVAILABLE.value
        percentile = _percentile_rank(sorted_values, current_basis)

    return BasisDistribution(
        state=distribution_state,
        usable_observation_count=len(usable),
        history_span_seconds=span_seconds,
        historical_min_basis_bps=_s(sorted_values[0]),
        historical_q25_basis_bps=_s(_quartile(sorted_values, Decimal("0.25"))),
        historical_median_basis_bps=_s(_quartile(sorted_values, Decimal("0.5"))),
        historical_q75_basis_bps=_s(_quartile(sorted_values, Decimal("0.75"))),
        historical_max_basis_bps=_s(sorted_values[-1]),
        current_basis_percentile=(
            _s(percentile) if percentile is not None else None),
    )


# ── Dislocation persistence ───────────────────────────────────────────────────

@dataclass(frozen=True)
class DislocationPersistence:
    """Truthful current dislocation persistence for one representation."""

    state: str                       # DislocationState value
    start_state: str                 # DislocationStartState value
    started_at: str | None
    duration_seconds: int | None
    threshold_bps: str


def _classify(basis: Decimal, threshold: Decimal) -> str:
    """Threshold-equal-consistent classification (same >= boundary as
    the #179 crossing authority)."""
    if basis >= threshold:
        return DislocationState.PREMIUM_DISLOCATION.value
    if basis <= -threshold:
        return DislocationState.DISCOUNT_DISLOCATION.value
    return DislocationState.WITHIN_THRESHOLD.value


def _is_stale(history: RepresentationHistory) -> bool:
    return history.current_state == "STALE"


def compute_dislocation_persistence(
    history: RepresentationHistory, *,
    now: datetime | None = None,
) -> DislocationPersistence:
    """Truthful current dislocation persistence using the existing threshold
    authority and the #179 discrete-observation policy.

    Correction A semantics:
      - the full chronological point stream is iterated INCLUDING unusable
        points; any explicit unusable/missing evidence breaks provable
        continuity (no bridging);
      - sign reversal (premium→discount or discount→premium) starts a NEW
        episode — direction matters, abs() alone is insufficient;
      - threshold equality uses >= (consistent with #179 crossing);
      - stale current evidence is reported as STALE, never as a current
        dislocation;
      - first usable observation already above threshold does NOT prove
        when the dislocation began → PREHISTORY_UNAVAILABLE.
    """
    now = now or datetime.now(timezone.utc)
    threshold = dislocation_threshold_bps()

    # STALE current evidence is not a current dislocation.
    if _is_stale(history):
        return DislocationPersistence(
            state=DislocationState.STALE.value,
            start_state=DislocationStartState.STALE.value,
            started_at=None, duration_seconds=None,
            threshold_bps=str(threshold))

    # Build the full chronological stream INCLUDING unusable points.
    stream: list[tuple[datetime | None, Decimal | None]] = []
    seen: set[str] = set()
    for point in history.points:
        key = point.t or str(len(stream))
        if key in seen:
            continue
        seen.add(key)
        stamp = _parse_aware_utc(point.t)
        basis = _parse_basis(point.v)
        stream.append((stamp, basis))
    stream.sort(key=lambda pair: (pair[0] is not None,
                                  pair[0].isoformat() if pair[0] else "",
                                  str(pair[1])))

    if not stream:
        return DislocationPersistence(
            state=DislocationState.UNAVAILABLE.value,
            start_state=DislocationStartState.UNAVAILABLE.value,
            started_at=None, duration_seconds=None,
            threshold_bps=str(threshold))

    # Current state from the LATEST usable point.
    latest_stamp, latest_basis = None, None
    for stamp, basis in reversed(stream):
        if stamp is not None and basis is not None:
            latest_stamp, latest_basis = stamp, basis
            break

    if latest_basis is None:
        return DislocationPersistence(
            state=DislocationState.UNAVAILABLE.value,
            start_state=DislocationStartState.UNAVAILABLE.value,
            started_at=None, duration_seconds=None,
            threshold_bps=str(threshold))

    current_class = _classify(latest_basis, threshold)
    if current_class == DislocationState.WITHIN_THRESHOLD.value:
        return DislocationPersistence(
            state=DislocationState.WITHIN_THRESHOLD.value,
            start_state=DislocationStartState.NO_DISLOCATION.value,
            started_at=None, duration_seconds=None,
            threshold_bps=str(threshold))

    # Walk BACKWARDS through the full stream (including unusable points).
    # Continuity breaks on: a None basis (missing/unusable evidence), a
    # sign reversal (direction change above threshold starts a new
    # episode), or a transition to within-threshold.  The first usable
    # observation being already above threshold means prehistory.
    episode_start: datetime | None = None
    start_state = DislocationStartState.UNAVAILABLE.value

    latest_direction = 1 if latest_basis > 0 else -1
    found_break = False

    for i in range(len(stream) - 1, -1, -1):
        stamp_i, basis_i = stream[i]
        if basis_i is None or stamp_i is None:
            # Correction B: a continuity gap proves only that the episode
            # start is unknown.  It must never be reinterpreted by the
            # generic post-loop logic as a proven threshold crossing.
            found_break = True
            episode_start = None
            start_state = DislocationStartState.PREHISTORY_UNAVAILABLE.value
            break
        above = abs(basis_i) >= threshold
        direction = 1 if basis_i > 0 else (-1 if basis_i < 0 else 0)

        if not above:
            # Transition to within-threshold — episode ended AFTER this point.
            found_break = True
            break

        if direction != latest_direction:
            # Sign reversal — the episode started AFTER this point.
            found_break = True
            if i + 1 < len(stream) and stream[i + 1][0] is not None:
                episode_start = stream[i + 1][0]
            start_state = DislocationStartState.SIGN_REVERSAL.value
            break

        episode_start = stamp_i

    if not found_break:
        # Walked all the way to the beginning — first observation is already
        # above threshold: prehistory unavailable.
        start_state = DislocationStartState.PREHISTORY_UNAVAILABLE.value
        episode_start = None
    elif (episode_start is not None
          and start_state == DislocationStartState.UNAVAILABLE.value):
        # Below-threshold transition (not sign reversal): proven crossing.
        start_state = DislocationStartState.PROVEN_CROSSING.value

    started_at = (episode_start.isoformat()
                  if episode_start is not None and start_state != (
                      DislocationStartState.PREHISTORY_UNAVAILABLE.value)
                  else None)
    duration_seconds = (int((now - episode_start).total_seconds())
                        if episode_start is not None and started_at
                        else None)

    return DislocationPersistence(
        state=current_class,
        start_state=start_state,
        started_at=started_at,
        duration_seconds=duration_seconds,
        threshold_bps=str(threshold))


# ── Cross-asset dislocation monitor ───────────────────────────────────────────

@dataclass(frozen=True)
class DislocationMonitorRow:
    canonical_asset_id: str
    underlying_name: str | None
    venue_id: str
    instrument_id: str
    representation_type: str
    current_basis_bps: str | None
    premium_discount: str | None
    basis_change_24h_bps: str | None
    basis_change_7d_bps: str | None
    current_basis_percentile: str | None
    historical_median_basis_bps: str | None
    current_dislocation_duration_seconds: int | None
    dislocation_start_state: str | None
    cross_venue_divergence_bps: str | None
    market_evidence_state: str
    integrity_state: str | None
    observed_at: str | None


def build_dislocation_monitor(
    *, registry: VenueRegistry, store: VenueMarketStore,
    now: datetime | None = None,
    symbols: list[str] | None = None,
    limit: int = DEFAULT_MONITOR_LIMIT,
    integrity_reader: Callable[[str], dict | None] | None = None,
) -> list[DislocationMonitorRow]:
    """Cross-asset dislocation monitor over eligible Tokenized Markets
    underlyings.

    Bounded: resolves the eligible universe, limits it deterministically,
    and fetches #179 intelligence WITH history points ONLY for the bounded
    set (no N×1500 problem).  No provider acquisition; persisted
    VenueMarketStore only.
    """
    now = now or datetime.now(timezone.utc)
    from finco_radar.venues.intelligence import build_tokenized_intelligence

    underlyings = sorted(registry._underlyings)
    if symbols is not None:
        symbol_set = {s.strip().upper() for s in symbols}
        underlyings = [s for s in underlyings if s in symbol_set]
    underlyings = underlyings[:limit]

    rows: list[DislocationMonitorRow] = []
    for symbol in underlyings:
        resolved = registry.representations_for_underlying(symbol)
        active = [r for r in resolved if r.status.value == "ACTIVE"]
        if not active:
            continue
        try:
            # Correction A #1: include_points=True for the BOUNDED monitor
            # universe so distribution/persistence have actual history.
            intel = build_tokenized_intelligence(
                symbol, registry=registry, store=store, as_of=now,
                include_points=True)
        except Exception:
            continue

        integrity = (integrity_reader(symbol) if integrity_reader else None)
        integrity_state = integrity.get("integrity_flags") if integrity else None
        if isinstance(integrity_state, (list, tuple)):
            integrity_state = ", ".join(integrity_state)

        underlying_name = getattr(
            registry.get_underlying(symbol), "underlying_name", None)

        for history in intel.representations:
            basis = _parse_basis(history.latest_basis_bps)
            threshold = dislocation_threshold_bps()
            current_usable = (
                history.current_state == "AVAILABLE" and basis is not None)
            if current_usable:
                pd_state = ("PREMIUM" if basis >= threshold
                            else "DISCOUNT" if basis <= -threshold
                            else "WITHIN_THRESHOLD")
            else:
                # Preserve the last factual basis separately, but do not
                # describe stale/unavailable evidence as a CURRENT premium
                # or discount.
                pd_state = None

            distribution = compute_basis_distribution(history, now=now)
            persistence = compute_dislocation_persistence(history, now=now)

            # Correction A #10: None stays None, never the string "None".
            cross_bps = None
            if intel.cross_venue is not None:
                raw_div = getattr(intel.cross_venue, "divergence_bps", None)
                if raw_div is not None:
                    cross_bps = str(raw_div)

            # Correction A #11: observed_at from the latest point's source ts.
            observed_at = None
            if history.points:
                last_point = history.points[-1]
                parsed = _parse_aware_utc(last_point.t)
                if parsed is not None:
                    observed_at = last_point.t

            rows.append(DislocationMonitorRow(
                canonical_asset_id=symbol,
                underlying_name=underlying_name,
                venue_id=history.venue_id,
                instrument_id=history.instrument_id,
                representation_type=history.representation_type,
                current_basis_bps=history.latest_basis_bps,
                premium_discount=pd_state,
                basis_change_24h_bps=history.basis_change_24h_bps,
                basis_change_7d_bps=history.basis_change_7d_bps,
                current_basis_percentile=distribution.current_basis_percentile,
                historical_median_basis_bps=distribution.historical_median_basis_bps,
                current_dislocation_duration_seconds=persistence.duration_seconds,
                dislocation_start_state=persistence.start_state,
                cross_venue_divergence_bps=cross_bps,
                market_evidence_state=history.current_state,
                integrity_state=integrity_state,
                observed_at=observed_at,
            ))

    threshold = dislocation_threshold_bps()

    def _sort_key(row: DislocationMonitorRow):
        basis = _parse_basis(row.current_basis_bps)
        current_usable = (
            row.market_evidence_state == "AVAILABLE" and basis is not None)
        dislocated = current_usable and abs(basis) >= threshold
        evidence_bucket = 0 if dislocated else 1 if current_usable else 2
        return (
            evidence_bucket,
            -(abs(basis) if dislocated and basis is not None else 0),
            -(row.current_dislocation_duration_seconds or 0)
            if dislocated else 0,
            row.canonical_asset_id, row.venue_id, row.instrument_id,
        )

    rows.sort(key=_sort_key)
    return rows
