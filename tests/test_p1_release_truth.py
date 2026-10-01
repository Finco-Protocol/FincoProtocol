"""P1 Release Truth — lightweight semantic-contract tests (Opus residual).

Covers Section I of the master stream: Supported Today consistency, JEV
EXPERIMENTAL/default OFF, Yield default OFF (and execution separately
default OFF), production Verify count truth, token production metering
wording, Signed Run != Verify, Reference Regression Check naming, and the
early-repayment Known Limitation.

PR #153 (Radar snapshot UX) is deliberately NOT asserted as shipped: an
open PR is not a shipped feature.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _flat(rel: str) -> str:
    return " ".join(_read(rel).split()).lower()


class TestYieldTruth:
    def test_yield_flags_default_off(self):
        from finco_yield import flags

        assert flags.yield_enabled() is False
        assert flags.execution_enabled() is False

    def test_yield_authority_modules_exist_merged(self):
        # Implementation merged (PR #148): the isolated module exists.
        assert (REPO / "finco_yield" / "__init__.py").exists()
        assert (REPO / "finco_yield" / "underwriting.py").exists()


class TestJEVTruth:
    def test_jev_default_off(self):
        from app.radar_rwa.jev_intelligence.config import JevIntelligenceConfig
        from app.radar_rwa.jev_intelligence.contracts import JevMode

        cfg = JevIntelligenceConfig()
        assert cfg.mode is JevMode.OFF
        assert cfg.enabled is False

    def test_jev_shadow_not_visible_without_explicit_mode(self):
        from app.radar_rwa.jev_intelligence.config import JevIntelligenceConfig
        from app.radar_rwa.jev_intelligence.contracts import JevMode

        cfg = JevIntelligenceConfig.from_env({
            "FINCO_JEV_INTELLIGENCE_ENABLED": "1"})
        assert cfg.mode is JevMode.SHADOW
        assert cfg.visible is False


class TestVerifyAndMeteringTruth:
    def test_no_production_verified_asset_claim_in_bridge(self):
        import inspect

        from app.model_market_bridge import registry as registry_module

        source = inspect.getsource(registry_module)
        assert "app.verified" not in source

    def test_metering_wording_not_production_live(self):
        finco = _flat("app/templates/protocol/finco.html")
        assert "production_token_metering = not_shipped" in finco
        assert "production metering coverage is not live" in _flat("README.md") or \
            "not yet wired into all production resource-usage paths" in _flat("README.md")


class TestSignedRunTruth:
    def test_signed_run_distinct_from_verify_in_docs(self):
        readme = _flat("README.md")
        assert "not finco verify. not economic truth." in readme

    def test_m2_public_trust_shipped_modules_exist(self):
        # PR #149 merged: key registry + shared public/offline verifier exist.
        hits = list((REPO / "tools").glob("*verify*")) + \
            list((REPO / "tools").glob("*certificate*"))
        assert hits, "public/offline verifier tooling expected post-M-2"


class TestReferenceRegressionNaming:
    def test_trust_pack_uses_reference_regression_check(self):
        # Visible copy only: the Jinja comment documents the historical label
        # rename and is never rendered.
        import re

        raw = _read("app/templates/v2/partials/sheet_trust.html")
        visible = " ".join(re.sub(r"\{#.*?#\}", "", raw, flags=re.S).split()).lower()
        assert "reference regression check" in visible
        assert "model validation" not in visible


class TestEarlyRepaymentTruth:
    def test_known_limitation_documented_in_docs_status(self):
        docs = _flat("app/templates/protocol_docs.html")
        assert "voluntary early repayment</strong> — not_supported" in docs
        assert "refinancing</strong> — not_supported" in docs
        assert "prepayment penalty</strong> — not_supported" in docs
        assert "debt acceleration</strong> — not_supported" in docs
        assert "mandatory cash sweep" in docs

    def test_generic_debt_schedule_does_not_imply_structures(self):
        docs = _flat("app/templates/protocol_docs.html")
        assert "generic debt-schedule functionality does not imply" in docs

    def test_engine_has_no_voluntary_prepayment_module(self):
        engine_dir = REPO / "financial_engine"
        hits = [p for p in engine_dir.rglob("*.py")
                if "voluntary" in p.read_text(encoding="utf-8").lower()]
        assert not hits, hits


class TestPR153And156Truth:
    def test_pr153_merged_snapshot_first_may_be_described(self):
        """PR #153 is MERGED: snapshot-first UX is shipped and MAY be
        described; it must still never be called an executable price."""
        road = _flat("docs/ROADMAP.md")
        assert "r-live snapshot-first ux" in road
        docs = _flat("app/templates/protocol_docs.html")
        assert "not executable" in docs

    def test_m6_engine_capability_shipped_not_user_exposed(self):
        road = _flat("docs/ROADMAP.md")
        assert "m-6 full-tenor gearing sculpting" in road
        assert "explicit opt-in" in road
        assert "user-facing configuration not exposed" in road
        # M-6 must not be blurred into voluntary early repayment.
        limits = _flat("app/templates/protocol_docs.html")
        assert "voluntary early repayment" in limits
        assert "not_supported" in limits
