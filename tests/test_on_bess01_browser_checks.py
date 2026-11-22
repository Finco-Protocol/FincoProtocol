"""On-demand genuine UI proof. Explicit local invocation only; no CI imports.

PLAYWRIGHT_BROWSERS_PATH and BESS_SCREENSHOT_DIR select local tooling/evidence.
"""
import json
import os
from pathlib import Path
import socket
import threading
import time

import pytest


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    import uvicorn
    from app.persistence import db
    mp = pytest.MonkeyPatch()
    mp.setattr(db, "DB_PATH", str(tmp_path_factory.mktemp("bess-preview") / "synthetic.db"))
    mp.setenv("FINCO_MODEL_REACT_V1", "1")
    db.init_db()
    import main_web
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    instance = uvicorn.Server(uvicorn.Config(main_web.app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=instance.run, daemon=True); thread.start()
    deadline = time.monotonic() + 30
    while not instance.started:
        if time.monotonic() > deadline: raise RuntimeError("Synthetic local server did not start")
        time.sleep(.05)
    yield f"http://127.0.0.1:{port}"
    instance.should_exit = True; thread.join(10)
    from app.runtime.model_execution import reset_model_executor_for_tests
    reset_model_executor_for_tests(None)
    mp.undo()


@pytest.fixture
def page(server):
    from playwright.sync_api import sync_playwright
    from app.auth import COOKIE_NAME, create_session_token
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id="synthetic-bess-browser", username="admin"), "url": server}])
        page = context.new_page()
        yield page
        context.close(); browser.close()


def open_preview(page, server):
    page.goto(server + "/v2/model-react/#new-project/new")
    page.locator("[data-bess-setup]").wait_for()
    assert page.locator('[data-tech-card="storage"]').is_disabled()
    page.get_by_role("button", name="Preview standalone Storage inputs").click()


def config():
    from domain.bess.synthetic import example
    return json.dumps({"version": 1, "configuration": example(), "variable_om_eur_per_dc_mwh": 0})


@pytest.mark.parametrize("width", [1440, 1024, 390, 320])
def test_real_setup_preview_at_required_widths(page, server, width):
    from playwright.sync_api import expect
    errors, posts = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: posts.append(r.url) if r.method != "GET" else None)
    page.set_viewport_size({"width": width, "height": 1000})
    open_preview(page, server)
    page.locator("#bess-native-json").fill(config())
    page.get_by_role("button", name="Validate setup on server").click()
    expect(page.locator("[data-bess-validated]")).to_be_visible()
    shots = os.environ.get("BESS_SCREENSHOT_DIR")
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(shots) / f"bess-{width}-native-valid.png"), full_page=True)
    page.locator('[data-bess-field="discharge_power_mw"]').fill("2")
    expect(page.locator("[data-bess-validated]")).to_have_count(0)
    page.get_by_role("button", name="Validate setup on server").click()
    expect(page.locator("[data-bess-validated]")).to_be_visible()
    expected = float(json.loads(config())["configuration"]["battery"]["usable_energy_mwh"]) / 2
    assert float(page.locator("output").inner_text().split()[0]) == expected
    page.locator('[data-bess-field="discharge_power_mw"]').fill("0")
    page.get_by_role("button", name="Validate setup on server").click()
    expect(page.locator("[data-bess-error]")).to_contain_text("BESS_NUMBER")
    assert page.locator('[data-bess-field="discharge_power_mw"]').input_value() == "0"
    assert page.locator("#bess-native-json").input_value() == config()
    assert not page.locator("[data-wizard-create]").count()
    assert page.locator("[data-wizard-next]").is_disabled()
    page.get_by_role("button", name="Hide setup preview (keep input)").click()
    page.get_by_role("button", name="Preview standalone Storage inputs").click()
    assert page.locator('[data-bess-field="discharge_power_mw"]').input_value() == "0"
    page.get_by_text("Why Create, Save and Run are unavailable", exact=True).click()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    assert all(url.endswith("/bess-preview") for url in posts), posts
    assert not errors
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(shots) / f"bess-{width}-invalid-gated.png"), full_page=True)


def test_keyboard_navigation_cancel_and_path_change_retain_local_input(page, server):
    from playwright.sync_api import expect
    open_preview(page, server)
    expect(page.locator("#bess-local-preview h4")).to_be_focused()
    page.keyboard.press("Tab")
    expect(page.locator("#bess-native-json")).to_be_focused()
    page.locator("#bess-native-json").fill(config())
    page.get_by_role("button", name="Validate setup on server").click()
    expect(page.locator("[data-bess-validated]")).to_be_visible()
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.locator("[data-wizard-cancel]").click()
    assert page.locator("#bess-native-json").input_value() == config()
    page.locator("[data-path-change]").click()
    page.locator('[data-path-card="template"]').click()
    assert page.locator("#bess-native-json").input_value() == config()
    # The existing template API omits non-cloneable sources. Storage's separate
    # capability/preview remains visible without adding a creation handle.
    expect(page.locator('[data-template-card="solar"]')).to_be_visible()
    storage = page.locator('[data-template-card="storage"]')
    assert storage.count() == 0 or storage.is_disabled()
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.evaluate("location.hash = 'library'")
    expect(page.locator("#bess-native-json")).to_have_value(config())
    assert page.evaluate("location.hash").startswith("#new-project")


def test_input_change_invalidates_late_validation_response(page, server):
    from playwright.sync_api import expect
    open_preview(page, server)
    page.locator("#bess-native-json").fill(config())
    held = []
    page.route("**/new-project/bess-preview", lambda route: held.append(route))
    page.get_by_role("button", name="Validate setup on server").click()
    deadline = time.monotonic() + 5
    while not held:
        if time.monotonic() > deadline: raise AssertionError("No preview request")
        page.wait_for_timeout(20)
    page.locator("#bess-native-json").fill("{}")
    held[0].fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True,
        "capability": {"preview_supported": True}, "preview": {"battery": {"duration_hours": "999"}}}))
    page.wait_for_timeout(150)
    expect(page.locator("[data-bess-validated]")).to_have_count(0)
    assert page.locator("#bess-native-json").input_value() == "{}"
