"""RC-UX A3 (Audit A GAP-R10) — JSON adapter for the React Excel/CSV import workspace.

A presentation/adapter layer over the EXISTING Workflow C import authority (``app.v2.import_router`` over ``app.model_import``).  It adds NO
mapping, normalisation, validation, persistence or financial authority of its own:

* ``GET  /model-react/import/context``  — the signed CSRF token, the composite content hash the review will be bound to, the upload limits and
  the registry fields a row may be mapped to.  Read-only.
* ``POST /model-react/import/preview``  — ``import_router.model_input_import_preview``: reads the uploaded CSV/XLSX in memory only and returns the
  proposed mappings plus the signed preview ticket.  Nothing is stored or written.
* ``POST /model-react/import/confirm``  — ``import_router.model_input_import_confirm``: re-derives every selected row from the signed ticket, validates
  it with the canonical field validator and returns the approved set plus the signed approval ticket.  Nothing is written.
* ``POST /model-react/import/apply``    — ``import_router.model_input_import_apply``: the ONLY write, and it is the canonical C0 batch writer
  (``WorkbookUpdateService.apply_batch_draft_update``: composite-hash compare-and-swap, one transaction).  It does not run the model.

Every state-changing step is the Legacy handler itself, called unchanged: its CSRF validation, ownership and protected-reference refusal, size
limits, proposal limit, preview-staleness check and error codes are the Legacy ones.  This module only (a) requires the feature flag, the React
request header and a session, (b) enforces the same upload body bound the Legacy path has in ``main_web.py`` BEFORE the body is parsed, and
(c) turns the handler's template context into JSON with an explicit allow-list of fields.  It contains no writer, SQL, token validator or
engine reference.

Feature flag: ``FINCO_MODEL_REACT_V1``.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.auth import resolve_request_session
from app.v2.react_poc_router import react_poc_enabled

router = APIRouter()

REQUEST_HEADER = "x-finco-react-request"
BODY_SLACK = 16 * 1024
ROW_KEYS = ("id", "sheet", "section", "source_cell", "label", "original_value", "source_unit", "field_id", "normalized_value", "current_value",
            "mapping_method", "confidence_class", "explanation", "category", "status", "reason", "duplicate_target", "bulk_selectable",
            "manual_scalar_mapping_allowed", "owner_editor")
APPROVED_KEYS = ("source_id", "sheet", "cell", "label", "field_id", "value", "unit", "original_value", "current_value", "changed",
                 "normalization", "corrections", "correction_note", "extracted_unit", "chosen_unit", "canonical_unit")
SAVED_KEYS = ("field_id", "source", "label", "original_value", "source_unit", "normalization", "previous_value", "actual_value",
              "approved_value", "corrections", "correction_note", "unit_corrected", "field_remapped", "value_overridden")


def _json(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "private, no-store"})


def _fail(status: int, code: str, message: str) -> JSONResponse:
    return _json({"ok": False, "code": code, "message": message + " Nothing was changed."}, status)


def _scope(request: Request, project: str, *, header: bool):
    """(user, record, ws, owner) or a ready JSONResponse: flag, header, session, own editable project, workspace."""
    if not react_poc_enabled():
        return None, None, None, None, _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    if header and request.headers.get(REQUEST_HEADER) != "1":
        return None, None, None, None, _fail(400, "REQUEST_HEADER_REQUIRED", "This step can only be started from the FINCO Model workspace.")
    user = resolve_request_session(request)
    if user is None:
        return None, None, None, None, _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.project_library_service import is_protected_reference

    record, owner = resolve_accessible_project(user.user_id, (project or "").strip())
    if record is None:
        return None, None, None, None, _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    # Import writes the owner's own working inputs: never through a shared project, a template or an archived project (the Legacy rule).
    if owner != user.user_id or is_protected_reference(record) or getattr(record, "archived", False):
        return None, None, None, None, _fail(403, "IMPORT_PROJECT_READ_ONLY", "This project cannot be edited.")
    ws = get_workspace_state(owner, record.project_id)
    if ws is None:
        return None, None, None, None, _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    return user, record, ws, owner, None


def _same_project(request: Request, form) -> Optional[JSONResponse]:
    """The project in the URL (which the scope check authorised) must be the one in the form the Legacy handler will act on."""
    if str(form.get("project", "")).strip() != (request.query_params.get("project") or "").strip():
        return _fail(400, "BODY_INVALID", "The request does not match the open project.")
    return None


def _pick(source: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: source.get(k) for k in keys}


def _legacy_failure(response) -> Optional[JSONResponse]:
    """A Legacy redirect (session / ownership) or an error context is a refusal: nothing was changed."""
    if isinstance(response, RedirectResponse):
        location = response.headers.get("location", "")
        if "login" in location:
            return _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
        return _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    context = getattr(response, "context", None)
    if not isinstance(context, dict):
        return _fail(502, "IMPORT_UNAVAILABLE", "The import service did not answer.")
    code = context.get("error")
    if code:
        status = response.status_code if isinstance(response.status_code, int) and response.status_code >= 400 else 422
        return _json({"ok": False, "code": str(code), "message": "The file could not be used. Nothing was changed."}, status)
    return None


@router.get("/model-react/import/context")
async def react_import_context(request: Request, project: str = ""):
    user, record, ws, owner, refused = _scope(request, project, header=False)
    if refused is not None:
        return refused
    from app.model_import.intake import MAX_UPLOAD_BYTES
    from app.v2.import_router import _context, _field_options

    ctx = _context(request, user, record, ws, stage="upload")
    return _json({
        "ok": True,
        "project": {"code": record.project_code, "name": record.project_name},
        "csrf_token": ctx["csrf_token"], "content_hash": ctx["content_hash"], "workbook_version": ctx["workbook_version"],
        "scenario_id": ctx["active_scenario_id"] or "",
        "limits": {"max_upload_bytes": MAX_UPLOAD_BYTES, "formats": ["csv", "xlsx"], "max_proposals": 150, "max_approved": 50,
                   "encodings": ["utf-8-sig", "utf-8", "cp1252", "latin-1"]},
        "fields": [{"id": f["id"], "label": f["label"], "unit": f["unit"]} for f in _field_options(record)],
        "steps": ["upload", "review", "confirm", "result"],
        "semantics": {"reads_file_in_memory_only": True, "file_is_stored": False, "apply_runs_the_model": False,
                      "apply_marks_results_stale": True},
    })


@router.post("/model-react/import/preview")
async def react_import_preview(request: Request):
    user, _record, _ws, _owner, refused = _scope(request, request.query_params.get("project", ""), header=True)
    if refused is not None:
        return refused
    from app.model_import.intake import MAX_UPLOAD_BYTES
    from app.v2 import import_router

    # The Legacy upload bound (main_web middleware) applies to the Legacy path only: the same bound is enforced here before parsing.
    try:
        size = int(request.headers.get("content-length") or 0)
    except (TypeError, ValueError):
        size = 0
    if size <= 0:
        return _fail(411, "IMPORT_CONTENT_LENGTH_REQUIRED", "The file size could not be determined.")
    if size > MAX_UPLOAD_BYTES + BODY_SLACK:
        return _fail(413, "IMPORT_BODY_SIZE_INVALID", "This file is too large.")
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001 - an unreadable body is a client error; nothing was read into the project
        return _fail(400, "BODY_INVALID", "The upload could not be read.")
    mismatch = _same_project(request, form)
    if mismatch is not None:
        return mismatch
    upload = form.get("upload")
    if upload is None or not hasattr(upload, "read"):
        return _fail(400, "BODY_INVALID", "Choose a CSV or XLSX file.")
    response = await import_router.model_input_import_preview(
        request, project=str(form.get("project", "")), csrf_token=str(form.get("csrf_token", "")),
        encoding=str(form.get("encoding", "utf-8-sig") or "utf-8-sig"), upload=upload, _=None)
    refusal = _legacy_failure(response)
    if refusal is not None:
        return refusal
    ctx = response.context
    return _json({
        "ok": True, "stage": "review", "detected": ctx["detected"], "totals": ctx["totals"], "digest": ctx["digest"],
        "preview_ticket": ctx["preview_ticket"], "content_hash": ctx["content_hash"], "workbook_version": ctx["workbook_version"],
        "categories": ctx["categories"], "category_counts": ctx["category_counts"],
        "counts": {"exact": ctx["exact_count"], "ambiguous": ctx["ambiguous_count"], "bulk_selectable": ctx["bulk_selectable_count"],
                   "attention": ctx["attention_count"]},
        "rows": [_pick(row, ROW_KEYS) for row in ctx["proposals"]],
        "semantics": {"nothing_written": True, "file_is_stored": False},
    })


@router.post("/model-react/import/confirm")
async def react_import_confirm(request: Request):
    user, _record, _ws, _owner, refused = _scope(request, request.query_params.get("project", ""), header=True)
    if refused is not None:
        return refused
    from app.v2 import import_router

    try:
        form = await request.form()
    except Exception:  # noqa: BLE001
        return _fail(400, "BODY_INVALID", "The review could not be read.")
    mismatch = _same_project(request, form)
    if mismatch is not None:
        return mismatch
    response = await import_router.model_input_import_confirm(
        request, project=str(form.get("project", "")), csrf_token=str(form.get("csrf_token", "")),
        preview_ticket=str(form.get("preview_ticket", "")), _=None)
    refusal = _legacy_failure(response)
    if refusal is not None:
        return refusal
    ctx = response.context
    return _json({
        "ok": True, "stage": "confirm", "approved_ticket": ctx["approved_ticket"],
        "approved": [_pick(row, APPROVED_KEYS) for row in ctx["approved"]],
        "approved_count": ctx["approved_count"], "changed_count": ctx["changed_count"], "unchecked_count": ctx["unchecked_count"],
        "content_hash": ctx["content_hash"], "workbook_version": ctx["workbook_version"],
        "semantics": {"nothing_written": True},
    })


@router.post("/model-react/import/apply")
async def react_import_apply(request: Request):
    user, _record, _ws, _owner, refused = _scope(request, request.query_params.get("project", ""), header=True)
    if refused is not None:
        return refused
    from app.v2 import import_router

    try:
        form = await request.form()
    except Exception:  # noqa: BLE001
        return _fail(400, "BODY_INVALID", "The approval could not be read.")
    mismatch = _same_project(request, form)
    if mismatch is not None:
        return mismatch
    response = await import_router.model_input_import_apply(
        request, project=str(form.get("project", "")), csrf_token=str(form.get("csrf_token", "")),
        approved_ticket=str(form.get("approved_ticket", "")), _=None)
    refusal = _legacy_failure(response)
    if refusal is not None:
        return refusal
    ctx = response.context
    return _json({
        "ok": True, "stage": "result", "saved": [_pick(row, SAVED_KEYS) for row in ctx["saved"]],
        "applied_count": ctx["applied_count"], "skipped_count": ctx["skipped_count"], "freshness": ctx["freshness_state"],
        "approved_at": ctx.get("approved_at"), "transaction_identity": ctx.get("transaction_identity"),
        "semantics": {"model_was_run": False,
                      "note": "The values were saved to your project. Nothing was calculated; run the model to see their effect."},
    })
