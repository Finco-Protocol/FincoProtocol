"""RC-UX Phase 2 / Addendum D: Construction timing (Start + Duration -> End = COD) in real Chromium under the real CSP.

The control computes the two existing authoritative inputs (cod_date, construction_months) and saves them atomically through the existing batch
writer. These tests prove the UI behaviour and the Save / STALE / Run semantics; downstream numerical reconciliation belongs to WF-A.
"""
from __future__ import annotations

import os
import re

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")

from tests.test_rcux2_ppa_quick_add_browser import browser, live_server  # noqa: F401,E402

SAVED_STALE = re.compile(r"STALE")


class Timing:
    def __init__(self, live_server, browser, uid, viewport=None, scheme="light"):
        from app.auth import COOKIE_NAME, create_session_token
        from app.services.reference_seed_service import create_reference_seeded_project

        self.uid = uid
        self.rec = create_reference_seeded_project(user_id=uid, template_source="generic_solar_reference", requested_name="CT", capacity_mw=40.0)
        self.ctx = browser.new_context(viewport=viewport or {"width": 1440, "height": 900}, color_scheme=scheme)
        self.ctx.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username="admin"), "url": live_server}])
        self.page = self.ctx.new_page()
        self.errors, self.posts = [], []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("console", lambda m: self.errors.append(m.text) if m.type == "error"
                     and not str((m.location or {}).get("url", "")).endswith("/favicon.ico") else None)
        self.page.on("request", lambda r: self.posts.append(r.url) if r.method == "POST" and "/grid/save" in r.url else None)
        self.base = live_server
        self.open()

    def open(self):
        self.page.goto(f"{self.base}/v2/workbook?project={self.rec.project_code}&sheet=project_setup")
        self.page.wait_for_selector("[data-testid=construction-timing]", state="attached")
        self.page.evaluate("document.getElementById('tab-project-setup').click()")
        self.page.locator("[data-testid=construction-timing]").scroll_into_view_if_needed()
        self.page.wait_for_function("() => document.querySelector('[data-testid=construction-timing] [data-dd=end]').value !== ''")

    def dd(self, name):
        return self.page.locator(f'[data-testid=construction-timing] [data-dd="{name}"]')

    def save_button(self):
        return self.page.locator("[data-ct-save]")

    def message(self):
        return self.page.locator("[data-testid=construction-timing-msg]").inner_text()

    def saved(self):
        from app.persistence.workspace_repository import get_workspace_state
        from app.workbook.input_set import ProjectInputSet
        ws = get_workspace_state(self.uid, self.rec.project_id)
        pis = ProjectInputSet.from_snapshot(ws.draft_snapshot)
        return str(pis.get("project_setup.technical.cod_date")), int(pis.get("project_setup.technical.construction_months"))

    def save(self):
        with self.page.expect_response(lambda r: "/grid/save" in r.url and r.request.method == "POST") as done:
            self.save_button().click()
        assert done.value.status == 200
        self.page.locator("[data-testid=construction-timing-msg]").filter(has_text="Saved").wait_for()

    def state(self):
        return self.page.locator("[data-testid=hybrid-run-state]").inner_text().strip()

    def run(self):
        with self.page.expect_response(lambda r: "/v2/workbook/run" in r.url and r.request.method == "POST", timeout=240000) as ran:
            self.page.locator('[data-testid="header-run-btn"]').click()
        assert ran.value.status == 200
        self.page.locator("[data-testid=hybrid-run-state]").filter(has_text="CURRENT").wait_for(timeout=240000)

    def close(self):
        self.ctx.close()


def test_the_saved_timing_is_shown_as_a_derived_start_plus_duration(live_server, browser):
    t = Timing(live_server, browser, "rcux2-ct-1")
    assert t.saved() == ("2031-03-01", 14)
    assert t.dd("start").input_value() == "2030-01-01" and t.dd("duration").input_value() == "14" and t.dd("unit").input_value() == "months"
    assert t.dd("end").input_value() == "2031-03-01" and t.save_button().is_disabled()           # nothing to save
    t.close()


@pytest.mark.parametrize("start,duration,unit,end,months", [
    ("2030-06-01", "18", "months", "2031-12-01", 18), ("2030-06-01", "2", "years", "2032-06-01", 24),
    ("2030-01-31", "1", "months", "2030-02-28", 1), ("2031-01-31", "13", "months", "2032-02-29", 13)])
def test_the_end_is_calculated_for_months_years_and_month_end_starts(live_server, browser, start, duration, unit, end, months):
    t = Timing(live_server, browser, "rcux2-ct-2")
    t.dd("start").fill(start)
    t.dd("duration").fill(duration)
    t.dd("unit").select_option(unit)
    assert t.dd("end").input_value() == end
    t.close()


def test_editing_the_start_recalculates_the_end_and_a_save_persists_cod_and_duration_atomically(live_server, browser):
    t = Timing(live_server, browser, "rcux2-ct-3")
    t.dd("duration").fill("18")
    assert t.dd("end").input_value() == "2031-07-01"                                 # 2030-01-01 + 18 months
    t.dd("start").fill("2030-06-01")
    assert t.dd("end").input_value() == "2031-12-01"
    assert t.save_button().is_enabled()
    t.save()
    assert t.saved() == ("2031-12-01", 18)
    assert len(t.posts) == 1                                                       # ONE atomic batch request for both fields
    assert t.state() == "NOT RUN"                                                  # saving never runs the model
    t.page.reload()
    t.page.wait_for_selector("[data-testid=construction-timing]", state="attached")
    t.page.wait_for_function("() => document.querySelector('[data-testid=construction-timing] [data-dd=end]').value !== ''")
    assert t.dd("end").input_value() == "2031-12-01" and t.dd("duration").input_value() == "18"     # reopening shows the saved configuration
    assert t.errors == [], t.errors
    t.close()


def test_a_double_click_saves_once(live_server, browser):
    t = Timing(live_server, browser, "rcux2-ct-4")
    t.dd("duration").fill("20")
    t.save_button().dblclick()
    t.page.locator("[data-testid=construction-timing-msg]").filter(has_text="Saved").wait_for()
    assert len(t.posts) == 1
    t.close()


def test_the_manual_end_override_is_explicit_whole_month_checked_and_representable(live_server, browser):
    t = Timing(live_server, browser, "rcux2-ct-5")
    t.dd("start").fill("2030-06-01")
    t.dd("duration").fill("12"); t.dd("unit").select_option("months")
    t.dd("manual").check()
    assert t.dd("end").get_attribute("readonly") is None and t.dd("end").input_value() == "2031-06-01"
    t.dd("end").fill("2031-09-01")                                                 # 15 months
    assert "15 months" in t.page.inner_text("[data-testid=construction-timing] [data-dd=note]")
    assert t.save_button().is_enabled()
    t.dd("end").fill("2031-09-15")                                                 # 15.5 months: not representable
    assert t.save_button().is_disabled() and "whole number of months" in t.message()
    t.dd("end").fill("2031-09-01")
    t.save()
    assert t.saved() == ("2031-09-01", 15)
    t.page.wait_for_selector(".htmx-request", state="detached")                    # the saved sheet is re-rendered; work on the fresh control
    t.dd("manual").check()
    t.dd("end").fill("2031-11-30")                                                 # a COD the model would derive differently (month-end): refused, not saved
    assert t.save_button().is_disabled()
    t.dd("end").fill("2031-12-15")
    t.dd("reset").click()                                                          # explicit return to the calculated end
    assert t.dd("manual").is_checked() is False and t.dd("end").input_value() == t.saved()[0]
    t.close()


@pytest.mark.parametrize("duration", ["0", "-1", "", "abc", "121", "0.4"])
def test_unsupported_durations_fail_closed_and_nothing_is_saved(live_server, browser, duration):
    t = Timing(live_server, browser, "rcux2-ct-6")
    t.dd("duration").fill(duration); t.dd("unit").select_option("months")
    assert t.save_button().is_disabled()
    assert t.saved() == ("2031-03-01", 14) and t.posts == []
    t.close()


def test_a_timing_change_makes_the_last_run_stale_history_stays_immutable_and_the_next_run_is_current(live_server, browser):
    from app.persistence.run_history_repository import get_run_history
    t = Timing(live_server, browser, "rcux2-ct-7")
    t.run()
    first = [str(getattr(e, "snapshot_id", e)) for e in get_run_history(t.uid, t.rec.project_id)]
    assert len(first) == 1
    t.open()
    t.dd("start").fill("2030-02-01")                                               # construction starts a month later (COD 2031-04-01), same duration
    t.save()
    assert t.saved() == ("2031-04-01", 14)
    assert t.state() == "STALE"                                                    # an applicable timing change stales the committed results
    assert [str(getattr(e, "snapshot_id", e)) for e in get_run_history(t.uid, t.rec.project_id)] == first
    t.run()
    after = [str(getattr(e, "snapshot_id", e)) for e in get_run_history(t.uid, t.rec.project_id)]
    assert len(after) == 2 and first[0] in after                                   # the earlier Run is unchanged
    assert t.errors == [], t.errors
    t.close()


def test_the_timing_card_fits_a_phone_in_dark_mode_without_document_overflow(live_server, browser):
    t = Timing(live_server, browser, "rcux2-ct-8", viewport={"width": 390, "height": 800}, scheme="dark")
    assert t.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    t.close()
