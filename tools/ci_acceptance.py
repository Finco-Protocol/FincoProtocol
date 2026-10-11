"""CI-only exact-tree attestation, process evidence and fail-closed shadow proof."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


class EvidenceError(ValueError):
    pass


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git_value(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def attest(expected):
    actual = git_value("rev-parse", "HEAD")
    if not expected or actual != expected:
        raise EvidenceError(f"Wrong tested SHA: expected {expected}, actual {actual}")
    return {"head": actual, "tree": git_value("rev-parse", "HEAD^{tree}")}


def partition_modules(nodes, weights):
    modules = set(node.split("::", 1)[0] for node in nodes)
    loads = [0.0, 0.0]
    result = {}
    for module in sorted(modules, key=lambda m: (-float(weights.get(m, 1.0)), m)):
        slot = min(range(2), key=lambda i: (loads[i], i))
        result[module] = slot
        loads[slot] += max(float(weights.get(module, 1.0)), 0.001)
    return result


def require_unique(nodes, label):
    duplicates = [key for key, count in Counter(nodes).items() if count != 1]
    if duplicates:
        raise EvidenceError(f"Duplicate node IDs in {label}: {duplicates[:5]}")


def check_record(record, head, tree):
    if record.get("head") != head or record.get("tree") != tree:
        raise EvidenceError("Wrong tested SHA/tree in artifact")
    if record.get("pytest_exit") != 0 or record.get("collection_errors"):
        raise EvidenceError("Failed pytest or collection errors")
    if not record.get("selected"):
        raise EvidenceError("Missing selected inventory")
    require_unique(record["collected"], "collection")
    require_unique(record["selected"], "selection")
    if set(record["outcomes"]) != set(record["selected"]):
        raise EvidenceError("Missing or unexpected test outcomes")
    if any(value["status"] not in ("passed", "skipped", "xfail", "xpass") for value in record["outcomes"].values()):
        raise EvidenceError("Failed test outcome")


def compare_records(control, shards, processes, head, tree, job_results):
    if job_results != ["success", "success", "success"]:
        raise EvidenceError(f"Failed/missing/cancelled job: {job_results}")
    if len(shards) != 2 or len(processes) != 3:
        raise EvidenceError("Missing shard or process artifact")
    records = [control, *shards]
    for record in records:
        check_record(record, head, tree)
    if control.get("shard") is not None or [s.get("shard") for s in shards] != [0, 1]:
        raise EvidenceError("Unexpected shard identity")
    if control.get("deselected"):
        raise EvidenceError("Control unexpectedly deselected tests")
    if control["selected"] != control["collected"]:
        raise EvidenceError("Control missing collected test IDs")
    for shard in shards:
        if shard["collected"] != control["collected"]:
            raise EvidenceError("Missing/changed full collection")
        if shard["collection_skips"] != control["collection_skips"]:
            raise EvidenceError("Unexpected collection skips")
        if set(shard["deselected"]) != set(control["collected"]) - set(shard["selected"]):
            raise EvidenceError("Unexpected shard deselection")
    union = [node for shard in shards for node in shard["selected"]]
    require_unique(union, "shard union")
    if set(union) != set(control["selected"]):
        raise EvidenceError("Missing shard node IDs")
    module_slots = {}
    for slot, shard in enumerate(shards):
        for node in shard["selected"]:
            module = node.split("::", 1)[0]
            if module in module_slots and module_slots[module] != slot:
                raise EvidenceError("Module fixture split between shards")
            module_slots[module] = slot
    outcomes = {node: value for shard in shards for node, value in shard["outcomes"].items()}
    if outcomes != control["outcomes"]:
        raise EvidenceError("Unexpected skip/xfail or changed test outcomes")
    for process in processes:
        if process.get("head") != head or process.get("tree") != tree:
            raise EvidenceError("Wrong process SHA/tree")
        if process.get("exit_code") != 0 or process.get("normal_exit") is not True:
            raise EvidenceError("Process failed/timed out/did not exit normally")
        if not process.get("junit_sha256") or process.get("junit_failures") != 0:
            raise EvidenceError("Missing or failing JUnit artifact")
    if len({p.get("environment_sha256") for p in processes}) != 1 or not processes[0].get("environment_sha256"):
        raise EvidenceError("Different dependency/OS/Python environments")
    return {"head": head, "tree": tree, "equivalent": True,
            "collected": len(control["collected"]), "selected": len(union),
            "collection_skips": control["collection_skips"],
            "outcomes": dict(Counter(v["status"] for v in outcomes.values())),
            "control_seconds": processes[0]["elapsed_seconds"],
            "shard_seconds": [p["elapsed_seconds"] for p in processes[1:]],
            "note": "Process timings exclude queue/setup/upload; use job timestamps for critical-path acceptance."}


def environment_digest():
    resolved = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
    payload = json.dumps([sys.version, sys.platform, sorted(resolved.splitlines())])
    return hashlib.sha256(payload.encode()).hexdigest()


def run_command(args):
    provenance = attest(args.expected)
    env = dict(os.environ, FINCO_CI_TESTED_SHA=provenance["head"], FINCO_CI_TESTED_TREE=provenance["tree"])
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        raise EvidenceError("Missing command")
    started = datetime.now(timezone.utc).isoformat()
    clock = time.monotonic()
    # Existing pytest supervisor remains the process/lifecycle authority.
    env["PYTHONIOENCODING"] = "utf-8"
    process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", bufsize=1)
    markers = {}
    log_path = Path(args.output).with_suffix(".log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    assert process.stdout is not None
    with log_path.open("w", encoding="utf-8") as log:
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log.write(line)
            elapsed = time.monotonic() - clock
            if "PYTEST_MAIN_STARTED" in line:
                markers["pytest_started_seconds"] = elapsed
            if "PYTEST_MAIN_RETURNED" in line:
                markers["pytest_returned_seconds"] = elapsed
                match = re.search(r"rc=(-?\d+)", line)
                markers["pytest_return_code"] = int(match.group(1)) if match else None
            if "PYTHON_PROCESS_EXITED FINCO_CI_SUPERVISOR child exit code" in line:
                markers["child_exit_seconds"] = elapsed
                markers["child_exit_code"] = int(line.rsplit(" ", 1)[1].strip())
    exit_code = process.wait()
    supervised = any("ci_pytest_runner.py" in part for part in command)
    normal = exit_code == 0 and (not supervised or (markers.get("pytest_return_code") == 0 and markers.get("child_exit_code") == 0))
    value = {**provenance, "label": args.label, "started_at": started,
             "completed_at": datetime.now(timezone.utc).isoformat(),
             "elapsed_seconds": time.monotonic() - clock,
             "command": command, "exit_code": exit_code,
             "normal_exit": normal, "process_markers": markers,
             "environment_sha256": environment_digest()}
    if args.junit:
        path = Path(args.junit)
        if path.is_file():
            root = ET.parse(path).getroot()
            value["junit_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            value["junit_failures"] = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in root.iter("testsuite"))
        else:
            value["junit_failures"] = None
    write_json(args.output, value)
    if args.junit and not value.get("junit_sha256"):
        return exit_code or 1
    return exit_code if normal else (exit_code or 1)


def weights_from_junit(path, source):
    modules = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        classname = case.get("classname", "")
        parts = classname.split(".")
        if len(parts) > 1 and parts[0] == "tests":
            module = "/".join(parts[:2]) + ".py"
            modules[module] = modules.get(module, 0.0) + float(case.get("time", 0))
    if not modules:
        raise EvidenceError("No module timings in source JUnit")
    return {"source": source, "junit_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(), "modules": modules}


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    capture = sub.add_parser("attest")
    capture.add_argument("--expected", required=True)
    capture.add_argument("--output", required=True)
    run = sub.add_parser("run")
    run.add_argument("--expected", required=True)
    run.add_argument("--label", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--junit")
    run.add_argument("command", nargs=argparse.REMAINDER)
    weights = sub.add_parser("weights")
    weights.add_argument("--junit", required=True)
    weights.add_argument("--source", required=True)
    weights.add_argument("--output", required=True)
    compare = sub.add_parser("compare")
    compare.add_argument("--expected", required=True)
    compare.add_argument("--artifacts", required=True)
    compare.add_argument("--output", required=True)
    compare.add_argument("--control-result", required=True)
    compare.add_argument("--shard-result", required=True)
    args = parser.parse_args()
    if args.action == "attest":
        write_json(args.output, attest(args.expected))
    elif args.action == "weights":
        write_json(args.output, weights_from_junit(args.junit, args.source))
    elif args.action == "run":
        return run_command(args)
    else:
        proof = attest(args.expected)
        root = Path(args.artifacts)
        for stage in ("scan", "compile"):
            stage_record = json.loads((root / "public-source-safety" / f"{stage}.json").read_text(encoding="utf-8"))
            if (stage_record.get("head"), stage_record.get("tree")) != (proof["head"], proof["tree"]):
                raise EvidenceError("Wrong safety/compile source")
            if stage_record.get("exit_code") != 0 or stage_record.get("normal_exit") is not True:
                raise EvidenceError("Missing/failed mandatory safety or compile")
        records, processes = [], []
        for label in ("public-verification-results", "public-shard-0", "public-shard-1"):
            folder = root / label
            records.append(json.loads((folder / "inventory.json").read_text(encoding="utf-8")))
            processes.append(json.loads((folder / "process.json").read_text(encoding="utf-8")))
            digest = hashlib.sha256((folder / "results.xml").read_bytes()).hexdigest()
            if digest != processes[-1].get("junit_sha256"):
                raise EvidenceError("Missing/changed JUnit file")
        result = compare_records(records[0], records[1:], processes, proof["head"], proof["tree"],
                                 [args.control_result, args.shard_result, args.shard_result])
        write_json(args.output, result)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (EvidenceError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"CI_ACCEPTANCE_FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
