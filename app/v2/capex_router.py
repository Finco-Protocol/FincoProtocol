"""
app.v2.capex_router — CAPEX custom-row command endpoints.

Mounted at /v2/capex by main_web.py (under the same FINCO_WORKBOOK_V2 flag
as the main V2 router).

Endpoints
---------
POST /v2/capex/line/add
POST /v2/capex/line/update
POST /v2/capex/line/deactivate
POST /v2/capex/line/reorder

All endpoints
  - Require authentication (finco_session cookie).
  - Accept content_hash (current composite workbook identity token).
  - Validate composite workbook identity before any mutation (CAS).
  - Re-render the CAPEX sheet partial with the NEW composite hash after success.
  - Return 409 JSON for protected-reference, stale identity/version, or
    concurrent edit; 404 for unknown project/workspace; 422 for validation errors.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.utils.workbook_flag import require_v2_active

from app.auth import COOKIE_NAME, decode_session_token
from app.v2.capex_commands import (
    CapexCommandError,
    CapexConcurrentEditError,
    CapexProtectedGroupError,
    CapexProtectedReferenceError,
    CapexRowNotFoundError,
    CapexStaleIdentityError,
    CapexVersionMismatchError,
    add_capex_line,
    deactivate_capex_line,
    reorder_capex_lines,
    update_capex_line,
)

capex_router = APIRouter()


def _get_current_user(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return decode_session_token(token)


def _render_capex_sheet(
    request: Request, project_record, pis, ws, project: str, field_error: str = "",
    workspace_owner: str = "",
) -> HTMLResponse:
    """Delegate to the main V2 router's CAPEX partial renderer."""
    from app.v2.router import _render_capex_htmx_sheet
    return _render_capex_htmx_sheet(
        request, pis, ws, project_record, project,
        field_error=field_error, workspace_owner=workspace_owner,
    )


def _load_project_and_ws(user, project: str):
    """Return (project_record, ws) or raise LookupError."""
    from app.persistence.projects_repository import get_project_record
    from app.persistence.workspace_repository import get_workspace_state

    project_record = get_project_record(user_id=user.user_id, project_code=project)
    if project_record is None:
        raise LookupError(f"Project {project!r} not found.")
    ws = get_workspace_state(user_id=user.user_id, project_id=project_record.project_id)
    if ws is None:
        raise LookupError("Workspace not found.")
    return project_record, ws


def _build_pis_with_hash(ws, project_record, user, new_composite_hash: str):
    """Build PIS carrying the given composite hash."""
    from app.workbook.service import WorkbookService
    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    return pis.with_composite_hash(new_composite_hash)


def _stale_identity_response(
    request, project_record, user, project, ws, is_htmx: bool
) -> HTMLResponse | JSONResponse:
    """Return a stale-content response: refreshed sheet with error message (HTMX)
    or 409 JSON (non-HTMX).
    """
    if is_htmx:
        from app.workbook.workbook_identity import assemble_consistent_for_get
        from app.workbook.service import WorkbookService
        try:
            fresh_identity = assemble_consistent_for_get(
                user_id=user.user_id,
                project_id=project_record.project_id,
                workbook_version=WorkbookService.build_draft_input_set_from_workspace(ws).workbook_version,
            )
            pis = WorkbookService.build_draft_input_set_from_workspace(ws).with_composite_hash(
                fresh_identity.composite_hash
            )
        except Exception:
            pis = WorkbookService.build_draft_input_set_from_workspace(ws)
        return _render_capex_sheet(
            request, project_record, pis, ws, project,
            field_error="Workbook changed since page loaded — values refreshed. Please try again.",
        )
    return JSONResponse(
        {"error": "Workbook changed since page loaded. Reload and try again."},
        status_code=409,
    )


def _render_capex_sheet_with_oob(
    request: Request, project_record, pis, ws, project: str,
    field_error: str = "", workspace_owner: str = "",
) -> HTMLResponse:
    """Render CAPEX sheet + full post-Save stale-state refresh (R6/F07
    Correction A: toolbar, stale Overview, runtime bars, scenario statuses)
    + run controls OOB on success."""
    resp = _render_capex_sheet(request, project_record, pis, ws, project, field_error=field_error)
    if field_error:
        return resp
    from app.workbook.runtime_projection import build_runtime_projection_bundle
    from app.v2.runtime_projection_views import build_all_runtime_bar_oob
    from app.workbook.service import WorkbookService
    from fastapi.templating import Jinja2Templates
    import os
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _tmpl = Jinja2Templates(directory=os.path.join(_BASE_DIR, "app", "templates", "v2"))
    rr = WorkbookService.get_runtime_result(ws)
    projection = build_runtime_projection_bundle(rr, ws.dirty)
    oob = build_all_runtime_bar_oob(projection)
    # R6 Correction A: the CAPEX save made the workspace dirty — the prior
    # runtime evidence must be visibly classified stale in the SAME response.
    from app.v2.post_run_ui import build_post_save_ui_state

    oob += chr(10) + build_post_save_ui_state(
        ws_fresh=ws, project_record=project_record, project=project,
        workspace_owner=workspace_owner, include_runtime_bars=False,
        projection=projection,
    )
    run_controls_html = _tmpl.get_template("partials/_v2_run_controls.html").render({
        "project_code": project,
        "workbook_version": pis.workbook_version,
        "content_hash": pis.content_hash,
    })
    run_controls_oob = '<div id="v2-run-controls" hx-swap-oob="true">' + run_controls_html + "</div>"
    return HTMLResponse(content=resp.body.decode() + "\n" + oob + "\n" + run_controls_oob)


def _handle_command_error(exc: CapexCommandError) -> JSONResponse:
    if isinstance(exc, CapexProtectedReferenceError):
        return JSONResponse({"error": str(exc)}, status_code=409)
    if isinstance(exc, CapexVersionMismatchError):
        return JSONResponse({"error": str(exc), "reload": True}, status_code=409)
    if isinstance(exc, CapexStaleIdentityError):
        return JSONResponse({"error": str(exc)}, status_code=409)
    if isinstance(exc, CapexConcurrentEditError):
        return JSONResponse({"error": str(exc)}, status_code=409)
    if isinstance(exc, CapexProtectedGroupError):
        return JSONResponse({"error": str(exc)}, status_code=422)
    if isinstance(exc, CapexRowNotFoundError):
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse({"error": str(exc)}, status_code=422)


@capex_router.post("/line/add")
async def capex_line_add(
    request: Request,
    project: str = Form(...),
    parent_category_code: str = Form(...),
    label: str = Form(...),
    amount_keur: float = Form(default=0.0),
    notes: str = Form(default=""),
    workbook_version: str = Form(...),
    content_hash: str = Form(...),
    _: None = Depends(require_v2_active),
):
    """Add a custom CAPEX row to an eligible group."""
    user = _get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    try:
        project_record, ws = _load_project_and_ws(user, project)
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

    is_htmx = request.headers.get("HX-Request") == "true"

    try:
        _, new_hash = add_capex_line(
            project_record=project_record,
            user_id=user.user_id,
            label=label.strip(),
            parent_category_code=parent_category_code,
            amount_keur=amount_keur,
            notes=notes,
            workbook_version=workbook_version,
            expected_content_hash=content_hash,
        )
    except CapexStaleIdentityError:
        return _stale_identity_response(request, project_record, user, project, ws, is_htmx)
    except CapexCommandError as exc:
        if is_htmx:
            from app.workbook.service import WorkbookService
            pis = WorkbookService.build_draft_input_set_from_workspace(ws).with_composite_hash(content_hash)
            return _render_capex_sheet(request, project_record, pis, ws, project, field_error=str(exc))
        return _handle_command_error(exc)
    except ValueError as exc:
        if is_htmx:
            from app.workbook.service import WorkbookService
            pis = WorkbookService.build_draft_input_set_from_workspace(ws).with_composite_hash(content_hash)
            return _render_capex_sheet(request, project_record, pis, ws, project, field_error=str(exc))
        return JSONResponse({"error": str(exc)}, status_code=422)

    from app.persistence.workspace_repository import get_workspace_state
    ws = get_workspace_state(user_id=user.user_id, project_id=project_record.project_id) or ws
    if is_htmx:
        pis = _build_pis_with_hash(ws, project_record, user, new_hash)
        return _render_capex_sheet_with_oob(request, project_record, pis, ws, project, workspace_owner=user.user_id)
    return RedirectResponse(url=f"/v2/workbook?project={project}", status_code=303)


@capex_router.post("/line/update")
async def capex_line_update(
    request: Request,
    project: str = Form(...),
    sub_line_id: str = Form(...),
    label: str = Form(...),
    amount_keur: float = Form(default=0.0),
    notes: str = Form(default=""),
    row_version: str = Form(...),
    workbook_version: str = Form(...),
    content_hash: str = Form(...),
    _: None = Depends(require_v2_active),
):
    """Update an existing custom CAPEX row (optimistic-lock on row_version)."""
    user = _get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    try:
        project_record, ws = _load_project_and_ws(user, project)
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

    is_htmx = request.headers.get("HX-Request") == "true"

    try:
        _, new_hash = update_capex_line(
            project_record=project_record,
            user_id=user.user_id,
            sub_line_id=sub_line_id,
            label=label.strip(),
            amount_keur=amount_keur,
            notes=notes,
            row_version=row_version,
            workbook_version=workbook_version,
            expected_content_hash=content_hash,
        )
    except CapexStaleIdentityError:
        return _stale_identity_response(request, project_record, user, project, ws, is_htmx)
    except CapexCommandError as exc:
        if is_htmx:
            err = str(exc)
            if isinstance(exc, CapexConcurrentEditError):
                err = "Row was modified concurrently — values refreshed. Try again."
            from app.workbook.service import WorkbookService
            pis = WorkbookService.build_draft_input_set_from_workspace(ws).with_composite_hash(content_hash)
            return _render_capex_sheet(request, project_record, pis, ws, project, field_error=err)
        return _handle_command_error(exc)
    except ValueError as exc:
        if is_htmx:
            from app.workbook.service import WorkbookService
            pis = WorkbookService.build_draft_input_set_from_workspace(ws).with_composite_hash(content_hash)
            return _render_capex_sheet(request, project_record, pis, ws, project, field_error=str(exc))
        return JSONResponse({"error": str(exc)}, status_code=422)

    from app.persistence.workspace_repository import get_workspace_state
    ws = get_workspace_state(user_id=user.user_id, project_id=project_record.project_id) or ws
    if is_htmx:
        pis = _build_pis_with_hash(ws, project_record, user, new_hash)
        return _render_capex_sheet_with_oob(request, project_record, pis, ws, project, workspace_owner=user.user_id)
    return RedirectResponse(url=f"/v2/workbook?project={project}", status_code=303)


@capex_router.post("/line/deactivate")
async def capex_line_deactivate(
    request: Request,
    project: str = Form(...),
    sub_line_id: str = Form(...),
    row_version: str = Form(...),
    workbook_version: str = Form(...),
    content_hash: str = Form(...),
    _: None = Depends(require_v2_active),
):
    """Deactivate (soft-delete) a custom CAPEX row."""
    user = _get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    try:
        project_record, ws = _load_project_and_ws(user, project)
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

    is_htmx = request.headers.get("HX-Request") == "true"

    try:
        _, new_hash = deactivate_capex_line(
            project_record=project_record,
            user_id=user.user_id,
            sub_line_id=sub_line_id,
            row_version=row_version,
            workbook_version=workbook_version,
            expected_content_hash=content_hash,
        )
    except CapexStaleIdentityError:
        return _stale_identity_response(request, project_record, user, project, ws, is_htmx)
    except CapexCommandError as exc:
        if is_htmx:
            err = str(exc)
            if isinstance(exc, CapexConcurrentEditError):
                err = "Row was modified concurrently — values refreshed. Try again."
            from app.workbook.service import WorkbookService
            pis = WorkbookService.build_draft_input_set_from_workspace(ws).with_composite_hash(content_hash)
            return _render_capex_sheet(request, project_record, pis, ws, project, field_error=err)
        return _handle_command_error(exc)

    from app.persistence.workspace_repository import get_workspace_state
    ws = get_workspace_state(user_id=user.user_id, project_id=project_record.project_id) or ws
    if is_htmx:
        pis = _build_pis_with_hash(ws, project_record, user, new_hash)
        return _render_capex_sheet_with_oob(request, project_record, pis, ws, project, workspace_owner=user.user_id)
    return RedirectResponse(url=f"/v2/workbook?project={project}", status_code=303)


@capex_router.post("/line/reorder")
async def capex_line_reorder(
    request: Request,
    project: str = Form(...),
    parent_category_code: str = Form(...),
    sub_line_id: List[str] = Form(default=[]),
    row_version: List[str] = Form(default=[]),
    workbook_version: str = Form(...),
    content_hash: str = Form(...),
    _: None = Depends(require_v2_active),
):
    """Atomically reorder all custom rows within a CAPEX group."""
    user = _get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    try:
        project_record, ws = _load_project_and_ws(user, project)
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

    is_htmx = request.headers.get("HX-Request") == "true"

    if len(sub_line_id) != len(row_version):
        err = "sub_line_id and row_version lists must have equal length."
        if is_htmx:
            from app.workbook.service import WorkbookService
            pis = WorkbookService.build_draft_input_set_from_workspace(ws).with_composite_hash(content_hash)
            return _render_capex_sheet(request, project_record, pis, ws, project, field_error=err)
        return JSONResponse({"error": err}, status_code=422)

    ordered_rows = [
        {"sub_line_id": sid, "row_version": rv}
        for sid, rv in zip(sub_line_id, row_version)
    ]

    try:
        _, new_hash = reorder_capex_lines(
            project_record=project_record,
            user_id=user.user_id,
            parent_category_code=parent_category_code,
            ordered_rows=ordered_rows,
            workbook_version=workbook_version,
            expected_content_hash=content_hash,
        )
    except CapexStaleIdentityError:
        return _stale_identity_response(request, project_record, user, project, ws, is_htmx)
    except CapexCommandError as exc:
        if is_htmx:
            from app.workbook.service import WorkbookService
            pis = WorkbookService.build_draft_input_set_from_workspace(ws).with_composite_hash(content_hash)
            return _render_capex_sheet(request, project_record, pis, ws, project, field_error=str(exc))
        return _handle_command_error(exc)

    from app.persistence.workspace_repository import get_workspace_state
    ws = get_workspace_state(user_id=user.user_id, project_id=project_record.project_id) or ws
    if is_htmx:
        # Reorder is hash-invariant; new_hash == content_hash
        pis = _build_pis_with_hash(ws, project_record, user, new_hash)
        return _render_capex_sheet_with_oob(request, project_record, pis, ws, project, workspace_owner=user.user_id)
    return RedirectResponse(url=f"/v2/workbook?project={project}", status_code=303)
