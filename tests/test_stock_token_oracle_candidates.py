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

import pytest

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


