"""A lazy read cannot discard a new draft or allow an obsolete form to Save."""
import pytest

pytest.importorskip('playwright', reason='playwright not installed in this workflow')
from tests.test_rcux2_ppa_quick_add_browser import live_server, browser, Session  # noqa: E402,F401
from tests.test_model_v7_refresh_browser import _save_increment  # noqa: E402
from tests.model_workspace_navigation import activate_destination  # noqa: E402


def test_pending_editor_preserves_new_draft_and_refuses_old_cas(live_server, browser):
    from app.persistence.workspace_repository import get_workspace_state
    s = Session(live_server, browser, 'v7-pending-editor')
    try:
        page = s.page
        _save_increment(page)
        held = []
        page.route('**/v2/workbook/grid/sheet?**sheet=capex', lambda route: held.append(route))
        activate_destination(page, 'tab-capex')
        page.wait_for_timeout(150)
        assert len(held) == 1
        response = page.request.get(held[0].request.url)
        assert response.status == 200
        group = page.locator('#v2-sheet-capex details[data-group-code]').first
        if group.get_attribute('open') is None:
            group.locator('summary').first.click()
        cell = page.locator('#v2-sheet-capex [data-cost-cell=amount]').first
        cell.fill('2042')
        before = get_workspace_state(s.uid, s.rec.project_id)
        posts = len([url for method, url in s.requests if method == 'POST'])
        cell.evaluate('node => node.closest("form").requestSubmit()')
        held[0].fulfill(response=response)
        page.wait_for_function("() => document.querySelector('#v2-sheet-capex').dataset.modelViewState === 'error'")
        assert page.locator('#v2-sheet-capex [data-cost-cell=amount]').first.input_value() == '2042'
        assert len([url for method, url in s.requests if method == 'POST']) == posts
        assert get_workspace_state(s.uid, s.rec.project_id) == before
        page.unroute('**/v2/workbook/grid/sheet?**sheet=capex')
        page.locator('#v2-sheet-capex [data-model-view-retry]').click()
        page.wait_for_function("() => document.querySelector('#v2-sheet-capex').dataset.modelViewState === 'loaded'")
        assert page.locator('#v2-sheet-capex [data-cost-cell=amount]').first.input_value() != '2042'
        assert not s.errors, s.errors
    finally:
        s.close()
