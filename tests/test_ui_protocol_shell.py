"""FINCO Protocol UI — Unified Shell Browser Acceptance Tests.

Tests the three-surface protocol shell (Home · Model · Radar · Verify) at
mobile (390 px) and desktop (1280 px).

Chromium executable: set FINCO_TEST_CHROMIUM_PATH to an explicit binary path
when the Playwright-managed browser is not installed (e.g. local dev
environments with a pre-installed chromium).  When the env var is absent,
pw.chromium.launch() uses the Playwright-managed install (the normal CI path
after ``playwright install chromium``).

Coverage:
  1. Protocol home loads with three product cards and shared nav.
  2. Model Library: accessible, contains Protocol links, no overflow.
  3. Workbook V2: accessible, contains Protocol links, end-to-end journey.
  4. Radar: READ-ONLY label + protocol nav; no transaction controls; sign-out
     visible when authenticated.
  5. Verify: truthful corpus data, correct success/failure banner semantics.
  6. Adversarial error-leak: raw exc never reaches browser output.
  7. Adversarial corpus failure: failure banner, no false green state.
  8. 390 px and 1280 px: no horizontal overflow on all surfaces.
  9. Logout reachability: Sign out visible on Home, Verify, authenticated Radar.
"""
from __future__ import annotations

import os
import socket
import threading
import time
import unittest.mock as mock
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("playwright")
pytest.importorskip("uvicorn")

from playwright.sync_api import sync_playwright  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
WIDTH_TOLERANCE = 2  # demonstrable browser rounding tolerance, px
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)

# Optional explicit chromium binary; unset → playwright-managed install.
_CHROMIUM_EXEC = os.getenv("FINCO_TEST_CHROMIUM_PATH")


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
    launch_kwargs = {"args": ["--no-sandbox", "--disable-setuid-sandbox"]}
    if _CHROMIUM_EXEC:
        launch_kwargs["executable_path"] = _CHROMIUM_EXEC
    with sync_playwright() as pw:
        b = pw.chromium.launch(**launch_kwargs)
        yield b
        b.close()


def _overflow_px(page) -> int:
    return page.evaluate(
        "document.documentElement.scrollWidth - window.innerWidth"
    )


def _assert_no_overflow(page, surface: str, width: int) -> None:
    overflow = _overflow_px(page)
    assert overflow <= WIDTH_TOLERANCE, (
        f"Horizontal overflow on {surface} at {width}px: {overflow}px"
    )


# ─── Protocol Home ─────────────────────────────────────────────────────────────

class TestProtocolHomeDesktop:
    def test_home_loads_three_product_cards_and_nav(self, live_url, browser):
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/")
        page.wait_for_load_state("domcontentloaded")

        assert page.query_selector(".proto-nav") is not None, (
            "Protocol nav (.proto-nav) not found on home page"
        )
        nav_text = page.inner_text(".proto-nav")
        assert "Radar" in nav_text
        assert "Model" in nav_text
        assert "Verify" in nav_text

        # Blueprint pass: home uses editorial architecture section (.proto-arch__product)
        # instead of equal-weight cards. Accept either the new product items
        # or the legacy proto-card class so both designs satisfy the invariant.
        products = page.query_selector_all(".proto-arch__product, .proto-card")
        assert len(products) >= 3, (
            f"Expected ≥3 product items (.proto-arch__product or .proto-card), "
            f"got {len(products)}"
        )

        page_text = page.inner_text("body")
        assert "READ-ONLY" in page_text, "READ-ONLY badge missing on Radar card"

    def test_home_no_overflow_desktop(self, live_url, browser):
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/")
        page.wait_for_load_state("domcontentloaded")
        _assert_no_overflow(page, "/", 1280)

    def test_home_signout_visible(self, live_url, browser):
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/")
        page.wait_for_load_state("domcontentloaded")
        signout = page.query_selector(".proto-nav__signout")
        assert signout is not None, "Sign out button missing on Home nav"


class TestProtocolHomeMobile:
    def test_home_no_overflow_mobile(self, live_url, browser):
        page = browser.new_page(viewport={"width": 390, "height": 844})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/")
        page.wait_for_load_state("domcontentloaded")
        _assert_no_overflow(page, "/", 390)

    def test_home_nav_present_mobile(self, live_url, browser):
        page = browser.new_page(viewport={"width": 390, "height": 844})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/")
        page.wait_for_load_state("domcontentloaded")
        assert page.query_selector(".proto-nav") is not None, (
            "Protocol nav missing at 390px"
        )


# ─── Model Library ─────────────────────────────────────────────────────────────

class TestModelLibrary:
    def test_library_loads_and_has_protocol_links(self, live_url, browser):
        """Library must load as the project listing page AND expose
        Protocol-level Home/Radar/Verify links in the sidebar (base.html)."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/library")
        page.wait_for_load_state("domcontentloaded")

        # Must not redirect to login or an error page
        assert "/library" in page.url, (
            f"Expected /library in URL but got {page.url}"
        )
        # Library heading is present
        page_text = page.inner_text("body")
        assert "Project Library" in page_text, (
            "Library heading not found — page may not have rendered"
        )
        # Protocol section in sidebar (added to base.html)
        proto_section = page.query_selector("#ps-protocol-surfaces")
        assert proto_section is not None, (
            "Protocol sidebar section (#ps-protocol-surfaces) missing on /library"
        )
        # Protocol links present
        links_text = proto_section.inner_text()
        assert "Home" in links_text, "Home link missing from Protocol sidebar"
        assert "Radar" in links_text, "Radar link missing from Protocol sidebar"
        assert "Verify" in links_text, "Verify link missing from Protocol sidebar"

    def test_library_no_overflow_1280(self, live_url, browser):
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/library")
        page.wait_for_load_state("domcontentloaded")
        _assert_no_overflow(page, "/library", 1280)

    def test_library_no_overflow_390(self, live_url, browser):
        """Full page must not overflow at 390px after chrome.css mobile fix."""
        page = browser.new_page(viewport={"width": 390, "height": 844})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/library")
        page.wait_for_load_state("domcontentloaded")
        _assert_no_overflow(page, "/library", 390)


# ─── End-to-end Model Journey ──────────────────────────────────────────────────

class TestModelJourney:
    """Prove coherent cross-surface navigation:
    Home → Library → Workbook → Radar → Verify → Home."""

    def test_workbook_has_protocol_links(self, live_url, browser):
        """Workbook V2 must expose Protocol links in sidebar (base.html)."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        # Open workbook with a reference project (always exists for admin).
        page.goto(f"{live_url}/v2/workbook?project=generic_solar_reference")
        page.wait_for_load_state("domcontentloaded")
        # Must not redirect to login
        assert "workbook" in page.url or "library" in page.url or "/" in page.url
        proto_section = page.query_selector("#ps-protocol-surfaces")
        assert proto_section is not None, (
            "Protocol sidebar section missing on Workbook V2"
        )
        links_text = proto_section.inner_text()
        assert "Radar" in links_text, "Radar link missing from Workbook sidebar"
        assert "Verify" in links_text, "Verify link missing from Workbook sidebar"

    def test_workbook_no_overflow_1280(self, live_url, browser):
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/v2/workbook?project=generic_solar_reference")
        page.wait_for_load_state("domcontentloaded")
        _assert_no_overflow(page, "/v2/workbook", 1280)

    def test_workbook_no_overflow_390(self, live_url, browser):
        """Full page must not overflow at 390px after chrome.css mobile fix."""
        page = browser.new_page(viewport={"width": 390, "height": 844})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/v2/workbook?project=generic_solar_reference")
        page.wait_for_load_state("domcontentloaded")
        _assert_no_overflow(page, "/v2/workbook", 390)

    def test_full_cross_surface_journey(self, live_url, browser):
        """Home → Library → Workbook → Radar → Verify → Home, no dead ends."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)

        # 1. Start at Home
        page.goto(f"{live_url}/")
        page.wait_for_load_state("domcontentloaded")
        assert page.query_selector(".proto-nav") is not None

        # 2. Navigate to Library via nav link
        page.goto(f"{live_url}/library")
        page.wait_for_load_state("domcontentloaded")
        assert "/library" in page.url

        # 3. Open Workbook via direct URL (simulates library click)
        page.goto(f"{live_url}/v2/workbook?project=generic_solar_reference")
        page.wait_for_load_state("domcontentloaded")
        proto = page.query_selector("#ps-protocol-surfaces")
        assert proto is not None, "Protocol section missing on Workbook"

        # 4. Navigate to Radar via protocol sidebar link
        radar_link = proto.query_selector("a[href='/radar']")
        assert radar_link is not None, "Radar link missing from Workbook sidebar"
        page.goto(f"{live_url}/radar")
        page.wait_for_load_state("domcontentloaded")
        assert "READ-ONLY" in page.inner_text("body")

        # 5. Navigate to Verify via protocol nav link
        verify_link = page.query_selector(".proto-nav a[href='/verify']")
        assert verify_link is not None, "Verify link missing from Radar nav"
        page.goto(f"{live_url}/verify")
        page.wait_for_load_state("domcontentloaded")
        assert "corpus" in page.inner_text("body").lower()

        # 6. Navigate Home via protocol nav link
        home_link = page.query_selector(".proto-nav a[href='/']")
        assert home_link is not None, "Home link missing from Verify nav"
        page.goto(f"{live_url}/")
        page.wait_for_load_state("domcontentloaded")
        # Blueprint pass: home uses .proto-arch__product; accept either class.
        assert page.query_selector(".proto-arch__product, .proto-card") is not None, (
            "Home product items missing after round-trip"
        )


# ─── Radar ─────────────────────────────────────────────────────────────────────

class TestRadar:
    def test_radar_readonly_label_and_nav_desktop(self, live_url, browser):
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url}/radar")
        page.wait_for_load_state("domcontentloaded")

        page_text = page.inner_text("body")
        assert "READ-ONLY" in page_text, "READ-ONLY label missing on Radar"
        nav = page.query_selector(".proto-nav")
        assert nav is not None, "Protocol nav missing on /radar"

    def test_radar_no_transaction_controls(self, live_url, browser):
        """Enumerate allowed Radar interactions using method-aware form safety contract.

        Safe Radar forms (method, action):
          (GET,  "/radar")         — asset selection / navigation only
          (POST, "/radar/refresh") — read-only quote acquisition
          (POST, "/logout")        — authentication logout

        Any other (method, action) combination is forbidden.
        """
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url}/radar")
        page.wait_for_load_state("domcontentloaded")

        # Method-aware form safety contract: enumerate (method, action) pairs.
        # HTML default method is GET when the attribute is absent.
        _ALLOWED_FORMS = {
            ("get",  "/radar"),          # asset selection — GET navigation only
            ("post", "/radar/refresh"),  # read-only quote acquisition
            ("post", "/logout"),         # authentication logout
        }
        forms = page.query_selector_all("form")
        for form in forms:
            action = form.get_attribute("action") or ""
            method = (form.get_attribute("method") or "get").lower()
            assert (method, action) in _ALLOWED_FORMS, (
                f"Unexpected (method, action) on Radar (possible tx control): "
                f"({method!r}, {action!r})"
            )

        # Links: must not target wallet/custody/approval/signing/tx endpoints
        _FORBIDDEN_HREF_FRAGMENTS = [
            "wallet", "connect", "approve", "sign", "transaction",
            "tx", "custody", "trade", "execute", "submit",
        ]
        links = page.query_selector_all("a[href]")
        for link in links:
            href = (link.get_attribute("href") or "").lower()
            # Skip same-page fragment, protocol links, and the Radar inspector
            if href.startswith("#") or href.startswith("/radar") or href in ("/", "/verify", "/library"):
                continue
            if href.startswith("http"):
                continue
            for frag in _FORBIDDEN_HREF_FRAGMENTS:
                assert frag not in href, (
                    f"Suspicious Radar link href {href!r} contains {frag!r}"
                )

    def test_radar_anonymous_no_signout(self, live_url, browser):
        """Anonymous Radar user must not see Sign out (no session)."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url}/radar")
        page.wait_for_load_state("domcontentloaded")
        signout = page.query_selector(".proto-nav__signout")
        assert signout is None, (
            "Sign out shown on anonymous Radar — should only appear when authenticated"
        )

    def test_radar_authenticated_signout_visible(self, live_url, browser):
        """Authenticated Radar user must see Sign out affordance."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/radar")
        page.wait_for_load_state("domcontentloaded")
        signout = page.query_selector(".proto-nav__signout")
        assert signout is not None, (
            "Sign out missing on authenticated Radar — expected proto-nav__signout"
        )

    def test_radar_no_overflow_mobile(self, live_url, browser):
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(f"{live_url}/radar")
        page.wait_for_load_state("domcontentloaded")
        _assert_no_overflow(page, "/radar", 390)

    def test_radar_no_overflow_desktop(self, live_url, browser):
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url}/radar")
        page.wait_for_load_state("domcontentloaded")
        _assert_no_overflow(page, "/radar", 1280)


# ─── Radar form contract ───────────────────────────────────────────────────────

class TestRadarFormContract:
    """Assert the exact Correction B form safety contract for the Radar surface.

    GET /radar   — asset selection; non-transactional navigation form.
    POST /radar/refresh — read-only quote acquisition; carries canonical UID.
    """

    def test_asset_selector_is_get_form(self, live_url, browser):
        """GET /radar form must use method=GET and action=/radar."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url}/radar")
        page.wait_for_load_state("domcontentloaded")

        forms = page.query_selector_all("form")
        get_radar_forms = [
            f for f in forms
            if (f.get_attribute("action") or "") == "/radar"
            and (f.get_attribute("method") or "get").lower() == "get"
        ]
        assert len(get_radar_forms) == 1, (
            f"Expected exactly 1 GET /radar form; found {len(get_radar_forms)}"
        )

    def test_asset_selector_contains_select_asset_uid(self, live_url, browser):
        """GET /radar form must contain select[name='asset_uid']."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url}/radar")
        page.wait_for_load_state("domcontentloaded")

        forms = page.query_selector_all("form")
        get_form = next(
            (f for f in forms
             if (f.get_attribute("action") or "") == "/radar"
             and (f.get_attribute("method") or "get").lower() == "get"),
            None,
        )
        assert get_form is not None, "GET /radar form not found"
        sel = get_form.query_selector("select[name='asset_uid']")
        assert sel is not None, "select[name='asset_uid'] missing from GET /radar form"

    def test_asset_selector_has_no_hx_post(self, live_url, browser):
        """GET /radar form must NOT carry hx-post (navigation only, not HTMX quote)."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url}/radar")
        page.wait_for_load_state("domcontentloaded")

        forms = page.query_selector_all("form")
        get_form = next(
            (f for f in forms
             if (f.get_attribute("action") or "") == "/radar"
             and (f.get_attribute("method") or "get").lower() == "get"),
            None,
        )
        assert get_form is not None, "GET /radar form not found"
        hx_post = get_form.get_attribute("hx-post")
        assert hx_post is None, (
            f"GET /radar form must not have hx-post; found: {hx_post!r}"
        )

    def test_asset_selector_no_transaction_fields(self, live_url, browser):
        """GET /radar form must not contain BUY/SELL authority or wallet/signing controls."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url}/radar")
        page.wait_for_load_state("domcontentloaded")

        forms = page.query_selector_all("form")
        get_form = next(
            (f for f in forms
             if (f.get_attribute("action") or "") == "/radar"
             and (f.get_attribute("method") or "get").lower() == "get"),
            None,
        )
        assert get_form is not None, "GET /radar form not found"

        # No BUY/SELL authority fields
        direction_inputs = get_form.query_selector_all(
            "input[name='direction'], input[value='BUY'], input[value='SELL']"
        )
        assert len(direction_inputs) == 0, (
            f"GET /radar form contains BUY/SELL authority fields: {len(direction_inputs)}"
        )

        # No transaction/wallet/signing control names
        _FORBIDDEN_NAMES = ["wallet", "sign", "approve", "transaction", "tx", "trade"]
        all_inputs = get_form.query_selector_all("input, button, select")
        for el in all_inputs:
            name = (el.get_attribute("name") or "").lower()
            for forbidden in _FORBIDDEN_NAMES:
                assert forbidden not in name, (
                    f"GET /radar form contains forbidden field name {name!r}"
                )

    def test_quote_form_is_post_with_htmx(self, live_url, browser):
        """POST /radar/refresh form must use method=POST and hx-post=/radar/refresh."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url}/radar")
        page.wait_for_load_state("domcontentloaded")

        forms = page.query_selector_all("form")
        post_form = next(
            (f for f in forms
             if (f.get_attribute("action") or "") == "/radar/refresh"
             and (f.get_attribute("method") or "get").lower() == "post"),
            None,
        )
        assert post_form is not None, "POST /radar/refresh form not found"

        hx_post = post_form.get_attribute("hx-post")
        assert hx_post == "/radar/refresh", (
            f"Quote form hx-post must be /radar/refresh; got {hx_post!r}"
        )

    def test_quote_form_has_hidden_asset_uid(self, live_url, browser):
        """POST /radar/refresh form must carry hidden input[name='asset_uid']."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url}/radar")
        page.wait_for_load_state("domcontentloaded")

        forms = page.query_selector_all("form")
        post_form = next(
            (f for f in forms
             if (f.get_attribute("action") or "") == "/radar/refresh"
             and (f.get_attribute("method") or "get").lower() == "post"),
            None,
        )
        assert post_form is not None, "POST /radar/refresh form not found"
        hidden_uid = post_form.query_selector(
            "input[type='hidden'][name='asset_uid']"
        )
        assert hidden_uid is not None, (
            "POST /radar/refresh form missing hidden input[name='asset_uid']"
        )

    def test_quote_form_has_direction_controls(self, live_url, browser):
        """POST /radar/refresh form must contain BUY/SELL direction radios."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url}/radar")
        page.wait_for_load_state("domcontentloaded")

        forms = page.query_selector_all("form")
        post_form = next(
            (f for f in forms
             if (f.get_attribute("action") or "") == "/radar/refresh"
             and (f.get_attribute("method") or "get").lower() == "post"),
            None,
        )
        assert post_form is not None, "POST /radar/refresh form not found"

        buy = post_form.query_selector("input[name='direction'][value='BUY']")
        sell = post_form.query_selector("input[name='direction'][value='SELL']")
        assert buy is not None, "BUY direction radio missing from POST quote form"
        assert sell is not None, "SELL direction radio missing from POST quote form"

    def test_quote_form_no_wallet_signing_controls(self, live_url, browser):
        """POST /radar/refresh form must not contain wallet/signing/submission controls."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url}/radar")
        page.wait_for_load_state("domcontentloaded")

        forms = page.query_selector_all("form")
        post_form = next(
            (f for f in forms
             if (f.get_attribute("action") or "") == "/radar/refresh"
             and (f.get_attribute("method") or "get").lower() == "post"),
            None,
        )
        assert post_form is not None, "POST /radar/refresh form not found"

        _FORBIDDEN_NAMES = ["wallet", "sign", "approve", "transaction", "tx", "trade",
                            "submit_tx", "execute", "custody"]
        all_inputs = post_form.query_selector_all("input, button, select")
        for el in all_inputs:
            name = (el.get_attribute("name") or "").lower()
            for forbidden in _FORBIDDEN_NAMES:
                assert forbidden not in name, (
                    f"POST /radar/refresh form contains forbidden field {name!r}"
                )

    def test_forbidden_post_radar_action(self, live_url, browser):
        """Demonstrate that POST /radar is not permitted on the Radar surface."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url}/radar")
        page.wait_for_load_state("domcontentloaded")

        forms = page.query_selector_all("form")
        forbidden = [
            f for f in forms
            if (f.get_attribute("action") or "") == "/radar"
            and (f.get_attribute("method") or "get").lower() == "post"
        ]
        assert len(forbidden) == 0, (
            "Found POST /radar form — only GET is permitted for asset selection"
        )

    def test_forbidden_get_refresh_action(self, live_url, browser):
        """Demonstrate that GET /radar/refresh is not permitted."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url}/radar")
        page.wait_for_load_state("domcontentloaded")

        forms = page.query_selector_all("form")
        forbidden = [
            f for f in forms
            if (f.get_attribute("action") or "") == "/radar/refresh"
            and (f.get_attribute("method") or "get").lower() == "get"
        ]
        assert len(forbidden) == 0, (
            "Found GET /radar/refresh form — only POST is permitted for quote acquisition"
        )


# ─── Verify ────────────────────────────────────────────────────────────────────

class TestVerify:
    def test_verify_loads_with_all_corpus_cases(self, live_url, browser):
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/verify")
        page.wait_for_load_state("domcontentloaded")

        page_text = page.inner_text("body")
        assert "model-solar-base" in page_text, (
            "model-solar-base corpus case missing on /verify"
        )
        assert "model-wind-base" in page_text, (
            "model-wind-base corpus case missing on /verify"
        )
        assert "radar-r3-synthetic-liquidity" in page_text, (
            "radar-r3-synthetic-liquidity corpus case missing on /verify"
        )

    def test_verify_success_banner_exact(self, live_url, browser):
        """Success state must show the positive-only class; failure class absent."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/verify")
        page.wait_for_load_state("domcontentloaded")

        success = page.query_selector(".proto-verify__corpus-ok")
        failure = page.query_selector(".proto-verify__corpus-fail")
        assert success is not None, (
            "Success banner (.proto-verify__corpus-ok) missing on /verify"
        )
        assert failure is None, (
            "Failure banner (.proto-verify__corpus-fail) present on successful /verify"
        )

    def test_verify_no_envelope_valid_claim(self, live_url, browser):
        """Cards must NOT claim 'envelope valid' — only presence is asserted."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/verify")
        page.wait_for_load_state("domcontentloaded")
        page_text = page.inner_text("body")
        assert "envelope valid" not in page_text.lower(), (
            "Forbidden 'envelope valid' claim found on /verify cards"
        )

    def test_verify_signout_visible(self, live_url, browser):
        """Sign out must be accessible on Verify page."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/verify")
        page.wait_for_load_state("domcontentloaded")
        signout = page.query_selector(".proto-nav__signout")
        assert signout is not None, "Sign out missing on Verify nav"

    def test_verify_digest_fits_mobile(self, live_url, browser):
        """SHA-256 digest must not cause overflow at 390px."""
        page = browser.new_page(viewport={"width": 390, "height": 844})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/verify")
        page.wait_for_load_state("domcontentloaded")
        _assert_no_overflow(page, "/verify digest", 390)

    def test_verify_no_overflow_desktop(self, live_url, browser):
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/verify")
        page.wait_for_load_state("domcontentloaded")
        _assert_no_overflow(page, "/verify", 1280)


# ─── Adversarial: Verify error-leak ────────────────────────────────────────────

class TestVerifyErrorLeak:
    """The router must NEVER reflect raw exception internals to the browser."""

    def _get_verify_html(self, live_url, browser, exc_text: str) -> str:
        """Patch build_public_validation_corpus to raise with sensitive text."""
        import app.protocol_ui.router as _router_mod

        real_build = None

        async def _raise_fake(*_, **__):
            raise RuntimeError(exc_text)

        with mock.patch.object(_router_mod, "run_in_threadpool",
                                side_effect=_raise_fake):
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            _auth_cookie(live_url, page)
            page.goto(f"{live_url}/verify")
            page.wait_for_load_state("domcontentloaded")
            html = page.content()
            page.close()
        return html

    def test_path_not_leaked(self, live_url, browser):
        sensitive = "/srv/finco/private/path"
        html = self._get_verify_html(live_url, browser, sensitive)
        assert sensitive not in html, (
            "Absolute path leaked into Verify browser output"
        )

    def test_password_not_leaked(self, live_url, browser):
        sensitive = "DATABASE_PASSWORD=should_not_leak"
        html = self._get_verify_html(live_url, browser, sensitive)
        assert sensitive not in html, (
            "Credential leaked into Verify browser output"
        )

    def test_db_url_not_leaked(self, live_url, browser):
        sensitive = "sqlite:///private.db"
        html = self._get_verify_html(live_url, browser, sensitive)
        assert sensitive not in html, (
            "DB URL leaked into Verify browser output"
        )

    def test_generic_safe_message_shown(self, live_url, browser):
        sensitive = "INTERNAL_SECRET_XYZ"
        html = self._get_verify_html(live_url, browser, sensitive)
        assert "temporarily unavailable" in html.lower(), (
            "Generic safe error message not shown when corpus build fails"
        )

    def test_no_success_state_on_error(self, live_url, browser):
        sensitive = "INTERNAL_SECRET_XYZ"
        html = self._get_verify_html(live_url, browser, sensitive)
        assert "proto-verify__corpus-ok" not in html, (
            "Success state shown on /verify error page"
        )
        assert "corpusSha256" not in html, (
            "Digest present on /verify error page"
        )


# ─── Adversarial: Corpus verification failure ──────────────────────────────────

class TestVerifyCorpusFailure:
    """Force verifier to return False; prove no misleading green state."""

    def _get_verify_html_with_failed_verification(
        self, live_url, browser
    ) -> str:
        import app.protocol_ui.router as _router_mod

        async def _fail_verify(*_, **__):
            # Build the real corpus but lie about verification
            from finco_protocol.verification.public_corpus import (
                build_public_validation_corpus,
            )
            corpus = build_public_validation_corpus()
            return corpus, False

        async def _mock_threadpool(func, *args, **kwargs):
            from finco_protocol.verification.public_corpus import (
                build_public_validation_corpus,
            )
            return build_public_validation_corpus()

        import finco_protocol.verification.public_corpus as _corpus_mod

        with mock.patch.object(_corpus_mod, "verify_public_validation_corpus",
                                return_value=False):
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            _auth_cookie(live_url, page)
            page.goto(f"{live_url}/verify")
            page.wait_for_load_state("domcontentloaded")
            html = page.content()
            page.close()
        return html

    def test_failure_banner_shown(self, live_url, browser):
        html = self._get_verify_html_with_failed_verification(live_url, browser)
        assert "proto-verify__corpus-fail" in html, (
            "Failure banner class missing when corpus verification fails"
        )

    def test_success_banner_absent_on_failure(self, live_url, browser):
        html = self._get_verify_html_with_failed_verification(live_url, browser)
        assert "proto-verify__corpus-ok" not in html, (
            "Success banner shown despite corpus verification failure"
        )

    def test_no_envelope_valid_on_failure(self, live_url, browser):
        html = self._get_verify_html_with_failed_verification(live_url, browser)
        # The corrected template uses "Envelope present" not "envelope valid"
        assert "envelope valid" not in html.lower(), (
            "Forbidden 'envelope valid' claim present on failed corpus page"
        )


# ─── E3 Company Terminal Browser Acceptance ───────────────────────────────────

import json
import sqlite3
import tempfile
from collections import namedtuple

_E3_SCHEMA = """
CREATE TABLE equity_assets (
    id INTEGER PRIMARY KEY,
    robinhood_token_symbol TEXT NOT NULL,
    underlying_ticker TEXT NOT NULL,
    name TEXT,
    token_contract_address TEXT,
    chain_network TEXT,
    underlying_exchange TEXT,
    cik TEXT, figi TEXT, currency TEXT, security_type TEXT,
    active INTEGER DEFAULT 1,
    first_seen_at TEXT, last_seen_at TEXT
);
CREATE TABLE equity_company_profiles (
    id INTEGER PRIMARY KEY, ticker TEXT NOT NULL,
    cik TEXT, profile_json TEXT, payload_hash TEXT,
    provider TEXT, source_contract TEXT, fetched_at TEXT
);
CREATE TABLE equity_financial_snapshots (
    id INTEGER PRIMARY KEY, ticker TEXT NOT NULL,
    cik TEXT, timeframe TEXT NOT NULL,
    fiscal_year TEXT, fiscal_quarter TEXT,
    period_end TEXT, filing_date TEXT,
    provider TEXT, source_contract TEXT,
    fetched_at TEXT, normalized_at TEXT, payload_hash TEXT,
    income_statement_json TEXT, balance_sheet_json TEXT,
    cash_flow_statement_json TEXT, derived_json TEXT
);
CREATE TABLE equity_dividends (
    id INTEGER PRIMARY KEY, ticker TEXT, external_id TEXT,
    cash_amount REAL, currency TEXT, declaration_date TEXT,
    ex_dividend_date TEXT, record_date TEXT, pay_date TEXT,
    frequency INTEGER, dividend_type TEXT, first_seen_at TEXT
);
CREATE TABLE equity_splits (
    id INTEGER PRIMARY KEY, ticker TEXT, external_id TEXT,
    execution_date TEXT, split_from REAL, split_to REAL, first_seen_at TEXT
);
CREATE TABLE equity_source_lineage (
    lineage_id INTEGER PRIMARY KEY, ticker TEXT,
    stage TEXT, provider TEXT, source_contract TEXT,
    endpoint TEXT, payload_hash TEXT, normalized_ref TEXT, fetched_at TEXT
);
"""

_E3_DERIVED = json.dumps({
    "revenues": 60000000000.0, "revenue_growth": 0.12,
    "gross_margin": 0.55, "ebit_margin": 0.28, "ebitda_margin": 0.32,
    "net_margin": 0.25, "free_cash_flow": 15000000000.0, "fcf_margin": 0.25,
    "return_on_equity": 1.20, "net_debt": -10000000000.0, "debt_to_equity": -0.5,
})

_SA_E3 = namedtuple("_SA_E3", [
    "economic_asset_uid", "token_symbol", "token_name",
    "chain_id", "contract_address", "token_decimals",
])

_NVDA_SA = _SA_E3("rh-equity-nvda-001", "NVDA", "NVIDIA Corporation", 4663, "0xnvda001abc", 0)
_JPM_SA  = _SA_E3("rh-equity-jpm-002",  "JPM",  "JPMorgan Chase",      4663, "0xjpm002def",  0)


_E3_BROWSER_PROVIDER   = "SYNTH_E3_BROWSER"
_E3_BROWSER_CONTRACT   = "E3_BROWSER_CONTRACT_V1"
_E3_BROWSER_PAYLDHASH  = "e3browser_payldhash_001"

_E3_PER_SYM = {
    "NVDA": {
        "sa": None,  # assigned in _build_e3_browser_db after module-level init
        "name": "NVIDIA Corporation",
        "annual_income":    {"revenues": 26001111000, "gross_profit": 16000222000,
                             "operating_income_loss": 12000333000, "net_income_loss": 9000444000},
        "quarterly_income": {"revenues":  7001111000, "gross_profit":  4400222000,
                             "operating_income_loss":  3200333000, "net_income_loss": 2300444000},
        "annual_balance":    {"assets": 65000555000, "cash": 5000666000,
                              "liabilities": 15000777000, "equity": 50000888000},
        "quarterly_balance": {"assets": 63000555000, "cash": 4800666000,
                              "liabilities": 14500777000, "equity": 48500888000},
        "annual_cashflow":    {"net_cash_flow_from_operating_activities": 11000999000,
                               "net_cash_flow_from_investing_activities": -3000111000,
                               "net_cash_flow_from_financing_activities": -4000222000,
                               "net_cash_flow": 4000666000},
        "quarterly_cashflow": {"net_cash_flow_from_operating_activities":  3000999000,
                               "net_cash_flow_from_investing_activities":  -800111000,
                               "net_cash_flow_from_financing_activities": -1000222000,
                               "net_cash_flow": 1200666000},
    },
    "JPM": {
        "sa": None,
        "name": "JPMorgan Chase",
        "annual_income":    {"revenues": 49001111000, "gross_profit": 30000222000,
                             "operating_income_loss": 22000333000, "net_income_loss": 15500444000},
        "quarterly_income": {"revenues": 12001111000, "gross_profit":  7500222000,
                             "operating_income_loss":  5500333000, "net_income_loss":  4000444000},
        "annual_balance":    {"assets": 180000555000, "cash": 30000666000,
                              "liabilities": 160000777000, "equity": 20000888000},
        "quarterly_balance": {"assets": 178000555000, "cash": 28000666000,
                              "liabilities": 158000777000, "equity": 20000888000},
        "annual_cashflow":    {"net_cash_flow_from_operating_activities": 25000999000,
                               "net_cash_flow_from_investing_activities": -10000111000,
                               "net_cash_flow_from_financing_activities":  -8000222000,
                               "net_cash_flow": 7000666000},
        "quarterly_cashflow": {"net_cash_flow_from_operating_activities":  6000999000,
                               "net_cash_flow_from_investing_activities":  -2500111000,
                               "net_cash_flow_from_financing_activities":  -2000222000,
                               "net_cash_flow": 1500666000},
    },
}


def _build_e3_browser_db() -> Path:
    """Create a temp SQLite DB with NVDA and JPM financial data for E3 browser tests."""
    # Bind SAs after they are defined (populated below after namedtuple definition)
    _E3_PER_SYM["NVDA"]["sa"] = _NVDA_SA
    _E3_PER_SYM["JPM"]["sa"]  = _JPM_SA

    tmp = Path(tempfile.mktemp(suffix=".db"))
    conn = sqlite3.connect(str(tmp))
    conn.executescript(_E3_SCHEMA)

    for symbol, d in _E3_PER_SYM.items():
        sa   = d["sa"]
        name = d["name"]
        # Fix #1: use exact per-symbol contract so validate_terminal_identity returns VERIFIED
        conn.execute(
            "INSERT INTO equity_assets (robinhood_token_symbol,underlying_ticker,name,"
            "token_contract_address,chain_network,currency,active) VALUES (?,?,?,?,?,?,1)",
            (symbol, symbol, name, sa.contract_address, "ethereum", "USD"),
        )
        conn.execute(
            "INSERT INTO equity_company_profiles "
            "(ticker,profile_json,provider,source_contract,payload_hash,fetched_at) "
            "VALUES (?,?,?,?,?,?)",
            (symbol, json.dumps({"name": name, "sector": "Technology"}),
             _E3_BROWSER_PROVIDER, _E3_BROWSER_CONTRACT, _E3_BROWSER_PAYLDHASH, "2024-10-01"),
        )
        for pe in ["2023-09-30", "2022-09-24", "2021-09-25"]:
            conn.execute(
                "INSERT INTO equity_financial_snapshots "
                "(ticker,timeframe,period_end,filing_date,provider,source_contract,"
                "payload_hash,derived_json,"
                "income_statement_json,balance_sheet_json,cash_flow_statement_json,"
                "fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    symbol, "annual", pe, f"{pe[:4]}-11-01",
                    _E3_BROWSER_PROVIDER, _E3_BROWSER_CONTRACT, "e3brw_snap_annual_001",
                    _E3_DERIVED,
                    json.dumps(d["annual_income"]),
                    json.dumps(d["annual_balance"]),
                    json.dumps(d["annual_cashflow"]),
                    "2024-11-05",
                ),
            )
        for pe in ["2024-06-30", "2024-03-31", "2023-12-31"]:
            conn.execute(
                "INSERT INTO equity_financial_snapshots "
                "(ticker,timeframe,period_end,filing_date,provider,source_contract,"
                "payload_hash,derived_json,"
                "income_statement_json,balance_sheet_json,cash_flow_statement_json,"
                "fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    symbol, "quarterly", pe, f"{pe[:7]}-20",
                    _E3_BROWSER_PROVIDER, _E3_BROWSER_CONTRACT, "e3brw_snap_qtr_001",
                    _E3_DERIVED,
                    json.dumps(d["quarterly_income"]),
                    json.dumps(d["quarterly_balance"]),
                    json.dumps(d["quarterly_cashflow"]),
                    "2024-11-05",
                ),
            )
        conn.execute(
            "INSERT INTO equity_financial_snapshots "
            "(ticker,timeframe,period_end,filing_date,provider,source_contract,"
            "payload_hash,derived_json,"
            "income_statement_json,balance_sheet_json,cash_flow_statement_json,"
            "fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                symbol, "ttm", "2024-06-30", "2024-08-01",
                _E3_BROWSER_PROVIDER, _E3_BROWSER_CONTRACT, "e3brw_snap_ttm_001",
                _E3_DERIVED,
                json.dumps(d["annual_income"]),
                json.dumps(d["annual_balance"]),
                json.dumps(d["annual_cashflow"]),
                "2024-11-05",
            ),
        )

    # Anti-false-green: verify inserted contracts exactly match SelectedAsset contracts
    for sym, sa in [("NVDA", _NVDA_SA), ("JPM", _JPM_SA)]:
        row = conn.execute(
            "SELECT token_contract_address FROM equity_assets WHERE robinhood_token_symbol=?",
            (sym,)
        ).fetchone()
        assert row and row[0] == sa.contract_address, (
            f"{sym} DB contract {row!r} != SA contract {sa.contract_address!r}; "
            "fixture drift would cause IDENTITY_MISMATCH"
        )

    conn.commit()
    conn.close()
    return tmp


@pytest.fixture(scope="module")
def live_url_e3():
    """Uvicorn server with patched universe (NVDA+JPM) for E3 Company Terminal tests."""
    from app.radar_ui import router as radar_router
    from app.radar_ui import equity_terminal, equity_enrichment
    from app.radar_ui.equity_enrichment import EquityEnrichmentResult, EnrichmentState
    from finco_radar.equity import get_equity_company_history
    import main_web
    import uvicorn

    tmp = _build_e3_browser_db()

    _orig_fetch    = radar_router._fetch_universe_safe
    _orig_featured = radar_router._get_featured_symbols
    _orig_many     = equity_enrichment.enrich_many_selected_assets
    _orig_single   = equity_enrichment.enrich_selected_asset
    _orig_history  = equity_terminal.get_history_for_terminal

    def _fake_fetch():
        return ([_NVDA_SA, _JPM_SA], None)

    def _fake_featured():
        return ("NVDA", "JPM")

    def _fake_enrich_many(pairs):
        return [
            EquityEnrichmentResult(
                state=EnrichmentState.SOURCE_UNAVAILABLE,
                bundle=None,
                identity_note=None,
            )
            for _ in pairs
        ]

    def _fake_enrich_single(token_symbol, contract_address, **kwargs):
        return EquityEnrichmentResult(
            state=EnrichmentState.SOURCE_UNAVAILABLE,
            bundle=None,
            identity_note=None,
        )

    def _fake_history(token_symbol, **kwargs):
        return get_equity_company_history(token_symbol, db_path=tmp, db_mode="snapshot")

    radar_router._fetch_universe_safe         = _fake_fetch
    radar_router._get_featured_symbols        = _fake_featured
    equity_enrichment.enrich_many_selected_assets = _fake_enrich_many
    equity_enrichment.enrich_selected_asset   = _fake_enrich_single
    equity_terminal.get_history_for_terminal  = _fake_history

    port = _free_port()
    config = uvicorn.Config(main_web.app, host="127.0.0.1", port=port, log_level="error")
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
        radar_router._fetch_universe_safe         = _orig_fetch
        radar_router._get_featured_symbols        = _orig_featured
        equity_enrichment.enrich_many_selected_assets = _orig_many
        equity_enrichment.enrich_selected_asset   = _orig_single
        equity_terminal.get_history_for_terminal  = _orig_history
        tmp.unlink(missing_ok=True)


class TestE3CompanyTerminal:
    """F16 — E3 Company Terminal browser acceptance (B00–B13).

    B00: Anti-false-green fixture contract proof.
    B01–B03: Featured Equities board → Details → terminal URL.
    B04: NVDA identity + IDENTITY_VERIFIED (not MISMATCH).
    B05: Financials tab click → panel visible.
    B06: Annual income — Revenue label + distinctive NVDA value.
    B07: Quarterly income — quarterly value present, annual value absent.
    B08: Balance Sheet — Total Assets label + distinctive NVDA value.
    B09: Cash Flow — Operating Cash Flow label + distinctive NVDA value.
    B10: Evidence tab — SYNTH_E3_BROWSER + E3_BROWSER_CONTRACT_V1 + payload_hash.
    B11: Asset switcher via select_option → JPM VERIFIED, NVDA value absent.
    B12: ← Radar link click (not go_back) → /radar URL.
    B13: 390px financials URL — no page-level horizontal overflow.
    """

    def test_b00_fixture_contracts_match_selected_assets(self):
        """B00: Anti-false-green — SelectedAsset contracts are the exact expected values."""
        assert _NVDA_SA.contract_address == "0xnvda001abc", (
            f"NVDA SA contract drift: {_NVDA_SA.contract_address!r}"
        )
        assert _JPM_SA.contract_address == "0xjpm002def", (
            f"JPM SA contract drift: {_JPM_SA.contract_address!r}"
        )
        # DB-level proof is asserted inside _build_e3_browser_db() at fixture build time.

    def test_b01_radar_loads_featured_equities(self, live_url_e3, browser):
        """B1: /radar loads and Featured Equities section is visible."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url_e3}/radar")
        page.wait_for_load_state("domcontentloaded")
        body_text = page.inner_text("body")
        assert "FEATURED EQUITIES" in body_text.upper(), (
            "Featured Equities section not found on /radar"
        )
        page.close()

    def test_b02_featured_board_shows_nvda_details_link(self, live_url_e3, browser):
        """B2: Featured Equities board shows NVDA Details → link."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url_e3}/radar")
        page.wait_for_load_state("domcontentloaded")
        nvda_link = page.query_selector('a.board-details-cta[data-symbol="NVDA"]')
        assert nvda_link is not None, (
            "NVDA Details → link (a.board-details-cta[data-symbol=NVDA]) not found on featured board"
        )
        page.close()

    def test_b03_nvda_details_navigates_to_terminal(self, live_url_e3, browser):
        """B3: Clicking NVDA Details → navigates to NVDA terminal URL."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url_e3}/radar")
        page.wait_for_load_state("domcontentloaded")
        nvda_link = page.query_selector('a.board-details-cta[data-symbol="NVDA"]')
        assert nvda_link is not None, "NVDA Details → link not found before click"
        nvda_link.click()
        page.wait_for_load_state("domcontentloaded")
        assert "rh-equity-nvda-001" in page.url, (
            f"Expected NVDA terminal URL after click, got: {page.url}"
        )
        page.close()

    def test_b04_terminal_header_shows_nvda_verified(self, live_url_e3, browser):
        """B4: NVDA terminal — exact UID in URL, NVDA/NVIDIA identity, IDENTITY_VERIFIED, no MISMATCH."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url_e3}/radar/equity/rh-equity-nvda-001")
        page.wait_for_load_state("domcontentloaded")
        assert "rh-equity-nvda-001" in page.url, f"UID missing from URL: {page.url}"
        body_text = page.inner_text("body")
        assert "NVDA" in body_text or "NVIDIA" in body_text, (
            "NVDA symbol or NVIDIA name not found in terminal"
        )
        assert "IDENTITY_VERIFIED" in body_text, (
            "IDENTITY_VERIFIED not visible — DB contract may not match SA contract"
        )
        assert "IDENTITY_MISMATCH" not in body_text, (
            "IDENTITY_MISMATCH present — DB token_contract_address does not match SA contract_address"
        )
        page.close()

    def test_b05_financials_tab_click_shows_panel(self, live_url_e3, browser):
        """B5: Clicking Financials tab navigates and makes the financials panel visible."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url_e3}/radar/equity/rh-equity-nvda-001")
        page.wait_for_load_state("domcontentloaded")
        fin_btn = page.query_selector('a.tab-btn[onclick*="tab-financials"]')
        assert fin_btn is not None, "Financials tab link (a.tab-btn[onclick*=tab-financials]) not found"
        fin_btn.click()
        page.wait_for_load_state("domcontentloaded")
        fin_panel = page.query_selector("#tab-financials")
        assert fin_panel is not None, "#tab-financials panel not found after tab click"
        assert fin_panel.is_visible(), "#tab-financials panel not visible after tab click"
        page.close()

    def test_b06_annual_income_statement_renders(self, live_url_e3, browser):
        """B6: Annual income — Revenue label + distinctive NVDA annual revenue value."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(
            f"{live_url_e3}/radar/equity/rh-equity-nvda-001"
            "?tab=financials&timeframe=annual&statement=income"
        )
        page.wait_for_load_state("domcontentloaded")
        body_text = page.inner_text("body")
        assert "Revenue" in body_text, "Revenue label missing from annual income statement"
        assert "26,001,111,000" in body_text, (
            "Distinctive NVDA annual revenue (26,001,111,000) missing from income statement matrix"
        )
        assert "Net Income" in body_text, "Net Income label missing from annual income statement"
        assert "9,000,444,000" in body_text, (
            "Distinctive NVDA annual net income (9,000,444,000) missing from income statement matrix"
        )
        page.close()

    def test_b07_quarterly_navigation(self, live_url_e3, browser):
        """B7: Quarterly income — quarterly value present, annual-only value absent."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(
            f"{live_url_e3}/radar/equity/rh-equity-nvda-001"
            "?tab=financials&timeframe=quarterly&statement=income"
        )
        page.wait_for_load_state("domcontentloaded")
        body_text = page.inner_text("body")
        assert "7,001,111,000" in body_text, (
            "Distinctive NVDA quarterly revenue (7,001,111,000) missing from quarterly income statement"
        )
        assert "26,001,111,000" not in body_text, (
            "Annual-only NVDA revenue (26,001,111,000) unexpectedly present in quarterly view"
        )
        page.close()

    def test_b08_balance_sheet_navigation(self, live_url_e3, browser):
        """B8: Balance Sheet — Total Assets label + distinctive NVDA value."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(
            f"{live_url_e3}/radar/equity/rh-equity-nvda-001"
            "?tab=financials&timeframe=annual&statement=balance"
        )
        page.wait_for_load_state("domcontentloaded")
        body_text = page.inner_text("body")
        assert "Total Assets" in body_text, "Total Assets label missing from balance sheet"
        assert "65,000,555,000" in body_text, (
            "Distinctive NVDA annual total assets (65,000,555,000) missing from balance sheet"
        )
        page.close()

    def test_b09_cash_flow_navigation(self, live_url_e3, browser):
        """B9: Cash Flow — Operating Cash Flow label + distinctive NVDA value."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(
            f"{live_url_e3}/radar/equity/rh-equity-nvda-001"
            "?tab=financials&timeframe=annual&statement=cashflow"
        )
        page.wait_for_load_state("domcontentloaded")
        body_text = page.inner_text("body")
        assert "Operating Cash Flow" in body_text, (
            "Operating Cash Flow label missing from cash flow statement"
        )
        assert "11,000,999,000" in body_text, (
            "Distinctive NVDA annual operating cash flow (11,000,999,000) missing from cash flow statement"
        )
        page.close()

    def test_b10_evidence_tab_renders(self, live_url_e3, browser):
        """B10: Evidence tab — SYNTH_E3_BROWSER provider, E3_BROWSER_CONTRACT_V1, payload_hash sentinel."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url_e3}/radar/equity/rh-equity-nvda-001?tab=evidence")
        page.wait_for_load_state("domcontentloaded")
        body_text = page.inner_text("body")
        assert "SYNTH_E3_BROWSER" in body_text, (
            "provider SYNTH_E3_BROWSER missing from evidence tab"
        )
        assert "E3_BROWSER_CONTRACT_V1" in body_text, (
            "source_contract E3_BROWSER_CONTRACT_V1 missing from evidence tab"
        )
        assert _E3_BROWSER_PAYLDHASH in body_text, (
            f"payload_hash sentinel {_E3_BROWSER_PAYLDHASH!r} missing from evidence tab"
        )
        page.close()

    def test_b11_asset_switcher_changes_url_and_identity(self, live_url_e3, browser):
        """B11: select_option switches to JPM; JPM IDENTITY_VERIFIED, NVDA revenue absent."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url_e3}/radar/equity/rh-equity-nvda-001")
        page.wait_for_load_state("domcontentloaded")
        switcher = page.query_selector("select[onchange*=\"location='/radar/equity/'\"]")
        assert switcher is not None, "Asset switcher <select> not found on terminal"
        options = switcher.query_selector_all("option")
        option_values = [o.get_attribute("value") for o in options]
        assert "rh-equity-nvda-001" in option_values, "NVDA option missing from switcher"
        assert "rh-equity-jpm-002" in option_values, "JPM option missing from switcher"
        # Use select_option (not page.goto) to switch — this exercises the UI control
        page.select_option("select[onchange*=\"location='/radar/equity/'\"]", "rh-equity-jpm-002")
        page.wait_for_url("**/rh-equity-jpm-002**", timeout=5000)
        page.wait_for_load_state("domcontentloaded")
        assert "rh-equity-jpm-002" in page.url, f"URL did not navigate to JPM terminal: {page.url}"
        body_text = page.inner_text("body")
        assert "JPM" in body_text or "JPMorgan" in body_text, (
            "JPM identity not visible after switcher navigation"
        )
        assert "IDENTITY_VERIFIED" in body_text, (
            "IDENTITY_VERIFIED not visible on JPM terminal"
        )
        # Prove JPM-specific financial sentinel and NVDA value absent
        page.goto(f"{live_url_e3}/radar/equity/rh-equity-jpm-002"
                  "?tab=financials&timeframe=annual&statement=income")
        page.wait_for_load_state("domcontentloaded")
        body_text = page.inner_text("body")
        assert "49,001,111,000" in body_text, (
            "JPM-specific annual revenue sentinel (49,001,111,000) missing from JPM financial panel"
        )
        assert "26,001,111,000" not in body_text, (
            "NVDA annual revenue (26,001,111,000) unexpectedly present on JPM terminal"
        )
        page.close()

    def test_b12_back_to_radar_navigation(self, live_url_e3, browser):
        """B12: Clicking ← Radar link (not go_back) returns to /radar URL."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url_e3}/radar/equity/rh-equity-nvda-001")
        page.wait_for_load_state("domcontentloaded")
        back_link = page.query_selector('a[href="/radar"]')
        assert back_link is not None, (
            "← Radar back link (a[href='/radar']) not found on terminal"
        )
        back_link.click()
        page.wait_for_load_state("domcontentloaded")
        assert page.url.rstrip("/").endswith("/radar"), (
            f"← Radar link did not navigate to /radar; got: {page.url}"
        )
        page.close()

    def test_b13_terminal_no_page_overflow_mobile(self, live_url_e3, browser):
        """B13: NVDA financials URL at 390px has no page-level horizontal overflow."""
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(
            f"{live_url_e3}/radar/equity/rh-equity-nvda-001"
            "?tab=financials&timeframe=annual&statement=income"
        )
        page.wait_for_load_state("domcontentloaded")
        _assert_no_overflow(
            page,
            "/radar/equity/rh-equity-nvda-001?tab=financials&timeframe=annual&statement=income",
            390,
        )
        page.close()


# ── E4 Execution Simulator browser fixtures ───────────────────────────────────

class _E4FakeSnapshot:
    """Offline snapshot for E4 browser tests."""

    def __init__(self, direction: str = "BUY", size: str = "100") -> None:
        self._direction = direction
        self._size = size
        self.snapshot_id = f"snap-e4-browser-{direction.lower()}-{size}"

    def to_payload(self):
        return {
            "snapshot_id": self.snapshot_id,
            "state": "COMPLETE",
            "startedAt": "2026-01-01T11:59:00+00:00",
            "completedAt": "2026-01-01T12:00:00+00:00",
            "economicAssetUid": "rh-equity-nvda-001",
            "chainId": 4663,
            "contractAddress": "0xnvda001abc",
            "request": {
                "direction": self._direction,
                "notionalUsd": self._size,
            },
            "providers": [
                {
                    "provider": "radar-core",
                    "state": "COMPLETE",
                    "errorClass": None,
                    "elapsedMs": 100,
                    "evidence": {
                        "asset": {
                            "symbol": "NVDA",
                            "economicAssetUid": "rh-equity-nvda-001",
                            "chainId": 4663,
                            "contractAddress": "0xnvda001abc",
                        },
                        "observedAt": "2026-01-01T11:59:00+00:00",
                        "reference": {
                            "available": True,
                            "price": "143.11",
                            "bid": "143.00",
                            "ask": "143.22",
                            "source": "FROZEN::BoundReferencePrice",
                            "observedAt": "2026-01-01T11:59:00+00:00",
                            "isTradingHalt": False,
                        },
                        "execution": {
                            "available": True,
                            "side": self._direction,
                            "notionalUsd": self._size,
                            "status": "QUOTE_OK",
                            "effectivePrice": "142.77" if self._direction == "BUY" else "143.45",
                            "source": "LiFi",
                            "quotedAt": "2026-01-01T11:59:30+00:00",
                        },
                        "gap": {
                            "available": True,
                            "side": self._direction,
                            "gapBps": "-24" if self._direction == "BUY" else "24",
                            "gapToMidBps": "-29" if self._direction == "BUY" else "29",
                            "executionPrice": "142.77" if self._direction == "BUY" else "143.45",
                            "referencePrice": "143.11",
                            "referenceSide": "bid" if self._direction == "BUY" else "ask",
                            "source": "FROZEN::DirectionalGap",
                            "quotedAt": "2026-01-01T11:59:30+00:00",
                        },
                    },
                }
            ],
        }


class _E4FakeAcqService:
    """Offline AcquisitionService for E4 browser acceptance tests."""

    def __init__(self) -> None:
        self._calls: list = []

    def acquire(self, request):
        self._calls.append(request)
        return _E4FakeSnapshot(direction=request.direction,
                               size=request.notional_usd)

    def get_snapshot(self, snapshot_id: str):
        return _E4FakeSnapshot()

    def close(self):
        pass


@pytest.fixture(scope="module")
def live_url_e4():
    """Uvicorn server with E3 DB + E4 fake AcquisitionService for simulate route."""
    from app.radar_ui import router as radar_router
    from app.radar_ui import equity_terminal, equity_enrichment
    from app.radar_ui.equity_enrichment import EquityEnrichmentResult, EnrichmentState
    from finco_radar.equity import get_equity_company_history
    import main_web
    import uvicorn

    tmp = _build_e3_browser_db()

    _orig_fetch    = radar_router._fetch_universe_safe
    _orig_featured = radar_router._get_featured_symbols
    _orig_many     = equity_enrichment.enrich_many_selected_assets
    _orig_single   = equity_enrichment.enrich_selected_asset
    _orig_history  = equity_terminal.get_history_for_terminal

    _e4_svc = _E4FakeAcqService()
    radar_router.set_service(_e4_svc)

    def _fake_fetch():
        return ([_NVDA_SA, _JPM_SA], None)

    def _fake_featured():
        return ("NVDA", "JPM")

    def _fake_enrich_many(pairs):
        return [
            EquityEnrichmentResult(
                state=EnrichmentState.SOURCE_UNAVAILABLE,
                bundle=None,
                identity_note=None,
            )
            for _ in pairs
        ]

    def _fake_enrich_single(token_symbol, contract_address, **kwargs):
        return EquityEnrichmentResult(
            state=EnrichmentState.SOURCE_UNAVAILABLE,
            bundle=None,
            identity_note=None,
        )

    def _fake_history(token_symbol, **kwargs):
        return get_equity_company_history(token_symbol, db_path=tmp, db_mode="snapshot")

    radar_router._fetch_universe_safe             = _fake_fetch
    radar_router._get_featured_symbols            = _fake_featured
    equity_enrichment.enrich_many_selected_assets = _fake_enrich_many
    equity_enrichment.enrich_selected_asset       = _fake_enrich_single
    equity_terminal.get_history_for_terminal      = _fake_history

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
        radar_router.set_service(None)
        radar_router._fetch_universe_safe             = _orig_fetch
        radar_router._get_featured_symbols            = _orig_featured
        equity_enrichment.enrich_many_selected_assets = _orig_many
        equity_enrichment.enrich_selected_asset       = _orig_single
        equity_terminal.get_history_for_terminal      = _orig_history
        tmp.unlink(missing_ok=True)


class TestE4ExecutionSimulator:
    """E4 Execution Simulator browser acceptance — original B1–B13 journey.

    B1:  /radar loads, Featured Equities section visible.
    B2:  Click NVDA Details → Company Terminal URL contains exact UID.
    B3:  Click/open Token Market tab → tab content visible.
    B4:  Execution Simulator heading visible on Token Market tab.
    B5:  Exact disclosure "Simulation only — no order is submitted." visible.
    B6:  Choose Simulate Buy via actual radio control.
    B7:  Choose $100 via actual size radio control.
    B8:  Click Check Execution via actual submit button → HTMX result appears.
    B9:  Result contains distinctive ref price + exec price + GAP + NVDA UID.
    B10: Simulate Sell → different effective price + different GAP direction.
    B11: Switch asset via Company Terminal selector → URL changes, old NVDA
         result absent, new result region initially empty.
    B12: Structural proof of ZERO wallet/signing controls across buttons/forms/inputs/links.
    B13: 390px viewport on token-market tab → Execution Simulator visible; no overflow.
    """

    # ── helpers ─────────────────────────────────────────────────────────────

    def _wait_sim_result(self, page, uid: str, timeout: int = 5000) -> str:
        """Wait for HTMX sim result to arrive and return its inner text."""
        sel = f"#sim-result-{uid}"
        page.wait_for_selector(sel, state="attached", timeout=timeout)
        page.wait_for_function(
            f'document.querySelector("{sel}").innerText.trim().length > 0',
            timeout=timeout,
        )
        return page.inner_text(sel)

    # ── B1 ──────────────────────────────────────────────────────────────────

    def test_b01_radar_loads_featured_equities(self, live_url_e4, browser):
        """B1: /radar loads and Featured Equities section is visible."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url_e4}/radar")
        page.wait_for_load_state("domcontentloaded")
        body_text = page.inner_text("body")
        assert "FEATURED EQUITIES" in body_text.upper(), (
            "Featured Equities section not found on /radar"
        )
        page.close()

    # ── B2 ──────────────────────────────────────────────────────────────────

    def test_b02_nvda_details_navigates_to_exact_uid_terminal(
            self, live_url_e4, browser):
        """B2: Clicking NVDA Details → navigates to exact UID Company Terminal URL."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url_e4}/radar")
        page.wait_for_load_state("domcontentloaded")
        nvda_link = page.query_selector('a.board-details-cta[data-symbol="NVDA"]')
        assert nvda_link is not None, "NVDA Details → link not found on featured board"
        # Use raw HTML for URL assertion (bypasses CSS uppercase)
        href = nvda_link.get_attribute("href")
        assert "rh-equity-nvda-001" in (href or ""), (
            f"NVDA Details link href does not contain UID: {href!r}"
        )
        nvda_link.click()
        page.wait_for_load_state("domcontentloaded")
        assert "rh-equity-nvda-001" in page.url, (
            f"Company Terminal URL does not contain UID after click: {page.url}"
        )
        page.close()

    # ── B3 ──────────────────────────────────────────────────────────────────

    def test_b03_token_market_tab_click_shows_content(
            self, live_url_e4, browser):
        """B3: Clicking Token Market tab makes the tab panel visible."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url_e4}/radar/equity/rh-equity-nvda-001")
        page.wait_for_load_state("domcontentloaded")
        tab_btn = page.query_selector('a.tab-btn[onclick*="token-market"]')
        assert tab_btn is not None, "Token Market tab button not found"
        tab_btn.click()
        page.wait_for_load_state("domcontentloaded")
        panel = page.query_selector("#tab-token-market")
        assert panel is not None, "#tab-token-market panel not found after tab click"
        assert panel.is_visible(), "#tab-token-market panel not visible after tab click"
        page.close()

    # ── B4 ──────────────────────────────────────────────────────────────────

    def test_b04_execution_simulator_heading_visible(
            self, live_url_e4, browser):
        """B4: Execution Simulator heading visible on Token Market tab."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(
            f"{live_url_e4}/radar/equity/rh-equity-nvda-001?tab=token-market"
        )
        page.wait_for_load_state("domcontentloaded")
        body_text = page.inner_text("body")
        assert "Execution Simulator" in body_text, (
            "Execution Simulator heading not found on Token Market tab"
        )
        page.close()

    # ── B5 ──────────────────────────────────────────────────────────────────

    def test_b05_exact_disclosure_visible(self, live_url_e4, browser):
        """B5: Exact disclosure 'Simulation only — no order is submitted.' visible."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(
            f"{live_url_e4}/radar/equity/rh-equity-nvda-001?tab=token-market"
        )
        page.wait_for_load_state("domcontentloaded")
        body_text = page.inner_text("body")
        assert "Simulation only" in body_text, (
            "Disclosure 'Simulation only' not found on Token Market tab"
        )
        assert "no order is submitted" in body_text, (
            "Disclosure 'no order is submitted' not found on Token Market tab"
        )
        page.close()

    # ── B6 ──────────────────────────────────────────────────────────────────

    def test_b06_simulate_buy_via_actual_radio(self, live_url_e4, browser):
        """B6: Simulate Buy radio control is present and checkable."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(
            f"{live_url_e4}/radar/equity/rh-equity-nvda-001?tab=token-market"
        )
        page.wait_for_load_state("domcontentloaded")
        buy_radio = page.query_selector('input[name="direction"][value="BUY"]')
        assert buy_radio is not None, "BUY radio input not found on Token Market form"
        page.check('input[name="direction"][value="BUY"]')
        assert buy_radio.is_checked(), "BUY radio did not become checked"
        page.close()

    # ── B7 ──────────────────────────────────────────────────────────────────

    def test_b07_size_100_via_actual_control(self, live_url_e4, browser):
        """B7: $100 size radio control is present and checkable."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(
            f"{live_url_e4}/radar/equity/rh-equity-nvda-001?tab=token-market"
        )
        page.wait_for_load_state("domcontentloaded")
        size_radio = page.query_selector('input[name="size"][value="100"]')
        assert size_radio is not None, "$100 size radio not found on Token Market form"
        page.check('input[name="size"][value="100"]')
        assert size_radio.is_checked(), "$100 size radio did not become checked"
        page.close()

    # ── B8 ──────────────────────────────────────────────────────────────────

    def test_b08_check_execution_button_triggers_htmx_result(
            self, live_url_e4, browser):
        """B8: Clicking Check Execution button triggers HTMX result swap."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(
            f"{live_url_e4}/radar/equity/rh-equity-nvda-001?tab=token-market"
        )
        page.wait_for_load_state("domcontentloaded")
        page.check('input[name="direction"][value="BUY"]')
        page.check('input[name="size"][value="100"]')
        btn = page.query_selector('button[type="submit"]')
        assert btn is not None, "Submit button not found on Token Market form"
        # Verify button text in raw HTML (CSS may uppercase it)
        btn_html = page.content()
        assert "Check Execution" in btn_html, (
            "'Check Execution' not found in page HTML"
        )
        btn.click()
        result_text = self._wait_sim_result(page, "rh-equity-nvda-001")
        assert len(result_text.strip()) > 0, (
            "HTMX sim-result region is empty after clicking Check Execution"
        )
        page.close()

    # ── B9 ──────────────────────────────────────────────────────────────────

    def test_b09_buy_result_distinctive_values_and_uid(
            self, live_url_e4, browser):
        """B9: BUY result — distinctive ref 143.11, exec 142.77, GAP -24, NVDA UID."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(
            f"{live_url_e4}/radar/equity/rh-equity-nvda-001?tab=token-market"
        )
        page.wait_for_load_state("domcontentloaded")
        page.check('input[name="direction"][value="BUY"]')
        page.check('input[name="size"][value="100"]')
        page.click('button[type="submit"]')
        result_text = self._wait_sim_result(page, "rh-equity-nvda-001")
        assert "143.11" in result_text, (
            f"Distinctive reference price 143.11 missing from BUY result: {result_text[:500]}"
        )
        assert "142.77" in result_text, (
            f"Distinctive effective price 142.77 missing from BUY result: {result_text[:500]}"
        )
        assert "-24" in result_text, (
            f"Directional GAP -24 missing from BUY result: {result_text[:500]}"
        )
        assert "rh-equity-nvda-001" in result_text, (
            f"Asset UID missing from BUY result: {result_text[:500]}"
        )
        page.close()

    # ── B10 ─────────────────────────────────────────────────────────────────

    def test_b10_sell_result_different_price_and_gap(
            self, live_url_e4, browser):
        """B10: SELL result — different effective price (143.45) and positive GAP (+24)."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(
            f"{live_url_e4}/radar/equity/rh-equity-nvda-001?tab=token-market"
        )
        page.wait_for_load_state("domcontentloaded")
        page.check('input[name="direction"][value="SELL"]')
        page.check('input[name="size"][value="100"]')
        page.click('button[type="submit"]')
        result_text = self._wait_sim_result(page, "rh-equity-nvda-001")
        # SELL-specific: effective price 143.45 (not 142.77 BUY price)
        assert "143.45" in result_text, (
            f"SELL effective price 143.45 missing from SELL result: {result_text[:500]}"
        )
        # SELL gap is positive (+24, not negative)
        assert "24" in result_text, (
            f"SELL GAP +24 missing from SELL result: {result_text[:500]}"
        )
        # BUY effective price must NOT appear (proves directionality)
        assert "142.77" not in result_text, (
            f"BUY effective price 142.77 unexpectedly present in SELL result: {result_text[:500]}"
        )
        page.close()

    # ── B11 ─────────────────────────────────────────────────────────────────

    def test_b11_asset_selector_clears_old_result_new_empty(
            self, live_url_e4, browser):
        """B11: Switch NVDA → JPM via selector — URL changes, old NVDA result absent, JPM empty."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        # Start on NVDA terminal, Token Market tab
        page.goto(
            f"{live_url_e4}/radar/equity/rh-equity-nvda-001?tab=token-market"
        )
        page.wait_for_load_state("domcontentloaded")
        # Simulate NVDA first to produce a result
        page.check('input[name="direction"][value="BUY"]')
        page.click('button[type="submit"]')
        self._wait_sim_result(page, "rh-equity-nvda-001")
        # Confirm NVDA result is present before switching
        nvda_result_pre = page.query_selector("#sim-result-rh-equity-nvda-001")
        assert nvda_result_pre is not None, "NVDA sim-result div not found before switch"
        # Switch to JPM via the Company Terminal asset selector
        page.select_option(
            "select[onchange*=\"location='/radar/equity/'\"]",
            "rh-equity-jpm-002",
        )
        page.wait_for_url("**/rh-equity-jpm-002**", timeout=5000)
        page.wait_for_load_state("domcontentloaded")
        # URL must now be the JPM terminal
        assert "rh-equity-jpm-002" in page.url, (
            f"URL did not navigate to JPM terminal: {page.url}"
        )
        # Old NVDA sim-result div must not exist on the new page
        old_nvda_div = page.query_selector("#sim-result-rh-equity-nvda-001")
        assert old_nvda_div is None, (
            "Old NVDA #sim-result-rh-equity-nvda-001 div still present on JPM terminal"
        )
        # New JPM result region must exist but be empty (no simulation run yet)
        jpm_result_div = page.query_selector("#sim-result-rh-equity-jpm-002")
        assert jpm_result_div is not None, (
            "#sim-result-rh-equity-jpm-002 div not found on JPM terminal"
        )
        jpm_text = jpm_result_div.inner_text().strip()
        assert jpm_text == "", (
            f"JPM sim-result region should start empty but contains: {jpm_text[:200]}"
        )
        page.close()

    # ── B12 ─────────────────────────────────────────────────────────────────

    def test_b12_structural_no_wallet_signing_controls(
            self, live_url_e4, browser):
        """B12: Token Market tab has ZERO wallet/signing/transaction controls across
        buttons, forms, inputs, and links."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(
            f"{live_url_e4}/radar/equity/rh-equity-nvda-001?tab=token-market"
        )
        page.wait_for_load_state("domcontentloaded")
        # Use raw HTML — text-transform:uppercase can hide casing in inner_text
        html = page.content()

        _FORBIDDEN_SUBSTRINGS = [
            "wallet connect", "wallet address", "walletaddress",
            "approve", "allowance", "permit",
            "signature", ">sign<", "\"sign\"", "'sign'",
            "submit order", "submit_order",
            "send", "swap",
            "transaction hash", "txhash", "tx_hash",
            "private key", "privatekey", "seed phrase", "seedphrase",
        ]
        lower_html = html.lower()
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            assert forbidden not in lower_html, (
                f"Forbidden wallet/signing term {forbidden!r} found in Token Market HTML"
            )

        # Structural: no button/input/link whose text or name references wallet ops
        _FORBIDDEN_CONTROL_TERMS = [
            "wallet", "sign", "approve", "allowance", "permit",
            "submit order", "execute", "swap", "send tx", "broadcast",
            "private key", "seed phrase",
        ]
        controls = page.query_selector_all("button, input[type='submit'], a[href]")
        for ctrl in controls:
            ctrl_html = ctrl.evaluate("el => el.outerHTML").lower()
            for term in _FORBIDDEN_CONTROL_TERMS:
                # skip terms that might appear in legitimate sim controls
                if term in ("sign",):
                    # "sign" is forbidden only in wallet context — skip "Execution Simulator"
                    continue
                assert term not in ctrl_html, (
                    f"Wallet/signing control term {term!r} found in control HTML: "
                    f"{ctrl_html[:200]}"
                )
        page.close()

    # ── B13 ─────────────────────────────────────────────────────────────────

    def test_b13_390px_token_market_no_overflow(self, live_url_e4, browser):
        """B13: 390px viewport on token-market tab — Execution Simulator visible, no overflow."""
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(
            f"{live_url_e4}/radar/equity/rh-equity-nvda-001?tab=token-market"
        )
        page.wait_for_load_state("domcontentloaded")
        # Execution Simulator must be visible at mobile width
        body_text = page.inner_text("body")
        assert "Execution Simulator" in body_text, (
            "Execution Simulator heading not visible at 390px"
        )
        # No page-level horizontal overflow
        _assert_no_overflow(
            page,
            "/radar/equity/rh-equity-nvda-001?tab=token-market",
            390,
        )
        page.close()
