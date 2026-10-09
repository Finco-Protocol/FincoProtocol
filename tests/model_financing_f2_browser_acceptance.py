"""Explicit authenticated F2 browser acceptance; screenshots stay in artifacts."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time


def main():
    import uvicorn
    from playwright.sync_api import sync_playwright, expect
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence import db
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.runtime.model_execution import reset_model_executor_for_tests
    from tests.model_financing_browser_acceptance import contrast
    from main_web import app

    out = Path('artifacts/model-financing-f2')
    out.mkdir(parents=True, exist_ok=True)
    original = db.DB_PATH
    server = thread = None
    evidence = []
    with tempfile.TemporaryDirectory() as tmp:
        try:
            db.DB_PATH = str(Path(tmp) / 'browser.db')
            db.init_db()
            records = [(kind, create_reference_seeded_project(user_id='f2-browser',
                requested_name='F2 ' + kind, template_source='generic_' + kind + '_reference', capacity_mw=16))
                for kind in ('solar', 'wind', 'data_center', 'ev_charging')]
            cookie = create_session_token(user_id='f2-browser', username='admin')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error', lifespan='off'))
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            deadline = time.monotonic() + 30
            while not server.started:
                assert time.monotonic() < deadline
                time.sleep(.1)
            url = f'http://127.0.0.1:{port}'
            with sync_playwright() as pw:
                kwargs = {'executable_path': os.environ['FINCO_TEST_CHROMIUM_PATH']} if os.environ.get('FINCO_TEST_CHROMIUM_PATH') else {}
                browser = pw.chromium.launch(**kwargs)
                try:
                    for kind, record in records:
                        for theme, width in (('light', 1440), ('dark', 1440), ('light', 390), ('dark', 390)):
                            context = browser.new_context(viewport={'width': width, 'height': 1000}, color_scheme=theme)
                            context.add_cookies([{'name': COOKIE_NAME, 'value': cookie, 'url': url}])
                            page = context.new_page()
                            errors = []
                            page.on('pageerror', lambda e: errors.append(str(e)))
                            assert page.goto(url + '/v2/workbook?project=' + record.project_code + '&sheet=debt').status == 200
                            form = page.locator('[data-f2-form]')
                            expect(form.locator('[data-f2-save]')).to_be_enabled()
                            if kind not in ('solar', 'wind'):
                                assert form.locator('[data-f2="lender_case"]').count() == 0
                            for summary in form.locator('summary').all():
                                if not summary.evaluate('el => el.parentElement.open'):
                                    summary.click()
                            form.locator('[data-f2="rates_mode"]').select_option('periods')
                            inputs = form.locator('[data-f2-rate]')
                            expect(inputs.first).to_be_enabled()
                            colors = inputs.first.evaluate('el => { const s=getComputedStyle(el); return [s.color,s.backgroundColor]; }')
                            assert contrast(colors) >= 4.5, colors
                            assert form.bounding_box()['width'] <= width
                            scroll = form.locator('.f2-scroll')
                            if width == 390:
                                assert scroll.evaluate('el => el.scrollWidth > el.clientWidth')
                                scroll.evaluate('el => { el.scrollLeft = 250; }')
                                assert scroll.evaluate('el => el.scrollLeft > 0')
                            screenshot = f'{kind}-{theme}-{width}.png'
                            page.screenshot(path=str(out / screenshot), full_page=True)
                            assert not errors, errors
                            evidence.append(dict(project=kind, theme=theme, width=width, screenshot=screenshot, errors=errors))
                            context.close()
                    for kind, record in records[:2]:
                        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                        context.add_cookies([{'name': COOKIE_NAME, 'value': cookie, 'url': url}])
                        page = context.new_page()
                        page.goto(url + '/v2/workbook?project=' + record.project_code + '&sheet=debt')
                        form = page.locator('[data-f2-form]')
                        form.locator('[data-f2="lender_case"]').select_option('P_50')
                        for summary in form.locator('summary').all():
                            if not summary.evaluate('el => el.parentElement.open'):
                                summary.click()
                        form.locator('[data-f2="rates_mode"]').select_option('periods')
                        form.locator('[data-f2-rate]').first.fill('6.50')
                        with page.expect_response(lambda r: r.url.endswith('/v2/workbook/update')) as result:
                            form.locator('[data-f2-save]').click()
                        assert result.value.status == 200
                        expect(page.locator('[data-f2="lender_case"]')).to_have_value('P_50')
                        ws = get_workspace_state('f2-browser', record.project_id)
                        assert json.loads(ws.draft_snapshot['bankability_config_json'])['lender_case'] == 'P_50'
                        from app.workbook.input_set import ProjectInputSet
                        assert ProjectInputSet.from_snapshot(ws.draft_snapshot).to_projectinputs().financing.senior_debt_interest_config.rate_schedule.explicit_all_in_rates[0] == .065
                        page.reload()
                        expect(page.locator('[data-f2="lender_case"]')).to_have_value('P_50')
                        # Real Run is the existing toolbar action, never a UI-side calculator.
                        run_button = page.locator('#v2-run-controls button').first
                        with page.expect_response(lambda r: r.url.endswith('/v2/workbook/run'), timeout=180000) as result:
                            run_button.click()
                        assert result.value.status == 200
                        expect(page.locator('[data-f2-save]')).to_be_enabled()
                        ws = get_workspace_state('f2-browser', record.project_id)
                        assert ws.last_runtime_summary and not ws.dirty
                        before = ws.last_runtime_snapshot_id
                        page.locator('[data-f2="lender_case"]').select_option('P90-10y')
                        with page.expect_response(lambda r: r.url.endswith('/v2/workbook/update')):
                            page.locator('[data-f2-save]').click()
                        ws = get_workspace_state('f2-browser', record.project_id)
                        assert ws.dirty and ws.last_runtime_snapshot_id == before
                        page.screenshot(path=str(out / (kind + '-stale.png')), full_page=True)
                        evidence.append(dict(project=kind, save=True, reload=True, canonical_run=True, stale=True, immutable_last_run=True))
                        context.close()
                finally:
                    browser.close()
        finally:
            if server:
                server.should_exit = True
            if thread:
                thread.join(timeout=15)
                assert not thread.is_alive(), 'Browser server did not terminate'
            reset_model_executor_for_tests()
            db.DB_PATH = original
    (out / 'evidence.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
