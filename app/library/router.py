"""Project Library router.

Routes
------
GET  /library                          — full project library page
GET  /library/list                     — HTMX partial: paginated project list
POST /library/clone/{source_project_id} — create working copy, redirect to workbook

Project Library Open / Clone destination is flag-aware via the central
``project_workbook_url()`` helper (``app.utils.workbook_flag``).

Flag contract (absent → active):
  - Absent or empty → Workbook V2 active → /v2/workbook?project=<code>
  - Canonical falsy ("0", "false", "no", "off") → legacy → /?project=<code>

The same helper is used for:

* Project Library Open link (``GET /library`` and ``GET /library/list``)
* Working-copy clone redirect (``POST /library/clone/{id}``)
* HTMX ``HX-Redirect`` for the clone handler
* Non-HTMX 303 ``Location`` for the clone handler

V2 routers are always mounted; router-mount probing is no longer needed.
"""
from __future__ import annotations

import math
import os
import logging
import traceback as _traceback
from typing import Optional
from app.workbook.financing_csrf import issue_token as _issue_csrf_token
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.utils.workbook_flag import project_workbook_url, workbook_v2_active

router = APIRouter()

PAGE_SIZE = 20
logger = logging.getLogger("finco.library.clone")


@router.post("/library/projects/{code}/archive")
async def archive_project(request: Request, code: str):
    from app.services.project_lifecycle_service import handle_transition
    return await handle_transition(request, code, "ARCHIVE")


@router.post("/library/projects/{code}/unarchive")
async def unarchive_project(request: Request, code: str):
    from app.services.project_lifecycle_service import handle_transition
    return await handle_transition(request, code, "UNARCHIVE")


@router.get("/library/projects/{code}/lifecycle/status")
async def project_lifecycle_status(request: Request, code: str, request_id: str = ""):
    from app.services.project_lifecycle_service import handle_status
    return handle_status(request, code, request_id)

# ---------------------------------------------------------------------------
# Workbook destination helper
# ---------------------------------------------------------------------------


def workbook_v2_enabled() -> bool:
    """Return True iff Workbook V2 is currently active.

    Delegates to the canonical flag helper (absent → ACTIVE).
    Kept for backward-compatibility with template context keys.
    """
    return workbook_v2_active()


def workbook_destination(project_code: str) -> str:
    """Return the navigation target for opening a project from the Project Library.

    Delegates to the canonical flag-aware helper. V2 active (default when absent)
    → /v2/workbook?project=<code>; explicit falsy → /?project=<code>.
    """
    return project_workbook_url(project_code)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_current_user(request: Request):
    from app.auth import resolve_request_session
    return resolve_request_session(request)


def _templates():
    from main_web import templates
    return templates


def _reference_templates(search: str | None, role: str | None):
    from app.persistence.projects_repository import get_reference_projects
    if role in ("working_copy", "user_project"):
        return []
    term = (search or "").casefold().strip()
    order = {"generic_solar_reference": 0, "generic_wind_reference": 1, "generic_storage_reference": 2, "generic_data_center_reference": 3}
    return sorted(
        (record for record in get_reference_projects()
         if not term or term in record.project_name.casefold()),
        key=lambda record: order.get(record.template_source, 3),
    )


# ---------------------------------------------------------------------------
# GET /library — full page
# ---------------------------------------------------------------------------

def _model_home_payload(user_id: str, records, references) -> dict:
    """Presentation rows for Model Home from PERSISTED authorities only.

    Reads the per-project WorkspaceState Last Run evidence (Workflow 07)
    for the current page's projects and the reference models.  Pure reads:
    no engine execution, no recomputation.  A missing workspace record
    simply means no persisted evidence — never a fabricated value.

    Workspace OWNER authority (Correction A1): canonical reference
    projects persist their workspace rows under their own owner
    (``record.user_id`` — the canonical ``__reference__`` user), so their
    Last Run evidence is read under that owner.  The logged-in user's
    recent projects are read under the logged-in user.  No cross-user
    lookup ever happens for arbitrary projects: only records returned by
    the canonical reference repository use the reference owner.
    """
    from app.persistence.workspace_repository import get_workspace_state
    from app.library.model_home import (
        build_recent_project_rows,
        build_reference_cards,
    )

    states: dict[str, Any] = {}
    for record in records:  # user's recent projects — logged-in owner
        try:
            states[record.project_id] = get_workspace_state(
                user_id, record.project_id)
        except Exception:  # evidence read failure == no evidence
            states[record.project_id] = None
    for record in references:  # canonical references — their own owner
        try:
            states[record.project_id] = get_workspace_state(
                record.user_id, record.project_id)
        except Exception:  # evidence read failure == no evidence
            states[record.project_id] = None
    return {
        "recent_rows": build_recent_project_rows(records, states),
        "reference_cards": build_reference_cards(references, states),
    }


@router.get("/library", response_class=HTMLResponse)
async def project_library_page(
    request: Request,
    search: Optional[str] = None,
    role: Optional[str] = None,
    page: int = 1,
    project: Optional[str] = None,
    notice: Optional[str] = None,
):
    from app.v2.react_poc_router import block_htmx_presentation
    blocked = block_htmx_presentation(request)
    if blocked is not None:
        return blocked

    user = _get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    from app.v2.react_redirect import react_library_url, react_project_url
    dest = react_project_url(project) if (project or "").strip() else react_library_url(notice=notice, search=search)
    return RedirectResponse(url=dest, status_code=302)


# ---------------------------------------------------------------------------
# GET /library/list — decommissioned HTMX partial
# ---------------------------------------------------------------------------

@router.get("/library/list")
async def project_library_list(request: Request):
    return JSONResponse(
        {
            "ok": False,
            "code": "HTMX_DECOMMISSIONED",
            "message": "Legacy HTMX library list has been decommissioned; use /v2/model-react/library.",
        },
        status_code=410,
        headers={"Cache-Control": "no-store"},
    )


# ---------------------------------------------------------------------------
# POST /library/clone/{source_project_id} — create working copy
# ---------------------------------------------------------------------------

@router.post("/library/clone/{source_project_id}")
async def project_library_clone(
    request: Request,
    source_project_id: str,
    requested_name: Optional[str] = Form(default=None),
    csrf_token: str = Form(default=""),
):
    user = _get_current_user(request)
    if not user:
        return JSONResponse({"error": "Login required"}, status_code=401)

    from app.auth import validate_csrf_token
    from app.workbook.financing_csrf import extract_bound_token
    if not validate_csrf_token(extract_bound_token(
            request, "", csrf_token, purpose="library-clone-v1")):
        return JSONResponse({"error": "Invalid or missing CSRF token"}, status_code=403)

    # A valid CSRF token is not authority to clone another user's project.
    # Unknown and noncanonical sources share the same non-disclosing response.
    from app.persistence.projects_repository import get_canonical_reference_by_id
    if get_canonical_reference_by_id(source_project_id) is None:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    from app.services.project_library_service import (
        ProtectedProjectError,
        UnsupportedProjectRuntimeError,
    )
    from app.services.reference_seed_service import (
        create_seeded_working_copy as create_working_copy,
    )

    try:
        new_project = create_working_copy(
            user_id=user.user_id,
            source_reference_id=source_project_id,
            requested_name=requested_name or None,
        )
    except UnsupportedProjectRuntimeError as exc:
        msg = f"{exc.project_type} working-copy runtime is not yet available. The reference model is still accessible for viewing."
        if request.headers.get("HX-Request") == "true":
            return HTMLResponse(f'<p role="alert">{msg}</p>', status_code=400)
        return JSONResponse({"error": msg}, status_code=400)
    except (ValueError, ProtectedProjectError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        request_id = request.scope.get("request_id", "unknown")
        _tb = exc.__traceback__
        if _tb is not None:
            while _tb.tb_next is not None:
                _tb = _tb.tb_next
            _tb_module = os.path.basename(_tb.tb_frame.f_code.co_filename).replace("\n", "_").replace("\r", "_")
            _tb_function = _tb.tb_frame.f_code.co_name.replace("\n", "_").replace("\r", "_")
            _tb_lineno = _tb.tb_lineno
        else:
            _tb_module = _tb_function = "unknown"
            _tb_lineno = 0
        logger.error(
            "clone_failed request_id=%s route=project_library_clone source_project_id=%s "
            "session_type=%s exception_type=%s module=%s function=%s lineno=%d",
            request_id, source_project_id.replace("\n", "_").replace("\r", "_")[:128],
            type(user).__name__, type(exc).__name__,
            _tb_module, _tb_function, _tb_lineno,
        )
        message = ("Could not create a working copy. Please try again or contact support "
                   f"with reference {request_id}.")
        if request.headers.get("HX-Request") == "true":
            return HTMLResponse(f'<p role="alert">{message}</p>', status_code=500)
        return HTMLResponse(
            f'<!doctype html><html><title>Working copy unavailable</title><body><h1>Working copy unavailable</h1><p>{message}</p><a href="/library">Back to Model Workspace</a></body></html>',
            status_code=500,
        )

    dest = workbook_destination(new_project.project_code)
    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        from fastapi.responses import Response
        resp = Response(status_code=204)
        resp.headers["HX-Redirect"] = dest
        return resp
    return RedirectResponse(url=dest, status_code=303)
