"""Authenticated two-Senior Save/Reload/Run and narrow/mobile acceptance.

Run with python -m tests.model_financing_f3_browser_acceptance.
Only temporary synthetic projects and local screenshot artifacts are written.
"""
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
    from app.workbook.input_set import ProjectInputSet
    from app.workbook import multisenior_config as config
    from app.runtime.model_execution import reset_model_executor_for_tests
    from tests.test_model_financing_f3_workspace import collection_for_inputs
    from main_web import app

    assert config.ACTIVATION_ENABLED, 'Do not report a disabled editor as executable.'
    out = Path('artifacts/model-financing-f3')
    out.mkdir(parents=True, exist_ok=True)
    original = db.DB_PATH
    server = thread = None
    evidence = []
    with tempfile.TemporaryDirectory() as tmp:
        try:
            db.DB_PATH = str(Path(tmp) / 'browser.db')
            db.init_db()
            records = [(kind, create_reference_seeded_project(user_id='f3-browser',
                requested_name='F3 ' + kind, template_source='generic_' + kind + '_reference', capacity_mw=16))
                for kind in ('solar', 'wind')]
            cookie = create_session_token(user_id='f3-browser', username='admin')
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
                        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                        context.add_cookies([{'name': COOKIE_NAME, 'value': cookie, 'url': url}])
                        page = context.new_page()
                        errors = []
                        page.on('pageerror', lambda e: errors.append(str(e)))
                        assert page.goto(url + '/v2/workbook?project=' + record.project_code + '&sheet=debt').status == 200
                        ws = get_workspace_state('f3-browser', record.project_id)
                        pi = ProjectInputSet.from_snapshot(ws.draft_snapshot).to_projectinputs()
                        terms = collection_for_inputs(pi)
                        form = page.locator('[data-f3-form]')
                        expect(form.locator('[data-f3-save]')).to_be_enabled()
                        for row, instrument in zip(form.locator('[data-f3-instrument]').all(), terms.instruments):
                            row.locator('[data-f3="commitment_keur"]').fill(str(instrument.commitment_keur))
                            row.locator('[data-f3="rate_pct"]').fill(str(instrument.interest.fixed_rate * 100))
                            row.locator('[data-f3="grace_months"]').fill(str(instrument.repayment.grace_months))
                            row.locator('[data-f3="maturity_date"]').fill(instrument.repayment.maturity_date.isoformat())
                            row.locator('[data-f3="draws"]').fill('\n'.join(f'{d.draw_date.isoformat()}, {d.amount_keur}' for d in instrument.drawdowns))
                            row.locator('[data-f3="upfront_pct"]').fill('1')
                            row.locator('[data-f3="commitment_pct"]').fill('0.5')
                        form.locator('[data-f3-activate]').check()
                        with page.expect_response(lambda r: r.url.endswith('/v2/workbook/update')) as response:
                            form.locator('[data-f3-save]').click()
                        assert response.value.status == 200
                        ws = get_workspace_state('f3-browser', record.project_id)
                        entry = config.parse_state(ws.draft_snapshot[config.SNAPSHOT_KEY])['scopes']['base']
                        assert entry['activation'] and entry['proposal']['instruments'][0]['interest']['fixed_rate'] == .04
                        assert ws.dirty and not ws.last_runtime_summary
                        page.reload()
                        expect(page.locator('[data-f3-activate]')).to_be_checked()
                        page.screenshot(path=str(out / (kind + '-saved.png')), full_page=True)
                        with page.expect_response(lambda r: r.url.endswith('/v2/workbook/run'), timeout=180000) as response:
                            page.locator('#v2-run-controls button').first.click()
                        assert response.value.status == 200
                        ws = get_workspace_state('f3-browser', record.project_id)
                        assert ws.last_runtime_summary and not ws.dirty
                        assert len(ws.last_runtime_summary['financing_evidence']['facility_schedules']) == 2
                        assert 'Last Run facility schedules' in page.content()
                        assert 'Construction: actual dated draws' in page.content()
                        su = context.request.get(url + '/v2/financing/sources-uses?project=' + record.project_code)
                        assert su.status == 200, su.text()
                        assert 'Senior debt (contractual)' in su.text()
                        original_run = ws.last_runtime_snapshot_id
                        form = page.locator('[data-f3-form]')
                        form.locator('[data-f3="rate_pct"]').first.fill('5')
                        with page.expect_response(lambda r: r.url.endswith('/v2/workbook/update')):
                            form.locator('[data-f3-save]').click()
                        expect(page.locator('[data-f3-form]')).to_be_visible()
                        ws = get_workspace_state('f3-browser', record.project_id)
                        assert ws.dirty and ws.last_runtime_snapshot_id == original_run
                        assert 'Last Run facility schedules' in page.content()
                        for theme, width in (('light', 1440), ('dark', 1440), ('light', 390), ('dark', 390)):
                            context.set_default_timeout(30000)
                            page.emulate_media(color_scheme=theme)
                            page.set_viewport_size({'width': width, 'height': 1000})
                            # The existing app theme uses data-theme, not only media queries.
                            page.evaluate('(theme) => document.documentElement.setAttribute("data-theme", theme)', theme)
                            panel = page.locator('[data-f3-form]')
                            expect(panel).to_be_visible()
                            assert panel.bounding_box()['width'] <= width
                            for summary in panel.locator('summary').all():
                                summary.click()
                                summary.click()
                            screenshot = f'{kind}-{theme}-{width}.png'
                            page.screenshot(path=str(out / screenshot), full_page=True)
                            panel.screenshot(path=str(out / ('editor-' + screenshot)))
                            from tests.model_financing_browser_acceptance import contrast
                            colors = panel.locator('[data-f3="rate_pct"]').first.evaluate('el => { const s=getComputedStyle(el); return [s.color,s.backgroundColor]; }')
                            assert contrast(colors) >= 4.5, colors
                            evidence.append(dict(project=kind, theme=theme, width=width, screenshot=screenshot,
                                save=True, reload=True, run=True, stale=True, last_run_immutable=True, errors=list(errors)))
                        assert not errors, errors
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
