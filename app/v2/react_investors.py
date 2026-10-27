"""RC-M Lane C — read-only JSON adapter for the React Investor & Sponsor agreement panel.

A projection over the EXISTING F4 authorities; it writes nothing and computes nothing:

* the agreement terms, the Run-bound investor evidence (validated by ``investor_f4.validate_evidence`` against the Run's owner /
  project / snapshot / composite hash / scenario) and the actual equity funding are exactly what the Legacy investor workspace loads
  (``investor_f4_router._load``);
* the sponsor / shareholder-loan facts are the read-only ``build_sponsor_view`` presentation of the typed financing inputs and the
  committed Run.  No SHL control is editable under the released authority, and none is exposed here.

The Save stays the canonical ``POST /v2/workbook/investor/agreement`` (session CSRF, composite-hash CAS, agreement-version CAS,
ownership / protected-reference gates, all in ``save_agreement``); this module only issues the page token that route already uses.

Endpoint: ``GET /model-react/investors/agreement``.  Feature flag: ``FINCO_MODEL_REACT_V1``.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.v2.react_poc_router import react_poc_enabled

router = APIRouter()
log = logging.getLogger(__name__)


def _json(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})


def _workflow(view: dict[str, Any]) -> dict[str, str]:
    """Where the saved agreement stands relative to the Last Run (mirrors the Legacy S7-07 states; never claims more)."""
    terms, evidence = view["terms"], view["evidence"]
    recorded = evidence["agreement"] if evidence else None
    if terms is None:
        return {"state": "NONE", "text": "No working agreement is saved. Investor allocations exist only for Runs that record a saved agreement."}
    same = recorded and recorded["agreement_id"] == terms.agreement_id and recorded["version"] == terms.version
    label = f"Saved agreement {terms.agreement_id} v{terms.version}"
    if same and view["state"] == "CURRENT":
        return {"state": "INCORPORATED", "text": f"{label} is incorporated in the Last Run."}
    if same:
        return {"state": "INCORPORATED_STALE", "text": f"{label} was recorded in the Last Run, but other inputs have changed since: Run again to refresh the investor evidence."}
    if recorded:
        return {"state": "SAVED_NOT_RUN", "text": f"{label} is not yet in a Run. The Last Run used {recorded['agreement_id']} v{recorded['version']}. Run to apply the saved agreement."}
    return {"state": "SAVED_NOT_RUN", "text": f"{label} has not been incorporated in any canonical Run. Run to produce investor evidence."}


@router.get("/model-react/investors/agreement")
async def react_investor_agreement(request: Request, project: str):
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    from fastapi.responses import HTMLResponse

    from app.auth import generate_csrf_token, resolve_request_session
    from app.persistence.run_history_repository import RunHistoryError
    from app.v2.investor_f4_router import _load
    from app.v2.post_run_context import PostRunContextChanged
    from app.v2.react_workspace_router import _jsonable
    from app.workbook.workbook_identity import WorkbookIdentityError

    if resolve_request_session(request) is None:
        return _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    try:
        view, error = _load(request, project)
    except (ValueError, TypeError, KeyError, PermissionError, RunHistoryError, WorkbookIdentityError, PostRunContextChanged):
        return _json({"ok": False, "code": "INVESTOR_EVIDENCE_UNAVAILABLE",
                      "message": "Investor evidence or the workspace identity changed. Reload to refresh."}, 503)
    if isinstance(error, HTMLResponse) or view is None:
        status = getattr(error, "status_code", 404)
        return _json({"ok": False, "code": "PROJECT_NOT_FOUND" if status == 404 else "UNAVAILABLE"}, status)
    try:
        from app.v2.financing_projection import build_sponsor_view

        context = view["context"]
        fin = None
        try:
            fin = context.inputs.to_projectinputs().financing
        except Exception:  # noqa: BLE001 - the sponsor presentation then reports "unavailable", never a guessed value
            fin = None
        sponsor = build_sponsor_view(fin, context.runtime_result)
        workflow = _workflow(view)
        terms = view["terms"]
        payload = {
            "ok": True,
            "project": {"code": view["project_code"]},
            "editable": bool(view["editable"]), "state": view["state"],
            "identity": {"content_hash": context.identity.composite_hash, "workbook_version": context.identity.workbook_version,
                         "scenario_name": context.workspace.active_scenario_name},
            "terms": None if terms is None else terms.document(),
            "workflow": workflow,
            "evidence": None if view["evidence"] is None else {
                "snapshot_id": view["snapshot_id"], "agreement": view["evidence"]["agreement"],
                "investors": view["evidence"]["investors"], "roc_status": view["evidence"].get("roc_status"),
                "nav_status": view["evidence"].get("nav_status")},
            "unavailable": view["unavailable"],
            "funding": view["funding"],
            "sponsor": sponsor,
            "save": {"url": "/v2/workbook/investor/agreement", "csrf_token": generate_csrf_token(),
                     "next_version": (terms.version + 1) if terms else 1, "saved_agreement_id": terms.agreement_id if terms else ""},
            "export_url": f"/v2/workbook/investor/export?project={view['project_code']}",
            "not_released": ["Return-of-capital ordering", "Preferences and carry", "NAV / terminal valuation",
                             "Shareholder-loan lender allocation", "Waterfall mechanisms beyond residual common equity"],
        }
        context.validate_current()
    except (ValueError, TypeError, KeyError, PermissionError, RunHistoryError, WorkbookIdentityError, PostRunContextChanged):
        return _json({"ok": False, "code": "INVESTOR_EVIDENCE_UNAVAILABLE",
                      "message": "Investor evidence or the workspace identity changed. Reload to refresh."}, 503)
    except Exception:  # noqa: BLE001
        log.exception("react_investors: projection failed project=%s", project)
        return _json({"ok": False, "code": "INVESTOR_UNAVAILABLE", "message": "The investor view could not be projected. Reload to refresh."}, 503)
    return _json(_jsonable(payload))
