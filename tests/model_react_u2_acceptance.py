"""PR-U2 real-Chromium acceptance bodies (synthetic Solar / Wind only; not collected by pytest — ``tests/u2_browser_role.py`` supplies fixtures).

U2a: Import % from a pasted Excel row, the ambiguity prompt for a lone comma, the exact 100 % check gating Save (Preview still allowed), a saved
EXPLICIT profile equal to the typed digits. U2b: OPEX Years per saved line — every listed line is a saved line of the ledger, base amounts are listed
apart with Year 1 only, no business code on the surface, no horizontal page overflow at phone width. Screenshots: ``$U2_SCREENSHOT_DIR``.
"""
from __future__ import annotations

import os

from tests.model_react_mvp_acceptance import session as vertical_session
from tests.model_react_overnight_b_acceptance import horizontal_overflow
from tests.model_react_u1_acceptance import CODE, _costlines, _goto

SHOTS = os.environ.get("U2_SCREENSHOT_DIR", "")


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, f"u2-{name}.png"), full_page=False)


def _profile(context, base, code):
    r = context.request.get(f"{base}/v2/model-react/capex/profiles?project={code}", headers={"X-Finco-React-Request": "1", "Accept": "application/json"})
    assert r.ok, r.text()[:200]
    return r.json()


def check_import_percent_exact_check_and_save(browser, base, kind):
    context, page, record, errors = vertical_session(browser, base, f"u2-imp-{kind}", kind)
    try:
        _goto(page, base, record.project_code, "inputs/capex/monthly")
        page.wait_for_selector("[data-capex-studio='ready']", timeout=60000)
        key = page.locator("select[data-capex-shape]:not([disabled])").first.get_attribute("data-capex-shape")
        months = int(_profile(context, base, record.project_code)["months"])
        assert months >= 1 and key
        page.locator(f"select[data-capex-shape='{key}']").select_option("EXPLICIT")
        page.locator(f"[data-capex-import-open='{key}']").click()
        dialog = page.locator(f"[data-capex-import-dialog='{key}']")
        if months == 1:
            dialog.locator("[data-capex-import-text]").fill("100,0")                       # a lone comma is never guessed
            page.wait_for_selector("[data-capex-import-ambiguous]")
            dialog.locator("input[type=radio]").first.check()
        else:
            dialog.locator("[data-capex-import-text]").fill("12,5")
            page.wait_for_selector("[data-capex-import-ambiguous]")
            assert dialog.locator("[data-capex-import-apply]").is_disabled()
            row = ["0"] * months
            row[0], row[-1] = "12,5", "87,5"                                                # Excel row from a decimal-comma locale
            dialog.locator("[data-capex-import-text]").fill("\t".join(row))
        page.wait_for_selector("[data-capex-import-check='ok']")
        shot(page, f"{kind}-import")
        dialog.locator("[data-capex-import-apply]").click()
        page.wait_for_selector(f"[data-capex-explicit-tools='{key}'] [data-capex-explicit-check='ok']")
        assert not page.locator("[data-capex-save]").is_disabled()
        # a total that is not 100 % blocks Save but not Preview
        ta = page.locator(f"textarea[data-capex-explicit='{key}']")
        good = ta.input_value()
        ta.fill(", ".join(["10"] + ["0"] * (months - 1)))
        page.wait_for_selector(f"[data-capex-explicit-tools='{key}'] [data-capex-explicit-check='invalid']")
        assert page.locator("[data-capex-save]").is_disabled() and page.locator("[data-capex-save][data-capex-save-blocked]").count() == 1
        assert not page.locator("[data-capex-preview]").is_disabled()
        ta.fill(good)
        page.wait_for_selector(f"[data-capex-explicit-tools='{key}'] [data-capex-explicit-check='ok']")
        page.locator("[data-capex-save]").click()
        page.wait_for_selector("[data-capex-status='ok']", timeout=60000)
        saved = _profile(context, base, record.project_code)
        row = saved["saved"]["rows"][key]
        assert "12.5" in str(row) or months == 1, row
        assert not errors, errors
    finally:
        context.close()


def check_opex_lines_by_year(browser, base, kind):
    context, page, record, errors = vertical_session(browser, base, f"u2-opex-{kind}", kind)
    try:
        _goto(page, base, record.project_code, "inputs/opex/years")
        page.wait_for_selector("[data-opex-lines='ready']", timeout=60000)
        shown = set(page.locator("[data-opex-line]").evaluate_all("els => els.map(e => e.dataset.opexLine)"))
        saved = {l["sub_line_id"] for l in _costlines(context, base, record.project_code, "opex")["lines"] if l.get("active", True)}
        assert shown and shown <= saved, shown - saved
        assert page.locator("[data-opex-base]").count() == 6
        assert "the Run adds them" in page.locator("[data-opex-lines-basis]").inner_text()
        assert not CODE.search(page.locator("[data-cost-workbench]").inner_text())
        page.locator("[data-opex-lines]").scroll_into_view_if_needed()
        shot(page, f"{kind}-opex-lines")
        page.set_viewport_size({"width": 390, "height": 844})
        assert not horizontal_overflow(page)
        assert not errors, errors
    finally:
        context.close()
