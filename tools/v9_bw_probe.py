"""Test-only BW seed-invariance probe; never a production warm-start path."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.services import production_financial_authority as pfa
    from financial_engine.orchestrator import _run_senior_debt_model_with_shl
    from financial_engine.run_scope import engine_run_scope
    from tools.v9_joint_acceptance import cases, flatten
    report = {"bw_activated": False, "production_seed_argument_added": False, "cases": {}}
    for name in ("S50", "W25"):
        captures = []

        def capture(frame, event, result):
            if event == "return" and frame.f_code.co_name == "_run_senior_debt_model_with_shl" and result is not None:
                captures.append((frame.f_locals["inputs"], result))

        factory, vertical, _ = cases()[name]
        pfa._POLICY_RUN_CACHE.clear()
        sys.setprofile(capture)
        try:
            pfa.run_clean_production(factory(), project_type=vertical)
        finally:
            sys.setprofile(None)
        inputs, original = captures[-1]
        shl = original.shareholder_loan
        guess = dict(zip(shl.period_indices, shl.shl_gross_interest_keur, strict=True))
        with engine_run_scope():
            cold = _run_senior_debt_model_with_shl(inputs)
        with engine_run_scope():
            warm = _run_senior_debt_model_with_shl(inputs, _test_only_initial_shl_interest_guess=guess)
        a, b = flatten(cold), flatten(warm)
        changed = [path for path in sorted(set(a) | set(b)) if a.get(path) != b.get(path)]
        report["cases"][name] = {"bit_identical": not changed, "changed_leaves": len(changed),
                                 "changes": [{"path": key, "cold": a.get(key), "warm": b.get(key)} for key in changed]}
        print(name, "changed_leaves", len(changed), flush=True)
    report["decision"] = "BW_EXCLUDED: no approved seed-invariance or changed-representative authority; no exception-order proof"
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
