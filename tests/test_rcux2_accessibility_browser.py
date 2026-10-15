"""UX-029 / UX-009: table names and scopes, skip link and focus order, and the colour-theme control (real Chromium, real CSP)."""
from __future__ import annotations

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")

from tests.test_rcux2_construction_timing_browser import Timing  # noqa: E402
from tests.test_rcux2_ppa_quick_add_browser import browser, live_server  # noqa: F401,E402

AUDIT = """(id) => { const root = document.getElementById("panel-" + id);
  const tables = Array.from(root.querySelectorAll("table"));
  const unnamed = tables.filter(t => !t.querySelector("caption") && !t.getAttribute("aria-label") && !t.getAttribute("aria-labelledby")).length;
  const noScope = Array.from(root.querySelectorAll("thead th")).filter(h => !h.getAttribute("scope")).length;
  return {tables: tables.length, unnamed, noScope}; }"""


def test_every_table_has_an_accessible_name_and_every_header_a_scope_in_every_results_sheet(live_server, browser):
    t = Timing(live_server, browser, "rcux2-a11y-1")
    t.run()
    t.page.goto(f"{live_server}/v2/workbook?project={t.rec.project_code}")
    seen = 0
    for tab in ("overview", "outputs", "returns", "debt", "revenue", "capex", "opex", "tax", "trust", "run-history", "sensitivity", "scenarios"):
        t.page.evaluate(f"document.getElementById('tab-{tab}').click()")
        t.page.wait_for_timeout(1000)
        r = t.page.evaluate(AUDIT, tab)
        assert r["unnamed"] == 0 and r["noScope"] == 0, (tab, r)
        seen += r["tables"]
    assert seen >= 15                                                                              # the audit really looked at the financial tables
    assert t.errors == [], t.errors
    t.close()


def test_the_skip_link_is_the_first_focus_stop_and_reaches_the_main_landmark(live_server, browser):
    t = Timing(live_server, browser, "rcux2-a11y-2")
    t.page.keyboard.press("Tab")
    link = t.page.locator(".v2-skip-link")
    assert link.evaluate("e => e === document.activeElement") and link.is_visible()                  # appears on focus
    t.page.keyboard.press("Enter")
    assert t.page.evaluate("document.activeElement && document.activeElement.id") == "v2-workbook-shell"
    t.page.evaluate("document.getElementById('tab-diagnostics').click()")                       # a sheet that renders its own h1 must not add a second level-1 heading
    t.page.wait_for_timeout(1500)
    level_one = t.page.evaluate("Array.from(document.querySelectorAll('main h1, main [role=heading]')).filter(e => (e.getAttribute('aria-level') || (e.tagName === 'H1' ? '1' : '')) === '1').length")
    assert level_one == 1
    t.close()


def test_the_theme_control_cycles_applies_the_attribute_and_is_remembered(live_server, browser):
    t = Timing(live_server, browser, "rcux2-a11y-3", scheme="light")
    toggle = t.page.locator("[data-testid=theme-toggle]")
    assert toggle.inner_text() == "Theme: Auto" and t.page.evaluate("document.documentElement.getAttribute('data-theme')") is None
    light_bg = t.page.evaluate("getComputedStyle(document.body).backgroundColor")
    toggle.click(); assert toggle.inner_text() == "Theme: Light"
    toggle.click(); assert toggle.inner_text() == "Theme: Dark"
    assert t.page.evaluate("document.documentElement.getAttribute('data-theme')") == "dark"
    t.page.reload(); t.page.wait_for_selector("[data-testid=theme-toggle]")
    assert t.page.evaluate("document.documentElement.getAttribute('data-theme')") == "dark"          # remembered across a reload
    assert t.page.locator("[data-testid=theme-toggle]").inner_text() == "Theme: Dark"
    assert t.page.locator("[data-testid=theme-toggle]").get_attribute("aria-label").startswith("Colour theme: dark")
    assert t.errors == [], t.errors
    t.close()


def test_a_model_period_index_shared_by_a_construction_row_and_an_operating_row_is_labelled_by_phase(live_server, browser):
    """UX-014: two rows carried the same model period number with different dates (the construction / operations boundary of the period axis).
    The periods are distinct, so only the label changes; no index, date or amount is altered."""
    t = Timing(live_server, browser, "rcux2-a11y-4")
    t.run()
    t.page.goto(f"{live_server}/v2/workbook?project={t.rec.project_code}")
    t.page.evaluate("document.getElementById('tab-returns').click()")
    t.page.locator("[data-testid=returns-sponsor-table] tbody tr").first.wait_for()
    labels = t.page.locator("[data-testid=returns-sponsor-table] tbody tr td:first-child").all_inner_texts()
    dates = t.page.locator("[data-testid=returns-sponsor-table] tbody tr td:nth-child(2)").all_inner_texts()
    assert len(labels) == len(set(labels)), labels                                                # every row is now unambiguous
    assert any("construction" in x for x in labels) and any("operations" in x for x in labels)
    assert len(set(dates)) == len(dates)                                                          # the underlying periods really are distinct
    t.close()


def test_phone_controls_meet_the_44px_target_and_the_save_bar_stays_reachable(live_server, browser):
    """UX-030 at 390 px: primary controls are at least 44 px high, field text is 16 px, no document overflow, and the grid Save bar sits at the bottom of the viewport."""
    t = Timing(live_server, browser, "rcux2-a11y-5", viewport={"width": 390, "height": 844})
    probe = """(sel) => Array.from(document.querySelectorAll(sel)).filter(e => e.offsetParent !== null).map(e => Math.round(e.getBoundingClientRect().height))"""
    t.page.evaluate("document.getElementById('tab-revenue').click()")
    t.page.wait_for_timeout(600)
    for sel in ("[data-quick-add]", "[data-revenue-save]", ".v2-run-btn", "[data-testid=theme-toggle]"):
        heights = t.page.evaluate(probe, sel)
        assert heights and min(heights) >= 44, (sel, heights)
    assert t.page.evaluate("getComputedStyle(document.querySelector('[data-quick=\"price\"]')).fontSize") == "16px"
    t.page.evaluate("document.getElementById('tab-project-setup').click()")
    t.page.wait_for_timeout(600)
    assert min(t.page.evaluate(probe, "[data-ct-save]")) >= 44
    t.page.evaluate("document.getElementById('tab-input-grid').click()")
    t.page.wait_for_selector(".ig-bar")
    bar = t.page.locator(".ig-bar").first
    box = bar.bounding_box()
    assert box is not None and abs((box["y"] + box["height"]) - 844) <= 2, box                        # pinned to the bottom of the phone viewport
    assert t.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    assert t.errors == [], t.errors
    t.close()
