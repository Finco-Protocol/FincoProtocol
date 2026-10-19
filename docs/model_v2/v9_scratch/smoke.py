import sys, time
sys.path.insert(0, ".")
import harness as H
from app import project_factories as pf
cases = {
 "S16": {"build": lambda: __import__("matrix").S16(), "ptype": "Solar"},
 "Solar50": {"build": pf.create_default_solar_project, "ptype": "Solar"},
 "Wind25": {"build": lambda: pf.create_default_wind_project(capacity_mw=25.0), "ptype": "Wind"},
}
which = sys.argv[1]; variants = sys.argv[2:]
case = cases[which]
base, tb, _ = H.run_case(case)
db = H.outcome_digest(base)
print(which, "baseline", f"{tb:.2f}s leaves={len(db)}", "EXC" if isinstance(base, Exception) else "")
for v in variants:
    flags = tuple(v.split("+"))
    out, t, st = H.run_case(case, flags)
    d = H.outcome_digest(out)
    r = H.compare(db, d)
    print(f"  {v:12s} {t:6.2f}s x{tb/t:4.2f} floats={r['float_leaves']} identical={r['bit_identical_floats']} "
          f"max_abs={r['max_abs']:.3e} ({r['max_abs_path']}) max_rel={r['max_rel']:.2e} "
          f"cat={len(r['categorical'])} struct={len(r['structural'])} diag={len(r['diagnostic'])} stats={st}")
    for c in r["categorical"][:8]: print("     CAT", c)
    for c in r["structural"][:5]: print("     STRUCT", c)
    if isinstance(out, Exception): print("     EXC", out)
