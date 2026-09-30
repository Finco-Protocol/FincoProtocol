"""FINCO public signing-key registry — single public trust authority for
Signed Run Certificate V1 (M-2, Correction B).

Trust-root policy (P0): the version-controlled manifest
``signing_keys_registry.json`` ships with ``keys: []`` — NO default trusted
signing key.  No key whose private counterpart (seed, derivation material,
test fixture, deterministic construction) is publicly known may EVER be
shipped as a runtime/default trust anchor.  A production issuer public key
is committed only when supplied by a real deployment, with a truthful kid;
its private key stays outside git, logs, and PRs.  Until then public
verification returns ``UNKNOWN_KEY_ID`` for every certificate and issuance
fails closed — documented as ``PUBLIC_ISSUER_KEY_NOT_CONFIGURED``.

Deterministic fixture keys (e.g. ``seed = bytes(range(32))``) live ONLY in
test code / tmp fixtures.  They are never the private counterpart of any
bundled trusted key.

This module owns:
  - the ``SigningKeyRecord`` public trust record (PUBLIC material only);
  - STRICT ATOMIC validation of key entries and whole documents (P1):
    exact schema version, Ed25519-only, DER-only, unique non-empty kids,
    cryptographically valid keys, JWK kty/crv/x bound to the DER key,
    explicit timezone-aware ``activated_at`` (optional tz-aware
    ``retired_at`` with ``activated_at < retired_at``), allowed status,
    issuer/schema consistency.  Any invalid entry fails the WHOLE
    document — no partially accepted trust registry is ever exposed.
  - runtime registration (tests / deployment bootstrap only — production
    trust comes from the reviewed manifest);

Rotation model (V1, P5):
  ACTIVE     — may sign NEW certificates and verify historical ones.
  VERIFY_ONLY — retired from issuance; still verifies historical
                certificates.  Retiring a key must never make historical
                certificates unverifiable.
  REVOKED    — compromised/revoked: no issuance, NO verification.  Rotation
               is not compromise: a compromised key must be removable from
               trust even if that invalidates certificates relying on it.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

SCHEMA_VERSION = "finco-signing-keys-v1"
ISSUER = "FINCO Protocol"
ALGORITHM_ED25519 = "Ed25519"
PUBLIC_KEY_ENCODING = "DER"
CERTIFICATE_SCHEMA_VERSION = "finco-run-certificate-v1"
STATUS_ACTIVE = "ACTIVE"
STATUS_VERIFY_ONLY = "VERIFY_ONLY"
STATUS_REVOKED = "REVOKED"
_VALID_STATUSES = frozenset({STATUS_ACTIVE, STATUS_VERIFY_ONLY, STATUS_REVOKED})

# Fields allowed in one manifest / keys-document entry.  Anything else is a
# validation failure (strict schema — unknown fields never silently pass).
_ALLOWED_ENTRY_FIELDS = frozenset({
    "kid", "algorithm", "public_key", "public_key_encoding", "jwk", "status",
    "activated_at", "retired_at", "issuer", "schema_version",
    "certificate_schema_version", "notes",
})

_REGISTRY_MANIFEST = Path(__file__).parent / "signing_keys_registry.json"


class SigningKeyRegistryError(RuntimeError):
    """Raised when a signing-key manifest or keys document fails STRICT
    validation.  Fail-closed: the whole document is rejected atomically."""


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


def parse_strict_iso_utc(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp that MUST be timezone-aware.

    Returns None when the value is absent, unparseable, or NAIVE — naive
    timestamps are never silently interpreted as UTC (P4 strictness).
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _require(condition: bool, kid: str, reason: str) -> None:
    if not condition:
        raise SigningKeyRegistryError(f"signing key entry {kid!r}: {reason}")


def validate_signing_key_entry(entry: Any) -> SigningKeyRecord:
    """STRICTLY validate one manifest / keys-document entry (P1).

    Every field is checked: exact schema/algorithm/encoding, unique-kid is
    enforced by the document-level loader, real Ed25519 cryptographic import,
    JWK kty/crv/x bound to the exact DER key bytes, explicit timezone-aware
    validity window, allowed status, issuer/schema consistency.  Any failure
    raises ``SigningKeyRegistryError`` — callers never receive a partial
    record.
    """
    kid_hint = entry.get("kid") if isinstance(entry, dict) else None
    kid_hint = kid_hint if isinstance(kid_hint, str) and kid_hint.strip() else "<unspecified>"

    if not isinstance(entry, dict):
        raise SigningKeyRegistryError(
            f"signing key entry {kid_hint!r}: entry must be a JSON object")
    unknown = sorted(set(entry) - _ALLOWED_ENTRY_FIELDS)
    _require(not unknown, kid_hint,
             f"unknown field(s) {unknown!r} (strict schema)")

    kid = entry.get("kid")
    _require(isinstance(kid, str) and kid.strip(), kid_hint,
             "kid is required and must be a non-empty string")
    kid = kid.strip()

    _require(entry.get("algorithm") == ALGORITHM_ED25519, kid,
             f"algorithm must be {ALGORITHM_ED25519!r}, got "
             f"{entry.get('algorithm')!r}")
    _require(entry.get("public_key_encoding") == PUBLIC_KEY_ENCODING, kid,
             f"public_key_encoding must be {PUBLIC_KEY_ENCODING!r}, got "
             f"{entry.get('public_key_encoding')!r}")

    public_key_b64 = entry.get("public_key")
    _require(isinstance(public_key_b64, str) and public_key_b64.strip(), kid,
             "public_key is required")
    try:
        der = base64.b64decode(public_key_b64, validate=True)
    except Exception as exc:
        raise SigningKeyRegistryError(
            f"signing key entry {kid!r}: public_key is not valid base64 "
            f"({type(exc).__name__})") from exc

    from Crypto.PublicKey import ECC
    try:
        key = ECC.import_key(der)
        if getattr(key, "curve", None) != "Ed25519":
            raise SigningKeyRegistryError(
                f"signing key entry {kid!r}: key curve is "
                f"{getattr(key, 'curve', None)!r}, not Ed25519")
    except SigningKeyRegistryError:
        raise
    except Exception as exc:
        raise SigningKeyRegistryError(
            f"signing key entry {kid!r}: public_key is not a valid Ed25519 "
            f"DER key ({type(exc).__name__})") from exc

    # JWK binding: kty/crv fixed; x must be EXACTLY the DER key's raw 32-byte
    # public point (last 32 bytes of the DER encoding), base64url-encoded.
    jwk = entry.get("jwk")
    _require(isinstance(jwk, dict), kid, "jwk is required and must be an object")
    _require(jwk.get("kty") == "OKP", kid,
             f"jwk.kty must be 'OKP', got {jwk.get('kty')!r}")
    _require(jwk.get("crv") == "Ed25519", kid,
             f"jwk.crv must be 'Ed25519', got {jwk.get('crv')!r}")
    jwk_x = jwk.get("x")
    _require(isinstance(jwk_x, str) and jwk_x, kid,
             "jwk.x is required")
    expected_x = base64.urlsafe_b64encode(der[-32:]).decode("ascii").rstrip("=")
    _require(jwk_x == expected_x, kid,
             "jwk.x does not match the DER public key (JWK/DER binding)")

    status = entry.get("status")
    _require(status in _VALID_STATUSES, kid,
             f"status must be one of {sorted(_VALID_STATUSES)}, got {status!r}")

    # Explicit timezone-aware validity window.  Naive timestamps are
    # rejected — never silently interpreted as UTC.
    activated = parse_strict_iso_utc(entry.get("activated_at"))
    _require(activated is not None, kid,
             "activated_at is required and must be a timezone-aware "
             "ISO-8601 timestamp")
    retired_raw = entry.get("retired_at")
    if retired_raw is None:
        retired = None
    else:
        retired = parse_strict_iso_utc(retired_raw)
        _require(retired is not None, kid,
                 "retired_at must be a timezone-aware ISO-8601 timestamp "
                 "or null")
        _require(activated < retired, kid,
                 "activated_at must be earlier than retired_at")

    entry_issuer = entry.get("issuer", ISSUER)
    _require(entry_issuer == ISSUER, kid,
             f"issuer must be {ISSUER!r}, got {entry_issuer!r}")
    entry_schema = entry.get("schema_version", SCHEMA_VERSION)
    _require(entry_schema == SCHEMA_VERSION, kid,
             f"schema_version must be {SCHEMA_VERSION!r}, got "
             f"{entry_schema!r}")
    entry_cert_schema = entry.get("certificate_schema_version")
    if entry_cert_schema is not None:
        _require(entry_cert_schema == CERTIFICATE_SCHEMA_VERSION, kid,
                 f"certificate_schema_version must be "
                 f"{CERTIFICATE_SCHEMA_VERSION!r}, got {entry_cert_schema!r}")
    notes = entry.get("notes")
    _require(notes is None or isinstance(notes, str), kid,
             "notes must be a string when present")

    return SigningKeyRecord(
        kid=kid,
        algorithm=ALGORITHM_ED25519,
        public_key_der_b64=public_key_b64,
        public_key_encoding=PUBLIC_KEY_ENCODING,
        jwk=dict(jwk),
        status=status,
        activated_at=entry["activated_at"],
        retired_at=entry.get("retired_at") or "",
        issuer=entry_issuer,
        schema_version=SCHEMA_VERSION,
    )


def validate_keys_document(document: Any) -> Tuple[SigningKeyRecord, ...]:
    """STRICTLY and ATOMICALLY validate a whole signing-keys document
    (bundled manifest or an external ``keys.json``).

    Exact schema_version, exact issuer, ``keys`` must be a list, every entry
    fully validated, no duplicate kids.  ANY failure raises
    ``SigningKeyRegistryError`` for the WHOLE document — a partially
    accepted trust registry is never returned (P1).
    """
    if not isinstance(document, dict):
        raise SigningKeyRegistryError(
            "signing-keys document: document must be a JSON object")
    _require(document.get("schema_version") == SCHEMA_VERSION, "<document>",
             f"schema_version must be {SCHEMA_VERSION!r}, got "
             f"{document.get('schema_version')!r}")
    _require(document.get("issuer") == ISSUER, "<document>",
             f"issuer must be {ISSUER!r}, got {document.get('issuer')!r}")
    keys = document.get("keys")
    _require(isinstance(keys, list), "<document>",
             "'keys' must be a list")

    records: Dict[str, SigningKeyRecord] = {}
    for entry in keys:
        record = validate_signing_key_entry(entry)
        _require(record.kid not in records, record.kid,
                 "duplicate kid in signing-keys document")
        records[record.kid] = record
    return tuple(records[k] for k in sorted(records))


def load_registry_manifest(path: Path) -> Tuple[SigningKeyRecord, ...]:
    """Load and STRICTLY validate a registry manifest file (atomic)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SigningKeyRegistryError(
            f"signing-keys manifest {path.name}: unreadable "
            f"({type(exc).__name__})") from exc
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SigningKeyRegistryError(
            f"signing-keys manifest {path.name}: invalid JSON "
            f"({type(exc).__name__})") from exc
    return validate_keys_document(document)


def _load_bundled_registry() -> Dict[str, SigningKeyRecord]:
    """Load the version-controlled manifest at import time.

    Fail-closed: an invalid bundled manifest raises at import — the process
    refuses to boot with a corrupt public trust root.  The shipped manifest
    contains ``keys: []`` (no default trust key; see module docstring).
    """
    records = load_registry_manifest(_REGISTRY_MANIFEST)
    return {record.kid: record for record in records}


_BUNDLED = _load_bundled_registry()
_REGISTRY: Dict[str, SigningKeyRecord] = dict(_BUNDLED)


def register_key(record: SigningKeyRecord) -> SigningKeyRecord:
    """Register (or replace) a public signing-key record.

    Validates structure and Ed25519 key type fail-closed using the
    cryptographic parser, including the JWK/DER binding and strict
    timezone-aware validity window.  Returns the record.  Runtime
    registration is available for tests / deployment bootstrap only —
    production trust uses the version-controlled manifest.
    """
    validated = validate_signing_key_entry({
        "kid": record.kid,
        "algorithm": record.algorithm,
        "public_key": record.public_key_der_b64,
        "public_key_encoding": record.public_key_encoding,
        "jwk": record.jwk,
        "status": record.status,
        "activated_at": record.activated_at,
        "retired_at": record.retired_at or None,
        "issuer": record.issuer,
        "schema_version": record.schema_version,
    })
    _REGISTRY[validated.kid] = validated
    return validated


def register_key_values(
    kid: str,
    public_key_der: bytes,
    *,
    algorithm: str = ALGORITHM_ED25519,
    status: str = STATUS_ACTIVE,
    activated_at: str,
    retired_at: Optional[str] = None,
    issuer: str = ISSUER,
) -> SigningKeyRecord:
    """Convenience wrapper: register from raw DER bytes.

    ``activated_at`` is REQUIRED and must be timezone-aware ISO-8601 —
    there is no implicit validity window.
    """
    der_b64 = base64.b64encode(public_key_der).decode("ascii")
    jwk_x = base64.urlsafe_b64encode(public_key_der[-32:]).decode("ascii").rstrip("=")
    jwk = {"kty": "OKP", "crv": "Ed25519", "x": jwk_x}
    return register_key(SigningKeyRecord(
        kid=kid,
        algorithm=algorithm,
        public_key_der_b64=der_b64,
        public_key_encoding=PUBLIC_KEY_ENCODING,
        jwk=jwk,
        status=status,
        activated_at=activated_at,
        retired_at=retired_at or "",
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
    """VERIFY_ONLY and ACTIVE keys verify historical certificates.

    REVOKED (compromised) keys verify NOTHING — rotation is not compromise.
    """
    return record.status in (STATUS_ACTIVE, STATUS_VERIFY_ONLY)


def is_issuance_capable(record: SigningKeyRecord) -> bool:
    """Only ACTIVE keys may sign NEW certificates."""
    return record.status == STATUS_ACTIVE


def public_keys_document() -> dict:
    """Deterministic public trust document for the discovery endpoints.

    Contains only PUBLIC trust material.  No private key, seed, environment
    variable value, filesystem path, or credential metadata ever appears.
    With no production issuer key configured this ships ``keys: []``
    (``PUBLIC_ISSUER_KEY_NOT_CONFIGURED``) — discovery truthfully reports
    that nothing is trusted by default.
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
                "retired_at": record.retired_at or None,
                "issuer": record.issuer,
                "schema_version": record.schema_version,
                "certificate_schema_version": CERTIFICATE_SCHEMA_VERSION,
            }
            for record in all_keys()
        ],
    }
