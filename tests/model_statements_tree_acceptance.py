"""Authenticated Chromium acceptance of Statements V2 drill-down, status dimensions and keyboard/Back behaviour (SC-03/09/11).

Run with:  python -m tests.model_statements_tree_acceptance --out artifacts/statements-tree

Real application server (``main_web``), real Save/Run routes, synthetic reference project only.  The historical-Run route is the
production-registered one (nothing is mounted by this script).  Every check is written to
``browser-results.json``; screenshots are CI artifacts, never committed.  Exit code is non-zero if any check fails.
"""
from __future__ import annotations

from tests.run_clone_csrf import post_valid_csrf

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
import re
import socket
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from tests.model_workspace_navigation import activate_destination

USER = "statements-tree-browser"


def focus_diagnostics(page):
    return page.evaluate("""() => {
      const a = document.activeElement, r = document.getElementById('v2-run-statements');
      return {url: location.href, hash: location.hash,
        focus: a && {html: a.outerHTML.slice(0, 2000), key: a.dataset.stKey,
          rowKey: a.closest('[data-st-row]')?.dataset.stKey,
          tabindex: a.getAttribute('tabindex'), link: a.hasAttribute('data-st-link'), href: a.getAttribute('href')},
        root: r && {ready: r.dataset.stReady, historyId: r.dataset.historyId, connected: r.isConnected},
        rows: r && [...r.querySelectorAll('table[data-st-basis="annual"][data-st-tree="pnl"] tr[data-st-row]')]
          .map(e => ({key:e.dataset.stKey, hidden:e.hidden, tabindex:e.getAttribute('tabindex'), expanded:e.getAttribute('aria-expanded')})),
        selectedOpex: document.getElementById('tab-opex')?.getAttribute('aria-selected'),
        events: window.__fincoStatementTrace || []};
    }""")


def record_browser_exception(out, results, error, step, pages):
    record = {"check": "uncaught browser exception", "status": "FAIL", "observed": str(error),
              "exception_type": type(error).__name__, "step": step["name"], "screenshot": ""}
    for page in reversed(pages):
        try:
            if page.is_closed():
                continue
            try:
                record["diagnostics"] = focus_diagnostics(page)
            except Exception as diagnostic_error:
                record["diagnostic_error"] = str(diagnostic_error)
            try:
                page.screenshot(path=str(out / "failure.png"), timeout=5000)
                record["screenshot"] = "failure.png"
            except Exception as screenshot_error:
                record["screenshot_error"] = str(screenshot_error)
            break
        except Exception:
            continue
    results.append(record)
    print("FAIL", record["step"], "|", record["exception_type"], str(error), flush=True)


@contextmanager
def browser_failure_guard(out, results, step, pages):
    # Capture the live page BEFORE Playwright tears it down, then retain the
    # original exception/exit status. Diagnostic failures cannot replace it.
    try:
        yield
    except BaseException as error:
        record_browser_exception(out, results, error, step, pages)
        raise


def write_browser_summary(out, results, logs):
    summary = {
        "schema": "finco.statements-tree.browser-acceptance.v1", "generated_at": datetime.now(timezone.utc).isoformat(),
        "command": "python -m tests.model_statements_tree_acceptance", "checks": results, "network_and_console": logs,
        "passed": sum(1 for r in results if r["status"] == "PASS"), "total": len(results),
        "all_pass": bool(results) and all(r["status"] == "PASS" for r in results),
        "screenshots": sorted(p.name for p in out.glob("*.png")),
        "screenshot_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob("*.png"))}}
    (out / "browser-results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("SUMMARY", summary["passed"], "/", summary["total"], "all_pass" if summary["all_pass"] else "FAILURES")
    return summary

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("artifacts/statements-tree"))
    args = parser.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    import uvicorn
    from playwright.sync_api import sync_playwright
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence import db
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.reference_seed_service import create_reference_seeded_project
    from main_web import app

    results: list[dict] = []
    logs: dict[str, dict] = {}

    def check(tag, ok, observed="", shot=""):
        step["name"] = tag
        results.append({"check": tag, "status": "PASS" if ok else "FAIL", "observed": str(observed)[:500], "screenshot": shot})
        if isinstance(observed, dict) and "focus" in observed:
            results[-1]["diagnostics"] = observed
        print(("PASS " if ok else "FAIL ") + tag, "|", str(observed)[:160], flush=True)
        return ok

    def shot(pg, name):
        pg.screenshot(path=str(out / name))
        return name

    pages = []
    step = {"name": "startup"}

    original_db = db.DB_PATH
    server = None
    with tempfile.TemporaryDirectory() as tmp:
        try:
            db.DB_PATH = str(Path(tmp) / "statements-tree.db")
            db.init_db()
            cookie = create_session_token(user_id=USER, username="admin")
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="off"))
            threading.Thread(target=server.run, daemon=True).start()
            deadline = time.monotonic() + 30
            while not server.started:
                assert time.monotonic() < deadline
                time.sleep(0.1)
            url = f"http://127.0.0.1:{port}"
            record = create_reference_seeded_project(user_id=USER, requested_name="Statements tree", template_source="generic_solar_reference", capacity_mw=16)

            with sync_playwright() as pw, browser_failure_guard(out, results, step, pages):
                kwargs = {"executable_path": os.environ["FINCO_TEST_CHROMIUM_PATH"]} if os.environ.get("FINCO_TEST_CHROMIUM_PATH") else {}
                browser = pw.chromium.launch(**kwargs)

                def new_page(tag, width=1440):
                    ctx = browser.new_context(viewport={"width": width, "height": 1000})
                    ctx.add_cookies([{"name": COOKIE_NAME, "value": cookie, "url": url}])
                    ctx.set_default_timeout(60000)
                    ctx.add_init_script("""(() => {
                      const trace = window.__fincoStatementTrace = [];
                      function record(e) {
                        const a = document.activeElement, row = a && a.closest('[data-st-row]');
                        trace.push({ms: performance.now(), event: e.type, key: e.key, hash: location.hash,
                          tag: a && a.tagName, id: a && a.id, row: row && row.dataset.stKey,
                          link: a && a.hasAttribute('data-st-link'), href: a && a.getAttribute('href')});
                        if (trace.length > 100) trace.shift();
                      }
                      ['focusin', 'keydown', 'popstate', 'htmx:beforeSwap', 'htmx:afterSwap']
                        .forEach(name => addEventListener(name, record, true));
                    })()""")
                    page = ctx.new_page()
                    pages.append(page)
                    log = logs.setdefault(tag, {"page_errors": [], "console_errors": [], "bad_responses": []})
                    page.on("pageerror", lambda e: log["page_errors"].append(str(e)))
                    page.on("console", lambda m: log["console_errors"].append(f"{m.text} @ {m.location.get('url')}") if m.type == "error" and "favicon" not in m.text and "favicon" not in (m.location.get("url") or "")
                            and not ("htmx.min.js" in m.text and "unsafe-eval" in m.text) else None)
                    page.on("response", lambda r: log["bad_responses"].append(f"{r.status} {r.url}") if r.status >= 400 and not r.url.endswith("/favicon.ico") else None)
                    return ctx, page

                def tokens(page):
                    html = page.content()
                    return {k: re.search(r'name="' + k + r'" value="([^"]*)"', html).group(1) for k in ("content_hash", "workbook_version")}

                ctx, page = new_page("main")
                page.goto(f"{url}/v2/workbook?project={record.project_code}")
                ran = post_valid_csrf(page.request, f"{url}/v2/workbook/run", form=dict(project=record.project_code, **tokens(page)), headers={"HX-Request": "true"})
                ws = get_workspace_state(USER, record.project_id)
                check("canonical Run committed", ran.status == 200 and bool(ws.last_runtime_summary) and not ws.dirty)
                history = get_run_history(USER, record.project_id)
                check("one immutable history entry exists", len(history) == 1, len(history))
                before_hist = history[0].to_dict()

                def open_outputs(pg, width):
                    pg.set_viewport_size({"width": width, "height": 1000})
                    pg.goto(f"{url}/v2/workbook?project={record.project_code}")
                    activate_destination(pg, "tab-outputs")
                    pg.wait_for_function("() => { const r = document.getElementById('v2-sheet-outputs'); return !!r && r.dataset.stReady === '1' && !!r.querySelector('[data-st-viewbar]'); }")

                def fresh_root(pg, old_marker):
                    pg.wait_for_function("(m) => { const r = document.getElementById('v2-sheet-outputs'); return !!r && r.dataset.stReady === '1' && window[m] !== r && !!r.querySelector('table[data-st-tree]'); }", arg=old_marker)

                open_outputs(page, 1440)
                dims = page.evaluate("() => Object.fromEntries([...document.querySelectorAll('[data-testid^=outputs-dim-]')].map(e => [e.dataset.testid, e.dataset.state]))")
                check("four independent status dimensions are shown", dims.get("outputs-dim-inputs") == "CURRENT" and dims.get("outputs-dim-engine") == "CURRENT_ENGINE"
                      and dims.get("outputs-dim-context") == "LAST_RUN" and dims.get("outputs-dim-integrity") in ("PASS", "INCOMPLETE", "FAIL", "UNAVAILABLE"), dims,
                      shot(page, "01-status-dimensions-1440.png"))

                # ── default is the unchanged flat view; the drill-down is opt-in ──
                check("flat statements are the default and the tree is hidden", page.locator('[data-st-pane="flat"]').first.is_visible()
                      and not page.locator('[data-st-pane="tree"]').first.is_visible())
                page.locator('[data-testid="st-view-tree-pnl"]').click()
                check("drill-down view opens; flat view hides", page.locator('[data-st-pane="tree"][data-st-statement="pnl"]').is_visible()
                      and not page.locator('[data-st-pane="flat"]').first.is_visible())
                tree = page.locator('table[data-st-tree="pnl"][data-st-basis="annual"]')
                visible_keys = lambda: page.evaluate("() => [...document.querySelectorAll('table[data-st-tree=\"pnl\"][data-st-basis=\"annual\"] tr[data-st-row]')].filter(r => !r.hidden).map(r => r.dataset.stKey)")
                check("tree starts collapsed (roots only)", visible_keys() == ["net_income_keur", "group:Equity roll-forward"], visible_keys())

                # ── chevron expands; the label link is a different control ──
                row = lambda key: tree.locator(f'tr[data-st-key="{key}"]')
                toggle = lambda key: row(key).locator("[data-st-toggle]")
                toggle("net_income_keur").click()
                toggle("earnings_before_tax_keur").click()
                toggle("ebit_keur").click()
                check("chevron expands and keeps aria-expanded in step", row("ebit_keur").get_attribute("aria-expanded") == "true"
                      and toggle("ebit_keur").get_attribute("aria-expanded") == "true"
                      and "operating_expenses_keur" in visible_keys(), visible_keys())
                controls = toggle("ebit_keur").get_attribute("aria-controls").split()
                check("aria-controls points at the revealed rows", all(page.locator(f"#{c}").count() == 1 for c in controls) and len(controls) == 3, controls)
                link = row("operating_expenses_keur").locator("[data-st-link]")
                check("label link and chevron are separate interactive elements", link.count() == 1 and row("operating_expenses_keur").locator("[data-st-toggle]").count() == 0
                      and link.get_attribute("href") == "#opex" and link.get_attribute("data-st-kind") == "input", link.get_attribute("href"))
                shot(page, "02-expanded-1440.png")

                # ── select a period, set a scroll offset, follow the link, press Back ──
                page.set_viewport_size({"width": 700, "height": 900})
                period_btn = tree.locator(".st-period").nth(3)
                period_date = period_btn.get_attribute("data-st-period")
                period_btn.click()
                check("period selection is exposed via aria-pressed", period_btn.get_attribute("aria-pressed") == "true")
                region = tree.locator("xpath=ancestor::div[@data-st-region]")
                region.evaluate("el => { el.scrollLeft = 160; }")
                scroll_before = region.evaluate("el => el.scrollLeft")
                link.focus()
                page.evaluate("() => { window.__old = document.getElementById('v2-sheet-outputs'); }")
                link.click()
                page.wait_for_function("() => location.hash === '#opex' && document.getElementById('tab-opex').getAttribute('aria-selected') === 'true'")
                check("following the link opens the OPEX assumptions", page.get_attribute("#tab-opex", "aria-selected") == "true", page.url[-30:],
                      shot(page, "03-opex-assumptions-700.png"))
                page.go_back()
                page.wait_for_function("() => location.hash === '#outputs' && document.getElementById('tab-outputs').getAttribute('aria-selected') === 'true'")
                fresh_root(page, "__old")
                tree = page.locator('table[data-st-tree="pnl"][data-st-basis="annual"]')
                page.wait_for_function("() => document.activeElement && document.activeElement.dataset && document.activeElement.dataset.stKey === 'operating_expenses_keur'")
                restored = {
                    "view": page.locator('[data-st-pane="tree"][data-st-statement="pnl"]').is_visible(),
                    "expanded": [k for k in ("net_income_keur", "earnings_before_tax_keur", "ebit_keur") if tree.locator(f'tr[data-st-key="{k}"]').get_attribute("aria-expanded") == "true"],
                    "period": tree.locator('.st-period[aria-pressed="true"]').get_attribute("data-st-period"),
                    "focus": page.evaluate("() => document.activeElement.dataset.stKey"),
                    "scroll": tree.locator("xpath=ancestor::div[@data-st-region]").evaluate("el => el.scrollLeft")}
                check("Back restores statement, view, expansion, period, focused row and scroll",
                      restored["view"] and restored["expanded"] == ["net_income_keur", "earnings_before_tax_keur", "ebit_keur"] and restored["period"] == period_date
                      and restored["focus"] == "operating_expenses_keur" and abs(restored["scroll"] - scroll_before) <= 2, restored,
                      shot(page, "04-after-back-700.png"))
                check("the Run identity is unchanged after the round trip", ws.last_runtime_snapshot_id == page.get_attribute("#v2-sheet-outputs", "data-out-snapshot"))

                # ── keyboard ──
                page.set_viewport_size({"width": 1440, "height": 1000})
                tree = page.locator('table[data-st-tree="pnl"][data-st-basis="annual"]')
                row = lambda key: tree.locator(f'tr[data-st-key="{key}"]')
                row("net_income_keur").focus()
                active = lambda: page.evaluate("() => document.activeElement.dataset.stKey || document.activeElement.className")
                page.keyboard.press("ArrowLeft")                       # expanded root: collapses
                collapsed = row("net_income_keur").get_attribute("aria-expanded") == "false" and visible_keys() == ["net_income_keur", "group:Equity roll-forward"]
                page.keyboard.press("ArrowRight")                      # expands again
                page.keyboard.press("ArrowRight")                      # moves to first child
                check("Arrow keys collapse, expand and move into the tree", collapsed and active() == "earnings_before_tax_keur", (collapsed, active()))
                page.keyboard.press("ArrowLeft")                       # child expanded? -> collapse then parent
                page.keyboard.press("ArrowDown"); page.keyboard.press("ArrowUp"); page.keyboard.press("End")
                check("Home/End jump to first and last visible line", (page.keyboard.press("Home") or True) and active() == "net_income_keur", active())
                row("net_income_keur").focus()
                page.keyboard.press("Enter")
                enter_toggled = row("net_income_keur").get_attribute("aria-expanded")
                row("net_income_keur").locator("[data-st-toggle]").focus()
                page.keyboard.press("Space")
                space_toggled = row("net_income_keur").get_attribute("aria-expanded")
                page.keyboard.press("Enter")
                enter_button = row("net_income_keur").get_attribute("aria-expanded")
                check("Enter on a line and Enter/Space on the chevron toggle it", len({enter_toggled, space_toggled}) == 2 and enter_button != space_toggled,
                      (enter_toggled, space_toggled, enter_button))
                label_ok = row("net_income_keur").locator("[data-st-toggle]").get_attribute("aria-label")
                check("chevron accessible name follows the state", label_ok.startswith(("Expand", "Collapse")) and "net income" in label_ok.lower(), label_ok)
                row("net_income_keur").focus()
                page.keyboard.press("Tab")
                check("Tab from a line reaches its own chevron before leaving the table", page.evaluate("() => document.activeElement.matches('[data-st-toggle]')"))

                # ── values: the tree shows exactly the flat statement's persisted numbers ──
                same = page.evaluate("""() => {
                  const flat = (id, label) => { const tb = document.querySelector(`[data-out-table="${id}"]`); const tr = [...tb.querySelectorAll('tbody tr')].find(r => r.querySelector('th').textContent.trim().startsWith(label));
                    return [...tr.querySelectorAll('td')].map(td => td.dataset.raw); };
                  const tree = key => { const tr = document.querySelector(`table[data-st-tree="pnl"][data-st-basis="annual"] tr[data-st-key="${key}"]`);
                    return [...tr.querySelectorAll('td[data-raw]')].map(td => td.dataset.raw); };
                  return [['revenues_keur', 'Revenues'], ['operating_expenses_keur', 'Operating'], ['ebit_keur', 'EBIT']].map(([k, l]) => JSON.stringify(tree(k)) === JSON.stringify(flat('pnl-annual', l)));
                }""")
                check("tree values equal the flat statement values", all(same), same)
                check("no horizontal page scroll at 1440", page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"))

                # ── responsive containment ──
                for width in (1440, 768, 390):
                    ctx2, pg = new_page(f"w{width}", width)
                    open_outputs(pg, width)
                    pg.locator('[data-testid="st-view-tree-pnl"]').click()
                    pg.locator('table[data-st-tree="pnl"][data-st-basis="annual"] tr[data-st-key="net_income_keur"] [data-st-toggle]').click()
                    geometry = pg.evaluate("""() => { const r = document.querySelector('table[data-st-tree="pnl"][data-st-basis="annual"]').closest('[data-st-region]');
                      return {pageOverflow: document.documentElement.scrollWidth - window.innerWidth, regionOverflowX: getComputedStyle(r).overflowX,
                              regionClient: r.clientWidth, regionScroll: r.scrollWidth, regionRight: r.getBoundingClientRect().right, viewport: window.innerWidth}; }""")
                    check(f"statement scrolling is contained within its region at {width}px",
                          geometry["pageOverflow"] <= 1 and geometry["regionOverflowX"] in ("auto", "scroll") and geometry["regionRight"] <= geometry["viewport"] + 1, geometry,
                          shot(pg, f"05-tree-{width}.png"))
                    ctx2.close()

                # ── Run History -> historical Statements -> Run detail (real UI, production registration) ──
                second = post_valid_csrf(page.request, f"{url}/v2/workbook/run", form=dict(project=record.project_code, **tokens(page)), headers={"HX-Request": "true"})
                entries = sorted(get_run_history(USER, record.project_id), key=lambda h: h.created_at)
                check("a second Run gives a second distinct history entry", second.status == 200 and len(entries) == 2 and entries[0].history_id != entries[1].history_id)
                before_hist = [h.to_dict() for h in entries]
                hctx, hp = new_page("history-flow")
                open_outputs(hp, 1440)                      # the Outputs sheet (#v2-sheet-outputs) is in the document ...
                hp.locator('[data-testid="st-view-tree-pnl"]').click()
                hp.locator('table[data-st-tree="pnl"][data-st-basis="annual"] tr[data-st-key="net_income_keur"] [data-st-toggle]').click()
                outputs_state = hp.evaluate("() => window.__fincoStatements.capture().statements.pnl")
                activate_destination(hp, "tab-run-history")  # ... while the Run History sheet is used
                hp.wait_for_selector('[data-testid="run-history-detail-1"]')
                row_ids = hp.evaluate("() => [...document.querySelectorAll('#v2-sheet-run-history tr[data-history-id]')].map(r => r.dataset.historyId)")
                hp.locator('[data-testid="run-history-detail-1"]').click()
                hp.wait_for_selector("#v2-run-detail")
                open_btn = hp.locator('[data-testid="run-detail-open-statements"]')
                chosen = open_btn.get_attribute("data-history-id")
                check("Run detail offers the statements link for the selected Run", open_btn.count() == 1 and chosen == row_ids[0], (chosen, row_ids))
                open_btn.click()
                hp.wait_for_function("() => { const r = document.getElementById('v2-run-statements'); return !!r && r.dataset.stReady === '1'; }")
                dup = lambda: hp.evaluate("() => { const ids = [...document.querySelectorAll('[id]')].map(e => e.id); return ids.filter((x, i) => ids.indexOf(x) !== i); }")
                check("historical statements show exactly the selected Run; no duplicate DOM ids",
                      hp.get_attribute("#v2-run-statements", "data-history-id") == chosen
                      and hp.get_attribute("#v2-run-statements", "data-out-snapshot") == next(e.runtime_snapshot_id for e in entries if e.history_id == chosen)
                      and dup() == [] and hp.locator("#v2-sheet-outputs").count() == 1 and hp.locator("#v2-run-detail").count() == 0, dup(),
                      shot(hp, "06-historical-from-run-history-1440.png"))
                check("focus lands on the statements heading", hp.evaluate("() => document.activeElement && document.activeElement.id") == "rh-stmt-title")
                htree = hp.locator('#v2-run-statements table[data-st-tree="pnl"][data-st-basis="annual"]')
                htree.locator('tr[data-st-key="net_income_keur"] [data-st-toggle]').click()
                htree.locator('tr[data-st-key="earnings_before_tax_keur"] [data-st-toggle]').click()
                hdate = htree.locator(".st-period").nth(2).get_attribute("data-st-period")
                htree.locator(".st-period").nth(2).click()
                htree.locator('tr[data-st-key="ebit_keur"] [data-st-link]').focus()
                hp.wait_for_timeout(50)
                # "Back to Run detail" drives the browser Back, returns focus to the opener
                hp.locator('[data-testid="historical-back-to-detail"]').click()
                hp.wait_for_selector("#v2-run-detail")
                hp.wait_for_function("() => document.activeElement && document.activeElement.dataset && document.activeElement.dataset.testid === 'run-detail-open-statements'")
                check("Back to Run detail returns to the same Run detail with focus on the opener", hp.get_attribute('[data-testid="run-detail-open-statements"]', "data-history-id") == chosen
                      and hp.locator("#v2-run-statements").count() == 0 and dup() == [])
                hp.locator('[data-testid="run-detail-open-statements"]').click()
                hp.wait_for_function("() => { const r = document.getElementById('v2-run-statements'); return !!r && r.dataset.stReady === '1'; }")
                hp.wait_for_function("() => document.activeElement && document.activeElement.dataset && document.activeElement.dataset.stKey === 'ebit_keur'")
                htree = hp.locator('#v2-run-statements table[data-st-tree="pnl"][data-st-basis="annual"]')
                restored = {"expanded": [k for k in ("net_income_keur", "earnings_before_tax_keur") if htree.locator(f'tr[data-st-key="{k}"]').get_attribute("aria-expanded") == "true"],
                            "period": htree.locator('.st-period[aria-pressed="true"]').get_attribute("data-st-period")}
                check("reopening the same Run restores expansion, period and focused line", restored == {"expanded": ["net_income_keur", "earnings_before_tax_keur"], "period": hdate}, restored)
                # native browser Back / Forward
                hp.go_back()
                hp.wait_for_selector("#v2-run-detail")
                back_ok = hp.locator("#v2-run-statements").count() == 0
                hp.go_forward()
                hp.wait_for_function("() => !!document.getElementById('v2-run-statements')")
                check("native browser Back returns to the Run detail and Forward to the statements", back_ok and hp.locator("#v2-run-detail").count() == 0 and dup() == [])
                # keyboard only: Tab/arrows expand, Enter on a line link follows to the current Working Copy, Back returns to the same view
                hp.wait_for_function("() => document.getElementById('v2-run-statements').dataset.stReady === '1'")
                htree = hp.locator('#v2-run-statements table[data-st-tree="pnl"][data-st-basis="annual"]')
                htree.locator('tr[data-st-key="ebit_keur"]').focus()
                hp.keyboard.press("ArrowRight")
                keyboard_expanded = htree.locator('tr[data-st-key="ebit_keur"]').get_attribute("aria-expanded") == "true"
                hp.keyboard.press("ArrowDown")
                hp.keyboard.press("ArrowDown")
                step["name"] = "ArrowDown must focus historical operating expenses row"
                state = focus_diagnostics(hp)
                on_opex = state["focus"].get("key")
                assert on_opex == "operating_expenses_keur", json.dumps(state)
                check(step["name"], True, state)
                hp.keyboard.press("Tab")                      # to the line's link (its chevron is absent on a leaf)
                step["name"] = "Tab must focus the historical operating expenses link"
                state = focus_diagnostics(hp)
                assert (state["focus"].get("rowKey") == "operating_expenses_keur"
                        and state["focus"]["link"] and state["focus"]["href"] == "#opex"), json.dumps(state)
                check(step["name"], True, state)
                step["name"] = "Enter must follow the OPEX link and select OPEX"
                hp.keyboard.press("Enter")
                hp.wait_for_function("() => location.hash === '#opex' && document.getElementById('tab-opex').getAttribute('aria-selected') === 'true'")
                hp.go_back()
                hp.wait_for_function("() => location.hash === '#run-history' && document.getElementById('tab-run-history').getAttribute('aria-selected') === 'true'")
                hp.wait_for_function("(id) => { const r = document.getElementById('v2-run-statements'); return !!r && r.dataset.stReady === '1' && r.dataset.historyId === id; }", arg=chosen)
                same_dom = (hp.locator("#v2-run-statements").count() == 1 and hp.get_attribute("#v2-run-statements", "data-history-id") == chosen
                            and hp.locator('#v2-run-statements table[data-st-tree="pnl"][data-st-basis="annual"] tr[data-st-key="ebit_keur"]').get_attribute("aria-expanded") == "true")
                check("keyboard-only expansion and drill-down, then Back to the same historical view", keyboard_expanded and on_opex == "operating_expenses_keur" and same_dom,
                      (keyboard_expanded, on_opex, same_dom, hp.evaluate("() => ({stmts: document.querySelectorAll('#v2-run-statements').length, detail: document.querySelectorAll('#v2-run-detail').length, list: document.querySelectorAll('#v2-sheet-run-history').length, hid: (document.getElementById('v2-run-statements') || {dataset: {}}).dataset.historyId, hash: location.hash})"), chosen), shot(hp, "07-historical-after-keyboard-back-1440.png"))
                # Repeat actual native traversal, including deliberately delayed
                # HTMX responses. This is fault injection, not a wait for focus.
                def delayed_statements(route):
                    response = route.fetch()
                    time.sleep(0.15)
                    route.fulfill(response=response)

                for cycle in range(2):
                    hp.route('**/v2/workbook/run-history/statements?*', delayed_statements)
                    try:
                        step["name"] = f"delayed native Back/Forward cycle {cycle + 1}"
                        hp.go_back()
                        hp.wait_for_selector('#v2-run-detail')
                        hp.go_forward()
                        hp.wait_for_function("(id) => { const r = document.getElementById('v2-run-statements'); return r && r.dataset.stReady === '1' && r.dataset.historyId === id; }", arg=chosen)
                        htree = hp.locator('#v2-run-statements table[data-st-tree="pnl"][data-st-basis="annual"]')
                        # Back restores the expanded state captured when the
                        # link was followed. Start this NEW expansion scenario
                        # collapsed through its real control, after restoration.
                        if htree.locator('tr[data-st-key="ebit_keur"]').get_attribute('aria-expanded') == 'true':
                            htree.locator('tr[data-st-key="ebit_keur"] [data-st-toggle]').click()
                        htree.locator('tr[data-st-key="ebit_keur"]').focus()
                        hp.keyboard.press('ArrowRight')
                        hp.keyboard.press('ArrowDown')
                        hp.keyboard.press('ArrowDown')
                        state = focus_diagnostics(hp)
                        assert state['focus'].get('key') == 'operating_expenses_keur', json.dumps(state)
                        hp.keyboard.press('Tab')
                        state = focus_diagnostics(hp)
                        assert (state['focus'].get('rowKey') == 'operating_expenses_keur'
                                and state['focus']['link'] and state['focus']['href'] == '#opex'), json.dumps(state)
                        hp.keyboard.press('Enter')
                        hp.wait_for_function("location.hash === '#opex' && document.getElementById('tab-opex').getAttribute('aria-selected') === 'true'")
                        hp.go_back()
                        hp.wait_for_function("(id) => { const r = document.getElementById('v2-run-statements'); return location.hash === '#run-history' && r && r.dataset.stReady === '1' && r.dataset.historyId === id; }", arg=chosen)
                        check(step["name"], dup() == [] and hp.locator('#v2-run-detail').count() == 0,
                              state, shot(hp, f"07-delayed-history-cycle-{cycle + 1}.png"))
                    finally:
                        hp.unroute('**/v2/workbook/run-history/statements?*', delayed_statements)
                # the Outputs sheet is untouched by the historical flow
                activate_destination(hp, "tab-outputs")
                hp.wait_for_function("() => { const r = document.getElementById('v2-sheet-outputs'); return !!r && r.dataset.stReady === '1' && !!r.querySelector('table[data-st-tree]'); }")
                check("Outputs workspace still works and is a single root", hp.locator("#v2-sheet-outputs").count() == 1 and hp.locator("#v2-sheet-outputs table.out-table").count() >= 7 and dup() == [])
                # subsequent selection: the other Run opens its own evidence
                activate_destination(hp, "tab-run-history")
                hp.evaluate("() => { const l = document.querySelector('#v2-run-statements [data-rh-back-detail]'); if (l) l.click(); }")
                hp.wait_for_selector("#v2-run-detail")
                hp.locator('[data-testid="run-detail-back"]').click()
                hp.wait_for_selector('[data-testid="run-history-detail-2"]')
                hp.locator('[data-testid="run-history-detail-2"]').click()
                hp.wait_for_selector('[data-testid="run-detail-open-statements"]')
                hp.locator('[data-testid="run-detail-open-statements"]').click()
                hp.wait_for_function("(id) => { const r = document.getElementById('v2-run-statements'); return !!r && r.dataset.stReady === '1' && r.dataset.historyId === id; }", arg=row_ids[1])
                check("a different Run selected afterwards shows its own immutable evidence", hp.get_attribute("#v2-run-statements", "data-history-id") == row_ids[1] != chosen
                      and dup() == [])
                # responsive containment of the historical view
                for width in (768, 390):
                    hp.set_viewport_size({"width": width, "height": 1000})
                    hp.wait_for_function("(w) => window.innerWidth === w", arg=width)
                    hp.wait_for_timeout(300)                      # let the responsive layout settle before measuring
                    g = hp.evaluate("""() => { const r = [...document.querySelectorAll('#v2-run-statements [data-st-region]')].find(e => e.offsetParent !== null); return {page: document.documentElement.scrollWidth - window.innerWidth,
                        overflowX: getComputedStyle(r).overflowX, right: r.getBoundingClientRect().right, vw: window.innerWidth,
                        offenders: [...document.querySelectorAll('body *')].filter(e => e.getBoundingClientRect().right > window.innerWidth + 1 && e.getBoundingClientRect().width > 0 && !e.closest('[data-st-region] table'))
                          .sort((a, b) => b.getBoundingClientRect().right - a.getBoundingClientRect().right).slice(0, 6).map(e => e.tagName + '#' + e.id + '.' + String(e.className).slice(0, 40) + ' r=' + Math.round(e.getBoundingClientRect().right))}; }""")
                    check(f"historical statements scrolling is contained at {width}px", g["page"] <= 1 and g["overflowX"] in ("auto", "scroll") and g["right"] <= g["vw"] + 1, g,
                          shot(hp, f"08-historical-{width}.png"))
                after = {h.history_id: h.to_dict() for h in get_run_history(USER, record.project_id)}
                check("opening, navigating and returning never changed or added a committed Run", after == {h["history_id"]: h for h in before_hist}, len(after))
                hctx.close()

                for tag, log in logs.items():
                    check(f"[{tag}] no page errors, console errors or failing responses", not (log["page_errors"] or log["console_errors"] or log["bad_responses"]),
                          json.dumps({k: v[:3] for k, v in log.items()}))
                check("the committed Run history is unchanged by all of the above", {h.history_id: h.to_dict() for h in get_run_history(USER, record.project_id)} == {h["history_id"]: h for h in before_hist})
                browser.close()
        except BaseException as error:
            if not any(r.get("check") == "uncaught browser exception" for r in results):
                record_browser_exception(out, results, error, step, [])
            raise
        finally:
            if server is not None:
                server.should_exit = True
            db.DB_PATH = original_db
            summary = write_browser_summary(out, results, logs)
    return 0 if summary["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
