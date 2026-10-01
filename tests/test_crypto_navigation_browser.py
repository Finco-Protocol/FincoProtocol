"""Browser regression for FINCO primary-product navigation."""
from __future__ import annotations

import os
import socket
import threading
import time

import pytest

pytest.importorskip("playwright")
pytest.importorskip("uvicorn")

from playwright.sync_api import sync_playwright  # noqa: E402

_CHROMIUM_EXEC = os.getenv("FINCO_TEST_CHROMIUM_PATH")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def live_url(tmp_path_factory):
    os.environ["FINCO_DB_PATH"] = str(tmp_path_factory.mktemp("crypto-nav") / "finco.db")
    import main_web
    import uvicorn

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


@pytest.fixture(scope="module")
def browser():
    launch_kwargs = {"args": ["--no-sandbox", "--disable-setuid-sandbox"]}
    if _CHROMIUM_EXEC:
        launch_kwargs["executable_path"] = _CHROMIUM_EXEC
    with sync_playwright() as pw:
        instance = pw.chromium.launch(**launch_kwargs)
        yield instance
        instance.close()


def test_home_architecture_and_shared_nav_are_consistent(live_url, browser):
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    page.goto(f"{live_url}/")
    page.wait_for_load_state("domcontentloaded")
    assert "MODEL · RADAR · YIELD · CRYPTO" in page.inner_text("body")
    nav = page.locator(".proto-nav")
    for label, href in (("Model", "/library"), ("Radar", "/radar"),
                        ("Yield", "/yield"), ("Crypto", "/crypto")):
        link = nav.locator(f'a[href="{href}"]')
        assert link.count() == 1, f"missing shared-nav {label} link"
        assert label in link.inner_text()
    page.close()


def test_crypto_page_marks_shared_crypto_nav_active(live_url, browser):
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    page.goto(f"{live_url}/crypto")
    page.wait_for_load_state("domcontentloaded")
    crypto = page.locator('.proto-nav a[href="/crypto"]')
    assert crypto.count() == 1
    assert "proto-nav__link--active" in (crypto.get_attribute("class") or "")
    assert crypto.get_attribute("aria-current") == "page"
    page.close()
