"""Radar RWA — deterministic provider/service/UI tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.radar_rwa.coingecko import CoinGeckoRwaProvider
from app.radar_rwa.service import RwaDashboardService
from app.radar_ui import router as radar_router_module
from app.radar_ui import rwa_router as rwa_router_module

NOW = datetime(2026, 9, 24, 14, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
    def raise_for_status(self):
        return None
    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, universe, leaders, stocks):
        self.universe = universe
        self.leaders = leaders
        self.stocks = stocks
        self.calls = []
        self.closed = False
    def get(self, url, params=None, headers=None):
        self.calls.append((url, params, headers))
        if url.endswith("/rwas/list"):
            return FakeResponse(self.universe)
        if url.endswith("/rwas/markets") and params and params.get("asset_type") == "stock":
            return FakeResponse(self.stocks)
        if url.endswith("/rwas/markets"):
            return FakeResponse(self.leaders)
        raise AssertionError(url)
    def close(self):
        self.closed = True


def _universe():
    return [
        {"id": "gold", "symbol": "XAU", "name": "Gold", "asset_type": "commodity"},
        {"id": "nvidia", "symbol": "NVDA", "name": "NVIDIA", "asset_type": "stock"},
        {"id": "tesla", "symbol": "TSLA", "name": "Tesla", "asset_type": "stock"},
        {"id": "sp500-etf", "symbol": "SPY", "name": "SPDR S&P 500 ETF", "asset_type": "etf"},
    ]


def _market_row(rwa_id, symbol, name, asset_type, *, observed_at=NOW, mcap=100_000_000):
    return {
        "id": rwa_id,
        "symbol": symbol.lower(),
        "name": name,
        "asset_type": asset_type,
        "tokenized_market_data": {
            "current_price": 123.45,
            "market_cap": mcap,
            "total_volume": 5_000_000,
            "price_change_percentage_24h": 1.25,
            "price_change_percentage_7d_in_currency": 3.5,
            "price_change_percentage_30d_in_currency": -2.0,
            "last_updated": observed_at.isoformat().replace("+00:00", "Z"),
        },
    }


def _provider(*, observed_at=NOW):
    leaders = [
        _market_row("gold", "XAU", "Gold", "commodity", observed_at=observed_at, mcap=5_000_000_000),
        _market_row("nvidia", "NVDA", "NVIDIA", "stock", observed_at=observed_at, mcap=500_000_000),
    ]
    stocks = [
        _market_row("nvidia", "NVDA", "NVIDIA", "stock", observed_at=observed_at, mcap=500_000_000),
        _market_row("tesla", "TSLA", "Tesla", "stock", observed_at=observed_at, mcap=400_000_000),
    ]
    client = FakeClient(_universe(), leaders, stocks)
    provider = CoinGeckoRwaProvider(
        api_key="demo-key",
        client_factory=lambda: client,
        now=lambda: NOW,
    )
    return provider, client


def test_missing_key_fails_closed_without_market_values():
    snapshot = CoinGeckoRwaProvider(api_key="", now=lambda: NOW).read_snapshot()
    assert snapshot.state.value == "UNAVAILABLE"
    assert snapshot.reason == "COINGECKO_DEMO_API_KEY_NOT_CONFIGURED"
    assert snapshot.total_count == 0
    assert snapshot.leaders == ()


def test_provider_uses_three_source_bound_calls_and_counts_universe():
    provider, client = _provider()
    snapshot = provider.read_snapshot()
    assert snapshot.state.value == "AVAILABLE"
    assert snapshot.total_count == 4
    assert snapshot.stock_count == 2
    assert snapshot.commodity_count == 1
    assert snapshot.etf_count == 1
    assert len(snapshot.leaders) == 2
    assert len(snapshot.stock_leaders) == 2
    assert len(client.calls) == 3
    assert client.closed is True
    assert all(call[2] == {"x-cg-demo-api-key": "demo-key"} for call in client.calls)
    assert snapshot.stock_leaders[0].id == "nvidia"
    assert snapshot.stock_leaders[0].market_cap == 500_000_000
    assert snapshot.stock_leaders[0].state.value == "FRESH"


def test_old_market_timestamp_is_stale_not_silently_fresh():
    provider, _ = _provider(observed_at=NOW - timedelta(hours=2))
    snapshot = provider.read_snapshot()
    assert snapshot.state.value == "AVAILABLE"
    assert all(row.state.value == "STALE" for row in snapshot.leaders + snapshot.stock_leaders)


def test_market_identity_mismatch_fails_closed():
    universe = _universe()
    bad = [_market_row("nvidia", "NVDA", "Wrong Name", "stock")]
    client = FakeClient(universe, bad, bad)
    provider = CoinGeckoRwaProvider(api_key="demo-key", client_factory=lambda: client, now=lambda: NOW)
    snapshot = provider.read_snapshot()
    assert snapshot.state.value == "UNAVAILABLE"
    assert snapshot.reason == "COINGECKO_RWA_READ_FAILED:ValueError"
    assert snapshot.leaders == ()


def test_service_labels_tokenized_market_not_underlying_spot():
    provider, _ = _provider()
    dashboard = RwaDashboardService(provider=provider).read_dashboard()
    assert dashboard["state"] == "AVAILABLE"
    assert dashboard["counts"][1] == {"key": "stock", "title": "Tokenized Stocks", "value": 2}
    row = dashboard["sections"][1]["rows"][0]
    assert row["name"] == "NVIDIA"
    assert row["market_cap_display"] == "$500.00M"
    assert row["source_id"] == "rwa:nvidia"
    assert row["source_endpoint"] == "/rwas/markets"


class FakeRwaService:
    def read_dashboard(self):
        return {
            "state": "AVAILABLE",
            "counts": [{"key": "stock", "title": "Tokenized Stocks", "value": 2}],
            "sections": [{
                "key": "stocks",
                "title": "Tokenized Stocks",
                "subtitle": "Underlying equities aggregated across tracked token issuers",
                "rows": [{
                    "id": "nvidia", "symbol": "NVDA", "name": "NVIDIA", "asset_type": "stock",
                    "state": "FRESH", "current_price_display": "$123.45", "market_cap_display": "$500.00M",
                    "total_volume_display": "$5.00M", "change_24h": 1.25, "change_24h_display": "+1.25%",
                    "change_7d": 3.5, "change_7d_display": "+3.50%", "change_30d": -2.0,
                    "change_30d_display": "-2.00%", "observed_at": NOW.isoformat(), "source_id": "rwa:nvidia",
                }],
            }],
            "reason": None,
            "retrieved_at": NOW.isoformat(),
            "publisher": "CoinGecko", "transport": "CoinGecko Demo API",
            "list_source_url": "https://docs.coingecko.com/demo/reference/rwas-list",
            "markets_source_url": "https://docs.coingecko.com/demo/reference/rwas-markets",
        }


def _client(service):
    rwa_router_module.set_rwa_service(service)
    app = FastAPI()
    app.include_router(radar_router_module.router)
    return TestClient(app)


def test_rwa_route_is_registered_and_renders_authority_boundary():
    response = _client(FakeRwaService()).get("/radar/crypto/rwa")
    assert response.status_code == 200
    assert "RWA Terminal" in response.text
    assert "NVIDIA" in response.text
    assert "$500.00M" in response.text
    assert "No premium/discount or parity signal is inferred" in response.text
    assert "rwa:nvidia" in response.text


def test_rwa_route_failure_does_not_leak_exception_details():
    class BrokenService:
        def read_dashboard(self):
            raise RuntimeError("secret upstream diagnostic")
    response = _client(BrokenService()).get("/radar/crypto/rwa")
    assert response.status_code == 200
    assert "RWA_DASHBOARD_UNAVAILABLE:RuntimeError" in response.text
    assert "secret upstream diagnostic" not in response.text
    assert "No replacement identities or substitute market values are displayed" in response.text


def test_crypto_subnav_exposes_live_rwa_route():
    template = Path("app/templates/radar/crypto_subnav.html").read_text(encoding="utf-8")
    assert 'href="/radar/crypto/rwa"' in template
    assert "RWA · next" not in template
