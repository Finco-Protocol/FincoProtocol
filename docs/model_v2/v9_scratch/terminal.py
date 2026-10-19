"""Terminal-classification margin: distance of every terminal balance from the 1e-7 REPAID threshold."""
import sys, json
sys.path.insert(0, ".")
import harness as H, matrix as M
TERM = ("balance_at_contractual_maturity_keur", "terminal_model_horizon_balance_keur", "outstanding_at_maturity_keur",
        "unpaid_at_maturity_keur")
out = {}
for name in sys.argv[2].split(","):
    build, ptype, policy = M.CASES[name]
    case = {"build": build, "ptype": ptype, "policy": policy}
    b, _, _ = H.run_case(case)
    if isinstance(b, Exception):
        continue
    db = H.flatten(b)
    rows = {}
    for v in sys.argv[3].split(","):
        o, _, _ = H.run_case(case, M.VARIANTS[v]); do = H.flatten(o)
        for k, x in db.items():
            if k.rsplit(".", 1)[-1] in TERM and isinstance(x, float):
                y = do.get(k)
                r = rows.setdefault(k, {"baseline": x})
                r[v] = y
    out[name] = rows
    worst = min((abs(r["baseline"] - 1e-7), k) for k, r in rows.items())
    print(name, "terminal balances:", len(rows), "closest-to-threshold:", worst[1].split(".")[-2:], f"{[r for k, r in rows.items() if k == worst[1]][0]}", flush=True)
json.dump(out, open(sys.argv[1], "w"), indent=1)
