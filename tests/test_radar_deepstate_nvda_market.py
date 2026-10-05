"""Deepstate NVDA/USDG market source — deterministic fixture + semantic tests.

Fixture = the REAL proven historical execution captured on-chain:
    tx 0x047b34ce…54e · block 74416355 · logIndex 4 · Router 0x6cf19308…B96
    AskMatched · bookId 0xdf941c235503a5d2e67aee5dea00f2965f99421c0d034bd77f924c05c66bf399
    node 0x2abbd1f1…: tick 716952049 · qty 1033735644 USDG raw · corr 1 · nonce 0xfffb9a27
    gross NVDA 4597241934232839072 raw · gross USDG 1033735644 raw · 224.859961426525136 USDG/NVDA
"""
from __future__ import annotations

import json
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
    price_factor_at_tick,
    quote_at_factor,
)

BLOCK_TIME = datetime(2026, 9, 28, 1, 49, 33, tzinfo=timezone.utc)
COLLECTED = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
FIXTURE_LOG = {
    "address": "0x6cf19308C22FC82ea620Fa0B3E94948d20f27B96",
    "topics": ["0xf75162201654e78313e5b7d92f42188c6ef4e53683c3c1c848103550f68016d2"],
    "data": ("0xdf941c235503a5d2e67aee5dea00f2965f99421c0d034bd77f924c05c66bf399"
             "2abbd1f1000000000000000000000000000000003d9d8ddc00000001fffb9a27"),
    "blockNumber": "0x46f80e3",
    "transactionHash": "0x047b34ce1eeed883dda333cc95b63f5acce671b2f8572425834900a4d74fa54e",
    "blockHash": "0x8bcdd0ee87e940873f23a6c0291f550b6246da67cee82d1b7980b1579e98e447",
    "logIndex": "0x4",
}


def _decoded():
    return decode_match_log(FIXTURE_LOG)


def _observations():
    obs = dsl.match_to_observations(_decoded(), collected_at=COLLECTED,
                                    block_timestamp=int(BLOCK_TIME.timestamp()))
    assert len(obs) == 1
    return obs[0]


def _node(tick, qty, corr, nonce=0):
    return decode_resting_node((tick << 224) | (qty << 64) | (corr << 32) | nonce)


def _batch_log(event_topic, node_ints):
    book = DEEPSTATE_BOOK_ID[2:].lower()
    data = book + hex(0x40)[2:].rjust(64, "0") + hex(len(node_ints))[2:].rjust(64, "0")
    for n in node_ints:
        data += hex(n)[2:].rjust(64, "0")
    return {"address": DEEPSTATE_ROUTER, "topics": [event_topic], "data": "0x" + data,
            "blockNumber": "0x46f80e3", "transactionHash": FIXTURE_LOG["transactionHash"],
            "blockHash": FIXTURE_LOG["blockHash"], "logIndex": "0x9"}


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
    assert DEEPSTATE_POOL_ID.lower() == "0x42819cadfbb25aab80543236e280fba4e61aa61e0b5b777541de54ae69da35e4"


# ── event topic verification ─────────────────────────────────────────────────

def test_ask_matched_topic0_keccak_verified():
    assert ask_matched_topic0() == "0xf75162201654e78313e5b7d92f42188c6ef4e53683c3c1c848103550f68016d2"


def test_bid_matched_topic0_keccak_verified():
    assert bid_matched_topic0() == "0x45d797337480d9dbb22bbc1915cf652d85208c1f85e844ed969b7e79c555cf32"


# ── node decode ──────────────────────────────────────────────────────────────

def test_fixture_node_decode_exact_fields():
    node = decode_resting_node("0x2abbd1f1000000000000000000000000000000003d9d8ddc00000001fffb9a27")
    assert node.tick == 716952049
    assert node.quantity == 1033735644
    assert node.correction == 1
    assert node.nonce == 0xFFFB9A27


def test_malformed_node_rejected():
    with pytest.raises(ValueError):
        decode_resting_node("0xzz")


# ── A: exact TickMath32 integer semantics ────────────────────────────────────

def test_tick_math32_tick_zero_represents_one_to_one():
    """Pinned: tick 0 → factor 2^128+1 @ shift 128; floor quote == quantity."""
    factor, shift = price_factor_at_tick(0)
    assert shift == 128
    assert factor == 2**128 + 1
    assert quote_at_factor(factor, shift, 1033735644, round_up=False) == 1033735644
    # round_up carries the pinned factor imprecision: (q*(2^128+1)) >> 128 == q,
    # remainder q != 0 → +1 (contract integer semantics, kept verbatim)
    assert quote_at_factor(factor, shift, 1033735644, round_up=True) == 1033735645


def test_tick_math32_shift_replicates_pinned_algorithm():
    for tick in (-22369621, 716952049, -1, 1, 0, -96 << 25):
        scaled = tick * 3
        ie = scaled >> 26
        frac = scaled - (ie << 26)
        if frac > 0x2000000:
            ie += 1
        factor, shift = price_factor_at_tick(tick)
        assert shift == 128 - ie
        assert factor > 0


def test_tick_math32_negative_tick_price_below_one():
    factor, shift = price_factor_at_tick(-22369621)
    assert Decimal(factor) / Decimal(2**shift) < 1


def test_tick_math32_positive_tick_price_above_one():
    factor, shift = price_factor_at_tick(716952049)
    assert Decimal(factor) / Decimal(2**shift) > 10**9


def test_quote_round_down_matches_shift_truncation():
    factor, shift = price_factor_at_tick(716952049)
    product = 1033735644 * factor
    assert quote_at_factor(factor, shift, 1033735644, round_up=False) == product >> shift


def test_quote_round_up_on_remainder_boundary():
    factor, shift = price_factor_at_tick(716952049)
    product = 1033735644 * factor
    if product & ((1 << shift) - 1):
        assert quote_at_factor(factor, shift, 1033735644, round_up=True) == \
               (product >> shift) + 1


# ── correction semantics (Ask floor − delta, Bid ceil + delta) ───────────────

def test_ask_match_correction_one_is_plain_floor():
    assert dsl.match_gross_base_raw(_node(716952049, 1033735644, 1), "AskMatched") == 4597241934232839072


def test_ask_match_correction_zero_adds_one():
    plain = dsl.match_gross_base_raw(_node(716952049, 1033735644, 1), "AskMatched")
    assert dsl.match_gross_base_raw(_node(716952049, 1033735644, 0), "AskMatched") == plain + 1


def test_ask_match_correction_gt_one_subtracts_delta():
    plain = dsl.match_gross_base_raw(_node(716952049, 1033735644, 1), "AskMatched")
    assert dsl.match_gross_base_raw(_node(716952049, 1033735644, 5), "AskMatched") == plain - 4


def test_bid_match_round_up_plus_delta():
    node = _node(716952049, 1033735644, 1)
    factor, shift = price_factor_at_tick(node.tick)
    assert dsl.match_gross_base_raw(node, "BidMatched") == \
           quote_at_factor(factor, shift, node.quantity, round_up=True)


def test_bid_match_correction_zero_subtracts_one():
    plain = dsl.match_gross_base_raw(_node(716952049, 1033735644, 1), "BidMatched")
    assert dsl.match_gross_base_raw(_node(716952049, 1033735644, 0), "BidMatched") == plain - 1


def test_bid_match_correction_gt_one_adds_delta():
    plain = dsl.match_gross_base_raw(_node(716952049, 1033735644, 1), "BidMatched")
    assert dsl.match_gross_base_raw(_node(716952049, 1033735644, 3), "BidMatched") == plain + 2


# ── canonical fixture: decode + mapping ──────────────────────────────────────

def test_canonical_fixture_accepted_with_identity_retained():
    decoded = _decoded()
    assert decoded["event_type"] == "AskMatched"
    assert decoded["log_index"] == 4
    assert decoded["block_number"] == 74416355
    assert decoded["transaction_hash"].startswith("0x047b34ce1eeed883")
    assert decoded["block_hash"] == FIXTURE_LOG["blockHash"]
    assert len(decoded["matches"]) == 1
    assert decoded["matches"][0]["match_index"] == 0


def test_historical_fixture_exact_reconstruction():
    observation = _observations()
    assert abs(Decimal(observation.price) - Decimal("224.859961426525136")) < Decimal("1e-9")
    payload = observation.payload
    assert payload["gross_base_amount_nvda"] == "4597241934232839072"
    assert payload["gross_quote_amount_usdg"] == 1033735644


def test_observation_mapping_retains_chain_identity():
    observation = _observations()
    assert observation.venue_id == "DEEPSTATE"
    assert observation.canonical_asset_id == "NVDA"
    assert observation.instrument_id == DEEPSTATE_POOL_ID
    assert observation.payload["chain_id"] == 4663
    assert observation.payload["transaction_hash"] == FIXTURE_LOG["transactionHash"]
    assert observation.payload["log_index"] == 4
    assert observation.payload["block_hash"] == FIXTURE_LOG["blockHash"]
    assert observation.ts == BLOCK_TIME.isoformat()


def test_protocol_fee_excluded_from_market_price():
    observation = _observations()
    assert abs(Decimal(observation.price) - Decimal("224.859961426525136")) < Decimal("1e-9")


# ── reject paths (fail closed) ───────────────────────────────────────────────

def test_wrong_book_rejected():
    log = dict(FIXTURE_LOG)
    log["data"] = "0x" + "11" * 32 + FIXTURE_LOG["data"][2:][64:]
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
    log = dict(FIXTURE_LOG)
    log["topics"] = ["0x" + "ab" * 32]
    assert decode_match_log(log) is None


def test_no_ticker_or_fuzzy_identity():
    log = dict(FIXTURE_LOG)
    log["data"] = "0x" + b"NVDA".hex().ljust(64, "0") + FIXTURE_LOG["data"][2:][64:]
    assert decode_match_log(log) is None


# ── B: batch + subtree event family ─────────────────────────────────────────

def test_asks_matched_multi_node_decode_in_priority_order():
    asks_topic = dsl.topic0("AsksMatched(bytes32,bytes32[])")
    decoded = decode_match_log(_batch_log(asks_topic, [
        (716952049 << 224) | (1033735644 << 64) | (1 << 32),
        (716000000 << 224) | (200 << 64) | (1 << 32)]))
    assert decoded is not None and decoded["event_type"] == "AsksMatched"
    assert [m["match_index"] for m in decoded["matches"]] == [0, 1]
    assert decoded["matches"][0]["node"].tick == 716952049
    assert decoded["matches"][1]["node"].tick == 716000000


def test_bids_matched_multi_node_decode():
    bids_topic = dsl.topic0("BidsMatched(bytes32,bytes32[])")
    decoded = decode_match_log(_batch_log(bids_topic, [
        (716952049 << 224) | (500 << 64) | (2 << 32),
        (716000000 << 224) | (250 << 64) | (2 << 32)]))
    assert decoded is not None and decoded["event_type"] == "BidsMatched"
    assert len(decoded["matches"]) == 2


def test_subtree_decode_uses_emitted_aggregates():
    ask_sub = dsl.topic0("AskSubtreeMatched(bytes32,bytes32,uint160,uint256)")
    data = (DEEPSTATE_BOOK_ID[2:].lower()
            + "ab" * 32
            + hex(4597241934232839072)[2:].rjust(64, "0")   # uint160 word
            + hex(1033735644)[2:].rjust(64, "0"))           # uint256 word
    decoded = decode_match_log({"address": DEEPSTATE_ROUTER, "topics": [ask_sub],
                                "data": "0x" + data, "blockNumber": "0x46f80e3",
                                "transactionHash": FIXTURE_LOG["transactionHash"],
                                "blockHash": FIXTURE_LOG["blockHash"], "logIndex": "0x6"})
    assert decoded is not None
    m = decoded["matches"][0]
    assert m["quantity_base_raw"] == 4597241934232839072
    assert m["quote_amount_quote_raw"] == 1033735644


def test_batch_sub_event_dedupe_identity_distinct(tmp_path):
    asks_topic = dsl.topic0("AsksMatched(bytes32,bytes32[])")
    decoded = decode_match_log(_batch_log(asks_topic, [
        (716952049 << 224) | (100 << 64) | (1 << 32),
        (716952049 << 224) | (200 << 64) | (1 << 32)]))
    from finco_radar.venues.store import VenueMarketStore
    store = VenueMarketStore(path=tmp_path / "v.db")
    obs = dsl.match_to_observations(decoded, collected_at=COLLECTED,
                                    block_timestamp=int(BLOCK_TIME.timestamp()))
    assert len(obs) == 2
    assert obs[0].payload["match_index"] != obs[1].payload["match_index"]
    assert obs[0].compute_digest() != obs[1].compute_digest()
    _, created0 = store.append_observation(obs[0])
    _, created1 = store.append_observation(obs[1])
    assert created0 and created1  # distinct batch nodes append


# ── freshness fail-closed (F) ────────────────────────────────────────────────

def test_no_arbitrary_freshness_ceiling_claimed():
    from finco_radar.venues.observations import FreshnessState
    observation = _observations()
    assert observation.freshness_state == FreshnessState.UNAVAILABLE
    assert observation.payload["deepstate_freshness_policy"] == "NOT_YET_APPROVED"


# ── E: USDG/USD normalization ────────────────────────────────────────────────

def test_usdg_normalization_and_effective_min_timestamp():
    deep = BLOCK_TIME
    usdg_obs = datetime(2026, 10, 5, 9, 0, 0, tzinfo=timezone.utc)
    normalized, effective = normalize_to_usd(
        Decimal("224.859961426525136"), deep, Decimal("1.0"), usdg_obs)
    assert normalized == Decimal("224.859961426525136")
    assert effective == deep


def test_fresh_usdg_cannot_refresh_old_execution():
    deep = BLOCK_TIME
    usdg_obs = datetime(2026, 10, 5, 9, 0, 0, tzinfo=timezone.utc)
    _, effective = normalize_to_usd(Decimal("225"), deep, Decimal("1.0"), usdg_obs)
    assert effective == deep


def test_missing_usdg_authority_is_not_zero():
    observation = _observations()
    assert "normalized_usd_price" not in observation.payload
    assert Decimal(observation.price) != 0


# ── C/D: collector bootstrap / head / lag / reorg ───────────────────────────

def _collect_env(monkeypatch, tmp_path, extra=None):
    import app.radar_rwa.deepstate_collect as dc
    monkeypatch.setenv("FINCO_DEEPSTATE_COLLECTOR_ENABLED", "1")
    monkeypatch.setenv("ROBINHOOD_RPC_URL", "http://localhost:1")
    monkeypatch.setenv("FINCO_VENUE_DB_PATH", str(tmp_path / "v.db"))
    monkeypatch.setattr(dc, "ensure_chain", lambda *a, **k: True)
    return dc


def test_empty_store_bootstrap_requires_explicit_start_block(monkeypatch, tmp_path, capsys):
    dc = _collect_env(monkeypatch, tmp_path)
    monkeypatch.delenv("FINCO_DEEPSTATE_START_BLOCK", raising=False)
    rc = dc.main([])
    assert rc == 4  # BOOTSTRAP_REQUIRED — no silent genesis scan
    assert "BOOTSTRAP_REQUIRED" in capsys.readouterr().out


def test_lag_truthfully_reported_when_budget_exhausted(monkeypatch, tmp_path, capsys):
    dc = _collect_env(monkeypatch, tmp_path)
    from finco_radar.venues.store import VenueMarketStore
    db = str(tmp_path / "v.db")
    store = VenueMarketStore(path=db)
    latest = 80000000
    conn = store._connect()
    conn.execute(
        "INSERT INTO market_observations (digest, ts, collected_at, canonical_asset_id,"
        " venue_id, instrument_id, instrument_type, price, source, freshness_state,"
        " observation_status, payload) VALUES ('x', NULL, ?, 'NVDA', 'DEEPSTATE', 'p',"
        " 't', '1', 's', 'AVAILABLE', 'OK', ?)",
        ("2026-10-04T00:00:00+00:00", json.dumps({"block_number": latest})))
    conn.commit(); conn.close()
    monkeypatch.setenv("FINCO_DEEPSTATE_MAX_BLOCKS_PER_REQ", "1000")
    monkeypatch.setenv("FINCO_DEEPSTATE_MAX_REQUESTS", "2")
    monkeypatch.setattr(dc, "eth_block_number", lambda *a, **k: latest + 99999)
    monkeypatch.setattr(dc, "fetch_match_logs", lambda *a, **k: [])
    monkeypatch.setattr(dc, "_canonical_block", lambda *a, **k: (True, 1780000000))
    rc = dc.main([])
    assert rc == 0
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report["lag_blocks_remaining"] > 0
    assert report["lag_truthfully_reported"] is True


def test_catchup_reaches_current_head(monkeypatch, tmp_path, capsys):
    dc = _collect_env(monkeypatch, tmp_path)
    from finco_radar.venues.store import VenueMarketStore
    db = str(tmp_path / "v.db")
    store = VenueMarketStore(path=db)
    latest = 80000000
    conn = store._connect()
    conn.execute(
        "INSERT INTO market_observations (digest, ts, collected_at, canonical_asset_id,"
        " venue_id, instrument_id, instrument_type, price, source, freshness_state,"
        " observation_status, payload) VALUES ('x', NULL, ?, 'NVDA', 'DEEPSTATE', 'p',"
        " 't', '1', 's', 'AVAILABLE', 'OK', ?)",
        ("2026-10-04T00:00:00+00:00", json.dumps({"block_number": latest})))
    conn.commit(); conn.close()
    monkeypatch.setattr(dc, "eth_block_number", lambda *a, **k: latest + 1500)
    monkeypatch.setattr(dc, "fetch_match_logs", lambda *a, **k: [])
    monkeypatch.setattr(dc, "_canonical_block", lambda *a, **k: (True, 1780000000))
    rc = dc.main([])
    assert rc == 0
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report["to_block"] == latest + 1500
    assert report["lag_blocks_remaining"] == 0


def test_reorged_evidence_not_persisted(monkeypatch, tmp_path):
    dc = _collect_env(monkeypatch, tmp_path)
    monkeypatch.delenv("FINCO_DEEPSTATE_START_BLOCK", raising=False)
    monkeypatch.setenv("FINCO_DEEPSTATE_START_BLOCK", "74416350")
    monkeypatch.setattr(dc, "eth_block_number", lambda *a, **k: 74416360)
    monkeypatch.setattr(dc, "fetch_match_logs", lambda *a, **k: [FIXTURE_LOG])
    monkeypatch.setattr(dc, "_canonical_block", lambda *a, **k: (False, None))
    rc = dc.main([])
    assert rc == 6  # fail closed
    from finco_radar.venues.store import VenueMarketStore
    store = VenueMarketStore(path=str(tmp_path / "v.db"))
    conn = store._connect()
    assert conn.execute("SELECT count(*) FROM market_observations").fetchone()[0] == 0
    conn.close()
