"""app.v2.credit_decision_router — RC-4 / B Institutional Credit Decision workspace (one focused, READ-ONLY entry point).

``GET /v2/credit-decision?project=<code>&run=<history_id>[&run=...]`` renders credit evidence for one to three COMMITTED Runs of
one project.  It never runs the engine, never writes (there is no POST route and nothing persists), never recalculates a
financial output and never mixes Working Copy data into committed Run evidence.  Authorisation follows the existing analysis
routes: authenticated owner, project isolation (a foreign or unknown Run id fails closed without a partial render) and
protected-reference denial.  Projection logic lives in ``app.v2.credit_decision_projection``.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()

HISTORY_LIMIT = 25
MAX_ID = 128
NO_STORE = {"Cache-Control": "private, no-store"}


def _page(status: int, message: str) -> HTMLResponse:
    return HTMLResponse(content=f"<p role=\"alert\">{message}</p>", status_code=status, headers=NO_STORE)


def _requested_ids(request: Request) -> list[str]:
    raw = list(request.query_params.getlist("run"))
    for chunk in request.query_params.getlist("runs"):
        raw += [part for part in chunk.split(",")]
    ids: list[str] = []
    for item in raw:
        item = item.strip()
        if item and item not in ids:
            ids.append(item)
    return ids


def _working_terms(pis: Any, record: Any) -> tuple[Optional[Any], dict[str, Any]]:
    """Working Copy terms bound to the CURRENT Last Run only (Q3 rule): typed thresholds + the F2 lender view."""
    from app.model_quality.evidence import terms_from_project_inputs
    from app.workbook.bankability_config import SNAPSHOT_KEY, build_view
    try:
        pi = pis.to_projectinputs()
    except Exception:  # noqa: BLE001 - thresholds then stay unavailable
        return None, {}
    terms = terms_from_project_inputs(pi)
    working: dict[str, Any] = {"reserve_regime": terms.reserve_regime}
    try:
        view = build_view(pi, pis.snapshot_origin.get(SNAPSHOT_KEY), project_type=pis.snapshot_origin.get("project_type"))
        if view.get("available"):
            working["lender_case"] = view.get("lender")
            working["sizing_mode"] = view.get("mode")
    except Exception:  # noqa: BLE001
        pass
    return terms, working


def _working_proposal(pis: Any, ws: Any) -> Optional[dict[str, Any]]:
    """Active versus saved-only F3 proposal in the WORKING COPY (never committed Run evidence)."""
    try:
        from app.workbook.multisenior_config import SNAPSHOT_KEY as f3_key, build_view as build_f3_view, scope_for_workspace
        pi = pis.to_projectinputs()
        view = build_f3_view(pi, pis.snapshot_origin.get(f3_key), scope_for_workspace(ws),
                             getattr(ws, "last_runtime_summary", None), owner_id=ws.user_id, project_id=ws.project_id)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(view, dict) or not view.get("available"):
        return {"available": False, "reason": str((view or {}).get("reason") or "Typed financing authority unavailable.")}
    entry = view.get("entry") or {}
    has_proposal = bool(entry.get("proposal"))
    active = bool(view.get("active"))
    return {"available": True, "has_saved_proposal": has_proposal, "active_in_working_copy": active,
            "saved_only": has_proposal and not active, "state": str(view.get("state") or ""),
            "note": "Working Copy status — not committed evidence. A saved proposal changes no Run until it is activated and the model is run."}


@router.get("/credit-decision", response_class=HTMLResponse)
async def credit_decision_page(request: Request, project: Optional[str] = None):
    from app.v2.router import _build_pis_with_composite_identity, _fmt_runtime_at, _get_current_user
    from main_web import templates as _templates      # same template root as the other focused v2 workspaces

    user = _get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    code = (project or "").strip()
    if not code or len(code) > 160:
        return _page(400, "Project required.")
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.run_history_repository import RunHistoryError, get_run_history, get_run_history_entry
    from app.persistence.scenario_insight_reads import resolve_last_run_scenario
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.project_library_service import is_protected_reference
    from app.v2.credit_decision_projection import (
        HISTORICAL, LAST_CURRENT, LAST_STALE, MAX_RUNS, RunInput, build_credit_decision)
    from app.workbook.runtime_authority import resolve_runtime_freshness

    record, owner = resolve_accessible_project(user.user_id, code)
    if record is None:
        return _page(404, "Project not found.")
    if is_protected_reference(record):
        return _page(409, "This is a protected reference model. Create a working copy to review its credit decision evidence.")
    ws = get_workspace_state(user_id=owner, project_id=record.project_id)
    if ws is None:
        return _page(404, "No workspace state.")

    requested = _requested_ids(request)
    if len(requested) > MAX_RUNS:
        return _page(422, f"Select at most {MAX_RUNS} committed Runs.")
    if any(len(r) > MAX_ID for r in requested):
        return _page(400, "Invalid Run id.")
    try:
        history = list(get_run_history(owner, record.project_id, limit=HISTORY_LIMIT))
    except RunHistoryError:
        return _page(422, "RUN_HISTORY_UNAVAILABLE: the stored Run History could not be read.")

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
            return _page(422, f"RUN_HISTORY_PAYLOAD_MALFORMED: {exc}")
        if entry is None:                          # unknown or foreign id — fail closed, nothing partially rendered
            return _page(404, "Run history entry not found.")
        selected.append(entry)

    pis = _build_pis_with_composite_identity(ws, record, owner)
    content_hash = getattr(pis, "content_hash", "") or ""
    try:
        freshness = resolve_runtime_freshness(ws, current_composite_hash=content_hash).state.value
    except Exception:  # noqa: BLE001
        freshness = "UNKNOWN"
    labels: dict[Any, Optional[str]] = {}

    def label(scenario_id: Optional[str]) -> Optional[str]:
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
    rows = [{"history_id": e.history_id, "ran_at": (_fmt_runtime_at(e.ran_at) or str(e.ran_at or "")[:16].replace("T", " ")), "scenario": label(e.last_runtime_scenario_id) or "UNAVAILABLE",
             "engine": e.engine_version or "—", "is_last": bool(last_snapshot) and e.runtime_snapshot_id == last_snapshot,
             "selected": e.history_id in requested} for e in history]
    ctx = {"project_code": record.project_code, "project_name": record.project_name, "data": data, "history_rows": rows,
           "requested": requested, "max_runs": MAX_RUNS, "freshness": freshness, "user": user}
    return _templates.TemplateResponse(request=request, name="v2/credit_decision.html", context=ctx, headers=NO_STORE)
