"""FINCO public signing-key registry — single public trust authority for
Signed Run Certificate V1 (M-2).

This module is the SINGLE SOURCE OF TRUTH for which Ed25519 public keys are
recognized FINCO issuer keys.  It is:

  - deterministic (same code/config → same registry);
  - version-controlled and auditable;
  - cheap to publish (the discovery endpoint serializes it directly).

Only PUBLIC key material lives here.  Private signing keys come exclusively
from deployment configuration (``FINCO_RUN_CERT_SIGNING_KEY``) and are never
committed, logged, or returned.

Rotation model (V1):
  ACTIVE       — may sign NEW certificates and verify historical ones.
  VERIFY_ONLY  — retired from issuance; still verifies historical
                 certificates.  Retiring a key must never make historical
                 certificates unverifiable.

``kid`` is the stable public key identifier.  V1 uses the SHA-256/16
fingerprint of the DER-encoded public key (computed by
``key_id_for_public_key``) — a cryptographically derived, collision-resistant
stable field, not an arbitrary label.  Certificates bind ``key_id`` (the
fingerprint) and ``kid`` (the registry identifier, equal by convention) in
their signed payload.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

SCHEMA_VERSION = "finco-signing-keys-v1"
ISSUER = "FINCO Protocol"
ALGORITHM_ED25519 = "Ed25519"
PUBLIC_KEY_ENCODING = "DER"

STATUS_ACTIVE = "ACTIVE"
STATUS_VERIFY_ONLY = "VERIFY_ONLY"
_VALID_STATUSES = frozenset({STATUS_ACTIVE, STATUS_VERIFY_ONLY})


@dataclass(frozen=True)
class SigningKeyRecord:
    """Public trust record for one FINCO Ed25519 signing key.

    ``public_key_der_b64`` is the base64 of the DER-encoded public key.
    No private material is ever stored or transported here.
    """
    kid: str
    public_key_der_b64: str
    status: str = STATUS_ACTIVE
    activated_at: str = ""
    retired_at: str = ""
    issuer: str = ISSUER
    schema_version: str = SCHEMA_VERSION
    algorithm: str = ALGORITHM_ED25519
    encoding: str = PUBLIC_KEY_ENCODING

    def public_key_der(self) -> bytes:
        return base64.b64decode(self.public_key_der_b64, validate=True)

    def public_key_jwk(self) -> dict:
        """RFC 8037 JWK representation (kty=OKP, crv=Ed25519)."""
        der = self.public_key_der()
        raw_public = der[-32:]  # RFC 8410 Ed25519 DER: 12-byte header + 32-byte key
        import base64 as _b64
        x = _b64.urlsafe_b64encode(raw_public).decode("ascii").rstrip("=")
        return {"kty": "OKP", "crv": "Ed25519", "x": x}


# Process-local registry.  Seeded empty; deployments/tests register public
# key records explicitly (code/config or test fixtures).  Registration is
# additive and auditable; duplicate kids replace the record deliberately.
_REGISTRY: Dict[str, SigningKeyRecord] = {}


def register_key(record: SigningKeyRecord) -> SigningKeyRecord:
    """Register (or replace) a public signing-key record.

    Validates structure and encoding fail-closed.  Returns the record.
    """
    if not record.kid or not record.kid.strip():
        raise ValueError("signing key record: kid is required")
    if record.algorithm != ALGORITHM_ED25519:
        raise ValueError(
            f"signing key record {record.kid!r}: unsupported algorithm "
            f"{record.algorithm!r} (only {ALGORITHM_ED25519!r} is supported)"
        )
    if record.status not in _VALID_STATUSES:
        raise ValueError(
            f"signing key record {record.kid!r}: invalid status {record.status!r}"
        )
    try:
        record.public_key_der()  # fail-closed base64/DER validation
    except Exception as exc:
        raise ValueError(
            f"signing key record {record.kid!r}: public_key_der_b64 is not "
            f"valid base64 DER ({type(exc).__name__})"
        ) from exc
    _REGISTRY[record.kid] = record
    return record


def register_key_values(
    kid: str,
    public_key_der: bytes,
    *,
    status: str = STATUS_ACTIVE,
    activated_at: str = "",
) -> SigningKeyRecord:
    """Convenience wrapper: register from raw DER bytes."""
    import base64 as _b64
    return register_key(SigningKeyRecord(
        kid=kid,
        public_key_der_b64=_b64.b64encode(public_key_der).decode("ascii"),
        status=status,
        activated_at=activated_at,
    ))


def unregister_key(kid: str) -> None:
    """Remove a record (test/config housekeeping only)."""
    _REGISTRY.pop(kid, None)


def get_signing_key(kid: str) -> Optional[SigningKeyRecord]:
    """Exact O(1) kid lookup — no fuzzy matching, no fallback keys."""
    if not kid:
        return None
    return _REGISTRY.get(kid)


def all_keys() -> Tuple[SigningKeyRecord, ...]:
    """All registered public key records, deterministically ordered by kid."""
    return tuple(_REGISTRY[k] for k in sorted(_REGISTRY))


def is_verify_capable(record: SigningKeyRecord) -> bool:
    """VERIFY_ONLY and ACTIVE keys both verify historical certificates."""
    return record.status in (STATUS_ACTIVE, STATUS_VERIFY_ONLY)


def is_issuance_capable(record: SigningKeyRecord) -> bool:
    """Only ACTIVE keys may sign NEW certificates."""
    return record.status == STATUS_ACTIVE


def public_keys_document() -> dict:
    """Deterministic public trust document for the discovery endpoint.

    Contains only PUBLIC trust material.  No private key, seed, environment
    variable value, filesystem path, or credential metadata ever appears.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "issuer": ISSUER,
        "keys": [
            {
                "kid": record.kid,
                "algorithm": record.algorithm,
                "status": record.status,
                "public_key": record.public_key_der_b64,
                "public_key_encoding": record.encoding,
                "jwk": record.public_key_jwk(),
                "activated_at": record.activated_at,
                "retired_at": record.retired_at,
                "issuer": record.issuer,
                "schema_version": record.schema_version,
                "certificate_schema_version": (
                    "finco-run-certificate-v1"
                ),
            }
            for record in all_keys()
        ],
    }
