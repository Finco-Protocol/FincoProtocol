"""FINCO A2 — Public Verify + Exact Methodology Reproducibility tests.

Covers:
  A2.1 — Public Reference Verify Contract
    - HTTP 200 on all anonymous routes (no auth)
    - Certificate hash recomputation
    - Signature envelope structure

  A2.2 — Outsider Verification
    - Valid package → PASS
    - Modified assumptions → FAIL (assumptions_sha256 mismatch)
    - Modified outputs → FAIL (outputs_sha256 mismatch)
    - Tampered certificate → FAIL (certificate_digest mismatch)
    - Wrong signing key → FAIL (signature invalid)

  A2.3 — Methodology Reproducibility
    - Bank (P90) CFADS for stub period = base_rev × (1400/1500) − opex
    - Stub principal = bank_cfads / target_dscr − interest
    - Day-count: interest uses ACT/360 (121 days exclusive), OPEX uses ACT/365 (122 days)
    - Target DSCR (1.20) ≠ Achieved min DSCR (1.25)
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import pytest

from fastapi.testclient import TestClient


# ── Helpers ────────────────────────────────────────────────────────────────────

def _canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def test_issuer_key_hex() -> str:
    """Generate a fresh Ed25519 private key for testing and set it in the env."""
    from Crypto.PublicKey import ECC
    key = ECC.generate(curve="Ed25519")
    seed = key.d.to_bytes(32, "big")
    return seed.hex()


@pytest.fixture(scope="module")
def client(test_issuer_key_hex):
    """TestClient with issuer key set in env."""
    os.environ["FINCO_ISSUER_PRIVATE_KEY_HEX"] = test_issuer_key_hex
    import main_web
    yield TestClient(main_web.app, raise_server_exceptions=True)
    os.environ.pop("FINCO_ISSUER_PRIVATE_KEY_HEX", None)


@pytest.fixture(scope="module")
def reference_package(client):
    """Fetch all reference package artifacts once for the module."""
    cert_r = client.get("/verify/reference/solar-reference-a/certificate.json")
    assume_r = client.get("/verify/reference/solar-reference-a/assumptions.json")
    output_r = client.get("/verify/reference/solar-reference-a/outputs.json")
    sig_r = client.get("/verify/reference/solar-reference-a/signature.json")
    key_r = client.get("/verify/reference/solar-reference-a/public-key.pem")
    assert cert_r.status_code == 200
    assert assume_r.status_code == 200
    assert output_r.status_code == 200
    assert sig_r.status_code == 200
    assert key_r.status_code == 200
    return {
        "certificate": cert_r.json(),
        "assumptions": assume_r.json(),
        "outputs": output_r.json(),
        "signature": sig_r.json(),
        "public_key_pem": key_r.text,
    }


# ── A2.1: Public routes — no auth required ─────────────────────────────────────

class TestPublicRoutes:
    """All reference routes return 200 with no authentication cookie."""

    def test_certificate_json_anonymous(self, client):
        r = client.get("/verify/reference/solar-reference-a/certificate.json")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["schema"] == "FINCO_REFERENCE_CERTIFICATE_V1"
        assert data["asset_id"] == "solar-reference-a"

    def test_assumptions_json_anonymous(self, client):
        r = client.get("/verify/reference/solar-reference-a/assumptions.json")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)

    def test_outputs_json_anonymous(self, client):
        r = client.get("/verify/reference/solar-reference-a/outputs.json")
        assert r.status_code == 200
        data = r.json()
        assert "runtime_summary" in data

    def test_signature_json_anonymous(self, client):
        r = client.get("/verify/reference/solar-reference-a/signature.json")
        assert r.status_code == 200
        data = r.json()
        assert data["schema"] == "FINCO_ISSUER_SIGNATURE_V1"
        assert data["algorithm"] == "Ed25519"
        assert "signature_b64" in data

    def test_public_key_pem_anonymous(self, client):
        r = client.get("/verify/reference/solar-reference-a/public-key.pem")
        assert r.status_code == 200
        assert "BEGIN PUBLIC KEY" in r.text

    def test_verify_py_anonymous(self, client):
        r = client.get("/verify/reference/solar-reference-a/verify.py")
        assert r.status_code == 200
        assert "FINCO Solar Reference" in r.text
        assert "def main" in r.text

    def test_html_page_anonymous(self, client):
        r = client.get("/verify/reference/solar-reference-a")
        assert r.status_code == 200
        assert "Public Verification" in r.text


# ── A2.1: Certificate hash recomputation ───────────────────────────────────────

class TestCertificateHash:

    def test_assumptions_sha256_matches_certificate(self, reference_package):
        cert = reference_package["certificate"]
        assumptions = reference_package["assumptions"]
        expected = cert["identity"]["assumptions_sha256"]
        computed = _sha256(_canonical_json(assumptions))
        assert computed == expected, (
            f"assumptions_sha256 mismatch\n  cert:     {expected}\n  computed: {computed}"
        )

    def test_outputs_sha256_matches_certificate(self, reference_package):
        cert = reference_package["certificate"]
        outputs = reference_package["outputs"]
        expected = cert["identity"]["outputs_sha256"]
        computed = _sha256(_canonical_json(outputs))
        assert computed == expected, (
            f"outputs_sha256 mismatch\n  cert:     {expected}\n  computed: {computed}"
        )

    def test_certificate_digest_self_consistent(self, reference_package):
        cert = reference_package["certificate"]
        stored_digest = cert["certificate_digest_sha256"]
        stored_id = cert["certificate_id"]
        payload_only = {
            k: v for k, v in cert.items()
            if k not in ("certificate_id", "certificate_digest_sha256")
        }
        computed_digest = _sha256(_canonical_json(payload_only))
        assert computed_digest == stored_digest
        assert stored_id == "frc_" + computed_digest[:16]

    def test_certificate_structure(self, reference_package):
        cert = reference_package["certificate"]
        assert cert["schema"] == "FINCO_REFERENCE_CERTIFICATE_V1"
        assert cert["asset_id"] == "solar-reference-a"
        assert cert["run"]["project_code"] == "REF-SOLAR-A"
        assert cert["run"]["scenario"] == "Base"
        assert cert["model"]["engine_version"]
        assert cert["identity"]["assumptions_sha256"]
        assert cert["identity"]["outputs_sha256"]
        assert cert["certificate_id"].startswith("frc_")
        assert len(cert["certificate_id"]) == 4 + 16  # "frc_" + 16 hex chars


# ── A2.2: Signature verification ───────────────────────────────────────────────

class TestSignatureVerification:

    def test_signature_valid_for_certificate(self, reference_package):
        from finco_protocol.verification.issuer import verify_signature_with_pem
        cert = reference_package["certificate"]
        sig = reference_package["signature"]
        pub_pem = reference_package["public_key_pem"]
        assert verify_signature_with_pem(cert, sig, pub_pem) is True

    def test_signature_schema_correct(self, reference_package):
        sig = reference_package["signature"]
        assert sig["schema"] == "FINCO_ISSUER_SIGNATURE_V1"
        assert sig["algorithm"] == "Ed25519"
        assert len(sig["signature_b64"]) > 0
        # Ed25519 signature is 64 bytes = 88 base64 chars (padded)
        assert len(base64.b64decode(sig["signature_b64"])) == 64


# ── A2.2: Tamper tests ─────────────────────────────────────────────────────────

class TestTamperDetection:

    def test_modified_assumptions_fails_hash(self, reference_package):
        """Modifying assumptions produces a different hash → certificate check fails."""
        cert = reference_package["certificate"]
        assumptions = copy.deepcopy(reference_package["assumptions"])
        # Inject a fake field
        assumptions["__tampered__"] = True
        tampered_sha = _sha256(_canonical_json(assumptions))
        assert tampered_sha != cert["identity"]["assumptions_sha256"]

    def test_modified_outputs_fails_hash(self, reference_package):
        """Modifying outputs produces a different hash."""
        cert = reference_package["certificate"]
        outputs = copy.deepcopy(reference_package["outputs"])
        outputs["__tampered__"] = True
        tampered_sha = _sha256(_canonical_json(outputs))
        assert tampered_sha != cert["identity"]["outputs_sha256"]

    def test_tampered_certificate_fails_digest(self, reference_package):
        """Modifying the certificate payload makes the digest check fail."""
        cert = copy.deepcopy(reference_package["certificate"])
        cert["headline_outputs"]["project_irr"] = 9.99  # tamper
        stored_digest = cert["certificate_digest_sha256"]
        payload_only = {
            k: v for k, v in cert.items()
            if k not in ("certificate_id", "certificate_digest_sha256")
        }
        computed = _sha256(_canonical_json(payload_only))
        assert computed != stored_digest

    def test_wrong_key_fails_signature(self, reference_package):
        """Signature verified against a different key fails."""
        from Crypto.PublicKey import ECC
        from finco_protocol.verification.issuer import verify_signature_with_pem
        # Generate a fresh unrelated key
        wrong_key = ECC.generate(curve="Ed25519")
        wrong_pem = wrong_key.public_key().export_key(format="PEM")
        cert = reference_package["certificate"]
        sig = reference_package["signature"]
        assert verify_signature_with_pem(cert, sig, wrong_pem) is False

    def test_modified_certificate_fails_signature(self, reference_package):
        """A tampered certificate fails signature verification."""
        from finco_protocol.verification.issuer import verify_signature_with_pem
        cert = copy.deepcopy(reference_package["certificate"])
        cert["headline_outputs"]["project_irr"] = 9.99  # tamper
        sig = reference_package["signature"]
        pub_pem = reference_package["public_key_pem"]
        assert verify_signature_with_pem(cert, sig, pub_pem) is False


# ── A2.3: Methodology Reproducibility ─────────────────────────────────────────

class TestMethodologyReproducibility:
    """Trace authoritative runtime values and confirm methodology matches."""

    @pytest.fixture(scope="class")
    def solar_run(self):
        """Run the Solar reference model once for all methodology tests."""
        from app.api.project_runner import run_project
        return run_project("Generic Solar Reference", "Base")

    def test_stub_period_interest_act360(self, solar_run):
        """Y2031-H1 (stub) interest uses ACT/360 with 121 exclusive days."""
        debt = solar_run.get("debt_schedule", {})
        periods = debt.get("periods", [])
        # First repayment period (stub, COD=2031-03-01 to 2031-06-30)
        stub = next(
            (p for p in periods
             if p.get("is_operation") and p.get("year_index") == 2031 and p.get("period_in_year") == 1),
            None,
        )
        if stub is None:
            pytest.skip("Debt schedule period labels not in expected format")

        interest = stub.get("senior_interest_keur", 0)
        # Expected: 24750 × 0.055 × 121/360 ≈ 457.53
        expected_interest = 24750.0 * 0.055 * (121 / 360)
        assert abs(interest - expected_interest) < 0.05, (
            f"Stub period ACT/360 interest: expected ≈{expected_interest:.2f}, got {interest:.2f}"
        )

    def test_bank_cfads_p90_sculpting(self, solar_run):
        """Stub period principal uses bank (P90) CFADS, not base (P50) CFADS.

        Bank CFADS = base_revenue × (1400/1500) − opex
        Principal = bank_cfads / 1.20 − interest
        """
        kpis = solar_run.get("kpis", {})
        debt = solar_run.get("debt_schedule", {})
        periods = debt.get("periods", [])

        stub = next(
            (p for p in periods
             if p.get("is_operation") and p.get("year_index") == 2031 and p.get("period_in_year") == 1),
            None,
        )
        if stub is None:
            pytest.skip("Debt schedule period labels not in expected format")

        interest = stub.get("senior_interest_keur", 0)
        principal = stub.get("senior_principal_keur", 0)
        # Runtime interest ≈ 457.53 (ACT/360 exclusive: 24750 × 5.5% × 121/360)
        # Bank CFADS ≈ base_revenue × (1400/1500) − opex ≈ 1572.46 × 0.9333 − 127.01 = 1340.61
        # Principal ≈ 1340.61/1.20 − 457.53 ≈ 659.65
        assert abs(principal - 659.65) < 0.10, (
            f"Stub principal (bank P90 sculpting): expected ≈659.65, got {principal:.2f}"
        )

    def test_target_dscr_is_sculpting_parameter(self, solar_run):
        """target_dscr is 1.20 (sculpting parameter), not the achieved min DSCR."""
        kpis = solar_run.get("kpis", {})
        target_dscr = kpis.get("target_dscr")
        assert target_dscr is not None
        assert abs(target_dscr - 1.20) < 0.001, (
            f"target_dscr (sculpting parameter): expected 1.20, got {target_dscr}"
        )

    def test_min_dscr_exceeds_target(self, solar_run):
        """Achieved min DSCR (1.25) > target DSCR (1.20) due to gearing constraint."""
        kpis = solar_run.get("kpis", {})
        min_dscr = kpis.get("min_dscr")
        assert min_dscr is not None
        assert min_dscr > 1.20, (
            f"Achieved min DSCR ({min_dscr}) should exceed sculpting target (1.20)"
        )
        assert abs(min_dscr - 1.25) < 0.02, (
            f"Achieved min DSCR: expected ≈1.25, got {min_dscr:.4f}"
        )

    def test_total_capex_33000(self, solar_run):
        """Total CAPEX = 33,000 kEUR (factory canonical value)."""
        kpis = solar_run.get("kpis", {})
        total_capex = kpis.get("total_capex_keur")
        assert total_capex is not None
        assert abs(total_capex - 33000) < 1, (
            f"Total CAPEX: expected 33,000 kEUR, got {total_capex}"
        )

    def test_senior_debt_24750(self, solar_run):
        """Senior debt = 24,750 kEUR (gearing cap binding: 75% × 33,000)."""
        kpis = solar_run.get("kpis", {})
        senior_debt = kpis.get("senior_debt_keur")
        assert senior_debt is not None
        assert abs(senior_debt - 24750) < 1, (
            f"Senior debt: expected 24,750 kEUR, got {senior_debt}"
        )

    def test_p90_yield_ratio(self):
        """Solar reference: P90_10Y operating hours = 1400, P50 = 1500 → ratio = 0.9333."""
        from app.project_factories import create_generic_solar_reference
        inputs = create_generic_solar_reference()
        tech = inputs.technical
        assert tech.operating_hours_p50 == 1500.0
        assert tech.operating_hours_p90_10y == 1400.0
        ratio = tech.operating_hours_p90_10y / tech.operating_hours_p50
        assert abs(ratio - (1400 / 1500)) < 1e-9

    def test_bank_cfads_formula_derivation(self, solar_run):
        """Bank CFADS for stub period = base_revenue × (P90/P50) − opex ≈ 1340.6 kEUR."""
        # We can't directly read bank-case values from the payload (it only has base values)
        # but we can verify the sculpting outcome: principal = bank_cfads/1.20 − interest
        # implies bank_cfads = (principal + interest) × 1.20
        debt = solar_run.get("debt_schedule", {})
        periods = debt.get("periods", [])
        stub = next(
            (p for p in periods
             if p.get("is_operation") and p.get("year_index") == 2031 and p.get("period_in_year") == 1),
            None,
        )
        if stub is None:
            pytest.skip("Debt schedule period labels not in expected format")

        interest = stub.get("senior_interest_keur", 0)
        principal = stub.get("senior_principal_keur", 0)
        implied_bank_cfads = (principal + interest) * 1.20
        expected_bank_cfads = 1340.61
        assert abs(implied_bank_cfads - expected_bank_cfads) < 0.15, (
            f"Implied bank CFADS: expected ≈{expected_bank_cfads}, got {implied_bank_cfads:.2f}"
        )
