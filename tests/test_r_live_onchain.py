"""Deterministic, network-free checks of the R-LIVE on-chain authority."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest

from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.contracts import AssetKey
from finco_radar.authority.contracts import AuthorityState
from finco_radar.authority.r_live_onchain import JsonRpc, observe_onchain_reference
from finco_radar.authority.r_live_policy import AAPL_KEY, AAPL_POOL, TWAP_WINDOW_SECONDS


UID = "0x" + "ab" * 32
BLOCK_TIME = 1_800_000_000
BLOCK_HASH = "0x" + "ab" * 32


def word(n: int) -> str:
    return f"{n % (1 << 256):064x}"


def encoded_string(s: str) -> str:
    raw = s.encode().hex()
    return "0x" + word(32) + word(len(s)) + raw.ljust(64, "0")


def registry():
    return RobinhoodAssetRegistryAdapter.parse_snapshot({"assets": [{
        "id": UID, "tokenSymbol": "AAPL", "tokenName": "Apple Robinhood Token",
        "deployments": [{"chainId": 4663, "contractAddress": AAPL_KEY.contract_address}],
        "currentMultiplier": "1", "status": "ASSET_STATUS_ACTIVE",
    }]}, observed_at=datetime.fromtimestamp(BLOCK_TIME, timezone.utc))


class FakeRpc:
    def __init__(self, *, tick: int = 0, feed_answer: int = 99_994_000,
                 feed_updated: int = BLOCK_TIME - 20) -> None:
        self.tick, self.feed_answer, self.feed_updated = tick, feed_answer, feed_updated
        self.calls = []
        self.overrides = {}

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "eth_chainId":
            return self.overrides.get("chain", "0x1237")
        if method == "eth_getBlockByNumber":
            return self.overrides.get("block", {"number": "0x123", "hash": BLOCK_HASH,
                                                  "timestamp": hex(BLOCK_TIME)})
        if method == "eth_getCode":
            return self.overrides.get(("code", params[0]), "0x6001")
        assert method == "eth_call"
        to, data = params[0]["to"], params[0]["data"]
        if (to, data) in self.overrides:
            return self.overrides[(to, data)]
        if to == AAPL_POOL.factory_address:
            return "0x" + word(int(AAPL_POOL.pool_address, 16))
        if to == AAPL_KEY.contract_address:
            return "0x" + word(18)
        if to == AAPL_POOL.quote_token_address:
            return "0x" + word(6)
        if to == AAPL_POOL.pool_address:
            if data == "0xc45a0155":
                return "0x" + word(int(AAPL_POOL.factory_address, 16))
            if data == "0x0dfe1681":
                return "0x" + word(int(AAPL_POOL.quote_token_address, 16))
            if data == "0xd21220a7":
                return "0x" + word(int(AAPL_KEY.contract_address, 16))
            if data == "0xddca3f43":
                return "0x" + word(500)
            if data == "0x1a686502":
                return "0x" + word(1_000_000)
            if data == "0x3850c7bd":
                return "0x" + "".join(map(word, [1, 0, 1, 3, 3, 0, 1]))
            if data.startswith("0x883bdbfd"):
                return "0x" + "".join(map(word, [64, 160, 2, 0,
                                                      self.tick * TWAP_WINDOW_SECONDS, 2, 0, 0]))
        if to == AAPL_POOL.quote_feed_address:
            if data == "0x7284e416":
                return encoded_string("USDG / USD")
            if data == "0x313ce567":
                return "0x" + word(8)
            if data == "0xfeaf968c":
                return "0x" + "".join(map(word, [7, self.feed_answer,
                                                      self.feed_updated - 5,
                                                      self.feed_updated, 7]))
        raise AssertionError((to, data))


def observe(rpc=None, *, key=AAPL_KEY):
    return observe_onchain_reference(registry=registry(), key=key,
                                     rpc=rpc or FakeRpc(),
                                     retrieved_at=datetime.fromtimestamp(BLOCK_TIME + 1, timezone.utc))


def test_exact_identity_and_approved_pool_only():
    result = observe()
    assert result.state is AuthorityState.AVAILABLE
    assert result.registry_asset_uid == UID
    assert result.evidence["pool"] == AAPL_POOL.pool_address
    assert observe(key=AssetKey(56, AAPL_KEY.contract_address)).state is AuthorityState.UNAVAILABLE
    assert observe(key=AssetKey(4663, "0x" + "11" * 20)).state is AuthorityState.UNAVAILABLE
    assert result.to_independent_reference().asset_key == AAPL_KEY


def test_twap_conversion_and_negative_tick_without_float():
    zero = observe(FakeRpc(tick=0))
    assert zero.evidence["twapWindowSeconds"] == 300
    assert zero.evidence["arithmeticMeanTick"] == 0
    assert zero.evidence["tokenQuotePrice"] == "1E+12"
    assert zero.evidence["quoteUsdPrice"] == "0.99994"
    assert zero.price_usd_per_token == Decimal("999940000000")
    negative = observe(FakeRpc(tick=-1))
    assert negative.state is AuthorityState.AVAILABLE
    assert negative.evidence["arithmeticMeanTick"] == -1
    assert negative.price_usd_per_token > zero.price_usd_per_token


@pytest.mark.parametrize("field,data", [
    ("factory", "0x0000000000000000000000000000000000000000"),
    ("pair", "0x" + word(0)),
    ("fee", "0x" + word(3000)),
    ("description", encoded_string("AAPL / USD")),
    ("decimals", "0x" + word(18)),
])
def test_wrong_authority_fails_closed(field, data):
    rpc = FakeRpc()
    target = {
        "factory": (AAPL_POOL.pool_address, "0xc45a0155"),
        "pair": (AAPL_POOL.pool_address, "0xd21220a7"),
        "fee": (AAPL_POOL.pool_address, "0xddca3f43"),
        "description": (AAPL_POOL.quote_feed_address, "0x7284e416"),
        "decimals": (AAPL_POOL.quote_feed_address, "0x313ce567"),
    }[field]
    rpc.overrides[target] = data
    assert observe(rpc).state is AuthorityState.UNAVAILABLE


def test_stale_invalid_round_and_missing_code():
    assert observe(FakeRpc(feed_updated=BLOCK_TIME - 86401)).state is AuthorityState.STALE
    assert observe(FakeRpc(feed_answer=0)).state is AuthorityState.UNAVAILABLE
    assert observe(FakeRpc(feed_answer=-1)).state is AuthorityState.UNAVAILABLE
    rpc = FakeRpc()
    rpc.overrides[("code", AAPL_POOL.quote_feed_address)] = "0x"
    assert observe(rpc).state is AuthorityState.UNAVAILABLE


def test_every_contract_read_uses_one_block_and_reorg_fails_closed():
    rpc = FakeRpc()
    assert observe(rpc).state is AuthorityState.AVAILABLE
    assert {params[1] for method, params in rpc.calls if method == "eth_call"} == {"0x123"}
    assert {params[1] for method, params in rpc.calls if method == "eth_getCode"} == {"0x123"}
    rpc = FakeRpc()
    rpc.overrides["chain"] = "0x1"
    assert observe(rpc).reason == "CHAIN_ID_MISMATCH"


def test_rpc_secret_never_in_repr_or_exception():
    secret = "FAKE_SECRET_123"
    def fail(_):
        raise httpx.ConnectError(secret)
    client = httpx.Client(transport=httpx.MockTransport(fail))
    rpc = JsonRpc(f"https://rpc.example/{secret}", client=client)
    assert secret not in repr(rpc)
    with pytest.raises(ValueError) as exc:
        rpc.call("eth_chainId", [])
    assert secret not in str(exc.value)
    client.close()
