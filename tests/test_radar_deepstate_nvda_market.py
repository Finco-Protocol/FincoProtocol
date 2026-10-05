"""Deepstate NVDA/USDG market source — deterministic fixture tests.

The fixture is the REAL proven historical execution captured on-chain
(staging RPC, 2026-10-05 acceptance):

    transaction 0x047b34ce1eeed883dda333cc95b63f5acce671b2f8572425834900a4d74fa54e
    block 74416355 (2026-09-28T01:49:33Z) · logIndex 4
    Router 0x6cf19308C22FC82ea620Fa0B3E94948d20f27B96
    AskMatched(bytes32 bookId, bytes32 restingNode)
    bookId  0xdf941c235503a5d2e67aee5dea00f2965f99421c0d034bd77f924c05c66bf399
    node    0x2abbd1f1000000000000000000000000000000003d9d8ddc00000001fffb9a27
      tick 716952049 · quantity 1033735644 USDG raw · correction 1 · nonce 0xfffb9a27
    canonical gross: NVDA 4597241934232839072 raw (4.597241934232839072)
                     USDG 1033735644 raw (1033.735644)
                     execution price 224.859961426525136 USDG/NVDA
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from finco_radar.venues import deepstate_live as dsl
from finco_radar.venues.deepstate_live import (
    DEEPSTATE_BOOK_ID,
    DEEPSTATE_CHAIN_ID,
    DEEPSTATE_NVDA,
    DEEPSTATE_POOL_ID,
    DEEPSTATE_ROUTER,
    DEEPSTATE_USDG,
    NVDA_DECIMALS,
    USDG_DECIMALS,
    ask_matched_topic0,
    bid_matched_topic0,
    decode_match_log,
    decode_resting_node,
    normalize_to_usd,
    tick_price,
)

BLOCK_TIME = datetime(2026, 9, 28, 1, 49, 33, tzinfo=timezone.utc)
FIXTURE_LOG = {
    "address": "0x6cf19308C22FC82ea620Fa0B3E94948d20f27B96",
    "topics": ["0xf75162201654e78313e5b7d92f42188c6ef4e53683c3c1c848103550f68016d2"],
    "data": ("0xdf941c235503a5d2e67aee5dea00f2965f99421c0d034bd77f924c05c66bf399"
             "2abbd1f1000000000000000000000000000000003d9d8ddc00000001fffb9a27"),
    "blockNumber": "0x46f80e3",
    "transactionHash": ("0x047b34ce1eeed883dda333cc95b63f5acce671b2f8572425"
                        "834900a4d74fa54e"),
    "blockHash": "0x8bcdd0ee87e940873f23a6c0291f550b6246da67cee82d1b7980b1579e98e447",
    "logIndex": "0x4",
}


def _decoded():
    return decode_match_log(FIXTURE_LOG)


# ── canonical identity ───────────────────────────────────────────────────────

def test_exact_chain_id_is_robinhood_chain():
    assert DEEPSTATE_CHAIN_ID == 4663


def test_exact_router_address():
    assert DEEPSTATE_ROUTER.lower() == "0x6cf19308c22fc82ea620fa0b3e94948d20f27b96"


def test_exact_nvda_and_usdg_and_decimals():
    assert DEEPSTATE_NVDA.lower() == "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec"
    assert DEEPSTATE_USDG.lower() == "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
    assert NVDA_DECIMALS == 18
    assert USDG_DECIMALS == 6


def test_exact_pool_id():
    assert DEEPSTATE_POOL_ID.lower() == ("0x42819cadfbb25aab80543236e280fba4e61"
                                         "aa61e0b5b777541de54ae69da35e4")


# ── canonical event topic verification ───────────────────────────────────────

def test_ask_matched_topic0_keccak_verified():
    assert ask_matched_topic0() == ("0xf75162201654e78313e5b7d92f42188c6ef4e536"
                                    "83c3c1c848103550f68016d2")


def test_bid_matched_topic0_keccak_verified():
    assert bid_matched_topic0() == ("0x45d797337480d9dbb22bbc1915cf652d85208c1f"
                                    "85e844ed969b7e79c555cf32")


# ── node decode ──────────────────────────────────────────────────────────────

def test_fixture_node_decode_exact_fields():
    node = decode_resting_node("0x2abbd1f100000000000000000000000000000000"
                               "3d9d8ddc00000001fffb9a27")
    assert node.tick == 716952049
    assert node.quantity == 1033735644
    assert node.correction == 1
    assert node.nonce == 0xFFFB9A27


def test_malformed_node_rejected():
    with pytest.raises(ValueError):
        decode_resting_node("0xzz")


# ── gross reconstruction ─────────────────────────────────────────────────────

def test_canonical_gross_nvda_reconstruction():
    node = decode_resting_node(FIXTURE_LOG["data"][2:][64:])
    gross = int(Decimal(node.quantity) * tick_price(node.tick))
    assert gross == 4597241934232839072


def test_canonical_gross_usdg_reconstruction():
    node = decode_resting_node(FIXTURE_LOG["data"][2:][64:])
    assert node.quantity == 1033735644  # USDG raw (6 decimals)


def test_execution_price_matches_diagnostic():
    node = decode_resting_node(FIXTURE_LOG["data"][2:][64:])
    price = (Decimal(node.quantity) * Decimal(10**12)
             / (Decimal(node.quantity) * tick_price(node.tick)))
    assert price == pytest.approx(Decimal("224.859961426525136"), rel=Decimal("1e-12"))


def test_protocol_fee_excluded_from_market_price():
    """The MARKET observation price is the GROSS execution price; the 0.1%
    protocol fee is a settlement detail and never enters the price."""
    decoded = _decoded()
    observation = dsl.match_to_observation(decoded, collected_at=BLOCK_TIME,
                                           block_timestamp=int(BLOCK_TIME.timestamp()))
    assert Decimal(observation.price) == pytest.approx(
        Decimal("224.859961426525136"), rel=Decimal("1e-12"))


# ── log decode: accept / reject ──────────────────────────────────────────────

def test_canonical_fixture_accepted_with_identity_retained():
    decoded = _decoded()
    assert decoded["event_type"] == "AskMatched"
    assert decoded["log_index"] == 4
    assert decoded["block_number"] == 74416355
    assert decoded["transaction_hash"].startswith("0x047b34ce1eeed883")
    assert decoded["block_hash"] == FIXTURE_LOG["blockHash"]
    assert decoded["book_id"].lower() == DEEPSTATE_BOOK_ID.lower()


def test_observation_mapping_retains_chain_identity():
    observation = dsl.match_to_observation(_decoded(), collected_at=BLOCK_TIME,
                                           block_timestamp=int(BLOCK_TIME.timestamp()))
    assert observation.venue_id == "DEEPSTATE"
    assert observation.canonical_asset_id == "NVDA"
    assert observation.instrument_id == DEEPSTATE_POOL_ID
    assert observation.payload["chain_id"] == 4663
    assert observation.payload["transaction_hash"] == FIXTURE_LOG["transactionHash"]
    assert observation.payload["log_index"] == 4
    assert observation.payload["block_hash"] == FIXTURE_LOG["blockHash"]
    assert observation.ts == BLOCK_TIME.isoformat()


def test_wrong_book_rejected():
    log = dict(FIXTURE_LOG)
    data = "0x" + "11" * 32 + FIXTURE_LOG["data"][2:][64:]
    log["data"] = data
    assert decode_match_log(log) is None


def test_wrong_router_rejected():
    log = dict(FIXTURE_LOG)
    log["address"] = "0x000000000000000000000000000000000000dEaD"
    assert decode_match_log(log) is None


def test_transfer_only_evidence_rejected():
    log = dict(FIXTURE_LOG)
    log["topics"] = ["0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"]
    assert decode_match_log(log) is None


def test_quote_only_evidence_rejected():
    """A foreign single-topic event (e.g. a quote/oracle heartbeat) is not a
    canonical Deepstate match."""
    log = dict(FIXTURE_LOG)
    log["topics"] = ["0x" + "ab" * 32]
    assert decode_match_log(log) is None


def test_batch_match_form_not_decoded_as_single():
    log = dict(FIXTURE_LOG)
    log["topics"] = ["0x" + "32" * 2 + "37fd582c53d9acd9c6fbe490e967407f8745c175"
                     "e4c0d213b752e22d272e90"]
    assert decode_match_log(log) is None


def test_malformed_data_rejected():
    log = dict(FIXTURE_LOG)
    log["data"] = "0x1234"
    assert decode_match_log(log) is None


def test_no_ticker_or_fuzzy_identity():
    """Identity is the exact bookId bytes; a ticker string can never bind."""
    log = dict(FIXTURE_LOG)
    log["data"] = "0x" + b"NVDA".hex().ljust(64, "0") + FIXTURE_LOG["data"][2:][64:]
    assert decode_match_log(log) is None


# ── persistence: dedupe / append-only ────────────────────────────────────────

def test_duplicate_event_dedupes_and_different_log_index_appends(tmp_path):
    from finco_radar.venues.observations import MarketObservation
    from finco_radar.venues.store import VenueMarketStore
    store = VenueMarketStore(path=tmp_path / "venues.db")
    collected = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    first = dsl.match_to_observation(_decoded(), collected_at=collected,
                                     block_timestamp=int(BLOCK_TIME.timestamp()))
    digest, created = store.append_observation(first)
    assert created is True
    second = MarketObservation(
        ts=first.ts, collected_at=first.collected_at,
        canonical_asset_id=first.canonical_asset_id, venue_id=first.venue_id,
        instrument_id=first.instrument_id, instrument_type=first.instrument_type,
        price=first.price, source=first.source,
        freshness_state=first.freshness_state,
        observation_status=first.observation_status, payload=first.payload)
    _, created_again = store.append_observation(second)
    assert created_again is False  # same event -> dedupe
    variant_log = dict(FIXTURE_LOG)
    variant_log["logIndex"] = "0x5"
    variant = decode_match_log(variant_log)
    variant["log_index"] = 5
    variant["transaction_hash"] = "0x" + "ab" * 32
    other = dsl.match_to_observation(variant, collected_at=collected,
                                     block_timestamp=int(BLOCK_TIME.timestamp()))
    _, created_other = store.append_observation(other)
    assert created_other is True  # distinct execution -> append


# ── USD normalization ────────────────────────────────────────────────────────

def test_usdg_normalization_and_effective_min_timestamp():
    deep = datetime(2026, 9, 28, 1, 49, 33, tzinfo=timezone.utc)
    usdg_obs = datetime(2026, 10, 5, 9, 0, 0, tzinfo=timezone.utc)
    normalized, effective = normalize_to_usd(
        Decimal("224.859961426525136"), deep, Decimal("1.0"), usdg_obs)
    assert normalized == Decimal("224.859961426525136")
    assert effective == deep  # min(...) — fresh USDG cannot refresh old execution
