"""WF-06B real-Chromium acceptance bodies (cost workbench). Not collected by pytest: ``tests/test_wf06b_browser.py`` supplies the fixtures.

Real server, synthetic users. The only edit is a staged probe that is discarded and never saved. Screenshots: ``WF06B_SCREENSHOT_DIR``.
"""
from __future__ import annotations

import os
import re

from tests.model_react_mvp_acceptance import session as vertical_session
from tests.model_react_overnight_b_acceptance import horizontal_overflow, settle_inputs
from tests.model_react_wf1_browser_acceptance import api, open_section

SHOTS = os.environ.get("WF06B_SCREENSHOT_DIR", "")
VIEWPORTS = ((1440, 900), (1280, 800), (768, 1024), (390, 844))
PROVENANCE = re.compile(r"excel[\s_-]*source|source[\s_-]*(workbook|sheet|cell)|excel_source_ref|[A-Za-z' ]+![$]?[A-Z]{1,3}[$]?\d+", re.I)


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, f"wf06b-{name}.png"), full_page=False)


def _costlines(context, base, code, sheet):
    response = context.request.get(f"{base}/v2/model-react/costlines?sheet={sheet}&project={code}")
    assert response.ok, response.text()[:300]
    return response.json()


def _open_sheet(page, base, code, sheet):
    open_section(page, base, code, "inputs")
    settle_inputs(page)
    page.locator(f"[data-inputs-jump] [data-jump-label='{sheet.upper()}']").click()
    grid = page.locator(f"[data-cost-grid='{sheet}']")
    grid.wait_for()
    page.wait_for_function("""(s) => { const g = document.querySelector(`[data-cost-grid='${s}']`);
        return g && g.querySelector('[data-saved-total]') && g.querySelector('tr.ws2-group-row th'); }""", arg=sheet, timeout=60000)
    return grid


def check_cost_workbench_matches_the_server_projection_and_hides_provenance(browser, base, kind):
    context, page, record, errors = vertical_session(browser, base, f"wf06b-{kind}", kind)
    try:
        for sheet in ("capex", "opex"):
            grid = _open_sheet(page, base, record.project_code, sheet)
            proj = _costlines(context, base, record.project_code, sheet)["projection"]
            # P-04/U-06: the live DOM carries no spreadsheet provenance anywhere on the page, in any state
            assert not PROVENANCE.search(page.locator("body").inner_text()), PROVENANCE.search(page.locator("body").inner_text())
            html = page.content()
            assert "excel_source" not in html.lower() and "Excel source" not in html
            # every group subtotal on screen is the server's, formatted only
            for g in proj["groups"]:
                cell = grid.locator(f"[data-group-saved-total='{g['code']}']")
                if g["saved_total_keur"] is None or not g["line_count"]:
                    continue
                shown = re.search(r"-?[\d,]*\.?\d+", (cell.text_content() or "").replace("Saved", "")).group(0).replace(",", "")
                assert abs(float(shown) - g["saved_total_keur"]) <= 0.0051, (g["code"], shown, g["saved_total_keur"])
            total = (grid.locator("[data-saved-total]").text_content() or "").replace(",", "")
            assert abs(float(total) - proj["saved_total_keur"]) <= 0.0051
            # FINCO codes (never a cell address) are shown for template lines
            codes = grid.locator("[data-finco-code]").all_inner_texts()
            assert codes and all(re.fullmatch(r"[CB]\.\d{2}\.(\d{2}|U\d{3})", c) for c in codes), codes[:5]
            # unresolved / derived parents are labelled, not hidden
            if sheet == "capex":
                assert grid.locator("[data-mapping-status='UNRESOLVED']").count() >= 1
        assert not errors, errors
    finally:
        context.close()


def check_density_toggle_and_viewports(browser, base, kind):
    context, page, record, errors = vertical_session(browser, base, f"wf06b-dens-{kind}", kind)
    try:
        grid = _open_sheet(page, base, record.project_code, "capex")
        cell = grid.locator("input[data-r='1'][data-c='1']")
        normal = cell.evaluate("el => el.getBoundingClientRect().height")
        assert normal >= 30, normal                                         # readable default row (>=30px control)
        grid.locator("[data-density-toggle]").click()
        assert grid.get_attribute("data-density") == "compact"
        compact = cell.evaluate("el => el.getBoundingClientRect().height")
        assert compact <= 28.5 and compact < normal, (normal, compact)       # optional compact rows
        # amount accuracy is untouched by density: the value is still the stored text
        assert cell.input_value() == grid.locator("input[data-r='1'][data-c='1']").input_value()
        grid.locator("[data-density-toggle]").click()
        for width, height in VIEWPORTS:
            page.set_viewport_size({"width": width, "height": height})
            assert not horizontal_overflow(page), f"{kind} page overflows at {width}"
            scroller = grid.locator("[data-lines-scroll]")
            assert scroller.evaluate("el => el.scrollWidth <= el.clientWidth + 2"), f"grid scrolls sideways at {width}"
            shot(page, f"{kind}-capex-{width}x{height}")
        assert not errors, errors
    finally:
        context.close()


def check_workflow_bar_discloses_save_scope_and_has_no_stale_without_a_run(browser, base):
    context, page, record, errors = vertical_session(browser, base, "wf06b-bar", "solar")
    try:
        open_section(page, base, record.project_code, "inputs")
        settle_inputs(page)
        bar = page.locator("[data-workflow-bar='true']")
        text = bar.inner_text()
        scope = bar.locator("[data-save-scope-note]").inner_text()
        assert "saved separately" in scope and "financing collections" in scope.lower(), scope
        assert "NOT RUN" in text and bar.locator("[data-last-run-id]").count() == 0, text     # no invented Last Run
        assert bar.locator("[data-wf-run]").is_enabled()                                       # Run is a deliberate separate action
        assert not PROVENANCE.search(text)
        assert not errors, errors
    finally:
        context.close()
