"""Radar Crypto Derivatives — deterministic provider/service/UI tests."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.radar_derivatives.hyperliquid import HyperliquidDerivativesProvider
from app.radar_derivatives.service import DerivativesDashboardService
from app.radar_ui import derivatives_router as derivatives_router_module
from app.radar_ui import router as radar_router_module

NOW = datetime(2026, 9, 24, 14, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []
        self.closed = False

    def post(self, url, json=None, headers=None):
        self.calls.append((url, json, headers))
        return FakeResponse(self.payload)

    def close(self):
        self.closed = True


def _payload():
    # ETH deliberately precedes BTC: provider must bind through universe index,
    # never assume fixed positions.
    return [
        {"universe": [
            {"name": "ETH", "szDecimals": 4, "maxLeverage": 50},
            {"name": "SOL", "szDecimals": 2, "maxLeverage": 20},
            {"name": "BTC", "szDecimals": 5, "maxLeverage": 50},
        ]},
        [
            {"markPx": "3200", "oraclePx": "3196", "funding": "0.0000125", "openInterest": "1000", "dayNtlVlm": "50000000", "premium": "0.0003"},
            {"markPx": "150", "oraclePx": "150", "funding": "0", "openInterest": "10", "dayNtlVlm": "100", "premium": "0"},
            {"markPx": "80000", "oraclePx": "79900", "funding": "-0.00001", "openInterest": "250", "dayNtlVlm": "100000000", "premium": "-0.0002"},
        ],
    ]


def test_provider_uses_one_public_meta_and_asset_context_request_and_uid_binding():
    client = FakeClient(_payload())
    provider = HyperliquidDerivativesProvider(client_factory=lambda: client, now=lambda: NOW)
    snapshot = provider.read()

    assert len(client.calls) == 1
    assert client.calls[0][1] == {"type": "metaAndAssetCtxs"}
    assert client.closed is True
    assert [asset.symbol for asset in snapshot.assets] == ["BTC", "ETH"]
    assert snapshot.assets[0].mark_price == pytest.approx(80000.0)
    assert snapshot.assets[0].source_id == "universe[2]=BTC"
    assert snapshot.assets[1].source_id == "universe[0]=ETH"


def test_provider_fails_closed_when_required_asset_is_missing():
    payload = _payload()
    payload[0]["universe"][2]["name"] = "XRP"
    client = FakeClient(payload)
    provider = HyperliquidDerivativesProvider(client_factory=lambda: client, now=lambda: NOW)
    with pytest.raises(ValueError, match="MISSING_REQUIRED_SYMBOLS"):
        provider.read()


def test_service_computes_oi_and_basis_only_from_same_bound_context():
    provider = HyperliquidDerivativesProvider(client_factory=lambda: FakeClient(_payload()), now=lambda: NOW)
    dashboard = DerivativesDashboardService(provider=provider).read_dashboard()
    assert dashboard["state"] == "AVAILABLE"
    by_symbol = {row["symbol"]: row for row in dashboard["assets"]}
    assert by_symbol["BTC"]["open_interest_usd"] == pytest.approx(20_000_000.0)
    assert by_symbol["ETH"]["open_interest_usd"] == pytest.approx(3_200_000.0)
    assert by_symbol["BTC"]["basis_bps"] == pytest.approx((80000 / 79900 - 1) * 10000)
    assert by_symbol["ETH"]["funding_bps"] == pytest.approx(0.125)
    assert dashboard["summary"]["combined_day_notional_volume_usd"] == pytest.approx(150_000_000.0)


def test_service_failure_is_unavailable_without_fallback_exchange():
    class BrokenProvider:
        def read(self):
            raise RuntimeError("upstream detail")

    dashboard = DerivativesDashboardService(provider=BrokenProvider()).read_dashboard()
    assert dashboard["state"] == "UNAVAILABLE"
    assert dashboard["assets"] == []
    assert dashboard["reason"] == "DERIVATIVES_READ_FAILED:RuntimeError"
    assert "upstream detail" not in dashboard["reason"]


class FakeDerivativesService:
    def read_dashboard(self):
        return {
            "state": "AVAILABLE",
            "asset_count": 1,
            "assets": [{
                "symbol": "BTC", "state": "AVAILABLE",
                "mark_price": 80000.0, "mark_price_display": "$80,000.00",
                "oracle_price": 79900.0, "oracle_price_display": "$79,900.00",
                "basis_bps": 12.5, "basis_bps_display": "+12.50 bp",
                "funding_rate": -0.00001, "funding_bps": -0.1, "funding_bps_display": "-0.10 bp",
                "open_interest_base": 250.0, "open_interest_usd": 20_000_000.0, "open_interest_usd_display": "$20.00M",
                "day_notional_volume_usd": 100_000_000.0, "day_notional_volume_usd_display": "$100.00M",
                "premium_bps": -2.0, "premium_bps_display": "-2.00 bp",
                "retrieved_at": NOW.isoformat(), "publisher": "Hyperliquid",
                "transport": "Hyperliquid Info API", "source_endpoint": "POST /info · metaAndAssetCtxs",
                "source_id": "universe[2]=BTC", "source_url": "https://example.invalid/docs",
            }],
            "summary": {
                "combined_open_interest_usd": 20_000_000.0,
                "combined_open_interest_usd_display": "$20.00M",
                "combined_day_notional_volume_usd": 100_000_000.0,
                "combined_day_notional_volume_usd_display": "$100.00M",
            },
            "retrieved_at": NOW.isoformat(), "publisher": "Hyperliquid",
            "transport": "Hyperliquid Info API", "source_endpoint": "POST /info · metaAndAssetCtxs",
            "source_url": "https://example.invalid/docs",
            "freshness_note": "Source has no observation timestamp; retrieval time only.",
        }


def _client(service):
    derivatives_router_module.set_derivatives_service(service)
    app = FastAPI()
    app.include_router(radar_router_module.router)
    return TestClient(app)


def test_derivatives_route_renders_exchange_bound_metrics():
    response = _client(FakeDerivativesService()).get("/radar/crypto/derivatives")
    assert response.status_code == 200
    assert "Perpetuals" in response.text
    assert "Hyperliquid" in response.text
    assert "$20.00M" in response.text
    assert "+12.50 bp" in response.text
    assert "whole-market aggregate" in response.text


def test_crypto_subnav_exposes_derivatives_and_keeps_rwa_disabled():
    template = Path("app/templates/radar/crypto_subnav.html").read_text(encoding="utf-8")
    assert 'href="/radar/crypto/derivatives"' in template
    assert "Derivatives · next" not in template
    assert "RWA · next" in template
    assert 'href="/radar/crypto/rwa"' not in template
