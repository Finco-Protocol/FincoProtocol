"""Playwright acceptance for FINCO Yield V1 beta."""
from __future__ import annotations

from dataclasses import replace
import socket
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright")
pytest.importorskip("uvicorn")

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import sync_playwright

import finco_yield.web as yield_web
from finco_yield.registry import YieldRegistry, load_bundled_registry


REPO = Path(__file__).resolve().parents[1]
WIDTH_TOLERANCE = 2


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def yield_url():
    import uvicorn

    app = FastAPI()
    app.include_router(yield_web.router)
    app.mount("/static", StaticFiles(directory=REPO / "static"), name="static")

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(5)


@pytest.fixture(scope="module")
def yield_browser():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        yield browser
        browser.close()


def _overflow_px(page) -> int:
    return page.evaluate(
        "document.documentElement.scrollWidth - window.innerWidth"
    )


def test_yield_default_off_browser(yield_url, yield_browser, monkeypatch):
    monkeypatch.delenv("FINCO_YIELD_ENABLED", raising=False)
    page = yield_browser.new_page(viewport={"width": 1280, "height": 900})
    response = page.goto(f"{yield_url}/yield")
    assert response is not None
    assert response.status == 404
    page.close()


def test_yield_enabled_explore_detail_evidence_compare_and_execution_off(
    yield_url, yield_browser, monkeypatch
):
    monkeypatch.setenv("FINCO_YIELD_ENABLED", "1")
    monkeypatch.delenv("FINCO_YIELD_EXECUTION_ENABLED", raising=False)
    registry = load_bundled_registry()
    first, second = registry.all()[:2]

    page = yield_browser.new_page(viewport={"width": 1280, "height": 900})
    response = page.goto(f"{yield_url}/yield")
    assert response is not None and response.status == 200
    page.wait_for_load_state("domcontentloaded")

    assert page.locator("h1").inner_text() == "Explore"
    assert page.locator("tbody tr").count() >= 1
    assert page.locator(f"a[href='/yield/{first.uid}']").count() == 1
    assert _overflow_px(page) <= WIDTH_TOLERANCE

    page.goto(f"{yield_url}/yield/{first.uid}")
    page.wait_for_load_state("domcontentloaded")
    assert page.locator("h1").inner_text() == first.name
    assert page.locator(f"a[href='/yield/{first.uid}/evidence.json']").count() == 1
    assert page.get_by_role("button", name="Execution flag OFF").is_disabled()
    assert page.locator("input[name='private_key']").count() == 0
    assert page.get_by_role("button", name="Sign", exact=False).count() == 0
    assert page.get_by_role("button", name="Broadcast", exact=False).count() == 0

    evidence = page.request.get(f"{yield_url}/yield/{first.uid}/evidence.json")
    assert evidence.status == 200
    payload = evidence.json()
    assert payload["identity"]["opportunity_uid"] == first.uid
    assert len(payload["canonical_input_hash"]) == 64
    assert len(payload["canonical_output_hash"]) == 64

    compare_url = (
        f"{yield_url}/yield/compare?uid={first.uid}&uid={second.uid}"
    )
    page.goto(compare_url)
    page.wait_for_load_state("domcontentloaded")
    text = page.locator("body").inner_text()
    assert "Side-by-side mechanics" in text
    assert "No winner, score or recommendation is generated." in text
    assert "winner:" not in text.lower()
    assert "ProviderError" not in text
    assert _overflow_px(page) <= WIDTH_TOLERANCE
    page.close()


def test_yield_mobile_390_no_page_overflow_and_controls_usable(
    yield_url, yield_browser, monkeypatch
):
    monkeypatch.setenv("FINCO_YIELD_ENABLED", "1")
    monkeypatch.delenv("FINCO_YIELD_EXECUTION_ENABLED", raising=False)
    uid = load_bundled_registry().all()[0].uid

    page = yield_browser.new_page(viewport={"width": 390, "height": 844})
    page.goto(f"{yield_url}/yield")
    page.wait_for_load_state("domcontentloaded")
    assert _overflow_px(page) <= WIDTH_TOLERANCE

    scroll = page.locator(".scroll").first
    assert scroll.count() == 1
    metrics = scroll.evaluate(
        "el => ({clientWidth: el.clientWidth, scrollWidth: el.scrollWidth})"
    )
    assert metrics["scrollWidth"] >= metrics["clientWidth"]

    page.goto(f"{yield_url}/yield/{uid}")
    page.wait_for_load_state("domcontentloaded")
    assert _overflow_px(page) <= WIDTH_TOLERANCE
    button = page.get_by_role("button", name="Execution flag OFF")
    assert button.is_visible()
    box = button.bounding_box()
    assert box is not None
    assert box["x"] >= 0
    assert box["x"] + box["width"] <= 390 + WIDTH_TOLERANCE
    page.close()


def test_monitor_unauthenticated_redirects_to_login(
    yield_url, yield_browser, monkeypatch
):
    monkeypatch.setenv("FINCO_YIELD_ENABLED", "1")
    import app.auth

    monkeypatch.setattr(app.auth, "resolve_request_session", lambda request: None)

    page = yield_browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(f"{yield_url}/yield/monitor")
    assert page.url.endswith("/login")
    page.close()


def test_monitor_verified_wallet_absence_is_calm_read_only(
    yield_url, yield_browser, monkeypatch
):
    monkeypatch.setenv("FINCO_YIELD_ENABLED", "1")
    import app.auth
    import app.protocol.wallet_auth as wallet_auth

    class User:
        user_id = "yield-browser-user"

    monkeypatch.setattr(
        app.auth, "resolve_request_session", lambda request: User()
    )
    monkeypatch.setattr(wallet_auth, "get_verified_wallet", lambda user_id: None)

    page = yield_browser.new_page(viewport={"width": 1280, "height": 900})
    response = page.goto(f"{yield_url}/yield/monitor")
    assert response is not None and response.status == 200
    page.wait_for_load_state("domcontentloaded")
    text = page.locator("body").inner_text()
    assert "No verified FINCO wallet is linked" in text
    assert "read-only" in text.lower()
    assert page.locator("input[name='private_key']").count() == 0
    assert page.get_by_role("button", name="Sign", exact=False).count() == 0
    assert page.get_by_role("button", name="Broadcast", exact=False).count() == 0
    page.close()


def test_script_like_registry_content_is_inert_and_href_rejected(
    yield_url, yield_browser, monkeypatch
):
    monkeypatch.setenv("FINCO_YIELD_ENABLED", "1")
    base_registry = load_bundled_registry()
    original = base_registry.all()[0]
    hostile = replace(
        original,
        name='<script data-yield-xss>window.__yield_xss=1</script>',
        protocol='<img data-yield-img src=x onerror="window.__yield_img=1">',
        underlying_symbol="<svg onload=window.__yield_svg=1>",
        source_uri="javascript:window.__yield_href=1",
    )
    custom_registry = YieldRegistry([hostile])
    monkeypatch.setattr(
        yield_web, "load_bundled_registry", lambda: custom_registry
    )

    page = yield_browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(f"{yield_url}/yield")
    page.wait_for_load_state("domcontentloaded")

    assert page.locator("script[data-yield-xss]").count() == 0
    assert page.locator("[data-yield-img]").count() == 0
    assert page.locator("svg[onload]").count() == 0
    assert page.evaluate("window.__yield_xss === undefined")
    assert page.evaluate("window.__yield_img === undefined")
    assert page.evaluate("window.__yield_svg === undefined")

    page.goto(f"{yield_url}/yield/{hostile.uid}")
    page.wait_for_load_state("domcontentloaded")
    assert page.locator("script[data-yield-xss]").count() == 0
    assert page.locator("a[href^='javascript:']").count() == 0
    assert page.evaluate("window.__yield_href === undefined")
    page.close()
