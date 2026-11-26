"""FINCO46: Enter in a V2 field editor saves exactly once and keeps the user where they are (real Chromium).

Before: Enter submitted the field through htmx with focus still in the input; the htmx swap then removed that focused
input, the browser fired change + blur on it, and the blur handler re-submitted the same value from the form being
swapped out — a second, NATIVE POST /v2/workbook/update that navigated the whole page back to Overview.
Synthetic Data Center working copy (the vertical whose journey exposed it); the handler is shared by every field.
"""
from __future__ import annotations

import uuid

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")

from tests.model_workspace_navigation import activate_destination  # noqa: E402
from tests.test_data_center_browser_acceptance import (  # noqa: E402,F401  (fixtures + helpers)
    _create_dc_working_copy, _page, browser, dc_app,
)

FIELD = '#panel-revenue [data-field-id="revenue.data_center.service_price"] input.v2-field-input'


def test_enter_saves_once_without_navigation_and_keeps_the_sheet(browser, dc_app):
    page = _page(browser, dc_app, user_id="dc-enter-" + uuid.uuid4().hex[:8])
    try:
        _create_dc_working_copy(page, dc_app, "DC Enter Save")
        activate_destination(page, "tab-revenue")
        page.locator("#panel-revenue").wait_for(state="visible")
        navigations, updates = [], []
        page.on("request", lambda r: navigations.append(r.url) if r.is_navigation_request() else None)
        page.on("request", lambda r: updates.append(r.headers.get("hx-request")) if "/v2/workbook/update" in r.url else None)
        for value in ("181", "182"):                         # twice: the second edit runs on the swapped-in form
            field = page.locator(FIELD).first
            field.click()
            field.press("Control+a")
            page.keyboard.type(value)
            with page.expect_response(lambda r: "/v2/workbook/update" in r.url and r.status == 200):
                page.keyboard.press("Enter")
            page.wait_for_timeout(800)                         # a duplicate native POST would arrive in this window
            assert page.locator(FIELD).first.input_value().startswith(value)
        assert updates == ["true", "true"], "one htmx Save per Enter, never a native re-submit"
        assert navigations == [], "the page never navigates away on a field Save"
        assert page.get_attribute("#tab-revenue", "aria-selected") == "true"
    finally:
        page.close()
