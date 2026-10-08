"""Authenticated V6 paired benchmark. No timing thresholds in regular CI.

Run before edits with --baseline-only, then without that flag for acceptance.
Instrumentation replaces only the builder/worker entry in this isolated CLI;
production uses explicit context parameters, never function replacement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import platform
from pathlib import Path
import re
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def measured_worker(*args, **kwargs):
    from app.api.project_runner import run_project
    from app.services import production_financial_authority
    production_financial_authority._POLICY_RUN_CACHE.clear()
    wall, cpu = time.perf_counter(), time.process_time()
    result = run_project(*args, **kwargs)
    return result, {"wall": time.perf_counter() - wall,
                    "cpu": time.process_time() - cpu}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--baseline-only", action="store_true")
    ap.add_argument("--pairs", type=int, default=3)
    ap.add_argument("--blocks", type=int, default=3)
    ap.add_argument("--other-technologies", action="store_true")
    args = ap.parse_args()
    os.environ.setdefault("FINCO_MODEL_EXECUTION_MODE", "process")
    from app.persistence import db
    from app.runtime import model_execution
    from app.v2 import post_run_ui
    db.DB_PATH = str(Path(tempfile.mkdtemp(prefix="finco-v6-context-")) / "bench.db")
    db.init_db()
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.workbook.update_service import WorkbookUpdateService
    from fastapi.testclient import TestClient
    import main_web

    original_builder = post_run_ui.build_post_run_ui_state
    entry_name = ("build_post_run_ui_state" if args.baseline_only else
                  "build_coherent_post_run_ui_state")
    original_entry = getattr(post_run_ui, entry_name)
    original_executor = model_execution.run_model_process
    active = {"arm": "baseline", "case": "solar"}
    rows, captures, workers, logs = [], [], [], []
    render_samples, parity = {}, []

    def render(arm, kw):
        if args.baseline_only:
            return original_builder(**kw)
        if arm == "baseline":
            return original_builder(**kw, context=None)
        return original_entry(**kw)

    def instrumented_builder(**kw):
        # The coherent entry captures the context inside this timed call;
        # capture and final validation are not a free/prebuilt cache.
        kw.pop("context", None)
        t = time.perf_counter()
        html = render(active["arm"], kw)
        rows.append({**active, "builder": time.perf_counter() - t})
        captures.append((kw, html))
        return html

    async def instrumented_executor(fn, *a, **k):
        result, metrics = await original_executor(measured_worker, *a, **k)
        workers.append(metrics)
        return result

    class StageLog(logging.Handler):
        def emit(self, record):
            logs.append(record.getMessage())

    handler = StageLog()
    logger = logging.getLogger("finco.run_stages")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    setattr(post_run_ui, entry_name, instrumented_builder)
    model_execution.run_model_process = instrumented_executor
    uid = "bench-context-user"
    cookies = {COOKIE_NAME: create_session_token(user_id=uid, username="admin")}
    try:
        with TestClient(main_web.app) as client:
            cases = [
                ("solar", "generic_solar_reference", 64.0),
                ("wind", "generic_wind_reference", 48.0),
            ]
            if args.other_technologies:
                cases += [("data_center", "generic_data_center_reference", 16.0),
                          ("ev_charging", "generic_ev_charging_reference", 1.0)]
            for case, template, capacity in cases:
                pr = create_reference_seeded_project(
                    user_id=uid, template_source=template,
                    requested_name="Context " + case, capacity_mw=capacity)
                active["case"] = case

                def tokens():
                    page = client.get("/v2/workbook", params={"project": pr.project_code},
                                      cookies=cookies)
                    assert page.status_code == 200
                    return (re.search(r'name="content_hash" value="([^"]+)"', page.text).group(1),
                            re.search(r'name="workbook_version" value="([^"]+)"', page.text).group(1))

                def run(arm):
                    h, v = tokens()
                    active["arm"] = arm
                    t = time.perf_counter()
                    response = client.post("/v2/workbook/run", cookies=cookies,
                        headers={"HX-Request": "true"},
                        data={"project": pr.project_code, "content_hash": h,
                              "workbook_version": v})
                    assert response.status_code == 200, response.text[:400]
                    rows[-1].update(route=time.perf_counter() - t,
                                    worker=workers[-1], stages=logs[-1:])

                run("baseline")
                rows[-1]["first_use"] = True
                kw, expected = captures[-1]
                samples = {"baseline": [], "context": []}
                for block in range(args.blocks):
                    order = ("baseline", "context", "context", "baseline")
                    if block % 2:
                        order = ("context", "baseline", "baseline", "context")
                    for arm in order:
                        t = time.perf_counter()
                        actual = render(arm, kw)
                        samples[arm].append(time.perf_counter() - t)
                        assert actual == expected, "Deterministic HTML diverged"
                render_samples[case] = samples
                for pair in range(args.pairs):
                    h, v = tokens()
                    ws = get_workspace_state(uid, pr.project_id)
                    WorkbookUpdateService.apply_draft_update(
                        ws=ws, field_id="opex.lines.technical_management",
                        raw_value=str(600.125 + pair), content_hash=h,
                        workbook_version=v, project_record=pr)
                    order = ("baseline", "context") if pair % 2 == 0 else ("context", "baseline")
                    for arm in order:
                        run(arm)
                        kw, actual = captures[-1]
                        exact = actual == render("baseline", kw)
                        assert exact, "Actual route HTML diverged"
                        parity.append({"case": case, "arm": arm, "html_exact": exact})
                    print(case, pair, rows[-2:], flush=True)
    finally:
        setattr(post_run_ui, entry_name, original_entry)
        model_execution.run_model_process = original_executor
        model_execution.reset_model_executor_for_tests()
        logger.removeHandler(handler)
    summary = {}
    for case, samples in render_samples.items():
        med = {k: statistics.median(v) for k, v in samples.items()}
        route_summary = {}
        for arm in ("baseline", "context"):
            actual = [r for r in rows if r["case"] == case and r["arm"] == arm and not r.get("first_use")]
            stages = [dict((k, int(v)) for k, v in re.findall(r'(\w+)=(\d+)ms', r["stages"][0]))
                      for r in actual]
            route_summary[arm] = {
                "route": statistics.median(r["route"] for r in actual),
                "worker": statistics.median(r["worker"]["wall"] for r in actual),
                "builder": statistics.median(r["builder"] for r in actual),
                "post_engine_ms": statistics.median(s["persistence_completed"] + s["response_generated"] for s in stages),
                "stage_medians_ms": {k: statistics.median(s[k] for s in stages) for k in stages[0]},
            }
        reduction = 100 * (1 - route_summary["context"]["post_engine_ms"] / route_summary["baseline"]["post_engine_ms"])
        summary[case] = {"builder_medians": med,
                         "saving_ms": 1000 * (med["baseline"] - med["context"]),
                         "route": route_summary, "post_engine_reduction_pct": reduction}
    out = {"baseline_only": args.baseline_only, "rows": rows, "renders": render_samples,
           "parity": parity, "summary": summary,
           "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
           "python": sys.version, "platform": platform.platform(),
           "source_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in (
               "app/v2/post_run_context.py", "app/v2/post_run_ui.py", "app/v2/router.py",
               "app/ui/trust_pack.py", "app/api/v1_1/institutional.py") if (ROOT / p).exists()}}
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(summary, flush=True)


if __name__ == "__main__":
    main()
