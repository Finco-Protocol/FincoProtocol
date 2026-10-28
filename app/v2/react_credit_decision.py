"""RC-UX (Audit A GAP-R12) — read-only JSON adapter for the React "Credit decision" panel.

The Institutional Credit Decision evidence of one to three COMMITTED Runs of a project: the same payload the Legacy ``/v2/credit-decision`` page
renders (``app.v2.credit_decision_projection.build_credit_decision`` over ``RunInput`` built exactly as ``credit_decision_router`` builds them), as
JSON.  It never runs the engine, never writes, never recalculates a financial output and never mixes Working Copy data into committed Run evidence;
a figure a Run did not persist stays unavailable with its reason.  Authorisation follows the Legacy route: authenticated owner, project isolation
(an unknown or foreign Run id fails closed without a partial payload) and protected-reference denial.

* ``GET /model-react/analysis/credit-decision?project=<code>[&run=<history_id>…]`` — the projection plus the picker rows.  Without ``run`` the
  Last Run (or the newest committed Run) is used, as in Legacy.

Feature flag: ``FINCO_MODEL_REACT_V1``.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request

from app.v2.react_projects import _gate, _json

router = APIRouter()
log = logging.getLogger(__name__)


@router.get("/model-react/analysis/credit-decision")
async def react_credit_decision(request: Request, project: str = ""):
    user, refused = _gate(request)
    if refused is not None:
        return refused
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.run_history_repository import RunHistoryError, get_run_history, get_run_history_entry
    from app.persistence.scenario_insight_reads import resolve_last_run_scenario
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.project_library_service import is_protected_reference
    from app.v2.credit_decision_projection import HISTORICAL, LAST_CURRENT, LAST_STALE, MAX_RUNS, RunInput, build_credit_decision
    from app.v2.credit_decision_router import HISTORY_LIMIT, MAX_ID, _requested_ids, _working_proposal, _working_terms
    from app.v2.react_workspace_router import _jsonable
    from app.v2.router import _build_pis_with_composite_identity, _fmt_runtime_at
    from app.workbook.runtime_authority import resolve_runtime_freshness

    code = project.strip()
    if not code or len(code) > 160:
        return _json({"ok": False, "code": "PROJECT_REQUIRED"}, 400)
    record, owner = resolve_accessible_project(user.user_id, code)
    if record is None:
        return _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    if is_protected_reference(record):
        return _json({"ok": False, "code": "PROTECTED_REFERENCE",
                      "message": "Templates are read-only. Start a project from this template to review its credit evidence."}, 409)
    ws = get_workspace_state(user_id=owner, project_id=record.project_id)
    if ws is None:
        return _json({"ok": False, "code": "NO_WORKSPACE"}, 404)
    requested = _requested_ids(request)
    if len(requested) > MAX_RUNS:
        return _json({"ok": False, "code": "TOO_MANY_RUNS", "message": f"Select at most {MAX_RUNS} committed Runs."}, 422)
    if any(len(r) > MAX_ID for r in requested):
        return _json({"ok": False, "code": "INVALID_RUN_ID"}, 400)
    try:
        history = list(get_run_history(owner, record.project_id, limit=HISTORY_LIMIT))
    except RunHistoryError:
        return _json({"ok": False, "code": "RUN_HISTORY_UNAVAILABLE", "message": "The stored Run History could not be read."}, 422)

    last_snapshot = str(getattr(ws, "last_runtime_snapshot_id", "") or "")
    last_entry = next((e for e in history if last_snapshot and e.runtime_snapshot_id == last_snapshot), None)
    if not requested:
        default = last_entry or (history[0] if history else None)
        requested = [default.history_id] if default is not None else []
    selected = []
    for history_id in requested:
        try:
            entry = get_run_history_entry(owner, record.project_id, history_id)
        except RunHistoryError as exc:
            return _json({"ok": False, "code": "RUN_HISTORY_PAYLOAD_MALFORMED", "message": str(exc)}, 422)
        if entry is None:                            # unknown or foreign id — fail closed, nothing partially returned
            return _json({"ok": False, "code": "RUN_NOT_FOUND"}, 404)
        selected.append(entry)
    try:
        pis = _build_pis_with_composite_identity(ws, record, owner)
        try:
            freshness = resolve_runtime_freshness(ws, current_composite_hash=getattr(pis, "content_hash", "") or "").state.value
        except Exception:  # noqa: BLE001 - an unreadable freshness is UNKNOWN, never CURRENT
            freshness = "UNKNOWN"
        labels: dict[Any, Any] = {}

        def label(scenario_id):
            if scenario_id not in labels:
                labels[scenario_id] = resolve_last_run_scenario(owner, record.project_id, scenario_id).label
            return labels[scenario_id]

        inputs = []
        for entry in selected:
            is_last = bool(last_snapshot) and entry.runtime_snapshot_id == last_snapshot
            state = (LAST_CURRENT if freshness == "CURRENT" else LAST_STALE if freshness == "STALE" else HISTORICAL) if is_last else HISTORICAL
            terms, working = (None, {})
            if state == LAST_CURRENT:
                terms, working = _working_terms(pis, record)
            inputs.append(RunInput(entry=entry, state=state, scenario_label=label(entry.last_runtime_scenario_id), terms=terms, working=working or None))
        data = build_credit_decision(inputs, project_code=record.project_code, working_proposal=_working_proposal(pis, ws)) if inputs else None
        rows = [{"history_id": e.history_id, "ran_at": (_fmt_runtime_at(e.ran_at) or str(e.ran_at or "")[:16].replace("T", " ")),
                 "scenario": label(e.last_runtime_scenario_id) or "UNAVAILABLE", "engine": e.engine_version or "—",
                 "is_last": bool(last_snapshot) and e.runtime_snapshot_id == last_snapshot, "selected": e.history_id in requested} for e in history]
    except Exception:  # noqa: BLE001 - fail closed; the Legacy page stays authoritative
        log.exception("react_credit_decision: projection failed project=%s", code)
        return _json({"ok": False, "code": "CREDIT_UNAVAILABLE", "message": "The credit evidence could not be projected. Nothing was changed."}, 503)
    return _json({"ok": True, "project": {"code": record.project_code, "name": record.project_name}, "freshness": freshness,
                  "requested": requested, "max_runs": MAX_RUNS, "history_rows": rows, "data": _jsonable(data) if data is not None else None})
