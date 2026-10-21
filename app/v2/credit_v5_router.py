"""Isolated GET-only headroom analysis; no Working Copy reads, writes or solver."""
from dataclasses import asdict

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.services.credit_v5 import Constraint, METRICS, analyze_runs

router = APIRouter()
HEADERS = {"Cache-Control": "private, no-store"}


@router.get("/credit-decision/v5", response_class=HTMLResponse)
async def credit_v5_page(request: Request, project: str = "", format: str = "html"):
    from app.v2.router import _get_current_user
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.run_history_repository import RunHistoryError, get_run_history, get_run_history_entry
    from app.services.project_library_service import is_protected_reference
    from main_web import templates

    def error(status, reason):
        return JSONResponse({"error": reason}, status_code=status, headers=HEADERS)

    user = _get_current_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=302)
    if not project.strip() or len(project) > 160 or format not in ("html", "json"):
        return error(400, "CREDIT_V5_REQUEST_INVALID")
    record, owner = resolve_accessible_project(user.user_id, project.strip())
    if record is None:
        return error(404, "PROJECT_NOT_FOUND")
    if is_protected_reference(record):
        return error(409, "PROTECTED_REFERENCE_CREATE_WORKING_COPY")
    ids = request.query_params.getlist("run")
    if len(ids) > 3 or len(set(ids)) != len(ids) or any(not r.strip() or len(r) > 128 for r in ids):
        return error(422, "CREDIT_V5_RUN_SELECTION_INVALID")
    constraints = []
    try:
        for metric in METRICS:
            values = request.query_params.getlist(metric)
            if len(values) > 1:
                return error(422, "CREDIT_V5_DUPLICATE_THRESHOLD")
            raw = values[0] if values else ""
            constraints.append(Constraint(metric, float(raw) if raw.strip() else None))
    except (ValueError, OverflowError):
        return error(422, "CREDIT_V5_THRESHOLD_INVALID")
    try:
        history = list(get_run_history(owner, record.project_id, limit=25))
        requested = ids or ([history[0].history_id] if history else [])
        selected = []
        for hid in requested:
            entry = get_run_history_entry(owner, record.project_id, hid)
            if entry is None:
                return error(404, "RUN_HISTORY_ENTRY_NOT_FOUND")
            selected.append(entry)
        data = asdict(analyze_runs(selected, constraints, owner_id=owner, project_id=record.project_id,
                                  project_code=record.project_code)) if selected else None
    except (RunHistoryError, ValueError, TypeError, KeyError):
        return error(422, "CREDIT_V5_COMMITTED_EVIDENCE_INVALID")
    payload = {"data": data, "state": "AVAILABLE" if data else "NO_COMMITTED_RUN",
               "project_code": record.project_code, "project_name": record.project_name,
               "history": history, "requested": requested, "constraints": constraints, "user": user}
    if format == "json":
        return JSONResponse({"state": payload["state"], "data": data}, headers=HEADERS)
    return templates.TemplateResponse(request=request, name="v2/credit_v5.html", context=payload, headers=HEADERS)
