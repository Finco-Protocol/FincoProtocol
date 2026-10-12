"""Cost editing UX V2 — batch editing as the default, in a REAL Chromium.

Covers what this change adds on top of the existing guarded row Save (#225), the atomic batch Save (#250),
the hybrid Inputs Grid (#245) and the consolidated navigation (#248):

* staged (batch) editing is the default, the per-row immediate mode is an explicit, remembered choice;
* no network write happens before the deliberate Save, and one Save is one atomic request;
* the stale-authority defect (an OPEX save left the CAPEX authority element stale, so the next batch Save
  presented an old composite hash) stays fixed;
* Esc discards only the current cell, Ctrl+S saves, the keyboard alone is enough;
* unresolved staged edits are never lost to a scenario switch or a Run: a visible Save / Discard / Stay choice;
* scroll and focus survive the Save; light and dark text stay legible; 390 px works;
* Inputs Grid values that belong to cost lines link to the owning category and are NOT editable there.

Real mouse/keyboard events against a live uvicorn server and synthetic disposable working copies; waits are
event-driven.  Skipped when Playwright or Chromium is unavailable.
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")

from tests.test_cost_batch_save_browser_v1 import (  # noqa: E402,F401  (fixtures + the shared session helper)
    VERTICALS, Session, browser, live_server,
)

CONTRAST_JS = """
(sel) => {
  const el = document.querySelector(sel);
  const parse = (c) => c.match(/[\\d.]+/g).map(Number);
  const lum = ([r, g, b]) => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const cs = getComputedStyle(el);
  let bg = parse(cs.backgroundColor), node = el;
  while ((bg.length === 4 && bg[3] === 0) && node.parentElement) { node = node.parentElement; bg = parse(getComputedStyle(node).backgroundColor); }
  const fg = parse(cs.color), a = lum(bg.slice(0, 3)), b = lum(fg.slice(0, 3));
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}
"""


class UxSession(Session):
    def stage_state(self):
        return self.page.evaluate("window.v2CostGrid.state()")

    def immediate_on(self):
        box = self.page.locator("[data-cost-stage-toggle]:visible").first
        box.uncheck()
        self.page.wait_for_function("window.v2CostGrid.state().stageMode === false")

    def save_click(self, kind=None):
        self.page.locator(f"#v2-sheet-{kind or self.kind} [data-cost-stage-save]").click()

    def wait_saved_message(self):
        self.page.wait_for_function(
            "[...document.querySelectorAll('[data-cost-stage-msg]')].some(e => /Saved \\d+ lines/.test(e.textContent))")

    def switch(self, kind):
        self.page.evaluate(f"document.getElementById('tab-{kind}').click()")
        self.page.wait_for_selector(f"#v2-sheet-{kind} form[data-cost-row]", state="attached")
        self.open_groups(kind)
        self.kind = kind

    def history_rows(self):
        from app.persistence.db import get_cursor

        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM model_run_history WHERE project_id=?", (self.rec.project_id,))
            return cur.fetchone()["n"]


@pytest.fixture
def make(live_server, browser):
    made = []

    def _make(uid, **kw):
        s = UxSession(live_server, browser, uid, **kw)
        made.append(s)
        return s

    yield _make
    for s in made:
        s.close()


# ── batch editing is the default ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("template", VERTICALS)
def test_batch_is_the_default_four_opex_edits_are_one_atomic_request(make, template):
    s = make(f"u-ux-four-{template}", template=template)
    s.open("opex")
    assert s.stage_state()["stageMode"] is True
    assert s.page.locator("#v2-sheet-opex [data-cost-stage-toggle]").is_checked()
    ids = s.row_ids("opex", 4)
    before = s.db_amounts("opex", ids)
    s.type_amounts("opex", ["101.5", "102.25", "103", "104.125"])
    s.page.wait_for_function("document.querySelector('[data-cost-stage-count]').textContent.trim() === '4 staged'")
    assert s.posts == [], "no network write at all before the deliberate Save"
    assert s.db_amounts("opex", ids) == before
    with s.page.expect_response(lambda r: "/cost-lines/save" in r.url) as info:
        s.save_click()
    assert info.value.status == 200
    s.wait_saved_message()
    assert s.posts_to("/cost-lines/save") == ["/v2/workbook/grid/cost-lines/save"] and s.posts_to("/line/update") == []
    assert s.db_amounts("opex", ids) == [101.5, 102.25, 103.0, 104.125]
    assert s.errors == []


@pytest.mark.parametrize("template", VERTICALS)
def test_ten_mixed_capex_opex_edits_are_one_request_with_exact_values(make, template):
    s = make(f"u-ux-ten-{template}", template=template)
    s.open("capex")
    cap_ids, op_ids = s.row_ids("capex", 6), None
    cap_vals = ["1234.56789", "2000", "3000.5", "4000.25", "5000.125", "6000.0625"]
    s.type_amounts("capex", cap_vals)
    s.switch("opex")
    op_ids = s.row_ids("opex", 4)
    op_vals = ["11.11", "22.22", "33.33", "44.44"]
    s.type_amounts("opex", op_vals)
    assert s.posts == [], "ten staged edits across two sheets: still no network write"
    with s.page.expect_response(lambda r: "/cost-lines/save" in r.url):
        s.save_click("opex")
    s.wait_saved_message()
    assert len(s.posts_to("/cost-lines/save")) == 1, "one request for CAPEX + OPEX edits"
    assert s.db_amounts("capex", cap_ids) == [float(v) for v in cap_vals]
    assert s.db_amounts("opex", op_ids) == [float(v) for v in op_vals]
    assert s.history_rows() == 0, "Save never runs the model and never writes Run History"
    assert not [p for p in s.posts if "run" in p.lower().split("/")[-1]], "no financial recalculation"


def test_no_duplicate_save_from_double_click_or_repeated_shortcut(make):
    s = make("u-ux-dup")
    s.open("capex")
    s.type_amounts("capex", ["71", "72"])
    s.page.locator("#v2-sheet-capex [data-cost-stage-save]").dblclick()
    s.wait_saved_message()
    s.page.wait_for_timeout(400)
    assert len(s.posts_to("/cost-lines/save")) == 1


# ── the stale-authority defect stays fixed, in both directions ──────────────────────────────

def test_immediate_opex_save_then_staged_capex_save_is_not_a_false_409(make):
    s = make("u-ux-modeswitch")
    s.open("opex")
    s.immediate_on()
    s.rows("opex").nth(0).locator('input[name="amount_keur"]').click()
    s.page.keyboard.press("Control+A")
    s.page.keyboard.type("5555")
    with s.page.expect_response(lambda r: "/opex/line/update" in r.url) as first:
        s.page.keyboard.press("Enter")
    assert first.value.status == 200
    s.page.wait_for_function("window.v2CostGrid && !window.v2CostGrid.busy()")
    s.page.locator("[data-cost-stage-toggle]:visible").first.check()
    s.page.wait_for_function("window.v2CostGrid.state().stageMode === true")
    s.switch("capex")
    ids = s.row_ids("capex", 1)
    s.type_amounts("capex", ["4321"])
    with s.page.expect_response(lambda r: "/cost-lines/save" in r.url) as second:
        s.save_click()
    assert second.value.status == 200, "the CAPEX authority element must have been brought forward"
    assert s.db_amounts("capex", ids) == [4321.0]


def test_staged_opex_save_then_staged_capex_save_is_not_a_false_409(make):
    s = make("u-ux-twice")
    s.open("opex")
    s.type_amounts("opex", ["61"])
    with s.page.expect_response(lambda r: "/cost-lines/save" in r.url) as first:
        s.save_click()
    assert first.value.status == 200
    s.wait_saved_message()
    s.switch("capex")
    ids = s.row_ids("capex", 1)
    s.type_amounts("capex", ["62"])
    with s.page.expect_response(lambda r: "/cost-lines/save" in r.url) as second:
        s.save_click()
    assert second.value.status == 200
    assert s.db_amounts("capex", ids) == [62.0]


# ── immediate editing stays an explicit, remembered choice ─────────────────────────────────

def test_immediate_mode_is_an_explicit_choice_that_survives_a_reload(make):
    s = make("u-ux-immediate")
    s.open("capex")
    s.immediate_on()
    ids = s.row_ids("capex", 1)
    s.rows("capex").nth(0).locator('input[name="amount_keur"]').click()
    s.page.keyboard.press("Control+A")
    s.page.keyboard.type("888")
    with s.page.expect_response(lambda r: "/capex/line/update" in r.url) as info:
        s.page.keyboard.press("Enter")
    assert info.value.status == 200
    s.page.wait_for_function("window.v2CostGrid && !window.v2CostGrid.busy()")
    assert s.db_amounts("capex", ids) == [888.0] and s.posts_to("/cost-lines/save") == []
    s.page.reload()
    s.page.wait_for_function("window.v2CostGrid !== undefined")
    assert s.stage_state()["stageMode"] is False, "the explicit choice is remembered for this tab"
    assert not s.page.locator("[data-cost-stage-toggle]:visible").first.is_checked()
    s.page.locator("[data-cost-stage-toggle]:visible").first.check()
    s.page.wait_for_function("window.v2CostGrid.state().stageMode === true")


# ── keyboard-only editing, cell-level Esc, Ctrl+S ──────────────────────────────────────────

def test_keyboard_only_editing_esc_is_cell_level_and_ctrl_s_saves(make):
    s = make("u-ux-keys")
    s.open("capex")
    ids = s.row_ids("capex", 3)
    before = s.db_amounts("capex", ids)
    cells = [s.rows("capex").nth(i).locator('input[name="amount_keur"]') for i in range(3)]
    cells[0].focus()                                   # programmatic focus: no pointer needed from here on
    s.page.keyboard.type("111")
    s.page.keyboard.press("Enter")                     # commits row 0 (staged), moves to row 1
    s.page.keyboard.type("222")
    s.page.keyboard.press("Escape")                    # discards ONLY this cell edit
    assert cells[1].input_value() != "222"
    assert cells[0].input_value() == "111", "the staged cell is untouched by Esc in another cell"
    s.page.wait_for_function("document.querySelector('[data-cost-stage-count]').textContent.trim() === '1 staged'")
    s.page.keyboard.press("Enter")                     # nothing typed: moves on, stages nothing
    s.page.keyboard.type("333")
    s.page.keyboard.press("Shift+Enter")               # commit and go back up
    s.page.wait_for_function("document.querySelector('[data-cost-stage-count]').textContent.trim() === '2 staged'")
    assert s.posts == []
    with s.page.expect_response(lambda r: "/cost-lines/save" in r.url) as info:
        s.page.keyboard.press("Control+s")
    assert info.value.status == 200
    s.wait_saved_message()
    assert s.db_amounts("capex", ids) == [111.0, before[1], 333.0]
    assert s.page.evaluate("!!document.activeElement.matches('input[data-cost-cell]')"), "focus stays in the grid"


def test_invalid_value_blocks_the_save_without_losing_anything(make):
    s = make("u-ux-invalid")
    s.open("capex")
    ids = s.row_ids("capex", 2)
    before = s.db_amounts("capex", ids)
    s.type_amounts("capex", ["12", "abc"])
    s.save_click()
    s.page.wait_for_function("document.querySelector('[data-cost-stage-msg]').textContent.includes('nothing was saved')")
    assert s.posts == [] and s.db_amounts("capex", ids) == before
    typed = [s.rows("capex").nth(i).locator('input[name="amount_keur"]').input_value() for i in range(2)]
    assert typed == ["12", "abc"], "typed values are preserved after a validation failure"


# ── concurrency identity: stale composite hash and stale row version ───────────────────────

def _concurrent_row_edit(s, row_index, amount):
    tokens = s.page.evaluate("(() => { const sh = document.getElementById('v2-workbook-shell');"
                             " return [sh.dataset.contentHash, sh.dataset.workbookVersion]; })()")
    row = s.rows("capex").nth(row_index)
    resp = s.ctx.request.post(f"{s.base}/v2/capex/line/update", form={
        "project": s.rec.project_code, "sub_line_id": row.get_attribute("data-sub-line-id"),
        "label": row.locator('input[name="label"]').input_value(), "amount_keur": amount,
        "row_version": row.locator('input[name="row_version"]').input_value(),
        "workbook_version": tokens[1], "content_hash": tokens[0]}, headers={"HX-Request": "true"})
    assert resp.status == 200


def test_stale_composite_hash_is_rejected_when_a_different_row_changed(make):
    s = make("u-ux-stale-hash")
    s.open("capex")
    ids = s.row_ids("capex", 3)
    s.type_amounts("capex", ["31"])
    _concurrent_row_edit(s, 2, "777")                  # a row that is NOT staged moves the composite hash
    mid = s.db_amounts("capex", ids)
    with s.page.expect_response(lambda r: "/cost-lines/save" in r.url) as info:
        s.save_click()
    assert info.value.status == 409
    s.page.wait_for_function("document.querySelector('[data-cost-stage-msg]').textContent.includes('Nothing was saved')")
    assert s.db_amounts("capex", ids) == mid
    assert s.rows("capex").nth(0).locator('input[name="amount_keur"]').input_value() == "31"
    assert len(s.posts_to("/cost-lines/save")) == 1, "a genuine conflict is never retried"


def test_stale_row_version_is_rejected_and_rolls_everything_back(make):
    s = make("u-ux-stale-row")
    s.open("capex")
    ids = s.row_ids("capex", 3)
    s.type_amounts("capex", ["41", "42", "43"])
    _concurrent_row_edit(s, 1, "888")                  # a STAGED row changed underneath
    mid = s.db_amounts("capex", ids)
    with s.page.expect_response(lambda r: "/cost-lines/save" in r.url) as info:
        s.save_click()
    assert info.value.status == 409
    assert s.db_amounts("capex", ids) == mid, "fail-one is fail-all"
    assert [s.rows("capex").nth(i).locator('input[name="amount_keur"]').input_value() for i in range(3)] == ["41", "42", "43"]


def test_cross_project_foreign_line_and_protected_reference_are_denied(make):
    from app.auth import generate_csrf_token

    a, b = make("u-ux-owner-a"), make("u-ux-owner-b")
    a.open("capex")
    b.open("capex")
    foreign = b.row_ids("capex", 1)[0]
    b_before = b.db_amounts("capex", [foreign])
    tokens = a.page.evaluate("(() => { const sh = document.getElementById('v2-workbook-shell');"
                             " return [sh.dataset.contentHash, sh.dataset.workbookVersion]; })()")
    line = [{"kind": "capex", "sub_line_id": foreign, "row_version": "x", "label": "stolen", "amount_keur": "1"}]
    import json

    def post(project):
        return a.ctx.request.post(f"{a.base}/v2/workbook/grid/cost-lines/save", form={
            "project": project, "csrf_token": generate_csrf_token(), "workbook_version": tokens[1],
            "content_hash": tokens[0], "sheet": "capex", "payload": json.dumps(line)})

    assert post("no-such-project-xyz").status == 404, "an unknown or unowned project is not addressable"
    # both synthetic projects share the code "batch": it resolves to MY project, where B's line does not exist
    assert post(a.rec.project_code).status in (409, 422), "a foreign line id inside my own project is refused"
    assert b.db_amounts("capex", [foreign]) == b_before
    from app.persistence.projects_repository import resolve_accessible_project

    if resolve_accessible_project("u-ux-owner-a", "generic_solar_reference-reference")[0] is None:
        pytest.skip("reference project not seeded in this fixture")
    assert post("generic_solar_reference-reference").status == 403, "protected reference is read-only"


# ── nothing is lost to a scenario switch or a Run ───────────────────────────────────────────

def _make_scenario(s):
    r = s.page.request.post(f"{s.base}/v2/workbook/scenarios/create",
                            form={"project": s.rec.project_code, "scenario_name": "UX Case"},
                            headers={"HX-Request": "true"})
    assert r.status == 200
    s.open("capex")


def test_scenario_switch_with_staged_edits_offers_save_discard_or_stay(make):
    s = make("u-ux-scenario")
    s.page.goto(f"{s.base}/v2/workbook?project={s.rec.project_code}")
    s.page.wait_for_selector("#tab-scenarios", state="attached")
    _make_scenario(s)
    ids = s.row_ids("capex", 1)
    before = s.db_amounts("capex", ids)
    s.type_amounts("capex", ["9191"])
    s.page.evaluate("document.getElementById('tab-scenarios').click()")
    select = s.page.locator('#v2-sheet-scenarios form[hx-post="/v2/workbook/scenarios/select"] button').first
    select.click()
    s.page.wait_for_selector('[data-testid="cost-guard"]', state="visible")
    assert s.posts_to("/scenarios/select") == [], "the switch did not happen"
    s.page.locator('[data-testid="cost-guard-stay"]').click()
    assert s.page.locator('[data-testid="cost-guard"]').count() == 0 and s.db_amounts("capex", ids) == before
    select.click()
    s.page.wait_for_selector('[data-testid="cost-guard"]', state="visible")
    with s.page.expect_response(lambda r: "/cost-lines/save" in r.url) as saved:
        s.page.locator('[data-testid="cost-guard-save"]').click()
    assert saved.value.status == 200
    s.wait_saved_message()
    assert s.db_amounts("capex", ids) == [9191.0]
    with s.page.expect_response(lambda r: "/scenarios/select" in r.url) as switched:
        select.click()
    assert switched.value.status == 200


def test_run_with_staged_edits_is_refused_visibly_from_any_tab(make):
    s = make("u-ux-run")
    s.open("capex")
    ids = s.row_ids("capex", 1)
    before = s.db_amounts("capex", ids)
    s.type_amounts("capex", ["9999"])
    s.page.evaluate("document.getElementById('tab-project-setup') ? document.getElementById('tab-project-setup').click() : 0")
    s.page.locator(".v2-toolbar .v2-run-form button[type=submit], #v2-run-controls button[type=submit]").first.click()
    s.page.wait_for_selector('[data-testid="cost-guard"]', state="visible")
    assert [p for p in s.posts if p.endswith("/run") or "/workbook/run" in p] == []
    assert s.db_amounts("capex", ids) == before, "never silently saved"
    s.page.locator('[data-testid="cost-guard-discard"]').click()
    s.page.evaluate("document.getElementById('tab-capex').click()")
    assert s.rows("capex").nth(0).locator('input[name="amount_keur"]').input_value() != "9999"


def test_unsaved_edits_are_flagged_on_the_other_sheets_tab(make):
    s = make("u-ux-tabdot")
    s.open("opex")
    s.type_amounts("opex", ["12"])
    s.switch("capex")
    assert s.page.get_attribute("#tab-opex", "data-unsaved") == "1"
    assert s.page.get_attribute("#tab-capex", "data-unsaved") is None


# ── no unexpected scroll or focus reset; light/dark; mobile ────────────────────────────────

def test_scroll_and_focus_survive_a_keyboard_save(make):
    s = make("u-ux-scroll")
    s.open("capex")
    s.type_amounts("capex", ["4321"])
    s.rows("capex").nth(1).locator('input[name="amount_keur"]').focus()
    s.page.evaluate("window.scrollTo(0, 260)")
    y = s.page.evaluate("window.scrollY")
    with s.page.expect_response(lambda r: "/cost-lines/save" in r.url):
        s.page.keyboard.press("Control+s")
    s.wait_saved_message()
    assert abs(s.page.evaluate("window.scrollY") - y) <= 2
    assert s.page.evaluate("!!document.activeElement.matches('input[data-cost-cell]')")


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_staged_state_and_stage_bar_are_legible_in_light_and_dark(make, scheme):
    s = make(f"u-ux-{scheme}")
    s.page.emulate_media(color_scheme=scheme)
    s.open("capex")
    s.type_amounts("capex", ["1500"])
    s.page.wait_for_selector('#v2-sheet-capex form[data-cost-row][data-save-state="staged"]')
    for selector in ('#v2-sheet-capex form[data-save-state="staged"] input[name="amount_keur"]',
                     '#v2-sheet-capex [data-cost-stagebar]', '#v2-sheet-capex [data-cost-stage-save]',
                     '#v2-sheet-capex [id^="capex-cattotal-"] .v2-field-label'):
        ratio = s.page.evaluate(CONTRAST_JS, selector)
        assert ratio >= 4.5, f"{scheme}: {selector} contrast {ratio:.2f}"


def test_mobile_390_edit_and_save_work_without_horizontal_scroll(make):
    s = make("u-ux-mobile", viewport={"width": 390, "height": 844})
    s.open("capex")
    ids = s.row_ids("capex", 2)
    s.type_amounts("capex", ["61", "62"])
    assert s.page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    bar = s.page.evaluate("(() => { const b = document.querySelector('#v2-sheet-capex [data-cost-stagebar]');"
                          " return b.scrollWidth <= b.clientWidth + 1; })()")
    assert bar
    s.page.locator("#v2-sheet-capex [data-cost-stage-save]").scroll_into_view_if_needed()
    assert s.page.locator("#v2-sheet-capex [data-cost-stage-save]").is_visible()
    with s.page.expect_response(lambda r: "/cost-lines/save" in r.url):
        s.save_click()
    s.wait_saved_message()
    assert s.db_amounts("capex", ids) == [61.0, 62.0]


# ── Inputs Grid ⇄ cost sheets ──────────────────────────────────────────────────────────────

def test_inputs_grid_links_cost_categories_to_their_sheet_and_never_edits_them(make):
    s = make("u-ux-grid")
    s.page.goto(f"{s.base}/v2/workbook?project={s.rec.project_code}")
    s.page.wait_for_selector("#tab-input-grid", state="attached")
    s.page.evaluate("document.getElementById('tab-input-grid').click()")
    s.page.wait_for_selector("#v2-input-grid", state="attached")
    links = s.page.locator('#v2-input-grid button[data-nav-group][data-nav-tab="tab-capex"]')
    if links.count() == 0:
        # a reference-seeded working copy has line items, so at least one category must point at its lines
        pytest.fail("no category links to the CAPEX lines")
    link = links.first
    group = link.get_attribute("data-nav-group")
    row = link.locator("xpath=ancestor::tr[1]")
    assert row.locator("input.ig-input").count() == 0, "a line-item category is not editable through the scalar writer"
    link.click()
    s.page.wait_for_function("window.v2CostGrid !== undefined")
    s.page.wait_for_function(
        "(g) => { const d = document.querySelector('#v2-sheet-capex details[data-group-code=\"' + g + '\"]');"
        " return !!d && d.open && d.contains(document.activeElement) && document.activeElement.matches('input[data-cost-cell]'); }",
        arg=group)
    assert s.page.locator("#panel-capex").is_visible()


def test_mouse_save_across_both_sheets_returns_focus_to_the_cell_being_edited(make):
    s = make("u-ux-mixed-focus")
    s.open("capex")
    s.type_amounts("capex", ["201", "202"])
    s.switch("opex")
    s.type_amounts("opex", ["31", "32"])
    with s.page.expect_response(lambda r: "/cost-lines/save" in r.url):
        s.save_click("opex")                           # a real mouse click: focus sits on the Save button
    s.wait_saved_message()
    s.page.wait_for_load_state("networkidle")
    s.page.wait_for_function("!!document.activeElement && document.activeElement.matches('input[data-cost-cell]')")
    assert s.page.evaluate("document.activeElement.closest('[data-cost-grid]').dataset.costGrid") == "opex", \
        "focus stays in the sheet the user was working in"
    assert len(s.posts_to("/cost-lines/save")) == 1
