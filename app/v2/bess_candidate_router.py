"""Release-closed, non-persisting operating review; never a financial Save/Run."""
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from app.auth import resolve_request_session, generate_csrf_token, validate_csrf_token
from app.persistence.projects_repository import resolve_accessible_project
from app.ui.protected_reference_service import is_protected_reference
from app.utils.workbook_flag import require_v2_active
from app.workbook.registry import WORKBOOK
from app.workbook.workbook_identity import assemble_consistent_for_get, WorkbookIdentityError
from domain.bess.contracts import parse_configuration, BessInputError, DispatchMode
from domain.bess.dispatch import evaluate
from domain.bess.synthetic import example

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))
CANDIDATE_UI_ENABLED = False
HEADERS = {"Cache-Control": "no-store"}
MAX_REVIEW_HOURS = 8784
MAX_REQUEST_BYTES = 2_100_000


def _error(status, message):
    return JSONResponse({"error": message, "financial_calculation_count": 0, "persisted": False}, status_code=status, headers=HEADERS)


def _scope(request, project):
    if not CANDIDATE_UI_ENABLED:
        return None, None, None, _error(404, "BESS_CANDIDATE_UI_RELEASE_CLOSED")
    user = resolve_request_session(request)
    if user is None:
        return None, None, None, _error(401, "Unauthenticated")
    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return None, None, None, _error(404, "Project not found")
    if (record.project_type or "").strip().lower() != "storage":
        return None, None, None, _error(409, "BESS_STANDALONE_STORAGE_SCOPE_REQUIRED")
    return user, record, owner, None


def _identity(owner, project_id):
    return assemble_consistent_for_get(owner, project_id, WORKBOOK.version).composite_hash


def _render(request, record, identity, config, result=None, readonly=False):
    import json
    return templates.TemplateResponse(request=request, name="v2/bess_candidate.html", context={
        "project": record, "content_hash": identity, "csrf_token": generate_csrf_token(),
        "configuration": json.loads(config.canonical_json) if config else example(),
        "result": result, "readonly": readonly,
        "sample_hours": result.hours[:24] + result.hours[-24:] if result and len(result.hours) > 48 else result.hours if result else (),
        "financial_release": False,
    }, headers=HEADERS)


@router.get("/workbook/bess/candidate", response_class=HTMLResponse)
async def candidate_page(request: Request, project: str, _: None = Depends(require_v2_active)):
    user, record, owner, error = _scope(request, project)
    if error is not None:
        return error
    try:
        identity = _identity(owner, record.project_id)
    except WorkbookIdentityError:
        return _error(409, "BESS_CONTEXT_UNAVAILABLE")
    return _render(request, record, identity, None, readonly=is_protected_reference(record) or owner != user.user_id)


@router.post("/workbook/bess/candidate/validate", response_class=HTMLResponse)
async def validate_candidate(request: Request, _: None = Depends(require_v2_active)):
    if not CANDIDATE_UI_ENABLED:
        return _error(404, "BESS_CANDIDATE_UI_RELEASE_CLOSED")
    # Stream-bound the request, including a missing/forged Content-Length header.
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_REQUEST_BYTES:
            return _error(413, "BESS_REQUEST_TOO_LARGE")
    from urllib.parse import parse_qs
    try:
        if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
            return _error(415, "BESS_FORM_ENCODING_REQUIRED")
        fields = parse_qs(bytes(data).decode("utf-8"), keep_blank_values=True, max_num_fields=4)
        if set(fields) != {"project", "csrf_token", "content_hash", "configuration"} or any(len(v) != 1 for v in fields.values()):
            return _error(422, "BESS_FORM_SCHEMA_INVALID")
        form = {key: values[0] for key, values in fields.items()}
    except (UnicodeDecodeError, ValueError):
        return _error(422, "BESS_FORM_SCHEMA_INVALID")
    user, record, owner, error = _scope(request, form["project"])
    if error is not None:
        return error
    if not validate_csrf_token(form["csrf_token"]):
        return _error(403, "BESS_CSRF_INVALID")
    if is_protected_reference(record) or owner != user.user_id:
        return _error(409, "BESS_READ_ONLY_SCOPE")
    try:
        identity = _identity(owner, record.project_id)
        if not form["content_hash"] or identity != form["content_hash"]:
            return _error(409, "BESS_CONTEXT_CHANGED")
        config = parse_configuration(form["configuration"])
        if config.mode is not DispatchMode.FIXED_DAILY_PLAN:
            return _error(422, "BESS_REVIEW_FORM_FIXED_DAILY_ONLY: explicit hourly files remain Python-candidate input")
        if (config.end - config.start).total_seconds() > MAX_REVIEW_HOURS * 3600:
            return _error(422, "BESS_REVIEW_HORIZON_LIMIT: at most 8784 hours in the ephemeral UI")
        result = await run_in_threadpool(evaluate, config)
        # An edit, selected scenario, archived/protected project, or owner change
        # during calculation invalidates this response; nothing was persisted.
        current, current_owner = resolve_accessible_project(user.user_id, form["project"])
        if (current is None or current_owner != owner or current.project_id != record.project_id
            or is_protected_reference(current) or (current.project_type or "").lower() != "storage"
            or _identity(owner, record.project_id) != identity):
            return _error(409, "BESS_CONTEXT_CHANGED")
    except WorkbookIdentityError:
        return _error(409, "BESS_CONTEXT_UNAVAILABLE")
    except BessInputError as exc:
        return _error(422, str(exc))
    return _render(request, record, identity, config, result)
