"""BNB RWA market intelligence authority and browser-boundary tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.radar_rwa.bnb_coingecko import CoinGeckoBnbRwaProvider
from app.radar_rwa.bnb_contracts import GLOBAL_MARKET_SCOPE, RWA_TVL_REASON
from app.radar_rwa.bnb_service import BnbRwaDashboardService, serialize_bnb_snapshot
from app.radar_rwa.bnb_snapshot import compose_bnb_snapshot
from app.radar_ui import rwa_router

NOW = datetime(2026, 9, 28, 10, tzinfo=timezone.utc)
ADDR_A = "0x" + "a" * 40
ADDR_B = "0x" + "b" * 40


def _platforms():
    return [{"id": "binance-smart-chain", "chain_identifier": 56},
            {"id": "ethereum", "chain_identifier": 1}]


def _coin(identifier="asset-a", address=ADDR_A, *, symbol="AAA", name="Asset A"):
    return {"id": identifier, "symbol": symbol.lower(), "name": name,
            "platforms": {"binance-smart-chain": address}}


def _market(identifier="asset-a", *, symbol="AAA", name="Asset A",
            observed_at=NOW, cap=100, volume=10, price=2):
    return {"id": identifier, "symbol": symbol.lower(), "name": name,
            "last_updated": observed_at.isoformat() if observed_at else None,
            "current_price": price, "market_cap": cap, "total_volume": volume,
            "price_change_percentage_24h": -1.25,
            "circulating_supply": 50, "total_supply": 100}


def _snapshot(*, platforms=None, coins=None, markets=None):
    return compose_bnb_snapshot(
        platforms=_platforms() if platforms is None else platforms,
        coins=[_coin()] if coins is None else coins,
        markets=[_market()] if markets is None else markets,
        retrieved_at=NOW,
    )


def test_exact_bnb_deployment_and_global_market_scope_are_separate():
    snapshot = _snapshot()
    row = snapshot.observations[0]
    assert snapshot.state.value == "AVAILABLE"
    assert row.asset_key.chain_id == 56
    assert row.asset_key.contract_address == ADDR_A
    assert row.robinhood_binding.value == "IDENTITY_UNAVAILABLE"
    assert row.market_scope == GLOBAL_MARKET_SCOPE
    assert row.price_change_24h_pct == Decimal("-1.25")
    assert snapshot.observed_market_cap_usd == Decimal(100)
    assert snapshot.observed_volume_24h_usd == Decimal(10)
    assert snapshot.rwa_tvl_usd is None
    assert snapshot.rwa_tvl_reason == RWA_TVL_REASON


def test_symbol_or_name_never_establishes_bnb_identity():
    snapshot = _snapshot(coins=[_coin("different-id")])
    assert snapshot.observations == ()
    assert snapshot.observed_market_cap_usd is None
    assert snapshot.state.value == "UNAVAILABLE"


def test_provider_metadata_conflict_fails_closed():
    snapshot = _snapshot(coins=[_coin(name="Different Asset")])
    assert snapshot.observations == ()
    assert "PROVIDER_ID_METADATA_CONFLICT_EXCLUDED" in snapshot.degraded_reasons


def test_missing_contract_is_visible_but_excluded_from_aggregates():
    snapshot = _snapshot(coins=[_coin(address=None)])
    assert len(snapshot.observations) == 1
    assert snapshot.observations[0].asset_key is None
    assert snapshot.observations[0].deployment_reason == "BNB_CONTRACT_UNAVAILABLE"
    assert snapshot.deployment_unavailable_count == 1
    assert snapshot.observed_market_cap_usd is None
    assert snapshot.observed_volume_24h_usd is None


def test_wrong_chain_platform_and_ambiguous_platform_fail_closed():
    ethereum_only = [_coin() | {"platforms": {"ethereum": ADDR_A}}]
    assert _snapshot(coins=ethereum_only).observations == ()
    ambiguous = _platforms() + [{"id": "other-bnb", "chain_identifier": 56}]
    snapshot = _snapshot(platforms=ambiguous)
    assert snapshot.state.value == "UNAVAILABLE"
    assert snapshot.reason == "BNB_PLATFORM_IDENTITY_UNAVAILABLE_OR_CONFLICTING"


def test_duplicate_exact_deployment_and_duplicate_provider_id_excluded():
    coins = [_coin(), _coin("asset-b", ADDR_A, symbol="BBB", name="Asset B")]
    markets = [_market(), _market("asset-b", symbol="BBB", name="Asset B")]
    snapshot = _snapshot(coins=coins, markets=markets)
    assert snapshot.observations == ()
    assert "DUPLICATE_BNB_DEPLOYMENT_EXCLUDED" in snapshot.degraded_reasons
    duplicate_id = _snapshot(coins=[_coin(), _coin()], markets=[_market()])
    assert duplicate_id.observations == ()
    assert "DUPLICATE_PROVIDER_COIN_ID_EXCLUDED" in duplicate_id.degraded_reasons


def test_stale_and_unidentified_rows_do_not_enter_current_aggregate():
    coins = [_coin(), _coin("asset-b", ADDR_B, symbol="BBB", name="Asset B")]
    markets = [_market(observed_at=NOW - timedelta(hours=2), cap=100),
               _market("asset-b", symbol="BBB", name="Asset B", cap=200, volume=20)]
    snapshot = _snapshot(coins=coins, markets=markets)
    assert snapshot.stale_count == 1
    assert snapshot.current_count == 1
    assert snapshot.observed_market_cap_usd == Decimal(200)
    assert snapshot.observed_volume_24h_usd == Decimal(20)
    assert snapshot.market_cap_contributors == 1


def test_missing_timestamp_or_price_is_unavailable_and_never_aggregated():
    no_time = _snapshot(markets=[_market(observed_at=None)])
    assert no_time.observations[0].state.value == "UNAVAILABLE"
    assert "observed_at" in no_time.observations[0].unavailable_fields
    assert no_time.observed_market_cap_usd is None
    no_price = _snapshot(markets=[_market(price=None)])
    assert no_price.observations[0].state.value == "UNAVAILABLE"
    assert "price_usd" in no_price.observations[0].unavailable_fields
    assert no_price.observed_market_cap_usd is None


def test_future_timestamp_and_bad_economics_are_excluded():
    future = _snapshot(markets=[_market(observed_at=NOW + timedelta(minutes=6))])
    assert future.observations == ()
    assert "FUTURE_MARKET_OBSERVATION_EXCLUDED" in future.degraded_reasons
    bad = _snapshot(markets=[_market(cap=-1)])
    assert bad.observations == ()
    assert "BAD_MARKET_ECONOMICS_EXCLUDED" in bad.degraded_reasons


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self):
        self.calls = []
        self.closed = False

    def get(self, url, params=None, headers=None):
        self.calls.append((url, params, headers))
        if url.endswith("/asset_platforms"):
            return FakeResponse(_platforms())
        if url.endswith("/coins/list"):
            return FakeResponse([_coin()])
        if url.endswith("/coins/markets"):
            return FakeResponse([_market()])
        raise AssertionError(url)

    def close(self):
        self.closed = True


def test_provider_uses_three_explicit_source_calls_and_no_generic_tvl():
    client = FakeClient()
    provider = CoinGeckoBnbRwaProvider(
        api_key="test-key", client_factory=lambda: client, now=lambda: NOW,
    )
    snapshot = provider.read_snapshot()
    assert snapshot.state.value == "AVAILABLE"
    assert len(client.calls) == 3 and client.closed
    assert client.calls[2][1]["category"] == "tokenized-products"
    assert client.calls[2][1]["page"] == 1
    assert client.calls[2][1]["per_page"] == 250
    assert all(call[2] == {"x-cg-demo-api-key": "test-key"} for call in client.calls)
    assert not any("defillama" in call[0].lower() for call in client.calls)
    assert snapshot.rwa_tvl_usd is None


def test_missing_key_fails_closed_without_network_or_invented_values():
    snapshot = CoinGeckoBnbRwaProvider(api_key="", now=lambda: NOW).read_snapshot()
    assert snapshot.state.value == "UNAVAILABLE"
    assert snapshot.reason == "COINGECKO_DEMO_API_KEY_NOT_CONFIGURED"
    assert snapshot.observations == ()
    assert snapshot.observed_market_cap_usd is None


def test_json_and_html_report_unavailable_robinhood_binding_and_tvl():
    payload = serialize_bnb_snapshot(_snapshot())
    assert payload["market_scope"] == GLOBAL_MARKET_SCOPE
    assert payload["rwa_tvl_usd"] is None
    assert payload["observations"][0]["asset_key"]["chain_id"] == 56
    assert payload["observations"][0]["robinhood_binding"] == "IDENTITY_UNAVAILABLE"

    class Service:
        def read_payload(self):
            return payload

    previous = rwa_router._bnb_service
    rwa_router.set_bnb_service(Service())
    try:
        app = FastAPI()
        app.include_router(rwa_router.router)
        client = TestClient(app)
        response = client.get("/radar/crypto/rwa/bnb")
        assert response.status_code == 200
        assert "BNB Tokenized Assets" in response.text
        assert "Robinhood economic binding: Unavailable" in response.text
        assert "not BNB-specific market size" in response.text
        assert "No trading, custody" in response.text
        assert "href=\"/radar/crypto/rwa\"" in response.text
        assert client.get("/radar/crypto/rwa/bnb/snapshot").json()["rwa_tvl_usd"] is None
    finally:
        rwa_router.set_bnb_service(previous)
