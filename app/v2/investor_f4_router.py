"""Owned agreement Save and read-only canonical/historical investor evidence."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.model_v2.investor_f4 import EVIDENCE_KEY, parse_terms, validate_evidence
from app.workbook.investor_agreement_service import effective_raw, save_agreement, InvestorAgreementConflict

router = APIRouter()


def _load(request, project, history_id=None):
    from app.v2.router import _get_current_user
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.run_history_repository import get_run_history_entry, get_run_history
    from app.v2.post_run_context import PostRunRequestContext
    from app.persistence.scenarios_repository import get_scenario
    from app.workbook.runtime_projection import thaw_runtime_payload
    from app.ui.protected_reference_service import is_protected_reference

    user = _get_current_user(request)
    if user is None:
        return None, HTMLResponse("Authentication required.", status_code=401)
    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return None, HTMLResponse("Project not found.", status_code=404)
    context = PostRunRequestContext.capture(owner_id=owner, project_id=record.project_id)
    context.require_scope(owner, record.project_id)
    ws = context.workspace
    scenario = get_scenario(scenario_id=ws.active_scenario_id, user_id=owner) if ws.active_scenario_id else None
    if ws.active_scenario_id and (scenario is None or scenario.project_id != record.project_id or scenario.archived):
        raise ValueError("Active agreement scenario is unavailable")
    terms = None if history_id is not None else parse_terms(effective_raw(context.inputs.snapshot_origin, scenario))
    selected = get_run_history_entry(owner, record.project_id, history_id) if history_id is not None else None
    if history_id is not None and selected is None:
        return None, HTMLResponse("Run History entry not found.", status_code=404)
    rr = selected or context.runtime_result
    snapshot_id = selected.runtime_snapshot_id if selected else getattr(rr, "snapshot_id", "")
    run_hash = selected.composite_hash if selected else ws.last_runtime_composite_hash
    scenario_id = selected.last_runtime_scenario_id if selected else ws.last_runtime_scenario_id
    evidence = None
    unavailable = "Investor evidence is unavailable for this Run. Save an agreement and Run; legacy allocations are not reconstructed."
    runtime = thaw_runtime_payload(getattr(rr, "runtime_summary", None) or {})
    if EVIDENCE_KEY in runtime:
        evidence = validate_evidence(runtime[EVIDENCE_KEY], owner_id=owner,
            project_id=record.project_id, snapshot_id=snapshot_id, composite_hash=run_hash, scenario_id=scenario_id)
        unavailable = ""
    sponsor = thaw_runtime_payload(getattr(rr, "sponsor_schedule", None) or {})
    # Existing per-date paid-in fields are funding evidence, never commitments.
    funding = []
    for row in sponsor.get("periods", []):
        keys = ("share_capital_contribution_keur", "share_premium_contribution_keur",
                "other_committed_equity_contribution_keur", "additional_equity_contribution_keur")
        if row.get("date") and all(type(row.get(k)) in (int, float) for k in keys):
            value = sum(row[k] for k in keys)
            if value:
                funding.append(dict(date=row["date"], paid_in_keur=value))
    return dict(context=context, record=record, owner=owner, terms=terms, evidence=evidence,
        unavailable=unavailable, funding=funding, history=get_run_history(owner, record.project_id, limit=12),
        history_id=history_id, project_code=record.project_code, snapshot_id=snapshot_id,
        state="HISTORICAL" if selected else context.freshness.state.value,
        editable=not is_protected_reference(record) and not selected), None


def _unavailable():
    return HTMLResponse('<section id="f4-investor-workspace" role="status">UNAVAILABLE: investor evidence or workspace identity changed. Reload to refresh.</section>',
                        headers={"Cache-Control": "private, no-store"})


def _render(view):
    from app.auth import generate_csrf_token
    from app.v2.router import _templates
    view["csrf_token"] = generate_csrf_token()
    html = _templates.get_template("partials/_investor_f4.html").render(f4=view)
    view["context"].validate_current()
    return html


@router.get("/workbook/investor/agreement")
async def investor_workspace(request: Request, project: str, history_id: str | None = None):
    from app.persistence.run_history_repository import RunHistoryError
    from app.workbook.workbook_identity import WorkbookIdentityError
    from app.v2.post_run_context import PostRunContextChanged
    try:
        view, error = _load(request, project, history_id)
        return error or HTMLResponse(_render(view), headers={"Cache-Control": "private, no-store"})
    except (ValueError, TypeError, KeyError, PermissionError, RunHistoryError, WorkbookIdentityError, PostRunContextChanged):
        return _unavailable()


@router.post("/workbook/investor/agreement")
async def investor_save(request: Request):
    from app.v2.router import _get_current_user, _scenario_authority_oob
    from app.auth import validate_csrf_token
    from app.persistence.projects_repository import resolve_accessible_project
    from app.ui.protected_reference_service import is_protected_reference
    from app.v2.post_run_context import PostRunContextChanged
    from app.workbook.workbook_identity import WorkbookIdentityError
    from app.persistence.run_history_repository import RunHistoryError
    user = _get_current_user(request)
    if user is None:
        return JSONResponse({"error": "Authentication required"}, status_code=401)
    form = await request.form()
    if not validate_csrf_token(form.get("csrf_token")):
        return JSONResponse({"error": "INVESTOR_CSRF_INVALID"}, status_code=403)
    code = str(form.get("project") or "")
    record, owner = resolve_accessible_project(user.user_id, code)
    if record is None:
        return JSONResponse({"error": "Project not found"}, status_code=404)
    if is_protected_reference(record):
        return JSONResponse({"error": "Reference is read-only; create a working copy"}, status_code=409)
    if form.get("action") not in ("save", "remove"):
        return JSONResponse({"error": "Unsupported agreement action"}, status_code=422)
    try:
        save_agreement(owner=owner, project_id=record.project_id,
            expected_hash=str(form.get("content_hash") or ""), raw=form.get("agreement", ""),
            remove=form.get("action") == "remove")
    except (ValueError, TypeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=409 if isinstance(exc, InvestorAgreementConflict) else 422)
    try:
        view, error = _load(request, code)
        if error:
            return error
        ctx = view["context"]
        html = _render(view) + _scenario_authority_oob(
            request, ctx.workspace, ctx.project_record, code, owner, include_revenue=False)
        ctx.validate_current()
        return HTMLResponse(html, headers={"Cache-Control": "private, no-store"})
    except (ValueError, TypeError, PermissionError, PostRunContextChanged, WorkbookIdentityError, RunHistoryError):
        return _unavailable()


@router.get("/workbook/investor/export")
async def investor_export(request: Request, project: str, history_id: str | None = None):
    from app.export.investor_f4 import export_investor_evidence
    from app.persistence.run_history_repository import RunHistoryError
    from app.workbook.workbook_identity import WorkbookIdentityError
    from app.v2.post_run_context import PostRunContextChanged
    try:
        view, error = _load(request, project, history_id)
        if error:
            return error
        if view["evidence"] is None:
            return JSONResponse({"error": "Run-bound investor evidence is unavailable"}, status_code=409)
        payload = export_investor_evidence(view["evidence"], project_name=view["record"].project_name,
                                         historical=history_id is not None)
        view["context"].validate_current()
        return Response(payload, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="investor-waterfall.xlsx"',
                                 "Cache-Control": "private, no-store"})
    except (ValueError, TypeError, KeyError, PermissionError, RunHistoryError, WorkbookIdentityError, PostRunContextChanged):
        return JSONResponse({"error": "Investor evidence or workspace identity is inconsistent"}, status_code=409)
