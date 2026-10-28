"""RC-UX (Addendum A, R-HIST-STATEMENTS) — read-only JSON adapter for the statements of ONE earlier committed Run.

The same payload the Legacy ``/v2/workbook/run-history/statements`` page renders (``app.v2.historical_statements.build_historical_statements`` over
the immutable Run History entry), as JSON, so the React Model can present an earlier Run's financial statements without leaving React.  Every value
and identity comes from the history entry that Run committed; the current inputs are consulted for exactly one thing — whether they still match
the Run's input fingerprint.  It never runs the engine, never writes, never recalculates a line and never substitutes current inputs.

* ``GET /model-react/analysis/run-statements?project=<code>&history_id=<id>``

Feature flag: ``FINCO_MODEL_REACT_V1``.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from app.v2.react_projects import _gate, _json

router = APIRouter()
log = logging.getLogger(__name__)


@router.get("/model-react/analysis/run-statements")
async def react_run_statements(request: Request, project: str = "", history_id: str = ""):
    user, refused = _gate(request)
    if refused is not None:
        return refused
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.run_history_repository import RunHistoryError, get_run_history_entry
    from app.persistence.scenario_insight_reads import resolve_last_run_scenario
    from app.persistence.workspace_repository import get_workspace_state
    from app.v2.historical_statements import build_historical_statements
    from app.v2.react_workspace_router import _jsonable
    from app.v2.router import _build_pis_with_composite_identity

    code, run_id = project.strip(), history_id.strip()
    if not code or not run_id or len(code) > 160 or len(run_id) > 128:
        return _json({"ok": False, "code": "PROJECT_AND_RUN_REQUIRED"}, 400)
    record, owner = resolve_accessible_project(user.user_id, code)
    if record is None:
        return _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    try:
        entry = get_run_history_entry(owner, record.project_id, run_id)
    except RunHistoryError:
        log.warning("react_run_statements: malformed stored entry (details withheld)")
        return _json({"ok": False, "code": "RUN_EVIDENCE_MALFORMED", "message": "This Run's stored evidence is malformed and cannot be displayed."}, 422)
    if entry is None:
        return _json({"ok": False, "code": "RUN_NOT_FOUND"}, 404)
    current_hash = None
    try:
        ws = get_workspace_state(user_id=owner, project_id=record.project_id)
        if ws is not None:
            current_hash = _build_pis_with_composite_identity(ws, record, owner).content_hash
    except Exception:  # noqa: BLE001 - the input-match label degrades to "not evaluated", never to a guess
        current_hash = None
    try:
        label = resolve_last_run_scenario(owner, record.project_id, getattr(entry, "last_runtime_scenario_id", None)).label
    except Exception:  # noqa: BLE001
        label = None
    try:
        statements = build_historical_statements(entry, current_composite_hash=current_hash, scenario_label=label)
    except Exception as exc:  # noqa: BLE001 - fail closed on malformed persisted evidence; never echo it
        log.warning("react_run_statements: projection failed (%s; details withheld)", type(exc).__name__)
        return _json({"ok": False, "code": "RUN_EVIDENCE_UNPROJECTABLE", "message": "This Run's stored evidence could not be projected. Nothing is estimated."}, 422)
    return _json({"ok": True, "project": {"code": record.project_code}, "statements": _jsonable(statements)})
