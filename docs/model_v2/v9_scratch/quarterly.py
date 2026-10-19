"""Quarterly 3/3 in the isolated research environment only (tools/quarterly_research on main)."""
import sys, time, statistics
sys.path.insert(0, "."); sys.path.insert(0, "/home/user/v9/tests")
import harness as H, matrix as M, v9proto
from tools.quarterly_research.runtime import evaluate_quarterly_candidate
from tools.quarterly_research.calendar import RenewableTechnology
from financial_engine.senior_debt.policy import SeniorDebtSizingMode
from test_rc7_quarterly_financial_candidate import study
for kind in (RenewableTechnology.SOLAR, RenewableTechnology.WIND):
    for sizing in (SeniorDebtSizingMode.DSCR_SCULPTED, SeniorDebtSizingMode.COMBINED_MINIMUM):
        def go():
            t = time.perf_counter(); r = evaluate_quarterly_candidate(study(kind=kind, sizing=sizing, tax_rate=0.0)); return r, time.perf_counter() - t
        base, tb = go(); db = H.flatten(base)
        line = [f"{kind.name:5s} {sizing.name:16s} base={tb*1000:.1f}ms leaves={len(db)}"]
        for v, flags in M.VARIANTS.items():
            with v9proto.installed(flags):
                out, t = go()
            r = H.compare(db, H.flatten(out))
            line.append(f"{v}:id={r['bit_identical_floats']}/{r['float_leaves']},cat={len(r['categorical'])}")
        print(" ".join(line), flush=True)
