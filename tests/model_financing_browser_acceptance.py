"""Authenticated Workflow B browser acceptance. Run explicitly, not during unit collection.

python -m tests.model_financing_browser_acceptance
Evidence remains untracked under artifacts/model-financing-bankability/.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import socket
import tempfile
import threading
import time


def contrast(colors):
    def luminance(rgb):
        channels = [int(c) / 255 for c in re.findall(r"\d+", rgb)[:3]]
        channels = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
        return sum(c * w for c, w in zip(channels, (.2126, .7152, .0722)))
    lum = sorted(luminance(c) for c in colors)
    return (lum[1] + .05) / (lum[0] + .05)


def main():
    import uvicorn
    from fastapi.testclient import TestClient
    from playwright.sync_api import sync_playwright, expect
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence import db
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.workbook.service import WorkbookService
    from app.runtime.model_execution import reset_model_executor_for_tests
    from main_web import app

    out = Path("artifacts/model-financing-bankability")
    out.mkdir(parents=True, exist_ok=True)
    original = db.DB_PATH
    server = thread = None
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        try:
            db.DB_PATH = str(Path(tmp) / "browser.db")
            db.init_db()
            records = []
            cookie = create_session_token(user_id="finance-browser", username="admin")
            with TestClient(app) as client:
                client.cookies.set(COOKIE_NAME, cookie)
                for kind, capacity in (("solar", 64), ("wind", 48), ("data_center", 16), ("ev_charging", 1)):
                    record = create_reference_seeded_project(user_id="finance-browser", requested_name="Bankability " + kind,
                        template_source="generic_" + kind + "_reference", capacity_mw=capacity)
                    page = client.get("/v2/workbook", params={"project": record.project_code})
                    assert page.status_code == 200
                    h = re.search(r'name="content_hash" value="([^"]+)"', page.text).group(1)
                    v = re.search(r'name="workbook_version" value="([^"]+)"', page.text).group(1)
                    response = client.post("/v2/workbook/run", headers={"HX-Request": "true"}, data={
                        "project": record.project_code, "content_hash": h, "workbook_version": v})
                    assert response.status_code == 200, response.text[:1000]
                    records.append((kind, record))
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            sock.close()
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="off"))
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            deadline = time.monotonic() + 30
            while not server.started:
                assert time.monotonic() < deadline, "Server startup timeout"
                time.sleep(.1)
            with sync_playwright() as pw:
                kwargs = {"executable_path": os.environ["FINCO_TEST_CHROMIUM_PATH"]} if os.environ.get("FINCO_TEST_CHROMIUM_PATH") else {}
                browser = pw.chromium.launch(**kwargs)
                try:
                    for kind, record in records:
                        before = get_workspace_state("finance-browser", record.project_id)
                        for theme, width in (("light", 1440), ("dark", 1440), ("light", 390), ("dark", 390)):
                            context = browser.new_context(viewport={"width": width, "height": 1000}, color_scheme=theme)
                            context.add_cookies([{"name": COOKIE_NAME, "value": cookie, "url": f"http://127.0.0.1:{port}"}])
                            page = context.new_page()
                            errors = []
                            page.on("pageerror", lambda e: errors.append(str(e)))
                            for sheet in ("overview", "debt", "investor"):
                                response = page.goto(f"http://127.0.0.1:{port}/v2/workbook?project={record.project_code}&sheet={sheet}")
                                assert response.status == 200
                                page.locator('[data-testid="financial-integrity-status"]').wait_for(state="attached")
                                if sheet == "overview":
                                    status = page.locator('[data-testid="financial-integrity-status"]')
                                    assert status.is_visible()
                                    assert status.bounding_box()["y"] < 700, "Integrity below first viewport"
                                if sheet == "debt":
                                    panel = page.locator('#v2-sheet-senior-debt')
                                    assert panel.is_visible()
                                    cfads = page.locator('[data-testid="cfads-period-1"]')
                                    assert cfads.count() == 1
                                    inputs = panel.locator('input[name="value"]')
                                    assert inputs.count() >= 4
                                    colors = inputs.first.evaluate("el => {const s=getComputedStyle(el);return [s.color,s.backgroundColor]}")
                                    assert contrast(colors) >= 4.5, colors
                                    headings = panel.locator('.v2-inputs-section-summary')
                                    colors = headings.first.evaluate("el => {const s=getComputedStyle(el);return [s.color,s.backgroundColor]}")
                                    assert contrast(colors) >= 4.5, colors
                                    assert panel.bounding_box()["width"] <= width
                                if sheet == "investor":
                                    assert page.locator('[data-testid="investor-return-evidence"]').is_visible()
                                filename = f"{kind}-{sheet}-{theme}-{width}.png"
                                page.screenshot(path=str(out / filename), full_page=True)
                                assert not errors, errors
                                results.append({"kind": kind, "sheet": sheet, "theme": theme, "width": width, "screenshot": filename})
                            context.close()
                        assert get_workspace_state("finance-browser", record.project_id) == before
                    for kind, record in records[:2]:
                        context = browser.new_context(viewport={"width": 1440, "height": 1000})
                        context.add_cookies([{"name": COOKIE_NAME, "value": cookie, "url": f"http://127.0.0.1:{port}"}])
                        page = context.new_page()
                        page.goto(f"http://127.0.0.1:{port}/v2/workbook?project={record.project_code}&sheet=debt")
                        field = page.locator('[data-field-id="debt.senior.interest_rate_pct"] input[name="value"]')
                        field.fill("5.50")
                        with page.expect_response(lambda r: "/v2/workbook/update" in r.url and r.request.method == "POST"):
                            field.press("Enter")
                        page.locator("#tab-investor").click()
                        expect(page.locator('[data-testid="investor-freshness"]')).to_contain_text("STALE", timeout=30000)
                        page.screenshot(path=str(out / f"{kind}-investor-after-save.png"), full_page=True)
                        page.locator('[data-testid="header-run-btn"]').click()
                        expect(page.locator('[data-testid="investor-freshness"]')).to_contain_text("CURRENT", timeout=120000)
                        page.screenshot(path=str(out / f"{kind}-investor-after-run.png"), full_page=True)
                        results.append({"kind": kind, "workflow": "HTMX Save -> Investor STALE -> Run -> Investor CURRENT"})
                        context.close()
                finally:
                    browser.close()
            (out / "acceptance.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
            print(f"{len(results)} authenticated browser views passed; evidence: {out}")
        finally:
            if server:
                server.should_exit = True
            if thread:
                thread.join(10)
                assert not thread.is_alive(), "Browser server failed to stop"
            reset_model_executor_for_tests()
            db.DB_PATH = original


if __name__ == "__main__":
    main()
