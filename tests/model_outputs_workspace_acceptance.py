"""Authenticated Chromium acceptance of the React Statements & Results workspace.

Run with:  python -m tests.model_outputs_workspace_acceptance --out artifacts/outputs-workspace

Real application server (``main_web``), canonical React workspace (``/v2/model-react/{code}``),
real Save/Run routes, synthetic reference projects across all four verticals
(Solar, Wind, Data Center, EV Charging). Writes ``browser-results.json`` and PNGs
into ``--out`` and exits non-zero on any failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
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


def _open_section(page, url: str, project_code: str, section: str, width: int = 1440, theme: str = "light"):
    page.emulate_media(color_scheme=theme)
    page.set_viewport_size({"width": width, "height": 1000})
    target = f"{url}/v2/model-react/{project_code}#{section}"
    if page.url.split("#", 1)[0] == target.split("#", 1)[0] and page.url.endswith(f"#{section}"):
        page.reload(wait_until="load")
    else:
        page.goto(target, wait_until="load")
    page.locator('[data-workflow-bar="true"]').wait_for(timeout=30000)


def _save_input_via_canonical_route(page, url: str, project_code: str, field_id: str, value: str):
    sheet_id = "debt" if field_id.startswith("debt.") else "project_setup"
    fields_resp = page.request.get(f"{url}/v2/model-react/fields/{sheet_id}", params={"project": project_code})
    assert fields_resp.status == 200, fields_resp.text()[:300]
    meta = fields_resp.json()["save"]
    token = meta["financing_csrf_token"] if field_id == "debt.financing.instruments" else meta["csrf_token"]
    return page.request.post(
        f"{url}/v2/workbook/update",
        form={
            "project": project_code,
            "sheet_id": sheet_id,
            "field_id": field_id,
            "value": value,
            "csrf_token": token,
            "content_hash": meta["content_hash"],
            "workbook_version": meta["workbook_version"],
        },
        headers={"HX-Request": "true"},
    )


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
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.services.project_library_service import ensure_reference_models
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.workbook import multisenior_config as config
    from app.workbook.input_set import ProjectInputSet
    from main_web import app
    from tests.model_financing_browser_acceptance import contrast
    from tests.test_model_financing_f3_workspace import collection_for_inputs, state

    results: list[dict] = []
    net_errors: dict[str, dict] = {}

    def check(tag: str, ok: bool, observed="", shot: str = "") -> bool:
        results.append({
            "check": tag,
            "status": "PASS" if ok else "FAIL",
            "observed": str(observed)[:500],
            "screenshot": shot,
        })
        print(("PASS " if ok else "FAIL ") + tag, "|", str(observed)[:160], flush=True)
        return ok

    def shot(page, name: str, full: bool = False) -> str:
        page.screenshot(path=str(out / name), full_page=full)
        return name

    def write_summary() -> dict:
        summary = {
            "schema": "finco.outputs-workspace.browser-acceptance.v2-react",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "command": "python -m tests.model_outputs_workspace_acceptance",
            "checks": results,
            "network_and_console": net_errors,
            "passed": sum(1 for r in results if r["status"] == "PASS"),
            "total": len(results),
            "all_pass": bool(results) and all(r["status"] == "PASS" for r in results),
            "screenshots": sorted(p.name for p in out.glob("*.png")),
            "screenshot_sha256": {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(out.glob("*.png"))
            },
        }
        (out / "browser-results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print("SUMMARY", summary["passed"], "/", summary["total"], "all_pass" if summary["all_pass"] else "FAILURES")
        return summary

    original_db = db.DB_PATH
    server = thread = None
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        try:
            db.DB_PATH = str(Path(tmp) / "outputs_react.db")
            db.init_db()
            ensure_reference_models()
            cookie = create_session_token(user_id=USER, username="admin")
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="off"))
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            deadline = time.monotonic() + 60
            while not server.started:
                assert time.monotonic() < deadline, "Server did not start in time"
                time.sleep(0.1)
            url = f"http://127.0.0.1:{port}"

            with sync_playwright() as pw:
                kwargs: dict = {"args": ["--no-sandbox", "--disable-setuid-sandbox"]}
                exec_path = os.environ.get("FINCO_TEST_CHROMIUM_PATH") or (
                    "/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else ""
                )
                if exec_path:
                    kwargs["executable_path"] = exec_path
                browser = pw.chromium.launch(**kwargs)

                def new_page(tag: str, width: int = 1440, scheme: str = "light"):
                    ctx = browser.new_context(viewport={"width": width, "height": 1000}, color_scheme=scheme)
                    ctx.add_cookies([{"name": COOKIE_NAME, "value": cookie, "url": url}])
                    ctx.set_default_timeout(60000)
                    page = ctx.new_page()
                    log = net_errors.setdefault(tag, {"page_errors": [], "console_errors": [], "bad_responses": []})
                    page.on("pageerror", lambda e: log["page_errors"].append(str(e)))
                    page.on(
                        "console",
                        lambda m: log["console_errors"].append(m.text)
                        if m.type == "error" and FAVICON not in (m.location.get("url") or "") and "favicon" not in m.text.lower()
                        else None,
                    )
                    page.on(
                        "response",
                        lambda r: log["bad_responses"].append(f"{r.status} {r.url}")
                        if r.status >= 400 and not r.url.endswith(FAVICON)
                        else None,
                    )
                    return ctx, page

                for kind in KINDS:
                    record = create_reference_seeded_project(
                        user_id=USER,
                        requested_name=f"React Outputs {kind}",
                        template_source=f"generic_{kind}_reference",
                        capacity_mw=16,
                    )
                    ctx, page = new_page(kind)

                    # ── NOT_RUN ──
                    _open_section(page, url, record.project_code, "statements")
                    page.locator('[data-statements-view="true"][data-statements-state="NOT_RUN"]').wait_for(timeout=30000)
                    f = shot(page, f"{kind}-00-not-run-light-1440.png")
                    check(
                        f"[{kind}] NOT_RUN: honest unavailable state, no fabricated statement table",
                        page.locator('[data-workflow-bar="true"]').get_attribute("data-bar-freshness") == "NOT_RUN"
                        and page.locator("table.fm-sw-table").count() == 0
                        and "Statement data unavailable" in page.inner_text("#statement-workbook"),
                        "",
                        f,
                    )

                    # ── Optional F3 activation (Solar/Wind) + canonical Run via React WorkflowBar ──
                    if kind in F3_KINDS:
                        ws = get_workspace_state(USER, record.project_id)
                        pi = ProjectInputSet.from_snapshot(ws.draft_snapshot).to_projectinputs()
                        saved = _save_input_via_canonical_route(
                            page,
                            url,
                            record.project_code,
                            config.FIELD_ID,
                            state(active=True, collection=collection_for_inputs(pi)),
                        )
                        check(f"[{kind}] F3 activation saved through canonical CAS route", saved.status == 200)
                        page.reload(wait_until="load")
                        page.locator('[data-workflow-bar="true"]').wait_for(timeout=30000)

                    run_btn = page.locator('[data-wf-run="true"]')
                    page.wait_for_function("() => { const b = document.querySelector('[data-wf-run=\"true\"]'); return b && !b.disabled; }")
                    run_btn.click()
                    page.locator('[data-workflow-bar="true"][data-bar-freshness="CURRENT"]').wait_for(timeout=180000)
                    ws = get_workspace_state(USER, record.project_id)
                    snapshot = ws.last_runtime_snapshot_id
                    check(f"[{kind}] canonical Run committed via React WorkflowBar", bool(snapshot) and not ws.dirty, snapshot)

                    # ── CURRENT Results + Statements ──
                    page.locator('[data-workspace-nav="true"] a[href="#results"]').first.click()
                    page.locator('[data-financial-page="results"][data-financial-state="CURRENT"]').wait_for(timeout=30000)
                    check(f"[{kind}] Results view reports CURRENT Project IRR", "Project IRR" in page.locator('[data-financial-page="results"]').inner_text())

                    page.locator('[data-workspace-nav="true"] a[href="#statements"]').first.click()
                    page.locator('[data-statements-view="true"][data-statements-state="CURRENT"]').wait_for(timeout=30000)
                    tabs_ok = all(page.locator(f"#fm-sw-tab-{t}").count() == 1 for t in ("pl", "balance", "cashflow", "cfads", "debt", "sponsor"))
                    snap_suffix = snapshot.split(".", 1)[1].split("+", 1)[0].split("Z", 1)[0] if "." in snapshot else snapshot[:12]
                    run_text = page.inner_text(".fm-sw-run")
                    f = shot(page, f"{kind}-01-current-statements-light-1440.png")
                    check(f"[{kind}] Statements workbook displays all 6 sheets and saved Run badge", tabs_ok and snap_suffix in run_text, run_text, f)

                    # ── Unit / Precision / View / Year 0 are display formatting only ──
                    page.locator("#fm-sw-view").select_option("model")
                    cols_with_y0 = page.locator("table.fm-sw-table thead tr:last-child th").count()
                    page.locator(".fm-sw-period-toggle").click()
                    cols_no_y0 = page.locator("table.fm-sw-table thead tr:last-child th").count()
                    page.locator(".fm-sw-period-toggle").click()
                    target_coords = page.evaluate("""() => {
                        const btns = [...document.querySelectorAll('button.fm-sw-cell-button')];
                        const hit = btns.find(b => Number.isFinite(parseFloat(b.dataset.canonicalV || '')) && Math.abs(parseFloat(b.dataset.canonicalV)) >= 1);
                        return hit ? [hit.dataset.statementRow, hit.dataset.statementCol] : null;
                    }""")
                    assert target_coords is not None, "Expected at least one non-zero statement cell"
                    first_cell = page.locator(f'button.fm-sw-cell-button[data-statement-row="{target_coords[0]}"][data-statement-col="{target_coords[1]}"]').first
                    raw_canon = first_cell.get_attribute("data-canonical")
                    text_keur = first_cell.inner_text().strip()
                    precision_sel = page.locator('#fm-sw-precision, select[aria-label="Report precision"]').first
                    page.locator("#fm-sw-unit").select_option("EUR")
                    precision_sel.select_option("0")
                    text_eur = first_cell.inner_text().strip()
                    canon_after = first_cell.get_attribute("data-canonical")
                    page.locator("#fm-sw-unit").select_option("kEUR")
                    precision_sel.select_option("2")
                    page.locator("#fm-sw-view").select_option("annual")
                    f = shot(page, f"{kind}-02-formatting-checks-light-1440.png")
                    check(
                        f"[{kind}] Model/Annual, Year 0 toggle, EUR/0dp reformat without altering canonical data",
                        cols_no_y0 == cols_with_y0 - 1 and raw_canon == canon_after and text_eur != text_keur,
                        f"cols {cols_with_y0}->{cols_no_y0}; '{text_keur}' -> '{text_eur}'",
                        f,
                    )

                    # ── Scrollable region + sticky column + keyboard arrow ──
                    page.set_viewport_size({"width": 700, "height": 900})
                    region = page.locator(".fm-sw-region").first
                    before_scroll = region.evaluate("e => e.scrollLeft")
                    region.focus()
                    page.keyboard.press("ArrowRight")
                    page.keyboard.press("ArrowRight")
                    after_scroll = region.evaluate("e => e.scrollLeft")
                    sticky_pos = page.evaluate("() => getComputedStyle(document.querySelector('th.fm-sw-label')).position")
                    check(
                        f"[{kind}] Scrollable period region responds to ArrowRight and keeps label sticky",
                        after_scroll > before_scroll and sticky_pos == "sticky",
                        f"scrollLeft {before_scroll}->{after_scroll}, position={sticky_pos}",
                    )

                    # ── Viewports & themes ──
                    for theme, width in (("light", 1440), ("dark", 1440), ("light", 390), ("dark", 390)):
                        _open_section(page, url, record.project_code, "statements", width=width, theme=theme)
                        page.locator('[data-statements-view="true"][data-statements-state="CURRENT"]').wait_for(timeout=30000)
                        overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                        colors = page.evaluate("""() => {
                            const c = document.querySelector('button.fm-sw-cell-button');
                            const fg = getComputedStyle(c).color;
                            let el = c;
                            let bg = 'rgb(255, 255, 255)';
                            while (el) {
                                const b = getComputedStyle(el).backgroundColor;
                                if (b && b !== 'rgba(0, 0, 0, 0)' && b !== 'transparent') { bg = b; break; }
                                el = el.parentElement;
                            }
                            return [fg, bg];
                        }""")
                        f = shot(page, f"{kind}-03-{theme}-{width}.png")
                        check(
                            f"[{kind}] {theme} {width}px: zero page overflow and readable contrast",
                            overflow <= 2 and contrast(colors) >= 4.5,
                            f"overflow={overflow}px contrast={contrast(colors):.1f}",
                            f,
                        )

                    # ── Edit input -> STALE -> Run -> CURRENT ──
                    _open_section(page, url, record.project_code, "statements", width=1440, theme="light")
                    page.locator('[data-statements-view="true"][data-statements-state="CURRENT"]').wait_for(timeout=30000)
                    before_cell_canon = page.locator("button.fm-sw-cell-button").first.get_attribute("data-canonical")
                    if kind in F3_KINDS:
                        from dataclasses import replace
                        from finco_core.inputs.financing_instruments import FinancingCollection

                        base = collection_for_inputs(ProjectInputSet.from_snapshot(get_workspace_state(USER, record.project_id).draft_snapshot).to_projectinputs())
                        first = replace(base.instruments[0], interest=replace(base.instruments[0].interest, fixed_rate=base.instruments[0].interest.fixed_rate + 0.005))
                        edit_field = config.FIELD_ID
                        edit_value = state(active=True, collection=FinancingCollection((first,) + tuple(base.instruments[1:])))
                    else:
                        edit_field = "debt.senior.target_dscr"
                        edit_value = "1.37"
                    edit_resp = _save_input_via_canonical_route(page, url, record.project_code, edit_field, edit_value)
                    assert edit_resp.status == 200, edit_resp.text()[:200]
                    _open_section(page, url, record.project_code, "statements", width=1440, theme="light")
                    page.locator('[data-statements-view="true"][data-statements-state="STALE"]').wait_for(timeout=30000)
                    stale_canon = page.locator("button.fm-sw-cell-button").first.get_attribute("data-canonical")
                    check(
                        f"[{kind}] STALE after input edit preserves prior Run values",
                        page.locator('[data-stale-banner="true"]').is_visible() and stale_canon == before_cell_canon,
                    )

                    # No polling loop while idle on STALE statements
                    seen: list[str] = []
                    page.on("request", lambda r: seen.append(r.url) if "/v2/model-react/statements" in r.url else None)
                    page.wait_for_timeout(1500)
                    check(f"[{kind}] idle statements view issues zero background refresh loops", not seen, len(seen))

                    page.wait_for_function("() => { const b = document.querySelector('[data-wf-run=\"true\"]'); return b && !b.disabled; }")
                    page.locator('[data-wf-run="true"]').click()
                    page.locator('[data-workflow-bar="true"][data-bar-freshness="CURRENT"]').wait_for(timeout=180000)
                    new_snapshot = get_workspace_state(USER, record.project_id).last_runtime_snapshot_id
                    check(
                        f"[{kind}] Re-Run refreshes workspace to CURRENT with a new snapshot",
                        bool(new_snapshot) and new_snapshot != snapshot,
                        f"{snapshot} -> {new_snapshot}",
                    )
                    log = net_errors[kind]
                    check(f"[{kind}] zero page errors, console errors or >=400 responses", not any(log.values()), json.dumps(log)[:600])
                    ctx.close()

                # ── Owner isolation + Protected Reference ──
                iso_ctx, iso_page = new_page("isolation")
                owner_rec = create_reference_seeded_project(
                    user_id=USER,
                    requested_name="Isolation Solar",
                    template_source="generic_solar_reference",
                    capacity_mw=16,
                )
                intruder = browser.new_context()
                intruder.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id="outputs-intruder", username="other"), "url": url}])
                denied = intruder.request.get(f"{url}/v2/model-react/statements", params={"project": owner_rec.project_code})
                anon_ctx = browser.new_context()
                anon = anon_ctx.request.get(f"{url}/v2/model-react/statements", params={"project": owner_rec.project_code})
                check("owner isolation: intruder receives 404 and anonymous is denied", denied.status == 404 and anon.status in (401, 404) and "revenues_keur" not in denied.text() and "revenues_keur" not in anon.text(), f"{denied.status}/{anon.status}")
                intruder.close()
                anon_ctx.close()

                _open_section(iso_page, url, "generic_solar_reference-reference", "statements")
                iso_page.locator('[data-statements-view="true"]').wait_for(timeout=30000)
                check(
                    "Protected Reference statements view has no editable text inputs",
                    iso_page.locator('#statement-workbook input[type="text"], #statement-workbook textarea').count() == 0,
                )
                iso_ctx.close()
                browser.close()
        finally:
            if server is not None:
                server.should_exit = True
            if thread is not None:
                thread.join(timeout=20)
            reset_model_executor_for_tests()
            db.DB_PATH = original_db
            summary = write_summary()

    return 0 if summary["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
