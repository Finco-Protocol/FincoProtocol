"""Offline whole-module LPT planner. Inert unless called; never runs or selects pytest."""
from __future__ import annotations

import argparse
from collections import Counter
import sys

from tools.ci_v3_schema import (
    ContractError, DOMAINS, SCHEMA, check_seal, integer, read_json, require,
    seal, validate_inventory, validate_plan, validate_policy, write_json,
)


def plan_partitions(inventory, policy, weights, workers=3, groups=None):
    validate_inventory(inventory)
    validate_policy(policy, inventory)
    check_seal(weights, "ci-v3-weights")
    require(weights.get("inventory_digest") == inventory["digest"], "weight inventory mismatch")
    require(weights.get("source") == inventory["source"], "weight source mismatch")
    measured = weights.get("modules_ms")
    require(isinstance(measured, dict) and set(measured) == set(inventory["modules"]),
            "missing/foreign module weights; no implicit default")
    for value in measured.values():
        integer(value, "module milliseconds")
    require(type(workers) is int and workers in (2, 3, 4), "only 2/3/4 workers supported")
    names = ["worker-%d" % i for i in range(workers)]
    loads = dict.fromkeys(names, 0)
    assigned = {}
    # Groups arrive from independently reviewed isolation decisions at the hosted
    # boundary. Never move modules after scheduling: schedule indivisible units.
    units, grouped = [], set()
    require(groups is None or isinstance(groups, dict), "invalid colocation groups")
    for group, members in sorted((groups or {}).items()):
        require(isinstance(group, str) and group and isinstance(members, list) and members
                and all(isinstance(m, str) for m in members), "invalid colocation group")
        require(len(members) == len(set(members)) and set(members) <= set(measured)
                and not grouped.intersection(members), "overlapping/missing/foreign group modules")
        grouped.update(members); units.append(tuple(sorted(members)))
    units += [(m,) for m in measured if m not in grouped]
    # Integer milliseconds, lexical unit membership and worker index fix ties.
    for unit in sorted(units, key=lambda u: (-sum(measured[m] for m in u), u)):
        slot = min(names, key=lambda w: (loads[w], names.index(w)))
        for module in unit:
            assigned[module] = slot
        loads[slot] += sum(measured[m] for m in unit)
    plan = seal({"schema": SCHEMA, "kind": "ci-v3-plan", "authority": "offline-prototype",
                 "source": inventory["source"], "inventory_digest": inventory["digest"],
                 "policy_digest": policy["digest"], "weights_digest": weights["digest"],
                 "algorithm": "whole-module-group-lpt-integer-ms/path/worker-index-v2",
                 "worker_count": workers, "module_workers": assigned})
    validate_plan(plan, inventory, policy)
    return plan


def summarize_plan(inventory, policy, weights, plan, overhead_ms, source_ms, aggregate_ms):
    validate_inventory(inventory)
    validate_policy(policy, inventory)
    names = validate_plan(plan, inventory, policy)
    require(plan["weights_digest"] == weights["digest"], "weight digest mismatch")
    check_seal(weights, "ci-v3-weights")
    for label, value in (("overhead", overhead_ms), ("source", source_ms), ("aggregate", aggregate_ms)):
        integer(value, label)
    records = {w: {"worker": w, "modules": [], "nodes": 0, "weight_ms": 0,
                   "domains": dict.fromkeys(DOMAINS, 0)} for w in names}
    for module, owner in sorted(plan["module_workers"].items()):
        for w in [owner, *policy["module_overlaps"].get(module, [])]:
            records[w]["modules"].append(module)
            records[w]["weight_ms"] += weights["modules_ms"][module]
    for node in inventory["nodes"]:
        for w in [plan["module_workers"][node["module"]], *policy["module_overlaps"].get(node["module"], [])]:
            records[w]["nodes"] += 1
            records[w]["domains"][node["domain"]] += 1
    values = [r["weight_ms"] for r in records.values()]
    maximum, total = max(values), sum(values)
    mean = total / len(values)
    return {"plan_digest": plan["digest"], "prediction_only": True, "workers": list(records.values()),
            "maximum_ms": maximum, "mean_ms": mean,
            "imbalance_fraction": maximum / mean - 1 if mean else 0,
            "per_worker_overhead_ms": overhead_ms, "source_job_ms": source_ms,
            "aggregate_job_ms": aggregate_ms,
            "critical_path_ms": max(maximum + overhead_ms, source_ms) + aggregate_ms,
            "runner_ms": total + len(values) * overhead_ms + source_ms + aggregate_ms,
            "domain_counts_are_unreviewed_candidates": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--weights", required=True)
    parser.add_argument("--workers", type=int, choices=(2, 3, 4), default=3)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        value = plan_partitions(read_json(args.inventory), read_json(args.policy),
                                read_json(args.weights), args.workers)
        write_json(args.output, value)
    except (ContractError, KeyError, TypeError, ValueError) as exc:
        print("CI_V3_OFFLINE_PLAN_REJECTED: " + str(exc), file=sys.stderr)
        return 1
    print("CI_V3_OFFLINE_PLAN_ONLY " + value["digest"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
