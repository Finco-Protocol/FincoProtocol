"""CI V4 central bounded governance gate: ONE pass on every PR (Fast and RISK).

Replaces re-running the historical exactness/governance test corpus on each PR (that corpus stays in FULL: nightly + release gate).
Checks, at the tested checkout: every registered exact-source cohort is exact, the composite registry is valid, and the mutation-security
inventory has no violation and its successor holds. Any exception or False fails closed. Writes a JSON record.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def run():
    started = time.monotonic()
    from tests import fin_v2_cohorts as C
    from tests import model_mutation_security_successor as S
    cohorts = {m.__name__: bool(m.exact_blobs_ok()) for m in C.cohorts()}
    registered = list(C.COHORT_MODULES)
    composite = bool(C.valid())
    sources = {p: (S.ROOT / p).read_text(encoding="utf-8") for p in S.BLOBS}
    violations = S.violations(sources)
    successor = bool(S.current_mutation_successor_valid())
    ok = (bool(cohorts) and all(cohorts.values()) and set(cohorts) == set(registered) and composite and not violations and successor)
    return {"schema": "FINCO_CI_V4_GOVERNANCE_GATE_V1", "verdict": "PASS" if ok else "FAIL", "cohorts": cohorts,
            "registered": registered, "composite_valid": composite, "mutation_violations": violations,
            "mutation_successor_valid": successor, "elapsed_s": round(time.monotonic() - started, 1)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    a = ap.parse_args(argv)
    try:
        rec = run()
    except Exception as exc:  # fail closed on any error
        rec = {"schema": "FINCO_CI_V4_GOVERNANCE_GATE_V1", "verdict": "FAIL", "error": "%s: %s" % (type(exc).__name__, exc)}
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(rec, indent=2, sort_keys=True))
    bad = [k for k, v in rec.get("cohorts", {}).items() if not v]
    print("CI V4 governance gate %s (not exact: %s, composite=%s, violations=%d)" % (
        rec["verdict"], bad, rec.get("composite_valid"), len(rec.get("mutation_violations", []))))
    return 0 if rec["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
