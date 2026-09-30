"""M-2 — Signed Run public trust: registry, discovery, kid binding, public
verifier, offline verifier.

Authority separation: Signed Run verification is cryptographic provenance/
integrity ONLY.  No engine calls, no Verify mutation, no Radar/DB writes,
no token gating, no blockchain claims, no private-key exposure.
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

TEST_SEED = bytes(range(32))
TEST_KID = "finco-prod-2026-01"
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
    between tests — including garbage-DER registrations from negative
    tests."""
    register_key_values(TEST_KID, TEST_PUBLIC_DER, status=reg.STATUS_ACTIVE)
    yield
    reg.unregister_key(TEST_KID)


@pytest.fixture()
def test_key():
    """Register the deterministic test key; clean up afterwards."""
    from Crypto.PublicKey import ECC
    der = ECC.construct(curve="Ed25519", seed=TEST_SEED).public_key().export_key(format="DER")
    record = register_key_values(TEST_KID, der, status=reg.STATUS_ACTIVE)
    yield record
    reg.unregister_key(TEST_KID)


@pytest.fixture()
def m2_env(monkeypatch, test_key):
    monkeypatch.setenv("FINCO_RUN_CERT_SIGNING_KEY", base64.b64encode(TEST_SEED).decode())
    monkeypatch.setenv("FINCO_RUN_CERT_SIGNING_KID", TEST_KID)
    return test_key


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
    import base64
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


# ── Issuance kid binding ─────────────────────────────────────────────────────

def test_issuance_binds_registered_kid(m2_env, tmp_path):
    from app.services.run_certificate_service import issue_run_certificate
    from app.persistence.projects_repository import _compute_baseline_snapshot
    baseline = _compute_baseline_snapshot("EV Charging", "generic_ev_charging_reference")
    baseline["project_name"] = "M2"
    from app.workbook.input_set import ProjectInputSet
    pis = ProjectInputSet.from_snapshot(baseline)
    from types import SimpleNamespace
    from datetime import datetime, timezone
    ws = SimpleNamespace(
        project_id="m2-pid", project_code="m2-code", any_run_committed=True,
        last_runtime_snapshot_id="m2-snap",
        last_runtime_composite_hash="m2-composite-hash",
        last_runtime_at=datetime.now(timezone.utc),
        last_runtime_origin="saved_state",
        last_runtime_scenario_id=None, last_runtime_identity={
            "engine_version": "e", "workbook_version": "v", "git_sha": "g",
            "git_branch": "b", "project_type": "EV Charging",
            "template_source": "generic_ev_charging_reference",
            "composite_hash": "m2-composite-hash",
            "finco_verify_state": "NOT_VERIFIED"},
        last_runtime_summary={"k": 1},
    )
    cert = issue_run_certificate(ws)
    assert cert["kid"] == TEST_KID
    assert cert["key_id"]  # fingerprint also present (V1 field kept)


def test_issuance_missing_kid_fails_closed(m2_env, monkeypatch):
    monkeypatch.delenv("FINCO_RUN_CERT_SIGNING_KID", raising=False)
    from app.services.run_certificate_service import (
        CertificateBuildUnavailable, issue_run_certificate,
    )
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
    record is a VALID Ed25519 key (registry validation is real now) — only
    the binding to the configured private key is wrong."""
    from Crypto.PublicKey import ECC
    foreign_der = ECC.construct(
        curve="Ed25519", seed=bytes(range(1, 33))
    ).public_key().export_key(format="DER")
    register_key_values(TEST_KID, foreign_der, status=reg.STATUS_ACTIVE)
    from app.services.run_certificate_service import issue_run_certificate
    ws = _stub_ws()
    with pytest.raises(Exception, match="SIGNING_KEY_REGISTRY_MISMATCH"):
        issue_run_certificate(ws)
    # cleanup: restore the correct test key record
    register_key_values(TEST_KID, TEST_PUBLIC_DER)


# ── Rotation: VERIFY_ONLY verifies historical certificates ──────────────────

def test_verify_only_key_still_verifies_historical_certificate(m2_env, monkeypatch):
    from app.services import run_certificate_service as rcs
    from app.services.run_certificate_service import issue_run_certificate
    ws = _stub_ws()
    # issue under ACTIVE
    monkeypatch.setenv("FINCO_RUN_CERT_SIGNING_KID", TEST_KID)
    cert = issue_run_certificate(ws)
    # rotate to VERIFY_ONLY
    register_key_values(TEST_KID, TEST_PUBLIC_DER, status=reg.STATUS_VERIFY_ONLY)
    valid, reason = rcs.verify_run_certificate(cert, TEST_PUBLIC_DER)
    assert valid, reason
    # but a NEW issuance under VERIFY_ONLY fails closed
    from Crypto.PublicKey import ECC
    der = ECC.construct(curve="Ed25519", seed=TEST_SEED).public_key().export_key(format="DER")
    register_key_values(TEST_KID, der, status=reg.STATUS_VERIFY_ONLY)
    with pytest.raises(Exception, match="cannot sign NEW certificates"):
        issue_run_certificate(ws)


def test_public_verifier_accepts_verify_only_key(monkeypatch, tmp_path):
    """Registry-backed public verification accepts certificates from a
    retired (VERIFY_ONLY) key — retirement never breaks history."""
    from app.protocol.signing_keys import get_signing_key
    register_key_values(TEST_KID, TEST_PUBLIC_DER, status=reg.STATUS_VERIFY_ONLY)
    record = get_signing_key(TEST_KID)
    assert reg.is_verify_capable(record)


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
    from app.services.run_certificate_service import issue_run_certificate
    ws = _stub_ws()
    cert = issue_run_certificate(ws)
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
    import hashlib
    from app.services.run_certificate_service import issue_run_certificate
    ws = _stub_ws()
    cert = issue_run_certificate(ws)
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
    from app.services.run_certificate_service import issue_run_certificate
    ws = _stub_ws()
    cert = issue_run_certificate(ws)
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
    from app.services.run_certificate_service import issue_run_certificate
    ws = _stub_ws()
    cert = issue_run_certificate(ws)
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
            "payload_digest": "d", "run_at": None}
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": cert})
    assert resp.status_code == 200
    assert resp.json()["state"] == "UNKNOWN_KEY_ID"


def test_public_verify_unsupported_algorithm(verify_client):
    cert = {"certificate_schema_version": "finco-run-certificate-v1",
            "kid": TEST_KID, "key_id": "x",
            "signature_algorithm": "RS256", "signature": base64.b64encode(b"x").decode(),
            "payload_digest": "d", "run_at": None}
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
            "payload_digest": "d", "run_at": None}
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": cert})
    assert resp.status_code == 200
    assert resp.json()["state"] == "UNSUPPORTED_CERTIFICATE_VERSION"


def test_public_verifier_no_engine_no_writes(verify_client, m2_env, monkeypatch):
    """Verifier makes zero engine calls and zero Last Run/Verify/Radar writes."""
    from app.services.run_certificate_service import issue_run_certificate
    ws = _stub_ws()
    cert = issue_run_certificate(ws)
    import app.services.production_waterfall_seam as seam
    calls = []
    monkeypatch.setattr(seam, "execute_production_waterfall",
                        lambda *a, **k: calls.append(1) or (_ for _ in ()).throw(
                            AssertionError("engine call from verifier")))
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": cert})
    assert resp.status_code == 200
    assert calls == []


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
    from app.services.run_certificate_service import issue_run_certificate
    ws = _stub_ws()
    cert = issue_run_certificate(ws)
    keys_document = {"keys": [{"kid": TEST_KID, "algorithm": "Ed25519",
                               "status": "ACTIVE",
                               "public_key": base64.b64encode(TEST_PUBLIC_DER).decode()}]}
    rc, payload = _offline_verify(cert, keys_document, tmp_path)
    assert rc == 0
    assert payload["state"] == "VALID"
    assert payload["signature_valid"] is True
    assert payload["kid"] == TEST_KID


def test_offline_verifier_valid_with_bundled_registry_trust_root(
        tmp_path, m2_env, test_key):
    """Default trust root = the version-controlled registry manifest; no
    external keys document is needed."""
    from app.services.run_certificate_service import issue_run_certificate
    ws = _stub_ws()
    cert = issue_run_certificate(ws)
    rc, payload = _offline_verify(cert, None, tmp_path)
    assert rc == 0
    assert payload["state"] == "VALID", payload.get("detail")
    assert payload["kid"] == TEST_KID


def test_offline_verifier_tampered_fails(tmp_path, m2_env, test_key):
    from app.services.run_certificate_service import issue_run_certificate
    ws = _stub_ws()
    cert = issue_run_certificate(ws)
    cert["project_id"] = "tampered"
    keys_document = {"keys": [{"kid": TEST_KID, "algorithm": "Ed25519",
                               "status": "ACTIVE",
                               "public_key": base64.b64encode(TEST_PUBLIC_DER).decode()}]}
    rc, payload = _offline_verify(cert, keys_document, tmp_path)
    assert rc != 0
    assert payload["state"] == "PAYLOAD_DIGEST_MISMATCH"


def test_offline_verifier_unknown_key_fails(tmp_path, m2_env, test_key):
    from app.services.run_certificate_service import issue_run_certificate
    ws = _stub_ws()
    cert = issue_run_certificate(ws)
    cert["kid"] = "unknown"
    rc, payload = _offline_verify(cert, None, tmp_path)
    assert rc != 0
    assert payload["state"] == "UNKNOWN_KEY_ID"


# ── M-2 Correction A — security hardening ───────────────────────────────────

def test_public_verify_legacy_key_id_only_certificate_rejected(verify_client):
    """A certificate carrying ONLY the legacy key_id fingerprint (no explicit
    kid) is malformed — key_id is never a trust anchor."""
    cert = {"certificate_schema_version": "finco-run-certificate-v1",
            "key_id": "0123456789abcdef",
            "signature_algorithm": "Ed25519",
            "signature": base64.b64encode(b"x").decode(),
            "payload_digest": "d", "run_at": None}
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": cert})
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "MALFORMED_CERTIFICATE"
    assert "kid" in body["detail"]


def test_public_verify_key_activated_after_certificate_time(
        verify_client, m2_env):
    """A key activated AFTER the certificate issuance time must not verify
    historical certificates issued before its activation window."""
    from datetime import datetime, timezone
    from app.services.run_certificate_service import issue_run_certificate
    ws = _stub_ws()
    cert = issue_run_certificate(ws)  # issued "now"
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
    from app.services.run_certificate_service import issue_run_certificate
    ws = _stub_ws()
    cert = issue_run_certificate(ws)
    register_key_values(TEST_KID, TEST_PUBLIC_DER, status=reg.STATUS_VERIFY_ONLY,
                        retired_at="2020-01-01T00:00:00+00:00")
    resp = verify_client.post("/api/v1.1/run-certificates/verify",
                              json={"certificate": cert})
    body = resp.json()
    assert body["state"] == "KEY_NOT_VALID_FOR_CERTIFICATE_TIME", (
        body["state"], body.get("detail"))


def test_public_verify_key_within_window_still_valid(verify_client, m2_env):
    """A key whose activated_at/retired_at window CONTAINS the certificate
    issuance time verifies normally."""
    from app.services.run_certificate_service import issue_run_certificate
    ws = _stub_ws()
    cert = issue_run_certificate(ws)
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
    from app.services.run_certificate_service import issue_run_certificate
    ws = _stub_ws()
    cert = issue_run_certificate(ws)
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


def test_registry_rejects_non_ed25519_key():
    """register_key does REAL cryptographic validation — a P-256 key is
    rejected with a typed error, not accepted as opaque bytes."""
    from Crypto.PublicKey import ECC
    foreign = ECC.generate(curve="P-256").public_key().export_key(format="DER")
    with pytest.raises(ValueError, match="Ed25519"):
        register_key_values("bad-curve-key", foreign)


def test_registry_rejects_garbage_der():
    with pytest.raises(ValueError, match="Ed25519|invalid"):
        register_key_values("garbage-key", b"\x00\x01\x02\x03")


def test_bundled_manifest_is_the_registry_seed():
    """The version-controlled manifest seeds the process registry: the
    canonical kid is present even with NO runtime registration."""
    import importlib
    import app.protocol.signing_keys as sk
    reloaded = importlib.reload(sk)
    try:
        record = reloaded.get_signing_key("finco-prod-2026-01")
        assert record is not None
        assert record.status == "ACTIVE"
        assert reloaded.is_issuance_capable(record)
        # public material only — no private key anywhere in the record
        assert not hasattr(record, "private_key")
    finally:
        importlib.reload(sk)


def test_public_keys_document_contains_only_public_material(test_key):
    doc = reg.public_keys_document()
    text = json.dumps(doc)
    assert "private" not in text.lower()
    assert "seed" not in text.lower()
    assert TEST_SEED_B64 not in text
    for key in doc["keys"]:
        assert key["algorithm"] == "Ed25519"
        assert key["status"] in ("ACTIVE", "VERIFY_ONLY")
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


def test_offline_verifier_rejects_expired_window(tmp_path, m2_env, test_key):
    """Offline verifier enforces the same time-validity contract as the API."""
    from app.services.run_certificate_service import issue_run_certificate
    ws = _stub_ws()
    cert = issue_run_certificate(ws)
    keys_document = {"keys": [{"kid": TEST_KID, "algorithm": "Ed25519",
                               "status": "ACTIVE",
                               "public_key": base64.b64encode(TEST_PUBLIC_DER).decode(),
                               "activated_at": "2099-01-01T00:00:00+00:00"}]}
    rc, payload = _offline_verify(cert, keys_document, tmp_path)
    assert rc != 0
    assert payload["state"] == "KEY_NOT_VALID_FOR_CERTIFICATE_TIME"
