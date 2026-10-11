"""Workflow C — one integrated real-Chromium acceptance.

Financial Statements, Key-metrics strip, Smart Panel / trace evidence, navigation (deep links,
active highlight, Back/Forward), CURRENT / STALE / NOT_RUN, light / dark, desktop / narrow
viewport, and a regression check of the merged Excel-like cost grid.
"""
from __future__ import annotations

from tests.model_workspace_navigation import activate_destination, open_insight

import os
import socket
import threading
import time

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")
from playwright.sync_api import sync_playwright  # noqa: E402

PORT = 8795


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    import uvicorn
    from app.persistence import db

    mp = pytest.MonkeyPatch()
    mp.setattr(db, "DB_PATH", str(tmp_path_factory.mktemp("wc-browser") / "c.db"))
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


class Sess:
    def __init__(self, live_server, browser, uid, template="generic_solar_reference", viewport=None, scheme="light"):
        from app.auth import COOKIE_NAME, create_session_token
        from app.services.reference_seed_service import create_reference_seeded_project

        self.base = live_server
        self.uid = uid
        self.rec = create_reference_seeded_project(user_id=uid, template_source=template,
                                                   requested_name="WC", capacity_mw=40.0)
        self.ctx = browser.new_context(viewport=viewport or {"width": 1440, "height": 1000},
                                       color_scheme=scheme, bypass_csp=True)
        self.ctx.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username="admin"),
                               "url": live_server}])
        self.page = self.ctx.new_page()
        self.page.on("dialog", lambda d: d.accept())

    def url(self, frag=""):
        return f"{self.base}/v2/workbook?project={self.rec.project_code}{frag}"

    def open(self, frag=""):
        self.page.goto(self.url(frag))
        self.page.wait_for_selector("#model-workspace-nav", state="attached")

    def selected_tab(self):
        return self.page.evaluate("document.querySelector('#v2-sheet-tabs [aria-selected=\"true\"]').id")

    def nav_current(self):
        return self.page.evaluate(
            "(() => { const b = document.querySelector('#model-workspace-nav [aria-current=\"page\"]');"
            " return b ? b.getAttribute('data-nav-tab') : null; })()")

    def state(self):
        return self.page.locator('[data-testid="toolbar-runtime-state"]').first.inner_text().strip()

    def strip(self, key):
        loc = self.page.locator(f'[data-testid="kpi-strip-{key}"]')
        return (loc.get_attribute("data-available"), loc.get_attribute("data-raw"),
                loc.locator(".v2-kpi-strip-value").inner_text().strip())

    def run(self):
        self.page.click('[data-testid="v2-run-btn"]')
        self.page.wait_for_function(
            "document.querySelector('[data-testid=\"toolbar-runtime-state\"]').innerText.trim() === 'Current'",
            timeout=120000)

    def close(self):
        self.ctx.close()


@pytest.fixture
def make(live_server, browser):
    made = []

    def _make(uid, **kw):
        s = Sess(live_server, browser, uid, **kw)
        made.append(s)
        return s

    yield _make
    for s in made:
        s.close()


def test_integrated_statements_kpis_trace_navigation_and_freshness(make):
    from app.persistence.workspace_repository import get_workspace_state

    s = make("u-wcb-main")
    p = s.page
    s.open()

    # NOT RUN: the strip shows no values; statements show no fabricated figures
    assert p.locator('[data-testid="kpi-strip"]').get_attribute("data-run-state") == "NOT_RUN"
    assert s.strip("project_irr") == ("false", None, "—")
    activate_destination(p, 'tab-outputs')
    assert s.selected_tab() == "tab-outputs" and s.nav_current() == "tab-outputs"
    assert p.evaluate("location.hash") == "#outputs"
    assert p.locator('[data-testid="outputs-state"]').inner_text().strip() == "NOT RUN"
    assert p.locator('[data-out-table="pnl"]').count() == 0

    # Run -> CURRENT; strip equals the persisted Last Run
    s.run()
    ws = get_workspace_state(s.uid, s.rec.project_id)
    avail, raw, shown = s.strip("project_irr")
    assert avail == "true" and float(raw) == pytest.approx(ws.last_runtime_summary["project_irr"])
    assert shown == f"{ws.last_runtime_summary['project_irr'] * 100:.2f}%"
    assert s.strip("project_npv_keur") == ("false", None, "—")            # authority gap, not zero
    assert "authority gap" in p.locator('[data-testid="kpi-strip-project_npv_keur"] button').get_attribute("title")
    assert p.locator('[data-testid="kpi-strip-state"]').inner_text().strip() == "CURRENT"
    assert p.locator('[data-testid="fs-state-badge"]').inner_text().strip() == "CURRENT"

    p.wait_for_selector('[data-out-table="pnl-annual"]', state='visible')
    # Statements: full axis, parentheses for negatives, sticky header and first column
    wrapper = p.locator('[data-out-table="pnl-annual"] >> xpath=ancestor::div[@data-out-scroll]')
    wrapper.scroll_into_view_if_needed()
    assert wrapper.get_attribute("role") == "region"
    n_years = p.locator('[data-out-table="pnl-annual"] thead th.out-num').count()
    assert n_years >= 10
    p.locator('[data-out-basis]').select_option('model')
    n_model = p.locator('[data-out-table="pnl"] thead th.out-num').count()
    assert n_model > n_years
    sticky = p.evaluate("""() => {
        const w = document.querySelector('[data-out-table="pnl"]').closest('[data-out-scroll]');
        const th = w.querySelector('thead th.out-num');
        const lab = w.querySelector('tbody th.out-label');
        w.scrollLeft = 400; w.scrollTop = 40;
        const wr = w.getBoundingClientRect();
        return {headTop: th.getBoundingClientRect().top - wr.top, labLeft: lab.getBoundingClientRect().left - wr.left,
                canScrollX: w.scrollWidth > w.clientWidth};
    }""")
    assert sticky["canScrollX"] and abs(sticky["headTop"]) <= 2 and abs(sticky["labLeft"]) <= 2

    # drill-down: a metric opens its authoritative sheet; the nav follows
    open_insight(p)
    p.click('[data-testid="kpi-strip-project_irr"] button')
    assert s.selected_tab() == "tab-returns" and s.nav_current() == "tab-returns"
    p.click('[data-testid="kpi-strip-min_dscr"] button')
    assert s.selected_tab() == "tab-debt" and s.nav_current() == "tab-debt"

    # Back / Forward between nav-chosen sheets
    activate_destination(p, 'tab-outputs')
    p.click('[data-testid="nav-returns"]')
    p.go_back()
    p.wait_for_function("document.getElementById('tab-outputs').getAttribute('aria-selected') === 'true'")
    assert s.selected_tab() == "tab-outputs" and s.nav_current() == "tab-outputs"
    p.go_forward()
    p.wait_for_function("document.getElementById('tab-returns').getAttribute('aria-selected') === 'true'")
    assert s.selected_tab() == "tab-returns" and s.nav_current() == "tab-returns"

    # Smart Panel: trace is typed unavailable, available evidence listed separately
    panel = p.locator('[data-testid="smart-panel-section-trace"]')
    assert "not persisted after a run" in panel.inner_text()
    assert "Available evidence (not a full trace)" in panel.inner_text()
    assert p.locator('[data-testid="smart-panel-group-input"]').count() == 1

    # Economic edit through the merged Excel-like grid -> STALE everywhere, values kept as prior run
    activate_destination(p, 'tab-capex')
    rows = p.locator('#v2-sheet-capex form[data-cost-row]')
    p.evaluate("document.querySelectorAll('#v2-sheet-capex details[data-group-code]').forEach(d => d.open = true)")
    cell = rows.nth(0).locator('input[name="amount_keur"]')
    cell.click()
    p.keyboard.press("Control+A")
    p.keyboard.type(str(int(float(cell.get_attribute("data-exact"))) + 1))
    p.keyboard.press("Enter")
    p.wait_for_function("window.v2CostGrid && !window.v2CostGrid.busy()")
    p.wait_for_function(
        "document.querySelector('[data-testid=\"toolbar-runtime-state\"]').innerText.trim() === 'Stale'")
    assert p.locator('[data-testid="kpi-strip-state"]').inner_text().strip() == "PRIOR RUN"
    assert s.strip("project_irr")[1] == raw                                  # same persisted value, now labelled prior
    activate_destination(p, 'tab-outputs')
    assert p.locator('[data-testid="fs-state-badge"]').inner_text().strip().startswith("STALE")
    # no hidden execution: Last Run identity untouched
    ws2 = get_workspace_state(s.uid, s.rec.project_id)
    assert ws2.last_runtime_composite_hash == ws.last_runtime_composite_hash

    # Run again -> CURRENT
    s.run()
    assert p.locator('[data-testid="kpi-strip-state"]').inner_text().strip() == "CURRENT"


def test_deep_link_activates_the_section_and_highlights_the_nav(make):
    s = make("u-wcb-deep")
    s.open("#revenue")
    s.page.wait_for_function("document.getElementById('tab-revenue').getAttribute('aria-selected') === 'true'")
    assert s.nav_current() == "tab-revenue"
    s.open("#outputs")
    s.page.wait_for_function("document.getElementById('tab-outputs').getAttribute('aria-selected') === 'true'")
    assert s.nav_current() == "tab-outputs"


def test_keyboard_navigation_in_the_nav(make):
    s = make("u-wcb-kbd")
    s.open()
    activate_destination(s.page, 'tab-input-grid')
    s.page.focus('[data-nav-tab="tab-input-grid"]')
    s.page.keyboard.press("ArrowDown")
    assert s.page.evaluate("document.activeElement.getAttribute('data-nav-tab')") == "tab-project-setup"
    s.page.keyboard.press("Enter")
    assert s.selected_tab() == "tab-project-setup"


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_strip_and_statements_are_readable_in_light_and_dark(make, scheme):
    s = make(f"u-wcb-theme-{scheme}", scheme=scheme)
    s.open()
    s.run()
    contrast = s.page.evaluate("""() => {
      const lum = c => { const a = c.match(/\\d+(\\.\\d+)?/g).slice(0,3).map(Number).map(v => { v/=255; return v<=.03928? v/12.92 : Math.pow((v+.055)/1.055,2.4);});
                         return .2126*a[0]+.7152*a[1]+.0722*a[2]; };
      const bg = el => { while (el) { const c = getComputedStyle(el).backgroundColor; if (c && !/rgba\\(0, 0, 0, 0\\)|transparent/.test(c)) return c; el = el.parentElement; } return 'rgb(255,255,255)'; };
      const ratio = el => { const f = lum(getComputedStyle(el).color), b = lum(bg(el)); const hi = Math.max(f,b), lo = Math.min(f,b); return (hi+.05)/(lo+.05); };
      const sel = ['.v2-kpi-strip-label', '.v2-kpi-strip-value', '.v2-kpi-strip-caption', '.v2-kpi-strip-title'];
      return sel.map(q => [q, ratio(document.querySelector(q))]);
    }""")
    for q, r in contrast:
        assert r >= 4.5, (scheme, q, r)
    activate_destination(s.page, 'tab-outputs')
    s.page.wait_for_selector('[data-out-table="pnl-annual"] td.out-num')
    ratios = s.page.evaluate("""() => {
      const q = document.querySelector('[data-out-table="pnl-annual"] td.out-num');
      return getComputedStyle(q).color; }""")
    assert ratios


def test_narrow_viewport_keeps_nav_statements_and_strip_usable(make):
    s = make("u-wcb-narrow", viewport={"width": 390, "height": 844})
    s.open()
    s.run()
    assert s.page.locator("#model-workspace-nav").is_hidden()
    s.page.locator('[data-workspace-drawer][aria-controls="model-workspace-nav"]').click()
    nav_box = s.page.locator("#model-workspace-nav").bounding_box()
    assert nav_box["width"] <= 392 and nav_box["height"] <= 422              # bounded contextual drawer
    assert s.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    activate_destination(s.page, 'tab-outputs')
    s.page.wait_for_selector('[data-out-table="pnl-annual"]')
    assert s.selected_tab() == "tab-outputs"
    overflow = s.page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 1
    wrapper = s.page.locator('[data-out-table="pnl-annual"] >> xpath=ancestor::div[@data-out-scroll]')
    assert wrapper.evaluate("w => w.scrollWidth > w.clientWidth")                # scrolls, labels stay readable
    assert s.page.locator('[data-testid="kpi-strip"]').count() == 1


def test_overview_tiles_drill_down_to_their_authoritative_sheet(make):
    s = make("u-wcb-drill")
    s.open()
    s.run()
    p = s.page
    p.click('[data-testid="nav-overview"]')
    p.click('[data-testid="kpi-project-irr"]')
    assert s.selected_tab() == "tab-returns" and s.nav_current() == "tab-returns"
    p.click('[data-testid="nav-overview"]')
    p.focus('[data-testid="kpi-min-dscr"]')
    p.keyboard.press("Enter")                                   # keyboard-operable
    assert s.selected_tab() == "tab-debt" and s.nav_current() == "tab-debt"
    p.click('[data-testid="nav-overview"]')
    p.click('[data-testid="kpi-total-revenue"]')
    assert s.selected_tab() == "tab-revenue"
