"""Exact-source duration weights with explicit deterministic planning fallbacks.

Weights are scheduling estimates, never execution/isolation evidence or approval.
Historical measurements remain identified but cannot become current measurements.
"""
from __future__ import annotations

import argparse
from collections import Counter
from statistics import median_low

from tools.ci_v3_schema import check_seal, integer, read_json, require, seal, validate_inventory, write_json


def build_weights(inventory, environment_digest, measurements=(), fallback_node_ms=1000):
    validate_inventory(inventory)
    integer(fallback_node_ms, "fallback node milliseconds")
    require(fallback_node_ms > 0, "fallback must be positive")
    require(isinstance(environment_digest, str) and len(environment_digest) == 64
            and all(c in "0123456789abcdef" for c in environment_digest), "invalid weight environment digest")
    counts = Counter(n["module"] for n in inventory["nodes"])
    samples = {m: [] for m in counts}; excluded = []
    seen = set()
    for record in measurements:
        check_seal(record, "ci-v3-duration-measurements")
        require(record["digest"] not in seen, "duplicate measurement document")
        seen.add(record["digest"])
        require(record.get("reference"), "measurement lacks original evidence reference")
        if (record.get("source") != inventory["source"]
                or record.get("inventory_digest") != inventory["digest"]
                or record.get("environment_digest") != environment_digest):
            excluded.append({"digest": record["digest"], "reason": "source/inventory/environment mismatch"})
            continue
        values = record.get("modules_ms")
        require(isinstance(values, dict) and set(values) <= set(counts), "foreign measurement modules")
        for module, value in values.items():
            integer(value, "measured module milliseconds")
            samples[module].append((value, record["digest"]))
    values, provenance = {}, {}
    for module in sorted(counts):
        current = samples[module]
        values[module] = median_low(sorted(v for v, _ in current)) if current else counts[module] * fallback_node_ms
        provenance[module] = {"basis": "measured" if current else "node-count-fallback",
                              "measurement_digests": sorted(d for _, d in current)}
    return seal({"schema": 1, "kind": "ci-v3-weights", "source": inventory["source"],
        "inventory_digest": inventory["digest"], "environment_digest": environment_digest,
        "measurement": "Exact-bound measured durations where available; EXPLICIT NODE-COUNT PROXY ONLY otherwise. No admission authority.",
        "fallback_node_ms": fallback_node_ms, "excluded_measurements": sorted(excluded, key=lambda r: r["digest"]),
        "provenance": provenance, "modules_ms": values})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("inventory", "environment-digest", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--measurements", nargs="*", default=[])
    args = parser.parse_args(argv)
    write_json(args.output, build_weights(read_json(args.inventory), args.environment_digest,
        [read_json(p) for p in args.measurements]))


if __name__ == "__main__":
    main()
