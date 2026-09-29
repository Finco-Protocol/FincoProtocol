"""Network-free V2 admission, exact binding and read-surface regressions."""
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.api.v1_1 import institutional
from app.api.v1_1 import router as api_router
from app.radar_rwa.bnb_history import BnbIntelligenceHistoryStore, read_r_live_points_readonly
from app.radar_rwa.r_live_service import compose_r_live, read_r_live_history
from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.contracts import AssetKey
from finco_radar.authority.contracts import AuthorityState
from finco_radar.authority.r_live_onchain import SWAP_TOPIC0, observe_onchain_reference
from finco_radar.authority.r_live_policy import (
    AAPL_KEY, AAPL_POOL, APPROVED_BY_CANONICAL_ID, APPROVED_RLIVE_ASSETS,
)
from finco_radar.gap.contracts import BoundReferencePrice
from tests.test_r_live_onchain import BLOCK_TIME, FakeRpc, encoded_string, word


def _registry(policy, *, uid=None):
    return RobinhoodAssetRegistryAdapter.parse_snapshot({"assets": [{
        "id": uid or policy.economic_asset_uid,
        "tokenSymbol": policy.symbol,
        "tokenName": policy.symbol + " Robinhood Token",
        "deployments": [{"chainId": 4663, "contractAddress": policy.asset_key.contract_address}],
        "currentMultiplier": "1", "status": "ASSET_STATUS_ACTIVE",
    }]}, observed_at=datetime.fromtimestamp(BLOCK_TIME, timezone.utc))


class ReviewedPoolRpc(FakeRpc):
    def __init__(self, policy, *, tick=0, activity_age_seconds=0, activity_unavailable=False):
        super().__init__(tick=tick)
        self.policy = policy
        self.activity_age_seconds = activity_age_seconds
        self.activity_unavailable = activity_unavailable

    def call(self, method, params):
        if method == "eth_getLogs":
            if self.activity_unavailable:
                raise ValueError("secret https://rpc.invalid/credential")
            return [{
                "address": self.policy.pool.pool_address,
                "topics": [SWAP_TOPIC0, "0x" + word(1), "0x" + word(2)],
                "blockNumber": "0x122" if self.activity_age_seconds else "0x123",
                "blockHash": "0x" + "cd" * 32 if self.activity_age_seconds else "0x" + "ab" * 32,
                "logIndex": "0x0",
                "data": "0x" + "".join(map(word, [1, 2, 2 ** 96, 1_000_000, 0])),
            }]
        if method == "eth_getBlockByNumber" and params[0] == "0x122":
            return {"number": "0x122", "hash": "0x" + "cd" * 32,
                    "timestamp": hex(BLOCK_TIME - self.activity_age_seconds)}
        if method != "eth_call":
            return super().call(method, params)
        to, data = params[0]["to"], params[0]["data"]
        pool = self.policy.pool
        if to == pool.factory_address:
            return "0x" + word(int(pool.pool_address, 16))
        if to == self.policy.asset_key.contract_address:
            return "0x" + word(pool.token_decimals)
        if to == pool.quote_token_address:
            return "0x" + word(pool.quote_decimals)
        if to == pool.pool_address:
            if data == "0xc45a0155": return "0x" + word(int(pool.factory_address, 16))
            token0, token1 = sorted((pool.quote_token_address, self.policy.asset_key.contract_address))
            if data == "0x0dfe1681": return "0x" + word(int(token0, 16))
            if data == "0xd21220a7": return "0x" + word(int(token1, 16))
            if data == "0xddca3f43": return "0x" + word(pool.fee)
            if data == "0x1a686502": return "0x" + word(1_000_000)
            if data == "0x3850c7bd": return "0x" + "".join(map(word, [1, 0, 1, 3, 3, 0, 1]))
            if data.startswith("0x883bdbfd"):
                return "0x" + "".join(map(word, [64, 160, 2, 0,
                                                self.tick * self.policy.twap_window_seconds, 2, 0, 0]))
        if to == pool.quote_feed_address:
            if data == "0x7284e416": return encoded_string("USDG / USD")
            if data == "0x313ce567": return "0x" + word(pool.feed_decimals)
            if data == "0xfeaf968c": return "0x" + "".join(map(word, [7, self.feed_answer,
                                                               self.feed_updated - 5, self.feed_updated, 7]))
        raise AssertionError((to, data))


def _observe(policy, *, tick=0, uid=None, activity_age_seconds=0, activity_unavailable=False):
    return observe_onchain_reference(
        registry=_registry(policy, uid=uid), key=policy.asset_key,
        rpc=ReviewedPoolRpc(policy, tick=tick, activity_age_seconds=activity_age_seconds,
                            activity_unavailable=activity_unavailable),
        retrieved_at=datetime.fromtimestamp(BLOCK_TIME + 1, timezone.utc),
    )


def test_reviewed_universe_is_immutable_and_exact():
    assert {p.symbol for p in APPROVED_RLIVE_ASSETS.values()} == {
        "AAPL", "NVDA", "AMZN", "GOOGL", "TSLA", "AVGO", "NFLX", "AMD",
        "DELL", "SNAP", "INTC", "MSFT", "META",
    }
    assert APPROVED_RLIVE_ASSETS[AAPL_KEY].pool == AAPL_POOL
    assert len(APPROVED_BY_CANONICAL_ID) == len(APPROVED_RLIVE_ASSETS)
    assert "NVDA" not in APPROVED_BY_CANONICAL_ID
    with pytest.raises(TypeError):
        APPROVED_RLIVE_ASSETS[AAPL_KEY] = None
    for symbol in ("PLTR", "ORCL", "SNOW", "COST"):
        assert symbol not in {p.symbol for p in APPROVED_RLIVE_ASSETS.values()}


def test_new_admissions_are_exact_reviewed_pools_not_symbol_lookup():
    reviewed = {
        "DELL": ("0x941ae714ec6d8130c7b75d67160ca08f1e7d11dd",
                 "0xc30c89cb7815a1488b7998d15eec73961707fc5a", 10000),
        "SNAP": ("0xf6589f11bc40b669e584073f428b05562f568733",
                 "0x0ebd4650c9e641e9745b5a508a2d46935dfe753e", 3000),
        "INTC": ("0xc72b96e0e48ecd4dc75e1e45396e26300bc39681",
                 "0x2e5a92f5013a64661a49312111be2e8abd33f56a", 3000),
        "MSFT": ("0xe93237c50d904957cf27e7b1133b510c669c2e74",
                 "0xeb60bcd1d920ad6e102690ccfc6fb488899e1510", 3000),
        "META": ("0xc0d6457c16cc70d6790dd43521c899c87ce02f35",
                 "0x107a7cb40d8665360ba10e59471af06150a50922", 3000),
    }
    policies = {p.symbol: p for p in APPROVED_RLIVE_ASSETS.values()}
    for symbol, (token, pool, fee) in reviewed.items():
        policy = policies[symbol]
        assert policy.asset_key == AssetKey(4663, token)
        assert policy.pool.pool_address == pool
        assert policy.pool.fee == fee
        assert policy.pool.factory_address == AAPL_POOL.factory_address
        assert policy.pool.quote_token_address == AAPL_POOL.quote_token_address
        assert policy.pool.quote_feed_address == AAPL_POOL.quote_feed_address
        assert policy.pool.token_decimals == 18
        assert policy.pool.quote_decimals == 6
        assert policy.pool.feed_decimals == 8
        assert policy.asset_key.canonical_id in APPROVED_BY_CANONICAL_ID
    for symbol in ("PLTR", "ORCL", "SNOW", "COST"):
        assert symbol not in policies


@pytest.mark.parametrize("policy", tuple(APPROVED_RLIVE_ASSETS.values()), ids=lambda p: p.symbol)
def test_every_approved_policy_observes_exact_pair_and_quote(policy):
    observed = _observe(policy)
    assert observed.state is AuthorityState.AVAILABLE
    assert observed.registry_asset_uid == policy.economic_asset_uid
    assert observed.evidence["pool"] == policy.pool.pool_address
    assert observed.evidence["twapWindowSeconds"] == 300
    assert observed.evidence["lastPoolActivityBlock"] == 0x123
    assert observed.evidence["poolActivityAgeSeconds"] == 0
    assert observed.evidence["quoteUsdPrice"] == "0.99994"
    assert observed.price_usd_per_token != Decimal(1)
    assert _observe(policy, tick=-1).price_usd_per_token != observed.price_usd_per_token
    assert _observe(policy, uid="0x" + "ab" * 32).reason == "CANONICAL_ECONOMIC_UID_MISMATCH"


def test_two_real_reviewed_pool_orientations_have_inverse_tick_math():
    nvda = next(p for p in APPROVED_RLIVE_ASSETS.values() if p.symbol == "NVDA")
    amzn = next(p for p in APPROVED_RLIVE_ASSETS.values() if p.symbol == "AMZN")
    assert nvda.pool.quote_token_address < nvda.asset_key.contract_address  # USDG token0
    assert amzn.asset_key.contract_address < amzn.pool.quote_token_address  # asset token0
    nvda_positive = _observe(nvda, tick=100)
    amzn_positive = _observe(amzn, tick=100)
    assert nvda_positive.state is amzn_positive.state is AuthorityState.AVAILABLE
    assert nvda_positive.evidence["token0"] == nvda.pool.quote_token_address
    assert amzn_positive.evidence["token0"] == amzn.asset_key.contract_address
    baseline = Decimal(10) ** 12
    assert Decimal(nvda_positive.evidence["tokenQuotePrice"]) < baseline
    assert Decimal(amzn_positive.evidence["tokenQuotePrice"]) > baseline
    product = (Decimal(nvda_positive.evidence["tokenQuotePrice"])
               * Decimal(amzn_positive.evidence["tokenQuotePrice"]))
    assert abs(product - baseline * baseline) < Decimal("0.000001")


def test_stale_or_unavailable_pool_activity_suppresses_current_number():
    nvda = next(p for p in APPROVED_RLIVE_ASSETS.values() if p.symbol == "NVDA")
    fresh = _observe(nvda, activity_age_seconds=300)
    assert fresh.state is AuthorityState.AVAILABLE
    assert fresh.observed_at == datetime.fromtimestamp(BLOCK_TIME - 300, timezone.utc)
    stale = _observe(nvda, activity_age_seconds=301)
    assert stale.state is AuthorityState.STALE
    assert stale.reason == "POOL_ACTIVITY_STALE"
    assert stale.price_usd_per_token is None
    assert stale.to_independent_reference() is None
    assert stale.evidence["poolActivityAgeSeconds"] == 301
    unavailable = _observe(nvda, activity_unavailable=True)
    assert unavailable.state is AuthorityState.UNAVAILABLE
    assert unavailable.reason == "POOL_ACTIVITY_UNAVAILABLE"
    assert unavailable.price_usd_per_token is None
    assert "credential" not in str(unavailable.to_evidence_dict())


def test_unknown_identity_rejected_before_rpc_and_no_symbol_resolution():
    rpc = ReviewedPoolRpc(APPROVED_RLIVE_ASSETS[AAPL_KEY])
    result = observe_onchain_reference(registry=_registry(APPROVED_RLIVE_ASSETS[AAPL_KEY]),
        key=AssetKey(4663, "0x" + "11" * 20), rpc=rpc)
    assert result.state is AuthorityState.UNAVAILABLE
    assert rpc.calls == []
    assert institutional.get_r_live("AAPL") == ("UNAVAILABLE", {"reason": "ASSET_UID_INVALID"})


def test_history_readback_uses_exact_uid_and_is_read_only():
    policy = next(p for p in APPROVED_RLIVE_ASSETS.values() if p.symbol == "NVDA")
    class Ledger:
        def read(self, uid, key, *, limit):
            assert (uid, key, limit) == (policy.economic_asset_uid, policy.asset_key, 3)
            return [{"historical": True}]
    assert read_r_live_history(policy.asset_key.canonical_id, history=Ledger(), limit=3) == [{"historical": True}]
    with pytest.raises(ValueError):
        read_r_live_history("NVDA", history=Ledger())


def test_history_get_does_not_create_database_or_writer(tmp_path, monkeypatch):
    policy = next(p for p in APPROVED_RLIVE_ASSETS.values() if p.symbol == "NVDA")
    path = tmp_path / "absent" / "history.db"
    monkeypatch.setenv("RADAR_BNB_INTELLIGENCE_DB_PATH", str(path))
    assert read_r_live_history(policy.asset_key.canonical_id) == []
    assert not path.exists() and not path.parent.exists()
    store = BnbIntelligenceHistoryStore(str(path), allowed_chain_id=4663)
    store.close()
    assert read_r_live_points_readonly(policy.economic_asset_uid, policy.asset_key, path=str(path)) == []


def test_generic_get_never_requests_history_writer():
    policy = next(p for p in APPROVED_RLIVE_ASSETS.values() if p.symbol == "NVDA")
    with patch.dict("os.environ", {"ROBINHOOD_RPC_URL": "https://example.invalid"}):
        with patch("app.radar_rwa.r_live_service.collect_r_live", side_effect=RuntimeError("secret")) as acquire:
            state, data = institutional.get_r_live(policy.asset_key.canonical_id)
    assert state == "UNAVAILABLE" and data == {"reason": "RADAR_AUTHORITY_UNAVAILABLE"}
    acquire.assert_called_once_with(canonical_asset_id=policy.asset_key.canonical_id,
                                    rpc_url="https://example.invalid", persist_history=False)


def test_api_list_and_history_contract_is_explicitly_historical():
    assets = api_router.list_r_live_assets()
    assert assets["state"] == "AVAILABLE"
    assert len(assets["data"]["assets"]) == len(APPROVED_RLIVE_ASSETS)
    assert all(row["canonical_id"].startswith("4663:0x") for row in assets["data"]["assets"])
    assert api_router.get_r_live_history("NVDA")["state"] == "UNAVAILABLE"
    policy = next(p for p in APPROVED_RLIVE_ASSETS.values() if p.symbol == "NVDA")
    with patch("app.radar_rwa.r_live_service.read_r_live_history", return_value=[{"value_bps": "1"}]) as read:
        response = api_router.get_r_live_history(policy.asset_key.canonical_id, limit=2)
    assert response["data"]["history_kind"] == "HISTORICAL"
    read.assert_called_once_with(policy.asset_key.canonical_id, limit=2)


def test_generic_b1_premium_and_b13_idempotent_available_only():
    policy = next(p for p in APPROVED_RLIVE_ASSETS.values() if p.symbol == "NVDA")
    basis = BoundReferencePrice(
        asset_uid=policy.economic_asset_uid, asset_key=policy.asset_key, symbol=policy.symbol,
        raw_bid_usd_per_share=Decimal("100"), raw_ask_usd_per_share=Decimal("100"),
        current_multiplier=Decimal("1"), currency="USD",
        generated_at=datetime.fromtimestamp(BLOCK_TIME - 10, timezone.utc),
        is_trading_halt=False, source="ROBINHOOD_STOCK_TOKEN_BOUND_PRICE",
    )
    ledger = BnbIntelligenceHistoryStore(":memory:", allowed_chain_id=4663)
    clock = datetime.fromtimestamp(BLOCK_TIME + 1, timezone.utc)
    try:
        first = compose_r_live(registry=_registry(policy), underlying=basis,
            rpc=ReviewedPoolRpc(policy), as_of=clock, history=ledger, key=policy.asset_key)
        second = compose_r_live(registry=_registry(policy), underlying=basis,
            rpc=ReviewedPoolRpc(policy), as_of=clock, history=ledger, key=policy.asset_key)
        assert first.authority.premium.state is AuthorityState.AVAILABLE
        assert first.history_digest == second.history_digest
        assert len(ledger.read(policy.economic_asset_uid, policy.asset_key)) == 1
        stale_rpc = ReviewedPoolRpc(policy)
        stale_rpc.feed_updated = BLOCK_TIME - 86401
        stale = compose_r_live(registry=_registry(policy), underlying=basis,
            rpc=stale_rpc, as_of=clock, history=ledger, key=policy.asset_key)
        assert stale.onchain.state is AuthorityState.STALE
        assert stale.history_digest is None
        assert len(ledger.read(policy.economic_asset_uid, policy.asset_key)) == 1
        stale_pool = compose_r_live(registry=_registry(policy), underlying=basis,
            rpc=ReviewedPoolRpc(policy, activity_age_seconds=301), as_of=clock,
            history=ledger, key=policy.asset_key)
        assert stale_pool.onchain.state is AuthorityState.STALE
        assert stale_pool.authority.token.price_usd_per_token is None
        assert stale_pool.authority.premium.value_bps is None
        assert stale_pool.history_digest is None
        assert len(ledger.read(policy.economic_asset_uid, policy.asset_key)) == 1
        with patch.dict("os.environ", {"ROBINHOOD_RPC_URL": "https://example.invalid"}):
            with patch("app.radar_rwa.r_live_service.collect_r_live", return_value=stale_pool):
                state, payload = institutional.get_r_live(policy.asset_key.canonical_id)
        assert state == "STALE"
        assert payload["token_reference"]["price_usd_per_token"] is None
        assert payload["robinhood_basis"]["price_usd_per_token"] is None
        assert payload["b1_0_premium"]["value_bps"] is None
    finally:
        ledger.close()
