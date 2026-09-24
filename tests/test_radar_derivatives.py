"""Radar Crypto Derivatives V2 — deterministic provider/service/UI tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    def __init__(self, *, fail_types=None):
        self.calls = []
        self.closed = False
        self.fail_types = set(fail_types or ())

    def post(self, url, json=None, headers=None):
        body = json or {}
        self.calls.append((url, body, headers))
        request_type = body.get("type")
        if request_type in self.fail_types:
            raise RuntimeError(f"forced {request_type} failure")
        if request_type == "metaAndAssetCtxs":
            return FakeResponse(_primary_payload())
        if request_type == "fundingHistory":
            return FakeResponse(_funding_payload(body["coin"]))
        if request_type == "predictedFundings":
            return FakeResponse(_predicted_payload())
        raise AssertionError(f"unexpected request type {request_type}")

    def close(self):
        self.closed = True


def _ms(value):
    return int(value.timestamp() * 1000)


def _primary_payload():
    # ETH deliberately precedes BTC: provider must bind through universe index.
    return [
        {"universe": [
            {"name": "ETH", "szDecimals": 4, "maxLeverage": 50},
            {"name": "SOL", "szDecimals": 2, "maxLeverage": 20},
            {"name": "BTC", "szDecimals": 5, "maxLeverage": 50},
        ]},
        [
            {
                "markPx": "3200", "oraclePx": "3196", "prevDayPx": "3100",
                "midPx": "3198", "impactPxs": ["3194", "3202"],
                "funding": "0.0000125", "openInterest": "1000",
                "dayNtlVlm": "50000000", "premium": "0.0003",
            },
            {
                "markPx": "150", "oraclePx": "150", "prevDayPx": "151",
                "midPx": "150", "impactPxs": ["149.9", "150.1"],
                "funding": "0", "openInterest": "10",
                "dayNtlVlm": "100", "premium": "0",
            },
            {
                "markPx": "80000", "oraclePx": "79900", "prevDayPx": "76000",
                "midPx": "79950", "impactPxs": ["79900", "80000"],
                "funding": "-0.00001", "openInterest": "250",
                "dayNtlVlm": "100000000", "premium": "-0.0002",
            },
        ],
    ]


def _funding_payload(symbol):
    if symbol == "BTC":
        return [
            {
                "coin": "BTC", "fundingRate": "-0.00001", "premium": "-0.0002",
                "time": _ms(NOW - timedelta(hours=23)),
            },
            {
                "coin": "BTC", "fundingRate": "0.00002", "premium": "0.0001",
                "time": _ms(NOW - timedelta(hours=1)),
            },
        ]
    return [
        {
            "coin": "ETH", "fundingRate": "0.0000125", "premium": "0.0003",
            "time": _ms(NOW - timedelta(hours=22)),
        },
        {
            "coin": "ETH", "fundingRate": "0.0000125", "premium": "0.0002",
            "time": _ms(NOW - timedelta(hours=2)),
        },
    ]


def _predicted_payload():
    return [
        ["BTC", [
            ["BinPerp", {"fundingRate": "0.0001", "nextFundingTime": _ms(NOW + timedelta(hours=2))}],
            ["HlPerp", {"fundingRate": "0.0000125", "nextFundingTime": _ms(NOW + timedelta(hours=1))}],
            ["BybitPerp", {"fundingRate": "0.00008", "nextFundingTime": _ms(NOW + timedelta(hours=2))}],
        ]],
        ["ETH", [
            ["BinPerp", {"fundingRate": "0.00009", "nextFundingTime": _ms(NOW + timedelta(hours=2))}],
            ["HlPerp", {"fundingRate": "0.0000125", "nextFundingTime": _ms(NOW + timedelta(hours=1))}],
            ["BybitPerp", {"fundingRate": "0.00007", "nextFundingTime": _ms(NOW + timedelta(hours=2))}],
        ]],
        ["SOL", [["HlPerp", {"fundingRate": "0", "nextFundingTime": _ms(NOW + timedelta(hours=1))}]]],
    ]


def test_provider_binds_primary_context_and_reads_v2_auxiliary_endpoints():
    client = FakeClient()
    provider = HyperliquidDerivativesProvider(client_factory=lambda: client, now=lambda: NOW)
    snapshot = provider.read()

    assert client.closed is True
    assert [call[1]["type"] for call in client.calls] == [
        "metaAndAssetCtxs", "fundingHistory", "fundingHistory", "predictedFundings"
    ]
    history_calls = [call[1] for call in client.calls if call[1]["type"] == "fundingHistory"]
    assert [call["coin"] for call in history_calls] == ["BTC", "ETH"]
    assert all(call["endTime"] == _ms(NOW) for call in history_calls)
    assert all(call["startTime"] == _ms(NOW - timedelta(hours=24)) for call in history_calls)

    assert [asset.symbol for asset in snapshot.assets] == ["BTC", "ETH"]
    btc = snapshot.assets[0]
    assert btc.source_id == "universe[2]=BTC"
    assert btc.prev_day_price == pytest.approx(76000.0)
    assert btc.mid_price == pytest.approx(79950.0)
    assert btc.impact_bid_price == pytest.approx(79900.0)
    assert btc.impact_ask_price == pytest.approx(80000.0)
    assert btc.max_leverage == 50
    assert len(snapshot.funding_history) == 4
    assert len(snapshot.predicted_funding) == 6
    assert snapshot.funding_history_reason is None
    assert snapshot.predicted_funding_reason is None


def test_provider_auxiliary_failure_does_not_replace_primary_hyperliquid_context():
    client = FakeClient(fail_types={"fundingHistory"})
    provider = HyperliquidDerivativesProvider(client_factory=lambda: client, now=lambda: NOW)
    snapshot = provider.read()

    assert [asset.symbol for asset in snapshot.assets] == ["BTC", "ETH"]
    assert snapshot.funding_history == ()
    assert snapshot.funding_history_reason == "FUNDING_HISTORY_READ_FAILED:RuntimeError"
    assert len(snapshot.predicted_funding) == 6
    assert snapshot.predicted_funding_reason is None


def test_provider_fails_closed_when_required_primary_asset_is_missing():
    class MissingBtcClient(FakeClient):
        def post(self, url, json=None, headers=None):
            body = json or {}
            if body.get("type") == "metaAndAssetCtxs":
                payload = _primary_payload()
                payload[0]["universe"][2]["name"] = "XRP"
                return FakeResponse(payload)
            return super().post(url, json=json, headers=headers)

    provider = HyperliquidDerivativesProvider(
        client_factory=lambda: MissingBtcClient(), now=lambda: NOW
    )
    with pytest.raises(ValueError, match="MISSING_REQUIRED_SYMBOLS"):
        provider.read()


def test_service_computes_price_liquidity_funding_and_cross_venue_metrics():
    provider = HyperliquidDerivativesProvider(client_factory=FakeClient, now=lambda: NOW)
    dashboard = DerivativesDashboardService(provider=provider).read_dashboard()

    assert dashboard["state"] == "AVAILABLE"
    by_symbol = {row["symbol"]: row for row in dashboard["assets"]}
    btc = by_symbol["BTC"]
    assert btc["open_interest_usd"] == pytest.approx(20_000_000.0)
    assert btc["change_24h_pct"] == pytest.approx((80000 / 76000 - 1) * 100)
    assert btc["basis_bps"] == pytest.approx((80000 / 79900 - 1) * 10000)
    assert btc["oi_turnover"] == pytest.approx(5.0)
    assert btc["impact_spread_bps"] == pytest.approx((100 / 79950) * 10000)
    assert btc["max_leverage"] == 50

    assert dashboard["summary"]["combined_open_interest_usd"] == pytest.approx(23_200_000.0)
    assert dashboard["summary"]["combined_day_notional_volume_usd"] == pytest.approx(150_000_000.0)
    assert dashboard["summary"]["combined_oi_turnover"] == pytest.approx(150_000_000 / 23_200_000)
    assert dashboard["summary"]["funding_sign"] == "Mixed / flat"

    history = {row["symbol"]: row for row in dashboard["funding_history"]}
    assert dashboard["funding_history_state"] == "AVAILABLE"
    assert history["BTC"]["average_24h_bps"] == pytest.approx(0.05)
    assert history["BTC"]["sum_24h_bps"] == pytest.approx(0.10)
    assert history["BTC"]["sample_count"] == 2

    predicted = {row["symbol"]: row for row in dashboard["predicted_funding"]}
    assert dashboard["predicted_funding_state"] == "AVAILABLE"
    assert predicted["BTC"]["venues"]["HlPerp"]["rate_bps"] == pytest.approx(0.125)
    assert predicted["BTC"]["venues"]["BinPerp"]["rate_bps"] == pytest.approx(1.0)
    assert predicted["BTC"]["venues"]["BybitPerp"]["rate_bps"] == pytest.approx(0.8)
    assert predicted["BTC"]["spread_bps"] == pytest.approx(0.875)


def test_service_failure_is_unavailable_without_fallback_exchange_or_detail_leak():
    class BrokenProvider:
        def read(self):
            raise RuntimeError("upstream secret detail")

    dashboard = DerivativesDashboardService(provider=BrokenProvider()).read_dashboard()
    assert dashboard["state"] == "UNAVAILABLE"
    assert dashboard["assets"] == []
    assert dashboard["reason"] == "DERIVATIVES_READ_FAILED:RuntimeError"
    assert "upstream secret detail" not in dashboard["reason"]


class FakeDerivativesService:
    def read_dashboard(self):
        return {
            "state": "AVAILABLE",
            "asset_count": 1,
            "assets": [{
                "symbol": "BTC", "state": "AVAILABLE",
                "mark_price": 80000.0, "mark_price_display": "$80,000.00",
                "prev_day_price": 76000.0, "prev_day_price_display": "$76,000.00",
                "change_24h_pct": 5.26, "change_24h_display": "+5.26%",
                "oracle_price": 79900.0, "oracle_price_display": "$79,900.00",
                "mid_price": 79950.0, "mid_price_display": "$79,950.00",
                "basis_bps": 12.5, "basis_bps_display": "+12.50 bp",
                "funding_rate": -0.00001, "funding_bps": -0.1,
                "funding_bps_display": "-0.10 bp",
                "open_interest_base": 250.0, "open_interest_usd": 20_000_000.0,
                "open_interest_usd_display": "$20.00M",
                "day_notional_volume_usd": 100_000_000.0,
                "day_notional_volume_usd_display": "$100.00M",
                "oi_turnover": 5.0, "oi_turnover_display": "5.00x",
                "impact_bid_price": 79900.0, "impact_ask_price": 80000.0,
                "impact_spread_bps": 12.5, "impact_spread_bps_display": "+12.50 bp",
                "max_leverage": 50, "max_leverage_display": "50x",
                "premium_bps": -2.0, "premium_bps_display": "-2.00 bp",
                "retrieved_at": NOW.isoformat(), "publisher": "Hyperliquid",
                "transport": "Hyperliquid Info API",
                "source_endpoint": "POST /info · metaAndAssetCtxs",
                "source_id": "universe[2]=BTC",
                "source_url": "https://example.invalid/docs",
            }],
            "summary": {
                "combined_open_interest_usd": 20_000_000.0,
                "combined_open_interest_usd_display": "$20.00M",
                "combined_day_notional_volume_usd": 100_000_000.0,
                "combined_day_notional_volume_usd_display": "$100.00M",
                "combined_oi_turnover": 5.0,
                "combined_oi_turnover_display": "5.00x",
                "funding_sign": "Mixed / flat",
            },
            "funding_history_state": "AVAILABLE",
            "funding_history_reason": None,
            "funding_history": [{
                "symbol": "BTC", "current_funding_bps": -0.1,
                "current_funding_bps_display": "-0.10 bp",
                "average_24h_bps": 0.05, "average_24h_bps_display": "+0.05 bp",
                "sum_24h_bps": 0.1, "sum_24h_bps_display": "+0.10 bp",
                "sample_count": 24, "latest_observed_at": NOW.isoformat(),
                "latest_observed_at_display": "2026-09-24 14:00 UTC",
            }],
            "predicted_funding_state": "AVAILABLE",
            "predicted_funding_reason": None,
            "predicted_funding": [{
                "symbol": "BTC",
                "venues": {
                    "HlPerp": {"name": "Hyperliquid", "rate_bps": 0.125, "rate_bps_display": "+0.12 bp", "next_funding_at": NOW.isoformat(), "next_funding_at_display": "2026-09-24 15:00 UTC"},
                    "BinPerp": {"name": "Binance", "rate_bps": 1.0, "rate_bps_display": "+1.00 bp", "next_funding_at": NOW.isoformat(), "next_funding_at_display": "2026-09-24 16:00 UTC"},
                    "BybitPerp": {"name": "Bybit", "rate_bps": 0.8, "rate_bps_display": "+0.80 bp", "next_funding_at": NOW.isoformat(), "next_funding_at_display": "2026-09-24 16:00 UTC"},
                },
                "spread_bps": 0.875, "spread_bps_display": "0.88 bp",
            }],
            "retrieved_at": NOW.isoformat(),
            "publisher": "Hyperliquid", "transport": "Hyperliquid Info API",
            "source_endpoint": "POST /info",
            "source_url": "https://example.invalid/docs",
            "freshness_note": "Primary retrieval time only; history has timestamps.",
            "cross_venue_note": "Binance and Bybit predictions are Hyperliquid aggregated evidence.",
        }


def _client(service):
    derivatives_router_module.set_derivatives_service(service)
    app = FastAPI()
    app.include_router(radar_router_module.router)
    return TestClient(app)


def test_derivatives_route_renders_v2_leverage_liquidity_and_funding_surfaces():
    response = _client(FakeDerivativesService()).get("/radar/crypto/derivatives")
    assert response.status_code == 200
    assert "Perpetuals" in response.text
    assert "24h Volume / OI" in response.text
    assert "Impact Spread" in response.text
    assert "Max Lev." in response.text
    assert "24h Funding History" in response.text
    assert "Cross-Venue Predicted Funding" in response.text
    assert "Binance" in response.text
    assert "Bybit" in response.text
    assert "whole-market aggregate" in response.text


def test_crypto_subnav_exposes_derivatives_and_rwa():
    template = Path("app/templates/radar/crypto_subnav.html").read_text(encoding="utf-8")
    assert 'href="/radar/crypto/derivatives"' in template
    assert "Derivatives · next" not in template
    assert 'href="/radar/crypto/rwa"' in template
    assert "RWA · next" not in template
