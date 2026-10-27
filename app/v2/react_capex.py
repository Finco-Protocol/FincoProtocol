"""RC-UX A2 (Audit A GAP-R9) — JSON adapter for the React CAPEX spending-profile studio.

A presentation/adapter layer over the EXISTING canonical CAPEX-profile authority.  It adds NO economic or persistence authority and
re-implements NO allocation, rounding or IDC algorithm:

* the eligible items, timeline, saved document, binding status and Last Run reconciliation are the ones of
  ``app.v2.capex_profile_router`` (the Legacy planner page reads the same helpers) over ``app.capex_profiles``;
* the hypothetical monthly allocation is ``app.capex_profiles.plan.build_plan`` — exact ``Fraction`` weights, the 1e-6 kEUR quantum and the
  last-month rounding residual are the contract's own;
* the only write is the EXISTING ``POST /v2/capex/spending-profiles/save`` (CSRF + composite-hash CAS, exclusive transaction), which the React
  editor posts to directly.  This module issues no token other than the one that page issues and writes nothing.

``GET /model-react/capex/profiles?project=CODE``   — items, timeline, saved profile, binding status, Last Run reconciliation, save contract.
``GET /model-react/capex/preview?project=CODE&spec=[...]`` — ephemeral allocation of a submitted draft (nothing saved, no Run, never a result).
  ``spec`` is a JSON array of ``[item_key, shape, "explicit,percent,list", milestone_month]``, bounded in size.

IDC, commitment fees and Sources & Uses depend on the full construction-funding engine: they are NOT estimated here.  The studio shows the
committed Last Run's figures as such and states that the draft's impact on them exists only after a Run.
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import resolve_request_session
from app.v2.react_poc_router import react_poc_enabled

router = APIRouter()
log = logging.getLogger(__name__)

REQUEST_HEADER = "x-finco-react-request"
MAX_SPEC_CHARS = 8000
MAX_SPEC_ROWS = 200


def _json(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "private, no-store"})


def _fail(status: int, code: str, message: str) -> JSONResponse:
    return _json({"ok": False, "code": code, "message": message + " Nothing was changed."}, status)


def _scope(request: Request, project: str, *, header: bool):
    """(user, record, ws, owner) or a ready JSONResponse: flag, header, session, project access, workspace."""
    if not react_poc_enabled():
        return None, None, None, None, _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    if header and request.headers.get(REQUEST_HEADER) != "1":
        return None, None, None, None, _fail(400, "REQUEST_HEADER_REQUIRED", "This preview can only be started from the FINCO Model workspace.")
    user = resolve_request_session(request)
    if user is None:
        return None, None, None, None, _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state

    record, owner = resolve_accessible_project(user.user_id, (project or "").strip())
    if record is None:
        return None, None, None, None, _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    ws = get_workspace_state(user_id=owner, project_id=record.project_id)
    if ws is None:
        return None, None, None, None, _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    return user, record, ws, owner, None


def _amount(value: Any) -> str:
    """Exact kEUR display, three decimals, thousands separated; unavailable stays '—'."""
    if value is None:
        return "—"
    return f"{Decimal(str(value)):,.3f}"


def _item(view) -> dict[str, Any]:
    return {"item_key": view.item_key, "kind": view.kind, "label": view.label, "category_code": view.category_code,
            "amount_keur": float(view.amount_keur), "amount_display": _amount(view.amount_keur)}


def _timeline(timeline) -> dict[str, Any]:
    return {"available": bool(timeline.available), "reason": timeline.reason, "months": timeline.months, "source": timeline.source,
            "month_start": [d.isoformat() for d in timeline.month_start], "month_to_period": list(timeline.month_to_period),
            "period_starts": [d.isoformat() for d in timeline.period_starts], "period_ends": [d.isoformat() for d in timeline.period_ends]}


def _context(request: Request, user, record, ws, owner):
    from app.v2.capex_profile_router import _context as legacy_context
    from app.workbook.service import WorkbookService

    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    return legacy_context(request, user, record, ws, pis, owner)


def _last_run(raw: dict[str, Any]) -> dict[str, Any]:
    if not raw.get("available"):
        return {"available": False, "note": "No committed Run exists for this Working Copy."}
    su = raw.get("sources_uses") or {}
    keys = ("base_project_capex_keur", "capitalized_idc_keur", "commitment_fee_keur", "structuring_fee_keur", "initial_dsra_funding_keur",
            "total_uses_keur", "total_sources_keur")
    return {"available": True, "freshness": raw.get("freshness"), "used_profile": bool(raw.get("used_profile")), "ran_at": raw.get("ran_at"),
            "sources_uses": {k: (None if su.get(k) is None else {"value": su.get(k), "display": _amount(su.get(k))}) for k in keys},
            "periods": [{"period": p.get("period"), "uses": _amount(p.get("uses")), "sources": _amount(p.get("sources")),
                         "difference": _amount(p.get("difference"))} for p in raw.get("periods") or []],
            "basis": "Committed Run evidence, shown as persisted. It is the Run that last executed, not the draft below."}


@router.get("/model-react/capex/profiles")
async def react_capex_profiles(request: Request, project: str = ""):
    user, record, ws, owner, refused = _scope(request, project, header=False)
    if refused is not None:
        return refused
    from app.capex_profiles.contract import ProfileShape

    ctx = _context(request, user, record, ws, owner)
    from app.v2.react_workspace_router import _vertical_scope

    scope = _vertical_scope(record)
    can_edit = bool(ctx["can_edit"])
    reason = "" if can_edit else ("A scenario is selected: scenarios inherit the saved profile; switch to the Base case to edit it."
                                  if not ctx["base_case"] else "This project is read-only for you; the profile can be viewed but not saved.")
    return _json({
        "ok": True,
        "project": {"code": record.project_code, "name": record.project_name, "vertical": scope["key"], "pilot_tier": scope["pilot_tier"]},
        "months": ctx["months"], "timeline": _timeline(ctx["timeline"]),
        "shapes": [s.value for s in ProfileShape],
        "items": [_item(i) for i in ctx["items"]],
        "excluded": [_item(i) for i in ctx["excluded"]],
        "saved": {"rows": ctx["form_rows"], "error": ctx["saved_error"], "binding": ctx["binding"]},
        "last_run": _last_run(ctx["last_run"]),
        "edit": {"allowed": can_edit, "reason": reason, "base_case": bool(ctx["base_case"])},
        "save": {"url": "/v2/capex/spending-profiles/save", "csrf_token": ctx["csrf_token"], "content_hash": ctx["content_hash"],
                 "scenario_id": ws.active_scenario_id or ""},
        "semantics": {"save_runs_the_model": False, "preview_is_a_result": False,
                      "idc_and_sources_uses": "Computed by the canonical engine at Run. They are not estimated by this studio."},
    })


def parse_spec(raw: str):
    """Specs from the compact preview draft; raises ValueError(code) for anything malformed."""
    from app.capex_profiles.contract import ProfileShape, ProfileSpec

    if not raw or len(raw) > MAX_SPEC_CHARS:
        raise ValueError("CAPEX_PROFILE_SPEC_INVALID_OR_TOO_LARGE")
    try:
        rows = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("CAPEX_PROFILE_SPEC_INVALID_OR_TOO_LARGE") from exc
    if not isinstance(rows, list) or len(rows) > MAX_SPEC_ROWS:
        raise ValueError("CAPEX_PROFILE_SPEC_INVALID_OR_TOO_LARGE")
    valid = {s.value for s in ProfileShape}
    specs = []
    for row in rows:
        if not (isinstance(row, list) and len(row) == 4 and all(isinstance(c, (str, int, type(None))) for c in row)):
            raise ValueError("CAPEX_PROFILE_SPEC_INVALID_OR_TOO_LARGE")
        key, shape, explicit, milestone = row
        if not isinstance(key, str) or not key or not isinstance(shape, str):
            raise ValueError("CAPEX_PROFILE_SPEC_INVALID_OR_TOO_LARGE")
        if not shape:
            continue
        if shape not in valid:
            raise ValueError("CAPEX_PROFILE_SHAPE_INVALID")
        explicit_text = explicit if isinstance(explicit, str) else ""
        month = milestone
        if isinstance(month, str):
            month = int(month) if month.strip().isdigit() else (None if not month.strip() else -1)
        specs.append(ProfileSpec(item_key=key, shape=ProfileShape(shape),
                                 explicit_percent=tuple(p.strip() for p in explicit_text.replace(";", ",").split(",")) if explicit_text.strip() else (),
                                 milestone_month=month))
    return specs


def plan_json(plan) -> dict[str, Any]:
    rows = []
    for r in plan.rows:
        if r.spec is None:
            continue
        rows.append({"item_key": r.item.item_key, "label": r.item.label, "shape": r.spec.shape.value,
                     "amount_display": _amount(r.item.amount_keur),
                     "status": "invalid" if r.error_code else "valid", "error_code": r.error_code, "error_detail": r.error_detail,
                     "unallocated_display": _amount(r.unallocated_keur),
                     "rounding_residual": None if r.result is None else str(r.result.rounding_residual_keur),
                     "period_equivalent": [_amount(v) for v in r.period_equivalent_keur]})
    valid = [r for r in plan.rows if r.result is not None]
    months = []
    for k in range(plan.months):
        months.append({"month": k + 1,
                       "start": plan.timeline.month_start[k].isoformat() if plan.timeline.available else None,
                       "period": plan.timeline.month_to_period[k] if plan.timeline.available else None,
                       "items": {r.item.item_key: _amount(r.result.months[k].amount_keur) for r in valid},
                       "total": _amount(plan.monthly_total_keur[k]), "cumulative": _amount(plan.monthly_cumulative_keur[k]),
                       "remaining": _amount(plan.monthly_remaining_keur[k])})
    return {"months_count": plan.months, "rows": rows, "months": months,
            "item_order": [r.item.item_key for r in valid],
            "totals": {"planned": _amount(plan.planned_total_keur), "profiled": _amount(plan.profiled_total_keur),
                       "unallocated": _amount(plan.unallocated_total_keur),
                       "reconciles": plan.unallocated_total_keur == 0 and not plan.global_errors},
            "period_equivalent_total": [_amount(v) for v in plan.period_equivalent_total_keur],
            "global_errors": list(plan.global_errors), "notice": plan.notice, "canonical": plan.canonical}


@router.get("/model-react/capex/preview")
async def react_capex_preview(request: Request, project: str = "", spec: str = ""):
    user, record, ws, owner, refused = _scope(request, project, header=True)
    if refused is not None:
        return refused
    if set(request.query_params) - {"project", "spec"}:
        return _fail(400, "INVALID_QUERY", "Unexpected query parameters.")
    from app.capex_profiles.plan import build_plan

    try:
        specs = parse_spec(spec)
    except ValueError as exc:
        return _fail(422, str(exc), "The draft profile could not be read.")
    ctx = _context(request, user, record, ws, owner)
    if not ctx["months"]:
        return _fail(422, "CAPEX_PROFILE_DURATION_INVALID", "The construction duration is not available.")
    excluded_keys = frozenset(e.item_key for e in ctx["excluded"])
    plan = build_plan(ctx["items"], specs, ctx["months"], ctx["timeline"], excluded_keys=excluded_keys, inactive_keys=ctx["inactive_keys"])
    return _json({"ok": True, "plan": plan_json(plan), "content_hash": ctx["content_hash"],
                  "semantics": {"preview_is_a_result": False, "writes_nothing": True, "is_a_run": False}})
