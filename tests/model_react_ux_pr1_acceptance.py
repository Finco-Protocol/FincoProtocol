"""Real React, real server, synthetic working projects only; no private source material."""
import json
import os
from pathlib import Path
from tests.model_react_mvp_acceptance import session
from tests.model_react_wf06b_acceptance import _costlines


def check_dense_comments_and_responsive(browser,base):
    context,page,record,errors=session(browser,base,'ux-pr1-dense','wind')
    evidence=Path(os.environ['UX_PR1_EVIDENCE_DIR']) if os.environ.get('UX_PR1_EVIDENCE_DIR') else None
    try:
        page.goto(f'{base}/v2/model-react/{record.project_code}#capex')
        grid=page.locator('[data-cost-grid="capex"]');grid.wait_for()
        page.wait_for_selector('[data-saved-total]')
        assert page.locator('[data-workspace-destination="inputs/capex"]').get_attribute('aria-current')=='page'
        assert grid.locator('.ci-h-notes').count()==0 and grid.locator('.ci-h-status').count()==0
        assert grid.locator('thead th').all_text_contents()[:2]==['Line','Amount (kEUR)']
        measures=[]
        for w,h in ((1440,900),(1024,768),(850,844),(390,844)):
            page.set_viewport_size({'width':w,'height':h});page.wait_for_timeout(150)
            if w<=900:
                nav=page.locator('#wsv2-navigation')
                assert not nav.is_visible()
                page.locator('.wsv2-menu').click()
                page.wait_for_function("() => document.activeElement?.closest('#wsv2-navigation') !== null")
                assert nav.is_visible()
                page.keyboard.press('Escape');assert not nav.is_visible()
            page.evaluate('scrollTo(0,0)')
            m=grid.evaluate('''g=>{let rows=[...g.querySelectorAll('tr[data-line],tr[data-group-row]')].filter(e=>!e.hidden);let meaningful=rows.filter(e=>e.hasAttribute('data-line')||e.querySelector('[data-group-saved-total]'));let rects=meaningful.map(e=>e.getBoundingClientRect());return {first:rects[0].top,visible:rects.filter(r=>r.height>0&&r.top>=0&&r.bottom<=innerHeight).length,overflow:document.documentElement.scrollWidth-innerWidth,leafFont:getComputedStyle(g.querySelector('tr[data-line] input')).fontSize}}''')
            assert m['overflow']<=1,m
            if w==1440:
                assert m['first']<225,m
                assert m['visible']>=25,m
                assert m['leafFont']=='13px',m
            measures.append({'width':w,'height':h,**m})
            if evidence: page.screenshot(path=str(evidence/f'accepted-capex-{w}.png'))
        # Fullscreen mobile inspector edits the SAME notes field; closing never discards it.
        first=grid.locator('tr[data-line]').first
        line_id=first.get_attribute('data-line')
        saved=next(l for l in _costlines(context,base,record.project_code,'capex')['projection']['lines'] if l['sub_line_id']==line_id)
        before=saved.get('notes') or ''
        first.locator('.ux-comment-presence').click()
        dialog=page.get_by_role('dialog',name='Line details and comment')
        assert dialog.is_visible()
        comment=dialog.locator('[data-cost-notes-for]');assert comment.input_value()==before
        probe='FINCO synthetic comment · unchanged exact text 12.3400'
        comment.fill(probe)
        page.keyboard.press('Escape');assert not dialog.is_visible()
        first.locator('.ux-comment-presence').click();assert comment.input_value()==probe
        page.get_by_role('button',name='Close line details').click()
        page.set_viewport_size({'width':1440,'height':900})
        grid.locator('[data-cost-comments]').click()
        assert grid.locator('thead th').last.text_content().strip()=='Comments'
        page.wait_for_function("() => document.activeElement?.hasAttribute('data-cost-notes-for')")
        notes=grid.locator(f'.ux-col-notes [data-cost-notes-for="{line_id}"]')
        assert notes.input_value()==probe
        page.set_viewport_size({'width':1024,'height':768});page.wait_for_timeout(100)
        scroller=grid.locator('[data-lines-scroll]')
        scroller.evaluate('el=>el.scrollLeft=160')
        line_name=first.locator('.ci-col-line').bounding_box()
        line_amount=first.locator('.ci-col-amount').bounding_box()
        group=grid.locator('tr[data-group-row]').first
        group_name=group.locator('th').bounding_box()
        group_amount=group.locator('[data-group-saved-total]').bounding_box()
        assert abs(group_name['x']-line_name['x'])<2
        assert abs(group_amount['x']-line_amount['x'])<2
        assert abs(group_amount['width']-line_amount['width'])<2
        if evidence: page.screenshot(path=str(evidence/'accepted-comments-sticky-1024.png'))
        page.set_viewport_size({'width':1440,'height':900});page.wait_for_timeout(100)
        grid.locator('[data-cost-comments]').click();assert grid.locator('.ci-h-notes').count()==0
        assert next(l for l in _costlines(context,base,record.project_code,'capex')['projection']['lines'] if l['sub_line_id']==line_id).get('notes','')==before
        assert page.locator('[data-unsaved-indicator]').is_visible() and page.locator('[data-wf-run]').is_disabled()
        grid.locator('[data-cost-save]').click()
        page.wait_for_function("() => !!document.querySelector('[data-saved-indicator]')",timeout=30000)
        page.reload();page.wait_for_selector('[data-cost-comments]')
        page.locator('[data-cost-comments]').click()
        assert page.locator(f'.ux-col-notes [data-cost-notes-for="{line_id}"]').input_value()==probe
        # Default-OFF read contract stays disabled; UI changes must not opt it in.
        response=context.request.get(f'{base}/v2/model-react/opex-run-projection?project={record.project_code}')
        assert response.status==404
        assert response.json().get('code')=='G10_RUN_OPEX_PANEL_DISABLED'
        if evidence: (evidence/'accepted-layout.json').write_text(json.dumps(measures,indent=2))
        assert not errors,errors
    finally:
        context.close()


def check_real_clipboard(browser,base):
    context,page,record,errors=session(browser,base,'ux-pr1-clipboard','wind')
    try:
        context.grant_permissions(['clipboard-read','clipboard-write'],origin=base)
        page.goto(f'{base}/v2/model-react/{record.project_code}#inputs/capex')
        page.wait_for_selector('[data-saved-total]')
        amount=page.locator('[data-cost-grid="capex"] tr[data-line] input[data-c="1"]').first
        original=amount.input_value()
        # Actual browser clipboard + native keyboard paste, no DOM ClipboardEvent.
        page.evaluate("navigator.clipboard.writeText('1234.56789')")
        amount.focus();page.keyboard.press('Control+A');page.keyboard.press('Control+V')
        page.wait_for_timeout(150)
        assert amount.input_value()=='1234.56789'
        page.keyboard.press('Control+Z');assert amount.input_value()==original
        page.keyboard.press('Control+Y');assert amount.input_value()=='1234.56789'
        page.keyboard.press('Escape');assert amount.input_value()==original
        assert not errors,errors
    finally:
        context.close()


def check_mobile_route_lifecycle(browser, base, width):
    """Rapid genuine clicks must not race a passive close from the previous route."""
    from playwright.sync_api import expect
    from tests.model_react_wf2_lifecycle_acceptance import dialog, STAY, DISCARD
    context, page, record, errors = session(browser, base, f'ux-pr1-nav-{width}', 'solar')
    try:
        page.set_viewport_size({'width': width, 'height': 900 if width == 1440 else 844})
        page.goto(f'{base}/v2/model-react/{record.project_code}#inputs')
        page.wait_for_selector('[data-grid-cell="tax.assumptions.cit_rate_pct"]')
        nav = page.locator('[data-workspace-nav]')
        toggle = page.locator('.wsv2-menu')

        def choose(destination, guarded=False):
            if width <= 900:
                toggle.click()
                expect(toggle).to_have_attribute('aria-expanded', 'true')
            expect(nav).to_be_visible()
            link = nav.locator(f'[data-workspace-destination="{destination}"]')
            link.click()
            if guarded:
                expect(dialog(page)).to_be_visible()
            else:
                expect(link).to_have_attribute('aria-current', 'page')
            if width <= 900:
                expect(toggle).to_have_attribute('aria-expanded', 'false')
                expect(nav).to_be_hidden()

        for _ in range(4):
            for destination in ('inputs/project', 'inputs/technical', 'inputs/capex', 'inputs/opex', 'inputs/revenue'):
                choose(destination)
        for history, destination in ((page.go_back, 'inputs/opex'), (page.go_back, 'inputs/capex'),
                                     (page.go_forward, 'inputs/opex'), (page.go_forward, 'inputs/revenue')):
            history()
            expect(nav.locator(f'[data-workspace-destination="{destination}"]')).to_have_attribute('aria-current', 'page')
            if width <= 900:
                expect(toggle).to_have_attribute('aria-expanded', 'false')
        choose('inputs/tax')
        tax = page.locator('[data-grid-section="tax-assumptions"]')
        expect(tax).to_have_attribute('open', '')
        page.wait_for_function('() => document.activeElement?.closest(\'[data-grid-section="tax-assumptions"]\') !== null')
        expect(page.locator('[data-tax-navigation-fallback]')).to_have_count(0)
        cell = tax.locator('[data-grid-cell="tax.assumptions.cit_rate_pct"]')
        cell.fill('17')
        expect(page.locator('[data-unsaved-indicator]')).to_be_visible()
        choose('financing', guarded=True)
        dialog(page).get_by_role('button', name=STAY, exact=True).click()
        expect(cell).to_have_value('17')
        choose('financing', guarded=True)
        dialog(page).get_by_role('button', name=DISCARD, exact=True).click()
        expect(nav.locator('[data-workspace-destination="financing"]')).to_have_attribute('aria-current', 'page')
        # Keyboard can reopen, traverse and escape the one primary menu.
        if width <= 900:
            toggle.focus(); page.keyboard.press('Enter')
            expect(toggle).to_have_attribute('aria-expanded', 'true')
        nav.locator('a').first.focus(); page.keyboard.press('End')
        expect(nav.locator('a').last).to_be_focused()
        page.keyboard.press('Escape')
        if width <= 900:
            expect(toggle).to_be_focused()
            expect(nav).to_be_hidden()
        assert not errors, errors
    finally:
        context.close()


def check_tax_fallback(browser, base):
    """A response without a tax group gets explicit fallback copy, never invented fields."""
    context, page, record, errors = session(browser, base, 'ux-pr1-tax-fallback', 'solar')
    try:
        def without_tax(route):
            response = route.fetch()
            payload = response.json()
            payload['grid']['sections'] = [s for s in payload['grid']['sections'] if s['section_id'] != 'tax-assumptions']
            route.fulfill(response=response, json=payload)
        page.route('**/v2/model-react/inputs?*', without_tax)
        page.goto(f'{base}/v2/model-react/{record.project_code}#inputs/tax')
        expect_text = page.locator('[data-tax-navigation-fallback]')
        expect_text.wait_for()
        assert "not available in this project's input grid" in expect_text.inner_text()
        assert page.locator('[data-grid-section="tax-assumptions"]').count() == 0
        assert page.locator('[data-input-grid]').is_visible()
        assert not errors, errors
    finally:
        context.close()
