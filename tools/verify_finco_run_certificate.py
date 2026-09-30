"""FINCO offline verifier — standalone Signed Run certificate verification.

Operates WITHOUT: database, web app, financial engine, FINCO session,
wallet, token, Radar, or FINCO Verify.

Trust source (M-2 Correction A):
  A. the version-controlled FINCO public signing-key registry manifest
     (app/protocol/signing_keys_registry.json), bundled with the
     repository/package — the DEFAULT and recommended trust root; or
  B. an explicit keys.json document (``--keys <path>``) downloaded from
     ``/.well-known/finco/keys.json``.

The kid binding is EXPLICIT: a certificate without a ``kid`` field is
malformed.  A legacy ``key_id`` fingerprint alone is never a trust anchor.

Checks mirror the public API verifier exactly, in the same order:
structural invariants → kid resolution → key verify capability
(ACTIVE/VERIFY_ONLY rotation contract) → key time validity
(activated_at/retired_at window vs. the certificate's issuance time) →
independent payload-digest recompute → Ed25519 signature over the
canonical signed bytes.

Output: deterministic machine-readable JSON verdict.  Verdict states are
cryptographic: VALID / INVALID_SIGNATURE / UNKNOWN_KEY_ID /
KEY_NOT_VERIFY_CAPABLE / KEY_NOT_VALID_FOR_CERTIFICATE_TIME /
PAYLOAD_DIGEST_MISMATCH / UNSUPPORTED_CERTIFICATE_VERSION /
MALFORMED_CERTIFICATE / UNSUPPORTED_ALGORITHM / VERIFICATION_UNAVAILABLE.
The verdict is NEVER an economic judgment, never FINCO Verify, never a
blockchain claim.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

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


def _verify(certificate: dict, keys_document: dict) -> dict:
    """Registry-backed verification using the same canonical serialization
    authority as issuance and the API surface."""
    from app.services.run_certificate_service import (
        canonical_certificate_signing_bytes,
    )
    from Crypto.PublicKey import ECC
    from Crypto.Signature import eddsa

    kid = certificate.get("kid") if isinstance(certificate, dict) else None
    base: Dict[str, Any] = {
        "kid": kid,
        "algorithm": certificate.get("signature_algorithm")
        if isinstance(certificate, dict) else None,
        "certificate_schema_version": certificate.get("certificate_schema_version")
        if isinstance(certificate, dict) else None,
        "certificate_digest": certificate.get("payload_digest")
        if isinstance(certificate, dict) else None,
        "signature_valid": False,
    }

    if not isinstance(certificate, dict) or not certificate:
        return {**base, "state": "MALFORMED_CERTIFICATE",
                "detail": "empty or non-object certificate"}
    if not certificate.get("signature"):
        return {**base, "state": "MALFORMED_CERTIFICATE", "detail": "missing signature"}
    if not certificate.get("payload_digest"):
        return {**base, "state": "MALFORMED_CERTIFICATE", "detail": "missing payload digest"}
    # M-2 Correction A: the kid binding is EXPLICIT — no key_id fallback.
    if not isinstance(kid, str) or not kid.strip():
        return {**base, "state": "MALFORMED_CERTIFICATE",
                "detail": "missing explicit kid binding"}
    if certificate.get("certificate_schema_version") != (
            SUPPORTED_CERTIFICATE_SCHEMA_VERSION):
        return {**base, "state": "UNSUPPORTED_CERTIFICATE_VERSION",
                "detail": f"unsupported schema: "
                          f"{certificate.get('certificate_schema_version')!r}"}
    if certificate.get("signature_algorithm") != SUPPORTED_ALGORITHM:
        return {**base, "state": "UNSUPPORTED_ALGORITHM",
                "detail": f"unsupported algorithm: "
                          f"{certificate.get('signature_algorithm')!r}"}

    # resolve kid from the keys document
    record = None
    for key in keys_document.get("keys", []):
        if key.get("kid") == kid:
            record = key
            break
    if record is None:
        return {**base, "state": "UNKNOWN_KEY_ID",
                "detail": f"kid {kid!r} is not a registered FINCO signing key"}
    if record.get("status") not in ("ACTIVE", "VERIFY_ONLY"):
        return {**base, "state": "KEY_NOT_VERIFY_CAPABLE",
                "detail": f"registered kid {kid!r} has status "
                          f"{record.get('status')!r} and cannot verify certificates"}

    # Key time validity: the key must have been inside its validity window
    # when the certificate was issued.
    certificate_time = _parse_iso_utc(
        certificate.get("issued_at") or certificate.get("run_at"))
    if certificate_time is None:
        return {**base, "state": "MALFORMED_CERTIFICATE",
                "detail": "certificate has no parseable issued_at or run_at "
                          "timestamp"}
    activated_at = _parse_iso_utc(record.get("activated_at"))
    retired_at = _parse_iso_utc(record.get("retired_at"))
    if activated_at is not None and certificate_time < activated_at:
        return {**base, "state": "KEY_NOT_VALID_FOR_CERTIFICATE_TIME",
                "detail": f"kid {kid!r} was activated after this certificate "
                          "was issued"}
    if retired_at is not None and certificate_time > retired_at:
        return {**base, "state": "KEY_NOT_VALID_FOR_CERTIFICATE_TIME",
                "detail": f"kid {kid!r} was retired before this certificate "
                          "was issued"}

    # Independent payload-digest recompute over the received fields.
    digest_input = {k: v for k, v in certificate.items()
                    if k not in ("payload_digest", "signature")}
    recomputed = hashlib.sha256(
        canonical_certificate_signing_bytes(digest_input)).hexdigest()
    if recomputed != certificate.get("payload_digest"):
        return {**base, "state": "PAYLOAD_DIGEST_MISMATCH",
                "detail": "payload digest does not match the independently "
                          "recomputed digest of the received certificate fields"}

    der = base64.b64decode(record["public_key"], validate=True)
    fingerprint = hashlib.sha256(der).hexdigest()[:16]
    if certificate.get("key_id") not in (None, fingerprint):
        return {**base, "state": "INVALID_SIGNATURE",
                "detail": "certificate key_id does not match the registered key"}

    # Signing bytes = canonical bytes of the certificate minus ONLY the
    # signature field.  The payload_digest field IS part of the signed
    # bytes (it was computed over the payload pre-digest at issuance).
    unsigned = {k: v for k, v in certificate.items() if k != "signature"}
    signing_bytes = canonical_certificate_signing_bytes(unsigned)
    signature = base64.b64decode(certificate["signature"], validate=True)

    try:
        pub = ECC.import_key(der)
        eddsa.new(pub, "rfc8032").verify(signing_bytes, signature)
    except Exception:
        # Sanitized: no exception text, no traceback, no key material.
        return {**base, "state": "INVALID_SIGNATURE",
                "detail": "Ed25519 signature does not verify over the "
                          "canonical bytes against the registered public key"}

    return {**base, "state": "VALID", "signature_valid": True,
            "detail": "cryptographic certificate verification passed"}


def _bundled_keys_document() -> dict:
    from app.protocol.signing_keys import public_keys_document
    return public_keys_document()


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline FINCO Signed Run certificate verifier. "
                    "Cryptographic provenance/integrity verification ONLY — "
                    "never an economic judgment, never FINCO Verify."
    )
    parser.add_argument("certificate", help="Path to the certificate JSON file.")
    parser.add_argument("--keys", dest="keys_path", default=None,
                        help="Optional keys.json document; defaults to the "
                             "version-controlled FINCO public key registry "
                             "bundled with this repository.")
    args = parser.parse_args(argv)

    try:
        certificate = json.loads(Path(args.certificate).read_text(encoding="utf-8"))
    except Exception as exc:
        print(json.dumps({"state": "MALFORMED_CERTIFICATE",
                          "detail": f"unreadable certificate file: "
                                    f"{type(exc).__name__}"}, indent=2))
        return 1

    if args.keys_path:
        try:
            keys_document = json.loads(Path(args.keys_path).read_text(encoding="utf-8"))
        except Exception as exc:
            print(json.dumps({"state": "VERIFICATION_UNAVAILABLE",
                              "detail": f"unreadable keys document: "
                                        f"{type(exc).__name__}"}, indent=2))
            return 1
    else:
        keys_document = _bundled_keys_document()

    result = _verify(certificate, keys_document)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["state"] == "VALID" else 1


if __name__ == "__main__":
    if __package__ in (None, ""):
        # allow direct execution: python tools/verify_finco_run_certificate.py
        _here = str(Path(__file__).resolve().parents[1])
        if _here not in sys.path:
            sys.path.insert(0, _here)
        # re-run main with import context available
        import importlib
        mod = importlib.import_module("tools.verify_finco_run_certificate")
        raise SystemExit(mod.main(sys.argv[1:]))
    raise SystemExit(main())
