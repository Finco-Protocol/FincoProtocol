"""SAFE CORE V3.4 / Workstream B: the integrated input -> save -> run -> understand -> recover journey in real Chromium under the real CSP.

SC-06 (effective Wind inputs), SC-07 (one project name), SC-08 (shareholder-loan maturity vs shortened horizon), SC-10 (explained, non-recorded failed
Run) plus unsaved-field protection on scenario switch, keyboard operation and a phone viewport. Set SC34_SCREENSHOT_DIR to keep screenshots.
"""
from __future__ import annotations

import os
import re

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")

from tests.test_rcux2_ppa_quick_add_browser import Session, browser, live_server  # noqa: F401,E402
from tests.model_workspace_navigation import activate_destination

SHOTS = os.environ.get("SC34_SCREENSHOT_DIR")


def _shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=False)


def _history(uid, rec):
    from app.persistence.run_history_repository import get_run_history
    return len(get_run_history(uid, rec.project_id))


def _no_horizontal_scroll(page):
    return page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")


def test_wind_revenue_sheet_shows_the_real_effective_tariff_and_balancing(live_server, browser):
    s = Session(live_server, browser, "sc34-j-wind", template="generic_wind_reference")
    activate_destination(s.page, "tab-revenue")
    panel = s.page.locator("[data-testid=revenue-effective-inputs]")
    panel.scroll_into_view_if_needed()
    assert re.match(r"^60 EUR/MWh", panel.locator("[data-testid=effective-tariff-value]").inner_text().strip())
    assert panel.locator("[data-testid=effective-tariff-source]").inner_text() == "Saved legacy tariff key"
    assert re.match(r"^8 EUR/MWh", panel.locator("[data-testid=effective-balancing-value]").inner_text().strip())
    assert panel.locator("[data-testid=effective-balancing-source]").inner_text().startswith("Project template default")
    assert "net revenue = gross revenue - balancing deduction" in panel.inner_text()
    assert "takes effect only after Save and a new Run" in panel.inner_text()
    basis = s.page.locator(".v2-revenue-pricing-item")                               # the summary above agrees with the panel (no empty dashes)
    assert re.search(r"Contracted tariff\s*60\b", basis.filter(has_text="Contracted tariff").first.inner_text().replace("\n", " "))
    assert re.search(r"Balancing cost\s*8\b", basis.filter(has_text="Balancing cost").first.inner_text().replace("\n", " "))
    _shot(s.page, "sc06-wind-effective-inputs-desktop")
    assert s.errors == [], s.errors
    s.close()


def test_effective_inputs_fit_a_phone_viewport(live_server, browser):
    s = Session(live_server, browser, "sc34-j-wind-m", template="generic_wind_reference", viewport={"width": 390, "height": 844})
    activate_destination(s.page, "tab-revenue")
    s.page.locator("[data-testid=revenue-effective-inputs]").scroll_into_view_if_needed()
    box = s.page.locator("[data-testid=revenue-effective-inputs]").bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= 391                          # never wider than the screen
    assert _no_horizontal_scroll(s.page)
    _shot(s.page, "sc06-wind-effective-inputs-mobile")
    s.close()


def test_project_rename_is_coherent_in_the_browser(live_server, browser):
    s = Session(live_server, browser, "sc34-j-rename")
    activate_destination(s.page, "tab-project-setup")
    field = s.page.locator('[data-field-id="project_setup.identity.project_name"] input[name="value"]').first
    with s.page.expect_response(lambda r: r.url.endswith("/v2/workbook/update")) as done:
        field.fill("Renamed In Browser"); field.press("Tab")
    assert done.value.status == 200
    s.page.reload()
    s.page.wait_for_selector(".v2-toolbar-name")
    assert s.page.locator(".v2-toolbar-name").first.inner_text() == "Renamed In Browser"
    assert s.page.title().startswith("Renamed In Browser")
    s.page.goto(f"{live_server}/library")
    assert s.page.get_by_text("Renamed In Browser").first.is_visible()
    s.page.goto(f"{live_server}/v2/workbook?project={s.rec.project_code}&sheet=project_setup")
    activate_destination(s.page, "tab-project-setup")
    assert s.page.locator('[data-field-id="project_setup.identity.project_name"] input[name="value"]').first.input_value() == "Renamed In Browser"
    assert s.errors == [], s.errors
    s.close()


def test_shortened_horizon_journey_notice_navigation_refusal_and_recovery(live_server, browser):
    s = Session(live_server, browser, "sc34-j-horizon")
    page = s.page
    activate_destination(page, "tab-project-setup")
    # a committed Run first, so there is a previous result to protect
    with page.expect_response(lambda r: r.url.endswith("/v2/workbook/run") and r.request.method == "POST", timeout=240000):
        page.locator('[data-testid="header-run-btn"]').click()
    page.locator("[data-testid=hybrid-run-state]").filter(has_text="CURRENT").wait_for(timeout=240000)
    runs_before = _history("sc34-j-horizon", s.rec)
    assert runs_before == 1
    last_run_text = page.locator("[data-testid=hybrid-last-run]").inner_text()
    horizon = page.locator('[data-field-id="project_setup.technical.horizon_years"] input[name="value"]').first
    with page.expect_response(lambda r: r.url.endswith("/v2/workbook/update")):
        horizon.fill("20"); horizon.press("Tab")
    notice = page.locator("[data-testid=shl-horizon-notice]")
    notice.wait_for()
    assert "at least 25 years" in notice.inner_text() and "nothing has been moved or changed for you" in notice.inner_text()
    _shot(page, "sc08-shl-horizon-notice")
    # keyboard: the notice buttons are reachable and operable without a pointer
    notice.get_by_role("button", name="Go to Project Horizon").focus()
    page.keyboard.press("Enter")
    assert page.evaluate("document.activeElement.closest('[data-field-id]') && document.activeElement.closest('[data-field-id]').dataset.fieldId") == "project_setup.technical.horizon_years"
    notice.get_by_role("button", name="View shareholder-loan terms").focus()
    page.keyboard.press("Enter")
    assert page.locator("#tab-investor").get_attribute("aria-selected") == "true"
    activate_destination(page, "tab-project-setup")
    # Run is refused, explained, and records nothing
    with page.expect_response(lambda r: r.url.endswith("/v2/workbook/run") and r.request.method == "POST", timeout=240000) as ran:
        page.locator('[data-testid="header-run-btn"]').click()
    assert ran.value.status == 200 and ran.value.headers.get("x-finco-run-outcome") == "FAILED"
    detail = page.locator("[data-testid=run-failure-detail]")
    detail.wait_for()
    assert "SHL_MATURITY_NOT_ON_PERIOD_GRID_FAILS_CLOSED" in detail.locator("[data-testid=run-failure-class]").inner_text()
    assert "unchanged and remains STALE" in detail.locator("[data-testid=run-failure-prior]").inner_text()
    assert page.locator("[data-testid=banner-current]").count() == 0                  # nothing claims the model is current
    _shot(page, "sc10-run-refusal-explained")
    assert _history("sc34-j-horizon", s.rec) == runs_before
    assert page.locator("[data-testid=hybrid-last-run]").inner_text() == last_run_text   # previous Last Run untouched
    # recovery: follow the guidance, restore the horizon, run again
    detail.get_by_role("button").first.click()
    assert page.locator("#tab-project-setup").get_attribute("aria-selected") == "true"
    horizon = page.locator('[data-field-id="project_setup.technical.horizon_years"] input[name="value"]').first
    with page.expect_response(lambda r: r.url.endswith("/v2/workbook/update")):
        horizon.fill("25"); horizon.press("Tab")
    page.wait_for_function("() => !document.querySelector('[data-testid=shl-horizon-notice]')")
    with page.expect_response(lambda r: r.url.endswith("/v2/workbook/run") and r.request.method == "POST", timeout=240000):
        page.locator('[data-testid="header-run-btn"]').click()
    page.locator("[data-testid=hybrid-run-state]").filter(has_text="CURRENT").wait_for(timeout=240000)
    assert _history("sc34-j-horizon", s.rec) == runs_before + 1
    assert [e for e in s.errors if "favicon" not in e] == [], s.errors
    s.close()


def test_unsaved_contract_fields_block_a_scenario_switch_and_survive(live_server, browser):
    from fastapi.testclient import TestClient  # noqa: F401  (documented dependency of the live app)
    s = Session(live_server, browser, "sc34-j-scn")
    page = s.page
    activate_destination(page, "tab-scenarios")
    page.locator("[data-testid=scenario-name-input], input[name=scenario_name]").first.fill("Upside")
    with page.expect_response(lambda r: r.url.endswith("/v2/workbook/scenarios/create")):
        page.get_by_role("button", name=re.compile("Create", re.I)).first.click()
    activate_destination(page, "tab-revenue")
    page.locator("[data-testid=ppa-quick-add]").scroll_into_view_if_needed()
    s.fill(price="61", share="50", ref="PPA-SCN"); s.use_full_window(); s.add()
    assert page.locator("[data-revenue-editor]").get_attribute("data-dirty") == "true"
    activate_destination(page, "tab-scenarios")
    select = page.locator("form[hx-post='/v2/workbook/scenarios/select'] button").first
    select.click()
    activate_destination(page, "tab-revenue")
    box = page.locator("[data-revenue-error]")
    assert "Save or discard the unsaved contract changes before changing the scenario" in box.inner_text()
    assert page.locator("[data-revenue-editor]").get_attribute("data-dirty") == "true"      # the draft is still there
    assert s.saved_book() is None                                                             # nothing was saved behind the user's back
    s.close()
