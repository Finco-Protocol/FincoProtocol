"""Radar v1 UI router (P2/P6/P7/P9).

Browser-reachable surface.  Routes NEVER call providers directly and
NEVER import private live_proof helpers:

- ``GET  /radar``                                 page shell (no acquisition)
- ``POST /radar/refresh``                         ONE acquire -> ONE snapshot_id
- ``GET  /radar/snapshot/{snapshot_id}``          re-render panels (network-free)
- ``GET  /radar/inspector/{snapshot_id}/{field}`` Evidence Inspector (network-free)

Every detail endpoint takes the exact ``snapshot_id`` and reads through
the P1 ``AcquisitionService.get_snapshot`` network-free path.  No HTMX
partial can trigger acquisition.
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

_service_instance = None


def get_service():
    """Lazily build the canonical P1 acquisition service (composition
    root owns wiring)."""
    global _service_instance
    if _service_instance is None:
        _service_instance = composition.build_service()
    return _service_instance


def set_service(service) -> None:
    """Test/diagnostic seam: inject a service with offline fake
    providers.  Never used by production routes themselves."""
    global _service_instance
    _service_instance = service


def _panels_context(snapshot) -> dict:
    return {"view": view_model.build_radar_view(snapshot)}


@router.get("/radar", response_class=HTMLResponse)
async def radar_home(request: Request, snapshot_id: str = ""):
    view = None
    load_error = None
    if snapshot_id:
        try:
            snapshot = get_service().get_snapshot(snapshot_id)
            view = view_model.build_radar_view(snapshot)
        except RadarRuntimeError as exc:
            load_error = str(exc)
    return _templates.TemplateResponse(
        request=request,
        name="radar/index.html",
        context={
            "asset": composition.asset_config(),
            "sizes": composition.SIZES,
            "directions": composition.DIRECTIONS,
            "view": view,
            "load_error": load_error,
            "snapshot_id": snapshot_id,
        },
    )


@router.post("/radar/refresh", response_class=HTMLResponse)
async def radar_refresh(request: Request, direction: str = Form("BUY"),
                        size: str = Form("100")):
    """ONE refresh = at most ONE acquisition = exactly ONE snapshot_id.
    The returned fragment (and every panel inside it) is bound to that
    single snapshot."""
    try:
        request_obj = composition.build_request(direction, size)
    except RadarRuntimeError as exc:
        return _templates.TemplateResponse(
            request=request,
            name="radar/panels.html",
            context={"view": None, "error": f"INVALID_REQUEST: {exc}"},
            status_code=200,
        )
    # N03: the blocking acquisition is offloaded to Starlette's worker
    # threadpool so the ASGI event loop stays responsive (a lightweight
    # heartbeat route completes while the provider call runs).
    snapshot = await run_in_threadpool(get_service().acquire, request_obj)
    if request.headers.get("HX-Request", "").lower() == "true":
        # HTMX path: swap in the snapshot-bound panel fragment.
        return _templates.TemplateResponse(
            request=request,
            name="radar/panels.html",
            context=_panels_context(snapshot),
        )
    # A1: progressive fallback — a normal HTML POST returns the full
    # Radar page for the resulting snapshot; correctness never depends
    # on JavaScript.
    return _templates.TemplateResponse(
        request=request,
        name="radar/index.html",
        context={
            "asset": composition.asset_config(),
            "sizes": composition.SIZES,
            "directions": composition.DIRECTIONS,
            "view": view_model.build_radar_view(snapshot),
            "load_error": None,
            "snapshot_id": snapshot.snapshot_id,
        },
    )


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
