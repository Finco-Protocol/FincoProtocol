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
from typing import Optional
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.utils.workbook_flag import project_workbook_url, workbook_v2_active

router = APIRouter()

PAGE_SIZE = 20

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
    from main_web import get_current_user
    return get_current_user(request)


def _templates():
    from main_web import templates
    return templates


# ---------------------------------------------------------------------------
# GET /library — full page
# ---------------------------------------------------------------------------

@router.get("/library", response_class=HTMLResponse)
async def project_library_page(
    request: Request,
    search: Optional[str] = None,
    role: Optional[str] = None,
    page: int = 1,
    project: Optional[str] = None,
):
    user = _get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    from app.persistence.projects_repository import (
        list_projects_paged,
        get_reference_projects,
    )
    from app.services.project_library_service import ensure_reference_models

    ensure_reference_models()

    page = max(1, page)
    records, total = list_projects_paged(
        user_id=user.user_id,
        page=page,
        page_size=PAGE_SIZE,
        search=search or None,
        role_filter=role or None,
    )
    total_pages = max(1, math.ceil(total / PAGE_SIZE))

    ctx = {
        "user": user,
        "projects": records,
        "search": search or "",
        "role_filter": role or "",
        "page": page,
        "page_size": PAGE_SIZE,
        "total": total,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "selected_project": project or "",
        # sidebar context — no active project on the library page
        "project_record": None,
        "project_ctx": None,
        "workspace_state": None,
        "runtime_summary": None,
        "user_project_records": [],
        "factory_template_projects": [],
        "active_project_code": None,
        "workbook_destination_fn": workbook_destination,
        "workbook_v2_enabled_flag": workbook_v2_enabled(),
    }
    return _templates().TemplateResponse(request=request, name="library/project_library.html", context=ctx)


# ---------------------------------------------------------------------------
# GET /library/list — HTMX partial (paginated list only)
# ---------------------------------------------------------------------------

@router.get("/library/list", response_class=HTMLResponse)
async def project_library_list(
    request: Request,
    search: Optional[str] = None,
    role: Optional[str] = None,
    page: int = 1,
    project: Optional[str] = None,
):
    user = _get_current_user(request)
    if not user:
        return JSONResponse({"error": "Login required"}, status_code=401)

    from app.persistence.projects_repository import list_projects_paged

    page = max(1, page)
    records, total = list_projects_paged(
        user_id=user.user_id,
        page=page,
        page_size=PAGE_SIZE,
        search=search or None,
        role_filter=role or None,
    )
    total_pages = max(1, math.ceil(total / PAGE_SIZE))

    ctx = {
        "user": user,
        "projects": records,
        "search": search or "",
        "role_filter": role or "",
        "page": page,
        "page_size": PAGE_SIZE,
        "total": total,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "selected_project": project or "",
        "workbook_destination_fn": workbook_destination,
        "workbook_v2_enabled_flag": workbook_v2_enabled(),
    }
    return _templates().TemplateResponse(request=request, name="library/project_library_list.html", context=ctx)


# ---------------------------------------------------------------------------
# POST /library/clone/{source_project_id} — create working copy
# ---------------------------------------------------------------------------

@router.post("/library/clone/{source_project_id}")
async def project_library_clone(
    request: Request,
    source_project_id: str,
    requested_name: Optional[str] = Form(default=None),
):
    user = _get_current_user(request)
    if not user:
        return JSONResponse({"error": "Login required"}, status_code=401)

    from app.services.project_library_service import (
        create_working_copy,
        ProtectedProjectError,
    )

    try:
        new_project = create_working_copy(
            user_id=user.user_id,
            source_reference_id=source_project_id,
            requested_name=requested_name or None,
        )
    except (ValueError, ProtectedProjectError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    dest = workbook_destination(new_project.project_code)
    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        from fastapi.responses import Response
        resp = Response(status_code=204)
        resp.headers["HX-Redirect"] = dest
        return resp
    return RedirectResponse(url=dest, status_code=303)
