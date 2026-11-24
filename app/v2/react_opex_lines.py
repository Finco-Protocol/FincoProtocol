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


def build_line_projection(record, ws, owner: str, *, request: Optional[Request] = None, actor_user_id: Optional[str] = None) -> dict[str, Any]:
    from app.cost_line_ledger.opex_bases import opex_bases
    from app.opex_annual_exceptions import (
        document_token as opex_ann_token,
        effective_raw as opex_ann_effective_raw,
        parse_exceptions as parse_opex_ann,
    )
    from app.persistence.scenarios_repository import get_scenario
    from app.ui.protected_reference_service import is_protected_reference
    from app.v2.opex_authority import opex_group_authority_notes
    from app.v2.router import _build_opex_vm_ctx
    from app.workbook.service import WorkbookService
    from app.workbook.workbook_identity import assemble_consistent_for_get

    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    ctx = _build_opex_vm_ctx(record, pis, ws=ws, workspace_owner=owner)
    vm, sheet = ctx["opex_vm"], ctx["opex_sheet_groups"]
    years = int(vm.display_years)
    vm_groups = {g.code: g for g in vm.groups}

    active_sc = get_scenario(ws.active_scenario_id) if ws.active_scenario_id else None
    raw_ann = opex_ann_effective_raw(ws.draft_snapshot, active_sc)
    ann_map = parse_opex_ann(raw_ann) if raw_ann else {}
    has_overrides = bool(ann_map)

    groups = []
    fixed_totals = [0.0] * years
    for g in sheet:
        values = _series(g.year_rows, years) if g.has_vm_data else [None] * years
        lines, drivers, placeholders = [], [], 0
        for ln in (vm_groups[g.code].lines if g.code in vm_groups else ()):
            if ln.is_contingency or not ln.is_active:
                continue
            row_values = _series(ln.year_values, years)
            if ln.sub_line_id:
                line_ov = ann_map.get(ln.code) or {}
                overridden_years = sorted(yr for yr in line_ov if 1 <= yr <= years)
                if overridden_years:
                    row_values = list(row_values)
                    for yr in overridden_years:
                        row_values[yr - 1] = float(line_ov[yr])
                lines.append({
                    "sub_line_id": ln.sub_line_id,
                    "business_code": ln.code,
                    "label": ln.name,
                    "y1_keur": float(ln.y1_keur),
                    "inflation_pct": float(ln.inflation_pct),
                    "values": row_values,
                    "overridden_years": overridden_years,
                    "source": "saved_line",
                })
            elif any(v for v in row_values if v is not None):
                drivers.append({"label": ln.name, "values": row_values, "source": "technology_driver"})
            else:
                placeholders += 1
        derived = bool(g.is_derived)
        if has_overrides and not derived and (lines or drivers):
            recomputed = []
            for t in range(years):
                parts_t = [r["values"][t] for r in lines + drivers]
                recomputed.append(None if any(v is None for v in parts_t) else float(sum(parts_t)))
            values = recomputed
        if not derived and values and all(v is not None for v in values):
            for t in range(years):
                fixed_totals[t] += float(values[t])
        groups.append({
            "code": g.code, "name": g.display_name, "derived": derived, "has_data": bool(g.has_vm_data), "values": values,
            "lines": lines, "drivers": drivers, "placeholder_rows_not_listed": placeholders,
            "reconciles": None if derived else _reconciles(values, [r["values"] for r in lines + drivers]),
        })

    if has_overrides:
        cont_rate = float(vm.contingency_rate) / 100.0
        cont_by_year = [float(v * cont_rate) for v in fixed_totals]
        total_excl = [float(v) for v in fixed_totals]
        total_incl = [float(fixed_totals[t] + cont_by_year[t]) for t in range(years)]
        for g_obj in groups:
            if g_obj["code"] == "B.13" and g_obj["derived"]:
                g_obj["values"] = cont_by_year
    else:
        cont_by_year = _series(vm.contingency_by_year, years)
        total_excl = _series(vm.total_excl_contingency, years)
        total_incl = _series(vm.total_incl_contingency, years)

    notes = opex_group_authority_notes(record.project_id, getattr(record, "template_source", "") or "")
    protected = bool(is_protected_reference(record))
    bases = opex_bases(pis.get, notes, protected=protected)
    return {
        "ok": True, "project": {"code": record.project_code}, "unit": "kEUR", "years": list(range(1, years + 1)), "groups": groups,
        "contingency": {"rate_pct": float(vm.contingency_rate), "by_year": cont_by_year},
        "totals": {"excluding_contingency": total_excl, "including_contingency": total_incl},
        "bases": bases,
        "basis": ("Saved working inputs, not a Run result. Rows are the saved OPEX lines (Year 1 amount escalated by each line's own inflation, "
                  "with any explicit nominal annual overrides applied) and technology-driven rows. The six group base amounts are listed separately "
                  "with Year 1 only: the Run adds them, these yearly rows do not."),
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
        payload = build_line_projection(record, ws, owner, request=request, actor_user_id=user.user_id)
    except Exception:  # noqa: BLE001 - fail closed; never fabricate a projection
        return _json({"ok": False, "code": "OPEX_LINE_PROJECTION_UNAVAILABLE", "message": "The OPEX line projection could not be built. Reload to try again."}, 503)
    return _json(payload)


@router.get("/model-react/opex-projection/annual-exceptions/editor")
async def react_opex_annual_editor_context(request: Request, project: str = ""):
    """Separate authorized mutation context for annual OPEX exceptions (never exposed on read-only /lines).

    Returns ``editable: false`` with zero tokens/hashes for non-owners or protected references.
    For an authorized owner, returns consistent CAS tokens bound to the same snapshot.
    """
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user = resolve_request_session(request)
    if user is None:
        return _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    from app.opex_annual_exceptions import (
        document_token as opex_ann_token,
        effective_raw as opex_ann_effective_raw,
        parse_exceptions as parse_opex_ann,
    )
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.scenarios_repository import get_scenario
    from app.persistence.workspace_repository import get_workspace_state
    from app.ui.protected_reference_service import is_protected_reference
    from app.workbook.mutation_csrf import mutation_token
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get

    record, owner = resolve_accessible_project(user.user_id, (project or "").strip())
    if record is None:
        return _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    ws = get_workspace_state(owner, record.project_id)
    if ws is None:
        return _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)

    protected = bool(is_protected_reference(record))
    editable = (not protected) and (user.user_id == owner)
    if not editable:
        return _json({"ok": True, "editable": False})

    ident = assemble_consistent_for_get(owner, record.project_id, WORKBOOK.version)
    ws_consistent = get_workspace_state(owner, record.project_id) or ws
    active_sc = get_scenario(ws_consistent.active_scenario_id) if ws_consistent.active_scenario_id else None
    raw_ann = opex_ann_effective_raw(ws_consistent.draft_snapshot, active_sc)
    ann_map = parse_opex_ann(raw_ann) if raw_ann else {}
    return _json({
        "ok": True,
        "editable": True,
        "base_token": opex_ann_token(raw_ann),
        "content_hash": ident.composite_hash,
        "workbook_version": WORKBOOK.version,
        "scenario_id": ws_consistent.active_scenario_id,
        "csrf_token": mutation_token(request, record.project_code, "opex-annual-exceptions"),
        "endpoint": "/v2/model-react/opex-projection/annual-exceptions",
        "overrides": [
            {"line_key": lk, "year": yr, "amount_keur": amt}
            for lk, ym in sorted(ann_map.items())
            for yr, amt in sorted(ym.items())
        ],
    })


@router.post("/model-react/opex-projection/annual-exceptions")
async def save_opex_annual_exceptions(request: Request):
    """Canonical atomic CAS writer for annual OPEX exceptions (delegates to Save All transaction; never runs the model)."""
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user = resolve_request_session(request)
    if user is None:
        return _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    try:
        body = await request.json()
    except Exception:
        return _json({"ok": False, "code": "INVALID_JSON"}, 400)
    if not isinstance(body, dict):
        return _json({"ok": False, "code": "INVALID_JSON"}, 400)

    project_code = str(body.get("project") or "").strip()
    csrf_token = str(body.get("csrf_token") or "")
    from app.workbook.mutation_csrf import validate_mutation_token
    if not validate_mutation_token(request, project_code, csrf_token, "opex-annual-exceptions"):
        return _json({"ok": False, "code": "CSRF_INVALID"}, 403)

    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    record, owner = resolve_accessible_project(user.user_id, project_code)
    if record is None:
        return _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    if owner != user.user_id:
        return _json({"ok": False, "code": "OWNER_MISMATCH"}, 403)
    ws = get_workspace_state(owner, record.project_id)
    if ws is None:
        return _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)

    import json as _json_mod
    import uuid as _uuid
    from app.opex_annual_exceptions import (
        SCHEMA_VERSION,
        OpexAnnualExceptionError,
        document_token as opex_ann_token,
        effective_raw as opex_ann_effective_raw,
    )
    from app.persistence.scenarios_repository import get_scenario
    from app.v2.capex_commands import CapexProtectedReferenceError, CapexStaleIdentityError
    from app.v2.opex_commands import OpexProtectedReferenceError, OpexStaleIdentityError
    from app.v2.save_all_commands import SaveAllError, SaveAllInput, SaveAllRequestIdReused, save_all
    from app.workbook.registry import WORKBOOK
    from app.workbook.runtime_authority import resolve_runtime_freshness
    from app.workbook.update_service import StaleContentError

    overrides = body.get("overrides", [])
    raw_doc = _json_mod.dumps({"schema_version": SCHEMA_VERSION, "overrides": overrides}, sort_keys=True)
    req_id = str(body.get("request_id") or f"opexann-{_uuid.uuid4().hex[:16]}")
    data = SaveAllInput(
        request_id=req_id,
        workbook_version=str(body.get("workbook_version") or WORKBOOK.version),
        content_hash=str(body.get("content_hash") or ""),
        scenario_id=body.get("scenario_id"),
        opex_annual_exceptions_json=raw_doc,
        opex_annual_exceptions_base_token=str(body.get("base_token") or ""),
    )
    try:
        res = save_all(project_record=record, user_id=user.user_id, data=data)
    except (CapexProtectedReferenceError, OpexProtectedReferenceError) as exc:
        return _json({"ok": False, "code": "PROTECTED_REFERENCE", "message": str(exc)}, 403)
    except (StaleContentError, CapexStaleIdentityError, OpexStaleIdentityError, SaveAllRequestIdReused) as exc:
        return _json({"ok": False, "code": "STALE_CONTENT", "reload": True, "message": str(exc)}, 409)
    except OpexAnnualExceptionError as exc:
        return _json({"ok": False, "code": exc.code, "message": exc.message}, 422)
    except SaveAllError as exc:
        return _json({"ok": False, "code": exc.code, "message": str(exc), **exc.detail}, 422)

    ws_after = get_workspace_state(owner, record.project_id)
    active_sc = get_scenario(ws_after.active_scenario_id) if ws_after and ws_after.active_scenario_id else None
    raw_after = opex_ann_effective_raw(ws_after.draft_snapshot if ws_after else {}, active_sc)
    fresh = resolve_runtime_freshness(ws_after, current_composite_hash=res.content_hash) if ws_after else None
    run_state = (
        str(fresh.state.value)
        if fresh is not None and hasattr(fresh.state, "value")
        else (str(fresh.state) if fresh is not None else "NOT_RUN")
    )
    return _json({
        "ok": True,
        "content_hash": res.content_hash,
        "base_token": opex_ann_token(raw_after),
        "replayed": res.replayed,
        "model_executed": False,
        "run_state": run_state,
    })
