"""Post-R12 P2 Correction A — real-browser integration ring.

Exercises the ACTUAL ``main_web.app`` composition root (real middleware
stack: SecurityHeadersMiddleware CSP, exception handling, static mount)
rather than a bare synthetic FastAPI app, with a fake-provider P1
service injected through the documented test seam.

No live external network is required.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.radar_runtime.service import AcquisitionService, ServiceConfig
from app.radar_runtime.snapshot_store import SnapshotStore

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

HTMX_HEADERS = {"HX-Request": "true"}


def _fake_core(calls: list):
    def provider(request):
        calls.append(request)
        return {
            "evidence": {
                "asset": {"symbol": "AAPL", "chainId": request.chain_id,
                          "contractAddress": request.contract_address,
                          "economicAssetUid": "AAPL"},
                "observedAt": "2026-09-19T12:00:00+00:00",
                "reference": {"available": True, "price": "101.25",
                              "bid": "101.20", "ask": "101.30",
                              "source": "FROZEN::BoundReferencePrice",
                              "observedAt": "2026-09-19T11:59:00+00:00"},
                "execution": {"available": True, "side": request.direction,
                              "notionalUsd": request.notional_usd,
                              "status": "QUOTE_OK",
                              "rawAmountIn": "100000000",
                              "rawAmountOut": "9880000000",
                              "effectivePrice": "101.30",
                              "source": "LIFI_V1_QUOTE",
                              "quotedAt": "2026-09-19T12:00:00+00:00"},
                "gap": {"available": True, "side": request.direction,
                        "gapBps": "-42.5", "gapToMidBps": "-12.5",
                        "source": "FROZEN::DirectionalGapObservation",
                        "quotedAt": "2026-09-19T12:00:00+00:00"},
            },
            "observedAt": "2026-09-19T12:00:00+00:00",
        }
    return provider


@pytest.fixture(scope="module")
def real_client():
    """The REAL main_web application with the real middleware stack, and
    the Radar router's service replaced by an offline fake provider."""
    from types import SimpleNamespace as SN

    import main_web  # the actual product composition root
    from app.radar_ui import composition, router as radar_router_module

    aapl_addr = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    _key = SN(chain_id=4663, contract_address=aapl_addr)
    _asset = SN(
        asset_uid="AAPL", token_symbol="AAPL", token_name="Apple Inc.",
        raw_evidence={"tokenDecimals": 18},
        deployment_for_chain=lambda c: _key if c == 4663 else None)
    _snap = SN(
        assets=[_asset],
        get_by_uid=lambda u: _asset if u == "AAPL" else None)

    def _offline_factory():
        return SN(
            fetch_snapshot=lambda: _snap,
            fetch_bound_reference=lambda sn, k: ({}, {}))

    composition.set_registry_factory(_offline_factory)

    calls: list = []
    service = AcquisitionService(
        SnapshotStore(":memory:"), {"radar-core": _fake_core(calls)},
        config=ServiceConfig(per_provider_timeout_seconds=2.0,
                             total_budget_seconds=5.0,
                             max_concurrent_providers=4),
        clock=lambda: NOW)
    radar_router_module.set_service(service)
    client = TestClient(main_web.app)
    yield client, calls
    radar_router_module.set_service(None)
    composition.set_registry_factory(None)


def test_integration_01_radar_route_on_real_app(real_client):
    client, _ = real_client
    response = client.get("/radar")
    assert response.status_code == 200
    assert "RADAR" in response.text.upper()
    # READ-ONLY branding removed from product chrome (chrome cleanup pass).
    # Execution simulation renders as Coming soon and remains disabled.
    assert "Coming soon" in response.text or "coming soon" in response.text.lower()


def test_integration_02_real_csp_self_only_scripts(real_client):
    client, _ = real_client
    response = client.get("/radar")
    csp = response.headers.get("content-security-policy")
    assert csp, "real middleware must attach the CSP header"
    assert "script-src 'self'" in csp
    assert "unpkg.com" not in csp


def test_integration_03_htmx_self_hosted_no_cdn(real_client):
    client, _ = real_client
    page = client.get("/radar").text
    assert "unpkg.com" not in page
    assert "/static/radar/vendor/htmx.min.js" in page
    asset = client.get("/static/radar/vendor/htmx.min.js")
    assert asset.status_code == 200
    assert len(asset.content) > 10000  # the real vendored library


def test_integration_04_refresh_form_has_post_fallback_semantics(real_client):
    client, _ = real_client
    page = client.get("/radar").text
    assert 'action="/radar/refresh"' in page
    assert 'method="post"' in page
    assert 'hx-post="/radar/refresh"' in page
    assert 'hx-target="#radar-panels"' in page


def test_integration_05_htmx_refresh_returns_fragment_one_snapshot(
    real_client):
    client, calls = real_client
    response = client.post("/radar/refresh",
                           data={"asset_uid": "AAPL", "direction": "BUY", "size": "100"},
                           headers=HTMX_HEADERS)
    assert response.status_code == 200
    assert "<!DOCTYPE html>" not in response.text  # fragment, not a page
    assert response.text.count("acq-snap:") >= 1
    assert len(calls) == 1


def test_integration_06_normal_post_fallback_returns_full_page(real_client):
    client, calls = real_client
    before = len(calls)
    # a DISTINCT request (different fingerprint) proves the fallback path
    # acquires and renders the full page for its own snapshot
    response = client.post("/radar/refresh",
                           data={"asset_uid": "AAPL", "direction": "SELL", "size": "1000"})
    assert response.status_code == 200
    assert "<!DOCTYPE html>" in response.text  # full Radar page
    assert response.text.count("acq-snap:") >= 1
    # the fallback POST performed its own single acquisition
    assert len(calls) == before + 1


def test_integration_07_inspector_on_real_app_zero_acquisition(real_client):
    client, calls = real_client
    refresh = client.post("/radar/refresh",
                          data={"asset_uid": "AAPL", "direction": "BUY", "size": "100"},
                          headers=HTMX_HEADERS)
    import re
    snapshot_id = re.search(r"acq-snap:[0-9a-f]{64}",
                            refresh.text).group(0)
    before = len(calls)
    inspector = client.get(
        f"/radar/inspector/{snapshot_id}/reference.price")
    assert inspector.status_code == 200
    assert "101.25" in inspector.text
    assert snapshot_id in inspector.text
    assert len(calls) == before
