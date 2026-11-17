"""Explicitly labelled scheduling simulation from local collection + old timings.

It does NOT prove runtime or coverage. Historical timings from different commits
are scenario inputs, not current-main measurements. Unknown modules retain
explicit node-count proxies; no claim of a 30/40-minute execution is made.
"""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--collection", required=True)
    p.add_argument("--weights", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    collection = json.loads(Path(a.collection).read_text())
    weights = json.loads(Path(a.weights).read_text())["modules"]
    counts = Counter(n.split("::")[0] for n in collection["collected"])
    historical = {
        "tests/test_ci_v3_reference_admission_successor.py": 13121.6,
        "tests/test_wf03_lifecycle_scope.py": 4809.1,
        "tests/test_trust_readiness_registry.py": 4278.7,
        "tests/test_u1_scope.py": 2315.8,
        "tests/test_ci_v3_outcome_reconciliation.py": 312.3,
    }
    rows = []
    for workers in (8, 10, 12):
        measured = {m: historical.get(m, weights.get(m, counts[m])) for m in counts}
        loads = [0.] * workers
        for module in sorted(counts, key=lambda m: (-measured[m], m)):
            slot = min(range(workers), key=lambda i: (loads[i], i))
            weight = measured[module]
            origin = "historical_different_head" if module in historical else "frozen_stale_weights" if module in weights else "UNMEASURED_node_count_seconds_proxy"
            rows.append({"scenario": "historical_whole_module_LPT_NOT_A_FORECAST", "workers": workers,
                "module": module, "nodes_local_collection": counts[module], "worker": slot,
                "scenario_weight_s": weight, "weight_source": origin})
            loads[slot] += weight
        print(json.dumps({"workers": workers, "simulation_only": True, "loads_s": loads,
            "minimum_module_critical_path_s": max(historical.values()), "real_overhead_s": None,
            "within_40_min_proven": False}))
    with Path(a.output).open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n");writer.writeheader();writer.writerows(rows)


if __name__ == "__main__": main()
