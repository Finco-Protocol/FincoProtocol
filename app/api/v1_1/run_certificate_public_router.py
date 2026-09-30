"""FINCO M-2 — public Signed Run certificate verification + key discovery.

Public trust surfaces (no auth, no token, no DB mutation, no engine call):

  GET  /.well-known/finco/keys.json          — public key discovery document
  POST /api/v1.1/run-certificates/verify     — typed certificate verification
  GET  /api/v1.1/protocol/signing-keys       — byte-identical API mirror

This router is a THIN ADAPTER over the ONE shared verification core
(``app.protocol.run_certificate_verifier``) — the same state machine the
standalone offline CLI uses.  No crypto decision logic lives here.

Verification answers exactly one question: *was this certificate signed by a
FINCO key that was valid for that kid, over these exact bytes?*  It never
implies economic truth, FINCO Verify status, asset verification, or on-chain
anchoring.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from pydantic import BaseModel

from app.protocol.run_certificate_verifier import (  # noqa: F401 (re-export)
    STATE_INVALID_SIGNATURE,
    STATE_KEY_NOT_VERIFY_CAPABLE,
    STATE_KEY_NOT_VALID_FOR_CERTIFICATE_TIME,
    STATE_MALFORMED_CERTIFICATE,
    STATE_PAYLOAD_DIGEST_MISMATCH,
    STATE_UNKNOWN_KEY_ID,
    STATE_UNSUPPORTED_ALGORITHM,
    STATE_UNSUPPORTED_CERTIFICATE_VERSION,
    STATE_VALID,
    STATE_VERIFICATION_UNAVAILABLE,
    verify_certificate,
)
from app.protocol.signing_keys import (
    all_keys,
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


def verify_certificate_against_registry(certificate: dict) -> dict:
    """Adapter: run the shared verification core against THIS process's
    validated registry (bundled manifest + deployment/bootstrap records).

    No DB, no engine, no mutation.  All verdict logic — structural checks,
    explicit kid resolution, key state, strict issued_at time validity,
    digest recompute, Ed25519 — lives in the shared core, so the API and
    the offline CLI always agree on the same certificate + registry.
    """
    return verify_certificate(certificate, all_keys())


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
    return JSONResponse(status_code=200, content=result)


@router.get("/protocol/signing-keys")
def protocol_signing_keys(request: Request):
    """Canonical API mirror of the public signing-key registry — the exact
    same document the ``/.well-known/finco/keys.json`` discovery endpoint
    serves (one manifest authority, byte-identical mirrors)."""
    _ = request
    return JSONResponse(content=public_keys_document())
