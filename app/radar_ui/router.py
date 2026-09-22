"""Radar v1 UI router (P2/P6/P7/P9).

Browser-reachable surface.  Routes NEVER call providers directly and
NEVER import private live_proof helpers:

- ``GET  /radar``                                 page shell with live universe
- ``POST /radar/refresh``                         ONE acquire -> ONE snapshot_id
- ``GET  /radar/snapshot/{snapshot_id}``          re-render panels (network-free)
- ``GET  /radar/inspector/{snapshot_id}/{field}`` Evidence Inspector (network-free)

Every detail endpoint takes the exact ``snapshot_id`` and reads through
the P1 ``AcquisitionService.get_snapshot`` network-free path.  No HTMX
partial can trigger acquisition.

Multi-asset: GET /radar fetches the live Robinhood universe via the frozen
RobinhoodAssetRegistryAdapter.  POST /radar/refresh requires an asset_uid
form field; the server resolves the exact UID/chain/contract/decimals from
a fresh registry snapshot.  Missing or unknown asset_uid fails closed with
a stable reason and zero acquisition calls.

Stale-identity prevention:
- HTMX: panels.html emits an OOB swap that updates #radar-asset-header
  (is_htmx_partial=True in context).
- Non-JS: _selected_from_snapshot_identity derives selected from the
  snapshot's authoritative identity after acquisition.
- Snapshot query: GET /radar?snapshot_id=X derives selected from the
  snapshot identity, not from the query asset_uid.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.radar_runtime.contracts import RadarRuntimeError
from app.radar_ui import composition, equity_enrichment, equity_terminal, equity_view_model, view_model

# Featured equities default — symbols present in the canonical Robinhood universe.
# Override with RADAR_FEATURED_EQUITY_SYMBOLS (comma-separated).
_DEFAULT_FEATURED_SYMBOLS = (
    "AAPL", "NVDA", "MSFT", "AMZN", "GOOGL",
    "META", "TSLA", "AVGO", "JPM", "V",
    "WMT", "NFLX", "AMD", "ORCL", "PLTR",
)


def _get_featured_symbols() -> tuple:
    raw = os.environ.get("RADAR_FEATURED_EQUITY_SYMBOLS", "")
    if raw.strip():
        return tuple(s.strip() for s in raw.split(",") if s.strip())
    return _DEFAULT_FEATURED_SYMBOLS

router = APIRouter()

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_templates = Jinja2Templates(
    directory=os.path.join(_APP_DIR, "templates"))


def _intcomma(v):
    try:
        return "{:,}".format(int(float(str(v))))
    except (ValueError, TypeError):
        return str(v) if v else ""


_templates.env.filters["intcomma"] = _intcomma

_service_instance = None


def get_service():
    """Lazily build the canonical P1 acquisition service."""
    global _service_instance
    if _service_instance is None:
        _service_instance = composition.build_service()
    return _service_instance


def set_service(service) -> None:
    """Test/diagnostic seam: inject a service with offline fake providers."""
    global _service_instance
    _service_instance = service


def _fetch_universe_safe():
    """Fetch the Robinhood asset universe; returns (list, error_str|None)."""
    try:
        universe = composition.fetch_robinhood_asset_universe()
        return universe, None
    except Exception as exc:  # noqa: BLE001
        return [], type(exc).__name__


def _resolve_selected(universe, uid: str):
    """Resolve SelectedAsset from universe by uid (case-insensitive).

    When uid is provided and not found, returns None (fail-closed).
    When uid is empty, falls back to the first AAPL asset (convenience
    default for GET /radar with no explicit selection).
    Returns None if the universe is empty."""
    if not universe:
        return None
    if uid:
        uid_lower = uid.lower()
        for a in universe:
            if a.economic_asset_uid.lower() == uid_lower:
                return a
        return None  # explicit uid not found — fail closed
    # Default for empty uid: AAPL if present, else first
    for a in universe:
        if a.token_symbol == "AAPL":
            return a
    return universe[0]


def _get_snapshot_uid(snapshot) -> str:
    """Extract economicAssetUid from a snapshot's payload; empty string on
    failure."""
    try:
        return snapshot.to_payload().get("economicAssetUid", "") or ""
    except Exception:  # noqa: BLE001
        return ""


def _load_equity_and_featured_board(
    universe: list,
    selected,
    fallback_name: str = "",
) -> tuple:
    """Unified equity detail + featured board load.

    Performs at most one batch read (for all featured assets) plus at most one
    additional single read (only when selected is NOT already in the featured
    set).  When selected is featured, its EquityEnrichmentResult is reused from
    the batch — zero extra single reads.

    Selected-detail reuse is UID-first: a featured batch result is reused only
    when the featured SelectedAsset is the SAME canonical identity as selected,
    proven by equal economic_asset_uid, chain_id, and contract_address
    (case-insensitive).  Token symbol alone is never sufficient.

    Featured resolution is duplicate-safe: a configured symbol with >1 live
    matches is skipped from the board rather than silently choosing one.

    Returns (equity_view_dict, featured_board_rows).
    """
    featured_symbols = _get_featured_symbols()

    # Build per-symbol match lists to detect duplicates — fail closed on ambiguity.
    symbol_to_assets: dict = {}
    for a in universe:
        sym_upper = a.token_symbol.upper()
        if sym_upper not in symbol_to_assets:
            symbol_to_assets[sym_upper] = []
        symbol_to_assets[sym_upper].append(a)

    # Featured assets in configured order:
    #   0 matches  → skip (not in live universe)
    #   1 match    → include
    #   >1 matches → skip (ambiguous; do not silently choose)
    featured_assets = []
    for sym in featured_symbols:
        matches = symbol_to_assets.get(sym.upper(), [])
        if len(matches) == 1:
            featured_assets.append(matches[0])

    # ONE batch read for all featured assets.
    if featured_assets:
        pairs = [(a.token_symbol, a.contract_address) for a in featured_assets]
        featured_results = equity_enrichment.enrich_many_selected_assets(pairs)
    else:
        featured_results = ()

    # featured_pairs carries both identity and result for UID-first reuse below.
    featured_pairs = list(zip(featured_assets, featured_results))

    # Build board rows — pass token_symbol separately so UID never leaks into
    # the symbol column.
    rows = [
        equity_view_model.build_equity_board_row(
            result,
            asset_uid=asset.economic_asset_uid,
            fallback_name=asset.token_name,
            token_symbol=asset.token_symbol,
        )
        for asset, result in featured_pairs
    ]

    # Equity view for the selected asset.
    equity_view: dict = {}
    if selected is not None:
        # UID-first reuse: selected may reuse a featured batch result ONLY when
        # the featured SelectedAsset is the SAME canonical identity — equal
        # economic_asset_uid, chain_id, and contract_address (case-insensitive).
        selected_result = None
        for feat_asset, feat_result in featured_pairs:
            if (
                feat_asset.economic_asset_uid == selected.economic_asset_uid
                and feat_asset.chain_id == selected.chain_id
                and feat_asset.contract_address.lower() == selected.contract_address.lower()
            ):
                selected_result = feat_result
                break

        if selected_result is not None:
            equity_view = equity_view_model.build_equity_view(
                selected_result, fallback_name=fallback_name,
            )
        else:
            # Not featured (or ambiguous) — one additional single read.
            single = equity_enrichment.enrich_selected_asset(
                selected.token_symbol, selected.contract_address,
            )
            equity_view = equity_view_model.build_equity_view(
                single, fallback_name=fallback_name,
            )

    return equity_view, rows


def _panels_context(snapshot, *, is_htmx_partial: bool = False) -> dict:
    return {
        "view": view_model.build_radar_view(snapshot),
        "is_htmx_partial": is_htmx_partial,
    }


def _error_panels(request, error: str) -> HTMLResponse:
    return _templates.TemplateResponse(
        request=request,
        name="radar/panels.html",
        context={"view": None, "error": error, "is_htmx_partial": False},
        status_code=200,
    )


@router.get("/radar", response_class=HTMLResponse)
async def radar_home(request: Request, snapshot_id: str = "",
                     asset_uid: str = ""):
    universe, universe_error = await run_in_threadpool(_fetch_universe_safe)

    # When a snapshot is requested its identity is authoritative for selection.
    # Never substitute AAPL when the snapshot identity resolves differently.
    selected = None
    view = None
    load_error = None
    snapshot_identity_note = None
    _snapshot_loaded = False

    if snapshot_id:
        try:
            snapshot = get_service().get_snapshot(snapshot_id)
            _snapshot_loaded = True
            view = view_model.build_radar_view(snapshot)
            snap_uid = _get_snapshot_uid(snapshot)
            if snap_uid:
                snap_selected = _resolve_selected(universe, snap_uid)
                if snap_selected is not None:
                    selected = snap_selected
                else:
                    snapshot_identity_note = (
                        f"SNAPSHOT_UID_NOT_IN_UNIVERSE: {snap_uid!r}")
            # B04: no asset_uid fallback when snapshot loaded — identity is
            # authoritative from the snapshot, not the query parameter.
        except RadarRuntimeError as exc:
            load_error = str(exc)

    # Only use asset_uid query param when no snapshot was successfully loaded.
    if selected is None and not _snapshot_loaded:
        selected = _resolve_selected(universe, asset_uid)

    # E2: load corporate fundamentals and featured board in one threadpool call.
    # Unified: one batch read for featured assets; selected reuses batch result
    # if featured, otherwise one additional single read.
    equity_view, featured_board = await run_in_threadpool(
        lambda: _load_equity_and_featured_board(
            universe,
            selected,
            selected.token_name if selected else "",
        )
    )

    from app.auth import resolve_request_session
    user = resolve_request_session(request)
    return _templates.TemplateResponse(
        request=request,
        name="radar/index.html",
        context={
            "universe": universe,
            "universe_error": universe_error,
            "selected": selected,
            "sizes": composition.SIZES,
            "directions": composition.DIRECTIONS,
            "view": view,
            "load_error": load_error,
            "snapshot_id": snapshot_id,
            "snapshot_identity_note": snapshot_identity_note,
            "user": user,
            "equity_view": equity_view,
            "featured_board": featured_board,
        },
    )


@router.post("/radar/refresh", response_class=HTMLResponse)
async def radar_refresh(request: Request, direction: str = Form("BUY"),
                        size: str = Form("100"),
                        asset_uid: str = Form("")):
    """ONE refresh = at most ONE acquisition = exactly ONE snapshot_id.

    asset_uid is MANDATORY.  Missing, unresolvable, or universe-unavailable
    states all fail closed with a stable reason and ZERO acquisition calls."""
    # C01: asset_uid is required; missing → ASSET_UID_REQUIRED, zero acquire.
    if not asset_uid:
        return _error_panels(request, "ASSET_UID_REQUIRED")

    # C01: universe must be available; failure → ASSET_UNIVERSE_UNAVAILABLE.
    universe, universe_error = await run_in_threadpool(_fetch_universe_safe)
    if universe_error:
        return _error_panels(request, "ASSET_UNIVERSE_UNAVAILABLE")

    # C01: unknown uid → ASSET_NOT_FOUND_IN_UNIVERSE, zero acquire.
    selected_asset = _resolve_selected(universe, asset_uid)
    if selected_asset is None:
        return _error_panels(request, "ASSET_NOT_FOUND_IN_UNIVERSE")

    try:
        request_obj = composition.build_request(
            direction, size, selected_asset)
    except RadarRuntimeError as exc:
        return _error_panels(request, f"INVALID_REQUEST: {exc}")

    is_htmx = request.headers.get("HX-Request", "").lower() == "true"

    # N03: the blocking acquisition is offloaded to Starlette's worker
    # threadpool so the ASGI event loop stays responsive.
    snapshot = await run_in_threadpool(get_service().acquire, request_obj)

    if is_htmx:
        # HTMX path: swap in the snapshot-bound panel fragment.
        # is_htmx_partial=True causes panels.html to emit the OOB header swap.
        return _templates.TemplateResponse(
            request=request,
            name="radar/panels.html",
            context=_panels_context(snapshot, is_htmx_partial=True),
        )

    # A1: progressive fallback — a normal HTML POST returns the full Radar
    # page.  Derive selected from the snapshot's authoritative identity so
    # the header and selector cannot show a stale asset.
    selected_from_snapshot = _selected_from_snapshot_identity(
        snapshot, universe)
    final_selected = selected_from_snapshot or selected_asset
    # E2: load fundamentals from the snapshot-authoritative selected identity.
    equity_view, featured_board = await run_in_threadpool(
        lambda: _load_equity_and_featured_board(
            universe,
            final_selected,
            final_selected.token_name if final_selected else "",
        )
    )
    from app.auth import resolve_request_session
    user = resolve_request_session(request)
    return _templates.TemplateResponse(
        request=request,
        name="radar/index.html",
        context={
            "universe": universe,
            "universe_error": universe_error,
            "selected": final_selected,
            "sizes": composition.SIZES,
            "directions": composition.DIRECTIONS,
            "view": view_model.build_radar_view(snapshot),
            "load_error": None,
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_identity_note": None,
            "user": user,
            "equity_view": equity_view,
            "featured_board": featured_board,
        },
    )


def _selected_from_snapshot_identity(snapshot, universe):
    """Derive the SelectedAsset for a non-JS full-page re-render from the
    snapshot's authoritative identity, ensuring no stale asset header."""
    snap_uid = _get_snapshot_uid(snapshot)
    if snap_uid:
        return _resolve_selected(universe, snap_uid)
    return None


@router.get("/radar/snapshot/{snapshot_id}", response_class=HTMLResponse)
async def radar_snapshot(request: Request, snapshot_id: str):
    """Network-free re-render of a persisted snapshot's panels."""
    try:
        snapshot = get_service().get_snapshot(snapshot_id)
    except RadarRuntimeError as exc:
        return _templates.TemplateResponse(
            request=request,
            name="radar/panels.html",
            context={"view": None, "error": f"SNAPSHOT_NOT_FOUND: {exc}",
                     "is_htmx_partial": False},
            status_code=200,
        )
    is_htmx = request.headers.get("HX-Request", "").lower() == "true"
    return _templates.TemplateResponse(
        request=request,
        name="radar/panels.html",
        context=_panels_context(snapshot, is_htmx_partial=is_htmx),
    )


@router.get("/radar/equity/{economic_asset_uid}", response_class=HTMLResponse)
async def radar_equity_terminal(request: Request, economic_asset_uid: str):
    """Company Terminal for one equity asset.  Network-free: zero quote
    acquisitions, zero LI.FI calls, zero GAP calculations.

    Path authority is economic_asset_uid (UID-first).  Unknown UID → 404 page.
    """
    universe, universe_error = await run_in_threadpool(_fetch_universe_safe)
    selected = _resolve_selected(universe, economic_asset_uid)
    if selected is None:
        return _templates.TemplateResponse(
            request=request,
            name="radar/equity_terminal.html",
            context={
                "terminal": {
                    "state": "NOT_FOUND",
                    "available": False,
                    "economic_asset_uid": economic_asset_uid,
                    "symbol": "",
                },
                "error": f"UID_NOT_FOUND: {economic_asset_uid!r}",
            },
            status_code=404,
        )

    from app.auth import resolve_request_session

    history_bundle = await run_in_threadpool(
        lambda: equity_terminal.get_history_for_terminal(selected.token_symbol)
    )
    terminal_view = equity_terminal.build_terminal_view(
        history_bundle,
        economic_asset_uid=economic_asset_uid,
        fallback_name=selected.token_name,
    )
    user = resolve_request_session(request)
    return _templates.TemplateResponse(
        request=request,
        name="radar/equity_terminal.html",
        context={
            "terminal": terminal_view,
            "selected": selected,
            "universe": universe,
            "universe_error": universe_error,
            "user": user,
            "error": None,
        },
    )


@router.get("/radar/inspector/{snapshot_id}/{field_id}",
            response_class=HTMLResponse)
async def radar_inspector(request: Request, snapshot_id: str,
                          field_id: str):
    """Evidence Inspector for one displayed field.  Reads the exact same
    persisted snapshot through the network-free P1 read path; an
    inspector click can never trigger acquisition."""
    try:
        snapshot = get_service().get_snapshot(snapshot_id)
    except RadarRuntimeError as exc:
        return _templates.TemplateResponse(
            request=request,
            name="radar/inspector.html",
            context={"inspector": None,
                     "error": f"SNAPSHOT_NOT_FOUND: {exc}",
                     "field_id": field_id},
            status_code=200,
        )
    inspector = view_model.build_inspector_view(snapshot, field_id)
    if inspector is None:
        return _templates.TemplateResponse(
            request=request,
            name="radar/inspector.html",
            context={"inspector": None,
                     "error": f"UNKNOWN_FIELD: {field_id}",
                     "field_id": field_id},
            status_code=200,
        )
    return _templates.TemplateResponse(
        request=request,
        name="radar/inspector.html",
        context={"inspector": inspector, "error": None,
                 "field_id": field_id},
    )
