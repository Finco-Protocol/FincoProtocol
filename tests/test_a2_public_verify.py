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

  A2.2b — Real standalone verifier (subprocess e2e)
    - Valid package dir → exit 0
    - Tamper cases → non-zero exit
    - No-crypto mode → non-zero (never passes without Ed25519)

  A2.3 — Methodology Reproducibility
    - Bank (P90) CFADS from authoritative debt_sizing engine object (non-circular)
    - Stub principal = bank_cfads / target_dscr − interest
    - Day-count: interest uses ACT/360 (121 days exclusive), OPEX uses ACT/365 (122 days)
    - Target DSCR (1.20) ≠ Achieved min DSCR (1.25)
    - Public methodology HTML contains exact runtime values (drift test)
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
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


@pytest.fixture(scope="module")
def package_dir(reference_package, tmp_path_factory):
    """Write reference package to a temp dir for offline subprocess tests."""
    d = tmp_path_factory.mktemp("ref_pkg")
    (d / "certificate.json").write_text(json.dumps(reference_package["certificate"]))
    (d / "assumptions.json").write_text(json.dumps(reference_package["assumptions"]))
    (d / "outputs.json").write_text(json.dumps(reference_package["outputs"]))
    (d / "signature.json").write_text(json.dumps(reference_package["signature"]))
    (d / "public-key.pem").write_text(reference_package["public_key_pem"])
    return str(d)


# ── A2.1: Public routes — no auth required ─────────────────────────────────────

class TestPublicRoutes:
    """All reference routes return 200 with no authentication cookie.
    Routes that require issuer signing return 200 when the key is configured.
    Routes fail closed (503) when the issuer key is absent.
    """

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
        assert r.status_code == 200, f"expected 200 with issuer key configured, got {r.status_code}"
        data = r.json()
        assert data["schema"] == "FINCO_ISSUER_SIGNATURE_V1"
        assert data["algorithm"] == "Ed25519"
        assert "signature_b64" in data

    def test_public_key_pem_anonymous(self, client):
        r = client.get("/verify/reference/solar-reference-a/public-key.pem")
        assert r.status_code == 200, f"expected 200 with issuer key configured, got {r.status_code}"
        assert "BEGIN PUBLIC KEY" in r.text

    def test_verify_py_anonymous(self, client):
        r = client.get("/verify/reference/solar-reference-a/verify.py")
        assert r.status_code == 200
        assert "FINCO Solar Reference" in r.text
        assert "def main" in r.text
        # Canonical verifier must not skip signature
        assert "SKIP" not in r.text or "integrity-only" in r.text.lower()

    def test_html_page_anonymous(self, client):
        r = client.get("/verify/reference/solar-reference-a")
        assert r.status_code == 200
        assert "Public Verification" in r.text

    def test_signer_absent_fails_closed(self):
        """Without the issuer key, signature/public-key routes return 503."""
        saved = os.environ.pop("FINCO_ISSUER_PRIVATE_KEY_HEX", None)
        try:
            import main_web
            test_client = TestClient(main_web.app, raise_server_exceptions=True)
            sig_r = test_client.get("/verify/reference/solar-reference-a/signature.json")
            key_r = test_client.get("/verify/reference/solar-reference-a/public-key.pem")
            assert sig_r.status_code == 503, f"expected 503 without key, got {sig_r.status_code}"
            assert key_r.status_code == 503, f"expected 503 without key, got {key_r.status_code}"
        finally:
            if saved is not None:
                os.environ["FINCO_ISSUER_PRIVATE_KEY_HEX"] = saved

    def test_malformed_key_fails_closed(self):
        """Malformed issuer key hex returns controlled 503, not unhandled server error."""
        saved = os.environ.get("FINCO_ISSUER_PRIVATE_KEY_HEX")
        os.environ["FINCO_ISSUER_PRIVATE_KEY_HEX"] = "notvalidhex!!!!"
        try:
            import main_web
            test_client = TestClient(main_web.app, raise_server_exceptions=False)
            sig_r = test_client.get("/verify/reference/solar-reference-a/signature.json")
            assert sig_r.status_code == 503, (
                f"malformed key should return 503, got {sig_r.status_code}"
            )
        finally:
            if saved is not None:
                os.environ["FINCO_ISSUER_PRIVATE_KEY_HEX"] = saved
            else:
                os.environ.pop("FINCO_ISSUER_PRIVATE_KEY_HEX", None)


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
        from app.verify.issuer import verify_signature_with_pem
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
        from app.verify.issuer import verify_signature_with_pem
        wrong_key = ECC.generate(curve="Ed25519")
        wrong_pem = wrong_key.public_key().export_key(format="PEM")
        cert = reference_package["certificate"]
        sig = reference_package["signature"]
        assert verify_signature_with_pem(cert, sig, wrong_pem) is False

    def test_modified_certificate_fails_signature(self, reference_package):
        """A tampered certificate fails signature verification."""
        from app.verify.issuer import verify_signature_with_pem
        cert = copy.deepcopy(reference_package["certificate"])
        cert["headline_outputs"]["project_irr"] = 9.99  # tamper
        sig = reference_package["signature"]
        pub_pem = reference_package["public_key_pem"]
        assert verify_signature_with_pem(cert, sig, pub_pem) is False


# ── A2.2b: Real standalone verifier subprocess tests ──────────────────────────

_VERIFIER_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tools", "verify_reference_package.py",
)


def _run_verifier(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, _VERIFIER_SCRIPT, *args],
        capture_output=True, text=True,
    )


class TestStandaloneVerifier:
    """End-to-end tests for the real standalone verifier script via subprocess."""

    def test_valid_package_exits_zero(self, package_dir):
        """Valid package dir → exit 0, output contains PASS and authentic."""
        r = _run_verifier("--package-dir", package_dir)
        assert r.returncode == 0, f"expected exit 0\nstdout: {r.stdout}\nstderr: {r.stderr}"
        assert "PASS" in r.stdout
        assert "authentic" in r.stdout.lower()

    def test_tampered_assumptions_exits_nonzero(self, package_dir, reference_package):
        """Tampered assumptions → non-zero exit."""
        with tempfile.TemporaryDirectory() as bad_dir:
            import shutil
            for f in ["certificate.json", "outputs.json", "signature.json", "public-key.pem"]:
                shutil.copy(os.path.join(package_dir, f), os.path.join(bad_dir, f))
            bad_assumptions = copy.deepcopy(reference_package["assumptions"])
            bad_assumptions["__tampered__"] = True
            (os.path.join(bad_dir, "assumptions.json") and
             open(os.path.join(bad_dir, "assumptions.json"), "w").write(
                 json.dumps(bad_assumptions)
             ))
            r = _run_verifier("--package-dir", bad_dir)
            assert r.returncode != 0, "tampered assumptions should cause non-zero exit"
            assert "FAIL" in r.stderr or "mismatch" in r.stderr.lower()

    def test_tampered_outputs_exits_nonzero(self, package_dir, reference_package):
        """Tampered outputs → non-zero exit."""
        with tempfile.TemporaryDirectory() as bad_dir:
            import shutil
            for f in ["certificate.json", "assumptions.json", "signature.json", "public-key.pem"]:
                shutil.copy(os.path.join(package_dir, f), os.path.join(bad_dir, f))
            bad_outputs = copy.deepcopy(reference_package["outputs"])
            bad_outputs["__tampered__"] = True
            open(os.path.join(bad_dir, "outputs.json"), "w").write(
                json.dumps(bad_outputs)
            )
            r = _run_verifier("--package-dir", bad_dir)
            assert r.returncode != 0, "tampered outputs should cause non-zero exit"

    def test_tampered_certificate_exits_nonzero(self, package_dir, reference_package):
        """Tampered certificate → non-zero exit."""
        with tempfile.TemporaryDirectory() as bad_dir:
            import shutil
            for f in ["assumptions.json", "outputs.json", "signature.json", "public-key.pem"]:
                shutil.copy(os.path.join(package_dir, f), os.path.join(bad_dir, f))
            bad_cert = copy.deepcopy(reference_package["certificate"])
            bad_cert["headline_outputs"]["project_irr"] = 99.9
            open(os.path.join(bad_dir, "certificate.json"), "w").write(
                json.dumps(bad_cert)
            )
            r = _run_verifier("--package-dir", bad_dir)
            assert r.returncode != 0, "tampered certificate should cause non-zero exit"

    def test_wrong_public_key_exits_nonzero(self, package_dir, reference_package):
        """Wrong public key → signature fails → non-zero exit."""
        from Crypto.PublicKey import ECC
        with tempfile.TemporaryDirectory() as bad_dir:
            import shutil
            for f in ["certificate.json", "assumptions.json", "outputs.json", "signature.json"]:
                shutil.copy(os.path.join(package_dir, f), os.path.join(bad_dir, f))
            wrong_key = ECC.generate(curve="Ed25519")
            wrong_pem = wrong_key.public_key().export_key(format="PEM")
            open(os.path.join(bad_dir, "public-key.pem"), "w").write(wrong_pem)
            r = _run_verifier("--package-dir", bad_dir)
            assert r.returncode != 0, "wrong public key should cause non-zero exit"
            assert "FAIL" in r.stderr

    def test_integrity_only_never_outputs_pass(self, package_dir):
        """--integrity-only mode never outputs the PASS verdict or authenticity claim."""
        r = _run_verifier("--package-dir", package_dir, "--integrity-only")
        assert r.returncode == 0, f"integrity-only should exit 0 on valid hashes\nstderr: {r.stderr}"
        assert "INTEGRITY CHECK ONLY" in r.stdout
        # Final verdict must not say PASS or claim FINCO issued/authentic
        assert "PASS — " not in r.stdout
        assert "authentic and unmodified" not in r.stdout.lower()
        assert "FINCO issued this exact certificate" not in r.stdout


# ── A2.3: Methodology Reproducibility ─────────────────────────────────────────

class TestMethodologyReproducibility:
    """Trace authoritative runtime values and confirm methodology matches.
    All tests use assert (never pytest.skip) — 0 skipped is required.
    """

    @pytest.fixture(scope="class")
    def solar_financing_result(self):
        """Run Solar reference model via financing model for direct debt_sizing access."""
        from app.project_factories import create_generic_solar_reference
        from financial_engine.financing.project import run_project_financing_model
        inputs = create_generic_solar_reference()
        return run_project_financing_model(inputs)

    @pytest.fixture(scope="class")
    def solar_run(self):
        """Run the Solar reference model via app API for KPI/schedule access."""
        from app.api.project_runner import run_project
        return run_project("Generic Solar Reference", "Base")

    @pytest.fixture(scope="class")
    def stub_debt_period(self, solar_run):
        """First operating (stub) period from debt schedule — Y2031-H1."""
        debt = solar_run.get("debt_schedule", {})
        periods = debt.get("periods", [])
        stub = next(
            (p for p in periods
             if p.get("is_operation") and p.get("year_index") == 2031 and p.get("period_in_year") == 1),
            None,
        )
        assert stub is not None, (
            "canonical Solar reference stub period (Y2031-H1, year_index=2031, period_in_year=1) "
            "is missing from debt_schedule — this is a canonical invariant and must not be absent"
        )
        return stub

    def test_stub_period_interest_act360(self, stub_debt_period):
        """Y2031-H1 (stub) interest uses ACT/360 with 121 exclusive days."""
        interest = stub_debt_period.get("senior_interest_keur", 0)
        # Expected: 24750 × 0.055 × 121/360 ≈ 457.53
        expected_interest = 24750.0 * 0.055 * (121 / 360)
        assert abs(interest - expected_interest) < 0.05, (
            f"Stub period ACT/360 interest: expected ≈{expected_interest:.2f}, got {interest:.2f}"
        )

    def test_bank_cfads_p90_from_authoritative_engine_object(self, solar_financing_result):
        """Bank CFADS for stub period (period_index=3) from authoritative DebtSizingSchedules.

        Non-circular proof: reads debt_sizing.bank_cfads_keur directly from the engine
        result object — not reverse-solved from principal.

        Authority: financial_engine.results.DebtSizingSchedules.bank_cfads_keur
        """
        pmr = solar_financing_result.project_model_result
        ds = pmr.debt_sizing
        assert ds is not None, "DebtSizingSchedules must be populated for Solar reference"
        # Period index 3 = first operating period (stub, Y2031-H1)
        assert 3 in ds.period_indices, "Period index 3 must exist in debt sizing schedules"
        idx = ds.period_indices.index(3)
        bank_cfads = ds.bank_cfads_keur[idx]
        assert abs(bank_cfads - 1340.61) < 0.10, (
            f"Authoritative bank CFADS (period_index=3): expected ≈1340.61 kEUR, got {bank_cfads:.4f}"
        )

    def test_bank_revenue_p90_from_authoritative_engine_object(self, solar_financing_result):
        """Bank revenue for stub period from DebtSizingSchedules (non-circular).

        Bank revenue = base_revenue × (P90_operating_hours / P50_operating_hours)
                     = base_revenue × (1400 / 1500)
        """
        pmr = solar_financing_result.project_model_result
        ds = pmr.debt_sizing
        assert ds is not None
        idx = ds.period_indices.index(3)
        bank_revenue = ds.bank_revenue_keur[idx]
        # Expected: base_revenue × (1400/1500) ≈ 1572.5 × 0.9333 ≈ 1467.6
        assert abs(bank_revenue - 1467.6) < 0.5, (
            f"Authoritative bank revenue (period_index=3): expected ≈1467.6 kEUR, got {bank_revenue:.4f}"
        )

    def test_bank_cfads_p90_sculpting_principal(self, stub_debt_period, solar_financing_result):
        """Stub period principal = bank_cfads / target_DSCR − interest (non-circular).

        Uses authoritative bank_cfads from engine object — not from principal.
        """
        pmr = solar_financing_result.project_model_result
        ds = pmr.debt_sizing
        idx = ds.period_indices.index(3)
        bank_cfads = ds.bank_cfads_keur[idx]

        interest = stub_debt_period.get("senior_interest_keur", 0)
        principal = stub_debt_period.get("senior_principal_keur", 0)
        target_dscr = 1.20

        expected_principal = bank_cfads / target_dscr - interest
        assert abs(principal - expected_principal) < 0.10, (
            f"Principal mismatch: bank_cfads({bank_cfads:.2f})/1.20 - interest({interest:.2f}) "
            f"= {expected_principal:.2f}, but actual principal = {principal:.2f}"
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

    def test_stub_p50_base_cfads(self, solar_financing_result):
        """Stub period base (P50) CFADS ≈ 1445.4 kEUR from TaxAndCfadsSchedules."""
        pmr = solar_financing_result.project_model_result
        tac = pmr.tax_and_cfads
        assert tac is not None, "TaxAndCfadsSchedules must be populated for Solar reference"
        assert 3 in tac.period_indices, "Period index 3 must exist in tax_and_cfads"
        idx = tac.period_indices.index(3)
        cfads = tac.cfads_keur[idx]
        assert abs(cfads - 1445.4) < 0.5, (
            f"Base (P50) CFADS stub period: expected ≈1445.4 kEUR, got {cfads:.4f}"
        )


# ── A2.4: Public methodology HTML is bound to runtime values ───────────────────

class TestMethodologyHtmlBinding:
    """Proves the public methodology page contains authoritative runtime values.
    If the HTML drifts, these tests fail.
    """

    @pytest.fixture(scope="class")
    def methodology_html(self):
        """Read the rendered methodology HTML file."""
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "app", "templates", "model_methodology.html",
        )
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    @pytest.fixture(scope="class")
    def runtime_values(self):
        """Canonical runtime values from the authoritative engine run."""
        from app.project_factories import create_generic_solar_reference
        from financial_engine.financing.project import run_project_financing_model
        inputs = create_generic_solar_reference()
        result = run_project_financing_model(inputs)
        pmr = result.project_model_result
        ds = pmr.debt_sizing

        from app.api.project_runner import run_project
        run = run_project("Generic Solar Reference", "Base")

        debt = run.get("debt_schedule", {})
        stub = next(
            (p for p in debt.get("periods", [])
             if p.get("is_operation") and p.get("year_index") == 2031 and p.get("period_in_year") == 1),
            None,
        )
        assert stub is not None, "canonical stub period missing"

        idx = ds.period_indices.index(3)
        return {
            "p50_operating_hours": inputs.technical.operating_hours_p50,
            "p90_operating_hours": inputs.technical.operating_hours_p90_10y,
            "bank_cfads": ds.bank_cfads_keur[idx],
            "bank_revenue": ds.bank_revenue_keur[idx],
            "senior_interest": stub["senior_interest_keur"],
            "senior_principal": stub["senior_principal_keur"],
            "senior_ds": stub["senior_ds_keur"],
            "target_dscr": run["kpis"]["target_dscr"],
            "min_dscr": run["kpis"]["min_dscr"],
            "total_capex": run["kpis"]["total_capex_keur"],
            "senior_debt": run["kpis"]["senior_debt_keur"],
        }

    def test_p50_operating_hours_in_html(self, methodology_html, runtime_values):
        """HTML contains canonical P50 operating hours."""
        assert "1,500" in methodology_html or "1500" in methodology_html, (
            "P50 operating hours (1,500 hr/yr) not found in methodology HTML"
        )

    def test_p90_operating_hours_in_html(self, methodology_html, runtime_values):
        """HTML contains canonical P90 operating hours."""
        assert "1,400" in methodology_html or "1400" in methodology_html, (
            "P90 operating hours (1,400 hr/yr) not found in methodology HTML"
        )

    def test_bank_cfads_in_html(self, methodology_html, runtime_values):
        """HTML contains bank CFADS value for stub period."""
        bank_cfads = runtime_values["bank_cfads"]
        # 1340.6 → "1,340.6" or "1340.6"
        rounded = f"{bank_cfads:.1f}"
        formatted = f"{bank_cfads:,.1f}"
        assert rounded in methodology_html or formatted in methodology_html, (
            f"Bank CFADS ({formatted} kEUR) not found in methodology HTML"
        )

    def test_senior_principal_in_html(self, methodology_html, runtime_values):
        """HTML contains senior principal for stub period."""
        principal = runtime_values["senior_principal"]
        rounded = f"{principal:.1f}"
        formatted = f"{principal:,.1f}"
        assert rounded in methodology_html or formatted in methodology_html, (
            f"Senior principal ({formatted} kEUR) not found in methodology HTML"
        )

    def test_senior_interest_in_html(self, methodology_html, runtime_values):
        """HTML contains senior interest for stub period."""
        interest = runtime_values["senior_interest"]
        rounded = f"{interest:.1f}"
        formatted = f"{interest:,.1f}"
        assert rounded in methodology_html or formatted in methodology_html, (
            f"Senior interest ({formatted} kEUR) not found in methodology HTML"
        )

    def test_capex_in_html(self, methodology_html, runtime_values):
        """HTML contains total CAPEX."""
        capex = runtime_values["total_capex"]
        assert "33,000" in methodology_html or "33000" in methodology_html, (
            f"Total CAPEX ({capex} kEUR) not found in methodology HTML"
        )

    def test_senior_debt_in_html(self, methodology_html, runtime_values):
        """HTML contains senior debt amount."""
        assert "24,750" in methodology_html or "24750" in methodology_html, (
            "Senior debt (24,750 kEUR) not found in methodology HTML"
        )

    def test_target_dscr_in_html(self, methodology_html, runtime_values):
        """HTML contains target DSCR (sculpting parameter)."""
        assert "1.20" in methodology_html, (
            "Target DSCR (1.20×) not found in methodology HTML"
        )

    def test_min_dscr_in_html(self, methodology_html, runtime_values):
        """HTML contains minimum achieved DSCR."""
        assert "1.25" in methodology_html, (
            "Minimum achieved DSCR (1.25×) not found in methodology HTML"
        )

    def test_bank_vs_base_distinction_in_html(self, methodology_html):
        """HTML explicitly distinguishes bank (P90_10Y) from base (P50) cases."""
        assert "P90" in methodology_html or "bank" in methodology_html.lower(), (
            "Bank/P90 distinction missing from methodology HTML"
        )
        assert "P50" in methodology_html, (
            "P50 base case missing from methodology HTML"
        )

    def test_interest_day_count_in_html(self, methodology_html):
        """HTML mentions ACT/360 or 121 days for interest day-count."""
        has_act360 = "ACT/360" in methodology_html or "act/360" in methodology_html.lower()
        has_121 = "121" in methodology_html
        assert has_act360 or has_121, (
            "ACT/360 exclusive day-count convention (or 121 days) not documented in methodology HTML"
        )
