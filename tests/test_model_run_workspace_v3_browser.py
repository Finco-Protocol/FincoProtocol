"""V3 Run Workspace: Chromium HTMX navigation, accessible controls and mobile containment."""
from __future__ import annotations

import pytest

pytest.importorskip("playwright", reason="browser support not installed")

from playwright.sync_api import expect  # noqa: E402

from tests.test_rcux2_run_history_browser import (  # noqa: E402
    _no_document_overflow, _open_history, _two_runs,
)
from tests.test_rcux2_ppa_quick_add_browser import browser, live_server  # noqa: F401,E402


@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_run_workspace_three_slot_selector_and_return_navigation(live_server, browser, width, height):
    t = _two_runs(live_server, browser, "rw-v3-%s" % width)
    t.page.set_viewport_size({"width": width, "height": height})
    _open_history(t)
    t.page.locator('[data-testid="run-history-workspace-v3"]').click()
    t.page.locator('[data-testid="run-workspace-v3"]').wait_for()
    assert t.page.locator('select[data-testid^="rw-run-"]').count() == 3
    assert t.page.locator('[data-testid="rw-reference"]').count() == 1
    assert t.page.locator('[data-testid="rw-run-identity"] .v3-rw-identity').count() == 2
    assert t.page.locator('[data-testid="rw-delta-basis"]').is_visible()
    assert _no_document_overflow(t.page), "V3 grid widened viewport"
    t.page.locator('[data-testid="rw-back-history"]').click()
    t.page.locator('[data-testid="run-history-table"]').wait_for()
    assert t.errors == [], t.errors
    t.close()



def test_selector_reference_tracks_three_slots_when_changed_or_cleared(live_server, browser):
    """Actual HTMX/Chromium: stale reference options never survive an edit."""
    t = _two_runs(live_server, browser, "rw-v3-correction-a")
    # Change an actual input so the third committed Run has a distinct
    # snapshot identity, not merely a repeat execution at the same inputs.
    t.open()
    t.dd("start").fill("2030-03-01")
    t.save()
    t.run()
    _open_history(t)
    history_ids = t.page.locator('[data-testid="run-history-table"] tr[data-history-id]').evaluate_all(
        "(rows) => rows.map(row => row.getAttribute('data-history-id'))")
    assert len(history_ids) == 3
    assert len(set(history_ids)) == 3
    t.page.locator('[data-testid="run-history-workspace-v3"]').click()
    t.page.locator('[data-testid="run-workspace-v3"]').wait_for()

    run1 = t.page.locator('[data-testid="rw-run-1"]')
    run2 = t.page.locator('[data-testid="rw-run-2"]')
    run3 = t.page.locator('[data-testid="rw-run-3"]')
    ref = t.page.locator('[data-testid="rw-reference"]')

    # Historical A, canonical Last B, historical C — all three distinct.
    run1.select_option(history_ids[2])
    run2.select_option("last")
    run3.select_option(history_ids[1])
    assert ref.locator("option").count() == 3
    ref.select_option(history_ids[1])
    t.page.locator('[data-testid="rw-compare-submit"]').click()
    expect(t.page.locator('[data-testid="rw-run-identity"] .v3-rw-identity')).to_have_count(3)

    # Removing the reference's own slot must not keep the now-invalid value.
    t.page.locator('[data-testid="rw-run-3"]').select_option("")
    assert t.page.locator('[data-testid="rw-reference"]').input_value() in (
        history_ids[2], "last")
    assert t.page.locator('[data-testid="rw-reference"] option').count() == 2
    t.page.locator('[data-testid="rw-compare-submit"]').click()
    expect(t.page.locator('[data-testid="rw-run-identity"] .v3-rw-identity')).to_have_count(2)

    # Switch both participating slots to two separate historical Runs.
    t.page.locator('[data-testid="rw-run-1"]').select_option(history_ids[2])
    t.page.locator('[data-testid="rw-run-2"]').select_option(history_ids[1])
    t.page.locator('[data-testid="rw-compare-submit"]').click()
    expect(t.page.locator('[data-testid="rw-run-identity"] .v3-rw-identity')).to_have_count(2)
    expect(t.page.locator(".v3-rw-identity .v3-rw-chip")).to_have_text(["HISTORICAL", "HISTORICAL"])
    assert t.errors == [], t.errors
    t.close()
