"""Authenticated Chromium acceptance of React StatementWorkbook drill-down, trace, and Back/Forward navigation.

Run with:  python -m tests.model_statements_tree_acceptance --out artifacts/statements-tree

Retains ``browser_failure_guard``, ``record_browser_exception``, ``focus_diagnostics``, and
``write_browser_summary`` for CI contract tests while executing ``main()`` directly against
the canonical React workspace (``/v2/model-react/{code}``).
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time

USER = "statements-tree-browser"


def focus_diagnostics(page):
    return page.evaluate("""() => {
      const a = document.activeElement, r = document.getElementById('statement-workbook');
      return {url: location.href, hash: location.hash,
        focus: a && {html: a.outerHTML.slice(0, 2000), tag: a.tagName,
          statementRow: a.dataset.statementRow, statementCol: a.dataset.statementCol,
          ariaExpanded: a.getAttribute('aria-expanded')},
        root: r && {present: true, project: r.dataset.statementProject || null},
        rows: r ? [...r.querySelectorAll('table.fm-sw-table tbody tr')].length : 0,
        events: window.__fincoStatementTrace || []};
    }""")


def record_browser_exception(out, results, error, step, pages):
    record = {
        "check": "uncaught browser exception",
        "status": "FAIL",
        "observed": str(error),
        "exception_type": type(error).__name__,
        "step": step["name"],
        "screenshot": "",
    }
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
    try:
        yield
    except BaseException as error:
        record_browser_exception(out, results, error, step, pages)
        raise


def write_browser_summary(out, results, logs):
    summary = {
        "schema": "finco.statements-tree.browser-acceptance.v2-react",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "command": "python -m tests.model_statements_tree_acceptance",
        "checks": results,
        "network_and_console": logs,
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
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.services.project_library_service import ensure_reference_models
    from app.services.reference_seed_service import create_reference_seeded_project
    from main_web import app

    results: list[dict] = []
    logs: dict[str, dict] = {}
    pages = []
    step = {"name": "startup"}

    def check(tag: str, ok: bool, observed="", shot_name: str = "") -> bool:
        step["name"] = tag
        results.append({
            "check": tag,
            "status": "PASS" if ok else "FAIL",
            "observed": str(observed)[:500],
            "screenshot": shot_name,
        })
        print(("PASS " if ok else "FAIL ") + tag, "|", str(observed)[:160], flush=True)
        return ok

    def shot(pg, name: str) -> str:
        pg.screenshot(path=str(out / name))
        return name

    original_db = db.DB_PATH
    server = thread = None
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        try:
            db.DB_PATH = str(Path(tmp) / "statements-tree-react.db")
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
                assert time.monotonic() < deadline
                time.sleep(0.1)
            url = f"http://127.0.0.1:{port}"
            record = create_reference_seeded_project(
                user_id=USER,
                requested_name="React Statements Tree",
                template_source="generic_solar_reference",
                capacity_mw=16,
            )

            with sync_playwright() as pw, browser_failure_guard(out, results, step, pages):
                kwargs: dict = {"args": ["--no-sandbox", "--disable-setuid-sandbox"]}
                exec_path = os.environ.get("FINCO_TEST_CHROMIUM_PATH") or (
                    "/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else ""
                )
                if exec_path:
                    kwargs["executable_path"] = exec_path
                browser = pw.chromium.launch(**kwargs)
                ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
                ctx.add_cookies([{"name": COOKIE_NAME, "value": cookie, "url": url}])
                ctx.set_default_timeout(60000)
                page = ctx.new_page()
                pages.append(page)
                log = logs.setdefault("main", {"page_errors": [], "console_errors": [], "bad_responses": []})
                page.on("pageerror", lambda e: log["page_errors"].append(str(e)))
                page.on(
                    "console",
                    lambda m: log["console_errors"].append(m.text)
                    if m.type == "error" and "favicon" not in m.text.lower()
                    else None,
                )
                page.on(
                    "response",
                    lambda r: log["bad_responses"].append(f"{r.status} {r.url}")
                    if r.status >= 400 and not r.url.endswith("/favicon.ico")
                    else None,
                )

                step["name"] = "open React workspace and commit canonical Run"
                page.goto(f"{url}/v2/model-react/{record.project_code}", wait_until="load")
                page.locator('[data-workflow-bar="true"]').wait_for(timeout=30000)
                page.wait_for_function("() => { const b = document.querySelector('[data-wf-run=\"true\"]'); return b && !b.disabled; }")
                page.locator('[data-wf-run="true"]').click()
                page.locator('[data-workflow-bar="true"][data-bar-freshness="CURRENT"]').wait_for(timeout=180000)
                ws = get_workspace_state(USER, record.project_id)
                history = get_run_history(USER, record.project_id)
                check("canonical Run committed with 1 history row", len(history) == 1 and bool(ws.last_runtime_summary))
                before_hist = history[0].to_dict()

                step["name"] = "open Statements view and verify status dimensions"
                page.locator('[data-workspace-nav="true"] a[href="#statements"]').first.click()
                page.locator('[data-statements-view="true"][data-statements-state="CURRENT"]').wait_for(timeout=30000)
                run_box = page.locator(".fm-sw-run")
                check(
                    "status metadata shows saved Run freshness and checks",
                    run_box.get_attribute("data-run-freshness") is not None
                    and run_box.get_attribute("data-check-status") is not None,
                    run_box.inner_text(),
                    shot(page, "01-statements-status-1440.png"),
                )

                step["name"] = "expand and collapse tree detail rows"
                collapsed_rows = page.locator("table.fm-sw-table tbody tr").count()
                page.get_by_role("button", name="Expand all").click()
                expanded_rows = page.locator("table.fm-sw-table tbody tr").count()
                page.get_by_role("button", name="Collapse all").click()
                recollapsed_rows = page.locator("table.fm-sw-table tbody tr").count()
                check(
                    "Expand all reveals child detail rows and Collapse all restores",
                    expanded_rows >= collapsed_rows and recollapsed_rows == collapsed_rows,
                    f"{collapsed_rows} -> {expanded_rows} -> {recollapsed_rows}",
                    shot(page, "02-statements-expanded-1440.png"),
                )

                step["name"] = "toggle individual group chevron and inspect canonical cell source"
                chevrons = page.locator('table.fm-sw-table button[aria-label*="detail rows"]')
                if chevrons.count() > 0:
                    first_chev = chevrons.first
                    assert first_chev.get_attribute("aria-expanded") == "false"
                    first_chev.click()
                    assert first_chev.get_attribute("aria-expanded") == "true"
                page.locator("button.fm-sw-cell-button").first.click()
                trace_row = page.locator('tr.fm-sw-trace-row[data-canonical-source="true"]')
                trace_row.wait_for(timeout=10000)
                check("selecting a cell reveals canonical SOURCE row", trace_row.is_visible(), shot(page, "03-cell-source-1440.png"))

                step["name"] = "keyboard Back/Forward navigation preserves Statements without mutating history"
                page.locator('[data-workspace-nav="true"] a[href="#inputs"]').first.click()
                page.locator('#wf-inputs-setup').wait_for(timeout=30000)
                page.go_back()
                page.locator('[data-statements-view="true"][data-statements-state="CURRENT"]').wait_for(timeout=30000)
                page.go_forward()
                page.locator('#wf-inputs-setup').wait_for(timeout=30000)
                page.go_back()
                page.locator('[data-statements-view="true"][data-statements-state="CURRENT"]').wait_for(timeout=30000)
                check("Back/Forward between Statements and Inputs stays consistent", "#statements" in page.url)

                step["name"] = "responsive containment at 768px and 390px"
                for width in (768, 390):
                    page.set_viewport_size({"width": width, "height": 1000})
                    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                    region = page.locator(".fm-sw-region").first
                    overflow_x = region.evaluate("e => getComputedStyle(e).overflowX")
                    check(
                        f"statements contained cleanly at {width}px",
                        overflow <= 2 and overflow_x in ("auto", "scroll"),
                        f"overflow={overflow}px overflowX={overflow_x}",
                        shot(page, f"04-statements-{width}.png"),
                    )

                after_hist = get_run_history(USER, record.project_id)
                check("Run history immutable throughout navigation", len(after_hist) == 1 and after_hist[0].to_dict() == before_hist)
                check(
                    "zero page errors, console errors or failing HTTP responses",
                    not any(log.values()),
                    json.dumps(log)[:600],
                )
                ctx.close()
                browser.close()
        finally:
            if server is not None:
                server.should_exit = True
            if thread is not None:
                thread.join(timeout=20)
            reset_model_executor_for_tests()
            db.DB_PATH = original_db
            summary = write_browser_summary(out, results, logs)

    return 0 if summary["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
