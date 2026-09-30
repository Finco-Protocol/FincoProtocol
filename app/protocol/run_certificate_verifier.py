"""FINCO M-2 shared Run Certificate verification core (Correction B, P2).

ONE pure verification state machine shared by:
  - the public API adapter (``app.api.v1_1.run_certificate_public_router``);
  - the standalone offline CLI (``tools/verify_finco_run_certificate.py``).

The same certificate plus the same key registry MUST return the same typed
state through both surfaces — there is no duplicated crypto decision logic.

Checks, in order:
  1. structural invariants (schema version, algorithm, kid binding, size
     cap);
  2. EXPLICIT kid resolution — no fallback to ``key_id`` or anything else;
  3. key verify capability — ACTIVE/VERIFY_ONLY verify; REVOKED (compromised)
     and any other status verify NOTHING (P5: rotation != compromise);
  4. STRICT certificate time (P4): ``issued_at`` is REQUIRED and MUST be
     timezone-aware.  Naive timestamps are rejected, never silently read as
     UTC; ``run_at`` is NEVER consulted — key validity is decided against
     ``issued_at`` only;
  5. key time validity — the key's ``activated_at``/``retired_at`` window
     must contain the certificate's ``issued_at``;
  6. independent payload-digest recompute over the received fields;
  7. Ed25519 verification over the canonical signed bytes.

All failure details are typed and sanitized: no exception text, no
traceback, no key material.  A verdict is cryptographic provenance/integrity
ONLY — never economic truth, never FINCO Verify, never a blockchain claim.
"""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from app.protocol.signing_keys import (
    SigningKeyRecord,
    parse_strict_iso_utc,
)

# Typed verification states.  There is deliberately NO "FINCO_VERIFIED"
# state: cryptographic verification is not economic truth and not FINCO
# Verify.
STATE_VALID = "VALID"
STATE_INVALID_SIGNATURE = "INVALID_SIGNATURE"
STATE_UNKNOWN_KEY_ID = "UNKNOWN_KEY_ID"
STATE_UNSUPPORTED_CERTIFICATE_VERSION = "UNSUPPORTED_CERTIFICATE_VERSION"
STATE_MALFORMED_CERTIFICATE = "MALFORMED_CERTIFICATE"
STATE_UNSUPPORTED_ALGORITHM = "UNSUPPORTED_ALGORITHM"
STATE_KEY_NOT_VERIFY_CAPABLE = "KEY_NOT_VERIFY_CAPABLE"
STATE_KEY_NOT_VALID_FOR_CERTIFICATE_TIME = "KEY_NOT_VALID_FOR_CERTIFICATE_TIME"
STATE_PAYLOAD_DIGEST_MISMATCH = "PAYLOAD_DIGEST_MISMATCH"
STATE_KEYS_DOCUMENT_INVALID = "KEYS_DOCUMENT_INVALID"
STATE_VERIFICATION_UNAVAILABLE = "VERIFICATION_UNAVAILABLE"

SUPPORTED_CERTIFICATE_SCHEMA_VERSION = "finco-run-certificate-v1"
SUPPORTED_ALGORITHM = "Ed25519"

# Certificates above this canonical size are malformed — no unbounded
# field stress on the public surface.
MAX_CERTIFICATE_JSON_BYTES = 1_000_000


def validate_keys_document(document: Any) -> tuple:
    """Validate an external keys document STRICTLY and ATOMICALLY.

    Raises ``SigningKeyRegistryError`` for the whole document on ANY invalid
    entry (P1/P3) — a partially accepted trust list is never exposed.
    """
    from app.protocol.signing_keys import validate_keys_document as _validate
    return _validate(document)


def verify_certificate(
    certificate: Any,
    key_records: Iterable[SigningKeyRecord],
) -> dict:
    """Pure registry-backed verification — the ONE shared state machine.

    ``key_records`` is the already-validated trust list (records carry only
    PUBLIC material).  No DB, no engine, no mutation, no I/O.
    """
    from app.services.run_certificate_service import (
        canonical_certificate_signing_bytes,
    )

    records = {record.kid: record for record in key_records}
    kid = certificate.get("kid") if isinstance(certificate, dict) else None
    result: Dict[str, Any] = {
        "state": None,
        "kid": kid,
        "algorithm": certificate.get("signature_algorithm")
        if isinstance(certificate, dict) else None,
        "certificate_schema_version": certificate.get(
            "certificate_schema_version")
        if isinstance(certificate, dict) else None,
        "certificate_digest": certificate.get("payload_digest")
        if isinstance(certificate, dict) else None,
        "signature_valid": False,
        "run_at": certificate.get("run_at")
        if isinstance(certificate, dict) else None,
        "verification_timestamp": datetime.now(timezone.utc).isoformat(),
        "detail": "",
    }

    def _finish(state: str, detail: str = "") -> dict:
        result["state"] = state
        result["detail"] = detail
        return result

    if not isinstance(certificate, dict) or not certificate:
        return _finish(STATE_MALFORMED_CERTIFICATE,
                       "empty or non-object certificate")
    if not certificate.get("signature"):
        return _finish(STATE_MALFORMED_CERTIFICATE, "missing signature")
    if not certificate.get("payload_digest"):
        return _finish(STATE_MALFORMED_CERTIFICATE, "missing payload digest")
    # The kid binding is EXPLICIT.  A legacy ``key_id`` fingerprint alone is
    # NOT a trust anchor — no fallback, no guessing.
    if not isinstance(kid, str) or not kid.strip():
        return _finish(STATE_MALFORMED_CERTIFICATE,
                       "missing explicit kid binding")
    if certificate.get("certificate_schema_version") != (
            SUPPORTED_CERTIFICATE_SCHEMA_VERSION):
        return _finish(
            STATE_UNSUPPORTED_CERTIFICATE_VERSION,
            f"unsupported certificate_schema_version: "
            f"{certificate.get('certificate_schema_version')!r}")
    algorithm = certificate.get("signature_algorithm")
    if algorithm != SUPPORTED_ALGORITHM:
        return _finish(
            STATE_UNSUPPORTED_ALGORITHM,
            f"unsupported signature algorithm: {algorithm!r} "
            f"(only {SUPPORTED_ALGORITHM!r} certificates verify)")

    # Size cap before any hashing/serialization work.
    if len(canonical_certificate_signing_bytes(certificate)) > (
            MAX_CERTIFICATE_JSON_BYTES):
        return _finish(STATE_MALFORMED_CERTIFICATE,
                       "certificate exceeds the maximum allowed size")

    record = records.get(kid)
    if record is None:
        return _finish(STATE_UNKNOWN_KEY_ID,
                       f"kid {kid!r} is not a registered FINCO signing key")
    if record.status not in ("ACTIVE", "VERIFY_ONLY"):
        # REVOKED (compromised) or any future non-verifying status.
        return _finish(
            STATE_KEY_NOT_VERIFY_CAPABLE,
            f"registered kid {kid!r} has status {record.status!r} and "
            "cannot verify certificates (revocation removes trust even for "
            "historical certificates)")

    # STRICT certificate time (P4): issued_at is REQUIRED, timezone-aware,
    # and is the ONLY time authority for key validity.  No run_at fallback,
    # no naive-as-UTC interpretation.
    issued_at = parse_strict_iso_utc(certificate.get("issued_at"))
    if certificate.get("issued_at") is None:
        return _finish(STATE_MALFORMED_CERTIFICATE,
                       "certificate is missing the required issued_at "
                       "timestamp")
    if issued_at is None:
        return _finish(STATE_MALFORMED_CERTIFICATE,
                       "issued_at must be a timezone-aware ISO-8601 "
                       "timestamp (naive timestamps are not accepted)")

    activated_at = parse_strict_iso_utc(record.activated_at)
    retired_at = parse_strict_iso_utc(record.retired_at)
    if activated_at is not None and issued_at < activated_at:
        return _finish(
            STATE_KEY_NOT_VALID_FOR_CERTIFICATE_TIME,
            f"kid {kid!r} was activated after this certificate was issued")
    if retired_at is not None and issued_at > retired_at:
        return _finish(
            STATE_KEY_NOT_VALID_FOR_CERTIFICATE_TIME,
            f"kid {kid!r} was retired before this certificate was issued")

    # Independent payload-digest recompute: the stated digest must match the
    # digest recomputed from the received fields themselves.
    digest_input = {k: v for k, v in certificate.items()
                    if k not in ("payload_digest", "signature")}
    recomputed_digest = hashlib.sha256(
        canonical_certificate_signing_bytes(digest_input)).hexdigest()
    if recomputed_digest != certificate.get("payload_digest"):
        return _finish(
            STATE_PAYLOAD_DIGEST_MISMATCH,
            "payload digest does not match the independently recomputed "
            "digest of the received certificate fields")

    # Registry public key must match the certificate's key_id fingerprint
    # when one is carried (integrity crosscheck only — never a trust
    # anchor).
    fingerprint = hashlib.sha256(record.public_key_der()).hexdigest()[:16]
    if certificate.get("key_id") not in (None, fingerprint):
        return _finish(STATE_INVALID_SIGNATURE,
                       "certificate key_id does not match the registered "
                       "public key")

    # Canonical signed bytes: everything except the signature field — the
    # exact serialization used at issuance.  The payload_digest field IS
    # part of the signed bytes (it was computed over the payload pre-digest
    # at issuance).
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
            "Ed25519 signature does not verify against the registered "
            "public key for this certificate's canonical bytes")

    result["signature_valid"] = True
    return _finish(STATE_VALID,
                   "cryptographic certificate verification passed")
