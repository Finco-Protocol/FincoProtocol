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
    """Pinned Solidity: tick 0 -> exactly Q128, not Q128+1."""
    factor, shift = price_factor_at_tick(0)
    assert shift == 128
    assert factor == 2**128
    assert quote_at_factor(factor, shift, 1033735644, round_up=False) == 1033735644
    assert quote_at_factor(factor, shift, 1033735644, round_up=True) == 1033735644


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


def _subtree_log(event_topic, *, usdg_raw=1033735644,
                 nvda_raw=4597241934232839072, log_index="0x6"):
    data = (DEEPSTATE_BOOK_ID[2:].lower()
            + "ab" * 32
            + hex(usdg_raw)[2:].rjust(64, "0")   # token0 quantity = USDG raw
            + hex(nvda_raw)[2:].rjust(64, "0"))  # token1 quoteAmount = NVDA raw
    return {"address": DEEPSTATE_ROUTER, "topics": [event_topic],
            "data": "0x" + data, "blockNumber": "0x46f80e3",
            "transactionHash": FIXTURE_LOG["transactionHash"],
            "blockHash": FIXTURE_LOG["blockHash"], "logIndex": log_index}


def test_ask_subtree_contract_orientation_maps_to_finco_nvda_usdg():
    event = dsl.topic0("AskSubtreeMatched(bytes32,bytes32,uint160,uint256)")
    decoded = decode_match_log(_subtree_log(event))
    assert decoded is not None
    m = decoded["matches"][0]
    assert m["quantity_token0_raw"] == 1033735644
    assert m["quote_amount_token1_raw"] == 4597241934232839072
    observation = dsl.match_to_observations(
        decoded, collected_at=COLLECTED,
        block_timestamp=int(BLOCK_TIME.timestamp()))[0]
    assert observation.payload["gross_base_amount_nvda"] == "4597241934232839072"
    assert observation.payload["gross_quote_amount_usdg"] == 1033735644


def test_bid_subtree_contract_orientation_maps_to_finco_nvda_usdg():
    event = dsl.topic0("BidSubtreeMatched(bytes32,bytes32,uint160,uint256)")
    decoded = decode_match_log(_subtree_log(event, log_index="0x7"))
    assert decoded is not None
    observation = dsl.match_to_observations(
        decoded, collected_at=COLLECTED,
        block_timestamp=int(BLOCK_TIME.timestamp()))[0]
    assert observation.payload["gross_base_amount_nvda"] == "4597241934232839072"
    assert observation.payload["gross_quote_amount_usdg"] == 1033735644


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
    monkeypatch.setenv("FINCO_DEEPSTATE_START_BLOCK", "100")
    monkeypatch.delenv("FINCO_DEEPSTATE_RESCAN_BLOCKS", raising=False)
    monkeypatch.setattr(dc, "ensure_chain", lambda *a, **k: True)
    return dc


def test_empty_store_bootstrap_requires_explicit_start_block(monkeypatch, tmp_path, capsys):
    dc = _collect_env(monkeypatch, tmp_path)
    monkeypatch.delenv("FINCO_DEEPSTATE_START_BLOCK", raising=False)
    rc = dc.main([])
    assert rc == 4  # BOOTSTRAP_REQUIRED — no silent genesis scan
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report["state"] == "BOOTSTRAP_REQUIRED"
    assert report["exit_code"] == 4


def test_lag_truthfully_reported_when_budget_exhausted(monkeypatch, tmp_path, capsys):
    dc = _collect_env(monkeypatch, tmp_path)
    from finco_radar.venues.store import VenueMarketStore
    db = str(tmp_path / "v.db")
    store = VenueMarketStore(path=db)
    latest = 80000000
    dc._advance_checkpoint(store, latest)
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
    dc._advance_checkpoint(store, latest)
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


# ── Correction B: byte/integer conformance + fail-closed runtime ─────────────

def test_tickmath_inverse_uses_max_uint256_semantics():
    assert ((2**256 - 1) // (2**128)) + 1 == 2**128
    assert price_factor_at_tick(0) == (2**128, 128)


@pytest.mark.parametrize("tick,expected_factor", [
    (-49, 340281850264288272068178212455338505136),
    (-50, 340281839720283170798433562459963554929),
    (-47, 340281871352299454760279964182336241080),
])
def test_tickmath_residual_vectors_match_pinned_solidity(tick, expected_factor):
    factor, shift = price_factor_at_tick(tick)
    assert factor == expected_factor
    assert shift == 128


def test_tickmath_all_nibble_tables_include_pinned_default_15():
    expected = [
        0xfffff59a50ce87c017af4391fc7bd1b4,
        0xffff59a53f94ab936ae8cc833ff1a560,
        0xfff59a86a4cb5e55dfd877cc112a9619,
        0xff59db0ae05450ba1ecf379840cb103d,
        0xf5cfa433e653729065e4527c9e33781c,
        0x85aac367cc487b14c5c95b8c2154c1b0,
    ]
    for i, value in enumerate(expected):
        table = getattr(dsl, f"_TICKMATH_FACTOR{i}")
        expected_keys = set(range(16)) if i == 0 else set(range(1, 16))
        assert set(table) == expected_keys
        assert table[15] == value
        if i > 0:
            assert 0 not in table
    assert dsl._TICKMATH_RESIDUAL == {
        1: 0xffffffd3a37a05e383e14c90273c94f5,
        2: 0xffffffa746f41376f74124cd483186d4,
        3: 0xffffff7aea6e28ba5a1e33b2f9234215,
    }


def test_tickmath_fraction_branch_vectors_match_pinned_solidity():
    assert price_factor_at_tick(-12000000) == (
        469228483368501207124397082768245158967, 129)
    assert price_factor_at_tick(-11135801) == (
        240981650533380289779414885556838269951, 128)


def test_quote_boundary_uint160_at_tick_zero_is_exact():
    quantity = (1 << 160) - 1
    factor, shift = price_factor_at_tick(0)
    assert quote_at_factor(factor, shift, quantity, False) == quantity
    assert quote_at_factor(factor, shift, quantity, True) == quantity


def test_fetch_match_logs_requests_all_six_canonical_topics(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return b'{"jsonrpc":"2.0","id":1,"result":[]}'

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode())
        return Response()

    monkeypatch.setattr(dsl.urllib.request, "urlopen", fake_urlopen)
    assert dsl.fetch_match_logs("http://rpc.invalid", 1, 2) == []
    topics = captured["payload"]["params"][0]["topics"][0]
    assert set(topics) == set(dsl.SUPPORTED_MATCH_TOPICS)
    assert len(topics) == 6


def test_single_event_rejects_trailing_abi_word():
    log = dict(FIXTURE_LOG)
    log["data"] = FIXTURE_LOG["data"] + "00" * 32
    assert decode_match_log(log) is None


def test_batch_rejects_truncation_and_trailing_words():
    topic = dsl.topic0("AsksMatched(bytes32,bytes32[])")
    good = _batch_log(topic, [(716952049 << 224) | (100 << 64) | (1 << 32)])
    truncated = dict(good)
    truncated["data"] = good["data"][:-64]
    trailing = dict(good)
    trailing["data"] = good["data"] + "00" * 32
    assert decode_match_log(truncated) is None
    assert decode_match_log(trailing) is None


def test_subtree_rejects_nonzero_uint160_high_bits():
    topic = dsl.topic0("AskSubtreeMatched(bytes32,bytes32,uint160,uint256)")
    bad_quantity = (1 << 160) + 1
    data = (DEEPSTATE_BOOK_ID[2:].lower() + "ab" * 32
            + hex(bad_quantity)[2:].rjust(64, "0")
            + hex(123)[2:].rjust(64, "0"))
    log = _subtree_log(topic)
    log["data"] = "0x" + data
    assert decode_match_log(log) is None


def test_collector_happy_path_uses_validated_timestamp_and_batched_persistence(
        monkeypatch, tmp_path, capsys):
    dc = _collect_env(monkeypatch, tmp_path)
    monkeypatch.setenv("FINCO_DEEPSTATE_START_BLOCK", "74416355")
    monkeypatch.setattr(dc, "eth_block_number", lambda *_a, **_k: 74416355)
    monkeypatch.setattr(dc, "fetch_match_logs", lambda *_a, **_k: [FIXTURE_LOG])
    monkeypatch.setattr(
        dc, "_canonical_block",
        lambda *_a, **_k: (True, int(BLOCK_TIME.timestamp())))
    assert dc.main([]) == 0
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report["observations_persisted"] == 1
    assert report["operational_checkpoint_block"] == 74416355
    from finco_radar.venues.store import VenueMarketStore
    store = VenueMarketStore(path=str(tmp_path / "v.db"))
    row = store.get_latest_for_underlying("NVDA", venue_id="DEEPSTATE")
    assert row is not None
    assert row.ts == BLOCK_TIME.isoformat()


def test_final_hash_change_persists_zero_and_does_not_advance_checkpoint(
        monkeypatch, tmp_path):
    dc = _collect_env(monkeypatch, tmp_path)
    monkeypatch.setenv("FINCO_DEEPSTATE_START_BLOCK", "74416355")
    monkeypatch.setattr(dc, "eth_block_number", lambda *_a, **_k: 74416355)
    monkeypatch.setattr(dc, "fetch_match_logs", lambda *_a, **_k: [FIXTURE_LOG])
    calls = {"n": 0}

    def canonical(*_a, **_k):
        calls["n"] += 1
        return ((True, int(BLOCK_TIME.timestamp()))
                if calls["n"] == 1 else (False, None))

    monkeypatch.setattr(dc, "_canonical_block", canonical)
    assert dc.main([]) == 6
    from finco_radar.venues.store import VenueMarketStore
    store = VenueMarketStore(path=str(tmp_path / "v.db"))
    assert store.count(venue_id="DEEPSTATE") == 0
    assert dc._checkpoint_block(store) is None


def test_empty_successful_range_advances_operational_checkpoint(
        monkeypatch, tmp_path):
    dc = _collect_env(monkeypatch, tmp_path)
    monkeypatch.setenv("FINCO_DEEPSTATE_START_BLOCK", "100")
    monkeypatch.setattr(dc, "eth_block_number", lambda *_a, **_k: 105)
    monkeypatch.setattr(dc, "fetch_match_logs", lambda *_a, **_k: [])
    assert dc.main([]) == 0
    from finco_radar.venues.store import VenueMarketStore
    store = VenueMarketStore(path=str(tmp_path / "v.db"))
    assert dc._checkpoint_block(store) == 105


def test_interrupted_batch_cannot_advance_checkpoint_or_skip_same_block(
        monkeypatch, tmp_path):
    dc = _collect_env(monkeypatch, tmp_path)
    monkeypatch.setenv("FINCO_DEEPSTATE_START_BLOCK", "74416355")
    monkeypatch.setattr(dc, "eth_block_number", lambda *_a, **_k: 74416355)
    two = [FIXTURE_LOG, dict(FIXTURE_LOG, logIndex="0x5")]
    monkeypatch.setattr(dc, "fetch_match_logs", lambda *_a, **_k: two)
    monkeypatch.setattr(
        dc, "_canonical_block",
        lambda *_a, **_k: (True, int(BLOCK_TIME.timestamp())))

    original = dc.VenueMarketStore.append_many_batched

    def interrupted(self, observations):
        assert len(list(observations)) == 2
        raise RuntimeError("simulated interrupted persistence")

    monkeypatch.setattr(dc.VenueMarketStore, "append_many_batched", interrupted)
    with pytest.raises(RuntimeError):
        dc.main([])
    store = dc.VenueMarketStore(path=str(tmp_path / "v.db"))
    assert dc._checkpoint_block(store) is None
    assert store.count(venue_id="DEEPSTATE") == 0

    monkeypatch.setattr(dc.VenueMarketStore, "append_many_batched", original)
    assert dc.main([]) == 0
    store = dc.VenueMarketStore(path=str(tmp_path / "v.db"))
    assert dc._checkpoint_block(store) == 74416355
    assert store.count(venue_id="DEEPSTATE") == 2
    assert dc.main([]) == 0
    assert store.count(venue_id="DEEPSTATE") == 2


def test_deferred_usdg_normalization_is_truthful_runtime_state():
    observation = _observations()
    assert "normalized_usd_price" not in observation.payload
    assert "usdg_usd_value" not in observation.payload
    assert "usdg_usd_timestamp" not in observation.payload
    assert "effective_evidence_timestamp" not in observation.payload
    assert "usdg_usd_authority" not in observation.payload


def test_normalization_fields_appear_when_evidence_is_supplied():
    observed_at = datetime(2026, 9, 28, 1, 49, 30, tzinfo=timezone.utc)
    observation = dsl.match_to_observations(
        _decoded(), collected_at=COLLECTED,
        block_timestamp=int(BLOCK_TIME.timestamp()),
        usdg_usd=(Decimal("1.0001"), observed_at),
    )[0]
    assert Decimal(observation.payload["normalized_usd_price"]) == (
        Decimal(observation.price) * Decimal("1.0001"))
    assert observation.payload["usdg_usd_value"] == "1.0001"
    assert observation.payload["usdg_usd_timestamp"] == observed_at.isoformat()
    assert observation.payload["effective_evidence_timestamp"] == observed_at.isoformat()


def test_same_canonical_sub_event_recollects_as_dedupe(tmp_path):
    from finco_radar.venues.store import VenueMarketStore
    store = VenueMarketStore(path=tmp_path / "dedupe.db")
    observations = dsl.match_to_observations(
        _decoded(), collected_at=COLLECTED,
        block_timestamp=int(BLOCK_TIME.timestamp()))
    first = store.append_many_batched(observations)
    second = store.append_many_batched(observations)
    assert first[0][1] is True
    assert second[0][1] is False
    assert store.count(venue_id="DEEPSTATE") == 1


# ── Correction B addendum: bounded checkpoint overlap / empty-block reorg ────

def _log_at(block_number, *, tx_hash=None, log_index="0x4", block_hash=None):
    log = dict(FIXTURE_LOG)
    log["blockNumber"] = hex(block_number)
    if tx_hash is not None:
        log["transactionHash"] = tx_hash
    if log_index is not None:
        log["logIndex"] = log_index
    if block_hash is not None:
        log["blockHash"] = block_hash
    return log


def test_checkpoint_next_run_rescans_configured_overlap(monkeypatch, tmp_path):
    dc = _collect_env(monkeypatch, tmp_path)
    from finco_radar.venues.store import VenueMarketStore
    store = VenueMarketStore(path=str(tmp_path / "v.db"))
    dc._advance_checkpoint(store, 105)
    monkeypatch.setenv("FINCO_DEEPSTATE_START_BLOCK", "100")
    monkeypatch.setenv("FINCO_DEEPSTATE_RESCAN_BLOCKS", "4")
    monkeypatch.setattr(dc, "eth_block_number", lambda *_a, **_k: 110)
    calls = []
    def fetch(_rpc, start, end):
        calls.append((start, end))
        return []
    monkeypatch.setattr(dc, "fetch_match_logs", fetch)
    assert dc.main([]) == 0
    assert calls == [(102, 110)]
    assert dc._checkpoint_block(store) == 110


def test_overlap_captures_event_that_appears_after_prior_empty_scan(
        monkeypatch, tmp_path):
    dc = _collect_env(monkeypatch, tmp_path)
    from finco_radar.venues.store import VenueMarketStore
    store = VenueMarketStore(path=str(tmp_path / "v.db"))
    # Prior run completed 100..105 with no Deepstate logs.
    dc._advance_checkpoint(store, 105)
    monkeypatch.setenv("FINCO_DEEPSTATE_START_BLOCK", "100")
    monkeypatch.setenv("FINCO_DEEPSTATE_RESCAN_BLOCKS", "4")
    monkeypatch.setattr(dc, "eth_block_number", lambda *_a, **_k: 106)
    late = _log_at(104)
    monkeypatch.setattr(dc, "fetch_match_logs", lambda *_a, **_k: [late])
    monkeypatch.setattr(
        dc, "_canonical_block",
        lambda *_a, **_k: (True, int(BLOCK_TIME.timestamp())))
    assert dc.main([]) == 0
    assert store.count(venue_id="DEEPSTATE") == 1
    row = store.get_latest_for_underlying("NVDA", venue_id="DEEPSTATE")
    assert row is not None
    assert row.payload["block_number"] == 104
    assert dc._checkpoint_block(store) == 106


def test_previously_persisted_event_inside_overlap_dedupes(
        monkeypatch, tmp_path, capsys):
    dc = _collect_env(monkeypatch, tmp_path)
    monkeypatch.setenv("FINCO_DEEPSTATE_START_BLOCK", "100")
    monkeypatch.setenv("FINCO_DEEPSTATE_RESCAN_BLOCKS", "4")
    log = _log_at(104)
    head = {"value": 105}
    monkeypatch.setattr(dc, "eth_block_number", lambda *_a, **_k: head["value"])
    monkeypatch.setattr(dc, "fetch_match_logs", lambda *_a, **_k: [log])
    monkeypatch.setattr(
        dc, "_canonical_block",
        lambda *_a, **_k: (True, int(BLOCK_TIME.timestamp())))
    assert dc.main([]) == 0
    capsys.readouterr()
    head["value"] = 106
    assert dc.main([]) == 0
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    from finco_radar.venues.store import VenueMarketStore
    store = VenueMarketStore(path=str(tmp_path / "v.db"))
    assert store.count(venue_id="DEEPSTATE") == 1
    assert report["observations_persisted"] == 0
    assert report["duplicates_skipped"] == 1
    assert dc._checkpoint_block(store) == 106


def test_new_event_in_already_scanned_reorged_block_appends(
        monkeypatch, tmp_path):
    dc = _collect_env(monkeypatch, tmp_path)
    monkeypatch.setenv("FINCO_DEEPSTATE_START_BLOCK", "100")
    monkeypatch.setenv("FINCO_DEEPSTATE_RESCAN_BLOCKS", "4")
    from finco_radar.venues.store import VenueMarketStore
    store = VenueMarketStore(path=str(tmp_path / "v.db"))

    old = _log_at(
        104,
        tx_hash="0x" + "11" * 32,
        block_hash="0x" + "aa" * 32,
    )
    monkeypatch.setattr(dc, "eth_block_number", lambda *_a, **_k: 105)
    monkeypatch.setattr(dc, "fetch_match_logs", lambda *_a, **_k: [old])
    monkeypatch.setattr(
        dc, "_canonical_block",
        lambda _rpc, _n, expected_hash, **_k:
            (True, int(BLOCK_TIME.timestamp())))
    assert dc.main([]) == 0
    assert store.count(venue_id="DEEPSTATE") == 1

    # The previously scanned block is replaced and now carries a distinct
    # canonical match. Overlap makes it observable; append-only identity
    # retains both historical evidence rows rather than mutating the first.
    new = _log_at(
        104,
        tx_hash="0x" + "22" * 32,
        log_index="0x8",
        block_hash="0x" + "bb" * 32,
    )
    monkeypatch.setattr(dc, "eth_block_number", lambda *_a, **_k: 106)
    monkeypatch.setattr(dc, "fetch_match_logs", lambda *_a, **_k: [new])
    assert dc.main([]) == 0
    assert store.count(venue_id="DEEPSTATE") == 2
    assert dc._checkpoint_block(store) == 106


def test_checkpoint_advances_only_after_final_canonicality_and_atomic_persistence(
        monkeypatch, tmp_path):
    dc = _collect_env(monkeypatch, tmp_path)
    monkeypatch.setenv("FINCO_DEEPSTATE_START_BLOCK", "74416355")
    monkeypatch.setenv("FINCO_DEEPSTATE_RESCAN_BLOCKS", "4")
    monkeypatch.setattr(dc, "eth_block_number", lambda *_a, **_k: 74416355)
    monkeypatch.setattr(dc, "fetch_match_logs", lambda *_a, **_k: [FIXTURE_LOG])
    order = []
    def canonical(*_a, **_k):
        order.append("canonical")
        return True, int(BLOCK_TIME.timestamp())
    monkeypatch.setattr(dc, "_canonical_block", canonical)

    original_append = dc.VenueMarketStore.append_many_batched
    def append(self, observations):
        order.append("persist")
        return original_append(self, observations)
    monkeypatch.setattr(dc.VenueMarketStore, "append_many_batched", append)

    original_advance = dc._advance_checkpoint
    def advance(store, block):
        order.append("checkpoint")
        return original_advance(store, block)
    monkeypatch.setattr(dc, "_advance_checkpoint", advance)

    assert dc.main([]) == 0
    assert order == ["canonical", "canonical", "persist", "checkpoint"]


def test_overlap_never_scans_before_reviewed_bootstrap_boundary(
        monkeypatch, tmp_path):
    dc = _collect_env(monkeypatch, tmp_path)
    from finco_radar.venues.store import VenueMarketStore
    store = VenueMarketStore(path=str(tmp_path / "v.db"))
    dc._advance_checkpoint(store, 102)
    monkeypatch.setenv("FINCO_DEEPSTATE_START_BLOCK", "100")
    monkeypatch.setenv("FINCO_DEEPSTATE_RESCAN_BLOCKS", "16")
    monkeypatch.setattr(dc, "eth_block_number", lambda *_a, **_k: 104)
    calls = []
    monkeypatch.setattr(
        dc, "fetch_match_logs",
        lambda _rpc, start, end: calls.append((start, end)) or [])
    assert dc.main([]) == 0
    assert calls == [(100, 104)]
    assert dc._checkpoint_block(store) == 104


def test_checkpoint_does_not_remove_bootstrap_requirement(
        monkeypatch, tmp_path, capsys):
    dc = _collect_env(monkeypatch, tmp_path)
    from finco_radar.venues.store import VenueMarketStore
    store = VenueMarketStore(path=str(tmp_path / "v.db"))
    dc._advance_checkpoint(store, 105)
    monkeypatch.delenv("FINCO_DEEPSTATE_START_BLOCK", raising=False)
    assert dc.main([]) == 4
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report["state"] == "BOOTSTRAP_REQUIRED"
    assert dc._checkpoint_block(store) == 105

# ── Post-merge staging Correction A: urllib RPC header compatibility ─────────

class _RpcJsonResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _assert_deepstate_rpc_request_headers(request):
    assert request.get_header("Content-type") == "application/json"
    user_agent = request.get_header("User-agent")
    assert user_agent
    assert user_agent == "FINCO-Protocol/Deepstate-Collector"
    assert "rpc.invalid" not in user_agent
    assert "token" not in user_agent.lower()
    assert "key" not in user_agent.lower()


def test_deepstate_chain_rpc_requests_send_content_type_and_user_agent(monkeypatch):
    import app.radar_rwa.deepstate_chain as chain

    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        method = json.loads(request.data.decode())["method"]
        result = "0x1237" if method == "eth_chainId" else "0x46f80e3"
        return _RpcJsonResponse({"jsonrpc": "2.0", "id": 1, "result": result})

    monkeypatch.setattr(chain.urllib.request, "urlopen", fake_urlopen)
    assert chain.ensure_chain("https://rpc.invalid", expected_chain_id=4663)
    assert chain.eth_block_number("https://rpc.invalid") == 74416355
    assert len(requests) == 2
    for request in requests:
        _assert_deepstate_rpc_request_headers(request)


def test_deepstate_live_rpc_requests_send_content_type_and_user_agent(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        method = json.loads(request.data.decode())["method"]
        if method == "eth_getLogs":
            result = []
        elif method == "eth_getBlockByNumber":
            result = {"timestamp": hex(int(BLOCK_TIME.timestamp()))}
        else:
            raise AssertionError(f"unexpected RPC method: {method}")
        return _RpcJsonResponse({"jsonrpc": "2.0", "id": 1, "result": result})

    monkeypatch.setattr(dsl.urllib.request, "urlopen", fake_urlopen)
    assert dsl.fetch_match_logs("https://rpc.invalid", 74416350, 74416360) == []
    assert dsl.fetch_block_timestamp("https://rpc.invalid", 74416355) == int(
        BLOCK_TIME.timestamp())
    assert len(requests) == 2
    for request in requests:
        _assert_deepstate_rpc_request_headers(request)


def test_deepstate_collector_canonical_block_request_sends_headers(monkeypatch):
    import app.radar_rwa.deepstate_collect as dc

    expected_hash = FIXTURE_LOG["blockHash"]
    captured = []

    def fake_urlopen(request, timeout):
        captured.append(request)
        assert json.loads(request.data.decode())["method"] == "eth_getBlockByNumber"
        return _RpcJsonResponse({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "hash": expected_hash,
                "timestamp": hex(int(BLOCK_TIME.timestamp())),
            },
        })

    monkeypatch.setattr(dc._urllib_request, "urlopen", fake_urlopen)
    assert dc._canonical_block(
        "https://rpc.invalid", 74416355, expected_hash) == (
            True, int(BLOCK_TIME.timestamp()))
    assert len(captured) == 1
    _assert_deepstate_rpc_request_headers(captured[0])

