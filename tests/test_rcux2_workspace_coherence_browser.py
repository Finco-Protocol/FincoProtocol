"""UX-010 / UX-011 / UX-016: one status presentation, non-overlapping Inputs navigation, compact OPEX headings (real Chromium, real CSP)."""
from __future__ import annotations

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")

from tests.test_rcux2_construction_timing_browser import Timing  # noqa: E402
from tests.test_rcux2_ppa_quick_add_browser import browser, live_server  # noqa: F401,E402


def _visible(page, selector):
    return page.locator(selector).count() > 0 and page.locator(selector).first.is_visible()


def test_a_current_state_is_presented_once_and_a_stale_state_is_still_fully_visible(live_server, browser):
    t = Timing(live_server, browser, "rcux2-coh-1")
    t.run()
    t.page.goto(f"{live_server}/v2/workbook?project={t.rec.project_code}&sheet=overview")
    t.page.evaluate("document.getElementById('tab-overview').click()")
    t.page.wait_for_selector("[data-testid=hybrid-run-state]")
    assert t.state() == "CURRENT"
    assert not _visible(t.page, "[data-testid=overview-state-strip]")                  # the overview strip no longer repeats CURRENT
    assert not _visible(t.page, "[data-testid=banner-current]")                        # nor does the "Outputs are current" banner
    assert _visible(t.page, "[data-testid=hybrid-run-state]") and _visible(t.page, "[data-testid=hybrid-integrity]")   # the one place that states it
    box = t.page.locator("[data-testid=hybrid-identity]").bounding_box()
    assert box is not None and box["width"] <= 2 and box["height"] <= 2               # identity is kept for assistive technology, not shown a third time
    assert "Scenario:" in t.page.locator("[data-testid=hybrid-identity]").inner_text()
    t.open()
    t.dd("start").fill("2030-02-01")
    t.save()
    assert t.state() == "STALE"
    t.page.evaluate("document.getElementById('tab-overview').click()")
    assert not _visible(t.page, "[data-testid=overview-state-strip]")                  # the earlier CURRENT strip never contradicts the STALE state shown in the strip
    t.page.goto(f"{live_server}/v2/workbook?project={t.rec.project_code}&sheet=overview")
    t.page.evaluate("document.getElementById('tab-overview').click()")
    assert _visible(t.page, "[data-testid=overview-state-strip]")                      # a re-rendered overview shows STALE fully and actionably
    assert "STALE" in t.page.locator("[data-testid=overview-state-strip]").inner_text().upper() or "Inputs changed" in t.page.locator("[data-testid=overview-state-strip]").inner_text()
    assert t.errors == [], t.errors
    t.close()


def test_the_inputs_navigation_labels_no_longer_overlap(live_server, browser):
    t = Timing(live_server, browser, "rcux2-coh-2")
    labels = t.page.evaluate("Array.from(document.querySelectorAll('[data-nav-tab]')).map(e => e.textContent.trim())")
    for wanted in ("Assumptions grid", "Project setup", "Inputs summary"):
        assert wanted in labels, labels
    for old in ("All assumptions", "Project & Technical", "Technical assumptions"):
        assert old not in labels, labels
    for wanted in ("Assumptions grid", "Project setup", "Inputs summary"):
        assert labels.count(wanted) == 1, (wanted, labels)                             # each idea has exactly one entry
    for tab in ("tab-input-grid", "tab-project-setup", "tab-inputs"):                  # deep links and tab ids are unchanged
        t.page.evaluate(f"location.hash = '{tab.replace('tab-', '#')}'")
        t.page.wait_for_function("(id) => document.getElementById(id).getAttribute('aria-selected') === 'true'", arg=tab)
    t.close()


def test_opex_headings_are_compact_and_do_not_repeat_the_projection_title(live_server, browser):
    t = Timing(live_server, browser, "rcux2-coh-3")
    t.page.evaluate("document.getElementById('tab-opex').click()")
    t.page.wait_for_selector("#v2-sheet-opex .v2-sheet-section-heading")
    style = t.page.locator("#v2-sheet-opex .v2-sheet-section-heading").first.evaluate("e => { const c = getComputedStyle(e); return {d: c.display, g: c.columnGap}; }")
    assert style["d"] == "flex" and style["g"] != "0px"                                # title and subtitle no longer run together
    bare = t.page.evaluate("Array.from(document.querySelectorAll('#v2-sheet-opex .v2-sheet-section-heading > span')).map(e => e.textContent.trim())")
    assert "Year Projection" not in bare                                              # the toggle below already carries that title
    assert t.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    t.close()
