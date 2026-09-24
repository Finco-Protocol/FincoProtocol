"""Radar Stablecoins — deterministic provider/service/UI tests."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.radar_stablecoins.contracts import StablecoinAssetRecord, StablecoinSnapshot, StablecoinState
from app.radar_stablecoins.defillama import DefiLlamaStablecoinProvider
from app.radar_stablecoins.service import StablecoinDashboardService
from app.radar_ui import router as radar_router_module
from app.radar_ui import stablecoin_router as stablecoin_router_module

NOW = datetime(2026, 9, 24, 13, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, payload, *, fail=False):
        self.payload = payload
        self.fail = fail

    def raise_for_status(self):
        if self.fail:
            raise RuntimeError("upstream failed")

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, payload, *, fail=False):
        self.payload = payload
        self.fail = fail
        self.calls = []
        self.closed = False

    def get(self, url, params=None):
        self.calls.append((url, params))
        return FakeResponse(self.payload, fail=self.fail)

    def close(self):
        self.closed = True


def _asset(asset_id, symbol, current, day, week, month, price=1.0, peg_type="peggedUSD"):
    return {
        "id": str(asset_id),
        "name": symbol + " name",
        "symbol": symbol,
        "pegType": peg_type,
        "circulating": {"peggedUSD": current},
        "circulatingPrevDay": {"peggedUSD": day},
        "circulatingPrevWeek": {"peggedUSD": week},
        "circulatingPrevMonth": {"peggedUSD": month},
        "price": price,
    }


def _payload():
    return {"peggedAssets": [
        _asset(1, "USDT", 100.0, 99.0, 95.0, 90.0, 1.001),
        _asset(2, "USDC", 50.0, 49.0, 45.0, 40.0, 0.999),
        _asset(5, "DAI", 10.0, 9.0, 8.0, 7.0, 1.0),
        _asset(99, "EURX", 999.0, 999.0, 999.0, 999.0, 1.1, peg_type="peggedEUR"),
    ]}


def test_provider_uses_one_public_defillama_call_and_filters_to_usd_pegs():
    client = FakeClient(_payload())
    provider = DefiLlamaStablecoinProvider(client_factory=lambda: client, now=lambda: NOW)
    snapshot = provider.read_snapshot()
    assert snapshot.state is StablecoinState.AVAILABLE
    assert client.closed is True
    assert len(client.calls) == 1
    assert client.calls[0][0] == "https://stablecoins.llama.fi/stablecoins"
    assert client.calls[0][1] == {"includePrices": "true"}
    assert [asset.symbol for asset in snapshot.assets] == ["USDT", "USDC", "DAI"]
    assert snapshot.source_endpoint == "/stablecoins?includePrices=true"


def test_provider_failure_is_typed_unavailable_and_never_raises():
    client = FakeClient({}, fail=True)
    provider = DefiLlamaStablecoinProvider(client_factory=lambda: client, now=lambda: NOW)
    snapshot = provider.read_snapshot()
    assert snapshot.state is StablecoinState.UNAVAILABLE
    assert snapshot.assets == ()
    assert snapshot.reason == "DEFILLAMA_STABLECOINS_READ_FAILED:RuntimeError"


def test_malformed_usd_asset_fails_complete_snapshot_instead_of_biasing_total():
    payload = _payload()
    payload["peggedAssets"].append({
        "id": "404", "name": "Broken USD", "symbol": "BUSD?", "pegType": "peggedUSD",
        "circulating": {},
    })
    provider = DefiLlamaStablecoinProvider(
        client_factory=lambda: FakeClient(payload), now=lambda: NOW)
    snapshot = provider.read_snapshot()
    assert snapshot.state is StablecoinState.UNAVAILABLE
    assert snapshot.assets == ()
    assert snapshot.reason == "DEFILLAMA_STABLECOINS_READ_FAILED:ValueError"


def test_service_computes_total_supply_rotation_and_canonical_shares():
    provider = DefiLlamaStablecoinProvider(client_factory=lambda: FakeClient(_payload()), now=lambda: NOW)
    dashboard = StablecoinDashboardService(provider=provider).read_dashboard()
    rows = {row["key"]: row for row in dashboard["summary_rows"]}
    assert dashboard["state"] == "AVAILABLE"
    assert rows["total_supply_usd"]["value"] == pytest.approx(160.0)
    assert rows["total_supply_usd"]["change_1d"] == pytest.approx((160 / 157 - 1) * 100)
    assert rows["total_supply_usd"]["change_7d"] == pytest.approx((160 / 148 - 1) * 100)
    assert rows["total_supply_usd"]["change_30d"] == pytest.approx((160 / 137 - 1) * 100)
    assert rows["usdt_share"]["value"] == pytest.approx(62.5)
    assert rows["usdc_share"]["value"] == pytest.approx(31.25)
    assert rows["tracked_count"]["value"] == pytest.approx(3.0)
    assert dashboard["top_assets"][0]["symbol"] == "USDT"


def test_usdt_and_usdc_bind_to_exact_defillama_ids_not_ticker_only():
    snapshot = StablecoinSnapshot(
        state=StablecoinState.AVAILABLE,
        retrieved_at=NOW,
        assets=(
            StablecoinAssetRecord("777", "Fake Tether", "USDT", "peggedUSD", 100.0, 99.0, 98.0, 97.0, 1.0),
            StablecoinAssetRecord("2", "USD Coin", "USDC", "peggedUSD", 50.0, 49.0, 48.0, 47.0, 1.0),
        ),
        publisher="DefiLlama",
        transport="DefiLlama Stablecoins API",
        source_endpoint="/stablecoins?includePrices=true",
    )

    class Provider:
        def read_snapshot(self):
            return snapshot

    dashboard = StablecoinDashboardService(provider=Provider()).read_dashboard()
    rows = {row["key"]: row for row in dashboard["summary_rows"]}
    assert dashboard["state"] == "PARTIAL"
    assert rows["usdt_supply_usd"]["state"] == "UNAVAILABLE"
    assert rows["usdt_supply_usd"]["reason"] == "CANONICAL_ASSET_BINDING_UNAVAILABLE"
    assert rows["usdc_supply_usd"]["state"] == "AVAILABLE"


class FakeService:
    def __init__(self, dashboard):
        self.dashboard = dashboard
        self.calls = 0

    def read_dashboard(self):
        self.calls += 1
        return self.dashboard


def _ui_dashboard():
    return {
        "state": "AVAILABLE",
        "retrieved_at": NOW.isoformat(),
        "summary_rows": [{
            "key": "total_supply_usd",
            "title": "USD Stablecoin Supply",
            "state": "AVAILABLE",
            "value": 306_000_000_000.0,
            "value_display": "$306.00B",
            "change_1d": 0.1,
            "change_7d": 0.5,
            "change_30d": 1.0,
            "change_1d_display": "+0.10%",
            "change_7d_display": "+0.50%",
            "change_30d_display": "+1.00%",
            "price": None,
            "price_display": "—",
            "source_id": "sum:peggedUSD",
            "reason": None,
        }],
        "top_assets": [{
            "asset_id": "1",
            "name": "Tether",
            "symbol": "USDT",
            "supply": 183_000_000_000.0,
            "supply_display": "$183.00B",
            "price": 1.0,
            "price_display": "$1",
            "change_1d": 0.1,
            "change_7d": 0.2,
            "change_30d": 0.3,
            "change_1d_display": "+0.10%",
            "change_7d_display": "+0.20%",
            "change_30d_display": "+0.30%",
        }],
        "publisher": "DefiLlama",
        "transport": "DefiLlama Stablecoins API",
        "source_endpoint": "/stablecoins?includePrices=true",
        "source_url": "https://defillama.com/stablecoins",
        "reason": None,
    }


def _client(service):
    stablecoin_router_module.set_stablecoin_service(service)
    app = FastAPI()
    app.include_router(radar_router_module.router)
    return TestClient(app)


def test_stablecoin_route_renders_supply_rotation_and_source_identity():
    service = FakeService(_ui_dashboard())
    response = _client(service).get("/radar/crypto/stablecoins")
    assert response.status_code == 200
    assert service.calls == 1
    assert "Stablecoins" in response.text
    assert "USD Stablecoin Supply" in response.text
    assert "$306.00B" in response.text
    assert "+0.50%" in response.text
    assert "USDT" in response.text
    assert "DefiLlama" not in response.text
    assert "/stablecoins?includePrices=true" not in response.text


def test_stablecoin_route_failure_does_not_leak_exception_text():
    class BrokenService:
        def read_dashboard(self):
            raise RuntimeError("private upstream details")

    response = _client(BrokenService()).get("/radar/crypto/stablecoins")
    assert response.status_code == 200
    assert "STABLECOIN_DASHBOARD_UNAVAILABLE:RuntimeError" in response.text
    assert "private upstream details" not in response.text
    assert "No substitute supply or dominance values are displayed" in response.text
