"""Shared Tokenized Markets read model for the UI router and the crypto API.

 thin composition layer over the EXISTING canonical surfaces — it owns no
 mathematics and no access logic:

    identity / composition   app.radar_ui.tokenized_composition
    history / divergence     finco_radar.venues.intelligence (frozen namespace)
    persistence              finco_radar.venues.store (read-only here)
    access decisions         app.radar_ui.tokenized_gating

Every function here is network-free: evidence comes only from the persisted
VenueMarketStore written by the separate collector runtime.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.radar_ui import tokenized_router as _surface


def registry():
    return _surface._registry()


def store():
    return _surface._store()


def collector_health() -> dict:
    return _surface._collector_health()


def landing_rows(*, gates, limit: int | None = None,
                 now: datetime | None = None) -> tuple[list[dict], dict]:
    """Landing rows + page meta.  ``gates`` decides whether premium fields
    (24h/7d basis movement, cross-venue divergence) are computed at all —
    denied payload is never built, only to be hidden afterwards."""
    from app.radar_ui.tokenized_composition import (
        compose_underlying, list_supported_underlyings,
    )
    from app.radar_ui.tokenized_gating import redact_landing_row

    now = now or datetime.now(timezone.utc)
    registry = _surface._registry()
    venue_store = _surface._store()
    reference_reader = _surface._persisted_reference_reader(venue_store, as_of=now)

    universe = list_supported_underlyings(registry)
    featured_first = _surface._order_featured_first(universe)
    if limit is None:
        limit = _surface._DEFAULT_LANDING_LIMIT
    page_rows = featured_first[:limit]

    composed = []
    for row in page_rows:
        try:
            view = compose_underlying(
                row["canonical_asset_id"], registry=registry,
                reference_reader=reference_reader, store=venue_store, now=now)
        except Exception:
            continue  # a row that cannot compose never breaks the page
        intel = (_surface._intelligence(
            row["canonical_asset_id"], registry, venue_store,
            include_points=False, as_of=now) if gates.any_premium_allowed else None)
        composed.append(redact_landing_row(_surface._landing_row(view, intel), gates))

    meta = {
        "total_underlyings": len(universe),
        "showing": len(composed),
        "history_available": venue_store is not None and venue_store.count() > 0,
        "collector_health": collector_health(),
    }
    return composed, meta


def detail(canonical_asset_id: str, *, gates, now: datetime | None = None) -> dict:
    """Detail read for one canonical underlying.  ``known`` is False when the
    canonical symbol is not in the registry (fail-closed unknown identity)."""
    from app.radar_ui.tokenized_composition import (
        UnknownCanonicalUnderlying, compose_underlying,
    )
    from app.radar_ui.tokenized_gating import redact_intelligence
    from finco_radar.venues.models import canonical_underlying_symbol

    now = now or datetime.now(timezone.utc)
    registry = _surface._registry()

    try:
        known_symbol = canonical_underlying_symbol(canonical_asset_id)
    except ValueError:
        known_symbol = None
    known = (known_symbol is not None and any(
        u.canonical_symbol == known_symbol
        for u in registry._underlyings.values()))
    if not known:
        return {"known": False, "view": None, "intelligence": None,
                "basis_series": [], "collector_health": collector_health(),
                "reference": {}, "history_available": False}

    venue_store = _surface._store()
    reference_reader = _surface._persisted_reference_reader(venue_store, as_of=now)
    try:
        view = compose_underlying(
            canonical_asset_id, registry=registry,
            reference_reader=reference_reader, store=venue_store, now=now)
    except UnknownCanonicalUnderlying:
        return {"known": False, "view": None, "intelligence": None,
                "basis_series": [], "collector_health": collector_health(),
                "reference": {}, "history_available": False}

    intelligence = None
    if gates.any_premium_allowed:
        intelligence = redact_intelligence(
            _surface._intelligence(
                canonical_asset_id, registry, venue_store,
                include_points=gates.history.access_allowed, as_of=now),
            gates)
    # R3 is a separate historical MARKET component, not an extra registry
    # representation or a modification to #183 own-history statistics.
    # Both existing premium entitlements are required for the combined
    # history + cross-venue result; denied payload is never computed.
    deepstate_history = None
    if (venue_store is not None and view.canonical_asset_id == "NVDA"
            and gates.history.access_allowed and gates.dislocation.access_allowed):
        from app.crypto_terminal.deepstate_composition import (
            DeepstateHistoricalMarketContext, build_deepstate_historical_context,
        )
        try:
            deepstate_history = build_deepstate_historical_context(
                view.canonical_asset_id, registry=registry, store=venue_store,
                as_of=now)  # no approved USDG/USD policy: fail closed by default
        except Exception:
            deepstate_history = DeepstateHistoricalMarketContext(
                view.canonical_asset_id, "UNAVAILABLE",
                "HISTORICAL_COMPARISON_UNAVAILABLE", (), ())
    basis_series = []
    if intelligence is not None:
        for item in intelligence.representations:
            points = [{"t": point.t, "v": point.v} for point in item.points]
            if any(point["v"] is not None for point in points):
                basis_series.append({
                    "venue_id": item.venue_id,
                    "instrument_id": item.instrument_id,
                    "points": points,
                })
    return {
        "known": True,
        "view": view,
        "intelligence": intelligence,
        "basis_series": basis_series[:2],
        "collector_health": collector_health(),
        "reference": view.reference,
        "history_available": view.history_available,
        "deepstate_history": deepstate_history,
    }
