"""PR-U2b — read-only OPEX year projection per saved line (React Inputs > OPEX > Years).

No arithmetic of its own. The values are the SAME ``OpexViewModel`` the existing group projection (``react_opex_projection``) and the Legacy OPEX
sheet are built from (``app.v2.router._build_opex_vm_ctx`` over the saved Working Copy): each line's ``year_values`` (Y1 amount escalated by that
line's own inflation) and each group's ``year_rows``, passed through unchanged.

Lineage, so nothing is shown as a saved item that is not one:
* ``lines``   — rows that carry a saved ``sub_line_id`` (reference-seeded or user-added, active only, exactly as the projection folds them);
* ``drivers`` — rows computed from technology drivers (e.g. Data Center power expenses): read-only, labelled as such;
* catalogue placeholder rows (no saved record, zero) are NOT listed; their count is reported.
The six OPEX group base scalars are listed separately (``bases``, Year 1 only, with whether the Run adds them): the yearly rows here do not include
them and nothing here is an all-in OPEX figure. ``reconciles`` states, per group, whether lines + drivers equal the group row for every year.

``GET /model-react/opex-projection/lines?project=CODE`` — requires the React feature flag and a session; protected and shared projects are readable.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import resolve_request_session
from app.v2.react_poc_router import react_poc_enabled

router = APIRouter()

_TOLERANCE_KEUR = 1e-9


def _json(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "private, no-store"})


def _series(values, years: int) -> list[Optional[float]]:
    out: list[Optional[float]] = []
    for v in list(values)[:years]:
        out.append(None if v is None or not math.isfinite(float(v)) else float(v))
    return out + [None] * (years - len(out))


def _reconciles(group_values: list[Optional[float]], parts: list[list[Optional[float]]]) -> Optional[bool]:
    if any(v is None for v in group_values):
        return None
    for t, g in enumerate(group_values):
        if any(p[t] is None for p in parts):
            return None
        if abs(sum(p[t] for p in parts) - g) > max(_TOLERANCE_KEUR, 1e-12 * abs(g)):
            return False
    return True


def build_line_projection(record, ws, owner: str) -> dict[str, Any]:
    from app.cost_line_ledger.opex_bases import opex_bases
    from app.ui.protected_reference_service import is_protected_reference
    from app.v2.opex_authority import opex_group_authority_notes
    from app.v2.router import _build_opex_vm_ctx
    from app.workbook.service import WorkbookService

    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    ctx = _build_opex_vm_ctx(record, pis, ws=ws, workspace_owner=owner)
    vm, sheet = ctx["opex_vm"], ctx["opex_sheet_groups"]
    years = int(vm.display_years)
    vm_groups = {g.code: g for g in vm.groups}
    groups = []
    for g in sheet:
        values = _series(g.year_rows, years) if g.has_vm_data else [None] * years
        lines, drivers, placeholders = [], [], 0
        for ln in (vm_groups[g.code].lines if g.code in vm_groups else ()):
            if ln.is_contingency or not ln.is_active:
                continue
            row_values = _series(ln.year_values, years)
            if ln.sub_line_id:
                lines.append({"sub_line_id": ln.sub_line_id, "label": ln.name, "y1_keur": float(ln.y1_keur), "inflation_pct": float(ln.inflation_pct),
                              "values": row_values, "source": "saved_line"})
            elif any(v for v in row_values if v is not None):
                drivers.append({"label": ln.name, "values": row_values, "source": "technology_driver"})
            else:
                placeholders += 1
        derived = bool(g.is_derived)
        groups.append({"code": g.code, "name": g.display_name, "derived": derived, "has_data": bool(g.has_vm_data), "values": values,
                       "lines": lines, "drivers": drivers, "placeholder_rows_not_listed": placeholders,
                       "reconciles": None if derived else _reconciles(values, [r["values"] for r in lines + drivers])})
    notes = opex_group_authority_notes(record.project_id, getattr(record, "template_source", "") or "")
    bases = opex_bases(pis.get, notes, protected=bool(is_protected_reference(record)))
    return {
        "ok": True, "project": {"code": record.project_code}, "unit": "kEUR", "years": list(range(1, years + 1)), "groups": groups,
        "contingency": {"rate_pct": float(vm.contingency_rate), "by_year": _series(vm.contingency_by_year, years)},
        "totals": {"excluding_contingency": _series(vm.total_excl_contingency, years), "including_contingency": _series(vm.total_incl_contingency, years)},
        "bases": bases,
        "basis": ("Saved working inputs, not a Run result. Rows are the saved OPEX lines (Year 1 amount escalated by each line's own inflation) and "
                  "technology-driven rows. The six group base amounts are listed separately with Year 1 only: the Run adds them, these yearly rows do not."),
    }


@router.get("/model-react/opex-projection/lines")
async def react_opex_line_projection(request: Request, project: str = ""):
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
        payload = build_line_projection(record, ws, owner)
    except Exception:  # noqa: BLE001 - fail closed; never fabricate a projection
        return _json({"ok": False, "code": "OPEX_LINE_PROJECTION_UNAVAILABLE", "message": "The OPEX line projection could not be built. Reload to try again."}, 503)
    return _json(payload)
