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


class TestVerificationToolStaticGuards:
    """Static guards only; the verifier's behaviour is exercised in test_verify_stock_token_oracles_behavior.py."""

    def test_tool_no_prediction_or_execution(self):
        source = open(REPO / "tools" / "verify_stock_token_oracles.py", encoding="utf-8").read()
        for banned in ("PERSISTENCE_PROBABILITY", "LIKELY_TO_PERSIST", "PRICE_TARGET", "sign_transaction",
                       "private_key", "broadcast", "execute_trade", "custody"):
            assert banned not in source, banned


class TestCorrectedCandidateMetadata:
    def test_taxonomy_is_exactly_0_proven_0_active_8_rejected_5_unresolved(self):
        raw = json.loads(CAND_PATH.read_text(encoding="utf-8"))
        assert raw["active_candidates"] == []
        assert {r["symbol"] for r in raw["rejected_candidates"]} == EXPECTED_REJECTED
        assert {u["symbol"] for u in raw["unresolved"]} == EXPECTED_UNRESOLVED
        assert raw["taxonomy_summary"] == {"source_proven": 0, "active_candidates": 0, "rejected": 8, "unresolved": 5}
        assert json.loads(SHIP_PATH.read_text(encoding="utf-8"))["bindings"] == []

    def test_authority_note_is_truthful_and_not_stale(self):
        note = json.loads(CAND_PATH.read_text(encoding="utf-8"))["authority_note"]
        for stale in ("have NOT been on-chain verified", "MUST pass the staging verification runbook",
                      "These candidates have NOT"):
            assert stale not in note
        for fact in ("0 SOURCE_PROVEN", "0 active candidates", "8 rejected", "NOT_DEPLOYED_ON_4663", "80165854",
                     "retained for audit only", "chain-4663-specific"):
            assert fact in note

    def test_reviewer_text_no_longer_claims_verification_is_deferred(self):
        reviewer = json.loads(CAND_PATH.read_text(encoding="utf-8"))["reviewer"]
        assert "deferred" not in reviewer.lower()
        assert "completed" in reviewer and "NOT_DEPLOYED_ON_4663" in reviewer

    def test_rejection_does_not_overclaim_which_other_network_owns_the_address(self):
        raw = json.loads(CAND_PATH.read_text(encoding="utf-8"))
        text = json.dumps(raw).lower()
        assert "likely belongs" not in text and "likely belong" not in text
        for row in raw["rejected_candidates"]:
            assert row["verification_result"] == "NOT_DEPLOYED_ON_4663"            # the only canonical typed reason
            assert "does not establish which other network" in row["reason"]
            assert "not deployed on chain 4663" in row["reason"].lower()

    def test_historical_note_does_not_overclaim_either(self):
        note = json.loads(VER_PATH.read_text(encoding="utf-8"))["authority_note"].lower()
        assert "likely belong" not in note and "does not establish which other network" in note


class TestHistoricalEvidencePreserved:
    HISTORICAL_PROXIES = {
        "AAPL": "0x7E7B45b08F68EC69A99AAb12e42FcCB078e10094", "AMZN": "0xf9184b8E5da48C19fA4E06f83f77742e748cca96",
        "GOOGL": "0x1b32682C033b2DD7EFdC615FA82d353e254F39b5", "META": "0xfc76E9445952A3C31369dFd26edfdfb9713DF5Bb",
        "MSFT": "0xC43081d9EA6d1c53f1F0e525504d47Dd60de12da", "TSLA": "0x567E67f456c7453c583B6eFA6F18452cDee1F5a8",
    }

    def test_eight_real_rows_are_preserved_unchanged(self):
        raw = json.loads(VER_PATH.read_text(encoding="utf-8"))
        assert {r["symbol"] for r in raw["results"]} == EXPECTED_REJECTED and len(raw["results"]) == 8
        assert raw["pinned_block_number"] == 80165854 and raw["chain_id"] == 4663
        assert raw["not_deployed"] == 8 and raw["onchain_verified"] == 0 and raw["reorg_detected"] is False
        by_symbol = {r["symbol"]: r for r in raw["results"]}
        for symbol, proxy in self.HISTORICAL_PROXIES.items():
            assert by_symbol[symbol]["candidate_proxy"] == proxy
            assert by_symbol[symbol]["verification_block"] == 80165854
            assert by_symbol[symbol]["eth_getCode_result"] == "empty (not deployed)"

    def test_missing_audit_fields_are_declared_not_fabricated(self):
        raw = json.loads(VER_PATH.read_text(encoding="utf-8"))
        completeness = raw["audit_completeness"]
        assert completeness["pinned_block_hash"] == "NOT_RECORDED_BY_ORIGINAL_RUN"
        assert completeness["pinned_block_timestamp"] == "NOT_RECORDED_BY_ORIGINAL_RUN"
        assert "pinned_block_hash" not in raw and "pinned_block_timestamp" not in raw      # nothing invented

    def test_rejected_rows_match_the_candidate_artifact(self):
        ver = {r["symbol"]: r for r in json.loads(VER_PATH.read_text(encoding="utf-8"))["results"]}
        cand = {r["symbol"]: r for r in json.loads(CAND_PATH.read_text(encoding="utf-8"))["rejected_candidates"]}
        for symbol, row in cand.items():
            assert ver[symbol]["candidate_proxy"] == row["rejected_proxy"]
            assert ver[symbol]["canonical_id"] == row["canonical_id"]


class TestFrozen:
    @pytest.mark.parametrize("namespace", ["financial_engine", "finco_core",
                                           "finco_yield"])
    def test_zero_diff(self, namespace):
        # Branch-owned changes only (merge-base boundary). Exact released Model V2
        # engine authorities (pinned to their reviewed content) are exempt; every
        # other path in the namespace stays frozen.
        from finance_integrity_governance import changed_paths_vs_main
        from finance_integrity_governance import approved_frozen_path
        changed = [p for p in changed_paths_vs_main()
                   if p.startswith(namespace + "/") and not approved_frozen_path(p)]
        assert changed == [], changed


class TestShippedRegistryFileIsUntouchedByCorrectionB:
    def test_registry_feeds_file_has_no_diff_against_main(self):
        import subprocess
        out = subprocess.run(["git", "diff", "--name-only", "origin/main..HEAD", "--",
                              "app/radar_rwa/data/stock_token_oracle_feeds.json"], cwd=REPO, capture_output=True, text=True)
        if out.returncode != 0:
            pytest.skip("git unavailable")
        assert out.stdout.strip() == "", out.stdout
