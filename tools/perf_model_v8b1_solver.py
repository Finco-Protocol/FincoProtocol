"""Performance V8-B1: paired, cold-process measurement of the Senior Debt solver (non-production tooling).

Usage::

    python tools/perf_model_v8b1_solver.py --baseline <tree-dir> --candidate <tree-dir> [--samples 5] [--json out.json]

Each sample is a FRESH Python process (cold module state, cleared policy run cache) that executes one genuine production
``run_clean_production`` per vertical. Trees are alternated sample by sample so machine drift hits both equally. A separate
instrumented pass (wrappers installed only there, never in the timed pass) counts solver operations. The complete Run result is
canonicalised (floats by ``repr``) and hashed; the exit status is 0 only when every digest is identical.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

KINDS = ("solar", "wind")

_CHILD = r'''
import dataclasses, hashlib, json, math, sys, time
from datetime import date
from enum import Enum

def canon(o):
    if isinstance(o, Enum):
        return ["enum", type(o).__name__, canon(o.value)]
    if isinstance(o, float):
        return ["f", repr(o)] if math.isfinite(o) else ["f", str(o)]
    if isinstance(o, (bool, int, str, type(None))):
        return o
    if isinstance(o, date):
        return ["d", o.isoformat()]
    if isinstance(o, (list, tuple)):
        return [canon(v) for v in o]
    if isinstance(o, dict):
        return [["k", canon(k), canon(v)] for k, v in sorted(o.items(), key=lambda kv: repr(kv[0]))]
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return canon(dataclasses.asdict(o))
    return ["r", repr(o)]

mode, kind = sys.argv[1], sys.argv[2]
from app import project_factories as pf
from app.services import production_financial_authority as authority
from financial_engine.senior_debt import solver

counts = {}
if mode == "count":
    def wrap(name):
        original = getattr(solver, name)
        def inner(*a, **k):
            counts[name] = counts.get(name, 0) + 1
            return original(*a, **k)
        setattr(solver, name, inner)
    for name in ("_compute_max_abs_diff", "_schedules_converged", "_finalise_authoritative", "_solve_dscr",
                 "_backward_dscr_capacity", "_forward_roll_numeric", "_forward_roll", "solve_senior_debt"):
        wrap(name)
    original_solve = solver.solve_senior_debt
    def counted_solve(*, policy, inputs, periods, tax_cfads_fn):
        def cb(interest):
            counts["tax_callbacks"] = counts.get("tax_callbacks", 0) + 1
            return tax_cfads_fn(interest)
        return original_solve(policy=policy, inputs=inputs, periods=periods, tax_cfads_fn=cb)
    solver.solve_senior_debt = counted_solve
    # the orchestrator imports solve_senior_debt at call time from the module, so the wrapper above is the one it receives

pi = getattr(pf, "create_generic_" + kind + "_reference")()
authority._POLICY_RUN_CACHE.clear()
start = time.perf_counter()
result = authority.run_clean_production(pi)
elapsed = time.perf_counter() - start
tree = canon(dataclasses.asdict(result))
print(json.dumps({"kind": kind, "seconds": elapsed, "counts": counts,
                  "sha256": hashlib.sha256(json.dumps(tree, separators=(",", ":")).encode()).hexdigest()}))
'''


def _sample(tree: Path, mode: str, kind: str, script: str) -> dict:
    out = subprocess.run([sys.executable, script, mode, kind], cwd=tree, check=True, capture_output=True, text=True,
                         env={**__import__("os").environ, "PYTHONPATH": str(tree)}).stdout.strip().splitlines()[-1]
    return json.loads(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--json")
    args = parser.parse_args(argv)
    trees = {"baseline": Path(args.baseline).resolve(), "candidate": Path(args.candidate).resolve()}
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(_CHILD)
        script = handle.name
    report: dict = {"samples": args.samples, "verticals": {}}
    identical = True
    for kind in KINDS:
        timed = {name: [] for name in trees}
        digests = {name: set() for name in trees}
        for _ in range(args.samples):
            for name, tree in trees.items():                       # alternate A/B inside every round
                row = _sample(tree, "time", kind, script)
                timed[name].append(row["seconds"])
                digests[name].add(row["sha256"])
        counted = {name: _sample(tree, "count", kind, script) for name, tree in trees.items()}
        same = len(digests["baseline"]) == 1 and digests["baseline"] == digests["candidate"] and \
            counted["baseline"]["sha256"] == counted["candidate"]["sha256"] == next(iter(digests["baseline"]))
        identical &= same
        med = {name: statistics.median(values) for name, values in timed.items()}
        report["verticals"][kind] = {
            "median_seconds": med, "samples_seconds": timed,
            "improvement_pct": round(100.0 * (med["baseline"] - med["candidate"]) / med["baseline"], 2),
            "operation_counts": {name: counted[name]["counts"] for name in trees},
            "result_sha256": {name: sorted(digests[name]) for name in trees}, "bit_identical": same,
        }
    report["all_results_bit_identical"] = identical
    text = json.dumps(report, indent=2)
    print(text)
    if args.json:
        Path(args.json).write_text(text + "\n", encoding="utf-8")
    return 0 if identical else 1


if __name__ == "__main__":
    raise SystemExit(main())
