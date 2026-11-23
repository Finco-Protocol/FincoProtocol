"""Independent schema-2 parent-receipt verification plus the unchanged V1 verifier."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys
import time

from tools.ci_v3_evidence_verify import verify_execution
from tools.ci_v3_real_contract import (
    REAL_EVALUATOR, actual_execution_records, check_envelope, envelope, file_sha,
)
from tools.ci_v3_schema import ContractError, digest, read_json, reconcile_collection, require, write_json

REQUIRED_WORKER_FILES = {"request.json", "release", "process.log", "adapter.json", "native.xml",
                         "pytest-return.json", "interpreter-exit.json", "bootstrap-start.json", "results.xml", "execution.json"}


def verify_files(directory, hashes, required):
    require(isinstance(hashes, dict) and required <= set(hashes), "incomplete artifact transfer/manifest")
    for name, sha in hashes.items():
        require(isinstance(name, str) and "/" not in name and "\\" not in name and name not in (".", ".."),
                "unsafe artifact filename")
        path = directory / name
        require(path.is_file() and not path.is_symlink() and file_sha(path) == sha,
                "artifact differs from independently pinned parent observation: " + name)


def verify_observed(root, observations_sha256, trusted_input, trusted_producer):
    started = time.perf_counter()
    root = Path(root)
    # This anchor must come from a trusted controller, not receipt-pin.json supplied with artifacts.
    require(file_sha(root / "observations.json") == observations_sha256, "independent parent receipt anchor mismatch")
    receipt = read_json(root / "observations.json")
    check_envelope(receipt, "ci-v3-parent-observations")
    require(receipt.get("authority") == "local-non-authoritative", "wrong observation authority")
    require(receipt.get("producer") == trusted_producer and trusted_producer.get("evaluator") == REAL_EVALUATOR,
            "unapproved evaluator/producer content")
    require(receipt.get("context") == trusted_input["context"] and receipt["context"]["mode"] == "recorded",
            "wrong source/run/attempt/policy context or simulated process evidence")
    require(receipt.get("controller_error") is None, "controller rejected source/collection: " + str(receipt.get("controller_error")))
    source = trusted_input["context"]["source"]
    require(receipt["source_before"] == receipt["source_after"] == source, "controller source identity changed")
    require(digest(receipt["environment"]) == trusted_input["context"]["environment_digest"], "trusted environment mismatch")
    inventory, policy, plan, collection = (read_json(root / (k + ".json")) for k in ("inventory", "policy", "plan", "collection"))
    require(read_json(root / "trust.json") == trusted_input, "transferred trust file is not independent trusted input")
    discovery = receipt["discovery"]
    require(discovery["normal_successful_exit"] and discovery["os_exit_code"] == 0 and not discovery["timed_out"],
            "discovery OS failure/timeout")
    verify_files(root / "discovery", discovery["artifact_sha256"], REQUIRED_WORKER_FILES - {"results.xml", "execution.json"})
    discovery_report = read_json(root / "discovery/adapter.json")
    check_envelope(discovery_report, "ci-v3-pytest-report")
    require(discovery_report["mode"] == "discover" and discovery_report["phases"] == []
            and not discovery_report["unauthorized_deselection"], "collection-only discovery must not claim executions")
    require(discovery_report["context"] == trusted_input["context"]
            and discovery_report["environment_digest"] == trusted_input["context"]["environment_digest"], "discovery provenance")
    require(discovery_report["collection"] == collection, "fresh collection substituted")
    reconcile_collection(inventory, collection)
    names = {"worker-0", "worker-1", "worker-2"}
    require(set(receipt["workers"]) == names and {p.name for p in (root / "workers").iterdir()} == names,
            "missing/foreign worker")
    workers = []
    for name in sorted(names):
        observed = receipt["workers"][name]
        require(observed["worker"] == name and observed["os_exit_code"] == 0 and not observed["timed_out"]
                and observed["normal_successful_exit"] is True, "observed OS failure/timeout/abnormal exit")
        require(observed["interpreter_exit"] is not None and observed["interpreter_exit"]["finalizing"] is True,
                "missing independently observed interpreter-exit confirmation")
        require(observed["pytest_return"] is not None and observed["pytest_return"]["code"] == 0,
                "pytest return not independently observed")
        directory = root / "workers" / name
        require(not directory.is_symlink(), "symlinked worker directory")
        verify_files(directory, observed["artifact_sha256"], REQUIRED_WORKER_FILES)
        require(read_json(directory / "pytest-return.json") == observed["pytest_return"]
                and read_json(directory / "interpreter-exit.json") == observed["interpreter_exit"],
                "process files differ from observed return/exit records")
        report = read_json(directory / "adapter.json")
        check_envelope(report, "ci-v3-pytest-report")
        require(report["mode"] == "worker" and report["worker"] == name and report["context"] == trusted_input["context"],
                "wrong actual worker provenance")
        require(report["environment_digest"] == digest(report["environment"])
                == trusted_input["context"]["environment_digest"], "actual worker dependency environment mismatch")
        require(report["pytest_exitstatus"] == 0 and not report["unauthorized_deselection"], "pytest error or unexpected deselection")
        owned = {n["nodeid"] for n in inventory["nodes"] if name in
                 [plan["module_workers"][n["module"]], *policy["module_overlaps"].get(n["module"], [])]}
        require(Counter(report["selected"]) == Counter(owned), "selected ownership mismatch")
        require(Counter(report["deselected"]) == Counter(set(collection["nodes"]) - owned), "unexpected deselection")
        actual = actual_execution_records(report)
        execution = read_json(directory / "execution.json")
        require(execution["executions"] == actual, "actual execution records were substituted")
        require(execution["process"]["exit_code"] == execution["process"]["child_exit_code"] == observed["os_exit_code"]
                and execution["process"]["normal_exit"] == observed["normal_successful_exit"], "process claims differ from OS observation")
        require(execution["process"]["pytest_return_code"] == observed["pytest_return"]["code"], "pytest return claim substituted")
        workers.append((execution, (directory / "results.xml").read_bytes()))
    require(len({r["temporary_directory"] for r in receipt["workers"].values()}) == 3, "cross-worker temp-directory contamination")
    legacy = verify_execution(inventory, policy, plan, collection, workers, trusted_input)
    return envelope("ci-v3-observed-proof", coverage_valid=True, authoritative_acceptance=False,
        observation_mode="real-local-OS-observed", evaluator=REAL_EVALUATOR, parent_receipt_sha256=observations_sha256,
        phase1_proof=legacy, aggregation_ms=round((time.perf_counter() - started) * 1000),
        warning="Local prototype only; hosted authenticity and fixture independence require owner review.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("evidence", "observations-sha256", "trusted-input", "trusted-producer", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    try:
        proof = verify_observed(args.evidence, args.observations_sha256, read_json(args.trusted_input), read_json(args.trusted_producer))
        write_json(args.output, proof)
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        write_json(args.output, envelope("ci-v3-observed-rejection", coverage_valid=False, authoritative_acceptance=False, reason=str(exc)))
        print("CI_V3_OBSERVED_REJECTED: " + str(exc), file=sys.stderr)
        return 1
    print("CI_V3_REAL_LOCAL_COVERAGE_VALID; AUTHORITATIVE_ACCEPTANCE=false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
