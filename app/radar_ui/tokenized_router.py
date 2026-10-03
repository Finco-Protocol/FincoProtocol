"""Tokenized Markets product surface (PR 3b) — read-only composition over
the canonical venue registry and persisted market observations.

UNDERLYING → REPRESENTATIONS mental model.  Exact identity authority
(``finco_radar.venues.VenueRegistry``); existing bound-reference authority
for the underlying; persisted ``VenueMarketStore`` history where collected.
No UI-triggered acquisition and no execution/trading. Live observations are
written only by the separate bounded Tokenized collector runtime.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_templates = Jinja2Templates(directory=os.path.join(_REPO_ROOT, "templates"))

# Landing universe cap: the seed carries ~1.5k underlyings; the first
# product surface lists a bounded, deterministic subset (performance +
# readability).  Exact detail pages resolve any canonical symbol.
_DEFAULT_LANDING_LIMIT = 60


def _registry():
    from finco_radar.venues.registry import VenueRegistry
    return VenueRegistry.load()


def _store():
    """Persisted-observation store when a venue DB actually exists —
    absent DB simply means no market history yet (truthful state)."""
    from finco_radar.venues.store import VenueMarketStore, default_db_path
    path = os.getenv("FINCO_VENUE_DB_PATH", default_db_path())
    if not os.path.exists(path):
        return None
    try:
        return VenueMarketStore(path)
    except Exception:
        # Market-history storage is observational infrastructure. A broken
        # collector/store must degrade this read-only surface to unavailable,
        # never take down the web runtime or trigger replacement acquisition.
        return None



def _collector_health():
    """Read operational collector health without creating/writing state."""
    try:
        from finco_radar.venues.health import read_tokenized_collector_health
        return read_tokenized_collector_health().public_dict()
    except Exception:
        return {
            "health_state": "UNHEALTHY",
            "liveness": "UNKNOWN",
            "last_attempt_at": None,
            "last_success_at": None,
            "outcome": "UNAVAILABLE",
            "failure_reason": "COLLECTOR_HEALTH_UNAVAILABLE",
        }


def _intelligence(canonical_asset_id: str, registry, store, *,
                  include_points: bool, as_of: datetime | None = None):
    if store is None:
        return None
    try:
        from finco_radar.venues.intelligence import build_tokenized_intelligence
        return build_tokenized_intelligence(
            canonical_asset_id, registry=registry, store=store,
            include_points=include_points, as_of=as_of)
    except Exception:
        return None

def _persisted_reference_reader(store, *, as_of: datetime):
    """Read underlying reference evidence only from canonical persisted history.

    This is deliberately network-free. The collector owns provider acquisition;
    browser requests can only consume what was already persisted.
    """
    from finco_radar.venues.intelligence import market_max_age_seconds

    def read(symbol: str) -> list[dict]:
        if store is None:
            return []
        observation = store.get_latest_reference_for_underlying(symbol)
        if observation is None or observation.reference_price is None:
            return []
        payload = observation.payload if isinstance(observation.payload, dict) else {}
        source_stamp = payload.get("reference_observed_at")
        source_state = str(payload.get("reference_state") or "UNAVAILABLE")
        source = payload.get("reference_source")
        state = "UNAVAILABLE"
        if source_state in ("AVAILABLE", "FRESH") and source_stamp:
            try:
                stamp = datetime.fromisoformat(str(source_stamp))
                if stamp.tzinfo is not None and stamp.utcoffset() is not None:
                    age = (as_of.astimezone(timezone.utc)
                           - stamp.astimezone(timezone.utc)).total_seconds()
                    if -60 <= age <= market_max_age_seconds():
                        state = "FRESH"
                    elif age > market_max_age_seconds():
                        state = "STALE"
            except (TypeError, ValueError):
                state = "UNAVAILABLE"
        elif source_state == "STALE":
            state = "STALE"
        return [{
            "uid": None,
            "symbol": symbol,
            "state": state,
            "price": observation.reference_price,
            "bid": None,
            "ask": None,
            "observed_at": source_stamp,
            "source": source,
        }]

    return read


@router.get("/radar/tokenized-markets", response_class=HTMLResponse)
async def tokenized_markets_landing(request: Request):
    """UNDERLYING → REPRESENTATIONS cross-venue composition landing."""
    from app.radar_ui.tokenized_composition import (
        compose_underlying, list_supported_underlyings,
    )
    from app.auth import resolve_request_session

    from app.radar_ui.tokenized_gating import redact_landing_row, resolve_tokenized_gates

    user = resolve_request_session(request)
    registry = _registry()
    store = _store()
    now = datetime.now(timezone.utc)
    reference_reader = _persisted_reference_reader(store, as_of=now)
    # Canonical access decisions (public basic; holder history / dislocation). Gating off keeps the
    # existing ungated behaviour; protected payload is removed from the context when denied.
    gates = await resolve_tokenized_gates(request)

    universe = list_supported_underlyings(registry)
    featured_first = _order_featured_first(universe)
    limit = int(os.getenv("RADAR_TOKENIZED_LANDING_LIMIT",
                          str(_DEFAULT_LANDING_LIMIT)))
    page_rows = featured_first[:limit]

    # Browser path is network-free: all market/reference evidence comes from
    # VenueMarketStore populated by the separate collector.

    composed = []
    for row in page_rows:
        try:
            view = compose_underlying(
                row["canonical_asset_id"], registry=registry,
                reference_reader=reference_reader, store=store, now=now)
        except Exception:
            continue  # a row that cannot compose never breaks the page
        intel = (_intelligence(
            row["canonical_asset_id"], registry, store,
            include_points=False, as_of=now) if gates.any_premium_allowed else None)
        composed.append(redact_landing_row(_landing_row(view, intel), gates))

    return _templates.TemplateResponse(
        request=request,
        name="radar/tokenized_markets.html",
        context={
            "user": user,
            "rows": composed,
            "total_underlyings": len(universe),
            "showing": len(composed),
            "history_available": store is not None and store.count() > 0,
            "collector_health": _collector_health(),
            "integrity": integrity,
            "access": gates.public_view(),
        },
    )


def _order_featured_first(universe: list[dict]) -> list[dict]:
    from app.radar_ui.router import _get_featured_symbols
    featured = [r for r in universe
                if r["canonical_asset_id"] in set(_get_featured_symbols())]
    rest = [r for r in universe
            if r["canonical_asset_id"] not in set(_get_featured_symbols())]
    return featured + rest


def _landing_row(view, intelligence=None) -> dict:
    best = None
    for representation in view.representations:
        # Correction B: quarantined evidence never qualifies for
        # closest-basis selection (has_market_data is False).
        if not representation.has_market_data or representation.price is None:
            continue
        if best is None or representation.basis_bps is not None and (
                best.basis_bps is None
                or abs(float(representation.basis_bps))
                < abs(float(best.basis_bps))):
            best = representation
    reference = view.reference
    history_row = None
    cross_venue = None
    if intelligence is not None:
        cross_venue = intelligence.cross_venue
        if best is not None:
            history_row = next(
                (item for item in intelligence.representations
                 if item.venue_id == best.venue_id
                 and item.instrument_id == best.instrument_id),
                None,
            )
    return {
        "canonical_asset_id": view.canonical_asset_id,
        "underlying_name": view.underlying_name,
        "reference_price": reference.get("price"),
        "reference_state": reference.get("state"),
        "reference_observed_at": reference.get("observed_at"),
        "representation_count": len(view.representations),
        "priced_count": len(view.priced_representations),
        "best_price": best.price if best else None,
        "best_basis_bps": best.basis_bps if best else None,
        "best_venue": best.venue_id if best else None,
        "basis_change_24h_bps": (
            history_row.basis_change_24h_bps if history_row else None),
        "basis_change_7d_bps": (
            history_row.basis_change_7d_bps if history_row else None),
        "cross_venue_state": (
            cross_venue.state if cross_venue is not None else "UNAVAILABLE"),
        "cross_venue_divergence_bps": (
            cross_venue.divergence_bps if cross_venue is not None else None),
        # Correction A #14: neutral selection semantics — the shown
        # representation is the one with the smallest absolute basis when a
        # basis exists ("Closest basis venue"); otherwise a neutral
        # "Representation" (no evaluative claim).
        "overall_state": view.overall_state,
        "evaluation_time": view.evaluation_time,
    }


@router.get("/radar/tokenized-markets/{canonical_asset_id}",
            response_class=HTMLResponse)
async def tokenized_markets_detail(request: Request, canonical_asset_id: str):
    """One canonical underlying: reference + representations + basis."""
    from app.radar_ui.tokenized_composition import compose_underlying
    from app.auth import resolve_request_session

    user = resolve_request_session(request)
    registry = _registry()

    # Correction A: prove the canonical underlying exists BEFORE any
    # reference read, provider seam, or store composition.
    from finco_radar.venues.models import canonical_underlying_symbol
    try:
        known_symbol = canonical_underlying_symbol(canonical_asset_id)
    except ValueError:
        known_symbol = None
    known = (known_symbol is not None and any(
        u.canonical_symbol == known_symbol
        for u in registry._underlyings.values()))
    if not known:
        from starlette.status import HTTP_404_NOT_FOUND
        return _templates.TemplateResponse(
            request=request,
            name="radar/tokenized_markets_detail.html",
            context={
                "user": user,
                "view": None,
                "reference": {},
                "history_available": False,
                "unknown": True,
                "canonical_asset_id": canonical_asset_id,
                "intelligence": None,
                "basis_series": [],
                "collector_health": _collector_health(),
            },
            status_code=HTTP_404_NOT_FOUND,
        )

    from app.radar_ui.tokenized_composition import UnknownCanonicalUnderlying

    store = _store()
    now = datetime.now(timezone.utc)
    reference_reader = _persisted_reference_reader(store, as_of=now)
    try:
        view = compose_underlying(
            canonical_asset_id, registry=registry,
            reference_reader=reference_reader, store=store, now=now)
    except UnknownCanonicalUnderlying:
        from starlette.status import HTTP_404_NOT_FOUND
        return _templates.TemplateResponse(
            request=request,
            name="radar/tokenized_markets_detail.html",
            context={
                "user": user,
                "view": None,
                "reference": {},
                "history_available": False,
                "unknown": True,
                "canonical_asset_id": canonical_asset_id,
                "intelligence": None,
                "basis_series": [],
                "collector_health": _collector_health(),
            },
            status_code=HTTP_404_NOT_FOUND,
        )

    from app.radar_ui.tokenized_gating import redact_intelligence, resolve_tokenized_gates

    gates = await resolve_tokenized_gates(request)
    intelligence = None
    if gates.any_premium_allowed:
        intelligence = redact_intelligence(
            _intelligence(
                canonical_asset_id, registry, store,
                include_points=gates.history.access_allowed, as_of=now),
            gates)
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

    # RWA Integrity is factual/public product evidence.  It reuses the exact
    # registry/store/reference context above and has no additional entitlement
    # or acquisition path.  Any evidence-dimension failure degrades fail-soft.
    integrity = None
    try:
        from app.crypto_terminal.integrity_read import detail_data
        integrity = detail_data(
            canonical_asset_id, now=now, registry=registry, store=store,
            reference_evidence_reader=reference_reader)
    except Exception:
        integrity = None

    return _templates.TemplateResponse(
        request=request,
        name="radar/tokenized_markets_detail.html",
        context={
            "user": user,
            "view": view,
            "reference": view.reference,
            # Correction A: per-underlying history truth from the view —
            # never the global store count.
            "history_available": view.history_available,
            "intelligence": intelligence,
            "basis_series": basis_series[:2],
            "collector_health": _collector_health(),
            "access": gates.public_view(),
        },
    )
