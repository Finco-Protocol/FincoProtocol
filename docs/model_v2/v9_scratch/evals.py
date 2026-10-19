"""Evaluation counts per fixed-point level (cProfile ncalls aggregated by function name)."""
import cProfile, pstats, sys, json
sys.path.insert(0, ".")
import harness as H, matrix as M
KEYS = {"run_with_generic_financing_policy": "DSRA policy", "run_project_shareholder_waterfall_model": "engine (WF)",
        "_run_with_construction_idc": "IDC loops", "run_project_financing_model": "G2A solves",
        "run_senior_debt_model": "Senior model runs", "_run_senior_debt_model_with_shl": "SHL-tax fixed points",
        "solve_senior_debt": "DSCR/gearing solves", "calculate_cfads_and_cash_tax": "tax/CFADS evaluations",
        "run_stage_b2_provisional": "Stage B2 provisional", "run_stage_b2": "Stage B2 strict"}
out = {}
for name in sys.argv[1].split(","):
    build, ptype, policy = M.CASES[name]
    case = {"build": build, "ptype": ptype, "policy": policy}
    out[name] = {}
    for v in ["A", "B1", "B", "C", "CBW", "FULLnoD", "D"]:
        flags = () if v == "A" else M.VARIANTS[v]
        pr = cProfile.Profile(); pr.enable(); H.run_case(case, flags); pr.disable()
        agg = {}
        for (fn, ln, fname), (cc, nc, tt, ct, callers) in pstats.Stats(pr).stats.items():
            if fname in KEYS:
                agg[KEYS[fname]] = agg.get(KEYS[fname], 0) + nc
        out[name][v] = agg
        print(name, v, agg, flush=True)
json.dump(out, open(sys.argv[2], "w"), indent=1)
