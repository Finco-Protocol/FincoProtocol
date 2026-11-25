"""FINCO43 — bounded, opt-in performance harness (not part of CI; wall-clock depends on the machine).

Two measurements, both on a disposable temporary SQLite database with synthetic reference-seeded projects only:

``engine``  paired, alternating (AB/BA) fresh-interpreter samples of ONE canonical ``run_project`` per scenario in two
            source trees (baseline vs candidate), separately for the cold first Run of the process, warm Runs with the
            process policy memo cleared (cache MISS, real recompute) and the identical re-run (memo HIT, reported
            separately — never counted as engine speed). Records wall + CPU per sample and max RSS.

``http``    the real ``POST /v2/workbook/run`` route through the ASGI app (owner session cookie, CSRF token, CAS
            content_hash/workbook_version) with the stage breakdown logged by ``app.services.run_stage_timing``
            (workspace / model / persistence / response), response bytes, and the follow-up ``GET /v2/workbook``
            bytes. Every measured Run follows a real draft edit (unique inputs -> real recompute, not replay).

    python tools/finco43_perf_harness.py engine --baseline /path/base --candidate . --pairs 5 --out engine.json
    python tools/finco43_perf_harness.py http --tree /path/to/tree --runs 6 --out http.json [--mode process|thread]

Outputs are raw JSON samples plus a printed p50 / max summary (max over n samples; with n < 30 no reliable p95 is
claimed). No user data, secrets or host paths are written; the temporary database is deleted on exit.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ENGINE_SCENARIOS = {
    "solar": ("Solar", "create_default_solar_project"),
    "wind": ("Wind", "create_default_wind_project"),
    "solar-ref": ("Generic Solar Reference", "create_generic_solar_reference"),
    "wind-ref": ("Generic Wind Reference", "create_generic_wind_reference"),
    "dc-ref": ("Generic Data Center Reference", "create_generic_data_center_reference"),
    "ev-ref": ("Generic EV Charging Reference", "create_generic_ev_charging_reference"),
}

_CHILD = r"""
import json, os, resource, sys, time
sys.path.insert(0, os.getcwd())
from app import project_factories as pf
from app.api.project_runner import run_project
from app.services import production_financial_authority as pfa
pt, fac, reps = sys.argv[1], sys.argv[2], int(sys.argv[3])
base = getattr(pf, fac)()
def one(clear):
    if clear:
        pfa._POLICY_RUN_CACHE.clear()
    w, c = time.perf_counter(), time.process_time()
    run_project(pt, "Base", project_inputs_override=base)
    return [time.perf_counter() - w, time.process_time() - c]
out = {"cold": one(True), "warm": [one(True) for _ in range(reps)], "hit": one(False)}
out["maxrss_kb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(json.dumps(out))
"""


def _summ(values):
    return {"n": len(values), "p50": statistics.median(values), "max": max(values), "min": min(values)}


def engine(args) -> int:
    trees = {"base": os.path.abspath(args.baseline), "cand": os.path.abspath(args.candidate)}
    env = dict(os.environ, PYTHONHASHSEED="0", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    rows = []
    labels = args.scenarios.split(",")
    for pair in range(args.pairs):
        for label in labels:
            pt, fac = ENGINE_SCENARIOS[label]
            order = ("base", "cand") if pair % 2 == 0 else ("cand", "base")
            for arm in order:
                proc = subprocess.run([sys.executable, "-c", _CHILD, pt, fac, str(args.warm)], cwd=trees[arm],
                                      env=env, capture_output=True, text=True, check=True)
                sample = json.loads(proc.stdout.strip().splitlines()[-1])
                sample.update(arm=arm, pair=pair, label=label)
                rows.append(sample)
    summary = {}
    for label in labels:
        for metric in ("cold", "warm", "hit"):
            per = {}
            for arm in ("base", "cand"):
                sel = [r for r in rows if r["label"] == label and r["arm"] == arm]
                if metric == "warm":
                    vals = [s[0] for r in sel for s in r["warm"]]
                    cpu = [s[1] for r in sel for s in r["warm"]]
                elif metric == "cold":
                    vals, cpu = [r["cold"][0] for r in sel], [r["cold"][1] for r in sel]
                else:
                    vals, cpu = [r["hit"] for r in sel], []
                per[arm] = {"wall": _summ(vals), "cpu": _summ(cpu) if cpu else None,
                            "maxrss_kb_p50": statistics.median(r["maxrss_kb"] for r in sel)}
            per["delta_p50_pct"] = 100.0 * (per["cand"]["wall"]["p50"] / per["base"]["wall"]["p50"] - 1.0)
            summary[f"{label}:{metric}"] = per
            print(f"{label:10s} {metric:5s} base p50 {per['base']['wall']['p50']:.3f}s (n={per['base']['wall']['n']}, "
                  f"max {per['base']['wall']['max']:.3f}) | cand p50 {per['cand']['wall']['p50']:.3f}s "
                  f"(max {per['cand']['wall']['max']:.3f}) | {per['delta_p50_pct']:+.1f}%", flush=True)
    meta = {"python": sys.version.split()[0], "cpus": os.cpu_count(), "pairs": args.pairs, "warm_per_child": args.warm,
            "trees": {k: subprocess.run(["git", "rev-parse", "HEAD"], cwd=v, capture_output=True, text=True).stdout.strip()
                      for k, v in trees.items()},
            "dirty": {k: bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=v,
                                             capture_output=True, text=True).stdout.strip()) for k, v in trees.items()}}
    Path(args.out).write_text(json.dumps({"meta": meta, "rows": rows, "summary": summary}, indent=1))
    return 0


def http(args) -> int:
    os.environ["FINCO_MODEL_EXECUTION_MODE"] = args.mode
    tree = os.path.abspath(args.tree)
    sys.path.insert(0, tree)          # the measured tree's app/financial_engine, never this file's own tree
    os.chdir(tree)
    import logging

    tmp = tempfile.mkdtemp(prefix="finco43-http-")
    try:
        from app.persistence import db
        db.DB_PATH = str(Path(tmp) / "bench.db")
        db.init_db()
        from fastapi.testclient import TestClient

        import main_web
        from app.auth import COOKIE_NAME, create_session_token
        from app.persistence.workspace_repository import get_workspace_state
        from app.services.reference_seed_service import create_reference_seeded_project
        from app.workbook.update_service import WorkbookUpdateService
        from tests.run_clone_csrf import post_valid_csrf

        lines: list[str] = []

        class _Stages(logging.Handler):
            def emit(self, record):
                lines.append(record.getMessage())

        handler = _Stages()
        stage_log = logging.getLogger("finco.run_stages")
        stage_log.setLevel(logging.INFO)
        stage_log.addHandler(handler)
        uid = "finco43-bench-owner"
        cookies = {COOKIE_NAME: create_session_token(user_id=uid, username="admin")}
        rows = []
        with TestClient(main_web.app) as client:
            for case, template, capacity in (("solar", "generic_solar_reference", 64.0),
                                             ("wind", "generic_wind_reference", 48.0)):
                record = create_reference_seeded_project(user_id=uid, template_source=template,
                                                         requested_name="FINCO43 " + case, capacity_mw=capacity)

                def tokens():
                    t = time.perf_counter()
                    page = client.get("/v2/workbook", params={"project": record.project_code}, cookies=cookies)
                    elapsed = time.perf_counter() - t
                    assert page.status_code == 200
                    return (re.search(r'name="content_hash" value="([^"]+)"', page.text).group(1),
                            re.search(r'name="workbook_version" value="([^"]+)"', page.text).group(1),
                            len(page.content), elapsed)

                for i in range(args.runs + 1):
                    h, v, _, _ = tokens()
                    if i:  # real draft edit before every measured Run -> unique inputs, real recompute
                        WorkbookUpdateService.apply_draft_update(
                            ws=get_workspace_state(uid, record.project_id), field_id="revenue.ppa.base_tariff",
                            raw_value=f"{60.0 + 0.125 * i:.3f}", content_hash=h, workbook_version=v,
                            project_record=record)
                        h, v, _, _ = tokens()
                    t = time.perf_counter()
                    response = post_valid_csrf(client, "/v2/workbook/run", cookies=cookies,
                                               headers={"HX-Request": "true"},
                                               data={"project": record.project_code, "content_hash": h,
                                                     "workbook_version": v})
                    route = time.perf_counter() - t
                    assert response.status_code == 200, response.status_code
                    _, _, get_bytes, get_s = tokens()
                    stages = {k: int(x) for k, x in re.findall(r"(\w+)=(\d+)ms", lines[-1])}
                    rows.append({"case": case, "i": i, "first": i == 0, "route_s": route,
                                 "response_bytes": len(response.content), "get_after_bytes": get_bytes,
                                 "get_after_s": get_s, "stages_ms": stages})
                    print(json.dumps(rows[-1]), flush=True)
        stage_log.removeHandler(handler)
        summary = {}
        for case in ("solar", "wind"):
            sel = [r for r in rows if r["case"] == case and not r["first"]]
            summary[case] = {"route_s": _summ([r["route_s"] for r in sel]),
                             "response_bytes_p50": statistics.median(r["response_bytes"] for r in sel),
                             "stages_ms_p50": {k: statistics.median(r["stages_ms"].get(k, 0) for r in sel)
                                               for k in sel[0]["stages_ms"]}}
        print(json.dumps(summary, indent=1))
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tree, capture_output=True, text=True).stdout.strip()
        import financial_engine
        assert os.path.dirname(os.path.dirname(os.path.abspath(financial_engine.__file__))) == tree
        Path(args.out).write_text(json.dumps({"mode": args.mode, "head": head, "rows": rows, "summary": summary},
                                             indent=1))
        return 0
    finally:
        try:
            from app.runtime import model_execution
            model_execution.reset_model_executor_for_tests()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("engine")
    e.add_argument("--baseline", required=True)
    e.add_argument("--candidate", default=str(ROOT))
    e.add_argument("--pairs", type=int, default=5)
    e.add_argument("--warm", type=int, default=3)
    e.add_argument("--scenarios", default="solar,wind,solar-ref,wind-ref")
    e.add_argument("--out", required=True)
    h = sub.add_parser("http")
    h.add_argument("--runs", type=int, default=6)
    h.add_argument("--mode", choices=("process", "thread"), default="process")
    h.add_argument("--out", required=True)
    h.add_argument("--tree", default=str(ROOT), help="source tree to measure (baseline or candidate checkout)")
    args = ap.parse_args(argv)
    return engine(args) if args.cmd == "engine" else http(args)


if __name__ == "__main__":
    raise SystemExit(main())
