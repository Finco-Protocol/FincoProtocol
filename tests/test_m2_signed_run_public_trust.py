"""M-2 — Signed Run public trust: registry, discovery, kid binding, public
verifier, offline verifier, trust-root security hardening (Correction B).

Authority separation: Signed Run verification is cryptographic provenance/
integrity ONLY.  No engine calls, no Verify mutation, no Radar/DB writes,
no token gating, no blockchain claims, no private-key exposure.

Correction B invariants proven here:
  - P0: the bundled/default trust root ships NO key whose private
    counterpart is publicly known — a certificate signed with the
    deterministic test seed is UNKNOWN_KEY_ID by default
    (KNOWN_TEST_PRIVATE_KEY_CAN_FORGE_DEFAULT_TRUST_ROOT = NO).
  - P1: manifest / keys-document validation is strict and atomic — any
    invalid entry rejects the WHOLE document.
  - P2: API and offline CLI share ONE verification core — same certificate
    plus same registry returns the same state through both.
  - P3: malformed external keys documents produce typed sanitized
    failures, never tracebacks.
  - P4: issued_at is required, timezone-aware, and the only time authority
    for key validity (no naive-as-UTC, no run_at fallback).
  - P5: REVOKED keys verify nothing — rotation is not compromise.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app import ev_charging_economics as ev  # noqa: F401 (EV context)
from app.protocol import signing_keys as reg
from app.protocol.signing_keys import (
    STATUS_ACTIVE,
    STATUS_VERIFY_ONLY,
    SigningKeyRecord,
    register_key_values,
)

TEST_SEED = bytes(range(32))  # deterministic fixture — TESTS ONLY, never a
# private counterpart of any bundled/default trusted key (P0/P7).
TEST_KID = "m2-test-fixture-2026-01"
TEST_ACTIVATED_AT = "2026-01-01T00:00:00+00:00"
TEST_PUBLIC_DER = __import__("Crypto.PublicKey.ECC", fromlist=["ECC"]).construct(
    curve="Ed25519", seed=TEST_SEED).public_key().export_key(format="DER")
TEST_SEED_B64 = base64.b64encode(TEST_SEED).decode()
TEST_PUBLIC_DER_B64 = base64.b64encode(TEST_PUBLIC_DER).decode()


def _stub_ws(**overrides):
    """Stub committed Last Run workspace with full canonical identity."""
    from types import SimpleNamespace
    from datetime import datetime, timezone
    base = {
        "project_id": "m2-pid", "project_code": "m2-code",
        "any_run_committed": True,
        "last_runtime_snapshot_id": "m2-snap",
        "last_runtime_composite_hash": "m2-composite-hash",
        "last_runtime_at": datetime.now(timezone.utc),
        "last_runtime_origin": "saved_state",
        "last_runtime_scenario_id": None,
        "last_runtime_identity": {
            "engine_version": "finco-engine-test",
            "workbook_version": "v2.0.0",
            "git_sha": "1" * 40,
            "git_branch": "protocol/m2-signed-run-public-trust",
            "project_type": "EV Charging",
            "template_source": "generic_ev_charging_reference",
            "composite_hash": "m2-composite-hash",
            "finco_verify_state": "NOT_VERIFIED",
        },
        "last_runtime_summary": {"project_irr": 0.147},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _registry_hygiene():
    """Every test starts with the test key correctly registered ACTIVE
    (canonical DER); teardown removes it so registry state never leaks
    between tests."""
    register_key_values(TEST_KID, TEST_PUBLIC_DER,
                        status=reg.STATUS_ACTIVE,
                        activated_at=TEST_ACTIVATED_AT)
    yield
    reg.unregister_key(TEST_KID)


@pytest.fixture()
def test_key():
    """Register the deterministic test key; clean up afterwards."""
    from Crypto.PublicKey import ECC
    der = ECC.construct(curve="Ed25519", seed=TEST_SEED).public_key().export_key(format="DER")
    record = register_key_values(TEST_KID, der, status=reg.STATUS_ACTIVE,
                                 activated_at=TEST_ACTIVATED_AT)
    yield record
    reg.unregister_key(TEST_KID)


@pytest.fixture()
def m2_env(monkeypatch, test_key):
    monkeypatch.setenv("FINCO_RUN_CERT_SIGNING_KEY", base64.b64encode(TEST_SEED).decode())
    monkeypatch.setenv("FINCO_RUN_CERT_SIGNING_KID", TEST_KID)
    return test_key


# ── Strict keys-document builder helpers (valid entries unless corrupted) ────

def _key_entry(der=TEST_PUBLIC_DER, kid=TEST_KID, status=STATUS_ACTIVE,
               activated_at=TEST_ACTIVATED_AT, retired_at=None, **overrides):
    entry = {
        "kid": kid,
        "algorithm": "Ed25519",
        "public_key": base64.b64encode(der).decode(),
        "public_key_encoding": "DER",
        "jwk": {
            "kty": "OKP", "crv": "Ed25519",
            "x": base64.urlsafe_b64encode(der[-32:]).decode().rstrip("="),
        },
        "status": status,
        "activated_at": activated_at,
        "retired_at": retired_at,
        "issuer": "FINCO Protocol",
    }
    entry.update(overrides)
    return entry


def _keys_document(*entries):
    return {
        "schema_version": "finco-signing-keys-v1",
        "issuer": "FINCO Protocol",
        "keys": list(entries),
    }


def _issue_cert():
    from app.services.run_certificate_service import issue_run_certificate
    return issue_run_certificate(_stub_ws())


# ── Key discovery ────────────────────────────────────────────────────────────

@pytest.fixture()
def well_known_client(tmp_path, monkeypatch):
    from app.persistence import db as db_mod
    db_mod.DB_PATH = str(tmp_path / "m2.db")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import main_web
    from app.api.v1_1.run_certificate_public_router import router as pub_router
    from app.api.v1_1.router import router as v11_router
    app = FastAPI()
    app.include_router(v11_router, prefix="/api/v1.1")
    app.include_router(pub_router, prefix="/api/v1.1")
    app.add_api_route("/.well-known/finco/keys.json",
                      lambda: __import__("app.protocol.signing_keys", fromlist=["public_keys_document"]).public_keys_document(),
                      methods=["GET"])
    return TestClient(app, raise_server_exceptions=False)


def test_well_known_discovery_document(well_known_client, test_key):
    resp = well_known_client.get("/.well-known/finco/keys.json")
    assert resp.status_code == 200
    doc = resp.json()
    assert doc["schema_version"] == "finco-signing-keys-v1"
    keys = doc["keys"]
    assert len(keys) >= 1
    entry = next(k for k in keys if k["kid"] == TEST_KID)
    assert entry["algorithm"] == "Ed25519"
    assert entry["status"] == "ACTIVE"
    # valid Ed25519 DER encoding present; raw JWK x is 32 bytes
    der = base64.b64decode(entry["public_key"])
    assert der[:12] == bytes.fromhex("302a300506032b6570032100")
    jwk_x = entry["jwk"]["x"]
    assert len(base64.urlsafe_b64decode(jwk_x + "=" * 4)) == 32
    # no private material anywhere in the document
    assert "seed" not in json.dumps(doc).lower()
    assert "private" not in json.dumps(doc).lower()


def test_well_known_discovery_deterministic(well_known_client, test_key):
    r1 = well_known_client.get("/.well-known/finco/keys.json").text
    r2 = well_known_client.get("/.well-known/finco/keys.json").text
    assert r1 == r2


def test_bundled_manifest_ships_no_default_trust_key():
    """P0: the version-controlled manifest ships ``keys: []`` — no default
    trusted signing key, and no public key whose private counterpart is a
    publicly known deterministic fixture (PUBLIC_ISSUER_KEY_NOT_CONFIGURED)."""
    import importlib
    manifest_path = Path(reg.__file__).parent / "signing_keys_registry.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["keys"] == []
    assert "seed" not in manifest_path.read_text(encoding="utf-8").lower()
    assert "bytes(range" not in manifest_path.read_text(encoding="utf-8")
    reloaded = importlib.reload(reg)
    try:
        # manifest seeds the process registry EMPTY — no bundled trust key
        assert reloaded.all_keys() == ()
        assert reloaded.get_signing_key(TEST_KID) is None
    finally:
        importlib.reload(reg)


def test_public_keys_document_contains_only_public_material(test_key):
    doc = reg.public_keys_document()
    text = json.dumps(doc)
    assert "private" not in text.lower()
    assert "seed" not in text.lower()
    assert TEST_SEED_B64 not in text
    for key in doc["keys"]:
        assert key["algorithm"] == "Ed25519"
        assert key["status"] in ("ACTIVE", "VERIFY_ONLY", "REVOKED")
        assert set(key) <= {
            "kid", "algorithm", "status", "public_key", "public_key_encoding",
            "jwk", "activated_at", "retired_at", "issuer", "schema_version",
            "certificate_schema_version"}


def test_discovery_and_api_mirror_share_one_source(well_known_client, test_key):
    """Well-known discovery and the /protocol/signing-keys API mirror are
    byte-identical — one registry authority, two surfaces."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1_1.run_certificate_public_router import router as pub_router
    app = FastAPI()
    app.include_router(pub_router, prefix="/api/v1.1")
    client = TestClient(app, raise_server_exceptions=False)
    wk = well_known_client.get("/.well-known/finco/keys.json").text
    mirror = client.get("/api/v1.1/protocol/signing-keys").text
    assert wk == mirror


# ── Issuance kid binding ─────────────────────────────────────────────────────

def test_issuance_binds_registered_kid(m2_env):
    cert = _issue_cert()
    assert cert["kid"] == TEST_KID
    assert cert["key_id"]  # fingerprint also present (V1 field kept)


def test_issuance_missing_kid_fails_closed(m2_env, monkeypatch):
    monkeypatch.delenv("FINCO_RUN_CERT_SIGNING_KID", raising=False)
    from app.services.run_certificate_service import issue_run_certificate
    ws = _stub_ws()
    with pytest.raises(Exception, match="kid binding is required"):
        issue_run_certificate(ws)


def test_issuance_unknown_kid_fails_closed(m2_env, monkeypatch):
    from app.services.run_certificate_service import issue_run_certificate
    ws = _stub_ws()
    monkeypatch.setenv("FINCO_RUN_CERT_SIGNING_KID", "unknown-kid")
    with pytest.raises(Exception, match="SIGNING_KEY_UNKNOWN_KID"):
        issue_run_certificate(ws)


def test_issuance_registry_mismatch_fails_closed(m2_env, monkeypatch):
    """Configured private key whose derived public key does NOT match the
    registry record for the configured kid → fail closed.  The foreign
    record is a VALID Ed25519 key — only the binding to the configured
    private key is wrong."""
    from Crypto.PublicKey import ECC
    foreign_der = ECC.construct(
        curve="Ed25519", seed=bytes(range(1, 33))
    ).public_key().export_key(format="DER")
    register_key_values(TEST_KID, foreign_der, status=reg.STATUS_ACTIVE,
                        activated_at=TEST_ACTIVATED_AT)
    from app.services.run_certificate_service import issue_run_certificate
    ws = _stub_ws()
    with pytest.raises(Exception, match="SIGNING_KEY_REGISTRY_MISMATCH"):
        issue_run_certificate(ws)
    # cleanup: restore the correct test key record
    register_key_values(TEST_KID, TEST_PUBLIC_DER, status=reg.STATUS_ACTIVE,
                        activated_at=TEST_ACTIVATED_AT)


# ── Rotation and revocation (P5) ─────────────────────────────────────────────

def test_verify_only_key_still_verifies_historical_certificate(m2_env, monkeypatch):
    from app.services import run_certificate_service as rcs
    from app.services.run_certificate_service import issue_run_certificate
    ws = _stub_ws()
    # issue under ACTIVE
    monkeypatch.setenv("FINCO_RUN_CERT_SIGNING_KID", TEST_KID)
    cert = issue_run_certificate(ws)
    # rotate to VERIFY_ONLY
    register_key_values(TEST_KID, TEST_PUBLIC_DER,
                        status=reg.STATUS_VERIFY_ONLY,
                        activated_at=TEST_ACTIVATED_AT)
    valid, reason = rcs.verify_run_certificate(cert, TEST_PUBLIC_DER)
    assert valid, reason
    # but a NEW issuance under VERIFY_ONLY fails closed
    from Crypto.PublicKey import ECC
    der = ECC.construct(curve="Ed25519", seed=TEST_SEED).public_key().export_key(format="DER")
    register_key_values(TEST_KID, der, status=reg.STATUS_VERIFY_ONLY,
                        activated_at=TEST_ACTIVATED_AT)
    with pytest.raises(Exception, match="cannot sign NEW certificates"):
        issue_run_certificate(ws)


def test_public_verifier_accepts_verify_only_key():
    """Registry-backed public verification accepts certificates from a
    retired (VERIFY_ONLY) key — retirement never breaks history."""
    from app.protocol.signing_keys import get_signing_key
    register_key_values(TEST_KID, TEST_PUBLIC_DER,
                        status=reg.STATUS_VERIFY_ONLY,
                        activated_at=TEST_ACTIVATED_AT)
    record = get_signing_key(TEST_KID)
    assert reg.is_verify_capable(record)


def test_revoked_key_rejected_by_public_verifier(verify_client, m2_env):
    """P5: REVOKED (compromised) keys verify NOTHING — no issuance, no
    verification.  Rotation != compromise."""
    from app.protocol.run_certificate_verifier import (
        STATE_KEY_NOT_VERIFY_CAPABLE,
    )
    cert = _issue_cert()
    register_key_values(TEST_KID, TEST_PUBLIC_DER, status=reg.STATUS_REVOKED,
                        activated_at=TEST_ACTIVATED_AT)
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": cert})
    body = resp.json()
    assert body["state"] == STATE_KEY_NOT_VERIFY_CAPABLE, (
        body["state"], body.get("detail"))
    assert "REVOKED" in body["detail"]
    assert body["signature_valid"] is False


def test_revoked_key_cannot_issue(m2_env):
    from app.protocol.signing_keys import is_issuance_capable
    register_key_values(TEST_KID, TEST_PUBLIC_DER, status=reg.STATUS_REVOKED,
                        activated_at=TEST_ACTIVATED_AT)
    record = reg.get_signing_key(TEST_KID)
    assert not is_issuance_capable(record)
    with pytest.raises(Exception, match="cannot sign NEW certificates"):
        _issue_cert()


# ── Public verifier endpoint (typed result) ─────────────────────────────────

@pytest.fixture()
def verify_client(tmp_path, monkeypatch, test_key):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1_1.run_certificate_public_router import router as pub_router
    app = FastAPI()
    app.include_router(pub_router, prefix="/api/v1.1")
    return TestClient(app, raise_server_exceptions=False)


def test_public_verify_valid_certificate(verify_client, m2_env):
    cert = _issue_cert()
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": cert})
    assert resp.status_code == 200
    result = resp.json()
    assert result["state"] == "VALID", (result["state"], result.get("detail"))
    assert result["signature_valid"] is True
    assert result["kid"] == TEST_KID
    assert result["algorithm"] == "Ed25519"
    assert "verification_timestamp" in result
    # never a FINCO Verify / economic claim
    assert result["state"] != "FINCO_VERIFIED"


def test_public_verify_tampered_payload_digest_mismatch(verify_client, m2_env):
    """Any field tampering is caught FIRST by the independent payload-digest
    recompute — a typed, precise failure before the signature check."""
    cert = _issue_cert()
    cert["project_id"] = "tampered"
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": cert})
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "PAYLOAD_DIGEST_MISMATCH", (
        body["state"], body.get("detail"))
    assert body["signature_valid"] is False


def test_public_verify_tampered_payload_consistent_digest_invalid_signature(
        verify_client, m2_env):
    """A tamperer who ALSO recomputes the payload digest still fails: the
    Ed25519 signature covers the canonical signed bytes."""
    import hashlib
    from app.services import run_certificate_service as rcs
    cert = _issue_cert()
    cert["project_id"] = "tampered"
    digest_input = {k: v for k, v in cert.items()
                    if k not in ("payload_digest", "signature")}
    cert["payload_digest"] = hashlib.sha256(
        rcs.canonical_certificate_signing_bytes(digest_input)).hexdigest()
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": cert})
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "INVALID_SIGNATURE", (
        body["state"], body.get("detail"))
    assert body["signature_valid"] is False


def test_public_verify_tampered_signature_invalid(verify_client, m2_env):
    cert = _issue_cert()
    sig = base64.b64decode(cert["signature"])
    cert["signature"] = base64.b64encode(bytes(sig[:-1]) + bytes([sig[-1] ^ 0xFF])).decode()
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": cert})
    assert resp.status_code == 200
    assert resp.json()["state"] == "INVALID_SIGNATURE"


def test_public_verify_unknown_kid(verify_client):
    cert = {"certificate_schema_version": "finco-run-certificate-v1",
            "kid": "unknown-kid", "key_id": "x",
            "signature_algorithm": "Ed25519", "signature": base64.b64encode(b"x").decode(),
            "payload_digest": "d", "issued_at": TEST_ACTIVATED_AT}
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": cert})
    assert resp.status_code == 200
    assert resp.json()["state"] == "UNKNOWN_KEY_ID"


def test_public_verify_unsupported_algorithm(verify_client):
    cert = {"certificate_schema_version": "finco-run-certificate-v1",
            "kid": TEST_KID, "key_id": "x",
            "signature_algorithm": "RS256", "signature": base64.b64encode(b"x").decode(),
            "payload_digest": "d", "issued_at": TEST_ACTIVATED_AT}
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": cert})
    assert resp.status_code == 200
    assert resp.json()["state"] == "UNSUPPORTED_ALGORITHM"


def test_public_verify_malformed_certificate(verify_client):
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": {"kid": TEST_KID}})
    assert resp.status_code == 200
    assert resp.json()["state"] == "MALFORMED_CERTIFICATE"


def test_public_verify_unsupported_version(verify_client):
    cert = {"certificate_schema_version": "finco-run-certificate-v0",
            "kid": TEST_KID, "key_id": "x",
            "signature_algorithm": "Ed25519", "signature": base64.b64encode(b"x").decode(),
            "payload_digest": "d", "issued_at": TEST_ACTIVATED_AT}
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": cert})
    assert resp.status_code == 200
    assert resp.json()["state"] == "UNSUPPORTED_CERTIFICATE_VERSION"


def test_public_verify_legacy_key_id_only_certificate_rejected(verify_client):
    """A certificate carrying ONLY the legacy key_id fingerprint (no explicit
    kid) is malformed — key_id is never a trust anchor."""
    cert = {"certificate_schema_version": "finco-run-certificate-v1",
            "key_id": "0123456789abcdef",
            "signature_algorithm": "Ed25519",
            "signature": base64.b64encode(b"x").decode(),
            "payload_digest": "d", "issued_at": TEST_ACTIVATED_AT}
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": cert})
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "MALFORMED_CERTIFICATE"
    assert "kid" in body["detail"]


def test_public_verify_missing_issued_at_rejected_no_run_at_fallback(
        verify_client, m2_env):
    """P4: key validity is decided against issued_at ONLY.  A certificate
    without issued_at is malformed even when run_at is present — run_at and
    issued_at are different authorities and run_at is never consulted."""
    cert = _issue_cert()
    del cert["issued_at"]
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": cert})
    body = resp.json()
    assert body["state"] == "MALFORMED_CERTIFICATE", (
        body["state"], body.get("detail"))
    assert "issued_at" in body["detail"]


def test_public_verify_naive_issued_at_rejected(verify_client, m2_env):
    """P4: naive timestamps are NEVER silently interpreted as UTC."""
    cert = _issue_cert()
    cert["issued_at"] = cert["issued_at"].replace("+00:00", "").replace("Z", "")
    assert "+" not in cert["issued_at"]
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": cert})
    body = resp.json()
    assert body["state"] == "MALFORMED_CERTIFICATE", (
        body["state"], body.get("detail"))
    assert "timezone-aware" in body["detail"]


def test_public_verify_key_activated_after_certificate_time(
        verify_client, m2_env):
    """A key activated AFTER the certificate issuance time must not verify
    historical certificates issued before its activation window."""
    from datetime import datetime, timezone
    cert = _issue_cert()
    assert datetime.fromisoformat(
        cert["issued_at"]) < datetime(2099, 1, 1, tzinfo=timezone.utc)
    # re-register the same key material with a FUTURE activation date
    register_key_values(TEST_KID, TEST_PUBLIC_DER, status=reg.STATUS_ACTIVE,
                        activated_at="2099-01-01T00:00:00+00:00")
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": cert})
    body = resp.json()
    assert body["state"] == "KEY_NOT_VALID_FOR_CERTIFICATE_TIME", (
        body["state"], body.get("detail"))
    assert body["signature_valid"] is False


def test_public_verify_key_retired_before_certificate_time(
        verify_client, m2_env):
    """A key retired BEFORE the certificate issuance time must not verify
    certificates issued after its retirement."""
    cert = _issue_cert()
    register_key_values(TEST_KID, TEST_PUBLIC_DER, status=reg.STATUS_VERIFY_ONLY,
                        activated_at="2019-01-01T00:00:00+00:00",
                        retired_at="2020-01-01T00:00:00+00:00")
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": cert})
    body = resp.json()
    assert body["state"] == "KEY_NOT_VALID_FOR_CERTIFICATE_TIME", (
        body["state"], body.get("detail"))


def test_public_verify_key_within_window_still_valid(verify_client, m2_env):
    """A key whose activated_at/retired_at window CONTAINS the certificate
    issuance time verifies normally."""
    cert = _issue_cert()
    register_key_values(TEST_KID, TEST_PUBLIC_DER, status=reg.STATUS_ACTIVE,
                        activated_at="2020-01-01T00:00:00+00:00",
                        retired_at="2099-01-01T00:00:00+00:00")
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": cert})
    body = resp.json()
    assert body["state"] == "VALID", (body["state"], body.get("detail"))


def test_public_verify_failures_are_sanitized(verify_client, m2_env):
    """Typed failure details never leak exception class names, tracebacks,
    or key material."""
    cert = _issue_cert()
    cert["signature"] = "not-valid-base64!!!"
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": cert})
    body = resp.json()
    assert body["state"] == "INVALID_SIGNATURE"
    forbidden = ("Error", "Exception", "Traceback", "binascii",
                 "invalid literal", TEST_SEED_B64)
    for token in forbidden:
        assert token not in body["detail"], token
    # key material never appears anywhere in the response
    assert TEST_PUBLIC_DER_B64 not in json.dumps(body)


def test_public_verify_huge_certificate_field_malformed(
        verify_client, m2_env):
    """P3 hardening: an oversized junk field is MALFORMED_CERTIFICATE — no
    unbounded field stress reaches hashing/serialization."""
    cert = _issue_cert()
    cert["junk"] = "x" * 1_100_000
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": cert})
    body = resp.json()
    assert body["state"] == "MALFORMED_CERTIFICATE", (
        body["state"], body.get("detail"))


def test_public_verifier_no_engine_no_writes(verify_client, m2_env, monkeypatch):
    """Verifier makes zero engine calls and zero Last Run/Verify/Radar writes."""
    cert = _issue_cert()
    import app.services.production_waterfall_seam as seam
    calls = []
    monkeypatch.setattr(seam, "execute_production_waterfall",
                        lambda *a, **k: calls.append(1) or (_ for _ in ()).throw(
                            AssertionError("engine call from verifier")))
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": cert})
    assert resp.status_code == 200
    assert calls == []


# ── P2: API and offline CLI share ONE verification core ─────────────────────

def test_api_and_offline_share_one_core_parity_valid(m2_env, test_key, tmp_path):
    """Same certificate + same registry → same state through the shared
    core, the API endpoint and the offline CLI."""
    cert = _issue_cert()
    # 1. shared core directly (registry records)
    from app.protocol.run_certificate_verifier import verify_certificate
    core_result = verify_certificate(cert, reg.all_keys())
    # 2. API endpoint
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1_1.run_certificate_public_router import (
        router as pub_router, verify_certificate_against_registry)
    app = FastAPI()
    app.include_router(pub_router, prefix="/api/v1.1")
    client = TestClient(app, raise_server_exceptions=False)
    api_result = client.post("/api/v1.1/run-certificates/verify",
                             json={"certificate": cert}).json()
    adapter_result = verify_certificate_against_registry(cert)
    # 3. offline CLI with the same trust list
    doc = reg.public_keys_document()
    keys_file = tmp_path / "keys.json"
    keys_file.write_text(json.dumps(doc), encoding="utf-8")
    cert_file = tmp_path / "cert.json"
    cert_file.write_text(json.dumps(cert), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "tools" /
                             "verify_finco_run_certificate.py"),
         str(cert_file), "--keys", str(keys_file)],
        capture_output=True, text=True)
    offline_result = json.loads(proc.stdout)
    assert core_result["state"] == "VALID"
    assert api_result["state"] == core_result["state"]
    assert adapter_result["state"] == core_result["state"]
    assert offline_result["state"] == core_result["state"]
    assert proc.returncode == 0


def test_api_and_offline_share_one_core_parity_tampered(m2_env, test_key, tmp_path):
    cert = _issue_cert()
    cert["project_id"] = "tampered"
    from app.protocol.run_certificate_verifier import verify_certificate
    core_result = verify_certificate(cert, reg.all_keys())
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1_1.run_certificate_public_router import router as pub_router
    app = FastAPI()
    app.include_router(pub_router, prefix="/api/v1.1")
    client = TestClient(app, raise_server_exceptions=False)
    api_result = client.post("/api/v1.1/run-certificates/verify",
                             json={"certificate": cert}).json()
    doc = reg.public_keys_document()
    keys_file = tmp_path / "keys.json"
    keys_file.write_text(json.dumps(doc), encoding="utf-8")
    cert_file = tmp_path / "cert.json"
    cert_file.write_text(json.dumps(cert), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "tools" /
                             "verify_finco_run_certificate.py"),
         str(cert_file), "--keys", str(keys_file)],
        capture_output=True, text=True)
    offline_result = json.loads(proc.stdout)
    assert core_result["state"] == "PAYLOAD_DIGEST_MISMATCH"
    assert api_result["state"] == core_result["state"]
    assert offline_result["state"] == core_result["state"]


# ── Offline verifier ─────────────────────────────────────────────────────────

def _offline_verify(certificate: dict, keys_document: dict | None, tmp_path=None):
    """Run the standalone offline verifier in a subprocess.

    Key material files are written to a pytest tmp dir — NEVER into the
    repository (tools/ stays free of runtime-generated key documents, so no
    test/production key confusion can be committed).
    """
    script = Path(__file__).resolve().parents[1] / "tools" / "verify_finco_run_certificate.py"
    work = tmp_path if tmp_path is not None else Path.cwd()
    cert_file = work / "_offline_cert.json"
    cert_file.write_text(json.dumps(certificate), encoding="utf-8")
    cmd = [sys.executable, str(script), str(cert_file)]
    keys_file = None
    if keys_document is not None:
        keys_file = work / "_offline_keys.json"
        keys_file.write_text(json.dumps(keys_document), encoding="utf-8")
        cmd += ["--keys", str(keys_file)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    for path in (cert_file, keys_file):
        if path is not None and path.exists():
            path.unlink()
    payload = {}
    try:
        payload = json.loads(result.stdout)
    except Exception:
        payload = {"raw_stdout": result.stdout[:200], "raw_stderr": result.stderr[:200]}
    return result.returncode, payload


def test_offline_verifier_valid(tmp_path, m2_env, test_key):
    cert = _issue_cert()
    keys_document = _keys_document(_key_entry())
    rc, payload = _offline_verify(cert, keys_document, tmp_path)
    assert rc == 0
    assert payload["state"] == "VALID"
    assert payload["signature_valid"] is True
    assert payload["kid"] == TEST_KID


def test_known_test_private_key_cannot_forge_default_trust_root(
        tmp_path, m2_env, test_key):
    """P0/P7 regression: KNOWN_TEST_PRIVATE_KEY_CAN_FORGE_DEFAULT_TRUST_ROOT
    = NO.  A certificate signed with the publicly documented deterministic
    test seed is UNTRUSTED against the default (bundled) registry — the
    offline verifier returns UNKNOWN_KEY_ID because the shipped manifest
    trusts no key by default."""
    cert = _issue_cert()  # signed by TEST_SEED
    assert cert["kid"] == TEST_KID
    rc, payload = _offline_verify(cert, None, tmp_path)  # default trust root
    assert rc != 0
    assert payload["state"] == "UNKNOWN_KEY_ID", (
        payload["state"], payload.get("detail"))
    assert payload["signature_valid"] is False


def test_offline_verifier_tampered_fails(tmp_path, m2_env, test_key):
    cert = _issue_cert()
    cert["project_id"] = "tampered"
    keys_document = _keys_document(_key_entry())
    rc, payload = _offline_verify(cert, keys_document, tmp_path)
    assert rc != 0
    assert payload["state"] == "PAYLOAD_DIGEST_MISMATCH"


def test_offline_verifier_unknown_key_fails(tmp_path, m2_env, test_key):
    cert = _issue_cert()
    cert["kid"] = "unknown"
    rc, payload = _offline_verify(cert, None, tmp_path)
    assert rc != 0
    assert payload["state"] == "UNKNOWN_KEY_ID"


def test_offline_verifier_rejects_expired_window(tmp_path, m2_env, test_key):
    """Offline verifier enforces the same time-validity contract as the API."""
    cert = _issue_cert()
    keys_document = _keys_document(
        _key_entry(activated_at="2099-01-01T00:00:00+00:00"))
    rc, payload = _offline_verify(cert, keys_document, tmp_path)
    assert rc != 0
    assert payload["state"] == "KEY_NOT_VALID_FOR_CERTIFICATE_TIME"


def test_offline_verifier_revoked_key_rejected(tmp_path, m2_env, test_key):
    cert = _issue_cert()
    keys_document = _keys_document(_key_entry(status="REVOKED"))
    rc, payload = _offline_verify(cert, keys_document, tmp_path)
    assert rc != 0
    assert payload["state"] == "KEY_NOT_VERIFY_CAPABLE"


# ── P3: malformed external keys documents fail closed, sanitized ────────────

@pytest.mark.parametrize("corrupt,expected_fragment", [
    ({"public_key": None}, "public_key"),                      # missing public_key
    ({"public_key": "!!!not-base64!!!"}, "base64"),            # invalid base64
])
def test_keys_document_missing_or_bad_public_key(corrupt, expected_fragment):
    from app.protocol.signing_keys import (
        SigningKeyRegistryError, validate_keys_document)
    entry = _key_entry()
    entry.update(corrupt)
    with pytest.raises(SigningKeyRegistryError, match=expected_fragment):
        validate_keys_document(_keys_document(entry))


def test_keys_document_non_ed25519_der_rejected():
    from Crypto.PublicKey import ECC
    from app.protocol.signing_keys import (
        SigningKeyRegistryError, validate_keys_document)
    p256 = ECC.generate(curve="P-256").public_key().export_key(format="DER")
    with pytest.raises(SigningKeyRegistryError, match="Ed25519"):
        validate_keys_document(_keys_document(_key_entry(der=p256)))


@pytest.mark.parametrize("jwk_override,fragment", [
    ({"jwk": {"kty": "EC", "crv": "Ed25519", "x": "AAAA"}}, "kty"),
    ({"jwk": {"kty": "OKP", "crv": "P-256", "x": "AAAA"}}, "crv"),
    ({"jwk": {"kty": "OKP", "crv": "Ed25519", "x": "AAAA"}}, "jwk.x"),
    ({"jwk": {"kty": "OKP", "crv": "Ed25519"}}, "jwk.x"),
])
def test_keys_document_malformed_jwk_rejected(jwk_override, fragment):
    from app.protocol.signing_keys import (
        SigningKeyRegistryError, validate_keys_document)
    entry = _key_entry()
    entry.update(jwk_override)
    with pytest.raises(SigningKeyRegistryError, match=fragment):
        validate_keys_document(_keys_document(entry))


def test_keys_document_duplicate_kid_rejected():
    from app.protocol.signing_keys import (
        SigningKeyRegistryError, validate_keys_document)
    with pytest.raises(SigningKeyRegistryError, match="duplicate kid"):
        validate_keys_document(_keys_document(_key_entry(), _key_entry()))


def test_keys_document_naive_activated_at_rejected():
    from app.protocol.signing_keys import (
        SigningKeyRegistryError, validate_keys_document)
    entry = _key_entry(activated_at="2026-01-01T00:00:00")  # naive
    with pytest.raises(SigningKeyRegistryError, match="timezone-aware"):
        validate_keys_document(_keys_document(entry))


def test_keys_document_missing_activated_at_rejected():
    from app.protocol.signing_keys import (
        SigningKeyRegistryError, validate_keys_document)
    entry = _key_entry()
    del entry["activated_at"]
    with pytest.raises(SigningKeyRegistryError, match="activated_at"):
        validate_keys_document(_keys_document(entry))


def test_keys_document_naive_retired_at_rejected():
    from app.protocol.signing_keys import (
        SigningKeyRegistryError, validate_keys_document)
    entry = _key_entry(retired_at="2030-01-01T00:00:00")  # naive
    with pytest.raises(SigningKeyRegistryError, match="timezone-aware"):
        validate_keys_document(_keys_document(entry))


def test_keys_document_retired_before_activated_rejected():
    from app.protocol.signing_keys import (
        SigningKeyRegistryError, validate_keys_document)
    entry = _key_entry(activated_at="2030-01-01T00:00:00+00:00",
                       retired_at="2026-01-01T00:00:00+00:00")
    with pytest.raises(SigningKeyRegistryError, match="earlier than"):
        validate_keys_document(_keys_document(entry))


def test_keys_document_wrong_schema_version_rejected():
    from app.protocol.signing_keys import (
        SigningKeyRegistryError, validate_keys_document)
    doc = _keys_document(_key_entry())
    doc["schema_version"] = "finco-signing-keys-v0"
    with pytest.raises(SigningKeyRegistryError, match="schema_version"):
        validate_keys_document(doc)


def test_keys_document_wrong_issuer_rejected():
    from app.protocol.signing_keys import (
        SigningKeyRegistryError, validate_keys_document)
    doc = _keys_document(_key_entry())
    doc["issuer"] = "Not FINCO"
    with pytest.raises(SigningKeyRegistryError, match="issuer"):
        validate_keys_document(doc)


def test_keys_document_unknown_field_rejected():
    from app.protocol.signing_keys import (
        SigningKeyRegistryError, validate_keys_document)
    entry = _key_entry(private_material="never")  # strict schema: unknown field
    with pytest.raises(SigningKeyRegistryError, match="unknown field"):
        validate_keys_document(_keys_document(entry))


def test_keys_document_atomic_no_partial_acceptance():
    """P1: ONE invalid entry rejects the WHOLE document — a valid entry in
    the same list never leaks through (atomic fail-closed)."""
    from Crypto.PublicKey import ECC
    from app.protocol.signing_keys import validate_keys_document
    other_der = ECC.construct(curve="Ed25519", seed=bytes(range(1, 33))
                              ).public_key().export_key(format="DER")
    good = _key_entry(der=other_der, kid="other-kid")
    bad = _key_entry(kid="bad-kid", public_key="!!!")
    with pytest.raises(Exception):
        validate_keys_document(_keys_document(good, bad))


def test_offline_cli_malformed_keys_document_typed_failure(
        tmp_path, m2_env, test_key):
    """P3: a malformed external keys document produces a typed sanitized
    machine-readable failure — never a traceback."""
    cert = _issue_cert()
    keys_document = _keys_document(_key_entry(public_key="!!!not-base64!!!"))
    rc, payload = _offline_verify(cert, keys_document, tmp_path)
    assert rc != 0
    assert payload["state"] == "KEYS_DOCUMENT_INVALID"
    assert "base64" in payload["detail"]
    assert "Traceback" not in json.dumps(payload)
    assert TEST_PUBLIC_DER_B64 not in json.dumps(payload)


def test_offline_cli_not_json_keys_document_typed_failure(tmp_path, m2_env, test_key):
    cert = _issue_cert()
    keys_file = tmp_path / "keys.json"
    keys_file.write_text("{not json", encoding="utf-8")
    cert_file = tmp_path / "cert.json"
    cert_file.write_text(json.dumps(cert), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "tools" / "verify_finco_run_certificate.py"
    proc = subprocess.run(
        [sys.executable, str(script), str(cert_file), "--keys", str(keys_file)],
        capture_output=True, text=True)
    payload = json.loads(proc.stdout)
    assert proc.returncode != 0
    assert payload["state"] == "KEYS_DOCUMENT_INVALID"
    assert proc.stderr.strip() == "" or "Traceback" not in proc.stderr


# ── Registry hardening ───────────────────────────────────────────────────────

def test_registry_rejects_non_ed25519_key():
    """register_key does REAL cryptographic validation — a P-256 key is
    rejected with a typed error, not accepted as opaque bytes."""
    from Crypto.PublicKey import ECC
    foreign = ECC.generate(curve="P-256").public_key().export_key(format="DER")
    with pytest.raises(Exception, match="Ed25519"):
        register_key_values("bad-curve-key", foreign,
                            activated_at=TEST_ACTIVATED_AT)


def test_registry_rejects_garbage_der():
    with pytest.raises(Exception, match="Ed25519|invalid|base64"):
        register_key_values("garbage-key", b"\x00\x01\x02\x03",
                            activated_at=TEST_ACTIVATED_AT)


def test_load_registry_manifest_invalid_file_fails_closed(tmp_path):
    """File-level atomic loading: unreadable and non-JSON manifests raise a
    typed registry error."""
    from app.protocol.signing_keys import (
        SigningKeyRegistryError, load_registry_manifest)
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{nope", encoding="utf-8")
    with pytest.raises(SigningKeyRegistryError):
        load_registry_manifest(bad_json)
    missing = tmp_path / "missing.json"
    with pytest.raises(SigningKeyRegistryError):
        load_registry_manifest(missing)


def test_load_registry_manifest_valid_empty(tmp_path):
    from app.protocol.signing_keys import load_registry_manifest
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps(_keys_document()), encoding="utf-8")
    assert load_registry_manifest(ok) == ()
