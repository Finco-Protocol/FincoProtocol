"""Exact canonical comparison across V9-P1 widths; writes private evidence only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

from tools.v9_joint_acceptance import cases, run_case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, action="append", required=True)
    parser.add_argument("--baseline-inputs", type=Path, action="append", default=[])
    parser.add_argument("--workers", default="0,1,2,3")
    parser.add_argument("--cases")
    parser.add_argument("--research-inventory", type=Path)
    parser.add_argument("--admission", choices=("adaptive", "primitive"), default="adaptive")
    args = parser.parse_args()
    from financial_engine.financing import speculative as sp
    if args.admission == "primitive":
        # Explicit numerical coverage only; never installed in application code.
        sp.parallel_admitted = lambda session: session.workers > 0

    expected = {}
    sources = []
    for path in args.baseline:
        content = path.read_bytes()
        data = json.loads(content)
        assert data["source_head"] == "5996453b8d5bbfaa48bc06922fc6963cf94d2f84"
        expected.update(data["results"])
        sources.append({"sha256": hashlib.sha256(content).hexdigest(),
                        "source_head": data["source_head"]})
    for path in args.baseline_inputs:
        content = path.read_bytes()
        data = json.loads(content)
        assert data["source_head"] == "5996453b8d5bbfaa48bc06922fc6963cf94d2f84"
        for name, row in data["results"].items():
            expected[name]["input_digest"] = row["input_digest"]
        sources.append({"input_only": True, "sha256": hashlib.sha256(content).hexdigest(),
                        "source_head": data["source_head"]})
    selected = args.cases.split(",") if args.cases else list(cases())
    assert all(name in expected for name in selected)
    report = {"head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"])),
              "platform": platform.platform(), "python": sys.version, "baseline_sources": sources,
              "selected_cases": selected, "results": {}, "release_approval": False,
              "admission": args.admission}
    if args.research_inventory:
        data = args.research_inventory.read_bytes()
        names = json.loads(data)
        assert len(names) == 58 and len(set(names)) == 58
        assert set(names).issubset(selected)
        report["research_58"] = {"names": names, "sha256": hashlib.sha256(data).hexdigest(),
                                  "covered_as_subset_of": len(selected)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    def source_blobs():
        return {path: subprocess.check_output(["git", "hash-object", "--path=" + path, path],
                    text=True).strip() for path in (
                    "financial_engine/financing/project.py", "financial_engine/financing/speculative.py")}
    report["protected_git_blobs"] = source_blobs()

    def save():
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    try:
        for workers in map(int, args.workers.split(",")):
            sp.shutdown_helpers()
            os.environ["FINCO_G2A_WORKERS"] = str(workers)
            assert sp.configured_workers() == workers, "RESOURCE_BUDGET_REFUSES_REQUESTED_WIDTH"
            if args.admission == "adaptive" and workers >= 2:
                assert sp.prewarm_worker()["ready"], "PREWARM_FAILED"
            report["results"][str(workers)] = {}
            for name in selected:
                started = time.perf_counter()
                row = run_case(name, "canonical", False)
                assert row["input_digest"] == expected[name]["input_digest"], name
                assert row["digest"] == expected[name]["digest"], (name, workers, "DIFFERENT_BITS")
                if workers and args.admission == "primitive":
                    assert sp._POOL is not None and not sp._POOL.broken, "SPECULATIVE_POOL_FAILED"
                report["results"][str(workers)][name] = {
                    key: value for key, value in row.items() if key != "evidence"}
                report["results"][str(workers)][name]["whole_case_wall_s"] = time.perf_counter() - started
                report["results"][str(workers)][name]["configured_helpers"] = sp.configured_workers()
                if sp._POOL is not None:
                    report["results"][str(workers)][name]["helper_metrics"] = json.loads(json.dumps(sp._POOL.metrics))
                save()
                print(workers, name, row["status"], "BIT_IDENTICAL", row["seconds"], flush=True)
            assert source_blobs() == report["protected_git_blobs"], "SOURCE_CHANGED_DURING_MATRIX"
    finally:
        sp.shutdown_helpers()
        save()


if __name__ == "__main__":
    main()
