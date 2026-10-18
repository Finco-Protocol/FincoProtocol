"""WF-09 CAPEX Spending Profiles V1 - read-only CANDIDATE planner.

GET  /v2/capex/spending-profiles?project=CODE            item list + profile form
POST /v2/capex/spending-profiles/preview                 hypothetical monthly allocation (CSRF-protected)

No route here writes anything, persists a profile, starts a Run or calls a financial engine.  The committed Run is unchanged.
A canonical Save is deliberately NOT offered: no existing owned writer's persisted schedule reaches the Run (see the WF-09 report).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.templating import Jinja2Templates

from app.auth import generate_csrf_token, resolve_request_session, validate_csrf_token
from app.capex_profiles.contract import ProfileShape, ProfileSpec
from app.capex_profiles.plan import build_plan
from app.capex_profiles.projection import Timeline, build_timeline, catalogue
from app.persistence.capex_sub_lines import list_sub_lines_for_project
from app.persistence.db import get_cursor
from app.persistence.projects_repository import resolve_accessible_project
from app.persistence.workspace_repository import get_workspace_state
from app.utils.workbook_flag import require_v2_active
from app.workbook.service import WorkbookService

profile_router = APIRouter()
_templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates" / "v2"))
MAX_FORM_ROWS = 200


def _context(request, user, record, ws, pis):
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
    return {"request": request, "user": user, "project": record, "project_code": record.project_code, "csrf_token": generate_csrf_token(),
            "items": items, "excluded": excluded, "months": months, "timeline": timeline, "inactive_keys": inactive,
            "shapes": [s.value for s in ProfileShape], "plan": None, "form_rows": {}, "error": None}


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
    return user, record, ws


@profile_router.get("/spending-profiles", response_class=HTMLResponse)
async def capex_spending_profiles_page(request: Request, project: str = "", _: None = Depends(require_v2_active)):
    guard = _guard(request, project)
    if isinstance(guard, RedirectResponse):
        return guard
    user, record, ws = guard
    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    return _templates.TemplateResponse(request=request, name="capex_spending_profiles.html", context=_context(request, user, record, ws, pis))


@profile_router.post("/spending-profiles/preview", response_class=HTMLResponse)
async def capex_spending_profiles_preview(request: Request, project: str = Form(...), csrf_token: str = Form(...),
                                          _: None = Depends(require_v2_active)):
    guard = _guard(request, project)
    if isinstance(guard, RedirectResponse):
        return guard
    user, record, ws = guard
    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    ctx = _context(request, user, record, ws, pis)
    if not validate_csrf_token(csrf_token):
        ctx["error"] = "CAPEX_PROFILE_CSRF_INVALID"
        return _templates.TemplateResponse(request=request, name="capex_spending_profiles.html", context=ctx, status_code=403)
    form = await request.form()
    specs, form_rows = [], {}
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
        if shape not in {s.value for s in ProfileShape}:
            ctx["error"] = "CAPEX_PROFILE_SHAPE_INVALID"
            return _templates.TemplateResponse(request=request, name="capex_spending_profiles.html", context=ctx, status_code=422)
        specs.append(ProfileSpec(
            item_key=key, shape=ProfileShape(shape),
            explicit_percent=tuple(p.strip() for p in explicit.replace(";", ",").split(",")) if explicit.strip() else (),
            milestone_month=int(milestone) if milestone.isdigit() else (None if not milestone else -1)))
    if not ctx["months"]:
        ctx["error"] = "CAPEX_PROFILE_DURATION_INVALID"
        return _templates.TemplateResponse(request=request, name="capex_spending_profiles.html", context=ctx, status_code=422)
    excluded_keys = frozenset(e.item_key for e in ctx["excluded"])
    ctx["plan"] = build_plan(ctx["items"], specs, ctx["months"], ctx["timeline"], excluded_keys=excluded_keys,
                             inactive_keys=ctx["inactive_keys"])
    ctx["form_rows"] = form_rows
    return _templates.TemplateResponse(request=request, name="capex_spending_profiles.html", context=ctx)
