"""Read GitHub job/step timestamps; keep active-gate and shadow costs separate."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
import statistics
import subprocess

from tools.ci_acceptance import EvidenceError, write_json


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", path], text=True, encoding="utf-8"))


def seconds(start, finish):
    return (datetime.fromisoformat(finish.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds()


def distribution(values):
    ordered = sorted(values)
    if not ordered:
        return None
    return {"samples": len(values), "median": statistics.median(values),
            "p90_nearest_rank": ordered[math.ceil(0.9 * len(ordered)) - 1], "maximum": max(values)}


def measure_run(repo, run_id, expected):
    run = api(f"repos/{repo}/actions/runs/{run_id}")
    if run["head_sha"] != expected or run["status"] != "completed":
        raise EvidenceError(f"Run {run_id} wrong head or incomplete")
    jobs = []
    page = 1
    while True:
        batch = api(f"repos/{repo}/actions/runs/{run_id}/attempts/{run['run_attempt']}/jobs?per_page=100&page={page}")["jobs"]
        jobs.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    usable = [job for job in jobs if job.get("started_at") and job.get("completed_at")]
    return {"run_id": run_id, "head": expected, "attempt": run["run_attempt"],
            "workflow": run["name"], "event": run["event"], "conclusion": run["conclusion"],
            "created_at": run["created_at"],
            "wall_seconds": max(seconds(run["created_at"], j["completed_at"]) for j in usable),
            "queue_seconds": min(seconds(run["created_at"], j["started_at"]) for j in usable),
            "runner_minutes": sum(seconds(j["started_at"], j["completed_at"]) for j in usable) / 60,
            "jobs": [{"id": j["id"], "name": j["name"], "conclusion": j["conclusion"],
                      "queue_from_run_seconds": seconds(run["created_at"], j["started_at"]),
                      "runner_seconds": seconds(j["started_at"], j["completed_at"]),
                      "finish_from_run_seconds": seconds(run["created_at"], j["completed_at"]),
                      "steps": j["steps"]} for j in usable]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="Finco-Protocol/FincoProtocol")
    parser.add_argument("--head", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("run_ids", nargs="+", type=int)
    args = parser.parse_args()
    rows = [measure_run(args.repo, run_id, args.head) for run_id in args.run_ids]
    write_json(args.output, {"head": args.head, "runs": rows,
                            "wall_seconds": distribution([r["wall_seconds"] for r in rows]),
                            "runner_minutes": distribution([r["runner_minutes"] for r in rows]),
                            "note": "Do not combine unlike workflows as a performance cohort. Shadow gate waits for unchanged control; no active Public reduction is implied."})


if __name__ == "__main__":
    main()
