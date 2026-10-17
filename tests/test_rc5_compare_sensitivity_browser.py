"""RC-5A / Workstream B browser acceptance (real Chromium, real CSP): truthful Run Compare and the explicit contracted-sensitivity refusal."""
from __future__ import annotations

import re

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")

from tests.test_rcux2_ppa_quick_add_browser import Session, browser, live_server  # noqa: F401,E402
from tests.test_rcux2_run_history_browser import _no_document_overflow, _open_history, _two_runs  # noqa: E402

SAVED = re.compile(r"^Saved Working Copy")


def test_run_compare_states_the_convention_signs_every_delta_and_never_claims_no_differences(live_server, browser):
    t = _two_runs(live_server, browser, "rc5-cmp-1")
    page = t.page
    for width, height in ((1440, 900), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        _open_history(t)
        page.locator("[data-testid=run-history-compare-expanded-2]").click()
        page.locator("[data-testid=ds-delta-convention]").wait_for()
        assert "Δ = Selected Run (B) − Reference Run (A)" in page.locator("[data-testid=ds-delta-convention]").inner_text()
        assert "Reference (Run A)" in page.locator("[data-testid=ds-reference-name]").inner_text()
        assert "Selected (Run B)" in page.locator("[data-testid=ds-selected-name]").inner_text()
        attribution = page.locator("[data-testid=ds-attribution]")
        assert attribution.get_attribute("data-status") in ("DIFFERENT_UNEXPLAINED", "DIFFERENT_EXPLAINED")   # two different committed identities
        body = page.locator("[data-testid=run-compare-expanded]").inner_text()
        assert "No assumption differences" not in body and "iterative solve" not in body
        if attribution.get_attribute("data-status") == "DIFFERENT_UNEXPLAINED":
            assert "Detailed historical attribution is unavailable." in attribution.inner_text()
        rows = page.locator("tr[data-direction]")
        checked = 0
        for i in range(rows.count()):
            direction = rows.nth(i).get_attribute("data-direction")
            delta = rows.nth(i).locator("td").nth(3).inner_text().strip()
            if direction == "up":
                assert delta.startswith("+"), delta                                                         # the direction is never hidden
                checked += 1
            elif direction == "down":
                assert delta.startswith("-"), delta
                checked += 1
            elif direction == "flat":
                assert not delta.startswith(("+", "-")), delta
        assert checked, "the two Runs differ, so at least one signed delta must be visible"
        assert _no_document_overflow(page), width
        page.locator("[data-testid=ds-back-to-history]").click()
        page.locator("[data-testid=run-history-table]").wait_for()
    assert t.errors == [], t.errors
    t.close()


def test_sensitivity_on_a_contracted_project_is_refused_visibly_and_shows_no_flat_table(live_server, browser):
    s = Session(live_server, browser, "rc5-sens-1")
    page = s.page
    page.evaluate("document.getElementById('tab-revenue').click()")
    page.locator("[data-testid=ppa-quick-add]").scroll_into_view_if_needed()
    s.fill(price="60", share="50", ref="REF-SENS")
    s.use_full_window()
    s.add()
    page.locator("[data-revenue-save]").click()
    page.locator("[data-revenue-feedback]").filter(has_text=SAVED).wait_for()
    page.evaluate("document.getElementById('tab-sensitivity').click()")
    page.locator("#v2-sens-driver").select_option("tariff")
    with page.expect_response(lambda r: r.url.endswith("/scenarios/sensitivity/run")) as done:
        page.locator("[data-testid=sensitivity-run-btn]").click()
    assert done.value.status == 200 and done.value.headers.get("x-finco-sensitivity-outcome") == "REFUSED"
    refusal = page.locator("[data-testid=sensitivity-refused]")
    refusal.wait_for()
    text = refusal.inner_text()
    assert "Sensitivity not run." in text and "explicit revenue contracts" in text and "contracted prices" in text
    assert refusal.get_attribute("role") == "alert"                                                      # announced, not silent
    results = page.locator("#v2-sensitivity-results")
    assert "+20%" not in results.inner_text() and "-20%" not in results.inner_text()                  # no apparently successful five-point table
    assert s.errors == [], s.errors
    s.close()
