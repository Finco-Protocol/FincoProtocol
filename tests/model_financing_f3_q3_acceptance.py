"""Authenticated Chromium acceptance of F3 two-Senior financing integrated with Q3 FINCO Insight.

Run with:  python -m tests.model_financing_f3_q3_acceptance --out artifacts/f3-evidence/browser

Real application server, real Save/Run/CAS routes, synthetic reference projects only.  Every check is recorded in
``browser-results.json`` with PASS/FAIL, the observed string and the screenshot that shows it; the screenshots are
written next to it (they are CI artifacts and are never committed).  Exit code is non-zero if any check fails.
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

USER = "f3-q3-browser"
FAVICON = "/favicon.ico"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("artifacts/f3-evidence/browser"))
    args = parser.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    import uvicorn
    from playwright.sync_api import sync_playwright, expect
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence import db
    from app.persistence.projects_repository import get_project_by_code
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.project_library_service import ensure_reference_models
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.workbook.input_set import ProjectInputSet
    from app.workbook import multisenior_config as config
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.model_quality import evaluate_model_quality
    from app.model_quality.evidence import evidence_from_workspace, terms_from_project_inputs
    from app.v2.router import _build_pis_with_composite_identity
    from tests.test_model_financing_f3_workspace import collection_for_inputs
    from main_web import app

    results: list[dict] = []
    net_errors: dict[str, dict] = {}
    # Findings present on origin/main and untouched by this PR (htmx trigger filters blocked by the page CSP; the
    # workspace-nav strip overflowing the 390px document).  They are itemised in browser-results.json, never hidden.
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
            db.DB_PATH = str(Path(tmp) / "f3q3.db")
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
            mk = lambda kind, name: create_reference_seeded_project(
                user_id=USER, requested_name=name, template_source=f"generic_{kind}_reference", capacity_mw=16)

            def q1_report(record, freshness="CURRENT"):
                ws = get_workspace_state(USER, record.project_id)
                pis = _build_pis_with_composite_identity(ws, get_project_by_code(USER, record.project_code), USER)
                return evaluate_model_quality(evidence_from_workspace(
                    ws, freshness=freshness, terms=terms_from_project_inputs(pis.to_projectinputs()) if freshness == "CURRENT" else None,
                    active_scenario_id=ws.active_scenario_id, scenario_known=True))

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
                    page.on("console", lambda m: log["console_errors"].append(m.text + " @" + str(m.location.get("url")) + ":" + str(m.location.get("lineNumber"))) if m.type == "error" and FAVICON not in (m.location.get("url") or "") and "favicon" not in m.text else None)
                    page.on("response", lambda r: log["bad_responses"].append(f"{r.status} {r.url}") if r.status >= 400 and not r.url.endswith(FAVICON) else None)
                    page.on("dialog", lambda d: d.accept())
                    return ctx, page

                def shot(page, name, full=False):
                    page.screenshot(path=str(out / name), full_page=full)
                    return name

                def q3_state(page):
                    return page.get_attribute('[data-testid="q3-quality"]', "data-q3-state")

                def identity(page):
                    text = " ".join(page.inner_text('[data-testid="q3-context"]').split())
                    m = re.search(r"Scenario: (.*?) · Run ", text)
                    s = re.search(r"snapshot (\S+)", text)
                    return (m.group(1) if m else None), (s.group(1) if s else None), text

                def checks_in_dom(page):
                    return page.evaluate("Object.fromEntries([...document.querySelectorAll('details[data-q3-check]')].map(d=>[d.dataset.checkId,d.dataset.checkStatus]))")

                def fill_and_save(page, record, activate=True, rate_edit=None):
                    ws = get_workspace_state(USER, record.project_id)
                    pi = ProjectInputSet.from_snapshot(ws.draft_snapshot).to_projectinputs()
                    terms = collection_for_inputs(pi)
                    form = page.locator("[data-f3-form]")
                    expect(form.locator("[data-f3-save]")).to_be_enabled()
                    for row, instrument in zip(form.locator("[data-f3-instrument]").all(), terms.instruments):
                        row.locator('[data-f3="commitment_keur"]').fill(str(instrument.commitment_keur))
                        row.locator('[data-f3="rate_pct"]').fill(str(instrument.interest.fixed_rate * 100))
                        row.locator('[data-f3="grace_months"]').fill(str(instrument.repayment.grace_months))
                        row.locator('[data-f3="maturity_date"]').fill(instrument.repayment.maturity_date.isoformat())
                        row.locator('[data-f3="draws"]').fill("\n".join(f"{d.draw_date.isoformat()}, {d.amount_keur}" for d in instrument.drawdowns))
                        row.locator('[data-f3="upfront_pct"]').fill("1")
                        row.locator('[data-f3="commitment_pct"]').fill("0.5")
                    if activate:
                        form.locator("[data-f3-activate]").check()
                    with page.expect_response(lambda r: r.url.endswith("/v2/workbook/update")) as response:
                        form.locator("[data-f3-save]").click()
                    return response.value

                def run_model(page):
                    with page.expect_response(lambda r: r.url.endswith("/v2/workbook/run"), timeout=240000) as response:
                        page.locator("#v2-run-controls button").first.click()
                    page.wait_for_function("() => document.getElementById('model-smart-panel').dataset.runState==='CURRENT'", timeout=60000)
                    return response.value

                def no_horizontal_overflow(page):
                    return page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth") <= 1

                records = {k: mk(k, f"F3 {k.title()}") for k in ("solar", "wind")}
                for kind, record in records.items():
                    ctx, page = new_page(kind)
                    check(f"[{kind}] debt sheet loads (200)", page.goto(f"{url}/v2/workbook?project={record.project_code}&sheet=debt").status == 200)
                    # ── editor before activation (every input visible, none clipped) ──
                    form = page.locator("[data-f3-form]")
                    expect(form).to_be_visible()
                    page.locator("[data-f3-instrument] summary").first.scroll_into_view_if_needed()
                    inputs = form.locator("[data-f3]").all()
                    boxes = [i.bounding_box() for i in inputs]
                    vis = all(b and b["width"] > 20 and b["height"] > 10 and b["x"] >= 0 and b["x"] + b["width"] <= 1440 for b in boxes)
                    f = shot(page, f"{kind}-01-editor-before-activation-light-1440.png")
                    check(f"[{kind}] F3 editor before activation: all {len(inputs)} facility inputs visible and inside the viewport",
                          vis and not form.locator("[data-f3-activate]").is_checked() and q3_state(page) == "NOT_RUN", f"{len(inputs)} inputs", f)
                    check(f"[{kind}] Q3 NOT_RUN before any Run: no committed identity and no score",
                          page.locator('[data-testid="q3-context"]').count() == 0 and page.locator('[data-testid="q3-score"]').count() == 0)
                    # ── Save activation, reload ──
                    resp = fill_and_save(page, record)
                    ws = get_workspace_state(USER, record.project_id)
                    entry = config.parse_state(ws.draft_snapshot[config.SNAPSHOT_KEY])["scopes"]["base"]
                    check(f"[{kind}] Save activation through CAS (200, activation bound to the proposal digest)",
                          resp.status == 200 and bool(entry["activation"]) and ws.dirty and not ws.last_runtime_summary,
                          entry["activation"]["proposal_digest"][:16] if entry["activation"] else None)
                    page.reload()
                    expect(page.locator("[data-f3-activate]")).to_be_checked()
                    f = shot(page, f"{kind}-02-two-senior-active-saved-light-1440.png")
                    names = [page.locator('[data-f3-instrument]').nth(i).locator('[data-f3="name"]').input_value() for i in range(2)]
                    rates = [page.locator('[data-f3-instrument]').nth(i).locator('[data-f3="rate_pct"]').input_value() for i in range(2)]
                    mats = [page.locator('[data-f3-instrument]').nth(i).locator('[data-f3="maturity_date"]').input_value() for i in range(2)]
                    check(f"[{kind}] Reload: activation persisted; Facility A/B show separate rates and maturities",
                          len(set(rates)) == 2 and len(set(mats)) == 2, f"names={names} rates={rates} maturities={mats}", f)
                    # ── Run: CURRENT, committed A/B, Q3 ──
                    r = run_model(page)
                    ws = get_workspace_state(USER, record.project_id)
                    fe = ws.last_runtime_summary["financing_evidence"]
                    check(f"[{kind}] canonical Run committed (200) with two facility schedules and the F3 authority",
                          r.status == 200 and not ws.dirty and len(fe["facility_schedules"]) == 2 and fe["facility_authority"].startswith("F3_TWO_SENIOR"))
                    page.goto(f"{url}/v2/workbook?project={record.project_code}&sheet=debt")
                    body = page.content()
                    check(f"[{kind}] committed A/B facility detail rendered (construction draws/IDC/fees and operating service)",
                          "Last Run facility schedules" in body and "Construction: actual dated draws" in body and "Operating debt service" in body
                          and page.locator("details:has(h5)").count() == 2)
                    page.locator("details:has(h5)").first.evaluate("e => e.open = true")
                    page.locator("details:has(h5)").first.scroll_into_view_if_needed()
                    f = shot(page, f"{kind}-03-last-run-facility-detail-current-light-1440.png")
                    rep = q1_report(record)
                    ident_name, ident_snap, ident_text = identity(page)
                    check(f"[{kind}] F3 post-Run CURRENT: Findings identity is the committed Base Case Run (exact name and snapshot)",
                          q3_state(page) == "CURRENT" and ident_name == f"Base Case (F3 {kind.title()})"
                          and ident_snap == ws.last_runtime_snapshot_id[:22], ident_text, f)
                    check(f"[{kind}] Q3 Findings on the F3 Run equal the Q1 report over the committed record (30 checks, no FAIL/WARNING)",
                          checks_in_dom(page) == {c.check_id: c.status.value for c in rep.checks} and len(checks_in_dom(page)) == 30
                          and rep.summary.failed == 0 and rep.summary.warnings == 0,
                          f"score={rep.summary.score} coverage={rep.summary.coverage_weighted}")
                    page.locator('#v2-sp-view-solutions').scroll_into_view_if_needed()
                    f = shot(page, f"{kind}-04-q3-findings-on-f3-run-light-1440.png")
                    su = ctx.request.get(f"{url}/v2/financing/sources-uses?project={record.project_code}")
                    check(f"[{kind}] Sources & Uses page shows contractual Senior debt for the committed Run",
                          su.status == 200 and "Senior debt (contractual)" in su.text())
                    # ── history: back / forward / HTMX refresh ──
                    page.goto(f"{url}/v2/workbook?project={record.project_code}")
                    page.goto(f"{url}/v2/workbook?project={record.project_code}&sheet=debt")
                    page.go_back(); page.go_forward()
                    page.wait_for_selector("#model-smart-panel")
                    check(f"[{kind}] back/forward keeps one Insight panel, the F3 editor and the committed identity",
                          page.locator("#model-smart-panel").count() == 1 and page.locator("[data-f3-form]").count() == 1
                          and q3_state(page) == "CURRENT" and identity(page)[1] == ws.last_runtime_snapshot_id[:22])
                    # ── edit -> STALE; committed Last Run unchanged ──
                    original_run = ws.last_runtime_snapshot_id
                    form = page.locator("[data-f3-form]")
                    form.locator('[data-f3="rate_pct"]').first.fill("5")
                    with page.expect_response(lambda r: r.url.endswith("/v2/workbook/update")):
                        form.locator("[data-f3-save]").click()
                    page.wait_for_function("() => document.getElementById('model-smart-panel').dataset.runState==='STALE'", timeout=60000)
                    ws2 = get_workspace_state(USER, record.project_id)
                    ident2 = identity(page)
                    f = shot(page, f"{kind}-05-f3-edited-stale-light-1440.png")
                    check(f"[{kind}] F3 edit -> STALE: Last Run immutable; Findings keep the prior committed Base Case identity; thresholds unbound",
                          ws2.dirty and ws2.last_runtime_snapshot_id == original_run and q3_state(page) == "STALE"
                          and ident2[0] == f"Base Case (F3 {kind.title()})" and ident2[1] == original_run[:22]
                          and "RUN_THRESHOLD_NOT_BOUND" in page.inner_text('[data-testid="q3-quality"]')
                          and "Last Run facility schedules" in page.content(), ident2[2], f)
                    # ── themes x viewports ──
                    for theme, width in (("light", 1440), ("dark", 1440), ("light", 390), ("dark", 390)):
                        page.emulate_media(color_scheme=theme)
                        page.set_viewport_size({"width": width, "height": 1000})
                        page.evaluate("(t) => document.documentElement.setAttribute('data-theme', t)", theme)
                        panel = page.locator("[data-f3-form]")
                        expect(panel).to_be_visible()
                        fits = panel.bounding_box()["width"] <= width
                        doc_overflow = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
                        if doc_overflow > 1:
                            known.setdefault("document_horizontal_overflow_px_from_workspace_nav", {})[f"{kind}-{theme}-{width}"] = doc_overflow
                        for summary in panel.locator("summary").all():
                            summary.click(); summary.click()
                        name = f"{kind}-06-editor-{theme}-{width}.png"
                        panel.scroll_into_view_if_needed()
                        shot(page, name)
                        from tests.model_financing_browser_acceptance import contrast
                        colors = panel.locator('[data-f3="rate_pct"]').first.evaluate("el => { const s=getComputedStyle(el); return [s.color,s.backgroundColor]; }")
                        panel_inputs_visible = all((b := i.bounding_box()) and b["width"] > 20 and b["x"] >= -1 and b["x"] + b["width"] <= width + 1
                                                   for i in panel.locator("[data-f3]").all())
                        check(f"[{kind}] F3 editor {theme} {width}px: fits the viewport, every input visible, contrast >= 4.5",
                              fits and panel_inputs_visible and contrast(colors) >= 4.5, f"contrast={contrast(colors):.2f}", name)
                    page.set_viewport_size({"width": 1440, "height": 1000})
                    page.emulate_media(color_scheme="light")
                    page.evaluate("() => document.documentElement.setAttribute('data-theme','light')")
                    # mobile Insight panel with the F3 Run
                    page.set_viewport_size({"width": 390, "height": 900})
                    page.locator('[data-sp-mode="solutions"]').scroll_into_view_if_needed()
                    check(f"[{kind}] 390px Insight panel (F3 Run): all four mode buttons visible inside the 390px viewport",
                          all((b := page.locator(f'[data-sp-mode="{m}"]').bounding_box()) and b["x"] >= -1 and b["x"] + b["width"] <= 391
                              for m in ("solutions", "inspector", "changes", "scenarios")))
                    shot(page, f"{kind}-07-q3-panel-stale-light-390.png")
                    page.set_viewport_size({"width": 1440, "height": 1000})
                    log = net_errors[kind]
                    log = drop_known_csp(log)
                    check(f"[{kind}] no page exceptions, console errors or failed requests (known main-branch findings itemised separately)", not any(log.values()), json.dumps(log)[:1500])
                    ctx.close()

                # ── named scenario + scenario switching (Solar) ──
                record = records["solar"]
                ctx, page = new_page("scenario")
                page.goto(f"{url}/v2/workbook?project={record.project_code}&sheet=debt")
                # bring the Base Case back to CURRENT with its own committed Run first (the edit above made it STALE)
                form = page.locator("[data-f3-form]")
                form.locator('[data-f3="rate_pct"]').first.fill("4")
                with page.expect_response(lambda r: r.url.endswith("/v2/workbook/update")):
                    form.locator("[data-f3-save]").click()
                run_model(page)
                base_snap = get_workspace_state(USER, record.project_id).last_runtime_snapshot_id
                base_fe_digest = get_workspace_state(USER, record.project_id).last_runtime_summary["financing_evidence"]["collection_digest"]
                page.click("#tab-scenarios"); page.wait_for_selector("#v2-sheet-scenarios")
                page.fill(".v2-scenario-name-input", "F3 Upside"); page.click(".v2-scenario-create-btn")
                page.wait_for_selector("text=F3 Upside"); page.wait_for_timeout(1500)
                page.goto(f"{url}/v2/workbook?project={record.project_code}&sheet=debt")
                f = shot(page, "solar-08-named-scenario-selected-no-run-light-1440.png")
                check("[scenario] switching to a new scenario without a Run: Findings NOT_RUN with no committed identity (not the selected name)",
                      q3_state(page) == "NOT_RUN" and page.locator('[data-testid="q3-context"]').count() == 0
                      and "F3 Upside" not in page.inner_text('[data-testid="q3-quality"]'), q3_state(page), f)
                check("[scenario] the new scenario has its own empty F3 scope (inactive editor, no inherited activation)",
                      not page.locator("[data-f3-activate]").is_checked())
                resp = fill_and_save(page, record)
                run_model(page)
                ws = get_workspace_state(USER, record.project_id)
                page.goto(f"{url}/v2/workbook?project={record.project_code}&sheet=debt")
                name, snap, text = identity(page)
                f = shot(page, "solar-09-named-scenario-f3-run-light-1440.png")
                check("[scenario] named scenario F3 Run: Findings identity is exactly 'F3 Upside' with its own snapshot",
                      name == "F3 Upside" and snap == ws.last_runtime_snapshot_id[:22] and snap != base_snap[:22], text, f)
                page.click('#model-smart-panel [data-sp-mode="scenarios"]')
                rows = page.evaluate("[...document.querySelectorAll('#v2-sp-view-scenarios [data-scenario-id]')].map(r=>[r.querySelector('strong').textContent,r.dataset.scenarioBasis])")
                check("[scenario] Scenarios mode: named scenario CURRENT, Base Case HISTORICAL_RUN (own committed Run)",
                      sorted(r[1] for r in rows) == ["CURRENT", "HISTORICAL_RUN"], rows)
                f = shot(page, "solar-10-scenarios-comparison-light-1440.png")
                # switch back to Base Case via the existing workspace control
                page.click("#tab-scenarios"); page.wait_for_selector("#v2-sheet-scenarios")
                page.locator("#v2-sheet-scenarios form[hx-post$='scenarios/select'] button").first.click()
                page.wait_for_timeout(2500)
                page.goto(f"{url}/v2/workbook?project={record.project_code}&sheet=debt")
                name, snap, text = identity(page)
                ws = get_workspace_state(USER, record.project_id)
                check("[scenario] switching back restores the Base Case's own committed Run and identity (never the other scenario's)",
                      name.startswith("Base Case") and snap == base_snap[:22]
                      and ws.last_runtime_summary["financing_evidence"]["collection_digest"] == base_fe_digest, text)
                f = shot(page, "solar-11-base-case-restored-light-1440.png")
                log = drop_known_csp(net_errors["scenario"])
                check("[scenario] no page exceptions, console errors or failed requests", not any(log.values()), json.dumps(log)[:1500])
                ctx.close()

                # ── visible reserve-authority conflict (Correction D) ──
                conflict = mk("solar", "F3 Reserve conflict")
                ctx, page = new_page("reserve")
                from app.workbook.input_set import ProjectInputSet as PIS
                from dataclasses import replace
                from finco_core.inputs import DebtServiceReserveSupportMode
                real_to_pi = PIS.to_projectinputs

                def with_existing_reserve(self):
                    pi = real_to_pi(self)
                    return replace(pi, financing=replace(pi.financing, dsra_support_mode=DebtServiceReserveSupportMode.CASH_DSRA,
                                                         debt_service_reserve_requirement_keur=100.0, dsra_target_policy="fixed_amount"))
                PIS.to_projectinputs = with_existing_reserve   # real adapter seam: no UI input exists for these typed terms
                try:
                    page.goto(f"{url}/v2/workbook?project={conflict.project_code}&sheet=debt")
                    ws_before = get_workspace_state(USER, conflict.project_id)
                    fill_and_save(page, conflict)
                    page.wait_for_timeout(1500)
                    text = page.inner_text("body")
                    ws_after = get_workspace_state(USER, conflict.project_id)
                    shown = page.get_by_text("F3_EXISTING_RESERVE_AUTHORITY_CONFLICT").first
                    shown.scroll_into_view_if_needed()
                    f = shot(page, "solar-12-reserve-authority-conflict-visible-light-1440.png")
                    check("[reserve] existing reserve authority + activation: typed F3_EXISTING_RESERVE_AUTHORITY_CONFLICT is visible and nothing is saved",
                          shown.is_visible() and ws_after.updated_at == ws_before.updated_at, "typed error visible" if shown.is_visible() else text[:200], f)
                finally:
                    PIS.to_projectinputs = real_to_pi
                ctx.close()

                # ── Protected Reference ──
                ctx, page = new_page("reference")
                page.goto(f"{url}/v2/workbook?project=generic_solar_reference-reference&sheet=debt")
                editable = page.eval_on_selector_all(".v2-field-row .v2-field-input", "els=>els.filter(e=>!(e.disabled||e.readOnly)).length")
                f = shot(page, "solar-13-protected-reference-light-1440.png")
                check("[reference] Protected Reference: F3 instrument configuration read-only, no editable inputs, Insight panel present",
                      page.locator("[data-f3-form]").count() == 0 and editable == 0 and page.locator("#model-smart-panel").count() == 1
                      and "read-only" in page.inner_text("body").lower(), f"editable={editable}", f)
                log = drop_known_csp(net_errors["reference"])
                check("[reference] no page exceptions, console errors or failed requests", not any(log.values()), json.dumps(log)[:1500])
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
        "schema": "finco.f3.browser-acceptance.v1", "generated_at": datetime.now(timezone.utc).isoformat(),
        "command": "python -m tests.model_financing_f3_q3_acceptance", "checks": results,
        "network_and_console": net_errors, "known_findings_on_origin_main": known, "passed": sum(1 for r in results if r["status"] == "PASS"), "total": len(results),
        "all_pass": all(r["status"] == "PASS" for r in results),
        "screenshots": sorted(p.name for p in out.glob("*.png")),
        "screenshot_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob("*.png"))},
    }
    (out / "browser-results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("SUMMARY", summary["passed"], "/", summary["total"], "all_pass" if summary["all_pass"] else "FAILURES")
    return 0 if summary["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
