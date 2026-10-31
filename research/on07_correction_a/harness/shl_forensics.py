#!/usr/bin/env python3
"""WND-02 SHL maturity forensics. Builds the TRUE-ROUTE materialised ProjectInputs (via true_route helpers) and probes the period grid.
python -I shl_forensics.py --repo R --fixtures CSV --out JSON"""
import argparse, json, os, sys, tempfile, math, dataclasses
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import on07_common as C
ap = argparse.ArgumentParser(); [ap.add_argument(f"--{x}", required=True) for x in ("repo", "fixtures", "out")]; ap.add_argument("--sweep", action="store_true"); a = ap.parse_args()
os.environ["FINCO_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="on07shl_"), "d.db"); C.repo_setup(a.repo)
import true_route as T
from financial_engine.adapters.project_inputs import from_project_inputs
from financial_engine.orchestrator import _build_period_engine
from dataclasses import replace

def materialise(fid, overrides=None):
    # re-use the true-route pipeline but stop before run_project: monkeypatch run_project to capture the override
    import app.api.project_runner as PR
    cap = {}
    orig = PR.run_project
    def spy(key, scen, view, project_inputs_override=None, **kw):
        cap["pi"] = project_inputs_override; raise StopIteration("captured")
    PR.run_project = spy
    try:
        class A: pass
        aa = A(); aa.repo = a.repo; aa.tag = "forensics"
        r = T.run_fixture(fid, T.load(a.fixtures)[fid], aa, overrides)
    finally:
        PR.run_project = orig
    return cap.get("pi"), r

def grid(pi):
    ps = list(_build_period_engine(from_project_inputs(pi)).periods())
    return [p.index for p in ps], ps

out = {"fixtures": {}}
for fid in ("SOL-01", "SOL-02", "WND-01", "WND-02"):
    pi, r = materialise(fid)
    idx, ps = grid(pi)
    f = pi.financing; i = pi.info
    cm, hy, tn = i.construction_months, i.horizon_years, f.senior_tenor_years
    cper = math.ceil(cm / 6); pol_mat = cper + hy * 2 - 1; pol_elig = cper + tn * 2
    out["fixtures"][fid] = {"construction_months": cm, "horizon_years": hy, "senior_tenor_years": tn, "cod": str(i.cod_date), "financial_close": str(getattr(i, "financial_close", None)),
        "grid_first": idx[0], "grid_last": idx[-1], "grid_len": len(idx), "grid_last_end": str(ps[-1].end_date),
        "shl_maturity_in_inputs": f.shl_maturity_period_index, "shl_elig_start_in_inputs": f.shl_principal_eligibility_start_period,
        "policy_formula_maturity(c+2h-1)": pol_mat, "policy_formula_elig(c+2*tenor)": pol_elig,
        "maturity_on_grid": f.shl_maturity_period_index in idx, "inputs_equal_policy_formula": (f.shl_maturity_period_index == pol_mat and f.shl_principal_eligibility_start_period == pol_elig),
        "run_status_true_route": r["status"], "run_error": r.get("error")}
    print(fid, {k: out["fixtures"][fid][k] for k in ("grid_last", "shl_maturity_in_inputs", "policy_formula_maturity(c+2h-1)", "maturity_on_grid", "inputs_equal_policy_formula", "run_status_true_route")})
json.dump(out, open(a.out, "w"), indent=1, default=str)
