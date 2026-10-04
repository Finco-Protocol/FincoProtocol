"""Multi-source evidence V2: MARKET != OFFICIAL_REFERENCE != ORACLE.

Deterministic fixtures only (no network). The shipped oracle registry has NO source-proven binding because none could be
verified against official Chainlink authority from the authoring environment; the oracle machinery is exercised with
explicit test-only bindings that carry official-source provenance fields, exactly as a reviewed binding would.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.radar_rwa import multi_source_collect as msc
from app.radar_rwa.keccak import keccak256, selector
from app.radar_rwa.multi_source_evidence import (
    EvidenceLeg, EvidenceRole, SourceEvidenceStore, build_matrix, market_leg, oracle_leg, read_latest_legs_readonly,
    reference_leg,
)
from app.radar_rwa.stock_token_oracle import (
    SEL_DECIMALS, SEL_DESCRIPTION, SEL_LATEST_ROUND, SEL_ORACLE_PAUSED, SequencerStatus, check_sequencer,
    pin_oracle_block, read_stock_token_oracle,
)
from app.radar_rwa.stock_token_oracle_registry import (
    ORACLE_FEED_NOT_REVIEWED, SOURCE_PROVEN, FeedBinding, OracleRegistry, OracleRegistryError, Provenance,
    SequencerBinding, load_registry, parse_registry,
)
from finco_radar.authority.contracts import AuthorityState, ReferenceLayer
from finco_radar.authority.r_live_onchain import OnchainReferenceObservation, RpcUnavailable
from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 5, 14, 0, 0, tzinfo=timezone.utc)
NVDA_ID = next(c for c, p in APPROVED_BY_CANONICAL_ID.items() if p.symbol == "NVDA")
AAPL_ID = next(c for c, p in APPROVED_BY_CANONICAL_ID.items() if p.symbol == "AAPL")
NVDA_TOKEN = APPROVED_BY_CANONICAL_ID[NVDA_ID].asset_key.contract_address.lower()
AAPL_TOKEN = APPROVED_BY_CANONICAL_ID[AAPL_ID].asset_key.contract_address.lower()
FEED = "0x" + "f1" * 20
SEQ = "0x" + "5e" * 20
BLOCK_TS = int(NOW.timestamp()) - 5
PROV = {"source": "CHAINLINK_OFFICIAL_FEED_CATALOG", "reference_url": "https://docs.chain.link/data-feeds/price-feeds/addresses",
        "reviewed_at": "2026-10-05", "reviewer": "test-fixture"}


def word(value: int) -> str:
    return f"{value % (1 << 256):064x}"


def abi_string(text: str) -> str:
    raw = text.encode()
    return "0x" + word(32) + word(len(raw)) + raw.hex().ljust(((len(raw) + 31) // 32) * 64, "0")


def block_hash_for(number: int) -> str:
    return f"0x{number:064x}"


class FakeRpc:
    """Deterministic EVM read double. Records every read (address, selector, block tag) so tests can prove what was
    NOT called. ``advance`` makes every further ``latest`` read return the NEXT block number."""

    def __init__(self, *, answer=190_00000000, updated_at=BLOCK_TS - 60, decimals=8, description="NVDA / USD",
                 paused=0, seq_answer=0, seq_started=BLOCK_TS - 86400, round_id=7, answered_in=7, block_ts=BLOCK_TS,
                 fail=(), first_block=1000, advance=False, reorg=False, extra=None):
        self.calls: list[tuple[str, str]] = []
        self.tags: list[str] = []                 # block tag of every eth_call
        self.block_reads: list[str] = []          # first param of every eth_getBlockByNumber
        self.fail = set(fail)
        self.first_block, self.advance, self.reorg, self.block_ts = first_block, advance, reorg, block_ts
        self.latest_calls = 0
        self.map = {
            (FEED, SEL_DESCRIPTION): abi_string(description),
            (FEED, SEL_DECIMALS): "0x" + word(decimals),
            (FEED, SEL_LATEST_ROUND): "0x" + word(round_id) + word(answer) + word(updated_at - 10) + word(updated_at) + word(answered_in),
            (NVDA_TOKEN, SEL_ORACLE_PAUSED): "0x" + word(paused),
            (SEQ, SEL_LATEST_ROUND): "0x" + word(1) + word(seq_answer) + word(seq_started) + word(seq_started) + word(1),
        }
        self.map.update(extra or {})

    def _block(self, number: int, *, altered=False) -> dict:
        digest = block_hash_for(number if not altered else number + 10**6)
        return {"number": hex(number), "timestamp": hex(self.block_ts), "hash": digest}

    def call(self, method, params):
        if method == "eth_getBlockByNumber":
            self.block_reads.append(params[0])
            if "block" in self.fail:
                raise RpcUnavailable("RPC_TRANSPORT_UNAVAILABLE")
            if params[0] == "latest":
                self.latest_calls += 1
                return self._block(self.first_block + (self.latest_calls - 1 if self.advance else 0))
            return self._block(int(params[0], 16), altered=self.reorg)
        assert method == "eth_call"
        to, data = params[0]["to"].lower(), params[0]["data"]
        self.calls.append((to, data))
        self.tags.append(params[1])
        if (to, data) in {(a, b) for a, b in self.fail if isinstance(a, str)}:
            raise RpcUnavailable("RPC_RESPONSE_UNAVAILABLE")
        return self.map[(to, data)]


def binding(**kw) -> FeedBinding:
    base = dict(canonical_id=NVDA_ID, chain_id=4663, token_contract=NVDA_TOKEN, feed_proxy=FEED,
                feed_description="NVDA / USD", reviewed_decimals=8, heartbeat_seconds=86400,
                provenance=Provenance(**PROV))
    base.update(kw)
    return FeedBinding(**base)


def registry(*, bindings=None, sequencer="default") -> OracleRegistry:
    seq = SequencerBinding(4663, SEQ, 3600, Provenance(**PROV)) if sequencer == "default" else sequencer
    items = {b.canonical_id: b for b in (bindings if bindings is not None else [binding()])}
    return OracleRegistry(items, seq)


def read(rpc=None, reg=None, **kw):
    return read_stock_token_oracle(rpc=rpc or FakeRpc(), registry=reg or registry(), canonical_id=kw.pop("cid", NVDA_ID),
                                   as_of=NOW, **kw)


# ── primitives ───────────────────────────────────────────────────────────────────────────────────
def test_keccak_selectors_match_known_vectors():
    assert keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    assert selector("decimals()") == "0x313ce567" and selector("latestRoundData()") == "0xfeaf968c"
    assert selector("description()") == "0x7284e416"


# ── registry authority ───────────────────────────────────────────────────────────────────────────
def test_shipped_registry_has_no_unverified_binding_and_every_reviewed_asset_is_not_reviewed():
    reg = load_registry()
    coverage = reg.coverage()
    assert len(coverage) == 13 and set(coverage) == set(APPROVED_BY_CANONICAL_ID)
    assert set(coverage.values()) == {ORACLE_FEED_NOT_REVIEWED}      # no address is guessed
    assert reg.sequencer is None


def _raw(**item):
    base = {"canonical_id": NVDA_ID, "chain_id": 4663, "token_contract": NVDA_TOKEN, "feed_proxy": FEED,
            "feed_description": "NVDA / USD", "reviewed_decimals": 8, "heartbeat_seconds": 86400, "provenance": dict(PROV)}
    base.update(item)
    return {"schema_version": "FINCO_STOCK_TOKEN_ORACLE_FEEDS_V1", "chain_id": 4663, "sequencer": None, "bindings": [base]}


def test_valid_official_binding_is_source_proven():
    reg = parse_registry(_raw())
    assert reg.status_for(NVDA_ID) == SOURCE_PROVEN and reg.status_for(AAPL_ID) == ORACLE_FEED_NOT_REVIEWED


@pytest.mark.parametrize("override,code", [
    ({"token_contract": AAPL_TOKEN}, "ORACLE_BINDING_TOKEN_CONTRACT_MISMATCH"),     # wrong Stock Token contract
    ({"chain_id": 1}, "ORACLE_BINDING_CHAIN_INVALID"),                              # wrong chain
    ({"canonical_id": "4663:0x" + "00" * 20}, "ORACLE_BINDING_ASSET_NOT_APPROVED"),  # not a reviewed asset
    ({"provenance": {**PROV, "source": "THIRD_PARTY_GITHUB"}}, "ORACLE_BINDING_PROVENANCE_NOT_OFFICIAL"),
    ({"provenance": {**PROV, "reference_url": "http://x"}}, "ORACLE_BINDING_PROVENANCE_URL_REQUIRED"),
    ({"feed_proxy": "NVDA"}, "ORACLE_BINDING_PROXY_INVALID_ADDRESS"),               # no ticker inference
    ({"feed_description": ""}, "ORACLE_BINDING_DESCRIPTION_REQUIRED"),
    ({"heartbeat_seconds": 0}, "ORACLE_BINDING_HEARTBEAT_INVALID"),
])
def test_invalid_or_unreviewed_bindings_are_rejected(override, code):
    with pytest.raises(OracleRegistryError, match=code):
        parse_registry(_raw(**override))


def test_one_feed_proxy_can_never_serve_two_assets():
    raw = _raw()
    raw["bindings"].append({**raw["bindings"][0], "canonical_id": AAPL_ID, "token_contract": AAPL_TOKEN})
    with pytest.raises(OracleRegistryError, match="ORACLE_BINDING_DUPLICATE_PROXY"):
        parse_registry(raw)


# ── oracle leg ───────────────────────────────────────────────────────────────────────────────────
def test_available_oracle_reads_decimals_and_does_not_apply_the_multiplier():
    rpc = FakeRpc(answer=190_12345678, decimals=8)
    obs = read(rpc)
    assert obs.state is AuthorityState.AVAILABLE and obs.reason is None
    assert obs.value == Decimal("190.12345678") and obs.decimals == 8 and obs.feed_proxy == FEED
    assert obs.evidence["multiplierApplied"] is False and obs.evidence["unit"] == "USD_PER_STOCK_TOKEN"
    assert (FEED, SEL_DECIMALS) in rpc.calls                      # decimals() is read from the proxy
    assert selector("uiMultiplier()") not in {data for _, data in rpc.calls}   # never double-applied


def test_decimals_are_read_not_hardcoded():
    obs = read(FakeRpc(answer=190_123456, decimals=6), registry(bindings=[binding(reviewed_decimals=None)]))
    assert obs.state is AuthorityState.AVAILABLE and obs.value == Decimal("190.123456") and obs.decimals == 6


def test_decimals_disagreeing_with_review_fail_closed():
    obs = read(FakeRpc(decimals=6))
    assert obs.state is AuthorityState.UNAVAILABLE and obs.reason == "ORACLE_FEED_DECIMALS_MISMATCH"


def test_unreviewed_asset_is_oracle_feed_not_reviewed_and_never_blocks_a_reviewed_one():
    reg = registry()
    assert read(reg=reg, cid=AAPL_ID).reason == "ORACLE_FEED_NOT_REVIEWED"
    assert read(reg=reg, cid=NVDA_ID).state is AuthorityState.AVAILABLE


def test_unapproved_asset_is_identity_unavailable():
    obs = read(cid="4663:0x" + "00" * 20)
    assert obs.state is AuthorityState.IDENTITY_UNAVAILABLE and obs.reason == "ORACLE_ASSET_NOT_APPROVED"


def test_runtime_binding_identity_mismatch_is_rejected():
    bad = binding(token_contract=AAPL_TOKEN)
    obs = read(reg=registry(bindings=[bad]))
    assert obs.state is AuthorityState.IDENTITY_UNAVAILABLE and obs.reason == "ORACLE_BINDING_IDENTITY_MISMATCH"


@pytest.mark.parametrize("kwargs,reason", [
    ({"answer": 0}, "ORACLE_ANSWER_NOT_POSITIVE"),
    ({"answer": -5}, "ORACLE_ANSWER_NOT_POSITIVE"),
    ({"updated_at": 0}, "ORACLE_UPDATED_AT_INVALID"),
    ({"updated_at": BLOCK_TS + 3600}, "ORACLE_UPDATED_AT_IN_FUTURE"),
    ({"round_id": 0}, "ORACLE_ROUND_INCOMPLETE"),
    ({"answered_in": 3}, "ORACLE_ROUND_INCOMPLETE"),
    ({"description": "AAPL / USD"}, "ORACLE_FEED_DESCRIPTION_MISMATCH"),
])
def test_invalid_feed_rounds_are_rejected(kwargs, reason):
    obs = read(FakeRpc(**kwargs))
    assert obs.state is AuthorityState.UNAVAILABLE and obs.reason == reason and obs.value is None


def test_heartbeat_exceeded_is_stale_not_available():
    obs = read(FakeRpc(updated_at=BLOCK_TS - 86400 - 1))
    assert obs.state is AuthorityState.STALE and obs.reason == "ORACLE_HEARTBEAT_EXCEEDED" and obs.age_seconds > 86400


def test_age_equal_to_heartbeat_is_available():
    assert read(FakeRpc(updated_at=BLOCK_TS - 86400)).state is AuthorityState.AVAILABLE


def test_missing_reviewed_heartbeat_fails_closed_without_a_generic_ttl():
    obs = read(reg=registry(bindings=[binding(heartbeat_seconds=None)]))
    assert obs.state is AuthorityState.UNAVAILABLE and obs.reason == "ORACLE_HEARTBEAT_NOT_REVIEWED"


def test_old_oracle_is_judged_by_its_own_heartbeat_not_a_shared_ceiling():
    reg = registry(bindings=[binding(heartbeat_seconds=60)])
    assert read(FakeRpc(updated_at=BLOCK_TS - 120), reg).state is AuthorityState.STALE
    assert read(FakeRpc(updated_at=BLOCK_TS - 120)).state is AuthorityState.AVAILABLE   # 24h heartbeat binding


def test_sequencer_down_rejected():
    obs = read(FakeRpc(seq_answer=1))
    assert obs.state is AuthorityState.UNAVAILABLE and obs.reason == "ORACLE_SEQUENCER_DOWN" and obs.value is None


def test_sequencer_grace_period_rejected():
    obs = read(FakeRpc(seq_started=BLOCK_TS - 100))
    assert obs.reason == "ORACLE_SEQUENCER_GRACE_PERIOD"


def test_sequencer_without_reviewed_authority_fails_closed():
    obs = read(reg=registry(sequencer=None))
    assert obs.state is AuthorityState.UNAVAILABLE and obs.reason == "ORACLE_SEQUENCER_AUTHORITY_UNAVAILABLE"


def test_sequencer_unreadable_or_invalid_fails_closed():
    for rpc in (FakeRpc(fail={(SEQ, SEL_LATEST_ROUND)}), FakeRpc(seq_answer=7), FakeRpc(seq_started=0)):
        ctx = pin_oracle_block(rpc, as_of=NOW)
        assert check_sequencer(rpc, registry().sequencer, ctx).reason == "ORACLE_SEQUENCER_AUTHORITY_UNAVAILABLE"


def test_oracle_paused_is_unavailable_even_with_a_readable_fresh_round():
    rpc = FakeRpc(paused=1)
    obs = read(rpc)
    assert obs.state is AuthorityState.UNAVAILABLE and obs.reason == "ORACLE_CORPORATE_ACTION_PAUSED"
    assert obs.value is None
    assert (FEED, SEL_LATEST_ROUND) not in rpc.calls               # the old round is never trusted


def test_pause_state_unreadable_fails_closed():
    obs = read(FakeRpc(fail={(NVDA_TOKEN, SEL_ORACLE_PAUSED)}))
    assert obs.reason == "ORACLE_PAUSE_STATE_UNAVAILABLE"


def test_staleness_still_checked_when_not_paused():
    assert read(FakeRpc(paused=0, updated_at=BLOCK_TS - 90000)).state is AuthorityState.STALE


def test_stale_chain_block_and_rpc_failure_are_typed():
    assert read(FakeRpc(block_ts=int(NOW.timestamp()) - 3600)).reason == "ORACLE_CHAIN_BLOCK_STALE"
    assert read(FakeRpc(fail={"block"})).reason == "ORACLE_RPC_UNAVAILABLE"


# ── legs, no substitution ────────────────────────────────────────────────────────────────────────
def _leg(role, state="AVAILABLE", value="190", ts=NOW - timedelta(seconds=10), reason=None, cid=NVDA_ID):
    return EvidenceLeg(cid, role, f"SRC_{role.value}", "inst", state, None if value is None else Decimal(value),
                       "USD_PER_STOCK_TOKEN", ts, reason)


def test_reference_leg_reuses_existing_bound_reference_layer_values():
    layer = ReferenceLayer(AuthorityState.AVAILABLE, "uid", APPROVED_BY_CANONICAL_ID[NVDA_ID].asset_key, "NVDA",
                           Decimal("189.5"), "ROBINHOOD_STOCK_TOKEN_BOUND_PRICE", NOW - timedelta(seconds=8), None)
    leg = reference_leg(NVDA_ID, layer)
    assert leg.role is EvidenceRole.OFFICIAL_REFERENCE and leg.value == Decimal("189.5")
    assert leg.source_authority == "ROBINHOOD_STOCK_TOKEN_BOUND_PRICE" and leg.state == "AVAILABLE"
    assert reference_leg(NVDA_ID, None).reason == "REFERENCE_EVIDENCE_UNAVAILABLE"


def test_market_leg_keeps_its_own_state_independent_of_the_reference():
    stale = OnchainReferenceObservation(AuthorityState.STALE, APPROVED_BY_CANONICAL_ID[NVDA_ID].asset_key, "uid",
                                        "POOL_ACTIVITY_STALE", evidence={"pool": "0xpool"})
    leg = market_leg(NVDA_ID, stale)
    assert leg.role is EvidenceRole.MARKET and leg.state == "STALE" and leg.reason == "POOL_ACTIVITY_STALE"
    assert leg.source_instrument == "0xpool"


def test_fresh_oracle_and_reference_never_make_a_stale_market_current():
    legs = {NVDA_ID: {EvidenceRole.MARKET: _leg(EvidenceRole.MARKET, "STALE", "190", reason="POOL_ACTIVITY_STALE"),
                      EvidenceRole.OFFICIAL_REFERENCE: _leg(EvidenceRole.OFFICIAL_REFERENCE),
                      EvidenceRole.ORACLE: _leg(EvidenceRole.ORACLE)}}
    row = next(r for r in build_matrix(legs, now=NOW) if r["canonical_id"] == NVDA_ID)
    assert row["MARKET"]["state"] == "STALE" and row["OFFICIAL_REFERENCE"]["state"] == "AVAILABLE"
    assert row["ORACLE"]["state"] == "AVAILABLE"
    assert row["comparisons"]["market_vs_reference"] == {"basis_bps": None, "time_skew_seconds": None, "reason": "LEG_NOT_AVAILABLE"}
    assert row["comparisons"]["market_vs_oracle"]["basis_bps"] is None
    assert row["comparisons"]["oracle_vs_reference"]["basis_bps"] == "0"


def test_unavailable_market_is_not_filled_from_reference_or_oracle():
    legs = {NVDA_ID: {EvidenceRole.MARKET: _leg(EvidenceRole.MARKET, "UNAVAILABLE", None, None, "RPC_OR_SOURCE_EVIDENCE_UNAVAILABLE"),
                      EvidenceRole.OFFICIAL_REFERENCE: _leg(EvidenceRole.OFFICIAL_REFERENCE, value="191"),
                      EvidenceRole.ORACLE: _leg(EvidenceRole.ORACLE, value="192")}}
    row = next(r for r in build_matrix(legs, now=NOW) if r["canonical_id"] == NVDA_ID)
    assert row["MARKET"]["value"] is None and row["MARKET"]["source_timestamp"] is None
    assert row["MARKET"]["reason"] == "RPC_OR_SOURCE_EVIDENCE_UNAVAILABLE"


def test_comparison_basis_only_when_both_legs_available():
    legs = {NVDA_ID: {EvidenceRole.MARKET: _leg(EvidenceRole.MARKET, value="190.19"),
                      EvidenceRole.OFFICIAL_REFERENCE: _leg(EvidenceRole.OFFICIAL_REFERENCE, value="190"),
                      EvidenceRole.ORACLE: _leg(EvidenceRole.ORACLE, "STALE", "190", reason="ORACLE_HEARTBEAT_EXCEEDED")}}
    row = next(r for r in build_matrix(legs, now=NOW) if r["canonical_id"] == NVDA_ID)
    assert Decimal(row["comparisons"]["market_vs_reference"]["basis_bps"]) == Decimal("10")
    assert row["comparisons"]["oracle_vs_reference"]["reason"] == "LEG_NOT_AVAILABLE"


def test_matrix_always_lists_all_13_reviewed_assets_with_three_cells():
    rows = build_matrix({}, now=NOW, oracle_coverage=load_registry().coverage())
    assert len(rows) == 13 and {r["canonical_id"] for r in rows} == set(APPROVED_BY_CANONICAL_ID)
    for row in rows:
        for role in ("MARKET", "OFFICIAL_REFERENCE", "ORACLE"):
            assert row[role]["state"] == "UNAVAILABLE" and row[role]["reason"] == "EVIDENCE_LEG_NOT_COLLECTED"
        assert row["oracle_binding"] == ORACLE_FEED_NOT_REVIEWED


# ── orchestration: one failing source never erases the other two ─────────────────────────────────
def _pair(cid):
    return (market_leg(cid, OnchainReferenceObservation(AuthorityState.AVAILABLE, APPROVED_BY_CANONICAL_ID[cid].asset_key,
                                                         "uid", None, Decimal("190"), NOW - timedelta(seconds=30),
                                                         {"pool": "0xpool"})),
            reference_leg(cid, ReferenceLayer(AuthorityState.AVAILABLE, "uid", APPROVED_BY_CANONICAL_ID[cid].asset_key,
                                              "x", Decimal("189.9"), "ROBINHOOD_STOCK_TOKEN_BOUND_PRICE",
                                              NOW - timedelta(seconds=8), None)))


def run(acquire=_pair, rpc=None, reg=None, store=None):
    return msc.collect_multi_source_once(acquire_asset=acquire, oracle_rpc=rpc or FakeRpc(), oracle_registry=reg or registry(),
                                         as_of=NOW, store=store)


def _row(report, cid=NVDA_ID):
    return next(r for r in report["matrix"] if r["canonical_id"] == cid)


def test_all_three_roles_are_independent_in_one_cycle():
    report = run()
    row, aapl = _row(report), _row(report, AAPL_ID)
    assert report["assets"] == 13 and len(report["matrix"]) == 13
    assert row["MARKET"]["state"] == row["OFFICIAL_REFERENCE"]["state"] == row["ORACLE"]["state"] == "AVAILABLE"
    assert aapl["ORACLE"]["reason"] == "ORACLE_FEED_NOT_REVIEWED" and aapl["MARKET"]["state"] == "AVAILABLE"
    assert report["oracle_coverage"][NVDA_ID] == SOURCE_PROVEN


def test_market_and_reference_failure_does_not_erase_the_oracle():
    def failing(cid):
        if cid == NVDA_ID:
            raise RuntimeError("boom")
        return _pair(cid)
    row = _row(run(failing))
    assert row["MARKET"]["reason"] == row["OFFICIAL_REFERENCE"]["reason"] == "RADAR_AUTHORITY_UNAVAILABLE"
    assert row["ORACLE"]["state"] == "AVAILABLE" and row["ORACLE"]["value"] == "190"


def test_oracle_failure_does_not_erase_market_and_reference():
    row = _row(run(rpc=FakeRpc(paused=1)))
    assert row["ORACLE"]["reason"] == "ORACLE_CORPORATE_ACTION_PAUSED"
    assert row["MARKET"]["state"] == "AVAILABLE" and row["OFFICIAL_REFERENCE"]["state"] == "AVAILABLE"


def test_sequencer_down_marks_every_bound_oracle_unavailable_but_not_market_or_reference():
    row = _row(run(rpc=FakeRpc(seq_answer=1)))
    assert row["ORACLE"]["reason"] == "ORACLE_SEQUENCER_DOWN"
    assert row["MARKET"]["state"] == "AVAILABLE" and row["OFFICIAL_REFERENCE"]["state"] == "AVAILABLE"


# ── append-only per-source persistence ───────────────────────────────────────────────────────────
@pytest.fixture()
def store(tmp_path):
    return SourceEvidenceStore(tmp_path / "evidence.db")


def test_exact_duplicate_dedupes_and_changed_evidence_appends(store):
    leg = _leg(EvidenceRole.ORACLE)
    assert store.append(leg, collected_at=NOW) is True
    assert store.append(leg, collected_at=NOW + timedelta(minutes=5)) is False      # same source evidence, later poll
    assert store.count() == 1
    changed = _leg(EvidenceRole.ORACLE, value="191", ts=NOW)
    assert store.append(changed, collected_at=NOW + timedelta(minutes=10)) is True
    assert store.count() == 2


def test_a_to_b_to_a_appends_three_rows_never_collapsing_history(store):
    a = _leg(EvidenceRole.ORACLE, "AVAILABLE", "190")
    b = _leg(EvidenceRole.ORACLE, "UNAVAILABLE", None, None, "ORACLE_CORPORATE_ACTION_PAUSED")
    for index, leg in enumerate((a, b, a)):
        assert store.append(leg, collected_at=NOW + timedelta(minutes=index))
    assert [r["state"] for r in store.history(NVDA_ID, EvidenceRole.ORACLE)] == ["AVAILABLE", "UNAVAILABLE", "AVAILABLE"]


def test_roles_are_persisted_independently_and_never_overwrite_each_other(store):
    for role in EvidenceRole:
        assert store.append(_leg(role), collected_at=NOW)
    assert store.count() == 3
    assert {store.latest(NVDA_ID, role)["source_authority"] for role in EvidenceRole} == {f"SRC_{r.value}" for r in EvidenceRole}


def test_unavailable_legs_are_persisted_with_typed_reason_and_null_value_not_zero(store):
    leg = _leg(EvidenceRole.ORACLE, "UNAVAILABLE", None, None, "ORACLE_FEED_NOT_REVIEWED")
    store.append(leg, collected_at=NOW)
    row = store.latest(NVDA_ID, EvidenceRole.ORACLE)
    assert row["value"] is None and row["source_timestamp"] is None and row["reason"] == "ORACLE_FEED_NOT_REVIEWED"


def test_digest_excludes_collected_at_and_covers_source_fields():
    base = _leg(EvidenceRole.ORACLE)
    assert base.digest() == _leg(EvidenceRole.ORACLE).digest()
    assert base.digest() != _leg(EvidenceRole.ORACLE, value="190.1").digest()
    assert base.digest() != _leg(EvidenceRole.ORACLE, ts=NOW).digest()
    assert base.digest() != _leg(EvidenceRole.ORACLE, "STALE").digest()


def test_store_exposes_no_update_or_delete_and_requires_an_aware_clock(store):
    assert not any(hasattr(store, name) for name in ("update", "delete", "remove", "overwrite"))
    with pytest.raises(ValueError):
        store.append(_leg(EvidenceRole.ORACLE), collected_at=datetime(2026, 1, 1))


def test_collect_persists_per_source_and_second_identical_cycle_dedupes(store):
    first = run(store=store)
    assert first["persisted"] == 39 and first["duplicates"] == 0           # 13 assets x 3 roles
    second = run(store=store)
    assert second["persisted"] == 0 and second["duplicates"] == 39
    assert store.count() == 39


# ── read path is network-free and write-free ─────────────────────────────────────────────────────
def test_read_path_is_network_free_and_never_creates_the_database(tmp_path, monkeypatch):
    import httpx
    def boom(*a, **k):
        raise AssertionError("network access is forbidden on the read path")
    monkeypatch.setattr(httpx.Client, "send", boom)
    missing = tmp_path / "absent.db"
    payload = read_latest_legs_readonly(NVDA_ID, path=missing, now=NOW)
    assert payload["legs"] == {"MARKET": None, "OFFICIAL_REFERENCE": None, "ORACLE": None}
    assert not missing.exists()


def test_read_path_returns_each_persisted_role_with_age(store):
    store.append(_leg(EvidenceRole.MARKET, ts=NOW - timedelta(seconds=120)), collected_at=NOW)
    payload = read_latest_legs_readonly(NVDA_ID, path=store.path, now=NOW)
    assert payload["legs"]["MARKET"]["age_seconds"] == 120 and payload["legs"]["ORACLE"] is None
    with sqlite3.connect(store.path) as conn:
        before = conn.execute("SELECT COUNT(*) FROM source_evidence").fetchone()[0]
    read_latest_legs_readonly(NVDA_ID, path=store.path, now=NOW)
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM source_evidence").fetchone()[0] == before


def test_unknown_asset_is_rejected_on_the_read_path(tmp_path):
    with pytest.raises(ValueError):
        read_latest_legs_readonly("4663:0x" + "00" * 20, path=tmp_path / "x.db")


def test_evidence_route_is_read_only_and_exact_key_only(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.radar_ui.r_live_router import router
    monkeypatch.setenv("FINCO_SOURCE_EVIDENCE_DB_PATH", str(tmp_path / "evidence.db"))
    client = TestClient(FastAPI())
    client.app.include_router(router)
    ok = client.get(f"/radar/r-live/{NVDA_ID}/evidence")
    assert ok.status_code == 200 and ok.json()["oracle_binding"] == ORACLE_FEED_NOT_REVIEWED
    assert not (tmp_path / "evidence.db").exists()
    assert client.get("/radar/r-live/NVDA/evidence").status_code == 404      # no ticker lookup


# ── no duplicate Robinhood provider, terminology, frozen areas ───────────────────────────────────
def test_no_new_robinhood_provider_adapter_is_created():
    for name in ("multi_source_evidence.py", "multi_source_collect.py", "stock_token_oracle.py"):
        text = (ROOT / "app" / "radar_rwa" / name).read_text(encoding="utf-8")
        assert "api.robinhood.com" not in text and "httpx.get" not in text
    collect = (ROOT / "app" / "radar_rwa" / "multi_source_collect.py").read_text(encoding="utf-8")
    assert "from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter" in collect
    assert "build_bound_reference_price" in collect


def test_rlive_copy_uses_stock_token_terminology():
    for template in ("radar/r_live_landing.html", "radar/r_live_detail.html"):
        text = (ROOT / "app" / "templates" / template).read_text(encoding="utf-8")
        assert "tokenized equit" not in text.lower() and "tokenized stock" not in text.lower()
    assert "R-LIVE — Stock Token Market Tape" in (ROOT / "app/templates/radar/r_live_landing.html").read_text(encoding="utf-8")


def test_rlive_detail_shows_status_first_source_legs_panel():
    text = (ROOT / "app/templates/radar/r_live_detail.html").read_text(encoding="utf-8")
    assert 'data-testid="source-legs"' in text and "Status" in text.split('data-testid="source-legs"', 1)[1][:1500]
    for role in ("MARKET", "OFFICIAL_REFERENCE", "ORACLE"):
        assert f'data-leg="{role}"' in text


@pytest.mark.parametrize("path", ["financial_engine", "finco_core", "finco_yield"])
def test_frozen_namespaces_have_zero_diff(path):
    out = subprocess.run(["git", "diff", "--name-only", "origin/main..HEAD", "--", path], cwd=ROOT,
                         capture_output=True, text=True)
    if out.returncode != 0:
        pytest.skip("git unavailable")
    assert out.stdout.strip() == ""


def test_existing_authorities_are_not_modified():
    # Pre-#188 authority files must stay untouched; the multi-source modules themselves are the subject of later
    # reviewed corrections and are excluded from this guard.
    excluded = [
        ":(exclude)app/radar_rwa/stock_token_oracle.py", ":(exclude)app/radar_rwa/stock_token_oracle_registry.py",
        ":(exclude)app/radar_rwa/multi_source_evidence.py", ":(exclude)app/radar_rwa/multi_source_collect.py",
        ":(exclude)app/radar_rwa/keccak.py", ":(exclude)app/radar_rwa/data/stock_token_oracle_feeds.json"]
    out = subprocess.run(["git", "diff", "--name-only", "--diff-filter=MD", "origin/main..HEAD", "--",
                          "finco_radar", "app/radar_rwa", "app/crypto_resource_access.py", *excluded], cwd=ROOT,
                         capture_output=True, text=True)
    if out.returncode != 0:
        pytest.skip("git unavailable")
    assert out.stdout.strip() == "", out.stdout
