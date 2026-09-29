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
from finco_radar.authority.r_live_onchain import observe_onchain_reference
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
    def __init__(self, policy, *, tick=0):
        super().__init__(tick=tick)
        self.policy = policy

    def call(self, method, params):
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
            if data == "0x0dfe1681": return "0x" + word(int(pool.quote_token_address, 16))
            if data == "0xd21220a7": return "0x" + word(int(self.policy.asset_key.contract_address, 16))
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


def _observe(policy, *, tick=0, uid=None):
    return observe_onchain_reference(
        registry=_registry(policy, uid=uid), key=policy.asset_key,
        rpc=ReviewedPoolRpc(policy, tick=tick),
        retrieved_at=datetime.fromtimestamp(BLOCK_TIME + 1, timezone.utc),
    )


def test_reviewed_universe_is_immutable_and_exact():
    assert {p.symbol for p in APPROVED_RLIVE_ASSETS.values()} == {
        "AAPL", "NVDA", "AMZN", "GOOGL", "TSLA", "AVGO", "NFLX", "AMD",
    }
    assert APPROVED_RLIVE_ASSETS[AAPL_KEY].pool == AAPL_POOL
    assert len(APPROVED_BY_CANONICAL_ID) == len(APPROVED_RLIVE_ASSETS)
    assert "NVDA" not in APPROVED_BY_CANONICAL_ID
    with pytest.raises(TypeError):
        APPROVED_RLIVE_ASSETS[AAPL_KEY] = None
    for symbol in ("MSFT", "META", "PLTR", "ORCL"):
        assert symbol not in {p.symbol for p in APPROVED_RLIVE_ASSETS.values()}


@pytest.mark.parametrize("symbol", ["AAPL", "NVDA", "AMZN", "GOOGL", "TSLA", "AVGO", "NFLX", "AMD"])
def test_every_approved_policy_observes_exact_pair_and_quote(symbol):
    policy = next(p for p in APPROVED_RLIVE_ASSETS.values() if p.symbol == symbol)
    observed = _observe(policy)
    assert observed.state is AuthorityState.AVAILABLE
    assert observed.registry_asset_uid == policy.economic_asset_uid
    assert observed.evidence["pool"] == policy.pool.pool_address
    assert observed.evidence["twapWindowSeconds"] == 300
    assert observed.evidence["quoteUsdPrice"] == "0.99994"
    assert observed.price_usd_per_token != Decimal(1)
    assert _observe(policy, tick=-1).price_usd_per_token != observed.price_usd_per_token
    assert _observe(policy, uid="0x" + "ab" * 32).reason == "CANONICAL_ECONOMIC_UID_MISMATCH"


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
    assert len(assets["data"]["assets"]) == 8
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
    finally:
        ledger.close()
