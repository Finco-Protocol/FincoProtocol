"""WF-06B real-Chromium acceptance bodies (cost workbench). Not collected by pytest: ``tests/wf06b_browser_role.py`` supplies the fixtures.

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


# ── Correction C: Compact Inputs, truthful overview, navigation and accessibility ───────────────────────────────

def _statements(context, base, code):
    response = context.request.get(f"{base}/v2/model-react/statements?project={code}")
    assert response.ok, response.text()[:300]
    return response.json()


def _inputs(page, base, code):
    open_section(page, base, code, "inputs")
    settle_inputs(page)
    page.wait_for_selector("[data-inputs-overview='true']", timeout=30000)
    page.wait_for_function("() => document.querySelector('[data-ci-capex]') && document.querySelector('[data-ci-capex]').dataset.ciCapex !== 'unavailable'", timeout=30000)


def check_compact_inputs_overview_is_server_owned_and_two_column(browser, base, kind):
    context, page, record, errors = vertical_session(browser, base, f"wf06b-ci-{kind}", kind)
    try:
        _inputs(page, base, record.project_code)
        capex = _costlines(context, base, record.project_code, "capex")["projection"]["saved_total_keur"]
        opex = _costlines(context, base, record.project_code, "opex")["projection"]["saved_total_keur"]
        ov = page.locator("[data-inputs-overview='true']")
        assert abs(float(ov.locator("[data-ci-capex]").get_attribute("data-ci-capex")) - capex) < 1e-6
        assert abs(float(ov.locator("[data-ci-opex]").get_attribute("data-ci-opex")) - opex) < 1e-6
        # no committed Run yet: no invented KPI, the empty state is explicit
        assert ov.locator("[data-ci-norun]").count() == 1 and ov.locator("[data-ci-metric]").count() == 0
        assert "not a model result" in ov.inner_text()
        # two columns on desktop: overview columns and Inputs sections sit side by side
        cols = ov.locator("[data-ci-col]")
        a, b = cols.nth(0).bounding_box(), cols.nth(1).bounding_box()
        assert abs(a["y"] - b["y"]) < 4 and b["x"] > a["x"] + a["width"] - 2, (a, b)
        sections = page.locator("[data-ci-sections] > details")
        assert sections.count() >= 2
        s0, s1 = sections.nth(0).bounding_box(), sections.nth(1).bounding_box()
        assert abs(s0["y"] - s1["y"]) < 4 and s1["x"] > s0["x"], (s0, s1)
        # the default 'Editable' chip is not repeated on every row (word kept for assistive technology only)
        assert page.locator(".rx-input-table .rx-state-editable").count() == 0
        assert page.locator(".rx-input-table .rx-state-editable-sr").count() > 0
        # 14px text; 32px controls (27px when compact)
        grid = page.locator("[data-input-grid='canonical']")
        assert grid.evaluate("el => getComputedStyle(el).fontSize") == "14px"
        cell = grid.locator("input.rx-grid-input").first
        assert cell.evaluate("el => el.getBoundingClientRect().height") >= 31.5
        grid.locator("[data-density-toggle]").click()
        assert cell.evaluate("el => el.getBoundingClientRect().height") <= 28.5
        grid.locator("[data-density-toggle]").click()
        # single column and no overflow at the remaining widths
        for width, height in VIEWPORTS + ((320, 700),):
            page.set_viewport_size({"width": width, "height": height})
            assert not horizontal_overflow(page), f"{kind} inputs overflow at {width}"
            if width <= 900:
                a, b = cols.nth(0).bounding_box(), cols.nth(1).bounding_box()
                assert b["y"] > a["y"] + a["height"] - 2, f"overview must stack at {width}"
            if width < 1100:
                s0, s1 = sections.nth(0).bounding_box(), sections.nth(1).bounding_box()
                assert s1["y"] > s0["y"], f"sections must stack at {width}"
            shot(page, f"{kind}-inputs-{width}x{height}")
        assert not errors, errors
    finally:
        context.close()


def check_overview_shows_only_the_committed_run_and_marks_stale(browser, base):
    from tests.model_react_wf1_browser_acceptance import run_canonical
    context, page, record, errors = vertical_session(browser, base, "wf06b-ci-run", "solar")
    try:
        run_canonical(context, base, record.project_code)
        _inputs(page, base, record.project_code)
        stm = _statements(context, base, record.project_code)
        server = {m["label"]: m for m in stm["results"]["metrics"]}
        dscr = next(m for m in stm["results"]["lender_metrics"] if m["key"] == "min_dscr")
        ov = page.locator("[data-inputs-overview='true']")
        page.wait_for_selector("[data-ci-metric='project-irr']", timeout=30000)
        assert ov.locator("[data-ci-metric='project-irr']").inner_text() == server["Project IRR"]["display"]
        assert ov.locator("[data-ci-metric='sponsor-irr']").inner_text() == server["Total Sponsor IRR"]["display"]
        assert ov.locator("[data-ci-metric='min-dscr']").inner_text() == dscr["display"]          # the server's own text, never recomputed
        assert "Pure Equity" not in ov.inner_text()                                                # demoted from the headline
        assert "xx" not in ov.inner_text().replace(" ", "")
        run_id = ov.locator("[data-ci-run-id]").get_attribute("data-ci-run-id")
        assert run_id == stm["status"]["runId"]
        before = ov.locator("[data-ci-metric='project-irr']").inner_text()
        # a STAGED edit never moves a committed figure and is counted separately
        cell = page.locator("[data-input-grid='canonical'] input.rx-grid-input:not([readonly])").first
        original = cell.input_value()
        cell.fill(original + "1" if original else "1")
        page.wait_for_function("() => Number(document.querySelector('[data-ci-staged]')?.dataset.ciStaged) > 0", timeout=10000)
        # the overview reports exactly the number the workflow bar reports (one shared source), never its own count
        assert ov.locator("[data-ci-staged]").get_attribute("data-ci-staged") == page.locator("[data-workflow-bar='true']").get_attribute("data-unsaved")
        assert ov.locator("[data-ci-metric='project-irr']").inner_text() == before
        page.locator("[data-discard='true']").first.click()
        page.wait_for_function("() => document.querySelector('[data-ci-staged]')?.dataset.ciStaged === '0'", timeout=10000)
        assert not errors, errors
    finally:
        context.close()


def check_back_forward_keeps_staged_text_and_never_crosses_projects(browser, base):
    context, page, record, errors = vertical_session(browser, base, "wf06b-nav", "solar")
    try:
        _inputs(page, base, record.project_code)
        cell = page.locator("[data-input-grid='canonical'] input.rx-grid-input:not([readonly])").first
        field = cell.get_attribute("data-grid-cell")
        original = cell.input_value()
        staged = original + "7" if original else "7"
        cell.fill(staged)
        page.locator("[data-inputs-jump] [data-jump-label='CAPEX']").click()
        page.wait_for_selector("[data-cost-grid='capex']", timeout=30000)
        page.go_back()
        page.wait_for_selector(f"[data-grid-cell='{field}']", timeout=30000)
        assert page.locator(f"[data-grid-cell='{field}']").input_value() == staged, "staged text must survive Back"
        assert page.locator("[data-unsaved-indicator]").count() == 1
        page.go_forward()
        page.wait_for_selector("[data-cost-grid='capex']", timeout=30000)
        page.go_back()
        page.wait_for_selector(f"[data-grid-cell='{field}']", timeout=30000)
        assert page.locator(f"[data-grid-cell='{field}']").input_value() == staged
        # nothing was written: the server value is unchanged
        grid = context.request.get(f"{base}/v2/model-react/inputs?project={record.project_code}").json()
        rows = [r for s in grid["grid"]["sections"] for c in s["categories"] for r in c["rows"] if (r["field_id"] or r["code"]) == field]
        assert rows and rows[0]["value"] == original
        # no project value in browser storage
        store = page.evaluate("() => JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)])")
        assert staged not in store.replace(f'"{original}"', "") or staged == original
        assert not errors, errors
    finally:
        context.close()


def check_keyboard_focus_and_live_status(browser, base):
    context, page, record, errors = vertical_session(browser, base, "wf06b-a11y", "solar")
    try:
        _inputs(page, base, record.project_code)
        status = page.locator("#rx-grid-status")
        assert status.get_attribute("role") == "status" and status.get_attribute("aria-live") == "polite"
        cell = page.locator("[data-input-grid='canonical'] input.rx-grid-input:not([readonly])").first
        assert (cell.get_attribute("aria-label") or "").strip(), "every editable cell has an accessible name"
        cell.focus()
        outline = cell.evaluate("el => { const s = getComputedStyle(el); return [s.outlineStyle, parseFloat(s.outlineWidth)]; }")
        assert outline[0] != "none" and outline[1] >= 2, outline                                  # visible focus ring
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement !== document.body")
        grid_buttons = page.locator("[data-input-grid] button")
        for i in range(grid_buttons.count()):
            box = grid_buttons.nth(i).bounding_box()
            assert box is None or box["height"] >= 24, box
        assert not errors, errors
    finally:
        context.close()


def check_axe_has_no_serious_or_critical_violations(browser, base, axe_path):
    """Local/accessibility-role evidence: injects axe-core from ``axe_path`` (a developer-supplied file; not committed)."""
    context, page, record, errors = vertical_session(browser, base, "wf06b-axe", "solar")
    try:
        results = {}
        for name, setup in (("inputs", lambda: _inputs(page, base, record.project_code)),):
            setup()
            page.add_script_tag(path=axe_path)
            out = page.evaluate("async () => (await axe.run(document, {runOnly: ['wcag2a', 'wcag2aa']})).violations.map(v => ({id: v.id, impact: v.impact, n: v.nodes.length}))")
            results[name] = [v for v in out if v["impact"] in ("serious", "critical")]
        assert not any(results.values()), results
    finally:
        context.close()
