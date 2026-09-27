#!/usr/bin/env python3
"""FINCO Solar Reference — standalone verifier.

Verifies the FINCO Solar Reference package without any FINCO internal imports.
Requires: Python 3.9+, stdlib (hashlib, json, urllib.request, base64, sys).
Requires: pycryptodome (pip install pycryptodome) for Ed25519 issuer authenticity.

PASS requires ALL four checks to succeed:
  1. Assumptions hash   — SHA-256 of assumptions matches certificate
  2. Outputs hash       — SHA-256 of outputs matches certificate
  3. Certificate digest — certificate is internally self-consistent
  4. Issuer signature   — Ed25519 signature is valid (FINCO issuer authenticity)

A missing or unavailable Ed25519 implementation is a FAIL — hash checks alone
prove content integrity but do NOT prove FINCO issued this certificate.

Use --integrity-only for hash-only inspection (see below).

Usage:
    # Full verification (requires pycryptodome):
    python verify_reference_package.py --base-url https://fincoprotocol.com

    # Offline verification from a downloaded package directory:
    python verify_reference_package.py --package-dir /path/to/package

    # Integrity-only mode (no signature check, NEVER outputs "authentic"):
    python verify_reference_package.py --base-url URL --integrity-only

Exits 0 on full PASS, non-zero on any FAIL or if signature verification is
unavailable in default mode.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import urllib.request
from typing import Any

ASSET_ID = "solar-reference-a"
DEFAULT_BASE_URL = "http://localhost:8000"


# ── I/O helpers ───────────────────────────────────────────────────────────────

def _read_local(package_dir: str, filename: str) -> bytes:
    path = os.path.join(package_dir, filename)
    with open(path, "rb") as f:
        return f.read()


def _fetch_url(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read()


def _load_artifact(
    name: str,
    *,
    package_dir: str | None,
    base_url: str | None,
) -> bytes:
    if package_dir:
        return _read_local(package_dir, name)
    assert base_url
    url = f"{base_url.rstrip('/')}/verify/reference/{ASSET_ID}/{name}"
    return _fetch_url(url)


# ── Crypto helpers ────────────────────────────────────────────────────────────

def _canonical_json(obj: Any) -> bytes:
    """FINCO_SORTED_JSON_V1: sort_keys=True, compact separators, UTF-8."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── Output helpers ────────────────────────────────────────────────────────────

def _fail(step: str, detail: str) -> None:
    print(f"\nFAIL [{step}]: {detail}", file=sys.stderr)
    sys.exit(1)


def _ok(step: str, detail: str) -> None:
    print(f"  OK [{step}]: {detail}")


# ── Verification steps ────────────────────────────────────────────────────────

def _verify_assumptions(certificate: dict, assumptions: dict) -> None:
    expected = certificate.get("identity", {}).get("assumptions_sha256", "")
    computed = _sha256(_canonical_json(assumptions))
    if computed != expected:
        _fail(
            "assumptions_sha256",
            f"mismatch\n  certificate: {expected}\n  computed:    {computed}",
        )
    _ok("assumptions_sha256", f"{computed[:32]}...")


def _verify_outputs(certificate: dict, outputs: dict) -> None:
    expected = certificate.get("identity", {}).get("outputs_sha256", "")
    computed = _sha256(_canonical_json(outputs))
    if computed != expected:
        _fail(
            "outputs_sha256",
            f"mismatch\n  certificate: {expected}\n  computed:    {computed}",
        )
    _ok("outputs_sha256", f"{computed[:32]}...")


def _verify_certificate_digest(certificate: dict) -> None:
    stored_digest = certificate.get("certificate_digest_sha256", "")
    stored_id = certificate.get("certificate_id", "")
    payload_only = {
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


def _verify_issuer_signature(
    certificate: dict,
    signature: dict,
    public_key_pem: str,
    *,
    integrity_only: bool,
) -> None:
    if integrity_only:
        print(
            "\n  INTEGRITY-ONLY MODE: issuer signature NOT verified.\n"
            "  Hash checks confirm content self-consistency only — NOT FINCO issuer authenticity.\n"
            "  Run without --integrity-only (and with pycryptodome) for full verification."
        )
        return

    try:
        from Crypto.PublicKey import ECC
        from Crypto.Signature import eddsa
    except ImportError:
        _fail(
            "signature",
            "pycryptodome is not installed. Ed25519 verification is required for full PASS.\n"
            "  Install: pip install pycryptodome\n"
            "  Or use --integrity-only for hash-only inspection (does not prove issuer authenticity).",
        )
        return  # unreachable; _fail exits

    try:
        pub = ECC.import_key(public_key_pem)
        sig_bytes = base64.b64decode(signature["signature_b64"])
        message = _canonical_json(certificate)
        verifier = eddsa.new(pub, "rfc8032")
        verifier.verify(message, sig_bytes)
    except Exception as exc:
        _fail("signature", f"Ed25519 verification failed: {exc}")

    fingerprint = signature.get("public_key_fingerprint", "n/a")
    _ok("signature", f"Ed25519 valid (fingerprint: {fingerprint})")


# ── Main ──────────────────────────────────────────────────────────────────────

def main(
    *,
    base_url: str | None,
    package_dir: str | None,
    integrity_only: bool,
) -> None:
    source = f"package-dir: {package_dir}" if package_dir else f"base-url: {base_url}"
    print("FINCO Solar Reference — standalone verifier")
    print(f"Source   : {source}")
    print(f"Asset ID : {ASSET_ID}")
    if integrity_only:
        print("Mode     : INTEGRITY-ONLY (hash checks only; issuer authenticity NOT verified)")
    print()

    def load(name: str) -> bytes:
        return _load_artifact(name, package_dir=package_dir, base_url=base_url)

    print("Loading artifacts...")
    try:
        certificate = json.loads(load("certificate.json"))
        assumptions = json.loads(load("assumptions.json"))
        outputs     = json.loads(load("outputs.json"))
        signature   = json.loads(load("signature.json"))
        public_key  = load("public-key.pem").decode()
    except Exception as exc:
        _fail("load", str(exc))
        return  # unreachable

    print()
    _verify_assumptions(certificate, assumptions)
    _verify_outputs(certificate, outputs)
    _verify_certificate_digest(certificate)
    _verify_issuer_signature(
        certificate, signature, public_key, integrity_only=integrity_only
    )

    print()
    print("=" * 60)
    if integrity_only:
        print("INTEGRITY CHECK ONLY — content is self-consistent.")
        print("  Issuer authenticity was NOT verified.")
        print("  Use full mode (pycryptodome required) to confirm FINCO issued this package.")
    else:
        print("PASS — FINCO Solar Reference package is authentic and unmodified.")
        print("  Ed25519 signature confirms FINCO issued this exact certificate.")
        print("  Note: this proves issuer authenticity, not economic correctness")
        print("  or external-data authenticity.")
    print(f"  Certificate ID  : {certificate.get('certificate_id')}")
    print(f"  Engine version  : {certificate.get('model', {}).get('engine_version', 'n/a')}")
    print(f"  Project code    : {certificate.get('run', {}).get('project_code', 'n/a')}")
    print("=" * 60)
    sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="FINCO Solar Reference standalone verifier",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Full PASS requires pycryptodome (pip install pycryptodome).\n"
            "Ed25519 issuer signature is mandatory for full PASS.\n"
            "Use --integrity-only for hash-only inspection (not issuer-authenticated)."
        ),
    )
    src = parser.add_mutually_exclusive_group()
    src.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Base URL of the FINCO server (default: {DEFAULT_BASE_URL})",
    )
    src.add_argument(
        "--package-dir",
        metavar="DIR",
        help=(
            "Directory containing pre-downloaded artifacts "
            "(certificate.json, assumptions.json, outputs.json, signature.json, public-key.pem). "
            "Enables offline/CI verification without network access."
        ),
    )
    parser.add_argument(
        "--integrity-only",
        action="store_true",
        default=False,
        help=(
            "Hash-only inspection mode: verify SHA-256 hashes and certificate digest "
            "but skip Ed25519 signature. Output is 'INTEGRITY CHECK ONLY', never 'PASS'. "
            "Does NOT prove FINCO issued this certificate."
        ),
    )
    args = parser.parse_args()
    main(
        base_url=args.base_url if not args.package_dir else None,
        package_dir=args.package_dir,
        integrity_only=args.integrity_only,
    )
