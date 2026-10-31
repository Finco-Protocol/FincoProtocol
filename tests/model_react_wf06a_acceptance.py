"""WF-06A Correction A — real-Chromium acceptance bodies (Save All guide, Run failure notice, cost-line groups, DSCR units).

Not collected by pytest. Executed through the existing live-server and browser fixtures. Read-only except the intentional staged-edit probe,
which is discarded and never saved. Screenshots go to ``WF06A_SCREENSHOT_DIR`` when set.
"""
from __future__ import annotations

import json
import os

from tests.model_react_mvp_acceptance import session as vertical_session
from tests.model_react_overnight_b_acceptance import horizontal_overflow, settle_inputs
from tests.model_react_wf1_browser_acceptance import api, open_section, run_canonical

SHOTS = os.environ.get("WF06A_SCREENSHOT_DIR", "")
WIDTHS = (1440, 1280, 768, 390, 320)


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, f"wf06a-{name}.png"), full_page=True)


def shot_element(locator, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        locator.screenshot(path=os.path.join(SHOTS, f"wf06a-{name}.png"))


def check_save_scope_guide_matches_server_capability(browser, base):
    context, page, record, errors = vertical_session(browser, base, "wf06a-guide", "solar")
    try:
        capability = api(context, base, "workspace", record.project_code).get("save_all") or {}
        assert capability.get("available") is True and set(capability.get("sections", [])) == {"cells", "contracts", "cost_lines"}
        assert capability.get("excluded") == ["debt.financing.instruments"]
        open_section(page, base, record.project_code, "inputs")
        settle_inputs(page)
        guide = page.locator("[data-save-scope-guide]")
        guide.locator("summary").click()
        text = guide.inner_text()
        assert "there is no global Save" not in text.lower() and "saves on its own" not in text.lower()
        for required in ("Save All", "only when the server enables it", "CAPEX and OPEX lines", "PPA contract changes",
                         "Financing collections", "refused as a whole", "Nothing saves automatically", "no Save runs the model"):
            assert required in text, required
        assert guide.locator("[data-save-all-row]").count() == 1
        run_row = guide.locator("[data-run-scope-row]").inner_text()
        assert "working draft" in run_row and "Last Run" in run_row and "unsaved in an editor is not used" in run_row, run_row
        assert "already saved" not in run_row
        shot(page, "guide-1440")
        for width in WIDTHS:
            page.set_viewport_size({"width": width, "height": 900})
            assert not horizontal_overflow(page), f"guide overflows at {width}"
        assert not errors, errors
    finally:
        context.close()


def check_cost_lines_show_group_context_without_changing_keyboard_or_layout(browser, base, kind):
    context, page, record, errors = vertical_session(browser, base, f"wf06a-cost-{kind}", kind)
    try:
        open_section(page, base, record.project_code, "inputs")
        settle_inputs(page)
        for sheet in ("CAPEX", "OPEX"):
            page.locator(f"[data-inputs-jump] [data-jump-label='{sheet}']").click()
            grid = page.locator(f"[data-cost-grid='{sheet.lower()}']")
            grid.wait_for()
            # the sheet switch briefly keeps the previous sheet's lines: wait for the sheet's own columns and its first group heading
            page.wait_for_function("""(sheet) => { const g = document.querySelector(`[data-cost-grid='${sheet}']`); const first = g && g.querySelector('tr.ws2-group-row th');
                return first && first.textContent.startsWith(sheet === 'capex' ? 'C.' : 'B.') && (sheet === 'capex' || /Inflation/.test(g.textContent)); }""", arg=sheet.lower())
            groups = grid.locator("tr.ws2-group-row")
            assert groups.count() >= 3, (kind, sheet, groups.count(), grid.locator("tr").count())
            first_group = groups.first.inner_text()
            assert first_group.startswith("C.01" if sheet == "CAPEX" else "B.01"), first_group
            assert "undefined" not in grid.inner_text() and "null" not in grid.inner_text()
            # no bare calculated-group code is shown anywhere in the sheet
            for row in grid.locator("tr.ws2-group-row th").all_inner_texts():
                assert " " in row.strip(), f"bare group code: {row!r}"
            # first data row follows its group heading and keeps its accessible name and units
            inputs = grid.locator("input[data-r][data-c]")
            first_input = inputs.first
            assert (first_input.get_attribute("aria-label") or "").startswith("Label for ")
            assert "Amount (kEUR)" in grid.locator("table.ws2-grid thead").text_content()
            # keyboard: Tab to the amount cell, Enter moves to the same column of the next row (group headings are skipped)
            first_input.focus(); page.keyboard.press("Tab")
            assert page.evaluate("document.activeElement.dataset.c") == "1"
            page.keyboard.press("Enter")
            assert page.evaluate("document.activeElement.dataset.r") == "1", "Enter must move to the next line, not to a group heading"
            # staged edit survives, is flagged, and is discarded again (never saved)
            amount = grid.locator("input[data-r='1'][data-c='1']")
            if amount.is_enabled():
                original = amount.input_value()
                amount.fill("123.45")
                assert amount.get_attribute("data-changed") == "true"
                grid.get_by_role("button", name="Discard staged edits").click()
                assert grid.locator("input[data-r='1'][data-c='1']").input_value() == original
            for width in WIDTHS:
                page.set_viewport_size({"width": width, "height": 1000})
                assert not horizontal_overflow(page), f"{kind} {sheet} page overflows at {width}"
                scroller = grid.locator("[data-lines-scroll]")
                # density: label and amount (and OPEX inflation) fit the scroll box without sideways scrolling at every width
                assert scroller.evaluate("el => el.scrollWidth <= el.clientWidth + 2"), f"{kind} {sheet} grid scrolls sideways at {width}"
                shot_element(grid, f"{kind}-{sheet.lower()}-{width}")
            page.set_viewport_size({"width": 1440, "height": 1000})
        assert not errors, errors
    finally:
        context.close()


def check_run_failure_notice_is_classified_and_never_offers_blind_retry(browser, base):
    context, page, record, errors = vertical_session(browser, base, "wf06a-fail", "wind")
    try:
        open_section(page, base, record.project_code, "inputs")
        settle_inputs(page)
        scenarios = (
            ("FINANCIAL_REFUSED", "The shareholder loan still has an unpaid balance at maturity. No result was committed.", "SHL", "false"),
            ("ADMISSION_REFUSED", "Calculation capacity is currently busy. Nothing was run or saved. Please run again shortly.", "TRANSIENT", "true"),
            ("ENGINE_FAILED", "Base cash cannot pay the contractual Senior service, including maturity principal. (Reference: F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL)", "FINANCING", "false"),
        )
        for code, message, kind, retryable in scenarios:
            body = json.dumps({"ok": False, "outcome": "FAILED", "error_code": code, "message": message})

            def handler(route, request, body=body):
                route.fulfill(status=409, content_type="application/json", body=body)
            page.route("**/v2/workbook/run", handler)
            page.locator("[data-wf-run]").click()
            page.wait_for_selector("[data-run-failure]")
            notice = page.locator("[data-run-failure]")
            assert notice.get_attribute("data-run-failure-kind") == kind, (code, notice.get_attribute("data-run-failure-kind"))
            assert notice.get_attribute("data-run-failure-retryable") == retryable
            guidance = notice.locator("[data-run-failure-guidance]").inner_text()
            assert ("safe to choose Run model again" in guidance) == (retryable == "true"), guidance
            for href in notice.locator("[data-run-failure-links] a").evaluate_all("els => els.map(e => e.getAttribute('href'))"):
                assert href in ("#inputs", "#inputs/project", "#financing", "#diagnostics"), href
            assert notice.locator("[role=alert]").count() >= 1
            shot(page, f"run-failure-{kind.lower()}")
            page.unroute("**/v2/workbook/run", handler)
            page.reload(); settle_inputs(page)
        assert not [e for e in errors if "409" not in e], errors
    finally:
        context.close()


def check_overview_dscr_and_ratios_never_carry_a_money_unit(browser, base):
    context, page, record, errors = vertical_session(browser, base, "wf06a-dscr", "solar")
    try:
        run_canonical(context, base, record.project_code)
        open_section(page, base, record.project_code, "overview")
        page.wait_for_selector("[data-financial-overview]")
        page.wait_for_selector(".wsv2-return-facts")
        facts = page.locator(".wsv2-return-facts > div")
        seen = {}
        for i in range(facts.count()):
            label = facts.nth(i).locator("dt").inner_text(); value = facts.nth(i).locator("dd").inner_text()
            seen[label] = value
            if "DSCR" in label.upper() or "IRR" in label.upper() or "MOIC" in label.upper():
                assert "EUR" not in value, (label, value)
            if "DSCR" in label.upper() and value != "Unavailable":
                assert value.endswith("x"), (label, value)
            if "IRR" in label.upper() and value != "Unavailable":
                assert value.endswith("%"), (label, value)
        chart = page.locator("[data-chart='dscr']")
        if chart.get_attribute("data-chart-state") == "available":
            head = chart.locator(".rx-live-card-head").inner_text()
            assert head.rstrip().endswith("· x") and "EUR" not in head, head
            assert "EUR" not in (chart.locator("svg").get_attribute("aria-label") or "")
        shot(page, "overview-dscr")
        assert seen, "no return facts rendered"
        assert not errors, errors
    finally:
        context.close()
