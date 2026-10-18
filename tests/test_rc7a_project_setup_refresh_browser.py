"""Project Setup cannot accept edits into an obsolete, pending presentation."""
import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")
from playwright.sync_api import expect  # noqa: E402
from tests.test_rcux2_ppa_quick_add_browser import live_server, browser, Session  # noqa: E402,F401
from tests.test_model_v7_refresh_browser import _save_increment  # noqa: E402
from tests.model_workspace_navigation import activate_destination  # noqa: E402


def _capacity(page):
    return page.locator('#v2-sheet-project-setup [data-field-id="project_setup.technical.capacity_mw"]')


def _saved_grid(page):
    page.wait_for_function("() => window.FincoInputGrid.stagedCount() === 0")


def test_pending_project_setup_waits_for_authorized_refresh_before_capacity_save(live_server, browser):
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.run_history_repository import get_run_history
    s = Session(live_server, browser, "rc7a-setup-refresh")
    try:
        page = s.page
        held = []
        page.route("**/v2/workbook/grid/sheet?**sheet=project_setup", lambda route: held.append(route))
        _save_increment(page)
        _saved_grid(page)
        activate_destination(page, "tab-project-setup")
        page.wait_for_function("() => document.querySelector('#v2-sheet-project-setup').getAttribute('aria-busy') === 'true'")
        assert len(held) == 1
        row = _capacity(page)
        expect(row.locator('input[name="value"]')).to_be_disabled()
        expect(row.locator("button.v2-field-save")).to_be_disabled()
        before = get_workspace_state(s.uid, s.rec.project_id)
        history = get_run_history(s.uid, s.rec.project_id)
        posts = len(s.posts_to("/v2/workbook/update"))
        row.locator("form").evaluate("form => form.requestSubmit()")
        assert len(s.posts_to("/v2/workbook/update")) == posts
        assert get_workspace_state(s.uid, s.rec.project_id) == before

        response = page.request.get(held[0].request.url)
        assert response.status == 200
        held[0].fulfill(response=response)
        page.wait_for_function("() => document.querySelector('#v2-sheet-project-setup').dataset.modelViewState === 'loaded'")
        row = _capacity(page)
        expect(row.locator('input[name="value"]')).to_be_enabled()
        row.locator('input[name="value"]').fill("150")
        with page.expect_response(lambda res: "/v2/workbook/update" in res.url) as saved:
            row.locator("button.v2-field-save").click()
        assert saved.value.status == 200
        expect(_capacity(page).locator('input[name="value"]')).to_have_value("150.0")
        after = get_workspace_state(s.uid, s.rec.project_id)
        assert float(after.draft_snapshot["capacity_mw"]) == 150
        assert after.last_runtime_snapshot_id == before.last_runtime_snapshot_id
        assert get_run_history(s.uid, s.rec.project_id) == history
        assert len(s.posts_to("/v2/workbook/update")) == posts + 1
        assert not s.errors, s.errors
    finally:
        s.close()


def test_failed_project_setup_refresh_stays_locked_until_explicit_success(live_server, browser):
    from app.persistence.workspace_repository import get_workspace_state
    s = Session(live_server, browser, "rc7a-setup-refresh-failure")
    try:
        page = s.page
        pattern = "**/v2/workbook/grid/sheet?**sheet=project_setup"
        page.route(pattern, lambda route: route.fulfill(status=503, body="Unavailable"))
        _save_increment(page)
        _saved_grid(page)
        before = get_workspace_state(s.uid, s.rec.project_id)
        activate_destination(page, "tab-project-setup")
        page.wait_for_function("() => document.querySelector('#v2-sheet-project-setup').dataset.modelViewState === 'error'")
        expect(_capacity(page).locator('input[name="value"]')).to_be_disabled()
        assert get_workspace_state(s.uid, s.rec.project_id) == before
        page.unroute(pattern)
        page.locator('#v2-sheet-project-setup [data-model-view-retry]').click()
        page.wait_for_function("() => document.querySelector('#v2-sheet-project-setup').dataset.modelViewState === 'loaded'")
        expect(_capacity(page).locator('input[name="value"]')).to_be_enabled()
        assert get_workspace_state(s.uid, s.rec.project_id) == before
        assert not s.posts_to("/v2/workbook/update")
    finally:
        s.close()
