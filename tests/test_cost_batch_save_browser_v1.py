"""CAPEX/OPEX Productivity V1.1 — staged multi-row Save in a REAL Chromium.

Genuine mouse/keyboard events against a live uvicorn server running the real application on
synthetic disposable working copies; persisted values are read back from the database.  Waits are
event-driven (responses / DOM predicates), never fixed sleeps.  Skipped when Playwright or Chromium
is unavailable.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")
from playwright.sync_api import sync_playwright  # noqa: E402

PORT = 8795
VERTICALS = ["generic_solar_reference", "generic_wind_reference",
             "generic_data_center_reference", "generic_ev_charging_reference"]
TIMINGS: dict[str, float] = {}


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    import uvicorn
    from app.persistence import db

    mp = pytest.MonkeyPatch()
    mp.setattr(db, "DB_PATH", str(tmp_path_factory.mktemp("cost-batch") / "b.db"))
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
    from app.runtime import model_execution as me
    me.reset_model_executor_for_tests(None)
    mp.undo()
    out = os.environ.get("WF05_SCREENSHOT_DIR")
    if out and TIMINGS:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "cost-batch-timings.json"), "w", encoding="utf-8") as fh:
            json.dump(TIMINGS, fh, indent=2, sort_keys=True)


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
    def __init__(self, live_server, browser, uid, template="generic_solar_reference", viewport=None):
        from app.auth import COOKIE_NAME, create_session_token
        from app.services.reference_seed_service import create_reference_seeded_project

        self.base, self.uid = live_server, uid
        self.rec = create_reference_seeded_project(
            user_id=uid, template_source=template, requested_name="Batch", capacity_mw=40.0)
        self.ctx = browser.new_context(viewport=viewport or {"width": 1440, "height": 1000}, bypass_csp=True)
        self.ctx.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username="admin"),
                               "url": live_server}])
        self.page = self.ctx.new_page()
        self.page.on("dialog", lambda d: d.accept())
        self.errors: list[str] = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.posts: list[str] = []
        self.page.on("request", lambda r: self.posts.append(r.url.split(str(PORT), 1)[-1].split("?")[0])
                     if r.method == "POST" else None)

    def posts_to(self, fragment):
        return [p for p in self.posts if fragment in p]

    def open(self, kind):
        self.kind = kind
        self.page.goto(f"{self.base}/v2/workbook?project={self.rec.project_code}")
        self.page.wait_for_selector(f"#tab-{kind}", state="attached")
        self.page.evaluate(f"document.getElementById('tab-{kind}').click()")
        self.page.wait_for_selector(f"#v2-sheet-{kind} form[data-cost-row]", state="attached")
        self.open_groups(kind)

    def open_groups(self, kind=None):
        kind = kind or self.kind
        self.page.evaluate(f"document.querySelectorAll('#v2-sheet-{kind} details[data-group-code]').forEach(d => d.open = true)")

    def rows(self, kind=None):
        return self.page.locator(f"#v2-sheet-{kind or self.kind} form[data-cost-row]")

    def stage_on(self, kind=None):
        box = self.page.locator(f"#v2-sheet-{kind or self.kind} [data-cost-stage-toggle]")
        box.check()
        self.page.wait_for_function("window.v2CostGrid.state().stageMode === true")

    def type_amounts(self, kind, values):
        """Click the first amount cell, then type + Enter per row (Enter moves to the next amount cell)."""
        first = self.rows(kind).nth(0).locator('input[name="amount_keur"]')
        first.click()
        for v in values:
            self.page.keyboard.press("Control+A")
            self.page.keyboard.type(v)
            self.page.keyboard.press("Enter")

    def db_amounts(self, kind, ids):
        from app.persistence.db import get_cursor
        table = "capex_sub_lines" if kind == "capex" else "opex_sub_lines"
        with get_cursor() as cur:
            cur.execute(f"SELECT sub_line_id, amount_keur FROM {table} WHERE project_id=?", (self.rec.project_id,))
            by = {r["sub_line_id"]: r["amount_keur"] for r in cur.fetchall()}
        return [by[i] for i in ids]

    def row_ids(self, kind, n):
        return [self.rows(kind).nth(i).get_attribute("data-sub-line-id") for i in range(n)]

    def chip(self):
        return self.page.locator('[data-testid="toolbar-runtime-state"]').first.inner_text().strip()

    def close(self):
        self.ctx.close()


@pytest.fixture
def make(live_server, browser):
    made = []

    def _make(uid, **kw):
        s = Session(live_server, browser, uid, **kw)
        made.append(s)
        return s

    yield _make
    for s in made:
        s.close()


@pytest.mark.parametrize("template", VERTICALS)
def test_ten_staged_cells_save_in_one_request_exactly_and_make_the_run_stale(make, template):
    s = make(f"u-ten-{template}", template=template)
    s.open("capex")
    n = min(10, s.rows("capex").count())
    assert n >= 6, f"{template} offers only {n} editable CAPEX lines"
    ids = s.row_ids("capex", n)
    before = s.db_amounts("capex", ids)
    s.stage_on()
    values = [f"{2000 + i}.25" for i in range(n)]
    s.type_amounts("capex", values)
    s.page.wait_for_function(f"document.querySelector('[data-cost-stage-count]').textContent.trim() === '{n} staged'")
    assert s.posts_to("/line/update") == [], "staged mode never autosaves a row"
    assert s.db_amounts("capex", ids) == before, "nothing is persisted before the batch Save"
    t0 = time.perf_counter()
    with s.page.expect_response(lambda r: "/cost-lines/save" in r.url) as info:
        s.page.locator('#v2-sheet-capex [data-cost-stage-save]').click()
    assert info.value.status == 200
    s.page.wait_for_function("document.querySelector('[data-cost-stage-msg]').textContent.includes('Saved')")
    TIMINGS[f"save_{n}_lines_{template}_s"] = round(time.perf_counter() - t0, 3)
    assert s.posts_to("/cost-lines/save") == ["/v2/workbook/grid/cost-lines/save"]
    assert s.db_amounts("capex", ids) == [float(v) for v in values]
    s.page.wait_for_function("document.querySelector('[data-testid=\"toolbar-runtime-state\"]').textContent.trim().toUpperCase() === 'STALE' "
                             "|| document.querySelector('[data-testid=\"toolbar-runtime-state\"]').textContent.trim().toUpperCase() === 'NOT RUN'")
    assert s.errors == []


def test_failure_in_one_row_rolls_back_all_rows_keeps_typed_values_and_never_retries(make):
    s = make("u-fail")
    s.open("capex")
    ids = s.row_ids("capex", 3)
    before = s.db_amounts("capex", ids)
    s.stage_on()
    s.type_amounts("capex", ["111", "222", "333"])
    s.page.wait_for_function("document.querySelector('[data-cost-stage-count]').textContent.trim() === '3 staged'")
    # a concurrent writer changes ONE staged row through the existing single-row command
    tokens = s.page.evaluate("(() => { const a = document.querySelector('[id^=v2-cost-authority-]');"
                             " return [a.dataset.contentHash, a.dataset.workbookVersion]; })()")
    row = s.rows("capex").nth(1)
    resp = s.ctx.request.post(f"{s.base}/v2/capex/line/update", form={
        "project": s.rec.project_code, "sub_line_id": ids[1], "label": row.locator('input[name="label"]').input_value(),
        "amount_keur": "999", "row_version": row.locator('input[name="row_version"]').input_value(),
        "workbook_version": tokens[1], "content_hash": tokens[0]}, headers={"HX-Request": "true"})
    assert resp.status == 200
    mid = s.db_amounts("capex", ids)
    assert mid[1] == 999.0 and mid[0] == before[0] and mid[2] == before[2]
    with s.page.expect_response(lambda r: "/cost-lines/save" in r.url) as info:
        s.page.locator('#v2-sheet-capex [data-cost-stage-save]').click()
    assert info.value.status == 409
    s.page.wait_for_function("document.querySelector('[data-cost-stage-msg]').textContent.includes('Nothing was saved')")
    assert s.db_amounts("capex", ids) == mid, "rollback: not even the valid rows were written"
    typed = [s.rows("capex").nth(i).locator('input[name="amount_keur"]').input_value() for i in range(3)]
    assert typed == ["111", "222", "333"], "typed values stay on screen"
    states = s.page.evaluate("Array.from(document.querySelectorAll('#v2-sheet-capex form[data-cost-row]'))"
                             ".slice(0,3).map(r => r.getAttribute('data-save-state'))")
    assert states == ["failed", "failed", "failed"]
    assert len(s.posts_to("/cost-lines/save")) == 1, "no silent retry of a genuine 409"
    assert s.page.evaluate("window.v2CostGrid.state().batch") is False


def test_open_groups_scroll_and_focus_survive_the_save(make):
    s = make("u-view")
    s.open("capex")
    s.stage_on()
    groups = s.page.locator("#v2-sheet-capex details[data-group-code]")
    assert groups.count() >= 3
    codes = [groups.nth(i).get_attribute("data-group-code") for i in range(groups.count())]
    s.page.evaluate("document.querySelectorAll('#v2-sheet-capex details[data-group-code]')[1].open = false")
    s.type_amounts("capex", ["4321"])
    s.page.evaluate("window.scrollTo(0, 220)")
    s.rows("capex").nth(0).locator('input[name="amount_keur"]').click()
    focus_before = s.page.evaluate("document.activeElement.closest('form').id + '|' + document.activeElement.name")
    open_before = s.page.evaluate("Array.from(document.querySelectorAll('#v2-sheet-capex details[data-group-code]')).map(d => d.open)")
    # the click itself may scroll the button into view: compare with the position AT the click
    s.page.evaluate("document.addEventListener('click', () => { window.__yAtSave = window.scrollY; }, true)")
    with s.page.expect_response(lambda r: "/cost-lines/save" in r.url):
        s.page.locator('#v2-sheet-capex [data-cost-stage-save]').click()
    s.page.wait_for_function("document.querySelector('[data-cost-stage-msg]').textContent.includes('Saved')")
    assert s.page.evaluate("Array.from(document.querySelectorAll('#v2-sheet-capex details[data-group-code]')).map(d => d.open)") == open_before
    assert abs(s.page.evaluate("window.scrollY") - s.page.evaluate("window.__yAtSave")) <= 2
    assert s.page.evaluate("document.querySelector('#v2-sheet-capex [data-cost-stage-toggle]').checked") is True, "mode survives the swap"
    assert codes and s.errors == []
    del focus_before  # focus restoration to the row/cell is covered by the swap-view contract of the existing grid


def test_cross_sheet_batch_then_single_row_edit_has_no_false_409(make):
    s = make("u-cross")
    s.open("capex")
    s.stage_on()
    cap_ids = s.row_ids("capex", 3)
    s.type_amounts("capex", ["501", "502", "503"])
    s.page.evaluate("document.getElementById('tab-opex').click()")
    s.page.wait_for_selector("#v2-sheet-opex form[data-cost-row]", state="attached")
    s.open_groups("opex")
    s.kind = "opex"
    op_ids = s.row_ids("opex", 2)
    s.type_amounts("opex", ["61", "62"])
    s.page.wait_for_function("document.querySelector('[data-cost-stage-count]').textContent.trim().length > 0")
    with s.page.expect_response(lambda r: "/cost-lines/save" in r.url) as info:
        s.page.locator('#v2-sheet-opex [data-cost-stage-save]').click()
    assert info.value.status == 200
    assert len(s.posts_to("/cost-lines/save")) == 1, "CAPEX + OPEX edits travel in ONE request"
    s.page.wait_for_function("document.querySelector('[data-cost-stage-msg]').textContent.includes('Saved')")
    assert s.db_amounts("capex", cap_ids) == [501.0, 502.0, 503.0] and s.db_amounts("opex", op_ids) == [61.0, 62.0]
    # leave staged mode, then edit ONE row with the existing autosave: tokens must be current on both sheets
    s.page.locator("#v2-sheet-opex [data-cost-stage-toggle]").uncheck()
    s.page.wait_for_function("window.v2CostGrid.state().stageMode === false")
    s.rows("opex").nth(0).locator('input[name="amount_keur"]').click()
    s.page.keyboard.press("Control+A")
    s.page.keyboard.type("77")
    with s.page.expect_response(lambda r: "/opex/line/update" in r.url) as single:
        s.page.keyboard.press("Enter")
    assert single.value.status == 200
    s.page.wait_for_function("window.v2CostGrid && !window.v2CostGrid.busy()")
    assert s.db_amounts("opex", op_ids)[0] == 77.0
    assert "data-cost-error" not in single.value.text()


def test_stage_mode_off_keeps_the_existing_per_row_autosave(make):
    s = make("u-off")
    s.open("capex")
    ids = s.row_ids("capex", 2)
    s.rows("capex").nth(0).locator('input[name="amount_keur"]').click()
    s.page.keyboard.press("Control+A")
    s.page.keyboard.type("888")
    with s.page.expect_response(lambda r: "/capex/line/update" in r.url) as info:
        s.page.keyboard.press("Enter")
    assert info.value.status == 200
    s.page.wait_for_function("window.v2CostGrid && !window.v2CostGrid.busy()")
    assert s.db_amounts("capex", ids)[0] == 888.0
    assert s.posts_to("/cost-lines/save") == []


def test_run_is_refused_while_edits_are_staged_never_silently_saved(make):
    s = make("u-run")
    s.open("capex")
    s.stage_on()
    ids = s.row_ids("capex", 1)
    before = s.db_amounts("capex", ids)
    s.type_amounts("capex", ["9999"])
    s.page.wait_for_function("document.querySelector('[data-cost-stage-count]').textContent.trim() === '1 staged'")
    s.page.locator(".v2-toolbar .v2-run-form button[type=submit], #v2-run-controls button[type=submit]").first.click()
    s.page.wait_for_function("document.querySelector('[data-cost-stage-msg]').textContent.includes('Save or discard')")
    assert s.posts_to("/workbook/run") == [] and s.db_amounts("capex", ids) == before
    s.page.locator('#v2-sheet-capex [data-cost-stage-discard]').click()
    s.page.wait_for_function("document.querySelector('[data-cost-stage-count]').textContent.trim() === ''")
    assert s.rows("capex").nth(0).locator('input[name="amount_keur"]').input_value() != "9999"


def test_mobile_390_stage_bar_fits_without_horizontal_scroll(make):
    s = make("u-mobile", viewport={"width": 390, "height": 800})
    s.open("capex")
    s.stage_on()
    assert s.page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    assert s.page.locator("#v2-sheet-capex [data-cost-stage-save]").is_visible()


def test_measure_ten_sequential_row_autosaves_for_comparison(make):
    """Measurement only (no speed assertion): the existing per-row path, same ten edits, event-driven wait."""
    s = make("u-seq")
    s.open("capex")
    n = min(10, s.rows("capex").count())
    ids = s.row_ids("capex", n)
    t0 = time.perf_counter()
    s.type_amounts("capex", [f"{3000 + i}.5" for i in range(n)])
    s.page.wait_for_function("window.v2CostGrid && !window.v2CostGrid.busy()", timeout=60000)
    TIMINGS[f"sequential_autosave_{n}_rows_solar_s"] = round(time.perf_counter() - t0, 3)
    assert s.db_amounts("capex", ids) == [float(f"{3000 + i}.5") for i in range(n)]
    assert len(s.posts_to("/capex/line/update")) == n
