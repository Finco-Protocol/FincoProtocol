"""M3 two-driver sensitivity matrix — real authenticated Chromium acceptance.

Live uvicorn server, disposable synthetic Solar working copy, real mouse/keyboard events: the form is lazy-loaded in
the Sensitivity tab, drivers / scenario / grid / metric / threshold are selected, a 3x3 matrix is run through the real
model executor and the result table is checked (numeric value + status text without relying on colour), error
messaging, scenario selection and the 390 px layout.  Skipped when Playwright or Chromium is unavailable.
"""
from __future__ import annotations

import os
import re

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")

from tests.test_cost_batch_save_browser_v1 import Session, browser, live_server  # noqa: E402,F401

SHOTS = os.environ.get("M3_SCREENSHOT_DIR")


def _open_sensitivity(s):
    s.page.goto(f"{s.base}/v2/workbook?project={s.rec.project_code}")
    s.page.wait_for_selector("#tab-sensitivity", state="attached")
    # The tab click re-renders the whole sheet (existing outerHTML refresh): wait for that swap before interacting.
    with s.page.expect_response(lambda r: "/workbook/decision/sensitivity" in r.url, timeout=30000):
        s.page.evaluate("document.getElementById('tab-sensitivity').click()")
    s.page.wait_for_selector('[data-testid="matrix-run-btn"]', state="visible", timeout=30000)
    s.page.wait_for_function("!document.querySelector('.htmx-request') && !document.querySelector('.htmx-swapping')")


def _shot(s, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        s.page.screenshot(path=os.path.join(SHOTS, name), full_page=True)


def _run_and_wait(s, timeout=240000):
    with s.page.expect_response(lambda r: "/sensitivity/matrix/run" in r.url, timeout=timeout) as info:
        s.page.locator('[data-testid="matrix-run-btn"]').click()
    return info.value


@pytest.fixture
def make(live_server, browser):
    made = []

    def _make(uid, **kw):
        s = Session(live_server, browser, uid, **kw)
        made.append(s)
        return s

    yield _make
    for s in made:
        s.close()


def test_form_selection_run_results_threshold_and_scenario(make):
    s = make("u-m3-desktop", template="generic_solar_reference")
    created = s.page.request.post(f"{s.base}/v2/workbook/scenarios/create",
                                  form={"project": s.rec.project_code, "scenario_name": "Upside"},
                                  headers={"HX-Request": "true"})
    assert created.ok
    _open_sensitivity(s)
    page = s.page
    options = page.locator('[data-testid="matrix-driver-a"] option').all_inner_texts()
    assert any("CAPEX" in o for o in options) and any("PPA" in o for o in options)
    assert not any("PUE" in o for o in options), "Data Center drivers must not be offered on a Solar project"
    metrics = page.locator('[data-testid="matrix-metric"] option').all_inner_texts()
    assert not any("CFADS" in m for m in metrics), "a metric the canonical run cannot supply is not offered"
    assert page.locator('[data-testid="matrix-grid"]').input_value() == "3"

    page.select_option('[data-testid="matrix-driver-a"]', "capex")
    page.select_option('[data-testid="matrix-driver-b"]', "tariff")
    page.select_option('[data-testid="matrix-metric"]', "equity_irr")
    scenarios = page.locator('[data-testid="matrix-scenario"] option').all_inner_texts()
    assert any("Upside" in o for o in scenarios), scenarios
    page.select_option('[data-testid="matrix-scenario"]', label=next(o for o in scenarios if "Upside" in o))
    _shot(s, "m3-form-desktop.png")

    # 1st run without a threshold: nothing is classified; the values then define a threshold that splits the grid
    assert _run_and_wait(s).status == 200
    page.wait_for_selector('[data-testid="matrix-table"]', timeout=30000)
    cells = page.locator('[data-testid="matrix-cell"]')
    assert cells.count() == 9
    assert set(cells.evaluate_all("els => els.map(e => e.dataset.threshold)")) == {"NOT_SET"}
    values = sorted(float(re.search(r"(-?\d+\.\d\d)%", t).group(1)) for t in cells.all_inner_texts())
    threshold = f"{values[4]:.2f}"                                   # the median cell value: a real split
    page.fill('[data-testid="matrix-threshold"]', threshold)
    assert _run_and_wait(s).status == 200
    page.wait_for_function("document.querySelector('[data-testid=\"matrix-threshold-summary\"]')")
    cells = page.locator('[data-testid="matrix-cell"]')
    assert cells.count() == 9
    statuses = cells.evaluate_all("els => els.map(e => e.dataset.status)")
    assert statuses == ["OK"] * 9
    flags = cells.evaluate_all("els => els.map(e => e.dataset.threshold)")
    assert set(flags) == {"PASS", "FAIL"}, flags
    texts = cells.all_inner_texts()
    assert all(re.search(r"\d+\.\d\d%", t) for t in texts), texts                           # numeric value is text
    assert all(("PASS" in t) or ("FAIL" in t) for t in texts), "status must be readable without colour"
    banner = page.locator('[data-testid="matrix-banner"]').inner_text()
    assert "Upside" in banner and "Ephemeral" in banner and "not CURRENT" in banner
    assert "Pure Equity IRR" in banner
    assert page.locator('[data-testid="matrix-brackets"]').count() == 1
    assert "no boundary value is inferred" in page.locator('[data-testid="matrix-brackets"]').inner_text()
    summary = page.locator('[data-testid="matrix-run-summary"]').inner_text()
    assert "9 canonical evaluation" in summary and "9 of 9 cells completed" in summary
    # cell inspection: keyboard-focusable with a tooltip naming BOTH shocked inputs
    first = cells.nth(0)
    first.focus()
    title = first.get_attribute("title")
    assert "CAPEX" in title and "PPA" in title
    _shot(s, "m3-result-desktop.png")
    # a single ephemeral analysis: nothing was written
    assert [p for p in s.posts if "/matrix/run" not in p and "/scenarios/create" not in p] == []
    assert s.errors == []


def test_error_messages_are_visible_and_leave_no_results(make):
    s = make("u-m3-errors", template="generic_solar_reference")
    _open_sensitivity(s)
    s.page.select_option('[data-testid="matrix-driver-a"]', "capex")
    s.page.select_option('[data-testid="matrix-driver-b"]', "capex")
    response = _run_and_wait(s, timeout=30000)
    assert response.status == 422
    err = s.page.locator('[data-testid="matrix-error"]')
    err.wait_for(state="visible")
    assert "MATRIX_DRIVER_DUPLICATE" in err.inner_text() and "Nothing was changed" in err.inner_text()
    s.page.select_option('[data-testid="matrix-driver-b"]', "opex")
    s.page.fill('[data-testid="matrix-levels-a"]', "1,2")
    response = _run_and_wait(s, timeout=30000)
    assert response.status == 422
    assert "MATRIX_LEVEL_COUNT" in s.page.locator('[data-testid="matrix-error"]').inner_text()
    assert s.page.locator('[data-testid="matrix-table"]').count() == 0
    _shot(s, "m3-error-desktop.png")


def test_narrow_viewport_390_keeps_form_and_table_usable(make):
    s = make("u-m3-mobile", template="generic_solar_reference", viewport={"width": 390, "height": 844})
    _open_sensitivity(s)
    page = s.page
    for sel in ('[data-testid="matrix-driver-a"]', '[data-testid="matrix-driver-b"]', '[data-testid="matrix-metric"]',
                '[data-testid="matrix-run-btn"]'):
        page.locator(sel).scroll_into_view_if_needed()
        box = page.locator(sel).bounding_box()
        assert box and box["x"] >= 0 and box["x"] + box["width"] <= 392, (sel, box)   # fully inside the 390 px viewport
    page.select_option('[data-testid="matrix-driver-a"]', "interest_rate")
    page.select_option('[data-testid="matrix-driver-b"]', "gearing")
    page.select_option('[data-testid="matrix-metric"]', "min_dscr")
    assert _run_and_wait(s).status == 200
    page.wait_for_selector('[data-testid="matrix-table"]', timeout=30000)
    cells = page.locator('[data-testid="matrix-cell"]')
    assert cells.count() == 9
    assert cells.evaluate_all("els => els.map(e => e.dataset.status)") == ["OK"] * 9, "-100 bps must be a valid rate shock"
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "no horizontal page scroll"
    assert page.locator('[data-testid="matrix-run-summary"]').is_visible()
    _shot(s, "m3-result-390.png")
    assert s.errors == []
