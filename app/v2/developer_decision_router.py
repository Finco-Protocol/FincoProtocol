"""app.v2.developer_decision_router — Developer Economics & Investment Decision workspace.

One read-only GET.  Auth, ownership and protected-reference semantics are the existing
``resolve_accessible_project`` authority; freshness is the canonical
``resolve_runtime_freshness`` over the composite workbook identity.  The page never runs the
engine, never writes, and never reads the Working Copy for economics other than through the
canonical ``ProjectInputSet.to_projectinputs`` bridge.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()


@router.get("/developer-decision", response_class=HTMLResponse)
async def developer_decision_page(request: Request, project: Optional[str] = None):
    from app.v2.router import _build_pis_with_composite_identity, _fmt_runtime_at, _get_current_user

    user = _get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.v2.developer_decision_projection import build_decision_panel, build_project_meta
    from app.v2.developer_economics_projection import (
        STATE_DISABLED,
        DeveloperWorkspace,
        build_developer_workspace,
    )
    from app.workbook.runtime_authority import resolve_runtime_freshness
    from app.workbook.service import WorkbookService

    record, owner = resolve_accessible_project(user.user_id, (project or "").strip())
    if record is None:
        return HTMLResponse(content="<p>Project not found.</p>", status_code=404)
    try:
        ws = get_workspace_state(owner, record.project_id)
    except Exception:
        ws = None

    run_state = "NOT_RUN"
    workspace = DeveloperWorkspace(
        state=STATE_DISABLED,
        state_note="Developer Economics evidence is unavailable: the project inputs could not be resolved.",
    )
    if ws is not None:
        try:
            pis = _build_pis_with_composite_identity(ws, record, owner)
            run_state = resolve_runtime_freshness(
                ws, current_composite_hash=getattr(pis, "content_hash", None)).state.value
            workspace = build_developer_workspace(WorkbookService.to_projectinputs(pis))
        except Exception:
            pass

    summary = (getattr(ws, "last_runtime_summary", None) or {}) if ws else {}
    ran_at = _fmt_runtime_at(getattr(ws, "last_runtime_at", None)) if ws else ""
    lineage = ""
    if ws is not None and run_state != "NOT_RUN":
        short = str(getattr(ws, "last_runtime_composite_hash", "") or "")[:8]
        lineage = " · ".join(b for b in (ran_at, short) if b)

    from main_web import templates as _templates

    ctx = {
        "user": user,
        "project_code": record.project_code,
        "project_name": record.project_name,
        "meta": build_project_meta(record),
        "workspace": workspace,
        "decision": build_decision_panel(summary, run_state=run_state),
        "run_state": run_state,
        "lineage": lineage,
    }
    return _templates.TemplateResponse(request=request, name="v2/developer_decision.html", context=ctx)
