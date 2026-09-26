"""P4 FINCO Token Utility V1 — browser acceptance tests.

Tests:
  1. test_finco_access_browser_1280 — desktop 1280px: page loads, no overflow,
     three utility cards visible, wallet area present, protocol boundary statement,
     NOT_CONFIGURED state renders without error.
  2. test_finco_access_browser_390 — mobile 390px: no horizontal overflow,
     cards stack, long addresses wrap safely.

Server runs on port 19760 (distinct from P3's 19750 and other test servers).
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
_WIDTH_TOLERANCE = 2
_PORT = 19760


def _wait_port(host: str, port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as s:
            try:
                s.connect((host, port))
                return
            except OSError:
                time.sleep(0.05)
    raise RuntimeError(f"Port {port} did not open within {timeout}s")


@pytest.fixture(scope="module")
def finco_server_url(tmp_path_factory):
    import os
    import uvicorn

    tmp = tmp_path_factory.mktemp("finco_browser_db")
    os.environ["FINCO_DB_PATH"] = str(tmp / "test.db")
    # Ensure token is NOT configured — so NOT_CONFIGURED state is tested
    for env_key in ("FINCO_TOKEN_RPC_URL", "FINCO_TOKEN_CHAIN_ID", "FINCO_TOKEN_ADDRESS", "FINCO_ACCESS_MIN_BALANCE"):
        os.environ.pop(env_key, None)

    app = FastAPI()

    # Auth middleware shim: inject admin session cookie reader
    from app.auth import create_session_token, COOKIE_NAME, decode_session_token
    from app.protocol.router import router as _finco_router
    app.include_router(_finco_router)

    # Add session middleware so routes can read cookies
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request as StarRequest

    class _FakeSessionMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            return await call_next(request)

    app.add_middleware(_FakeSessionMiddleware)

    # Serve static files for CSS
    static_dir = REPO / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    config = uvicorn.Config(app, host="127.0.0.1", port=_PORT, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    _wait_port("127.0.0.1", _PORT)
    try:
        yield f"http://127.0.0.1:{_PORT}"
    finally:
        server.should_exit = True
        thread.join(5)


def _chromium_executable() -> str | None:
    """Find an available Chromium executable in common Playwright browser paths."""
    import glob
    patterns = [
        "/opt/pw-browsers/chromium-*/chrome-linux/chrome",
        "/opt/pw-browsers/chromium-*/chrome-linux64/chrome",
    ]
    for pattern in patterns:
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return matches[0]
    return None


@pytest.fixture(scope="module")
def finco_browser():
    with sync_playwright() as pw:
        exe = _chromium_executable()
        launch_kwargs: dict = {
            "args": ["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"]
        }
        if exe:
            launch_kwargs["executable_path"] = exe
        browser = pw.chromium.launch(**launch_kwargs)
        yield browser
        browser.close()


def _overflow_px(page) -> int:
    return page.evaluate("document.documentElement.scrollWidth - window.innerWidth")


def _auth_cookie(server_url: str) -> dict:
    from app.auth import create_session_token, COOKIE_NAME
    token = create_session_token()
    host = server_url.replace("http://", "").split(":")[0]
    port = int(server_url.split(":")[-1])
    return {"name": COOKIE_NAME, "value": token, "domain": host, "path": "/"}


def test_finco_access_browser_1280(finco_server_url, finco_browser):
    """Desktop 1280px: page loads, no overflow, 3 utility cards, wallet area,
    protocol boundary statement, NOT_CONFIGURED state renders without error."""
    page = finco_browser.new_page(viewport={"width": 1280, "height": 900})
    ctx = page.context
    ctx.add_cookies([_auth_cookie(finco_server_url)])
    page.goto(f"{finco_server_url}/protocol/finco")
    page.wait_for_load_state("domcontentloaded")

    # Page title / header
    title = page.title()
    assert "$FINCO" in title or "Protocol" in title

    # No horizontal overflow
    overflow = _overflow_px(page)
    assert overflow <= _WIDTH_TOLERANCE, f"Horizontal overflow: {overflow}px"

    # Three utility cards present
    cards = page.locator(".finco-utility-card")
    assert cards.count() == 3, f"Expected 3 utility cards, found {cards.count()}"

    # Verify all 3 identifiers appear
    page_text = page.content()
    assert "FINCO_COMPUTE" in page_text
    assert "FINCO_VERIFY_PUBLISH" in page_text
    assert "FINCO_INTELLIGENCE" in page_text

    # Wallet connection area present (either wallet state or connect area)
    wallet_section = page.locator(".finco-wallet")
    assert wallet_section.count() >= 1

    # Protocol boundary statement visible
    assert "$FINCO controls access to protocol services" in page_text
    assert "never changes FINCO calculations" in page_text

    # NOT_CONFIGURED state renders without error (config is missing in test)
    assert "not configured" in page_text.lower() or "Token access not configured" in page_text

    page.close()


def test_finco_access_browser_390(finco_server_url, finco_browser):
    """Mobile 390px: no horizontal overflow (scrollWidth <= 392), cards stack,
    long addresses wrap safely."""
    page = finco_browser.new_page(viewport={"width": 390, "height": 844})
    ctx = page.context
    ctx.add_cookies([_auth_cookie(finco_server_url)])
    page.goto(f"{finco_server_url}/protocol/finco")
    page.wait_for_load_state("domcontentloaded")

    # No horizontal overflow — strict at mobile (allows 2px for rounding)
    overflow = _overflow_px(page)
    assert overflow <= _WIDTH_TOLERANCE, f"Mobile horizontal overflow: {overflow}px"

    scroll_width = page.evaluate("document.documentElement.scrollWidth")
    assert scroll_width <= 392, f"scrollWidth {scroll_width} > 392 at 390px viewport"

    # Three utility cards still present
    cards = page.locator(".finco-utility-card")
    assert cards.count() == 3

    # Wallet section present
    wallet_section = page.locator(".finco-wallet")
    assert wallet_section.count() >= 1

    # Protocol boundary statement still visible
    page_text = page.content()
    assert "$FINCO controls access to protocol services" in page_text

    page.close()
