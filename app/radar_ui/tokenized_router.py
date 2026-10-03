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


def _reference_reader(reference_map: dict[str, dict] | None = None):
    """Existing cached bound-reference authority (reused, not reimplemented).

    With a ``reference_map`` the reader serves rows from ONE batched board
    read (Correction A: no per-symbol singleton acquisition); symbols
    outside the map stay honestly REFERENCE_UNAVAILABLE.
    """
    from app.radar_ui.router import _market_read_service
    from app.radar_ui.router import _get_featured_symbols
    service = _market_read_service
    featured = set(_get_featured_symbols())
    reference_map = reference_map if reference_map is not None else {}

    def read(symbol: str) -> list[dict]:
        row = reference_map.get(symbol)
        if row is not None:
            return [row]
        if symbol in featured:
            # Single-symbol fallback (detail pages): one cached service read.
            return service.read(featured_symbols=(symbol,))
        # Non-featured underlyings have no bound-reference authority row in
        # the current product — reference stays honestly unavailable.
        return []
    return read


def _batched_reference_map(symbols: tuple[str, ...]) -> dict[str, dict]:
    """ONE MarketReadService.read for all needed featured symbols, then an
    exact symbol → row map (Correction A: no N singleton reads)."""
    from app.radar_ui.router import _market_read_service
    if not symbols:
        return {}
    rows = _market_read_service.read(featured_symbols=tuple(symbols))
    return {row.get("symbol"): row for row in rows if row.get("symbol")}


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
    page_rows = featured_first[:limit]

    # Correction A: ONE batched reference read for every needed featured
    # symbol on this page (Fast & Fresh friendly — never N singleton reads).
    from app.radar_ui.router import _get_featured_symbols
    needed = tuple(
        row["canonical_asset_id"] for row in page_rows
        if row["canonical_asset_id"] in set(_get_featured_symbols()))
    reference_map = _batched_reference_map(needed)
    reference_reader = _reference_reader(reference_map)

    composed = []
    for row in page_rows:
        try:
            view = compose_underlying(
                row["canonical_asset_id"], registry=registry,
                reference_reader=reference_reader, store=store)
        except Exception:
            continue  # a row that cannot compose never breaks the page
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
            },
            status_code=HTTP_404_NOT_FOUND,
        )

    from app.radar_ui.tokenized_composition import UnknownCanonicalUnderlying

    store = _store()
    reference_reader = _reference_reader()
    try:
        view = compose_underlying(
            canonical_asset_id, registry=registry,
            reference_reader=reference_reader, store=store)
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
            },
            status_code=HTTP_404_NOT_FOUND,
        )

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
        },
    )
