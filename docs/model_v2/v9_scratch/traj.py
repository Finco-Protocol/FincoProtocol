"""V9-A scratch: residual trajectories per fixed-point level (runtime wrapping only)."""
import sys, importlib, functools, math
sys.path.insert(0, "/home/user/v9")
from app import project_factories as pf
from app.services import production_financial_authority as pfa

log = []
def patch(mod, name, make):
    m = importlib.import_module(mod); orig = getattr(m, name); w = make(orig)
    for sm in list(sys.modules.values()):
        d = getattr(sm, "__dict__", None)
        if d is None: continue
        for k, v in list(d.items()):
            if v is orig: d[k] = w

def mk_peak(orig):
    def w(result):
        v = orig(result); log.append(("DSRA_TARGET", v)); return v
    return w
def mk_b2p(orig):
    def w(cfg):
        r = orig(cfg); c = r.capitalized_financing_costs
        log.append(("B2P", c.senior_idc_keur, c.senior_commitment_fee_keur, c.structuring_fee_keur, r.unfunded_uses_keur)); return r
    return w
def mk_g2a(orig):
    def w(*a, **k):
        log.append(("G2A_IN",))
        r = orig(*a, **k)
        log.append(("G2A_OUT", r.final_senior_commitment_keur, r.derived_shl_cash_principal_keur,
                    r.project_uses.total_project_uses_keur, r.fixed_point_iteration_count, r.fixed_point_maximum_difference_keur)); return r
    return w
def mk_shl(orig):
    def w(periods, shl_input, cash, *a, **k):
        r = orig(periods, shl_input, cash, *a, **k)
        log.append(("SHL", tuple(r.shl_gross_interest_keur), tuple(r.shl_closing_keur))); return r
    return w
def mk_sdm(orig):
    def w(*a, **k):
        log.append(("SHLTAX_IN",)); r = orig(*a, **k); log.append(("SHLTAX_OUT",)); return r
    return w
def mk_solve(orig):
    def w(*a, **k):
        fn = k.get("tax_cfads_fn"); cnt = [0]
        if fn is not None:
            def f2(*x, **y):
                cnt[0] += 1; return fn(*x, **y)
            k["tax_cfads_fn"] = f2
        r = orig(*a, **k); log.append(("SOLVE", cnt[0], r.diagnostics.iteration_count if hasattr(r.diagnostics, "iteration_count") else None)); return r
    return w

if __name__ == "__main__":
    patch("financial_engine.financing.generic_product_policy", "_peak_forward_debt_service_keur", mk_peak)
    patch("finco_core.construction.stage_b2", "run_stage_b2_provisional", mk_b2p)
    patch("financial_engine.financing.project", "run_project_financing_model", mk_g2a)
    patch("financial_engine.shl.production", "compute_shareholder_loan_schedules", mk_shl)
    patch("financial_engine.orchestrator", "_run_senior_debt_model_with_shl", mk_sdm)
    patch("financial_engine.senior_debt.solver", "solve_senior_debt", mk_solve)
    import matrix as _M
    F = {"S16": lambda: _M.scale_capex(pf.create_default_solar_project(capacity_mw=16.0), 0.26), "Solar": pf.create_default_solar_project, "Wind": pf.create_default_wind_project, "DC": pf.create_default_data_center_project, "Wind25": lambda: pf.create_default_wind_project(capacity_mw=25.0), "Solar16": lambda: pf.create_default_solar_project(capacity_mw=16.0)}
    which = sys.argv[1]
    pfa.run_clean_production(F[which](), project_type={"DC":"DataCenter","Wind25":"Wind","Solar16":"Solar"}.get(which, "Solar" if which == "S16" else which))
    prev_b2 = None; prev_g = None; shl_prev = None; solves = []
    for e in log:
        t = e[0]
        if t == "DSRA_TARGET": print(f"DSRA target={e[1]!r}")
        elif t == "B2P":
            d = max(abs(a - b) for a, b in zip(e[1:4], prev_b2[1:4])) if prev_b2 else float('nan')
            print(f"   B2P idc={e[1]:.9f} fee={e[2]:.9f} st={e[3]:.9f} unf={e[4]:.3e} d={d:.3e}"); prev_b2 = e
        elif t == "G2A_OUT":
            d = max(abs(a - b) for a, b in zip(e[1:4], prev_g[1:4])) if prev_g else float('nan')
            print(f"   G2A sen={e[1]:.9f} shl={e[2]:.9f} uses={e[3]:.9f} it={e[4]} md={e[5]:.2e} dprev={d:.3e}"); prev_g = e
        elif t == "SHLTAX_IN": shl_prev = None; solves = []; deltas = []
        elif t == "SHL":
            if shl_prev is not None:
                deltas.append(max(abs(a - b) for a, b in zip(e[1], shl_prev[1])))
            shl_prev = e
        elif t == "SOLVE": solves.append(e[1])
        elif t == "SHLTAX_OUT":
            print("      SHLTAX iters=%d taxfn/solve=%s dInt=%s" % (len(solves), solves, " ".join(f"{x:.1e}" for x in deltas)))
