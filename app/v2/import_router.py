"""Workflow C: authenticated read-only CSV/XLSX intake and review surface.

The C0 transaction must pass independent focused acceptance before mutation
routes are enabled. Upload and review never run the financial engine.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.templating import Jinja2Templates

from app.auth import (
    generate_csrf_token, resolve_request_session, validate_csrf_token,
)
from app.model_import.intake import MAX_UPLOAD_BYTES, IntakeError, extract_proposals
from app.persistence.projects_repository import resolve_accessible_project
from app.persistence.workspace_repository import get_workspace_state
from app.services.project_library_service import is_protected_reference
from app.utils.workbook_flag import require_v2_active
from app.workbook.input_set import ProjectInputSet
from app.workbook.registry import WORKBOOK
from app.workbook.specs import BindingStatus, FieldKind, SourceOfTruth
from app.workbook.update_service import _assert_batch_field_applicable, BatchApplyError
from app.workbook.workbook_identity import assemble_consistent_for_get

router = APIRouter()
_templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates" / "v2"))


def _field_options(project) -> list[dict]:
    options = []
    for spec in WORKBOOK.all_fields():
        if (spec.binding_status != BindingStatus.BOUND
                or spec.kind != FieldKind.INPUT
                or spec.source_of_truth != SourceOfTruth.INPUT_SET
                or not spec.editable or not spec.persisted or spec.runtime_only):
            continue
        try:
            _assert_batch_field_applicable(
                spec.field_id, project_type=project.project_type or "",
                template_source=project.template_source or "")
        except BatchApplyError:
            continue
        options.append({
            "id": spec.field_id, "label": spec.label, "unit": spec.unit or "",
            "register_path": spec.engine_path or "",
        })
    return options


def _context(request, user, project, ws, *, stage, proposals=None, error=None,
             detected=0, totals=None, digest=None):
    pis = ProjectInputSet.from_snapshot(ws.draft_snapshot, workbook=WORKBOOK)
    identity = assemble_consistent_for_get(ws.user_id, project.project_id, WORKBOOK.version)
    rows = []
    for p in proposals or []:
        q = dict(p)
        q["current_value"] = pis.get(p["field_id"]) if p["field_id"] else None
        rows.append(q)
    return {
        "request": request, "user": user,
        "project": project, "project_code": project.project_code,
        "stage": stage, "csrf_token": generate_csrf_token(),
        "error": error, "proposals": rows, "detected": detected,
        "totals": totals or {}, "digest": digest or "",
        "content_hash": identity.composite_hash,
        "workbook_version": WORKBOOK.version,
        "active_scenario_id": ws.active_scenario_id,
        "fields": _field_options(project),
        "apply_available": True,
    }


@router.get("/workbook/import", response_class=HTMLResponse)
async def model_input_import_page(request: Request, project: str = "",
                                  _: None = Depends(require_v2_active)):
    user = resolve_request_session(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None or owner != user.user_id or is_protected_reference(record):
        return RedirectResponse(url="/library", status_code=302)
    ws = get_workspace_state(owner, record.project_id)
    if ws is None:
        return RedirectResponse(url="/library", status_code=302)
    return _templates.TemplateResponse(
        request=request, name="import_review.html",
        context=_context(request, user, record, ws, stage="upload"))


@router.post("/workbook/import/preview", response_class=HTMLResponse)
async def model_input_import_preview(
    request: Request,
    project: str = Form(...),
    csrf_token: str = Form(...),
    encoding: str = Form("utf-8-sig"),
    upload: UploadFile = File(...),
    _: None = Depends(require_v2_active),
):
    user = resolve_request_session(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None or owner != user.user_id or is_protected_reference(record):
        return RedirectResponse(url="/library", status_code=302)
    ws = get_workspace_state(owner, record.project_id)
    if ws is None:
        return RedirectResponse(url="/library", status_code=302)
    if not validate_csrf_token(csrf_token):
        return _templates.TemplateResponse(
            request=request, name="import_review.html",
            context=_context(request, user, record, ws, stage="upload", error="IMPORT_CSRF_INVALID"),
            status_code=403)
    try:
        header_length = request.headers.get("content-length")
        if header_length and int(header_length) > MAX_UPLOAD_BYTES + 16 * 1024:
            raise IntakeError("IMPORT_BODY_SIZE_INVALID")
        data = await upload.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise IntakeError("IMPORT_FILE_SIZE_INVALID")
        result = extract_proposals(
            data, upload.filename or "", encoding=encoding,
            project_type=record.project_type or "",
            template_source=record.template_source or "",
        )
        if result["detected"] > 150:
            raise IntakeError("IMPORT_PROPOSAL_LIMIT_EXCEEDED")
        ctx = _context(
            request, user, record, ws, stage="review",
            proposals=result["proposals"], detected=result["detected"],
            totals=result["totals"], digest=hashlib.sha256(data).hexdigest(),
        )
        from app.model_import.review import seal_preview
        ctx["preview_ticket"] = seal_preview(
            owner=owner, project_id=record.project_id,
            scenario_id=ws.active_scenario_id,
            content_hash=ctx["content_hash"], workbook_version=WORKBOOK.version,
            digest=ctx["digest"], proposals=result["proposals"],
        )
        return _templates.TemplateResponse(
            request=request, name="import_review.html", context=ctx)
    except (IntakeError, ValueError) as exc:
        code = getattr(exc, "code", "IMPORT_PARSE_REJECTED")
        return _templates.TemplateResponse(
            request=request, name="import_review.html",
            context=_context(request, user, record, ws, stage="upload", error=code),
            status_code=422)
    finally:
        await upload.close()


@router.post("/workbook/import/confirm", response_class=HTMLResponse)
async def model_input_import_confirm(
    request: Request,
    project: str = Form(...),
    csrf_token: str = Form(...),
    preview_ticket: str = Form(...),
    _: None = Depends(require_v2_active),
):
    """Second explicit review boundary: approve, validate, then seal a final set.

    This route never writes financial inputs or runs a model.
    """
    from app.model_import.review import (
        ImportReviewError, resolve_review, seal_approved,
    )
    user = resolve_request_session(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None or owner != user.user_id or is_protected_reference(record):
        return RedirectResponse(url="/library", status_code=302)
    ws = get_workspace_state(owner, record.project_id)
    if ws is None:
        return RedirectResponse(url="/library", status_code=302)
    if not validate_csrf_token(csrf_token):
        return _templates.TemplateResponse(
            request=request, name="import_review.html",
            context=_context(request, user, record, ws, stage="upload", error="IMPORT_CSRF_INVALID"),
            status_code=403)
    try:
        form = await request.form()
        preview, approved = resolve_review(
            ticket=preview_ticket, owner=owner, project_id=record.project_id,
            selections=form, project_type=record.project_type or "",
            template_source=record.template_source or "",
        )
        current = assemble_consistent_for_get(owner, record.project_id, WORKBOOK.version)
        if (preview["scenario_id"] != ws.active_scenario_id
                or preview["content_hash"] != current.composite_hash
                or preview["workbook_version"] != WORKBOOK.version):
            raise ImportReviewError("IMPORT_PREVIEW_STALE")
        pis = ProjectInputSet.from_snapshot(ws.draft_snapshot, workbook=WORKBOOK)
        for row in approved:
            row["current_value"] = pis.get(row["field_id"])
            row["changed"] = str(row["current_value"]) != str(row["value"])
        ctx = _context(request, user, record, ws, stage="confirm")
        ctx["approved"] = approved
        ctx["approved_ticket"] = seal_approved(preview, approved)
        ctx["approved_count"] = len(approved)
        ctx["changed_count"] = sum(bool(r["changed"]) for r in approved)
        return _templates.TemplateResponse(
            request=request, name="import_review.html", context=ctx)
    except (ImportReviewError, IntakeError, ValueError) as exc:
        code = getattr(exc, "code", "IMPORT_REVIEW_INVALID")
        return _templates.TemplateResponse(
            request=request, name="import_review.html",
            context=_context(request, user, record, ws, stage="upload", error=code),
            status_code=409 if code == "IMPORT_PREVIEW_STALE" else 422)


@router.post("/workbook/import/apply", response_class=HTMLResponse)
async def model_input_import_apply(
    request: Request,
    project: str = Form(...),
    csrf_token: str = Form(...),
    approved_ticket: str = Form(...),
    _: None = Depends(require_v2_active),
):
    """Explicit authenticated Apply: ONLY the C0 canonical batch writer."""
    from app.model_import.review import ImportReviewError, unseal_approved
    from app.workbook.update_service import (
        WorkbookUpdateService, BatchApplyError, FieldValidationError,
        StaleContentError, VersionMismatchError, ProtectedReferenceError,
        NonEditableFieldError, UnknownFieldError,
    )
    user = resolve_request_session(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None or owner != user.user_id or is_protected_reference(record):
        return RedirectResponse(url="/library", status_code=302)
    ws = get_workspace_state(owner, record.project_id)
    if ws is None:
        return RedirectResponse(url="/library", status_code=302)
    if not validate_csrf_token(csrf_token):
        return _templates.TemplateResponse(
            request=request, name="import_review.html",
            context=_context(request, user, record, ws, stage="upload", error="IMPORT_CSRF_INVALID"),
            status_code=403)
    try:
        signed = unseal_approved(approved_ticket, owner=owner, project_id=record.project_id)
        approved = signed["approved"]
        # Server repeats canonical field validation inside the C0 transaction.
        changes = [(item["field_id"], item["value"]) for item in approved]
        WorkbookUpdateService.apply_batch_draft_update(
            ws=ws, updates=changes,
            content_hash=signed["content_hash"],
            workbook_version=signed["workbook_version"],
            expected_scenario_id=signed["scenario_id"],
            project_record=record, actor_user_id=user.user_id,
        )
        fresh = get_workspace_state(owner, record.project_id)
        if fresh is None:
            raise ImportReviewError("IMPORT_POST_APPLY_READ_UNAVAILABLE")
        pis = ProjectInputSet.from_snapshot(fresh.draft_snapshot, workbook=WORKBOOK)
        from app.workbook.runtime_authority import resolve_runtime_freshness
        identity = assemble_consistent_for_get(owner, record.project_id, WORKBOOK.version)
        freshness = resolve_runtime_freshness(
            fresh, current_composite_hash=identity.composite_hash)
        saved = [{
            "field_id": item["field_id"],
            "source": f'{item["sheet"]}!{item["cell"]}',
            "actual_value": pis.get(item["field_id"]),
            "approved_value": item["value"],
        } for item in approved]
        ctx = _context(request, user, record, fresh, stage="result")
        ctx["saved"] = saved
        ctx["applied_count"] = len(saved)
        ctx["skipped_count"] = 0
        ctx["freshness_state"] = freshness.state.value
        return _templates.TemplateResponse(
            request=request, name="import_review.html", context=ctx)
    except (ImportReviewError, BatchApplyError, FieldValidationError,
            StaleContentError, VersionMismatchError, ProtectedReferenceError,
            NonEditableFieldError, UnknownFieldError, ValueError) as exc:
        code = getattr(exc, "code", type(exc).__name__)
        return _templates.TemplateResponse(
            request=request, name="import_review.html",
            context=_context(request, user, record, ws, stage="upload", error=code),
            status_code=409 if isinstance(exc, (StaleContentError, VersionMismatchError)) else 422)
