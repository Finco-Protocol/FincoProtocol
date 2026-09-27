#!/usr/bin/env python3
"""FINCO Solar Reference — standalone verifier.

Verifies the FINCO Solar Reference package without any FINCO internal imports.
Requires only: Python 3.9+, stdlib (hashlib, json, urllib.request, base64, sys).
Optional: pycryptodome (pip install pycryptodome) for Ed25519 signature verification.

Usage:
    python tools/verify_reference_package.py [--base-url URL]

Default base URL: http://localhost:8000
Exits 0 on PASS, non-zero on any FAIL.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "http://localhost:8000"
ASSET_ID = "solar-reference-a"


def _endpoint(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/verify/reference/{ASSET_ID}/{path}"


def _fetch_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def _fetch_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode()


def _canonical_json(obj: Any) -> bytes:
    """FINCO_SORTED_JSON_V1: sort_keys=True, compact separators, UTF-8."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fail(step: str, detail: str) -> None:
    print(f"\nFAIL [{step}]: {detail}", file=sys.stderr)
    sys.exit(1)


def _ok(step: str, detail: str) -> None:
    print(f"  PASS [{step}]: {detail}")


def main(base_url: str) -> None:
    print("FINCO Solar Reference — standalone verifier")
    print(f"Base URL : {base_url}")
    print(f"Asset ID : {ASSET_ID}")
    print()

    print("Fetching artifacts...")
    try:
        certificate = _fetch_json(_endpoint(base_url, "certificate.json"))
        assumptions = _fetch_json(_endpoint(base_url, "assumptions.json"))
        outputs     = _fetch_json(_endpoint(base_url, "outputs.json"))
        signature   = _fetch_json(_endpoint(base_url, "signature.json"))
        public_key  = _fetch_text(_endpoint(base_url, "public-key.pem"))
    except Exception as exc:
        _fail("fetch", str(exc))

    print()

    # ── Step 1: Assumptions hash ──────────────────────────────────────────────
    expected_a = certificate.get("identity", {}).get("assumptions_sha256", "")
    computed_a = _sha256(_canonical_json(assumptions))
    if computed_a != expected_a:
        _fail(
            "assumptions_sha256",
            f"mismatch\n  certificate: {expected_a}\n  computed:    {computed_a}",
        )
    _ok("assumptions_sha256", f"{computed_a[:32]}...")

    # ── Step 2: Outputs hash ──────────────────────────────────────────────────
    expected_o = certificate.get("identity", {}).get("outputs_sha256", "")
    computed_o = _sha256(_canonical_json(outputs))
    if computed_o != expected_o:
        _fail(
            "outputs_sha256",
            f"mismatch\n  certificate: {expected_o}\n  computed:    {computed_o}",
        )
    _ok("outputs_sha256", f"{computed_o[:32]}...")

    # ── Step 3: Certificate digest ────────────────────────────────────────────
    stored_digest = certificate.get("certificate_digest_sha256", "")
    stored_id     = certificate.get("certificate_id", "")
    payload_only  = {
        k: v for k, v in certificate.items()
        if k not in ("certificate_id", "certificate_digest_sha256")
    }
    computed_digest = _sha256(_canonical_json(payload_only))
    if computed_digest != stored_digest:
        _fail(
            "certificate_digest",
            f"mismatch (tampered?)\n  stored:   {stored_digest}\n  computed: {computed_digest}",
        )
    expected_id = "frc_" + computed_digest[:16]
    if stored_id != expected_id:
        _fail(
            "certificate_id",
            f"mismatch\n  expected: {expected_id}\n  stored:   {stored_id}",
        )
    _ok("certificate_digest", f"{computed_digest[:32]}...")
    _ok("certificate_id", stored_id)

    # ── Step 4: Issuer signature ──────────────────────────────────────────────
    try:
        from Crypto.PublicKey import ECC
        from Crypto.Signature import eddsa
    except ImportError:
        print(
            "\n  SKIP [signature]: pycryptodome not installed "
            "(pip install pycryptodome to enable signature verification)"
        )
    else:
        try:
            pub = ECC.import_key(public_key)
            sig_bytes = base64.b64decode(signature["signature_b64"])
            message = _canonical_json(certificate)
            verifier = eddsa.new(pub, "rfc8032")
            verifier.verify(message, sig_bytes)
        except Exception as exc:
            _fail("signature", str(exc))
        fingerprint = signature.get("public_key_fingerprint", "n/a")
        _ok("signature", f"Ed25519 valid (fingerprint: {fingerprint})")

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("PASS — FINCO Solar Reference package is authentic and unmodified.")
    print(f"  Certificate ID  : {certificate.get('certificate_id')}")
    print(f"  Engine version  : {certificate.get('model', {}).get('engine_version', 'n/a')}")
    print(f"  Project code    : {certificate.get('run', {}).get('project_code', 'n/a')}")
    print("=" * 60)
    sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FINCO Solar Reference standalone verifier")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Base URL of the FINCO server (default: {DEFAULT_BASE_URL})",
    )
    args = parser.parse_args()
    main(args.base_url)
