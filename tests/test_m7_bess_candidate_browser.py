"""Real Chromium for the isolated release-closed operating-review candidate."""
import os
from pathlib import Path
import socket
import threading
import time

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")
from playwright.sync_api import sync_playwright, expect
from tests.test_m7_bess_candidate_workspace import env, enabled, state  # noqa: F401


@pytest.fixture
def live(env, enabled):
    import uvicorn
    from fastapi.staticfiles import StaticFiles
    env.client.app.mount("/static", StaticFiles(directory="static"), name="static")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(env.client.app, log_level="error"))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(.05)
        assert server.started
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        worker.join(15)
        sock.close()
        assert not worker.is_alive(), "Candidate server did not terminate"


@pytest.mark.parametrize("theme,width", [("light", 1440), ("dark", 390)])
def test_real_candidate_form_validation_and_readonly_reference(env, live, theme, width):
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence.db import get_connection
    before = state(env)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={"width": width, "height": 1000}, color_scheme=theme)
        context.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id="battery-owner", username="battery-owner"), "url": live}])
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"{live}/v2/workbook/bess/candidate?project={env.record.project_code}")
        expect(page.locator('[data-m7-battery="charge_efficiency"]')).to_have_value("90")
        expect(page.locator('[data-m7-validate]')).to_be_enabled()
        scroll = page.locator(".m7-scroll").first
        if width < 1050:
            assert scroll.evaluate("e => e.scrollWidth > e.clientWidth")
            scroll.evaluate("e => e.scrollLeft = e.scrollWidth")
            assert scroll.evaluate("e => e.scrollLeft > 0")
        else:
            assert scroll.locator("table").bounding_box()["width"] <= scroll.bounding_box()["width"] + 1
        page.locator('[data-m7-add-event]').click()
        expect(page.locator('[data-m7-events] input')).not_to_have_count(0)
        page.locator('[data-m7-events] button').click()
        expect(page.locator('[data-m7-events] input')).to_have_count(0)
        page.locator('[data-m7-validate]').click()
        expect(page.locator('[data-testid="bess-operating-evidence"]')).to_contain_text("0.05622000")
        assert page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 1
        directory = os.environ.get("M7_SCREENSHOT_DIR")
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(directory) / f"bess-{theme}-{width}.png"), full_page=True)
        page.locator('[data-m7-point="20"] [data-m7-point-field="sell_price_eur_mwh"]').fill("120")
        page.locator('[data-m7-add-event]').click()
        for key, value in {"at": "2028-01-02T00:00", "installed_energy_mwh": "1.5", "usable_energy_mwh": "1",
                           "cost_keur": "100", "useful_life_years": "5", "source_ref": "finco-paid-synthetic-event"}.items():
            page.locator(f'[data-m7-event-field="{key}"]').fill(value)
        page.locator('[data-m7-event-field="kind"]').select_option("AUGMENT")
        page.locator('[data-m7-validate]').click()
        evidence = page.locator('[data-testid="bess-operating-evidence"]')
        expect(evidence).to_contain_text("0.08862000")
        expect(evidence.locator("dl")).to_contain_text("Lifecycle CAPEX kEUR100.00000000")
        assert state(env) == before
        page.goto(f"{live}/v2/workbook/bess/candidate?project={env.record.project_code}")
        expect(page.locator('[data-testid="bess-operating-evidence"]')).to_have_count(0)
        expect(page.locator('[data-m7-point="20"] [data-m7-point-field="sell_price_eur_mwh"]')).to_have_value("100")
        conn = get_connection()
        try:
            conn.execute("UPDATE projects SET is_protected=1, is_readonly=1, project_role='reference' WHERE project_id=?", (env.record.project_id,))
            conn.commit()
        finally:
            conn.close()
        page.goto(f"{live}/v2/workbook/bess/candidate?project={env.record.project_code}")
        expect(page.locator('[data-testid="bess-reference-readonly"]')).to_be_visible()
        expect(page.locator('[data-m7-battery="charge_power_mw"]')).to_be_disabled()
        expect(page.locator('[data-m7-validate]')).to_have_count(0)
        assert not errors
        context.close()
        browser.close()
