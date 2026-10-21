"""UX-01 Full-React Architecture PoC — isolated, feature-flagged entry surface.

This router adds NO authority of its own:

* The page shell (``GET /model-react``) serves a same-origin React bundle from
  ``/static/react/``; the legacy Jinja2/HTMX workbook stays the default and is
  never modified.
* The one editable input (``tax.assumptions.cit_rate_pct``) saves exclusively
  through the EXISTING canonical ``POST /v2/workbook/grid/save`` (C0 atomic
  batch writer, composite CAS, CSRF, session ownership).  This router never
  persists anything.
* The read-only P&L comes from the SAME authorized snapshot the Statements
  workspace uses (``PostRunRequestContext`` + ``build_output_workspace_safe``),
  serialised as a thin JSON projection over the existing persisted RuntimeResult
  and statement services.  No financial value is computed here.

Feature flag: ``FINCO_MODEL_REACT_V1`` (absent/empty → OFF; canonical truthy →
ON; anything else → OFF).  OFF leaves every existing route untouched: the page
renders an explicit fallback that links back to the legacy workbook.

Run action: deliberately NOT exposed.  The canonical ``POST /workbook/run``
answers with HTMX fragments / 303 redirects (see its docstring); a React client
needs a thin outcome adapter before a Run button can exist without inventing a
second Run authority.  Nothing in this surface triggers a Run.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.auth import generate_csrf_token, resolve_request_session
from app.utils.workbook_flag import env_flag
from app.workbook.registry import WORKBOOK

router = APIRouter()

#: Registry-bound field proven editable by ``WorkbookUpdateService.validate_field_update``
#: (``editable=True``, PCT, 0–100).  Kept in ONE place; the React client only learns
#: about it through the bootstrap payload.
CIT_FIELD_ID = "tax.assumptions.cit_rate_pct"

REACT_ASSET_VERSION = "ux01-v1"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "app", "templates", "v2"))


def react_poc_enabled() -> bool:
    """Flag contract: absent/empty → OFF (legacy behaviour unchanged)."""
    return env_flag("FINCO_MODEL_REACT_V1", default=False)


def _json(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})


# ───────────────────────────── page shell ─────────────────────────────

# NOTE: the bootstrap route is declared BEFORE the /{project_code} page route so
# the literal path can never be captured by the catch-all.


def _render_host(project_code: str) -> HTMLResponse:
    """Same-origin host page.  The React bundle reads its config from data attributes
    (never inline script/data, so no value crosses an HTML boundary unescaped)."""
    from urllib.parse import quote

    code = (project_code or "").strip()
    legacy_url = f"/v2/workbook?project={quote(code, safe='')}" if code else "/v2/workbook"
    html = _templates.get_template("react_poc.html").render(
        project_code=code,
        legacy_url=legacy_url,
        asset_version=REACT_ASSET_VERSION,
    )
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


def _render_fallback(request: Request, project_code: str) -> HTMLResponse:
    """Explicit fallback/rollback surface shown while the flag is OFF."""
    from urllib.parse import quote

    code = (project_code or "").strip()
    legacy_url = f"/v2/workbook?project={quote(code, safe='')}" if code else "/v2/workbook"
    html = _templates.get_template("react_poc_fallback.html").render(
        project_code=code, legacy_url=legacy_url, asset_version=REACT_ASSET_VERSION)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@router.get("/model-react", response_class=HTMLResponse)
async def react_poc_home(request: Request):
    if not react_poc_enabled():
        return _render_fallback(request, "")
    return _render_host("")


# ───────────────────────────── bootstrap projection ─────────────────────────────

def _bootstrap_disabled() -> JSONResponse:
    return _json({"ok": False, "code": "REACT_POC_DISABLED",
                  "message": "The React preview is disabled on this server."}, 404)


def _field_projection(pis: Any, editable: bool) -> dict[str, Any]:
    """Authorized read of the ONE canonical registry-bound input.

    The value is the real Working Copy draft value; editability is the project-level
    protected-reference gate.  Field rules (type, range) stay owned by the canonical
    validator invoked on Save — nothing about them is duplicated here.
    """
    from app.v2.grid_router import _display

    spec = WORKBOOK.field(CIT_FIELD_ID)
    typed = pis.get(CIT_FIELD_ID)
    return {
        "field_id": CIT_FIELD_ID,
        "label": spec.label,
        "unit": spec.unit,
        "min": spec.min_value,
        "max": spec.max_value,
        "decimals": spec.decimals,
        "editable": editable,
        "value": _display(typed),
    }


@router.get("/model-react/bootstrap")
async def react_poc_bootstrap(request: Request, project: str):
    """One coherent authorized snapshot for the React PoC page.

    Same capture/validation order as ``GET /workbook/outputs``: session → accessible
    project → ``PostRunRequestContext`` → Run integrity → statement projection →
    ``validate_current()``.  The mutation path is NOT here: the React client saves
    through the existing ``POST /v2/workbook/grid/save``.
    """
    if not react_poc_enabled():
        return _bootstrap_disabled()
    user = resolve_request_session(request)
    if user is None:
        return _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    from app.persistence.projects_repository import resolve_accessible_project
    from app.services.project_library_service import is_protected_reference

    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)

    outputs: dict[str, Any]
    try:
        from app.api.v1_1.institutional import get_run_integrity_checks
        from app.persistence.scenario_insight_reads import resolve_last_run_scenario
        from app.v2.output_workspace_projection import build_output_workspace_safe
        from app.v2.post_run_context import PostRunContextChanged, PostRunRequestContext
        from app.workbook.workbook_identity import WorkbookIdentityError

        context = PostRunRequestContext.capture(owner_id=owner, project_id=record.project_id)
        state, report = get_run_integrity_checks(owner, record.project_id, context=context)
        last_run_scenario = None
        if context.runtime_result is not None and context.freshness.state.value != "NOT_RUN":
            last_run_scenario = resolve_last_run_scenario(
                owner, record.project_id, getattr(context.workspace, "last_runtime_scenario_id", None)).label
        outputs = build_output_workspace_safe(
            runtime_result=context.runtime_result, workspace=context.workspace,
            freshness=context.freshness, last_run_scenario=last_run_scenario,
            integrity_report=report if state == "AVAILABLE" else None,
            statement_projection=context.projection.fs)
        payload = {
            "ok": True,
            "react_poc": {"version": REACT_ASSET_VERSION},
            "project": {"code": record.project_code,
                        # Canonical display name (ProjectRecord.project_name); the
                        # code is only the fallback, never a fabricated name.
                        "name": getattr(record, "project_name", None) or record.project_code,
                        "project_type": getattr(record, "project_type", None) or "",
                        "protected_reference": is_protected_reference(record)},
            "workbook": {"version": WORKBOOK.version,
                         "composite_hash": context.identity.composite_hash,
                         "scenario_id": context.workspace.active_scenario_id,
                         "scenario_name": context.workspace.active_scenario_name},
            "field": _field_projection(context.draft_inputs, editable=not is_protected_reference(record)),
            "csrf_token": generate_csrf_token(),
            "freshness": {"state": context.freshness.state.value,
                          "basis": context.freshness.source,
                          "has_runtime": context.freshness.has_runtime,
                          "is_stale": context.freshness.is_stale},
            "outputs": {"state": outputs.get("state"),
                        "identity": outputs.get("identity"),
                        "integrity": outputs.get("integrity"),
                        "status_dimensions": outputs.get("status_dimensions"),
                        "banner": outputs.get("banner") or "",
                        # P&L only — the PoC scope.  Cells carry ``v: null`` + text "—"
                        # for values the Run never produced; never a fabricated zero.
                        "pnl": (outputs.get("statements") or [None])[0]},
        }
        context.validate_current()
        return _json(payload)
    except (PostRunContextChanged, WorkbookIdentityError, PermissionError):
        return _json({
            "ok": False, "code": "WORKSPACE_UNAVAILABLE",
            "message": "Statements unavailable: the workspace changed while the response "
                       "was assembled. Reload to refresh.",
        }, 503)


@router.get("/model-react/{project_code}", response_class=HTMLResponse)
async def react_poc_page(request: Request, project_code: str):
    if not react_poc_enabled():
        return _render_fallback(request, project_code)
    return _render_host(project_code)
