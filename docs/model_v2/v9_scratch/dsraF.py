import sys; sys.path.insert(0, ".")
import harness as H, matrix as M
import financial_engine.financing.generic_product_policy as GP
orig = GP._peak_forward_debt_service_keur
log = []
def w(r):
    v = orig(r); log.append(v); return v
GP._peak_forward_debt_service_keur = w
name = sys.argv[1]
build, ptype, policy = M.CASES[name]
case = {"build": build, "ptype": ptype, "policy": policy}
b, tb, _ = H.run_case(case); print("A targets:", [repr(x) for x in log]); log.clear()
d = H.flatten(b)
fa = [v for k, v in d.items() if k.endswith("debt_service_reserve_requirement_keur")]
o, tc, st = H.run_case(case, M.VARIANTS["C"]); print("C targets:", [repr(x) for x in log][-6:], st)
do = H.flatten(o)
fc = [v for k, v in do.items() if k.endswith("debt_service_reserve_requirement_keur")]
print("F baseline", fa[:2], "F C", fc[:2])
