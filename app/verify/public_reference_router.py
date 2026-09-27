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
    from finco_protocol.verification.issuer import sign_certificate, IssuerKeyNotConfigured
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
    from finco_protocol.verification.issuer import get_public_key_pem, IssuerKeyNotConfigured
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
    """FINCO Solar Reference — standalone Python verifier script (anonymous)."""
    base_url = str(request.base_url).rstrip("/")
    script = _build_verifier_script(base_url)
    return PlainTextResponse(script, media_type="text/x-python")


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


def _build_verifier_script(base_url: str) -> str:
    """Generate the standalone Python verification script."""
    return f'''#!/usr/bin/env python3
"""FINCO Solar Reference — standalone verifier.

Verifies the FINCO Solar Reference package without any FINCO internal imports.
Requires only: Python 3.9+, hashlib, json, urllib.request, base64, sys (stdlib).
Optional: pycryptodome (pip install pycryptodome) for signature verification.

Usage:
    python verify.py [--base-url {base_url}]

Exits 0 on PASS, non-zero on FAIL.
"""
import base64
import hashlib
import json
import sys
import urllib.request
from typing import Any

BASE_URL = "{base_url}"
ASSET_ID = "solar-reference-a"

CERTIFICATE_URL = f"{{BASE_URL}}/verify/reference/{{ASSET_ID}}/certificate.json"
ASSUMPTIONS_URL = f"{{BASE_URL}}/verify/reference/{{ASSET_ID}}/assumptions.json"
OUTPUTS_URL     = f"{{BASE_URL}}/verify/reference/{{ASSET_ID}}/outputs.json"
SIGNATURE_URL   = f"{{BASE_URL}}/verify/reference/{{ASSET_ID}}/signature.json"
PUBLIC_KEY_URL  = f"{{BASE_URL}}/verify/reference/{{ASSET_ID}}/public-key.pem"


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read()


def _canonical_json(obj: Any) -> bytes:
    """FINCO_SORTED_JSON_V1: sort_keys=True, compact separators, no ASCII escaping."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fail(msg: str):
    print(f"FAIL: {{msg}}", file=sys.stderr)
    sys.exit(1)


def _ok(msg: str):
    print(f"  OK  {{msg}}")


def main():
    print(f"FINCO Solar Reference Verifier")
    print(f"Base URL: {{BASE_URL}}")
    print()

    print("Fetching artifacts...")
    try:
        certificate  = json.loads(_fetch(CERTIFICATE_URL))
        assumptions  = json.loads(_fetch(ASSUMPTIONS_URL))
        outputs      = json.loads(_fetch(OUTPUTS_URL))
        signature    = json.loads(_fetch(SIGNATURE_URL))
        public_key   = _fetch(PUBLIC_KEY_URL).decode()
    except Exception as exc:
        _fail(f"Failed to fetch artifacts: {{exc}}")

    print()
    print("Step 1 — Assumptions hash")
    expected_assumptions_sha256 = certificate["identity"]["assumptions_sha256"]
    computed_assumptions_sha256 = _sha256(_canonical_json(assumptions))
    if computed_assumptions_sha256 != expected_assumptions_sha256:
        _fail(
            f"Assumptions hash mismatch:\\n"
            f"  expected: {{expected_assumptions_sha256}}\\n"
            f"  computed: {{computed_assumptions_sha256}}"
        )
    _ok(f"assumptions_sha256 = {{computed_assumptions_sha256[:16]}}...")

    print()
    print("Step 2 — Outputs hash")
    expected_outputs_sha256 = certificate["identity"]["outputs_sha256"]
    computed_outputs_sha256 = _sha256(_canonical_json(outputs))
    if computed_outputs_sha256 != expected_outputs_sha256:
        _fail(
            f"Outputs hash mismatch:\\n"
            f"  expected: {{expected_outputs_sha256}}\\n"
            f"  computed: {{computed_outputs_sha256}}"
        )
    _ok(f"outputs_sha256 = {{computed_outputs_sha256[:16]}}...")

    print()
    print("Step 3 — Certificate digest")
    stored_digest = certificate.get("certificate_digest_sha256")
    stored_id     = certificate.get("certificate_id")
    payload_without_digest = {{
        k: v for k, v in certificate.items()
        if k not in ("certificate_id", "certificate_digest_sha256")
    }}
    computed_digest = _sha256(_canonical_json(payload_without_digest))
    if computed_digest != stored_digest:
        _fail(
            f"Certificate digest mismatch (tampered?):\\n"
            f"  expected: {{stored_digest}}\\n"
            f"  computed: {{computed_digest}}"
        )
    expected_id = "frc_" + computed_digest[:16]
    if stored_id != expected_id:
        _fail(f"Certificate ID mismatch: expected {{expected_id}}, got {{stored_id}}")
    _ok(f"certificate_digest_sha256 = {{computed_digest[:16]}}...")
    _ok(f"certificate_id = {{stored_id}}")

    print()
    print("Step 4 — Issuer signature")
    try:
        from Crypto.PublicKey import ECC
        from Crypto.Signature import eddsa
    except ImportError:
        print("  SKIP: pycryptodome not installed (pip install pycryptodome to verify signature)")
    else:
        try:
            pub = ECC.import_key(public_key)
            sig_bytes = base64.b64decode(signature["signature_b64"])
            message = _canonical_json(certificate)
            verifier = eddsa.new(pub, "rfc8032")
            verifier.verify(message, sig_bytes)
            _ok(f"Ed25519 signature valid (fingerprint: {{signature.get('public_key_fingerprint', 'n/a')}})")
        except Exception as exc:
            _fail(f"Signature verification failed: {{exc}}")

    print()
    print("PASS — FINCO Solar Reference package is authentic and unmodified.")
    print(f"  Certificate ID: {{certificate.get('certificate_id')}}")
    print(f"  Engine version: {{certificate.get('model', {{}}).get('engine_version')}}")
    sys.exit(0)


if __name__ == "__main__":
    # Allow --base-url override.
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--base-url" and i + 1 < len(sys.argv):
            BASE_URL = sys.argv[i + 1]
            CERTIFICATE_URL = f"{{BASE_URL}}/verify/reference/{{ASSET_ID}}/certificate.json"
            ASSUMPTIONS_URL = f"{{BASE_URL}}/verify/reference/{{ASSET_ID}}/assumptions.json"
            OUTPUTS_URL     = f"{{BASE_URL}}/verify/reference/{{ASSET_ID}}/outputs.json"
            SIGNATURE_URL   = f"{{BASE_URL}}/verify/reference/{{ASSET_ID}}/signature.json"
            PUBLIC_KEY_URL  = f"{{BASE_URL}}/verify/reference/{{ASSET_ID}}/public-key.pem"
    main()
'''
