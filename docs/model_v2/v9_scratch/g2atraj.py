import sys; sys.path.insert(0, ".")
import harness as H, matrix as M
import financial_engine.financing.project as P
orig = P.reconcile_financing_stack
log = []
def w(**k):
    r = orig(**k); log.append((k["final_senior_commitment_keur"], r[0])); return r
P.reconcile_financing_stack = w
case = {"build": lambda: M.scale_capex(M.pf.create_default_solar_project(capacity_mw=16.0), 0.26), "ptype": "Solar"}
H.run_case(case)
prev = None
for s, d in log[:40]:
    print(f"senior={s:.9f} derived_shl={d:.9f}" + (f" d={d-prev:+.3e}" if prev is not None else "")); prev = d
