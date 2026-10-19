import sys; sys.path.insert(0, ".")
import harness as H, matrix as M
name = sys.argv[1]
build, ptype, policy = M.CASES[name]
case = {"build": build, "ptype": ptype, "policy": policy}
for v in ["A"] + sys.argv[2:]:
    out, t, st = H.run_case(case, () if v == "A" else M.VARIANTS[v])
    print(v, f"{t:.2f}s", (type(out).__name__ + ": " + str(out)[:600]) if isinstance(out, Exception) else ("OK " + str(H.summary(out))[:900]), st)
