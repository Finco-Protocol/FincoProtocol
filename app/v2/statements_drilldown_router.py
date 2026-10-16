"""Isolated read-only route: Statements V2 drill-down for one immutable Run History entry.

Registered in ``app/v2/router.py`` (``router.include_router(statements_drilldown_router)``); the Run History detail page links here only
while this route is mounted.  The Last Run drill-down needs no route of its own: it is rendered by ``/workbook/outputs``.

Failure responses are fixed generic texts: exception messages, persisted payloads and identifiers are never echoed into HTML or logs.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()
_log = logging.getLogger(__name__)


def _page(status: int, message: str) -> HTMLResponse:
    return HTMLResponse(content=f"<p role=\"alert\">{message}</p>", status_code=status, headers={"Cache-Control": "private"})


@router.get("/workbook/run-history/statements", response_class=HTMLResponse)
async def run_history_statements(request: Request, project: Optional[str] = None, history_id: Optional[str] = None):
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.run_history_repository import RunHistoryError, get_run_history_entry
    from app.persistence.scenario_insight_reads import resolve_last_run_scenario
    from app.persistence.workspace_repository import get_workspace_state
    from app.v2.historical_statements import build_historical_statements
    from app.v2.router import _build_pis_with_composite_identity, _get_current_user, _templates

    user = _get_current_user(request)
    if user is None:
        return _page(401, "Unauthenticated.")
    code = (project or "").strip()
    if not code or not (history_id or "").strip() or len(code) > 160 or len(history_id) > 128:
        return _page(400, "Project and history_id required.")
    record, owner = resolve_accessible_project(user.user_id, code)
    if record is None:
        return _page(404, "Project not found.")
    try:
        entry = get_run_history_entry(owner, record.project_id, history_id)
    except RunHistoryError:
        _log.warning("run history statements: malformed stored entry (details withheld)")
        return _page(422, "This Run's stored evidence is malformed and cannot be displayed.")
    if entry is None:
        return _page(404, "Run history entry not found.")
    current_hash = None
    try:
        ws = get_workspace_state(user_id=owner, project_id=record.project_id)
        if ws is not None:
            current_hash = _build_pis_with_composite_identity(ws, record, owner).content_hash
    except Exception:  # noqa: BLE001 - freshness label degrades to "not evaluated", never to a guess
        current_hash = None
    label = None
    try:
        label = resolve_last_run_scenario(owner, record.project_id, getattr(entry, "last_runtime_scenario_id", None)).label
    except Exception:  # noqa: BLE001
        label = None
    try:
        statements = build_historical_statements(entry, current_composite_hash=current_hash, scenario_label=label)
        html = _templates.get_template("partials/run_history_statements.html").render(
            statements=statements, project_code=record.project_code)
    except Exception as exc:  # noqa: BLE001 - fail closed on malformed persisted evidence; never echo it
        _log.warning("run history statements: projection failed (%s; details withheld)", type(exc).__name__)
        return _page(422, "This Run's stored evidence could not be projected. Nothing is estimated.")
    return HTMLResponse(html, headers={"Cache-Control": "private"})
