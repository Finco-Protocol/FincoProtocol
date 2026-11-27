"""FINCO48 consolidated canonical React E2E browser suite (real Chromium).

Covers the end-to-end production React Model journey across all shipped verticals
(Solar, Wind, Data Center, EV Charging) under default React ON:

  My Projects / New Project Wizard -> Working Copy Workspace (NOT_RUN)
  -> Run Model (CURRENT) -> Results & Returns -> Statements -> Trust

Verifies zero JS page errors and zero horizontal overflow at desktop (1280px)
and mobile (390px) viewports.
"""
from __future__ import annotations

import os
import socket
import threading
import time

import pytest

pytest.importorskip("playwright")
pytest.importorskip("uvicorn")

from playwright.sync_api import sync_playwright  # noqa: E402


VERTICALS = [
    ("solar", "FINCO48 Solar E2E"),
    ("wind", "FINCO48 Wind E2E"),
    ("data_center", "FINCO48 Data Center E2E"),
    ("ev_charging", "FINCO48 EV Charging E2E"),
]


def _chromium_launch_kwargs() -> dict:
    kwargs: dict = {"args": ["--no-sandbox", "--disable-setuid-sandbox"]}
    exec_path = os.getenv("FINCO_TEST_CHROMIUM_PATH") or (
        "/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else ""
    )
    if exec_path:
        kwargs["executable_path"] = exec_path
    return kwargs


@pytest.fixture(scope="module")
def e2e_server(tmp_path_factory):
    from app.persistence import db

    old_db = db.DB_PATH
    db.DB_PATH = str(tmp_path_factory.mktemp("finco48-e2e") / "finco48_e2e.db")
    db.init_db()

    import main_web
    import uvicorn

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    server = uvicorn.Server(
        uvicorn.Config(main_web.app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 180
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "FINCO48 E2E server did not start in time"
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        db.DB_PATH = old_db


@pytest.fixture(scope="module")
def e2e_browser():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(**_chromium_launch_kwargs())
        yield browser
        browser.close()


def _authed_context(e2e_browser, base_url: str, user_id: str, *, width: int = 1280, height: int = 900):
    from app.auth import COOKIE_NAME, create_session_token

    context = e2e_browser.new_context(viewport={"width": width, "height": height})
    context.add_cookies([{
        "name": COOKIE_NAME,
        "value": create_session_token(user_id=user_id, username=user_id),
        "url": base_url,
    }])
    return context


@pytest.mark.parametrize("tech_key,project_name", VERTICALS)
def test_react_e2e_vertical_journey(e2e_server, e2e_browser, tech_key: str, project_name: str):
    """Create via React template wizard, Run model, and inspect Results, Statements, and Trust."""
    user_id = f"finco48-e2e-{tech_key}"
    context = _authed_context(e2e_browser, e2e_server, user_id)
    page = context.new_page()
    page_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    try:
        # 1. Start at My Projects (canonical React library)
        page.goto(f"{e2e_server}/v2/model-react/", wait_until="load")
        page.locator('[data-library-view="true"]').wait_for(timeout=20000)

        # 2. Navigate via wizard CTA to template selection
        page.locator('[data-choose-template-cta="true"]').click()
        card = page.locator(f'[data-template-card="{tech_key}"][data-creatable="true"]')
        card.wait_for(timeout=20000)
        card.click()
        ack = page.locator('[data-preview-ack="true"]')
        if ack.count() > 0:
            ack.evaluate("el => { el.scrollIntoView({block: 'center'}); el.click(); }")
            page.wait_for_function(
                "() => { const c = document.querySelector('[data-preview-ack=\"true\"]'); return !c || c.checked; }",
                timeout=10000,
            )
        page.locator('[data-wizard-next="true"]').click()

        page.locator('[data-wizard-panel="details"]').wait_for(timeout=15000)
        page.locator("#rcm-name").fill(project_name)
        page.locator('[data-wizard-next="true"]').click()

        create_btn = page.locator('[data-wizard-create="true"]')
        create_btn.wait_for(timeout=15000)
        create_btn.click()
        page.wait_for_url(
            lambda url: "/v2/model-react/" in url and "new-project" not in url,
            timeout=30000,
        )

        # 3. Verify initial NOT_RUN state
        page.locator('[data-workflow-bar="true"][data-bar-freshness="NOT_RUN"]').wait_for(timeout=20000)

        # 4. Trigger canonical Run via React WorkflowBar
        run_btn = page.locator('[data-wf-run="true"]')
        run_btn.wait_for(state="visible", timeout=15000)
        page.wait_for_function(
            "() => { const b = document.querySelector('[data-wf-run=\"true\"]'); return b && !b.disabled; }",
            timeout=15000,
        )
        run_btn.click()
        page.locator('[data-workflow-bar="true"][data-bar-freshness="CURRENT"]').wait_for(timeout=90000)

        # 5. Inspect Results / Returns
        page.locator('[data-workspace-nav="true"] a[href="#results"]').first.click()
        results = page.locator('[data-financial-page="results"][data-financial-state="CURRENT"]')
        results.wait_for(timeout=20000)
        assert page.locator('[data-returns-explainer="true"]').is_visible()
        assert "Project IRR" in results.inner_text()

        # 6. Inspect Statements
        page.locator('[data-workspace-nav="true"] a[href="#statements"]').first.click()
        stmt = page.locator('[data-statements-view="true"]')
        stmt.wait_for(timeout=20000)
        assert stmt.get_attribute("data-statements-state") == "CURRENT"

        # 7. Inspect Trust
        page.locator('[data-workspace-nav="true"] a[href="#trust"]').first.click()
        page.locator('[data-trust-panel="validation"]').wait_for(timeout=20000)
        page.locator('[data-trust-panel="certificate"]').wait_for(timeout=20000)

        # 8. Desktop & 390px mobile overflow checks
        desktop_overflow = page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert desktop_overflow <= 2, f"{tech_key} desktop overflow: {desktop_overflow}px"

        page.set_viewport_size({"width": 390, "height": 844})
        mobile_overflow = page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert mobile_overflow <= 2, f"{tech_key} 390px overflow: {mobile_overflow}px"

        assert page_errors == [], f"Unexpected browser page errors: {page_errors}"
    finally:
        context.close()
