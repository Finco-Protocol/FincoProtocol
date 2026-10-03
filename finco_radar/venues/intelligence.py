"""Read-only Tokenized Markets history and dislocation intelligence.

This module never acquires market data and never writes history. It consumes
only exact canonical VenueRegistry identities plus append-only
VenueMarketStore observations.

No interpolation or synthetic backfill is performed. Missing values remain
None. Dislocations are evidence/reference divergences, never executable
arbitrage claims.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import os
from typing import Iterable

from finco_radar.venues.basis import (
    BASIS_MAX_CLOCK_SKEW_SECONDS,
    basis_for_evidence,
)
from finco_radar.venues.models import RegistryStatus
from finco_radar.venues.observations import MarketObservation, ObservationStatus
from finco_radar.venues.registry import VenueRegistry
from finco_radar.venues.store import VenueMarketStore

DEFAULT_MARKET_MAX_AGE_SECONDS = 15 * 60
DEFAULT_DISLOCATION_THRESHOLD_BPS = Decimal("100")
HORIZONS = (("24h", timedelta(hours=24)), ("7d", timedelta(days=7)))
HISTORY_WINDOW = timedelta(days=7)


@dataclass(frozen=True)
class BasisPoint:
    t: str
    v: str | None
    reason: str | None


@dataclass(frozen=True)
class RepresentationHistory:
    venue_id: str
    instrument_id: str
    representation_type: str
    current_state: str
    latest_price: str | None
    latest_basis_bps: str | None
    latest_basis_reason: str | None
    basis_change_24h_bps: str | None
    basis_change_7d_bps: str | None
    points: tuple[BasisPoint, ...]


@dataclass(frozen=True)
class CrossVenueDivergence:
    state: str
    divergence_bps: str | None
    low_venue: str | None
    high_venue: str | None
    low_price: str | None
    high_price: str | None
    comparison_unit: str | None
    reason: str | None


@dataclass(frozen=True)
class DislocationEvent:
    observed_at: str
    event_type: str
    venue_id: str | None
    instrument_id: str | None
    value_bps: str
    direction: str
    threshold_bps: str


@dataclass(frozen=True)
class TokenizedIntelligence:
    canonical_asset_id: str
    generated_at: str
    representations: tuple[RepresentationHistory, ...]
    cross_venue: CrossVenueDivergence
    events: tuple[DislocationEvent, ...]


def market_max_age_seconds() -> int:
    raw = os.getenv("FINCO_TOKENIZED_MARKET_MAX_AGE_SECONDS", "").strip()
    if not raw:
        return DEFAULT_MARKET_MAX_AGE_SECONDS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MARKET_MAX_AGE_SECONDS
    return value if 60 <= value <= 86400 else DEFAULT_MARKET_MAX_AGE_SECONDS


def dislocation_threshold_bps() -> Decimal:
    raw = os.getenv("FINCO_TOKENIZED_DISLOCATION_THRESHOLD_BPS", "").strip()
    if not raw:
        return DEFAULT_DISLOCATION_THRESHOLD_BPS
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return DEFAULT_DISLOCATION_THRESHOLD_BPS
    if not value.is_finite() or value <= 0 or value > Decimal("10000"):
        return DEFAULT_DISLOCATION_THRESHOLD_BPS
    return value


def _parse_aware(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def effective_observation_state(
    observation: MarketObservation | None,
    *,
    as_of: datetime,
    max_age_seconds: int | None = None,
) -> str:
    """Read-time market state from immutable source evidence."""
    if observation is None or observation.price is None:
        return "UNAVAILABLE"
    if observation.observation_status is ObservationStatus.QUARANTINED:
        return "QUARANTINED"
    stored = observation.freshness_state.value
    if stored == "UNAVAILABLE":
        return "UNAVAILABLE"
    if stored == "STALE":
        return "STALE"
    source_time = _parse_aware(observation.ts)
    if source_time is None:
        return "UNAVAILABLE"
    age = (as_of.astimezone(timezone.utc) - source_time).total_seconds()
    if age < -60:
        return "UNAVAILABLE"
    ceiling = max_age_seconds if max_age_seconds is not None else market_max_age_seconds()
    return "AVAILABLE" if age <= ceiling else "STALE"


def _entry_identity(entry) -> tuple[str, str]:
    venue_id = entry.network or entry.platform
    instrument_id = entry.contract_address or entry.representation_symbol.strip().upper()
    return venue_id, instrument_id


def _basis_from_observation(observation: MarketObservation) -> tuple[str | None, str | None]:
    if observation.observation_status is ObservationStatus.QUARANTINED:
        return None, "REPRESENTATION_QUARANTINED"
    payload = observation.payload if isinstance(observation.payload, dict) else {}
    reference_state = str(payload.get("reference_state") or (
        "AVAILABLE" if observation.reference_price is not None else "UNAVAILABLE"
    ))
    reference_observed_at = payload.get("reference_observed_at")
    return basis_for_evidence(
        representation_price=observation.price,
        representation_state=observation.freshness_state.value,
        representation_source_timestamp=observation.ts,
        reference_price=observation.reference_price,
        reference_state=reference_state,
        reference_source_timestamp=reference_observed_at,
    )


def _basis_decimal(observation: MarketObservation | None) -> Decimal | None:
    if observation is None:
        return None
    value, _reason = _basis_from_observation(observation)
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _basis_change(
    store: VenueMarketStore,
    *,
    canonical_asset_id: str,
    venue_id: str,
    instrument_id: str,
    latest: MarketObservation | None,
    horizon: timedelta,
) -> str | None:
    if latest is None or latest.canonical_asset_id.upper() != canonical_asset_id.upper():
        return None
    latest_time = _parse_aware(latest.ts)
    latest_basis = _basis_decimal(latest)
    if latest_time is None or latest_basis is None:
        return None
    baseline = store.get_latest_at_or_before_for_instrument(
        instrument_id,
        venue_id=venue_id,
        before=latest_time - horizon,
    )
    if (baseline is None
            or baseline.canonical_asset_id.upper() != canonical_asset_id.upper()):
        return None
    baseline_basis = _basis_decimal(baseline)
    if baseline_basis is None:
        return None
    return str(latest_basis - baseline_basis)


def _history_for_representation(
    store: VenueMarketStore,
    *,
    canonical_asset_id: str,
    venue_id: str,
    instrument_id: str,
    representation_type: str,
    as_of: datetime,
    include_points: bool,
) -> RepresentationHistory:
    latest = store.get_latest_for_instrument(instrument_id, venue_id=venue_id)
    if (latest is not None
            and latest.canonical_asset_id.upper() != canonical_asset_id.upper()):
        latest = None
    current_state = effective_observation_state(latest, as_of=as_of)
    latest_basis = None
    latest_reason = "REPRESENTATION_PRICE_UNAVAILABLE"
    if latest is not None:
        latest_basis, latest_reason = _basis_from_observation(latest)

    points: tuple[BasisPoint, ...] = ()
    if include_points:
        rows = store.get_window_for_instrument(
            instrument_id,
            venue_id=venue_id,
            since=as_of - HISTORY_WINDOW,
            until=as_of,
        )
        built: list[BasisPoint] = []
        for row in rows:
            if row.canonical_asset_id.upper() != canonical_asset_id.upper():
                continue
            basis, reason = _basis_from_observation(row)
            built.append(BasisPoint(t=row.ts or "", v=basis, reason=reason))
        points = tuple(built)

    return RepresentationHistory(
        venue_id=venue_id,
        instrument_id=instrument_id,
        representation_type=representation_type,
        current_state=current_state,
        latest_price=latest.price if latest is not None else None,
        latest_basis_bps=latest_basis,
        latest_basis_reason=latest_reason,
        basis_change_24h_bps=_basis_change(
            store, canonical_asset_id=canonical_asset_id,
            venue_id=venue_id, instrument_id=instrument_id,
            latest=latest, horizon=timedelta(hours=24)),
        basis_change_7d_bps=_basis_change(
            store, canonical_asset_id=canonical_asset_id,
            venue_id=venue_id, instrument_id=instrument_id,
            latest=latest, horizon=timedelta(days=7)),
        points=points,
    )


def _cross_venue(
    histories: Iterable[RepresentationHistory],
    store: VenueMarketStore,
    *,
    as_of: datetime,
) -> CrossVenueDivergence:
    comparable: list[tuple[RepresentationHistory, MarketObservation, str]] = []
    for history in histories:
        if history.current_state != "AVAILABLE":
            continue
        latest = store.get_latest_for_instrument(
            history.instrument_id, venue_id=history.venue_id)
        if latest is None or latest.price is None:
            continue
        payload = latest.payload if isinstance(latest.payload, dict) else {}
        unit = payload.get("comparison_unit")
        if not isinstance(unit, str) or not unit.strip():
            continue
        comparable.append((history, latest, unit.strip()))

    if len(comparable) < 2:
        return CrossVenueDivergence(
            "UNAVAILABLE", None, None, None, None, None, None,
            "COMPARABLE_VENUE_EVIDENCE_UNAVAILABLE")

    units = {unit for _history, _obs, unit in comparable}
    if len(units) != 1:
        return CrossVenueDivergence(
            "UNAVAILABLE", None, None, None, None, None, None,
            "COMPARISON_UNIT_MISMATCH")

    parsed: list[tuple[RepresentationHistory, MarketObservation, Decimal, datetime]] = []
    for history, obs, _unit in comparable:
        stamp = _parse_aware(obs.ts)
        try:
            price = Decimal(obs.price) if obs.price is not None else None
        except InvalidOperation:
            price = None
        if stamp is None or price is None or not price.is_finite() or price <= 0:
            continue
        parsed.append((history, obs, price, stamp))
    if len(parsed) < 2:
        return CrossVenueDivergence(
            "UNAVAILABLE", None, None, None, None, None, None,
            "COMPARABLE_VENUE_EVIDENCE_UNAVAILABLE")

    oldest = min(item[3] for item in parsed)
    newest = max(item[3] for item in parsed)
    if (newest - oldest).total_seconds() > BASIS_MAX_CLOCK_SKEW_SECONDS:
        return CrossVenueDivergence(
            "UNAVAILABLE", None, None, None, None, None, next(iter(units)),
            "CROSS_VENUE_EVIDENCE_SKEW_EXCEEDED")

    low = min(parsed, key=lambda item: item[2])
    high = max(parsed, key=lambda item: item[2])
    if low[2] <= 0:
        return CrossVenueDivergence(
            "UNAVAILABLE", None, None, None, None, None, next(iter(units)),
            "CROSS_VENUE_ARITHMETIC_INVALID")
    divergence = ((high[2] / low[2]) - Decimal(1)) * Decimal(10_000)
    divergence = divergence.quantize(Decimal("1"))
    return CrossVenueDivergence(
        "AVAILABLE",
        str(divergence),
        low[0].venue_id,
        high[0].venue_id,
        str(low[2]),
        str(high[2]),
        next(iter(units)),
        None,
    )


def _events(
    histories: Iterable[RepresentationHistory],
    cross_venue: CrossVenueDivergence,
) -> tuple[DislocationEvent, ...]:
    threshold = dislocation_threshold_bps()
    events: list[DislocationEvent] = []
    for history in histories:
        previous: Decimal | None = None
        for point in history.points:
            current = None
            if point.v is not None:
                try:
                    current = Decimal(point.v)
                except InvalidOperation:
                    current = None
            if current is None:
                previous = None
                continue
            crossed = abs(current) >= threshold and (
                previous is None
                or abs(previous) < threshold
                or (previous < 0 < current)
                or (previous > 0 > current)
            )
            if crossed:
                events.append(DislocationEvent(
                    observed_at=point.t,
                    event_type="REFERENCE_DIVERGENCE",
                    venue_id=history.venue_id,
                    instrument_id=history.instrument_id,
                    value_bps=str(current),
                    direction="PREMIUM" if current > 0 else "DISCOUNT" if current < 0 else "FLAT",
                    threshold_bps=str(threshold),
                ))
            previous = current

    if cross_venue.state == "AVAILABLE" and cross_venue.divergence_bps is not None:
        try:
            cross_value = Decimal(cross_venue.divergence_bps)
        except InvalidOperation:
            cross_value = None
        if cross_value is not None and abs(cross_value) >= threshold:
            events.append(DislocationEvent(
                observed_at="CURRENT",
                event_type="CROSS_VENUE_DIVERGENCE",
                venue_id=None,
                instrument_id=None,
                value_bps=str(cross_value),
                direction="DIVERGENCE",
                threshold_bps=str(threshold),
            ))

    events.sort(key=lambda event: event.observed_at)
    return tuple(events[-20:])


def build_tokenized_intelligence(
    canonical_asset_id: str,
    *,
    registry: VenueRegistry,
    store: VenueMarketStore,
    as_of: datetime | None = None,
    include_points: bool = True,
) -> TokenizedIntelligence:
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    now = now.astimezone(timezone.utc)
    underlying = registry.get_underlying(canonical_asset_id)
    if underlying is None:
        raise KeyError(canonical_asset_id)

    histories: list[RepresentationHistory] = []
    for resolved in registry.representations_for_underlying(
            underlying.canonical_symbol):
        if resolved.status is not RegistryStatus.ACTIVE:
            continue
        entry = resolved.entry
        venue_id, instrument_id = _entry_identity(entry)
        histories.append(_history_for_representation(
            store,
            canonical_asset_id=underlying.canonical_symbol,
            venue_id=venue_id,
            instrument_id=instrument_id,
            representation_type=entry.instrument_type,
            as_of=now,
            include_points=include_points,
        ))

    cross = _cross_venue(histories, store, as_of=now)
    events = _events(histories, cross) if include_points else ()
    return TokenizedIntelligence(
        canonical_asset_id=underlying.canonical_symbol,
        generated_at=now.isoformat(),
        representations=tuple(histories),
        cross_venue=cross,
        events=events,
    )
