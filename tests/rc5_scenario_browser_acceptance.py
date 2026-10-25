"""RC-5A browser acceptance: scenario editor admission + status truthfulness (real app, real Run, isolated DB).

Run explicitly: python -m tests.rc5_scenario_browser_acceptance   (FINCO_TEST_CHROMIUM_PATH optional)
"""
from __future__ import annotations

from tests.run_clone_csrf import post_valid_csrf

import os
import re
import socket
import tempfile
import threading
import time
from pathlib import Path

USER = "rc5-browser"
UNBOUND = ["p50_hours", "opex_y1_keur", "total_capex_keur", "gearing_pct", "interest_rate_pct", "tenor_years", "target_dscr"]


def main():
    import uvicorn
    from fastapi.testclient import TestClient
    from playwright.sync_api import sync_playwright, expect
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence import db
    from app.persistence.scenarios_repository import list_scenarios, update_scenario_overrides
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.reference_seed_service import create_reference_seeded_project
    from main_web import app

    out = Path("artifacts/rc5-scenario-browser")
    out.mkdir(parents=True, exist_ok=True)
    original, server = db.DB_PATH, None
    cookie = create_session_token(user_id=USER, username="admin")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            db.DB_PATH = str(Path(tmp) / "rc5.db")
            db.init_db()
            with TestClient(app) as client:
                client.cookies.set(COOKIE_NAME, cookie)
                record = create_reference_seeded_project(user_id=USER, requested_name="RC5 solar",
                                                         template_source="generic_solar_reference", capacity_mw=32)
                page = client.get("/v2/workbook", params={"project": record.project_code})
                tokens = {k: re.search(r'name="' + k + r'" value="([^"]+)"', page.text).group(1) for k in ("content_hash", "workbook_version")}
                assert post_valid_csrf(client, "/v2/workbook/run", headers={"HX-Request": "true"},
                                   data={"project": record.project_code, **tokens}).status_code == 200
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            sock.close()
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="off"))
            threading.Thread(target=server.run, daemon=True).start()
            deadline = time.monotonic() + 30
            while not server.started:
                assert time.monotonic() < deadline
                time.sleep(.1)
            base = f"http://127.0.0.1:{port}/v2/workbook?project={record.project_code}"
            with sync_playwright() as pw:
                kwargs = {"executable_path": os.environ["FINCO_TEST_CHROMIUM_PATH"]} if os.environ.get("FINCO_TEST_CHROMIUM_PATH") else {}
                browser = pw.chromium.launch(**kwargs)
                try:
                    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
                    ctx.add_cookies([{"name": COOKIE_NAME, "value": cookie, "url": f"http://127.0.0.1:{port}"}])
                    page = ctx.new_page()
                    errors = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.goto(base)
                    assert "integrity-pass" in (page.locator("[data-testid=hybrid-integrity]").get_attribute("class") or "")
                    page.goto(base + "&sheet=scenarios")
                    # Repeated create: a double submission yields one scenario.
                    page.fill(".v2-scenario-create-form .v2-scenario-name-input", "Upside")
                    with page.expect_response(lambda r: "/scenarios/create" in r.url):
                        page.click(".v2-scenario-create-form .v2-scenario-create-btn")
                    assert len([s for s in list_scenarios(USER, record.project_id) if not s.is_base_case]) == 1
                    page.goto(base + "&sheet=scenarios")
                    page.fill(".v2-scenario-create-form .v2-scenario-name-input", "Upside")
                    with page.expect_response(lambda r: "/scenarios/create" in r.url) as info:
                        page.click(".v2-scenario-create-form .v2-scenario-create-btn")
                    assert info.value.status == 409
                    assert len([s for s in list_scenarios(USER, record.project_id) if not s.is_base_case]) == 1
                    # Editor: only the tariff is an editable, Run-bound input.
                    page.goto(base + "&sheet=scenarios")
                    page.locator(".v2-scenario-action-btn--edit").first.click()
                    expect(page.locator("#v2-scenario-override-modal")).to_be_visible()
                    expect(page.locator("#ov-tariff_eur_mwh")).to_be_enabled()
                    for key in UNBOUND:
                        expect(page.locator("#ov-" + key)).to_be_disabled()
                    expect(page.locator("[data-testid=override-authority-hint]")).to_contain_text("PPA tariff")
                    page.screenshot(path=str(out / "editor.png"), full_page=True)
                    page.fill("#ov-tariff_eur_mwh", "61.5")
                    with page.expect_response(lambda r: "update-overrides" in r.url) as info:
                        page.click("#v2-scenario-override-form .v2-scenario-create-btn")
                    assert info.value.status == 200
                    child = next(s for s in list_scenarios(USER, record.project_id) if not s.is_base_case)
                    assert child.overrides == {"tariff_eur_mwh": 61.5}
                    # Reopen: the saved value is still visible.
                    page.locator(".v2-scenario-action-btn--edit").first.click()
                    expect(page.locator("#ov-tariff_eur_mwh")).to_have_value("61.5")
                    # A legacy unsupported override is flagged, kept visible and removable.
                    assert update_scenario_overrides(USER, child.scenario_id, {"gearing_pct": 55.0})
                    page.goto(base + "&sheet=scenarios")
                    expect(page.locator("[data-testid=scenario-unbound-overrides]")).to_contain_text("gearing_pct")
                    page.locator(".v2-scenario-action-btn--edit").first.click()
                    expect(page.locator(".v2-override-active-desc[data-unbound='1']")).to_contain_text("Not applied to Run")
                    page.screenshot(path=str(out / "legacy-unbound.png"), full_page=True)
                    with page.expect_response(lambda r: "remove-override" in r.url):
                        page.locator(".v2-scenario-action-btn--reset[data-field=gearing_pct]").click()
                    assert next(s for s in list_scenarios(USER, record.project_id) if not s.is_base_case).overrides == {"tariff_eur_mwh": 61.5}
                    # Status strip: a scenario with no Run must not show the Base Case Integrity PASS.
                    page.goto(base)
                    child = next(s for s in list_scenarios(USER, record.project_id) if not s.is_base_case)
                    page.goto(base)
                    chip = page.locator("[data-testid=hybrid-integrity]")
                    assert "unavailable" in (chip.get_attribute("class") or ""), chip.get_attribute("class")
                    expect(page.locator("[data-testid=hybrid-integrity-note]")).to_be_visible()
                    page.screenshot(path=str(out / "status-no-run.png"), full_page=True)
                    ws = get_workspace_state(USER, record.project_id)
                    assert ws.active_scenario_id == child.scenario_id and not ws.last_runtime_snapshot_id
                    assert not errors, errors
                finally:
                    browser.close()
            print("RC5 BROWSER ACCEPTANCE: PASS")
        finally:
            if server is not None:
                server.should_exit = True
            db.DB_PATH = original


if __name__ == "__main__":
    main()
