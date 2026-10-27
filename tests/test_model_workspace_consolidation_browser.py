"""Real Chromium Option C acceptance, with CSP enabled and isolated synthetic projects."""
import os
from pathlib import Path

import pytest

from tests.test_workflow_c_browser_v1 import live_server, browser  # noqa: F401
from tests.model_mutation_cookie_policy_acceptance import mutation_browser_servers  # noqa: F401


def test_model_mutation_secure_cookie_policy(mutation_browser_servers, tmp_path):
    from tests.model_mutation_cookie_policy_acceptance import (
        test_verified_secure_lax_policy_same_origin_same_site_and_cross_site,
    )
    test_verified_secure_lax_policy_same_origin_same_site_and_cross_site(mutation_browser_servers, tmp_path)
    from tests.model_mutation_cookie_policy_acceptance import check_legacy_cost_buttons_use_their_own_operation_tokens
    check_legacy_cost_buttons_use_their_own_operation_tokens(mutation_browser_servers)


def assert_unique_dom_ids(page):
    duplicates = page.evaluate("""() => {
        const ids = Array.from(document.querySelectorAll('[id]'), node => node.id);
        return [...new Set(ids.filter((id, index) => ids.indexOf(id) !== index))];
    }""")
    assert duplicates == [], duplicates


# Additive Diagnostics acceptance belongs to the EXISTING mandatory consolidation role.
# Its fail-closed execution inventory / JUnit / screenshot verifier remains unchanged.
@pytest.mark.parametrize('template', ['generic_solar_reference', 'generic_wind_reference',
                                      'generic_data_center_reference', 'generic_ev_charging_reference'])
def test_model_diagnostics_vertical_acceptance(workspace, template):
    from tests.model_diagnostics_browser_acceptance import test_diagnostics_vertical_run_health_matrix_detail_and_readonly
    test_diagnostics_vertical_run_health_matrix_detail_and_readonly(workspace, template)


def test_model_diagnostics_failed_check_mobile_acceptance(workspace):
    from tests.model_diagnostics_browser_acceptance import test_failed_check_period_residual_drilldown_and_mobile
    test_failed_check_period_residual_drilldown_and_mobile(workspace)


def test_model_diagnostics_late_read_cannot_overwrite_new_run(workspace):
    from tests.model_diagnostics_browser_acceptance import test_delayed_diagnostics_refresh_after_new_run
    test_delayed_diagnostics_refresh_after_new_run(workspace)


@pytest.mark.parametrize('template', ['generic_solar_reference', 'generic_wind_reference',
                                      'generic_data_center_reference', 'generic_ev_charging_reference'])
def test_model_diagnostics_v2_vertical_acceptance(workspace, template):
    from tests.model_diagnostics_v2_browser_acceptance import test_v2_sections_checks_heatmap_and_bankability_per_vertical
    test_v2_sections_checks_heatmap_and_bankability_per_vertical(workspace, template)


def test_model_diagnostics_v2_failed_period_mobile_acceptance(workspace):
    from tests.model_diagnostics_v2_browser_acceptance import test_failed_period_heatmap_drilldown_root_cause_and_mobile
    test_failed_period_heatmap_drilldown_root_cause_and_mobile(workspace)


def test_model_diagnostics_v2_guided_actions_acceptance(workspace):
    from tests.model_diagnostics_v2_browser_acceptance import test_guided_actions_navigate_only_and_disabled_actions_state_their_reason
    test_guided_actions_navigate_only_and_disabled_actions_state_their_reason(workspace)


def test_model_diagnostics_v2_run_comparison_acceptance(workspace):
    from tests.model_diagnostics_v2_browser_acceptance import test_run_comparison_section_between_two_committed_runs
    test_run_comparison_section_between_two_committed_runs(workspace)


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
        # Chromium's implicit /favicon.ico probe (no <link rel=icon>) is browser chrome, not an app request.
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error'
                and not str((message.location or {}).get('url', '')).endswith('/favicon.ico') else None)
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
    assert page.locator('#panel-debt').is_visible() or page.locator('#panel-investor').is_visible()      # Inputs -> Financing is the next area in the Phase 2 hierarchy (the group reopens its last tab)
    assert page.locator('[data-hy-group="financing"]').evaluate('e => e === document.activeElement')
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
        # Keep RC-SEC post-Save CSRF/CAS regression after #375 browser integration.
        form = page.locator('#v2-canonical-run-form')
        assert form.locator('[name="content_hash"]').input_value()
        assert form.locator('[name="run_csrf_token"]').input_value(), (
            "Post-Save OOB Run form dropped its scoped CSRF token"
        )
    assert sum('/grid/save' in url for url in posts) == 2
    assert not any('/run' in url for url in posts)
    with page.expect_response(lambda response: '/v2/workbook/run' in response.url and response.request.method == 'POST', timeout=240000) as ran:
        page.locator('[data-testid="header-run-btn"]').click()
    assert ran.value.status == 200
    page.wait_for_function("() => document.querySelector('[data-testid=hybrid-run-state]').textContent.trim() === 'CURRENT'", timeout=240000)
    committed = get_workspace_state(record.user_id, record.project_id).last_runtime_snapshot_id
    assert page.locator('#v2-sheet-diagnostics').get_attribute('data-state') == 'CURRENT'
    assert page.locator('#v2-model-health').get_attribute('data-state') == 'CURRENT'
    cell = page.locator(f'.ig-input[data-ig-field="{field}"]')
    cell.fill('1533')
    cell.press('Enter')
    page.wait_for_function('() => window.FincoInputGrid.stagedCount() === 1')
    page.keyboard.press('Control+S')
    page.wait_for_function("() => document.querySelector('[data-testid=hybrid-run-state]').textContent.trim() === 'STALE'", timeout=30000)
    page.wait_for_function('() => window.FincoInputGrid.stagedCount() === 0')
    assert get_workspace_state(record.user_id, record.project_id).last_runtime_snapshot_id == committed
    page.wait_for_function("() => document.querySelector('#v2-sheet-diagnostics').dataset.state === 'STALE'", timeout=30000)
    assert page.locator('#v2-sheet-diagnostics').get_attribute('data-state') == 'STALE'
    assert page.locator('#v2-model-health').get_attribute('data-state') == 'STALE'
    assert 'HISTORICAL' in page.locator('#v2-model-health').inner_text()
    with page.expect_response(lambda response: '/v2/workbook/run' in response.url and response.request.method == 'POST', timeout=240000) as ran:
        page.locator('[data-testid="header-run-btn"]').click()
    assert ran.value.status == 200
    page.wait_for_function("() => document.querySelector('[data-testid=hybrid-run-state]').textContent.trim() === 'CURRENT'", timeout=240000)
    assert get_workspace_state(record.user_id, record.project_id).last_runtime_snapshot_id != committed
    assert page.locator('#v2-sheet-diagnostics').get_attribute('data-state') == 'CURRENT'
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
    def investor_read(response):
        return '/grid/sheet?' in response.url and 'sheet=investor' in response.url
    page.on('response', lambda response: investor_gets.append(response.status)
            if investor_read(response) else None)
    for index, value in enumerate(('1601', '1602'), 1):
        activate_destination(page, 'tab-inputs')
        page.wait_for_function("() => document.querySelector('#v2-sheet-inputs').dataset.modelViewState === 'loaded'")
        form = page.locator('.v2-inputs-slice1-row[data-field-id="project_setup.technical.p50_hours"] form')
        form.locator('input[name=value]').fill(value)
        with page.expect_response(lambda response: '/inputs-slice1/update' in response.url) as saved:
            form.locator('button[type=submit]').click()
        assert saved.value.status == 200
        page.wait_for_timeout(100)
        assert len(investor_gets) == index - 1
        with page.expect_response(investor_read) as refreshed:
            activate_destination(page, 'tab-investor')
        assert refreshed.value.status == 200
        page.wait_for_function("() => document.querySelector('#v2-sheet-investor').dataset.modelViewState === 'loaded'")
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
    assert page.locator('#v2-sheet-investor').get_attribute('data-model-view-state') == 'pending'
    held = []
    page.evaluate("""() => {
        document.addEventListener('htmx:beforeOnLoad', e => {
            if (e.detail.xhr.responseURL.includes('/grid/sheet?')) window.__prbDelayedInvestorHandled = true;
        });
    }""")

    def delay_first(route):
        if not held:
            held.append(route)
        else:
            route.continue_()

    page.route('**/v2/workbook/grid/sheet?**sheet=investor', delay_first)
    activate_destination(page, 'tab-investor')
    page.wait_for_timeout(100)  # Dispatch Playwright route callbacks; do not fabricate a response.
    assert held
    response = page.request.get(held[0].request.url)
    assert response.status == 200 and 'CURRENT' in response.text()
    activate_destination(page, 'tab-scenarios')
    page.locator('[aria-label="New scenario name"]').fill('Delayed Investor acceptance')
    with page.expect_response(lambda response: '/scenarios/create' in response.url
                              and response.request.method == 'POST') as created:
        page.locator('.v2-scenario-create-form button[type=submit]').click()
    assert created.value.status == 200
    page.wait_for_function("() => document.querySelector('[data-testid=hybrid-run-state]').textContent.trim() === 'NOT RUN'")
    assert page.locator('#v2-sheet-investor').get_attribute('data-model-view-state') == 'pending'
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
    activate_destination(page, 'tab-investor')
    page.wait_for_function("() => document.querySelector('#v2-sheet-investor').dataset.modelViewState === 'loaded'")
    assert page.locator('[data-testid=investor-freshness]').inner_text().startswith('NOT RUN')
    assert_unique_dom_ids(page)
    assert not errors, errors


@pytest.mark.parametrize('boundary', ['row', 'link'])
@pytest.mark.parametrize('pass_to_delay', ['frame', 'timer'])
def test_historical_statement_restore_cannot_override_new_keyboard_input(browser, boundary, pass_to_delay):
    """Control the actual restore callbacks, without waiting or forcing the link focus."""
    import json
    context = browser.new_context()
    page = context.new_page()
    html = '''<div id="v2-run-statements" data-st-historical="1" data-out-project="p"
      data-out-snapshot="s" data-out-scenario="Base" data-history-id="h">
      <h2 id="rh-stmt-title" tabindex="-1">Historical</h2>
      <button data-rh-back-detail>Back to Run detail</button>
      <div><div data-st-viewbar="pnl"></div><div data-st-pane="tree">
      <div data-st-region><table data-st-tree="pnl" data-st-basis="annual"><tbody>
      <tr tabindex="-1" data-st-row data-st-key="ebit_keur" aria-expanded="false"><td>
        <button data-st-toggle>Expand</button><a data-st-link href="#trust">EBIT</a></td></tr>
      <tr tabindex="-1" data-st-row data-st-key="revenues_keur" data-st-parent="ebit_keur"><td>Revenue</td></tr>
      <tr tabindex="-1" data-st-row data-st-key="operating_expenses_keur" data-st-parent="ebit_keur"><td>
        <a data-st-link href="#opex">Operating expenses</a></td></tr>
      </tbody></table></div></div></div></div>'''
    page.route('http://statements.test/', lambda route: route.fulfill(body=html, content_type='text/html'))
    try:
        page.goto('http://statements.test/')
        page.evaluate('''() => {
          window.pendingRestore = [];
          window.requestAnimationFrame = cb => { window.pendingRestore.push(cb); return 1; };
          const original = window.setTimeout;
          window.setTimeout = (cb, ms, ...args) => {
            if (ms === 60) { window.pendingRestore.push(cb); return 1; }
            return original(cb, ms, ...args);
          };
        }''')
        state = {'run': {'project': 'p', 'snapshot': 's', 'scenario': 'Base'},
                 'statements': {'pnl': {'expanded': [], 'view': 'tree'}},
                 'focus': {'statement': 'pnl', 'basis': 'annual', 'key': 'ebit_keur'}}
        page.evaluate('(state) => history.replaceState({fincoStmt: state}, "")', state)
        page.add_script_tag(path=str(Path(__file__).resolve().parents[1] / 'static/js/model_statements_tree.js'))
        assert page.evaluate('window.pendingRestore.length') == 1
        if pass_to_delay == 'timer':
            page.evaluate('pendingRestore.shift()()')
        page.locator('[data-st-key="ebit_keur"]').focus()
        page.keyboard.press('ArrowRight')
        page.keyboard.press('ArrowDown')
        page.keyboard.press('ArrowDown')
        assert page.evaluate('document.activeElement.dataset.stKey') == 'operating_expenses_keur'
        if boundary == 'link':
            page.keyboard.press('Tab')
        # A late real restore must not rewind a deliberate keyboard interaction.
        page.evaluate('() => { while (pendingRestore.length) pendingRestore.shift()(); }')
        from tests.model_statements_tree_acceptance import focus_diagnostics
        state = focus_diagnostics(page)
        expected = state['focus'].get('rowKey') if boundary == 'link' else state['focus'].get('key')
        assert expected == 'operating_expenses_keur', json.dumps(state)
        if boundary == 'row':
            page.keyboard.press('Tab')
        state = focus_diagnostics(page)
        assert state['focus']['link'] and state['focus']['href'] == '#opex', json.dumps(state)
        page.keyboard.press('Enter')
        page.wait_for_function("location.hash === '#opex'")
    finally:
        context.close()


def test_late_historical_back_response_cannot_replace_forward_state(browser):
    """Exercise real HTMX and native history, holding only the old response."""
    context = browser.new_context()
    page = context.new_page()
    pending = []
    html = '''<div id="v2-run-statements" data-out-project="p" data-history-id="h">
      <h2 id="rh-stmt-title" tabindex="-1">Historical</h2><button data-rh-back-detail>Back</button></div>'''
    root = Path(__file__).resolve().parents[1]
    page.route('http://statements.test/', lambda route: route.fulfill(body=html, content_type='text/html'))
    page.route('**/run-history/detail?*', lambda route: pending.append(route))
    try:
        page.goto('http://statements.test/')
        page.add_script_tag(path=str(root/'static/vendor/htmx.min.js'))
        page.add_script_tag(path=str(root/'static/js/model_run_history_statements_nav.js'))
        page.evaluate('''() => {
          window.completedReads = 0;
          document.addEventListener('htmx:afterRequest', () => completedReads++);
          history.replaceState({}, '', '/');
          history.pushState({fincoRhStmt:{view:'statements', id:'h'}}, '', '/');
        }''')
        with page.expect_request('**/run-history/detail?*'):
            page.go_back()
        page.go_forward()
        page.wait_for_function("history.state?.fincoRhStmt?.view === 'statements'")
        assert len(pending) == 1
        pending[0].fulfill(content_type='text/html', body='''<div id="v2-run-detail">
          <button data-testid="run-detail-open-statements" data-rh-statements
          data-history-id="h" hx-get="/v2/workbook/run-history/statements?project=p">Open</button></div>''')
        page.wait_for_function('completedReads === 1')
        assert page.locator('#v2-run-statements').count() == 1, page.content()
        assert page.locator('#v2-run-detail').count() == 0
    finally:
        context.close()


def test_trust_diagnostics_and_history_render_exact_contracts_without_automatic_actions(browser, tmp_path):
    import json
    from urllib.parse import urlparse
    ROOT = Path(__file__).resolve().parents[1]

    integrity = {"overall": "INCOMPLETE", "counts": {"PASS": 0, "UNAVAILABLE": 9},
                 "run_identity": {"snapshot_id": "snapshot-contract-123"},
                 "checks": [{"check_id": "balance", "title": "Balance reconciliation",
                             "status": "UNAVAILABLE", "detail": "Evidence is absent"}]}
    payloads = {
        "workspace": {"ok": True, "react_workspace": {"version": "ux02-v1"}, "project": {"code": "p", "name": "Contract replay", "project_type": "solar", "protected_reference": False},
                      "workbook": {"version": "2.0", "composite_hash": "hash-contract", "scenario_id": "scenario-b", "scenario_name": "Scenario B"},
                      "freshness": {"state": "CURRENT", "basis": "canonical", "has_runtime": True, "is_stale": False},
                      "identity": {"snapshot_id": "snapshot-contract-123", "ran_at": "2026-10-25", "scenario": "Scenario B", "scenario_proven": True},
                      "integrity": {"status": "INCOMPLETE", "counts": {}, "failures": []}, "integrity_available": True,
                      "engine": {"currency": "CURRENT_ENGINE"}},
        "trust": {"ok": True, "run_state": "CURRENT", "identity": {"snapshot_id": "snapshot-contract-123"}, "integrity": integrity,
                  "validation": {"state": "DEFERRED", "scope": "Pinned reference only; not validation of this Working Copy", "load_url": "/v2/workbook/trust/validation?project=p"},
                  "certificate": {"state": "DEFERRED", "scope": "Provenance only; availability not established", "load_url": "/v2/workbook/trust/certificate?project=p"}},
        "diagnostics": {"ok": True, "run_state": "CURRENT", "integrity": integrity,
                        "insight": {"run_state": "CURRENT", "context_note": "Committed Run", "not_claims": "Not Verify"},
                        "diagnostics": {"state": "CURRENT", "checks": [{"check_id": "balance", "label": "Balance reconciliation", "status": "UNAVAILABLE", "note": "Evidence is absent"}]}},
        "statements": {"ok": True, "project": {"name": "Contract replay"}, "state": "CURRENT", "snapshot": None,
                       "status": {"runId": "snapshot-contract-123", "freshness": "current", "integrity": "not evaluated", "engineVersion": "engine-contract", "dataOrigin": "caller-provided"},
                       "results": {"available": False}, "integrity_available": True, "integrity": {"status": "INCOMPLETE"}},
        "runs": {"ok": True, "project": {"protected_reference": False}, "run_contract": {"url": "/v2/workbook/run"},
                 "runs": [{"history_id": "history-contract", "runtime_snapshot_id": "snapshot-contract-123", "runtime_origin": "canonical-v2", "ran_at": "2026-10-25", "active_scenario_id": "scenario-b", "active_scenario_name": "Scenario B", "engine_version": "engine-contract", "composite_hash": "hash-contract"}]},
    }
    actions = []
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    def route(request_route):
        request = request_route.request
        path = urlparse(request.url).path
        if request.method not in ("GET", "HEAD"):
            actions.append(request.url)
            return request_route.abort()
        if path.startswith("/v2/workbook/"):
            actions.append(request.url)
            return request_route.abort()
        if path.startswith("/static/"):
            target = ROOT / path.lstrip("/")
            if target.is_file():
                return request_route.fulfill(path=str(target), content_type="application/javascript" if target.suffix == ".js" else "text/css")
            return request_route.fulfill(status=404, body="")
        key = path.rsplit("/", 1)[-1]
        if key in payloads:
            return request_route.fulfill(content_type="application/json", body=json.dumps(payloads[key]))
        return request_route.fulfill(content_type="text/html", body='''<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="/static/react/finco-react.css"><div id="finco-react-root" data-project="p" data-bootstrap-url="/v2/model-react/bootstrap" data-save-url="/v2/workbook/grid/save" data-validate-url="/v2/workbook/grid/validate" data-legacy-url="/v2/workbook?project=p"></div><script src="/static/react/finco-react.js"></script>''')
    context.route("**/*", route)
    try:
        page.goto("http://rc-ux-b.invalid/v2/model-react/p#trust")
        section = page.get_by_role("region", name="Trust and integrity evidence", exact=True)
        section.wait_for()
        assert "INCOMPLETE" in section.inner_text()
        assert "snapshot-contract-123" in section.inner_text()
        assert "not validation of this project" in section.inner_text()
        assert page.get_by_role("link", name="Explicitly run reference regression (separate evidence)").get_attribute("href") == "/v2/workbook/trust/validation?project=p"
        assert len(actions) == 0
        page.screenshot(path=str(tmp_path / "trust-contract-replay.png"), full_page=True)
        page.goto("http://rc-ux-b.invalid/v2/model-react/p#diagnostics")
        checks = page.get_by_role("region", name="Model checks and diagnostics", exact=True)
        checks.wait_for()
        assert "Run state: CURRENT" in checks.inner_text()
        assert "Balance reconciliation" in checks.inner_text()
        assert "Evidence is absent" in checks.inner_text()
        page.screenshot(path=str(tmp_path / "diagnostics-contract-replay.png"), full_page=True)
        page.goto("http://rc-ux-b.invalid/v2/model-react/p#results")
        history = page.get_by_role("region", name="Run history", exact=True)
        history.wait_for()
        assert "Scenario B" in history.inner_text()
        assert "canonical-v2" in history.inner_text()
        assert "hash-contract" in history.inner_text()
        assert "snapshot-contract-123" in history.inner_text()
        page.screenshot(path=str(tmp_path / "history-contract-replay.png"), full_page=True)
        assert not errors
        assert not actions
    except Exception:
        print("Browser errors:", errors)
        print("Rendered body:", page.locator("body").inner_text())
        raise
    finally:
        context.close()


# ── WF-React-1 (PR #377): Product Truth & Financial Workspace acceptance ───────────────
# Additive acceptance in the EXISTING mandatory consolidation role (shared Playwright
# fixture lifecycle; no module-level skip of its own).  The bodies live in
# tests/model_react_wf1_browser_acceptance.py, like the diagnostics acceptance above.

@pytest.fixture
def react_enabled(live_server):
    """The flag is read per request inside the server process, so setting it here
    switches the already-running live server onto the React surface."""
    old = os.environ.get('FINCO_MODEL_REACT_V1')
    os.environ['FINCO_MODEL_REACT_V1'] = '1'
    yield live_server
    if old is None:
        os.environ.pop('FINCO_MODEL_REACT_V1', None)
    else:
        os.environ['FINCO_MODEL_REACT_V1'] = old


@pytest.fixture
def seeded(browser, react_enabled):
    from tests.model_react_wf1_browser_acceptance import make_session
    context, page, record, errors = make_session(browser, react_enabled, 'wf1-user')
    try:
        yield context, page, record, errors, react_enabled
    finally:
        context.close()


def test_product_truth_no_prototype_or_synthetic_content_in_any_section(seeded):
    from tests.model_react_wf1_browser_acceptance import check_product_truth_no_prototype_or_synthetic_content_in_any_section
    check_product_truth_no_prototype_or_synthetic_content_in_any_section(seeded)


def test_statement_units_ratios_negatives_and_rounding_match_canonical_api(seeded):
    from tests.model_react_wf1_browser_acceptance import check_statement_units_ratios_negatives_and_rounding_match_canonical_api
    check_statement_units_ratios_negatives_and_rounding_match_canonical_api(seeded)


def test_results_and_analysis_values_are_the_canonical_values_of_the_same_run(seeded):
    from tests.model_react_wf1_browser_acceptance import check_results_and_analysis_values_are_the_canonical_values_of_the_same_run
    check_results_and_analysis_values_are_the_canonical_values_of_the_same_run(seeded)


def test_current_stale_not_run_are_consistent_across_every_surface(seeded):
    from tests.model_react_wf1_browser_acceptance import check_current_stale_not_run_are_consistent_across_every_surface
    check_current_stale_not_run_are_consistent_across_every_surface(seeded)


def test_library_search_pagination_and_reference_working_copy_status(browser, react_enabled):
    from tests.model_react_wf1_browser_acceptance import check_library_search_pagination_and_reference_working_copy_status
    check_library_search_pagination_and_reference_working_copy_status(browser, react_enabled)


def test_results_analysis_navigation_and_back_forward(seeded):
    from tests.model_react_wf1_browser_acceptance import check_results_analysis_navigation_and_back_forward
    check_results_analysis_navigation_and_back_forward(seeded)


@pytest.mark.parametrize('name,viewport', [('desktop', {'width': 1440, 'height': 1000}),
                                           ('tablet', {'width': 820, 'height': 1100}),
                                           ('mobile', {'width': 390, 'height': 844})])
def test_responsive_layout_has_no_page_level_horizontal_overflow(browser, react_enabled, name, viewport):
    from tests.model_react_wf1_browser_acceptance import check_responsive_layout_has_no_page_level_horizontal_overflow
    check_responsive_layout_has_no_page_level_horizontal_overflow(browser, react_enabled, name, viewport)


# ── WF-React-2 (PR #378): editable model workflow acceptance ───────────────────────────
# Additive acceptance in the EXISTING mandatory consolidation role (shared Playwright
# fixture lifecycle; no module-level skip of its own).  The bodies live in
# tests/model_react_wf2_browser_acceptance.py, like the WF-React-1 acceptance above.

def test_wf2_workflow_bar_and_sections_render_without_errors(browser, react_enabled):
    from tests.model_react_wf2_browser_acceptance import check_workflow_bar_and_sections_render_without_errors
    check_workflow_bar_and_sections_render_without_errors(browser, react_enabled)


def test_wf2_end_to_end_supported_workflow_save_never_runs_and_run_only_when_explicit(browser, react_enabled):
    from tests.model_react_wf2_browser_acceptance import check_end_to_end_supported_workflow_save_never_runs_and_run_only_when_explicit
    check_end_to_end_supported_workflow_save_never_runs_and_run_only_when_explicit(browser, react_enabled)


def test_wf2_guided_ppa_editor_creates_edits_and_schedules_a_contract_book(browser, react_enabled):
    from tests.model_react_wf2_browser_acceptance import check_guided_ppa_editor_creates_edits_and_schedules_a_contract_book
    check_guided_ppa_editor_creates_edits_and_schedules_a_contract_book(browser, react_enabled)


def test_wf2_stale_cas_cannot_overwrite_and_keeps_the_draft(browser, react_enabled):
    from tests.model_react_wf2_browser_acceptance import check_stale_cas_cannot_overwrite_and_keeps_the_draft
    check_stale_cas_cannot_overwrite_and_keeps_the_draft(browser, react_enabled)


def test_wf2_rejected_csrf_token_changes_nothing_and_keeps_the_draft(browser, react_enabled):
    from tests.model_react_wf2_browser_acceptance import check_rejected_csrf_token_changes_nothing_and_keeps_the_draft
    check_rejected_csrf_token_changes_nothing_and_keeps_the_draft(browser, react_enabled)


@pytest.mark.parametrize('scenario', ['field-save', 'cost-add', 'run'])
def test_wf2_unknown_outcomes_are_reconciled_never_retried(browser, react_enabled, scenario):
    from tests.model_react_wf2_browser_acceptance import check_unknown_outcomes_are_reconciled_never_retried
    check_unknown_outcomes_are_reconciled_never_retried(browser, react_enabled, scenario)


def test_wf2_protected_reference_workspace_is_read_only_in_every_editor(browser, react_enabled):
    from tests.model_react_wf2_browser_acceptance import check_protected_reference_workspace_is_read_only_in_every_editor
    check_protected_reference_workspace_is_read_only_in_every_editor(browser, react_enabled)


def test_wf2_scenario_selection_compare_and_overrides_are_isolated_and_never_run(browser, react_enabled):
    from tests.model_react_wf2_browser_acceptance import check_scenario_selection_compare_and_overrides_are_isolated_and_never_run
    check_scenario_selection_compare_and_overrides_are_isolated_and_never_run(browser, react_enabled)


@pytest.mark.parametrize('width,height', [(1440, 900), (900, 1000), (390, 844)])
def test_wf2_editable_sections_fit_desktop_tablet_and_mobile(browser, react_enabled, width, height):
    from tests.model_react_wf2_browser_acceptance import check_editable_sections_fit_desktop_tablet_and_mobile
    check_editable_sections_fit_desktop_tablet_and_mobile(browser, react_enabled, width, height)


# ── PR #378 Correction B: unsaved-input integrity, navigation protection, Run safety ───
# Bodies in tests/model_react_wf2_lifecycle_acceptance.py (no module-level skip there).

@pytest.mark.parametrize('check', [
    'check_grid_draft_counts_blocks_run_and_unchanged_values_are_not_dirty',
    'check_navigation_with_unsaved_edits_asks_and_keeps_the_draft',
    'check_verified_save_clears_dirty_updates_identity_and_enables_an_explicit_run',
    'check_failed_stale_and_unknown_saves_keep_drafts_and_locks_without_duplicates',
    'check_every_editor_reports_unsaved_work_and_guards_navigation',
    'check_rapid_repeated_activation_starts_at_most_one_run',
    'check_run_is_blocked_while_a_save_is_in_flight',
    'check_drafts_never_transfer_to_another_scenario_or_project',
    'check_protected_reference_grid_cannot_stage_or_save',
    'check_pending_mutations_cannot_escape_their_reconciliation_contract',
])
def test_wf2_lifecycle_acceptance(browser, react_enabled, check):
    import tests.model_react_wf2_lifecycle_acceptance as lifecycle
    getattr(lifecycle, check)(browser, react_enabled)


# ── RC-REACT-MVP: integrated Financial Insights + Internal MVP acceptance ───────────────
# Bodies in tests/model_react_mvp_acceptance.py (no module-level skip there).

def test_mvp_library_clone_creates_an_openable_unprotected_working_copy(browser, react_enabled):
    from tests.model_react_mvp_acceptance import check_library_clone_creates_an_openable_unprotected_working_copy
    check_library_clone_creates_an_openable_unprotected_working_copy(browser, react_enabled)


@pytest.mark.parametrize('kind', ['solar', 'wind'])
def test_mvp_internal_path_with_financial_intelligence(browser, react_enabled, kind):
    from tests.model_react_mvp_acceptance import check_internal_mvp_path_with_financial_intelligence
    check_internal_mvp_path_with_financial_intelligence(browser, react_enabled, kind)


def test_mvp_responsive_insights_and_touch_targets(browser, react_enabled):
    from tests.model_react_mvp_acceptance import check_responsive_insights_and_touch_targets
    check_responsive_insights_and_touch_targets(browser, react_enabled)


# ── D-029: Run intent (idempotency), React + Legacy ────────────────────────────────────
# Bodies in tests/model_d029_run_intent_browser_acceptance.py (no module-level skip there).

@pytest.mark.parametrize('check', [
    'check_react_run_sends_a_uuid_intent_and_consumes_it_on_commit',
    'check_react_lost_response_survives_reload_and_resumes_the_original_run',
    'check_react_resume_after_the_draft_changed_never_runs_against_the_new_draft',
    'check_react_typed_outcomes_keep_or_consume_the_intent',
])
def test_d029_react_run_intent_acceptance(browser, react_enabled, check):
    import tests.model_d029_run_intent_browser_acceptance as d029
    getattr(d029, check)(browser, react_enabled)


@pytest.mark.parametrize('check', [
    'check_legacy_run_carries_a_uuid_and_consumes_it_on_commit',
    'check_legacy_lost_response_reload_and_oob_refresh_keep_the_same_run',
    'check_legacy_queued_run_after_pending_save_keeps_one_key_and_the_saved_binding',
])
def test_d029_legacy_run_intent_acceptance(browser, live_server, check):
    import tests.model_d029_run_intent_browser_acceptance as d029
    getattr(d029, check)(browser, live_server)


# ── Overnight B: React Institutional Model MVP correction ───────────────────────────────────────────────
# Bodies in tests/model_react_overnight_b_acceptance.py (no module-level skip there).  Additive: no existing node id changes.

@pytest.mark.parametrize('kind', ['solar', 'wind', 'data_center', 'ev_charging'])
def test_onb_statement_identity_is_the_authorized_project_in_every_vertical(browser, react_enabled, kind):
    from tests.model_react_overnight_b_acceptance import check_statement_identity_is_the_authorized_project_in_every_vertical
    check_statement_identity_is_the_authorized_project_in_every_vertical(browser, react_enabled, kind)


def test_onb_hostile_or_stale_query_cannot_change_the_statement_identity(browser, react_enabled):
    from tests.model_react_overnight_b_acceptance import check_hostile_or_stale_query_cannot_change_the_statement_identity
    check_hostile_or_stale_query_cannot_change_the_statement_identity(browser, react_enabled)


def test_onb_switching_projects_never_carries_the_previous_statement_identity(browser, react_enabled):
    from tests.model_react_overnight_b_acceptance import check_switching_projects_never_carries_the_previous_statement_identity
    check_switching_projects_never_carries_the_previous_statement_identity(browser, react_enabled)


def test_onb_missing_or_conflicting_identity_fails_visibly(browser, react_enabled):
    from tests.model_react_overnight_b_acceptance import check_missing_or_conflicting_identity_fails_visibly
    check_missing_or_conflicting_identity_fails_visibly(browser, react_enabled)


def test_onb_two_runs_in_the_same_hour_are_distinguishable_everywhere(browser, react_enabled):
    from tests.model_react_overnight_b_acceptance import check_two_runs_in_the_same_hour_are_distinguishable_everywhere
    check_two_runs_in_the_same_hour_are_distinguishable_everywhere(browser, react_enabled)


def test_onb_scenario_comparison_and_results_refer_to_the_intended_run(browser, react_enabled):
    from tests.model_react_overnight_b_acceptance import check_scenario_comparison_and_results_refer_to_the_intended_run
    check_scenario_comparison_and_results_refer_to_the_intended_run(browser, react_enabled)


def test_onb_inputs_save_scope_language_is_accurate(browser, react_enabled):
    from tests.model_react_overnight_b_acceptance import check_inputs_save_scope_language_is_accurate_and_free_of_engineering_copy
    check_inputs_save_scope_language_is_accurate_and_free_of_engineering_copy(browser, react_enabled)


def test_onb_scalar_save_persists_after_reload_and_never_saves_another_editor(browser, react_enabled):
    from tests.model_react_overnight_b_acceptance import check_scalar_save_persists_after_reload_and_never_saves_another_editor
    check_scalar_save_persists_after_reload_and_never_saves_another_editor(browser, react_enabled)


@pytest.mark.parametrize('kind,width,limit', [('solar', 1440, 6000), ('solar', 390, 10000), ('data_center', 390, 8000), ('ev_charging', 320, 9000)])
def test_onb_inputs_are_compact_complete_and_navigable(browser, react_enabled, kind, width, limit):
    from tests.model_react_overnight_b_acceptance import check_inputs_are_compact_complete_and_navigable
    check_inputs_are_compact_complete_and_navigable(browser, react_enabled, kind, width, limit)


def test_onb_protected_reference_inputs_stay_visible_and_read_only(browser, react_enabled):
    from tests.model_react_overnight_b_acceptance import check_protected_reference_inputs_stay_visible_and_read_only
    check_protected_reference_inputs_stay_visible_and_read_only(browser, react_enabled)


def test_onb_workspace_navigation_is_discoverable_and_keyboard_operable(browser, react_enabled):
    from tests.model_react_overnight_b_acceptance import check_workspace_navigation_is_discoverable_keyboard_operable_and_never_overflows_the_page
    check_workspace_navigation_is_discoverable_keyboard_operable_and_never_overflows_the_page(browser, react_enabled)


@pytest.mark.parametrize('kind', ['solar', 'data_center', 'ev_charging'])
def test_onb_labels_and_typography_have_no_duplicated_units_or_literal_escapes(browser, react_enabled, kind):
    from tests.model_react_overnight_b_acceptance import check_labels_and_typography_have_no_duplicated_units_or_literal_escapes
    check_labels_and_typography_have_no_duplicated_units_or_literal_escapes(browser, react_enabled, kind)


@pytest.mark.parametrize('kind', ['solar', 'wind', 'data_center', 'ev_charging'])
def test_onb_returns_lender_metrics_and_vertical_scope_are_truthful(browser, react_enabled, kind):
    from tests.model_react_overnight_b_acceptance import check_returns_lender_metrics_and_vertical_scope_are_truthful
    check_returns_lender_metrics_and_vertical_scope_are_truthful(browser, react_enabled, kind)


def test_onb_scenario_override_boundary_matches_the_canonical_capability(browser, react_enabled):
    from tests.model_react_overnight_b_acceptance import check_scenario_override_boundary_matches_the_canonical_capability
    check_scenario_override_boundary_matches_the_canonical_capability(browser, react_enabled)


def test_onb_every_theme_keeps_the_corrected_surfaces_legible(browser, react_enabled):
    from tests.model_react_overnight_b_acceptance import check_every_theme_keeps_the_corrected_surfaces_legible
    check_every_theme_keeps_the_corrected_surfaces_legible(browser, react_enabled)


# RC-M integrated React acceptance (New Project wizard, Analysis, Financing, Investors, all-theme legibility).
# The bodies live in non-collected modules (each ``__all__`` lists its tests and fixture), so the mandatory consolidation role
# executes them with its own fail-closed inventory / JUnit verifier and no collection-time skip is introduced.
from tests.model_react_rcm_support import rcm_react_flag  # noqa: E402,F401
from tests.model_react_rcm_new_project_acceptance import *  # noqa: E402,F401,F403
from tests.model_react_rcm_analysis_acceptance import *  # noqa: E402,F401,F403
from tests.model_react_rcm_financing_acceptance import *  # noqa: E402,F401,F403
from tests.model_react_rcm_investors_acceptance import *  # noqa: E402,F401,F403
from tests.model_react_rcm_themes_acceptance import *  # noqa: E402,F401,F403


# RC-UX Completion V1 (Audit A GAP-R13): React Analysis > Run history & compare.  Same pattern as RC-M: a non-collected acceptance module
# executed by this existing mandatory role, so no collection-time skip is introduced.
from tests.model_react_rcux_runs_acceptance import *  # noqa: E402,F401,F403
from tests.model_react_rcux_capex_acceptance import *  # noqa: E402,F401,F403
from tests.model_react_rcux_product_acceptance import *  # noqa: E402,F401,F403
