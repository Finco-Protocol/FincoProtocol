"""FINCO Public Reference Verify — anonymous public routes for Solar reference.

These routes require NO authentication. They expose the canonical Solar reference
model certificate, assumptions, outputs, issuer signature, and standalone
verification instructions for any outsider to independently verify FINCO's
published model results.

Routes (all anonymous — no auth required):
  GET /verify/reference/solar-reference-a/certificate.json  — Run certificate
  GET /verify/reference/solar-reference-a/assumptions.json  — Canonical inputs
  GET /verify/reference/solar-reference-a/outputs.json      — Canonical outputs
  GET /verify/reference/solar-reference-a/signature.json    — Issuer signature
  GET /verify/reference/solar-reference-a/public-key.pem    — Issuer public key
  GET /verify/reference/solar-reference-a/verify.py         — Standalone verifier
  GET /verify/reference/solar-reference-a                   — HTML instructions

Private workbook run certificates (/verify/run/{project_code}) remain
auth-protected in app/verify/router.py.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

logger = logging.getLogger(__name__)
router = APIRouter()

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from fastapi.templating import Jinja2Templates
_templates = Jinja2Templates(directory=os.path.join(_APP_DIR, "templates"))

_ASSET_ID = "solar-reference-a"
_BASE_PATH = f"/verify/reference/{_ASSET_ID}"


def _build_reference_package():
    """Load reference certificate + assumptions + outputs. Pure sync helper."""
    from app.verify.reference_certificate import (
        build_solar_reference_package,
        ReferenceCertificateUnavailableError,
    )
    try:
        return build_solar_reference_package()
    except ReferenceCertificateUnavailableError:
        raise
    except Exception as exc:
        from app.verify.reference_certificate import ReferenceCertificateUnavailableError
        raise ReferenceCertificateUnavailableError(
            f"Unexpected error building reference package: {exc}",
            code="INTERNAL_ERROR",
        ) from exc


def _sign_certificate(certificate: dict) -> dict | None:
    """Sign certificate with issuer key. Returns None if key is not configured."""
    from app.verify.issuer import sign_certificate, IssuerKeyNotConfigured
    try:
        return sign_certificate(certificate)
    except IssuerKeyNotConfigured:
        return None
    except Exception:
        logger.exception("Certificate signing failed")
        return None


@router.get(f"{_BASE_PATH}/certificate.json")
async def reference_certificate_json(request: Request):
    """FINCO Solar Reference — certificate JSON (anonymous)."""
    try:
        certificate, _assumptions, _outputs = await run_in_threadpool(_build_reference_package)
    except Exception as exc:
        logger.exception("Reference certificate build failed")
        return JSONResponse(
            {"error": "certificate_unavailable", "reason": str(exc)},
            status_code=503,
        )
    return JSONResponse(certificate)


@router.get(f"{_BASE_PATH}/assumptions.json")
async def reference_assumptions_json(request: Request):
    """FINCO Solar Reference — canonical assumptions JSON (anonymous)."""
    try:
        _certificate, assumptions, _outputs = await run_in_threadpool(_build_reference_package)
    except Exception as exc:
        logger.exception("Reference assumptions build failed")
        return JSONResponse(
            {"error": "assumptions_unavailable", "reason": str(exc)},
            status_code=503,
        )
    return JSONResponse(assumptions)


@router.get(f"{_BASE_PATH}/outputs.json")
async def reference_outputs_json(request: Request):
    """FINCO Solar Reference — canonical outputs JSON (anonymous)."""
    try:
        _certificate, _assumptions, outputs = await run_in_threadpool(_build_reference_package)
    except Exception as exc:
        logger.exception("Reference outputs build failed")
        return JSONResponse(
            {"error": "outputs_unavailable", "reason": str(exc)},
            status_code=503,
        )
    return JSONResponse(outputs)


@router.get(f"{_BASE_PATH}/signature.json")
async def reference_signature_json(request: Request):
    """FINCO Solar Reference — issuer signature JSON (anonymous)."""
    try:
        certificate, _assumptions, _outputs = await run_in_threadpool(_build_reference_package)
    except Exception as exc:
        logger.exception("Reference certificate build failed for signature")
        return JSONResponse(
            {"error": "certificate_unavailable", "reason": str(exc)},
            status_code=503,
        )

    signature = await run_in_threadpool(_sign_certificate, certificate)
    if signature is None:
        return JSONResponse(
            {
                "error": "issuer_key_not_configured",
                "reason": (
                    "Issuer signing key is not configured in this environment. "
                    "Set FINCO_ISSUER_PRIVATE_KEY_HEX to enable issuer signatures."
                ),
            },
            status_code=503,
        )
    return JSONResponse(signature)


@router.get(f"{_BASE_PATH}/public-key.pem", response_class=PlainTextResponse)
async def reference_public_key_pem(request: Request):
    """FINCO Solar Reference — issuer Ed25519 public key in PEM format (anonymous)."""
    from app.verify.issuer import get_public_key_pem, IssuerKeyNotConfigured
    try:
        pem = await run_in_threadpool(get_public_key_pem)
    except IssuerKeyNotConfigured:
        return PlainTextResponse(
            "Issuer key not configured. Set FINCO_ISSUER_PRIVATE_KEY_HEX.",
            status_code=503,
        )
    return PlainTextResponse(pem, media_type="application/x-pem-file")


@router.get(f"{_BASE_PATH}/verify.py", response_class=PlainTextResponse)
async def reference_verify_script(request: Request):
    """FINCO Solar Reference — canonical standalone Python verifier script (anonymous).

    Serves the canonical verifier from tools/verify_reference_package.py — single source.
    """
    script = _read_canonical_verifier_script()
    return PlainTextResponse(script, media_type="text/x-python")


def _read_canonical_verifier_script() -> str:
    """Read the canonical standalone verifier from tools/verify_reference_package.py."""
    repo_root = os.path.dirname(_APP_DIR)
    script_path = os.path.join(repo_root, "tools", "verify_reference_package.py")
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError as exc:
        logger.error("Cannot read canonical verifier script at %s: %s", script_path, exc)
        return f"# ERROR: canonical verifier script not available: {exc}\n"


@router.get(f"{_BASE_PATH}", response_class=HTMLResponse)
async def reference_verify_html(request: Request):
    """FINCO Solar Reference — human-readable verification instructions (anonymous)."""
    from app.auth import resolve_request_session
    user = resolve_request_session(request)
    return _templates.TemplateResponse(
        request=request,
        name="verify/reference_verify.html",
        context={
            "user": user,
            "asset_id": _ASSET_ID,
            "base_path": _BASE_PATH,
            "proto_active_page": "verify",
        },
    )


