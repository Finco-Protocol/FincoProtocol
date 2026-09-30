"""FINCO M-2 — public Signed Run certificate verification + key discovery.

Public trust surfaces (no auth, no token, no DB mutation, no engine call):

  GET  /.well-known/finco/keys.json          — public key discovery document
  POST /api/v1.1/run-certificates/verify     — typed certificate verification
  GET  /api/v1.1/protocol/signing-keys       — byte-identical API mirror

PUBLIC INGRESS PERIMETER (Correction C): the verify endpoint is
unauthenticated, so the transport boundary is hardened BEFORE any parsing
or verification work:

  1. a hard RAW-BODY byte limit enforced by bounded streaming consumption —
     a chunked request cannot push more than ``MAX_VERIFY_REQUEST_BYTES``
     into the process, and an oversized ``Content-Length`` is rejected
     without reading the body at all;
  2. strict JSON parsing with typed failures — malformed bodies never
     reach the verifier;
  3. bounded structural limits (nesting depth, total node count, per-
     container size) enforced ITERATIVELY — pathological structures are
     rejected before canonicalization, so no recursion bombs and no
     unbounded hashing reach the shared core;
  4. a small in-process admission semaphore bounding concurrent verifier
     executions — no distributed infrastructure, excess requests get a
     typed busy verdict.

All ingress failures are typed and sanitized (fixed strings only — no
exception text, no body echoes).  The shared verification core
(``app.protocol.run_certificate_verifier``) remains the ONE decision
authority for both the API and the offline CLI; its 1 MB canonical
certificate semantic cap is unchanged and applies after ingress admission.

Verification answers exactly one question: *was this certificate signed by
a FINCO key that was valid for that kid, over these exact bytes?*  It never
implies economic truth, FINCO Verify status, asset verification, or
on-chain anchoring.
"""
from __future__ import annotations

import json
import threading
from collections import deque
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

# ── Ingress perimeter limits (Correction C) ──────────────────────────────────

# Hard RAW ingress cap — enforced before JSON parsing/canonicalization.
# The shared core's 1,000,000-byte canonical semantic cap remains in force
# after admission.
MAX_VERIFY_REQUEST_BYTES = 1_048_576  # 1 MiB
MAX_JSON_DEPTH = 32                    # nesting depth (certificate is flat)
MAX_JSON_NODES = 10_000                # total nodes across the document
MAX_CONTAINER_LEN = 512                # max entries per object/list

# Small bounded admission control — in-process only, no external infra.
MAX_CONCURRENT_VERIFICATIONS = 8
_VERIFIER_ADMISSION = threading.BoundedSemaphore(MAX_CONCURRENT_VERIFICATIONS)

# Typed ingress states (transport layer — distinct from cryptographic
# verdicts, which live in the shared core).
STATE_REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"
STATE_MALFORMED_REQUEST = "MALFORMED_REQUEST"
STATE_VERIFICATION_BUSY = "VERIFICATION_BUSY"


def _too_large(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=413,
        content={
            "state": STATE_REQUEST_TOO_LARGE,
            "detail": detail,
            "verification_timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


def _malformed_request(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "state": STATE_MALFORMED_REQUEST,
            "detail": detail,
            "verification_timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


async def _read_bounded_body(request: Request, limit: int) -> Optional[bytes]:
    """Consume the request body with bounded streaming.

    Reads at most ``limit`` bytes; returns None the moment the stream
    exceeds the cap (consumption STOPS — an oversized chunked request
    cannot push unbounded bytes into the process).  A declared
    ``Content-Length`` above the cap short-circuits without reading.
    """
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                return None
        except ValueError:
            return None
    received = 0
    chunks = []
    async for chunk in request.stream():
        received += len(chunk)
        if received > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _check_structure_bounded(node: Any) -> bool:
    """Iterative structural bounds check (no recursion — a deep literal
    from ``json.loads`` is walked via an explicit queue).

    Rejects: nesting deeper than MAX_JSON_DEPTH, more than MAX_JSON_NODES
    total nodes, any object/list with more than MAX_CONTAINER_LEN entries.
    """
    queue = deque([(node, 1)])
    seen = 0
    while queue:
        current, depth = queue.popleft()
        seen += 1
        if seen > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            return False
        if isinstance(current, dict):
            if len(current) > MAX_CONTAINER_LEN:
                return False
            for value in current.values():
                queue.append((value, depth + 1))
        elif isinstance(current, (list, tuple)):
            if len(current) > MAX_CONTAINER_LEN:
                return False
            for value in current:
                queue.append((value, depth + 1))
    return True


def _extract_certificate(parsed: Any) -> Optional[dict]:
    """Accept either ``{"certificate": {...}}`` or a bare certificate
    object — the exact envelope contract the endpoint always had."""
    if not isinstance(parsed, dict):
        return None
    inner = parsed.get("certificate")
    if isinstance(inner, dict):
        return inner
    return parsed


def verify_certificate_against_registry(certificate: dict) -> dict:
    """Pure adapter over the shared verification core against THIS
    process's validated registry (bundled manifest + deployment records).

    Used by direct callers and tests; the HTTP endpoint applies the ingress
    perimeter (raw cap, JSON, structure bounds, admission) and then calls
    the SAME core with the SAME registry.  No duplicated crypto logic.
    """
    return verify_certificate(certificate, all_keys())


@router.post("/run-certificates/verify")
async def verify_run_certificate(request: Request):
    """Public, unauthenticated typed verification of a Signed Run certificate.

    Ingress perimeter first (raw cap → JSON → structure bounds → bounded
    admission), THEN the ONE shared verification core:
      - no financial engine execution;
      - no Working Copy access;
      - no Last Run mutation;
      - no FINCO Verify mutation;
      - no Radar call;
      - no token/entitlement requirement.
    """
    # 1. Raw-body cap — bounded streaming, chunked requests included.
    try:
        body = await _read_bounded_body(request, MAX_VERIFY_REQUEST_BYTES)
    except Exception:
        body = None
    if body is None:
        return _too_large(
            "request body exceeds the maximum allowed size "
            f"({MAX_VERIFY_REQUEST_BYTES} bytes)"
        )

    # 2. Strict JSON parsing — typed sanitized failure, no traceback.
    try:
        parsed = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return _malformed_request("request body is not valid JSON")
    except RecursionError:
        return _too_large("request structure exceeds verifier bounds")

    # 3. Bounded structure — depth / node count / container size, checked
    # iteratively BEFORE any canonicalization or hashing work.
    if not _check_structure_bounded(parsed):
        return _too_large("request structure exceeds verifier bounds")

    certificate_body = _extract_certificate(parsed)
    if certificate_body is None:
        return _malformed_request(
            "request must be a certificate object or a "
            '{"certificate": {...}} envelope'
        )

    # 4. Bounded in-process admission — excess concurrent verifications get
    # a typed busy verdict instead of unbounded CPU commitment.
    if not _VERIFIER_ADMISSION.acquire(blocking=False):
        return JSONResponse(
            status_code=503,
            content={
                "state": STATE_VERIFICATION_BUSY,
                "detail": "verifier is at its concurrent verification limit; "
                          "retry shortly.",
                "verification_timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
    try:
        # 5. THE shared verification core — same authority as the offline
        # CLI.  No duplicated crypto decision logic here.
        result = verify_certificate(certificate_body, all_keys())
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
    finally:
        _VERIFIER_ADMISSION.release()
    return JSONResponse(status_code=200, content=result)


@router.get("/protocol/signing-keys")
def protocol_signing_keys(request: Request):
    """Canonical API mirror of the public signing-key registry — the exact
    same document the ``/.well-known/finco/keys.json`` discovery endpoint
    serves (one manifest authority, byte-identical mirrors)."""
    _ = request
    return JSONResponse(content=public_keys_document())
