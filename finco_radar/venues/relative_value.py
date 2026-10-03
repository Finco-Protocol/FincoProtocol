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
  - a proven crossing anchors the start to the first above-threshold
    observation (no interpolation between observations);
  - continuity breaks on missing/unusable evidence (no bridging);
  - no predictive persistence (never "likely to persist").
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum

from finco_radar.venues.intelligence import (
    RepresentationHistory,
    dislocation_threshold_bps,
)

MIN_USABLE_OBSERVATIONS = 8
MIN_HISTORY_SPAN_SECONDS = 3600  # 1 hour

HISTORY_WINDOW = timedelta(days=7)


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
    UNAVAILABLE = "UNAVAILABLE"


class DislocationStartState(str, Enum):
    PROVEN_CROSSING = "PROVEN_CROSSING"
    PREHISTORY_UNAVAILABLE = "PREHISTORY_UNAVAILABLE"
    NO_DISLOCATION = "NO_DISLOCATION"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class BasisDistribution:
    """Own-history distribution context for one exact representation."""

    state: str                       # DistributionState value
    usable_observation_count: int = 0
    history_span_seconds: int | None = None
    historical_min_basis_bps: str | None = None
    historical_q25_basis_bps: str | None = None
    historical_median_basis_bps: str | None = None
    historical_q75_basis_bps: str | None = None
    historical_max_basis_bps: str | None = None
    current_basis_percentile: str | None = None  # 0–100, Decimal string
    percentile_method: str = (
        "mean-rank within own usable basis history "
        "(values strictly below + half of equal values) / total")


def _parse_basis(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        d = Decimal(value)
        return d if d.is_finite() else None
    except InvalidOperation:
        return None


def _percentile_rank(sorted_values: list[Decimal], current: Decimal) -> Decimal:
    """Mean-rank percentile: (count strictly below + 0.5 × equal) / total.

    Deterministic tie handling: all equal values share the same rank.
    Returns 0–100 as a Decimal quantized to 1 decimal place.
    """
    n = len(sorted_values)
    if n == 0:
        return Decimal(0)
    below = sum(1 for v in sorted_values if v < current)
    equal = sum(1 for v in sorted_values if v == current)
    rank = (Decimal(below) + Decimal(equal) / 2) / Decimal(n)
    return (rank * 100).quantize(Decimal("0.1"))


def _quartile(sorted_values: list[Decimal], q: Decimal) -> Decimal:
    """Linear interpolation quartile (same method as numpy default)."""
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
    current_basis_bps: str | None = None,
    now: datetime | None = None,
    min_observations: int = MIN_USABLE_OBSERVATIONS,
    min_span_seconds: int = MIN_HISTORY_SPAN_SECONDS,
) -> BasisDistribution:
    """Own-history distribution context from persisted basis history.

    Eligibility: at least ``min_observations`` usable observations AND at
    least ``min_span_seconds`` elapsed span.  Otherwise INSUFFICIENT_HISTORY.

    Deduplication: identical (source timestamp, basis value) pairs are
    collapsed in the derived view only (storage is immutable).
    """
    threshold = dislocation_threshold_bps()

    # Extract usable (timestamp, basis) pairs from history points.
    seen: set[tuple[str, str]] = set()
    usable: list[tuple[str, Decimal]] = []
    for point in history.points:
        if not point.t or point.v is None:
            continue
        basis = _parse_basis(point.v)
        if basis is None:
            continue
        key = (point.t, str(basis))
        if key in seen:
            continue
        seen.add(key)
        usable.append((point.t, basis))

    current_basis = _parse_basis(
        current_basis_bps if current_basis_bps is not None
        else history.latest_basis_bps)

    if not usable:
        return BasisDistribution(
            state=DistributionState.UNAVAILABLE.value,
            usable_observation_count=0)

    usable.sort(key=lambda pair: (pair[0], pair[1]))
    timestamps = [t for t, _ in usable]
    values = [v for _, v in usable]

    span_seconds = 0
    try:
        t0 = datetime.fromisoformat(timestamps[0])
        t1 = datetime.fromisoformat(timestamps[-1])
        if t0.tzinfo is not None and t1.tzinfo is not None:
            span_seconds = int((t1 - t0).total_seconds())
    except ValueError:
        pass

    if len(usable) < min_observations or span_seconds < min_span_seconds:
        return BasisDistribution(
            state=DistributionState.INSUFFICIENT_HISTORY.value,
            usable_observation_count=len(usable),
            history_span_seconds=span_seconds)

    sorted_values = sorted(values)
    percentile = (_percentile_rank(sorted_values, current_basis)
                  if current_basis is not None else None)

    def _str(v: Decimal) -> str:
        return str(v)

    return BasisDistribution(
        state=DistributionState.AVAILABLE.value,
        usable_observation_count=len(usable),
        history_span_seconds=span_seconds,
        historical_min_basis_bps=_str(sorted_values[0]),
        historical_q25_basis_bps=_str(_quartile(sorted_values, Decimal("0.25"))),
        historical_median_basis_bps=_str(_quartile(sorted_values, Decimal("0.5"))),
        historical_q75_basis_bps=_str(_quartile(sorted_values, Decimal("0.75"))),
        historical_max_basis_bps=_str(sorted_values[-1]),
        current_basis_percentile=(
            _str(percentile) if percentile is not None else None),
    )


# ── Dislocation persistence ───────────────────────────────────────────────────

@dataclass(frozen=True)
class DislocationPersistence:
    """Truthful current dislocation persistence for one representation."""

    state: str                       # DislocationState value
    start_state: str                 # DislocationStartState value
    started_at: str | None           # proven start (None when prehistory/unavailable)
    duration_seconds: int | None     # continuous proven duration
    threshold_bps: str               # authority threshold


def compute_dislocation_persistence(
    history: RepresentationHistory, *,
    now: datetime | None = None,
) -> DislocationPersistence:
    """Truthful current dislocation persistence using the existing threshold
    authority and the #179 discrete-observation policy.

    True start-time semantics:
      - the FIRST usable observation already above threshold does NOT prove
        when the dislocation began → PREHISTORY_UNAVAILABLE;
      - a proven crossing (from below/at threshold to above) anchors the
        start to the first above-threshold observation;
      - continuity breaks on missing/unusable evidence — duration never
        bridges a gap;
      - no interpolation, no prediction.
    """
    now = now or datetime.now(timezone.utc)
    threshold = dislocation_threshold_bps()

    # Extract usable chronological evidence (deduplicated).
    seen: set[tuple[str, str]] = set()
    usable: list[tuple[datetime, Decimal]] = []
    for point in history.points:
        if not point.t or point.v is None:
            continue
        basis = _parse_basis(point.v)
        if basis is None:
            continue
        key = (point.t, str(basis))
        if key in seen:
            continue
        seen.add(key)
        try:
            dt = datetime.fromisoformat(point.t)
            if dt.tzinfo is None:
                continue
            usable.append((dt.astimezone(timezone.utc), basis))
        except ValueError:
            continue
    usable.sort(key=lambda pair: pair[0])

    if not usable:
        return DislocationPersistence(
            state=DislocationState.UNAVAILABLE.value,
            start_state=DislocationStartState.UNAVAILABLE.value,
            started_at=None, duration_seconds=None,
            threshold_bps=str(threshold))

    # Determine current dislocation state from the latest usable point.
    latest_dt, latest_basis = usable[-1]
    if abs(latest_basis) < threshold:
        return DislocationPersistence(
            state=DislocationState.WITHIN_THRESHOLD.value,
            start_state=DislocationStartState.NO_DISLOCATION.value,
            started_at=None, duration_seconds=None,
            threshold_bps=str(threshold))

    current_state = (DislocationState.PREMIUM_DISLOCATION.value
                     if latest_basis > 0
                     else DislocationState.DISCOUNT_DISLOCATION.value)

    # Walk backwards to find the proven start of the CURRENT episode.
    # Continuity breaks on any gap in usable evidence or on a transition
    # back to within-threshold.  The first usable observation being above
    # threshold means PREHISTORY_UNAVAILABLE (we cannot prove when it began).
    episode_start: datetime | None = None
    prehistory = True

    for i in range(len(usable) - 1, -1, -1):
        dt_i, basis_i = usable[i]
        above = abs(basis_i) >= threshold

        if above:
            episode_start = dt_i
            if i == 0:
                # First observation is already above threshold: prehistory.
                break
            _, prev_basis = usable[i - 1]
            if abs(prev_basis) < threshold:
                # Proven crossing: previous point was within threshold.
                prehistory = False
                break
            # Previous point also above threshold (same episode continues).
        else:
            # Transition to within threshold — episode ended here.
            break

    if episode_start is None:
        return DislocationPersistence(
            state=current_state,
            start_state=DislocationStartState.UNAVAILABLE.value,
            started_at=None, duration_seconds=None,
            threshold_bps=str(threshold))

    start_state = (DislocationStartState.PREHISTORY_UNAVAILABLE.value
                   if prehistory
                   else DislocationStartState.PROVEN_CROSSING.value)
    started_at = (episode_start.isoformat()
                  if start_state == DislocationStartState.PROVEN_CROSSING.value
                  else None)
    duration_seconds = (int((now - episode_start).total_seconds())
                        if started_at is not None else None)

    return DislocationPersistence(
        state=current_state,
        start_state=start_state,
        started_at=started_at,
        duration_seconds=duration_seconds,
        threshold_bps=str(threshold))


# ── Cross-asset dislocation monitor ──────────────────────────────────────────

@dataclass(frozen=True)
class DislocationMonitorRow:
    """One row in the cross-asset dislocation monitor."""

    canonical_asset_id: str
    underlying_name: str | None
    venue_id: str
    instrument_id: str
    representation_type: str
    current_basis_bps: str | None
    premium_discount: str | None       # PREMIUM / DISCOUNT / WITHIN_THRESHOLD
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
    integrity_reader: Callable[[str], dict | None] | None = None,
) -> list[DislocationMonitorRow]:
    """Cross-asset dislocation monitor over eligible Tokenized Markets
    underlyings.

    Ordering (documented, deterministic):
      1. current dislocations first (abs basis ≥ threshold)
      2. absolute current basis magnitude descending
      3. duration descending when proven
      4. canonical identity stable tie-break

    ``integrity_reader(canonical_asset_id) -> {"state": str} | None`` is an
    optional injected #182 Integrity reader.  When provided, integrity
    state is composed (not recomputed) alongside market analytics.
    """
    now = now or datetime.now(timezone.utc)
    from finco_radar.venues.intelligence import build_tokenized_intelligence

    underlyings = sorted(registry._underlyings)
    if symbols is not None:
        symbol_set = {s.strip().upper() for s in symbols}
        underlyings = [s for s in underlyings if s in symbol_set]

    rows: list[DislocationMonitorRow] = []
    for symbol in underlyings:
        resolved = registry.representations_for_underlying(symbol)
        active = [r for r in resolved
                  if r.status.value == "ACTIVE"]
        if not active:
            continue
        try:
            intel = build_tokenized_intelligence(
                symbol, registry=registry, store=store, as_of=now,
                include_points=False)
        except Exception:
            continue

        integrity = (integrity_reader(symbol) if integrity_reader else None)
        integrity_state = integrity.get("state") if integrity else None

        underlying_name = getattr(
            registry.get_underlying(symbol), "underlying_name", None)

        for history in intel.representations:
            basis = _parse_basis(history.latest_basis_bps)
            threshold = dislocation_threshold_bps()
            if basis is not None:
                pd_state = ("PREMIUM" if basis > threshold
                            else "DISCOUNT" if basis < -threshold
                            else "WITHIN_THRESHOLD")
            else:
                pd_state = None

            distribution = compute_basis_distribution(
                history, current_basis_bps=history.latest_basis_bps, now=now)
            persistence = compute_dislocation_persistence(history, now=now)

            cross_bps = None
            if (intel.cross_venue is not None
                    and hasattr(intel.cross_venue, "divergence_bps")):
                cross_bps = str(intel.cross_venue.divergence_bps)

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
                observed_at=(history.points[-1].t if history.points else None),
            ))

    # Documented deterministic ordering.
    threshold = dislocation_threshold_bps()

    def _sort_key(row: DislocationMonitorRow):
        basis = _parse_basis(row.current_basis_bps)
        dislocated = basis is not None and abs(basis) >= threshold
        return (
            0 if dislocated else 1,                       # dislocations first
            -(abs(basis) if basis is not None else 0),    # magnitude descending
            -(row.current_dislocation_duration_seconds or 0),  # duration desc
            row.canonical_asset_id, row.venue_id, row.instrument_id,  # stable tie
        )

    rows.sort(key=_sort_key)
    return rows
