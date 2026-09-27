"""FINCO Issuer Signature V1 — Ed25519 signing and verification (application layer).

Private key: loaded from FINCO_ISSUER_PRIVATE_KEY_HEX env var (hex-encoded 32-byte seed).
Public key: derived from private key; may be served publicly.

Algorithm: Ed25519 (RFC 8032) via pycryptodome.
Schema: FINCO_ISSUER_SIGNATURE_V1

Signature covers canonical_json_bytes(certificate_dict).
"""
from __future__ import annotations

import base64
import os
from typing import Any

ISSUER_SIGNATURE_SCHEMA = "FINCO_ISSUER_SIGNATURE_V1"
_ENV_KEY = "FINCO_ISSUER_PRIVATE_KEY_HEX"


class IssuerKeyNotConfigured(Exception):
    """Raised when no issuer private key is available in the environment."""


def _load_private_key():
    """Load Ed25519 private key from env var. Returns ECC key object."""
    from Crypto.PublicKey import ECC
    hex_seed = os.environ.get(_ENV_KEY, "").strip()
    if not hex_seed:
        raise IssuerKeyNotConfigured(
            f"{_ENV_KEY} environment variable is not set. "
            "Issuer signatures require this key to be configured."
        )
    seed = bytes.fromhex(hex_seed)
    if len(seed) != 32:
        raise IssuerKeyNotConfigured(
            f"{_ENV_KEY} must be exactly 32 bytes (64 hex chars); got {len(seed)} bytes."
        )
    return ECC.construct(curve="Ed25519", seed=seed)


def get_public_key_pem() -> str:
    """Return PEM-encoded Ed25519 public key for the configured issuer key."""
    priv = _load_private_key()
    return priv.public_key().export_key(format="PEM")


def get_public_key_hex() -> str:
    """Return hex-encoded raw Ed25519 public key bytes (32 bytes = 64 hex chars)."""
    priv = _load_private_key()
    pub = priv.public_key()
    return pub.pointQ.x.to_bytes(32, "little").hex()


def sign_certificate(certificate: dict[str, Any]) -> dict[str, Any]:
    """Build FINCO_ISSUER_SIGNATURE_V1 for the given certificate dict.

    Message = canonical_json_bytes(certificate).
    Raises IssuerKeyNotConfigured if the private key env var is absent.
    """
    from Crypto.Signature import eddsa
    from finco_protocol.verification.envelope import canonical_json_bytes, canonical_sha256

    priv = _load_private_key()
    pub = priv.public_key()

    message = canonical_json_bytes(certificate)
    signer = eddsa.new(priv, "rfc8032")
    sig_bytes = signer.sign(message)

    pub_pem = pub.export_key(format="PEM")
    key_fingerprint = canonical_sha256(pub_pem)[:16]

    return {
        "schema": ISSUER_SIGNATURE_SCHEMA,
        "algorithm": "Ed25519",
        "certificate_id": certificate.get("certificate_id"),
        "certificate_digest_sha256": certificate.get("certificate_digest_sha256"),
        "public_key_fingerprint": key_fingerprint,
        "signature_b64": base64.b64encode(sig_bytes).decode(),
    }


def verify_signature_with_pem(
    certificate: dict[str, Any],
    signature_dict: dict[str, Any],
    public_key_pem: str,
) -> bool:
    """Verify FINCO_ISSUER_SIGNATURE_V1 against certificate using a PEM public key.

    Checks ALL envelope metadata bindings before attempting Ed25519 verification:
      1. schema == FINCO_ISSUER_SIGNATURE_V1
      2. algorithm == Ed25519
      3. certificate_id matches certificate
      4. certificate_digest_sha256 matches certificate
      5. public_key_fingerprint matches recomputed fingerprint from PEM
      6. Ed25519 signature over canonical certificate JSON

    Returns True only if all six checks pass; False on any failure.
    """
    from Crypto.PublicKey import ECC
    from Crypto.Signature import eddsa
    from finco_protocol.verification.envelope import canonical_json_bytes, canonical_sha256

    try:
        # 1. Schema
        if signature_dict.get("schema") != ISSUER_SIGNATURE_SCHEMA:
            return False
        # 2. Algorithm
        if signature_dict.get("algorithm") != "Ed25519":
            return False
        # 3. Certificate ID binding
        if signature_dict.get("certificate_id") != certificate.get("certificate_id"):
            return False
        # 4. Certificate digest binding
        if signature_dict.get("certificate_digest_sha256") != certificate.get("certificate_digest_sha256"):
            return False
        # 5. Public key fingerprint binding
        pub = ECC.import_key(public_key_pem)
        computed_pem = pub.export_key(format="PEM")
        computed_fingerprint = canonical_sha256(computed_pem)[:16]
        if computed_fingerprint != signature_dict.get("public_key_fingerprint"):
            return False
        # 6. Ed25519 signature
        sig_bytes = base64.b64decode(signature_dict["signature_b64"])
        message = canonical_json_bytes(certificate)
        verifier = eddsa.new(pub, "rfc8032")
        verifier.verify(message, sig_bytes)
        return True
    except Exception:  # noqa: BLE001
        return False
