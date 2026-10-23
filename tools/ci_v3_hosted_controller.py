"""Executable shadow stages. Requires independently pinned owner inputs; never merge authority."""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys

from tools.ci_v3_container import image_ref, observe_container
from tools.ci_v3_hosted_transport import GitHub, receive, sha, validate_run
from tools.ci_v3_isolation import constrained_plan, validate_isolation, verify_colocation
from tools.ci_v3_observed_verify import verify_files, verify_observed
from tools.ci_v3_real_contract import envelope, file_sha, git_source, producer_identity
from tools.ci_v3_schema import (ContractError, EVALUATOR, _pairs, _invalid_constant, check_seal,
    digest, read_json, reconcile_collection, require, validate_inventory, validate_plan, validate_policy, write_json)
from tools.ci_v3_shadow_local import ARTIFACTS, bridge_worker

STAGES = {"plan": "ci-v3-plan", **{f"worker-{i}": f"ci-v3-worker-{i}" for i in range(3)}}
BUNDLE_FILES = {"inventory", "policy", "weights", "isolation", "environment"}


def stage_names(root):
    prefix = "safety-and-smoke / " if root.get("execution_authority") == "mandatory" else ""
    return {k: prefix+v for k,v in STAGES.items()}


def decode(data):
    return json.loads(data, object_pairs_hook=_pairs, parse_constant=_invalid_constant)


def load_root(path, expected_sha):
    require(re.fullmatch(r"[0-9a-f]{64}", expected_sha or ""), "missing independent protected root pin")
    data = Path(path).read_bytes()
    require(sha(data) == expected_sha, "admission root substitution")
    root = decode(data)
    require(root.get("schema") == 3 and root.get("kind") == "ci-v3-hosted-admission", "admission root schema")
    require(root.get("enabled") is True, "hosted admission is closed; separate exact-content owner/deployment approval required")
    require(root.get("review_reference") and root.get("owner_decisions") == ["Financial", "Security", "CI"], "missing independent owner decision references")
    require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", root["repository"]), "repository identity")
    mandatory = root.get("execution_authority") == "mandatory"
    expected_path = ".github/workflows/public_safety_and_smoke.yml" if mandatory else ".github/workflows/ci_v3_shadow.yml"
    require(root["workflow_path"] == expected_path, "unauthorized workflow path")
    image_ref(root["image"])
    require(set(root["bundle"]["files"]) == BUNDLE_FILES, "incomplete approved bundle")
    require(root.get("experiment_pairs") == 1 and root.get("workers") == 3, "one-pair/three-worker admission only")
    calibration = root.get("target_calibration", {})
    require(calibration.get("ceiling_s") == 0.6 and calibration.get("statistic") == "maximum"
            and type(calibration.get("samples")) is int and 3 <= calibration["samples"] <= 30,
            "missing exact target calibration contract")
    require(root.get("execution_mode") in ("control", "shadow"), "missing control/shadow mode")
    if mandatory:
        from tools.ci_v3_mandatory import activation_check
        require(root["execution_mode"] == "shadow" and activation_check(root)["mode"] == "parallel", "mandatory activation closed")
        budget = root.get("production_budget_authorization", {})
        require(budget.get("approved") is True and budget.get("review_reference")
                and budget.get("run_id") == root["run_id"] and budget.get("attempt") == root["run_attempt"]
                and budget.get("source") == root["source"] and budget.get("maximum_minutes") == 375
                and budget.get("ancillary_accounting") == "separately-authorized"
                and type(budget.get("ancillary_max_minutes")) is int and budget["ancillary_max_minutes"] >= 75
                and budget.get("ancillary_review_reference"),
                "exact mandatory allocation unapproved")
    else:
        from tools.ci_v3_admission_budget import validate_spending
        validate_spending(root)
    return root


def load_bundle(api, root):
    bundle = {}
    for name, item in root["bundle"]["files"].items():
        data = api.content(root["bundle"]["repository"], root["bundle"]["revision"], item["path"])
        require(sha(data) == item["sha256"], "approved bundle substitution: " + name)
        bundle[name] = decode(data)
    validate_inventory(bundle["inventory"]); validate_policy(bundle["policy"], bundle["inventory"])
    from tools.ci_v3_admission_budget import validate_nonpass_decisions
    validate_nonpass_decisions(bundle["policy"],root.get("nonpass_owner_decisions",{}),root["source"])
    require(bundle["isolation"].get("allowed_daemon_threads",{}) == {}, "final admission forbids name-only survivor permissions")
    check_seal(bundle["weights"], "ci-v3-weights")
    if "environment_digest" in bundle["weights"]:
        require(bundle["weights"]["environment_digest"] == digest(bundle["environment"]), "stale weight environment")
    require(bundle["inventory"]["source"] == root["source"] and bundle["inventory"]["repository"] == root["repository"], "stale source inventory")
    require(bundle["isolation"].get("digest") == digest({k: v for k, v in bundle["isolation"].items() if k != "digest"}), "isolation digest mismatch")
    if root.get("execution_authority") == "mandatory":
        decisions=root["accepted_pair_proof"]["accepted_decisions"]
        for name,decision in (("policy","nonpass"),("isolation","isolation"),("environment","environment")):
            require(digest(bundle[name])==decisions[decision]["sha256"], "mandatory approved bundle changed: "+name)
    return bundle


def validate_controller(root):
    controller = Path(__file__).resolve().parents[1]
    try:
        actual = git_source(controller)
    except subprocess.CalledProcessError as exc:
        raise ContractError("controller source identity unavailable") from exc
    require(actual == {"head": root["controller_head"], "tree": root["controller_tree"]}, "wrong/modified controller checkout")
    files = {p.relative_to(controller).as_posix(): file_sha(p) for p in (controller / "tools").rglob("*.py")}
    require(files == root["controller_files_sha256"], "wrong evaluator/bootstrap content")


def validate_merge(api, root):
    if root["pr_number"] is None:
        main = api.get(f"/repos/{root['repository']}/branches/main")
        require(main["commit"]["sha"] == root["source"]["head"], "main-head source is not independently observed main")
        require(root["merge_proof"] == {"mode": "main-head", "merge_sha": None, "merge_tree": None}, "main merge proof")
    else:
        pr = api.get(f"/repos/{root['repository']}/pulls/{root['pr_number']}")
        proof = root["merge_proof"]
        require(pr["head"]["sha"] == root["source"]["head"] and pr["head"]["repo"]["full_name"] == root["repository"]
                and pr["merge_commit_sha"] == proof["merge_sha"] and proof["mode"] == "identical-tree", "PR/synthetic merge changed")
        merge = api.get(f"/repos/{root['repository']}/git/commits/{proof['merge_sha']}")
        require(merge["tree"]["sha"] == proof["merge_tree"] == root["source"]["tree"]
                and {p["sha"] for p in merge["parents"]} == {pr["head"]["sha"], pr["base"]["sha"]}, "synthetic merge tree/parents differ")


def context(root, bundle, plan, run_id, attempt):
    return {"repository": root["repository"], "pr_number": root["pr_number"], "workflow": root["workflow_path"],
        "run_id": str(run_id), "attempt": attempt, "mode": "recorded", "evaluator": EVALUATOR,
        "source": root["source"], "environment_digest": digest(bundle["environment"]),
        "inventory_digest": bundle["inventory"]["digest"], "policy_digest": bundle["policy"]["digest"],
        "plan_digest": plan["digest"], "merge_proof": root["merge_proof"]}


def receipt(path, stage, root_sha, ctx, observation, root):
    value = {"schema": 3, "kind": "ci-v3-isolated-host-receipt", "stage": stage,
        "root_sha256": root_sha, "context": ctx, "controller_head": root["controller_head"],
        "producer": producer_identity(), "observation": observation,
        "source_before": root["source"], "source_after": root["source"], "authoritative_acceptance": False}
    write_json(Path(path) / "receipt.json", value)
    return value


def validate_receipt(directory, stage, root_sha, ctx, root, execution_profile="docker-private-linux-posix-group-v1"):
    value = read_json(Path(directory) / "receipt.json")
    require(value["schema"] == 3 and value["kind"] == "ci-v3-isolated-host-receipt" and value["stage"] == stage
            and value["root_sha256"] == root_sha and value["context"] == ctx
            and value["controller_head"] == root["controller_head"], "host receipt provenance mismatch")
    require(value["producer"] == producer_identity(), "host evaluator substituted")
    require(value["source_before"] == value["source_after"] == root["source"], "host source changed")
    observed = value["observation"]
    require(observed.get("containment") == execution_profile and not observed.get("cancelled"), "unproved execution isolation/cleanup")
    if execution_profile == "docker-private-linux-posix-group-v1":
        require(observed.get("container_removed") is True and observed.get("image") == root["image"]
                and observed.get("source_bytes_unchanged") is True, "unproved container isolation/cleanup/source")
    else:
        require(value.get("synthetic_only") is True, "non-container evidence is limited to explicit synthetic fixtures")
    if stage != "plan" and execution_profile == "docker-private-linux-posix-group-v1":
        validate_calibration(Path(directory) / "child", root, ctx, observed)
    verify_files(Path(directory) / "child", observed["artifact_sha256"], set(ARTIFACTS) if stage != "plan" else set(ARTIFACTS) - {"results.xml", "execution.json"})
    return value


def make_plan(project, bundle):
    return constrained_plan(project, bundle["inventory"], bundle["policy"], bundle["weights"], bundle["isolation"])


def run_plan(root, root_sha, bundle, project, output, run_id, attempt):
    require(git_source(project) == root["source"], "wrong discovery checkout")
    plan = make_plan(project, bundle)
    ctx = context(root, bundle, plan, run_id, attempt)
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    child, observed = observe_container({"mode": "discover", "context": ctx, "worker": None}, output / "execution", project, root["image"], 600)
    report = read_json(child / "adapter.json")
    require(observed["normal_successful_exit"] and report["environment_digest"] == ctx["environment_digest"]
            and report["phases"] == [] and not report["unauthorized_deselection"], "discovery process/environment failed")
    reconcile_collection(bundle["inventory"], report["collection"])
    require(git_source(project) == root["source"], "discovery source changed")
    shutil.move(str(child), output / "child")
    observed["artifact_sha256"] = {p.name: file_sha(p) for p in (output / "child").iterdir() if p.is_file() and p.name in ARTIFACTS}
    # Do not transfer copies of source/.git/bootstrap into the artifact.
    shutil.rmtree(output / "execution")
    write_json(output / "plan.json", plan); write_json(output / "collection.json", report["collection"])
    observed["plan_sha256"] = file_sha(output / "plan.json"); observed["collection_sha256"] = file_sha(output / "collection.json")
    receipt(output, "plan", root_sha, ctx, observed, root)
    return ctx


def read_plan(directory, root, root_sha, bundle, project, run_id, attempt, execution_profile="docker-private-linux-posix-group-v1"):
    plan = read_json(Path(directory) / "plan.json")
    validate_plan(plan, bundle["inventory"], bundle["policy"])
    verify_colocation(plan, validate_isolation(project, bundle["inventory"], bundle["isolation"]))
    require(plan["isolation_digest"] == bundle["isolation"]["digest"] and plan["worker_count"] == 3
            and plan["weights_digest"] == bundle["weights"]["digest"], "wrong partition contract")
    ctx = context(root, bundle, plan, run_id, attempt)
    value = validate_receipt(directory, "plan", root_sha, ctx, root, execution_profile)
    observed = value["observation"]
    require(file_sha(Path(directory) / "plan.json") == observed["plan_sha256"]
            and file_sha(Path(directory) / "collection.json") == observed["collection_sha256"], "plan/collection substituted")
    reconcile_collection(bundle["inventory"], read_json(Path(directory) / "collection.json"))
    return plan, ctx, value


def worker_request(ctx, worker, bundle, modules):
    """The worker request comes from the approved bundle only; the allowlist is never supplied by the worker."""
    return {"mode": "worker", "context": ctx, "worker": worker, "inventory": bundle["inventory"], "owned_modules": modules,
            "allowed_daemon_threads": bundle["isolation"].get("allowed_daemon_threads", {})}


def validate_calibration(directory, root, ctx, observed):
    path = Path(directory) / "calibration.json"
    require(file_sha(path) == observed.get("calibration_sha256"), "target calibration bytes missing/substituted")
    value = read_json(path)
    samples = value.get("samples_s", [])
    contract = root["target_calibration"]
    require(value.get("context") == ctx and len(samples) == contract["samples"]
            and all(type(x) in (int, float) and math.isfinite(x) and 0 < x <= .6 for x in samples)
            and value.get("ceiling_s") == .6 and value.get("acceptance_statistic") == "maximum"
            and value.get("meets_test_assumption") is True, "target readiness calibration failed/stale")
    return value


def run_worker(root, root_sha, bundle, project, plan_directory, worker, output, run_id, attempt):
    require(root.get("execution_mode") == "shadow", "control authorization cannot run shadow workers")
    require(worker in STAGES and worker != "plan", "unexpected worker")
    require(git_source(project) == root["source"], "wrong worker checkout")
    plan, ctx, _ = read_plan(plan_directory, root, root_sha, bundle, project, run_id, attempt)
    modules = sorted(m for m, owner in plan["module_workers"].items() if owner == worker)
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    request = worker_request(ctx, worker, bundle, modules)
    request["target_calibration"] = root["target_calibration"]
    child, observed = observe_container(request, output / "execution", project, root["image"], 4800)
    observed = bridge_worker(child, observed, ctx)
    observed["calibration_sha256"] = file_sha(child / "calibration.json")
    validate_calibration(child, root, ctx, observed)
    shutil.move(str(child), output / "child"); shutil.rmtree(output / "execution")
    require(git_source(project) == root["source"], "worker source changed")
    receipt(output, worker, root_sha, ctx, observed, root)
    require(observed["normal_successful_exit"] and not observed["adapter_errors"], "worker failed; retain failure evidence")
    return ctx


def run_control(root, root_sha, bundle, project, output, run_id, attempt):
    """One full unsharded advisory control in the same contained runtime."""
    require(root.get("execution_mode") == "control", "shadow authorization cannot run full control")
    require(git_source(project) == root["source"], "wrong control checkout")
    plan = make_plan(project, bundle)
    ctx = context(root, bundle, plan, run_id, attempt)
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    request = worker_request(ctx, "control", bundle, sorted(bundle["inventory"]["modules"]))
    request["target_calibration"] = root["target_calibration"]
    child, observed = observe_container(request, output / "execution", project, root["image"], 12600)
    observed = bridge_worker(child, observed, ctx)
    observed["calibration_sha256"] = file_sha(child / "calibration.json")
    validate_calibration(child, root, ctx, observed)
    shutil.move(str(child), output / "child"); shutil.rmtree(output / "execution")
    require(git_source(project) == root["source"], "control source changed")
    write_json(output / "plan.json", plan)
    observed["plan_sha256"] = file_sha(output / "plan.json")
    receipt(output, "control", root_sha, ctx, observed, root)
    require(observed["normal_successful_exit"] and not observed["adapter_errors"], "control failed")
    return ctx


def aggregate(root, root_sha, bundle, project, received, output, run_id, attempt, transport,
              execution_profile="docker-private-linux-posix-group-v1", service_api=None):
    """Independent full-node verification; never recompute planner selections from totals."""
    require(set(transport["receipts"]) == set(STAGES), "incomplete independently authenticated worker set")
    require(execution_profile == "docker-private-linux-posix-group-v1" or transport["provenance_authenticated"] is False,
            "local synthetic execution cannot claim hosted provenance")
    received, output = Path(received), Path(output)
    plan, ctx, discovery = read_plan(received / "plan", root, root_sha, bundle, project, run_id, attempt, execution_profile)
    output.mkdir(parents=True, exist_ok=False)
    for name in ("inventory", "policy"):
        write_json(output / (name + ".json"), bundle[name])
    write_json(output / "plan.json", plan)
    shutil.copyfile(received / "plan/collection.json", output / "collection.json")
    trust = {"schema": 1, "kind": "ci-v3-trust-input", "context": ctx}
    write_json(output / "trust.json", trust)
    shutil.copytree(received / "plan/child", output / "discovery")
    workers = {}
    for worker in sorted(set(STAGES) - {"plan"}):
        value = validate_receipt(received / worker, worker, root_sha, ctx, root, execution_profile)
        workers[worker] = value["observation"]
        shutil.copytree(received / worker / "child", output / "workers" / worker)
    local = envelope("ci-v3-parent-observations", context=ctx, producer=producer_identity(),
        source_before=root["source"], source_after=root["source"], environment=bundle["environment"],
        discovery=discovery["observation"], workers=workers, controller_error=None, authority="local-non-authoritative")
    write_json(output / "observations.json", local)
    checked = verify_observed(output, file_sha(output / "observations.json"), trust, producer_identity())
    proof = {"schema": 3, "kind": "ci-v3-hosted-shadow-proof", "coverage_valid": True,
        "authoritative_acceptance": False, "root_sha256": root_sha, "context": ctx,
        "transport": transport, "execution": checked,
        "execution_profile": execution_profile,
        "warning": "Advisory only. No mandatory, financial, security or merge acceptance."}
    if root.get("execution_authority") == "mandatory":
        from tools.ci_v3_mandatory import verify_current_phases
        phase = verify_current_phases({**root, "_root_sha256":root_sha},bundle,project,received,output/"accepted-control-comparison",service_api or GitHub())
        proof["mandatory_execution_valid"] = phase["phase_equivalent"]
        proof["mandatory_phase_comparison"] = phase
        proof["warning"] = "Requires exact protected Financial/Security/CI activation authority and independent required-gate verification."
    write_json(output / "shadow-proof.json", proof)
    return proof


def anchors_from_env(expected):
    value = decode(os.environ.get("CI_V3_HOST_ANCHORS", "{}"))
    require(set(value) == set(expected), "independent host outputs missing")
    for anchor in value.values():
        for key in ("artifact_id", "job_id"):
            require(str(anchor[key]).isdigit(), "invalid service identity anchor")
            anchor[key] = int(anchor[key])
    return value


def write_outputs(values):
    target = os.environ.get("GITHUB_OUTPUT")
    require(target, "protected host output channel missing")
    with open(target, "a", encoding="utf-8") as file:
        for key, value in values.items():
            require("\n" not in str(value) and "\r" not in str(value), "unsafe host output")
            file.write(f"{key}={value}\n")


def prune_failed_workspace(output):
    """Retain reports/host diagnostics, never upload disposable source/history copies."""
    output = Path(output).resolve()
    for relative in ("execution/source", "execution/bootstrap"):
        target = output / relative
        require(target.resolve().is_relative_to(output) and not target.is_symlink(), "unsafe cleanup scope")
        if target.exists():
            shutil.rmtree(target)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("admit", "plan", "worker", "aggregate", "outputs", "pull-image", "control"))
    parser.add_argument("--root", required=True); parser.add_argument("--root-sha256", required=True)
    parser.add_argument("--project"); parser.add_argument("--output", required=True)
    parser.add_argument("--worker", choices=("worker-0", "worker-1", "worker-2", "control"))
    args = parser.parse_args(argv)
    output = Path(args.output).resolve()
    try:
        root = load_root(args.root, args.root_sha256)
        api = GitHub(); run_id = int(os.environ["GITHUB_RUN_ID"]); attempt = int(os.environ["GITHUB_RUN_ATTEMPT"])
        validate_run(api, root, run_id, attempt); validate_merge(api, root); validate_controller(root)
        bundle = load_bundle(api, root)
        if args.stage == "admit":
            require(os.environ.get("CI_V3_REQUESTED_HEAD") == root["source"]["head"], "input is not approved tested source")
            require(os.environ.get("CI_V3_REQUESTED_MODE") == root["execution_mode"], "mode lacks exact run authorization")
            write_outputs({"tested_sha": root["source"]["head"], "controller_sha": root["controller_head"],
                "root_sha256": args.root_sha256, "root_b64": base64.b64encode(Path(args.root).read_bytes()).decode(),
                "image": root["image"], "execution_mode": root["execution_mode"]})
            write_json(output / "admission.json", {"root_sha256": args.root_sha256, "admitted": True,
                "run_id": run_id, "attempt": attempt, "authoritative_acceptance": False})
        elif args.stage == "pull-image":
            require(sys.platform == "linux", "hosted image requires Linux")
            subprocess.run(["docker", "pull", root["image"]], check=True, timeout=600)
        elif args.stage == "outputs":
            stage = args.worker or "plan"
            jobs = api.listing(f"/repos/{root['repository']}/actions/runs/{run_id}/attempts/{attempt}/jobs", "jobs")
            expected_job = "ci-v3-control" if stage == "control" else stage_names(root)[stage]
            jobs = [j for j in jobs if j["name"] == expected_job and j["run_attempt"] == attempt]
            require(len(jobs) == 1, "ambiguous current host job")
            write_outputs({"receipt_sha256": file_sha(output / "receipt.json"), "job_id": jobs[0]["id"]})
        elif args.stage == "control":
            run_control(root, args.root_sha256, bundle, Path(args.project), output, run_id, attempt)
        elif args.stage == "plan":
            run_plan(root, args.root_sha256, bundle, Path(args.project), output, run_id, attempt)
        else:
            expected = {"plan": stage_names(root)["plan"]} if args.stage == "worker" else stage_names(root)
            received = output.parent / (output.name + "-received")
            transport = receive(api, root, run_id, attempt, anchors_from_env(expected), received, expected)
            if args.stage == "worker":
                run_worker(root, args.root_sha256, bundle, Path(args.project), received / "plan", args.worker, output, run_id, attempt)
            else:
                aggregate(root, args.root_sha256, bundle, Path(args.project), received, output, run_id, attempt, transport, service_api=api)
        print("CI_V3_STAGE_COMPLETE; AUTHORITATIVE_ACCEPTANCE=false")
        return 0
    except (ContractError, OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError) as exc:
        prune_failed_workspace(output)
        write_json(output / "rejection.json", {"coverage_valid": False,
            "authoritative_acceptance": False, "stage": args.stage, "reason": str(exc)})
        print("CI_V3_HOSTED_REJECTED: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    def terminate(signum, frame):
        raise KeyboardInterrupt("host cancellation")
    signal.signal(signal.SIGTERM, terminate)
    sys.exit(main())
