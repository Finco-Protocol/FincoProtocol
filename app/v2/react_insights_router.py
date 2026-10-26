"""Authenticated, read-only JSON financial intelligence for the React Model.

Project access is resolved before history or scenario reads. Explicit Run IDs,
immutable bindings and canonical projections are the only result authorities.
No writes, signing, CSRF token issuance, Save, Clone or Run execution occurs.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import resolve_request_session
from app.services.react_insights_service import (
    MAX_RUNS, SCHEMA, InsightsIdentityError, build_insights, run_identity,
    run_links, validate_entry,
)

router = APIRouter()
HISTORY_LIMIT = 25


def _json(payload: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "private, no-store"})


def _error(code: str, status: int, message: str = "") -> JSONResponse:
    return _json({"ok": False, "code": code, "message": message}, status)


def _context(request: Request, project: str):
    from app.v2.react_poc_router import react_poc_enabled
    if not react_poc_enabled():
        return None, _error("REACT_POC_DISABLED", 404)
    user = resolve_request_session(request)
    if user is None:
        return None, _error("AUTH_REQUIRED", 401)
    from app.persistence.projects_repository import resolve_accessible_project
    from app.services.project_library_service import is_protected_reference
    code = project.strip()
    if not code or len(code) > 160:
        return None, _error("PROJECT_NOT_FOUND", 404)
    record, owner = resolve_accessible_project(user.user_id, code)
    if record is None:
        return None, _error("PROJECT_NOT_FOUND", 404)
    if is_protected_reference(record):
        return None, _error("PROTECTED_REFERENCE", 409,
                            "Create a working copy to review committed credit evidence.")
    from app.v2.post_run_context import PostRunRequestContext
    from app.workbook.workbook_identity import WorkbookIdentityError
    try:
        context = PostRunRequestContext.capture(owner_id=owner, project_id=record.project_id)
        context.require_scope(owner, record.project_id)
    except (PermissionError, WorkbookIdentityError, ValueError):
        return None, _error("INSIGHTS_CONTEXT_UNAVAILABLE", 503,
                            "A coherent workspace read is unavailable. Reload before reviewing evidence.")
    if is_protected_reference(context.project_record):
        return None, _error("PROTECTED_REFERENCE", 409,
                            "Create a working copy to review committed credit evidence.")
    return (context.project_record, owner, context.workspace, context), None


def _validated_json(context, payload):
    """Reject concurrent Working Copy drift before exposing freshness or terms."""
    from app.v2.post_run_context import PostRunContextChanged
    from app.workbook.workbook_identity import WorkbookIdentityError
    try:
        context.validate_current()
        return _json(payload)
    except (PostRunContextChanged, WorkbookIdentityError, PermissionError):
        return _error("INSIGHTS_CONTEXT_CHANGED", 503,
                      "The workspace changed during this read. Reload to review coherent evidence.")
    except ValueError:
        return _error("RUN_EVIDENCE_UNAVAILABLE", 422, "Stored evidence is not valid JSON financial data.")


def _state(entry, ws, freshness):
    from app.v2.credit_decision_projection import HISTORICAL, LAST_CURRENT, LAST_STALE
    if entry.runtime_snapshot_id != getattr(ws, "last_runtime_snapshot_id", None):
        return HISTORICAL
    return {"CURRENT": LAST_CURRENT, "STALE": LAST_STALE}.get(freshness, HISTORICAL)


@router.get("/model-react/insights/history")
async def react_insights_history(request: Request, project: str = ""):
    context, failure = _context(request, project)
    if failure is not None:
        return failure
    record, owner, ws, read_context = context
    if set(request.query_params) - {"project"} or len(request.query_params.getlist("project")) != 1:
        return _error("INVALID_QUERY", 400)
    from app.persistence.run_history_repository import RunHistoryError, get_run_history
    from app.persistence.scenario_insight_reads import (
        HISTORY_UNAVAILABLE, list_insight_scenarios, newest_committed_runs,
    )
    try:
        entries = list(get_run_history(owner, record.project_id, limit=HISTORY_LIMIT))
        for entry in entries:
            validate_entry(entry, project_id=record.project_id, project_code=record.project_code, owner=owner)
    except (RunHistoryError, InsightsIdentityError):
        return _error("RUN_HISTORY_UNAVAILABLE", 422, "Stored Run History could not be verified.")
    freshness = read_context.freshness.state.value
    rows = [{"identity": run_identity(e, _state(e, ws, freshness)),
             "links": run_links(record.project_code, e.history_id)} for e in entries]
    scenarios = list_insight_scenarios(owner, record.project_id, getattr(ws, "active_scenario_id", None))
    committed = newest_committed_runs(owner, record.project_id, scenarios.records)
    scenario_rows = []
    for scenario in scenarios.records:
        entry = committed.get(scenario.scenario_id, HISTORY_UNAVAILABLE)
        available = entry is not None and entry != HISTORY_UNAVAILABLE
        reason = ""
        if available:
            try:
                validate_entry(entry, project_id=record.project_id, project_code=record.project_code, owner=owner)
                if (entry.last_runtime_scenario_id != scenario.scenario_id
                        and not (scenario.is_base_case and entry.last_runtime_scenario_id is None)):
                    raise InsightsIdentityError("Run scenario binding mismatch.")
            except InsightsIdentityError:
                available, entry = False, HISTORY_UNAVAILABLE
        if not available:
            reason = ("No committed Run exists for this scenario." if entry is None
                      else "Committed Run evidence could not be verified.")
        scenario_rows.append({"scenario_id": scenario.scenario_id, "name": scenario.scenario_name,
                              "is_base_case": bool(scenario.is_base_case),
                              "availability": "available" if available else "not_run" if entry is None else "unavailable",
                              "reason": reason,
                              "committed_run": {"history_id": entry.history_id, "snapshot_id": entry.runtime_snapshot_id,
                                                "scenario_id": entry.last_runtime_scenario_id} if available else None})
    return _validated_json(read_context, {"ok": True, "schema": SCHEMA,
                  "project": {"code": record.project_code, "project_id": record.project_id, "name": record.project_name},
                  "working_copy": {"freshness": freshness}, "max_runs": MAX_RUNS,
                  "history": rows, "history_limit": HISTORY_LIMIT,
                  "history_limit_reached": len(entries) == HISTORY_LIMIT,
                  "scenarios": scenario_rows, "scenarios_complete": scenarios.complete,
                  "scenarios_omitted": scenarios.omitted})


@router.get("/model-react/insights")
async def react_insights(request: Request, project: str = ""):
    context, failure = _context(request, project)
    if failure is not None:
        return failure
    record, owner, ws, read_context = context
    if set(request.query_params) - {"project", "run"} or len(request.query_params.getlist("project")) != 1:
        return _error("INVALID_QUERY", 400)
    requested = request.query_params.getlist("run")
    if (not 1 <= len(requested) <= MAX_RUNS or len(set(requested)) != len(requested)
            or any(not r.strip() or len(r) > 128 or r != r.strip() for r in requested)):
        return _error("EXPLICIT_RUN_SELECTION_REQUIRED", 422, "Select one to three distinct committed Runs explicitly.")
    from app.persistence.run_history_repository import RunHistoryError, get_run_history_entry
    entries = []
    try:
        for history_id in requested:
            entry = get_run_history_entry(owner, record.project_id, history_id)
            if entry is None:
                return _error("RUN_NOT_FOUND", 404)
            validate_entry(entry, project_id=record.project_id, project_code=record.project_code, owner=owner)
            entries.append(entry)
    except (RunHistoryError, InsightsIdentityError):
        return _error("RUN_HISTORY_UNAVAILABLE", 422, "Stored Run evidence could not be verified.")
    freshness, pis = read_context.freshness.state.value, read_context.inputs
    states = {e.history_id: _state(e, ws, freshness) for e in entries}
    from app.v2.credit_decision_projection import LAST_CURRENT
    from app.v2.credit_decision_router import _working_terms
    terms, working = {}, {}
    for entry in entries:
        # Matching snapshot plus canonical CURRENT state is necessary; scenario
        # and composite equality also prevent mutable terms crossing Run bindings.
        if (states[entry.history_id] == LAST_CURRENT and pis is not None
                and entry.last_runtime_scenario_id == getattr(ws, "last_runtime_scenario_id", None)
                and entry.last_runtime_scenario_id == getattr(ws, "active_scenario_id", None)
                and entry.composite_hash == pis.content_hash):
            terms[entry.history_id], working[entry.history_id] = _working_terms(pis, record)
    try:
        payload = build_insights(entries, project_code=record.project_code, project_id=record.project_id,
                                 project_name=record.project_name, states=states, terms=terms, working=working)
    except (InsightsIdentityError, ValueError, TypeError, AttributeError, KeyError):
        return _error("RUN_EVIDENCE_UNAVAILABLE", 422, "Selected committed evidence could not be projected.")
    payload["working_copy"] = {"freshness": freshness}
    return _validated_json(read_context, payload)
