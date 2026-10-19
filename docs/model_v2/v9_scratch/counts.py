"""V9-A scratch: cProfile call counts for the nested fixed-point hierarchy (read-only on /home/user/v9)."""
import cProfile, pstats, sys, time, json
sys.path.insert(0, "/home/user/v9")
from app import project_factories as pf
from app.services import production_financial_authority as pfa
F = {"Solar": pf.create_default_solar_project, "Wind": pf.create_default_wind_project,
     "DC": pf.create_default_data_center_project}
KEYS = ["run_with_generic_financing_policy", "run_project_shareholder_waterfall_model",
        "_run_with_construction_idc", "run_project_financing_model", "run_stage_b2_provisional", "run_stage_b2",
        "run_senior_debt_model", "_run_senior_debt_model_with_shl", "solve_senior_debt",
        "_make_solver_tax_cfads_fn", "calculate_cfads_and_cash_tax", "compute_shareholder_loan_schedules",
        "reconcile_financing_stack", "_finalise_authoritative", "_compute_max_abs_diff", "run_operating_model"]
which = sys.argv[1]
pi = F[which]()
ptype = "DataCenter" if which == "DC" else which
pr = cProfile.Profile(); pr.enable()
t = time.perf_counter(); pfa.run_clean_production(pi, project_type=ptype); dt = time.perf_counter() - t
pr.disable()
st = pstats.Stats(pr).stats
out = {}
for (fn, ln, name), (cc, nc, tt, ct, callers) in st.items():
    if name in KEYS:
        k = f"{name}@{fn.split('/')[-1]}"
        out[k] = (nc, round(ct, 3))
print(which, f"profiled={dt:.2f}s")
for k, v in sorted(out.items(), key=lambda kv: -kv[1][1]):
    print(f"  {k:70s} calls={v[0]:6d} cum={v[1]:8.3f}s")
