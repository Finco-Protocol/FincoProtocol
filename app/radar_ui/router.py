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
from app.radar_ui import composition, equity_enrichment, equity_view_model, view_model

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


def _load_equity_view(selected, fallback_name: str = "") -> dict:
    """Synchronous helper: E1 enrichment + view model for one selected asset.

    Called via run_in_threadpool from async routes; never called on its own
    from HTMX refresh paths (corporate fundamentals live outside #radar-panels).
    Returns an empty dict when selected is None so templates receive equity_view={}
    and the include guard ``{% if equity_view %}`` suppresses the section.
    """
    if selected is None:
        return {}
    result = equity_enrichment.enrich_selected_asset(
        selected.token_symbol,
        selected.contract_address,
    )
    return equity_view_model.build_equity_view(result, fallback_name=fallback_name)


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

    # E2: load corporate fundamentals for the selected asset.
    # Runs in the threadpool (SQLite is blocking); equity_view is {} when
    # selected is None so the template include-guard suppresses the section.
    equity_view = await run_in_threadpool(
        _load_equity_view, selected,
        selected.token_name if selected else "",
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
    equity_view = await run_in_threadpool(
        _load_equity_view, final_selected,
        final_selected.token_name if final_selected else "",
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
