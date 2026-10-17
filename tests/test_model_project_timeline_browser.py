"""WF-10 Project Timeline V1 in real Chromium under the real CSP: persisted values, calendar correctness, Save consistency, a11y and layout."""
from __future__ import annotations

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")

from dateutil.relativedelta import relativedelta
from datetime import date

from tests.test_rcux2_construction_timing_browser import Timing
from tests.test_rcux2_ppa_quick_add_browser import browser, live_server  # noqa: F401,E402


class TL(Timing):
    def open(self):
        super().open()
        self.page.wait_for_selector("[data-project-timeline][data-pt-state]")

    def root(self):
        return self.page.locator("[data-project-timeline]")

    def cell(self, attr):
        return self.page.locator(f"[data-project-timeline] [{attr}]").first.get_attribute(attr)

    def text(self):
        return self.root().inner_text()


def oracle_start(cod, months):
    return (date.fromisoformat(cod) - relativedelta(months=months)).isoformat()


@pytest.mark.parametrize("template", ["generic_solar_reference", "generic_wind_reference"])
def test_solar_and_wind_show_the_saved_dates_with_the_derived_start(live_server, browser, template, monkeypatch):
    import tests.test_rcux2_construction_timing_browser as mod
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project
    rec = create_reference_seeded_project(user_id="wf10-" + template, template_source=template, requested_name="TL", capacity_mw=40.0)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id="wf10-" + template, username="admin"), "url": live_server}])
    page = ctx.new_page()
    page.goto(f"{live_server}/v2/workbook?project={rec.project_code}&sheet=project_setup")
    page.wait_for_selector("[data-project-timeline][data-pt-state]", state="attached")
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.input_set import ProjectInputSet
    pis = ProjectInputSet.from_snapshot(get_workspace_state("wf10-" + template, rec.project_id).draft_snapshot)
    cod, months, horizon = str(pis.get("project_setup.technical.cod_date")), int(pis.get("project_setup.technical.construction_months")), int(pis.get("project_setup.technical.horizon_years"))
    assert page.locator("[data-pt-cod]").first.get_attribute("data-pt-cod") == cod
    assert page.locator("[data-pt-start]").first.get_attribute("data-pt-start") == oracle_start(cod, months)
    assert page.locator("[data-pt-months]").first.get_attribute("data-pt-months") == str(months)
    assert page.locator("[data-pt-horizon]").first.get_attribute("data-pt-horizon") == str(horizon)
    text = page.locator("[data-project-timeline]").inner_text()
    assert "derived: COD" in text and "saved input" in text and "not derived here" in text
    assert page.locator("[data-pt-warning]").count() == 0
    ctx.close()


@pytest.mark.parametrize("cod,months", [("2032-02-29", 12), ("2031-03-31", 1), ("2031-05-31", 3), ("2032-03-01", 13), ("2030-12-31", 120), ("2031-03-01", 14)])
def test_leap_year_and_month_end_derivation_matches_the_calendar_oracle(live_server, browser, cod, months):
    t = TL(live_server, browser, "wf10-cal")
    got = t.page.evaluate("([c, m]) => window.FincoProjectTimeline.evaluate(c, String(m), '25')", [cod, months])
    expected = oracle_start(cod, months)
    reproducible = (date.fromisoformat(expected) + relativedelta(months=months)).isoformat() == cod
    assert (got["start"] == expected) if reproducible else (got["start"] is None and any("month-end" in w for w in got["warnings"]))
    t.close()


@pytest.mark.parametrize("cod,months,horizon,needle", [
    ("", "14", "25", "COD) is not set"), ("2031-13-40", "14", "25", "not a valid calendar date"), ("2031-02-29", "14", "25", "not a valid calendar date"),
    ("2031-03-01", "", "25", "construction duration is not set"), ("2031-03-01", "0", "25", "positive whole number of months"),
    ("2031-03-01", "abc", "25", "positive whole number of months"), ("2031-03-01", "14", "0", "positive whole number of years"),
    ("2031-03-01", "14", "", "horizon is not set"), ("2031-03-31", "1", "25", "month-end convention")])
def test_missing_and_invalid_values_warn_without_repairing_or_inventing_dates(live_server, browser, cod, months, horizon, needle):
    t = TL(live_server, browser, "wf10-bad")
    got = t.page.evaluate("([c, m, h]) => window.FincoProjectTimeline.evaluate(c, m, h)", [cod, months, horizon])
    assert any(needle in w for w in got["warnings"]), got
    if "horizon" not in needle and "years" not in needle:
        assert (got["start"] is None) or needle == "month-end convention"
    t.close()


def test_a_successful_save_refreshes_the_timeline_from_accepted_values_without_running_the_model(live_server, browser):
    from app.persistence.run_history_repository import get_run_history
    t = TL(live_server, browser, "wf10-save")
    assert t.cell("data-pt-cod") == "2031-03-01" and t.cell("data-pt-start") == "2030-01-01"
    history = len(get_run_history(t.uid, t.rec.project_id))
    t.dd("start").fill("2030-06-01"); t.dd("duration").fill("18"); t.dd("unit").select_option("months")
    assert "unsaved draft" in t.text() and t.cell("data-pt-cod") == "2031-03-01"          # the draft is flagged, not displayed
    t.save()
    t.page.wait_for_selector(".htmx-request", state="detached")
    t.page.wait_for_selector("[data-project-timeline][data-pt-state]")
    assert t.saved() == ("2031-12-01", 18)
    assert t.cell("data-pt-cod") == "2031-12-01" and t.cell("data-pt-start") == "2030-06-01" and t.cell("data-pt-months") == "18"
    assert "unsaved draft" not in t.text()
    assert len(t.posts) == 1 and len(get_run_history(t.uid, t.rec.project_id)) == history
    assert t.state() == "NOT RUN"                                                         # never labelled CURRENT by a timeline refresh
    assert t.errors == [], t.errors
    t.close()


def test_a_rejected_or_conflicting_save_keeps_the_last_accepted_timeline(live_server, browser):
    t = TL(live_server, browser, "wf10-conflict")
    t.dd("duration").fill("20")
    t.page.evaluate("document.getElementById('v2-workbook-shell').dataset.contentHash='stale'; const a=document.getElementById('v2-scenario-edit-authority'); if (a) a.dataset.contentHash='stale';")
    with t.page.expect_response(lambda r: "/grid/save" in r.url) as done:
        t.save_button().click()
    assert done.value.status in (409, 422)                                               # the server rejects the stale identity; nothing is saved
    assert t.cell("data-pt-cod") == "2031-03-01" and t.cell("data-pt-months") == "14"
    assert "unsaved draft" in t.text() and t.saved() == ("2031-03-01", 14)
    t.close()


def test_one_timeline_one_handler_set_and_unique_ids_after_htmx_replacement(live_server, browser):
    t = TL(live_server, browser, "wf10-dom")
    t.dd("duration").fill("16"); t.save()
    t.page.wait_for_selector(".htmx-request", state="detached")
    t.page.wait_for_selector("[data-project-timeline][data-pt-state]")
    assert t.page.locator("[data-project-timeline]").count() == 1
    assert t.page.evaluate("() => { const ids=[...document.querySelectorAll('[id]')].map(n=>n.id); return ids.length === new Set(ids).size; }")
    t.dd("duration").fill("17")
    assert t.page.locator("[data-pt-draft]").count() == 1                                 # one handler: one note, not several
    t.close()


def test_layout_fits_390px_in_light_and_dark_and_is_readable_as_text(live_server, browser):
    for scheme in ("light", "dark"):
        t = TL(live_server, browser, "wf10-" + scheme, viewport={"width": 390, "height": 800}, scheme=scheme)
        assert t.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        assert t.page.evaluate("() => { const r=document.querySelector('[data-project-timeline]').getBoundingClientRect(); return r.right <= window.innerWidth + 1; }")
        stages = t.page.locator("[data-project-timeline] .pt-stage")
        assert stages.count() == 2
        tops = [stages.nth(i).bounding_box()["y"] for i in range(2)]
        assert tops[1] > tops[0]                                                         # stacked on a phone
        assert "Milestones not recorded" in t.text()
        t.close()
    d = TL(live_server, browser, "wf10-desktop")
    boxes = [d.page.locator("[data-project-timeline] .pt-stage").nth(i).bounding_box() for i in range(2)]
    assert abs(boxes[0]["y"] - boxes[1]["y"]) < 4 and boxes[1]["x"] > boxes[0]["x"]      # horizontal on desktop
    d.close()


def test_keyboard_reaches_the_disclosure_and_semantics_do_not_rely_on_colour(live_server, browser):
    t = TL(live_server, browser, "wf10-a11y")
    summary = t.page.locator("[data-testid=project-timeline-unavailable] summary")
    summary.focus()
    t.page.keyboard.press("Enter")
    assert t.page.locator("[data-testid=project-timeline-unavailable]").get_attribute("open") is not None
    assert t.page.locator("[data-project-timeline] ol li").count() >= 2                  # an ordered list: order is textual, not coloured
    assert t.page.locator("[data-project-timeline] .pt-bar").get_attribute("role") == "img"
    assert t.page.locator("[data-project-timeline] .pt-bar").get_attribute("aria-label")
    t.close()
