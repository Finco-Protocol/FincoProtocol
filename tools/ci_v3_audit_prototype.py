"""Reproduce the historical Audit V3 offline prototype; never execute audited tests.

Generated inventories contain historical parameter strings and runner paths. Keep
these research artifacts outside the repository; do not publish them as policy.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

from tools.ci_v3_partition_plan import plan_partitions, summarize_plan
from tools.ci_v3_schema import (
    EVALUATOR, SCHEMA, canonical_bytes, digest, read_json, require, seal, skip_key, write_json,
)

CATEGORIES = {"A": "Model", "B": "Radar", "C": "Shared", "D": "Cross-domain", "E": "Governance", "F": "F"}
RUNS = ("39510669730", "39547632809", "39554954313")


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def junit_locator(node):
    module, rest = node.split("::", 1)
    stem, separator, parameters = rest.partition("[")
    klass, split, function = stem.rpartition("::")
    classname = module[:-3].replace("/", ".") + ("." + klass.replace("::", ".") if split else "")
    return classname, (function if split else stem) + ("[" + parameters if separator else "")


def read_historical(root, run):
    folder = root / "evidence" / run / "public-verification-results"
    inv, proc = read_json(folder / "inventory.json"), read_json(folder / "process.json")
    collected = inv["collected"]
    require(len(collected) == 15440 and len(set(collected)) == 15440, "historical node identity/multiplicity drift")
    require(inv["selected"] == collected and not inv["deselected"] and not inv["collection_errors"], "historical collection error")
    require(len(inv["collection_skips"]) == 68 and set(inv["outcomes"]) == set(collected), "historical skip/outcome drift")
    require((inv["head"], inv["tree"]) == (proc["head"], proc["tree"]), "historical process source mismatch")
    require(file_digest(folder / "results.xml") == proc["junit_sha256"], "historical JUnit checksum mismatch")
    locators = defaultdict(list)
    for node in collected:
        locators[junit_locator(node)].append(node)
    require(all(len(v) == 1 for v in locators.values()), "ambiguous historical JUnit identity")
    seen, skipped_modules = Counter(), Counter()
    for case in ET.parse(folder / "results.xml").getroot().iter("testcase"):
        locator = case.get("classname"), case.get("name")
        if locator in locators:
            node = locators[locator][0]
            seen[node] += 1
            status = "failed" if case.find("failure") is not None or case.find("error") is not None else (
                "skipped" if case.find("skipped") is not None else "passed")
            require(status == inv["outcomes"][node]["status"], "historical JUnit outcome mismatch")
        else:
            require(locator[0] == "" and case.find("skipped") is not None, "foreign historical JUnit case")
            skipped_modules[locator[1]] += 1
    require(seen == Counter(collected), "historical JUnit multiset mismatch")
    require(skipped_modules == Counter(n[:-3].replace("/", ".") for n, _ in inv["collection_skips"]),
            "historical collection-skip JUnit mismatch")
    timing = []
    for line in (folder / "progress/tests.jsonl").read_text(encoding="utf-8").splitlines():
        timing.append(json.loads(line))
    require(Counter(t["n"] for t in timing) == Counter(collected), "historical timing multiset mismatch")
    modules = defaultdict(int)
    for item in timing:
        milliseconds = 0
        for field in ("s", "c", "t"):
            # Setup-skipped nodes have no call report; absent phase means zero.
            value = Decimal(str(item.get(field, 0))) * 1000
            require(value.is_finite() and value >= 0 and value == value.to_integral_value(), "invalid measured duration")
            milliseconds += int(value)
        modules[item["n"].split("::", 1)[0]] += milliseconds
    outcomes = Counter(o["status"] for o in inv["outcomes"].values())
    successful = inv["pytest_exit"] == proc["exit_code"] == 0 and proc["normal_exit"] is True
    require(successful == (outcomes.get("failed", 0) == 0), "historical success provenance mismatch")
    jobs = read_json(root / "evidence" / ("jobs-" + run + ".json"))["jobs"]
    from datetime import datetime
    def elapsed(j):
        a, b = (datetime.fromisoformat(j[k].replace("Z", "+00:00")) for k in ("started_at", "completed_at"))
        return int((b - a).total_seconds() * 1000)
    durations = {j["name"]: elapsed(j) for j in jobs}
    return inv, dict(modules), {"run_id": run, "source": {"head": inv["head"], "tree": inv["tree"]},
        "successful_acceptance_evidence": successful, "outcomes": dict(outcomes), "nodes": len(collected),
        "modules": len(modules), "collection_skips": len(inv["collection_skips"]),
        "inventory_sha256": file_digest(folder / "inventory.json"), "junit_sha256": proc["junit_sha256"],
        "timing_sha256": file_digest(folder / "progress/tests.jsonl"), "module_weight_ms": sum(modules.values()),
        "process": proc, "job_ms": durations,
        "overhead_ms": durations["safety-and-smoke / tests"] - sum(modules.values())}


def write_simulated_workers(inventory, policy, plan, output, run_id):
    """Data-only mock package. Process markers here are fabricated, explicitly labeled.

    This is NOT an execution adapter, scheduler or GitHub producer.
    """
    context = {"repository": inventory["repository"], "pr_number": None,
        "workflow": "offline/ci-v3-simulation", "run_id": "simulated-" + run_id,
        "attempt": 1, "mode": "simulated", "evaluator": EVALUATOR,
        "source": inventory["source"], "environment_digest": digest({"simulation": "no-tests-executed"}),
        "inventory_digest": inventory["digest"], "policy_digest": policy["digest"], "plan_digest": plan["digest"],
        "merge_proof": {"mode": "main-head", "merge_sha": None, "merge_tree": None}}
    collection = {"source": inventory["source"], "complete": True, "errors": [],
                  "nodes": [n["nodeid"] for n in inventory["nodes"]], "skips": inventory["collection_skips"]}
    write_json(output / "collection.json", collection)
    write_json(output / "trust.json", {"schema": SCHEMA, "kind": "ci-v3-trust-input", "context": context})
    for number in range(plan["worker_count"]):
        worker = "worker-%d" % number
        records = []
        for node in inventory["nodes"]:
            if worker in [plan["module_workers"][node["module"]], *policy["module_overlaps"].get(node["module"], [])]:
                outcome = policy["allowed_nonpass"].get(node["nodeid"], {"status": "passed", "reason": ""})
                records.append({"nodeid": node["nodeid"], **outcome})
        skip_count = sum(r["status"] != "passed" for r in records) + len(collection["skips"])
        suite = ET.Element("testsuite", {"tests": str(len(records) + len(collection["skips"])),
                                        "failures": "0", "errors": "0", "skipped": str(skip_count)})
        def case(kind, identity, status, reason):
            element = ET.SubElement(suite, "testcase", {"name": "identity-in-properties"})
            props = ET.SubElement(element, "properties")
            ET.SubElement(props, "property", {"name": "ci_v3_identity", "value": json.dumps([kind, identity], ensure_ascii=True)})
            if status != "passed":
                ET.SubElement(props, "property", {"name": "ci_v3_reason", "value": json.dumps(reason, ensure_ascii=True)})
                ET.SubElement(element, "skipped", {"type": "pytest.xfail" if status == "xfail" else "pytest.skip"})
        for rec in records:
            case("node", rec["nodeid"], rec["status"], rec["reason"])
        for skip in collection["skips"]:
            case("collection-skip", skip_key(skip), "skipped", skip["reason"])
        xml = ET.tostring(suite, encoding="utf-8", xml_declaration=True)
        directory = output / "workers" / worker
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "results.xml").write_bytes(xml)
        write_json(directory / "execution.json", seal({"schema": SCHEMA, "kind": "ci-v3-worker-evidence",
            "worker": worker, "context": context, "complete": True, "job_result": "success",
            "collection": collection, "executions": records, "junit_sha256": hashlib.sha256(xml).hexdigest(),
            "process": {"exit_code": 0, "pytest_return_code": 0, "child_exit_code": 0,
                        "normal_exit": True, "timed_out": False, "pytest_started_ms": 0,
                        "pytest_returned_ms": 100, "child_exited_ms": 101, "elapsed_ms": 102}}))


def build(audit, output):
    audit, output = Path(audit), Path(output)
    require(not output.exists(), "preserve existing output; use a new evidence directory")
    # Check every manifest-covered input, not just nominal counts.
    manifest = read_json(audit / "SHA256SUMS.json")
    for relative, expected in manifest.items():
        path = (audit / relative).resolve()
        require(path.is_relative_to(audit.resolve()) and file_digest(path) == expected, "audit input checksum mismatch")
    historical = {run: read_historical(audit, run) for run in RUNS}
    reference = Counter(historical[RUNS[0]][0]["collected"])
    require(all(Counter(v[0]["collected"]) == reference for v in historical.values()), "historical universes differ")
    old_limit = csv.field_size_limit(20_000_000)
    try:
        with (audit / "analysis/modules-ownership-candidates.csv").open(encoding="utf-8-sig", newline="") as f:
            ownership_rows = list(csv.DictReader(f))
    finally:
        csv.field_size_limit(old_limit)
    ownership = {r["module"]: r for r in ownership_rows}
    require(len(ownership_rows) == len(ownership) == 469, "ownership module multiset drift")
    require(sum(r["category"] == "F" for r in ownership_rows) == 394, "unresolved module baseline drift")
    require(sum(int(r["nodes"]) for r in ownership_rows if r["category"] == "F") == 11042, "unresolved node baseline drift")
    summary = {}
    for run, (old, measured, metadata) in historical.items():
        if not metadata["successful_acceptance_evidence"]:
            summary[run] = metadata  # Preserve failure; do not synthesize successful workers from it.
            continue
        target = output / run
        count_by_module = Counter(n.split("::", 1)[0] for n in old["collected"])
        require(set(count_by_module) == set(ownership), "ownership module identity mismatch")
        require(all(count_by_module[m] == int(ownership[m]["nodes"]) for m in ownership), "ownership node count drift")
        deps_digest = file_digest(audit / "analysis/dependency-closures.json")
        fixture_digest = file_digest(audit / "analysis/fixtures.json")
        nodes = []
        for node in sorted(old["collected"]):
            module = node.split("::", 1)[0]
            category = CATEGORIES[ownership[module]["category"]]
            obligations = ["full-regression"]
            obligations += {"Model": ["financial"], "Radar": ["market-domain"], "Shared": ["security", "shared-runtime"],
                "Cross-domain": ["financial", "security", "cross-domain"], "Governance": ["governance"],
                "F": ["financial-security-governance-scope-unresolved"]}[category]
            nodes.append({"nodeid": node, "module": module, "fixture_unit": module,
                "execution_owner": "plan.module_workers", "optional_overlap_ownership": "policy.module_overlaps",
                "domain": category, "confidence": "unresolved" if category == "F" else "candidate-static",
                "mandatory": True, "obligations": obligations, "dependency_evidence": "modules/" + module})
        inventory = seal({"schema": SCHEMA, "kind": "ci-v3-inventory", "authority": "offline-prototype",
            "repository": "Finco-Protocol/FincoProtocol", "source": metadata["source"], "baseline": metadata,
            "nodes": nodes, "collection_skips": [{"nodeid": n, "reason": reason} for n, reason in old["collection_skips"]],
            "modules": {m: {"isolation_review": "unproven", "candidate_reason": ownership[m]["reason"],
                "dependency_evidence": {"artifact_sha256": deps_digest, "module_key": m},
                "fixture_evidence_sha256": fixture_digest} for m in sorted(ownership)}})
        policy = seal({"schema": SCHEMA, "kind": "ci-v3-policy", "authority": "offline-prototype",
            "inventory_digest": inventory["digest"], "new_nodes": "fail-closed", "selective_execution": False,
            "module_overlaps": {}, "allowed_nonpass": {n: v for n, v in old["outcomes"].items() if v["status"] != "passed"}})
        weights = seal({"schema": SCHEMA, "kind": "ci-v3-weights", "source": metadata["source"],
            "inventory_digest": inventory["digest"], "measurement": {"run_id": run, "timing_sha256": metadata["timing_sha256"],
            "unit": "integer-milliseconds", "phases": ["setup", "call", "teardown"]}, "modules_ms": measured})
        write_json(target / "inventory.json", inventory)
        write_json(target / "policy.json", policy)
        write_json(target / "weights.json", weights)
        layouts = {}
        for size in (2, 3, 4):
            plan = plan_partitions(inventory, policy, weights, size)
            write_json(target / ("plan-%d.json" % size), plan)
            layouts[str(size)] = summarize_plan(inventory, policy, weights, plan, metadata["overhead_ms"],
                metadata["job_ms"]["source-safety"], metadata["job_ms"]["mandatory-evidence"])
            if size == 3:
                write_simulated_workers(inventory, policy, plan, target / "simulation", run)
        summary[run] = {**metadata, "layouts": layouts}
        with (target / "resolved-node-assignments.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["nodeid", "module", "domain", "worker_2", "worker_3", "worker_4"])
            assignments = {k: read_json(target / ("plan-%s.json" % k))["module_workers"] for k in (2, 3, 4)}
            for node in nodes:
                writer.writerow([node["nodeid"], node["module"], node["domain"], *[assignments[k][node["module"]] for k in (2, 3, 4)]])
    write_json(output / "historical-and-performance.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        result = build(args.audit, args.output)
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
        print("CI_V3_AUDIT_REJECTED: " + str(exc), file=sys.stderr)
        return 1
    print("CI_V3_HISTORICAL_OFFLINE_ONLY " + ",".join(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
