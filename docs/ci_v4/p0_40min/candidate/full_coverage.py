"""Inert FULL coverage verifier candidate. No routing, policy or activation hook.

Run explicitly outside ordinary pytest collection. The caller must authenticate
the historical baseline and all current artifacts against GitHub, then pass the
sealed current plan and original worker reports here. A digest is byte integrity,
not service authentication. This module never claims a green hosted FULL.
"""
from __future__ import annotations

from collections import Counter
import hashlib

from tools.ci_v3_phase_compare import phase_map, native_cases
from tools.ci_v3_pytest_config import PLUGINS, semantic_plugin_profile
from tools.ci_v3_real_contract import check_envelope, outcome
from tools.ci_v3_schema import (check_seal, require, skip_counter, validate_inventory,
                                validate_plan, seal, worker_count)


def validate_context(ctx):
    require(isinstance(ctx, dict) and set(ctx) == {"source", "repository", "run_id", "attempt"}, "context shape")
    require(ctx["repository"] == "Finco-Protocol/FincoProtocol", "foreign repository")
    require(isinstance(ctx["run_id"], str) and ctx["run_id"].isdecimal() and int(ctx["run_id"]) > 0, "run identity")
    require(type(ctx["attempt"]) is int and ctx["attempt"] > 0, "attempt identity")


def make_plan(inventory, policy, weights, context, image_digest, runtime_archive_digest, groups=None, workers=8):
    """Reuse the whole-module planner; require a complete collection externally.

    Every module stays indivisible. The new plan has no accepted-source green
    reference, so it cannot depend on a green FULL of its own source.
    """
    from tools.ci_v3_partition_plan import plan_partitions
    validate_context(context)
    validate_inventory(inventory)
    require(inventory["source"] == context["source"], "collection source")
    for value in (image_digest, runtime_archive_digest):
        require(isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value), "runtime digest")
    plan = plan_partitions(inventory, policy, weights, workers=workers, groups=groups)
    require(set(plan["module_workers"].values()) == {f"worker-{i}" for i in range(workers)}, "empty worker")
    return seal({"schema": 1, "kind": "ci-v4-full-plan-candidate", "context": context,
                 "inventory": inventory, "policy": policy, "weights": weights, "plan": plan,
                 "groups": groups or {}, "image_digest": image_digest,
                 "runtime_archive_digest": runtime_archive_digest,
                 "activation": "NOT_ACTIVATED"})


def validate_full_plan(bundle):
    from tools.ci_v3_partition_plan import plan_partitions
    check_seal(bundle, "ci-v4-full-plan-candidate")
    ctx, inv, plan = bundle["context"], bundle["inventory"], bundle["plan"]
    validate_context(ctx)
    for value in (bundle["image_digest"], bundle["runtime_archive_digest"]):
        require(isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value), "runtime digest")
    validate_inventory(inv)
    require(inv["source"] == ctx["source"], "inventory context source")
    validate_plan(plan, inv, bundle["policy"])
    # Re-derive both ownership and grouping; a re-sealed forged assignment fails.
    expected = plan_partitions(inv, bundle["policy"], bundle["weights"],
                               workers=plan["worker_count"], groups=bundle["groups"])
    require(expected == plan, "ownership/group/weight plan drift")
    require(not bundle["policy"]["module_overlaps"], "FULL requires disjoint ownership")
    require(set(plan["module_workers"].values()) == {f"worker-{i}" for i in range(worker_count(plan["worker_count"]))}, "empty worker")
    require(bundle["activation"] == "NOT_ACTIVATED", "candidate cannot certify activation")
    return ctx, inv, plan


def verify(bundle, workers, baseline_report, baseline_junit, environment, plugins, transition=None):
    """Verify actual phases/native XML and exact once-only full coverage.

    `workers` contains {index, binding, report, junit, process}. Service archive
    digests and producer jobs must be independently authenticated by a separate
    trusted controller before this pure data verifier is eligible for use.
    `transition` is an explicit controller callback to the UNCHANGED D-029
    verifier, over immutable source facts and ALL same-run phases/native cases.
    It is considered only for the exact D-029 node and skip -> pass shape.
    """
    ctx, inv, plan = validate_full_plan(bundle)
    require(len(workers) == plan["worker_count"], "missing/extra worker")
    require({w["index"] for w in workers} == set(range(plan["worker_count"])), "duplicate/foreign worker index")
    old = phase_map(baseline_report)
    old_native = native_cases(baseline_junit, baseline_report)
    expected = {n["nodeid"] for n in inv["nodes"]}
    require(set(old) <= expected, "historical inventory removed")
    require(not baseline_report.get("deselected") and baseline_report["pytest_exitstatus"] == 0, "incomplete historical baseline")
    require(set(baseline_report["selected"]) == set(baseline_report["collection"]["nodes"]), "partial historical baseline")
    require(baseline_report["collection"]["complete"] and not baseline_report["collection"]["errors"], "historical collection errors")
    seen, native, receipts, counts = {}, {}, [], Counter()
    for worker in sorted(workers, key=lambda w: w["index"]):
        index, report, proc = worker["index"], worker["report"], worker["process"]
        require(type(index) is int, "worker index type")
        require(worker["binding"] == {"context": ctx, "worker": index,
                "bundle_digest": bundle["digest"], "image_digest": bundle["image_digest"],
                "runtime_archive_digest": bundle["runtime_archive_digest"]}, "worker binding drift")
        check_envelope(report, "ci-v3-pytest-report")
        require(report["context"] == ctx and report["mode"] == "worker" and report["worker"] == f"worker-{index}", "report binding drift")
        cleanup = proc.get("descendant_cleanup", {})
        require(proc.get("normal_successful_exit") is True and proc.get("container_removed") is True
                and proc.get("source_bytes_unchanged") is True and not proc.get("timed_out", False), "worker exit/timeout/source")
        require(cleanup.get("cleanup_verified") is True and cleanup.get("survivors_observed") == cleanup.get("survivors_remaining") == [], "descendant cleanup")
        from tools.ci_v3_calibrate import STEADY_STATE_CONTRACT, evaluate
        calibration = worker.get("calibration", {})
        require(calibration.get("context") == ctx and calibration.get("contract") == STEADY_STATE_CONTRACT
                and evaluate(calibration.get("samples_s"), STEADY_STATE_CONTRACT)["meets_test_assumption"] is True,
                "worker calibration")
        require(report["pytest_exitstatus"] == 0 and not report["unauthorized_deselection"], "worker pytest exit/deselection")
        c = report["collection"]
        require(c["source"] == ctx["source"] and c["complete"] and not c["errors"], "worker collection source/errors")
        require(Counter(c["nodes"]) == Counter(expected), "worker full inventory drift")
        require(skip_counter(c["skips"]) == skip_counter(inv["collection_skips"]), "collection skip drift")
        owned = {n for n in expected if plan["module_workers"][n.split("::")[0]] == f"worker-{index}"}
        require(Counter(report["selected"]) == Counter(owned), "lost/duplicate/foreign ownership")
        require(Counter(report["deselected"]) == Counter(expected - owned), "unplanned deselection")
        require(report["environment"] == environment and report["pytest_plugins"] == list(PLUGINS), "runtime/plugin configuration drift")
        require(semantic_plugin_profile(report["plugin_registrations"]) == plugins, "plugin implementation drift")
        phases = phase_map(report)
        require(not set(seen) & set(phases), "duplicate executed node")
        seen.update(phases)
        native.update(native_cases(worker["junit"], report))
        receipts.append({"worker": index, "junit_sha256": hashlib.sha256(worker["junit"]).hexdigest(), "nodes": len(phases)})
    require(set(seen) == expected == set(native), "incomplete FULL inventory")
    from tools.ci_v3_production import D029_NODE
    for node, phases in seen.items():
        status = outcome(phases)["status"]
        require(status in ("passed", "skipped", "xfail"), "failure/error/xpass")
        if node in old:
            same = phases == old[node] and native[node] == old_native[node]
            if not same:
                require(node == D029_NODE and outcome(old[node])["status"] == "skipped"
                        and status == "passed" and native[node][0] == "passed"
                        and callable(transition) and transition(node, old[node], old_native[node], phases,
                                      native[node], seen, native) is True, "historical outcome regression")
        else:
            require(status == "passed", "new nonpass has no reviewed authority")
        counts[status] += 1
    require(skip_counter(inv["collection_skips"]) == skip_counter(baseline_report["collection"]["skips"]), "new collection skip has no reviewed authority")
    return seal({"schema": 1, "kind": "ci-v4-full-coverage-candidate", "context": ctx,
                 "bundle_digest": bundle["digest"], "inventory_digest": inv["digest"],
                 "collected": len(expected), "executed": len(seen), "counts": dict(counts),
                 "junit": receipts, "coverage": "FULL_COVERAGE_VERIFIED_LOCAL_DATA_ONLY",
                 "hosted_full": "NOT_PROVEN", "activation": "NOT_ACTIVATED"})


def verify_service_artifacts(bundle, run, jobs, artifacts, archives):
    """Pure half of independent GitHub authentication; no cached-name download.

    The caller fetches this run/attempt's live metadata and archive bytes using
    the read-only API. No ID, digest or producer comes from a worker claim.
    """
    ctx, _, plan = validate_full_plan(bundle)
    require(run["id"] == int(ctx["run_id"]) and run["run_attempt"] == ctx["attempt"]
            and run["head_sha"] == ctx["source"]["head"], "service run/attempt/source")
    require(run["path"] == ".github/workflows/ci_v4_full.yml" and run["event"] in ("workflow_dispatch", "schedule"), "service workflow/event")
    require(run["repository"]["full_name"] == run["head_repository"]["full_name"] == ctx["repository"], "service repository")
    suffix = f"-attempt-{ctx['attempt']}"
    names = {f"public-ci-v4-full-plan{suffix}": "plan"}
    names.update({f"public-ci-v4-full-worker-{i}{suffix}": f"worker-{i}" for i in range(plan["worker_count"])})
    require(Counter(a["name"] for a in artifacts) == Counter(names.keys()), "missing/duplicate/foreign service artifact")
    require(len({a["id"] for a in artifacts}) == len(names) and set(archives) == {a["id"] for a in artifacts}, "archive identity set")
    for artifact in artifacts:
        require(artifact.get("expired") is False and artifact["workflow_run"]["id"] == run["id"]
                and artifact["workflow_run"]["head_sha"] == run["head_sha"], "artifact expiration/run/source")
        producer = names[artifact["name"]]
        matches = [j for j in jobs if j["name"] == producer or j["name"].endswith("/ " + producer)]
        require(len(matches) == 1 and matches[0]["status"] == "completed" and matches[0]["conclusion"] == "success"
                and matches[0]["run_id"] == run["id"] and matches[0]["run_attempt"] == ctx["attempt"], "artifact producer not successful at this attempt")
        require(artifact["digest"] == "sha256:" + hashlib.sha256(archives[artifact["id"]]).hexdigest(), "archive digest")
    # Archive safe extraction and byte-for-byte comparison with worker inputs
    # remains mandatory in the controller; this function does not attest that.
    return True
