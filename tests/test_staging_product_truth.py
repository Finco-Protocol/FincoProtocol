"""Staging Product Truth & Roadmap Refresh — contract tests.

Proves the public staging surfaces (/docs, /roadmap, /verify, /protocol/finco)
state the current post-#143 product truth:

  - FINCO Trust Stack present with the five separate authorities;
  - Reference Regression Check terminology (no generic MODEL VALIDATION label);
  - Run Integrity shipped with its implemented scope;
  - Signed Run ≠ FINCO Verify ≠ economic truth; M-2 in development;
  - FINCO Verify production boundary (Verified production assets: 0);
  - R-LIVE documented as a first-class domain (not executable price);
  - Wallet identity implemented-foundation vs future split;
  - JEV not claimed shipped (EXPERIMENTAL / IN DEVELOPMENT only);
  - token launch not claimed.

Presentation-only stream: no financial_engine / finco_core / Radar authority /
model_validation / verified changes.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _flat(rel: str) -> str:
    return " ".join(_read(rel).split())


@pytest.fixture(scope="module")
def rendered():
    import tempfile, os

    os.environ["FINCO_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "staging-truth.db")
    from app.persistence import db

    db.DB_PATH = os.environ["FINCO_DB_PATH"]
    db.init_db()
    from fastapi.testclient import TestClient
    import main_web

    return TestClient(main_web.app, raise_server_exceptions=True)


class TestDocsTrustStack:
    def test_docs_trust_stack_section_present(self):
        docs = _flat("app/templates/protocol_docs.html")
        assert "FINCO Trust Stack" in docs
        for layer in (
            "What did FINCO calculate?",
            "Is the committed run internally consistent under implemented checks?",
            "Does the canonical reference still reproduce pinned expected outputs?",
            "Did FINCO cryptographically sign these exact committed bytes/evidence?",
            "sufficient source-attested evidence to bind the model/asset",
        ):
            assert layer in docs, layer

    def test_docs_trust_stack_separations(self):
        docs = _flat("app/templates/protocol_docs.html")
        assert "Reference Regression Check ≠ Run Integrity" in docs
        assert "Run Integrity ≠ FINCO Verify" in docs
        assert "Signed Run ≠ FINCO Verify" in docs
        assert "Signed Run ≠ economic truth" in docs

    def test_docs_run_integrity_shipped_scope(self):
        docs = _flat("app/templates/protocol_docs.html")
        assert "Run Integrity" in docs
        for scope in ("Sources &amp; Uses", "balance-sheet reconciliation",
                      "debt rollforward", "DSCR sculpting feasibility",
                      "sponsor-return input consistency"):
            assert scope in docs, scope
        assert "not economic truth" in docs

    def test_docs_signed_run_and_m2_truth(self):
        docs = _flat("app/templates/protocol_docs.html")
        assert "Ed25519" in docs
        assert "config-gated" in docs
        assert "M-2" in docs
        assert "blockchain anchoring" in docs or "anchoring" in docs

    def test_docs_no_generic_model_validation_label(self):
        docs = _flat("app/templates/protocol_docs.html")
        assert "MODEL VALIDATION" not in docs
        assert "Reference Regression Check" in docs

    def test_docs_r_live_first_class(self):
        docs = _flat("app/templates/protocol_docs.html")
        assert "R-LIVE" in docs
        assert "not tradeable or executable prices" in docs
        assert "AVAILABLE / STALE / UNAVAILABLE" in docs
        assert "1h / 24h" in docs
        assert "no ticker-based or fuzzy lookup" in docs


class TestRoadmapTruth:
    def test_roadmap_active_section(self):
        road = _flat("app/templates/protocol_roadmap.html")
        assert "Active now" in road
        assert "JEV Radar Intelligence V1" in road
        assert "EXPERIMENTAL / ACTIVE DEVELOPMENT" in road or "IN DEVELOPMENT" in road
        assert "not shipped" in road  # JEV explicitly not shipped
        assert "JEV interprets. FINCO authorities remain authoritative." in road

    def test_roadmap_m2_in_development(self):
        road = _flat("app/templates/protocol_roadmap.html")
        assert "Signed Run Public Trust — M-2" in road
        assert "IN DEVELOPMENT" in road
        assert "M-2 is not shipped until merged" in road

    def test_roadmap_model_market_bridge(self):
        road = _flat("app/templates/protocol_roadmap.html")
        assert "Model ↔ Market Bridge" in road
        assert "economic_asset_uid" in road
        assert "production VERIFIED assets today: 0" in road

    def test_roadmap_metered_utility_next(self):
        road = _flat("app/templates/protocol_roadmap.html")
        assert "$FINCO Metered Utility — M-1" in road
        assert "Token economics are not final; token launch is not claimed" in road

    def test_roadmap_wallet_identity_implemented_foundation(self):
        road = _flat("app/templates/protocol_roadmap.html")
        assert "foundation shipped" in road
        assert "EIP-1193" in road
        assert "EIP-191" in road
        assert "production token activation is not" in road

    def test_roadmap_shipped_truth_chips(self):
        road = _flat("app/templates/protocol_roadmap.html")
        assert "Run Integrity" in road
        assert "R-LIVE" in road
        assert "Reference Regression" in road or "Reference Regression Check" in road
        assert "DSCR-sculpting fail-closed feasibility" in road
        assert "production Verified assets: 0" in road

    def test_roadmap_r_live_no_generic_300s_freshness_claim(self):
        """F1: R-LIVE freshness is a TWAP window plus fail-closed rules — never
        a single collapsed '300-second freshness' SLA on the public roadmap."""
        road = _flat("app/templates/protocol_roadmap.html")
        assert "300-second freshness" not in road
        assert "300-second TWAP" in road
        assert "fail-closed freshness rules" in road

    def test_roadmap_later_uses_bands(self):
        road = _flat("app/templates/protocol_roadmap.html")
        assert ">LATER<" in road
        assert "L2 / Merkle Anchoring" in road


class TestVerifyTrustSurface:
    def test_verify_page_trust_sections(self):
        verify = _flat("app/templates/protocol_verify.html")
        assert "Trust &amp; Verification" in verify
        assert "Run Integrity Checks — SHIPPED" in verify
        assert "Reference Regression Check — SHIPPED" in verify
        assert "Signed Run Certificate — SHIPPED (config-gated)" in verify
        assert "in development (M-2)" in verify
        assert "No blockchain anchoring is implemented" in verify

    def test_verify_page_verify_boundary(self):
        verify = _flat("app/templates/protocol_verify.html")
        assert "Verified production assets: 0" in verify
        assert "MODEL_ONLY never means VERIFIED" in verify
        assert "Signed Run is not FINCO Verify and not economic truth" in verify

    def test_verify_no_unsupported_evidence_id_claim(self):
        """F2: the public Verify page must not invent an evidence_id contract."""
        verify = _flat("app/templates/protocol_verify.html")
        assert "confirmed evidence_id" not in verify
        assert "source-proven model↔market binding" in verify
        assert "canonical market evidence" in verify

    def test_verify_corpus_retained(self):
        verify = _read("app/templates/protocol_verify.html")
        assert "Public Validation Corpus" in verify
        assert "corpusSha256" in verify


class TestFincoPageTruth:
    def test_finco_implemented_vs_not_active(self):
        finco = _flat("app/templates/protocol/finco.html")
        assert "Implemented" in finco
        assert "Not necessarily production-active" in finco
        assert "EIP-1193" in finco
        assert "balance reader" in finco
        assert "entitlement decision rail" in finco
        assert "not a claim" in finco or "not claimed here" in finco

    def test_finco_invariants(self):
        finco = _flat("app/templates/protocol/finco.html")
        assert "$FINCO never touches the math" in finco
        assert "never determines whether evidence is true" in finco
        assert "never improves IRR, DSCR, valuation, Radar" in finco


class TestStatusVocabulary:
    def test_no_ambiguous_coming_soon(self):
        for rel in ("app/templates/protocol_docs.html",
                    "app/templates/protocol_roadmap.html",
                    "app/templates/protocol_verify.html"):
            assert "coming soon" not in _flat(rel).lower(), rel


class TestFrozenAuthorities:
    @pytest.mark.parametrize("frozen", [
        "financial_engine", "finco_core", "finco_radar/authority",
        "app/model_validation", "app/verified",
    ])
    def test_zero_diff_vs_main(self, frozen):
        import subprocess

        out = subprocess.run(
            ["git", "diff", "--name-only", "origin/main..HEAD", "--", frozen],
            cwd=REPO, capture_output=True, text=True,
        )
        if out.returncode != 0:
            pytest.skip("git history unavailable in this checkout")
        assert out.stdout.strip() == "", out.stdout
