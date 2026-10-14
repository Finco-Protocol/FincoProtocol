"""app.v2.developer_decision_router — Developer Economics & Investment Decision workspace.

GET renders the Working Copy configuration editor, a clearly labelled Working Copy preview, the
last COMMITTED Run-bound Developer result (or a selected historical Run) and the decision panel.
The page never runs the engine and never writes on GET. POST ``/developer-decision/configuration``
is the single explicit Save/Reset: authenticated owner, project isolation, protected-reference
denial, signed CSRF and composite CAS via ``developer_economics_service`` (no financial computation).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

router = APIRouter()


def _scenario_context(ws, owner):
    """(scenario record or None, is_base, display name) for the workspace's selected scenario."""
    active = getattr(ws, "active_scenario_id", None)
    if not active:
        return None, True, "Base Case"
    from app.persistence.scenarios_repository import get_scenario
    scenario = get_scenario(scenario_id=active, user_id=owner)
    if scenario is None or scenario.archived:
        return None, True, "Base Case"
    return scenario, bool(scenario.is_base_case), scenario.scenario_name or "Scenario"


def _render(request, user, record, owner, ws, *, project, history_id="", form_error="", saved=False,
            status_code=200, submitted=None):
    from app.v2.router import _build_pis_with_composite_identity, _fmt_runtime_at
    from app.persistence.run_history_repository import get_run_history, get_run_history_entry
    from app.ui.protected_reference_service import is_protected_reference
    from app.v2.developer_committed_projection import build_committed_view, build_editor_model
    from app.v2.developer_decision_projection import build_decision_panel, build_project_meta
    from app.v2.developer_economics_projection import STATE_DISABLED, DeveloperWorkspace, build_developer_workspace
    from app.workbook.developer_economics_config import (
        DeveloperConfigError, SNAPSHOT_KEY, apply_config, effective_raw, parse_config,
    )
    from app.workbook.runtime_authority import resolve_runtime_freshness
    from app.workbook.service import WorkbookService

    run_state, content_hash, config, config_error = "NOT_RUN", "", None, ""
    preview = DeveloperWorkspace(
        state=STATE_DISABLED,
        state_note="Developer Economics evidence is unavailable: the project inputs could not be resolved.")
    scenario, is_base, scenario_name = _scenario_context(ws, owner) if ws is not None else (None, True, "Base Case")
    if ws is not None:
        try:
            pis = _build_pis_with_composite_identity(ws, record, owner)
            content_hash = getattr(pis, "content_hash", "") or ""
            run_state = resolve_runtime_freshness(ws, current_composite_hash=content_hash).state.value
            raw = effective_raw(pis.snapshot_origin, scenario)
            try:
                config = parse_config(raw)
                inputs = WorkbookService.to_projectinputs(pis)
                if scenario is not None and not is_base and (scenario.overrides or {}).get(SNAPSHOT_KEY):
                    inputs = apply_config(inputs, scenario.overrides[SNAPSHOT_KEY])
                preview = build_developer_workspace(inputs)
            except (DeveloperConfigError, ValueError) as exc:
                config_error = str(exc)
                preview = DeveloperWorkspace(
                    state="INVALID", state_note="The saved Developer Economics payload failed closed; no figure is shown.",
                    error_code=config_error.partition(":")[0], error_detail=config_error.partition(":")[2].strip())
        except Exception:
            pass

    summary = (getattr(ws, "last_runtime_summary", None) or {}) if ws is not None else {}
    ran_at = _fmt_runtime_at(getattr(ws, "last_runtime_at", None)) if ws is not None else ""
    committed = build_committed_view(
        summary, freshness=run_state, ran_at=ran_at,
        snapshot_id=getattr(ws, "last_runtime_snapshot_id", None) if ws is not None else None,
        composite_hash=getattr(ws, "last_runtime_composite_hash", None) if ws is not None else None,
        scenario_id=getattr(ws, "last_runtime_scenario_id", None) if ws is not None else None,
        check_scenario=ws is not None)
    history_rows, selected = [], None
    if ws is not None:
        try:
            entries = get_run_history(owner, record.project_id, limit=15)
        except Exception:
            entries = []
        from app.model_v2.developer_evidence import has_developer_key
        history_rows = [{"history_id": e.history_id, "ran_at": _fmt_runtime_at(e.ran_at) or e.ran_at,
                         "scenario": e.active_scenario_name or "Base Case",
                         "has_developer": has_developer_key(e.runtime_summary)} for e in entries]
        if history_id:
            entry = get_run_history_entry(owner, record.project_id, history_id)
            if entry is None:
                selected = {"state": "UNAVAILABLE", "note": "That Run does not exist for this project."}
            else:
                selected = build_committed_view(
                    entry.runtime_summary, freshness=run_state, historical=True, ran_at=_fmt_runtime_at(entry.ran_at) or entry.ran_at,
                    snapshot_id=entry.runtime_snapshot_id, composite_hash=entry.composite_hash,
                    scenario_id=entry.last_runtime_scenario_id or entry.active_scenario_id, check_scenario=True)
                selected["history_id"] = entry.history_id
    editor = build_editor_model(config, scenario_name=scenario_name, is_base=is_base,
                                overridden=bool(scenario is not None and not is_base and
                                                SNAPSHOT_KEY in (scenario.overrides or {})),
                                raw_error=form_error or config_error)
    if submitted is not None:
        editor["submitted"] = submitted
    lineage = ""
    if ws is not None and run_state != "NOT_RUN":
        short = str(getattr(ws, "last_runtime_composite_hash", "") or "")[:8]
        lineage = " · ".join(b for b in (ran_at, short) if b)

    from app.auth import generate_csrf_token
    from main_web import templates as _templates

    ctx = {
        "user": user, "project_code": record.project_code, "project_name": record.project_name,
        "meta": build_project_meta(record), "workspace": preview,
        "decision": build_decision_panel(summary, run_state=run_state),
        "run_state": run_state, "lineage": lineage, "committed": committed, "selected": selected,
        "history_rows": history_rows, "editor": editor, "content_hash": content_hash,
        "active_scenario_id": getattr(ws, "active_scenario_id", None) or "" if ws is not None else "",
        "csrf_token": generate_csrf_token(), "read_only": is_protected_reference(record),
        "saved": saved, "form_error": form_error,
    }
    return _templates.TemplateResponse(request=request, name="v2/developer_decision.html",
                                       context=ctx, status_code=status_code)


@router.get("/developer-decision", response_class=HTMLResponse)
async def developer_decision_page(request: Request, project: Optional[str] = None,
                                  history_id: Optional[str] = None, saved: Optional[str] = None):
    from app.v2.router import _get_current_user

    user = _get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state

    record, owner = resolve_accessible_project(user.user_id, (project or "").strip())
    if record is None:
        return HTMLResponse(content="<p>Project not found.</p>", status_code=404)
    try:
        ws = get_workspace_state(owner, record.project_id)
    except Exception:
        ws = None
    return _render(request, user, record, owner, ws, project=project, history_id=(history_id or "").strip(),
                   saved=saved == "1")


@router.post("/developer-decision/configuration")
async def developer_decision_save(request: Request):
    """Single explicit Save (or Reset to inherited) of the Developer Economics configuration."""
    from app.v2.router import _get_current_user

    user = _get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthenticated"}, status_code=401)
    form = await request.form()
    from app.auth import validate_csrf_token
    if not validate_csrf_token(form.get("csrf_token")):
        return JSONResponse({"error": "DEVELOPER_ECONOMICS_CSRF_INVALID"}, status_code=403)
    project = str(form.get("project") or "").strip()
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.ui.protected_reference_service import is_protected_reference
    from app.v2.developer_committed_projection import document_from_form
    from app.workbook.developer_economics_config import DeveloperConfigError
    from app.workbook.developer_economics_service import DeveloperEconomicsConflict, save_configuration

    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return JSONResponse({"error": "Project not found"}, status_code=404)
    if is_protected_reference(record):
        return JSONResponse({"error": "Protected reference; create a working copy"}, status_code=409)
    inherit = form.get("action") == "inherit"
    try:
        save_configuration(owner=owner, project_id=record.project_id,
                           expected_hash=str(form.get("content_hash") or ""),
                           expected_scenario_id=str(form.get("scenario_id") or ""),
                           raw="" if inherit else document_from_form(form), inherit=inherit)
    except (DeveloperConfigError, DeveloperEconomicsConflict, ValueError, TypeError) as exc:
        status = 409 if isinstance(exc, DeveloperEconomicsConflict) else 422
        ws = get_workspace_state(owner, record.project_id)
        return _render(request, user, record, owner, ws, project=project, form_error=str(exc),
                       status_code=status, submitted=dict(form))
    return RedirectResponse(f"/v2/developer-decision?project={record.project_code}&saved=1", status_code=303)
