"""CI V4 result aggregation: prove that the SELECTED nodes were the ones executed, then emit the manifest/record.

Fails closed on: junit missing, selected module with no executed case, executed module not selected, any failure/error, any skip
(FAST/RISK), duplicate node across shards, shard evidence bound to a different SHA/tree/plan, tampered plan digest. For a node plan
(allowlisted modules split by exact pytest node id) it additionally proves collected == disjoint union of executed nodes per split module
against an independent re-collection (``verify_node_split``).
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


def _expected_shard_modules(plan, index):
    shards = plan.get("schedule", {}).get("shards", [])
    return shards[index] if isinstance(index, int) and 0 <= index < len(shards) else None


def verify_node_split(plan, shard_records, node_evidence, junit_by_shard, inventory):
    """Exact node coverage for every split module (fail-closed list of problems).

    ``inventory`` is an INDEPENDENT re-collection (another job, after the shards) at the tested SHA/tree. For each split module:
    independent inventory == planned inventory (ordered ids, digest, profile); executed ids (per-node plugin evidence) form a DISJOINT union
    equal to the collected ids; each node ran in exactly the shard its unit was assigned to; the JUnit testcases of the shard reconcile 1:1
    with the evidence (pytest's own classname/name derivation) including the outcome; every shard's evidence is complete, bound to this
    plan/SHA/tree/shard, reports the same plugin profile as the collection and the same exit status as the shard record.
    """
    from tools.ci_v4_nodes import junit_address, ids_digest, verify_inventory, NodeError, EVIDENCE_SCHEMA
    from tools.ci_v4_schedule import NODE_SPLIT_SCHEMA
    problems = []
    ns = plan["node_split"]
    if ns.get("schema") != NODE_SPLIT_SCHEMA:
        return ["unknown node_split schema"]
    if inventory is None:
        return ["node plan without an independent re-collection inventory (refused)"]
    try:
        verify_inventory(inventory)
    except NodeError as exc:
        return ["independent inventory: %s" % exc]
    if (inventory["tested_sha"], inventory["tested_tree"]) != (plan["tested_sha"], plan["tested_tree"]):
        problems.append("independent inventory is bound to a different sha/tree")
    if inventory["profile_digest"] != ns["profile_digest"]:
        problems.append("plugin/conftest profile of the independent collection differs from the planned collection")
    units = plan["schedule"].get("units")
    if not isinstance(units, list) or len(units) != len(plan["schedule"]["shards"]):
        return problems + ["node plan schedule lacks units for every shard"]
    owner = {}
    for idx, shard_units in enumerate(units):
        for u in shard_units:
            if u["kind"] == "nodes":
                for n in u["node_ids"]:
                    if n in owner:
                        problems.append("node %s planned in two units" % n)
                    owner[n] = idx
    for m, meta in sorted(ns["modules"].items()):
        ind = inventory["modules"].get(m)
        if ind is None or ind["node_ids"] != meta["node_ids"] or ind["digest"] != meta["digest"] or ids_digest(meta["node_ids"]) != meta["digest"]:
            problems.append("independent collection of %s differs from the planned inventory" % m)
        planned = sorted(n for n, i in owner.items() if module_of_id(n) == m)
        if planned != sorted(meta["node_ids"]):
            problems.append("planned units of %s do not partition its collected nodes exactly" % m)
    by_shard = {}
    for r in shard_records:
        idx = r.get("shard")
        if idx in by_shard:
            problems.append("duplicate evidence for shard %s" % idx)
        by_shard[idx] = r
    if sorted(by_shard) != list(range(len(units))):
        problems.append("shard evidence %s does not match the planned shards 0..%d" % (sorted(by_shard), len(units) - 1))
    executed = {}
    for idx, r in sorted(by_shard.items(), key=lambda kv: str(kv[0])):
        if not isinstance(idx, int) or not 0 <= idx < len(units):
            continue
        if r.get("units") != units[idx]:
            problems.append("shard %d reports units that differ from the plan" % idx)
        ev = node_evidence.get(idx)
        if not ev or ev.get("schema") != EVIDENCE_SCHEMA or ev.get("complete") is not True:
            problems.append("shard %d: node evidence missing or incomplete (interrupted/truncated session)" % idx)
            continue
        b = ev.get("binding", {})
        if (b.get("tested_sha"), b.get("tested_tree"), b.get("plan_digest"), b.get("shard")) != (plan["tested_sha"], plan["tested_tree"], plan["digest"], idx):
            problems.append("shard %d: node evidence is bound to a different plan/sha/tree/shard" % idx)
        if ev.get("exitstatus") != r.get("pytest_exit"):
            problems.append("shard %d: evidence exit status %s != shard pytest exit %s" % (idx, ev.get("exitstatus"), r.get("pytest_exit")))
        if ev.get("profile_digest") != ns["profile_digest"]:
            problems.append("shard %d: execution plugin/conftest profile differs from the collection profile%s" % (idx, _profile_diff(inventory, ev)))
        for m, meta in ns["modules"].items():
            col = ev.get("collected", {}).get(m)
            if col is not None and (col.get("count"), col.get("digest")) != (meta["count"], meta["digest"]):
                problems.append("shard %d: execution-time collection of %s differs from the inventory" % (idx, m))
        kept = ev.get("kept") or []
        if len(kept) != len(set(kept)):
            problems.append("shard %d: duplicated kept node" % idx)
        cases = junit_by_shard.get(idx)
        if cases is None:
            problems.append("shard %d: junit-shard-%d.xml missing" % (idx, idx))
            cases = []
        jcount = {}
        for c in cases:
            key = (c["classname"], c["name"])
            jcount[key] = jcount.get(key, []) + [c["status"]]
        for nodeid, rec in ev.get("nodes", {}).items():
            m = module_of_id(nodeid)
            if m not in ns["modules"]:
                continue
            executed.setdefault(nodeid, []).append(idx)
            if owner.get(nodeid) != idx:
                problems.append("node %s executed in shard %d but assigned to shard %s" % (nodeid, idx, owner.get(nodeid)))
            statuses = jcount.get(junit_address(nodeid), [])
            want = {"passed": "passed", "failed": "failed", "error": "error", "skipped": "skipped"}.get(rec.get("outcome"))
            if want is None:
                problems.append("node %s did not complete (%s)" % (nodeid, rec.get("outcome")))
            elif statuses != [want] and not (want == "error" and statuses in (["error"], ["failed"])):
                problems.append("node %s: junit %s does not reconcile with evidence outcome %s" % (nodeid, statuses, rec.get("outcome")))
        ev_split = {n for n in ev.get("nodes", {}) if module_of_id(n) in ns["modules"]}
        for (cls, name), sts in jcount.items():
            node_like = [n for n in ev_split if junit_address(n) == (cls, name)]
            mod = _module_of(cls, {mm[:-3].replace("/", "."): mm for mm in ns["modules"]})
            if mod is not None and not node_like:
                problems.append("shard %d: junit case %s::%s has no node evidence" % (idx, cls, name))
            if mod is not None and len(sts) != 1:
                problems.append("shard %d: junit case %s::%s appears %d times" % (idx, cls, name, len(sts)))
    for m, meta in sorted(ns["modules"].items()):
        ids = meta["node_ids"]
        dup = sorted(n for n in ids if len(executed.get(n, [])) > 1)
        missing = sorted(n for n in ids if n not in executed)
        foreign = sorted(n for n in executed if module_of_id(n) == m and n not in set(ids))
        if dup:
            problems.append("%s: nodes executed more than once: %s" % (m, dup[:5]))
        if missing:
            problems.append("%s: collected nodes never executed: %s" % (m, missing[:5]))
        if foreign:
            problems.append("%s: executed nodes outside the collection: %s" % (m, foreign[:5]))
    return problems


def _profile_diff(inventory, evidence):
    """Diagnostic only (the verdict is the digest comparison): which registrations / fields differ."""
    a, b = (inventory or {}).get("profile") or {}, evidence.get("profile") or {}
    if not a or not b:
        return ""
    ra = {json.dumps(r, sort_keys=True) for r in a.get("registrations", [])}
    rb = {json.dumps(r, sort_keys=True) for r in b.get("registrations", [])}
    fields = sorted(k for k in set(a) | set(b) if k != "registrations" and a.get(k) != b.get(k))
    return " (collection only: %s; execution only: %s; fields: %s)" % (sorted(ra - rb)[:4], sorted(rb - ra)[:4], fields)


def module_of_id(nodeid):
    return nodeid.split("::", 1)[0]


def aggregate(plan, shard_records, junit_paths, pytest_tier_skip_policy=None, node_evidence=None, inventory=None):
    """Return the result dict. ``shard_records``: list of {shard, sha, tree, plan_digest, modules, wall_s, runner_s}.

    A node plan (``plan["node_split"]``) additionally requires ``node_evidence`` ({shard index: evidence}) and an independent ``inventory``.
    """
    verify_plan_digest(plan)
    if not plan.get("tested_sha") or not plan.get("tested_tree"):
        raise AggregateError("plan lacks tested sha/tree")
    node_plan = "node_split" in plan or "units" in plan.get("schedule", {})
    split_modules = set(plan.get("node_split", {}).get("modules", {})) if node_plan else set()
    selected = {m[:-3].replace("/", "."): m for m in plan["pytest_modules"]}
    problems = []
    for r in shard_records:
        if r.get("sha") != plan["tested_sha"] or r.get("tree") != plan["tested_tree"] or r.get("plan_digest") != plan["digest"]:
            problems.append("shard %s evidence is bound to a different sha/tree/plan" % r.get("shard"))
        if node_plan and r.get("modules") != _expected_shard_modules(plan, r.get("shard")):
            problems.append("shard %s modules differ from the plan" % r.get("shard"))
    shard_modules = [m for r in shard_records for m in r.get("modules", []) if m not in split_modules]
    if sorted(shard_modules) != sorted(set(shard_modules)):
        problems.append("a module is assigned to more than one shard")
    shard_modules += sorted({m for r in shard_records for m in r.get("modules", []) if m in split_modules})
    if set(shard_modules) != set(plan["pytest_modules"]):
        problems.append("shard assignment differs from the plan (missing=%s foreign=%s)" % (
            sorted(set(plan["pytest_modules"]) - set(shard_modules))[:5], sorted(set(shard_modules) - set(plan["pytest_modules"]))[:5]))
    if node_plan:
        if set(split_modules) - set(plan["pytest_modules"]):
            problems.append("split modules outside the selection: %s" % sorted(set(split_modules) - set(plan["pytest_modules"])))
        junit_by_shard = {}
        for jp in junit_paths:
            name = Path(jp).name
            if name.startswith("junit-shard-") and name[len("junit-shard-"):-4].isdigit():
                idx = int(name[len("junit-shard-"):-4])
                if idx in junit_by_shard:
                    problems.append("duplicate junit for shard %d" % idx)
                junit_by_shard[idx] = read_junit(jp)
            else:
                problems.append("unexpected junit file %s in a node plan" % name)
        problems += verify_node_split(plan, shard_records, node_evidence or {}, junit_by_shard, inventory)
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
    ap.add_argument("--inventory", default=None, help="independent re-collection (python -m tools.ci_v4_nodes collect); required for a node plan")
    ap.add_argument("--run-id", default="0"); ap.add_argument("--run-attempt", default="1"); ap.add_argument("--finished-at", default="")
    a = ap.parse_args(argv)
    plan = json.loads(Path(a.plan).read_text())
    shards = [json.loads(p.read_text()) for p in sorted(Path(a.shards).glob("**/shard-*.json"))]
    junit = sorted(Path(a.junit).glob("**/*.xml"))
    try:
        if not junit or not shards:
            raise AggregateError("no shard evidence / junit found")
        evidence = {}
        for p in sorted(Path(a.shards).glob("**/nodes-shard-*.json")):
            idx = p.name[len("nodes-shard-"):-5]
            if not idx.isdigit() or int(idx) in evidence:
                raise AggregateError("unexpected or duplicate node evidence %s" % p.name)
            evidence[int(idx)] = json.loads(p.read_text())
        inventory = json.loads(Path(a.inventory).read_text()) if a.inventory else None
        res = aggregate(plan, shards, junit, a.max_skipped, node_evidence=evidence, inventory=inventory)
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
