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

import base64
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from pydantic import BaseModel

from app.protocol.signing_keys import (
    get_signing_key,
    is_verify_capable,
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
STATE_KEY_NOT_VERIFY_CAPABLE = "KEY_NOT_VERIFY_CAPABLE"
STATE_KEY_NOT_VALID_FOR_CERTIFICATE_TIME = "KEY_NOT_VALID_FOR_CERTIFICATE_TIME"
STATE_PAYLOAD_DIGEST_MISMATCH = "PAYLOAD_DIGEST_MISMATCH"

SUPPORTED_CERTIFICATE_SCHEMA_VERSION = "finco-run-certificate-v1"
SUPPORTED_ALGORITHM = "Ed25519"


def _parse_iso_utc(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp; naive values are interpreted as UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _recompute_payload_digest(certificate: dict) -> str:
    """Independently recompute the payload digest over the certificate's own
    fields (everything except ``payload_digest`` and ``signature``) using the
    same canonical serialization authority as issuance."""
    from app.services.run_certificate_service import (
        canonical_certificate_signing_bytes,
    )

    digest_input = {
        k: v for k, v in certificate.items()
        if k not in ("payload_digest", "signature")
    }
    return hashlib.sha256(
        canonical_certificate_signing_bytes(digest_input)
    ).hexdigest()


def verify_certificate_against_registry(certificate: dict) -> dict:
    """Pure registry-backed verification.  No DB, no engine, no mutation.

    Checks, in order:
      1. structural invariants (schema version, algorithm, kid binding);
      2. kid resolution against the public signing-key registry — the kid is
         EXPLICIT; there is no fallback to ``key_id`` or any other field;
      3. key verify capability (ACTIVE / VERIFY_ONLY rotation contract);
      4. key time validity — the key must have been inside its
         activated_at/retired_at window at the certificate's issuance time;
      5. independent payload-digest recompute over the received bytes;
      6. Ed25519 signature over the canonical signed bytes.

    All failure details are typed and sanitized: no exception text, no
    traceback, no key material ever leaves this function.
    """
    from app.services.run_certificate_service import (
        canonical_certificate_signing_bytes,
    )

    kid = certificate.get("kid") if isinstance(certificate, dict) else None
    result: Dict[str, Any] = {
        "state": None,
        "kid": kid,
        "algorithm": certificate.get("signature_algorithm") if isinstance(certificate, dict) else None,
        "certificate_schema_version": certificate.get(
            "certificate_schema_version"
        ) if isinstance(certificate, dict) else None,
        "certificate_digest": certificate.get("payload_digest") if isinstance(certificate, dict) else None,
        "signature_valid": False,
        "run_at": certificate.get("run_at") if isinstance(certificate, dict) else None,
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
    # M-2 Correction A: the kid binding is EXPLICIT.  A legacy ``key_id``
    # fingerprint alone is NOT a trust anchor — no fallback, no guessing.
    if not isinstance(kid, str) or not kid.strip():
        return _finish(STATE_MALFORMED_CERTIFICATE, "missing explicit kid binding")
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
        return _finish(
            STATE_UNKNOWN_KEY_ID,
            f"kid {kid!r} is not a registered FINCO signing key",
        )
    if not is_verify_capable(record):
        return _finish(
            STATE_KEY_NOT_VERIFY_CAPABLE,
            f"registered kid {kid!r} has status {record.status!r} and cannot "
            "verify certificates",
        )

    # Key time validity: the signing key must have been inside its validity
    # window when the certificate was issued (issued_at, falling back to
    # run_at when issued_at is absent).
    certificate_time = _parse_iso_utc(
        certificate.get("issued_at") or certificate.get("run_at")
    )
    if certificate_time is None:
        return _finish(
            STATE_MALFORMED_CERTIFICATE,
            "certificate has no parseable issued_at or run_at timestamp",
        )
    activated_at = _parse_iso_utc(record.activated_at)
    retired_at = _parse_iso_utc(record.retired_at)
    if activated_at is not None and certificate_time < activated_at:
        return _finish(
            STATE_KEY_NOT_VALID_FOR_CERTIFICATE_TIME,
            f"kid {kid!r} was activated after this certificate was issued",
        )
    if retired_at is not None and certificate_time > retired_at:
        return _finish(
            STATE_KEY_NOT_VALID_FOR_CERTIFICATE_TIME,
            f"kid {kid!r} was retired before this certificate was issued",
        )

    # Independent payload-digest recompute: the stated digest must match the
    # digest recomputed from the received fields themselves.
    recomputed_digest = _recompute_payload_digest(certificate)
    if recomputed_digest != certificate.get("payload_digest"):
        return _finish(
            STATE_PAYLOAD_DIGEST_MISMATCH,
            "payload digest does not match the independently recomputed digest "
            "of the received certificate fields",
        )

    # Registry public key must match the certificate's key_id fingerprint
    # when one is carried (integrity crosscheck only — never a trust anchor).
    fingerprint = hashlib.sha256(record.public_key_der()).hexdigest()[:16]
    if certificate.get("key_id") not in (None, fingerprint):
        return _finish(
            STATE_INVALID_SIGNATURE,
            "certificate key_id does not match the registered public key",
        )

    # Canonical signed bytes: everything except the signature field — the
    # exact serialization used at issuance.  The payload_digest field IS part
    # of the signed bytes (it was computed over the payload pre-digest at
    # issuance).
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
    except Exception:
        # Sanitized: no exception text, no traceback, no key material.
        return _finish(
            STATE_INVALID_SIGNATURE,
            "Ed25519 signature does not verify against the registered public "
            "key for this certificate's canonical bytes",
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
