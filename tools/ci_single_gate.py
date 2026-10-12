"""Independent single full-suite Public Safety artifact verifier.

Does not infer success from the workflow badge. Requires exact-head source records,
the full unsharded inventory, JUnit integrity, explicit pytest/supervisor rc=0,
a normal process exit and a content-equal synthetic merge (for PRs).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

from tools.ci_acceptance import EvidenceError, attest, check_record, write_json


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_control(root: Path, expected: str, source_result: str, control_result: str,
                   pr_merge_sha: str = "") -> dict:
    if source_result != "success" or control_result != "success":
        raise EvidenceError(f"Required jobs failed/missing: source={source_result}, control={control_result}")
    source = attest(expected)
    guard = load(root / "public-verification-results" / "merge-tree.json")
    if guard.get("head") != expected or guard.get("tree") != source["tree"] or guard.get("equivalent") is not True:
        raise EvidenceError("Missing or source-mismatched merge-tree proof")
    if pr_merge_sha:
        if guard.get("mode") != "identical-tree" or guard.get("merge_sha") != pr_merge_sha or guard.get("merge_tree") != source["tree"]:
            raise EvidenceError("Synthetic merge is not proven byte-identical to the exact HEAD")
    elif guard.get("mode") != "main-head":
        raise EvidenceError("Unexpected merge event in main-branch control")

    safety = root / "public-source-safety"
    for stage in ("scan", "compile"):
        rec = load(safety / f"{stage}.json")
        if (rec.get("head"), rec.get("tree")) != (expected, source["tree"]):
            raise EvidenceError(f"Wrong {stage} source")
        if rec.get("exit_code") != 0 or rec.get("normal_exit") is not True:
            raise EvidenceError(f"Missing/failed {stage} proof")
    folder = root / "public-verification-results"
    inventory, proc = load(folder / "inventory.json"), load(folder / "process.json")
    check_record(inventory, expected, source["tree"])
    if inventory.get("shard") is not None or inventory.get("deselected"):
        raise EvidenceError("Public acceptance must be unsharded and undeselected")
    if inventory["selected"] != inventory["collected"]:
        raise EvidenceError("Full Public Safety collection was not executed")
    if (proc.get("head"), proc.get("tree"), proc.get("label")) != (expected, source["tree"], "control"):
        raise EvidenceError("Wrong Public Safety process origin")
    if proc.get("exit_code") != 0 or proc.get("normal_exit") is not True:
        raise EvidenceError("Public Safety did not finish successfully and normally")
    markers = proc.get("process_markers") or {}
    if markers.get("pytest_return_code") != 0 or markers.get("child_exit_code") != 0:
        raise EvidenceError("Missing exact pytest/supervisor success markers")
    if not proc.get("environment_sha256"):
        raise EvidenceError("Missing dependency environment attestation")
    junit = folder / "results.xml"
    if hashlib.sha256(junit.read_bytes()).hexdigest() != proc.get("junit_sha256") or proc.get("junit_failures") != 0:
        raise EvidenceError("Absent/changed/failing Public Safety JUnit")
    cases = list(ET.parse(junit).getroot().iter("testcase"))
    # Pytest represents module-level collection skips in JUnit but not selected node IDs.
    if len(cases) != len(inventory["selected"]) + len(inventory.get("collection_skips", [])):
        raise EvidenceError("Public Safety JUnit count differs from executed and collection-skipped tests")
    if any(e.tag in ("failure", "error") for c in cases for e in c):
        raise EvidenceError("Public Safety JUnit contains failure/error")
    return {"head": expected, "tree": source["tree"], "full_unsharded": True,
            "merge_tree_equal": True, "selected_test_ids": len(inventory["selected"]),
            "collection_skips": len(inventory.get("collection_skips", [])),
            "pytest_rc": 0, "supervisor_child_rc": 0, "normal_exit": True,
            "junit_sha256": proc["junit_sha256"], "environment_sha256": proc["environment_sha256"]}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--expected", required=True)
    p.add_argument("--artifacts", required=True)
    p.add_argument("--source-result", required=True)
    p.add_argument("--control-result", required=True)
    p.add_argument("--merge-sha", default="")
    p.add_argument("--output", required=True)
    args = p.parse_args()
    proof = verify_control(Path(args.artifacts), args.expected, args.source_result,
                           args.control_result, args.merge_sha)
    write_json(args.output, proof)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (EvidenceError, OSError, KeyError, json.JSONDecodeError, ET.ParseError) as exc:
        print(f"PUBLIC_SINGLE_GATE_FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
