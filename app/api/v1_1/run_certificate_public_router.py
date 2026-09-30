"""FINCO M-2 — public Signed Run certificate verification + key discovery.

Public trust surfaces (no auth, no token, no DB mutation, no engine call):

  GET  /.well-known/finco/keys.json          — public key discovery document
  POST /api/v1.1/run-certificates/verify     — typed certificate verification

Verification answers exactly one question: *was this certificate signed by a
FINCO key that was valid for that kid, over these exact bytes?*  It never
implies economic truth, FINCO Verify status, asset verification, or on-chain
anchoring.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import base64
import binascii
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from pydantic import BaseModel

from app.protocol.signing_keys import (
    STATUS_ACTIVE,
    STATUS_VERIFY_ONLY,
    get_signing_key,
    public_keys_document,
)


class VerifyCertificateRequest(BaseModel):
    certificate: Dict[str, Any]


class VerifyResultEnvelope(BaseModel):
    state: str
    kid: Optional[str] = None
    algorithm: Optional[str] = None
    certificate_schema_version: Optional[str] = None
    certificate_digest: Optional[str] = None
    signature_valid: Optional[bool] = None
    run_at: Optional[str] = None
    verification_timestamp: str
    detail: str = ""

    class Config:
        extra = "forbid"


router = APIRouter()

# Typed verification states.  There is deliberately NO "FINCO_VERIFIED" state:
# cryptographic verification is not economic truth and not FINCO Verify.
STATE_VALID = "VALID"
STATE_INVALID_SIGNATURE = "INVALID_SIGNATURE"
STATE_UNKNOWN_KEY_ID = "UNKNOWN_KEY_ID"
STATE_UNSUPPORTED_CERTIFICATE_VERSION = "UNSUPPORTED_CERTIFICATE_VERSION"
STATE_MALFORMED_CERTIFICATE = "MALFORMED_CERTIFICATE"
STATE_UNSUPPORTED_ALGORITHM = "UNSUPPORTED_ALGORITHM"
STATE_VERIFICATION_UNAVAILABLE = "VERIFICATION_UNAVAILABLE"

SUPPORTED_CERTIFICATE_SCHEMA_VERSION = "finco-run-certificate-v1"
SUPPORTED_ALGORITHM = "Ed25519"


def verify_certificate_against_registry(certificate: dict) -> dict:
    """Pure registry-backed verification.  No DB, no engine, no mutation.

    Reconstructs the canonical signed bytes with the SAME serialization
    authority used at issuance (canonical_certificate_signing_bytes), checks
    structural invariants, resolves the kid from the public key registry and
    verifies the Ed25519 signature.
    """
    from app.services.run_certificate_service import (
        canonical_certificate_signing_bytes,
    )

    kid = certificate.get("kid") or certificate.get("key_id")
    result: Dict[str, Any] = {
        "state": None,
        "kid": kid,
        "algorithm": certificate.get("signature_algorithm"),
        "certificate_schema_version": certificate.get(
            "certificate_schema_version"
        ),
        "certificate_digest": certificate.get("payload_digest"),
        "signature_valid": False,
        "run_at": certificate.get("run_at"),
        "verification_timestamp": datetime.now(timezone.utc).isoformat(),
        "detail": "",
    }

    def _finish(state: str, detail: str = "") -> dict:
        result["state"] = state
        result["detail"] = detail
        return result

    if not isinstance(certificate, dict) or not certificate:
        return _finish(STATE_MALFORMED_CERTIFICATE, "empty or non-object certificate")
    if not certificate.get("signature"):
        return _finish(STATE_MALFORMED_CERTIFICATE, "missing signature")
    if not certificate.get("payload_digest"):
        return _finish(STATE_MALFORMED_CERTIFICATE, "missing payload digest")
    if not kid:
        return _finish(STATE_MALFORMED_CERTIFICATE, "missing kid binding")
    if certificate.get("certificate_schema_version") != (
        SUPPORTED_CERTIFICATE_SCHEMA_VERSION
    ):
        return _finish(
            STATE_UNSUPPORTED_CERTIFICATE_VERSION,
            f"unsupported certificate_schema_version: "
            f"{certificate.get('certificate_schema_version')!r}",
        )
    algorithm = certificate.get("signature_algorithm")
    if algorithm != SUPPORTED_ALGORITHM:
        return _finish(
            STATE_UNSUPPORTED_ALGORITHM,
            f"unsupported signature algorithm: {algorithm!r} "
            f"(only {SUPPORTED_ALGORITHM!r} certificates verify)",
        )

    record = get_signing_key(kid)
    if record is None:
        return _finish(STATE_UNKNOWN_KEY_ID, f"kid {kid!r} is not a registered FINCO signing key")
    if not record.status in (STATUS_ACTIVE, STATUS_VERIFY_ONLY):
        return _finish(
            STATE_MALFORMED_CERTIFICATE,
            f"registered kid {kid!r} has invalid registry status {record.status!r}",
        )

    # Registry public key must match the certificate's key_id fingerprint.
    import hashlib
    fingerprint = hashlib.sha256(record.public_key_der()).hexdigest()[:16]
    if certificate.get("key_id") not in (None, fingerprint):
        return _finish(
            STATE_INVALID_SIGNATURE,
            "certificate key_id does not match the registered public key",
        )

    # Canonical signed bytes: everything except the signature field — the
    # exact serialization used at issuance.  Digest covers the same payload
    # minus payload_digest and signature (matching issuance).
    # Signing bytes = canonical bytes of the certificate minus ONLY the
    # signature field.  The payload_digest field IS part of the signed
    # bytes (it was computed over the payload pre-digest at issuance).
    unsigned = {k: v for k, v in certificate.items() if k != "signature"}
    signing_bytes = canonical_certificate_signing_bytes(unsigned)
    signature = certificate.get("signature")

    from Crypto.PublicKey import ECC
    from Crypto.Signature import eddsa

    try:
        pub = ECC.import_key(record.public_key_der())
        verifier = eddsa.new(pub, "rfc8032")
        signature_bytes = base64.b64decode(signature, validate=True)
        verifier.verify(signing_bytes, signature_bytes)
    except Exception as exc:
        import traceback as _tb
        _tb.print_exc()
        return _finish(
            STATE_INVALID_SIGNATURE,
            f"Ed25519 signature does not verify: {type(exc).__name__}: {exc}",
        )

    result["signature_valid"] = True
    return _finish(STATE_VALID, "cryptographic certificate verification passed")


@router.post("/run-certificates/verify")
def verify_run_certificate(certificate: dict, request: Request):
    """Public, unauthenticated typed verification of a Signed Run certificate.

    Cryptographic certificate verification ONLY:
      - no financial engine execution;
      - no Working Copy access;
      - no Last Run mutation;
      - no FINCO Verify mutation;
      - no Radar call;
      - no token/entitlement requirement.
    """
    _ = request  # explicit: no session/identity involved on this surface
    certificate_body = (certificate or {}).get("certificate")
    if not isinstance(certificate_body, dict):
        certificate_body = certificate or {}
    try:
        result = verify_certificate_against_registry(certificate_body)
    except Exception:
        # No raw exception leakage — typed unavailable state only.
        return JSONResponse(
            status_code=503,
            content={
                "state": STATE_VERIFICATION_UNAVAILABLE,
                "detail": "Verification temporarily unavailable.",
                "verification_timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
    status_code = 200 if result["state"] in (STATE_VALID,) else 200
    return JSONResponse(status_code=status_code, content=result)


@router.get("/protocol/signing-keys")
def protocol_signing_keys(request: Request):
    """Canonical API mirror of the public signing-key registry."""
    _ = request
    return JSONResponse(content=public_keys_document())
