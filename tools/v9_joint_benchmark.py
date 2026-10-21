"""Alternating uncached actual-Run measurements; profiling is separate from latency."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--candidate", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--samples", type=int, default=5)
    p.add_argument("--cases", nargs="+", default=["S50", "S16", "W25", "DC", "reference-ev_charging"])
    p.add_argument("--profiles", action="store_true")
    p.add_argument("--guarded", action="store_true")
    p.add_argument("--include-guarded", action="store_true")
    p.add_argument("--warm-numerics", action="store_true")
    args = p.parse_args()
    if args.samples < 1:
        p.error("positive sample count required")
    args.out = args.out.resolve()
    worker = Path(__file__).with_name("v9_joint_acceptance.py").resolve()
    arms = {"baseline": (args.baseline.resolve(), "canonical")}
    if args.candidate:
        arms["candidate"] = (args.candidate.resolve(), "guarded" if args.guarded else "proposal")
        if args.include_guarded:
            arms["guarded"] = (args.candidate.resolve(), "guarded")
    extra = ["--warm-numerics"] if args.warm_numerics else []
    args.out.mkdir(parents=True, exist_ok=True)
    report = {"samples_per_arm": args.samples, "timing": "actual uncached full financial Run, cold process; imports and flattening excluded",
              "p95_caution": "nearest rank; five samples imply observed maximum, not a reliable production tail",
              "profiles_excluded_from_timings": True, "cases": {}}
    report["numpy_preloaded_for_all_arms"] = args.warm_numerics
    report["source_origins"] = {}
    for name in args.cases:
        rows = {arm: [] for arm in arms}
        for i in range(args.samples):
            order = list(arms) if i % 2 == 0 else list(reversed(arms))
            for arm in order:
                repo, mode = arms[arm]
                out = args.out / f"{name}-{arm}-{i}.json"
                subprocess.run([sys.executable, "-u", str(worker), "--repo", str(repo),
                                "--out", str(out), "--cases", name, "--mode", mode, *extra], cwd=repo, check=True)
                execution = json.loads(out.read_text())
                row = execution["results"][name]
                report["source_origins"][arm] = {key: value for key, value in execution.items() if key != "results"}
                rows[arm].append({k: v for k, v in row.items() if k != "evidence"})
        summary = {}
        for arm, samples in rows.items():
            assert len({row["digest"] for row in samples}) == 1, (name, arm, "nondeterministic evidence")
            times = sorted(row["seconds"] for row in samples)
            summary[arm] = {"median_s": statistics.median(times),
                            "p95_nearest_rank_s": times[math.ceil(.95 * len(times)) - 1], "raw": samples}
        if "candidate" in rows:
            summary["measured_saving_pct"] = 100 * (1 - summary["candidate"]["median_s"] / summary["baseline"]["median_s"])
        if "guarded" in rows:
            summary["guarded_measured_saving_pct"] = 100 * (1 - summary["guarded"]["median_s"] / summary["baseline"]["median_s"])
            assert rows["guarded"][0]["digest"] == rows["baseline"][0]["digest"], (name, "guard changed canonical evidence")
        assert len({row["input_digest"] for samples in rows.values() for row in samples}) == 1, name
        if args.profiles:
            for arm, (repo, mode) in arms.items():
                out = args.out / f"{name}-{arm}-profile.json"
                subprocess.run([sys.executable, "-u", str(worker), "--repo", str(repo), "--out", str(out),
                                "--cases", name, "--mode", mode, "--profile", *extra], cwd=repo, check=True)
                row = json.loads(out.read_text())["results"][name]
                assert row["digest"] == rows[arm][0]["digest"], (name, arm, "profiling changed evidence")
                summary[arm]["profile"] = {k: v for k, v in row.items() if k != "evidence"}
        report["cases"][name] = summary
        (args.out / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
        print("COMPLETED", name, flush=True)


if __name__ == "__main__":
    main()
