"""Reviewed standalone BESS router AST; independent of the exact Git pin.

The literal tree fixes the two decorated routes, auth/flag refusal, same-origin
checks, strict body fields, stream bound, request/session/purpose-bound CSRF,
capability checks before AND after parsing, error redaction and non-persistence.
No API registration aliases, imports, helpers or extra calls are admitted.
Comments and formatting have no structural meaning; the separate Git seal still
rejects unsigned bytes. Never imports an app module or a predecessor cohort.
"""
import ast

REVIEWED_ROUTER = r'''
"""Authenticated, bounded, non-persisting native Storage setup validation."""
import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from app.auth import resolve_request_session, validate_csrf_token
from app.services.bess_setup_preview import capability, preview
from app.workbook.financing_csrf import extract_bound_token, issue_token
from domain.bess.contracts import BessInputError

router = APIRouter()
PURPOSE = "on-bess-01-preview"
MAX_BYTES = 2_100_000


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    csrf_token: str = Field(max_length=512)
    native_json: str = Field(max_length=2_001_000)
    edits: dict[str, str] = Field(default_factory=dict, max_length=9)


def _json(payload, status=200):
    return JSONResponse({"persisted": False, "financial_calculation_count": 0, **payload},
                        status_code=status, headers={"Cache-Control": "no-store"})


@router.get("/model-react/new-project/bess-options")
async def bess_options(request: Request):
    from app.v2.react_poc_router import react_poc_enabled
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    if resolve_request_session(request) is None:
        return _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    import uuid
    request_id = uuid.uuid4().hex
    return _json({"ok": True, "capability": capability(), "request_id": request_id,
                  "csrf_token": issue_token(request, request_id, purpose=PURPOSE)})


@router.post("/model-react/new-project/bess-preview")
async def bess_preview(request: Request):
    from app.v2.react_poc_router import react_poc_enabled
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    if resolve_request_session(request) is None:
        return _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    origin = request.headers.get("origin")
    if ((origin and origin.rstrip("/") != str(request.base_url).rstrip("/"))
            or request.headers.get("sec-fetch-site") == "cross-site"):
        return _json({"ok": False, "code": "CSRF_INVALID"}, 403)
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        return _json({"ok": False, "code": "BESS_JSON_REQUIRED"}, 415)
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_BYTES:
            return _json({"ok": False, "code": "BESS_REQUEST_TOO_LARGE"}, 413)
    try:
        body = PreviewBody.model_validate_json(bytes(data))
    except ValidationError:
        return _json({"ok": False, "code": "BESS_SETUP_BODY_INVALID"}, 422)
    if not validate_csrf_token(extract_bound_token(request, body.request_id, body.csrf_token, purpose=PURPOSE)):
        return _json({"ok": False, "code": "CSRF_INVALID"}, 403)
    cap = capability()
    if not cap["preview_supported"]:
        return _json({"ok": False, "code": "BESS_PREVIEW_UNAVAILABLE", "capability": cap}, 409)
    try:
        result = await run_in_threadpool(preview, body.native_json, body.edits)
    except BessInputError as exc:
        # Native errors can include submitted keys. Do not reflect user document
        # fragments, source identities or unbounded parser details to the UI/log.
        code = str(exc).split(":", 1)[0]
        if not re.fullmatch(r"BESS_[A-Z_]+", code):
            code = "BESS_NATIVE_SCHEMA"
        messages = {
            "BESS_DURATION": "Duration cannot match usable MWh / discharge MW within the native schema's precision. Check these quantities; no value was rounded into acceptance.",
            "BESS_RTE": "Round-trip efficiency must equal charge efficiency times discharge efficiency. Enter fractions explicitly.",
            "BESS_CAPACITY": "Check usable versus installed energy and the explicit state-of-charge range.",
            "BESS_EFFICIENCY": "Charge efficiency, discharge efficiency and minimum state of health must be positive fractions.",
            "BESS_POLICY": "The native schema requires standalone grid BESS, EUR/MWh and its explicit UTC hourly and physical conventions.",
            "BESS_DISPATCH": "Supply the complete hourly timeline or exactly 24 fixed daily UTC dispatch rows.",
            "BESS_HORIZON": "The declared end must follow the start within the native hourly horizon.",
        }
        message = messages.get(code, "Native configuration validation failed. Check explicit units, battery relationships, dates and dispatch completeness.")
        if code == "BESS_NUMBER":
            from app.services.bess_setup_preview import EDIT_FIELDS
            label = next((label for name, label, _unit in EDIT_FIELDS if re.search(r"\b" + name + r"\b", str(exc))), "Numeric input")
            message = label + ": enter a finite numeric value in the stated unit and native range."
        return _json({"ok": False, "code": code,
                      "message": message}, 422)
    # Recheck availability after parsing; no preview grants financial admission.
    cap = capability()
    if not cap["preview_supported"]:
        return _json({"ok": False, "code": "BESS_PREVIEW_UNAVAILABLE", "capability": cap}, 409)
    return _json({"ok": True, "preview": result, "capability": cap})
'''
REGISTRATION = "from app.v2.bess_setup_router import router as _bess_setup_router\nrouter.include_router(_bess_setup_router)\n"


def violations(source, parent_source, baseline_parent):
    try:
        if ast.dump(ast.parse(source)) != ast.dump(ast.parse(REVIEWED_ROUTER)):
            return ['unreviewed BESS route/import/schema/gate/call/response structure']
        original = ast.parse(baseline_parent).body
        if not isinstance(original[-1], ast.AsyncFunctionDef) or original[-1].name != 'react_poc_page':
            return ['unexpected accepted parent catch-all']
        expected = original[:-1] + ast.parse(REGISTRATION).body + original[-1:]
        if ast.dump(ast.parse(parent_source)) != ast.dump(ast.Module(body=expected, type_ignores=[])):
            return ['unreviewed parent router registration']
        return []
    except (SyntaxError, ValueError, TypeError):
        return ['invalid router source']
