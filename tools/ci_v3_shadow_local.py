"""Local-only three-worker synthetic-project harness. No FINCO suite or hosted jobs."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid
import xml.etree.ElementTree as ET

from tools.ci_v3_partition_plan import plan_partitions
from tools.ci_v3_process_observer import observe
from tools.ci_v3_real_contract import (
    actual_execution_records, check_envelope, environment_record, envelope,
    file_sha, git_source, producer_identity,
)
from tools.ci_v3_schema import (
    ContractError, EVALUATOR, digest, read_json, reconcile_collection, require, seal,
    skip_key, validate_inventory, validate_policy, write_json,
)

ARTIFACTS = ("request.json", "release", "process.log", "adapter.json", "native.xml",
             "pytest-return.json", "interpreter-exit.json", "bootstrap-start.json", "results.xml", "execution.json")


def normalize_native_junit(data, report):
    """Add collection identities only; never remove or change outcomes or counts."""
    text = data.decode("utf-8")
    require("<!DOCTYPE" not in text.upper() and "<!ENTITY" not in text.upper(), "native JUnit DTD/entity")
    root = ET.fromstring(text)
    skips = {s["nodeid"][:-3].replace("/", "."): s for s in report["collection"]["skips"]}
    require(len(skips) == len(report["collection"]["skips"]), "ambiguous collection skip identity")
    for case in root.iter("testcase"):
        if case.get("classname") == "" and case.get("name") in skips:
            skip = skips[case.get("name")]
            require(case.find("skipped") is not None, "collection identity is not a skip")
            skipped = case.find("skipped")
            require(skipped.get("type") in (None, "pytest.skip"), "collection skip has unexpected type")
            skipped.set("type", "pytest.skip")  # pytest's collection JUnit omits this metadata
            props = case.find("properties")
            if props is None:
                props = ET.SubElement(case, "properties")
            ET.SubElement(props, "property", name="ci_v3_identity",
                          value=json.dumps(["collection-skip", skip_key(skip)], ensure_ascii=True))
            ET.SubElement(props, "property", name="ci_v3_reason", value=json.dumps(skip["reason"], ensure_ascii=True))
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def bridge_worker(directory, observation, context):
    """V2 observed artifacts -> unchanged V1 evidence contract, preserving failures."""
    directory = Path(directory)
    errors = []
    report = read_json(directory / "adapter.json") if (directory / "adapter.json").exists() else None
    records = []
    if report:
        try:
            check_envelope(report, "ci-v3-pytest-report")
            require(report["mode"] == "worker" and report["context"] == context, "adapter context/mode")
            records = actual_execution_records(report)
        except (ContractError, KeyError, ValueError, TypeError) as exc:
            errors.append(str(exc))
    else:
        errors.append("missing actual adapter evidence")
    before = time.perf_counter()
    native = (directory / "native.xml").read_bytes() if (directory / "native.xml").exists() else b""
    try:
        xml = normalize_native_junit(native, report) if report else native
    except (ContractError, ValueError, TypeError, ET.ParseError, KeyError) as exc:
        errors.append("invalid native JUnit: " + str(exc))
        xml = native
    (directory / "results.xml").write_bytes(xml)
    junit_build_ms = round((time.perf_counter() - before) * 1000)
    returned = observation["pytest_return"]
    process = {"exit_code": observation["os_exit_code"], "child_exit_code": observation["os_exit_code"],
        "pytest_return_code": returned["code"] if returned else None,
        "normal_exit": observation["normal_successful_exit"] and not errors,
        "timed_out": observation["timed_out"],
        "pytest_started_ms": returned["pytest_started_ms"] if returned else None,
        "pytest_returned_ms": returned["pytest_returned_ms"] if returned else None,
        "child_exited_ms": observation["elapsed_ms"], "elapsed_ms": observation["elapsed_ms"]}
    collection = report["collection"] if report else {"source": context["source"], "complete": False,
        "errors": ["missing report"], "nodes": [], "skips": []}
    worker = seal({"schema": 1, "kind": "ci-v3-worker-evidence", "worker": observation["worker"],
        "context": context, "complete": bool(report) and not errors,
        "job_result": "success" if process["normal_exit"] else "failure", "collection": collection,
        "executions": records, "junit_sha256": hashlib.sha256(xml).hexdigest(), "process": process,
        "adapter_errors": errors})
    write_json(directory / "execution.json", worker)
    return {**observation, "adapter_errors": errors, "v3_junit_construction_ms": junit_build_ms,
            "artifact_sha256": {name: file_sha(directory / name) for name in ARTIFACTS if (directory / name).is_file()}}


def validate_synthetic_project(project, output):
    project, output = Path(project).resolve(), Path(output).resolve()
    tool_root = Path(__file__).resolve().parents[1]
    require(project != tool_root and not (project / "financial_engine").exists()
            and not (project / ".github/workflows/public_safety_and_smoke.yml").exists(), "FINCO suite execution forbidden")
    require((project / "ci_v3_synthetic_project.json").is_file()
            and read_json(project / "ci_v3_synthetic_project.json") == {"synthetic_only": True},
            "explicit synthetic-project marker required")
    require(not output.is_relative_to(project) and not project.is_relative_to(output), "evidence must be outside tested project")
    require(not output.exists(), "preserve existing execution evidence")
    return project, output


def run_shadow(project, inventory, policy, weights, output, timeout_s=20):
    project, output = validate_synthetic_project(project, output)
    validate_inventory(inventory); validate_policy(policy, inventory)
    require(len(inventory["nodes"]) <= 200, "local prototype is capped at 200 synthetic nodes")
    before_source = git_source(project)
    require(before_source == inventory["source"], "controller-observed source differs from inventory")
    plan = plan_partitions(inventory, policy, weights, 3)
    output.mkdir(parents=True)
    env = environment_record(); env["pytest_plugin_autoload"] = "1"
    context = {"repository": inventory["repository"], "pr_number": None, "workflow": "local-ci-v3-observed",
        "run_id": "local-" + uuid.uuid4().hex, "attempt": 1, "mode": "recorded", "evaluator": EVALUATOR,
        "source": before_source, "environment_digest": digest(env), "inventory_digest": inventory["digest"],
        "policy_digest": policy["digest"], "plan_digest": plan["digest"],
        "merge_proof": {"mode": "main-head", "merge_sha": None, "merge_tree": None}}
    trust = {"schema": 1, "kind": "ci-v3-trust-input", "context": context}
    for name, data in (("inventory", inventory), ("policy", policy), ("plan", plan), ("trust", trust), ("environment", env)):
        write_json(output / (name + ".json"), data)
    request = {"mode": "discover", "project": str(project), "context": context}
    discovery = observe(request, output / "discovery", timeout_s)
    rejection = None
    observations = {}
    collection = None
    try:
        require(discovery["normal_successful_exit"], "discovery subprocess did not finish successfully")
        report = read_json(output / "discovery/adapter.json")
        check_envelope(report, "ci-v3-pytest-report")
        require(report["mode"] == "discover" and report["phases"] == []
                and not report["unauthorized_deselection"], "invalid discovery or selection")
        collection = report["collection"]
        reconcile_collection(inventory, collection)
        write_json(output / "collection.json", collection)
        with ThreadPoolExecutor(max_workers=3) as pool:
            pending = {}
            for number in range(3):
                worker = "worker-%d" % number
                modules = [m for m, w in plan["module_workers"].items()
                           if worker in [w, *policy["module_overlaps"].get(m, [])]]
                req = {"mode": "worker", "project": str(project), "context": context, "worker": worker,
                       "inventory": inventory, "owned_modules": modules}
                pending[worker] = pool.submit(observe, req, output / "workers" / worker, timeout_s)
            for worker, future in pending.items():
                observations[worker] = bridge_worker(output / "workers" / worker, future.result(), context)
        require(git_source(project) == before_source, "source changed during actual execution")
    except (ContractError, OSError, ValueError, KeyError, TypeError) as exc:
        rejection = str(exc)
    discovery["artifact_sha256"] = {name: file_sha(output / "discovery" / name)
        for name in ARTIFACTS if (output / "discovery" / name).is_file()}
    receipt = envelope("ci-v3-parent-observations", context=context, producer=producer_identity(),
        source_before=before_source, source_after=before_source if rejection is None else None,
        environment=env, discovery=discovery, workers=observations, controller_error=rejection,
        authority="local-non-authoritative")
    write_json(output / "observations.json", receipt)
    anchor = file_sha(output / "observations.json")  # retained by the parent, never read from worker claims
    write_json(output / "receipt-pin.json", {"observations_sha256": anchor,
        "warning": "Convenience copy only; independent reviewers must receive the controller anchor out of band."})
    try:
        from tools.ci_v3_observed_verify import verify_observed
        proof = verify_observed(output, anchor, trust, producer_identity())
    except (ContractError, OSError, KeyError, ValueError, TypeError) as exc:
        proof = envelope("ci-v3-observed-rejection", authoritative_acceptance=False, coverage_valid=False, reason=str(exc))
    write_json(output / "proof.json", proof)
    return {"output": str(output), "observations_sha256": anchor, "proof": proof}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("project", "inventory", "policy", "weights", "output"):
        parser.add_argument("--" + option, required=True)
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args(argv)
    try:
        result = run_shadow(args.project, read_json(args.inventory), read_json(args.policy),
                            read_json(args.weights), args.output, args.timeout)
    except (ContractError, OSError, KeyError, ValueError, TypeError) as exc:
        print("CI_V3_LOCAL_REJECTED: " + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0 if result["proof"]["coverage_valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
