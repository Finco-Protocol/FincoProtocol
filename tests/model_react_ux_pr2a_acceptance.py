"""UX-PR2a — inline read-only CAPEX months / OPEX years in the Lines grid. Real React, real server, synthetic working projects only."""
import json
import os
import re
from pathlib import Path
from urllib.parse import urlencode
from tests.model_react_mvp_acceptance import session


def _profiles(context, base, code):
    r = context.request.get(f'{base}/v2/model-react/capex/profiles?project={code}')
    assert r.status == 200, r.text()
    return r.json()


def _save_profile(context, base, code, rows):
    """The EXISTING canonical profile writer (CSRF + composite CAS), exactly as the Monthly schedule posts it."""
    p = _profiles(context, base, code)
    fields = {'project': code, 'csrf_token': p['save']['csrf_token'], 'content_hash': p['save']['content_hash'], 'action': 'save'}
    for i, (key, shape, explicit, milestone) in enumerate(rows):
        fields.update({f'key_{i}': key, f'shape_{i}': shape, f'explicit_{i}': explicit, f'milestone_{i}': milestone})
    r = context.request.post(f'{base}/v2/capex/spending-profiles/save', data=urlencode(fields),
                             headers={'Content-Type': 'application/x-www-form-urlencoded'}, max_redirects=0)
    assert r.status in (200, 303), (r.status, r.text()[:300])


def check_capex_inline_months(browser, base):
    context, page, record, errors = session(browser, base, 'ux-pr2a-capex', 'wind')
    evidence = Path(os.environ['UX_PR2A_EVIDENCE_DIR']) if os.environ.get('UX_PR2A_EVIDENCE_DIR') else None
    code = record.project_code
    try:
        prof = _profiles(context, base, code)
        months = prof['months']
        items = [i for i in prof['items'] if i['amount_keur'] > 0 and not re.fullmatch(r'C\.\d{2}\.U\d{3}', i['item_key'])]
        assert len(items) >= 2
        uniform, milestone = items[0]['item_key'], items[1]['item_key']
        _save_profile(context, base, code, [(uniform, 'UNIFORM', '', ''), (milestone, 'MILESTONE', '', '1')])
        page.goto(f'{base}/v2/model-react/{code}#inputs/capex')
        grid = page.locator('[data-cost-grid="capex"]'); grid.wait_for(); page.wait_for_selector('[data-saved-total]')
        # Off by default: PR1's compact grid is unchanged.
        assert grid.locator('.ci-h-tl').count() == 0 and grid.locator('.ci-h-sigma').count() == 0
        grid.locator('[data-cost-timeline-toggle="capex"]').click()
        page.wait_for_selector('[data-timeline-note="ready"]')
        heads = grid.locator('thead th').all_text_contents()
        assert 'Σ %' in heads and [h for h in heads if re.fullmatch(r'M\d+', h)] == [f'M{i}' for i in range(1, months + 1)], heads
        # The numbers are the server's own preview of the SAVED document, cell for cell (no browser arithmetic).
        spec = json.dumps([[uniform, 'UNIFORM', '', ''], [milestone, 'MILESTONE', '', '1']])
        preview = context.request.get(f'{base}/v2/model-react/capex/preview?project={code}&' + urlencode({'spec': spec}), headers={'X-Finco-React-Request': '1'}).json()
        assert preview['ok'] is True
        # Resolve rows by the server-assigned display code through the cost-lines payload, then compare every month cell.
        lines = context.request.get(f'{base}/v2/model-react/costlines?project={code}&sheet=capex').json()
        by_code = {l['finco_display_code']: l['sub_line_id'] for l in lines['projection']['lines']}
        for key in (uniform, milestone):
            sub = by_code.get(key)
            assert sub, (key, list(by_code)[:5])
            for n in range(1, months + 1):
                cell = grid.locator(f'[data-timeline-cell="{sub}:M{n}"]')
                assert cell.get_attribute('data-timeline-state') == 'server'
                assert cell.text_content().strip() == preview['plan']['months'][n - 1]['items'][key], (key, n)
            assert grid.locator(f'[data-timeline-sigma="{sub}"]').text_content().strip() == '100%'
        # A line without a saved profile keeps the model default: a dash with the reason, never 0.
        other = next(i['item_key'] for i in items[2:] if i['item_key'] in by_code)
        cell = grid.locator(f'[data-timeline-cell="{by_code[other]}:M1"]')
        assert cell.text_content().strip() == '—' and 'Model default' in (cell.get_attribute('title') or '')
        # Layout: the grid scrolls inside its own region; the page never overflows.
        for w, h in ((1440, 900), (1024, 768)):
            page.set_viewport_size({'width': w, 'height': h}); page.wait_for_timeout(150)
            assert page.evaluate('document.documentElement.scrollWidth-innerWidth') <= 1, w
            assert grid.locator('[data-lines-scroll]').evaluate('el=>el.scrollWidth>el.clientWidth')
            if evidence: page.screenshot(path=str(evidence / f'pr2a-capex-{w}.png'))
        # Mobile: the timeline toggle is not offered (inspector only); no horizontal page overflow.
        for w in (390, 320):
            page.set_viewport_size({'width': w, 'height': 844}); page.wait_for_timeout(150)
            assert grid.locator('[data-cost-timeline-toggle]').count() == 0 and grid.locator('.ci-h-tl').count() == 0
            assert page.evaluate('document.documentElement.scrollWidth-innerWidth') <= 1, w
            if evidence: page.screenshot(path=str(evidence / f'pr2a-capex-{w}.png'))
        assert not errors, errors
    finally:
        context.close()


def check_opex_inline_years(browser, base):
    context, page, record, errors = session(browser, base, 'ux-pr2a-opex', 'wind')
    evidence = Path(os.environ['UX_PR2A_EVIDENCE_DIR']) if os.environ.get('UX_PR2A_EVIDENCE_DIR') else None
    code = record.project_code
    try:
        page.goto(f'{base}/v2/model-react/{code}#inputs/opex')
        grid = page.locator('[data-cost-grid="opex"]'); grid.wait_for(); page.wait_for_selector('[data-saved-total]')
        assert grid.locator('.ci-h-tl').count() == 0
        grid.locator('[data-cost-timeline-toggle="opex"]').click()
        page.wait_for_selector('[data-timeline-note="ready"]')
        proj = context.request.get(f'{base}/v2/model-react/opex-projection/lines?project={code}').json()
        assert proj['ok'] is True
        years = proj['years']
        heads = [h for h in grid.locator('thead th').all_text_contents() if re.fullmatch(r'Y\d+', h)]
        assert heads == [f'Y{i}' for i in range(1, len(years) + 1)]
        saved = [l for g in proj['groups'] if not g['derived'] for l in g['lines']]
        assert saved, 'the synthetic project must carry saved OPEX lines'
        for line in saved[:5]:
            for n in (1, len(years)):
                cell = grid.locator(f'[data-timeline-cell="{line["sub_line_id"]}:Y{n}"]')
                value = line['values'][n - 1]
                assert cell.get_attribute('data-timeline-state') == ('server' if value is not None else 'unavailable'), (line['label'], n)
        # Staged edits are NOT mixed into the saved projection; the note says so.
        first = grid.locator('tr[data-line] input[data-c="1"]').first
        before = first.input_value()
        first.fill('1234.5'); page.wait_for_timeout(100)
        assert 'not' in page.locator('[data-timeline-note="ready"]').text_content() and 'reflected' in page.locator('[data-timeline-note="ready"]').text_content()
        first.fill(before)
        # Last Run all-in OPEX stays its own default-OFF panel.
        r = context.request.get(f'{base}/v2/model-react/opex-run-projection?project={code}')
        assert r.status == 404 and r.json().get('code') == 'G10_RUN_OPEX_PANEL_DISABLED'
        for w in (1440, 1024):
            page.set_viewport_size({'width': w, 'height': 900 if w == 1440 else 768}); page.wait_for_timeout(150)
            assert page.evaluate('document.documentElement.scrollWidth-innerWidth') <= 1, w
            if evidence: page.screenshot(path=str(evidence / f'pr2a-opex-{w}.png'))
        assert not errors, errors
    finally:
        context.close()
