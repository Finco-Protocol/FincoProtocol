"""Existing browser selections, isolated per runner, with mandatory evidence checks."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import zlib

from tools.ci_acceptance import EvidenceError, attest, check_record, run_command, write_json


SELECTIONS = {
    "protocol": ["tests/test_ui_protocol_shell.py", "tests/test_protocol_roadmap_browser.py",
                 "tests/test_crypto_navigation_browser.py", "tests/test_ev_charging_browser.py",
                 "tests/test_yield_browser.py", "-k", "not test_api_b04_placeholders_not_links"],
    "import": ["tests/test_model_ai_import_browser_c.py"],
    "grid": ["tests/test_model_hybrid_inputs_grid_routes.py", "tests/test_model_hybrid_inputs_grid_browser.py"],
    "q4": ["tests/test_model_q4_browser.py"],
    "consolidation": ["tests/test_model_workspace_consolidation_browser.py"],
}
REQUIRED = {
    "protocol": ["artifacts/reference-driven-correction-a/*.png"],
    "import": ["artifacts/model-ai-import/*.png"],
    "grid": ["artifacts/wf05/*.png", "artifacts/wf05/timings.json"],
    "q4": ["artifacts/model-q4-browser/*.png"],
    "consolidation": ["artifacts/workspace-consolidation/prb-*.png"],
    "outputs": ["artifacts/outputs-workspace/browser-results.json", "artifacts/outputs-workspace/*.png"],
}


def manifest(role, root=Path(".")):
    for pattern in REQUIRED[role]:
        if not list(root.glob(pattern)):
            raise EvidenceError(f"Missing mandatory {role} evidence: {pattern}")
    return {path.relative_to(root / "artifacts").as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((root / "artifacts").rglob("*")) if path.is_file()}



# Accepted PR #248: four sectors x desktop/mobile, plus nine functional nodes.
CONSOLIDATION_TEMPLATES = (
    "generic_solar_reference", "generic_wind_reference",
    "generic_data_center_reference", "generic_ev_charging_reference",
)


def _check_png(path: Path, width: int) -> None:
    """Verify the PNG structure, CRC, image data and source viewport width."""
    raw = path.read_bytes()
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise EvidenceError(f"Invalid consolidation PNG signature: {path.name}")
    offset, first, found_image_data = 8, True, False
    while offset + 12 <= len(raw):
        size = int.from_bytes(raw[offset:offset + 4], "big")
        end = offset + size + 12
        if end > len(raw):
            raise EvidenceError(f"Truncated consolidation screenshot: {path.name}")
        tag = raw[offset + 4:offset + 8]
        data = raw[offset + 8:offset + 8 + size]
        expected_crc = int.from_bytes(raw[offset + 8 + size:end], "big")
        if (zlib.crc32(raw[offset + 4:offset + 8 + size]) & 0xffffffff) != expected_crc:
            raise EvidenceError(f"Invalid consolidation screenshot CRC: {path.name}")
        if first and (tag != b"IHDR" or size != 13
                      or int.from_bytes(data[:4], "big") != width
                      or int.from_bytes(data[4:8], "big") < 100):
            raise EvidenceError(f"Wrong consolidation screenshot size: {path.name}")
        if tag == b"IDAT":
            found_image_data = True
        offset, first = end, False
        if tag == b"IEND":
            if not found_image_data or offset != len(raw):
                raise EvidenceError(f"Incomplete consolidation screenshot: {path.name}")
            return
    raise EvidenceError(f"Missing consolidation screenshot end: {path.name}")


def validate_consolidation(folder: Path, inventory: dict, process: dict) -> None:
    """Fail closed on any missing/duplicate/unexecuted #248 node or capture."""
    selected = inventory.get("selected", [])
    if (len(selected) < 17 or selected != inventory.get("collected")
            or inventory.get("deselected")
            or len(set(selected)) != len(selected)
            or any(not node.startswith("tests/test_model_workspace_consolidation_browser.py::")
                   for node in selected)):
        raise EvidenceError("Incomplete/duplicate consolidation collection")
    outcomes = inventory.get("outcomes", {})
    if set(outcomes) != set(selected) or any(outcomes[node].get("status") != "passed" for node in selected):
        raise EvidenceError("Consolidation node failed/skipped/xfail/not executed")
    junit = folder / "results.xml"
    if (not junit.is_file() or hashlib.sha256(junit.read_bytes()).hexdigest()
            != process.get("junit_sha256") or process.get("junit_failures") != 0):
        raise EvidenceError("Missing/failing/source-mismatched consolidation JUnit")
    cases = list(ET.parse(junit).getroot().iter("testcase"))
    executed = [
        case.get("classname", "").replace(".", "/") + ".py::" + case.get("name", "")
        for case in cases
    ]
    if (len(cases) != len(selected) or set(executed) != set(selected)
            or len(set(executed)) != len(executed)):
        raise EvidenceError("Consolidation JUnit nodes differ from collection")
    if any(list(case) for case in cases):
        raise EvidenceError("Consolidation JUnit contains failure/error/skip/xfail")
    evidence = folder / "workspace-consolidation"
    if len(list(evidence.glob("prb-*.png"))) < 8:
        raise EvidenceError("Fewer than eight consolidation screenshots")
    for template in CONSOLIDATION_TEMPLATES:
        for width, scheme in ((1440, "light"), (390, "dark")):
            screenshot = evidence / f"prb-{template}-{width}-{scheme}.png"
            if not screenshot.is_file():
                raise EvidenceError(f"Missing consolidation viewport: {screenshot.name}")
            _check_png(screenshot, width)
    if process.get("exit_code") != 0 or process.get("normal_exit") is not True:
        raise EvidenceError("Consolidation browser process exit not normal")

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
            if role == "consolidation":
                validate_consolidation(folder, inventory, process)
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
    if args.role == "consolidation":
        os.environ.update(WF05_SCREENSHOT_DIR="artifacts/workspace-consolidation", FINCO_MODEL_EXECUTION_MODE="thread")
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
        if args.role == "consolidation":
            validate_consolidation(Path("artifacts"), json.loads(Path("artifacts/inventory.json").read_text()),
                                   json.loads(Path("artifacts/process.json").read_text()))
        write_json("artifacts/manifest.json", manifest(args.role))
    return code


if __name__ == "__main__":
    sys.exit(main())
