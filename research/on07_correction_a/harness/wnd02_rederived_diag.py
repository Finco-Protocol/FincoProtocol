#!/usr/bin/env python3
"""DIAGNOSTIC ONLY: original WND-02 (18m/25y) on the true route, SHL indices re-derived IN MEMORY with resolve_generic_shl_policy, then run_project.
Not a route, not a fix, not a baseline. python -I wnd02_rederived_diag.py --repo R --fixtures CSV --out JSON"""
import argparse, json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import on07_common as C
ap = argparse.ArgumentParser(); [ap.add_argument(f"--{x}", required=True) for x in ("repo", "fixtures", "out")]; a = ap.parse_args(); a.tag = "diag"
os.environ["FINCO_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="on07dg_"), "d.db"); C.repo_setup(a.repo)
import true_route as T, app.api.project_runner as PR
from app.generic_shl_policy import resolve_generic_shl_policy
orig = PR.run_project; res = {}
def hook(key, scen, view, project_inputs_override=None, **kw):
    pi = resolve_generic_shl_policy(project_inputs_override)
    res["rederived"] = {"maturity": pi.financing.shl_maturity_period_index, "elig_start": pi.financing.shl_principal_eligibility_start_period}
    return orig(key, scen, view, project_inputs_override=pi, **kw)
PR.run_project = hook
cap = T.run_fixture("WND-02", T.load(a.fixtures)["WND-02"], a, {})
k = cap.get("kpis") or {}
res.update(status=cap["status"], error=cap.get("error"), senior=k.get("senior_debt_keur"), min_dscr=k.get("min_dscr"), sponsor_xirr=k.get("total_sponsor_xirr"))
print(res); json.dump({"DIAGNOSTIC_ONLY": True, **res}, open(a.out, "w"), indent=1)
