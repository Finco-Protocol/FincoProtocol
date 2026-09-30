"""FINCO offline verifier — standalone Signed Run certificate verification.

Operates WITHOUT: database, web app, financial engine, FINCO session,
wallet, token, Radar, or FINCO Verify.

Trust source (M-2 Correction B):
  A. the version-controlled FINCO public signing-key registry manifest
     (app/protocol/signing_keys_registry.json) bundled with this
     repository — the DEFAULT trust root.  It ships with ``keys: []``:
     no key is trusted by default (PUBLIC_ISSUER_KEY_NOT_CONFIGURED), so
     certificates verify only once a real deployment commits its public
     issuer key to the reviewed manifest.
  B. an explicit keys.json document (``--keys <path>``) downloaded from
     ``/.well-known/finco/keys.json``.  External documents are validated
     STRICTLY and ATOMICALLY; any malformed entry yields a typed
     ``KEYS_DOCUMENT_INVALID`` failure — never a traceback.

This CLI is a THIN ADAPTER over the ONE shared verification core
(``app.protocol.run_certificate_verifier.verify_certificate``) — the same
state machine the public API uses.  The same certificate plus the same
registry returns the same state here and through the API.

Output: deterministic machine-readable JSON verdict.  Verdict states are
cryptographic: VALID / INVALID_SIGNATURE / UNKNOWN_KEY_ID /
KEY_NOT_VERIFY_CAPABLE / KEY_NOT_VALID_FOR_CERTIFICATE_TIME /
PAYLOAD_DIGEST_MISMATCH / UNSUPPORTED_CERTIFICATE_VERSION /
MALFORMED_CERTIFICATE / UNSUPPORTED_ALGORITHM / KEYS_DOCUMENT_INVALID /
VERIFICATION_UNAVAILABLE.  The verdict is NEVER an economic judgment,
never FINCO Verify, never a blockchain claim.  Failure output is sanitized:
no raw exception text, no tracebacks, no key material.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

# External keys documents above this size are rejected as malformed.
MAX_KEYS_DOCUMENT_BYTES = 1_000_000


def _load_keys_document(path: Optional[str]):
    """Return (records, error_result).  Exactly one is non-None.

    Default trust root: the bundled version-controlled manifest, already
    strictly validated at import (fail-closed).  ``--keys`` documents are
    validated atomically; any malformation returns a typed sanitized
    failure.
    """
    from app.protocol.run_certificate_verifier import (
        STATE_KEYS_DOCUMENT_INVALID,
        STATE_VERIFICATION_UNAVAILABLE,
    )
    from app.protocol.signing_keys import (
        SigningKeyRegistryError,
        all_keys,
        validate_keys_document,
    )

    if path is None:
        return all_keys(), None
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return None, {
            "state": STATE_VERIFICATION_UNAVAILABLE,
            "detail": f"unreadable keys document ({type(exc).__name__}).",
        }
    if len(raw) > MAX_KEYS_DOCUMENT_BYTES:
        return None, {
            "state": STATE_KEYS_DOCUMENT_INVALID,
            "detail": "keys document exceeds the maximum allowed size.",
        }
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, {
            "state": STATE_KEYS_DOCUMENT_INVALID,
            "detail": f"keys document is not valid JSON ({type(exc).__name__}).",
        }
    try:
        return validate_keys_document(document), None
    except SigningKeyRegistryError as exc:
        return None, {
            "state": STATE_KEYS_DOCUMENT_INVALID,
            "detail": str(exc),
        }


def main(argv: Optional[list] = None) -> int:
    from app.protocol.run_certificate_verifier import (
        STATE_VERIFICATION_UNAVAILABLE,
        STATE_VALID,
        verify_certificate,
    )

    parser = argparse.ArgumentParser(
        description="Offline FINCO Signed Run certificate verifier. "
                    "Cryptographic provenance/integrity verification ONLY — "
                    "never an economic judgment, never FINCO Verify."
    )
    parser.add_argument("certificate", help="Path to the certificate JSON file.")
    parser.add_argument("--keys", dest="keys_path", default=None,
                        help="Optional keys.json document; defaults to the "
                             "version-controlled FINCO public key registry "
                             "bundled with this repository (ships empty: "
                             "PUBLIC_ISSUER_KEY_NOT_CONFIGURED).")
    args = parser.parse_args(argv)

    try:
        certificate = json.loads(
            Path(args.certificate).read_text(encoding="utf-8"))
    except Exception as exc:
        print(json.dumps({"state": "MALFORMED_CERTIFICATE",
                          "detail": f"unreadable certificate file: "
                                    f"{type(exc).__name__}"}, indent=2))
        return 1

    try:
        records, keys_error = _load_keys_document(args.keys_path)
    except Exception:
        records, keys_error = None, {
            "state": STATE_VERIFICATION_UNAVAILABLE,
            "detail": "trust document loading failed.",
        }
    if keys_error is not None:
        print(json.dumps(keys_error, indent=2, sort_keys=True))
        return 1

    try:
        result = verify_certificate(certificate, records)
    except Exception:
        # Absolute last resort — never leak a traceback or exception text.
        result = {
            "state": STATE_VERIFICATION_UNAVAILABLE,
            "detail": "verification failed unexpectedly.",
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["state"] == STATE_VALID else 1


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
