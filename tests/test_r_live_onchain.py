"""Deterministic, network-free checks of the R-LIVE on-chain authority."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest

from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.contracts import AssetKey
from finco_radar.authority.contracts import AuthorityState
from finco_radar.authority.r_live_onchain import JsonRpc, RpcUnavailable, observe_onchain_reference
from finco_radar.authority.r_live_policy import AAPL_KEY, AAPL_POOL, TWAP_WINDOW_SECONDS
from finco_radar.gap.contracts import BoundReferencePrice
from finco_radar.tokenization_premium.engine import premium_bps
from app.radar_rwa.bnb_history import BnbIntelligenceHistoryStore
from app.radar_rwa.r_live_service import compose_r_live
from app.radar_rwa.r_live_collect import collect_once


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
    stale_registry = RobinhoodAssetRegistryAdapter.parse_snapshot({"assets": [{
        "id": UID, "tokenSymbol": "AAPL", "tokenName": "Apple Robinhood Token",
        "deployments": [{"chainId": 4663, "contractAddress": AAPL_KEY.contract_address}],
        "currentMultiplier": "1", "status": "ASSET_STATUS_ACTIVE",
    }]}, observed_at=datetime.fromtimestamp(BLOCK_TIME - 301, timezone.utc))
    assert observe_onchain_reference(
        registry=stale_registry, key=AAPL_KEY, rpc=FakeRpc(),
        retrieved_at=datetime.fromtimestamp(BLOCK_TIME + 1, timezone.utc),
    ).state is AuthorityState.STALE


def test_twap_conversion_and_negative_tick_without_float():
    zero = observe(FakeRpc(tick=0))
    assert zero.evidence["twapWindowSeconds"] == 300
    assert zero.evidence["arithmeticMeanTick"] == 0
    assert Decimal(zero.evidence["tokenQuotePrice"]) == Decimal("1E+12")
    assert zero.evidence["quoteUsdPrice"] == "0.99994"
    assert zero.price_usd_per_token == Decimal("999940000000")
    negative = observe(FakeRpc(tick=-1))
    assert negative.state is AuthorityState.AVAILABLE
    assert negative.evidence["arithmeticMeanTick"] == -1
    assert negative.price_usd_per_token > zero.price_usd_per_token
    positive = observe(FakeRpc(tick=1))
    assert positive.evidence["arithmeticMeanTick"] == 1
    assert positive.price_usd_per_token < zero.price_usd_per_token


def test_reversed_token_ordering_and_negative_rounding():
    rpc = FakeRpc(tick=0)
    rpc.overrides[(AAPL_POOL.pool_address, "0x0dfe1681")] = "0x" + word(int(AAPL_KEY.contract_address, 16))
    rpc.overrides[(AAPL_POOL.pool_address, "0xd21220a7")] = "0x" + word(int(AAPL_POOL.quote_token_address, 16))
    result = observe(rpc)
    assert result.state is AuthorityState.AVAILABLE
    assert Decimal(result.evidence["tokenQuotePrice"]) == Decimal("1E+12")
    rpc.tick = -1
    negative = observe(rpc)
    assert negative.evidence["arithmeticMeanTick"] == -1
    assert negative.price_usd_per_token < result.price_usd_per_token
    # -301 / 300 floors to -2, matching OracleLibrary arithmeticMeanTick.
    rpc.tick = -1
    class FractionalNegative(FakeRpc):
        def call(self, method, params):
            if method == "eth_call" and params[0]["data"].startswith("0x883bdbfd"):
                return "0x" + "".join(map(word, [64, 160, 2, 0, -301, 2, 0, 0]))
            return super().call(method, params)
    assert observe(FractionalNegative()).evidence["arithmeticMeanTick"] == -2


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


def test_insufficient_history_invalid_round_and_rpc_error():
    rpc = FakeRpc()
    rpc.overrides[(AAPL_POOL.pool_address, "0x3850c7bd")] = "0x" + "".join(
        map(word, [1, 0, 1, 1, 1, 0, 1]))
    assert observe(rpc).reason == "POOL_LIQUIDITY_OR_CARDINALITY_INSUFFICIENT"
    rpc = FakeRpc()
    rpc.overrides[(AAPL_POOL.quote_feed_address, "0xfeaf968c")] = "0x" + "".join(
        map(word, [7, 99_994_000, BLOCK_TIME - 30, BLOCK_TIME - 20, 6]))
    assert observe(rpc).reason == "QUOTE_FEED_ROUND_INVALID"
    rpc = FakeRpc()
    rpc.overrides[(AAPL_POOL.pool_address, "0x1a686502")] = "0xZZ"
    assert observe(rpc).state is AuthorityState.UNAVAILABLE
    class Timeout(FakeRpc):
        def call(self, method, params):
            raise RpcUnavailable("RPC_TRANSPORT_UNAVAILABLE")
    assert observe(Timeout()).state is AuthorityState.UNAVAILABLE


def test_every_contract_read_uses_one_block_and_reorg_fails_closed():
    rpc = FakeRpc()
    assert observe(rpc).state is AuthorityState.AVAILABLE
    assert {params[1] for method, params in rpc.calls if method == "eth_call"} == {"0x123"}
    assert {params[1] for method, params in rpc.calls if method == "eth_getCode"} == {"0x123"}
    rpc = FakeRpc()
    rpc.overrides["chain"] = "0x1"
    assert observe(rpc).reason == "CHAIN_ID_MISMATCH"
    class Reorg(FakeRpc):
        def __init__(self):
            super().__init__()
            self.block_reads = 0
        def call(self, method, params):
            if method == "eth_getBlockByNumber":
                self.block_reads += 1
                if self.block_reads == 2:
                    return {"number": "0x123", "hash": "0x" + "cd" * 32,
                            "timestamp": hex(BLOCK_TIME)}
            return super().call(method, params)
    assert observe(Reorg()).reason == "BLOCK_REORG_OR_MISMATCH"


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


def test_existing_b1_premium_and_b13_history_reused():
    basis = BoundReferencePrice(
        asset_uid=UID, asset_key=AAPL_KEY, symbol="AAPL",
        raw_bid_usd_per_share=Decimal("100"),
        raw_ask_usd_per_share=Decimal("100"),
        current_multiplier=Decimal("1"), currency="USD",
        generated_at=datetime.fromtimestamp(BLOCK_TIME - 10, timezone.utc),
        is_trading_halt=False, source="ROBINHOOD_STOCK_TOKEN_BOUND_PRICE",
    )
    store = BnbIntelligenceHistoryStore(":memory:", allowed_chain_id=4663)
    try:
        result = compose_r_live(registry=registry(), underlying=basis,
                                rpc=FakeRpc(),
                                as_of=datetime.fromtimestamp(BLOCK_TIME + 1, timezone.utc),
                                history=store)
        assert result.authority.premium.state is AuthorityState.AVAILABLE
        assert result.authority.premium.value_bps == premium_bps(
            result.onchain.price_usd_per_token, Decimal("100"))
        assert result.authority.token.evidence["pool"] == AAPL_POOL.pool_address
        assert result.history_digest is not None
        points = store.read(UID, AAPL_KEY)
        assert len(points) == 1
        assert points[0]["independent_token_reference"]["evidence"]["pool"] == AAPL_POOL.pool_address
        assert points[0]["asset_key"] == AAPL_KEY.canonical_id
        assert store.read("0x" + "cd" * 32, AAPL_KEY) == []
    finally:
        store.close()


def test_stale_quote_never_enters_history():
    store = BnbIntelligenceHistoryStore(":memory:", allowed_chain_id=4663)
    try:
        result = compose_r_live(registry=registry(), underlying=None,
                                rpc=FakeRpc(feed_updated=BLOCK_TIME - 86401),
                                as_of=datetime.fromtimestamp(BLOCK_TIME + 1, timezone.utc),
                                history=store)
        assert result.onchain.state is AuthorityState.STALE
        assert result.history_digest is None
        assert store.read(UID, AAPL_KEY) == []
    finally:
        store.close()


def test_api_without_config_fails_closed(monkeypatch):
    import asyncio
    from app.radar_ui.rwa_router import radar_r_live_aapl_snapshot
    monkeypatch.delenv("ROBINHOOD_RPC_URL", raising=False)
    assert asyncio.run(radar_r_live_aapl_snapshot()) == {
        "state": "UNAVAILABLE", "reason": "RPC_NOT_CONFIGURED"}


def test_api_exposes_only_canonical_reference_and_premium(monkeypatch):
    import asyncio
    from app.radar_ui import rwa_router
    from app.radar_rwa.r_live_service import RLiveResult
    basis = BoundReferencePrice(
        asset_uid=UID, asset_key=AAPL_KEY, symbol="AAPL",
        raw_bid_usd_per_share=Decimal("100"), raw_ask_usd_per_share=Decimal("100"),
        current_multiplier=Decimal("1"), currency="USD",
        generated_at=datetime.fromtimestamp(BLOCK_TIME - 10, timezone.utc),
        is_trading_halt=False, source="ROBINHOOD_STOCK_TOKEN_BOUND_PRICE",
    )
    result = compose_r_live(registry=registry(), underlying=basis, rpc=FakeRpc(),
                            as_of=datetime.fromtimestamp(BLOCK_TIME + 1, timezone.utc))
    monkeypatch.setenv("ROBINHOOD_RPC_URL", "https://example.invalid/FAKE_SECRET")
    monkeypatch.setattr(rwa_router, "collect_aapl_r_live", lambda **_: result)
    payload = asyncio.run(rwa_router.radar_r_live_aapl_snapshot())
    assert payload["state"] == "AVAILABLE"
    assert payload["reference"]["evidence"]["pool"] == AAPL_POOL.pool_address
    assert payload["reference_premium"]["state"] == "AVAILABLE"
    assert "FAKE_SECRET" not in str(payload)


def _basis():
    return BoundReferencePrice(
        asset_uid=UID, asset_key=AAPL_KEY, symbol="AAPL",
        raw_bid_usd_per_share=Decimal("100"), raw_ask_usd_per_share=Decimal("100"),
        current_multiplier=Decimal("1"), currency="USD",
        generated_at=datetime.fromtimestamp(BLOCK_TIME - 10, timezone.utc),
        is_trading_halt=False, source="ROBINHOOD_STOCK_TOKEN_BOUND_PRICE",
    )


def test_operational_collector_repeat_is_idempotent_across_retrieval_times():
    store = BnbIntelligenceHistoryStore(":memory:", allowed_chain_id=4663)
    def acquire(*, rpc_url, as_of, persist_history, history):
        assert persist_history is True
        assert rpc_url == "https://example.invalid/FAKE_SECRET"
        return compose_r_live(registry=registry(), underlying=_basis(), rpc=FakeRpc(),
                              as_of=as_of, history=history)
    try:
        first = collect_once(rpc_url="https://example.invalid/FAKE_SECRET",
                             as_of=datetime.fromtimestamp(BLOCK_TIME + 1, timezone.utc),
                             history=store, acquire=acquire)
        second = collect_once(rpc_url="https://example.invalid/FAKE_SECRET",
                              as_of=datetime.fromtimestamp(BLOCK_TIME + 2, timezone.utc),
                              history=store, acquire=acquire)
        assert first["state"] == second["state"] == "AVAILABLE"
        assert first["history_digest"] == second["history_digest"]
        points = store.read(UID, AAPL_KEY)
        assert len(points) == 1
        point = points[0]
        assert point["economic_asset_uid"] == UID
        assert point["asset_key"] == AAPL_KEY.canonical_id
        assert point["independent_token_reference"]["evidence"]["blockHash"] == BLOCK_HASH
        assert point["independent_token_reference"]["evidence"]["quoteRoundId"] == "7"
        assert point["independent_token_reference"]["evidence"]["twapWindowSeconds"] == 300
        assert point["independent_token_reference"]["evidence"]["retrievedAt"]
        assert point["independent_token_reference"]["evidence"]["policyVersion"]
        assert point["independent_token_reference"]["evidence"]["poolAuthorityVersion"]
        assert point["independent_token_reference"]["evidence"]["quoteAuthorityVersion"]
        assert Decimal(point["reference_premium_bps"]) == premium_bps(
            Decimal("999940000000"), Decimal("100"))
        assert "FAKE_SECRET" not in str(first) + str(point)
    finally:
        store.close()


def test_operational_idempotency_across_ledger_connections(tmp_path):
    path = str(tmp_path / "existing_b13_history.db")
    def acquire(*, rpc_url, as_of, persist_history, history):
        assert persist_history is True
        return compose_r_live(registry=registry(), underlying=_basis(), rpc=FakeRpc(),
                              as_of=as_of, history=history)
    first_store = BnbIntelligenceHistoryStore(path, allowed_chain_id=4663)
    second_store = BnbIntelligenceHistoryStore(path, allowed_chain_id=4663)
    try:
        first = collect_once(rpc_url="https://example.invalid",
                             as_of=datetime.fromtimestamp(BLOCK_TIME + 1, timezone.utc),
                             history=first_store, acquire=acquire)
        second = collect_once(rpc_url="https://example.invalid",
                              as_of=datetime.fromtimestamp(BLOCK_TIME + 2, timezone.utc),
                              history=second_store, acquire=acquire)
        assert first["history_digest"] == second["history_digest"]
        assert len(second_store.read(UID, AAPL_KEY)) == 1
    finally:
        first_store.close()
        second_store.close()


@pytest.mark.parametrize("rpc,expected", [
    (FakeRpc(feed_updated=BLOCK_TIME - 86401), "STALE"),
    (FakeRpc(feed_answer=0), "UNAVAILABLE"),
])
def test_operational_collector_never_persists_non_available(rpc, expected):
    store = BnbIntelligenceHistoryStore(":memory:", allowed_chain_id=4663)
    def acquire(*, rpc_url, as_of, persist_history, history):
        assert persist_history is True
        return compose_r_live(registry=registry(), underlying=_basis(), rpc=rpc,
                              as_of=as_of, history=history)
    try:
        status = collect_once(rpc_url="https://example.invalid",
                              as_of=datetime.fromtimestamp(BLOCK_TIME + 1, timezone.utc),
                              history=store, acquire=acquire)
        assert status["state"] == expected
        assert status["history_digest"] is None
        assert store.read(UID, AAPL_KEY) == []
    finally:
        store.close()


def test_operational_collector_rpc_failure_and_missing_config_are_redacted(monkeypatch):
    def failing(**_):
        raise RuntimeError("https://rpc.example/FAKE_SECRET")
    store = BnbIntelligenceHistoryStore(":memory:", allowed_chain_id=4663)
    try:
        status = collect_once(rpc_url="https://rpc.example/FAKE_SECRET",
                              history=store, acquire=failing)
        assert status == {"state": "UNAVAILABLE", "reason": "R_LIVE_COLLECTION_UNAVAILABLE",
                          "history_digest": None}
        assert "FAKE_SECRET" not in str(status)
        assert store.read(UID, AAPL_KEY) == []
    finally:
        store.close()
    monkeypatch.delenv("ROBINHOOD_RPC_URL", raising=False)
    assert collect_once()["reason"] == "RPC_NOT_CONFIGURED"


def test_operational_collector_rejects_wrong_exact_identity():
    wrong = RobinhoodAssetRegistryAdapter.parse_snapshot({"assets": [{
        "id": UID, "tokenSymbol": "AAPL", "tokenName": "Apple Robinhood Token",
        "deployments": [{"chainId": 4663, "contractAddress": "0x" + "11" * 20}],
        "currentMultiplier": "1", "status": "ASSET_STATUS_ACTIVE",
    }]}, observed_at=datetime.fromtimestamp(BLOCK_TIME, timezone.utc))
    store = BnbIntelligenceHistoryStore(":memory:", allowed_chain_id=4663)
    def acquire(*, rpc_url, as_of, persist_history, history):
        assert persist_history is True
        return compose_r_live(registry=wrong, underlying=_basis(), rpc=FakeRpc(),
                              as_of=as_of, history=history)
    try:
        status = collect_once(rpc_url="https://example.invalid",
                              as_of=datetime.fromtimestamp(BLOCK_TIME + 1, timezone.utc),
                              history=store, acquire=acquire)
        assert status["state"] == "UNAVAILABLE"
        assert status["history_digest"] is None
        assert store.read(UID, AAPL_KEY) == []
    finally:
        store.close()


def test_operational_collector_reports_history_failure_not_success():
    def acquire(*, rpc_url, as_of, persist_history, history):
        assert persist_history is True
        return compose_r_live(registry=registry(), underlying=_basis(), rpc=FakeRpc(),
                              as_of=as_of, history=history)
    store = BnbIntelligenceHistoryStore(":memory:", allowed_chain_id=4663)
    try:
        store.close()
        status = collect_once(rpc_url="https://example.invalid",
                              as_of=datetime.fromtimestamp(BLOCK_TIME + 1, timezone.utc),
                              history=store, acquire=acquire)
        assert status["state"] == "UNAVAILABLE"
        assert status["history_digest"] is None
    finally:
        pass


def test_radar_live_surface_age_history_and_fail_closed(monkeypatch):
    import asyncio
    from pathlib import Path
    from app.radar_ui import rwa_router
    result = compose_r_live(registry=registry(), underlying=_basis(), rpc=FakeRpc(),
                            as_of=datetime.fromtimestamp(BLOCK_TIME + 1, timezone.utc))
    monkeypatch.setenv("ROBINHOOD_RPC_URL", "https://rpc.example/FAKE_SECRET")
    monkeypatch.setattr(rwa_router, "collect_aapl_r_live", lambda **_: result)
    payload = asyncio.run(rwa_router.radar_r_live_aapl_snapshot())
    assert payload["state"] == "AVAILABLE"
    assert payload["source_label"] == "Direct On-Chain"
    assert payload["observation_age_seconds"] >= 0
    assert payload["observed_at"] == result.onchain.observed_at.isoformat()
    assert payload["reference_premium"]["value_bps"] == str(result.authority.premium.value_bps)
    assert "FAKE_SECRET" not in str(payload)

    stale = compose_r_live(registry=registry(), underlying=_basis(),
                           rpc=FakeRpc(feed_updated=BLOCK_TIME - 86401),
                           as_of=datetime.fromtimestamp(BLOCK_TIME + 1, timezone.utc))
    monkeypatch.setattr(rwa_router, "collect_aapl_r_live", lambda **_: stale)
    hidden = asyncio.run(rwa_router.radar_r_live_aapl_snapshot())
    assert hidden["state"] == "STALE"
    assert hidden["reference"] is None
    assert hidden["reference_premium"]["value_bps"] is None
    assert hidden["robinhood_basis"]["price_usd_per_token"] is None

    template = Path("app/templates/radar/rwa.html").read_text(encoding="utf-8")
    script = Path("static/radar/r_live.js").read_text(encoding="utf-8")
    assert "Direct On-Chain" in template and "not VERIFIED" in template
    assert "Historical observations only" in template
    assert "field(\"values\").hidden = true" in script
    assert "textContent" in script and "innerHTML" not in script
    assert "BUY" not in template + script and "SELL" not in template + script


def test_snapshot_get_and_browser_refresh_never_open_history_writer(monkeypatch):
    import asyncio
    from app.radar_rwa import r_live_service
    from app.radar_ui import rwa_router

    result = compose_r_live(registry=registry(), underlying=_basis(), rpc=FakeRpc(),
                            as_of=datetime.fromtimestamp(BLOCK_TIME + 1, timezone.utc))
    class Adapter:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return None
        def fetch_snapshot(self):
            return registry()
        def fetch_bound_reference(self, *_):
            raise ValueError("test basis unavailable")
    class Transport:
        def __init__(self, _url):
            pass
        def close(self):
            pass
    def forbidden_writer(**_):
        raise AssertionError("GET opened B1.3 history writer")
    observed = []
    original = r_live_service.collect_aapl_r_live
    def acquire(**kwargs):
        observed.append(kwargs)
        return original(**kwargs)
    monkeypatch.setattr(r_live_service, "RobinhoodAssetRegistryAdapter", Adapter)
    monkeypatch.setattr(r_live_service, "JsonRpc", Transport)
    monkeypatch.setattr(r_live_service, "BnbIntelligenceHistoryStore", forbidden_writer)
    monkeypatch.setattr(r_live_service, "compose_r_live", lambda **kwargs: (
        result if kwargs["history"] is None else forbidden_writer()))
    monkeypatch.setattr(rwa_router, "collect_aapl_r_live", acquire)
    monkeypatch.setenv("ROBINHOOD_RPC_URL", "https://rpc.example/FAKE_SECRET")

    first = asyncio.run(rwa_router.radar_r_live_aapl_snapshot())
    second = asyncio.run(rwa_router.radar_r_live_aapl_snapshot())
    assert first["state"] == second["state"] == "AVAILABLE"
    assert all(call["persist_history"] is False for call in observed)
    assert len(observed) == 2
    assert first["reference"]["priceUsdPerToken"]
    assert first["robinhood_basis"]["price_usd_per_token"]
    assert first["reference_premium"]["value_bps"]
    assert first["observation_age_seconds"] >= 0
    assert "FAKE_SECRET" not in str(first) + str(second)
    script = __import__("pathlib").Path("static/radar/r_live.js").read_text(encoding="utf-8")
    assert "window.setInterval(load, 60000)" in script
    assert 'fetch("/radar/crypto/rwa/r-live/aapl/snapshot"' in script
    assert "POST" not in script


def test_read_acquisition_requires_explicit_writer_intent(monkeypatch):
    from app.radar_rwa import r_live_service
    class Adapter:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return None
        def fetch_snapshot(self):
            return registry()
        def fetch_bound_reference(self, *_):
            raise ValueError("basis unavailable")
    class Transport:
        def __init__(self, _url):
            pass
        def close(self):
            pass
    def forbidden_writer(**_):
        raise AssertionError("read acquisition opened history writer")
    monkeypatch.setattr(r_live_service, "RobinhoodAssetRegistryAdapter", Adapter)
    monkeypatch.setattr(r_live_service, "JsonRpc", Transport)
    monkeypatch.setattr(r_live_service, "BnbIntelligenceHistoryStore", forbidden_writer)
    monkeypatch.setattr(r_live_service, "compose_r_live", lambda **kwargs: kwargs["history"])
    assert r_live_service.collect_aapl_r_live(rpc_url="https://example.invalid") is None
    with pytest.raises(ValueError, match="HISTORY_REQUIRES_EXPLICIT_PERSISTENCE"):
        r_live_service.collect_aapl_r_live(
            rpc_url="https://example.invalid", history=object())
