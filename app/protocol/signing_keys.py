"""FINCO public signing-key registry — single public trust authority for
Signed Run Certificate V1 (M-2).

Single source of truth: ``signing_keys_registry.json`` (version-controlled,
deterministic, auditable).  This module loads that manifest at import time
and exposes typed lookups.  Runtime registration is available only for
tests — production trust must NOT depend on process-local registration.

Only PUBLIC key material lives here.  Private signing keys come exclusively
from deployment configuration (``FINCO_RUN_CERT_SIGNING_KEY``) and are never
committed, logged, or returned.

Rotation model (V1):
  ACTIVE       — may sign NEW certificates and verify historical ones.
  VERIFY_ONLY  — retired from issuance; still verifies historical
                 certificates.  Retiring a key must never make historical
                 certificates unverifiable.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

SCHEMA_VERSION = "finco-signing-keys-v1"
ISSUER = "FINCO Protocol"
ALGORITHM_ED25519 = "Ed25519"
PUBLIC_KEY_ENCODING = "DER"
STATUS_ACTIVE = "ACTIVE"
STATUS_VERIFY_ONLY = "VERIFY_ONLY"
_VALID_STATUSES = frozenset({STATUS_ACTIVE, STATUS_VERIFY_ONLY})

_REGISTRY_MANIFEST = Path(__file__).parent / "signing_keys_registry.json"


@dataclass(frozen=True)
class SigningKeyRecord:
    """Public trust record for one FINCO Ed25519 signing key.

    ``public_key_der_b64`` is base64 of the DER-encoded public key.
    No private material is ever stored or transported here.
    """
    kid: str
    algorithm: str
    public_key_der_b64: str
    public_key_encoding: str
    jwk: dict
    status: str
    activated_at: str
    retired_at: str
    issuer: str
    schema_version: str

    def public_key_der(self) -> bytes:
        return base64.b64decode(self.public_key_der_b64, validate=True)

    def public_key_jwk(self) -> dict:
        return dict(self.jwk)


def _load_bundled_registry() -> Dict[str, SigningKeyRecord]:
    """Load the version-controlled manifest at import time (once)."""
    try:
        manifest = json.loads(_REGISTRY_MANIFEST.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    result: Dict[str, SigningKeyRecord] = {}
    for entry in manifest.get("keys", []):
        try:
            result[entry["kid"]] = SigningKeyRecord(
                kid=entry["kid"],
                algorithm=entry.get("algorithm", ALGORITHM_ED25519),
                public_key_der_b64=entry["public_key"],
                public_key_encoding=entry.get("public_key_encoding", "DER"),
                jwk=entry.get("jwk", {}),
                status=entry.get("status", STATUS_ACTIVE),
                activated_at=entry.get("activated_at", ""),
                retired_at=entry.get("retired_at") or "",
                issuer=entry.get("issuer", ISSUER),
                schema_version=manifest.get("schema_version", SCHEMA_VERSION),
            )
        except (KeyError, TypeError):
            continue
    return result


_BUNDLED = _load_bundled_registry()
_REGISTRY: Dict[str, SigningKeyRecord] = dict(_BUNDLED)


def register_key(record: SigningKeyRecord) -> SigningKeyRecord:
    """Register (or replace) a public signing-key record.

    Validates structure and Ed25519 key type fail-closed using the
    cryptographic parser.  Returns the record.  Runtime registration is
    available for tests only — production trust uses the version-controlled
    manifest.
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
    # Real Ed25519 key validation — not just base64 decoding.
    from Crypto.PublicKey import ECC
    try:
        der = record.public_key_der()
        key = ECC.import_key(der)
        if key.curve != "Ed25519":
            raise ValueError(f"key is {key.curve}, not Ed25519")
    except Exception as exc:
        raise ValueError(
            f"signing key record {record.kid!r}: invalid Ed25519 public key "
            f"({type(exc).__name__}: {exc})"
        ) from exc
    _REGISTRY[record.kid] = record
    return record


def register_key_values(
    kid: str,
    public_key_der: bytes,
    *,
    algorithm: str = ALGORITHM_ED25519,
    status: str = STATUS_ACTIVE,
    activated_at: str = "",
    retired_at: str = "",
    issuer: str = ISSUER,
) -> SigningKeyRecord:
    """Convenience wrapper: register from raw DER bytes."""
    import base64 as _b64
    der_b64 = _b64.b64encode(public_key_der).decode("ascii")
    jwk_x = _b64.urlsafe_b64encode(public_key_der[-32:]).decode("ascii").rstrip("=")
    jwk = {"kty": "OKP", "crv": "Ed25519", "x": jwk_x}
    return register_key(SigningKeyRecord(
        kid=kid,
        algorithm=algorithm,
        public_key_der_b64=der_b64,
        public_key_encoding=PUBLIC_KEY_ENCODING,
        jwk=jwk,
        status=status,
        activated_at=activated_at,
        retired_at=retired_at,
        issuer=issuer,
        schema_version=SCHEMA_VERSION,
    ))


def unregister_key(kid: str) -> None:
    """Remove a runtime-registered record (test/config housekeeping only)."""
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
                "public_key_encoding": record.public_key_encoding,
                "jwk": record.public_key_jwk(),
                "activated_at": record.activated_at,
                "retired_at": record.retired_at,
                "issuer": record.issuer,
                "schema_version": record.schema_version,
                "certificate_schema_version": "finco-run-certificate-v1",
            }
            for record in all_keys()
        ],
    }
