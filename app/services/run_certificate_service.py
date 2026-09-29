"""FINCO Signed Run Certificate V1 — cryptographically signed attestation of
provenance and integrity for a canonical committed Last Run.

AUTHORITY SEPARATION (non-negotiable)
-------------------------------------
A Run Certificate ATTESTS TO:
  - the exact certified payload (bytes, digest);
  - the exact FINCO run identity (snapshot id, composite hash, timing,
    scenario, origin, engine/workbook identity);
  - the issuer / signing-key identity;
  - payload integrity (Ed25519 signature over the canonical serialization).

A Run Certificate MUST NEVER be read as a claim that:
  - FINCO Verify is true for the project;
  - any evidence or market data is economically true;
  - the model result is "correct";
  - the asset is VERIFIED;
  - any market price is executable.

Signing proves provenance/integrity — not truth.  ``app.verify`` semantics
and ``PRODUCTION_VERIFIED_ASSET_COUNT`` are untouched by this module.

Payload source: the COMMITTED Last Run authority only (persisted
``last_runtime_*`` workspace state).  No Working Copy values.  No engine
rerun — the certificate is built from what was already committed.

Canonical serialization: deterministic JSON (sorted keys, compact
separators, UTF-8, explicit schema version).  The same payload bytes plus
the same signing key always produce the same verifiable certificate.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from app.data_center_authority import replace  # noqa: F401 (re-export symmetry)

CERTIFICATE_SCHEMA_VERSION = "finco-run-certificate-v1"
SIGNATURE_ALGORITHM = "Ed25519"
ISSUER = "FINCO Protocol — Signed Run Certificate V1"

# Environment variable holding the base64-encoded 32-byte Ed25519 seed.
SIGNING_KEY_ENV_VAR = "FINCO_RUN_CERT_SIGNING_KEY"


class SigningKeyUnavailable(RuntimeError):
    """Raised when production signing is requested but no signing key is
    configured.  Fail-closed: never sign with a fallback key."""

    REASON = "SIGNING_KEY_UNAVAILABLE"


class CertificateBuildUnavailable(RuntimeError):
    """Raised when a project has no committed Last Run to certify."""

    REASON = "COMMITTED_LAST_RUN_REQUIRED"


def _canonical_json_bytes(payload: dict) -> bytes:
    """Deterministic JSON serialization for signing/digest.

    - sorted keys (stable order)
    - compact separators (no whitespace variance)
    - ensure_ascii=False (UTF-8 native)
    - floats repr-stable via stdlib json (same payload → same bytes)
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _signing_key_pair() -> Tuple[bytes, bytes]:
    """Load the Ed25519 signing key pair from configuration.

    Returns (seed_bytes, public_key_der).  Raises
    ``SigningKeyUnavailable`` when the environment variable is absent or
    malformed.  The private material is never logged and never included in
    any certificate payload.
    """
    from Crypto.PublicKey import ECC

    raw = os.getenv(SIGNING_KEY_ENV_VAR, "")
    if not raw.strip():
        raise SigningKeyUnavailable(
            f"{SigningKeyUnavailable.REASON}: environment variable "
            f"{SIGNING_KEY_ENV_VAR} is not configured."
        )
    try:
        seed = base64.b64decode(raw.strip(), validate=True)
    except Exception as exc:
        raise SigningKeyUnavailable(
            f"{SigningKeyUnavailable.REASON}: {SIGNING_KEY_ENV_VAR} is not "
            f"valid base64 ({type(exc).__name__})."
        ) from exc
    if len(seed) != 32:
        raise SigningKeyUnavailable(
            f"{SigningKeyUnavailable.REASON}: {SIGNING_KEY_ENV_VAR} must decode "
            f"to exactly 32 bytes (got {len(seed)})."
        )
    key = ECC.construct(curve="Ed25519", seed=seed)
    pub_der = key.public_key().export_key(format="DER")
    return seed, pub_der


def key_id_for_public_key(public_key_der: bytes) -> str:
    """Stable identifier for the signing key: first 16 hex chars of the
    SHA-256 fingerprint of the DER-encoded public key."""
    return hashlib.sha256(public_key_der).hexdigest()[:16]


def build_certificate_payload(ws) -> dict:
    """Build the unsigned canonical certificate payload from committed
    Last Run state only.

    ``ws`` is a WorkspaceStateRecord.  A committed Last Run is REQUIRED
    (``any_run_committed`` + ``last_runtime_snapshot_id``); otherwise
    ``CertificateBuildUnavailable`` is raised.  No engine rerun; no
    Working Copy values enter the payload.
    """
    if not getattr(ws, "any_run_committed", False) or not getattr(
        ws, "last_runtime_snapshot_id", None
    ):
        raise CertificateBuildUnavailable(
            f"{CertificateBuildUnavailable.REASON}: project "
            f"{getattr(ws, 'project_id', '?')!r} has no committed Last Run."
        )

    identity = getattr(ws, "last_runtime_identity", None) or {}
    if not isinstance(identity, dict):
        identity = {}
    summary = getattr(ws, "last_runtime_summary", None) or {}
    if not isinstance(summary, dict):
        summary = {}

    run_at = getattr(ws, "last_runtime_at", None)
    run_at_iso = run_at.isoformat() if run_at else None

    payload: dict[str, Any] = {
        "certificate_schema_version": CERTIFICATE_SCHEMA_VERSION,
        "project_id": ws.project_id,
        "project_code": ws.project_code,
        "project_type": identity.get("project_type"),
        "template_source": identity.get("template_source"),
        "snapshot_id": ws.last_runtime_snapshot_id,
        "composite_hash": ws.last_runtime_composite_hash,
        "run_at": run_at_iso,
        "workbook_version": identity.get("workbook_version"),
        "engine_version": identity.get("engine_version"),
        "git_sha": identity.get("git_sha"),
        "git_branch": identity.get("git_branch"),
        "active_scenario_id": ws.last_runtime_scenario_id,
        "run_origin": ws.last_runtime_origin,
        "kpi_digest": hashlib.sha256(
            _canonical_json_bytes(summary)
        ).hexdigest(),
        # Explicit non-claims: the certificate carries the observed Verify
        # state as a separate authority reference — it NEVER converts it to
        # VERIFIED (app.verify semantics untouched).
        "observed_authorities": {
            "finco_verify_state": identity.get("finco_verify_state"),
            "note": "Observed authority state only. This certificate attests "
                    "to provenance/integrity, never economic truth.",
        },
    }
    return payload


def _sign_bytes(seed: bytes, data: bytes) -> bytes:
    from Crypto.PublicKey import ECC
    from Crypto.Signature import eddsa

    key = ECC.construct(curve="Ed25519", seed=seed)
    signer = eddsa.new(key, "rfc8032")
    return signer.sign(data)


def _verify_bytes(public_key_der: bytes, data: bytes, signature: bytes) -> bool:
    from Crypto.PublicKey import ECC
    from Crypto.Signature import eddsa

    pub = ECC.import_key(public_key_der)
    verifier = eddsa.new(pub, "rfc8032")
    try:
        verifier.verify(data, signature)
        return True
    except ValueError:
        return False


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text, validate=True)


def issue_run_certificate(ws) -> dict:
    """Issue a signed Run Certificate for a committed Last Run.

    Returns the full certificate dict (payload + key id + signature).  The
    private key never leaves this function and is never serialized into the
    certificate.  Fail-closed when no signing key is configured.
    """
    seed, public_key_der = _signing_key_pair()
    payload = build_certificate_payload(ws)
    payload["signature_algorithm"] = SIGNATURE_ALGORITHM
    payload["key_id"] = key_id_for_public_key(public_key_der)
    digest_input = {
        k: v for k, v in payload.items()
        if k not in ("payload_digest", "signature", "signature_algorithm", "key_id")
    }
    payload["payload_digest"] = hashlib.sha256(
        _canonical_json_bytes(digest_input)
    ).hexdigest()

    signing_bytes = _canonical_json_bytes(payload)
    signature = _sign_bytes(seed, signing_bytes)
    payload["signature"] = _b64(signature)
    return payload


def verify_run_certificate(
    certificate: dict, public_key_der: Optional[bytes] = None
) -> Tuple[bool, str]:
    """Pure verification of a supplied Run Certificate.

    Pass ``public_key_der`` (DER-encoded Ed25519 public key) to pin a
    specific key; when omitted, structural verification only.
    Returns (valid, reason).
    """
    cert = dict(certificate or {})
    signature_b64 = cert.get("signature")
    if not signature_b64:
        return False, "MISSING_SIGNATURE"

    stored_digest = cert.get("payload_digest")
    if not stored_digest:
        return False, "MISSING_PAYLOAD_DIGEST"

    # Rebuild the signed payload: everything except the signature field.
    unsigned = {k: v for k, v in cert.items() if k != "signature"}

    # Integrity check: the payload digest was computed over the payload
    # WITHOUT the digest/signature fields (signature_algorithm + key_id were
    # present, payload_digest + signature were not).
    digest_input = {
        k: v for k, v in unsigned.items()
        if k not in ("payload_digest", "signature", "signature_algorithm", "key_id")
    }
    digest = hashlib.sha256(_canonical_json_bytes(digest_input)).hexdigest()
    if digest != stored_digest:
        return False, "PAYLOAD_TAMPERED"

    signing_bytes = _canonical_json_bytes(unsigned)
    try:
        signature = _unb64(signature_b64)
    except Exception:
        return False, "MALFORMED_SIGNATURE"

    if public_key_der is not None:
        expected_kid = key_id_for_public_key(public_key_der)
        if cert.get("key_id") != expected_kid:
            return False, "WRONG_KEY_ID"
        if not _verify_bytes(public_key_der, signing_bytes, signature):
            return False, "SIGNATURE_INVALID"
        return True, "VALID"

    return False, "PUBLIC_KEY_REQUIRED"


def public_key_der_from_seed(seed: bytes) -> bytes:
    """Derive the raw Ed25519 public key bytes from a 32-byte seed."""
    from Crypto.PublicKey import ECC

    key = ECC.construct(curve="Ed25519", seed=seed)
    return key.public_key().export_key(format="DER")
