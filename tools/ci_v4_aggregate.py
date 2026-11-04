"""CI V4 result aggregation: prove that the SELECTED nodes were the ones executed, then emit the manifest/record.

Fails closed on: junit missing, selected module with no executed case, executed module not selected, any failure/error, any skip
(FAST/RISK), duplicate node across shards, shard evidence bound to a different SHA/tree/plan, tampered plan digest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


class AggregateError(ValueError):
    pass


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _module_of(classname, selected_dotted):
    parts = classname.split(".")
    for i in range(len(parts), 0, -1):
        cand = ".".join(parts[:i])
        if cand in selected_dotted:
            return selected_dotted[cand]
    return None


def verify_plan_digest(plan):
    body = {k: v for k, v in plan.items() if k != "digest"}
    want = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if plan.get("digest") != want:
        raise AggregateError("plan digest mismatch (tampered plan)")


def read_junit(path):
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise AggregateError("unreadable junit %s: %s" % (path, exc)) from exc
    out = []
    for c in root.iter("testcase"):
        status = "passed"
        if c.find("failure") is not None:
            status = "failed"
        elif c.find("error") is not None:
            status = "error"
        elif c.find("skipped") is not None:
            status = "skipped"
        out.append({"classname": c.get("classname", ""), "name": c.get("name", ""), "status": status, "time": float(c.get("time") or 0)})
    return out


def aggregate(plan, shard_records, junit_paths, pytest_tier_skip_policy=None):
    """Return the result dict. ``shard_records``: list of {shard, sha, tree, plan_digest, modules, wall_s, runner_s}."""
    verify_plan_digest(plan)
    if not plan.get("tested_sha") or not plan.get("tested_tree"):
        raise AggregateError("plan lacks tested sha/tree")
    selected = {m[:-3].replace("/", "."): m for m in plan["pytest_modules"]}
    problems = []
    for r in shard_records:
        if r.get("sha") != plan["tested_sha"] or r.get("tree") != plan["tested_tree"] or r.get("plan_digest") != plan["digest"]:
            problems.append("shard %s evidence is bound to a different sha/tree/plan" % r.get("shard"))
    shard_modules = [m for r in shard_records for m in r.get("modules", [])]
    if sorted(shard_modules) != sorted(set(shard_modules)):
        problems.append("a module is assigned to more than one shard")
    if set(shard_modules) != set(plan["pytest_modules"]):
        problems.append("shard assignment differs from the plan (missing=%s foreign=%s)" % (
            sorted(set(plan["pytest_modules"]) - set(shard_modules))[:5], sorted(set(shard_modules) - set(plan["pytest_modules"]))[:5]))
    cases, seen = [], set()
    for jp in junit_paths:
        for c in read_junit(jp):
            key = (c["classname"], c["name"])
            if key in seen:
                problems.append("duplicate node %s::%s across junit files" % key)
            seen.add(key)
            c["module"] = _module_of(c["classname"], selected)
            cases.append(c)
    per_module = {m: 0 for m in plan["pytest_modules"]}
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    skipped_ids, foreign = [], set()
    for c in cases:
        counts[c["status"]] += 1
        if c["module"] is None:
            foreign.add(c["classname"])
            continue
        per_module[c["module"]] += 1
        if c["status"] == "skipped":
            skipped_ids.append("%s::%s" % (c["classname"], c["name"]))
    if foreign:
        problems.append("executed nodes outside the selection: %s" % sorted(foreign)[:5])
    empty = sorted(m for m, n in per_module.items() if n == 0)
    if empty:
        problems.append("selected but never executed: %s" % empty[:10])
    if counts["failed"] or counts["error"]:
        problems.append("failures=%d errors=%d" % (counts["failed"], counts["error"]))
    # A skip is never a pass: every skipped node is listed as SKIPPED. It FAILS the gate when its module is a no-skip module (baseline, security,
    # save-integrity, F01 suites and the PR's own changed test modules) or when the run asks for zero skips.
    no_skip = set(plan.get("no_skip_modules", []))
    hard = sorted({c["module"] for c in cases if c["status"] == "skipped" and c["module"] in no_skip})
    if hard:
        problems.append("skipped nodes in no-skip modules: %s" % hard[:10])
    if pytest_tier_skip_policy is not None and counts["skipped"] > int(pytest_tier_skip_policy):
        problems.append("skipped=%d exceeds the allowed %d" % (counts["skipped"], int(pytest_tier_skip_policy)))
    wall = [float(r.get("wall_s", 0)) for r in shard_records]
    result = {
        "schema": "FINCO_CI_V4_RESULT_V1", "tier": plan["tier"], "tested_sha": plan["tested_sha"], "tested_tree": plan["tested_tree"],
        "plan_digest": plan["digest"], "rule_ids": plan["rule_ids"], "triggers": plan["triggers"],
        "selected_modules": len(plan["pytest_modules"]), "executed_nodes": len(cases),
        "counts": counts, "skipped_ids": sorted(skipped_ids), "skipped_label": "SKIPPED (not PASS)", "not_selected": plan["not_selected"],
        "workers": len(shard_records), "actual_critical_path_s": round(max(wall, default=0.0), 1),
        "actual_runner_minutes": round(sum(float(r.get("runner_s", r.get("wall_s", 0))) for r in shard_records) / 60.0, 2),
        "predicted_critical_path_s": plan.get("schedule", {}).get("predicted_critical_path_s"),
        "junit_sha256": sorted(_sha256(p) for p in junit_paths),
        "problems": problems, "verdict": "PASS" if not problems else "FAIL",
    }
    return result


def full_record(result, plan, run_id, run_attempt, finished_at, collected):
    """The FULL regression record consumed by the release gate. Untrusted by itself: the gate re-verifies it against GitHub."""
    if plan["tier"] != "full":
        raise AggregateError("only a FULL plan produces a release record")
    return {"schema": "FINCO_CI_V4_FULL_RECORD_V1", "tier": "full", "tested_sha": result["tested_sha"], "tested_tree": result["tested_tree"],
            "conclusion": "pass" if result["verdict"] == "PASS" else "fail", "run_id": int(run_id), "run_attempt": int(run_attempt),
            "finished_at": finished_at, "collected_nodes": int(collected), "executed_nodes": result["executed_nodes"],
            "counts": result["counts"], "skipped_ids": result["skipped_ids"], "plan_digest": result["plan_digest"],
            "junit_sha256": result["junit_sha256"]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True); ap.add_argument("--shards", required=True, help="directory with shard-*.json")
    ap.add_argument("--junit", required=True, help="directory with *.xml"); ap.add_argument("--output", required=True)
    ap.add_argument("--max-skipped", type=int, default=None, help="optional global cap; no-skip modules always fail on a skip")
    ap.add_argument("--run-id", default="0"); ap.add_argument("--run-attempt", default="1"); ap.add_argument("--finished-at", default="")
    a = ap.parse_args(argv)
    plan = json.loads(Path(a.plan).read_text())
    shards = [json.loads(p.read_text()) for p in sorted(Path(a.shards).glob("**/shard-*.json"))]
    junit = sorted(Path(a.junit).glob("**/*.xml"))
    try:
        if not junit or not shards:
            raise AggregateError("no shard evidence / junit found")
        res = aggregate(plan, shards, junit, a.max_skipped)
    except AggregateError as exc:
        print("CI V4 aggregate FAIL CLOSED: %s" % exc, file=sys.stderr)
        return 2
    out = Path(a.output); out.mkdir(parents=True, exist_ok=True)
    (out / "ci-v4-result.json").write_text(json.dumps(res, indent=2, sort_keys=True))
    if plan["tier"] == "full":
        (out / "ci-v4-full-record.json").write_text(json.dumps(
            full_record(res, plan, a.run_id, a.run_attempt, a.finished_at, res["executed_nodes"]), indent=2, sort_keys=True))
    print("%s tier=%s executed=%d problems=%s" % (res["verdict"], res["tier"], res["executed_nodes"], res["problems"]))
    return 0 if res["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
