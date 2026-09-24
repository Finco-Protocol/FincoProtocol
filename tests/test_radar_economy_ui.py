"""Radar Economy UI — deterministic, offline browser-surface tests."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.radar_ui import economy_router as economy_router_module
from app.radar_ui import router as radar_router_module


class FakeEconomyService:
    def __init__(self, dashboard):
        self.dashboard = dashboard
        self.calls = 0

    def read_dashboard(self):
        self.calls += 1
        return self.dashboard


def _dashboard(*, state="PARTIAL", row_state="FRESH", reason=None):
    row = {
        "key": "treasury_10y",
        "title": "U.S. Treasury 10Y",
        "state": row_state,
        "value": 4.12 if row_state != "UNAVAILABLE" else None,
        "value_display": "4.12%" if row_state != "UNAVAILABLE" else "—",
        "previous": 4.09 if row_state != "UNAVAILABLE" else None,
        "previous_display": "4.09%" if row_state != "UNAVAILABLE" else "—",
        "trend": "UP" if row_state != "UNAVAILABLE" else "FLAT",
        "period": "2026-09-23" if row_state != "UNAVAILABLE" else None,
        "retrieved_at": "2026-09-24T12:00:00+00:00",
        "frequency": "daily",
        "unit": "percent",
        "source_series_id": "DGS10",
        "publisher": "Board of Governors of the Federal Reserve System (US)",
        "transport": "FRED",
        "source_url": "https://fred.stlouisfed.org/series/DGS10",
        "reason": reason,
    }
    return {
        "state": state,
        "metric_count": 1,
        "fresh_count": 1 if row_state == "FRESH" else 0,
        "stale_count": 1 if row_state == "STALE" else 0,
        "unavailable_count": 1 if row_state == "UNAVAILABLE" else 0,
        "sections": [{"key": "overview", "title": "Economy Overview", "rows": [row]}],
    }


def _client(service):
    economy_router_module.set_economy_service(service)
    app = FastAPI()
    app.include_router(radar_router_module.router)
    return TestClient(app)


def test_economy_route_is_registered_on_root_radar_router():
    paths = {getattr(route, "path", None) for route in radar_router_module.router.routes}
    assert "/radar/economy" in paths


def test_economy_page_renders_offline_dashboard_and_source_identity():
    service = FakeEconomyService(_dashboard())
    response = _client(service).get("/radar/economy")
    assert response.status_code == 200
    assert service.calls == 1
    assert "Economy Overview" in response.text
    assert "U.S. Treasury 10Y" in response.text
    assert "4.12%" in response.text
    assert "DGS10" not in response.text
    assert "Board of Governors of the Federal Reserve System (US)" not in response.text
    assert "via FRED" not in response.text


def test_unavailable_macro_row_shows_neutral_text_and_never_fabricates_value():
    service = FakeEconomyService(_dashboard(
        state="UNAVAILABLE", row_state="UNAVAILABLE", reason="FRED_API_KEY_NOT_CONFIGURED"))
    response = _client(service).get("/radar/economy")
    assert response.status_code == 200
    assert "FRED_API_KEY_NOT_CONFIGURED" not in response.text
    assert "Source data unavailable" in response.text
    assert "UNAVAILABLE" in response.text
    assert "4.12%" not in response.text
    assert "—" in response.text


def test_domain_navigation_exposes_stocks_crypto_and_economy():
    template = Path("app/templates/radar/domain_nav.html").read_text(encoding="utf-8")
    assert 'href="/radar"' in template
    assert 'href="/radar/crypto"' in template
    assert 'href="/radar/economy"' in template
    assert 'aria-disabled="true"' not in template


def test_stock_surface_includes_shared_domain_navigation():
    template = Path("app/templates/radar/index.html").read_text(encoding="utf-8")
    assert '{% include "radar/domain_nav.html" %}' in template


def test_economy_route_failure_is_fail_closed():
    class BrokenService:
        def read_dashboard(self):
            raise RuntimeError("provider details must not leak")

    response = _client(BrokenService()).get("/radar/economy")
    assert response.status_code == 200
    assert "ECONOMY_DASHBOARD_UNAVAILABLE:RuntimeError" not in response.text
    assert "provider details must not leak" not in response.text
    assert "Source data unavailable" in response.text
    assert "No substitute values are displayed" in response.text
