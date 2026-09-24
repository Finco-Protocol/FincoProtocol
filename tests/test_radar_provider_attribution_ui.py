"""Radar provider attribution — prove provider names are absent from product surfaces.

Backend provenance (publisher, transport, source_endpoint, source_id, source_url)
must remain intact in service objects; only template rendering is changed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.radar_crypto.contracts import CryptoState
from app.radar_ui import crypto_router as crypto_router_module
from app.radar_ui import economy_router as economy_router_module
from app.radar_ui import router as radar_router_module
from app.radar_ui import rwa_router as rwa_router_module
from app.radar_ui import stablecoin_router as stablecoin_router_module

NOW = datetime(2026, 9, 24, 13, 0, tzinfo=timezone.utc)

# ── Provider names and implementation-detail strings that must NOT appear in UI ──

_PROVIDER_NAMES = [
    "CoinGecko",
    "DefiLlama",
    "Hyperliquid",
    "FRED",
    "Board of Governors",
    "Federal Reserve",
    "Bureau of Labor Statistics",
    "BLS",
]

_IMPL_DETAIL_STRINGS = [
    "transport + publisher",
    "/stablecoins?includePrices=true",
    "data.total_market_cap.usd",
    "Hyperliquid API documentation",
    "stablecoins.llama.fi",
]


# ── Minimal fake dashboards ──

def _crypto_dashboard():
    return {
        "state": "FRESH",
        "metric_count": 1,
        "fresh_count": 1,
        "stale_count": 0,
        "unavailable_count": 0,
        "sections": [{
            "key": "market-overview",
            "title": "Market Overview",
            "rows": [{
                "key": "total_market_cap_usd",
                "title": "Total Crypto Market Cap",
                "state": "FRESH",
                "value": 2_620_000_000_000.0,
                "value_display": "$2.62T",
                "change_24h": 1.25,
                "change_24h_display": "+1.25%",
                "observed_at": NOW.isoformat(),
                "retrieved_at": NOW.isoformat(),
                "unit": "usd_compact",
                "source_endpoint": "/global",
                "source_id": "data.total_market_cap.usd",
                "publisher": "CoinGecko",
                "transport": "CoinGecko Demo API",
                "source_url": "https://docs.coingecko.com/reference/crypto-global",
                "reason": None,
            }],
        }],
    }


def _economy_dashboard():
    row = {
        "key": "treasury_10y",
        "title": "U.S. Treasury 10Y",
        "state": "FRESH",
        "value": 4.12,
        "value_display": "4.12%",
        "previous": 4.09,
        "previous_display": "4.09%",
        "trend": "UP",
        "period": "2026-09-23",
        "retrieved_at": NOW.isoformat(),
        "frequency": "daily",
        "unit": "percent",
        "source_series_id": "DGS10",
        "publisher": "Board of Governors of the Federal Reserve System (US)",
        "transport": "FRED",
        "source_url": "https://fred.stlouisfed.org/series/DGS10",
        "reason": None,
    }
    return {
        "state": "FRESH",
        "metric_count": 1,
        "fresh_count": 1,
        "stale_count": 0,
        "unavailable_count": 0,
        "sections": [{"key": "overview", "title": "Economy Overview", "rows": [row]}],
    }


def _stablecoin_dashboard():
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


class _FakeService:
    def __init__(self, dashboard):
        self._dashboard = dashboard

    def read_dashboard(self):
        return self._dashboard


def _crypto_client(dashboard):
    crypto_router_module.set_crypto_service(_FakeService(dashboard))
    app = FastAPI()
    app.include_router(radar_router_module.router)
    return TestClient(app)


def _economy_client(dashboard):
    economy_router_module.set_economy_service(_FakeService(dashboard))
    app = FastAPI()
    app.include_router(radar_router_module.router)
    return TestClient(app)


def _stablecoin_client(dashboard):
    stablecoin_router_module.set_stablecoin_service(_FakeService(dashboard))
    app = FastAPI()
    app.include_router(radar_router_module.router)
    return TestClient(app)


# ── Provider names absent from product surfaces ──

@pytest.mark.parametrize("name", _PROVIDER_NAMES)
def test_provider_name_absent_from_crypto_overview(name):
    response = _crypto_client(_crypto_dashboard()).get("/radar/crypto")
    assert response.status_code == 200
    assert name not in response.text


@pytest.mark.parametrize("name", _PROVIDER_NAMES)
def test_provider_name_absent_from_economy(name):
    response = _economy_client(_economy_dashboard()).get("/radar/economy")
    assert response.status_code == 200
    assert name not in response.text


@pytest.mark.parametrize("name", _PROVIDER_NAMES)
def test_provider_name_absent_from_stablecoins(name):
    response = _stablecoin_client(_stablecoin_dashboard()).get("/radar/crypto/stablecoins")
    assert response.status_code == 200
    assert name not in response.text


@pytest.mark.parametrize("detail", _IMPL_DETAIL_STRINGS)
def test_impl_detail_absent_from_crypto_overview(detail):
    response = _crypto_client(_crypto_dashboard()).get("/radar/crypto")
    assert response.status_code == 200
    assert detail not in response.text


@pytest.mark.parametrize("detail", _IMPL_DETAIL_STRINGS)
def test_impl_detail_absent_from_stablecoins(detail):
    response = _stablecoin_client(_stablecoin_dashboard()).get("/radar/crypto/stablecoins")
    assert response.status_code == 200
    assert detail not in response.text


# ── Freshness states and timestamps still rendered ──

def test_fresh_state_still_rendered_on_crypto_overview():
    response = _crypto_client(_crypto_dashboard()).get("/radar/crypto")
    assert "FRESH" in response.text


def test_fresh_state_still_rendered_on_economy():
    response = _economy_client(_economy_dashboard()).get("/radar/economy")
    assert "FRESH" in response.text


def test_fresh_state_still_rendered_on_stablecoins():
    response = _stablecoin_client(_stablecoin_dashboard()).get("/radar/crypto/stablecoins")
    assert "AVAILABLE" in response.text


def test_unavailable_state_still_rendered_on_crypto_overview():
    dashboard = _crypto_dashboard()
    dashboard["state"] = "UNAVAILABLE"
    dashboard["reason"] = "CRYPTO_DASHBOARD_UNAVAILABLE:RuntimeError"
    response = _crypto_client(dashboard).get("/radar/crypto")
    assert "UNAVAILABLE" in response.text
    assert "No substitute market values are displayed" in response.text


def test_observed_timestamp_still_rendered_on_crypto_overview():
    response = _crypto_client(_crypto_dashboard()).get("/radar/crypto")
    assert NOW.isoformat()[:16] in response.text or "2026-09-24" in response.text


def test_period_still_rendered_on_economy():
    response = _economy_client(_economy_dashboard()).get("/radar/economy")
    assert "2026-09-23" in response.text


# ── Backend provenance contracts unchanged ──

def test_crypto_service_object_retains_publisher_field():
    dashboard = _crypto_dashboard()
    row = dashboard["sections"][0]["rows"][0]
    assert row["publisher"] == "CoinGecko"
    assert row["transport"] == "CoinGecko Demo API"
    assert row["source_endpoint"] == "/global"
    assert row["source_id"] == "data.total_market_cap.usd"
    assert row["source_url"] is not None


def test_economy_service_object_retains_publisher_field():
    dashboard = _economy_dashboard()
    row = dashboard["sections"][0]["rows"][0]
    assert row["publisher"] == "Board of Governors of the Federal Reserve System (US)"
    assert row["transport"] == "FRED"
    assert row["source_series_id"] == "DGS10"
    assert row["source_url"] is not None


def test_stablecoin_service_object_retains_publisher_field():
    dashboard = _stablecoin_dashboard()
    assert dashboard["publisher"] == "DefiLlama"
    assert dashboard["transport"] == "DefiLlama Stablecoins API"
    assert dashboard["source_endpoint"] == "/stablecoins?includePrices=true"
    assert dashboard["source_url"] is not None


# ── Correction A: raw provider reason codes suppressed from product surfaces ──

_PROVIDER_REASON_CODES = [
    "COINGECKO_DEMO_API_KEY_NOT_CONFIGURED",
    "COINGECKO_GLOBAL_READ_FAILED",
    "COINGECKO_PRICE_READ_FAILED",
    "COINGECKO_RWA_READ_FAILED",
    "FRED_API_KEY_NOT_CONFIGURED",
    "FRED_READ_FAILED",
    "DEFILLAMA_STABLECOINS_READ_FAILED",
    "HYPERLIQUID_READ_FAILED",
    "CRYPTO_DASHBOARD_UNAVAILABLE",
    "ECONOMY_DASHBOARD_UNAVAILABLE",
    "STABLECOIN_DASHBOARD_UNAVAILABLE",
    "RWA_DASHBOARD_UNAVAILABLE",
]


def _rwa_dashboard(*, reason=None):
    return {
        "state": "UNAVAILABLE" if reason else "AVAILABLE",
        "counts": [],
        "sections": [],
        "reason": reason,
        "retrieved_at": NOW.isoformat(),
        "publisher": "CoinGecko",
        "transport": "CoinGecko Demo API",
        "list_source_url": "https://example.com",
        "markets_source_url": "https://example.com",
    }


def _rwa_client(dashboard):
    rwa_router_module.set_rwa_service(_FakeService(dashboard))
    app = FastAPI()
    app.include_router(radar_router_module.router)
    return TestClient(app)


# Dashboard-level raw reason not visible

@pytest.mark.parametrize("code", _PROVIDER_REASON_CODES)
def test_raw_reason_absent_from_crypto_overview_dashboard(code):
    dashboard = _crypto_dashboard()
    dashboard["state"] = "UNAVAILABLE"
    dashboard["reason"] = f"{code}:SomeError"
    response = _crypto_client(dashboard).get("/radar/crypto")
    assert response.status_code == 200
    assert code not in response.text
    assert "Source data unavailable" in response.text


@pytest.mark.parametrize("code", _PROVIDER_REASON_CODES)
def test_raw_reason_absent_from_economy_dashboard(code):
    dashboard = _economy_dashboard()
    dashboard["state"] = "UNAVAILABLE"
    dashboard["reason"] = f"{code}:SomeError"
    dashboard["sections"] = []
    response = _economy_client(dashboard).get("/radar/economy")
    assert response.status_code == 200
    assert code not in response.text
    assert "Source data unavailable" in response.text


@pytest.mark.parametrize("code", _PROVIDER_REASON_CODES)
def test_raw_reason_absent_from_stablecoins_dashboard(code):
    dashboard = _stablecoin_dashboard()
    dashboard["state"] = "UNAVAILABLE"
    dashboard["reason"] = f"{code}:SomeError"
    response = _stablecoin_client(dashboard).get("/radar/crypto/stablecoins")
    assert response.status_code == 200
    assert code not in response.text
    assert "Source data unavailable" in response.text


@pytest.mark.parametrize("code", _PROVIDER_REASON_CODES)
def test_raw_reason_absent_from_rwa_dashboard(code):
    dashboard = _rwa_dashboard(reason=f"{code}:SomeError")
    response = _rwa_client(dashboard).get("/radar/crypto/rwa")
    assert response.status_code == 200
    assert code not in response.text
    assert "Source data unavailable" in response.text


# Row-level raw reason not visible

def test_raw_coingecko_reason_absent_from_crypto_overview_row():
    dashboard = _crypto_dashboard()
    row = dashboard["sections"][0]["rows"][0]
    row["state"] = "UNAVAILABLE"
    row["value_display"] = "—"
    row["reason"] = "COINGECKO_GLOBAL_READ_FAILED:HTTPStatusError"
    response = _crypto_client(dashboard).get("/radar/crypto")
    assert response.status_code == 200
    assert "COINGECKO_GLOBAL_READ_FAILED" not in response.text
    assert "Source data unavailable" in response.text


def test_raw_fred_reason_absent_from_economy_row():
    dashboard = _economy_dashboard()
    row = dashboard["sections"][0]["rows"][0]
    row["state"] = "UNAVAILABLE"
    row["value_display"] = "—"
    row["reason"] = "FRED_API_KEY_NOT_CONFIGURED"
    response = _economy_client(dashboard).get("/radar/economy")
    assert response.status_code == 200
    assert "FRED_API_KEY_NOT_CONFIGURED" not in response.text
    assert "Source data unavailable" in response.text


def test_raw_defillama_reason_absent_from_stablecoins_row():
    dashboard = _stablecoin_dashboard()
    row = dashboard["summary_rows"][0]
    row["state"] = "UNAVAILABLE"
    row["value_display"] = "—"
    row["reason"] = "DEFILLAMA_STABLECOINS_READ_FAILED:RuntimeError"
    response = _stablecoin_client(dashboard).get("/radar/crypto/stablecoins")
    assert response.status_code == 200
    assert "DEFILLAMA_STABLECOINS_READ_FAILED" not in response.text
    assert "Source data unavailable" in response.text


# Backend reason fields are preserved in service objects (not removed)

def test_backend_reason_field_preserved_in_crypto_service_object():
    dashboard = _crypto_dashboard()
    row = dashboard["sections"][0]["rows"][0]
    row["reason"] = "COINGECKO_GLOBAL_READ_FAILED:HTTPStatusError"
    assert row["reason"] == "COINGECKO_GLOBAL_READ_FAILED:HTTPStatusError"


def test_backend_reason_field_preserved_in_economy_service_object():
    dashboard = _economy_dashboard()
    row = dashboard["sections"][0]["rows"][0]
    row["reason"] = "FRED_API_KEY_NOT_CONFIGURED"
    assert row["reason"] == "FRED_API_KEY_NOT_CONFIGURED"


def test_backend_dashboard_reason_preserved_in_stablecoin_service_object():
    dashboard = _stablecoin_dashboard()
    dashboard["reason"] = "DEFILLAMA_STABLECOINS_READ_FAILED:RuntimeError"
    assert dashboard["reason"] == "DEFILLAMA_STABLECOINS_READ_FAILED:RuntimeError"
