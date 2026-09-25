"""Browser acceptance for the public FINCO Roadmap surface.

This focused suite owns the live Docs/Roadmap navigation contract after Roadmap
became a first-class public surface. The older API-B04 assertion is intentionally
superseded because it encoded Roadmap as a non-interactive placeholder.
"""
from __future__ import annotations

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

REPO = Path(__file__).resolve().parents[1]
WIDTH_TOLERANCE = 2


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def roadmap_url():
    import uvicorn
    from app.protocol_ui.router import router as protocol_router

    app = FastAPI()
    app.include_router(protocol_router)
    app.mount("/static", StaticFiles(directory=REPO / "static"), name="static")

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
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
def roadmap_browser():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
        yield browser
        browser.close()


def _overflow_px(page) -> int:
    return page.evaluate("document.documentElement.scrollWidth - window.innerWidth")


def test_roadmap_desktop_renders_model_sales_track(roadmap_url, roadmap_browser):
    page = roadmap_browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(f"{roadmap_url}/roadmap")
    page.wait_for_load_state("domcontentloaded")
    assert page.locator("h1").inner_text().startswith("From financial modelling")
    assert page.get_by_text("Institutional Modelling", exact=False).count() >= 1
    assert page.get_by_text("Enterprise Modelling Platform", exact=False).count() >= 1
    active = page.locator(".proto-nav__link--active")
    assert active.inner_text().strip() == "Roadmap"
    assert active.get_attribute("aria-current") == "page"
    assert _overflow_px(page) <= WIDTH_TOLERANCE
    page.close()


def test_roadmap_mobile_390_has_no_horizontal_overflow(roadmap_url, roadmap_browser):
    page = roadmap_browser.new_page(viewport={"width": 390, "height": 844})
    page.goto(f"{roadmap_url}/roadmap")
    page.wait_for_load_state("domcontentloaded")
    assert _overflow_px(page) <= WIDTH_TOLERANCE
    assert page.get_by_text("FINCO Fair Value", exact=True).count() >= 1
    assert page.get_by_text("Portfolio Modelling", exact=True).count() >= 1
    page.close()


def test_docs_and_roadmap_are_live_finco_remains_placeholder(roadmap_url, roadmap_browser):
    page = roadmap_browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(f"{roadmap_url}/roadmap")
    page.wait_for_load_state("domcontentloaded")
    nav = page.locator(".proto-nav")
    assert nav.locator("a[href='/docs']", has_text="Docs").count() == 1
    assert nav.locator("a[href='/roadmap']", has_text="Roadmap").count() == 1
    assert nav.locator("a", has_text="$FINCO").count() == 0
    assert nav.locator(".proto-nav__link--placeholder", has_text="$FINCO").count() == 1
    page.close()
