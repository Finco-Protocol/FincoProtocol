"""Post-R12 P2 — N04 real-browser mobile containment proof.

Launches a real headless Chromium against a live uvicorn server serving
the REAL ``main_web.app`` (with an offline fake-provider P1 service) and
asserts at 390 px (mobile) and 1440 px (desktop):

- ``document.documentElement.scrollWidth <= window.innerWidth`` (plus a
  2 px browser-rounding tolerance) across three states: page shell,
  refreshed Radar panels, and an open Evidence Inspector.

Requires playwright + chromium; skipped automatically when the browser
harness is unavailable.
"""
from __future__ import annotations

import re
import socket
import threading
from datetime import datetime, timezone

import pytest

pytest.importorskip("playwright")
pytest.importorskip("uvicorn")

from playwright.sync_api import sync_playwright  # noqa: E402

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

WIDTH_TOLERANCE = 2  # demonstrable browser rounding tolerance, px


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def live_url():
    import main_web  # the REAL product ASGI app
    from app.radar_runtime.service import AcquisitionService, ServiceConfig
    from app.radar_runtime.snapshot_store import SnapshotStore
    from app.radar_ui import router as radar_router_module
    import uvicorn

    def fake_core(calls_box):
        def provider(request):
            calls_box.append(request)
            return {"evidence": {
                "asset": {"symbol": "AAPL",
                          "economicAssetUid": "AAPL",
                          "chainId": request.chain_id,
                          "contractAddress": request.contract_address},
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
            }, "observedAt": "2026-09-19T12:00:00+00:00"}
        return provider

    calls_box: list = []
    service = AcquisitionService(
        SnapshotStore(":memory:"),
        {"radar-core": fake_core(calls_box)},
        config=ServiceConfig(per_provider_timeout_seconds=5.0,
                             total_budget_seconds=10.0,
                             max_concurrent_providers=2),
        clock=lambda: NOW)
    radar_router_module.set_service(service)

    port = _free_port()
    config = uvicorn.Config(main_web.app, host="127.0.0.1", port=port,
                            log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        import time
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", calls_box
    server.should_exit = True
    thread.join(5)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        yield browser
        browser.close()


def _overflow_px(page) -> int:
    return page.evaluate(
        "document.documentElement.scrollWidth - window.innerWidth")


def _assert_contained(page, label: str):
    overflow = _overflow_px(page)
    assert overflow <= WIDTH_TOLERANCE, (
        f"{label}: document overflows viewport by {overflow}px "
        f"(scrollWidth={page.evaluate('document.documentElement.scrollWidth')}, "
        f"innerWidth={page.evaluate('window.innerWidth')})")


def test_n04_mobile_and_desktop_containment(live_url, browser):
    url, calls_box = live_url
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        # 1. page shell
        page.goto(f"{url}/radar", wait_until="domcontentloaded")
        page.wait_for_selector(".radar")
        _assert_contained(page, "390px page shell")

        # 2. refresh -> snapshot panels (htmx intercepts the form submit)
        page.click("button.refresh-btn")
        page.wait_for_selector('[data-panel="snapshot"]', timeout=15000)
        _assert_contained(page, "390px refreshed panels")

        # 3. open the Evidence Inspector
        page.click('a.inspector-link[href*="reference.price"]')
        page.wait_for_selector(".inspector", timeout=15000)
        _assert_contained(page, "390px Evidence Inspector")

        # snapshot binding: one acquisition, one snapshot id everywhere
        ids = set(re.findall(r"acq-snap:[0-9a-f]{64}", page.content()))
        assert len(calls_box) == 1
        assert len(ids) == 1
        snapshot_id = ids.pop()
        assert page.content().count(snapshot_id) >= 3

        # 4. desktop non-regression
        page.set_viewport_size({"width": 1440, "height": 900})
        page.wait_for_timeout(150)
        _assert_contained(page, "1440px desktop")
    finally:
        page.close()
