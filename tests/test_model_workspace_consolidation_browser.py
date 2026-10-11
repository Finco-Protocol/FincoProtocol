"""Real Chromium Option C acceptance, with CSP enabled and isolated synthetic projects."""
import os
from pathlib import Path
from urllib.parse import urljoin

import pytest

from tests.test_workflow_c_browser_v1 import live_server, browser  # noqa: F401


def assert_unique_dom_ids(page):
    duplicates = page.evaluate("""() => {
        const ids = Array.from(document.querySelectorAll('[id]'), node => node.id);
        return [...new Set(ids.filter((id, index) => ids.indexOf(id) !== index))];
    }""")
    assert duplicates == [], duplicates


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
    for area, panel in [('scenarios', 'scenarios'), ('outputs', 'outputs'),
                        ('analysis', 'sensitivity'), ('trust', 'trust')]:
        page.click(f'[data-hy-group="{area}"]')
        assert page.locator(f'#panel-{panel}').is_visible()
    page.click('[data-hy-group="inputs"]')
    evidence_dir = Path(os.environ.get('WF05_SCREENSHOT_DIR', 'artifacts/model-workspace-consolidation'))
    evidence_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(evidence_dir / f'prb-{template}-{width}-{scheme}.png'), full_page=True)
    assert_unique_dom_ids(page)
    assert not errors, errors


@pytest.mark.parametrize('template', ['generic_solar_reference', 'generic_wind_reference',
                                      'generic_data_center_reference', 'generic_ev_charging_reference'])
def test_four_sector_statements_match_persisted_projection_with_csp(workspace, template):
    from app.persistence.workspace_repository import get_workspace_state
    from app.v2.post_run_context import PostRunRequestContext
    from app.v2.statement_presentation import financial_statement_tables
    from app.workbook.runtime_projection import thaw_runtime_payload
    from tests.model_workspace_navigation import activate_destination
    page, record, errors = workspace(template)
    with page.expect_response(lambda response: '/v2/workbook/run' in response.url
                              and response.request.method == 'POST', timeout=240000) as ran:
        page.locator('[data-testid="header-run-btn"]').click()
    assert ran.value.status == 200
    page.wait_for_function("() => document.querySelector('[data-testid=hybrid-run-state]').textContent.trim() === 'CURRENT'", timeout=240000)
    context = PostRunRequestContext.capture(owner_id=record.user_id, project_id=record.project_id)
    snapshot_id = context.workspace.last_runtime_snapshot_id
    expected = financial_statement_tables(context.projection.fs,
        payload=thaw_runtime_payload(context.runtime_result.financial_statements))
    activate_destination(page, 'tab-outputs')
    page.wait_for_selector('[data-out-table=pnl-annual]')
    assert page.locator('[data-out-basis]').input_value() == 'annual'
    for basis in ('annual', 'model'):
        page.locator('[data-out-basis]').select_option(basis)
        for canonical in expected:
            table = canonical['annual'] if basis == 'annual' else canonical
            rendered = page.locator(f'[data-out-table="{table["id"]}"]')
            assert rendered.is_visible()
            assert rendered.locator('thead th.out-num').count() == len(table['columns'])
            values = rendered.locator('tbody tr').evaluate_all("""rows => rows.map(row => ({
                raw: Array.from(row.querySelectorAll('td'), cell => cell.dataset.raw),
                missing: Array.from(row.querySelectorAll('td'), cell => cell.classList.contains('out-na')),
                negative: Array.from(row.querySelectorAll('td'), cell => cell.classList.contains('out-neg')),
                css: row.className, title: row.getAttribute('title')
            }))""")
            assert len(values) == len(table['rows'])
            for actual, row in zip(values, table['rows']):
                assert actual['missing'] == [cell['v'] is None for cell in row['cells']]
                assert actual['negative'] == [cell['neg'] for cell in row['cells']]
                for raw, cell in zip(actual['raw'], row['cells']):
                    if cell['v'] is None:
                        assert raw == ''  # Missing is not a numerical zero.
                    else:
                        assert float(raw) == cell['v']  # Exact persisted projection, not a rounded KPI.
                if row['key'] == 'balance_check_keur':
                    assert row['css_class'] in actual['css']
                    assert actual['title'] == row['status_title']
    year0 = page.locator('[data-out-table=pnl] [data-year0]')
    assert year0.count() > 0
    page.locator('[data-out-year0]').uncheck()
    assert year0.evaluate_all('cells => cells.every(cell => cell.hidden)')
    page.locator('[data-out-year0]').check()
    assert year0.evaluate_all('cells => cells.every(cell => !cell.hidden)')
    assert get_workspace_state(record.user_id, record.project_id).last_runtime_snapshot_id == snapshot_id
    assert_unique_dom_ids(page)
    evidence_dir = Path(os.environ.get('WF05_SCREENSHOT_DIR', 'artifacts/model-workspace-consolidation'))
    evidence_dir.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(evidence_dir / f'prb-financial-{template}-model.png'), full_page=True)
    assert not errors, errors


def test_legacy_links_context_navigation_history_and_keyboard(workspace):
    from app.v2.workspace_destinations import DESTINATIONS
    page, record, errors = workspace()
    for destination in DESTINATIONS:
        page.evaluate('(hash) => { location.hash = hash; }', destination.tab_id.replace('tab-', '#'))
        expected = destination.alias_of or destination.tab_id
        page.wait_for_function('(id) => document.getElementById(id).getAttribute("aria-selected") === "true"', arg=expected)
        assert page.locator(f'[data-nav-tab="{expected}"][aria-current="page"]').count() == 1
        assert_unique_dom_ids(page)
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
    assert_unique_dom_ids(page)
    assert not errors, errors


def test_consecutive_htmx_workbook_saves_refresh_investor_once_each(workspace, monkeypatch):
    from app.api import project_runner
    from app.persistence.workspace_repository import get_workspace_state
    from tests.model_workspace_navigation import activate_destination
    monkeypatch.setenv('FINCO_INPUTS_SLICE1_ENABLED', '1')
    page, record, errors = workspace()
    # Every action below is a Save or a read. Any hidden engine Run is a defect.
    def forbidden_run(*args, **kwargs):
        raise AssertionError('Investor GET must not run the financial engine')
    monkeypatch.setattr(project_runner, 'run_project', forbidden_run)
    investor_gets = []
    page.on('response', lambda response: investor_gets.append(response.status)
            if '/workbook/financing/investor?' in response.url else None)
    activate_destination(page, 'tab-inputs')
    for index, value in enumerate(('1601', '1602'), 1):
        form = page.locator('.v2-inputs-slice1-row[data-field-id="project_setup.technical.p50_hours"] form')
        form.locator('input[name=value]').fill(value)
        with page.expect_response(lambda response: '/workbook/financing/investor?' in response.url) as refreshed:
            with page.expect_response(lambda response: '/inputs-slice1/update' in response.url) as saved:
                form.locator('button[type=submit]').click()
        assert saved.value.status == 200
        assert refreshed.value.status == 200
        page.wait_for_timeout(100)  # Observe unintended follow-up GET loops too.
        assert len(investor_gets) == index
    assert get_workspace_state(record.user_id, record.project_id).last_runtime_snapshot_id is None
    assert_unique_dom_ids(page)
    assert not errors, errors


def test_investor_delayed_response_cannot_restore_pre_scenario_evidence(workspace):
    """A real GET captured before a real scenario POST must not swap afterwards."""
    from tests.model_workspace_navigation import activate_destination
    page, record, errors = workspace()
    with page.expect_response(lambda response: '/v2/workbook/run' in response.url
                              and response.request.method == 'POST', timeout=240000):
        page.locator('[data-testid="header-run-btn"]').click()
    page.wait_for_function("() => document.querySelector('[data-testid=hybrid-run-state]').textContent.trim() === 'CURRENT'", timeout=240000)
    page.wait_for_function("() => document.querySelector('[data-testid=investor-freshness]')?.textContent.startsWith('CURRENT')")
    response = page.request.get(urljoin(page.url, page.locator('#v2-sheet-investor').get_attribute('hx-get')))
    assert response.status == 200
    held = []
    page.evaluate("""() => {
        const source = document.getElementById('v2-sheet-investor');
        source.addEventListener('htmx:beforeOnLoad', () => { window.__prbDelayedInvestorHandled = true; });
    }""")

    def delay_first(route):
        if not held:
            held.append(route)
        else:
            route.continue_()

    page.route('**/v2/workbook/financing/investor?*', delay_first)
    activate_destination(page, 'tab-investor')
    page.wait_for_timeout(100)  # Dispatch Playwright route callbacks; do not fabricate a response.
    assert held
    activate_destination(page, 'tab-scenarios')
    page.locator('[aria-label="New scenario name"]').fill('Delayed Investor acceptance')
    with page.expect_response(lambda response: '/scenarios/create' in response.url
                              and response.request.method == 'POST') as created:
        page.locator('.v2-scenario-create-form button[type=submit]').click()
    assert created.value.status == 200
    page.wait_for_function("() => document.querySelector('[data-testid=hybrid-run-state]').textContent.trim() === 'NOT RUN'")
    page.wait_for_function("() => document.querySelector('[data-testid=investor-freshness]')?.textContent.startsWith('NOT RUN')")
    swaps = []
    page.expose_function('recordInvestorSwap', lambda text: swaps.append(text))
    page.evaluate("""() => document.addEventListener('htmx:afterSwap', event => {
        if (event.detail.target.id === 'v2-sheet-investor')
            window.recordInvestorSwap(document.querySelector('[data-testid=investor-freshness]').textContent.trim());
    })""")
    held[0].fulfill(response=response)
    page.wait_for_function('() => window.__prbDelayedInvestorHandled === true')
    page.wait_for_timeout(100)
    assert not any(text.startswith('CURRENT') for text in swaps), swaps
    assert page.locator('[data-testid=investor-freshness]').inner_text().startswith('NOT RUN')
    assert_unique_dom_ids(page)
    assert not errors, errors
