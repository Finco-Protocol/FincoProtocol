"""Quiet-CPU timing: genuine uncached runs, interleaved, median and p95 per candidate."""
import json, statistics, sys, gc
sys.path.insert(0, ".")
import harness as H, matrix as M
VARS = {"A": (), "B1": ("B1",), "B": M.VARIANTS["B"], "C": M.VARIANTS["C"],
        "CBW": M.VARIANTS["CBW"], "FULLnoD": M.VARIANTS["FULLnoD"]}
def p95(xs):
    xs = sorted(xs); k = 0.95 * (len(xs) - 1); f = int(k); c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)
out = {}
reps = int(sys.argv[2]); names = sys.argv[3].split(",")
for name in names:
    build, ptype, policy = M.CASES[name]
    case = {"build": build, "ptype": ptype, "policy": policy}
    H.run_case(case)  # warm imports/JIT-free caches outside the measured runs
    samples = {v: [] for v in VARS}
    for r in range(reps):
        for v, flags in VARS.items():
            gc.collect()
            _, t, _ = H.run_case(case, flags)
            samples[v].append(t)
    a = statistics.median(samples["A"])
    out[name] = {v: {"median": statistics.median(s), "p95": p95(s), "min": min(s), "max": max(s),
                     "samples": s, "speedup_median": a / statistics.median(s),
                     "time_saving_pct": 100.0 * (1 - statistics.median(s) / a)} for v, s in samples.items()}
    print(name, " ".join(f"{v}={out[name][v]['median']:.2f}s/p95={out[name][v]['p95']:.2f}({out[name][v]['time_saving_pct']:+.0f}%)" for v in VARS), flush=True)
    json.dump(out, open(sys.argv[1], "w"), indent=1)
