"""Exact original-node/phase/native-JUnit comparison. No authorization or network.

Inputs must be retained original artifacts with independently supplied hash pins.
Byte integrity is not service authentication. Missing same-source control phases
or host cleanup evidence blocks this gate; progress durations are never inferred.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import xml.etree.ElementTree as ET

from tools.ci_v3_nonpass import node_id
from tools.ci_v3_real_contract import check_envelope, outcome
from tools.ci_v3_pytest_config import PLUGINS
from tools.ci_v3_schema import ContractError, _pairs, _invalid_constant, read_json, require, seal, skip_counter, unique_strings, write_json

FIELDS = ("when", "outcome", "reason", "wasxfail")


def control_report(value):
    if value.get("kind") == "ci-v3-pytest-report":
        check_envelope(value, "ci-v3-pytest-report")
        require(value.get("mode") == "worker" and value.get("worker") == "control", "not a full advisory control report")
        return {**value, "source": value["context"]["source"]}
    require(value.get("phase_schema") == 1 and isinstance(value.get("phases"), list),
            "control phase evidence missing; record original reports, not progress durations")
    source = {"head": value.get("head"), "tree": value.get("tree")}
    return {"source": source, "collection": {"source": source, "complete": True,
        "errors": value["collection_errors"], "nodes": value["collected"],
        "skips": value["collection_skip_records"]},
        "selected": value["selected"], "deselected": value["deselected"], "phases": value["phases"],
        "pytest_exitstatus": value["pytest_exit"], "environment": value["environment"], "pytest_plugins": value.get("pytest_plugins"), "plugin_registrations": value.get("plugin_registrations"),
        "runtime_host": value.get("runtime_host")}


def phase_map(report):
    selected = report["selected"]
    unique_strings(selected, "selected original nodes")
    phases = defaultdict(list)
    for phase in report["phases"]:
        require(phase["nodeid"] in selected, "unknown/unowned phase node")
        require(all(k in phase for k in FIELDS), "incomplete phase fields")
        require(isinstance(phase["reason"], str) and (phase["wasxfail"] is None or isinstance(phase["wasxfail"], str)),
                "malformed phase reason")
        phases[phase["nodeid"]].append(phase)
    require(set(phases) == set(selected), "missing actual phase nodes")
    for values in phases.values():
        outcome(values)  # rejects duplicate, unknown or missing required phases
    return {n: [{k: p[k] for k in FIELDS} for p in sorted(v, key=lambda p: ("setup", "call", "teardown").index(p["when"]))]
            for n, v in phases.items()}


def native_cases(data, report):
    require(b"<!DOCTYPE" not in data.upper() and b"<!ENTITY" not in data.upper(), "JUnit DTD/entity")
    root = ET.fromstring(data)
    for suite in root.iter("testsuite"):
        direct = list(suite.findall("testcase"))
        if not direct: continue
        for label, actual in (("tests", len(direct)), ("failures", sum(c.find("failure") is not None for c in direct)),
                              ("errors", sum(c.find("error") is not None for c in direct)),
                              ("skipped", sum(c.find("skipped") is not None for c in direct))):
            require(suite.get(label) is not None and int(suite.get(label)) == actual, "native JUnit count mismatch")
    modules = {n.split("::", 1)[0] for n in report["collection"]["nodes"]}
    cases = {}
    collection = []
    for case in root.iter("testcase"):
        skip = case.find("skipped")
        classname = case.get("classname") or ""
        if not classname:
            require(skip is not None, "unknown native collection case")
            collection.append((case.get("name") or "").replace(".", "/") + ".py")
            continue
        ident = node_id(classname, case.get("name"), modules)
        require(ident in report["selected"] and ident not in cases, "unknown/duplicate native original node")
        tags = [c.tag for c in case if c.tag in ("failure", "error", "skipped")]
        require(len(tags) <= 1, "ambiguous native outcome")
        status = "passed"
        if tags:
            status = {"failure": "failed", "error": "error", "skipped": "skipped"}[tags[0]]
            if skip is not None and skip.get("type") == "pytest.xfail": status = "xfail"
        message = case.find(tags[0]).get("message", "") if tags else ""
        cases[ident] = (status, message)
    require(set(cases) == set(report["selected"]), "missing native original nodes")
    require(Counter(collection) == Counter(s["nodeid"] for s in report["collection"]["skips"]),
            "native collection skip mismatch")
    phases = phase_map(report)
    for ident, values in phases.items():
        status = outcome(values)["status"]
        if any(p["outcome"] == "failed" and p["when"] != "call" for p in values): status = "error"
        require(cases[ident][0] == ("passed" if status == "xpass" else status), "native JUnit/phase outcome mismatch")
    return cases


def process_check(process, source):
    if process.get("kind") == "ci-v3-isolated-host-receipt":
        require(process.get("source_before") == process.get("source_after") == source, "host receipt source mismatch")
        process = {**process["observation"], "source": source}
    actual = process.get("source") or {"head": process.get("head"), "tree": process.get("tree")}
    require(actual == source, "process source mismatch")
    require(process.get("exit_code", process.get("os_exit_code")) == 0
            and process.get("normal_exit", process.get("normal_successful_exit")) is True
            and not process.get("timed_out", False), "process did not finish normally")
    # A successful pytest return is not proof of descendant/container cleanup.
    require(process.get("cleanup_verified") is True or
            (process.get("container_removed") is True and process.get("source_bytes_unchanged") is True),
            "independent process cleanup evidence missing")


def compare(control, shadow, native, processes):
    require(len(shadow) == 3 and len(native) == len(processes) == 4, "one control and three workers required")
    source = control["source"]
    require(all(isinstance(source.get(k), str) and len(source[k]) == 40 for k in ("head", "tree")), "missing exact source")
    collection = control["collection"]
    require(collection["complete"] and not collection["errors"] and not control["deselected"], "incomplete/unsharded control required")
    unique_strings(collection["nodes"], "control original nodes")
    require(Counter(control["selected"]) == Counter(collection["nodes"]), "control selection mismatch")
    cp = phase_map(control); all_phases = {}; all_native = {}
    native_control = native_cases(native[0], control)
    for index, report in enumerate([control, *shadow]):
        require(report.get("pytest_plugins") == list(PLUGINS), "control/shadow plugin configuration missing or different")
        actual_source = report.get("source") or report.get("context", {}).get("source")
        require(actual_source == source and report["pytest_exitstatus"] == 0, "source/pytest completion mismatch")
        c = report["collection"]
        unique_strings(c["nodes"], "worker collection nodes")
        require(c["source"] == source and c["complete"] and not c["errors"]
                and Counter(c["nodes"]) == Counter(collection["nodes"])
                and skip_counter(c["skips"]) == skip_counter(collection["skips"]), "full collection/skip equivalence mismatch")
        process_check(processes[index], source)
        if index:
            require(report["selected"], "empty shadow worker")
            p = phase_map(report)
            require(not set(all_phases).intersection(p), "duplicate original ownership")
            require(Counter(report["deselected"]) == Counter(set(collection["nodes"]) - set(report["selected"])), "unexpected deselection")
            all_phases.update(p); all_native.update(native_cases(native[index], report))
    require(cp == all_phases, "original-node phase/outcome/nonpass equivalence mismatch")
    require(native_control == all_native, "native JUnit outcome equivalence mismatch")
    return seal({"schema": 1, "kind": "ci-v3-phase-comparison", "source": source,
        "phase_equivalent": True, "original_nodes": len(cp), "collection_skips": len(collection["skips"]),
        "process_cleanup_valid": True, "native_junit_valid": True,
        "environment_equal": all(r["environment"] == control["environment"] for r in shadow),
        "provenance_authenticated": False, "admission_ready": False,
        "warning": "Hash pins establish bytes only; independent service provenance and owner decisions remain required."})


def pinned(path, expected):
    from pathlib import Path
    data = Path(path).read_bytes()
    require(hashlib.sha256(data).hexdigest() == expected, "independent input hash mismatch")
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", required=True, help="independently retained paths/hashes for control then three workers")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        inputs = read_json(args.inputs)
        require(len(inputs) == 4, "four pinned input sets required")
        reports, native, processes = [], [], []
        for item in inputs:
            decode = lambda data: json.loads(data.decode("utf-8-sig"), object_pairs_hook=_pairs, parse_constant=_invalid_constant)
            reports.append(decode(pinned(item["report"]["path"], item["report"]["sha256"])))
            native.append(pinned(item["junit"]["path"], item["junit"]["sha256"]))
            processes.append(decode(pinned(item["process"]["path"], item["process"]["sha256"])))
        result = compare(control_report(reports[0]), reports[1:], native, processes)
    except (ContractError, OSError, KeyError, TypeError, ValueError, ET.ParseError) as exc:
        write_json(args.output, {"phase_equivalent": False, "admission_ready": False, "reason": str(exc)})
        return 1
    write_json(args.output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
