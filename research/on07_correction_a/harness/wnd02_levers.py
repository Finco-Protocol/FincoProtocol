#!/usr/bin/env python3
"""WND-02 economic-feasibility levers on the TRUE route (route-consistent timeline 20m/27y so the grid defect is removed). DIAGNOSTIC ONLY.
(1) original WND-02 with SHL indices re-derived in memory (not a route) -> which refusal; (2) bisection of total CAPEX; (3) bisection of PPA tariff.
python -I wnd02_levers.py --repo R --fixtures CSV --out JSON"""
import argparse, json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import on07_common as C
ap = argparse.ArgumentParser(); [ap.add_argument(f"--{x}", required=True) for x in ("repo", "fixtures", "out")]; a = ap.parse_args(); a.tag = "levers"
os.environ["FINCO_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="on07lev_"), "d.db"); C.repo_setup(a.repo)
import true_route as T
rows = T.load(a.fixtures)["WND-02"]
BASE = {"construction_months": "20", "horizon_years": "27"}
def run(ov):
    cap = T.run_fixture("WND-02", rows, a, {**BASE, **ov})
    k = cap.get("kpis") or {}
    code = None
    if cap["status"] != "RUN_OK":
        e = cap.get("error", ""); code = next((c for c in ("SHL_MATURITY_RESIDUAL_FAILS_CLOSED", "SHL_MATURITY_NOT_ON_PERIOD_GRID_FAILS_CLOSED") if c in e), e[:120])
    return {"overrides": ov, "status": cap["status"], "refusal": code, "senior": k.get("senior_debt_keur"), "actual_gearing": k.get("actual_gearing_pct"), "min_dscr": k.get("min_dscr"),
            "sponsor_xirr": k.get("total_sponsor_xirr"), "project_irr": k.get("project_irr"), "mismatch": [x for x, v in (cap.get("intended_vs_effective") or {}).items() if v["verdict"] != "MATCH"], "error": (cap.get("error") or "")[:200]}, cap
out = {"diagnostic_only": True, "timeline_override": BASE, "bisect_capex": [], "bisect_tariff": []}
def bis(lo, hi, key, fmt, log, tol):
    # lo = infeasible side value, hi = feasible side value; find the boundary
    for _ in range(14):
        mid = (lo + hi) / 2; r, _c = run({key: fmt(mid)}); log.append(r); print(key, fmt(mid), r["status"], r["refusal"])
        if r["status"] == "RUN_OK": hi = mid
        else: lo = mid
        if abs(hi - lo) < tol: break
    return hi
r0, _ = run({}); out["route_consistent_unaltered"] = r0; print("20m/27y unaltered:", r0["status"], r0["refusal"])
ok_lo, _ = run({"total_capex_keur": "20000"}); out["capex_20000"] = ok_lo; print("capex 20000:", ok_lo["status"], ok_lo["refusal"])
if ok_lo["status"] == "RUN_OK":
    out["capex_boundary_feasible_at"] = bis(52000.0, 20000.0, "total_capex_keur", lambda v: f"{v:.2f}", out["bisect_capex"], 50.0)
ok_t, _ = run({"rev_ppa_base_tariff": "120.00"}); out["tariff_120"] = ok_t; print("tariff 120:", ok_t["status"], ok_t["refusal"])
if ok_t["status"] == "RUN_OK":
    out["tariff_boundary_feasible_at"] = bis(58.0, 120.0, "rev_ppa_base_tariff", lambda v: f"{v:.2f}", out["bisect_tariff"], 1.0)
json.dump(out, open(a.out, "w"), indent=1, default=str)
