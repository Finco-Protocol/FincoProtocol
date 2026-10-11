"""Existing browser selections, isolated per runner, with mandatory evidence checks."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from tools.ci_acceptance import EvidenceError, attest, check_record, run_command, write_json


SELECTIONS = {
    "protocol": ["tests/test_ui_protocol_shell.py", "tests/test_protocol_roadmap_browser.py",
                 "tests/test_crypto_navigation_browser.py", "tests/test_ev_charging_browser.py",
                 "tests/test_yield_browser.py", "-k", "not test_api_b04_placeholders_not_links"],
    "import": ["tests/test_model_ai_import_browser_c.py"],
    "grid": ["tests/test_model_hybrid_inputs_grid_routes.py", "tests/test_model_hybrid_inputs_grid_browser.py"],
    "q4": ["tests/test_model_q4_browser.py"],
}
REQUIRED = {
    "protocol": ["artifacts/reference-driven-correction-a/*.png"],
    "import": ["artifacts/model-ai-import/*.png"],
    "grid": ["artifacts/wf05/*.png", "artifacts/wf05/timings.json"],
    "q4": ["artifacts/model-q4-browser/*.png"],
    "outputs": ["artifacts/outputs-workspace/browser-results.json", "artifacts/outputs-workspace/*.png"],
}


def manifest(role, root=Path(".")):
    for pattern in REQUIRED[role]:
        if not list(root.glob(pattern)):
            raise EvidenceError(f"Missing mandatory {role} evidence: {pattern}")
    return {path.relative_to(root / "artifacts").as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((root / "artifacts").rglob("*")) if path.is_file()}


def validate_browser_records(root, expected, tree, job_result, prefix="browser"):
    if job_result != "success":
        raise EvidenceError(f"Browser matrix failed/missing/cancelled: {job_result}")
    proof = {}
    for role in REQUIRED:
        folder = Path(root) / f"{prefix}-{role}"
        hashes = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        required_files = {"process.json"} | ({"inventory.json", "results.xml"} if role in SELECTIONS else set())
        if not required_files.issubset(hashes):
            raise EvidenceError("Missing mandatory file digest")
        for name, digest in hashes.items():
            path = folder / name
            if not path.resolve().is_relative_to(folder.resolve()) or not path.is_file():
                raise EvidenceError("Missing/invalid browser artifact path")
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise EvidenceError("Changed browser artifact")
        for pattern in REQUIRED[role]:
            if not list(folder.glob(pattern.removeprefix("artifacts/"))):
                raise EvidenceError(f"Missing mandatory {role} evidence")
        process = json.loads((folder / "process.json").read_text(encoding="utf-8"))
        if (process.get("head"), process.get("tree"), process.get("label")) != (expected, tree, role):
            raise EvidenceError("Wrong browser source or role")
        if process.get("exit_code") != 0 or process.get("normal_exit") is not True:
            raise EvidenceError("Browser process did not exit successfully")
        if role in SELECTIONS:
            inventory = json.loads((folder / "inventory.json").read_text(encoding="utf-8"))
            check_record(inventory, expected, tree)
            if process.get("junit_failures") != 0:
                raise EvidenceError("Failing browser JUnit")
            if not any(value["status"] == "passed" for value in inventory["outcomes"].values()):
                raise EvidenceError("Browser suite executed no passing tests")
            if hashlib.sha256((folder / "results.xml").read_bytes()).hexdigest() != process.get("junit_sha256"):
                raise EvidenceError("Missing/changed browser JUnit")
        proof[role] = process
    return {"head": expected, "tree": tree, "mandatory_roles": proof,
            "optional_f3": "Separately reported; not counted as mandatory success"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=[*SELECTIONS, "outputs", "aggregate"])
    parser.add_argument("--expected", required=True)
    parser.add_argument("--artifacts", default="evidence")
    parser.add_argument("--job-result")
    parser.add_argument("--merge-sha")
    parser.add_argument("--merge-result")
    args = parser.parse_args()
    if args.role == "aggregate":
        source = attest(args.expected)
        proof = validate_browser_records(args.artifacts, args.expected, source["tree"], args.job_result)
        if args.merge_sha:
            merge_process = Path(args.artifacts) / "merge-browser-protocol" / "process.json"
            merge_tree = json.loads(merge_process.read_text(encoding="utf-8"))["tree"]
            proof["merge_integration"] = validate_browser_records(args.artifacts, args.merge_sha, merge_tree, args.merge_result, "merge-browser")
        write_json("artifacts/browser-proof.json", proof)
        return 0
    for folder in ("artifacts/model-ai-import", "artifacts/wf05", "artifacts/model-q4-browser"):
        Path(folder).mkdir(parents=True, exist_ok=True)
    if args.role == "protocol":
        os.environ["FINCO_VISUAL_CAPTURE"] = "1"
    if args.role == "grid":
        os.environ.update(WF05_SCREENSHOT_DIR="artifacts/wf05", WF05_TIMINGS_JSON="artifacts/wf05/timings.json")
    if args.role == "outputs":
        os.environ["FINCO_MODEL_EXECUTION_MODE"] = "thread"
        command = [sys.executable, "-m", "tests.model_outputs_workspace_acceptance", "--out", "artifacts/outputs-workspace"]
        junit = None
    else:
        junit = "artifacts/results.xml"
        command = [sys.executable, "tools/ci_pytest_runner.py", "-v", "-p", "tools.ci_pytest_inventory",
                   "--ci-inventory=artifacts/inventory.json", f"--junitxml={junit}", *SELECTIONS[args.role]]
    code = run_command(argparse.Namespace(expected=args.expected, label=args.role, output="artifacts/process.json",
                                         junit=junit, command=command))
    if code == 0:
        write_json("artifacts/manifest.json", manifest(args.role))
    return code


if __name__ == "__main__":
    sys.exit(main())
