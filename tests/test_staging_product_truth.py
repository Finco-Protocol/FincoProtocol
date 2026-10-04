"""Staging Product Truth & Roadmap contract tests.

Public surfaces (/docs, /roadmap, /verify, /protocol/finco) must describe the
current merged product truth without promoting feature-gated or experimental
work into production-active capability.
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
    def test_roadmap_primary_architecture_and_bands(self):
        road = _flat("app/templates/protocol_roadmap.html")
        assert "MODEL · RADAR · YIELD · CRYPTO" in road
        assert "VERIFY · API · $FINCO" in road
        for status in ("LIVE / IMPLEMENTED", "Q4 2026", "Q1 2027", "LATER"):
            assert status in road

    def test_roadmap_active_section(self):
        road = _flat("app/templates/protocol_roadmap.html")
        assert "Active now" in road
        assert "JEV Radar Intelligence V1" in road

    def test_roadmap_jev_merged_experimental_truth(self):
        road = _flat("app/templates/protocol_roadmap.html")
        jev_card = road[road.index("JEV Radar Intelligence V1"):]
        jev_card = jev_card[:jev_card.index("Signed Run Public Trust")]
        assert "EXPERIMENTAL — merged (PR #146)" in jev_card
        assert "IN DEVELOPMENT" not in jev_card
        assert "not shipped" not in jev_card
        assert "default OFF" in jev_card
        assert "SHADOW" in jev_card and "VISIBLE" in jev_card
        assert "SKIPPED_NO_KEY" in jev_card
        assert "JEV interprets. FINCO authorities remain authoritative." in jev_card
        assert "No investment recommendations" in jev_card
        assert "no trading signals" in jev_card
        assert "no price prediction" in jev_card
        assert "no Verify or identity authority" in jev_card

    def test_jev_module_matches_public_truth(self):
        from app.radar_rwa.jev_intelligence.config import JevIntelligenceConfig
        from app.radar_rwa.jev_intelligence.contracts import JevMode
        cfg = JevIntelligenceConfig()
        assert cfg.mode is JevMode.OFF
        assert cfg.enabled is False
        assert cfg.visible is False
        shadow = JevIntelligenceConfig.from_env({"FINCO_JEV_INTELLIGENCE_ENABLED": "1"})
        assert shadow.mode is JevMode.SHADOW
        assert shadow.visible is False
        explicit = JevIntelligenceConfig.from_env({
            "FINCO_JEV_INTELLIGENCE_ENABLED": "1",
            "FINCO_JEV_INTELLIGENCE_MODE": "VISIBLE",
        })
        assert explicit.mode is JevMode.VISIBLE

    def test_roadmap_m2_in_development(self):
        road = _flat("app/templates/protocol_roadmap.html")
        assert "Signed Run Public Trust — M-2" in road
        assert "IN DEVELOPMENT" in road
        assert "M-2 is not shipped until merged" in road

    def test_m2_state_matches_merged_main(self):
        import subprocess
        probe = subprocess.run(
            ["git", "grep", "-l", "public_verifier", "origin/main", "--", "app/services/"],
            cwd=REPO, capture_output=True, text=True,
        )
        assert probe.stdout.strip() == "", probe.stdout

    def test_roadmap_yield_merged_but_execution_inactive_truth(self):
        road = _flat("app/templates/protocol_roadmap.html")
        assert "FINCO Yield" in road
        assert "IMPLEMENTED / FEATURE-GATED" in road
        assert "PR #148, not merged" not in road
        assert "FINCO_YIELD_ENABLED defaults OFF" in road
        assert "FINCO_YIELD_EXECUTION_ENABLED defaults OFF" in road
        assert "Non-custodial" in road
        assert "no server signing" in road
        assert "no automatic broadcast" in road
        assert "no FINCO-owned vault" in road
        assert "no production mainnet money movement" in road
        assert "External alert delivery is NOT SHIPPED" in road
        assert "Explore → Underwrite → Evidence → Monitor → Act" in road

    def test_roadmap_crypto_utility_not_production_active(self):
        road = _flat("app/templates/protocol_roadmap.html")
        assert "production FINCO deployment count = 0" in road
        assert "token gating default = OFF" in road
        assert "chain = UNSET" in road
        assert "token contract = UNSET" in road
        assert "production threshold = UNSET" in road
        assert "production token activation is not configured" in road

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
        for rel in (
            "app/templates/protocol_docs.html",
            "app/templates/protocol_roadmap.html",
            "app/templates/protocol_verify.html",
        ):
            assert "coming soon" not in _flat(rel).lower(), rel


class TestMasterWorkflowInventory:
    def test_library_storage_clone_copy_pinned(self):
        assert "Working-copy runtime coming soon" in _read("app/templates/library/project_library_list.html")

    def test_readme_r_live_freshness_precision(self):
        readme = _flat("README.md")
        assert "300-second freshness gate" not in readme
        assert "300-second TWAP" in readme
        assert "fail-closed freshness policies" in readme

    def test_roadmap_md_r_live_freshness_precision(self):
        road = _flat("docs/ROADMAP.md")
        assert "300-second freshness gate" not in road
        assert "300-second TWAP" in road

    def test_api_page_documents_r_live(self):
        api = _flat("app/templates/protocol_api.html")
        assert "R-LIVE — On-Chain Reference Observations" in api
        assert "/api/v1.1/radar/r-live/assets" in api
        assert "Observations are not executable prices" in api

    def test_release_matrix_exists_and_current(self):
        matrix = _read("docs/review/PRODUCT_TRUTH_RELEASE_MATRIX.md")
        for feature in (
            "Run Integrity Checks (H-4b)",
            "Reference Regression Check (P1.3)",
            "Signed Run",
            "M-2",
            "R-LIVE V2",
            "JEV Radar Intelligence V1",
            "Wallet identity",
            "B2.3",
        ):
            assert feature in matrix, feature
        assert "PRODUCTION_VERIFIED_ASSET_COUNT = 0" in matrix
        assert "not merged" in matrix


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
        # Explicitly authorized Model V2 epic engine files are governed by the
        # Model V2 scope contract (tests/model_v2_governance.py); this guard keeps
        # protecting every other frozen path.
        from model_v2_governance import approved_by_active_model_v2_scope
        changed = [
            p for p in out.stdout.splitlines()
            if p.strip() and not approved_by_active_model_v2_scope(p.strip())
        ]
        assert changed == [], changed
