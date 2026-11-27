"""Workflow C — one integrated real-Chromium acceptance on the React workspace.

Financial Statements, Key financial metrics, canonical source / evidence attribution,
navigation (deep links, active highlight, Back/Forward), CURRENT / STALE / NOT_RUN,
light / dark contrast, narrow viewport, and staged CAPEX Save -> STALE -> Run.
"""
from __future__ import annotations

import os
import re
import socket
import threading
import time

import pytest


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
    # Optional dependency is checked at setup, preserving every collected test identity.
    sync_playwright = pytest.importorskip("playwright.sync_api", reason="playwright not installed in this workflow").sync_playwright
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

        assert os.environ.get("FINCO_MODEL_REACT_V1") != "0", "Workflow C must run on the default React workspace"
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
        self.pageerrors: list[str] = []
        self.http_errors: list[str] = []
        self.runs: list[str] = []
        self.saves: list[str] = []
        self.page.on("pageerror", lambda exc: self.pageerrors.append(str(exc)))
        self.page.on("response", self._on_response)

    def _on_response(self, response):
        url = response.url
        if response.request.method == "POST":
            if "/v2/workbook/run" in url and not url.endswith("/run-history"):
                self.runs.append(f"{response.status} {url}")
            if "/cost-lines/save" in url:
                self.saves.append(f"{response.status} {url}")
        if response.status >= 400 and not url.endswith("/favicon.ico"):
            self.http_errors.append(f"{response.status} {response.request.method} {url}")

    def url(self, frag=""):
        return f"{self.base}/v2/model-react/{self.rec.project_code}{frag}"

    def open(self, frag=""):
        self.page.goto(self.url(frag))
        self.page.wait_for_selector('[data-workflow-bar="true"]', timeout=30000)
        self.page.wait_for_selector('[data-workspace-nav="true"]', state="attached", timeout=30000)

    def nav_to(self, dest: str):
        menu = self.page.locator(".wsv2-menu")
        if menu.is_visible() and menu.get_attribute("aria-expanded") != "true":
            menu.click()
        link = self.page.locator(f'#wsv2-navigation [data-workspace-destination="{dest}"]')
        link.click()
        self.page.wait_for_function(
            "d => document.querySelector('#wsv2-navigation [aria-current=\"page\"]')?.getAttribute('data-workspace-destination') === d",
            arg=dest,
        )

    def nav_current(self):
        return self.page.evaluate(
            "(() => { const a = document.querySelector('#wsv2-navigation [aria-current=\"page\"]');"
            " return a ? a.getAttribute('data-workspace-destination') : null; })()"
        )

    def freshness(self):
        return self.page.locator('[data-workflow-bar="true"]').get_attribute("data-bar-freshness")

    def run(self):
        self.page.wait_for_function(
            "() => { const b = document.querySelector('[data-wf-run=\"true\"]'); return Boolean(b) && !b.disabled; }",
            timeout=30000,
        )
        self.page.locator('[data-wf-run="true"]').click()
        self.page.wait_for_function(
            "() => document.querySelector('[data-workflow-bar=\"true\"]')?.getAttribute('data-bar-freshness') === 'CURRENT'"
            " && document.querySelector('[data-workflow-bar=\"true\"] [data-run-state-label=\"CURRENT\"]') !== null",
            timeout=120000,
        )

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
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.workspace_repository import get_workspace_state

    s = make("u-wcb-main")
    p = s.page
    s.open()

    # 1. NOT RUN: honest state, no fabricated KPI or statement values
    p.wait_for_selector('[data-financial-overview="true"]', timeout=20000)
    assert s.freshness() == "NOT_RUN"
    assert "No committed Run yet" in p.locator('[data-financial-overview="true"]').inner_text()
    s.nav_to("statements")
    p.wait_for_selector('[data-statements-view="true"][data-statements-state="NOT_RUN"]', timeout=20000)
    assert p.locator(".fm-sw-table").count() == 0
    s.nav_to("results")
    p.wait_for_selector('[data-financial-page="results"][data-financial-state="NOT_RUN"]', timeout=20000)

    # 2. Explicit Run -> CURRENT; KPIs match persisted Last Run with exact precision and honest unavailability
    s.run()
    assert len(s.runs) == 1 and s.runs[0].startswith("200 ")
    ws = get_workspace_state(s.uid, s.rec.project_id)
    assert not ws.dirty and len(get_run_history(s.uid, s.rec.project_id)) == 1

    p.wait_for_selector('[data-financial-page="results"][data-financial-state="CURRENT"]', timeout=20000)
    irr_card = p.locator('[data-metric-label="Project IRR"]')
    assert irr_card.get_attribute("data-metric-available") == "true"
    canonical_irr = irr_card.get_attribute("data-metric-canonical")
    assert canonical_irr == f"{ws.last_runtime_summary['project_irr'] * 100:.2f}%"
    unavailable_cards = p.locator('[data-metric-available="false"], [data-lender-metric-available="false"]')
    assert unavailable_cards.count() >= 1
    assert "Not available" in unavailable_cards.first.inner_text()
    assert p.locator('[data-results-view="true"] [data-freshness="CURRENT"]').count() == 1

    # 3. Statements: annual and model-period axes, scrollable container, canonical source disclosure
    s.nav_to("statements")
    p.wait_for_selector('[data-statements-view="true"][data-statements-state="CURRENT"]', timeout=20000)
    p.wait_for_selector('[data-statement-origin="canonical-run"]', timeout=20000)
    n_years = p.locator(".fm-sw-table thead tr:nth-child(2) th").count() - 1
    assert n_years >= 10
    p.locator("#fm-sw-view").select_option("model")
    p.wait_for_function(
        "n => document.querySelectorAll('.fm-sw-table thead tr:nth-child(2) th').length - 1 > n",
        arg=n_years,
    )
    scroll = p.evaluate("""() => {
        const w = document.querySelector('.fm-sw-region');
        return { role: w.getAttribute('role'), canScrollX: w.scrollWidth > w.clientWidth,
                 scrollWidth: w.scrollWidth, clientWidth: w.clientWidth };
    }""")
    assert scroll["role"] == "region" and scroll["canScrollX"]
    p.locator(".fm-sw-cell-button").first.click()
    trace_row = p.locator('[data-canonical-source="true"]')
    trace_row.wait_for(timeout=10000)
    assert "saved Run" in trace_row.inner_text()

    # 4. Overview drill-down, browser Back/Forward, and metric source evidence
    s.nav_to("overview")
    p.wait_for_selector(f'[data-financial-overview="true"][data-overview-snapshot="{ws.last_runtime_snapshot_id}"]', timeout=20000)
    p.locator('[data-overview-debt-metrics="true"] a').click()
    p.wait_for_function("() => document.querySelector('#wsv2-navigation [aria-current=\"page\"]')?.getAttribute('data-workspace-destination') === 'financing'")
    assert "financing=debt-metrics" in p.url
    s.nav_to("statements")
    s.nav_to("results")
    p.go_back()
    p.wait_for_function("() => document.querySelector('#wsv2-navigation [aria-current=\"page\"]')?.getAttribute('data-workspace-destination') === 'statements'")
    p.go_forward()
    p.wait_for_function("() => document.querySelector('#wsv2-navigation [aria-current=\"page\"]')?.getAttribute('data-workspace-destination') === 'results'")
    sources = p.locator('[data-metric-sources="true"]')
    sources.locator("summary").click()
    assert "Project IRR" in sources.inner_text()

    # 5. Real CAPEX edit via supported staged Save All / grid Save (one Save, zero hidden Run)
    s.nav_to("inputs/capex")
    first_cell = p.locator('[data-cost-grid="capex"] td.ci-col-amount input.ws2-cell:not([disabled])').first
    first_cell.wait_for(state="visible", timeout=20000)
    orig_exact = first_cell.get_attribute("data-exact")
    new_val = str(int(float(orig_exact)) + 1)
    first_cell.click()
    first_cell.fill(new_val)
    assert first_cell.get_attribute("data-changed") == "true"
    # Staging alone must NEVER persist or mutate workspace dirty state
    assert len(s.saves) == 0
    assert not get_workspace_state(s.uid, s.rec.project_id).dirty

    save_btn = p.locator('[data-cost-grid="capex"] [data-cost-save="true"]')
    save_btn.wait_for(timeout=10000)
    save_btn.click()
    p.wait_for_selector('[data-cost-grid="capex"] [data-tone="ok"]', timeout=20000)
    p.wait_for_function(
        "() => document.querySelector('[data-workflow-bar=\"true\"]')?.getAttribute('data-bar-freshness') === 'STALE'",
        timeout=20000,
    )
    assert len(s.saves) == 1 and s.saves[0].startswith("200 ")
    assert len(s.runs) == 1  # saving never triggers a hidden Run

    ws2 = get_workspace_state(s.uid, s.rec.project_id)
    assert ws2.dirty is True
    assert ws2.last_runtime_composite_hash == ws.last_runtime_composite_hash
    assert ws2.last_runtime_snapshot_id == ws.last_runtime_snapshot_id
    assert len(get_run_history(s.uid, s.rec.project_id)) == 1

    # 6. STALE everywhere; prior Run figures remain immutable and labeled stale
    s.nav_to("results")
    p.wait_for_selector('[data-financial-page="results"][data-financial-state="STALE"]', timeout=20000)
    assert p.locator('[data-results-view="true"] [data-stale-banner="true"]').is_visible()
    assert p.locator('[data-metric-label="Project IRR"]').get_attribute("data-metric-canonical") == canonical_irr
    s.nav_to("statements")
    p.wait_for_selector('[data-statements-view="true"][data-statements-state="STALE"]', timeout=20000)
    assert p.locator('[data-stale-banner="true"]').is_visible()
    s.nav_to("inputs/capex")
    s.nav_to("results")
    assert s.freshness() == "STALE"

    # 7. Explicit second Run -> CURRENT, new snapshot & history entry
    s.run()
    assert len(s.runs) == 2 and s.runs[1].startswith("200 ")
    ws3 = get_workspace_state(s.uid, s.rec.project_id)
    assert not ws3.dirty
    assert ws3.last_runtime_snapshot_id != ws.last_runtime_snapshot_id
    assert ws3.last_runtime_composite_hash != ws.last_runtime_composite_hash
    assert len(get_run_history(s.uid, s.rec.project_id)) == 2
    assert not s.pageerrors, s.pageerrors
    assert not s.http_errors, s.http_errors


def test_deep_link_activates_the_section_and_highlights_the_nav(make):
    s = make("u-wcb-deep")
    s.open("#inputs/revenue")
    s.page.wait_for_selector('[data-revenue-assumptions="true"]', timeout=20000)
    assert s.nav_current() == "inputs/revenue"
    s.open("#statements")
    s.page.wait_for_selector('#statement-workbook, [data-statements-view="true"]', timeout=20000)
    assert s.nav_current() == "statements"
    assert not s.pageerrors, s.pageerrors


def test_keyboard_navigation_in_the_nav(make):
    s = make("u-wcb-kbd")
    s.open("#overview")
    first = s.page.locator('#wsv2-navigation [data-workspace-destination="inputs/project"]')
    first.focus()
    s.page.keyboard.press("ArrowDown")
    assert s.page.evaluate("document.activeElement.getAttribute('data-workspace-destination')") == "inputs/technical"
    s.page.keyboard.press("Enter")
    s.page.wait_for_function(
        "() => document.querySelector('#wsv2-navigation [aria-current=\"page\"]')?.getAttribute('data-workspace-destination') === 'inputs/technical'"
    )
    assert s.nav_current() == "inputs/technical"
    assert not s.pageerrors, s.pageerrors


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_strip_and_statements_are_readable_in_light_and_dark(make, scheme):
    s = make(f"u-wcb-theme-{scheme}", scheme=scheme)
    s.open()
    s.run()
    s.nav_to("results")
    s.page.wait_for_selector('[data-financial-page="results"][data-financial-state="CURRENT"]', timeout=20000)
    contrast = s.page.evaluate("""() => {
      const parse = c => {
        const m = c.match(/[\\d.]+/g);
        if (!m) return null;
        return m.map(Number);
      };
      const lum = ([r, g, b]) => {
        const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); };
        return .2126 * f(r) + .7152 * f(g) + .0722 * f(b);
      };
      const bg = el => {
        while (el) {
          const c = getComputedStyle(el).backgroundColor;
          const p = parse(c);
          if (p && (p.length < 4 || p[3] > 0.05)) return p;
          el = el.parentElement;
        }
        return [255, 255, 255];
      };
      const ratio = el => {
        const fg = parse(getComputedStyle(el).color);
        const f = lum(fg), b = lum(bg(el));
        return (Math.max(f, b) + .05) / (Math.min(f, b) + .05);
      };
      return ['.rx-live-kpi-label', '.rx-live-kpi-value', '.ci-bar-id strong']
        .map(q => [q, ratio(document.querySelector(q))]);
    }""")
    for q, r in contrast:
        assert r >= 4.5, (scheme, q, r)
    s.nav_to("statements")
    s.page.wait_for_selector(".fm-sw-cell-button", timeout=20000)
    cell_color = s.page.evaluate("getComputedStyle(document.querySelector('.fm-sw-cell-button')).color")
    assert cell_color and not s.pageerrors, s.pageerrors


def test_narrow_viewport_keeps_nav_statements_and_strip_usable(make):
    s = make("u-wcb-narrow", viewport={"width": 390, "height": 844})
    s.open()
    s.run()
    menu = s.page.locator(".wsv2-menu")
    assert menu.is_visible() and menu.get_attribute("aria-expanded") == "false"
    menu.click()
    nav_box = s.page.locator("#wsv2-navigation").bounding_box()
    assert nav_box is not None and nav_box["width"] <= 392
    assert s.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    s.nav_to("statements")
    s.page.wait_for_selector(".fm-sw-table", timeout=20000)
    assert s.nav_current() == "statements"
    overflow = s.page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 1
    assert s.page.evaluate("document.querySelector('.fm-sw-region').scrollWidth > document.querySelector('.fm-sw-region').clientWidth")
    assert s.page.locator('[data-workflow-bar="true"]').count() == 1
    assert not s.pageerrors, s.pageerrors


def test_overview_tiles_drill_down_to_their_authoritative_sheet(make):
    s = make("u-wcb-drill")
    s.open()
    s.run()
    p = s.page
    s.nav_to("overview")
    p.wait_for_selector('[data-financial-overview="true"] [data-overview-debt-metrics="true"] a', timeout=20000)
    p.locator('[data-overview-debt-metrics="true"] a').click()
    p.wait_for_function("() => document.querySelector('#wsv2-navigation [aria-current=\"page\"]')?.getAttribute('data-workspace-destination') === 'financing'")
    assert "financing=debt-metrics" in p.url
    s.nav_to("overview")
    results_link = p.locator('[data-financial-overview="true"] a[href="#results"]')
    results_link.focus()
    p.keyboard.press("Enter")
    p.wait_for_function("() => document.querySelector('#wsv2-navigation [aria-current=\"page\"]')?.getAttribute('data-workspace-destination') === 'results'")
    s.nav_to("overview")
    p.locator('[data-financial-overview="true"] a[href="#statements"]').click()
    p.wait_for_function("() => document.querySelector('#wsv2-navigation [aria-current=\"page\"]')?.getAttribute('data-workspace-destination') === 'statements'")
    assert not s.pageerrors and not s.http_errors
