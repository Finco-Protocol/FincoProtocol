"""Workflow A — Excel-like CAPEX / OPEX direct-cell editing in a REAL Chromium.

Every interaction below is a genuine browser event (mouse click, Ctrl+A, typing, Enter,
Shift+Enter, Escape, Tab, arrows) against a live uvicorn server running the real
application; persisted values are read back from the database.  Skipped when Playwright
or Chromium is unavailable.
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

PORT = 8794


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    import uvicorn
    from app.persistence import db

    mp = pytest.MonkeyPatch()
    mp.setattr(db, "DB_PATH", str(tmp_path_factory.mktemp("cost-grid") / "g.db"))
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
    """One authenticated browser page on a fresh, seeded synthetic project."""

    def __init__(self, live_server, browser, uid, template="generic_solar_reference", viewport=None):
        from app.auth import COOKIE_NAME, create_session_token
        from app.services.reference_seed_service import create_reference_seeded_project

        self.base = live_server
        self.rec = create_reference_seeded_project(
            user_id=uid, template_source=template, requested_name="Grid", capacity_mw=40.0)
        # bypass_csp: only so the AUTOMATION may evaluate wait predicates; the app CSP is untouched
        self.ctx = browser.new_context(viewport=viewport or {"width": 1440, "height": 1000}, bypass_csp=True)
        self.ctx.add_cookies([{"name": COOKIE_NAME,
                               "value": create_session_token(user_id=uid, username="admin"),
                               "url": live_server}])
        self.page = self.ctx.new_page()
        self.page.on("dialog", lambda d: d.accept())
        self.updates = []
        self.page.on("request", lambda r: self.updates.append(r.url.rsplit(str(PORT), 1)[-1])
                     if r.method == "POST" and "/line/update" in r.url else None)

    def open(self, kind):
        self.kind = kind
        self.page.goto(f"{self.base}/v2/workbook?project={self.rec.project_code}")
        self.page.wait_for_selector(f"#tab-{kind}")
        self.page.evaluate(f"document.getElementById('tab-{kind}').click()")
        self.page.wait_for_selector(f"#v2-sheet-{kind} form[data-cost-row]", state="attached")
        self.open_groups()

    def open_groups(self):
        self.page.evaluate(
            f"document.querySelectorAll('#v2-sheet-{self.kind} details[data-group-code]')"
            ".forEach(d => d.open = true)")

    def rows(self):
        return self.page.locator(f"#v2-sheet-{self.kind} form[data-cost-row]")

    def amount(self, i):
        return self.rows().nth(i).locator('input[name="amount_keur"]')

    def rid(self, i):
        return self.rows().nth(i).get_attribute("id")

    def wait_idle(self, timeout=20000):
        self.page.wait_for_function("window.v2CostGrid && !window.v2CostGrid.busy()", timeout=timeout)
        self.page.wait_for_timeout(150)

    def wait_saved_value(self, rid, value, field="amount_keur", timeout=20000):
        self.page.wait_for_function(
            "([id, f, v]) => { const i = document.querySelector('#' + id + ' input[name=' + f + ']');"
            " return i && i.dataset.original === v && i.value === v; }",
            arg=[rid, field, value], timeout=timeout)

    def db_amount(self, rid):
        from app.persistence.db import get_cursor

        table = "capex_sub_lines" if self.kind == "capex" else "opex_sub_lines"
        sid = rid.split("-row-", 1)[1]
        with get_cursor() as cur:
            cur.execute(f"SELECT amount_keur FROM {table} WHERE sub_line_id=?", (sid,))
            return cur.fetchone()["amount_keur"]

    def state(self):
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


# ──────────────────────────────── keyboard edit matrix ───────────────────────────────

@pytest.mark.parametrize("kind", ["capex", "opex"])
def test_ctrl_a_then_type_replaces_the_value_ten_out_of_ten(make, kind):
    s = make(f"u-grid-ctrla-{kind}")
    s.open(kind)
    ok = 0
    for i in range(10):
        rid = s.rid(i)
        cell = s.amount(i)
        cell.click()
        s.page.keyboard.press("Control+A")
        s.page.keyboard.type(str(2000 + i))
        s.page.keyboard.press("Enter")
        s.wait_saved_value(rid, str(2000 + i))
        assert s.db_amount(rid) == 2000 + i
        ok += 1
    assert ok == 10


@pytest.mark.parametrize("kind", ["capex", "opex"])
def test_ten_consecutive_keyboard_only_edits_none_lost(make, kind):
    s = make(f"u-grid-kb-{kind}")
    s.open(kind)
    rids = [s.rid(i) for i in range(10)]
    s.amount(0).click()                       # first focus selects the value
    for i in range(10):
        s.page.keyboard.type(str(3100 + i))   # no Ctrl+A / Delete needed
        s.page.keyboard.press("Enter")        # commits and advances to the next row
    s.wait_idle()
    for i, rid in enumerate(rids):
        s.wait_saved_value(rid, str(3100 + i))
        assert s.db_amount(rid) == 3100 + i
    assert len(s.updates) == 10               # exactly one write per row


def test_enter_advances_shift_enter_goes_back_escape_discards(make):
    s = make("u-grid-nav")
    s.open("capex")
    first_name = lambda: s.page.evaluate("document.activeElement.closest('form').id")
    s.amount(2).click()
    start = first_name()
    s.page.keyboard.press("Enter")
    assert first_name() == s.rid(3) and first_name() != start
    s.page.keyboard.press("Shift+Enter")
    assert first_name() == s.rid(2)
    # Escape discards an uncommitted edit and sends nothing
    before = s.amount(2).input_value()
    s.page.keyboard.type("987654")
    assert s.amount(2).input_value() == "987654"
    s.page.keyboard.press("Escape")
    assert s.amount(2).input_value() == before
    s.page.wait_for_timeout(500)
    assert s.updates == []


def test_tab_and_shift_tab_move_across_cells_and_commit_on_leaving_the_row(make):
    s = make("u-grid-tab")
    s.open("capex")
    name = lambda: s.page.evaluate("document.activeElement.name || document.activeElement.className")
    s.amount(1).click()
    assert name() == "amount_keur"
    s.page.keyboard.press("Shift+Tab")
    assert name() == "label"
    s.page.keyboard.press("Tab")
    assert name() == "amount_keur"
    s.page.keyboard.type("4242")
    s.page.keyboard.press("Tab")               # to the row's action buttons: still the same row
    s.page.wait_for_timeout(300)
    assert s.updates == []
    # leave the row: commits exactly once
    for _ in range(3):
        s.page.keyboard.press("Tab")
    s.wait_idle()
    assert len(s.updates) == 1
    assert s.db_amount(s.rid(1)) == 4242


def test_arrow_keys_adjust_numbers_and_move_between_rows_in_text_cells(make):
    s = make("u-grid-arrows")
    s.open("opex")
    cell = s.amount(0)
    cell.click()
    s.page.keyboard.type("100")
    s.page.keyboard.press("ArrowUp")
    assert cell.input_value() == "101"
    s.page.keyboard.press("Shift+ArrowUp")
    assert cell.input_value() == "111"
    s.page.keyboard.press("ArrowDown")
    assert cell.input_value() == "110"
    s.page.keyboard.press("Escape")
    s.rows().nth(1).locator('input[name="label"]').click()
    s.page.keyboard.press("ArrowUp")
    assert s.page.evaluate("document.activeElement.closest('form').id") == s.rid(0)


def test_opex_escalation_cell_is_editable_and_persisted(make):
    s = make("u-grid-escl", template="generic_wind_reference")
    s.open("opex")
    rid = s.rid(0)
    esc = s.rows().nth(0).locator('input[name="inflation_pct"]')
    esc.click()
    s.page.keyboard.press("Control+A")
    s.page.keyboard.type("3.5")
    s.page.keyboard.press("Enter")
    s.wait_saved_value(rid, "3.5", field="inflation_pct")
    from app.persistence.db import get_cursor

    with get_cursor() as cur:
        cur.execute("SELECT inflation_pct FROM opex_sub_lines WHERE sub_line_id=?", (rid.split("-row-", 1)[1],))
        assert cur.fetchone()["inflation_pct"] == 3.5


# ─────────────────────────── write discipline / focus / scroll ───────────────────────

def test_enter_then_blur_sends_exactly_one_write(make):
    s = make("u-grid-once")
    s.open("capex")
    rid = s.rid(0)
    s.amount(0).click()
    s.page.keyboard.type("5150")
    s.page.keyboard.press("Enter")
    s.page.keyboard.press("Enter")             # focus moved; a second Enter is a no-op
    s.page.mouse.click(5, 5)                   # blur
    s.wait_idle()
    s.wait_saved_value(rid, "5150")
    assert len(s.updates) == 1


def test_focus_scroll_and_open_groups_are_stable_after_a_save(make):
    s = make("u-grid-stable", viewport={"width": 1280, "height": 700})
    s.open("capex")
    s.page.evaluate("document.querySelectorAll('#v2-sheet-capex details[data-group-code]').forEach((d,i)=>{d.open = i < 6;})")
    open_before = s.page.evaluate("[...document.querySelectorAll('#v2-sheet-capex details[data-group-code]')].map(d => d.open)")
    s.rows().nth(4).scroll_into_view_if_needed()
    s.page.evaluate("window.scrollBy(0, 40)")
    y_before = s.page.evaluate("window.scrollY")
    s.amount(4).click()
    s.page.keyboard.type("6001")
    s.page.keyboard.press("Enter")
    s.wait_saved_value(s.rid(4), "6001")
    y_after = s.page.evaluate("window.scrollY")
    assert abs(y_after - y_before) <= 60                # the page was not re-laid out from the top
    assert s.page.evaluate("[...document.querySelectorAll('#v2-sheet-capex details[data-group-code]')].map(d => d.open)") == open_before
    assert s.page.evaluate("document.activeElement.closest('form') && document.activeElement.closest('form').id") == s.rid(5)


def test_a_save_replaces_only_its_row_other_dirty_rows_keep_their_typing(make):
    s = make("u-grid-others")
    s.open("capex")
    s.amount(1).click()
    s.page.keyboard.type("7001")               # row 1: dirty, uncommitted
    s.amount(0).click()                         # leaving row 1 commits it...
    s.page.keyboard.type("7000")
    s.page.keyboard.press("Enter")
    s.wait_idle()
    s.wait_saved_value(s.rid(0), "7000")
    s.wait_saved_value(s.rid(1), "7001")
    assert (s.db_amount(s.rid(0)), s.db_amount(s.rid(1))) == (7000, 7001)
    assert len(s.updates) == 2


# ──────────────────────────── validation and failure behaviour ───────────────────────

def test_invalid_number_is_rejected_locally_and_sends_nothing(make):
    s = make("u-grid-invalid")
    s.open("capex")
    s.amount(0).click()
    s.page.keyboard.type("12abc")
    s.page.keyboard.press("Enter")
    s.page.wait_for_timeout(400)
    assert s.updates == []
    assert "Enter a number" in s.rows().nth(0).locator("[data-cost-state]").inner_text()


def test_genuine_conflict_is_reported_keeps_the_typed_value_and_never_retries(make):
    s = make("u-grid-409")
    s.open("capex")
    rid = s.rid(0)
    original = s.db_amount(rid)
    # another actor edits the same row first (same session cookie, real endpoint)
    form = s.page.evaluate(f"""() => Object.fromEntries([...new FormData(document.getElementById('{rid}'))])""")
    form["amount_keur"] = "111"
    r = s.page.request.post(f"{s.base}/v2/capex/line/update", form=form, headers={"HX-Request": "true"})
    assert r.status == 200 and s.db_amount(rid) == 111
    # the stale page now edits the same row
    s.amount(0).click()
    s.page.keyboard.type("222")
    s.page.keyboard.press("Enter")
    s.page.wait_for_function(
        f"document.getElementById('{rid}').getAttribute('data-save-state') === 'failed'", timeout=15000)
    assert s.db_amount(rid) == 111                           # nothing was overwritten
    assert s.amount(0).input_value() == "222"                # the user's value is kept
    s.page.wait_for_timeout(1500)
    assert len(s.updates) == 1                               # no automatic retry
    # an explicit Enter now succeeds with the refreshed tokens
    s.amount(0).click()
    s.page.keyboard.press("Enter")
    s.wait_saved_value(rid, "222")
    assert s.db_amount(rid) == 222 and len(s.updates) == 2
    assert original != 222


def test_failed_row_is_not_resubmitted_by_blur(make):
    s = make("u-grid-noresubmit")
    s.open("capex")
    rid = s.rid(0)
    form = s.page.evaluate(f"""() => Object.fromEntries([...new FormData(document.getElementById('{rid}'))])""")
    form["amount_keur"] = "333"
    s.page.request.post(f"{s.base}/v2/capex/line/update", form=form, headers={"HX-Request": "true"})
    s.amount(0).click()
    s.page.keyboard.type("444")
    s.page.keyboard.press("Enter")
    s.page.wait_for_function(
        f"document.getElementById('{rid}').getAttribute('data-save-state') === 'failed'", timeout=15000)
    s.amount(0).click()
    s.page.mouse.click(5, 5)                                  # focus and blur the failed cell
    s.page.wait_for_timeout(800)
    assert len(s.updates) == 1


# ──────────────────────── financial lifecycle through the real UI ────────────────────

@pytest.mark.parametrize("kind", ["capex", "opex"])
def test_save_marks_stale_then_run_makes_current_and_totals_follow(make, kind):
    s = make(f"u-grid-life-{kind}")
    s.open(kind)
    s.page.click('[data-testid="v2-run-btn"]')
    s.page.wait_for_function(
        "document.querySelector('[data-testid=\"toolbar-runtime-state\"]').innerText.trim() === 'Current'",
        timeout=120000)
    s.open(kind)
    total_sel = ('[data-testid="total-capex-keur"]' if kind == "capex" else '[data-testid="opex-y1-total"]')
    total_before = float(s.page.locator(total_sel).first.inner_text().replace(",", "").strip())
    rid = s.rid(0)
    old = s.db_amount(rid)
    s.amount(0).click()
    s.page.keyboard.type(str(int(old) + 100))
    s.page.keyboard.press("Enter")
    s.wait_idle()
    s.wait_saved_value(rid, str(int(old) + 100))
    assert s.state() == "Stale"                               # economic edit -> Last Run is stale
    total_after = float(s.page.locator(total_sel).first.inner_text().replace(",", "").strip())
    assert total_after - total_before == pytest.approx(100, abs=1.5)   # exactly the edit (whole-kEUR display); no hidden contingency
    s.open(kind)                                              # a full server render shows the SAME total
    assert float(s.page.locator(total_sel).first.inner_text().replace(",", "").strip()) == total_after
    s.page.click('[data-testid="v2-run-btn"]')
    s.page.wait_for_function(
        "document.querySelector('[data-testid=\"toolbar-runtime-state\"]').innerText.trim() === 'Current'",
        timeout=120000)


def test_run_with_an_uncommitted_edit_saves_first_then_runs(make):
    s = make("u-grid-runwait")
    s.open("capex")
    s.page.click('[data-testid="v2-run-btn"]')
    s.page.wait_for_function(
        "document.querySelector('[data-testid=\"toolbar-runtime-state\"]').innerText.trim() === 'Current'",
        timeout=120000)
    s.open("capex")
    rid = s.rid(0)
    s.amount(0).click()
    s.page.keyboard.type("8123")               # typed, never committed
    s.page.click('[data-testid="v2-run-btn"]')  # Run must save it first, then run
    s.wait_saved_value(rid, "8123", timeout=60000)
    s.page.wait_for_function(
        "document.querySelector('[data-testid=\"toolbar-runtime-state\"]').innerText.trim() === 'Current'",
        timeout=120000)
    assert s.db_amount(rid) == 8123


def test_first_save_after_a_scenario_switch_has_no_false_409(make):
    s = make("u-grid-scen")
    s.page.goto(f"{s.base}/v2/workbook?project={s.rec.project_code}")
    s.page.wait_for_selector("#tab-scenarios")
    r = s.page.request.post(f"{s.base}/v2/workbook/scenarios/create",
                            form={"project": s.rec.project_code, "scenario_name": "Grid Case"},
                            headers={"HX-Request": "true"})
    assert r.status == 200
    s.page.goto(f"{s.base}/v2/workbook?project={s.rec.project_code}")
    s.page.evaluate("document.getElementById('tab-scenarios').click()")
    select = s.page.locator('#v2-sheet-scenarios form[hx-post="/v2/workbook/scenarios/select"] button').first
    select.click()
    s.page.wait_for_timeout(1200)
    s.open("capex")
    rid = s.rid(0)
    s.amount(0).click()
    s.page.keyboard.type("9191")
    s.page.keyboard.press("Enter")
    s.wait_saved_value(rid, "9191")
    assert s.db_amount(rid) == 9191
    assert s.rows().nth(0).get_attribute("data-save-state") != "failed"


def test_deactivate_and_reactivate_keep_open_groups_and_persist(make):
    s = make("u-grid-lifecycle")
    s.open("opex")
    rid = s.rid(0)
    sid = rid.split("-row-", 1)[1]
    s.page.evaluate("document.querySelectorAll('#v2-sheet-opex details[data-group-code]').forEach((d,i)=>{d.open = i < 3;})")
    s.rows().nth(0).locator("button.v2-opex-deactivate-btn").click()
    s.page.wait_for_selector(f'[data-testid="opex-reactivate-{sid}"]', state="attached", timeout=15000)
    assert s.page.evaluate("[...document.querySelectorAll('#v2-sheet-opex details[data-group-code]')].map(d=>d.open).slice(0,3)") == [True, True, True]
    s.page.evaluate(f"document.querySelector('[data-testid=\"opex-reactivate-{sid}\"]').closest('details').open = true")
    s.page.click(f'[data-testid="opex-reactivate-{sid}"]')
    s.page.wait_for_selector(f"#opex-row-{sid}", state="attached", timeout=15000)


def test_duplicate_creates_a_distinct_custom_line(make):
    s = make("u-grid-dup")
    s.open("capex")
    n = s.rows().count()
    s.rows().nth(0).locator("button.v2-capex-duplicate-btn").click()
    s.page.wait_for_function(
        f"document.querySelectorAll('#v2-sheet-capex form[data-cost-row]').length === {n + 1}", timeout=15000)
    labels = s.page.eval_on_selector_all(
        '#v2-sheet-capex form[data-cost-row] input[name="label"]', "els => els.map(e => e.value)")
    assert any(l.endswith("(copy)") for l in labels)


def test_reference_project_is_read_only_no_inputs(make, live_server, browser):
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence.projects_repository import get_reference_by_template_source

    ref = get_reference_by_template_source("generic_solar_reference")
    s = make("u-grid-ref")
    page = s.page
    page.goto(f"{s.base}/v2/workbook?project={ref.project_code}")
    page.wait_for_selector("#tab-capex")
    assert page.locator("input[data-cost-cell]").count() == 0


TECHS = ["generic_solar_reference", "generic_wind_reference",
         "generic_data_center_reference", "generic_ev_charging_reference"]


@pytest.mark.parametrize("kind", ["capex", "opex"])
@pytest.mark.parametrize("template", TECHS)
def test_every_technology_edit_by_keyboard_stale_run_current(make, template, kind):
    """Solar / Wind / Data Center / EV: edit in the grid -> Stale -> Run -> Current,
    persisted value read back from the database (proportionate +1 so the engine's own
    plausibility checks are not the subject of this test)."""
    s = make(f"u-grid-tech-{kind}-{template[8:12]}", template=template)
    s.open(kind)
    s.page.click('[data-testid="v2-run-btn"]')
    s.page.wait_for_function(
        "document.querySelector('[data-testid=\"toolbar-runtime-state\"]').innerText.trim() === 'Current'",
        timeout=120000)
    s.open(kind)
    rid = s.rid(0)
    old = s.db_amount(rid)
    new = str(int(round(old)) + 1)
    s.amount(0).click()
    s.page.keyboard.press("Control+A")
    s.page.keyboard.type(new)
    s.page.keyboard.press("Enter")
    s.wait_idle()
    s.wait_saved_value(rid, new)
    assert s.db_amount(rid) == int(round(old)) + 1
    assert s.state() == "Stale"
    s.page.click('[data-testid="v2-run-btn"]')
    s.page.wait_for_function(
        "document.querySelector('[data-testid=\"toolbar-runtime-state\"]').innerText.trim() === 'Current'",
        timeout=120000)


def test_editing_one_cell_does_not_round_another_stored_value(make):
    """Wind OPEX line 1 is stored as 41.666666...; the cell shows 41.6667. Changing only the
    description must not overwrite the stored amount with the rounded display text."""
    s = make("u-grid-exact", template="generic_wind_reference")
    s.open("opex")
    rid = s.rid(0)
    before = s.db_amount(rid)
    assert before != round(before, 4)
    lab = s.rows().nth(0).locator('input[name="label"]')
    lab.click()
    s.page.keyboard.press("Control+A")
    s.page.keyboard.type("Renamed line")
    s.page.keyboard.press("Enter")
    s.wait_idle()
    s.page.wait_for_function(
        f"document.querySelector('#{rid} input[name=label]').dataset.original === 'Renamed line'")
    assert s.db_amount(rid) == before


# ───────── acceptance integrity: the row-form Deactivate button (was a separate form) ─────────

def _record_line_posts(s):
    posts = []

    def on_request(r):
        if r.method == "POST" and "/line/" in r.url:
            posts.append((r.url.rsplit("/line/", 1)[1], dict(
                pair.split("=", 1) for pair in (r.post_data or "").split("&") if "=" in pair)))

    s.page.on("request", on_request)
    return posts


def _unquote(v):
    from urllib.parse import unquote_plus
    return unquote_plus(v)


@pytest.mark.parametrize("kind,btn", [("capex", "button.v2-capex-deactivate-btn"),
                                      ("opex", "button.v2-opex-deactivate-btn")])
def test_deactivate_button_posts_deactivate_with_exact_guard_fields_and_reactivate_restores(make, kind, btn):
    from app.persistence.db import get_cursor
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get

    uid = f"u-grid-deact-{kind}"
    s = make(uid)
    s.open(kind)
    posts = _record_line_posts(s)
    rid = s.rid(0)
    sid = rid.split("-row-", 1)[1]
    table = "capex_sub_lines" if kind == "capex" else "opex_sub_lines"
    with get_cursor() as cur:
        cur.execute(f"SELECT updated_at, amount_keur FROM {table} WHERE sub_line_id=?", (sid,))
        row = cur.fetchone()
    version, amount = row["updated_at"], row["amount_keur"]
    comp = assemble_consistent_for_get(uid, s.rec.project_id, WORKBOOK.version).composite_hash
    total_sel = '[data-testid="total-capex-keur"]' if kind == "capex" else '[data-testid="opex-y1-total"]'
    before = float(s.page.locator(total_sel).first.inner_text().replace(",", ""))

    s.rows().nth(0).locator(btn).click()
    s.page.wait_for_selector(f'[data-testid="{kind}-reactivate-{sid}"]', state="attached", timeout=15000)

    assert [p[0] for p in posts] == ["deactivate"]                    # the deactivate command, once; no update
    fields = {k: _unquote(v) for k, v in posts[0][1].items()}
    assert fields["project"] == s.rec.project_code
    assert fields["sub_line_id"] == sid
    assert fields["row_version"] == version                           # current row_version token
    assert fields["content_hash"] == comp                             # current composite identity
    assert fields["workbook_version"] == WORKBOOK.version
    with get_cursor() as cur:
        cur.execute(f"SELECT is_active, amount_keur FROM {table} WHERE sub_line_id=?", (sid,))
        r = cur.fetchone()
    assert r["is_active"] == 0 and r["amount_keur"] == amount         # soft state change, value untouched
    after = float(s.page.locator(total_sel).first.inner_text().replace(",", ""))
    assert after < before                                             # excluded from active totals
    assert s.page.locator(f"#{rid}").count() == 0                     # the row left the active grid

    s.page.evaluate(f"document.querySelector('[data-testid=\"{kind}-reactivate-{sid}\"]').closest('details').open = true")
    s.page.click(f'[data-testid="{kind}-reactivate-{sid}"]')
    s.page.wait_for_selector(f"#{rid}", state="attached", timeout=15000)
    assert [p[0] for p in posts] == ["deactivate", "reactivate"]
    with get_cursor() as cur:
        cur.execute(f"SELECT is_active, amount_keur FROM {table} WHERE sub_line_id=?", (sid,))
        r = cur.fetchone()
    assert r["is_active"] == 1 and r["amount_keur"] == amount
    assert float(s.page.locator(total_sel).first.inner_text().replace(",", "")) == pytest.approx(before)


def test_deactivate_with_a_stale_identity_fails_closed_in_the_browser(make):
    from app.persistence.db import get_cursor

    s = make("u-grid-deact-stale")
    s.open("capex")
    posts = _record_line_posts(s)
    rid0, rid1 = s.rid(0), s.rid(1)
    # another actor changes the workbook (row 1) after this page was rendered
    form = s.page.evaluate(f"() => Object.fromEntries([...new FormData(document.getElementById('{rid1}'))])")
    form["amount_keur"] = "123"
    assert s.page.request.post(f"{s.base}/v2/capex/line/update", form=form,
                               headers={"HX-Request": "true"}).status == 200
    s.rows().nth(0).locator("button.v2-capex-deactivate-btn").click()
    s.page.wait_for_selector('#v2-capex-feedback [data-cost-error="true"]', state="attached", timeout=15000)
    sid0 = rid0.split("-row-", 1)[1]
    with get_cursor() as cur:
        cur.execute("SELECT is_active FROM capex_sub_lines WHERE sub_line_id=?", (sid0,))
        assert cur.fetchone()["is_active"] == 1                       # nothing was mutated
    assert [p[0] for p in posts] == ["deactivate"]                    # and nothing was retried


def test_uncommitted_edit_is_saved_before_a_deactivate_runs(make):
    s = make("u-grid-deact-order")
    s.open("capex")
    posts = _record_line_posts(s)
    rid1 = s.rid(1)
    s.amount(1).click()
    s.page.keyboard.type("6543")                                      # typed, never committed
    s.rows().nth(0).locator("button.v2-capex-deactivate-btn").click()
    s.page.wait_for_function("document.querySelectorAll('#v2-sheet-capex form[data-cost-row]').length > 0")
    s.wait_idle(timeout=30000)
    s.page.wait_for_timeout(1500)
    assert [p[0] for p in posts][:2] == ["update", "deactivate"]       # saved first, then the structural action
    assert s.db_amount(rid1) == 6543
