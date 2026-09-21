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
RobinhoodAssetRegistryAdapter.  POST /radar/refresh accepts an asset_uid
form field; the server resolves the exact UID/chain/contract/decimals from
a fresh registry snapshot.  When asset_uid is absent, falls back to
asset_config() for backward compat.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.radar_runtime.contracts import RadarRuntimeError
from app.radar_ui import composition, view_model

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
    default for GET /radar with no selection).
    Returns None if the universe is empty."""
    if not universe:
        return None
    if uid:
        uid_lower = uid.lower()
        for a in universe:
            if a.economic_asset_uid.lower() == uid_lower:
                return a
        return None  # explicit uid not found — fail closed
    # Default: AAPL if present, else first
    for a in universe:
        if a.token_symbol == "AAPL":
            return a
    return universe[0]


def _panels_context(snapshot) -> dict:
    return {"view": view_model.build_radar_view(snapshot)}


@router.get("/radar", response_class=HTMLResponse)
async def radar_home(request: Request, snapshot_id: str = "",
                     asset_uid: str = ""):
    universe, universe_error = await run_in_threadpool(_fetch_universe_safe)
    selected = _resolve_selected(universe, asset_uid)
    view = None
    load_error = None
    if snapshot_id:
        try:
            snapshot = get_service().get_snapshot(snapshot_id)
            view = view_model.build_radar_view(snapshot)
        except RadarRuntimeError as exc:
            load_error = str(exc)
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
            "user": user,
        },
    )


@router.post("/radar/refresh", response_class=HTMLResponse)
async def radar_refresh(request: Request, direction: str = Form("BUY"),
                        size: str = Form("100"),
                        asset_uid: str = Form("")):
    """ONE refresh = at most ONE acquisition = exactly ONE snapshot_id.

    When asset_uid is provided, the server resolves the full asset identity
    from a fresh registry snapshot before building the request.  When
    asset_uid is absent, falls back to asset_config() (backward compat)."""
    selected_asset = None
    universe = []
    universe_error = None

    if asset_uid:
        universe, universe_error = await run_in_threadpool(_fetch_universe_safe)
        selected_asset = _resolve_selected(universe, asset_uid)
        if selected_asset is None:
            return _templates.TemplateResponse(
                request=request,
                name="radar/panels.html",
                context={"view": None,
                         "error": "ASSET_NOT_FOUND_IN_UNIVERSE"},
                status_code=200,
            )

    try:
        request_obj = composition.build_request(
            direction, size, selected_asset)
    except RadarRuntimeError as exc:
        return _templates.TemplateResponse(
            request=request,
            name="radar/panels.html",
            context={"view": None, "error": f"INVALID_REQUEST: {exc}"},
            status_code=200,
        )

    # N03: the blocking acquisition is offloaded to Starlette's worker
    # threadpool so the ASGI event loop stays responsive.
    snapshot = await run_in_threadpool(get_service().acquire, request_obj)

    if request.headers.get("HX-Request", "").lower() == "true":
        # HTMX path: swap in the snapshot-bound panel fragment.
        return _templates.TemplateResponse(
            request=request,
            name="radar/panels.html",
            context=_panels_context(snapshot),
        )

    # A1: progressive fallback — a normal HTML POST returns the full Radar
    # page.  Re-fetch universe so the page renders with correct selector state.
    if not asset_uid:
        universe, universe_error = await run_in_threadpool(_fetch_universe_safe)
    selected_from_snapshot = _selected_from_snapshot_identity(
        snapshot, universe)
    from app.auth import resolve_request_session
    user = resolve_request_session(request)
    return _templates.TemplateResponse(
        request=request,
        name="radar/index.html",
        context={
            "universe": universe,
            "universe_error": universe_error,
            "selected": selected_from_snapshot or selected_asset,
            "sizes": composition.SIZES,
            "directions": composition.DIRECTIONS,
            "view": view_model.build_radar_view(snapshot),
            "load_error": None,
            "snapshot_id": snapshot.snapshot_id,
            "user": None,
        },
    )


def _selected_from_snapshot_identity(snapshot, universe):
    """Derive the SelectedAsset for a non-JS full-page re-render from the
    snapshot's authoritative identity, ensuring no stale asset header."""
    try:
        payload = snapshot.to_payload()
        uid = payload.get("economicAssetUid")
        if uid:
            return _resolve_selected(universe, uid)
    except Exception:  # noqa: BLE001
        pass
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
            context={"view": None, "error": f"SNAPSHOT_NOT_FOUND: {exc}"},
            status_code=200,
        )
    context = _panels_context(snapshot)
    return _templates.TemplateResponse(
        request=request, name="radar/panels.html", context=context)


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
