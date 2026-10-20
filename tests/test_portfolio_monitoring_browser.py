"""Real Chromium / authenticated HTTP, with real committed Run evidence."""
import os
from pathlib import Path
import socket
import threading
import time

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")
from playwright.sync_api import sync_playwright, expect  # noqa: E402
from tests.test_portfolio_monitoring_real_runs import penv  # noqa: F401
from tests.test_model_decision_workspace_v2 import env  # noqa: F401
from tests.test_model_financing_f2 import run


def test_portfolio_desktop_mobile_filters_details_navigation_and_themes(penv):
    import uvicorn
    from fastapi.staticfiles import StaticFiles
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.run_history_repository import get_run_history
    from app.v2.credit_decision_router import router as credit_router
    penv.client.app.include_router(credit_router, prefix="/v2")
    record = penv.create("solar")
    missing = penv.create("wind")
    run(penv, record)
    before = (get_workspace_state("decision-user", record.project_id), get_run_history("decision-user", record.project_id))
    root = Path(__file__).resolve().parents[1]
    penv.client.app.mount("/static", StaticFiles(directory=root / "static"), name="static")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(penv.client.app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        assert server.started
        with sync_playwright() as pw:
            options = {"args": ["--no-sandbox"]}
            if os.environ.get("FINCO_TEST_CHROMIUM_PATH"):
                options["executable_path"] = os.environ["FINCO_TEST_CHROMIUM_PATH"]
            with pw.chromium.launch(**options) as browser:
                for scheme, width, height in (("light", 1440, 900), ("dark", 1366, 768), ("light", 390, 844), ("dark", 390, 844)):
                    context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme)
                    context.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id="decision-user", username="admin"), "url": f"http://127.0.0.1:{port}"}])
                    context.add_init_script(f"document.addEventListener('DOMContentLoaded',()=>document.documentElement.setAttribute('data-theme','{scheme}'))")
                    page = context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(f"http://127.0.0.1:{port}/v2/portfolio")
                    expect(page.get_by_role("heading", name="Portfolio Monitoring", exact=True)).to_be_visible()
                    expect(page.locator('[data-testid="portfolio-performance"] tbody tr')).to_have_count(2)
                    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
                    for region in page.locator('.pm-scroll').all():
                        region.evaluate("e=>e.scrollLeft=e.scrollWidth")
                        assert region.evaluate("e=>e.scrollWidth>=e.clientWidth")
                        region.evaluate("e=>e.scrollLeft=0")
                    contrast = page.locator('.pm').evaluate("""e => {
                        const rgb=s=>s.match(/[0-9.]+/g).slice(0,3).map(Number).map(v=>{
                            v/=255; return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});
                        const lum=s=>{const c=rgb(s);return .2126*c[0]+.7152*c[1]+.0722*c[2];};
                        const s=getComputedStyle(e), a=lum(s.color), b=lum(s.backgroundColor);
                        return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
                    }""")
                    assert contrast >= 4.5
                    page.locator('[data-testid="portfolio-review"] details').first.locator('summary').click()
                    expect(page.locator('[data-testid="portfolio-review"] details[open]')).to_have_count(1)
                    directory = os.environ.get("PORTFOLIO_SCREENSHOT_DIR")
                    if directory:
                        Path(directory).mkdir(parents=True, exist_ok=True)
                        page.evaluate("window.scrollTo(0,0)")
                        page.screenshot(path=str(Path(directory) / f"portfolio-{scheme}-{width}.png"), full_page=True)
                    page.select_option('select[name="project"]', record.project_code)
                    page.get_by_role('button', name='Apply filters').click()
                    expect(page.locator('[data-testid="portfolio-performance"] tbody tr')).to_have_count(1)
                    page.reload()
                    expect(page.locator('[data-testid="portfolio-performance"] tbody tr')).to_have_count(1)
                    page.go_back()
                    expect(page.locator('[data-testid="portfolio-performance"] tbody tr')).to_have_count(2)
                    page.select_option('select[name="project"]', '')
                    page.select_option('select[name="review"]', 'no_run')
                    page.get_by_role('button', name='Apply filters').click()
                    expect(page.locator('[data-testid="portfolio-performance"] tbody')).to_contain_text(missing.project_name)
                    assert not page.locator('[data-testid="portfolio-review"] a', has_text='Committed Run').count()
                    assert not errors
                    if width == 1440:
                        page.goto(f"http://127.0.0.1:{port}/v2/portfolio")
                        page.get_by_role('link', name='Committed Run', exact=True).click()
                        assert "history_id=" in page.url
                        assert page.locator('body').inner_text().strip()
                        page.go_back()
                        page.get_by_role('link', name='Credit Decision', exact=True).click()
                        expect(page.locator('[data-testid="cd-page"]')).to_be_visible()
                    context.close()
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()
        assert not thread.is_alive()
    assert (get_workspace_state("decision-user", record.project_id), get_run_history("decision-user", record.project_id)) == before
