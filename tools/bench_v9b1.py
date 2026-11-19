"""Paired cold-process B1 Runs; timing excludes imports, flattening and profiling."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--cases", nargs="+", default=["S50", "S16", "W25r-dscr2.0", "DC"])
    parser.add_argument("--profiles", action="store_true")
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")
    args.baseline = args.baseline.resolve()
    args.candidate = args.candidate.resolve()
    args.out = args.out.resolve()
    worker = Path(__file__).resolve().with_name("validate_v9b1.py")
    args.out.mkdir(parents=True, exist_ok=True)
    report = {"samples_per_arm": args.samples, "method": "cold processes; alternating AB/BA",
              "profiled_timings_excluded": True, "cases": {}}
    for name in args.cases:
        rows = {"baseline": [], "candidate": []}
        for sample in range(args.samples):
            order = ("baseline", "candidate") if sample % 2 == 0 else ("candidate", "baseline")
            for arm in order:
                destination = args.out / f"{name}-{arm}-{sample}.json"
                command = [sys.executable, "-u", str(worker), "--repo", str(getattr(args, arm).resolve()),
                           "--out", str(destination), "--cases", name]
                subprocess.run(command, check=True, cwd=getattr(args, arm))
                row = json.loads(destination.read_text(encoding="utf-8"))["results"][name]
                rows[arm].append({key: value for key, value in row.items() if key != "evidence"})
        assert len({row["digest"] for arm in rows.values() for row in arm}) == 1, name
        summary = {}
        for arm, samples in rows.items():
            times = sorted(row["seconds"] for row in samples)
            summary[arm] = {"median_s": statistics.median(times),
                            "p95_nearest_rank_s": times[math.ceil(.95 * len(times)) - 1], "raw": samples}
        summary["median_saving_pct"] = 100 * (1 - summary["candidate"]["median_s"] / summary["baseline"]["median_s"])
        if args.profiles:
            summary["profiles"] = {}
            for arm in ("baseline", "candidate"):
                destination = args.out / f"{name}-{arm}-profile.json"
                subprocess.run([sys.executable, "-u", str(worker), "--repo", str(getattr(args, arm).resolve()),
                    "--out", str(destination), "--cases", name, "--profile"], check=True, cwd=getattr(args, arm))
                row = json.loads(destination.read_text(encoding="utf-8"))["results"][name]
                assert row["digest"] == rows[arm][0]["digest"], (name, arm, "profile changed output")
                summary["profiles"][arm] = row["counts"]
        report["cases"][name] = summary
        (args.out / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"{name}: saving={summary['median_saving_pct']:.2f}%", flush=True)


if __name__ == "__main__":
    main()
