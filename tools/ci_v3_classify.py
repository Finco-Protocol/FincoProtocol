"""Turn current collection and standalone-module evidence into a proposed (never self-approved) isolation policy.

A module is `runner-private` only when it passed alone in a fresh private no-network copy with exactly its
collected node count and no skip. Anything else is `blocked` and stops admission; nothing is dropped."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from tools.ci_v3_schema import ContractError, read_json, require, seal, write_json


def load_probe(*directories):
    results = {}
    for directory in directories:
        for line in (Path(directory) / "results.jsonl").read_text().splitlines():
            item = json.loads(line)
            require(item["module"] not in results, "duplicate standalone result: " + item["module"])
            results[item["module"]] = item
    return results


def classify(prepared, probe):
    inventory, isolation = prepared["inventory"], prepared["isolation"]
    expected = Counter(n["module"] for n in inventory["nodes"])
    modules, summary = {}, Counter()
    for name, base in isolation["modules"].items():
        record = dict(base)
        if name not in expected:
            record.update(mode="blocked", category="not-collected-helper", reason="no collected nodes; helper or collection-skipped file")
        else:
            result = probe.get(name)
            if result is None:
                record.update(mode="blocked", category="no-standalone-evidence", reason="module was not executed alone")
            elif result["exit_code"] != 0 or result["timed_out"] or result["failures"] or result["errors"]:
                record.update(mode="blocked", category="standalone-failure",
                              reason=f"alone: exit={result['exit_code']} failures={result['failures']} errors={result['errors']} timed_out={result['timed_out']}")
            elif result["skipped"] or result["tests"] != expected[name]:
                record.update(mode="blocked", category="coverage-mismatch",
                              reason=f"alone: tests={result['tests']} skipped={result['skipped']} expected={expected[name]}")
            else:
                record.update(mode="runner-private", category="standalone-pass",
                              reason=f"passed alone in a fresh private no-network copy: {result['tests']} nodes in {result['seconds']}s")
        record["rationale"] = record["reason"]
        record["reviewed"] = False  # owner review is the only approval
        record["standalone"] = probe.get(name)
        modules[name] = record
        summary[record["category"]] += 1
    proposal = seal({**{k: v for k, v in isolation.items() if k not in ("digest", "modules")},
                     "modules": modules, "authority": "evidence-proposal-unreviewed"})
    return proposal, {"modules": len(modules), "categories": dict(summary),
                      "unresolved_blocking_admission": sum(c for k, c in summary.items() if k not in ("standalone-pass", "not-collected-helper")),
                      "collected_modules_without_pass": sorted(n for n, r in modules.items() if n in expected and r["mode"] != "runner-private")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", required=True); parser.add_argument("--probe", required=True, nargs="+"); parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    prepared = {k: read_json(Path(args.prepared) / (k + ".json")) for k in ("inventory", "isolation")}
    try:
        proposal, summary = classify(prepared, load_probe(*args.probe))
    except ContractError as exc:
        print("CI_V3_CLASSIFY_REJECTED: " + str(exc)); return 1
    out = Path(args.output); out.mkdir(parents=True, exist_ok=False)
    write_json(out / "isolation-proposal.json", proposal); write_json(out / "summary.json", summary)
    print(json.dumps(summary)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
