"""RC-UX (Audit A GAP-R12) — read-only JSON adapter for the React "Covenant headroom" section of the Credit decision panel.

The Legacy ``GET /v2/credit-decision/v5?format=json`` analysis (``app.services.credit_v5.analyze_runs``) over one to three COMMITTED Runs and
HYPOTHETICAL lender thresholds supplied by the user.  Nothing is solved, written or run; the thresholds are never persisted and never imply
contractual compliance.  Authorisation mirrors the Legacy route: authenticated owner, project isolation, protected-reference denial and a
fail-closed 404 for an unknown or foreign Run id.

* ``GET /model-react/analysis/credit-headroom?project=<code>[&run=<history_id>…][&min_dscr=…&min_llcr=…&max_gearing=…&min_equity_keur=…&max_balloon_keur=…]``

Feature flag: ``FINCO_MODEL_REACT_V1``.
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Request

from app.v2.react_projects import _gate, _json

router = APIRouter()


@router.get("/model-react/analysis/credit-headroom")
async def react_credit_headroom(request: Request, project: str = ""):
    user, refused = _gate(request)
    if refused is not None:
        return refused
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.run_history_repository import RunHistoryError, get_run_history, get_run_history_entry
    from app.services.credit_v5 import METRICS, Constraint, analyze_runs
    from app.services.project_library_service import is_protected_reference
    from app.v2.react_workspace_router import _jsonable

    code = project.strip()
    if not code or len(code) > 160:
        return _json({"ok": False, "code": "PROJECT_REQUIRED"}, 400)
    record, owner = resolve_accessible_project(user.user_id, code)
    if record is None:
        return _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    if is_protected_reference(record):
        return _json({"ok": False, "code": "PROTECTED_REFERENCE", "message": "Templates are read-only. Start a project from this template to review its credit evidence."}, 409)
    ids = request.query_params.getlist("run")
    if len(ids) > 3 or len(set(ids)) != len(ids) or any(not r.strip() or len(r) > 128 for r in ids):
        return _json({"ok": False, "code": "RUN_SELECTION_INVALID", "message": "Select between one and three distinct committed Runs."}, 422)
    constraints = []
    try:
        for metric in METRICS:
            values = request.query_params.getlist(metric)
            if len(values) > 1:
                return _json({"ok": False, "code": "DUPLICATE_THRESHOLD"}, 422)
            raw = values[0] if values else ""
            constraints.append(Constraint(metric, float(raw) if raw.strip() else None))
    except (ValueError, OverflowError) as exc:
        message = "A gearing threshold is a fraction between 0 and 1." if "GEARING" in str(exc) else "Enter each threshold as a positive number."
        return _json({"ok": False, "code": "THRESHOLD_INVALID", "message": message}, 422)
    try:
        history = list(get_run_history(owner, record.project_id, limit=25))
        requested = ids or ([history[0].history_id] if history else [])
        selected = []
        for history_id in requested:
            entry = get_run_history_entry(owner, record.project_id, history_id)
            if entry is None:
                return _json({"ok": False, "code": "RUN_NOT_FOUND"}, 404)
            selected.append(entry)
        data = asdict(analyze_runs(selected, constraints, owner_id=owner, project_id=record.project_id, project_code=record.project_code)) if selected else None
    except (RunHistoryError, ValueError, TypeError, KeyError):
        return _json({"ok": False, "code": "COMMITTED_EVIDENCE_INVALID", "message": "The saved Run evidence could not be evaluated. Nothing is estimated."}, 422)
    return _json({"ok": True, "state": "AVAILABLE" if data else "NO_COMMITTED_RUN", "requested": requested,
                  "thresholds": {c.metric: c.threshold for c in constraints}, "data": _jsonable(data) if data is not None else None})
