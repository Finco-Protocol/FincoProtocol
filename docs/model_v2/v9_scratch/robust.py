"""Safeguard / fallback exercise: forced Anderson rejections, m variations, forced joint fallback."""
import sys; sys.path.insert(0, ".")
import harness as H, matrix as M, v9proto
name = sys.argv[1]
build, ptype, policy = M.CASES[name]
case = {"build": build, "ptype": ptype, "policy": policy}
b, tb, _ = H.run_case(case); db = H.outcome_digest(b)
orig_init = v9proto.Anderson.__init__
def show(label, flags):
    o, t, st = H.run_case(case, flags); r = H.compare(db, H.outcome_digest(o))
    print(f"{name} {label:34s} x{tb/t:5.2f} id={r['bit_identical_floats']}/{r['float_leaves']} max={r['max_abs']:.2e} cat={len(r['categorical'])} struct={len(r['structural'])} stats={ {k: v for k, v in st.items() if v} }", flush=True)
for label, kw in [("AA m=1", dict(m=1)), ("AA m=3", dict(m=3)), ("AA forced rejection (decrease=1e-12)", dict(decrease=1e-12)),
                  ("AA early terminal Picard (switch 1e-1)", dict(switch_tol=1e-1)), ("AA late terminal Picard (switch 1e-9)", dict(switch_tol=1e-9))]:
    v9proto.Anderson.__init__ = lambda self, _kw=kw, **k: orig_init(self, **{**k, **_kw})
    show(label, M.VARIANTS["CBW"])
v9proto.Anderson.__init__ = orig_init
# forced joint fallback: the acceptance test on the returned result fails -> canonical policy loop
orig_ctx = v9proto.JointCtx.__init__
v9proto.JointCtx.__init__ = lambda self, a, b_, F0, tol: orig_ctx(self, a, b_, F0, -1.0)
show("C forced fallback (acceptance fails)", ("C",))
v9proto.JointCtx.__init__ = orig_ctx
