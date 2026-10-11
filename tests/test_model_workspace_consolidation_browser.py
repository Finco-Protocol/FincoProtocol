"""Real Chromium Option C acceptance, with CSP enabled and isolated synthetic projects."""
import os
from pathlib import Path

import pytest

from tests.test_workflow_c_browser_v1 import live_server, browser  # noqa: F401


@pytest.fixture
def workspace(live_server, browser):
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project
    contexts = []

    def create(template='generic_solar_reference', width=1440, scheme='light'):
        uid = f'prb-{template}-{width}-{scheme}'
        record = create_reference_seeded_project(user_id=uid, template_source=template,
                                                requested_name='PR B browser', capacity_mw=40)
        context = browser.new_context(viewport={'width': width, 'height': 900}, color_scheme=scheme)
        contexts.append(context)
        context.add_cookies([{'name': COOKIE_NAME, 'value': create_session_token(user_id=uid, username='admin'),
                              'url': live_server}])
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
        page.goto(f'{live_server}/v2/workbook?project={record.project_code}')
        page.wait_for_selector('#model-workspace-main')
        return page, record, errors

    yield create
    for context in contexts:
        context.close()


@pytest.mark.parametrize('template', ['generic_solar_reference', 'generic_wind_reference',
                                      'generic_data_center_reference', 'generic_ev_charging_reference'])
@pytest.mark.parametrize('width,scheme', [(1440, 'light'), (390, 'dark')])
def test_four_sector_navigation_mobile_insight_and_csp(workspace, template, width, scheme):
    page, record, errors = workspace(template, width, scheme)
    assert page.locator('#v2-sheet-tabs').is_hidden()
    assert page.locator('#model-smart-panel').is_hidden()
    assert page.locator('#panel-overview').is_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    page.click('[data-hy-group="inputs"]')
    assert page.locator('#panel-input-grid').is_visible()
    if width == 390:
        assert page.locator('#model-workspace-nav').is_hidden()
        page.click('[aria-controls="model-workspace-nav"][data-workspace-drawer]')
    page.click('[data-nav-tab="tab-capex"]')
    assert page.locator('#panel-capex').is_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    page.click('[aria-controls="model-smart-panel"][data-workspace-drawer]')
    assert page.locator('#model-smart-panel').is_visible()
    page.click('[aria-controls="model-smart-panel"][data-workspace-drawer]')
    if template in ('generic_data_center_reference', 'generic_ev_charging_reference'):
        assert page.get_by_text('Excel P50/yield semantics remain unresolved.', exact=False).count() == 0
    evidence_dir = Path(os.environ.get('WF05_SCREENSHOT_DIR', 'artifacts/model-workspace-consolidation'))
    evidence_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(evidence_dir / f'prb-{template}-{width}-{scheme}.png'), full_page=True)
    assert not errors, errors


def test_legacy_links_context_navigation_history_and_keyboard(workspace):
    from app.v2.workspace_destinations import DESTINATIONS
    page, record, errors = workspace()
    for destination in DESTINATIONS:
        page.evaluate('(hash) => { location.hash = hash; }', destination.tab_id.replace('tab-', '#'))
        expected = destination.alias_of or destination.tab_id
        page.wait_for_function('(id) => document.getElementById(id).getAttribute("aria-selected") === "true"', arg=expected)
        assert page.locator(f'[data-nav-tab="{expected}"][aria-current="page"]').count() == 1
    page.click('[data-hy-group="inputs"]')
    page.click('[data-nav-tab="tab-capex"]')
    page.click('[data-nav-tab="tab-opex"]')
    page.go_back()
    page.wait_for_function('() => document.getElementById("tab-capex").getAttribute("aria-selected") === "true"')
    page.go_forward()
    page.wait_for_function('() => document.getElementById("tab-opex").getAttribute("aria-selected") === "true"')
    page.focus('[data-hy-group="inputs"]')
    page.keyboard.press('ArrowRight')
    assert page.locator('#panel-scenarios').is_visible()
    assert page.locator('[data-hy-group="scenarios"]').evaluate('e => e === document.activeElement')
    assert not errors, errors


def test_query_aliases_use_canonical_outputs_without_duplicate_table_ids(workspace):
    from app.v2.workspace_destinations import DESTINATIONS
    page, record, errors = workspace()
    url = page.url.split('#')[0]
    for destination in DESTINATIONS:
        page.goto(url + '&sheet=' + destination.tab_id.removeprefix('tab-'))
        expected = destination.alias_of or destination.tab_id
        page.wait_for_function('(id) => document.getElementById(id).getAttribute("aria-selected") === "true"', arg=expected)
        assert page.locator(f'[data-nav-tab="{expected}"][aria-current="page"]').count() == 1
    assert not errors, errors


def test_consecutive_atomic_save_run_stale_current_with_csp_enabled(workspace):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.input_set import ProjectInputSet
    from tests.model_workspace_navigation import activate_destination
    page, record, errors = workspace()
    posts = []
    page.on('request', lambda request: posts.append(request.url) if request.method == 'POST' else None)
    activate_destination(page, 'tab-input-grid')
    field = 'project_setup.technical.p50_hours'
    for value in ('1511', '1522'):
        cell = page.locator(f'.ig-input[data-ig-field="{field}"]')
        cell.fill(value)
        cell.press('Enter')
        page.wait_for_function('() => window.FincoInputGrid.stagedCount() === 1')
        with page.expect_response(lambda response: '/grid/save' in response.url and response.request.method == 'POST') as saved:
            page.keyboard.press('Control+S')
        assert saved.value.status == 200
        page.wait_for_function('() => window.FincoInputGrid.stagedCount() === 0')
        ws = get_workspace_state(record.user_id, record.project_id)
        assert ProjectInputSet.from_snapshot(ws.draft_snapshot).get(field) == float(value)
    assert sum('/grid/save' in url for url in posts) == 2
    assert not any('/run' in url for url in posts)
    with page.expect_response(lambda response: '/v2/workbook/run' in response.url and response.request.method == 'POST', timeout=240000) as ran:
        page.locator('[data-testid="header-run-btn"]').click()
    assert ran.value.status == 200
    page.wait_for_function("() => document.querySelector('[data-testid=hybrid-run-state]').textContent.trim() === 'CURRENT'", timeout=240000)
    committed = get_workspace_state(record.user_id, record.project_id).last_runtime_snapshot_id
    cell = page.locator(f'.ig-input[data-ig-field="{field}"]')
    cell.fill('1533')
    cell.press('Enter')
    page.wait_for_function('() => window.FincoInputGrid.stagedCount() === 1')
    page.keyboard.press('Control+S')
    page.wait_for_function("() => document.querySelector('[data-testid=hybrid-run-state]').textContent.trim() === 'STALE'", timeout=30000)
    page.wait_for_function('() => window.FincoInputGrid.stagedCount() === 0')
    assert get_workspace_state(record.user_id, record.project_id).last_runtime_snapshot_id == committed
    with page.expect_response(lambda response: '/v2/workbook/run' in response.url and response.request.method == 'POST', timeout=240000) as ran:
        page.locator('[data-testid="header-run-btn"]').click()
    assert ran.value.status == 200
    page.wait_for_function("() => document.querySelector('[data-testid=hybrid-run-state]').textContent.trim() === 'CURRENT'", timeout=240000)
    assert get_workspace_state(record.user_id, record.project_id).last_runtime_snapshot_id != committed
    assert not errors, errors
