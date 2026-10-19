"""Quarterly 3/3 in an ISOLATED worktree of PR #320 head (b8b9b392d5) — never production main."""
import os, sys
os.environ["V9_ROOT"] = "/home/user/v9q"
sys.path.insert(0, "."); sys.path.insert(0, "/home/user/v9q/tests"); sys.path.insert(0, "/home/user/v9q")
import v9proto, harness as H
assert v9proto.P.__file__.startswith("/home/user/v9q"), v9proto.P.__file__
from test_rc7b_quarterly_funding_statements import build, canonical_run
import time
def run_case(case, flags=()):
    pi = case["build"](); H.clear_caches()
    import contextlib
    cm = v9proto.installed(flags) if flags else contextlib.nullcontext()
    with cm:
        t = time.perf_counter()
        try:
            out = canonical_run(pi)
        except Exception as e:
            out = e
        return out, time.perf_counter() - t, {}
H.run_case = run_case
VARS = {"B1": ("B1",), "D": ("D",), "BA": ("BA",), "BG": ("BG",), "B1+D": ("B1", "D"),
        "B": ("B1", "BA", "BW", "BG"), "C": ("C", "B1"), "FULL": ("C", "B1", "D", "BW", "BG")}
for kind in ("solar", "wind"):
    for freq in ("Q", "S"):
        for extra in ({}, {"gearing_ratio": 0.5}):
            case = {"build": (lambda kind=kind, freq=freq, extra=extra: build(kind, freq, **extra)), "ptype": kind.capitalize()}
            base, tb, _ = H.run_case(case); db = H.outcome_digest(base)
            line = [f"{kind:5s} {freq} {extra or ''} base={tb:.2f}s {'EXC '+db['<exception>'][:90] if '<exception>' in db else ''}"]
            for v, fl in VARS.items():
                out, t, st = H.run_case(case, fl); r = H.compare(db, H.outcome_digest(out))
                line.append(f"{v}:x{tb/t:.2f},id={r['bit_identical_floats']}/{r['float_leaves']},max={r['max_abs']:.1e},cat={len(r['categorical'])}")
            print(" ".join(line), flush=True)
