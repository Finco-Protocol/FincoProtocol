"""FINCO Signed Run Certificate V1 — acceptance tests.

Authority separation (non-negotiable): a Run Certificate attests to
provenance/integrity only.  It never converts FINCO Verify state into
VERIFIED and never claims economic truth.

Test keys are deterministic fixtures (base64 of bytes(range(32)) / a
documented test seed) — never real production keys.
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid

import pytest

from app import ev_charging_economics  # noqa: F401 (canonical EV authority context)
from app.services import run_certificate_service as rcs

# Deterministic test signing key (base64 of 32 bytes) — fixture only.
TEST_SEED_B64 = base64.b64encode(bytes(range(32))).decode()
TEST_SEED = bytes(range(32))
TEST_PUBLIC_DER = rcs.public_key_der_from_seed(TEST_SEED)
TEST_KEY_ID = rcs.key_id_for_public_key(TEST_PUBLIC_DER)
WRONG_PUBLIC_DER = rcs.public_key_der_from_seed(bytes(range(32, 64)))


@pytest.fixture(autouse=True)
def _test_signing_key(monkeypatch):
    monkeypatch.setenv(rcs.SIGNING_KEY_ENV_VAR, TEST_SEED_B64)


@pytest.fixture()
def ev_project(tmp_path, monkeypatch):
    from app.persistence import db as db_mod
    db_mod.DB_PATH = str(tmp_path / "cert.db")
    from app.services.project_library_service import ensure_reference_models
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.persistence.workspace_repository import save_workspace_state, get_workspace_state
    ensure_reference_models()
    record = create_reference_seeded_project(
        user_id="cert-user", template_source="generic_ev_charging_reference",
        requested_name="Cert EV", capacity_mw=5.0,
    )
    # Commit a canonical Last Run: save a runtime snapshot + identity.
    ws = get_workspace_state("cert-user", record.project_id)
    identity = {
        "workbook_version": "v2.0.0",
        "engine_version": "finco-engine-test",
        "git_sha": "0" * 40,
        "git_branch": "trust/signed-run-certificate-v1",
        "project_type": "EV Charging",
        "template_source": "generic_ev_charging_reference",
        "finco_verify_state": "NOT_VERIFIED",
    }
    save_workspace_state(
        user_id="cert-user", project_id=record.project_id,
        project_code=record.project_code,
        draft_snapshot=ws.draft_snapshot, saved_snapshot=ws.draft_snapshot,
        last_runtime_snapshot=ws.draft_snapshot,
        last_runtime_summary={"project_irr": 0.147, "total_revenue_keur": 94773.4792},
        last_runtime_snapshot_id="cert-snap-0001",
        last_runtime_origin="saved_state",
        last_runtime_scenario_id=None,
        dirty=False,
        governance_state=ws.governance_state,
        replay_metadata=ws.replay_metadata,
    )
    # Persist run-commit state + identity exactly as v2_atomic_run_commit
    # does (these columns live on workspace_states; save_workspace_state
    # does not carry them).
    from app.persistence.db import get_connection
    conn = get_connection()
    conn.execute(
        "UPDATE workspace_states SET any_run_committed=1, "
        "last_runtime_identity_json=? "
        "WHERE workspace_id=? AND user_id=?",
        (json.dumps(identity), ws.workspace_id, "cert-user"),
    )
    conn.commit()
    conn.close()
    from app.persistence.workspace_repository import get_workspace_state as _gws
    return {"record": record, "user_id": "cert-user", "ws": _gws("cert-user", record.project_id)}


def _client():
    from fastapi.testclient import TestClient
    from app.api.v1_1.router import router as v1_1_router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(v1_1_router, prefix="/api/v1.1")
    return TestClient(app, raise_server_exceptions=False)


def _auth_cookies(user_id="cert-user"):
    from app.auth import COOKIE_NAME, create_session_token
    return {COOKIE_NAME: create_session_token(user_id=user_id, username="admin")}


def _get_certificate(client, project_id):
    return client.get(f"/api/v1.1/projects/{project_id}/run-certificate",
                      cookies=_auth_cookies())


# ── SIGNED_RUN_BINDS_CANONICAL_LAST_RUN ─────────────────────────────────────

def test_signed_run_binds_canonical_last_run(ev_project):
    ws = ev_project["ws"]
    cert = rcs.issue_run_certificate(ws)
    assert cert["certificate_schema_version"] == "finco-run-certificate-v1"
    assert cert["project_id"] == ev_project["record"].project_id
    assert cert["snapshot_id"] == "cert-snap-0001"
    assert cert["composite_hash"] == ws.last_runtime_composite_hash
    assert cert["run_origin"] == "saved_state"
    assert cert["signature_algorithm"] == "Ed25519"
    assert cert["key_id"] == TEST_KEY_ID
    assert cert["payload_digest"]
    assert cert["signature"]
    # no Working Copy draft values in the payload
    canonical = json.dumps(cert, sort_keys=True)
    assert "draft_snapshot" not in canonical


# ── SIGNED_RUN_DIRTY_WC_DOES_NOT_CHANGE_RUN ─────────────────────────────────

def test_signed_run_dirty_wc_does_not_change_run(ev_project):
    cert1 = rcs.issue_run_certificate(ev_project["ws"])
    # dirty the Working Copy (draft ≠ last run) — certificate unchanged
    from app.persistence.workspace_repository import get_workspace_state, save_workspace_state
    dirty = dict(ev_project["ws"].draft_snapshot)
    dirty["capacity_mw"] = "99"
    save_workspace_state(
        user_id="cert-user", project_id=ev_project["record"].project_id,
        project_code=ev_project["record"].project_code,
        draft_snapshot=dirty, saved_snapshot=ev_project["ws"].saved_snapshot,
        dirty=True, governance_state=ev_project["ws"].governance_state,
        replay_metadata=ev_project["ws"].replay_metadata,
    )
    ws2 = get_workspace_state("cert-user", ev_project["record"].project_id)
    assert ws2.dirty is True
    cert2 = rcs.issue_run_certificate(ws2)
    cert1_core = {k: v for k, v in cert1.items() if k != "issued_at"}
    cert2_core = {k: v for k, v in cert2.items() if k != "issued_at"}
    assert cert1_core == cert2_core, "dirty WC must not alter the certificate"


# ── SIGNED_RUN_NO_ENGINE_RERUN ──────────────────────────────────────────────

def test_signed_run_no_engine_rerun(ev_project, monkeypatch):
    calls = []
    import app.services.production_waterfall_seam as seam
    original = seam.execute_production_waterfall
    monkeypatch.setattr(seam, "execute_production_waterfall",
                        lambda *a, **k: calls.append(1) or original(*a, **k))
    rcs.issue_run_certificate(ev_project["ws"])
    assert calls == [], "certificate must never rerun the engine"


# ── SIGNED_RUN_CANONICAL_SERIALIZATION ──────────────────────────────────────

def test_signed_run_canonical_serialization():
    """Same payload → same canonical bytes regardless of key insertion order."""
    p1 = {"b": 1, "a": "x", "c": {"z": True, "y": 2.5}}
    p2 = {"a": "x", "c": {"y": 2.5, "z": True}, "b": 1}
    b1 = rcs._canonical_json_bytes(p1)
    b2 = rcs._canonical_json_bytes(p2)
    assert b1 == b2
    assert b1 == json.dumps(p2, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False).encode("utf-8")


# ── SIGNED_RUN_SIGNATURE_VERIFIES ───────────────────────────────────────────

def test_signed_run_signature_verifies(ev_project):
    cert = rcs.issue_run_certificate(ev_project["ws"])
    valid, reason = rcs.verify_run_certificate(cert, TEST_PUBLIC_DER)
    assert valid, reason


# ── SIGNED_RUN_PAYLOAD_TAMPER_FAILS ─────────────────────────────────────────

def test_signed_run_payload_tamper_fails(ev_project):
    cert = rcs.issue_run_certificate(ev_project["ws"])
    tampered = dict(cert)
    tampered["project_id"] = "other-project"
    valid, reason = rcs.verify_run_certificate(tampered, TEST_PUBLIC_DER)
    assert not valid and reason == "PAYLOAD_TAMPERED"


# ── SIGNED_RUN_SIGNATURE_TAMPER_FAILS ───────────────────────────────────────

def test_signed_run_signature_tamper_fails(ev_project):
    cert = rcs.issue_run_certificate(ev_project["ws"])
    sig = base64.b64decode(cert["signature"])
    tampered_sig = base64.b64encode(bytes(sig[:-1]) + bytes([sig[-1] ^ 0xFF])).decode()
    tampered = dict(cert, signature=tampered_sig)
    valid, reason = rcs.verify_run_certificate(tampered, TEST_PUBLIC_DER)
    assert not valid and reason == "SIGNATURE_INVALID"


# ── SIGNED_RUN_WRONG_PUBLIC_KEY_FAILS ───────────────────────────────────────

def test_signed_run_wrong_public_key_fails(ev_project):
    cert = rcs.issue_run_certificate(ev_project["ws"])
    valid, reason = rcs.verify_run_certificate(cert, WRONG_PUBLIC_DER)
    assert not valid and reason in ("WRONG_KEY_ID", "SIGNATURE_INVALID")


# ── SIGNED_RUN_MISSING_KEY_FAILS_CLOSED ─────────────────────────────────────

def test_signed_run_missing_key_fails_closed(ev_project, monkeypatch):
    monkeypatch.delenv(rcs.SIGNING_KEY_ENV_VAR, raising=False)
    with pytest.raises(rcs.SigningKeyUnavailable) as exc:
        rcs.issue_run_certificate(ev_project["ws"])
    assert exc.value.REASON == "SIGNING_KEY_UNAVAILABLE"


def test_signed_run_malformed_key_fails_closed(ev_project, monkeypatch):
    monkeypatch.setenv(rcs.SIGNING_KEY_ENV_VAR, "not-base64!!")
    with pytest.raises(rcs.SigningKeyUnavailable):
        rcs.issue_run_certificate(ev_project["ws"])
    monkeypatch.setenv(rcs.SIGNING_KEY_ENV_VAR, base64.b64encode(b"short").decode())
    with pytest.raises(rcs.SigningKeyUnavailable):
        rcs.issue_run_certificate(ev_project["ws"])


# ── SIGNED_RUN_PRIVATE_KEY_NEVER_EXPOSED ────────────────────────────────────

def test_signed_run_private_key_never_exposed(ev_project):
    cert = rcs.issue_run_certificate(ev_project["ws"])
    canonical = json.dumps(cert, sort_keys=True)
    from Crypto.PublicKey import ECC
    private_der = ECC.construct(curve="Ed25519", seed=TEST_SEED).export_key(format="DER")
    assert base64.b64encode(private_der).decode() not in canonical
    assert base64.b64encode(TEST_SEED).decode() not in canonical
    assert TEST_SEED.hex() not in canonical
    for v in cert.values():
        assert not isinstance(v, bytes), "no raw bytes in the certificate dict"


# ── SIGNED_RUN_NOT_FINCO_VERIFY ─────────────────────────────────────────────

def test_signed_run_not_finco_verify(ev_project):
    cert = rcs.issue_run_certificate(ev_project["ws"])
    observed = cert.get("observed_authorities", {})
    assert observed.get("finco_verify_state") == "NOT_VERIFIED"
    assert "never" in observed.get("note", "").lower()
    # the certificate carries no VERIFIED claim
    assert "VERIFIED" != cert.get("observed_authorities", {}).get("finco_verify_state")
    # app.verify semantics untouched: PRODUCTION_VERIFIED_ASSET_COUNT absent
    from pathlib import Path
    cap_src = (Path(__file__).resolve().parents[1]
               / "app/product_capability.py").read_text()
    assert "PRODUCTION_VERIFIED_ASSET_COUNT" not in cap_src


# ── API endpoint tests ──────────────────────────────────────────────────────

def test_signed_run_auth_required(ev_project):
    client = _client()
    resp = client.get(f"/api/v1.1/projects/{ev_project['record'].project_id}/run-certificate")
    assert resp.status_code == 401


def test_signed_run_endpoint_returns_signed_certificate(ev_project):
    client = _client()
    resp = _get_certificate(client, ev_project["record"].project_id)
    assert resp.status_code == 200, resp.text[:300]
    data = resp.json()["data"]
    assert data["certificate_schema_version"] == "finco-run-certificate-v1"
    assert data["signature"]
    valid, reason = rcs.verify_run_certificate(data, TEST_PUBLIC_DER)
    assert valid, reason


def test_signed_run_user_isolation(ev_project, tmp_path, monkeypatch):
    from app.persistence import db as db_mod
    db_mod.DB_PATH = str(tmp_path / "iso.db")
    from app.services.project_library_service import ensure_reference_models
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.persistence.workspace_repository import save_workspace_state
    from app.persistence.db import get_connection
    import json as _json
    ensure_reference_models()
    # cert-user's own EV working copy in THIS isolated DB
    own = create_reference_seeded_project(
        user_id="cert-user", template_source="generic_ev_charging_reference",
        requested_name="Own EV", capacity_mw=5.0,
    )
    ws_own = __import__("app.persistence.workspace_repository", fromlist=["get_workspace_state"]).get_workspace_state("cert-user", own.project_id)
    save_workspace_state(
        user_id="cert-user", project_id=own.project_id,
        project_code=own.project_code,
        draft_snapshot=ws_own.draft_snapshot, saved_snapshot=ws_own.draft_snapshot,
        last_runtime_snapshot=ws_own.draft_snapshot,
        last_runtime_summary={"project_irr": 0.147},
        last_runtime_snapshot_id="iso-snap-0001",
        last_runtime_origin="saved_state",
        dirty=False, governance_state=ws_own.governance_state,
        replay_metadata=ws_own.replay_metadata,
    )
    conn = get_connection()
    conn.execute(
        "UPDATE workspace_states SET any_run_committed=1, last_runtime_identity_json=? "
        "WHERE workspace_id=? AND user_id=?",
        (_json.dumps({"engine_version": "t"}), ws_own.workspace_id, "cert-user"),
    )
    conn.commit(); conn.close()
    # another user's EV working copy in the same DB
    other = create_reference_seeded_project(
        user_id="other-user", template_source="generic_ev_charging_reference",
        requested_name="Other EV", capacity_mw=5.0,
    )
    client = _client()
    # cert-user requests other-user's project → 403/404 (never data)
    resp = client.get(f"/api/v1.1/projects/{other.project_id}/run-certificate",
                      cookies=_auth_cookies("cert-user"))
    assert resp.status_code in (403, 404)
    # own project → 200
    resp = client.get(f"/api/v1.1/projects/{own.project_id}/run-certificate",
                      cookies=_auth_cookies("cert-user"))
    assert resp.status_code == 200


def _get_certificate(client, project_id):
    return client.get(f"/api/v1.1/projects/{project_id}/run-certificate",
                      cookies=_auth_cookies())


# ── API: committed Last Run required / no rerun ─────────────────────────────

def test_signed_run_endpoint_committed_last_run_required(tmp_path, monkeypatch):
    from app.persistence import db as db_mod
    db_mod.DB_PATH = str(tmp_path / "norun.db")
    from app.services.project_library_service import ensure_reference_models
    from app.services.reference_seed_service import create_reference_seeded_project
    ensure_reference_models()
    record = create_reference_seeded_project(
        user_id="norun-user", template_source="generic_ev_charging_reference",
        requested_name="No Run EV", capacity_mw=5.0,
    )
    client = _client()
    resp = client.get(f"/api/v1.1/projects/{record.project_id}/run-certificate",
                      cookies=_auth_cookies("norun-user"))
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "COMMITTED_LAST_RUN_REQUIRED"


# ── API: missing key → typed UNAVAILABLE, no raw exception ──────────────────

def test_signed_run_endpoint_missing_key_typed_unavailable(ev_project, monkeypatch):
    client = _client()
    monkeypatch.delenv(rcs.SIGNING_KEY_ENV_VAR, raising=False)
    resp = _get_certificate(client, ev_project["record"].project_id)
    assert resp.status_code == 503
    body = resp.json()
    assert body["error"] == "SIGNING_KEY_UNAVAILABLE"
    assert "Traceback" not in resp.text
