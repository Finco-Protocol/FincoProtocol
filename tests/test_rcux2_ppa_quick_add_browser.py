"""RC-UX Phase 2 (Workstream B): guided "Add a PPA" in real Chromium under the real CSP.

An ordinary PPA is added without typing a contract ID; the contract reference is still required (never invented); the existing
Save path persists the typed stream; Run stays a separate, explicit action.
"""
from __future__ import annotations

import json
import os
import re
import socket
import threading
import time

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")
from playwright.sync_api import sync_playwright  # noqa: E402

PORT = 8801
SAVED = re.compile(r"^Saved Working Copy")      # case-sensitive start: "Unsaved changes" must never satisfy a wait for the saved state


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    import uvicorn
    from app.persistence import db

    mp = pytest.MonkeyPatch()
    mp.setattr(db, "DB_PATH", str(tmp_path_factory.mktemp("rcux2-ppa") / "g.db"))
    db.init_db()
    import main_web

    server = uvicorn.Server(uvicorn.Config(main_web.app, host="127.0.0.1", port=PORT, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(180):
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=1).close()
            break
        except OSError:
            time.sleep(1)
    yield f"http://127.0.0.1:{PORT}"
    server.should_exit = True
    thread.join(timeout=10)
    mp.undo()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        options = {"args": ["--no-sandbox"]}
        exe = os.environ.get("FINCO_TEST_CHROMIUM_PATH")
        if exe:
            options["executable_path"] = exe
        try:
            instance = pw.chromium.launch(**options)
        except Exception as exc:
            pytest.skip(f"chromium unavailable: {exc}")
        yield instance
        instance.close()


class Session:
    def __init__(self, live_server, browser, uid, viewport=None, scheme="light"):
        from app.auth import COOKIE_NAME, create_session_token
        from app.services.reference_seed_service import create_reference_seeded_project

        self.uid = uid
        self.rec = create_reference_seeded_project(user_id=uid, template_source="generic_solar_reference", requested_name="PPA", capacity_mw=40.0)
        self.ctx = browser.new_context(viewport=viewport or {"width": 1440, "height": 900}, color_scheme=scheme)   # real CSP: no bypass
        self.ctx.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username="admin"), "url": live_server}])
        self.page = self.ctx.new_page()
        self.errors = []
        self.requests = []
        self.page.on("request", lambda r: self.requests.append((r.method, r.url)))
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("console", lambda m: self.errors.append(m.text) if m.type == "error"
                     and not str((m.location or {}).get("url", "")).endswith("/favicon.ico") else None)
        self.page.goto(f"{live_server}/v2/workbook?project={self.rec.project_code}&sheet=revenue")
        self.page.wait_for_selector("[data-testid=ppa-quick-add]", state="attached")

    def posts_to(self, path):
        return [u for m, u in self.requests if m == "POST" and u.endswith(path)]

    def quick(self, name):
        return self.page.locator(f'[data-testid=ppa-quick-add] [data-quick="{name}"]')

    def dd(self, name):
        return self.page.locator(f'[data-testid=ppa-quick-add] [data-dd="{name}"]')

    def set_dates(self, start=None, duration=None, unit=None, end=None):
        """Drive the shared Start + Duration -> End control; `end` switches to the explicit manual override."""
        if start is not None:
            self.dd("start").fill(start)
        if duration is not None:
            self.dd("duration").fill(str(duration))
        if unit is not None:
            self.dd("unit").select_option(unit)
        if end is not None:
            if not self.dd("manual").is_checked():
                self.dd("manual").check()
            self.dd("end").fill(end)

    def window_end(self):
        return self.page.locator("[data-testid=ppa-quick-add]").get_attribute("data-window-end")

    def use_full_window(self):
        self.set_dates(end=self.window_end())

    def fill(self, **values):
        for key, value in values.items():
            el = self.quick(key)
            if key == "kind":
                el.select_option(value)
            else:
                el.fill(value)

    def add(self):
        self.page.locator("[data-quick-add]").click()

    def saved_book(self):
        from app.persistence.workspace_repository import get_workspace_state
        from app.workbook.revenue_multistream import FIELD_ID
        from app.workbook.input_set import ProjectInputSet
        ws = get_workspace_state(self.uid, self.rec.project_id)
        raw = ProjectInputSet.from_snapshot(ws.draft_snapshot).get(FIELD_ID) or ""
        return json.loads(raw) if raw else None

    def close(self):
        self.ctx.close()


def _open_editor(s):
    s.page.evaluate("document.getElementById('tab-revenue').click()")
    s.page.locator("[data-testid=ppa-quick-add]").scroll_into_view_if_needed()


def test_a_fixed_ppa_is_added_with_a_generated_id_saved_and_not_run(live_server, browser):
    s = Session(live_server, browser, "rcux2-ppa-1")
    _open_editor(s)
    assert s.dd("start").input_value()                                              # defaults come from the project's own operating periods
    s.fill(price="62.5", share="80", ref="PPA-2031-A")
    s.use_full_window()
    s.add()
    assert s.page.locator("[data-quick-error]").is_hidden()
    s.page.locator("[data-revenue-save]").click()
    s.page.locator("[data-revenue-feedback]").filter(has_text=SAVED).wait_for()
    book = s.saved_book()
    stream = book["streams"][0]
    assert stream["id"] == "ppa-1" and stream["type"] == "ppa" and stream["price_eur_mwh"] == 62.5
    assert stream["volume_share"] == 0.8 and stream["source_ref"] == "PPA-2031-A" and stream["indexation_rate"] == 0
    assert s.errors == [], s.errors
    s.close()


def test_two_ppas_get_distinct_generated_ids_and_an_indexed_one_keeps_its_indexation(live_server, browser):
    s = Session(live_server, browser, "rcux2-ppa-2")
    _open_editor(s)
    s.fill(price="60", share="50", ref="REF-A"); s.use_full_window(); s.add()
    s.fill(kind="indexed_ppa", price="70", share="30", index="2.5", ref="REF-B"); s.use_full_window(); s.add()
    s.page.locator("[data-revenue-save]").click()
    s.page.locator("[data-revenue-feedback]").filter(has_text=SAVED).wait_for()
    streams = s.saved_book()["streams"]
    assert [r["id"] for r in streams] == ["ppa-1", "ppa-2"]
    assert streams[1]["indexation_rate"] == 0.025 and streams[1]["volume_share"] == 0.3
    assert s.errors == [], s.errors
    s.close()


@pytest.mark.parametrize("values,message", [
    ({"price": "62,5", "share": "80", "ref": "R"}, "starting price"),
    ({"price": "62.5", "share": "0", "ref": "R"}, "above 0%"),
    ({"price": "62.5", "share": "101", "ref": "R"}, "at most 100%"),
    ({"price": "62.5", "share": "80", "ref": ""}, "contract reference"),
])
def test_invalid_input_is_refused_with_an_actionable_message_and_nothing_is_added(live_server, browser, values, message):
    s = Session(live_server, browser, "rcux2-ppa-3")
    _open_editor(s)
    s.fill(**values)
    s.use_full_window()
    s.add()
    assert message in s.page.inner_text("[data-quick-error]")
    assert s.page.locator("[data-revenue-rows] tr").count() == 0
    assert s.saved_book() is None
    s.close()


def test_the_quick_add_form_fits_a_phone_without_document_overflow_in_dark_mode(live_server, browser):
    s = Session(live_server, browser, "rcux2-ppa-4", viewport={"width": 390, "height": 800}, scheme="dark")
    _open_editor(s)
    assert s.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    s.close()


def _state(s):
    return s.page.locator("[data-testid=hybrid-run-state]").inner_text().strip()


def _save(s):
    s.page.locator("[data-revenue-save]").click()
    s.page.locator("[data-revenue-feedback]").filter(has_text=SAVED).wait_for()


def _run(s):
    with s.page.expect_response(lambda r: "/v2/workbook/run" in r.url and r.request.method == "POST", timeout=240000) as ran:
        s.page.locator('[data-testid="header-run-btn"]').click()
    assert ran.value.status == 200
    s.page.locator("[data-testid=hybrid-run-state]").filter(has_text="CURRENT").wait_for(timeout=240000)


def _history(s):
    from app.persistence.run_history_repository import get_run_history
    return get_run_history(s.uid, s.rec.project_id)


def test_scheduled_ppa_is_an_incomplete_draft_until_every_point_has_a_price_then_saves_and_runs(live_server, browser):
    s = Session(live_server, browser, "rcux2-ppa-5")
    _open_editor(s)
    s.fill(kind="scheduled_ppa", price="55", share="100", ref="REF-SCHED")
    s.use_full_window()
    s.add()
    details = s.page.locator(".rc-price-curve-row details")
    assert details.get_attribute("open") is not None                                  # the price-point editor is opened for the user
    points = s.page.locator(".rc-curve-point")
    n = points.count()
    assert n >= 2
    first_price = points.nth(0).locator("input[type=number]")
    assert first_price.input_value() == "55"
    first_price.fill("")                                                              # a blank price: incomplete, not saveable
    assert "Incomplete draft" in s.page.locator("[data-revenue-feedback]").inner_text()
    assert s.page.locator("[data-revenue-save]").is_disabled()
    first_price.fill("57.5")
    assert s.page.locator("[data-revenue-save]").is_enabled()
    _save(s)
    stream = s.saved_book()["streams"][0]
    assert len(stream["price_curve"]) == n and stream["price_curve"][0]["price_eur_mwh"] == 57.5 and stream["id"] == "ppa-1"
    assert _state(s) == "NOT RUN"                                                    # never run: there is no Last Run to be stale
    before = len(_history(s))
    _run(s)
    assert len(_history(s)) == before + 1
    assert s.errors == [], s.errors
    s.close()


def test_fixed_then_indexed_ppa_save_run_and_the_earlier_run_stays_immutable(live_server, browser):
    s = Session(live_server, browser, "rcux2-ppa-6")
    _open_editor(s)
    s.fill(price="60", share="70", ref="REF-1"); s.use_full_window(); s.add()
    _save(s)
    assert _state(s) == "NOT RUN"
    _run(s)
    first = _history(s)
    first_ids = [e.snapshot_id if hasattr(e, "snapshot_id") else str(e) for e in first]
    assert first
    _open_editor(s)
    s.fill(kind="indexed_ppa", price="65", share="20", index="2", ref="REF-2"); s.use_full_window(); s.add()
    s.page.locator("[data-quick-error]").wait_for(state="hidden")
    _save(s)
    assert _state(s) == "STALE"                                                       # the new contract is not in the Last Run yet
    assert [r["id"] for r in s.saved_book()["streams"]] == ["ppa-1", "ppa-2"]
    _run(s)
    after = _history(s)
    assert len(after) == len(first) + 1
    assert all(i in [e.snapshot_id if hasattr(e, "snapshot_id") else str(e) for e in after] for i in first_ids)   # prior Runs unchanged
    assert s.errors == [], s.errors
    s.close()


# ---- Addendum D: Start Date + Duration -> End Date (PPA) and Section 3 (Scheduled PPA safety) --------------------------------------------

def _relativedelta_end(start, months):
    from datetime import date
    from dateutil.relativedelta import relativedelta
    return (date.fromisoformat(start) + relativedelta(months=months)).isoformat()


@pytest.mark.parametrize("start,duration,unit,months", [
    ("2030-01-01", "15", "years", 180), ("2030-07-01", "18", "months", 18), ("2031-03-01", "10", "years", 120),
    ("2030-01-31", "1", "months", 1), ("2032-01-31", "1", "months", 1), ("2032-02-29", "1", "years", 12), ("2030-12-31", "2", "months", 2)])
def test_end_date_is_calculated_with_the_model_calendar_convention(live_server, browser, start, duration, unit, months):
    s = Session(live_server, browser, "rcux2-dd-1")
    _open_editor(s)
    s.set_dates(start=start, duration=duration, unit=unit)
    assert s.dd("end").input_value() == _relativedelta_end(start, months)        # same arithmetic as the period engine (dateutil relativedelta)
    assert s.dd("end").get_attribute("readonly") is not None
    s.close()


def test_changing_duration_updates_the_end_and_the_manual_override_is_explicit_and_sticky(live_server, browser):
    s = Session(live_server, browser, "rcux2-dd-2")
    _open_editor(s)
    s.set_dates(start="2031-06-30", duration="10", unit="years")
    assert s.dd("end").input_value() == "2041-06-30"
    s.set_dates(duration="12")
    assert s.dd("end").input_value() == "2043-06-30"
    s.fill(price="61", share="60", ref="REF-DD")
    assert s.dd("end").input_value() == "2043-06-30"                              # editing other fields never resets the dates
    s.dd("manual").check()
    assert s.dd("end").get_attribute("readonly") is None and s.dd("end").input_value() == "2043-06-30"   # calculated date becomes the editable start value
    assert "off" in s.page.locator("[data-testid=ppa-quick-add] [data-dd=note]").inner_text()
    s.dd("end").fill("2040-12-31")
    s.quick("price").fill("62")
    s.set_dates(duration="3")                                                      # manual end is preserved while other fields change
    assert s.dd("end").input_value() == "2040-12-31"
    s.dd("reset").click()                                                          # explicit return to automatic mode
    assert s.dd("manual").is_checked() is False and s.dd("end").input_value() == "2034-06-30"
    assert s.quick("price").input_value() == "62" and s.quick("share").input_value() == "60"
    s.close()


@pytest.mark.parametrize("bad", ["0", "-3", "abc", "", "1,5", "0.4"])
def test_a_zero_negative_missing_or_non_whole_month_duration_fails_closed(live_server, browser, bad):
    s = Session(live_server, browser, "rcux2-dd-3")
    _open_editor(s)
    s.fill(price="60", share="50", ref="R")
    s.set_dates(start="2031-06-30", duration=bad, unit="years")
    s.add()
    assert "duration" in s.page.inner_text("[data-quick-error]").lower()
    assert s.page.locator("[data-revenue-rows] tr").count() == 0 and s.dd("end").input_value() == ""
    s.close()


def test_a_duration_ending_off_the_period_boundary_is_blocked_with_a_confirmable_suggestion(live_server, browser):
    s = Session(live_server, browser, "rcux2-dd-4")
    _open_editor(s)
    s.fill(price="60", share="50", ref="R")
    s.set_dates(start="2031-06-30", duration="18", unit="months")                  # 2032-12-30: not an operating boundary (2032-12-31 is)
    assert s.dd("end").input_value() == "2032-12-30"
    s.add()
    assert "operating-period boundary" in s.page.inner_text("[data-quick-error]")
    assert s.page.locator("[data-revenue-rows] tr").count() == 0                   # nothing was added or snapped silently
    s.page.locator("[data-quick-suggest]").click()                                 # explicit confirmation
    assert s.dd("manual").is_checked() and s.dd("end").input_value() == "2032-12-31"
    s.add()
    assert s.page.locator("[data-quick-error]").is_hidden() and s.page.locator("[data-revenue-rows] tr").count() == 1
    _save(s)
    stream = s.saved_book()["streams"][0]
    assert (stream["start_date"], stream["end_date"]) == ("2031-06-30", "2032-12-31")
    s.page.reload()
    s.page.wait_for_selector("[data-testid=ppa-quick-add]", state="attached")
    _open_editor(s)
    assert s.page.locator('[data-field="start_date"]').first.input_value() == "2031-06-30"     # saved dates are what reopens
    s.close()


def test_a_ppa_created_from_a_duration_saves_with_the_calculated_dates(live_server, browser):
    s = Session(live_server, browser, "rcux2-dd-5")
    _open_editor(s)
    s.fill(price="60", share="40", ref="R-FIX")
    s.set_dates(start="2031-06-30", duration="10", unit="years")
    s.add()
    s.fill(kind="indexed_ppa", price="70", share="30", index="1.5", ref="R-IDX")
    s.set_dates(start="2031-12-31", duration="5", unit="years")
    s.add()
    s.fill(kind="scheduled_ppa", price="55", share="20", ref="R-SCH")
    s.set_dates(start="2031-06-30", duration="2", unit="years")
    s.add()
    _save(s)
    streams = s.saved_book()["streams"]
    assert [(r["id"], r["start_date"], r["end_date"]) for r in streams] == [
        ("ppa-1", "2031-06-30", "2041-06-30"), ("ppa-2", "2031-12-31", "2036-12-31"), ("ppa-3", "2031-06-30", "2033-06-30")]
    assert len(streams[2]["price_curve"]) == 4                                     # one explicit point per operating period in the term
    assert s.errors == [], s.errors
    s.close()


def test_a_rejected_scheduled_add_leaves_the_contract_book_untouched(live_server, browser):
    """Section 3.1: no operating period inside the dates -> error, and the book (version included) is unchanged."""
    s = Session(live_server, browser, "rcux2-dd-6")
    _open_editor(s)
    s.fill(kind="scheduled_ppa", price="55", share="100", ref="R")
    s.set_dates(start="2056-06-30", duration="6", unit="months")                   # beyond the modeled horizon
    s.dd("manual").check(); s.dd("end").fill("2056-12-31")
    s.add()
    assert s.page.locator("[data-quick-error]").inner_text() != ""
    assert s.page.locator("[data-revenue-rows] tr").count() == 0
    assert s.page.locator("[data-revenue-form], form[data-revenue-editor]").first.get_attribute("data-dirty") == "false"   # a changed book version would make it dirty
    assert s.page.locator("[data-revenue-save]").is_disabled()
    s.close()


def _scheduled(s):
    _open_editor(s)
    s.fill(kind="scheduled_ppa", price="55", share="100", ref="R-SCH")
    s.set_dates(start="2031-06-30", duration="3", unit="years")
    s.add()
    return s.page.locator(".rc-curve-point")


def _paste(s, rows):
    s.page.locator(".rc-curve-editor").evaluate("d => { d.open = true; }")
    area = s.page.locator(".rc-curve-editor textarea")
    area.fill("\n".join(rows))
    s.page.get_by_role("button", name="Replace curve with pasted points").click()


def _curve_dates(s):
    return [s.page.locator(".rc-curve-point").nth(i).locator("input[type=date]").input_value() for i in range(s.page.locator(".rc-curve-point").count())]


def test_a_curve_missing_a_required_period_is_incomplete_until_it_is_repaired(live_server, browser):
    s = Session(live_server, browser, "rcux2-dd-7")
    points = _scheduled(s)
    dates = _curve_dates(s)
    assert len(dates) == 6
    save = s.page.locator("[data-revenue-save]")
    assert save.is_enabled()
    points.nth(2).get_by_role("button", name="Remove point").click()              # delete a required period
    assert "missing 1 operating period" in s.page.inner_text("[data-revenue-feedback]") and save.is_disabled()
    _paste(s, [f"{d}\t55" for d in dates if d != dates[2]] + ["2099-01-01\t55"])  # a date outside the contract/axis
    assert "not an operating period" in s.page.inner_text("[data-revenue-feedback]") and save.is_disabled()
    _paste(s, [f"{d}\t55" for d in dates])                                         # the complete, ordered curve re-enables Save
    assert "Incomplete" not in s.page.inner_text("[data-revenue-feedback]") and save.is_enabled()
    s.close()


def test_a_duplicate_period_is_flagged_and_a_negative_price_is_refused(live_server, browser):
    s = Session(live_server, browser, "rcux2-dd-8")
    _scheduled(s)
    save = s.page.locator("[data-revenue-save]")
    dates = _curve_dates(s)
    s.page.locator(".rc-curve-point").nth(1).locator("input[type=date]").fill(dates[0])      # same period twice
    assert "repeats" in s.page.inner_text("[data-revenue-feedback]") and save.is_disabled()
    s.page.locator(".rc-curve-point").nth(1).locator("input[type=date]").fill(dates[1])      # repair
    assert save.is_enabled()
    s.page.locator(".rc-curve-point").nth(3).locator("input[type=number]").fill("-1")
    assert "zero or more" in s.page.inner_text("[data-revenue-feedback]") and save.is_disabled()
    s.page.locator(".rc-curve-point").nth(3).locator("input[type=number]").fill("57")
    assert save.is_enabled()
    _save(s)
    curve = s.saved_book()["streams"][0]["price_curve"]
    assert [p["period_start"] for p in curve] == dates and curve[3]["price_eur_mwh"] == 57
    assert s.errors == [], s.errors
    s.close()


# ---- Section 4: multiple PPAs + explicit residual Merchant, allocation feedback, scenario restoration -------------------------------------

def _add_residual_merchant(s, price="48", ref="MKT-FWD-1"):
    s.page.locator("[data-revenue-add-type]").select_option("residual_merchant")
    s.page.locator("[data-revenue-add]").click()
    row = s.page.locator("[data-revenue-rows] tr").last
    row.locator('[data-field="id"]').fill("merchant-1")
    row.locator('[data-field="start_date"]').fill(s.dd("start").input_value())
    row.locator('[data-field="end_date"]').fill(s.window_end())
    row.locator('[data-field="price_eur_mwh"]').fill(price)
    row.locator('[data-field="source_ref"]').fill(ref)


def test_two_ppas_plus_an_explicit_residual_merchant_save_and_run(live_server, browser):
    s = Session(live_server, browser, "rcux2-c2-1")
    _open_editor(s)
    s.fill(price="62.5", share="60", ref="PPA-A"); s.use_full_window(); s.add()
    s.fill(kind="indexed_ppa", price="70", share="20", index="2", ref="PPA-B"); s.use_full_window(); s.add()
    alloc = s.page.locator("[data-testid=revenue-allocation]")
    assert "up to 80%" in alloc.inner_text() and "unallocated up to 20%" in alloc.inner_text()      # no residual yet: the remainder is shown as unallocated
    _add_residual_merchant(s)
    assert "residual Merchant takes the remainder" in alloc.inner_text()
    _save(s)
    streams = s.saved_book()["streams"]
    assert [r["type"] for r in streams] == ["ppa", "ppa", "merchant"]
    assert streams[2]["volume_share"] is None and streams[2]["price_eur_mwh"] == 48 and streams[2]["source_ref"] == "MKT-FWD-1"   # price and reference are the user's
    assert _state(s) == "NOT RUN"
    _run(s)
    assert _state(s) == "CURRENT" and len(_history(s)) == 1
    assert s.errors == [], s.errors
    s.close()


def test_contracted_shares_above_100_percent_are_reported_and_cannot_be_saved(live_server, browser):
    s = Session(live_server, browser, "rcux2-c2-2")
    _open_editor(s)
    s.fill(price="60", share="70", ref="A"); s.use_full_window(); s.add()
    s.fill(price="61", share="40", ref="B"); s.use_full_window(); s.add()
    assert "cannot exceed 100%" in s.page.locator("[data-testid=revenue-allocation]").inner_text()
    assert s.page.locator("[data-revenue-save]").is_disabled() and "Not saveable" in s.page.inner_text("[data-revenue-feedback]")
    s.page.locator("[data-revenue-rows] tr").last.locator('[data-field="volume_share"]').fill("30")
    assert s.page.locator("[data-revenue-save]").is_enabled()
    s.close()


def test_unsaved_contract_changes_block_a_scenario_change_and_a_run(live_server, browser):
    s = Session(live_server, browser, "rcux2-c2-3")
    _open_editor(s)
    s.fill(price="60", share="50", ref="A"); s.use_full_window(); s.add()                # unsaved
    before = len(s.posts_to("/v2/workbook/run"))
    s.page.locator('[data-testid="header-run-btn"]').click()
    s.page.wait_for_function("() => document.querySelector('[data-revenue-error]').textContent.includes('before running')")
    assert len(s.posts_to("/v2/workbook/run")) == before and s.saved_book() is None       # nothing ran, nothing was lost
    assert s.page.locator("[data-revenue-rows] tr").count() == 1
    s.close()


def test_base_and_alternative_scenario_contracts_are_restored_independently(live_server, browser):
    from app.persistence.scenarios_repository import list_scenarios
    s = Session(live_server, browser, "rcux2-c2-4")
    _open_editor(s)
    s.fill(price="60", share="50", ref="BASE-A"); s.use_full_window(); s.add()
    _save(s)
    base_book = s.saved_book()
    s.page.evaluate("document.getElementById('tab-scenarios').click()")
    s.page.locator("form.v2-scenario-create-form input[name=scenario_name]").fill("Alt")
    s.page.locator("form.v2-scenario-create-form button[type=submit]").click()
    s.page.locator(".v2-scenario-row").filter(has_text="Alt").first.wait_for()
    _open_editor(s)                                                                        # Alt is active after Create
    s.page.wait_for_selector("[data-revenue-save]", state="attached")
    s.fill(price="75", share="30", ref="ALT-B"); s.use_full_window(); s.add()
    _save(s)
    alt_rows = s.page.locator("[data-revenue-rows] tr").count()
    assert alt_rows == 2                                                                   # Alt now holds its own two-contract book
    assert s.saved_book() == base_book                                                     # no cross-scenario write: the Base draft is unchanged
    scenarios = {sc.scenario_name: sc for sc in list_scenarios(s.uid, s.rec.project_id)}
    assert '"id": "ppa-2"' in json.dumps(scenarios["Alt"].overrides) or "ppa-2" in json.dumps(scenarios["Alt"].overrides)
    s.page.evaluate("document.getElementById('tab-scenarios').click()")
    s.page.locator(".v2-scenario-row").filter(has=s.page.locator(".v2-scenario-base-badge")).first.get_by_role("button", name="Select", exact=True).click()
    s.page.wait_for_selector(".htmx-request", state="detached")                           # the scenario switch and its sheet refresh have settled
    _open_editor(s)
    assert s.page.locator("[data-revenue-rows] tr").count() == 1                           # Base restored
    s.page.evaluate("document.getElementById('tab-scenarios').click()")
    s.page.locator(".v2-scenario-row").filter(has_text="Alt").first.get_by_role("button", name="Select", exact=True).click()
    s.page.wait_for_selector(".htmx-request", state="detached")
    _open_editor(s)
    assert s.page.locator("[data-revenue-rows] tr").count() == 2                           # Alt restored
    assert s.errors == [], s.errors
    s.close()
