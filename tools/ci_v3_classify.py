"""Turn current collection and standalone-module evidence into a proposed (never self-approved) isolation policy.

A module is `runner-private` only when it passed alone in a fresh private no-network copy with exactly its
collected node count and no skip. Anything else is `blocked` and stops admission; nothing is dropped."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from tools.ci_v3_schema import ContractError, read_json, require, seal, write_json


def load_probe(*directories, reruns=()):
    results = {}
    for directory in directories:
        for line in (Path(directory) / "results.jsonl").read_text().splitlines():
            item = json.loads(line)
            require(item["module"] not in results, "duplicate standalone result: " + item["module"])
            results[item["module"]] = item
    for directory in reruns:  # uncontended re-execution evidence; the first attempt stays recorded
        for line in (Path(directory) / "results.jsonl").read_text().splitlines():
            item = json.loads(line)
            require(item["module"] in results, "rerun of unknown module: " + item["module"])
            results[item["module"]] = {**item, "first_attempt": results[item["module"]]}
    return results


def nonpass_proposal(junit_files, nodeids):
    """Observed standalone skip/xfail records keyed by exact original node id (proposal; owners approve)."""
    modules = {n.split("::", 1)[0] for n in nodeids}; known = set(nodeids)
    proposal, unmatched = {}, []
    for file in sorted(junit_files):
        for case in ET.parse(file).getroot().iter("testcase"):
            node = case.find("skipped")
            if node is None:
                continue
            parts = case.get("classname", "").split(".")
            for cut in range(len(parts), 0, -1):
                module = "/".join(parts[:cut]) + ".py"
                if module in modules:
                    nodeid = "::".join([module, *parts[cut:], case.get("name")])
                    break
            else:
                nodeid = None
            reason = node.get("message") or "no reason recorded"
            if nodeid in known:
                proposal[nodeid] = {"status": "xfail" if node.get("type") == "pytest.xfail" else "skipped", "reason": reason}
            else:
                unmatched.append({"classname": case.get("classname"), "name": case.get("name"), "reason": reason})
    return proposal, unmatched


def classify(prepared, probe, skipped_modules=frozenset()):
    inventory, isolation = prepared["inventory"], prepared["isolation"]
    expected = Counter(n["module"] for n in inventory["nodes"])
    modules, summary = {}, Counter()
    for name, base in isolation["modules"].items():
        record = dict(base)
        if name in skipped_modules:
            record.update(mode="blocked", category="collection-skipped",
                          reason="whole module skipped at collection (missing optional runtime); covered only if the control skips it identically")
        elif name not in expected:
            record.update(mode="blocked", category="not-collected-helper", reason="no collected nodes; helper or collection-skipped file")
        else:
            result = probe.get(name)
            if result is None:
                record.update(mode="blocked", category="no-standalone-evidence", reason="module was not executed alone")
            elif result["exit_code"] != 0 or result["timed_out"] or result["failures"] or result["errors"]:
                record.update(mode="blocked", category="standalone-failure",
                              reason=f"alone: exit={result['exit_code']} failures={result['failures']} errors={result['errors']} timed_out={result['timed_out']}")
            elif result["skipped"] and result["tests"] == expected[name]:
                record.update(mode="blocked", category="nonpass-approval-required",
                              reason=f"passed alone with {result['skipped']} runtime skip/xfail record(s); owner must approve exact nonpass policy")
            elif result["tests"] != expected[name]:
                record.update(mode="blocked", category="coverage-mismatch",
                              reason=f"alone: tests={result['tests']} skipped={result['skipped']} expected={expected[name]}")
            else:
                first = result.get("first_attempt")
                record.update(mode="runner-private", category="load-sensitive-pass" if first else "standalone-pass",
                              reason=f"passed alone in a fresh private no-network copy: {result['tests']} nodes in {result['seconds']}s"
                                     + (f"; first attempt under 4-way load failed (exit {first['exit_code']})" if first else ""))
        record["rationale"] = record["reason"]
        record["reviewed"] = False  # owner review is the only approval
        record["standalone"] = probe.get(name)
        modules[name] = record
        summary[record["category"]] += 1
    proposal = seal({**{k: v for k, v in isolation.items() if k not in ("digest", "modules")},
                     "modules": modules, "authority": "evidence-proposal-unreviewed"})
    return proposal, {"modules": len(modules), "categories": dict(summary),
                      "unresolved_blocking_admission": sum(c for k, c in summary.items() if k not in ("standalone-pass", "load-sensitive-pass", "not-collected-helper", "collection-skipped")),
                      "collected_modules_without_pass": sorted(n for n, r in modules.items() if n in expected and r["mode"] != "runner-private")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", required=True); parser.add_argument("--probe", required=True, nargs="+"); parser.add_argument("--rerun", nargs="*", default=[]); parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    prepared = {k: read_json(Path(args.prepared) / (k + ".json")) for k in ("inventory", "isolation", "collection")}
    skipped = {r["nodeid"] for r in prepared["collection"]["skips"]}
    try:
        proposal, summary = classify(prepared, load_probe(*args.probe, reruns=args.rerun), skipped)
    except ContractError as exc:
        print("CI_V3_CLASSIFY_REJECTED: " + str(exc)); return 1
    out = Path(args.output); out.mkdir(parents=True, exist_ok=False)
    junit = [f for d in args.probe for f in Path(d).glob("*.xml")]
    allowed, unmatched = nonpass_proposal(junit, [n["nodeid"] for n in prepared["inventory"]["nodes"]])
    write_json(out / "allowed-nonpass-proposal.json", {"authority": "evidence-proposal-unreviewed", "records": allowed, "unmatched": unmatched})
    summary["collection_skipped_modules"] = sorted(skipped)
    summary["observed_runtime_nonpass"] = len(allowed); summary["unmatched_nonpass"] = len(unmatched)
    write_json(out / "isolation-proposal.json", proposal); write_json(out / "summary.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "collected_modules_without_pass"})); return 0


if __name__ == "__main__":
    raise SystemExit(main())
