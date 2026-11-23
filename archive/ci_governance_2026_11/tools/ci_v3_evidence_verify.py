"""Independent offline coverage verifier; a valid result NEVER grants CI acceptance.

Consumes data only. It does not import the planner, invoke pytest, launch workers,
fetch GitHub artifacts, or trust a reported aggregate success flag.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

from tools.ci_v3_schema import (
    ContractError, EVALUATOR, SCHEMA, check_seal, digest, hash_value, integer,
    read_json, reconcile_collection, require, seal, skip_counter, skip_key, source,
    validate_inventory, validate_plan, validate_policy, write_json,
)


def validate_trust(trust, inventory, policy, plan):
    require(isinstance(trust, dict) and trust.get("schema") == SCHEMA
            and trust.get("kind") == "ci-v3-trust-input", "trust input missing")
    context = trust.get("context")
    keys = {"repository", "pr_number", "workflow", "run_id", "attempt", "mode", "evaluator",
            "source", "environment_digest", "inventory_digest", "policy_digest", "plan_digest", "merge_proof"}
    require(isinstance(context, dict) and set(context) == keys, "trust context shape")
    require(context["source"] == inventory["source"], "trusted source mismatch")
    source(context["source"])
    require(context["repository"] == inventory["repository"], "trusted repository mismatch")
    require(context["evaluator"] == EVALUATOR, "wrong evaluator version")
    for field, value in (("inventory_digest", inventory), ("policy_digest", policy), ("plan_digest", plan)):
        require(context[field] == value["digest"], "trusted " + field + " mismatch")
    require(context["mode"] in ("simulated", "recorded"), "unknown evidence mode")
    for key in ("workflow", "run_id"):
        require(isinstance(context[key], str) and context[key], key + " missing")
    integer(context["attempt"], "attempt", 1)
    hash_value(context["environment_digest"], "environment")
    proof = context["merge_proof"]
    require(isinstance(proof, dict) and set(proof) == {"mode", "merge_sha", "merge_tree"}, "merge proof shape")
    if context["pr_number"] is None:
        require(proof == {"mode": "main-head", "merge_sha": None, "merge_tree": None}, "main merge proof mismatch")
    else:
        integer(context["pr_number"], "PR number", 1)
        hash_value(proof["merge_sha"], "merge SHA", 40)
        require(proof["mode"] == "identical-tree" and proof["merge_tree"] == inventory["source"]["tree"],
                "synthetic merge tree mismatch")
    return context


def verify_process(process):
    require(isinstance(process, dict), "missing process evidence")
    for field in ("exit_code", "pytest_return_code", "child_exit_code"):
        require(type(process.get(field)) is int and process[field] == 0, "process return marker: " + field)
    require(process.get("normal_exit") is True and process.get("timed_out") is False,
            "process timeout or absent normal exit")
    for field in ("pytest_started_ms", "pytest_returned_ms", "child_exited_ms", "elapsed_ms"):
        integer(process.get(field), "process marker " + field)
    require(process["pytest_started_ms"] <= process["pytest_returned_ms"]
            <= process["child_exited_ms"] <= process["elapsed_ms"], "process marker order")


def junit_records(data):
    """Dedicated V3 JUnit identity properties preserve even unusual parameter strings.

    Old JUnit cannot establish full node identity on its own; Phase 2 needs an
    explicitly reviewed adapter. JSON-escaped identity properties avoid XML's
    attribute whitespace/control-character normalization of raw node IDs.
    """
    require(isinstance(data, bytes) and len(data) <= 128 * 1024 * 1024, "JUnit size/type")
    try:
        text = data.decode("utf-8")
        require("<!DOCTYPE" not in text.upper() and "<!ENTITY" not in text.upper(), "JUnit DTD/entity forbidden")
        root = ET.fromstring(text)
    except (UnicodeError, ET.ParseError) as exc:
        raise ContractError("invalid or truncated JUnit") from exc
    require(not any(e.tag in ("failure", "error") for e in root.iter()), "JUnit contains failure/error")
    if root.tag == "testsuites":
        require(len(root) > 0 and all(x.tag == "testsuite" for x in root), "JUnit suite shape")
        suites = list(root)
    else:
        require(root.tag == "testsuite", "JUnit root shape")
        suites = [root]
    result = []
    total_skips = 0
    for suite in suites:
        require(all(c.tag in ("testcase", "properties", "system-out", "system-err") for c in suite),
                "unexpected JUnit suite child")
        cases = list(suite.findall("testcase"))
        skips = 0
        for case in cases:
            require(all(c.tag in ("properties", "skipped", "system-out", "system-err") for c in case),
                    "JUnit test failure/error or unknown child")
            require(len(case.findall("properties")) == 1, "JUnit identity properties missing/duplicate")
            properties = case.find("properties")
            require(all(p.tag == "property" for p in properties), "invalid JUnit properties")
            identities = [p.get("value") for p in properties if p.get("name") == "ci_v3_identity"]
            require(len(identities) == 1, "JUnit exact identity missing/duplicate")
            try:
                identity = json.loads(identities[0])
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid JUnit identity") from exc
            require(isinstance(identity, list) and len(identity) == 2
                    and identity[0] in ("node", "collection-skip")
                    and isinstance(identity[1], str) and identity[1], "JUnit identity shape")
            skipped = case.findall("skipped")
            require(len(skipped) <= 1, "multiple JUnit skip outcomes")
            status, reason = "passed", ""
            if skipped:
                skips += 1
                require(skipped[0].get("type") in ("pytest.skip", "pytest.xfail"), "JUnit unexpected skip type")
                status = "xfail" if skipped[0].get("type") == "pytest.xfail" else "skipped"
                # Reasons use JSON in the V3 property too, avoiding XML normalization.
                reasons = [p.get("value") for p in properties if p.get("name") == "ci_v3_reason"]
                require(len(reasons) == 1, "JUnit skip reason missing/duplicate")
                try:
                    reason = json.loads(reasons[0])
                except (TypeError, ValueError) as exc:
                    raise ContractError("invalid JUnit reason") from exc
                require(isinstance(reason, str) and reason, "JUnit empty skip reason")
            result.append((identity[0], identity[1], status, reason))
        for name, expected in (("tests", len(cases)), ("failures", 0), ("errors", 0), ("skipped", skips)):
            require(suite.get(name) == str(expected), "JUnit suite count/outcome mismatch: " + name)
        total_skips += skips
    if root.tag == "testsuites":
        for name, expected in (("tests", len(result)), ("failures", 0), ("errors", 0), ("skipped", total_skips)):
            if name in root.attrib:
                require(root.get(name) == str(expected), "JUnit aggregate count mismatch")
    require(sum(1 for _ in root.iter("testcase")) == len(result), "JUnit hidden/nested testcase")
    return result


def verify_execution(inventory, policy, plan, collection, workers, trust):
    known = validate_inventory(inventory)
    validate_policy(policy, inventory)
    names = validate_plan(plan, inventory, policy)
    context = validate_trust(trust, inventory, policy, plan)
    reconcile_collection(inventory, collection)
    require(isinstance(workers, list) and len(workers) == len(names), "missing/extra worker")
    expected = {w: Counter() for w in names}
    for node, item in known.items():
        module = item["module"]
        for owner in [plan["module_workers"][module], *policy["module_overlaps"].get(module, [])]:
            expected[owner][node] += 1
    actual_union = Counter()
    observed = set()
    expected_skips = skip_counter(inventory["collection_skips"])
    artifact_digests = {}
    for evidence, junit in workers:
        check_seal(evidence, "ci-v3-worker-evidence")
        worker = evidence.get("worker")
        require(isinstance(worker, str) and worker in names and worker not in observed,
                "unknown/duplicate worker identity")
        observed.add(worker)
        require(evidence.get("context") == context, "worker source/policy/environment/run/attempt lineage mismatch")
        require(evidence.get("complete") is True and evidence.get("job_result") == "success", "failed/incomplete worker")
        reconcile_collection(inventory, evidence.get("collection"))
        verify_process(evidence.get("process"))
        require(isinstance(junit, bytes) and evidence.get("junit_sha256") == hashlib.sha256(junit).hexdigest(),
                "JUnit checksum mismatch")
        records = evidence.get("executions")
        require(isinstance(records, list), "execution records missing")
        actual = Counter()
        outcomes = {}
        for rec in records:
            require(isinstance(rec, dict) and set(rec) == {"nodeid", "status", "reason"}, "execution record shape")
            node = rec["nodeid"]
            require(isinstance(node, str) and node in known, "foreign/substituted/truncated node")
            actual[node] += 1
            require(rec["status"] in ("passed", "skipped", "xfail"), "failed/error/xpass test")
            require(isinstance(rec["reason"], str), "invalid outcome reason")
            authorized = policy["allowed_nonpass"].get(node)
            if rec["status"] == "passed":
                require(authorized is None and rec["reason"] == "", "changed baseline skip/xfail or pass reason")
            else:
                require(authorized == {"status": rec["status"], "reason": rec["reason"]}, "unexpected skip/xfail")
            outcomes[node] = (rec["status"], rec["reason"])
        require(actual == expected[worker], "worker node multiset mismatch: missing/duplicate/wrong owner")
        junit_nodes = Counter()
        junit_skips = Counter()
        for kind, identity, status, reason in junit_records(junit):
            if kind == "node":
                junit_nodes[identity] += 1
                require(identity in outcomes and outcomes[identity] == (status, reason), "JUnit identity/outcome mismatch")
            else:
                require(status == "skipped", "collection skip not represented as skip")
                junit_skips[identity] += 1
                require(any(skip_key(s) == identity and s["reason"] == reason for s in inventory["collection_skips"]),
                        "unexpected JUnit collection skip/reason")
        require(junit_nodes == actual, "JUnit missing/duplicate/substituted node")
        require(junit_skips == expected_skips, "JUnit missing/unexpected collection skip")
        artifact_digests[worker] = {"execution_digest": evidence["digest"],
                                    "junit_sha256": evidence["junit_sha256"]}
        actual_union.update(actual)
    require(observed == set(names), "missing required worker")
    expected_union = sum(expected.values(), Counter())
    require(actual_union == expected_union, "aggregate test multiset mismatch")
    return seal({"schema": SCHEMA, "kind": "ci-v3-offline-verification",
                 "evaluator": EVALUATOR, "mode": context["mode"], "coverage_valid": True,
                 "authoritative_acceptance": False, "context_digest": digest(context),
                 "inventory_digest": inventory["digest"], "plan_digest": plan["digest"],
                 "unique_nodes": len(known), "executions": sum(actual_union.values()),
                 "collection_skips_per_worker": sum(expected_skips.values()), "workers": names,
                 "worker_artifacts": artifact_digests, "fresh_collection_digest": digest(collection),
                 "warning": "Offline contract validation only; no financial/security/merge acceptance granted."})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("inventory", "policy", "plan", "collection", "trust", "evidence", "output"):
        parser.add_argument("--" + option, required=True)
    args = parser.parse_args(argv)
    try:
        inventory, policy, plan = (read_json(p) for p in (args.inventory, args.policy, args.plan))
        names = validate_plan(plan, inventory, policy)
        root = Path(args.evidence)
        require(root.is_dir() and {p.name for p in root.iterdir()} == set(names), "evidence worker directory mismatch")
        workers = []
        for w in names:
            directory = root / w
            require(not directory.is_symlink() and directory.is_dir(), "invalid worker evidence directory")
            require({p.name for p in directory.iterdir()} == {"execution.json", "results.xml"}, "unexpected/missing worker file")
            require(not any(p.is_symlink() for p in directory.iterdir()), "symlinked worker evidence")
            workers.append((read_json(directory / "execution.json"), (directory / "results.xml").read_bytes()))
        proof = verify_execution(inventory, policy, plan, read_json(args.collection), workers, read_json(args.trust))
        write_json(args.output, proof)
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        # Never leave an old valid-looking proof at the requested output path.
        write_json(args.output, seal({"schema": SCHEMA, "kind": "ci-v3-offline-rejection",
            "coverage_valid": False, "authoritative_acceptance": False, "reason": str(exc)}))
        print("CI_V3_OFFLINE_EVIDENCE_REJECTED: " + str(exc), file=sys.stderr)
        return 1
    print("CI_V3_OFFLINE_COVERAGE_VALID; AUTHORITATIVE_ACCEPTANCE=false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
