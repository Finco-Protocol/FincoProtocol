#!/usr/bin/env python3
"""Real-browser CAPEX/OPEX editing benchmark (local, synthetic, repeatable).

Drives the real application in Chromium against a live uvicorn server on a disposable database and
records, per scenario and repetition: interaction latency, request count, per-request server time
(time to first byte), response bytes, DOM swap/settle time and focus/scroll retention.  Distributions
(min / median / p90 / max / mean) are reported, never a single run.

    python tools/bench_cost_editing_ux.py --label before --repeats 7 --out artifacts/cost-ux-before.json

Nothing here changes product behaviour; it only observes.  Saved values are synthetic.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import statistics
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PORT = int(os.environ.get("BENCH_PORT", "8797"))
VERTICALS = {
    "solar": "generic_solar_reference",
    "wind": "generic_wind_reference",
    "data_center": "generic_data_center_reference",
    "ev": "generic_ev_charging_reference",
}
INSTRUMENT = r"""
(() => {
  window.__req = [];
  const by = new WeakMap();
  document.addEventListener('htmx:beforeRequest', e => {
    by.set(e.detail.xhr, {path: e.detail.pathInfo.requestPath, verb: e.detail.requestConfig.verb, t0: performance.now()});
  }, true);
  document.addEventListener('htmx:afterRequest', e => {
    const r = by.get(e.detail.xhr); if (!r) return;
    r.net = performance.now() - r.t0; r.status = e.detail.xhr.status;
    r.bytes = (e.detail.xhr.responseText || '').length; r.tAfter = performance.now(); window.__req.push(r);
  }, true);
  document.addEventListener('htmx:afterSettle', e => {
    const r = e.detail.xhr && by.get(e.detail.xhr); if (r) r.settle = performance.now() - r.tAfter;
  }, true);
})();
"""


def start_server(db_dir: str):
    import uvicorn
    from app.persistence import db

    db.DB_PATH = os.path.join(db_dir, "bench.db")
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
    return server, thread


def dist(values):
    v = sorted(values)
    if not v:
        return {}
    p90 = v[min(len(v) - 1, int(round(0.9 * (len(v) - 1))))]
    return {"n": len(v), "min": round(v[0], 1), "median": round(statistics.median(v), 1), "p90": round(p90, 1),
            "max": round(v[-1], 1), "mean": round(statistics.fmean(v), 1)}


class Bench:
    def __init__(self, browser, vertical, viewport=None):
        from app.auth import COOKIE_NAME, create_session_token
        from app.services.reference_seed_service import create_reference_seeded_project

        self.uid = f"bench-{vertical}-{int(time.time() * 1000) % 10**9}"
        self.rec = create_reference_seeded_project(user_id=self.uid, template_source=VERTICALS[vertical],
                                                   requested_name="Bench", capacity_mw=40.0)
        self.ctx = browser.new_context(viewport=viewport or {"width": 1440, "height": 1000}, bypass_csp=True)
        self.ctx.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=self.uid, username="admin"),
                               "url": f"http://127.0.0.1:{PORT}"}])
        self.ctx.add_init_script(INSTRUMENT)
        self.page = self.ctx.new_page()
        self.page.on("dialog", lambda d: d.accept())
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.net = []
        self.inflight = 0
        self.page.on("request", self._started)
        self.page.on("requestfailed", self._ended)
        self.page.on("requestfinished", self._finished)
        self.counter = 0

    def _started(self, req):
        if "/static/" not in req.url and req.resource_type not in ("image", "font", "stylesheet", "script"):
            self.inflight += 1

    def _ended(self, req):
        if "/static/" not in req.url and req.resource_type not in ("image", "font", "stylesheet", "script"):
            self.inflight = max(0, self.inflight - 1)

    def quiet(self, quiet_ms=600, timeout_ms=30000):
        """Wait until no request is in flight and none started for ``quiet_ms``.

        Playwright's wait_for_load_state("networkidle") returns immediately when that state was reached earlier
        in the page's life, so it cannot be used to make request counts complete.
        """
        deadline = time.perf_counter() + timeout_ms / 1000
        last_count, last_change = len(self.net), time.perf_counter()
        while time.perf_counter() < deadline:
            self.page.wait_for_timeout(50)
            if len(self.net) != last_count or self.inflight:
                last_count, last_change = len(self.net), time.perf_counter()
            elif (time.perf_counter() - last_change) * 1000 >= quiet_ms:
                return
        raise RuntimeError("network did not go quiet")

    def _finished(self, req):
        if "/static/" in req.url or req.resource_type in ("image", "font", "stylesheet", "script"):
            return
        self.inflight = max(0, self.inflight - 1)
        t = req.timing
        self.net.append({"method": req.method, "path": req.url.split(str(PORT), 1)[-1].split("?")[0],
                         "ttfb": max(0.0, t.get("responseStart", 0) - t.get("requestStart", 0)) if t else 0.0})

    def reset(self):
        self.quiet(400)                      # requests left over from page load must not leak into the scenario
        self.net.clear()
        self.page.evaluate("window.__req.length = 0")

    def open(self):
        self.page.goto(f"http://127.0.0.1:{PORT}/v2/workbook?project={self.rec.project_code}")
        self.page.wait_for_selector("#tab-capex", state="attached")
        for kind in ("opex", "capex"):
            self.page.evaluate(f"document.getElementById('tab-{kind}').click()")
            self.page.wait_for_selector(f"#v2-sheet-{kind} form[data-cost-row]", state="attached")
            self.page.evaluate(f"document.querySelectorAll('#v2-sheet-{kind} details[data-group-code]').forEach(d => d.open = true)")

    def tab(self, kind):
        self.page.evaluate(f"document.getElementById('tab-{kind}').click()")
        self.page.wait_for_selector(f"#panel-{kind}:not([hidden])")

    def set_staged(self, want):
        box = self.page.locator("[data-cost-stage-toggle]").first
        state = self.page.evaluate("window.v2CostGrid.state().stageMode")
        if state != want:
            self.tab_for_toggle()
            box.set_checked(want)
            self.page.wait_for_function(f"window.v2CostGrid.state().stageMode === {str(want).lower()}")

    def tab_for_toggle(self):
        self.tab("capex")

    def amount(self, kind, i):
        return self.page.locator(f"#v2-sheet-{kind} form[data-cost-row] input[name=\"amount_keur\"]").nth(i)

    def type_amount(self, kind, i, value):
        self.amount(kind, i).click()
        self.page.keyboard.press("Control+A")
        self.page.keyboard.type(str(value))

    def idle(self, timeout=60000):
        self.page.wait_for_function(
            "(() => { const s = window.v2CostGrid.state(); return !s.active && !s.queued.length && !s.batch; })()", timeout=timeout)

    def snapshot(self, t_start_ms):
        reqs = self.page.evaluate("window.__req")
        posts = [r for r in self.net if r["method"] == "POST"]
        focus = self.page.evaluate("!!(document.activeElement && document.activeElement.matches && document.activeElement.matches('input[data-cost-cell]'))")
        return {
            "ms": round(t_start_ms, 1),
            "requests": len(self.net), "posts": len(posts), "gets": len(self.net) - len(posts),
            "server_ttfb_ms": round(sum(r["ttfb"] for r in self.net), 1),
            "htmx_net_ms": round(sum(r.get("net", 0) for r in reqs), 1),
            "dom_settle_ms": round(sum(r.get("settle", 0) or 0 for r in reqs), 1),
            "bytes": sum(r.get("bytes", 0) for r in reqs),
            "paths": [f'{r["method"]} {r["path"]}' for r in self.net],
            "focus_in_grid": focus,
        }

    def close(self):
        self.ctx.close()


def edit_rows(b: Bench, plan, staged):
    """plan: list of (kind, row_index).  Returns metrics: first keystroke -> confirmed."""
    b.counter += 1
    b.reset()
    t0 = time.perf_counter()
    last_kind = None
    network_before_save = None
    for n, (kind, i) in enumerate(plan):
        if kind != last_kind:
            b.tab(kind)
            last_kind = kind
        b.type_amount(kind, i, 2000 + b.counter * 17 + n)
        b.page.keyboard.press("Enter")
        if not staged:
            pass
    t_typed = time.perf_counter()
    t_confirmed_abs = None
    if staged:
        network_before_save = len([r for r in b.net if r["method"] == "POST"])
        t_click = time.perf_counter()
        b.page.locator(f"#v2-sheet-{last_kind} [data-cost-stage-save]").click()
        try:
            b.page.wait_for_function("[...document.querySelectorAll('[data-cost-stage-msg]')].some(e => /Saved \\d+ lines/.test(e.textContent))",
                                     timeout=30000)
        except Exception:
            msgs = [e.inner_text() for e in b.page.locator("[data-cost-stage-msg]").all()]
            raise RuntimeError(f"staged save did not confirm: plan={plan} msgs={msgs} state={b.page.evaluate('window.v2CostGrid.state()')}")
        t_confirmed_abs = time.perf_counter()
        t_confirm = (t_confirmed_abs - t_click) * 1000
    else:
        b.idle()                                    # every row saved and swapped in
        t_confirmed_abs = time.perf_counter()
        t_confirm = (t_confirmed_abs - t_typed) * 1000
    # Same rule for both modes: the confirmation time stops HERE; afterwards wait for the follow-up
    # requests so the request counts are complete (Playwright's 500 ms idle detection is not counted).
    b.quiet()
    m = b.snapshot((t_confirmed_abs - t0) * 1000)
    m["confirm_ms"] = round(t_confirm, 1)
    if network_before_save is not None:
        m["posts_before_save"] = network_before_save
    chip = b.page.locator('[data-testid="toolbar-runtime-state"]').first.inner_text().strip()
    m["chip_after"] = chip
    b.page.wait_for_timeout(50)
    return m


SCENARIOS = {
    "capex_1": [("capex", 0)],
    "opex_1": [("opex", 0)],
    "opex_4": [("opex", i) for i in range(4)],
    "mixed_10": [("capex", i) for i in range(6)] + [("opex", i) for i in range(4)],
}


def probe_stale_authority(b: Bench):
    """Immediate OPEX save, then a staged CAPEX Save on the same page: must not be a false 409."""
    b.open()
    b.set_staged(False)
    b.tab("opex")
    b.type_amount("opex", 0, 7001 + b.counter)
    b.page.keyboard.press("Enter")
    b.idle()
    b.quiet()
    b.set_staged(True)
    b.tab("capex")
    b.type_amount("capex", 0, 7002 + b.counter)
    b.page.keyboard.press("Enter")
    b.page.locator("#v2-sheet-capex [data-cost-stage-save]").click()
    b.page.wait_for_function("[...document.querySelectorAll('[data-cost-stage-msg]')].some(e => e.textContent.trim().length > 0 "
                             "&& !/Saving/.test(e.textContent))", timeout=30000)
    msg = b.page.locator("[data-cost-stage-msg]").first.inner_text().strip()
    return {"saved": bool(__import__("re").search(r"Saved \d+ lines", msg)), "message": msg[:140]}


def tab_switch(b: Bench):
    b.reset()
    out = []
    for kind in ("opex", "capex", "opex", "capex"):
        t = time.perf_counter()
        b.tab(kind)
        out.append((time.perf_counter() - t) * 1000)
    m = b.snapshot(sum(out))
    m["per_switch_ms"] = [round(x, 1) for x in out]
    return m


def scenario_switch(b: Bench):
    r = b.page.request.post(f"http://127.0.0.1:{PORT}/v2/workbook/scenarios/create",
                            form={"project": b.rec.project_code, "scenario_name": f"Bench {b.counter}"},
                            headers={"HX-Request": "true"})
    assert r.status == 200
    b.open()
    b.reset()
    b.page.evaluate("document.getElementById('tab-scenarios').click()")
    btn = b.page.locator('#v2-sheet-scenarios form[hx-post="/v2/workbook/scenarios/select"] button').first
    t = time.perf_counter()
    btn.click()
    b.page.wait_for_function("window.__req.some(r => /scenarios\\/select/.test(r.path) && r.settle !== undefined)", timeout=30000)
    b.quiet()
    return b.snapshot((time.perf_counter() - t) * 1000)


def summarise(runs):
    keys = ["ms", "confirm_ms", "requests", "posts", "gets", "server_ttfb_ms", "htmx_net_ms", "dom_settle_ms", "bytes"]
    out = {k: dist([r[k] for r in runs if k in r]) for k in keys}
    out["focus_kept_in_grid_ratio"] = round(sum(1 for r in runs if r.get("focus_in_grid")) / len(runs), 2)
    out["paths_first_run"] = runs[0]["paths"]
    if "posts_before_save" in runs[0]:
        out["posts_before_save_max"] = max(r["posts_before_save"] for r in runs)
    out["chip_after"] = sorted({r.get("chip_after", "") for r in runs})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="run")
    ap.add_argument("--repeats", type=int, default=7)
    ap.add_argument("--verticals", default="solar,wind,data_center,ev")
    ap.add_argument("--modes", default="immediate,staged")
    ap.add_argument("--out", default="")
    ap.add_argument("--chromium", default=os.environ.get("FINCO_TEST_CHROMIUM_PATH", "/opt/pw-browsers/chromium"))
    args = ap.parse_args()

    import logging
    import tempfile
    from playwright.sync_api import sync_playwright

    logging.disable(logging.CRITICAL)
    tmp = tempfile.mkdtemp(prefix="cost-ux-")
    server, thread = start_server(tmp)
    result = {"label": args.label, "repeats": args.repeats, "chromium": "headless", "scenarios": {}}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"], executable_path=args.chromium)
        for vertical in args.verticals.split(","):
            b = Bench(browser, vertical)
            b.open()
            vres = result["scenarios"].setdefault(vertical, {})
            for mode in args.modes.split(","):
                staged = mode == "staged"
                b.set_staged(staged)
                for name, plan in SCENARIOS.items():
                    runs = []
                    for _ in range(args.repeats + 1):          # first run is a discarded warm-up
                        b.open()                               # identical starting state for every repetition
                        b.set_staged(staged)
                        runs.append(edit_rows(b, plan, staged))
                    vres[f"{name}:{mode}"] = summarise(runs[1:])
            vres["probe_staged_save_after_opex_save"] = probe_stale_authority(b)
            b.open()
            vres["tab_switch"] = summarise([tab_switch(b) for _ in range(args.repeats)])
            sw = []
            for _ in range(max(3, args.repeats // 2)):
                b.counter += 1
                sw.append(scenario_switch(b))
            vres["scenario_switch"] = summarise(sw)
            vres["page_errors"] = b.errors[:5]
            b.close()
        browser.close()
    server.should_exit = True
    thread.join(timeout=10)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
