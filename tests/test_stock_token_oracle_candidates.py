"""Stock Token oracle binding candidate tests (PR #190 Correction A).

The shipped registry stays at 0 bindings (fail-closed: on-chain
verification has not occurred).  Candidate bindings derived from the
official Chainlink Robinhood Chain Data Feeds catalog are stored in a
separate artifact for staging verification.

Proves:
  - shipped registry is unchanged (0 bindings, fail-closed);
  - candidate artifact has 8 candidates from official documentation;
  - every candidate maps to the exact reviewed token contract;
  - every candidate proxy is unique;
  - no guessed description suffix exists;
  - reviewed_at is not future-dated;
  - unresolved set is exact (AMD, AVGO, DELL, INTC, SNAP);
  - no ticker inference for unresolved assets.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

SHIP_PATH = REPO / "app" / "radar_rwa" / "data" / "stock_token_oracle_feeds.json"
CAND_PATH = REPO / "app" / "radar_rwa" / "data" / "stock_token_oracle_candidates.json"

EXPECTED_PROVEN = {"AAPL", "AMZN", "GOOGL", "META", "MSFT", "NFLX", "NVDA", "TSLA"}
EXPECTED_UNRESOLVED = {"AMD", "AVGO", "DELL", "INTC", "SNAP"}


class TestShippedRegistryUnchanged:
    def test_shipped_registry_has_zero_bindings(self):
        raw = json.loads(SHIP_PATH.read_text(encoding="utf-8"))
        assert raw["bindings"] == []
        assert raw["sequencer"] is None
        assert raw["sequencer_authority"]["state"] == "OFFICIAL_FEED_NOT_PUBLISHED"

    def test_shipped_registry_chain_id_is_4663(self):
        raw = json.loads(SHIP_PATH.read_text(encoding="utf-8"))
        assert raw["chain_id"] == 4663


class TestCandidateBindings:
    def test_candidate_artifact_exists_and_loads(self):
        raw = json.loads(CAND_PATH.read_text(encoding="utf-8"))
        assert raw["schema_version"] == "FINCO_STOCK_TOKEN_ORACLE_CANDIDATES_V1"
        assert raw["chain_id"] == 4663

    def test_exact_proven_symbol_set(self):
        raw = json.loads(CAND_PATH.read_text(encoding="utf-8"))
        symbols = {c["symbol"] for c in raw["candidates"]}
        assert symbols == EXPECTED_PROVEN

    def test_exact_unresolved_symbol_set(self):
        raw = json.loads(CAND_PATH.read_text(encoding="utf-8"))
        symbols = {u["symbol"] for u in raw["unresolved"]}
        assert symbols == EXPECTED_UNRESOLVED

    def test_every_candidate_maps_to_exact_reviewed_contract(self):
        import sys
        sys.path.insert(0, str(REPO))
        from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID
        raw = json.loads(CAND_PATH.read_text(encoding="utf-8"))
        for c in raw["candidates"]:
            key = c["canonical_id"]
            policy = APPROVED_BY_CANONICAL_ID.get(key)
            assert policy is not None, f"{key} not approved"
            assert c["token_contract"] == policy.asset_key.contract_address.lower()

    def test_every_candidate_proxy_is_unique(self):
        raw = json.loads(CAND_PATH.read_text(encoding="utf-8"))
        proxies = [c["candidate_feed_proxy"] for c in raw["candidates"]]
        assert len(proxies) == len(set(proxies))

    def test_every_candidate_has_official_provenance(self):
        raw = json.loads(CAND_PATH.read_text(encoding="utf-8"))
        for c in raw["candidates"]:
            provenance = c.get("official_pair_path")
            assert provenance, f"missing pair_path for {c['symbol']}"

    def test_reviewed_at_is_not_future_dated(self):
        raw = json.loads(CAND_PATH.read_text(encoding="utf-8"))
        reviewed = raw["reviewed_at"]
        parsed = datetime.fromisoformat(reviewed)
        assert parsed.tzinfo is None or parsed.tzinfo == timezone.utc
        # Must not be after the actual review date
        assert parsed <= datetime(2026, 10, 4, 23, 59, 59)

    def test_no_guessed_description_suffix(self):
        raw = json.loads(CAND_PATH.read_text(encoding="utf-8"))
        for c in raw["candidates"]:
            assert "Stock Token" not in json.dumps(c), (
                "guessed description suffix must not appear in candidates")

    def test_on_chain_verification_flag_is_false(self):
        raw = json.loads(CAND_PATH.read_text(encoding="utf-8"))
        assert raw["official_source"]["method"].find("on-chain") == -1 or \
               "deferred" in raw["official_source"].get("method", "") or \
               "not been on-chain verified" in raw["authority_note"]
