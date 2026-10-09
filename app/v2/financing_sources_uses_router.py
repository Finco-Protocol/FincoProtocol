"""F1 isolated read-only financing workspace route.

All Last Run and Working Copy inputs are captured by the existing authorized
PostRunRequestContext. Historical selection is scoped by canonical Run History
repository to the same owner/project. Never executes the engine or writes inputs.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.v2.financing_sources_uses_projection import (
    FinancingEvidenceInvalid, build_sources_uses_projection,
)

router = APIRouter()
_log = logging.getLogger(__name__)


def _unavailable(status: int, message: str) -> HTMLResponse:
    return HTMLResponse(content=f"<p>{message}</p>", status_code=status,
                        headers={"Cache-Control": "no-store"})


@router.get("/financing/sources-uses", response_class=HTMLResponse)
async def financing_sources_uses_page(
    request: Request, project: Optional[str] = None, history_id: Optional[str] = None,
):
    from app.v2.router import _get_current_user
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.run_history_repository import (
        RunHistoryError, get_run_history, get_run_history_entry,
    )
    from app.v2.post_run_context import PostRunContextChanged, PostRunRequestContext
    from app.workbook.service import WorkbookService

    user = _get_current_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=302)
    project_code = (project or "").strip()
    if not project_code or len(project_code) > 160:
        return _unavailable(404, "Project not found.")
    record, owner_id = resolve_accessible_project(user.user_id, project_code)
    if record is None:
        return _unavailable(404, "Project not found.")

    if history_id is not None and (not history_id.strip() or len(history_id) > 128):
        return _unavailable(404, "Run History entry not found.")

    try:
        snapshot = PostRunRequestContext.capture(
            owner_id=owner_id, project_id=record.project_id)
        snapshot.require_scope(owner_id, record.project_id)
        history = get_run_history(owner_id, record.project_id, limit=12)
        selected = None
        if history_id is not None:
            selected = get_run_history_entry(owner_id, record.project_id, history_id)
            if selected is None:
                return _unavailable(404, "Run History entry not found.")
            if selected.user_id != owner_id or selected.project_id != record.project_id:
                return _unavailable(404, "Run History entry not found.")
            rr = selected
            integrity = selected.integrity_evidence
            state = "STALE"  # Never treat historical evidence as current assumptions.
            kind = "HISTORICAL_RUN"
            run_at = selected.ran_at
            run_id = selected.runtime_snapshot_id
            run_scenario = selected.active_scenario_name or "Not persisted"
        else:
            rr = snapshot.runtime_result
            integrity = snapshot.workspace.last_integrity_evidence
            state = snapshot.freshness.state.value
            kind = "LAST_RUN"
            run_at = (rr.ran_at if rr is not None else "")
            run_id = (rr.snapshot_id if rr is not None else "")
            prior_scenario = snapshot.workspace.last_runtime_identity or {}
            run_scenario = prior_scenario.get("scenario_name") or "Not persisted"

        fin, capex = None, None
        if selected is None:
            # Current typed inputs are displayed separately, never used to fill Run values.
            try:
                pi = WorkbookService.to_projectinputs(snapshot.inputs)
                fin, capex = pi.financing, pi.capex
            except (ValueError, TypeError, AttributeError):
                _log.warning("F1 Working Copy financing bridge unavailable for project")
        view = build_sources_uses_projection(
            runtime_result=rr, integrity_evidence=integrity,
            working_financing=fin, working_capex=capex,
            freshness=state, run_kind=kind,
        )
        from main_web import templates
        response = templates.TemplateResponse(
            request=request, name="v2/financing_sources_uses.html",
            context={
                "user": user,
                "project_code": record.project_code,
                "project_name": record.project_name,
                "view": view,
                "history": history,
                "history_id": history_id,
                "run_at": run_at,
                "run_id": run_id,
                "run_scenario": run_scenario,
                "active_scenario": snapshot.workspace.active_scenario_name or "Base",
                "is_historical": selected is not None,
            },
        )
        snapshot.validate_current()
        response.headers["Cache-Control"] = "private, no-store"
        return response
    except (FinancingEvidenceInvalid, RunHistoryError, PostRunContextChanged,
            ValueError, TypeError, PermissionError) as exc:
        _log.warning("F1 financing snapshot rejected: %s", type(exc).__name__)
        return _unavailable(409, "Financing evidence is unavailable or changed. Reload the project.")
