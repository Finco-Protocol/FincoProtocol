"""RC-UX (Audit A GAP-R16) — read-only JSON adapter for the OPEX year projection (Y1 .. Yn) shown in React Inputs > Studios.

No arithmetic of its own: the rows are the SAME ``OpexViewModel`` / ``OpexSheetGroup`` projection the Legacy OPEX sheet renders
(``app.v2.router._build_opex_vm_ctx`` over the saved Working Copy: per-line amounts, per-line escalation, applied contingency), passed through
unchanged.  A year a group has no value for is ``null`` — never zero.

* ``GET /model-react/opex-projection?project=CODE`` — groups × years, the contingency and total rows, the Y1 KPIs and the escalation basis.

Read-only (GET), requires the feature flag and a session; shared and protected projects are readable (the same as the Legacy sheet).
Feature flag: ``FINCO_MODEL_REACT_V1``.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import resolve_request_session
from app.v2.react_poc_router import react_poc_enabled

router = APIRouter()


def _json(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "private, no-store"})


def _series(values, years: int) -> list[Optional[float]]:
    """The server's per-year values padded with ``None`` (unavailable) up to the displayed years."""
    out: list[Optional[float]] = [None if v is None else float(v) for v in list(values)[:years]]
    return out + [None] * (years - len(out))


@router.get("/model-react/opex-projection")
async def react_opex_projection(request: Request, project: str = ""):
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
        from app.v2.router import _build_opex_vm_ctx
        from app.workbook.service import WorkbookService

        pis = WorkbookService.build_draft_input_set_from_workspace(ws)
        ctx = _build_opex_vm_ctx(record, pis, ws=ws, workspace_owner=owner)
        vm, groups = ctx["opex_vm"], ctx["opex_sheet_groups"]
        years = int(vm.display_years)
        rows = [{"code": g.code, "name": g.display_name, "derived": bool(g.is_derived), "has_data": bool(g.has_vm_data),
                 "escalation": g.escalation_display, "values": _series(g.year_rows, years) if g.has_vm_data else [None] * years}
                for g in groups]
        escalation = ctx.get("opex_escalation_summary") or {}
        payload = {
            "ok": True, "project": {"code": record.project_code, "protected_reference": bool(getattr(record, "is_protected", False))},
            "unit": "kEUR", "years": list(range(1, years + 1)), "rows": rows,
            "contingency": {"rate_pct": float(vm.contingency_rate), "by_year": _series(vm.contingency_by_year, years)},
            "totals": {"excluding_contingency": _series(vm.total_excl_contingency, years), "including_contingency": _series(vm.total_incl_contingency, years)},
            "kpis": {"year1_total_keur": vm.y1_total_opex, "final_year_total_keur": vm.final_year_total_opex,
                     "per_mw_year1_keur": vm.opex_per_mw_y1, "per_mwh_year1_eur": vm.opex_per_mwh_y1},
            "escalation": {"value": escalation.get("value"), "label": escalation.get("label")},
            "basis": "The saved project: its OPEX lines, each line's escalation and the applied contingency. Not a Run result.",
        }
    except Exception:  # noqa: BLE001 - fail closed; never fabricate a projection
        return _json({"ok": False, "code": "OPEX_PROJECTION_UNAVAILABLE", "message": "The OPEX projection could not be built. Reload to try again."}, 503)
    return _json(payload)
