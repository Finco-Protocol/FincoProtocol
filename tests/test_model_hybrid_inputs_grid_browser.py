"""WF-05 — hybrid navigation, status strip and Inputs grid in a REAL Chromium.

Every interaction is a genuine browser event against a live uvicorn server running the real
application on a synthetic reference-seeded project; persisted values are read back from the
database.  Skipped when Playwright or Chromium is unavailable.

Timings (3-4 consecutive edits) are printed and written to the file named by
``WF05_TIMINGS_JSON`` when set, so the PR can quote measured numbers.
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

PORT = 8798
TIMINGS: dict = {}

EDITS = [
    ("project_setup.technical.p50_hours", "1511"),
    ("project_setup.technical.construction_months", "15"),
    ("project_setup.technical.horizon_years", "26"),
    ("revenue.ppa.base_tariff", "52.5"),
]


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    import uvicorn
    from app.persistence import db

    mp = pytest.MonkeyPatch()
    mp.setattr(db, "DB_PATH", str(tmp_path_factory.mktemp("wf05") / "g.db"))
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
    path = os.environ.get("WF05_TIMINGS_JSON")
    if path:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(TIMINGS, handle, indent=2)


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

        self.base = live_server
        self.uid = uid
        self.rec = create_reference_seeded_project(
            user_id=uid, template_source=template, requested_name="Grid", capacity_mw=40.0)
        self.ctx = browser.new_context(viewport=viewport or {"width": 1440, "height": 900}, bypass_csp=True)
        self.ctx.add_cookies([{"name": COOKIE_NAME,
                               "value": create_session_token(user_id=uid, username="admin"),
                               "url": live_server}])
        self.page = self.ctx.new_page()
        self.page.on("dialog", lambda d: d.accept())
        self.posts: list[str] = []
        self.page.on("request", lambda r: self.posts.append(r.url.split(str(PORT), 1)[-1])
                     if r.method == "POST" else None)
        self.errors: list[str] = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))

    def open_grid(self):
        self.page.goto(f"{self.base}/v2/workbook?project={self.rec.project_code}")
        self.page.wait_for_selector("#tab-input-grid")
        self.page.evaluate("document.getElementById('tab-input-grid').click()")
        self.page.wait_for_selector("#v2-input-grid .ig-input", state="visible")

    def cell(self, field_id):
        return self.page.locator(f'#v2-input-grid .ig-input[data-ig-field="{field_id}"]')

    def active_field(self):
        return self.page.evaluate("document.activeElement && document.activeElement.dataset.igField || null")

    def staged(self):
        return self.page.evaluate("window.FincoInputGrid.stagedCount()")

    def persisted(self, field_id):
        from app.persistence.workspace_repository import get_workspace_state
        from app.workbook.input_set import ProjectInputSet
        from app.workbook.registry import WORKBOOK

        ws = get_workspace_state(self.uid, self.rec.project_id)
        return ProjectInputSet.from_snapshot(ws.draft_snapshot, workbook=WORKBOOK).get(field_id)

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


def _shot(s, name):
    """Reviewer evidence: only when WF05_SCREENSHOT_DIR is set (CI artifact)."""
    out = os.environ.get("WF05_SCREENSHOT_DIR")
    if out:
        os.makedirs(out, exist_ok=True)
        s.page.screenshot(path=os.path.join(out, f"{name}.png"), full_page=False)


def _edit(s, field_id, value):
    s.cell(field_id).click()
    s.page.keyboard.press("Control+A")
    s.page.keyboard.type(value)
    s.page.keyboard.press("Enter")
    s.page.wait_for_timeout(150)


# ── hybrid navigation ────────────────────────────────────────────────────────────────

def test_hybrid_groups_switch_real_tabs_and_keep_every_tab_reachable(make):
    s = make("u-wf05-nav")
    s.open_grid()
    labels = s.page.locator('[data-testid="hybrid-nav"] .hy-group').all_inner_texts()
    assert [t.strip().lower() for t in labels] == ["inputs", "scenarios", "outputs", "analysis", "trust"]
    expectations = {"inputs": "tab-input-grid", "scenarios": "tab-scenarios", "outputs": "tab-overview",   # the landing tab counts as visited: a group returns to its last-visited tab
                    "analysis": "tab-sensitivity", "trust": "tab-trust"}
    for group, tab in expectations.items():
        s.page.locator(f'[data-hy-group="{group}"]').click()
        s.page.wait_for_function(
            "(t) => document.getElementById(t).getAttribute('aria-selected') === 'true'", arg=tab)
        assert s.page.locator(f'[data-hy-group="{group}"]').get_attribute("aria-selected") == "true"
    # every pre-existing sheet tab is still present and directly activatable
    for tab in ("tab-outputs", "tab-overview", "tab-capex", "tab-opex", "tab-revenue", "tab-debt", "tab-tax", "tab-returns",
                "tab-run-history", "tab-compare", "tab-goal-seek"):
        s.page.evaluate(f"document.getElementById('{tab}').click()")
        assert s.page.get_attribute(f"#{tab}", "aria-selected") == "true"
        group = s.page.evaluate(
            "(t) => Object.keys(window.FincoInputGrid.hybridGroups).find(g => window.FincoInputGrid.hybridGroups[g].includes(t))",
            tab)
        assert group, f"{tab} belongs to no hybrid group"
        assert s.page.locator(f'[data-hy-group="{group}"]').get_attribute("aria-selected") == "true"
    assert s.page.locator('[data-testid="workspace-nav"] [data-nav-tab="tab-capex"]').count() == 1
    assert not s.errors


def test_status_strip_states_identity_run_state_and_independent_integrity(make):
    s = make("u-wf05-strip")
    s.open_grid()
    strip = s.page.locator('[data-testid="hybrid-status"]')
    text = strip.inner_text()
    assert "Working Copy" in text and "Scenario:" in text
    assert s.page.locator('[data-testid="hybrid-run-state"]').inner_text().strip() == "NOT RUN"
    integrity = s.page.locator('[data-testid="hybrid-integrity"]').inner_text()
    assert integrity.startswith("Integrity:") and "UNAVAILABLE" in integrity   # no Last Run yet
    assert s.page.locator('[data-testid="hybrid-last-run"]').inner_text().strip().endswith("—")


# ── keyboard flow + atomic batch Save ────────────────────────────────────────────────

def test_enter_escape_tab_arrows_then_one_atomic_save_without_running_the_model(make):
    s = make("u-wf05-kbd")
    s.open_grid()
    first = s.cell(EDITS[0][0]).first

    first.click()
    s.page.keyboard.press("Control+A")
    s.page.keyboard.type("1511")
    s.page.keyboard.press("Enter")                            # commit + move down
    assert s.active_field() != EDITS[0][0]
    s.page.wait_for_timeout(300)
    assert s.page.locator(f'[data-ig-row][data-ig-field="{EDITS[0][0]}"]').get_attribute("class").count("ig-row--edited") == 1

    cur = s.active_field()
    s.page.keyboard.type("987654")                            # focus select-all replaced the value
    s.page.keyboard.press("Escape")                           # cancel: back to the committed value
    assert s.page.locator(f'#v2-input-grid .ig-input[data-ig-field="{cur}"]').input_value() != "987654"

    s.page.keyboard.press("ArrowDown")
    down = s.active_field()
    s.page.keyboard.press("ArrowUp")
    assert s.active_field() == cur and down != cur
    s.page.keyboard.press("Tab")
    assert s.active_field() != cur
    assert s.staged() == 1

    assert not any("/v2/workbook/update" in p or "/run" in p for p in s.posts)
    assert s.persisted(EDITS[0][0]) != 1511                    # nothing persisted before Save


def test_four_consecutive_edits_save_atomically_with_stable_focus_and_scroll(make):
    s = make("u-wf05-batch")
    s.open_grid()
    for field_id, value in EDITS:
        _edit(s, field_id, value)
    assert s.staged() == len(EDITS)
    _shot(s, "desktop-grid-four-staged-edits")
    assert "4 unsaved edits" in s.page.locator("[data-ig-count]").inner_text()
    assert s.page.locator('[data-testid="hybrid-unsaved"]').is_visible()

    # park the focus in a known cell and scroll so any jump is detectable
    s.cell(EDITS[2][0]).click()
    s.page.evaluate("window.scrollTo(0, 120)")
    before_scroll = s.page.evaluate("window.scrollY")
    before_posts = len(s.posts)

    t0 = time.perf_counter()
    s.page.keyboard.press("Control+S")
    s.page.wait_for_function("window.__igLastSaveMs !== undefined", timeout=30000)
    elapsed = time.perf_counter() - t0
    s.page.wait_for_timeout(400)

    new_posts = [p for p in s.posts[before_posts:] if "/grid/save" in p]
    assert len(new_posts) == 1, s.posts[before_posts:]                      # ONE atomic batch request
    assert not any("/v2/workbook/update" in p or p.endswith("/run") for p in s.posts)
    for field_id, value in EDITS:
        assert float(s.persisted(field_id)) == float(value)
    assert s.staged() == 0
    assert s.active_field() == EDITS[2][0], "focus must stay on the cell the user was in"
    assert abs(s.page.evaluate("window.scrollY") - before_scroll) <= 2, "Save must not scroll the page"
    assert s.page.locator('[data-ig-flag-notrun]:not([hidden])').count() == 0   # no Last Run to compare with
    hashes = set(s.page.evaluate(
        "Array.from(document.querySelectorAll('input[name=content_hash]')).map(i => i.value)"))
    assert hashes == {s.page.get_attribute("#v2-input-grid", "data-content-hash")}, "stale hash left behind"

    # a second consecutive batch must not hit a stale CAS
    for field_id, value in (("project_setup.technical.p50_hours", "1522"), ("revenue.ppa.base_tariff", "53")):
        _edit(s, field_id, value)
    s.page.evaluate("window.__igLastSaveMs = undefined")
    s.page.keyboard.press("Control+S")
    s.page.wait_for_function("window.__igLastSaveMs !== undefined", timeout=30000)
    assert float(s.persisted("project_setup.technical.p50_hours")) == 1522.0
    assert float(s.persisted("revenue.ppa.base_tariff")) == 53.0
    TIMINGS["grid_batch_save_4_edits_s"] = round(elapsed, 3)
    TIMINGS["grid_batch_save_ms_reported"] = s.page.evaluate("window.__igLastSaveMs")
    assert not s.errors


def test_save_blocked_run_and_discard_keep_the_user_in_control(make):
    s = make("u-wf05-guard")
    s.open_grid()
    _edit(s, *EDITS[0])
    s.page.locator('[data-testid="header-run-btn"]').click()
    s.page.wait_for_timeout(500)
    assert not any(p.endswith("/run") for p in s.posts), "Run must not fire over unsaved grid edits"
    assert "unsaved" in s.page.locator("[data-ig-msg]").inner_text().lower()
    s.page.locator("[data-ig-discard]").click()
    assert s.staged() == 0
    assert s.cell(EDITS[0][0]).input_value() != EDITS[0][1]


# ── paste ────────────────────────────────────────────────────────────────────────────

def _paste(s, field_id, text):
    s.cell(field_id).click()
    s.page.evaluate(
        """([id, text]) => {
            const el = document.querySelector('#v2-input-grid .ig-input[data-ig-field="' + id + '"]');
            const dt = new DataTransfer(); dt.setData('text/plain', text);
            el.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
        }""", [field_id, text])
    s.page.wait_for_timeout(600)


def test_multi_cell_paste_is_validated_all_or_nothing(make):
    s = make("u-wf05-paste")
    s.open_grid()
    start = EDITS[0][0]
    _paste(s, start, "1600\n16\n27")                      # positional: three consecutive editable cells
    assert s.staged() == 3
    assert s.cell("project_setup.technical.construction_months").input_value() == "16"
    s.page.locator("[data-ig-discard]").click()

    _paste(s, start, "1600\nnot-a-number\n27")
    assert s.staged() == 0, "an invalid cell rejects the whole paste"
    assert "rejected" in s.page.locator("[data-ig-msg]").inner_text().lower()

    label = s.page.locator('[data-ig-row][data-ig-field="revenue.ppa.base_tariff"] .ig-label').inner_text()
    _paste(s, start, f"{label}\t51,5\nUnknown thing\t1")
    assert s.staged() == 0 and "matches no editable" in s.page.locator("[data-ig-msg]").inner_text()
    _paste(s, start, f"{label}\t51,5")
    assert s.cell("revenue.ppa.base_tariff").input_value() == "51.5"   # decimal comma normalised
    assert s.staged() == 1
    assert not s.errors


def test_server_rejection_keeps_staged_edits_and_names_the_cell(make):
    s = make("u-wf05-reject")
    s.open_grid()
    _edit(s, "project_setup.technical.horizon_years", "-3")
    s.page.wait_for_timeout(500)
    row = s.page.locator('[data-ig-row][data-ig-field="project_setup.technical.horizon_years"]')
    assert "ig-row--error" in row.get_attribute("class")
    assert s.page.locator("[data-ig-save]").is_disabled()
    assert s.persisted("project_setup.technical.horizon_years") != -3


# ── mobile ───────────────────────────────────────────────────────────────────────────

def test_mobile_390_grid_edits_and_saves_without_horizontal_page_overflow(make):
    s = make("u-wf05-mobile", viewport={"width": 390, "height": 844})
    s.open_grid()
    overflow = s.page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 2, f"page overflows horizontally by {overflow}px"
    _edit(s, "project_setup.technical.p50_hours", "1533")
    s.page.locator("[data-ig-save]").click()
    s.page.wait_for_function("window.__igLastSaveMs !== undefined", timeout=30000)
    assert float(s.persisted("project_setup.technical.p50_hours")) == 1533.0
    _shot(s, "mobile-390-grid-after-save")
    assert s.page.locator('[data-testid="hybrid-status"]').is_visible()
    assert not s.errors


# ── all four verticals behave the same ───────────────────────────────────────────────

@pytest.mark.parametrize("template,uid", [
    ("generic_wind_reference", "u-wf05-wind"),
    ("generic_data_center_reference", "u-wf05-dc"),
    ("generic_ev_charging_reference", "u-wf05-ev"),
])
def test_other_verticals_render_the_same_grid_and_save_atomically(make, template, uid):
    s = make(uid, template=template)
    s.open_grid()
    editable = s.page.locator("#v2-input-grid .ig-input")
    assert editable.count() >= 3
    field_id = editable.first.get_attribute("data-ig-field")
    value = editable.first.input_value()
    new = str(float(value or "10") + 1)
    new = new[:-2] if new.endswith(".0") else new
    _edit(s, field_id, new)
    s.page.locator("[data-ig-save]").click()
    s.page.wait_for_function("window.__igLastSaveMs !== undefined", timeout=30000)
    assert float(s.persisted(field_id)) == float(new)
    assert s.page.locator('[data-testid="hybrid-integrity"]').count() == 1
    assert not s.errors


# ── existing cost-line grid: 4 consecutive OPEX/CAPEX edits, measured ────────────────

@pytest.mark.parametrize("kind", ["capex", "opex"])
def test_four_consecutive_cost_line_edits_keep_focus_and_scroll(make, kind):
    s = make(f"u-wf05-cost-{kind}")
    s.page_kind = kind
    s.page.goto(f"{s.base}/v2/workbook?project={s.rec.project_code}")
    s.page.wait_for_selector(f"#tab-{kind}")
    s.page.evaluate(f"document.getElementById('tab-{kind}').click()")
    s.page.wait_for_selector(f"#v2-sheet-{kind} form[data-cost-row]", state="attached")
    s.page.evaluate(f"document.querySelectorAll('#v2-sheet-{kind} details[data-group-code]').forEach(d => d.open = true)")
    rows = s.page.locator(f"#v2-sheet-{kind} form[data-cost-row]")
    amounts = [rows.nth(i).locator('input[name="amount_keur"]') for i in range(4)]
    ids = [rows.nth(i).get_attribute("id") for i in range(4)]
    amounts[0].scroll_into_view_if_needed()
    amounts[0].click()
    scroll0 = s.page.evaluate("window.scrollY")
    times = []
    for i in range(4):
        t0 = time.perf_counter()
        s.page.keyboard.press("Control+A")
        s.page.keyboard.type(str(4100 + i))
        s.page.keyboard.press("Enter")
        s.page.wait_for_function(
            "([id, v]) => { const n = document.querySelector('#' + id + ' input[name=amount_keur]');"
            " return n && n.dataset.original === v && n.value === v; }", arg=[ids[i], str(4100 + i)], timeout=20000)
        times.append(round(time.perf_counter() - t0, 3))
        if i < 3:
            assert s.page.evaluate("document.activeElement.closest('form') && document.activeElement.closest('form').id") == ids[i + 1], \
                "Enter must advance to the next row"
    s.page.wait_for_function("window.v2CostGrid && !window.v2CostGrid.busy()", timeout=20000)
    assert abs(s.page.evaluate("window.scrollY") - scroll0) <= 120, "edits must not jump the page"
    TIMINGS[f"cost_{kind}_4_consecutive_edits_s"] = times
    updates = [p for p in s.posts if f"/v2/{kind}/line/update" in p]
    assert len(updates) == 4, "exactly one write per edited row"
    assert not any(p.endswith("/run") for p in s.posts), "editing never runs the model"
    assert not s.errors


def test_cost_line_saved_after_last_run_is_marked_not_run_and_strip_follows(make):
    s = make("u-wf05-notrun")
    s.page.goto(f"{s.base}/v2/workbook?project={s.rec.project_code}")
    s.page.wait_for_selector("#tab-opex")
    s.page.locator('[data-testid="header-run-btn"]').click()
    s.page.wait_for_function(
        "document.querySelector('[data-testid=hybrid-run-state]').textContent.trim() === 'CURRENT'", timeout=240000)
    s.page.evaluate("document.getElementById('tab-opex').click()")
    s.page.wait_for_selector("#v2-sheet-opex form[data-cost-row]", state="attached")
    s.page.evaluate("document.querySelectorAll('#v2-sheet-opex details[data-group-code]').forEach(d => d.open = true)")
    assert s.page.locator('#v2-sheet-opex [data-testid="edited-not-run"]').count() == 0
    row = s.page.locator("#v2-sheet-opex form[data-cost-row]").first
    row.locator('input[name="amount_keur"]').click()
    s.page.keyboard.press("Control+A")
    s.page.keyboard.type("777")
    s.page.keyboard.press("Enter")
    s.page.wait_for_function(
        "document.querySelector('[data-testid=hybrid-run-state]').textContent.trim() === 'STALE'", timeout=30000)
    s.page.wait_for_selector('#v2-sheet-opex [data-testid="edited-not-run"]', state="attached", timeout=30000)
    integrity = s.page.locator('[data-testid="hybrid-integrity"]').inner_text()
    assert integrity.startswith("Integrity:")

    # grid fields saved after the Last Run carry the same marker, with the Last Run value on hover
    s.page.evaluate("document.getElementById('tab-input-grid').click()")
    s.page.wait_for_selector("#v2-input-grid .ig-input", state="visible")
    assert s.page.locator("[data-ig-flag-notrun]:not([hidden])").count() == 0
    _edit(s, "project_setup.technical.p50_hours", "1666")
    s.page.keyboard.press("Control+S")
    s.page.wait_for_function("window.__igLastSaveMs !== undefined", timeout=30000)
    flag = s.page.locator('[data-ig-row][data-ig-field="project_setup.technical.p50_hours"] [data-ig-flag-notrun]')
    flag.wait_for(state="visible", timeout=10000)
    assert "Last Run used" in flag.get_attribute("title")
    _shot(s, "desktop-grid-saved-not-run-after-run")
    assert not s.errors


# ── PR #245 Correction A: EV efficiency — grid and legacy editor agree ───────────────

EFF = "revenue.ev_charging.charging_efficiency"


def _legacy_eff(s):
    return s.page.locator(f'#v2-sheet-revenue .v2-field-row[data-field-id="{EFF}"] input[name="value"]')


def _legacy_edit(s, value, *, expect_saved=True):
    s.page.evaluate("document.getElementById('tab-revenue').click()")
    box = _legacy_eff(s)
    box.scroll_into_view_if_needed()
    box.click()
    s.page.keyboard.press("Control+A")
    s.page.keyboard.type(value)
    s.page.keyboard.press("Enter")
    if expect_saved:
        deadline = time.time() + 20
        while time.time() < deadline and s.persisted(EFF) != float(value):
            s.page.wait_for_timeout(200)
        assert s.persisted(EFF) == float(value), "legacy editor save did not persist"
        s.page.wait_for_timeout(800)          # let the HTMX swap settle
    else:
        s.page.wait_for_timeout(1200)


def test_ev_efficiency_rendered_identity_is_unique_and_shows_94_percent(make):
    s = make("u-wf05-ev-eff", template="generic_ev_charging_reference")
    html = s.page.goto(f"{s.base}/v2/workbook?project={s.rec.project_code}").text()
    # the legacy editor identity (data-field-id) exists exactly once; the grid uses its own attribute
    assert html.count(f'data-field-id="{EFF}"') == 1
    assert html.count(f'data-ig-field="{EFF}"') == 2          # grid row + grid input
    assert float(_legacy_eff(s).input_value()) == 94.0
    assert s.persisted(EFF) == 94.0


def test_ev_efficiency_valid_and_invalid_edits_and_effective_model_input_agree(make):
    s = make("u-wf05-ev-eff2", template="generic_ev_charging_reference")
    s.page.goto(f"{s.base}/v2/workbook?project={s.rec.project_code}")
    s.page.wait_for_selector("#tab-revenue")
    _legacy_edit(s, "92")
    assert s.persisted(EFF) == 92.0
    for bad in ("120", "-5", "100.5"):
        _legacy_edit(s, bad, expect_saved=False)
        assert s.persisted(EFF) == 92.0, f"{bad!r} must be rejected and the snapshot preserved"
    # the effective model input is the human percent converted to a runtime fraction (unchanged authority)
    from app.persistence.workspace_repository import get_workspace_state
    from app import ev_charging_economics as ev
    ws = get_workspace_state(s.uid, s.rec.project_id)
    assert ev.drivers_from_snapshot(dict(ws.draft_snapshot)).charging_efficiency == pytest.approx(0.92)
    # the grid shows the persisted value after the tab is (re)activated
    s.page.evaluate("document.getElementById('tab-input-grid').click()")
    s.page.wait_for_function("(f) => document.querySelector('.ig-input[data-ig-field=\"' + f + '\"]').value === '92'", arg=EFF)


def test_ev_grid_save_refreshes_the_legacy_editor_and_keeps_one_value(make):
    s = make("u-wf05-ev-eff3", template="generic_ev_charging_reference")
    s.open_grid()
    _edit(s, EFF, "90")
    s.page.keyboard.press("Control+S")
    s.page.wait_for_function("window.__igLastSaveMs !== undefined", timeout=30000)
    assert s.persisted(EFF) == 90.0
    s.page.evaluate("document.getElementById('tab-revenue').click()")
    s.page.wait_for_function(
        "(f) => parseFloat(document.querySelector('#v2-sheet-revenue .v2-field-row[data-field-id=\"' + f + '\"] input[name=value]').value) === 90",
        arg=EFF, timeout=20000)
    # invalid grid values are rejected before anything is staged
    s.page.evaluate("document.getElementById('tab-input-grid').click()")
    _edit(s, EFF, "150")
    s.page.wait_for_timeout(600)
    assert s.page.locator(f'[data-ig-row][data-ig-field="{EFF}"]').get_attribute("class").count("ig-row--error") == 1
    assert s.persisted(EFF) == 90.0


def test_grid_cannot_silently_overwrite_a_write_made_by_the_legacy_editor(make):
    s = make("u-wf05-ev-eff4", template="generic_ev_charging_reference")
    s.open_grid()
    _edit(s, EFF, "91")                                   # staged in the grid, not saved
    assert s.staged() == 1
    # another editor writes the same field through the legacy single-field endpoint (same CAS authority)
    status = s.page.evaluate(
        """async ([project, field]) => {
            const f = document.querySelector('#v2-canonical-run-form');
            const body = new URLSearchParams({project, field_id: field, value: '93', sheet_id: 'revenue',
                workbook_version: f.querySelector('[name=workbook_version]').value,
                content_hash: f.querySelector('[name=content_hash]').value});
            const r = await fetch('/v2/workbook/update', {method: 'POST', credentials: 'same-origin',
                headers: {'HX-Request': 'true', 'Content-Type': 'application/x-www-form-urlencoded'}, body});
            return r.status;
        }""", [s.rec.project_code, EFF])
    assert status == 200
    assert s.persisted(EFF) == 93.0
    assert s.staged() == 1
    s.page.keyboard.press("Control+S")
    s.page.wait_for_timeout(1500)
    assert s.persisted(EFF) == 93.0, "the stale staged value must NOT overwrite the newer write"
    assert "changed since" in s.page.locator("[data-ig-msg]").inner_text().lower() or \
        "stale" in s.page.locator("[data-ig-msg]").inner_text().lower() or \
        "nothing was saved" in s.page.locator("[data-ig-msg]").inner_text().lower()
    assert s.staged() == 1, "the user's staged edit is kept, never lost silently"


def test_save_pressed_right_after_enter_waits_for_the_validator_instead_of_refusing(make):
    """CI regression: Ctrl+S immediately after Enter, with a slow canonical validator."""
    s = make("u-wf05-slow-validate", template="generic_ev_charging_reference")
    s.open_grid()
    s.page.route("**/grid/validate", lambda route: (time.sleep(1.2), route.continue_()))
    s.cell(EFF).click()
    s.page.keyboard.press("Control+A")
    s.page.keyboard.type("90")
    s.page.keyboard.press("Enter")
    s.page.keyboard.press("Control+S")
    s.page.wait_for_function("window.__igLastSaveMs !== undefined", timeout=30000)
    assert s.persisted(EFF) == 90.0
