"""Authenticated Workflow D acceptance with real canonical runs and isolated DB.

Run explicitly: python -m tests.model_decision_workspace_browser
Screenshots and machine-readable evidence remain ignored in artifacts/.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import socket
import tempfile
import threading
import time


def main():
    import uvicorn
    from fastapi.testclient import TestClient
    from playwright.sync_api import sync_playwright, expect
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence import db
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.scenarios_repository import get_scenario
    from app.services.export_service import resolve_canonical_last_run_from_workspace
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.runtime.model_execution import reset_model_executor_for_tests
    from main_web import app

    out = Path("artifacts/model-decision-workspace")
    out.mkdir(parents=True, exist_ok=True)
    original = db.DB_PATH
    server = thread = None
    evidence = []
    cookie = create_session_token(user_id="decision-browser", username="admin")
    def settled(page):
        expect(page.locator('.htmx-request')).to_have_count(0)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            db.DB_PATH = str(Path(tmp) / "browser.db")
            db.init_db()
            records = []
            with TestClient(app) as client:
                client.cookies.set(COOKIE_NAME, cookie)
                for kind, capacity in (("solar", 64), ("wind", 48), ("data_center", 16), ("ev_charging", 1)):
                    record = create_reference_seeded_project(user_id="decision-browser", requested_name="Decision " + kind,
                        template_source="generic_" + kind + "_reference", capacity_mw=capacity)
                    page = client.get("/v2/workbook", params={"project": record.project_code})
                    data = {key: re.search(r'name="' + key + r'" value="([^"]+)"', page.text).group(1)
                            for key in ("content_hash", "workbook_version")}
                    result = client.post("/v2/workbook/run", headers={"HX-Request": "true"}, data={"project": record.project_code, **data})
                    assert result.status_code == 200, result.text[:1000]
                    assert get_workspace_state("decision-browser", record.project_id).last_runtime_snapshot_id
                    records.append((kind, record))
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            sock.close()
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="off"))
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            deadline = time.monotonic() + 30
            while not server.started:
                assert time.monotonic() < deadline
                time.sleep(.1)
            with sync_playwright() as pw:
                kwargs = {"executable_path": os.environ["FINCO_TEST_CHROMIUM_PATH"]} if os.environ.get("FINCO_TEST_CHROMIUM_PATH") else {}
                browser = pw.chromium.launch(**kwargs)
                try:
                    for kind, record in ([] if os.environ.get('FINCO_DECISION_JOURNEY_ONLY') else records):
                        for theme, width in (("light", 1440), ("dark", 1440), ("light", 390), ("dark", 390)):
                            ctx = browser.new_context(viewport={"width": width, "height": 1000}, color_scheme=theme)
                            ctx.add_init_script("document.addEventListener('DOMContentLoaded', () => document.documentElement.dataset.theme = " + json.dumps(theme) + ")")
                            ctx.add_cookies([{"name": COOKIE_NAME, "value": cookie, "url": f"http://127.0.0.1:{port}"}])
                            page = ctx.new_page()
                            errors = []
                            page.on("pageerror", lambda e: errors.append(str(e)))
                            for sheet in ("revenue", "scenarios", "sensitivity", "goal-seek"):
                                response = page.goto(f"http://127.0.0.1:{port}/v2/workbook?project={record.project_code}&sheet={sheet}")
                                assert response.status == 200
                                panel = page.locator("#panel-" + sheet)
                                expect(panel).to_be_visible()
                                assert panel.bounding_box()["width"] <= width
                                filename = f"{kind}-{sheet}-{theme}-{width}.png"
                                page.screenshot(path=str(out / filename), full_page=True)
                                assert not errors, errors
                                evidence.append({"kind": kind, "sheet": sheet, "theme": theme, "width": width, "screenshot": filename})
                            ctx.close()
                    if evidence:
                        (out/'visual-acceptance.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
                    for kind, record in ([] if os.environ.get('FINCO_DECISION_VISUAL_ONLY') else records[:2]):
                        ctx = browser.new_context(viewport={"width":1440,"height":1000})
                        ctx.add_cookies([{"name": COOKIE_NAME, "value": cookie, "url": f"http://127.0.0.1:{port}"}])
                        page = ctx.new_page()
                        page.goto(f"http://127.0.0.1:{port}/v2/workbook?project={record.project_code}&sheet=revenue")
                        page.locator('#nav-rev-merchant').click()
                        form = page.locator('[data-decision-merchant]')
                        if form.locator('tbody tr').count() == 0:
                            form.locator('[data-add-year]').click()
                            form.locator('[data-key=price_eur_mwh]').first.fill('80')
                        expect(form.locator('tbody tr').first).to_be_visible()
                        count = form.locator('tbody tr').count()
                        page.wait_for_timeout(500)
                        assert form.locator('tbody tr').count() == count  # idempotent initializer
                        price = form.locator('[data-key=price_eur_mwh]').first
                        expected_price = float(price.input_value()) + 1
                        price.fill(str(expected_price))
                        with page.expect_response(lambda r: '/v2/workbook/update' in r.url and r.request.method == 'POST'):
                            price.press('Enter')
                        settled(page)
                        page.reload()
                        page.locator('#nav-rev-merchant').click()
                        saved = get_workspace_state('decision-browser', record.project_id)
                        assert 'rev_merchant_price_curve_json' in saved.draft_snapshot
                        assert json.loads(saved.draft_snapshot['rev_merchant_price_curve_json'])[0]['price_eur_mwh'] == expected_price
                        with page.expect_response(lambda r: '/v2/workbook/run' in r.url and r.request.method == 'POST', timeout=120000):
                            page.locator('[data-testid=header-run-btn]').click()
                        page.reload()
                        expect(page.locator('[data-testid=revenue-state-clean]')).to_be_visible(timeout=120000)
                        base_run = get_workspace_state('decision-browser', record.project_id)
                        economics = [{'case': 'Base', 'working_override': None, 'run_bound_override': None,
                            'effective_tariff': base_run.last_runtime_summary['scenario_revenue_input']['effective_tariff_eur_mwh'],
                            'revenue_keur': base_run.last_runtime_summary['total_revenue_keur'],
                            'project_irr': base_run.last_runtime_summary['project_irr']}]
                        working_snapshot = dict(base_run.draft_snapshot)
                        def capture_case(name, scenario_id, tariff):
                            ws = get_workspace_state('decision-browser', record.project_id)
                            sc = get_scenario(scenario_id, 'decision-browser')
                            summary = sc.last_run_summary
                            assert sc.overrides['tariff_eur_mwh'] == tariff
                            assert summary['scenario_overrides_at_run']['tariff_eur_mwh'] == tariff
                            assert summary['scenario_revenue_input']['effective_tariff_eur_mwh'] == tariff
                            assert dict(ws.draft_snapshot) == working_snapshot
                            assert ws.last_runtime_scenario_id == scenario_id
                            assert ws.last_runtime_summary['total_revenue_keur'] == summary['kpis']['total_revenue_keur']
                            authority = resolve_canonical_last_run_from_workspace(record, 'decision-browser', ws)
                            assert authority.project_inputs.revenue.ppa_base_tariff == tariff
                            economics.append({'case':name, 'working_override':tariff, 'run_bound_override':tariff,
                                'effective_tariff':summary['scenario_revenue_input']['effective_tariff_eur_mwh'],
                                'revenue_keur':summary['kpis']['total_revenue_keur'], 'project_irr':summary['kpis']['project_irr']})
                        page.locator('#tab-scenarios').click()
                        page.locator('.v2-scenario-create-form input[name=scenario_name]').fill('Pricing Upside')
                        with page.expect_response(lambda r:'/scenarios/create' in r.url):
                            page.locator('.v2-scenario-create-form button').click()
                        settled(page)
                        row = page.locator('.v2-scenario-row').filter(has_text='Pricing Upside')
                        sid = row.get_attribute('data-scenario-id')
                        row.locator('button.v2-scenario-action-btn--edit').click()
                        page.locator('#ov-tariff_eur_mwh').fill('85')
                        with page.expect_response(lambda r:'/scenarios/update-overrides' in r.url):
                            page.locator('#v2-scenario-override-form button[type=submit]').click()
                        settled(page)
                        row = page.locator('.v2-scenario-row[data-scenario-id="' + sid + '"]')
                        if row.get_by_role('button',name='Select',exact=True).count():
                            with page.expect_response(lambda r:'/scenarios/select' in r.url):
                                row.get_by_role('button',name='Select',exact=True).click()
                            settled(page)
                        with page.expect_response(lambda r:'/v2/workbook/run' in r.url and r.request.method=='POST', timeout=120000) as run_response:
                            page.locator('[data-testid=header-run-btn]').click()
                        run_html = run_response.value.text()
                        assert 'id="v2-sheet-returns"' in run_html, run_html[:2000]
                        expect(page.locator('.v2-scenario-row[data-scenario-id="' + sid + '"] .v2-scenario-state')).to_have_text('Current',timeout=120000)
                        capture_case('Upside', sid, 85)
                        page.locator('.v2-scenario-create-form input[name=scenario_name]').fill('Pricing Downside')
                        with page.expect_response(lambda r:'/scenarios/create' in r.url):
                            page.locator('.v2-scenario-create-form button').click()
                        settled(page)
                        downside = page.locator('.v2-scenario-row').filter(has_text='Pricing Downside')
                        downside_id = downside.get_attribute('data-scenario-id')
                        downside.locator('button.v2-scenario-action-btn--edit').click()
                        page.locator('#ov-tariff_eur_mwh').fill('45')
                        with page.expect_response(lambda r:'/scenarios/update-overrides' in r.url):
                            page.locator('#v2-scenario-override-form button[type=submit]').click()
                        settled(page)
                        with page.expect_response(lambda r:'/v2/workbook/run' in r.url and r.request.method=='POST', timeout=120000):
                            page.locator('[data-testid=header-run-btn]').click()
                        expect(page.locator('.v2-scenario-row[data-scenario-id="' + downside_id + '"] .v2-scenario-state')).to_have_text('Current', timeout=120000)
                        capture_case('Downside', downside_id, 45)
                        assert economics[1]['revenue_keur'] > economics[0]['revenue_keur'] > economics[2]['revenue_keur']
                        assert economics[1]['project_irr'] > economics[0]['project_irr'] > economics[2]['project_irr']
                        page.locator('#tab-compare').click()
                        expect(page.locator('.v2-compare-chip')).to_have_count(3,timeout=30000)
                        for chip in page.locator('.v2-compare-chip').all(): chip.click()
                        with page.expect_response(lambda r:'/scenarios/compare' in r.url): page.locator('#v2-compare-submit-btn').click()
                        expect(page.locator('[data-testid=cmp-project_irr-delta-s2]')).to_contain_text('pp')
                        page.screenshot(path=str(out/f'{kind}-compare.png'),full_page=True)
                        with page.expect_response(lambda r:'/decision/sensitivity' in r.url): page.locator('#tab-sensitivity').click()
                        page.locator('#v2-sens-driver').select_option('tariff')
                        page.locator('#v2-sens-scenario').select_option(sid)
                        before = get_workspace_state('decision-browser',record.project_id)
                        history = get_run_history('decision-browser',record.project_id)
                        page.locator('[data-testid=sensitivity-run-btn]').click()
                        expect(page.locator('[data-testid=sensitivity-range]')).to_be_visible(timeout=120000)
                        expect(page.locator('#v2-sensitivity-results')).to_contain_text('revenue.ppa.base_tariff = 85.0')
                        assert get_workspace_state('decision-browser',record.project_id)==before
                        assert get_run_history('decision-browser',record.project_id)==history
                        page.screenshot(path=str(out/f'{kind}-sensitivity.png'),full_page=True)
                        page.locator('#tab-scenarios').click()
                        base = page.locator('.v2-scenario-row[data-is-base-case="true"]')
                        if not base.count():
                            base = page.locator('.v2-scenario-row').filter(has=page.locator('.v2-scenario-base-badge'))
                        with page.expect_response(lambda r:'/scenarios/select' in r.url):
                            base.get_by_role('button', name='Select', exact=True).click()
                        settled(page)
                        before = get_workspace_state('decision-browser',record.project_id)
                        history = get_run_history('decision-browser',record.project_id)
                        with page.expect_response(lambda r:'/decision/goal-seek' in r.url): page.locator('#tab-goal-seek').click()
                        target = round(float(before.last_runtime_summary['project_irr']) * 100 + .25, 2)
                        page.locator('#gs-target-value').fill(str(target))
                        page.locator('[data-testid=gs-run-btn]').click()
                        expect(page.locator('[data-testid=gs-apply-btn]')).to_be_visible(timeout=180000)
                        assert get_workspace_state('decision-browser',record.project_id)==before
                        assert get_run_history('decision-browser',record.project_id)==history
                        page.screenshot(path=str(out/f'{kind}-tender.png'),full_page=True)
                        page.locator('[data-testid=gs-apply-btn]').click()
                        expect(page.locator('[data-testid=gs-applied-note]')).to_be_visible(timeout=60000)
                        settled(page)
                        assert get_workspace_state('decision-browser',record.project_id).dirty
                        with page.expect_response(lambda r:'/v2/workbook/run' in r.url and r.request.method=='POST', timeout=120000) as final_run:
                            page.locator('[data-testid=header-run-btn]').click()
                        assert 'id="v2-sheet-returns"' in final_run.value.text()
                        page.reload()
                        expect(page.locator('[data-testid=revenue-state-clean]')).to_be_attached(timeout=120000)
                        assert not get_workspace_state('decision-browser',record.project_id).dirty
                        achieved = float(get_workspace_state('decision-browser',record.project_id).last_runtime_summary['project_irr']) * 100
                        assert abs(achieved - target) < .01, (achieved, target)
                        page.reload()
                        evidence.append({'kind':kind,'workflow':'Curve Save/reload -> Run -> Scenario override/select/Run -> Compare -> Sensitivity -> Goal Seek -> Apply STALE -> Run CURRENT',
                                         'target_percent':target, 'achieved_percent':achieved, 'scenario_economics':economics,
                                         'applied_tariff':get_workspace_state('decision-browser',record.project_id).draft_snapshot['rev_ppa_base_tariff']})
                        ctx.close()
                finally:
                    browser.close()
            filename = 'journey-acceptance.json' if os.environ.get('FINCO_DECISION_JOURNEY_ONLY') else 'acceptance.json'
            (out/filename).write_text(json.dumps(evidence,indent=2),encoding='utf-8')
            print(f'{len(evidence)} browser checks passed; evidence: {out}')
        finally:
            if server: server.should_exit=True
            if thread:
                thread.join(10)
                assert not thread.is_alive()
            reset_model_executor_for_tests()
            db.DB_PATH=original


if __name__=='__main__':
    main()
