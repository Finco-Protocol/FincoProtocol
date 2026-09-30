"""FINCO offline verifier — standalone Signed Run certificate verification.

Operates WITHOUT: database, web app, financial engine, FINCO session,
wallet, token, Radar, or FINCO Verify.

Trust source:
  A. the bundled FINCO public key registry (app/protocol/signing_keys.py), or
  B. an explicit keys.json document (``--keys <path>``) downloaded from
     ``/.well-known/finco/keys.json``.

Output: deterministic machine-readable JSON verdict.  Verdict states are
cryptographic: VALID / INVALID_SIGNATURE / UNKNOWN_KEY_ID /
UNSUPPORTED_CERTIFICATE_VERSION / MALFORMED_CERTIFICATE /
UNSUPPORTED_ALGORITHM.  The verdict is NEVER an economic judgment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Optional


def _verify(certificate: dict, keys_document: dict) -> dict:
    """Registry-backed verification using the same canonical serialization
    authority as issuance and the API surface."""
    from app.services.run_certificate_service import (
        canonical_certificate_signing_bytes,
    )
    from Crypto.PublicKey import ECC
    from Crypto.Signature import eddsa

    kid = certificate.get("kid") or certificate.get("key_id")
    base = {
        "kid": kid,
        "algorithm": certificate.get("signature_algorithm"),
        "certificate_schema_version": certificate.get("certificate_schema_version"),
        "certificate_digest": certificate.get("payload_digest"),
        "signature_valid": False,
    }

    if not isinstance(certificate, dict) or not certificate:
        return {**base, "state": "MALFORMED_CERTIFICATE",
                "detail": "empty or non-object certificate"}
    if not certificate.get("signature"):
        return {**base, "state": "MALFORMED_CERTIFICATE", "detail": "missing signature"}
    if not certificate.get("payload_digest"):
        return {**base, "state": "MALFORMED_CERTIFICATE", "detail": "missing payload digest"}
    if not kid:
        return {**base, "state": "MALFORMED_CERTIFICATE", "detail": "missing kid binding"}
    if certificate.get("certificate_schema_version") != "finco-run-certificate-v1":
        return {**base, "state": "UNSUPPORTED_CERTIFICATE_VERSION",
                "detail": f"unsupported schema: "
                          f"{certificate.get('certificate_schema_version')!r}"}
    if certificate.get("signature_algorithm") != "Ed25519":
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
        return {**base, "state": "MALFORMED_CERTIFICATE",
                "detail": f"registered kid {kid!r} has status {record.get('status')!r}"}

    import base64 as _b64
    der = _b64.b64decode(record["public_key"], validate=True)
    fingerprint = __import__("hashlib").sha256(der).hexdigest()[:16]
    if certificate.get("key_id") not in (None, fingerprint):
        return {**base, "state": "INVALID_SIGNATURE",
                "detail": "certificate key_id does not match the registered key"}

    # Signing bytes = canonical bytes WITHOUT signature and payload_digest
    # (matching issuance).
    # Signing bytes = canonical bytes of the certificate minus ONLY the
    # signature field.  The payload_digest field IS part of the signed
    # bytes (it was computed over the payload pre-digest at issuance).
    unsigned = {k: v for k, v in certificate.items() if k != "signature"}
    signing_bytes = canonical_certificate_signing_bytes(unsigned)
    signature = _b64.b64decode(certificate["signature"], validate=True)

    try:
        pub = ECC.import_key(der)
        eddsa.new(pub, "rfc8032").verify(signing_bytes, signature)
    except (ValueError, TypeError):
        return {**base, "state": "INVALID_SIGNATURE",
                "detail": "Ed25519 signature does not verify over the canonical bytes"}

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
                             "bundled FINCO public key registry.")
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
