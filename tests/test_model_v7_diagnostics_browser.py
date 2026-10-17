"""Real Chromium lazy loading, hidden/visible Save and navigation under the production CSP."""
import json

import pytest

pytest.importorskip('playwright', reason='playwright not installed in this workflow')
from tests.test_rcux2_ppa_quick_add_browser import live_server, browser, Session  # noqa: E402,F401
from tests.model_workspace_navigation import activate_destination  # noqa: E402


def _run(page):
    with page.expect_response(lambda r: '/v2/workbook/run' in r.url and r.request.method == 'POST', timeout=240000) as response:
        page.locator('[data-testid="header-run-btn"]').click()
    assert response.value.status == 200
    page.wait_for_function("() => document.querySelector('#v2-sheet-diagnostics').dataset.state === 'CURRENT'", timeout=240000)


def _open(page):
    activate_destination(page, 'tab-diagnostics')
    page.wait_for_selector('[data-md-payload]', state='attached')
    return json.loads(page.locator('[data-md-payload]').text_content())


def _save(page, value):
    activate_destination(page, 'tab-input-grid')
    cell = page.locator('.ig-input[data-ig-field="project_setup.technical.p50_hours"]')
    cell.fill(str(value)); cell.press('Enter')
    page.wait_for_function('() => window.FincoInputGrid.stagedCount() === 1')
    page.keyboard.press('Control+S')
    page.wait_for_function('() => window.FincoInputGrid.stagedCount() === 0')


@pytest.mark.parametrize('template,width,scheme', [('generic_solar_reference',1440,'light'),
    ('generic_wind_reference',1366,'dark'), ('generic_solar_reference',390,'dark')])
def test_lazy_payload_hidden_save_deep_link_and_history(live_server, browser, template, width, scheme):
    from app.persistence.workspace_repository import get_workspace_state
    s = Session(live_server, browser, 'v7-browser-' + template + str(width),
                viewport={'width':width,'height':844 if width == 390 else 900}, scheme=scheme, template=template)
    try:
        page = s.page
        assert page.locator('#v2-sheet-diagnostics').get_attribute('data-state') == 'NOT_RUN'
        assert page.locator('[data-md-payload]').count() == 0
        assert page.locator('#v2-sheet-diagnostics').get_attribute('data-diagnostics-load-state') == 'pending'
        assert not [u for m,u in s.requests if '/workbook/diagnostics?' in u]
        _run(page)
        before = get_workspace_state(s.uid, s.rec.project_id)
        s.requests.clear()
        data = _open(page)
        assert len(data['checks']) == 30 and data['state'] == 'CURRENT'
        assert len([u for m,u in s.requests if '/workbook/diagnostics?' in u]) == 1
        activate_destination(page, 'tab-overview'); _open(page)
        assert len([u for m,u in s.requests if '/workbook/diagnostics?' in u]) == 1
        button = page.locator('[data-md-select="QM-SD-002"]').first
        button.focus(); page.keyboard.press('Enter')
        assert page.locator('[data-md-detail]').is_visible()
        page.reload(); page.wait_for_selector('[data-md-detail]', state='visible')
        assert 'QM-SD-002' in page.locator('[data-md-detail-title]').inner_text()
        activate_destination(page, 'tab-overview'); page.go_back()
        page.wait_for_selector('#panel-diagnostics', state='visible')
        page.go_forward(); page.wait_for_selector('#panel-overview', state='visible')
        s.requests.clear()
        _save(page, 1517)
        page.wait_for_timeout(150)
        assert not [u for m,u in s.requests if '/workbook/diagnostics?' in u]
        assert page.locator('[data-md-payload]').count() == 0
        assert page.locator('#v2-sheet-diagnostics').get_attribute('data-state') == 'STALE'
        assert page.locator('#v2-model-health').get_attribute('data-state') == 'STALE'
        assert 'HISTORICAL' in page.locator('#v2-model-health').inner_text()
        assert json.loads(page.locator('#v2-sheet-diagnostics').get_attribute('data-last-run-identity')) == data['identity']
        assert _open(page)['state'] == 'STALE'
        after = get_workspace_state(s.uid, s.rec.project_id)
        assert after.last_runtime_snapshot_id == before.last_runtime_snapshot_id
        assert after.last_financial_statements == before.last_financial_statements
        assert after.last_integrity_evidence == before.last_integrity_evidence
        overflow = page.evaluate('''() => [...document.querySelectorAll('body *')].filter(n => {
          const r=n.getBoundingClientRect(); return r.width && r.right > innerWidth+1 && getComputedStyle(n).position !== 'fixed';
        }).slice(0,12).map(n => [n.tagName,n.id,n.className,n.getBoundingClientRect().width])''')
        # Unchanged main has 1801px desktop shell overflow (private control evidence);
        # Diagnostics tables remain contained and mobile must not acquire that defect.
        assert page.evaluate('document.documentElement.scrollWidth') <= (width + 1 if width == 390 else 1801), overflow
        assert page.locator('.md2-scroll').first.evaluate('(n) => n.clientWidth <= innerWidth')
        assert not s.errors, s.errors
    finally:
        s.close()


def test_visible_save_refresh_and_late_read_cannot_overwrite_new_run(live_server, browser):
    s = Session(live_server, browser, 'v7-browser-race')
    try:
        page = s.page; _run(page); first = _open(page)['identity']['snapshot_id']
        held = []
        def delay_first(route):
            if not held:
                held.append(route)
            else:
                route.continue_()
        page.route('**/v2/workbook/diagnostics?*', delay_first)
        # A real grid Save while hidden must not request Diagnostics.
        _save(page, 1523)
        page.wait_for_timeout(100); assert not held
        activate_destination(page, 'tab-diagnostics')
        page.wait_for_timeout(150); assert len(held) == 1
        stale = page.request.get(held[0].request.url)
        assert stale.status == 200 and 'data-state="STALE"' in stale.text()
        _run(page)
        page.wait_for_selector('[data-md-payload]', state='attached')
        current = json.loads(page.locator('[data-md-payload]').text_content())
        assert current['identity']['snapshot_id'] != first and current['state'] == 'CURRENT'
        held[0].fulfill(response=stale)
        page.wait_for_timeout(150)
        assert json.loads(page.locator('[data-md-payload]').text_content()) == current
        # Save through the canonical form while Diagnostics remains visible.
        response = page.evaluate("""async project => {
          const form = document.querySelector('#v2-canonical-run-form');
          const body = new FormData(form);
          body.set('project', project); body.set('field_id','project_setup.technical.p50_hours');
          body.set('value','1549'); body.set('sheet_id','project_setup');
          return htmx.ajax('POST','/v2/workbook/update', {source:document.body, target:'body', swap:'none',
            values:Object.fromEntries(body)}).then(() => true);
        }""", s.rec.project_code)
        assert response
        page.wait_for_function("() => document.querySelector('#v2-sheet-diagnostics').dataset.state === 'STALE'")
        page.wait_for_selector('[data-md-payload]', state='attached')
        assert json.loads(page.locator('[data-md-payload]').text_content())['identity'] == current['identity']
        assert not s.errors, s.errors
    finally:
        s.close()


def test_unavailable_read_retry_not_run_and_keyboard_focus(live_server, browser):
    s = Session(live_server, browser, 'v7-browser-unavailable')
    try:
        page = s.page
        attempts = []
        def fail_once(route):
            attempts.append(route.request.url)
            if len(attempts) == 1:
                route.fulfill(status=503, body='Unavailable')
            else:
                route.continue_()
        page.route('**/v2/workbook/diagnostics?*', fail_once)
        activate_destination(page, 'tab-diagnostics')
        page.wait_for_function("() => document.querySelector('#v2-sheet-diagnostics').dataset.diagnosticsLoadState === 'error'")
        assert page.locator('#v2-sheet-diagnostics').get_attribute('data-state') == 'UNAVAILABLE'
        retry = page.locator('[data-diagnostics-retry]')
        retry.focus(); page.keyboard.press('Enter')
        page.wait_for_function("() => document.querySelector('#v2-sheet-diagnostics').dataset.diagnosticsLoadState === 'loaded'")
        assert page.locator('#v2-sheet-diagnostics').get_attribute('data-state') == 'NOT_RUN'
        assert page.locator('[data-md-payload]').count() == 0
        assert len(attempts) == 2
        assert page.locator('#v2-sheet-diagnostics').evaluate('(n) => n === document.activeElement')
        assert not s.posts_to('/v2/workbook/run')
    finally:
        s.close()


@pytest.mark.parametrize('template', ['generic_solar_reference', 'generic_wind_reference'])
def test_rejected_save_preserves_current_freshness_and_committed_evidence(live_server, browser, template):
    from app.persistence.workspace_repository import get_workspace_state

    s = Session(live_server, browser, 'v7-rejected-' + template, template=template)
    try:
        page = s.page
        _run(page)
        before = get_workspace_state(s.uid, s.rec.project_id)
        data = _open(page)
        activate_destination(page, 'tab-input-grid')
        cell = page.locator('.ig-input[data-ig-field="project_setup.technical.p50_hours"]')
        cell.fill(str(float(cell.input_value()) + 1)); cell.press('Enter')
        page.wait_for_function('() => window.FincoInputGrid.stagedCount() === 1')

        def reject_token(route):
            body = route.request.post_data_json
            body['csrf_token'] = 'invalid-disposable-test-token'
            route.continue_(post_data=json.dumps(body))

        page.route('**/v2/workbook/grid/save', reject_token)
        assert page.evaluate('() => window.FincoInputGrid.save()') is False
        assert page.locator('#v2-sheet-diagnostics').get_attribute('data-state') == 'CURRENT'
        assert page.locator('#v2-model-health').get_attribute('data-state') == 'CURRENT'
        assert page.locator('[data-testid=hybrid-run-state]').inner_text().strip() == 'CURRENT'
        assert page.locator('#v2-sheet-diagnostics').get_attribute('data-diagnostics-load-state') == 'pending'
        assert json.loads(page.locator('#v2-sheet-diagnostics').get_attribute('data-last-run-identity')) == data['identity']
        assert page.evaluate('() => window.FincoInputGrid.stagedCount()') == 1
        after = get_workspace_state(s.uid, s.rec.project_id)
        for field in ('draft_snapshot', 'last_runtime_snapshot_id', 'last_financial_statements', 'last_integrity_evidence'):
            assert getattr(after, field) == getattr(before, field)
    finally:
        s.close()
