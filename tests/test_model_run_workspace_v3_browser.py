"""V3 Run Workspace: Chromium HTMX navigation, accessible controls and mobile containment."""
from __future__ import annotations

import pytest

pytest.importorskip("playwright", reason="browser support not installed")

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
    assert t.page.locator('[data-testid^="rw-run-"]').count() == 3
    assert t.page.locator('[data-testid="rw-reference"]').count() == 1
    assert t.page.locator('[data-testid="rw-run-identity"] .v3-rw-identity').count() == 2
    assert t.page.locator('[data-testid="rw-delta-basis"]').is_visible()
    assert _no_document_overflow(t.page), "V3 grid widened viewport"
    t.page.locator('[data-testid="rw-back-history"]').click()
    t.page.locator('[data-testid="run-history-table"]').wait_for()
    assert t.errors == [], t.errors
    t.close()
