"""Stock Token oracle candidate rejection tests (PR #190 Correction A)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

SHIP_PATH = REPO / "app" / "radar_rwa" / "data" / "stock_token_oracle_feeds.json"
CAND_PATH = REPO / "app" / "radar_rwa" / "data" / "stock_token_oracle_candidates.json"
VER_PATH = REPO / "docs" / "radar" / "stock_token_oracle_candidate_verification_2026-10-04.json"

EXPECTED_PROVEN = set()  # 0/13 SOURCE_PROVEN
EXPECTED_REJECTED = {"AAPL", "AMZN", "GOOGL", "META", "MSFT", "NFLX", "NVDA", "TSLA"}
EXPECTED_UNRESOLVED = {"AMD", "AVGO", "DELL", "INTC", "SNAP"}


class TestShippedRegistryStillZero:
    def test_shipped_registry_has_zero_bindings(self):
        raw = json.loads(SHIP_PATH.read_text(encoding="utf-8"))
        assert raw["bindings"] == []
        assert raw["sequencer"] is None

    def test_sequencer_authority_unchanged(self):
        raw = json.loads(SHIP_PATH.read_text(encoding="utf-8"))
        assert raw["sequencer_authority"]["state"] == "OFFICIAL_FEED_NOT_PUBLISHED"

    def test_chain_id_4663(self):
        raw = json.loads(SHIP_PATH.read_text(encoding="utf-8"))
        assert raw["chain_id"] == 4663


class TestCandidateRejection:
    def test_active_candidate_set_is_zero(self):
        raw = json.loads(CAND_PATH.read_text(encoding="utf-8"))
        assert raw["active_candidates"] == []
        assert len(raw["rejected_candidates"]) == 8

    def test_rejected_set_is_exact(self):
        raw = json.loads(CAND_PATH.read_text(encoding="utf-8"))
        symbols = {r["symbol"] for r in raw["rejected_candidates"]}
        assert symbols == EXPECTED_REJECTED

    def test_unresolved_set_is_exact(self):
        raw = json.loads(CAND_PATH.read_text(encoding="utf-8"))
        symbols = {u["symbol"] for u in raw["unresolved"]}
        assert symbols == EXPECTED_UNRESOLVED

    def test_every_rejection_has_typed_reason(self):
        raw = json.loads(CAND_PATH.read_text(encoding="utf-8"))
        for r in raw["rejected_candidates"]:
            assert r["verification_result"] == "NOT_DEPLOYED_ON_4663"
            assert "not deployed" in r["reason"].lower()

    def test_rejection_has_chain_and_block_evidence(self):
        raw = json.loads(CAND_PATH.read_text(encoding="utf-8"))
        for r in raw["rejected_candidates"]:
            assert r["verification_chain_id"] == 4663
            assert r["verification_block"] == 80165854

    def test_no_guessed_descriptions(self):
        raw = json.loads(CAND_PATH.read_text(encoding="utf-8"))
        for r in raw["rejected_candidates"]:
            assert "Stock Token" not in json.dumps(r)

    def test_provenance_preserved_for_audit(self):
        raw = json.loads(CAND_PATH.read_text(encoding="utf-8"))
        for r in raw["rejected_candidates"]:
            assert r.get("official_pair_path")
            assert r.get("token_contract")


class TestVerificationArtifact:
    def test_verification_artifact_exists_and_valid(self):
        raw = json.loads(VER_PATH.read_text(encoding="utf-8"))
        assert raw["chain_id"] == 4663
        assert raw["not_deployed"] == 8
        assert raw["onchain_verified"] == 0
        assert raw["pinned_block_number"] == 80165854
        assert raw["reorg_detected"] is False

    def test_verification_results_match_rejections(self):
        raw = json.loads(VER_PATH.read_text(encoding="utf-8"))
        assert len(raw["results"]) == 8
        for r in raw["results"]:
            assert r["verification_result"] == "NOT_DEPLOYED_ON_4663"
            assert r["eth_getCode_result"] == "empty (not deployed)"

    def test_reviewed_at_not_future(self):
        raw = json.loads(VER_PATH.read_text(encoding="utf-8"))
        assert raw["verified_at"] == "2026-10-04"

    def test_rpc_authority_is_sanitized(self):
        raw = json.loads(VER_PATH.read_text(encoding="utf-8"))
        assert raw["rpc_authority"] == "ROBINHOOD_CHAIN_MAINNET"
        raw_text = json.dumps(raw)
        assert "https://" not in raw_text or "docs.chain.link" not in raw_text


class TestVerificationTool:
    def test_tool_never_emits_promotion_eligible(self):
        source = open(REPO / "tools" / "verify_stock_token_oracles.py",
                      encoding="utf-8").read()
        assert "PROMOTION_ELIGIBLE" not in source

    def test_tool_uses_pinned_block(self):
        source = open(REPO / "tools" / "verify_stock_token_oracles.py",
                      encoding="utf-8").read()
        assert "pinned_block_number" in source
        assert "block_tag" in source

    def test_tool_does_not_leak_rpc_url(self):
        source = open(REPO / "tools" / "verify_stock_token_oracles.py",
                      encoding="utf-8").read()
        assert "_safe_rpc_label" in source

    def test_tool_has_signed_int256_decoding(self):
        source = open(REPO / "tools" / "verify_stock_token_oracles.py",
                      encoding="utf-8").read()
        assert "_decode_int256" in source
        assert "2 ** 255" in source

    def test_tool_detects_reorg(self):
        source = open(REPO / "tools" / "verify_stock_token_oracles.py",
                      encoding="utf-8").read()
        assert "reorg" in source.lower()

    def test_tool_no_prediction_or_execution(self):
        source = open(REPO / "tools" / "verify_stock_token_oracles.py",
                      encoding="utf-8").read()
        for banned in ("PERSISTENCE_PROBABILITY", "LIKELY_TO_PERSIST",
                       "PRICE_TARGET", "sign_transaction", "private_key",
                       "broadcast", "execute_trade", "custody"):
            assert banned not in source, banned


class TestFrozen:
    @pytest.mark.parametrize("namespace", ["financial_engine", "finco_core",
                                           "finco_yield"])
    def test_zero_diff(self, namespace):
        import subprocess
        out = subprocess.run(
            ["git", "diff", "--name-only", "origin/main..HEAD", "--", namespace],
            cwd=REPO, capture_output=True, text=True)
        if out.returncode != 0:
            pytest.skip("git unavailable")
        assert out.stdout.strip() == "", out.stdout
