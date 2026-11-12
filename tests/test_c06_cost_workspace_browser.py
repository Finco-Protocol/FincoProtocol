"""C06 added-line profile acceptance: real Chromium, canonical Save/Run and synthetic local data."""
import os
from pathlib import Path
import pytest
from tests.test_workflow_c_browser_v1 import live_server, browser
from tests.model_react_rcm_support import rcm_react_flag
from tests.model_react_mvp_acceptance import session
from tests.model_react_ux_pr2a_acceptance import _profiles
from tests.model_react_wf06b_acceptance import _open_add, _costlines
from tests.model_react_wf1_browser_acceptance import run_canonical

@pytest.mark.parametrize('width', [1440, 390])
def test_added_active_line_profile_save_reload_run(live_server, browser, rcm_react_flag, width):
    context, page, record, errors = session(browser, live_server, f'c06-browser-{width}', 'solar')
    code = record.project_code
    def history():
        return context.request.get(f'{live_server}/v2/model-react/runs?project={code}').json()['runs']
    try:
        page.goto(f'{live_server}/v2/model-react/{code}#inputs/capex')
        page.wait_for_selector('[data-cost-grid="capex"] [data-saved-total]')
        manager = _open_add(page, 'capex', 'C.02')
        manager.get_by_label('Line label').fill('C06 added profile line')
        manager.get_by_label('Amount').fill('120')
        manager.locator('[data-cost-add="capex"]').click()
        page.wait_for_selector('[data-cost-line-commands="capex"] [role="status"]:has-text("verified in the fresh projection")', timeout=30000)
        payload = _costlines(context, live_server, code, 'capex')
        line = next(l for l in payload['lines'] if l['label'] == 'C06 added profile line')
        sub = line['sub_line_id']
        key = next(l['finco_display_code'] for l in payload['projection']['lines'] if l['sub_line_id'] == sub)
        prof = _profiles(context, live_server, code); months = prof['months']
        assert line['active'] and '.U' in key and key in {i['item_key'] for i in prof['items']}
        assert not {i['item_key'] for i in prof.get('excluded', [])} & {i['item_key'] for i in prof['items']}
        page.locator('[data-pr2b-toggle="desktop"]').click()
        page.locator(f'[data-pr2b-shape="{key}"]').select_option('EXPLICIT')
        page.locator(f'[data-pr2b-open="{sub}"]').click()
        ta = page.locator(f'[data-capex-explicit="{key}"]')
        for values in (['100']+['0']*(months-2), ['99']+['0']*(months-1)):
            ta.fill('\t'.join(values)); assert page.locator('[data-capex-save]').is_disabled()
        values = ['37.5']+['0']*(months-2)+['62.5']
        ta.fill('\t'.join(values)); assert page.locator('[data-capex-save]').is_enabled()
        assert page.locator(f'[data-pr2b-editor="{key}"] [data-capex-month-input]').count() == months
        # Saving the profile must leave this separately staged amount unpersisted.
        amount = page.locator(f'tr[data-line="{sub}"] input[data-c="1"]')
        amount.fill('121')
        prior_history = history(); posts=[]
        page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' else None)
        page.locator('[data-capex-save]').click(); page.wait_for_selector('[data-capex-status="ok"]')
        expected = {'shape':'EXPLICIT','explicit':','.join(values),'milestone':''}
        assert _profiles(context, live_server, code)['saved']['rows'][key] == expected
        assert history() == prior_history
        assert len(posts) == 1 and '/spending-profiles/save' in posts[0]
        fresh = next(l for l in _costlines(context, live_server, code, 'capex')['lines'] if l['sub_line_id'] == sub)
        assert float(fresh['amount_keur']) == 120 and amount.input_value() == '121'
        amount.fill('120')
        page.reload(); page.wait_for_selector('[data-cost-grid="capex"] [data-saved-total]')
        assert _profiles(context, live_server, code)['saved']['rows'][key] == expected
        page.set_viewport_size({'width':width,'height':900})
        if width == 390:
            page.locator('[data-pr2b-toggle="mobile"]').click()
            dialog = page.locator('.ux-line-inspector[open]'); dialog.wait_for()
            dialog.locator('[aria-label="Choose line profile"]').select_option(sub)
            assert dialog.locator(f'[data-capex-month-input="{key}:1"]').is_enabled()
        else:
            page.locator('[data-pr2b-toggle="desktop"]').click()
            assert page.locator(f'[data-pr2b-shape="{key}"]').input_value() == 'EXPLICIT'
            page.locator(f'[data-pr2b-open="{sub}"]').click()
        assert page.evaluate('document.documentElement.scrollWidth-innerWidth') <= 1
        if folder := os.environ.get('C06_SCREENSHOT_DIR'):
            Path(folder).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(folder)/f'c06-profile-{width}.png'),full_page=True)
        run_canonical(context, live_server, code)
        assert len(history()) == len(prior_history)+1
        assert _profiles(context, live_server, code)['saved']['rows'][key] == expected
        # A retired profiled row must lose editing eligibility, keeping its saved profile intact.
        page.goto(f'{live_server}/v2/model-react/{code}#inputs/capex')
        page.set_viewport_size({'width':1440,'height':900})
        page.wait_for_selector('[data-cost-grid="capex"] [data-saved-total]')
        row = page.locator(f'tr[data-line="{sub}"]')
        row.locator('[data-row-menu]').click()
        row.locator('[role="menuitem"]').first.click()
        page.get_by_role('button', name='Deactivate line').last.click()
        page.wait_for_selector('[data-cost-line-commands="capex"] [role="status"]:has-text("deactivated and verified")', timeout=30000)
        after_retire = _profiles(context, live_server, code)
        assert key not in {i['item_key'] for i in after_retire['items']}
        assert after_retire['saved']['rows'][key] == expected
        page.reload(); page.wait_for_selector('[data-cost-grid="capex"] [data-saved-total]')
        page.locator('[data-pr2b-toggle="desktop"]').click()
        assert page.locator(f'[data-pr2b-shape="{key}"]:enabled').count() == 0
        assert not errors, errors
    finally:
        context.close()


# ── C06 Correction C + Addenda C1/C2: product truth, label geometry, CAPEX month navigation ──────────

def test_inputs_product_truth_holds_in_both_editor_timing_orders(live_server, browser, rcm_react_flag):
    # Correction C: the revenue-assumptions fields editor mounts asynchronously, so the product-truth scan must
    # hold in BOTH timing orders (before and after it lands). Registry provenance wording (e.g. "…reference
    # assumption") stays available behind the Technical-note disclosure and is never the visible hint of a field.
    context, page, record, errors = session(browser, live_server, 'c06-correction-c-truth', 'solar')
    code = record.project_code
    try:
        run_canonical(context, live_server, code)
        page.goto(f'{live_server}/v2/model-react/{code}#inputs')
        page.reload()
        page.wait_for_selector('[data-react-workspace-version]')
        page.wait_for_function("() => !document.body.innerText.includes('Loading the persisted') && "
                               "!document.body.innerText.includes('Loading the canonical input grid')")
        early = page.inner_text('body').lower()
        page.wait_for_selector("[data-sheet-editor='revenue']", timeout=30000)          # the async editor landed
        page.wait_for_timeout(500)                                                      # its own fields render
        late = page.inner_text('body').lower()
        for body in (early, late):
            for token in ('synthetic', 'prototype', 'demo-fixed', 'fictional'):
                assert token not in body, f'{token!r} visible in the inputs section body'
        assert page.locator("[data-sheet-editor='revenue'] details.rx-tech").count() >= 1   # provenance kept, disclosed on demand
        assert not errors, errors
    finally:
        context.close()


@pytest.mark.parametrize('width', [1440, 390])
def test_assumptions_labels_wrap_at_word_boundaries_never_one_character(live_server, browser, rcm_react_flag, width):
    # Addendum C1: `.rx-input-table` keeps `overflow-wrap: break-word` (not `anywhere`), so no narrow ancestor can
    # collapse a label column to one character per line; labels keep a readable minimum width at 1440 and 390.
    context, page, record, errors = session(browser, live_server, f'c06-c1-{width}', 'solar')
    code = record.project_code
    try:
        page.goto(f'{live_server}/v2/model-react/{code}#inputs')
        page.reload()
        page.wait_for_selector("[data-input-grid='canonical']")
        page.set_viewport_size({'width': width, 'height': 900})
        page.wait_for_timeout(1200)
        probe = page.evaluate("""() => {
          const tables = Array.from(document.querySelectorAll('.rx-input-table'))
            .filter(tb => tb.offsetParent !== null);
          if (!tables.length) return null;
          const th = tables[0].querySelector('th');
          const labels = tables.flatMap(tb => Array.from(tb.querySelectorAll('tbody th, tbody td:first-child')))
            .filter(n => (n.innerText || '').trim().length > 6 && n.getBoundingClientRect().width > 0);
          const rects = labels.map(n => n.getBoundingClientRect());
          return {
            wrap: getComputedStyle(th).overflowWrap,
            tableLayout: getComputedStyle(tables[0]).tableLayout,
            minLabelWidth: rects.length ? Math.round(Math.min(...rects.map(r => r.width))) : null,
            maxLabelHeight: rects.length ? Math.round(Math.max(...rects.map(r => r.height))) : null,
            overflow: document.documentElement.scrollWidth - window.innerWidth,
          };
        }""")
        assert probe is not None and probe['wrap'] == 'break-word', probe
        assert probe['tableLayout'] == 'fixed', probe
        assert probe['minLabelWidth'] >= 100, probe            # no letter-per-line collapse
        assert probe['maxLabelHeight'] <= 90, probe            # no runaway vertical stacking
        assert probe['overflow'] <= 1, probe                   # no page-level horizontal overflow
        if folder := os.environ.get('C06_SCREENSHOT_DIR'):
            Path(folder).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(folder) / f'c06-c1-inputs-{width}.png'), full_page=True)
        assert not errors, errors
    finally:
        context.close()


def test_capex_month_navigation_unit_labels_and_expanded_monthly_view(live_server, browser, rcm_react_flag):
    # Addendum C2: the Lines grid keeps native horizontal scroll with sticky Line/Amount columns, a live
    # M-range indicator and Previous/Next controls; month headers and the note name the unit; month cells stay
    # the exact server text (never re-rounded). The Monthly schedule keeps ONE canonical preview whose large
    # per-month table with Copy / CSV moves under the collapsed Expanded monthly view.
    context, page, record, errors = session(browser, live_server, 'c06-correction-c2-capex', 'solar')
    code = record.project_code
    try:
        page.goto(f'{live_server}/v2/model-react/{code}#inputs/capex')
        page.wait_for_selector('[data-cost-grid="capex"] [data-saved-total]')
        page.locator('[data-cost-timeline-toggle="capex"]').click()
        page.wait_for_selector('[data-timeline-note="ready"]')
        note = page.locator('[data-timeline-note="ready"]').inner_text()
        assert 'kEUR' in note and 'never re-rounds' in note, note
        nav = page.locator('[data-tl-nav="true"]')
        assert nav.count() == 1
        assert 'kEUR' in page.locator('th.ci-h-tl').first.get_attribute('title'), 'month header names the unit'
        before = page.evaluate("document.querySelector('.rx-lines-scroll').scrollLeft")
        nav.locator('[data-tl-next="true"]').click()
        page.wait_for_timeout(700)
        after = page.evaluate("document.querySelector('.rx-lines-scroll').scrollLeft")
        assert after > before, (before, after)
        assert 'M' in nav.locator('[data-tl-range="true"]').inner_text()
        line_cell = page.locator('td.ci-col-line').first
        assert page.evaluate("getComputedStyle(document.querySelector('td.ci-col-line')).position") == 'sticky'
        # Monthly schedule: the duplicated large table is opt-in under Expanded monthly view.
        page.goto(f'{live_server}/v2/model-react/{code}#inputs/capex/monthly')
        page.wait_for_selector("[data-capex-studio='ready']")
        key = page.locator('[data-capex-item]').first.get_attribute('data-capex-item')
        page.locator(f"[data-capex-shape='{key}']").select_option('FRONT_LOADED')
        page.locator('[data-capex-preview]').click()
        page.wait_for_selector("[data-capex-plan='current']")
        expanded = page.locator("[data-capex-expanded-monthly='true']")
        assert expanded.count() == 1 and expanded.get_attribute('open') is None
        assert expanded.locator('[data-copy-table="true"]').count() == 1
        assert expanded.locator('[data-download-csv="true"]').count() == 1
        expanded.locator('summary').click()
        assert page.locator('[data-capex-month]').count() >= 1
        assert 'total (keur)' in page.locator('[data-capex-months]').inner_text().lower()
        assert page.evaluate('document.documentElement.scrollWidth - window.innerWidth') <= 1
        if folder := os.environ.get('C06_SCREENSHOT_DIR'):
            Path(folder).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(folder) / 'c06-c2-capex-months.png'), full_page=True)
        assert not errors, errors
    finally:
        context.close()
