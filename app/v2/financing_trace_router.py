"""Authorized F3.8 read-only fragment, including immutable owned Run History."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.v2.financing_trace_projection import build_financing_trace
from app.v2.financing_sources_uses_projection import FinancingEvidenceInvalid

router = APIRouter()


@router.get("/workbook/financing/trace", response_class=HTMLResponse)
async def financing_trace(request: Request, project: str, history_id: str | None = None):
    from app.v2.router import _get_current_user, _templates
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.run_history_repository import get_run_history, get_run_history_entry, RunHistoryError
    from app.persistence.scenario_insight_reads import resolve_last_run_scenario
    from app.v2.post_run_context import PostRunRequestContext, PostRunContextChanged
    from app.workbook.workbook_identity import WorkbookIdentityError

    user = _get_current_user(request)
    if user is None:
        return HTMLResponse("Authentication required.", status_code=401)
    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return HTMLResponse("Project not found.", status_code=404)
    if history_id is not None and (not history_id.strip() or len(history_id) > 128):
        return HTMLResponse("Run History entry not found.", status_code=404)
    try:
        context = PostRunRequestContext.capture(owner_id=owner, project_id=record.project_id)
        context.require_scope(owner, record.project_id)
        history = get_run_history(owner, record.project_id, limit=12)
        selected = get_run_history_entry(owner, record.project_id, history_id) if history_id is not None else None
        if history_id is not None and (selected is None or selected.user_id != owner or selected.project_id != record.project_id):
            return HTMLResponse("Run History entry not found.", status_code=404)
        ws = context.workspace
        rr = selected if selected else context.runtime_result
        run_id = selected.runtime_snapshot_id if selected else getattr(rr, "snapshot_id", "")
        run_hash = selected.composite_hash if selected else ws.last_runtime_composite_hash
        scenario_id = selected.last_runtime_scenario_id if selected else ws.last_runtime_scenario_id
        scenario = (selected.active_scenario_name if selected else
                    resolve_last_run_scenario(owner, record.project_id, scenario_id).label)
        view = build_financing_trace(runtime_result=rr, freshness=context.freshness.state.value,
            snapshot_id=run_id, composite_hash=run_hash, scenario_id=scenario_id,
            integrity_evidence=selected.integrity_evidence if selected else ws.last_integrity_evidence,
            historical=selected is not None)
        html = _templates.get_template("partials/_financing_trace.html").render(
            trace=view, project_code=record.project_code, run_scenario=scenario or "UNAVAILABLE",
            run_at=getattr(rr, "ran_at", ""), history=history, history_id=history_id)
        context.validate_current()
        return HTMLResponse(html, headers={"Cache-Control": "private, no-store"})
    except (FinancingEvidenceInvalid, RunHistoryError, PostRunContextChanged,
            WorkbookIdentityError, PermissionError, ValueError, TypeError):
        # Like the existing Outputs fragment, deliver an unavailable view, not
        # an HTMX error that leaves the loading message visible indefinitely.
        # Authorization failures above still return 401/404; no numbers survive.
        return HTMLResponse('<p role="status" data-testid="financing-trace-unavailable">UNAVAILABLE: financing evidence is inconsistent or the workspace changed. Reload to refresh.</p>',
                            headers={"Cache-Control": "private, no-store"})
