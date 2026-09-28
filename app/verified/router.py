"""FINCO Verified Assets V1 — route handlers.

Routes:
  GET /verified                     — collection page (HTML)
  GET /verified/{asset_id}          — individual asset page (HTML)
  GET /verified/{asset_id}.json     — machine-readable asset record (JSON)

All routes require authentication. Unauthenticated requests are
redirected to /login (HTML) or return 401 (JSON).

Read-only. No financial-engine code is called here.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

logger = logging.getLogger(__name__)
router = APIRouter()

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from fastapi.templating import Jinja2Templates
_templates = Jinja2Templates(directory=os.path.join(_APP_DIR, "templates"))


def _load_verified_asset(asset_id: str) -> dict:
    """Resolve reference project, load workspace, build composed record. Sync."""
    from app.verified.asset_registry import get_asset_definition
    from app.persistence.projects_repository import (
        REFERENCE_USER_ID,
        get_reference_by_template_source,
    )
    from app.persistence.workspace_repository import get_workspace_state
    from app.verified.composer import build_verified_asset
    from app.verified.contracts import (
        VERIFIED_ASSET_SCHEMA,
        VerifiedAssetStatus,
        STATUS_DISPLAY,
    )

    asset_def = get_asset_definition(asset_id)
    if asset_def is None:
        return {"found": False}

    project_record = get_reference_by_template_source(asset_def.template_source)
    if project_record is None:
        return {
            "found": True,
            "asset_id": asset_id,
            "record": {
                "schema": VERIFIED_ASSET_SCHEMA,
                "asset_id": asset_id,
                "display_name": asset_def.display_name,
                "asset_type": asset_def.asset_type,
                "description": asset_def.description,
                "status": VerifiedAssetStatus.UNAVAILABLE,
                "status_display": STATUS_DISPLAY[VerifiedAssetStatus.UNAVAILABLE],
                "model": None,
                "verify": None,
                "market": None,
                "protocol": None,
                "error": {
                    "code": "REFERENCE_PROJECT_NOT_SEEDED",
                    "reason": "Reference project not yet seeded. System initialising.",
                },
            },
        }

    ws = get_workspace_state(REFERENCE_USER_ID, project_record.project_id)
    if ws is None:
        from app.verified.contracts import VERIFIED_ASSET_SCHEMA, VerifiedAssetStatus, STATUS_DISPLAY
        return {
            "found": True,
            "asset_id": asset_id,
            "record": {
                "schema": VERIFIED_ASSET_SCHEMA,
                "asset_id": asset_id,
                "display_name": asset_def.display_name,
                "asset_type": asset_def.asset_type,
                "description": asset_def.description,
                "status": VerifiedAssetStatus.UNAVAILABLE,
                "status_display": STATUS_DISPLAY[VerifiedAssetStatus.UNAVAILABLE],
                "model": None,
                "verify": None,
                "market": None,
                "protocol": None,
                "error": {
                    "code": "WORKSPACE_NOT_FOUND",
                    "reason": "Workspace state not found for reference project.",
                },
            },
        }

    record = build_verified_asset(asset_def, project_record, ws)
    return {"found": True, "asset_id": asset_id, "record": record}


def _load_all_verified_assets() -> list[dict]:
    """Load all V1 asset records. Sync."""
    from app.verified.asset_registry import list_asset_definitions
    results = []
    for asset_def in list_asset_definitions():
        result = _load_verified_asset(asset_def.asset_id)
        if result["found"]:
            results.append(result["record"])
    return results


@router.get("/verified", response_class=HTMLResponse)
async def verified_index(request: Request):
    """FINCO Verified Assets — collection page."""
    from app.auth import resolve_request_session

    user = resolve_request_session(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    assets = await run_in_threadpool(_load_all_verified_assets)

    return _templates.TemplateResponse(
        request=request,
        name="verified/index.html",
        context={
            "user": user,
            "assets": assets,
            "proto_active_page": "verified",
        },
    )


@router.get("/verified/{asset_id}.json")
async def verified_asset_json(asset_id: str, request: Request):
    """FINCO Verified Asset — machine-readable JSON."""
    from app.auth import resolve_request_session

    user = resolve_request_session(request)
    if not user:
        return JSONResponse({"error": "authentication_required"}, status_code=401)

    result = await run_in_threadpool(_load_verified_asset, asset_id)
    if not result["found"]:
        return JSONResponse({"error": "not_found"}, status_code=404)

    record = result["record"]
    from app.verified.entitlement import entitlement_public_view, resolve_verified_entitlement
    # Serialise VerifiedAssetStatus enum to string value.
    output = dict(record)
    output.pop("certificate", None)  # full artifact belongs to the dossier capability
    output["entitlement"] = entitlement_public_view(resolve_verified_entitlement(user))
    if hasattr(output.get("status"), "value"):
        output["status"] = output["status"].value
    if isinstance(output.get("status_display"), dict):
        pass  # already plain dict

    return JSONResponse(output)


@router.get("/verified/{asset_id}/dossier.json")
async def verified_asset_dossier(asset_id: str, request: Request):
    """Full run/evidence dossier; access does not affect verification truth."""
    from app.auth import resolve_request_session
    from app.verified.entitlement import (
        EntitlementState, entitlement_public_view, resolve_verified_entitlement,
    )

    user = resolve_request_session(request)
    if user is None:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    entitlement = resolve_verified_entitlement(user)
    if entitlement.state is not EntitlementState.ACTIVE:
        return JSONResponse({"error": "entitlement_required"}, status_code=403)
    result = await run_in_threadpool(_load_verified_asset, asset_id)
    if not result["found"]:
        return JSONResponse({"error": "not_found"}, status_code=404)
    record = dict(result["record"])
    if hasattr(record.get("status"), "value"):
        record["status"] = record["status"].value
    record["entitlement"] = entitlement_public_view(entitlement)
    return JSONResponse(record)


@router.get("/verified/{asset_id}", response_class=HTMLResponse)
async def verified_asset_detail(asset_id: str, request: Request):
    """FINCO Verified Asset — detail page."""
    from app.auth import resolve_request_session

    user = resolve_request_session(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    result = await run_in_threadpool(_load_verified_asset, asset_id)
    from app.verified.entitlement import entitlement_public_view, resolve_verified_entitlement
    entitlement = entitlement_public_view(resolve_verified_entitlement(user))

    if not result["found"]:
        return _templates.TemplateResponse(
            request=request,
            name="verified/asset.html",
            context={
                "user": user,
                "asset_id": asset_id,
                "record": None,
                "error": {"code": "NOT_FOUND", "reason": "Asset not found."},
                "proto_active_page": "verified",
                "entitlement": entitlement,
            },
            status_code=404,
        )

    return _templates.TemplateResponse(
        request=request,
        name="verified/asset.html",
        context={
            "user": user,
            "asset_id": asset_id,
            "record": result["record"],
            "error": result["record"].get("error"),
            "proto_active_page": "verified",
            "entitlement": entitlement,
        },
    )
