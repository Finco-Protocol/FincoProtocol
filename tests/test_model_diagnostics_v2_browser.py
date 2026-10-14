"""Diagnostics V2 in real Chromium: period risk heatmap, advanced checks, drill-down with root-cause relationships,
bankability monitor, keyboard selection and the 390 px layout.  Synthetic projects; read-only; zero console errors."""
import json

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")

from tests.test_workflow_c_browser_v1 import live_server, browser  # noqa: F401,E402
from tests.test_model_workspace_consolidation_browser import workspace, assert_unique_dom_ids  # noqa: F401,E402
from tests.model_diagnostics_browser_acceptance import capture, run  # noqa: E402


def open_diagnostics(page):
    page.locator('[data-hy-group="diagnostics"]').click()
    page.wait_for_selector('[data-md2]', state='visible')


@pytest.mark.parametrize("template", ['generic_solar_reference', 'generic_wind_reference',
                                      'generic_data_center_reference', 'generic_ev_charging_reference'])
def test_v2_sections_checks_heatmap_and_bankability_per_vertical(workspace, template):
    from app.persistence.workspace_repository import get_workspace_state
    page, record, errors = workspace(template)
    run(page)
    ws = get_workspace_state(record.user_id, record.project_id)
    page.reload()
    open_diagnostics(page)
    data = json.loads(page.locator('[data-md-payload]').text_content())
    v2 = data['v2']
    assert page.locator('.md2-heat-cell').count() == len(data['columns']) == len(v2['heatmap']['cells'])
    assert page.locator('[data-md2-row]').count() == 9 == v2['advanced_summary']['registered']
    assert len(data['checks']) == page.locator('[data-md-row]').count() == 30          # V1 matrix unchanged
    assert not page.locator('[data-md-row][data-check-id^="DX-"]').count()               # DX never enters the Quality matrix
    bank = page.locator('[data-md2-bankability]')
    assert bank.is_visible() and 'NOT_SOURCE_PROVEN' in bank.inner_text() and 'FINANCING_SIZING_TARGET' in bank.inner_text()
    assert 'no event of default is declared' in bank.inner_text()
    # keyboard selection of an advanced check cell opens evidence: definition, components, tolerance source
    check = next(c for c in v2['advanced_checks'] if c['check_id'] == 'DX-CASH-001')
    period = next(p for p in check['periods'] if p['status'] == 'PASS')
    cell = page.locator(f'[data-md2-select="DX-CASH-001"][data-md2-period="{period["period_index"]}"]')
    cell.focus(); page.keyboard.press('Enter')
    detail = page.locator('[data-md2-detail]')
    assert detail.is_visible()
    text = detail.inner_text()
    assert 'Distributable cash' in text and 'Tolerance source' in text and 'cfads' in text and 'pf_cash_waterfall.fcf_banks_keur' in text
    assert page.locator('.md-selected-period').count() > 0
    # period selection from the heatmap
    heat = page.locator(f'.md2-heat-cell[data-md2-period="{period["period_index"]}"]')
    heat.click()
    assert page.locator('[data-md2-period-detail]').is_visible()
    assert 'applicable checks' in page.locator('[data-md2-period-detail]').inner_text()
    # existing V1 detail still works beside it
    page.locator('[data-md-search]').fill('QM-SD-002')
    page.locator('[data-md-select="QM-SD-002"]').first.click()
    assert page.locator('[data-md-detail]').is_visible()
    page.locator('[data-md-search]').fill('')
    assert get_workspace_state(record.user_id, record.project_id) == ws                 # GET and navigation never persist
    capture(page, errors, 'v2-' + template)


def _corrupt_statement(record, period_index, **changes):
    from app.persistence import db
    from app.persistence.workspace_repository import get_workspace_state
    ws = get_workspace_state(record.user_id, record.project_id)
    statements = ws.last_financial_statements
    row = next(r for r in statements['pf_cash_waterfall']['periods'] if r['period_index'] == period_index)
    row.update(changes)
    with db.get_connection() as conn:
        conn.execute('UPDATE workspace_states SET last_financial_statements_json=? WHERE project_id=? AND user_id=?',
                     (json.dumps(statements), record.project_id, record.user_id))
        conn.commit()


def test_failed_period_heatmap_drilldown_root_cause_and_mobile(workspace):
    from app.persistence.workspace_repository import get_workspace_state
    page, record, errors = workspace(width=390, scheme='dark')
    run(page)
    ws = get_workspace_state(record.user_id, record.project_id)
    target = next(r for r in ws.last_financial_statements['pf_cash_waterfall']['periods']
                  if (r.get('fcf_for_distribution_keur') or 0) > 1)
    index = target['period_index']
    # Deliberate synthetic committed-evidence corruption, NEVER a production route.
    _corrupt_statement(record, index, fcf_for_distribution_keur=target['fcf_for_distribution_keur'] + 7.0)
    page.reload()
    open_diagnostics(page)
    cell = page.locator(f'.md2-heat-cell[data-md2-period="{index}"]')
    assert 'failed' in cell.get_attribute('aria-label') and cell.inner_text().startswith('✕')
    cell.click()
    host = page.locator('[data-md2-period-detail]')
    assert 'DX-CASH-001' in host.inner_text() and 'highest severity HIGH' in host.inner_text()
    host.locator('[data-md2-select="DX-CASH-001"]').click()
    detail = page.locator('[data-md2-detail]').inner_text()
    assert 'IDENTITY_RESIDUAL_OUTSIDE_TOLERANCE' in detail and 'PROVEN' in detail
    assert 'does not by itself prove why' in detail and 'cause established: no' in detail
    assert 'Residual (observed - expected)' in detail
    # the same failed period is also visible in the Advanced check matrix as a failed cell
    failed = page.locator(f'.md-cell[data-md2-select="DX-CASH-001"][data-md2-period="{index}"]')
    assert 'FAIL' in failed.get_attribute('aria-label')
    assert page.locator('[data-md2-row][data-check-id="DX-CASH-001"]').get_attribute('data-status') == 'FAIL'
    # mobile: tables scroll horizontally inside their own container, never the page
    assert page.locator('.md-scroll:visible').first.evaluate('(n) => n.scrollWidth > n.clientWidth')
    assert page.locator('.md2-scroll:visible').first.evaluate('(n) => n.scrollWidth > n.clientWidth')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    page.locator('[data-md2-bankability] summary').click()
    assert not page.locator('[data-md2-bankability]').evaluate('(n) => n.open')
    page.locator('[data-md2-bankability] summary').click()
    capture(page, errors, 'v2-failed-period-mobile')


def test_guided_actions_navigate_only_and_disabled_actions_state_their_reason(workspace):
    from app.persistence.workspace_repository import get_workspace_state
    page, record, errors = workspace('generic_solar_reference')
    run(page)
    ws = get_workspace_state(record.user_id, record.project_id)
    page.reload()
    open_diagnostics(page)
    posts = []
    page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' else None)
    # an existing V1 check mapped by Q4: what-if is enabled on Solar and only OPENS Insight
    page.locator('[data-md-search]').fill('QM-SD-004')
    page.locator('[data-md-select="QM-SD-004"]').first.click()
    page.wait_for_selector('[data-md2-v1-rootcause] [data-md2-action]')
    actions = page.locator('[data-md2-v1-rootcause] [data-md2-action]')
    assert actions.count() == 6
    whatif = page.locator('[data-md2-v1-rootcause] [data-md2-action="finding_whatif"]')
    assert whatif.is_enabled()
    goal = page.locator('[data-md2-v1-rootcause] [data-md2-action="goal_seek"]')
    assert goal.is_disabled() and 'not a return shortfall' in page.locator('[data-md2-v1-rootcause]').inner_text()
    page.locator('[data-md2-v1-rootcause] [data-md2-action="open_schedule"]').click()
    assert page.locator('#panel-debt').is_visible()
    open_diagnostics_again = page.locator('[data-hy-group="diagnostics"]')
    open_diagnostics_again.click()
    # an advanced check has no Q4 mapping: disabled WITH a visible reason
    check = page.locator('[data-md2-select="DX-CASH-001"]').first
    check.click()
    detail = page.locator('[data-md2-detail]')
    assert detail.locator('[data-md2-action="finding_whatif"]').is_disabled()
    assert 'no registered mapping' in detail.inner_text() and 'Unavailable:' in detail.inner_text()
    assert detail.locator('[data-md2-action="compare_runs"]').is_enabled()
    detail.locator('[data-md2-action="compare_runs"]').click()
    assert page.locator('#panel-compare').is_visible()
    assert posts == [], posts                                           # navigation only: no write, no Run
    assert get_workspace_state(record.user_id, record.project_id) == ws
    assert not errors, errors


def test_run_comparison_section_between_two_committed_runs(workspace):
    page, record, errors = workspace('generic_wind_reference')
    run(page)
    run(page)
    page.reload()
    open_diagnostics(page)
    section = page.locator('[data-md2-compare]')
    assert section.is_visible()
    assert page.locator('[data-md2-compare-select] option').count() == 1
    counts = page.locator('[data-md2-compare-run]:visible [data-md2-compare-counts]').inner_text()
    assert 'UNCHANGED_PASS' in counts and 'NOT_COMPARABLE' in counts and 'RESOLVED' not in counts
    assert page.locator('[data-md2-compare-run]:visible [data-md2-compare-row]').count() == 39
    assert 'never' in section.inner_text() and 'NOT_COMPARABLE' in section.inner_text()
    assert not errors, errors
