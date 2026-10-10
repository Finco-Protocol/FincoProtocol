"""Authenticated Chromium acceptance of the Statements & Debt output workspace (WF-06).

Run with:  python -m tests.model_outputs_workspace_acceptance --out artifacts/outputs-workspace

Real application server, real Save/Run routes, synthetic reference projects only (Solar and Wind with two Senior
facilities, Data Center and EV with the aggregate Senior schedule).  Every check is recorded in
``browser-results.json``; screenshots are written next to it and are CI artifacts, never committed.
Exit code is non-zero if any check fails.
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

USER = "outputs-browser"
FAVICON = "/favicon.ico"
KINDS = ("solar", "wind", "data_center", "ev_charging")
F3_KINDS = ("solar", "wind")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("artifacts/outputs-workspace"))
    args = parser.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    import uvicorn
    from playwright.sync_api import sync_playwright
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence import db
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.project_library_service import ensure_reference_models
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.workbook.input_set import ProjectInputSet
    from app.workbook import multisenior_config as config
    from app.workbook.service import WorkbookService
    from app.runtime.model_execution import reset_model_executor_for_tests
    from tests.model_financing_browser_acceptance import contrast
    from tests.test_model_financing_f3_workspace import collection_for_inputs, state
    from main_web import app

    results: list[dict] = []
    net_errors: dict[str, dict] = {}
    # Findings present on origin/main and untouched by this PR; itemised in browser-results.json, never hidden.
    known: dict = {}

    def drop_known_csp(log: dict) -> dict:
        htmx_csp = [e for e in log["console_errors"] if "htmx.min.js" in e and "unsafe-eval" in e]
        known["htmx_trigger_filter_csp_eval_errors"] = known.get("htmx_trigger_filter_csp_eval_errors", 0) + len(htmx_csp)
        return {**log, "console_errors": [e for e in log["console_errors"] if e not in htmx_csp]}

    def check(tag, ok, observed="", shot=""):
        results.append({"check": tag, "status": "PASS" if ok else "FAIL", "observed": str(observed)[:500], "screenshot": shot})
        print(("PASS " if ok else "FAIL ") + tag, "|", str(observed)[:160], flush=True)
        return ok

    original_db = db.DB_PATH
    server = thread = None
    with tempfile.TemporaryDirectory() as tmp:
        try:
            db.DB_PATH = str(Path(tmp) / "outputs.db")
            db.init_db()
            ensure_reference_models()
            cookie = create_session_token(user_id=USER, username="admin")
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="off"))
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            deadline = time.monotonic() + 30
            while not server.started:
                assert time.monotonic() < deadline
                time.sleep(0.1)
            url = f"http://127.0.0.1:{port}"
            mk = lambda kind: create_reference_seeded_project(
                user_id=USER, requested_name=f"Outputs {kind}", template_source=f"generic_{kind}_reference", capacity_mw=16)

            with sync_playwright() as pw:
                kwargs = {"executable_path": os.environ["FINCO_TEST_CHROMIUM_PATH"]} if os.environ.get("FINCO_TEST_CHROMIUM_PATH") else {}
                browser = pw.chromium.launch(**kwargs)

                def new_page(tag, width=1440, scheme="light"):
                    ctx = browser.new_context(viewport={"width": width, "height": 1000}, color_scheme=scheme)
                    ctx.add_cookies([{"name": COOKIE_NAME, "value": cookie, "url": url}])
                    ctx.set_default_timeout(60000)
                    page = ctx.new_page()
                    log = net_errors.setdefault(tag, {"page_errors": [], "console_errors": [], "bad_responses": []})
                    page.on("pageerror", lambda e: log["page_errors"].append(str(e)))
                    page.on("console", lambda m: log["console_errors"].append(m.text) if m.type == "error" and FAVICON not in (m.location.get("url") or "") and "favicon" not in m.text else None)
                    page.on("response", lambda r: log["bad_responses"].append(f"{r.status} {r.url}") if r.status >= 400 and not r.url.endswith(FAVICON) else None)
                    return ctx, page

                def shot(page, name, full=False):
                    page.screenshot(path=str(out / name), full_page=full)
                    return name

                def tokens(page):
                    html = page.content()
                    return {k: re.search(r'name="' + k + r'" value="([^"]*)"', html).group(1) for k in ("content_hash", "workbook_version")}

                def post(page, path, data):
                    return page.request.post(f"{url}{path}", form=data, headers={"HX-Request": "true"})

                def open_outputs(page, record, theme="light", width=1440):
                    page.emulate_media(color_scheme=theme)
                    page.set_viewport_size({"width": width, "height": 1000})
                    page.goto(f"{url}/v2/workbook?project={record.project_code}")
                    page.evaluate("(t) => document.documentElement.setAttribute('data-theme', t)", theme)
                    page.locator("#tab-outputs").click()
                    page.wait_for_selector('#v2-sheet-outputs[data-out-state="CURRENT"], #v2-sheet-outputs[data-out-state="STALE"], #v2-sheet-outputs[data-out-state="NOT_RUN"]')
                    page.wait_for_selector('[data-testid="outputs-toolbar"], [data-testid="outputs-not-run"]')
                    page.wait_for_load_state("networkidle")   # the tab may be fetched twice (restore + click); let the DOM settle
                    page.wait_for_selector('[data-testid="outputs-toolbar"], [data-testid="outputs-not-run"]')
                    page.wait_for_function("() => document.getElementById('v2-sheet-outputs').getAttribute('data-out-ready') === '1'")

                def cell_text(page, table_id, row_label, col=0):
                    return page.evaluate(
                        """([t, label, col]) => { const tb = document.querySelector(`[data-out-table="${t}"]`);
                        const tr = [...tb.querySelectorAll('tbody tr')].find(r => r.querySelector('th').textContent.trim().startsWith(label));
                        const td = tr.querySelectorAll('td')[col]; return [td.textContent.trim(), td.dataset.raw]; }""",
                        [table_id, row_label, col])

                for kind in KINDS:
                    record = mk(kind)
                    is_f3 = kind in F3_KINDS
                    ctx, page = new_page(kind)
                    # ── NOT_RUN ──
                    open_outputs(page, record)
                    f = shot(page, f"{kind}-00-not-run-light-1440.png")
                    check(f"[{kind}] NOT_RUN: status shown, no table, no fabricated zero",
                          page.get_attribute('[data-testid="outputs-state"]', "data-state") == "NOT_RUN"
                          and page.locator("table.out-table").count() == 0 and "No Run has been committed" in page.inner_text("#v2-sheet-outputs"), "", f)
                    # ── commit a real Run (F3 active for Solar/Wind) ──
                    if is_f3:
                        ws = get_workspace_state(USER, record.project_id)
                        pi = ProjectInputSet.from_snapshot(ws.draft_snapshot).to_projectinputs()
                        saved = post(page, "/v2/workbook/update", dict(project=record.project_code, field_id=config.FIELD_ID, sheet_id="debt",
                                     value=state(active=True, collection=collection_for_inputs(pi)), **tokens(page)))
                        check(f"[{kind}] F3 activation saved through the real CAS route", saved.status == 200 and "field-error-banner" not in saved.text())
                    page.goto(f"{url}/v2/workbook?project={record.project_code}")
                    ran = post(page, "/v2/workbook/run", dict(project=record.project_code, **tokens(page)))
                    ws = get_workspace_state(USER, record.project_id)
                    rr = WorkbookService.get_runtime_result(ws)
                    check(f"[{kind}] canonical Run committed", ran.status == 200 and bool(ws.last_runtime_summary) and not ws.dirty)
                    # ── CURRENT desktop light ──
                    open_outputs(page, record)
                    snapshot = ws.last_runtime_snapshot_id
                    toolbar = page.inner_text('[data-testid="outputs-toolbar"]')
                    state_attr = page.get_attribute('[data-testid="outputs-state"]', "data-state")
                    f = shot(page, f"{kind}-01-current-toolbar-light-1440.png")
                    check(f"[{kind}] toolbar: CURRENT, reconciliation indicator, Run Integrity, Run identity and timestamp",
                          state_attr == "CURRENT" and page.get_attribute('[data-testid="outputs-reconciliation"]', "data-state") == "RECONCILED"
                          and page.get_attribute('[data-testid="outputs-integrity"]', "data-state") == "PASS"
                          and snapshot[:22] in page.inner_text('[data-testid="outputs-identity"]') and "Base Case" in toolbar
                          and page.locator("[data-out-unit]").count() == 2 and page.locator("[data-out-precision]").count() == 1
                          and page.locator("[data-out-year0]").count() == 1, page.inner_text('[data-testid="outputs-identity"]'), f)
                    sections = [page.locator(f'[data-testid="out-section-{s}"]').count() for s in ("pnl", "balance_sheet", "cash_flow", "cfads", "debt", "returns")]
                    check(f"[{kind}] all six sections present (P&L, Balance Sheet, Cash Flow, CFADS, Debt, Distributions & Returns)", sections == [1] * 6, sections)
                    facilities = page.locator('[data-testid="out-facility"]').count()
                    expected = 2 if is_f3 else 1
                    check(f"[{kind}] debt workspace shows {expected} facility block(s)"
                          + (" (Senior A / Senior B separately with own maturity)" if is_f3 else " (aggregate Senior; unexposed terms labelled)"),
                          facilities == expected and (not is_f3 or page.locator('[data-testid="out-maturity"]').count() == 2))
                    # ── unit / precision / Year 0 are formatting only ──
                    raw_before = cell_text(page, "pnl", "Revenues", 5)
                    page.locator('[data-out-unit][value="eur"]').check()
                    after_eur = cell_text(page, "pnl", "Revenues", 5)
                    page.locator("[data-out-precision]").select_option("0")
                    after_dec = cell_text(page, "pnl", "Revenues", 5)
                    cols_before = page.locator('[data-out-table="pnl"] thead th:visible').count()
                    page.locator("[data-out-year0]").uncheck()
                    cols_after = page.locator('[data-out-table="pnl"] thead th:visible').count()
                    f = shot(page, f"{kind}-02-eur-0dp-no-year0-light-1440.png")
                    expected_eur = f"{round(float(raw_before[1]) * 1000):,}"
                    check(f"[{kind}] toolbar: EUR / 0 decimals / hide Year 0 reformat the same persisted numbers",
                          after_eur[1] == raw_before[1] and after_dec[0] == expected_eur and cols_after == cols_before - 1, f"{raw_before} -> {after_eur} -> {after_dec}; columns {cols_before}->{cols_after}", f)
                    page.locator('[data-out-unit][value="keur"]').check()
                    page.locator("[data-out-precision]").select_option("2")
                    page.locator("[data-out-year0]").check()
                    check(f"[{kind}] toolbar reset restores the persisted kEUR display",
                          cell_text(page, "pnl", "Revenues", 5)[0] == raw_before[0])
                    # ── sticky labels + keyboard ──
                    region = page.locator('[data-out-table="pnl"]').locator("xpath=ancestor::div[@data-out-scroll]")
                    region.scroll_into_view_if_needed()
                    region.focus()
                    before = region.evaluate("e => e.scrollLeft")
                    page.keyboard.press("ArrowRight"); page.keyboard.press("ArrowRight")
                    scrolled = region.evaluate("e => e.scrollLeft")
                    label_box = page.locator('[data-out-table="pnl"] tbody th').first.bounding_box()
                    region_box = region.bounding_box()
                    sticky = page.evaluate("() => getComputedStyle(document.querySelector('[data-out-table=pnl] tbody th')).position")
                    f = shot(page, f"{kind}-03-sticky-labels-scrolled-light-1440.png")
                    check(f"[{kind}] keyboard: scroll region is focusable, arrows scroll; line-item labels stay sticky",
                          scrolled > before and sticky == "sticky" and abs(label_box["x"] - region_box["x"]) <= 3
                          and page.evaluate("() => document.activeElement.hasAttribute('data-out-scroll')"), f"scrollLeft {before}->{scrolled}", f)
                    # ── debt section visual ──
                    page.locator('[data-testid="out-section-debt"]').scroll_into_view_if_needed()
                    f = shot(page, f"{kind}-04-debt-workspace-light-1440.png")
                    unpaid = page.locator('[data-testid="out-unpaid"]').first.inner_text()
                    check(f"[{kind}] debt workspace shows maturity, unpaid obligation and committed values", "fully repaid" in unpaid or "UNPAID" in unpaid, unpaid, f)
                    # ── themes x viewports ──
                    for theme, width in (("light", 1440), ("dark", 1440), ("light", 390), ("dark", 390)):
                        open_outputs(page, record, theme, width)
                        region_ok = page.evaluate(
                            "(w) => [...document.querySelectorAll('[data-out-scroll]')].every(r => r.getBoundingClientRect().right <= w + 1 && r.getBoundingClientRect().left >= -1)", width)
                        colors = page.evaluate("() => { const td = document.querySelector('[data-out-table=pnl] tbody td.out-num'); const s = getComputedStyle(td); return [s.color, s.backgroundColor]; }")
                        label_colors = page.evaluate("() => { const th = document.querySelector('[data-out-table=pnl] tbody th'); const s = getComputedStyle(th); return [s.color, s.backgroundColor]; }")
                        toolbar_box = page.locator('[data-testid="outputs-toolbar"]').bounding_box()
                        controls_visible = all(page.locator(s).first.is_visible() for s in ("[data-out-precision]", "[data-out-year0]", '[data-testid="outputs-state"]'))
                        page.locator('[data-testid="outputs-toolbar"]').scroll_into_view_if_needed()
                        f = shot(page, f"{kind}-05-{theme}-{width}.png")
                        check(f"[{kind}] {theme} {width}px: tables contained, toolbar visible, contrast >= 4.5",
                              region_ok and controls_visible and toolbar_box["x"] >= -1 and toolbar_box["x"] + toolbar_box["width"] <= width + 1
                              and contrast(colors) >= 4.5 and contrast(label_colors) >= 4.5, f"contrast {contrast(colors):.1f}/{contrast(label_colors):.1f}", f)
                    page.set_viewport_size({"width": 390, "height": 900})
                    page.locator('[data-testid="out-section-debt"]').scroll_into_view_if_needed()
                    shot(page, f"{kind}-06-debt-mobile-390.png")
                    page.set_viewport_size({"width": 1440, "height": 1000})
                    # ── STALE identifies the previous Run ──
                    page.goto(f"{url}/v2/workbook?project={record.project_code}")
                    if is_f3:
                        from dataclasses import replace
                        from finco_core.inputs.financing_instruments import FinancingCollection
                        base = collection_for_inputs(ProjectInputSet.from_snapshot(get_workspace_state(USER, record.project_id).draft_snapshot).to_projectinputs())
                        first = replace(base.instruments[0], interest=replace(base.instruments[0].interest, fixed_rate=base.instruments[0].interest.fixed_rate + 0.005))
                        edit = dict(field_id=config.FIELD_ID, value=state(active=True, collection=FinancingCollection((first,) + tuple(base.instruments[1:]))))
                    else:
                        edit = dict(field_id="debt.senior.target_dscr", value="1.31")
                    changed = post(page, "/v2/workbook/update", dict(project=record.project_code, sheet_id="debt", **edit, **tokens(page)))
                    open_outputs(page, record)
                    f = shot(page, f"{kind}-07-stale-light-1440.png")
                    check(f"[{kind}] STALE after an input edit: prior Run named, values unchanged",
                          changed.status == 200 and page.get_attribute('[data-testid="outputs-state"]', "data-state") == "STALE"
                          and snapshot[:22] in page.inner_text('[data-testid="outputs-stale-banner"]')
                          and cell_text(page, "pnl", "Revenues", 5) == raw_before, "", f)
                    # ── history navigation keeps the view ──
                    page.go_back(); page.go_forward()
                    page.wait_for_selector("#v2-sheet-outputs")
                    log = drop_known_csp(net_errors[kind])
                    check(f"[{kind}] no page exceptions, console errors or failed requests (known main findings itemised separately)", not any(log.values()), json.dumps(log)[:800])
                    ctx.close()

                # ── Protected Reference is readable ──
                ctx, page = new_page("reference")
                page.goto(f"{url}/v2/workbook?project=generic_solar_reference-reference")
                page.locator("#tab-outputs").click()
                page.wait_for_selector("#v2-sheet-outputs[data-out-state]")
                check("[reference] Protected Reference: output workspace renders without any editable input",
                      page.locator("#v2-sheet-outputs input[type=text], #v2-sheet-outputs textarea").count() == 0)
                ctx.close()
                browser.close()
        finally:
            if server:
                server.should_exit = True
            if thread:
                thread.join(timeout=20)
            reset_model_executor_for_tests()
            db.DB_PATH = original_db

    summary = {
        "schema": "finco.outputs-workspace.browser-acceptance.v1", "generated_at": datetime.now(timezone.utc).isoformat(),
        "command": "python -m tests.model_outputs_workspace_acceptance", "checks": results,
        "network_and_console": net_errors, "known_findings_on_origin_main": known,
        "passed": sum(1 for r in results if r["status"] == "PASS"), "total": len(results),
        "all_pass": all(r["status"] == "PASS" for r in results),
        "screenshots": sorted(p.name for p in out.glob("*.png")),
        "screenshot_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob("*.png"))},
    }
    (out / "browser-results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("SUMMARY", summary["passed"], "/", summary["total"], "all_pass" if summary["all_pass"] else "FAILURES")
    return 0 if summary["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
