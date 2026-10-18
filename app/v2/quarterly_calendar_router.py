"""RC-7B operating/debt frequency selection endpoint (release-closed).

Owner, CSRF and content-hash (CAS) protected; writes ONE typed Working Copy
field through the existing transactional contract writer. It performs no Run
and no financial calculation. While ``quarterly_frequency_config.ACTIVATION_ENABLED``
is False every request is refused, so no product surface can select 3/3.
"""
from __future__ import annotations

from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.auth import resolve_request_session, validate_csrf_token
from app.persistence.projects_repository import resolve_accessible_project
from app.ui.protected_reference_service import is_protected_reference
from app.utils.workbook_flag import require_v2_active
from app.workbook import quarterly_frequency_config as config
from app.workbook.registry import WORKBOOK

router = APIRouter()
MAX_REQUEST_BYTES = 4096
_FORM_KEYS = {"project", "content_hash", "csrf_token", "workbook_version", "frequency"}


@router.post("/workbook/calendar/operating-frequency")
async def save_operating_frequency(request: Request, _: None = Depends(require_v2_active)):
    if not config.ACTIVATION_ENABLED:
        return JSONResponse({"error": "QUARTERLY_ADMISSION_CLOSED"}, status_code=404)
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_REQUEST_BYTES:
            return JSONResponse({"error": "QUARTERLY_REQUEST_TOO_LARGE"}, status_code=413)
    try:
        if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
            raise ValueError("QUARTERLY_FORM_ENCODING")
        form = parse_qs(bytes(data).decode("utf-8"), keep_blank_values=True, max_num_fields=len(_FORM_KEYS))
        if set(form) != _FORM_KEYS or any(len(v) != 1 for v in form.values()):
            raise ValueError("QUARTERLY_FORM_SCHEMA")
        form = {k: v[0] for k, v in form.items()}
        user = resolve_request_session(request)
        if user is None:
            return JSONResponse({"error": "Unauthenticated"}, status_code=401)
        record, owner = resolve_accessible_project(user.user_id, form["project"])
        if record is None:
            return JSONResponse({"error": "Project not found"}, status_code=404)
        if not validate_csrf_token(form["csrf_token"]):
            return JSONResponse({"error": "QUARTERLY_CSRF_INVALID"}, status_code=403)
        if owner != user.user_id or is_protected_reference(record):
            return JSONResponse({"error": "QUARTERLY_READ_ONLY"}, status_code=403)
        if form["workbook_version"] != WORKBOOK.version:
            raise ValueError("QUARTERLY_WORKBOOK_VERSION_MISMATCH")
        if form["frequency"] == "3/3":
            config.require_admitted(record.project_type)
            raw = config.candidate_config_json()
        elif form["frequency"] == "6/6":
            raw = ""
        else:
            raise ValueError("QUARTERLY_FREQUENCY_UNSUPPORTED: only matched 6/6 or 3/3 (D-06/D-07 deferred)")
        from app.persistence.workspace_repository import get_workspace_state
        from app.workbook.update_service import WorkbookUpdateService
        ws = get_workspace_state(owner, record.project_id)
        if ws is None:
            return JSONResponse({"error": "Workspace not found"}, status_code=404)
        # The existing canonical field pipeline (validate -> version -> atomic CAS
        # persist) owns the write; this endpoint only adds the admission gate.
        WorkbookUpdateService.apply_draft_update(
            ws=ws, field_id=config.FIELD_ID, raw_value=raw, content_hash=form["content_hash"],
            workbook_version=form["workbook_version"], project_record=record)
        return RedirectResponse("/v2/workbook?project=" + quote(record.project_code), status_code=303)
    except (ValueError, UnicodeDecodeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    except Exception as exc:  # typed CAS / protected-reference / version refusals
        name = type(exc).__name__
        status = 403 if name == "ProtectedReferenceError" else 409
        return JSONResponse({"error": f"{name}: {exc}"}, status_code=status)
