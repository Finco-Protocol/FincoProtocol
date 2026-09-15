"""
app.v2.opex_router — OPEX custom-row command endpoints.

Mirrors capex_router.py for the OPEX domain.
Mounted at /v2/opex by main_web.py (under the same FINCO_WORKBOOK_V2 flag).

Endpoints
---------
POST /v2/opex/line/add
POST /v2/opex/line/update
POST /v2/opex/line/deactivate
POST /v2/opex/line/reorder

All endpoints accept content_hash (current composite workbook identity token)
and validate it before mutating.  The re-rendered OPEX sheet carries the new
composite hash after a successful mutation.
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.utils.workbook_flag import require_v2_active

from app.auth import COOKIE_NAME, decode_session_token
from app.v2.opex_commands import (
    OpexCommandError,
    OpexConcurrentEditError,
    OpexProtectedGroupError,
    OpexProtectedReferenceError,
    OpexRowNotFoundError,
    OpexStaleIdentityError,
    OpexVersionMismatchError,
    add_opex_line,
    deactivate_opex_line,
    reorder_opex_lines,
    update_opex_line,
)

opex_router = APIRouter()


def _get_current_user(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return decode_session_token(token)


def _render_opex_sheet(
    request: Request, project_record, pis, ws, project: str, field_error: str = ""
) -> HTMLResponse:
    from app.v2.router import _render_opex_htmx_sheet
    return _render_opex_htmx_sheet(request, pis, ws, project_record, project, field_error=field_error)


def _load_project_and_ws(user, project: str):
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
    from app.workbook.service import WorkbookService
    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    return pis.with_composite_hash(new_composite_hash)


def _stale_identity_response(
    request, project_record, user, project, ws, is_htmx: bool
) -> HTMLResponse | JSONResponse:
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
        return _render_opex_sheet(
            request, project_record, pis, ws, project,
            field_error="Workbook changed since page loaded — values refreshed. Please try again.",
        )
    return JSONResponse(
        {"error": "Workbook changed since page loaded. Reload and try again."},
        status_code=409,
    )


def _render_opex_sheet_with_oob(
    request: Request, project_record, pis, ws, project: str,
    field_error: str = "", workspace_owner: str = "",
) -> HTMLResponse:
    """Render OPEX sheet + full post-Save stale-state refresh (R6/F07
    Correction A: toolbar, stale Overview, runtime bars, scenario statuses)
    + run controls OOB on success."""
    resp = _render_opex_sheet(request, project_record, pis, ws, project, field_error=field_error)
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
    # R6 Correction A: the OPEX save made the workspace dirty — the prior
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


def _handle_command_error(exc: OpexCommandError) -> JSONResponse:
    if isinstance(exc, OpexProtectedReferenceError):
        return JSONResponse({"error": str(exc)}, status_code=409)
    if isinstance(exc, OpexVersionMismatchError):
        return JSONResponse({"error": str(exc), "reload": True}, status_code=409)
    if isinstance(exc, OpexStaleIdentityError):
        return JSONResponse({"error": str(exc)}, status_code=409)
    if isinstance(exc, OpexConcurrentEditError):
        return JSONResponse({"error": str(exc)}, status_code=409)
    if isinstance(exc, OpexProtectedGroupError):
        return JSONResponse({"error": str(exc)}, status_code=422)
    if isinstance(exc, OpexRowNotFoundError):
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse({"error": str(exc)}, status_code=422)


@opex_router.post("/line/add")
async def opex_line_add(
    request: Request,
    project: str = Form(...),
    parent_group_code: str = Form(...),
    label: str = Form(...),
    amount_keur: float = Form(default=0.0),
    inflation_pct: float = Form(default=0.0),
    notes: str = Form(default=""),
    workbook_version: str = Form(...),
    content_hash: str = Form(...),
    _: None = Depends(require_v2_active),
):
    user = _get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    try:
        project_record, ws = _load_project_and_ws(user, project)
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

    is_htmx = request.headers.get("HX-Request") == "true"

    try:
        _, new_hash = add_opex_line(
            project_record=project_record,
            user_id=user.user_id,
            label=label.strip(),
            parent_group_code=parent_group_code,
            amount_keur=amount_keur,
            inflation_pct=inflation_pct,
            notes=notes,
            workbook_version=workbook_version,
            expected_content_hash=content_hash,
        )
    except OpexStaleIdentityError:
        return _stale_identity_response(request, project_record, user, project, ws, is_htmx)
    except OpexCommandError as exc:
        if is_htmx:
            from app.workbook.service import WorkbookService
            pis = WorkbookService.build_draft_input_set_from_workspace(ws).with_composite_hash(content_hash)
            return _render_opex_sheet(request, project_record, pis, ws, project, field_error=str(exc))
        return _handle_command_error(exc)
    except ValueError as exc:
        if is_htmx:
            from app.workbook.service import WorkbookService
            pis = WorkbookService.build_draft_input_set_from_workspace(ws).with_composite_hash(content_hash)
            return _render_opex_sheet(request, project_record, pis, ws, project, field_error=str(exc))
        return JSONResponse({"error": str(exc)}, status_code=422)

    from app.persistence.workspace_repository import get_workspace_state
    ws = get_workspace_state(user_id=user.user_id, project_id=project_record.project_id) or ws
    if is_htmx:
        pis = _build_pis_with_hash(ws, project_record, user, new_hash)
        return _render_opex_sheet_with_oob(request, project_record, pis, ws, project, workspace_owner=user.user_id)
    return RedirectResponse(url=f"/v2/workbook?project={project}", status_code=303)


@opex_router.post("/line/update")
async def opex_line_update(
    request: Request,
    project: str = Form(...),
    sub_line_id: str = Form(...),
    label: str = Form(...),
    amount_keur: float = Form(default=0.0),
    inflation_pct: float = Form(default=0.0),
    notes: str = Form(default=""),
    row_version: str = Form(...),
    workbook_version: str = Form(...),
    content_hash: str = Form(...),
    _: None = Depends(require_v2_active),
):
    user = _get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    try:
        project_record, ws = _load_project_and_ws(user, project)
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

    is_htmx = request.headers.get("HX-Request") == "true"

    try:
        _, new_hash = update_opex_line(
            project_record=project_record,
            user_id=user.user_id,
            sub_line_id=sub_line_id,
            label=label.strip(),
            amount_keur=amount_keur,
            inflation_pct=inflation_pct,
            notes=notes,
            row_version=row_version,
            workbook_version=workbook_version,
            expected_content_hash=content_hash,
        )
    except OpexStaleIdentityError:
        return _stale_identity_response(request, project_record, user, project, ws, is_htmx)
    except OpexCommandError as exc:
        if is_htmx:
            err = str(exc)
            if isinstance(exc, OpexConcurrentEditError):
                err = "Row was modified concurrently — values refreshed. Try again."
            from app.workbook.service import WorkbookService
            pis = WorkbookService.build_draft_input_set_from_workspace(ws).with_composite_hash(content_hash)
            return _render_opex_sheet(request, project_record, pis, ws, project, field_error=err)
        return _handle_command_error(exc)
    except ValueError as exc:
        if is_htmx:
            from app.workbook.service import WorkbookService
            pis = WorkbookService.build_draft_input_set_from_workspace(ws).with_composite_hash(content_hash)
            return _render_opex_sheet(request, project_record, pis, ws, project, field_error=str(exc))
        return JSONResponse({"error": str(exc)}, status_code=422)

    from app.persistence.workspace_repository import get_workspace_state
    ws = get_workspace_state(user_id=user.user_id, project_id=project_record.project_id) or ws
    if is_htmx:
        pis = _build_pis_with_hash(ws, project_record, user, new_hash)
        return _render_opex_sheet_with_oob(request, project_record, pis, ws, project, workspace_owner=user.user_id)
    return RedirectResponse(url=f"/v2/workbook?project={project}", status_code=303)


@opex_router.post("/line/deactivate")
async def opex_line_deactivate(
    request: Request,
    project: str = Form(...),
    sub_line_id: str = Form(...),
    row_version: str = Form(...),
    workbook_version: str = Form(...),
    content_hash: str = Form(...),
    _: None = Depends(require_v2_active),
):
    user = _get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    try:
        project_record, ws = _load_project_and_ws(user, project)
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

    is_htmx = request.headers.get("HX-Request") == "true"

    try:
        _, new_hash = deactivate_opex_line(
            project_record=project_record,
            user_id=user.user_id,
            sub_line_id=sub_line_id,
            row_version=row_version,
            workbook_version=workbook_version,
            expected_content_hash=content_hash,
        )
    except OpexStaleIdentityError:
        return _stale_identity_response(request, project_record, user, project, ws, is_htmx)
    except OpexCommandError as exc:
        if is_htmx:
            err = str(exc)
            if isinstance(exc, OpexConcurrentEditError):
                err = "Row was modified concurrently — values refreshed. Try again."
            from app.workbook.service import WorkbookService
            pis = WorkbookService.build_draft_input_set_from_workspace(ws).with_composite_hash(content_hash)
            return _render_opex_sheet(request, project_record, pis, ws, project, field_error=err)
        return _handle_command_error(exc)

    from app.persistence.workspace_repository import get_workspace_state
    ws = get_workspace_state(user_id=user.user_id, project_id=project_record.project_id) or ws
    if is_htmx:
        pis = _build_pis_with_hash(ws, project_record, user, new_hash)
        return _render_opex_sheet_with_oob(request, project_record, pis, ws, project, workspace_owner=user.user_id)
    return RedirectResponse(url=f"/v2/workbook?project={project}", status_code=303)


@opex_router.post("/line/reorder")
async def opex_line_reorder(
    request: Request,
    project: str = Form(...),
    parent_group_code: str = Form(...),
    sub_line_id: List[str] = Form(default=[]),
    row_version: List[str] = Form(default=[]),
    workbook_version: str = Form(...),
    content_hash: str = Form(...),
    _: None = Depends(require_v2_active),
):
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
            return _render_opex_sheet(request, project_record, pis, ws, project, field_error=err)
        return JSONResponse({"error": err}, status_code=422)

    ordered_rows = [
        {"sub_line_id": sid, "row_version": rv}
        for sid, rv in zip(sub_line_id, row_version)
    ]

    try:
        _, new_hash = reorder_opex_lines(
            project_record=project_record,
            user_id=user.user_id,
            parent_group_code=parent_group_code,
            ordered_rows=ordered_rows,
            workbook_version=workbook_version,
            expected_content_hash=content_hash,
        )
    except OpexStaleIdentityError:
        return _stale_identity_response(request, project_record, user, project, ws, is_htmx)
    except OpexCommandError as exc:
        if is_htmx:
            from app.workbook.service import WorkbookService
            pis = WorkbookService.build_draft_input_set_from_workspace(ws).with_composite_hash(content_hash)
            return _render_opex_sheet(request, project_record, pis, ws, project, field_error=str(exc))
        return _handle_command_error(exc)

    from app.persistence.workspace_repository import get_workspace_state
    ws = get_workspace_state(user_id=user.user_id, project_id=project_record.project_id) or ws
    if is_htmx:
        pis = _build_pis_with_hash(ws, project_record, user, new_hash)
        return _render_opex_sheet_with_oob(request, project_record, pis, ws, project, workspace_owner=user.user_id)
    return RedirectResponse(url=f"/v2/workbook?project={project}", status_code=303)
