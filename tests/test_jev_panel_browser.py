"""JEV panel browser acceptance (desktop + mobile): experimental labelling, canonical data kept,
calm typed failure states, no overflow, and provider strings rendered as inert text."""
from __future__ import annotations

import copy
import os
import socket
import threading
import time
from pathlib import Path

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api", reason="playwright required")

import test_jev_radar_intelligence as base
import test_jev_shadow_universe_security as sec
from app.radar_rwa.jev_intelligence import service
from app.radar_rwa.jev_intelligence.transport import JevTransportError

_CHROMIUM_EXEC = "/opt/pw-browsers/chromium"
CID = base.CID
REPO = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def jev_app():
    """Minimal app: the real R-LIVE page + real public/intelligence routers, no startup seeding."""
    import uvicorn
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from app.api.v1_1 import institutional
    from app.api.v1_1.r_live_intelligence_router import router as intel_router
    from app.api.v1_1.r_live_public_router import router as public_router
    from app.radar_ui.r_live_router import router as page_router

    mp = pytest.MonkeyPatch()
    mp.setenv("FINCO_JEV_INTELLIGENCE_ENABLED", "1")
    mp.setenv("FINCO_JEV_INTELLIGENCE_MODE", "VISIBLE")
    mp.setenv("TYPESAFE_API_KEY", base.SECRET)
    holder = {"current": sec.real_current(CID), "transport": base.FakeTransport()}
    mp.setattr(institutional, "get_r_live", lambda uid: copy.deepcopy(holder["current"]))
    mp.setattr(service, "default_ranges_provider", lambda _c, _a: base.ranges())
    mp.setattr(service, "default_points_provider", lambda _c: base.points())
    mp.setattr(service, "build_transport", lambda _k: holder["transport"])

    app = FastAPI()
    from app._asset_paths import resolve_static_dir
    app.mount("/static", StaticFiles(directory=resolve_static_dir(str(REPO))), name="static")
    app.include_router(page_router)
    app.include_router(public_router, prefix="/api/v1.1")
    app.include_router(intel_router, prefix="/api/v1.1")
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "JEV browser fixture server did not start"
    try:
        yield {"url": f"http://127.0.0.1:{port}", "holder": holder}
    finally:
        server.should_exit = True
        thread.join(10)
        mp.undo()


@pytest.fixture(scope="module")
def browser():
    kwargs: dict = {"args": ["--no-sandbox", "--disable-setuid-sandbox"]}
    if os.path.exists(_CHROMIUM_EXEC):
        kwargs["executable_path"] = _CHROMIUM_EXEC
    with playwright_sync.sync_playwright() as pw:
        try:
            instance = pw.chromium.launch(**kwargs)
        except Exception as exc:  # noqa: BLE001 - environments without a browser skip, never fail
            pytest.skip(f"chromium unavailable: {type(exc).__name__}")
        yield instance
        instance.close()


VIEWPORTS = [("desktop", 1280, 800), ("mobile", 390, 844)]


def _open(browser, app, width, height, *, transport=None, route=None):
    service._CACHE.clear()
    service._LIMITERS.clear()
    app["holder"]["transport"] = transport or base.FakeTransport()
    page = browser.new_page(viewport={"width": width, "height": height})
    if route:
        page.route("**/intelligence", route)
    page.goto(f"{app['url']}/radar/r-live/{CID}")
    page.wait_for_function("document.getElementById('jev-intelligence').getAttribute('data-jev-state') !== 'LOADING'",
                           timeout=20_000)
    return page


def _no_overflow(page):
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    box = page.locator('[data-testid="jev-intelligence-panel"]').bounding_box()
    assert box is not None and box["x"] >= 0 and box["x"] + box["width"] <= page.viewport_size["width"] + 1


@pytest.mark.parametrize("name,width,height", VIEWPORTS)
def test_available_panel_is_labelled_experimental_and_canonical_data_remains(browser, jev_app, name, width, height):
    page = _open(browser, jev_app, width, height)
    try:
        panel = page.locator('[data-testid="jev-intelligence-panel"]')
        assert panel.get_attribute("data-jev-state") == "AVAILABLE"
        assert page.locator('[data-testid="jev-experimental-badge"]').inner_text().strip().lower() == "experimental"
        assert "not canonical finco market data" in page.locator('[data-testid="jev-scope-note"]').inner_text().lower()
        text = panel.inner_text()
        for expected in ("MOMENTUM", "ELEVATED", "jev-1.13", "last pool activity within 5 minutes"):
            assert expected.lower() in text.lower(), expected
        for label in ("Observation interpreted", "Interpretation generated", "Evidence freshness"):
            assert label in text
        for forbidden in ("BUY", "SELL", "LONG", "SHORT", "target price", "prediction", "forecast"):
            assert forbidden.lower() not in text.lower(), forbidden
        # canonical FINCO evidence is still present and distinct from the interpretation
        assert page.locator("#detail-live-block").count() == 1
        assert page.locator("#detail-premium").inner_text().strip() not in ("", "—")
        assert page.locator('[data-testid="detail-status-badge"]').inner_text().strip().upper() == "AVAILABLE"
        _no_overflow(page)
    finally:
        page.close()


FAILURES = [
    ("provider_unavailable", JevTransportError("HTTP_5XX"), "temporarily unavailable"),
    ("timeout", JevTransportError("TIMEOUT"), "temporarily unavailable"),
    ("invalid_response", None, "Interpretation unavailable."),
]


@pytest.mark.parametrize("name,width,height", VIEWPORTS)
@pytest.mark.parametrize("label,error,message", FAILURES)
def test_provider_failure_states_are_calm_typed_and_do_not_break_canonical_radar(
        browser, jev_app, name, width, height, label, error, message):
    transport = base.FakeTransport(error=error) if error else base.FakeTransport(
        {"model": "jev-1", "answers": {"only": {}}})
    page = _open(browser, jev_app, width, height, transport=transport)
    try:
        panel = page.locator('[data-testid="jev-intelligence-panel"]')
        assert panel.get_attribute("data-jev-state") == "UNAVAILABLE"
        status = page.locator('[data-testid="jev-status"]').inner_text()
        assert message.lower() in status.lower()
        for raw in ("HTTP_5XX", "TIMEOUT", "JEV_", "Traceback", "Exception"):
            assert raw not in status, raw
        assert "color:red" not in (panel.get_attribute("style") or "").lower()
        assert page.locator("#detail-premium").inner_text().strip() not in ("", "—")  # canonical intact
        _no_overflow(page)
    finally:
        page.close()


@pytest.mark.parametrize("name,width,height", VIEWPORTS)
def test_stale_canonical_evidence_offers_no_interpretation(browser, jev_app, name, width, height):
    jev_app["holder"]["current"] = sec.real_current(CID, onchain=sec.AuthorityState.STALE)
    try:
        page = _open(browser, jev_app, width, height)
        try:
            assert page.locator('[data-testid="jev-intelligence-panel"]').get_attribute("data-jev-state") == "UNAVAILABLE"
            assert "stale or unavailable" in page.locator('[data-testid="jev-status"]').inner_text().lower()
            assert page.locator("#detail-live-block").count() == 1  # canonical panel still rendered
            _no_overflow(page)
        finally:
            page.close()
    finally:
        jev_app["holder"]["current"] = sec.real_current(CID)


@pytest.mark.parametrize("name,width,height", VIEWPORTS)
def test_hostile_provider_strings_render_as_inert_text(browser, jev_app, name, width, height):
    payload = ('<img src=x onerror="window.__pwn=1">')
    body = {"state": "AVAILABLE", "data": {
        "state": "AVAILABLE", "input_fingerprint": "a" * 64, "evaluated_at": payload,
        "resolved_model": payload,
        "provenance": {"as_of": payload, "evidence_freshness": payload},
        "answers": {"market_regime": {"choice": payload, "confidence": "0.8"},
                    "attention": {"state": payload, "confidence": "0.7"}}}}

    def fulfill(route):
        route.fulfill(status=200, content_type="application/json", body=__import__("json").dumps(body))

    page = _open(browser, jev_app, width, height, route=fulfill)
    try:
        assert page.evaluate("window.__pwn") is None
        assert page.locator('[data-testid="jev-intelligence-panel"] img').count() == 0
        assert "<img" in page.locator("#jev-model").inner_text()  # shown literally, never interpreted
        _no_overflow(page)
    finally:
        page.close()


@pytest.mark.parametrize("name,width,height", VIEWPORTS)
def test_intelligence_endpoint_http_failure_keeps_page_usable(browser, jev_app, name, width, height):
    def fail(route):
        route.fulfill(status=500, content_type="text/plain", body="Internal Server Error /secret/path")

    page = _open(browser, jev_app, width, height, route=fail)
    try:
        assert page.locator('[data-testid="jev-intelligence-panel"]').get_attribute("data-jev-state") == "UNAVAILABLE"
        assert "/secret/path" not in page.content()
        assert page.locator("#detail-premium").inner_text().strip() not in ("", "—")
        _no_overflow(page)
    finally:
        page.close()
