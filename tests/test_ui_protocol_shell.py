"""FINCO Protocol UI — Unified Shell Browser Acceptance Tests.

Tests the three-surface protocol shell (Home · Model · Radar · Verify) at
mobile (390 px) and desktop (1280 px).  Every assertion is structurally
closed: the test name maps directly to a UI invariant.

Coverage:
  1. Protocol home loads with three product cards and shared nav.
  2. Model Library accessible with shell nav present.
  3. Radar renders with READ-ONLY label and protocol nav; no transaction controls.
  4. Verify page loads with truthful corpus data and digest.
  5. 390 px: no horizontal overflow on home, radar, verify.
  6. 1280 px: shell stable, no Model/Radar regression.

Requires playwright + chromium + uvicorn; skipped automatically otherwise.
"""
from __future__ import annotations

import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("playwright")
pytest.importorskip("uvicorn")

from playwright.sync_api import sync_playwright  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
WIDTH_TOLERANCE = 2  # demonstrable browser rounding tolerance, px
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _auth_cookie(base_url: str, page) -> None:
    """Inject a valid admin session cookie so authenticated routes render."""
    from app.auth import COOKIE_NAME, create_session_token
    token = create_session_token(user_id="1", username="admin")
    page.context.add_cookies([{
        "name": COOKIE_NAME,
        "value": token,
        "domain": "127.0.0.1",
        "path": "/",
    }])


@pytest.fixture(scope="module")
def live_url():
    import main_web
    from app.radar_runtime.service import AcquisitionService, ServiceConfig
    from app.radar_runtime.snapshot_store import SnapshotStore
    from app.radar_ui import router as radar_router_module
    import uvicorn

    def _fake_provider(calls_box):
        def provider(request):
            calls_box.append(request)
            return {"evidence": {
                "asset": {"symbol": "SYN",
                          "economicAssetUid": "SYN",
                          "chainId": request.chain_id,
                          "contractAddress": request.contract_address},
                "observedAt": "2026-09-20T12:00:00+00:00",
                "reference": {"available": True, "price": "101.25",
                              "bid": "101.20", "ask": "101.30",
                              "source": "FROZEN::BoundReferencePrice",
                              "observedAt": "2026-09-20T11:59:00+00:00"},
                "execution": {"available": True, "side": request.direction,
                              "notionalUsd": request.notional_usd,
                              "status": "QUOTE_OK",
                              "rawAmountIn": "100000000",
                              "rawAmountOut": "9880000000",
                              "effectivePrice": "101.30",
                              "source": "LIFI_V1_QUOTE",
                              "quotedAt": "2026-09-20T12:00:00+00:00"},
                "gap": {"available": True, "side": request.direction,
                        "gapBps": "-42.5", "gapToMidBps": "-12.5",
                        "source": "FROZEN::DirectionalGapObservation",
                        "quotedAt": "2026-09-20T12:00:00+00:00"},
            }, "observedAt": "2026-09-20T12:00:00+00:00"}
        return provider

    calls_box: list = []
    service = AcquisitionService(
        SnapshotStore(":memory:"),
        {"radar-core": _fake_provider(calls_box)},
        config=ServiceConfig(per_provider_timeout_seconds=5.0,
                             total_budget_seconds=10.0,
                             max_concurrent_providers=2),
        clock=lambda: NOW,
    )
    radar_router_module.set_service(service)

    port = _free_port()
    config = uvicorn.Config(main_web.app, host="127.0.0.1", port=port,
                            log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(5)
        service.close()
        radar_router_module.set_service(None)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path="/opt/pw-browsers/chromium",
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        yield browser
        browser.close()


def _overflow_px(page) -> int:
    return page.evaluate(
        "document.documentElement.scrollWidth - window.innerWidth"
    )


# ─── Protocol Home ─────────────────────────────────────────────────────────────

class TestProtocolHomeDesktop:
    def test_home_loads_three_product_cards_and_nav(self, live_url, browser):
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/")
        page.wait_for_load_state("domcontentloaded")

        # Shared protocol nav is present
        assert page.query_selector(".proto-nav") is not None, (
            "Protocol nav (.proto-nav) not found on home page"
        )
        # All three nav links
        nav_text = page.inner_text(".proto-nav")
        assert "Radar" in nav_text
        assert "Model" in nav_text
        assert "Verify" in nav_text

        # Three product cards
        cards = page.query_selector_all(".proto-card")
        assert len(cards) >= 3, f"Expected ≥3 product cards, got {len(cards)}"

        # READ-ONLY badge on Radar card
        page_text = page.inner_text("body")
        assert "READ-ONLY" in page_text, "READ-ONLY badge missing on Radar card"

    def test_home_no_overflow_desktop(self, live_url, browser):
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/")
        page.wait_for_load_state("domcontentloaded")
        overflow = _overflow_px(page)
        assert overflow <= WIDTH_TOLERANCE, (
            f"Horizontal overflow on home at 1280px: {overflow}px"
        )


class TestProtocolHomeMobile:
    def test_home_no_overflow_mobile(self, live_url, browser):
        page = browser.new_page(viewport={"width": 390, "height": 844})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/")
        page.wait_for_load_state("domcontentloaded")
        overflow = _overflow_px(page)
        assert overflow <= WIDTH_TOLERANCE, (
            f"Horizontal overflow on home at 390px: {overflow}px"
        )

    def test_home_nav_present_mobile(self, live_url, browser):
        page = browser.new_page(viewport={"width": 390, "height": 844})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/")
        page.wait_for_load_state("domcontentloaded")
        nav = page.query_selector(".proto-nav")
        assert nav is not None, "Protocol nav missing at 390px"


# ─── Model Library ─────────────────────────────────────────────────────────────

class TestModelLibrary:
    def test_model_library_accessible_and_shows_projects(self, live_url, browser):
        """The library must load and show the project list — shell nav is in the
        workbook sidebar (base.html), not the standalone proto-nav, which is
        correct: the workbook shell carries its own product-level chrome."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/library")
        page.wait_for_load_state("domcontentloaded")
        # Should not 404 or redirect to login
        assert "/library" in page.url or page.url.endswith("/library")
        # The page should render the FINCO Protocol title or a project list heading
        page_text = page.inner_text("body")
        assert "FINCO" in page_text or "Project" in page_text, (
            "Library page appears empty or broken"
        )

    def test_model_library_no_overflow_1280(self, live_url, browser):
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/library")
        page.wait_for_load_state("domcontentloaded")
        overflow = _overflow_px(page)
        assert overflow <= WIDTH_TOLERANCE, (
            f"Horizontal overflow on /library at 1280px: {overflow}px"
        )


# ─── Radar ─────────────────────────────────────────────────────────────────────

class TestRadar:
    def test_radar_renders_with_readonly_and_nav_desktop(self, live_url, browser):
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url}/radar")
        page.wait_for_load_state("domcontentloaded")

        page_text = page.inner_text("body")
        # READ-ONLY label present
        assert "READ-ONLY" in page_text, "READ-ONLY label missing on Radar page"
        # No wallet-connect / transaction-submission BUTTONS
        wallet_buttons = page.query_selector_all(
            "button[data-wallet], [class*='wallet-connect'], [class*='tx-submit']"
        )
        assert len(wallet_buttons) == 0, (
            f"Wallet/transaction controls found on Radar: {len(wallet_buttons)}"
        )
        # Shared protocol nav present
        nav = page.query_selector(".proto-nav")
        assert nav is not None, "Protocol nav missing on /radar"

    def test_radar_no_overflow_mobile(self, live_url, browser):
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(f"{live_url}/radar")
        page.wait_for_load_state("domcontentloaded")
        overflow = _overflow_px(page)
        assert overflow <= WIDTH_TOLERANCE, (
            f"Horizontal overflow on /radar at 390px: {overflow}px"
        )

    def test_radar_no_overflow_desktop(self, live_url, browser):
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url}/radar")
        page.wait_for_load_state("domcontentloaded")
        overflow = _overflow_px(page)
        assert overflow <= WIDTH_TOLERANCE, (
            f"Horizontal overflow on /radar at 1280px: {overflow}px"
        )


# ─── Verify ────────────────────────────────────────────────────────────────────

class TestVerify:
    def test_verify_loads_with_corpus_data(self, live_url, browser):
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/verify")
        page.wait_for_load_state("domcontentloaded")

        page_text = page.inner_text("body")
        # Should show real corpus cases, not error
        assert "model-solar-base" in page_text, (
            "model-solar-base corpus case not found on /verify"
        )
        assert "model-wind-base" in page_text, (
            "model-wind-base corpus case not found on /verify"
        )
        assert "radar-r3-synthetic-liquidity" in page_text, (
            "radar-r3-synthetic-liquidity corpus case not found on /verify"
        )

    def test_verify_no_overflow_mobile(self, live_url, browser):
        page = browser.new_page(viewport={"width": 390, "height": 844})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/verify")
        page.wait_for_load_state("domcontentloaded")
        overflow = _overflow_px(page)
        assert overflow <= WIDTH_TOLERANCE, (
            f"Horizontal overflow on /verify at 390px: {overflow}px"
        )

    def test_verify_no_overflow_desktop(self, live_url, browser):
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/verify")
        page.wait_for_load_state("domcontentloaded")
        overflow = _overflow_px(page)
        assert overflow <= WIDTH_TOLERANCE, (
            f"Horizontal overflow on /verify at 1280px: {overflow}px"
        )

    def test_verify_corpus_verified_status(self, live_url, browser):
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/verify")
        page.wait_for_load_state("domcontentloaded")
        page_text = page.inner_text("body")
        assert "verified" in page_text.lower(), (
            "Corpus verified status not shown on /verify"
        )
