"""FINCO Verify — Run Certificate routes.

GET /verify/run/{project_code}       — HTML browser surface
GET /verify/run/{project_code}.json  — machine-readable certificate

Both routes enforce project ownership via resolve_accessible_project:
  - User A cannot access User B's certificate by changing the URL.
  - Canonical reference projects are accessible to all authenticated users
    (same semantics as the existing workbook read routes).

Routes are read-only. No financial-engine code is called here.
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


def _get_certificate_result(project_code: str, user_id: str):
    """Resolve project, load workspace, build certificate. Pure sync helper."""
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.verify.run_certificate import (
        RunCertificateUnavailableError,
        build_run_certificate,
    )

    project_record, workspace_owner = resolve_accessible_project(user_id, project_code)
    if project_record is None:
        return None, None, None  # 404

    ws = get_workspace_state(workspace_owner, project_record.project_id)
    if ws is None:
        return None, None, None  # 404

    try:
        certificate = build_run_certificate(ws, project_record)
        return project_record, certificate, None
    except RunCertificateUnavailableError as exc:
        return project_record, None, {"code": exc.code, "reason": exc.reason}
    except Exception:
        logger.exception("Run certificate build failed for %s", project_code)
        return project_record, None, {
            "code": "INTERNAL_ERROR",
            "reason": "Certificate temporarily unavailable.",
        }


@router.get("/verify/run/{project_code}", response_class=HTMLResponse)
async def run_certificate_html(project_code: str, request: Request):
    """FINCO Run Certificate — HTML surface."""
    from app.auth import resolve_request_session

    user = resolve_request_session(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    project_record, certificate, error = await run_in_threadpool(
        _get_certificate_result, project_code, user.user_id
    )

    if project_record is None:
        return _templates.TemplateResponse(
            request=request,
            name="verify/run_certificate.html",
            context={
                "user": user,
                "project_code": project_code,
                "certificate": None,
                "error": {"code": "NOT_FOUND", "reason": "Project not found."},
            },
            status_code=404,
        )

    return _templates.TemplateResponse(
        request=request,
        name="verify/run_certificate.html",
        context={
            "user": user,
            "project_code": project_code,
            "project_name": getattr(project_record, "project_name", project_code),
            "certificate": certificate,
            "error": error,
        },
    )


@router.get("/verify/run/{project_code}.json")
async def run_certificate_json(project_code: str, request: Request):
    """FINCO Run Certificate — machine-readable JSON."""
    from app.auth import resolve_request_session

    user = resolve_request_session(request)
    if not user:
        return JSONResponse({"error": "authentication_required"}, status_code=401)

    project_record, certificate, error = await run_in_threadpool(
        _get_certificate_result, project_code, user.user_id
    )

    if project_record is None:
        return JSONResponse({"error": "not_found"}, status_code=404)

    if error:
        return JSONResponse(
            {
                "schema": "FINCO_RUN_CERTIFICATE_V1",
                "available": False,
                "error": error,
            },
            status_code=200,
        )

    return JSONResponse(certificate)
