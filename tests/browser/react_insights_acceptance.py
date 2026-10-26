"""Explicit local browser acceptance over real isolated Solar/Wind Run APIs.

Not a pytest collection module: Chromium is required, never collection-skipped.
Builds an isolated component harness, not the shipped/shared React application.
Run: python tests/browser/react_insights_acceptance.py --output /tmp/wf3-proof
"""
from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_HALF_UP
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def build_harness(work: Path) -> Path:
    root = work / 'harness'
    root.mkdir(parents=True, exist_ok=True)
    modules = ROOT / 'frontend/node_modules'
    entry = ROOT / 'frontend/src/app/insights/index.ts'
    (root / 'entry.tsx').write_text(
        "import React from 'react'; import {createRoot} from 'react-dom/client';\n"
        f"import {json.dumps(str(ROOT / 'frontend/src/styles/finco-react.css'))};\n"
        f"import {json.dumps(str(ROOT / 'frontend/src/styles/fm-themes.css'))};\n"
        f"import {{FinancialInsights}} from {json.dumps(str(entry))};\n"
        "createRoot(document.getElementById('root')!).render(<FinancialInsights "
        "project={new URLSearchParams(location.search).get('project') || ''}/>);\n")
    (root / 'index.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Isolated real-API analytics acceptance</title>'
        '<body><p>ISOLATED ACCEPTANCE HARNESS — not the production React shell</p>'
        '<main id="root" class="rx-page" data-fm-theme="b-slate-teal"></main>'
        '<script type="module" src="/entry.tsx"></script></body></html>')
    config = root / 'vite.config.mjs'
    dist = root / 'dist'
    config.write_text('export default ' + json.dumps({
        'root': str(root), 'base': '/__wf3_assets/',
        'resolve': {'alias': {'react': str(modules / 'react'), 'react-dom': str(modules / 'react-dom')}},
        'esbuild': {'jsx': 'automatic'},
        'build': {'outDir': str(dist), 'emptyOutDir': True},
    }) + ';\n')
    subprocess.run(['node', str(modules / 'vite/bin/vite.js'), 'build', '--config', str(config)],
                   cwd=ROOT / 'frontend', check=True)
    return dist


def exercise(output: Path):
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles
    from playwright.sync_api import sync_playwright
    import uvicorn
    from tests.insights_browser_fixture import browser_fixture

    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='wf3-harness-') as directory:
        dist = build_harness(Path(directory))
        with browser_fixture(output) as (app, records, cookie, db_snapshot):
            app.mount('/__wf3_assets', StaticFiles(directory=dist), name='wf3-acceptance-assets')
            @app.get('/__wf3_acceptance')
            def harness():
                return HTMLResponse((dist / 'index.html').read_text())
            sock = socket.socket()
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
            base = f'http://127.0.0.1:{port}'
            server = uvicorn.Server(uvicorn.Config(app, log_level='warning'))
            thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
            thread.start()
            deadline = time.monotonic() + 20
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(.05)
            assert server.started, 'Local acceptance server failed to start'
            proof, errors, forbidden, network = [], [], [], []
            before = db_snapshot()
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(executable_path=os.environ.get('FINCO_TEST_CHROMIUM_PATH', '/usr/bin/chromium'),
                                                 args=['--no-sandbox'])
                    context = browser.new_context()
                    context.add_cookies([{**cookie, 'url': base}])
                    def guard(route):
                        request = route.request
                        if request.method not in ('GET', 'HEAD', 'OPTIONS') or '/v2/workbook/' in request.url:
                            forbidden.append({'method': request.method, 'url': request.url})
                            route.abort()
                        else:
                            route.continue_()
                    context.route('**/*', guard)
                    for kind in ('solar', 'wind'):
                        record = next(r for r in records if r['kind'] == kind)
                        page = context.new_page()
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.on('response', lambda r: network.append({'url': r.url, 'status': r.status})
                                if '/model-react/insights' in r.url else None)
                        page.goto(f'{base}/__wf3_acceptance?project={record["code"]}')
                        boxes = page.locator('input[type=checkbox]')
                        boxes.first.wait_for()
                        assert boxes.count() >= 1
                        assert page.locator('[data-selected-history]').count() == 0, 'No implicit Run selection'
                        boxes.first.focus()
                        page.keyboard.press('Space')
                        assert boxes.first.is_checked()
                        page.get_by_role('button', name='Read selected Run evidence').focus()
                        page.keyboard.press('Enter')
                        panel = page.locator('[data-selected-history]').first
                        panel.wait_for()
                        selected_id = panel.get_attribute('data-selected-history')
                        oracle = next(r['payload']['runs'][0] for r in records if r['history_id'] == selected_id)
                        for metric in oracle['metrics']:
                            card = panel.locator(f'[data-metric="{metric["key"]}"]')
                            assert card.get_attribute('data-snapshot-id') == oracle['identity']['snapshot_id']
                            raw = metric['raw_value']
                            if raw is None:
                                assert card.get_attribute('data-available') == 'false'
                                assert 'Unavailable' in card.inner_text()
                            else:
                                assert float(card.get_attribute('data-raw-value')) == raw
                                if metric['unit'].lower() in ('keur', 'eur', 'meur'):
                                    # Approved display formatter uses two decimals in the same source unit.
                                    text = card.locator('.fi-metric-value').inner_text().replace('kEUR', '').replace('EUR', '').replace('mEUR', '').replace(',', '').strip()
                                    negative = text.startswith('(') and text.endswith(')')
                                    shown = Decimal(text.strip('()')) * (-1 if negative else 1)
                                    assert shown == Decimal(str(raw)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
                        timeline = oracle['credit']['timeline']
                        figures = panel.locator('.fi-chart')
                        chart_rows = [r for r in timeline.get('rows', []) if r['kind'] != 'flag']
                        assert figures.count() == len(chart_rows)
                        for index, row in enumerate(chart_rows):
                            values = [c['v'] for c in row['cells']]
                            finite = [v for v in values if isinstance(v, (int, float)) and math.isfinite(v)]
                            circles = figures.nth(index).locator('circle')
                            assert circles.count() == len(finite)
                            low, high = min([0, *finite]), max([0, *finite])
                            span = high - low or 1
                            expected = [(24 + n / max(1, len(values) - 1) * 592,
                                         144 - (v - low) / span * 128)
                                        for n, v in enumerate(values) if isinstance(v, (int, float)) and math.isfinite(v)]
                            for circle, (x, y) in zip(circles.all(), expected):
                                assert math.isclose(float(circle.get_attribute('cx')), x, abs_tol=1e-8)
                                assert math.isclose(float(circle.get_attribute('cy')), y, abs_tol=1e-8)
                        panel.locator('.fi-evidence summary').first.focus()
                        page.keyboard.press('Enter')
                        assert oracle['identity']['composite_hash'] in panel.inner_text()
                        # Tables preserve genuine sponsor and distribution row identities.
                        assert panel.get_by_text('Sponsor and investment evidence', exact=True).count() == 1
                        for width in (1440, 820, 390):
                            page.set_viewport_size({'width': width, 'height': 1000})
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Document overflow {kind}/{width}'
                            page.evaluate('scrollTo(0, 0)')
                            page.screenshot(path=str(output / f'{kind}-{width}.png'))
                            proof.append({'kind': kind, 'width': width, 'history_id': selected_id,
                                          'snapshot_id': oracle['identity']['snapshot_id'], 'chart_series': len(chart_rows),
                                          'original_numeric_values_match': True, 'document_overflow': False})
                        panel.locator('.fi-chart').first.screenshot(path=str(output / f'{kind}-timeline.png'))
                        if boxes.count() > 1:
                            boxes.nth(1).check()
                            page.get_by_role('button', name='Read selected Run evidence').click()
                            page.wait_for_function('document.querySelectorAll("[data-selected-history]").length === 2')
                            assert page.get_by_role('region', name='Scenario KPI comparison').count() == 1
                            assert page.locator('[data-selected-history]').count() == 2
                            ids = page.locator('[data-selected-history]').evaluate_all('(rows) => rows.map(row => row.dataset.selectedHistory)')
                            query = '&'.join('run=' + identifier for identifier in ids)
                            comparison = page.evaluate('async url => (await fetch(url)).json()',
                                f'{base}/v2/model-react/insights?project={record["code"]}&{query}')
                            assert [r['identity']['history_id'] for r in comparison['runs']] == ids
                            table = page.get_by_role('region', name='Scenario KPI comparison')
                            for row in comparison['comparison']['rows']:
                                assert row['label'] in table.inner_text()
                                for delta in row['deltas'][1:]:
                                    assert f'Change: {delta}' in table.inner_text()
                        page.close()
                    context.close()
                    browser.close()
                assert db_snapshot() == before, 'Analytics browser flow mutated persisted state'
                assert not errors, errors
                assert not forbidden, forbidden
                result = {'status': 'PASS', 'scope': 'Isolated component harness using real local committed Solar/Wind API evidence; not main-shell activation',
                          'cases': proof, 'database_unchanged': True, 'page_errors': errors,
                          'forbidden_requests': forbidden, 'network': network}
                (output / 'browser-proof.json').write_text(json.dumps(result, indent=2) + '\n')
                print(json.dumps({'status': 'PASS', 'viewport_cases': len(proof), 'database_unchanged': True}))
            finally:
                server.should_exit = True
                thread.join(timeout=15)
                sock.close()
                if thread.is_alive():
                    raise RuntimeError('Acceptance server did not shut down')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    exercise(parser.parse_args().output.resolve())
