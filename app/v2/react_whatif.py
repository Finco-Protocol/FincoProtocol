"""RC-UX B1 (Audit A GAP-R4) — read-only JSON adapter for the React What-if panel.

A presentation/adapter layer over the EXISTING Q4 finding-to-What-if authority (``app.v2.whatif``).  It adds NO economic, scenario or
persistence authority and writes nothing:

* ``GET /model-react/whatif/options`` — which findings of the saved Run may seed a What-if, with the current value of the one
  assumption each is proven to map to.  Eligibility is ``whatif.display_eligibility`` (supported verticals, scenario-editable field,
  no competing Two-Senior editor, valid current value) over the Model Quality finding of the saved Run.
* ``GET /model-react/whatif/preview`` — ``whatif.preview``: strictly read-only; returns the original and proposed assumption, the delta, the
  finding it came from and the signed, resource-bound confirmation token.  It is NOT a Run and shows no projected KPI.

Creating the scenario is the EXISTING ``POST /v2/workbook/whatif/commit`` (signed token, exclusive transaction, replay and conflict
checks) which the React panel posts to directly; the scenario is created ``NOT_RUN`` and nothing is run.  Comparing needs committed Runs
of both scenarios and is done in Run history & compare.

Feature flag: ``FINCO_MODEL_REACT_V1``.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import resolve_request_session
from app.v2.react_poc_router import react_poc_enabled

router = APIRouter()

REQUEST_HEADER = "x-finco-react-request"
PREVIEW_LIMITS = {"proposed": 100, "name": 80}


def _json(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "private, no-store"})


def _fail(status: int, code: str, message: str) -> JSONResponse:
    return _json({"ok": False, "code": code, "message": message + " Nothing was changed."}, status)


def _scope(request: Request, project: str, *, header: bool):
    """(record, owner, ws) or a ready JSONResponse: flag, header, session, own editable project, workspace."""
    if not react_poc_enabled():
        return None, None, None, _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    if header and request.headers.get(REQUEST_HEADER) != "1":
        return None, None, None, _fail(400, "REQUEST_HEADER_REQUIRED", "This preview can only be started from the FINCO Model workspace.")
    user = resolve_request_session(request)
    if user is None:
        return None, None, None, _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.project_library_service import is_protected_reference

    record, owner = resolve_accessible_project(user.user_id, (project or "").strip())
    if record is None:
        return None, None, None, _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    # The first version never writes through a shared project (same rule as the Q4 routes).
    if (owner != user.user_id or is_protected_reference(record) or getattr(record, "archived", False)
            or getattr(record, "is_readonly", False) or record.project_role not in ("working_copy", "user_project")):
        return None, None, None, _fail(403, "Q4_PROJECT_READ_ONLY", "This project cannot be edited.")
    ws = get_workspace_state(user_id=owner, project_id=record.project_id)
    if ws is None:
        return None, None, None, _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    return record, owner, ws, None


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if f == f and abs(f) != float("inf") else None


def _candidates(record, owner: str, ws) -> dict[str, Any]:
    from app.workbook.input_set import ProjectInputSet
    from app.workbook.registry import WORKBOOK
    from app.workbook.runtime_authority import resolve_runtime_freshness
    from app.workbook.workbook_identity import WorkbookIdentityError, assemble_consistent_for_get
    from app.v2 import whatif

    try:
        identity = assemble_consistent_for_get(user_id=owner, project_id=record.project_id, workbook_version=WORKBOOK.version)
        state = resolve_runtime_freshness(ws, current_composite_hash=identity.composite_hash).state.value
    except (WorkbookIdentityError, ValueError):
        return {"state": "UNKNOWN", "reason": "Q4_WORKSPACE_UNAVAILABLE", "items": []}
    if state == "NOT_RUN":
        return {"state": state, "reason": "Q4_REQUIRES_Q1_COMMITTED_FINDING", "items": []}
    pis = ProjectInputSet.from_snapshot(ws.draft_snapshot)
    seen: set[str] = set()
    items = []
    for check_id, (path, field_id, key) in whatif.CANDIDATES.items():
        if field_id in seen:                    # QM-SD-004 and QM-SD-007 both map to the target DSCR: offered once
            continue
        seen.add(field_id)
        try:
            finding = whatif._quality_check(ws, check_id, state)
            status = finding.status.value
            title = finding.title
        except Exception:                      # noqa: BLE001 - an unreadable finding is simply not offered
            continue
        eligible, reason = whatif.display_eligibility(check_id=check_id, check_status=status, project_type=record.project_type or "",
                                                      snapshot=ws.draft_snapshot)
        spec = WORKBOOK.field(field_id)
        original = _number(pis.get(field_id))
        items.append({"check_id": check_id, "finding": title, "finding_status": status, "field_id": field_id,
                      "assumption": spec.label, "unit": spec.unit or "", "original": original,
                      "eligible": bool(eligible), "reason": "" if eligible else reason})
    return {"state": state, "reason": "", "items": items}


@router.get("/model-react/whatif/options")
async def react_whatif_options(request: Request, project: str = ""):
    record, owner, ws, refused = _scope(request, project, header=False)
    if refused is not None:
        return refused
    data = _candidates(record, owner, ws)
    return _json({"ok": True, "run_state": data["state"], "reason": data["reason"], "candidates": data["items"],
                  "semantics": {"preview_is_a_run": False, "creates_scenario_not_run": True,
                                "note": "A What-if changes one assumption in a new scenario. Nothing is calculated until you run that scenario."}})


@router.get("/model-react/whatif/preview")
async def react_whatif_preview(request: Request, project: str = "", check_id: str = "", proposed_value: str = "", scenario_name: str = ""):
    record, owner, ws, refused = _scope(request, project, header=True)
    if refused is not None:
        return refused
    if set(request.query_params) - {"project", "check_id", "proposed_value", "scenario_name"}:
        return _fail(400, "INVALID_QUERY", "Unexpected query parameters.")
    if len(proposed_value) > PREVIEW_LIMITS["proposed"] or len(check_id) > 50 or len(scenario_name) > PREVIEW_LIMITS["name"] + 20:
        return _fail(422, "Q4_INPUT_TOO_LONG", "A value is too long.")
    from app.v2.whatif import Q4Rejected, preview

    try:
        result = preview(owner=owner, project_id=record.project_id, project_type=record.project_type or "", check_id=check_id,
                         proposed_raw=proposed_value, scenario_name=scenario_name)
    except Q4Rejected as exc:
        return _fail(exc.status, exc.code, "The What-if could not be prepared.")
    except Exception:                          # noqa: BLE001 - the authority is unavailable: nothing was prepared
        return _fail(503, "Q4_PREVIEW_AUTHORITY_UNAVAILABLE", "The What-if could not be prepared.")
    return _json({"ok": True, "preview": {
        "finding": {"id": result["finding_id"], "status": result["finding_status"], "source": result["evidence_source"]},
        "assumption": {"field_id": result["field_id"], "unit": result["unit"], "original": result["original"],
                       "proposed": result["proposed"], "delta": result["delta"]},
        "scenario_name": result["name"], "stale": bool(result["stale"]),
        "last_run_snapshot": result["snapshot_id"], "token": result["token"],
        "commit": {"url": "/v2/workbook/whatif/commit"},
        "semantics": {"is_a_run": False, "shows_projected_kpi": False,
                      "note": "Not an optimised result or lender decision. No projected KPI, covenant compliance or Quality score exists until the new scenario is run."}}})
