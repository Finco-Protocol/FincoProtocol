"""Tokenized Markets product surface (PR 3b) — read-only composition over
the canonical venue registry and persisted market observations.

UNDERLYING → REPRESENTATIONS mental model.  Exact identity authority
(``finco_radar.venues.VenueRegistry``); existing bound-reference authority
for the underlying; persisted ``VenueMarketStore`` history where collected.
No new provider, no runtime collector wiring, no execution/trading.
"""
from __future__ import annotations

import os

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
    return VenueMarketStore(path)


def _reference_reader():
    """Existing cached bound-reference authority (reused, not reimplemented)."""
    from app.radar_ui.router import _market_read_service
    from app.radar_ui.router import _get_featured_symbols
    service = _market_read_service
    featured = set(_get_featured_symbols())

    def read(symbol: str) -> list[dict]:
        if symbol not in featured:
            # Non-featured underlyings have no bound-reference authority row
            # in the current product — reference stays honestly unavailable.
            return []
        return service.read(featured_symbols=(symbol,))
    return read


@router.get("/radar/tokenized-markets", response_class=HTMLResponse)
async def tokenized_markets_landing(request: Request):
    """UNDERLYING → REPRESENTATIONS cross-venue composition landing."""
    from app.radar_ui.tokenized_composition import (
        compose_underlying, list_supported_underlyings,
    )
    from app.auth import resolve_request_session

    user = resolve_request_session(request)
    registry = _registry()
    store = _store()
    reference_reader = _reference_reader()

    universe = list_supported_underlyings(registry)
    featured_first = _order_featured_first(universe)
    limit = int(os.getenv("RADAR_TOKENIZED_LANDING_LIMIT",
                          str(_DEFAULT_LANDING_LIMIT)))

    composed = []
    for row in featured_first[:limit]:
        view = compose_underlying(
            row["canonical_asset_id"], registry=registry,
            reference_reader=reference_reader, store=store)
        composed.append(_landing_row(view))

    return _templates.TemplateResponse(
        request=request,
        name="radar/tokenized_markets.html",
        context={
            "user": user,
            "rows": composed,
            "total_underlyings": len(universe),
            "showing": len(composed),
            "history_available": store is not None and store.count() > 0,
        },
    )


def _order_featured_first(universe: list[dict]) -> list[dict]:
    from app.radar_ui.router import _get_featured_symbols
    featured = [r for r in universe
                if r["canonical_asset_id"] in set(_get_featured_symbols())]
    rest = [r for r in universe
            if r["canonical_asset_id"] not in set(_get_featured_symbols())]
    return featured + rest


def _landing_row(view) -> dict:
    best = None
    for representation in view.representations:
        if representation.price is None:
            continue
        if best is None or representation.basis_bps is not None and (
                best.basis_bps is None
                or abs(float(representation.basis_bps))
                < abs(float(best.basis_bps))):
            best = representation
    reference = view.reference
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
    store = _store()
    reference_reader = _reference_reader()

    try:
        view = compose_underlying(
            canonical_asset_id, registry=registry,
            reference_reader=reference_reader, store=store)
    except ValueError:
        from fastapi.responses import HTMLResponse as _HTML
        return _HTML("<h1>Unknown canonical underlying</h1>", status_code=404)

    return _templates.TemplateResponse(
        request=request,
        name="radar/tokenized_markets_detail.html",
        context={
            "user": user,
            "view": view,
            "reference": view.reference,
            "history_available": store is not None and store.count() > 0,
        },
    )
