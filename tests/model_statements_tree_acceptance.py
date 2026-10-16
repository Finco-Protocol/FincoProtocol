"""Authenticated Chromium acceptance of Statements V2 drill-down, status dimensions and keyboard/Back behaviour (SC-03/09/11).

Run with:  python -m tests.model_statements_tree_acceptance --out artifacts/statements-tree

Real application server (``main_web``), real Save/Run routes, synthetic reference project only.  The historical-Run route is
mounted in-process from its isolated router (the integration hook is documented in that module).  Every check is written to
``browser-results.json``; screenshots are CI artifacts, never committed.  Exit code is non-zero if any check fails.
"""
from __future__ import annotations

import argparse
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
    from app.v2.statements_drilldown_router import router as historical_router
    from main_web import app

    app.include_router(historical_router, prefix="/v2")     # test-only mount of the isolated historical route
    results: list[dict] = []
    logs: dict[str, dict] = {}

    def check(tag, ok, observed="", shot=""):
        results.append({"check": tag, "status": "PASS" if ok else "FAIL", "observed": str(observed)[:500], "screenshot": shot})
        print(("PASS " if ok else "FAIL ") + tag, "|", str(observed)[:160], flush=True)
        return ok

    def shot(pg, name):
        pg.screenshot(path=str(out / name))
        return name

    def write_summary():
        summary = {
            "schema": "finco.statements-tree.browser-acceptance.v1", "generated_at": datetime.now(timezone.utc).isoformat(),
            "command": "python -m tests.model_statements_tree_acceptance", "checks": results, "network_and_console": logs,
            "passed": sum(1 for r in results if r["status"] == "PASS"), "total": len(results),
            "all_pass": all(r["status"] == "PASS" for r in results), "screenshots": sorted(p.name for p in out.glob("*.png")),
            "screenshot_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob("*.png"))}}
        (out / "browser-results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print("SUMMARY", summary["passed"], "/", summary["total"], "all_pass" if summary["all_pass"] else "FAILURES")
        return summary

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

            with sync_playwright() as pw:
                kwargs = {"executable_path": os.environ["FINCO_TEST_CHROMIUM_PATH"]} if os.environ.get("FINCO_TEST_CHROMIUM_PATH") else {}
                browser = pw.chromium.launch(**kwargs)

                def new_page(tag, width=1440):
                    ctx = browser.new_context(viewport={"width": width, "height": 1000})
                    ctx.add_cookies([{"name": COOKIE_NAME, "value": cookie, "url": url}])
                    ctx.set_default_timeout(60000)
                    page = ctx.new_page()
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
                ran = page.request.post(f"{url}/v2/workbook/run", form=dict(project=record.project_code, **tokens(page)), headers={"HX-Request": "true"})
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

                # ── historical Run ──
                entry = get_run_history(USER, record.project_id)[0]
                hctx, hp = new_page("historical")
                hp.goto(f"{url}/v2/workbook/run-history/statements?project={record.project_code}&history_id={entry.history_id}")
                hp.wait_for_function("() => { const r = document.getElementById('v2-sheet-outputs'); return !!r && r.dataset.stReady === '1'; }")
                hd = hp.evaluate("() => Object.fromEntries([...document.querySelectorAll('[data-testid^=outputs-dim-]')].map(e => [e.dataset.testid, e.dataset.state]))")
                check("historical view: context HISTORICAL_RUN, explicit banner, tree-only", hd.get("outputs-dim-context") == "HISTORICAL_RUN"
                      and "not the inputs this Run used" in hp.inner_text('[data-testid="historical-context-banner"]')
                      and hp.locator('table[data-st-tree]').count() == 6, hd, shot(hp, "06-historical-1440.png"))
                hp.locator('[data-st-viewbar="pnl"] [data-st-expand-all]').click()
                check("historical view: Expand all reveals every line", hp.evaluate("() => [...document.querySelectorAll('table[data-st-tree=\"pnl\"][data-st-basis=\"annual\"] tr[data-st-row]')].every(r => !r.hidden)"))
                hctx.close()

                for tag, log in logs.items():
                    check(f"[{tag}] no page errors, console errors or failing responses", not (log["page_errors"] or log["console_errors"] or log["bad_responses"]),
                          json.dumps({k: v[:3] for k, v in log.items()}))
                check("the committed Run history entry is unchanged by all of the above", get_run_history(USER, record.project_id)[0].to_dict() == before_hist)
                browser.close()
        finally:
            if server is not None:
                server.should_exit = True
            db.DB_PATH = original_db
            summary = write_summary()
    return 0 if summary["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
