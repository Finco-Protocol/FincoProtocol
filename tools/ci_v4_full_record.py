"""Build the CI V4 FULL record from the unchanged CI V3 full-regression evidence of THIS run. Fails closed.

The record is what the release gate reads, but the gate never trusts it alone (it re-verifies junit digests and the GitHub run).
JUnit copies with identical bytes (the historical ``public-test-results.xml`` alias) are counted once.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def collect(evidence):
    files, seen = [], set()
    for p in sorted(Path(evidence).glob("**/*.xml")):
        raw = p.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest in seen:
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            continue
        if root.tag not in ("testsuite", "testsuites") or next(root.iter("testcase"), None) is None:
            continue
        seen.add(digest)
        files.append(p)
    return files


def build(sha, tree, junit_files, results, run_id, run_attempt):
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    skipped, nodes = [], set()
    dup = 0
    for f in junit_files:
        for c in ET.parse(f).getroot().iter("testcase"):
            key = (c.get("classname", ""), c.get("name", ""))
            dup += key in nodes
            nodes.add(key)
            if c.find("failure") is not None:
                counts["failed"] += 1
            elif c.find("error") is not None:
                counts["error"] += 1
            elif c.find("skipped") is not None:
                counts["skipped"] += 1; skipped.append("%s::%s" % key)
            else:
                counts["passed"] += 1
    executed = sum(counts.values())
    ok = (all(r == "success" for r in results.values()) and junit_files and dup == 0 and counts["failed"] == 0 and counts["error"] == 0)
    return {"schema": "FINCO_CI_V4_FULL_RECORD_V1", "tier": "full", "tested_sha": sha, "tested_tree": tree,
            "conclusion": "pass" if ok else "fail", "job_results": results, "duplicate_nodes": dup,
            "run_id": int(run_id), "run_attempt": int(run_attempt),
            "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(), "collected_nodes": executed, "executed_nodes": executed,
            "counts": counts, "skipped_ids": sorted(skipped), "plan_digest": "ci-v3-full-unchanged",
            "junit_sha256": sorted(hashlib.sha256(f.read_bytes()).hexdigest() for f in junit_files),
            "junit_files": [str(f) for f in junit_files]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", required=True); ap.add_argument("--evidence", required=True); ap.add_argument("--output", required=True)
    ap.add_argument("--result", action="append", default=[], help="name=result of each required FULL job")
    ap.add_argument("--run-id", required=True); ap.add_argument("--run-attempt", required=True)
    a = ap.parse_args(argv)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    if head != a.sha:
        print("checkout %s is not the FULL sha %s" % (head, a.sha), file=sys.stderr)
        return 2
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"]).decode().strip()
    results = dict(r.split("=", 1) for r in a.result)
    files = collect(a.evidence)
    rec = build(a.sha, tree, files, results, a.run_id, a.run_attempt)
    out = Path(a.output); out.mkdir(parents=True, exist_ok=True)
    (out / "ci-v4-full-record.json").write_text(json.dumps(rec, indent=2, sort_keys=True))
    for f in files:                                  # junit travels with the record so the gate can re-derive counts
        dst = out / "junit" / Path(f).relative_to(a.evidence)
        dst.parent.mkdir(parents=True, exist_ok=True); dst.write_bytes(Path(f).read_bytes())
    print("FULL %s executed=%d counts=%s" % (rec["conclusion"].upper(), rec["executed_nodes"], rec["counts"]))
    return 0 if rec["conclusion"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
