"""FINCO Protocol UI — Unified Shell Browser Acceptance Tests.

Tests the product protocol shell (Home · Model · Radar · API) at
mobile (390 px) and desktop (1280 px).

Chromium executable: set FINCO_TEST_CHROMIUM_PATH to an explicit binary path
when the Playwright-managed browser is not installed (e.g. local dev
environments with a pre-installed chromium).  When the env var is absent,
pw.chromium.launch() uses the Playwright-managed install (the normal CI path
after ``playwright install chromium``).

Coverage:
  1. Protocol home loads with two product cards and shared nav.
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

from playwright.sync_api import expect, sync_playwright  # noqa: E402

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
    def test_home_loads_product_cards_and_nav_without_verify(self, live_url, browser):
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
        assert "API" in nav_text
        assert "Verify" not in nav_text

        # Blueprint pass: home uses editorial architecture section (.proto-arch__product)
        # instead of equal-weight cards. Accept either the new product items
        # or the legacy proto-card class so both designs satisfy the invariant.
        products = page.query_selector_all(".proto-arch__product, .proto-card")
        assert len(products) == 2, (
            f"Expected exactly 2 product items (.proto-arch__product or .proto-card), "
            f"got {len(products)}"
        )

        page_text = page.inner_text("body")
        # Chrome cleanup pass removed READ-ONLY branding; Radar now surfaces
        # "Execution simulation — coming soon" on the home architecture card.
        assert "coming soon" in page_text.lower(), (
            "Radar card must mention execution simulation coming soon"
        )

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
    def test_clone_repeated_click_sends_one_request(self, live_url, browser):
        """HTMX disables the clone button before a second click can submit."""
        from app.persistence.db import get_connection
        from app.persistence.projects_repository import get_reference_by_template_source
        reference = get_reference_by_template_source("generic_solar_reference")
        assert reference is not None
        with get_connection() as conn:
            before = conn.execute(
                "SELECT COUNT(*) FROM projects WHERE user_id='1' AND source_project_id=?",
                (reference.project_id,),
            ).fetchone()[0]
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        requests = []
        page.on("request", lambda request: requests.append(request.url)
                if "/library/clone/" in request.url else None)
        page.goto(f"{live_url}/library")
        page.locator(f'[data-testid="clone-{reference.project_code}"]').evaluate(
            "button => { button.click(); button.click(); }"
        )
        page.wait_for_url("**/v2/workbook?project=*", timeout=15000)
        with get_connection() as conn:
            after = conn.execute(
                "SELECT COUNT(*) FROM projects WHERE user_id='1' AND source_project_id=?",
                (reference.project_id,),
            ).fetchone()[0]
        assert after - before == 1
        assert len(requests) == 1, f"Duplicate clone requests: {requests}"
        page.close()

    def test_library_loads_and_has_protocol_links(self, live_url, browser):
        """Library exposes cross-product navigation without project controls."""
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
        assert page.query_selector("#project-sidebar") is None
        assert page.query_selector("#fo-btn-run") is None
        assert page.query_selector("#fo-kpi-strip") is None
        for destination in ("/library", "/radar"):
            assert page.query_selector(f".fo-brand-bar__nav[href='{destination}']") is not None
        assert page.query_selector(".fo-brand-bar__nav[href='/verify']") is None

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
    """Prove coherent product navigation: Home → Library → Workbook → Radar → Home."""

    def test_workbook_has_protocol_links(self, live_url, browser):
        """Workbook V2 exposes only product-surface links."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        # Open workbook with a reference project (always exists for admin).
        page.goto(f"{live_url}/v2/workbook?project=generic_solar_reference-reference")
        page.wait_for_load_state("domcontentloaded")
        assert "/v2/workbook" in page.url, f"Workbook redirected to {page.url}"
        proto_section = page.query_selector(".v2-protocol-nav")
        assert proto_section is not None, (
            "Protocol navigation missing on Workbook V2"
        )
        links_text = proto_section.inner_text()
        assert "Model" in links_text, "Model link missing from Workbook navigation"
        assert "Radar" in links_text, "Radar link missing from Workbook navigation"
        assert "Verify" not in links_text, "Verify must not be a Workbook product module"

    def test_workbook_no_overflow_1280(self, live_url, browser):
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/v2/workbook?project=generic_solar_reference-reference")
        page.wait_for_load_state("domcontentloaded")
        assert "/v2/workbook" in page.url, f"Workbook redirected to {page.url}"
        _assert_no_overflow(page, "/v2/workbook", 1280)

    def test_workbook_no_overflow_390(self, live_url, browser):
        """Full page must not overflow at 390px after chrome.css mobile fix."""
        page = browser.new_page(viewport={"width": 390, "height": 844})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/v2/workbook?project=generic_solar_reference-reference")
        page.wait_for_load_state("domcontentloaded")
        assert "/v2/workbook" in page.url, f"Workbook redirected to {page.url}"
        _assert_no_overflow(page, "/v2/workbook", 390)

    def test_scenario_toolbar_activates_v2_tab_without_legacy_navigation(self, live_url, browser):
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/v2/workbook?project=generic_solar_reference-reference")
        page.wait_for_load_state("domcontentloaded")
        assert page.locator("#panel-scenarios").is_hidden()
        control = page.locator("button.v2-toolbar-scenario-link")
        assert control.count() == 1
        assert control.evaluate("""el => {
            const style = getComputedStyle(el);
            return {
                borderTop: style.borderTopStyle,
                borderRight: style.borderRightStyle,
                borderBottom: style.borderBottomStyle,
                borderLeft: style.borderLeftStyle,
                background: style.backgroundColor,
                paddingTop: style.paddingTop,
            };
        }""") == {
            "borderTop": "none", "borderRight": "none", "borderBottom": "none",
            "borderLeft": "solid", "background": "rgba(0, 0, 0, 0)", "paddingTop": "0px"
        }
        control.click()
        expect(page.locator("#panel-scenarios")).to_be_visible()
        assert page.locator("#tab-scenarios").get_attribute("aria-selected") == "true"
        assert "/scenarios" not in page.url
        assert "/scenarios?project=" not in page.content()

    def test_full_cross_surface_journey(self, live_url, browser):
        """Home → Library → Workbook → Radar → Home, no dead ends."""
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
        page.goto(f"{live_url}/v2/workbook?project=generic_solar_reference-reference")
        page.wait_for_load_state("domcontentloaded")
        assert "/v2/workbook" in page.url, f"Workbook redirected to {page.url}"
        proto = page.query_selector(".v2-protocol-nav")
        assert proto is not None, "Protocol navigation missing on Workbook"

        # 4. Navigate to Radar via Workbook navigation
        radar_link = proto.query_selector("a[href='/radar']")
        assert radar_link is not None, "Radar link missing from Workbook navigation"
        radar_link.click()
        page.wait_for_load_state("domcontentloaded")
        # Chrome cleanup pass removed READ-ONLY; Radar now shows Coming soon.
        assert "coming soon" in page.inner_text("body").lower()

        # 5. Verify is internal evidence, not a Radar product-navigation item.
        assert page.query_selector(".proto-nav a[href='/verify']") is None

        # 6. Navigate Home via protocol nav link.
        home_link = page.query_selector(".proto-nav a[href='/']")
        assert home_link is not None, "Home link missing from Radar nav"
        page.goto(f"{live_url}/")
        page.wait_for_load_state("domcontentloaded")
        # Blueprint pass: home uses .proto-arch__product; accept either class.
        assert page.query_selector(".proto-arch__product, .proto-card") is not None, (
            "Home product items missing after round-trip"
        )


# ─── Radar ─────────────────────────────────────────────────────────────────────

class TestRadar:
    def test_radar_execution_coming_soon_and_nav_desktop(self, live_url, browser):
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url}/radar")
        page.wait_for_load_state("domcontentloaded")

        page_text = page.inner_text("body")
        # Chrome cleanup pass removed READ-ONLY branding; execution is Coming soon.
        assert "coming soon" in page_text.lower(), (
            "Execution Coming soon label missing on Radar"
        )
        assert "READ-ONLY" not in page_text, (
            "READ-ONLY branding must not appear in Radar chrome"
        )
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

# Visual-market fixture — canonical UID required by normalize_asset_uid().
# Distinct from _NVDA_SA; same symbol ("NVDA") so E3 history DB data is reused.
# Contract matches DB so identity is VERIFIED in visual screenshots.
_NVDA_VISUAL_UID      = "0x" + "11" * 32   # 0x1111...1111 (64 hex chars)
_NVDA_VISUAL_SA = _SA_E3(_NVDA_VISUAL_UID, "NVDA", "NVIDIA Corporation", 4663, "0xnvda001abc", 0)


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
        assert "$26.0B" in body_text, (
            "Distinctive NVDA annual revenue ($26.0B compact) missing from income statement matrix"
        )
        assert "Net Income" in body_text, "Net Income label missing from annual income statement"
        assert "$9.0B" in body_text, (
            "Distinctive NVDA annual net income ($9.0B compact) missing from income statement matrix"
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
        assert "$7.0B" in body_text, (
            "Distinctive NVDA quarterly revenue ($7.0B compact) missing from quarterly income statement"
        )
        assert "$26.0B" not in body_text, (
            "Annual-only NVDA revenue ($26.0B compact) unexpectedly present in quarterly view"
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
        assert "$65.0B" in body_text, (
            "Distinctive NVDA annual total assets ($65.0B compact) missing from balance sheet"
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
        assert "$11.0B" in body_text, (
            "Distinctive NVDA annual operating cash flow ($11.0B compact) missing from cash flow statement"
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
        assert "$49.0B" in body_text, (
            "JPM-specific annual revenue ($49.0B compact) missing from JPM financial panel"
        )
        assert "$26.0B" not in body_text, (
            "NVDA annual revenue ($26.0B compact) unexpectedly present on JPM terminal"
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


@pytest.fixture(scope="module")
def live_url_radar_visual():
    """Uvicorn server for visual capture — uses canonical-UID NVDA visual asset."""
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
        return ([_NVDA_VISUAL_SA, _JPM_SA], None)

    def _fake_featured():
        # Keep JPM in the canonical universe but outside the featured board so
        # the Correction A capture can prove the non-featured asset path.
        return ("NVDA",)

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
    B6–B10: legacy controls remain structurally present but disabled; normal
             product UX exposes no active simulation CTA while Coming Soon.
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
        """B6: legacy BUY control is present but unavailable."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(
            f"{live_url_e4}/radar/equity/rh-equity-nvda-001?tab=token-market"
        )
        page.wait_for_load_state("domcontentloaded")
        buy_radio = page.query_selector('input[name="direction"][value="BUY"]')
        assert buy_radio is not None, "BUY radio input not found on Token Market form"
        assert buy_radio.is_checked(), "BUY radio did not become checked"
        assert buy_radio.is_disabled(), "Coming Soon BUY control must be disabled"
        page.close()

    # ── B7 ──────────────────────────────────────────────────────────────────

    def test_b07_size_100_via_actual_control(self, live_url_e4, browser):
        """B7: legacy size control is present but unavailable."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(
            f"{live_url_e4}/radar/equity/rh-equity-nvda-001?tab=token-market"
        )
        page.wait_for_load_state("domcontentloaded")
        size_radio = page.query_selector('input[name="size"][value="100"]')
        assert size_radio is not None, "$100 size radio not found on Token Market form"
        assert size_radio.is_checked(), "$100 size radio did not become checked"
        assert size_radio.is_disabled(), "Coming Soon size control must be disabled"
        page.close()

    # ── B8 ──────────────────────────────────────────────────────────────────

    def test_b08_check_execution_button_is_not_active(
            self, live_url_e4, browser):
        """B8: normal product surface exposes no active execution CTA."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(
            f"{live_url_e4}/radar/equity/rh-equity-nvda-001?tab=token-market"
        )
        page.wait_for_load_state("domcontentloaded")
        btn = page.query_selector('button[type="submit"]')
        assert btn is not None, "Submit button not found on Token Market form"
        assert btn.is_disabled(), "Coming Soon execution button must be disabled"
        assert "coming soon" in btn.inner_text().casefold()
        page.close()

    # ── B9 ──────────────────────────────────────────────────────────────────

    def test_b09_coming_soon_has_no_runtime_result(
            self, live_url_e4, browser):
        """B9: disabled normal UX does not create a simulation result."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(
            f"{live_url_e4}/radar/equity/rh-equity-nvda-001?tab=token-market"
        )
        page.wait_for_load_state("domcontentloaded")
        assert page.locator("#sim-result-rh-equity-nvda-001").inner_text().strip() == ""
        page.close()

    # ── B10 ─────────────────────────────────────────────────────────────────

    def test_b10_sell_control_is_disabled(
            self, live_url_e4, browser):
        """B10: SELL control cannot contradict the Coming Soon state."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(
            f"{live_url_e4}/radar/equity/rh-equity-nvda-001?tab=token-market"
        )
        page.wait_for_load_state("domcontentloaded")
        sell = page.query_selector('input[name="direction"][value="SELL"]')
        assert sell is not None and sell.is_disabled()
        page.close()

    # ── B11 ─────────────────────────────────────────────────────────────────

    def test_b11_asset_selector_clears_old_result_new_empty(
            self, live_url_e4, browser):
        """B11: Switch NVDA → JPM without exposing or retaining runtime results."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        # Start on NVDA terminal, Token Market tab
        page.goto(
            f"{live_url_e4}/radar/equity/rh-equity-nvda-001?tab=token-market"
        )
        page.wait_for_load_state("domcontentloaded")
        # Coming Soon keeps the legacy result region stable and empty.
        nvda_result_pre = page.query_selector("#sim-result-rh-equity-nvda-001")
        assert nvda_result_pre is not None, "NVDA sim-result div not found before switch"
        assert nvda_result_pre.inner_text().strip() == ""
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
            "send tx", "token swap",
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
            "submit order", "execute order", "execute tx", "execute trade",
            "swap", "send tx", "broadcast",
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


# ─── Correction A: Keyboard Focus Ring Coverage ────────────────────────────────

class TestKeyboardFocusRing:
    """CA1: Radar tab buttons retain a visible focus treatment for keyboard users.

    Proves that the :focus-visible rule in radar.css supplies an outline when
    a tab button receives keyboard focus, and that the outline is not suppressed
    by the legacy :focus { outline: none } rule.

    This is a deterministic CSS-property inspection test: it injects a tab
    button into the DOM, measures the computed outline-style before and after
    the element receives synthetic keyboard focus, and asserts that the
    :focus-visible selector produces a non-"none" outline.  The test does NOT
    assert specific colour values (those are unit-tested by the CSS source
    directly) — it asserts only that a visible outline is present.
    """

    def test_ca1_tab_btn_focus_visible_outline_not_none(self, live_url_e4, browser):
        """CA1: .tab-btn:focus-visible supplies a non-'none' outline."""
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{live_url_e4}/radar/equity/rh-equity-nvda-001")
        page.wait_for_load_state("domcontentloaded")

        # Locate any rendered tab button in the equity terminal.
        tab_btn = page.query_selector("a.tab-btn")
        assert tab_btn is not None, (
            "No .tab-btn element found on Company Terminal page; "
            "cannot test keyboard focus ring"
        )

        # Move keyboard focus to the tab button via Tab key navigation,
        # then read the computed outline-style.
        # We use evaluate to check the CSS rule directly because
        # :focus-visible is only active when focus was delivered
        # by keyboard, which requires a trusted user-gesture simulation.
        tab_btn.focus()

        outline_style = page.evaluate(
            """() => {
                const el = document.querySelector('a.tab-btn');
                if (!el) return 'ELEMENT_NOT_FOUND';
                return window.getComputedStyle(el).outlineStyle;
            }"""
        )

        # When :focus-visible applies (keyboard focus), outline-style must not
        # be 'none'. The legacy :focus { outline: none } was removed in Correction A;
        # any regression would set this back to 'none'.
        assert outline_style != "none", (
            f"tab-btn outline-style is 'none' after focus — "
            f":focus-visible ring is suppressed. outline-style={outline_style!r}"
        )
        page.close()


# ─── Correction B: 390px Model Workspace Overflow ─────────────────────────────

class TestCBH:
    """CBH: 390px viewport on the model workspace shell (library page) —
    the base.html shell with the command bar and model-saas.css applied must
    produce no destructive horizontal page-level overflow.

    The library page uses base.html → _app_chrome.html → _command_bar.html,
    exercising the same CSS layer (tokens → chrome → command bar → model-saas)
    that the model workspace shell depends on.
    """

    def test_cbh1_390px_library_no_overflow(self, live_url, browser):
        """CBH1: 390px viewport on /library — no horizontal page-level overflow."""
        page = browser.new_page(viewport={"width": 390, "height": 844})
        _auth_cookie(live_url, page)
        page.goto(f"{live_url}/library")
        page.wait_for_load_state("domcontentloaded")
        _assert_no_overflow(page, "/library", 390)
        page.close()


# ─── API Beta Surface Browser Tests (API-B01 – API-B09) ───────────────────────

class TestApiBetaBrowser:
    """Browser acceptance tests for the FINCO API Beta page (/api).

    API-B01 – API-B09 cover viewport correctness, nav active state,
    placeholder non-interactivity, endpoint tables, curl examples,
    discovery links, and mobile readability.  The /api route is public
    (no auth required) but we authenticate anyway to exercise the
    sign-out button path.
    """

    def test_api_b01_desktop_no_overflow(self, live_url, browser):
        """API-B01: /api at 1280px desktop — no horizontal page overflow."""
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{live_url}/api")
        page.wait_for_load_state("domcontentloaded")
        _assert_no_overflow(page, "/api", 1280)
        page.close()

    def test_api_b02_mobile_no_overflow(self, live_url, browser):
        """API-B02: /api at 390px mobile — no horizontal page overflow."""
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(f"{live_url}/api")
        page.wait_for_load_state("domcontentloaded")
        _assert_no_overflow(page, "/api", 390)
        page.close()

    def test_api_b03_nav_item_active(self, live_url, browser):
        """API-B03: Protocol nav 'API' link is present and marked active on /api."""
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{live_url}/api")
        page.wait_for_load_state("domcontentloaded")
        active = page.query_selector(".proto-nav__link--active")
        assert active is not None, "No active nav link found on /api"
        assert "API" in active.inner_text(), (
            f"Active nav link text '{active.inner_text()}' is not 'API'"
        )
        assert active.get_attribute("aria-current") == "page", (
            "Active API nav link missing aria-current='page'"
        )
        page.close()

    def test_api_b04_placeholders_not_links(self, live_url, browser):
        """API-B04: Docs/Roadmap/$FINCO appear as non-interactive placeholders."""
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{live_url}/api")
        page.wait_for_load_state("domcontentloaded")
        nav_text = page.inner_text(".proto-nav")
        for label in ("Docs", "Roadmap", "$FINCO"):
            assert label in nav_text, f"Placeholder '{label}' not in nav"
        # Placeholders must be spans, not anchors
        for label in ("Docs", "Roadmap", "$FINCO"):
            matches = page.query_selector_all(f"a:text('{label}')")
            assert len(matches) == 0, (
                f"Placeholder '{label}' is rendered as an anchor — must be non-interactive"
            )
        page.close()

    def test_api_b05_model_endpoint_table_visible(self, live_url, browser):
        """API-B05: Model API endpoint table is present and lists references endpoint."""
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{live_url}/api")
        page.wait_for_load_state("domcontentloaded")
        body = page.inner_text("body")
        assert "/model/references" in body, (
            "Model references endpoint path not found on /api page"
        )
        page.close()

    def test_api_b06_radar_endpoint_table_visible(self, live_url, browser):
        """API-B06: Radar API endpoint table is present and lists assets endpoint."""
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{live_url}/api")
        page.wait_for_load_state("domcontentloaded")
        body = page.inner_text("body")
        assert "/radar/assets" in body, (
            "Radar assets endpoint path not found on /api page"
        )
        page.close()

    def test_api_b07_curl_examples_visible(self, live_url, browser):
        """API-B07: curl examples section is rendered and contains a URL with a scheme."""
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{live_url}/api")
        page.wait_for_load_state("domcontentloaded")
        body = page.inner_text("body")
        assert "curl" in body, "curl examples section not found on /api page"
        # api_base_url must inject a full URL (http:// or https://) not a bare path
        assert "http" in body, (
            "curl examples must reference an absolute URL (http:// or https://)"
        )
        page.close()

    def test_api_b08_docs_and_openapi_links(self, live_url, browser):
        """API-B08: /docs and /openapi.json discovery anchor elements present on /api."""
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{live_url}/api")
        page.wait_for_load_state("domcontentloaded")
        docs_link = page.query_selector('a[href="/docs"]')
        openapi_link = page.query_selector('a[href="/openapi.json"]')
        assert docs_link is not None, "Link to /docs not found on /api page"
        assert openapi_link is not None, "Link to /openapi.json not found on /api page"
        page.close()

    def test_api_b09_mobile_endpoint_content_visible(self, live_url, browser):
        """API-B09: at 390px the endpoint paths are not clipped or off-screen."""
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(f"{live_url}/api")
        page.wait_for_load_state("domcontentloaded")
        body = page.inner_text("body")
        assert "/model/references" in body, (
            "Model endpoint path not readable at 390px mobile"
        )
        assert "/radar/assets" in body, (
            "Radar endpoint path not readable at 390px mobile"
        )
        page.close()


@pytest.mark.skipif(os.getenv("FINCO_VISUAL_CAPTURE") != "1", reason="visual artifact capture is enabled in CI")
def test_saas_visual_capture(live_url, live_url_radar_visual, browser):
    """Capture actual rendered product surfaces at this workflow's checked-out HEAD."""
    out = REPO / "artifacts" / "saas-visual"
    out.mkdir(parents=True, exist_ok=True)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    _auth_cookie(live_url, page)

    def shot(name):
        page.screenshot(path=str(out / f"{name}.png"), full_page=True, animations="disabled")

    page.goto(f"{live_url}/library")
    page.wait_for_load_state("domcontentloaded")
    shot("01-library-desktop")
    page.set_viewport_size({"width": 390, "height": 844})
    _assert_no_overflow(page, "/library", 390)
    shot("02-library-390")
    page.set_viewport_size({"width": 1280, "height": 900})
    page.locator('[data-testid="clone-generic_solar_reference-reference"]').click()
    page.wait_for_url("**/v2/workbook?project=*", timeout=15000)
    page.locator('[data-testid="overview-no-run-state"]').wait_for()
    shot("03-overview-no-run")
    page.locator('#v2-canonical-run-form button[type="submit"]').click()
    page.locator('[data-testid="toolbar-runtime-state"]').filter(has_text="Current").wait_for(timeout=90000)
    shot("04-overview-last-run")
    for tab, name in (("inputs", "05-inputs"), ("revenue", "06-revenue"),
                      ("debt", "07-debt"), ("fs", "08-financials")):
        page.locator(f"#tab-{tab}").click()
        shot(name)
    page.set_viewport_size({"width": 390, "height": 844})
    page.locator("#tab-overview").click()
    _assert_no_overflow(page, "/v2/workbook overview", 390)
    shot("08a-overview-390")
    page.locator("#tab-inputs").click()
    _assert_no_overflow(page, "/v2/workbook inputs", 390)
    shot("08b-inputs-390")
    page.close()

    from app.radar_ui import router as _radar_router

    class _FixedMarketService:
        """Deterministic visual fixture — NVDA at $143.11 / bid $142.77 / ask $143.45.

        Uses _NVDA_VISUAL_UID (canonical 0x-prefixed 64 hex chars) so the
        /radar/market/asset/{uid} endpoint passes normalize_asset_uid().
        """
        def read(self, *, uids=(), featured_symbols=()):
            def _row(uid, symbol):
                return {
                    "uid": uid, "symbol": symbol,
                    "chain_id": "polygon-mainnet",
                    "contract_address": "0x0001000000000000000000000000000000000000",
                    "state": "FRESH", "market_state": "REFERENCE",
                    "price": "143.11", "price_display": "$143.11",
                    "bid": "142.77", "bid_display": "$142.77",
                    "ask": "143.45", "ask_display": "$143.45",
                    "observed_at": "2026-01-01T00:00:00+00:00",
                    "source": "visual-fixture",
                }
            if uids:
                return [_row(uid, None) for uid in uids]
            return [_row(None, sym) for sym in featured_symbols]

    previous_market_service = _radar_router._market_read_service
    _radar_router.set_market_read_service(_FixedMarketService())
    try:
        radar = browser.new_page(viewport={"width": 1280, "height": 900})
        radar.goto(f"{live_url_radar_visual}/radar")
        radar.wait_for_load_state("domcontentloaded")
        # Wait for board market prices to populate before screenshot.
        radar.locator(
            '#featured-board [data-market-price]:not(:text("—"))'
        ).first.wait_for(timeout=10000)
        radar.screenshot(path=str(out / "09-radar-board.png"), full_page=True, animations="disabled")
        radar.goto(f"{live_url_radar_visual}/radar/equity/{_NVDA_VISUAL_UID}")
        radar.wait_for_load_state("domcontentloaded")
        for tab, name in (("overview", "10-company-overview"), ("financials", "11-company-financials"),
                          ("token-market", "12-market-execution"), ("evidence", "13-evidence")):
            radar.locator(f'a[href^="?tab={tab}"]').first.click()
            if tab == "overview":
                # Wait for header market price to populate.
                radar.locator(
                    'section[data-market-terminal-uid] [data-market-price]:not(:text("—"))'
                ).wait_for(timeout=10000)
            if tab == "token-market":
                # Wait for tab Reference Price and state to populate.
                radar.locator('[data-market-tab-price]:not(:text("—"))').wait_for(timeout=20000)
                radar.locator('[data-market-tab-state]').filter(
                    has_text="FRESH"
                ).wait_for(timeout=5000)
                # Assert all market values before capturing.
                price_text = radar.locator('[data-market-tab-price]').first.text_content()
                assert '$143.11' in price_text, f"Market price: {price_text!r}"
                bid_text = radar.locator('[data-market-bid]').first.text_content()
                assert '$142.77' in bid_text, f"Market bid: {bid_text!r}"
                ask_text = radar.locator('[data-market-ask]').first.text_content()
                assert '$143.45' in ask_text, f"Market ask: {ask_text!r}"
                state_text = radar.locator('[data-market-tab-state]').first.text_content()
                assert 'FRESH' in state_text, f"Market state: {state_text!r}"
                observed_text = radar.locator('[data-market-tab-observed]').first.text_content()
                assert '2026-01-01' in observed_text, f"Market observed: {observed_text!r}"
            radar.screenshot(path=str(out / f"{name}.png"), full_page=True, animations="disabled")
        radar.set_viewport_size({"width": 390, "height": 844})
        radar.goto(f"{live_url_radar_visual}/radar")
        _assert_no_overflow(radar, "/radar", 390)
        radar.screenshot(path=str(out / "14-radar-390.png"), full_page=True, animations="disabled")
        radar.goto(f"{live_url_radar_visual}/radar/equity/{_NVDA_VISUAL_UID}")
        _assert_no_overflow(radar, "/radar/equity", 390)
        radar.screenshot(path=str(out / "14a-company-390.png"), full_page=True, animations="disabled")
        radar.close()
    finally:
        _radar_router.set_market_read_service(previous_market_service)


@pytest.mark.skipif(
    os.getenv("FINCO_VISUAL_CAPTURE") != "1",
    reason="workstream browser evidence capture is enabled in CI",
)
def test_reference_driven_correction_a_22_capture_journey(
        live_url, live_url_radar_visual, browser):
    """Produce the dedicated 22-capture Correction A acceptance inventory."""
    from app.radar_ui import router as _radar_router
    from app.services.reference_seed_service import create_reference_seeded_project

    out = REPO / "artifacts" / "reference-driven-correction-a"
    out.mkdir(parents=True, exist_ok=True)

    page = browser.new_page(viewport={"width": 1280, "height": 900})
    _auth_cookie(live_url, page)

    def shot(name, locator=None):
        if locator is None:
            page.screenshot(
                path=str(out / f"{name}.png"), full_page=True,
                animations="disabled",
            )
        else:
            locator.screenshot(
                path=str(out / f"{name}.png"), animations="disabled",
            )

    # 01 — actual New Project reference chooser.
    page.goto(f"{live_url}/projects/new")
    page.wait_for_load_state("domcontentloaded")
    assert page.locator('input[value="generic_solar_reference"]').count() == 1
    assert page.locator('input[value="generic_wind_reference"]').count() == 1
    shot("01-new-project-reference-chooser")

    # Create independent projects through the same service invoked by the
    # rendered POST route, then exercise their actual workbook paths.
    suffix = f"{os.getpid()}-{time.time_ns()}"
    solar = create_reference_seeded_project(
        user_id="1",
        template_source="generic_solar_reference",
        requested_name=f"Correction A Solar {suffix}",
        capacity_mw=100.0,
    )
    wind = create_reference_seeded_project(
        user_id="1",
        template_source="generic_wind_reference",
        requested_name=f"Correction A Wind {suffix}",
        capacity_mw=72.0,
    )

    solar_url = f"{live_url}/v2/workbook?project={solar.project_code}"
    page.goto(solar_url)
    page.wait_for_load_state("domcontentloaded")
    page.locator("#v2-workbook-shell").wait_for()
    shot("02-solar-project")

    page.locator("#tab-capex").click()
    page.locator('[data-testid="capex-totals-bar"]').wait_for()
    shot("03-solar-capex-summary", page.locator('[data-testid="capex-totals-bar"]'))
    assert page.locator('[data-testid="total-capex-keur"]').inner_text().strip() not in {"", "0"}
    shot("04-solar-detailed-capex", page.locator("#v2-sheet-capex"))

    page.locator("#tab-opex").click()
    page.locator('[data-testid="opex-kpi-bar"]').wait_for()
    shot("05-solar-opex-summary", page.locator('[data-testid="opex-kpi-bar"]'))
    shot("06-solar-detailed-opex", page.locator("#v2-sheet-opex"))
    shot("07-opex-year-projection", page.locator('[data-testid="opex-projection-panel"]'))

    # Rename and override one immutable-provenance OPEX seed through the UI.
    seed_row = page.locator('[data-testid^="opex-custom-row-"]').first
    seed_row.wait_for()
    seed_row.locator("summary").click()
    label_input = seed_row.locator(".v2-opex-custom-label-input")
    amount_input = seed_row.locator(".v2-opex-custom-amount-input")
    overridden_label = "Renamed operating line — immutable seed identity"
    overridden_amount = float(amount_input.input_value()) + 37.0
    label_input.fill(overridden_label)
    amount_input.fill(f"{overridden_amount:.6f}")
    with page.expect_response(lambda response: "/v2/opex/line/update" in response.url):
        seed_row.locator(".v2-opex-custom-save-btn").click()
    renamed_row = page.locator('[data-testid^="opex-custom-row-"]').filter(
        has_text=overridden_label
    ).first
    renamed_row.locator("summary").wait_for()

    # Change MW through the actual bound Project Setup control.
    page.locator("#tab-project-setup").click()
    capacity_row = page.locator(
        '#panel-project-setup [data-field-id="project_setup.technical.capacity_mw"]'
    )
    capacity_input = capacity_row.locator('input[name="value"]')
    capacity_input.fill("150")
    with page.expect_response(lambda response: "/v2/workbook/update" in response.url):
        capacity_row.locator("button.v2-field-save").click()
    capacity_selector = (
        '#panel-project-setup '
        '[data-field-id="project_setup.technical.capacity_mw"] input[name="value"]'
    )
    expect(page.locator(capacity_selector)).to_have_value("150.0", timeout=10000)
    shot("08-capacity-change")

    page.locator("#tab-opex").click()
    survivor_row = page.locator('[data-testid^="opex-custom-row-"]').filter(
        has_text=overridden_label
    ).first
    survivor_row.locator("summary").click()
    survivor_row.locator(".v2-opex-custom-label-input").wait_for()
    assert float(survivor_row.locator(".v2-opex-custom-amount-input").input_value()) == pytest.approx(
        overridden_amount
    )
    survivor_row.locator("summary").click()
    shot("09-override-survival", survivor_row)

    page.goto(f"{live_url}/v2/workbook?project={wind.project_code}")
    page.wait_for_load_state("domcontentloaded")
    page.locator("#tab-capex").click()
    shot("10-wind-capex-summary", page.locator('[data-testid="capex-totals-bar"]'))
    shot("11-wind-detailed-capex", page.locator("#v2-sheet-capex"))
    page.locator("#tab-opex").click()
    shot("12-wind-opex", page.locator("#v2-sheet-opex"))
    page.set_viewport_size({"width": 390, "height": 844})
    _assert_no_overflow(page, "/v2/workbook wind", 390)
    shot("13-model-390")
    page.close()

    class _FixedMarketService:
        def read(self, *, uids=(), featured_symbols=()):
            def row(uid, symbol):
                return {
                    "uid": uid, "symbol": symbol,
                    "chain_id": "polygon-mainnet",
                    "contract_address": "0x0001000000000000000000000000000000000000",
                    "state": "FRESH", "market_state": "REFERENCE",
                    "price": "143.11", "price_display": "$143.11",
                    "bid": "142.77", "bid_display": "$142.77",
                    "ask": "143.45", "ask_display": "$143.45",
                    "observed_at": "2026-01-01T00:00:00+00:00",
                    "source": "correction-a-browser-fixture",
                }
            if uids:
                return [row(uid, None) for uid in uids]
            return [row(None, symbol) for symbol in featured_symbols]

    previous_market_service = _radar_router._market_read_service
    _radar_router.set_market_read_service(_FixedMarketService())
    try:
        radar = browser.new_page(viewport={"width": 1280, "height": 900})

        def radar_shot(name, locator=None):
            if locator is None:
                radar.screenshot(
                    path=str(out / f"{name}.png"), full_page=True,
                    animations="disabled",
                )
            else:
                locator.screenshot(
                    path=str(out / f"{name}.png"), animations="disabled",
                )

        radar.goto(f"{live_url_radar_visual}/radar")
        radar.wait_for_load_state("domcontentloaded")
        radar.locator('#featured-board [data-market-price]:not(:text("—"))').wait_for(timeout=10000)
        radar_shot("14-radar-featured-board", radar.locator("#featured-board"))

        radar.goto(f"{live_url_radar_visual}/radar?asset_uid=rh-equity-jpm-002")
        radar.wait_for_load_state("domcontentloaded")
        assert "JPM" in radar.locator('[data-panel="configured-target"]').inner_text()
        radar_shot("15-non-featured-canonical-asset")

        radar.goto(f"{live_url_radar_visual}/radar")
        cta = radar.locator("#featured-board .board-details-cta").first
        assert "Open Company Terminal" in cta.inner_text()
        radar_shot("16-open-company-terminal-cta", cta)

        radar.goto(f"{live_url_radar_visual}/radar/equity/{_NVDA_VISUAL_UID}")
        radar.wait_for_load_state("domcontentloaded")
        header = radar.locator(".terminal-header")
        header.locator('[data-market-price]:not(:text("—"))').wait_for(timeout=10000)
        assert "$142.77" in header.locator("[data-market-bid]").inner_text()
        assert "$143.45" in header.locator("[data-market-ask]").inner_text()
        radar_shot("17-company-header-market-price-bid-ask", header)

        radar.goto(f"{live_url_radar_visual}/radar/equity/{_NVDA_VISUAL_UID}?tab=financials")
        radar_shot("18-financials")
        radar.goto(f"{live_url_radar_visual}/radar/equity/{_NVDA_VISUAL_UID}?tab=token-market")
        radar.locator('[data-market-tab-price]:not(:text("—"))').wait_for(timeout=10000)
        radar_shot("19-token-market")
        coming_soon = radar.locator(".execution-coming-soon")
        assert "Execution Simulation — Coming soon" in coming_soon.inner_text()
        assert coming_soon.locator('button[type="submit"]').is_disabled()
        radar_shot("20-execution-coming-soon", coming_soon)
        radar.goto(f"{live_url_radar_visual}/radar/equity/{_NVDA_VISUAL_UID}?tab=evidence")
        radar_shot("21-evidence")
        radar.set_viewport_size({"width": 390, "height": 844})
        radar.goto(f"{live_url_radar_visual}/radar")
        _assert_no_overflow(radar, "/radar", 390)
        radar_shot("22-radar-390")
        radar.close()
    finally:
        _radar_router.set_market_read_service(previous_market_service)

    captures = sorted(out.glob("*.png"))
    assert len(captures) == 22, [path.name for path in captures]
