"""Radar Crypto Overview — deterministic provider/service/UI tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.radar_crypto.coingecko import CoinGeckoCryptoProvider
from app.radar_crypto.contracts import CryptoObservation, CryptoSection, CryptoState
from app.radar_crypto.registry import SERIES, metrics_for_section
from app.radar_crypto.service import CryptoDashboardService
from app.radar_ui import crypto_router as crypto_router_module
from app.radar_ui import router as radar_router_module

NOW = datetime(2026, 9, 24, 13, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, global_payload, price_payload):
        self.global_payload = global_payload
        self.price_payload = price_payload
        self.calls = []
        self.closed = False

    def get(self, url, params=None, headers=None):
        self.calls.append((url, params, headers))
        if url.endswith("/global"):
            return FakeResponse(self.global_payload)
        if url.endswith("/simple/price"):
            return FakeResponse(self.price_payload)
        raise AssertionError(url)

    def close(self):
        self.closed = True


def _payloads(observed_at=NOW):
    ts = int(observed_at.timestamp())
    return (
        {
            "data": {
                "active_cryptocurrencies": 17397,
                "total_market_cap": {"usd": 2_621_040_321_355.04},
                "total_volume": {"usd": 95_133_256_404.37},
                "market_cap_percentage": {"btc": 57.95, "eth": 9.58},
                "market_cap_change_percentage_24h_usd": -1.61,
                "volume_change_percentage_24h_usd": 33.06,
                "updated_at": ts,
            }
        },
        {
            "bitcoin": {
                "usd": 80_000.0,
                "usd_24h_change": 2.5,
                "last_updated_at": ts,
            },
            "ethereum": {
                "usd": 3_200.0,
                "usd_24h_change": -1.25,
                "last_updated_at": ts,
            },
        },
    )


def test_registry_is_unique_and_split_into_expected_sections():
    keys = [definition.key for definition in SERIES]
    assert len(keys) == len(set(keys)) == 8
    assert len(metrics_for_section(CryptoSection.MARKET_OVERVIEW)) == 5
    assert len(metrics_for_section(CryptoSection.MAJOR_ASSETS)) == 3


def test_missing_coingecko_key_fails_closed_for_every_metric():
    provider = CoinGeckoCryptoProvider(api_key="", now=lambda: NOW)
    observations = provider.read_all(SERIES)
    assert len(observations) == len(SERIES)
    assert all(o.state is CryptoState.UNAVAILABLE for o in observations)
    assert all(o.value is None for o in observations)
    assert {o.reason for o in observations} == {"COINGECKO_DEMO_API_KEY_NOT_CONFIGURED"}


def test_provider_batches_two_calls_and_normalizes_global_and_major_assets():
    global_payload, price_payload = _payloads()
    client = FakeClient(global_payload, price_payload)
    provider = CoinGeckoCryptoProvider(
        api_key="demo-key",
        client_factory=lambda: client,
        now=lambda: NOW,
    )
    observations = provider.read_all(SERIES)
    by_key = {o.key: o for o in observations}

    assert len(client.calls) == 2
    assert client.closed is True
    assert client.calls[0][2] == {"x-cg-demo-api-key": "demo-key"}
    assert by_key["total_market_cap_usd"].value == pytest.approx(2_621_040_321_355.04)
    assert by_key["total_market_cap_usd"].change_24h == pytest.approx(-1.61)
    assert by_key["btc_price_usd"].value == pytest.approx(80_000.0)
    assert by_key["btc_price_usd"].change_24h == pytest.approx(2.5)
    assert by_key["eth_btc_ratio"].value == pytest.approx(0.04)
    assert all(o.state is CryptoState.FRESH for o in observations)


def test_old_source_timestamp_is_explicitly_stale():
    global_payload, price_payload = _payloads(NOW - timedelta(hours=1))
    client = FakeClient(global_payload, price_payload)
    provider = CoinGeckoCryptoProvider(
        api_key="demo-key",
        client_factory=lambda: client,
        now=lambda: NOW,
    )
    observations = provider.read_all(SERIES)
    assert all(o.state is CryptoState.STALE for o in observations)


def test_service_rejects_source_binding_mismatch():
    definition = SERIES[0]

    class BadProvider:
        def read_all(self, definitions):
            rows = []
            for d in definitions:
                rows.append(CryptoObservation(
                    key=d.key,
                    state=CryptoState.FRESH,
                    value=1.0,
                    change_24h=None,
                    observed_at=NOW,
                    retrieved_at=NOW,
                    source_endpoint=d.source_endpoint,
                    source_id=d.source_id,
                    publisher="Wrong Publisher" if d.key == definition.key else d.publisher,
                    transport=d.transport,
                ))
            return tuple(rows)

    dashboard = CryptoDashboardService(provider=BadProvider()).read_dashboard()
    rows = {
        row["key"]: row
        for section in dashboard["sections"]
        for row in section["rows"]
    }
    assert rows[definition.key]["state"] == "UNAVAILABLE"
    assert rows[definition.key]["reason"] == "SOURCE_BINDING_MISMATCH"
    assert rows[definition.key]["value"] is None


class FakeCryptoService:
    def __init__(self, dashboard):
        self.dashboard = dashboard
        self.calls = 0

    def read_dashboard(self):
        self.calls += 1
        return self.dashboard


def _ui_dashboard():
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


def _client(service):
    crypto_router_module.set_crypto_service(service)
    app = FastAPI()
    app.include_router(radar_router_module.router)
    return TestClient(app)


def test_crypto_route_is_registered_and_page_renders_market_data():
    service = FakeCryptoService(_ui_dashboard())
    response = _client(service).get("/radar/crypto")
    assert response.status_code == 200
    assert service.calls == 1
    assert "Crypto Overview" in response.text
    assert "Total Crypto Market Cap" in response.text
    assert "$2.62T" in response.text
    assert "+1.25%" in response.text
    assert "data.total_market_cap.usd" not in response.text
    assert "CoinGecko" not in response.text


def test_crypto_route_failure_does_not_leak_exception_message():
    class BrokenService:
        def read_dashboard(self):
            raise RuntimeError("secret upstream diagnostic")

    response = _client(BrokenService()).get("/radar/crypto")
    assert response.status_code == 200
    assert "CRYPTO_DASHBOARD_UNAVAILABLE:RuntimeError" not in response.text
    assert "secret upstream diagnostic" not in response.text
    assert "Source data unavailable" in response.text
    assert "No substitute market values are displayed" in response.text


def test_shared_domain_navigation_has_three_live_domains():
    template = Path("app/templates/radar/domain_nav.html").read_text(encoding="utf-8")
    assert 'href="/radar"' in template
    assert 'href="/radar/crypto"' in template
    assert 'href="/radar/economy"' in template
    assert 'aria-disabled="true"' not in template
