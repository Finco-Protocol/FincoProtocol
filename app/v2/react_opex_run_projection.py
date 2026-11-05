"""G10 Option A (Draft) — read-only Last-Run all-in OPEX per financial period, from the committed immutable Run.

No arithmetic of its own. The per-period values are the engine's own ``operating_expenses_keur``
cells from the committed Run's serialized P&L (``model_run_history.financial_statements.pnl.periods``),
written inside the canonical ``v2_atomic_run_commit`` transaction and never updated afterwards. This
endpoint reads that evidence back and adds identity/freshness labels only:

* ``run``               — history id, ran_at, engine/workbook version, scenario id/name, runtime snapshot id;
* ``freshness``         — ``resolve_runtime_freshness`` over the current workspace (CURRENT / STALE / NOT_RUN);
* ``periods``           — ``[{period, date, operating_expenses_keur}]`` exactly as persisted (null when the
                          engine recorded no value for that cell — never zero-invented, never re-summed);
* ``basis``             — what the figure is (Run economics: all-in per financial period — construction
                          periods 0.0, partial operating years prorated by the engine's ``day_fraction``);
                          explicitly NOT the draft/working-copy projection and NOT a calendar-year sum.

There is deliberately no draft projection here (that is ``react_opex_projection``) and no escalation
editor (that is U2's per-line ``react_opex_lines``). Missing Run ⇒ ``run: null`` + ``status: "NOT_RUN"``
(never zeros). Missing P&L in an existing row ⇒ ``status: "OPLEX_STATEMENT_UNAVAILABLE"`` typed, fail closed.

``GET /model-react/opex-run-projection?project=CODE`` — read-only GET; feature flag + session required;
protected and shared projects readable (the same rule as the other OPEX read adapters).
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import resolve_request_session
from app.v2.react_poc_router import react_poc_enabled
from app.utils.workbook_flag import env_flag

router = APIRouter()


def g10_run_projection_enabled() -> bool:
    """Dedicated G10 gate: absent/empty -> OFF. The React surface flag alone does NOT authorize this panel —
    owner ratification of G10 Option A is a separate, still-pending decision, so the panel ships dark until
    ``FINCO_G10_RUN_OPEX_PANEL`` is explicitly set."""
    return env_flag("FINCO_G10_RUN_OPEX_PANEL", default=False)


def _json(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "private, no-store"})


def _finite(value: Any) -> Optional[float]:
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def build_run_opex_projection(record, ws, owner: str) -> dict[str, Any]:
    """Read the committed Run's all-in OPEX periods plus identity/freshness labels. Fail-closed."""
    from app.persistence.run_history_repository import get_latest_history_entry
    from app.workbook.runtime_authority import resolve_runtime_freshness
    from app.workbook.workbook_identity import assemble_consistent_for_get

    entry = get_latest_history_entry(ws.user_id, record.project_id)
    if entry is None:
        return {
            "ok": True, "project": {"code": record.project_code}, "unit": "kEUR",
            "status": "NOT_RUN", "run": None, "periods": [], "years": [], "freshness": {"state": "NOT_RUN"},
            "basis": ("No committed Run exists for this project yet. Last-Run OPEX is shown only from a "
                      "committed immutable Run; no estimate is invented from the working copy."),
        }

    from app.workbook.registry import WORKBOOK
    try:
        current_hash = assemble_consistent_for_get(owner, record.project_id, WORKBOOK.version).composite_hash
    except Exception:  # noqa: BLE001 - freshness unavailable is shown, never guessed
        current_hash = None
    fresh = resolve_runtime_freshness(ws, current_composite_hash=current_hash)
    freshness = {"state": str(fresh.state.value) if hasattr(fresh.state, "value") else str(fresh.state)}

    pnl = (entry.financial_statements or {}).get("pnl") if isinstance(entry.financial_statements, dict) else None
    periods_raw = pnl.get("periods") if isinstance(pnl, dict) else None
    if not isinstance(periods_raw, list) or not periods_raw:
        return {
            "ok": True, "project": {"code": record.project_code}, "unit": "kEUR",
            "status": "OPEX_STATEMENT_UNAVAILABLE", "run": _run_identity(entry), "periods": [], "years": [],
            "freshness": freshness,
            "basis": ("The committed Run's evidence does not carry a P&L with operating-expense periods; "
                      "the figure is NOT_AVAILABLE rather than zero."),
        }

    periods = []
    for p in periods_raw:
        if not isinstance(p, dict):
            continue
        periods.append({
            "period": p.get("period"),
            "date": p.get("date"),
            "operating_expenses_keur": _finite(p.get("operating_expenses_keur")),
        })
    return {
        "ok": True, "project": {"code": record.project_code}, "unit": "kEUR",
        "status": "OK", "run": _run_identity(entry), "freshness": freshness,
        "years": [p["period"] for p in periods],
        "periods": periods,
        "basis": ("Committed Run economics: the engine's all-in operating expenses per financial period "
                  "(construction periods are 0.0; partial operating years are prorated by the engine). "
                  "This is the immutable Run's own P&L evidence — not the draft projection, not a "
                  "calendar-year sum, and not an editor preview."),
    }


def _run_identity(entry) -> dict[str, Any]:
    return {
        "history_id": entry.history_id,
        "ran_at": entry.ran_at,
        "engine_version": entry.engine_version,
        "workbook_version": entry.workbook_version,
        "scenario_id": entry.active_scenario_id,
        "scenario_name": entry.active_scenario_name,
        "runtime_snapshot_id": entry.runtime_snapshot_id,
    }


@router.get("/model-react/opex-run-projection")
async def react_opex_run_projection(request: Request, project: str = ""):
    if not g10_run_projection_enabled():
        return _json({"ok": False, "code": "G10_RUN_OPEX_PANEL_DISABLED"}, 404)
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user = resolve_request_session(request)
    if user is None:
        return _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state

    record, owner = resolve_accessible_project(user.user_id, (project or "").strip())
    if record is None:
        return _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    ws = get_workspace_state(owner, record.project_id)
    if ws is None:
        return _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    try:
        payload = build_run_opex_projection(record, ws, owner)
    except Exception:  # noqa: BLE001 - fail closed; never fabricate Run evidence
        return _json({"ok": False, "code": "OPEX_RUN_PROJECTION_UNAVAILABLE", "message": "The Last-Run OPEX projection could not be built. Reload to try again."}, 503)
    return _json(payload)
