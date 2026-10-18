"""RC-7 - monthly CAPEX construction spending-profile planner: preview, authorised Save/Reset, and Last Run reconciliation.

GET  /v2/capex/spending-profiles?project=CODE            leaf items, saved profile, binding status, Last Run reconciliation
POST /v2/capex/spending-profiles/preview                 hypothetical monthly allocation (nothing saved, CSRF-protected)
POST /v2/capex/spending-profiles/save                    Save / Reset the Working Copy profile document (CSRF + composite CAS)

Save writes ONE snapshot key through ``app.capex_profiles.service.save_profiles`` (exclusive transaction, ownership, protected-reference
and composite-identity CAS, dirty flag).  It never runs the model: the profile reaches the financial result only through the next
Workbook V2 Run, which binds it onto the monthly construction timeline (``app.capex_profiles.runtime``).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.templating import Jinja2Templates

from app.auth import generate_csrf_token, resolve_request_session, validate_csrf_token
from app.capex_profiles import config
from app.capex_profiles.contract import ProfileError, ProfileShape, ProfileSpec
from app.capex_profiles.plan import build_plan
from app.capex_profiles.projection import Timeline, build_timeline, catalogue
from app.capex_profiles.runtime import CapexProfileBindingError
from app.capex_profiles.service import CapexProfileConflict, materialize, save_profiles
from app.persistence.capex_sub_lines import list_sub_lines_for_project
from app.persistence.db import get_cursor
from app.persistence.projects_repository import resolve_accessible_project
from app.persistence.workspace_repository import get_workspace_state
from app.utils.workbook_flag import require_v2_active
from app.workbook.registry import WORKBOOK
from app.workbook.service import WorkbookService
from app.workbook.workbook_identity import assemble_consistent_for_get

profile_router = APIRouter()
_templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates" / "v2"))
MAX_FORM_ROWS = 200


def _saved_rows(ws) -> tuple[dict, Optional[str]]:
    """(form rows prefilled from the saved document, parse error code)."""
    raw = (ws.draft_snapshot or {}).get(config.SNAPSHOT_KEY)
    try:
        specs = config.parse(raw)
    except ProfileError as exc:
        return {}, exc.code
    return {s.item_key: {"shape": ProfileShape(s.shape).value, "explicit": ",".join(s.explicit_percent),
                         "milestone": "" if s.milestone_month is None else str(s.milestone_month)} for s in specs}, None


def _binding_status(ws, record) -> dict:
    raw = (ws.draft_snapshot or {}).get(config.SNAPSHOT_KEY)
    if not raw:
        return {"saved": False, "bound": False, "code": "", "items": 0}
    try:
        bound = materialize(dict(ws.draft_snapshot), record.project_id, raw)
        return {"saved": True, "bound": True, "code": "", "items": len(bound.evidence.profiled_leaves) if bound.evidence else 0}
    except (CapexProfileBindingError, ProfileError, ValueError) as exc:
        return {"saved": True, "bound": False, "code": getattr(exc, "code", type(exc).__name__), "items": 0}


def _last_run(owner: str, record, ws) -> dict:
    from app.persistence.run_history_repository import get_run_history
    from app.workbook.runtime_authority import resolve_runtime_freshness
    if not ws.last_runtime_snapshot_id and not getattr(ws, "any_run_committed", False):
        return {"available": False}
    entries = get_run_history(owner, record.project_id)
    entry = next((e for e in entries if e.runtime_snapshot_id == ws.last_runtime_snapshot_id), entries[0] if entries else None)
    if entry is None:
        return {"available": False}
    try:
        current_hash = assemble_consistent_for_get(owner, record.project_id, WORKBOOK.version).composite_hash
        state = resolve_runtime_freshness(ws, current_composite_hash=current_hash).state.value
    except Exception:                                       # noqa: BLE001 - freshness unavailable is shown, never guessed
        state = "UNKNOWN"
    used = bool((ws.last_runtime_snapshot or {}).get(config.SNAPSHOT_KEY))
    periods = (entry.integrity_evidence or {}).get("sources_uses", {}).get("construction_periods", []) or []
    su = (entry.runtime_summary or {}).get("financing_evidence", {}).get("sources_uses", {}) or {}
    return {"available": True, "freshness": state, "used_profile": used, "periods": periods, "sources_uses": su,
            "ran_at": getattr(entry, "ran_at", "")}


def _context(request, user, record, ws, pis, owner):
    items, excluded = catalogue(pis, record.project_id)
    months_raw = pis.get("project_setup.technical.construction_months")
    try:
        months = int(float(months_raw))
    except (TypeError, ValueError):
        months = 0
    timeline = build_timeline(ws.draft_snapshot, months) if months else Timeline(False, "CONSTRUCTION_MONTHS_UNAVAILABLE", months)
    with get_cursor() as cur:
        every = list_sub_lines_for_project(cur, record.project_id, include_inactive=True)
    active = {i.item_key for i in items} | {e.item_key for e in excluded}
    inactive = frozenset(s.business_code for s in every if not s.is_active and s.business_code not in active)
    saved_rows, saved_error = _saved_rows(ws)
    base_case = True
    if ws.active_scenario_id:
        from app.persistence.scenarios_repository import get_scenario
        scenario = get_scenario(ws.active_scenario_id, owner)
        base_case = bool(scenario is not None and scenario.is_base_case)
    can_edit = (record.user_id == user.user_id) and owner == user.user_id and base_case and not getattr(record, "is_readonly", False)
    return {"request": request, "user": user, "project": record, "project_code": record.project_code, "csrf_token": generate_csrf_token(),
            "content_hash": assemble_consistent_for_get(owner, record.project_id, WORKBOOK.version).composite_hash,
            "items": items, "excluded": excluded, "months": months, "timeline": timeline, "inactive_keys": inactive,
            "shapes": [s.value for s in ProfileShape], "plan": None, "form_rows": dict(saved_rows), "error": None, "saved_error": saved_error,
            "binding": _binding_status(ws, record), "last_run": _last_run(owner, record, ws), "can_edit": can_edit, "base_case": base_case,
            "notice": None}


def _guard(request: Request, project: str):
    user = resolve_request_session(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return RedirectResponse(url="/library?notice=project-unavailable", status_code=302)
    ws = get_workspace_state(user_id=owner, project_id=record.project_id)
    if ws is None:
        return RedirectResponse(url="/library?notice=project-unavailable", status_code=302)
    return user, record, ws, owner


def _parse_rows(form, ctx):
    """(specs, form_rows, error) from the submitted rows; an invalid shape is rejected outright, never defaulted."""
    specs, form_rows = [], {}
    valid_shapes = {s.value for s in ProfileShape}
    for index in range(MAX_FORM_ROWS):
        key = str(form.get(f"key_{index}", "") or "")
        if not key:
            continue
        shape = str(form.get(f"shape_{index}", "") or "")
        explicit = str(form.get(f"explicit_{index}", "") or "")
        milestone = str(form.get(f"milestone_{index}", "") or "").strip()
        form_rows[key] = {"shape": shape, "explicit": explicit, "milestone": milestone}
        if not shape:
            continue
        if shape not in valid_shapes:
            return specs, form_rows, "CAPEX_PROFILE_SHAPE_INVALID"
        specs.append(ProfileSpec(
            item_key=key, shape=ProfileShape(shape),
            explicit_percent=tuple(p.strip() for p in explicit.replace(";", ",").split(",")) if explicit.strip() else (),
            milestone_month=int(milestone) if milestone.isdigit() else (None if not milestone else -1)))
    return specs, form_rows, None


@profile_router.get("/spending-profiles", response_class=HTMLResponse)
async def capex_spending_profiles_page(request: Request, project: str = "", saved: str = "", _: None = Depends(require_v2_active)):
    guard = _guard(request, project)
    if isinstance(guard, RedirectResponse):
        return guard
    user, record, ws, owner = guard
    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    ctx = _context(request, user, record, ws, pis, owner)
    if saved in ("saved", "reset"):
        ctx["notice"] = ("Profile saved to the Working Copy. The Last Run is now STALE: run the model to apply it." if saved == "saved"
                         else "Profile removed from the Working Copy. Run the model to return to the default timing.")
    return _templates.TemplateResponse(request=request, name="capex_spending_profiles.html", context=ctx)


@profile_router.post("/spending-profiles/preview", response_class=HTMLResponse)
async def capex_spending_profiles_preview(request: Request, project: str = Form(...), csrf_token: str = Form(...),
                                          _: None = Depends(require_v2_active)):
    guard = _guard(request, project)
    if isinstance(guard, RedirectResponse):
        return guard
    user, record, ws, owner = guard
    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    ctx = _context(request, user, record, ws, pis, owner)
    if not validate_csrf_token(csrf_token):
        ctx["error"] = "CAPEX_PROFILE_CSRF_INVALID"
        return _templates.TemplateResponse(request=request, name="capex_spending_profiles.html", context=ctx, status_code=403)
    form = await request.form()
    specs, form_rows, bad = _parse_rows(form, ctx)
    if bad:
        ctx["error"] = bad
        return _templates.TemplateResponse(request=request, name="capex_spending_profiles.html", context=ctx, status_code=422)
    if not ctx["months"]:
        ctx["error"] = "CAPEX_PROFILE_DURATION_INVALID"
        return _templates.TemplateResponse(request=request, name="capex_spending_profiles.html", context=ctx, status_code=422)
    excluded_keys = frozenset(e.item_key for e in ctx["excluded"])
    ctx["plan"] = build_plan(ctx["items"], specs, ctx["months"], ctx["timeline"], excluded_keys=excluded_keys,
                             inactive_keys=ctx["inactive_keys"])
    ctx["form_rows"] = form_rows
    return _templates.TemplateResponse(request=request, name="capex_spending_profiles.html", context=ctx)


@profile_router.post("/spending-profiles/save", response_class=HTMLResponse)
async def capex_spending_profiles_save(request: Request, project: str = Form(...), csrf_token: str = Form(...),
                                       content_hash: str = Form(...), action: str = Form("save"),
                                       _: None = Depends(require_v2_active)):
    guard = _guard(request, project)
    if isinstance(guard, RedirectResponse):
        return guard
    user, record, ws, owner = guard
    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    ctx = _context(request, user, record, ws, pis, owner)
    if not validate_csrf_token(csrf_token):
        ctx["error"] = "CAPEX_PROFILE_CSRF_INVALID"
        return _templates.TemplateResponse(request=request, name="capex_spending_profiles.html", context=ctx, status_code=403)
    if not ctx["can_edit"]:
        ctx["error"] = "CAPEX_PROFILE_READ_ONLY" if ctx["base_case"] else "CAPEX_PROFILE_SCENARIO_EDIT_UNSUPPORTED"
        return _templates.TemplateResponse(request=request, name="capex_spending_profiles.html", context=ctx, status_code=403)
    form = await request.form()
    specs, form_rows, bad = _parse_rows(form, ctx)
    ctx["form_rows"] = form_rows or ctx["form_rows"]
    if action not in ("save", "reset"):
        bad = "CAPEX_PROFILE_ACTION_INVALID"
    if bad:
        ctx["error"] = bad
        return _templates.TemplateResponse(request=request, name="capex_spending_profiles.html", context=ctx, status_code=422)
    document = "" if action == "reset" else json.dumps(config.to_document(specs))
    try:
        save_profiles(owner=owner, project_id=record.project_id, expected_hash=content_hash,
                      expected_scenario_id=ws.active_scenario_id or "", raw=document)
    except CapexProfileConflict as exc:
        ctx["error"] = exc.code
        return _templates.TemplateResponse(request=request, name="capex_spending_profiles.html", context=ctx, status_code=409)
    except (CapexProfileBindingError, ProfileError) as exc:
        ctx["error"] = getattr(exc, "code", "CAPEX_PROFILE_REJECTED")
        ctx["error_detail"] = str(exc)
        return _templates.TemplateResponse(request=request, name="capex_spending_profiles.html", context=ctx, status_code=422)
    outcome = "saved" if action == "save" else "reset"
    return RedirectResponse(url=f"/v2/capex/spending-profiles?project={record.project_code}&saved={outcome}", status_code=303)
