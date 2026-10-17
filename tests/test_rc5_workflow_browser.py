"""RC-5C real Chromium acceptance on disposable local projects."""
import copy
from io import BytesIO
import os
import re
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")
from playwright.sync_api import expect
from tests.test_rcux2_ppa_quick_add_browser import Session, browser, live_server, _run, SAVED
from tests.model_workspace_navigation import activate_destination


def _shot(page, name):
    if os.environ.get("RC5_SCREENSHOT_DIR"):
        root = Path(os.environ["RC5_SCREENSHOT_DIR"])
        root.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(root / (name + ".png")))


@pytest.mark.parametrize("template", ["generic_solar_reference", "generic_wind_reference"])
def test_quick_add_requires_an_explicit_valid_term(live_server, browser, template):
    s = Session(live_server, browser, "rc5-term-" + template, template=template)
    try:
        activate_destination(s.page, "tab-revenue")
        assert s.dd("duration").input_value() == ""
        assert s.dd("end").input_value() == ""
        expect(s.page.locator('[data-testid=ppa-term-required]')).to_be_visible()
        s.fill(price="62.5", share="100", ref="TEST-TERM")
        s.add()
        expect(s.page.locator('[data-quick-error]')).to_be_visible()
        assert s.page.locator('[data-revenue-row]').count() == 0
        s.use_full_window()
        s.add()
        expect(s.page.locator('[data-quick-error]')).to_be_hidden()
        s.page.locator('[data-revenue-save]').click()
        expect(s.page.locator('[data-revenue-feedback]')).to_have_text(SAVED)
        assert s.saved_book()["streams"][0]["end_date"] == s.window_end()
        assert s.errors == []
    finally:
        s.close()


@pytest.mark.parametrize("mobile", [False, True])
def test_hidden_required_field_identified_focused_and_draft_preserved(live_server, browser, mobile):
    from app.persistence.workspace_repository import get_workspace_state
    s = Session(live_server, browser, "rc5-validation-" + str(mobile),
                viewport={"width": 390, "height": 844} if mobile else None,
                scheme="dark" if mobile else "light")
    try:
        if not mobile:
            _run(s)
        before = copy.deepcopy(get_workspace_state(s.uid, s.rec.project_id).last_runtime_summary)
        activate_destination(s.page, "tab-revenue")
        s.fill(price="62.5", share="100", ref="TEST-DRAFT")
        s.use_full_window(); s.add()
        s.page.locator('[data-revenue-advanced]').click()
        ref = s.page.locator('[data-revenue-row="0"] [data-field=source_ref]')
        ref.fill("")
        s.page.locator('[data-revenue-advanced]').click()
        count = len(s.posts_to('/v2/workbook/revenue/contracts'))
        s.page.locator('[data-revenue-save]').click()
        expect(ref).to_be_focused()
        expect(s.page.locator('[data-field-error]')).to_be_visible()
        assert "ppa-1 (row 1)" in s.page.locator('[data-field-error]').inner_text()
        assert "Declared source reference" in s.page.locator('[data-field-error]').inner_text()
        assert s.page.locator('[data-revenue-row="0"] [data-field=price_eur_mwh]').input_value() == "62.5"
        assert s.saved_book() is None
        assert len(s.posts_to('/v2/workbook/revenue/contracts')) == count
        assert get_workspace_state(s.uid, s.rec.project_id).last_runtime_summary == before
        _shot(s.page, "validation-mobile" if mobile else "validation-desktop")
        ref.fill("CORRECTED-REF")
        s.page.locator('[data-revenue-save]').click()
        expect(s.page.locator('[data-revenue-feedback]')).to_have_text(SAVED)
        assert s.saved_book()["streams"][0]["source_ref"] == "CORRECTED-REF"
        assert get_workspace_state(s.uid, s.rec.project_id).last_runtime_summary == before
        assert s.errors == []
    finally:
        s.close()


def test_wind_contingency_run_and_renamed_scenario_download(live_server, browser):
    import openpyxl
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.db import get_cursor
    s = Session(live_server, browser, "rc5-wind-export", template="generic_wind_reference")
    try:
        # Explicit synthetic 550 kEUR constant cost fixture, not a claim about default Wind costs.
        # Only this disposable project's seeded decomposition is changed, before any Run.
        with get_cursor() as cur:
            cur.execute('SELECT sub_line_id FROM opex_sub_lines WHERE project_id=? ORDER BY display_order LIMIT 1', (s.rec.project_id,))
            first = cur.fetchone()['sub_line_id']
            cur.execute('UPDATE opex_sub_lines SET amount_keur=0, inflation_pct=0 WHERE project_id=?', (s.rec.project_id,))
            cur.execute('UPDATE opex_sub_lines SET amount_keur=550 WHERE project_id=? AND sub_line_id=?', (s.rec.project_id, first))
        page = s.page
        page.reload()
        activate_destination(page, "tab-project-setup")
        field = page.locator('[data-field-id="project_setup.identity.project_name"] input[name=value]').first
        with page.expect_response(lambda r: r.url.endswith('/v2/workbook/update')) as renamed:
            field.fill("Wind Export Review"); field.press('Tab')
        assert renamed.value.status == 200
        page.reload()
        activate_destination(page, "tab-scenarios")
        page.locator('input[name=scenario_name]').first.fill("Lender Review")
        with page.expect_response(lambda r: r.url.endswith('/v2/workbook/scenarios/create')) as created:
            page.get_by_role('button', name=re.compile('Create', re.I)).first.click()
        assert created.value.status == 200
        activate_destination(page, "tab-opex")
        assert page.locator('[data-testid=opex-y1-total]').inner_text().strip() == '550'
        form = page.locator('[data-testid=opex-contingency-form]')
        with page.expect_response(lambda r: r.url.endswith('/v2/capex/contingency')) as saved:
            form.locator('[name=contingency_pct]').fill('5')
            form.locator('button[type=submit]').click()
        assert saved.value.status in (200, 303)
        page.wait_for_load_state('networkidle')
        activate_destination(page, "tab-opex")
        # Whole-kEUR display is retained; the lineage panel preserves 27.5 exactly.
        assert page.locator('[data-testid="opex-subtotal-B.13"]').inner_text().strip() == '28'
        assert '27.5' in page.locator('[data-testid=opex-contingency-authority]').inner_text()
        assert page.locator('[data-testid=opex-y1-total]').inner_text().strip() == '578'
        _shot(page, 'wind-b13-desktop')
        _run(s)
        ws = get_workspace_state(s.uid, s.rec.project_id)
        assert ws.last_runtime_identity['contingency_authority']['opex_pct'] == 5
        before = copy.deepcopy(ws.last_runtime_summary)
        history = copy.deepcopy(get_run_history(s.uid, s.rec.project_id))
        # A later Working Copy edit must not change the historical inputs exported for this Run.
        activate_destination(page, "tab-opex")
        form = page.locator('[data-testid=opex-contingency-form]')
        with page.expect_response(lambda r: r.url.endswith('/v2/capex/contingency')):
            form.locator('[name=contingency_pct]').fill('6')
            form.locator('button[type=submit]').click()
        page.wait_for_load_state('networkidle')
        with page.expect_download() as download:
            page.locator('[data-testid=v2-export-btn]').click()
        dl = download.value
        assert dl.suggested_filename.startswith('finco-Wind-Export-Review-Lender-Review-results-')
        wb = openpyxl.load_workbook(BytesIO(Path(dl.path()).read_bytes()), data_only=True)
        def rows(sheet):
            return {row[0]: row[1] for row in wb[sheet].iter_rows(values_only=True) if row[0] is not None and len(row) > 1}
        assert rows('Cover')['Project'] == 'Wind Export Review'
        assert rows('Cover')['Active project'] == s.rec.project_code
        assert rows('Run Identity')['Scenario ID'] == ws.last_runtime_scenario_id
        assert rows('Run Identity')['Scenario name'] == 'Lender Review'
        assert rows('Run Identity')['Runtime snapshot ID'] == ws.last_runtime_snapshot_id
        assert rows('Run Identity')['Project ID'] == s.rec.project_id
        assert rows('OPEX')['Contingency percent'] == 0.05
        assert rows('OPEX')['Year 1 other OPEX budget'] == 550
        assert rows('OPEX')['B.13 Year 1 contingency budget'] == 27.5
        assert rows('OPEX')['Year 1 OPEX budget including contingency'] == 577.5
        # Existing XLSX writer serializes numeric cells at 16 significant digits; no engine rounding.
        assert rows('OPEX')['Runtime total OPEX'] == float(format(before['total_opex_keur'], '.16g'))
        assert 'Values-only' in wb['Cover']['A3'].value
        assert 'clean_not_ready' not in wb['Export_Metadata']['A3'].value
        assert get_workspace_state(s.uid, s.rec.project_id).last_runtime_summary == before
        assert get_run_history(s.uid, s.rec.project_id) == history
        assert s.errors == []
    finally:
        s.close()


def test_reference_library_discloses_historical_evidence(live_server, browser):
    s = Session(live_server, browser, 'rc5-library')
    try:
        s.page.goto(live_server + '/library')
        notes = s.page.locator('[data-testid^="reference-evidence-"]')
        assert notes.count() >= 2
        assert all('Saved reference results' in note.inner_text() and 'Not recalculated' in note.inner_text()
                   for note in notes.all())
        _shot(s.page, 'reference-evidence')
    finally:
        s.close()


@pytest.fixture(scope="module", autouse=True)
def _executor_cleanup():
    yield
    from app.runtime import model_execution
    model_execution.reset_model_executor_for_tests(None)
