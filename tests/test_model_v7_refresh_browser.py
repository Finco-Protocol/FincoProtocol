"""Real CSP Chromium: scoped refresh, pending editors and out-of-order reads."""
import pytest

pytest.importorskip('playwright', reason='playwright not installed in this workflow')
from tests.test_rcux2_ppa_quick_add_browser import live_server, browser, Session  # noqa: E402,F401
from tests.test_model_v7_diagnostics_browser import _run  # noqa: E402
from tests.model_workspace_navigation import activate_destination  # noqa: E402


def _save_increment(page):
    activate_destination(page, 'tab-input-grid')
    cell = page.locator('.ig-input[data-ig-field="project_setup.technical.p50_hours"]')
    cell.fill(str(float(cell.input_value().replace(',', '')) + 1)); cell.press('Enter')
    page.wait_for_function('() => window.FincoInputGrid.stagedCount() === 1')
    assert page.evaluate('() => window.FincoInputGrid.save()') is True


@pytest.mark.parametrize('template', ['generic_solar_reference', 'generic_wind_reference'])
def test_scoped_consecutive_save_lazy_outputs_and_hidden_editor_identity(live_server, browser, template):
    from app.persistence.workspace_repository import get_workspace_state
    s = Session(live_server, browser, 'v7-scoped-' + template, template=template)
    try:
        page = s.page
        _run(page)
        before = get_workspace_state(s.uid, s.rec.project_id)
        for _ in range(3):
            s.requests.clear()
            _save_increment(page)
            page.wait_for_timeout(500)
            reads = [u for method, u in s.requests if method == 'GET' and '/v2/workbook/' in u]
            assert len([url for url in reads if '/grid/panel?' in url]) == 1, reads
            assert all('/grid/panel?' in url or '/financing/integrity?' in url for url in reads), reads
            assert page.locator('#v2-sheet-capex').get_attribute('data-model-view-state') == 'pending'
            assert page.locator('#v2-sheet-outputs').get_attribute('data-model-view-state') == 'pending'
            assert page.locator('#v2-sheet-diagnostics').get_attribute('data-state') == 'STALE'
            assert page.locator('#v2-model-health').get_attribute('data-state') == 'STALE'
        after = get_workspace_state(s.uid, s.rec.project_id)
        for key in ('last_runtime_snapshot_id', 'last_financial_statements', 'last_integrity_evidence'):
            assert getattr(after, key) == getattr(before, key)
        activate_destination(page, 'tab-capex')
        page.wait_for_function("() => document.querySelector('#v2-sheet-capex').dataset.modelViewState === 'loaded'")
        live_hash = page.locator('#v2-canonical-run-form [name=content_hash]').input_value()
        hashes = page.locator('#v2-sheet-capex [name=content_hash]').evaluate_all('(nodes) => nodes.map(n => n.value)')
        assert hashes and set(hashes) == {live_hash}
        activate_destination(page, 'tab-outputs')
        page.wait_for_function("() => document.querySelector('#v2-sheet-outputs').dataset.modelViewState === 'loaded'")
        assert page.locator('#v2-sheet-outputs [data-raw]').count() > 0
        assert page.locator('#v2-sheet-financial-statements').get_attribute('data-model-view-state') == 'pending'
        _run(page)
        page.wait_for_function("() => document.querySelector('#v2-sheet-outputs').dataset.modelViewState === 'loaded'")
        assert page.locator('#v2-sheet-diagnostics').get_attribute('data-state') == 'CURRENT'
        assert not s.errors, s.errors
    finally:
        s.close()


def test_old_output_read_is_rejected_and_failed_read_can_retry(live_server, browser):
    s = Session(live_server, browser, 'v7-scoped-race')
    try:
        page = s.page; _run(page)
        held = []
        def hold_first(route):
            if not held:
                held.append(route)
            else:
                route.continue_()
        page.route('**/v2/workbook/outputs?*', hold_first)
        activate_destination(page, 'tab-outputs')
        page.wait_for_timeout(150)
        assert len(held) == 1
        old = page.request.get(held[0].request.url)
        assert old.status == 200
        _save_increment(page)
        activate_destination(page, 'tab-outputs')
        page.wait_for_function("() => document.querySelector('#v2-sheet-outputs').dataset.modelViewState === 'loaded'")
        values = page.locator('#v2-sheet-outputs [data-raw]').evaluate_all('(nodes) => nodes.map(n => n.dataset.raw)')
        page.locator('#v2-sheet-outputs').evaluate("node => { node.dataset.raceMarker = 'newer-response'; }")
        held[0].fulfill(response=old)
        page.wait_for_timeout(200)
        assert page.locator('#v2-sheet-outputs').get_attribute('data-race-marker') == 'newer-response'
        assert page.locator('#v2-sheet-outputs [data-raw]').evaluate_all('(nodes) => nodes.map(n => n.dataset.raw)') == values
        assert 'STALE' in page.locator('#v2-sheet-outputs').inner_text()
        page.unroute('**/v2/workbook/outputs?*')
        _save_increment(page)
        page.route('**/v2/workbook/outputs?*', lambda route: route.fulfill(status=503, body='Unavailable'))
        activate_destination(page, 'tab-outputs')
        page.wait_for_function("() => document.querySelector('#v2-sheet-outputs').dataset.modelViewState === 'error'")
        assert page.locator('#v2-sheet-outputs [data-raw]').count() == 0
        page.unroute('**/v2/workbook/outputs?*')
        page.locator('#v2-sheet-outputs [data-model-view-retry]').click()
        page.wait_for_function("() => document.querySelector('#v2-sheet-outputs').dataset.modelViewState === 'loaded'")
        assert page.locator('#v2-sheet-outputs [data-raw]').count() > 0
    finally:
        s.close()
