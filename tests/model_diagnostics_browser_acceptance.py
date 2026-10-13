"""Synthetic authenticated Chromium acceptance; financial assertions, not screenshots alone."""
import json
import os
from pathlib import Path

import pytest

from tests.test_workflow_c_browser_v1 import live_server, browser  # noqa: F401
from tests.test_model_workspace_consolidation_browser import workspace, assert_unique_dom_ids  # noqa: F401


def capture(page, errors, name):
    folder = Path(os.environ.get("DIAGNOSTICS_SCREENSHOT_DIR", "artifacts/model-diagnostics"))
    folder.mkdir(parents=True, exist_ok=True)
    page.evaluate('window.scrollTo(0,0)')
    page.screenshot(path=str(folder / (name + ".png")), full_page=True)
    page.screenshot(path=str(folder / (name + "-viewport.png")))
    (folder / (name + "-console.json")).write_text(json.dumps(errors), encoding="utf-8")
    assert not errors, errors
    assert_unique_dom_ids(page)


def run(page):
    with page.expect_response(lambda r: '/v2/workbook/run' in r.url and r.request.method == 'POST', timeout=240000) as response:
        page.locator('[data-testid="header-run-btn"]').click()
    assert response.value.status == 200
    page.wait_for_function("() => document.querySelector('#v2-sheet-diagnostics').dataset.state === 'CURRENT'", timeout=240000)


@pytest.mark.parametrize("template", ['generic_solar_reference', 'generic_wind_reference',
                                      'generic_data_center_reference', 'generic_ev_charging_reference'])
def test_diagnostics_vertical_run_health_matrix_detail_and_readonly(workspace, template):
    from app.persistence.workspace_repository import get_workspace_state
    from app.run_integrity import run_integrity_checks
    page, record, errors = workspace(template)
    assert page.locator('#v2-model-health').get_attribute('data-state') == 'NOT_RUN'
    page.locator('#v2-model-health [data-nav-tab]').first.click()
    assert page.locator('#panel-diagnostics').is_visible()
    assert page.locator('[data-md-row]').count() == 0
    run(page)
    ws = get_workspace_state(record.user_id, record.project_id)
    page.reload()
    page.locator('[data-hy-group="diagnostics"]').click()
    data = json.loads(page.locator('[data-md-payload]').text_content())
    assert len(data['checks']) == page.locator('[data-md-row]').count() == 30
    assert data['integrity'] == run_integrity_checks(ws.last_integrity_evidence).to_dict()
    assert data['identity']['snapshot_id'] == ws.last_runtime_snapshot_id
    assert len(data['columns']) == page.locator('.md-matrix').first.locator('thead th').count() - 4
    assert all(c['date'] for c in data['columns'])
    page.locator('[data-md-status]').select_option('UNAVAILABLE')
    assert page.locator('[data-md-row]:visible').count() == data['score']['counts']['unavailable']
    page.locator('[data-md-status]').select_option('')
    page.locator('[data-md-search]').fill('QM-SD-002')
    assert page.locator('[data-md-row]:visible').count() == 1
    period = next(p for p in next(c for c in data['checks'] if c['check_id'] == 'QM-SD-002')['periods'] if p['status'] == 'PASS')
    button = page.locator(f'[data-md-select="QM-SD-002"][data-md-period="{period["period_index"]}"]')
    button.focus(); page.keyboard.press('Enter')
    assert page.locator('[data-md-detail]').is_visible()
    assert 'PERIOD' in page.locator('[data-md-detail-facts]').inner_text()
    assert page.locator('.md-selected-period').count() > 0
    page.locator('[data-md-schedule]').click()
    assert page.locator('#panel-debt').is_visible()
    page.go_back()
    page.wait_for_selector('#panel-diagnostics', state='visible')
    page.reload()
    page.wait_for_selector('[data-md-detail]', state='visible')
    assert 'QM-SD-002' in page.locator('[data-md-detail-title]').inner_text()
    assert get_workspace_state(record.user_id, record.project_id) == ws  # GETs never rerun or persist
    page.locator('[data-md-search]').fill('')
    group = page.locator('[data-md-group]').first
    group.locator('summary').click()
    assert not group.evaluate('(node) => node.open')
    group.locator('summary').click()
    capture(page, errors, template)


def test_failed_check_period_residual_drilldown_and_mobile(workspace):
    from app.persistence import db
    from app.persistence.workspace_repository import get_workspace_state
    from app.run_integrity import evidence_digest
    page, record, errors = workspace(width=390, scheme='dark')
    run(page)
    ws = get_workspace_state(record.user_id, record.project_id)
    evidence = ws.last_integrity_evidence
    target = evidence['senior_debt']['periods'][2]
    target['interest'] += 5
    evidence['digest'] = evidence_digest(evidence)
    # Deliberate synthetic committed-evidence corruption, NEVER a production route.
    with db.get_connection() as conn:
        conn.execute('UPDATE workspace_states SET last_integrity_evidence_json=? WHERE project_id=? AND user_id=?',
                     (json.dumps(evidence), record.project_id, record.user_id))
        conn.commit()
    page.reload()
    page.locator('[data-hy-group="diagnostics"]').click()
    page.locator('[data-md-status]').select_option('FAIL')
    failed = page.locator(f'[data-md-select="QM-SD-002"][data-md-period="{target["period_index"]}"]')
    assert 'FAIL' in failed.get_attribute('aria-label')
    failed.click()
    assert 'INTEREST_OR_DEBT_SERVICE_MISMATCH' in page.locator('[data-md-detail]').inner_text()
    assert page.locator('.md-scroll:visible').first.evaluate('(n) => n.scrollWidth > n.clientWidth')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    assert page.locator('#v2-sheet-diagnostics').evaluate('(n) => getComputedStyle(n).backgroundColor') == 'rgb(24, 34, 49)'
    scroll = page.locator('.md-scroll:visible').first
    scroll.evaluate('(n) => { n.scrollLeft = n.scrollWidth; }')
    assert scroll.evaluate('(n) => n.scrollLeft > 0')
    page.locator('[aria-controls="model-smart-panel"][data-workspace-drawer]').click()
    page.locator('#model-smart-panel [data-diagnostics-check="QM-SD-002"]').click()
    assert 'QM-SD-002' in page.locator('[data-md-detail-title]').inner_text()
    page.locator('[aria-controls="model-smart-panel"][data-workspace-drawer]').click()
    capture(page, errors, 'failed-check-mobile')
