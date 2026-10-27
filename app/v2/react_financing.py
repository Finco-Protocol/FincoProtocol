"""RC-M Lane C — read-only JSON adapter for the React Financing Studio.

A projection layer over the EXISTING canonical financing authorities; it writes nothing and computes nothing:

* the studio view is the same Debt-sheet context the Legacy workbook renders (``app.v2.router._build_debt_ctx``): the bankability
  view (``bankability_config.build_view``), the Senior pricing / DSCR authority modes, the reserve and sponsor presentations, the
  canonical capital stack (Two-Senior) and the persisted financing evidence — captured through one ``PostRunRequestContext`` and
  validated for coherence before the response is released;
* Sources & Uses is ``build_sources_uses_projection`` for the committed Last Run, fail-closed when its evidence is inconsistent.

Writes stay on the canonical per-field writer ``POST /v2/workbook/update`` (composite-hash CAS, CSRF, rate-lock gates, fee-authority
gates); the React editor takes its CAS tokens from the existing ``/model-react/fields/debt`` projection.  Nothing here persists.

Endpoint: ``GET /model-react/financing/studio``.  Feature flag: ``FINCO_MODEL_REACT_V1``.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.v2.react_poc_router import react_poc_enabled

router = APIRouter()
log = logging.getLogger(__name__)
_STUDIO_KEYS = ("bankability", "senior_pricing_mode", "senior_dscr_mode", "debt_actual_senior_keur_display",
                "debt_actual_gearing_pct_display", "financing_evidence", "reserve_view", "sponsor_view", "senior_detail_rows",
                "senior_lock_reason", "capital_stack")


def _json(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})


def _two_senior(f3: dict[str, Any]) -> dict[str, Any]:
    """Only the facts the studio needs about the Two-Senior bridge: whether it is available and active, never the raw state."""
    keys = ("available", "active", "scope", "status", "reason", "enabled")
    return {k: f3.get(k) for k in keys if k in f3}


@router.get("/model-react/financing/studio")
async def react_financing_studio(request: Request, project: str):
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    from app.auth import resolve_request_session
    from app.persistence.projects_repository import resolve_accessible_project
    from app.ui.protected_reference_service import is_protected_reference
    from app.v2.post_run_context import PostRunContextChanged, PostRunRequestContext
    from app.v2.react_workspace_router import _jsonable
    from app.workbook.workbook_identity import WorkbookIdentityError

    user = resolve_request_session(request)
    if user is None:
        return _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    try:
        import app.v2.router as legacy

        context = PostRunRequestContext.capture(owner_id=owner, project_id=record.project_id)
        context.require_scope(owner, record.project_id)
        debt = legacy._build_debt_ctx(context.inputs, context.workspace, projection=context.projection, context=context)
        studio = {key: debt.get(key) for key in _STUDIO_KEYS}
        studio["multisenior"] = _two_senior(debt.get("multisenior") or {})
        studio["sources_uses"] = _sources_uses(context, owner, record)
        identity = {"content_hash": context.identity.composite_hash, "workbook_version": context.identity.workbook_version,
                    "scenario_id": context.workspace.active_scenario_id, "scenario_name": context.workspace.active_scenario_name}
        freshness = context.freshness.state.value
        context.validate_current()
    except (PostRunContextChanged, WorkbookIdentityError, PermissionError):
        return _json({"ok": False, "code": "WORKSPACE_UNAVAILABLE",
                      "message": "The workspace changed while the financing view was assembled. Reload to refresh."}, 503)
    except Exception:  # noqa: BLE001 - fail closed; the classic workbook stays authoritative
        log.exception("react_financing: studio projection failed project=%s", project)
        return _json({"ok": False, "code": "FINANCING_UNAVAILABLE",
                      "message": "The financing view could not be projected. Reload to refresh."}, 503)
    return _json({
        "ok": True, "project": {"code": record.project_code, "protected_reference": is_protected_reference(record)},
        "editable": not is_protected_reference(record), "freshness": freshness, "identity": identity,
        "save": {"field_id": "debt.bankability.configuration", "tokens_from": "/v2/model-react/fields/debt"},
        **_jsonable(studio),
    })


def _sources_uses(context, owner: str, record) -> dict[str, Any]:
    """Sources & Uses of the committed Last Run (never the Working Copy); a typed unavailable state when evidence is inconsistent."""
    from app.v2.financing_sources_uses_projection import FinancingEvidenceInvalid, build_sources_uses_projection

    state = context.freshness.state.value
    workspace = context.workspace
    try:
        view = build_sources_uses_projection(
            runtime_result=context.runtime_result, integrity_evidence=workspace.last_integrity_evidence,
            working_financing=None, working_capex=None, freshness=state, run_kind="LAST_RUN",
            expected_snapshot_id=getattr(context.runtime_result, "snapshot_id", None) or None,
            expected_composite_hash=workspace.last_runtime_composite_hash,
            expected_scenario_id=workspace.last_runtime_scenario_id)
    except (FinancingEvidenceInvalid, ValueError, TypeError, AttributeError) as exc:
        return {"available": False, "reason": "Financing evidence for the last Run is unavailable or inconsistent.",
                "code": type(exc).__name__}
    return {"available": True, "view": view}
