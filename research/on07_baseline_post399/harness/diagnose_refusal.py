#!/usr/bin/env python3
"""DIAGNOSTIC ONLY (not baseline evidence): re-run a refused fixture with ONE EXPLICIT value altered at a time to localise the
fail-closed cause. Altered runs are never reported as the fixture. python -I diagnose_refusal.py --repo R --fixtures CSV --fixture WND-02 --out json"""
import argparse, copy, json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import on07_common as C
ap = argparse.ArgumentParser(); [ap.add_argument(f"--{x}", required=True) for x in ("repo", "fixtures", "fixture", "out")]
ap.add_argument("--probe", action="append", default=[], help="key=value overrides, one per run, e.g. tenor_years=14")
a = ap.parse_args(); a.no_subline_fold = True
os.environ["FINCO_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="on07diag_"), "d.db"); C.repo_setup(a.repo)
import run_on07_workbook as R
rows = R.load(a.fixtures)[a.fixture]; out = {"DIAGNOSTIC_ONLY": True, "fixture": a.fixture, "runs": []}
for spec in ["(unaltered)"] + a.probe:
    rr = copy.deepcopy(rows)
    if spec != "(unaltered)":
        k, v = spec.split("=", 1)
        for r in rr:
            if r["fixture_key"] == k: r["intended_value"] = v
    cap = R.run_fixture(a.fixture, rr, a)
    out["runs"].append({"alteration": spec, "status": cap["status"], "error": cap.get("error"), "min_dscr": (cap.get("kpis") or {}).get("min_dscr")})
    print(out["runs"][-1])
json.dump(out, open(a.out, "w"), indent=1)
