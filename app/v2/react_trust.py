"""RC-UX Addendum A — JSON adapter for the React Trust evidence (Run certificate and reference regression).

Replaces the two classic HTML fragments ``/v2/workbook/trust/certificate`` and ``/v2/workbook/trust/validation`` that the Trust section used
to link to.  It adds NO validation, signing or persistence authority of its own: each response is the section dict that the SAME canonical
builders return to the classic fragments (``app.ui.trust_pack.build_certificate_fragment`` / ``build_validation_fragment``), projected through
an explicit allow-list.

* ``GET /model-react/trust/certificate?project=CODE`` — issues nothing new beyond what the classic fragment did on the same explicit request
  (the signed certificate of the committed Last Run); never called while the page renders.
* ``GET /model-react/trust/validation?project=CODE``  — the Reference Regression Check, run on the same bounded model thread behind the
  same admission gate as the classic fragment.  It is NOT a validation of the project or its Run, and the response says so.

Both require the feature flag, the React request header (so a plain link or prefetch can never trigger them), a session and an accessible
project.  Unavailable stays unavailable: it is never reported as a pass and never as zero.  Feature flag: ``FINCO_MODEL_REACT_V1``.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import resolve_request_session
from app.v2.react_poc_router import react_poc_enabled

router = APIRouter()

REQUEST_HEADER = "x-finco-react-request"
CERTIFICATE_KEYS = ("state", "reason", "schema_version", "issuer", "issued_at", "snapshot_id", "composite_hash", "composite_hash_short",
                    "workbook_version", "engine_version", "active_scenario_id", "effective_input_status", "effective_input_reason",
                    "effective_input_unbound", "run_origin", "key_id", "payload_digest", "signature_algorithm", "not_verify", "authority")
VALIDATION_KEYS = ("state", "validation_state", "passed", "framework_passed", "product_reconciled", "pass_count", "fail_count",
                   "gap_count", "authority")
GAP_KEYS = ("name", "detail")


def _json(payload: dict[str, Any], status: int = 200, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "private, no-store", **(headers or {})})


def _pick(source: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: source.get(k) for k in keys}


def _scope(request: Request, project: str):
    """(record, owner) or a ready JSONResponse: flag, React header, session, accessible project."""
    if not react_poc_enabled():
        return None, None, _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    if request.headers.get(REQUEST_HEADER) != "1":
        return None, None, _json({"ok": False, "code": "REQUEST_HEADER_REQUIRED",
                                  "message": "This evidence can only be requested from the FINCO Model workspace."}, 400)
    user = resolve_request_session(request)
    if user is None:
        return None, None, _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    from app.persistence.projects_repository import resolve_accessible_project

    record, owner = resolve_accessible_project(user.user_id, (project or "").strip())
    if record is None:
        return None, None, _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    return record, owner, None


@router.get("/model-react/trust/certificate")
async def react_trust_certificate(request: Request, project: str = ""):
    record, owner, refused = _scope(request, project)
    if refused is not None:
        return refused
    from app.ui.trust_pack import build_certificate_fragment

    try:
        section = build_certificate_fragment(owner, record.project_id)
    except Exception:  # noqa: BLE001 - the classic fragment degrades to the same typed unavailable state
        section = {"state": "UNAVAILABLE", "reason": "CERTIFICATE_UNAVAILABLE", "not_verify": True}
    return _json({"ok": True, "project": {"code": record.project_code}, "certificate": _pick(section, CERTIFICATE_KEYS)})


@router.get("/model-react/trust/validation")
async def react_trust_validation(request: Request, project: str = ""):
    record, owner, refused = _scope(request, project)
    if refused is not None:
        return refused
    from app.persistence.workspace_repository import get_workspace_state

    ws = get_workspace_state(owner, record.project_id)
    if ws is None or not ws.any_run_committed:
        return _json({"ok": True, "project": {"code": record.project_code},
                      "validation": {"state": "UNAVAILABLE", "reason": "COMMITTED_LAST_RUN_REQUIRED", "gaps": []}})
    # The Reference Regression Check is model work: bounded thread offload behind the shared admission gate, never on the event loop.
    from app.runtime.model_execution import BUSY_MESSAGE, ModelExecutionBusy, run_model_thread
    from app.ui.trust_pack import build_validation_fragment

    try:
        section = await run_model_thread(build_validation_fragment, owner, record.project_id)
    except ModelExecutionBusy:
        return _json({"ok": False, "code": "MODEL_BUSY", "message": BUSY_MESSAGE}, 429, {"Retry-After": "5", "X-Finco-Model-Busy": "1"})
    except Exception:  # noqa: BLE001
        section = {"state": "UNAVAILABLE"}
    validation = _pick(section, VALIDATION_KEYS)
    validation["gaps"] = [_pick(g, GAP_KEYS) for g in (section.get("gaps") or []) if isinstance(g, dict)]
    return _json({"ok": True, "project": {"code": record.project_code}, "validation": validation})
