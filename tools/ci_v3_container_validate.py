"""Bounded real-container validation of the Phase 3A controller stages on a derived subset repository.

Runs the implemented plan/worker/aggregate stages with real Docker containers. Only GitHub service metadata is
mocked (provenance_authenticated stays false). A subset result is never complete FINCO coverage."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from tests.ci_v3_hosted_fixtures import FixtureAPI, archive
from tools.ci_v3_hosted_controller import STAGES, aggregate, context, run_plan, run_worker
from tools.ci_v3_hosted_transport import receive, sha
from tools.ci_v3_prepare import prepare
from tools.ci_v3_real_contract import file_sha
from tools.ci_v3_schema import ContractError, canonical_bytes, read_json, require, seal, write_json

RUN, ATTEMPT = 123, 2
WORKFLOW = (Path(__file__).resolve().parents[1] / "docs/ci_v3/phase3b/ci_v3_shadow.yml").read_bytes()
REVIEW = "BOUNDED LOCAL CONTAINER VALIDATION ONLY - not an owner isolation approval"


NEGATIVE = {
    "failure": ("tests/test_zz_ci_v3_negative_failure.py", "def test_failure_must_stay_a_failure():\n    assert 1 + 1 == 3\n"),
    "unapproved-skip": ("tests/test_zz_ci_v3_negative_skip.py", "import pytest\n\n\ndef test_unapproved_skip():\n    pytest.skip('unapproved runtime skip')\n"),
}


def make_subset(source_repo, modules, destination, inject=None):
    """Commit a derived project (full Git history, every file kept) whose tests/conftest.py ignores all
    other test modules at collection. Files stay present so imports and repository-citation tests resolve."""
    destination = Path(destination)
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(source_repo), str(destination)], check=True)
    git = ["git", "-C", str(destination), "-c", "user.name=ci", "-c", "user.email=ci@invalid"]
    existing = {p.relative_to(destination).as_posix() for p in (destination / "tests").glob("test_*.py")}
    require(set(modules) <= existing, "subset module missing")
    if inject:   # synthetic negative-control test, present only in the derived subset commit
        name, body = inject
        (destination / name).write_text(body, encoding="utf-8"); existing.add(name); modules = [*modules, name]
    ignored = sorted(existing - set(modules))
    conftest = destination / "tests/conftest.py"
    conftest.write_text(conftest.read_text(encoding="utf-8") + "\n\n# bounded validation subset only\ncollect_ignore = [p.split('/', 1)[1] for p in " + repr(ignored) + "]\n", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], check=True); subprocess.run([*git, "commit", "-q", "-m", "bounded validation subset"], check=True)
    return destination


def build_api(root, payloads):
    api, repo = FixtureAPI(), root["repository"]; prefix = "/repos/" + repo
    run = {"id": RUN, "run_attempt": ATTEMPT, "repository": {"full_name": repo, "id": 99}, "head_sha": root["workflow_head"],
           "workflow_id": 77, "event": "workflow_dispatch", "conclusion": None, "status": "in_progress"}
    api.data[prefix + f"/actions/runs/{RUN}"] = deepcopy(run); api.data[prefix + f"/actions/runs/{RUN}/attempts/{ATTEMPT}"] = run
    api.data[prefix + "/actions/workflows/77"] = {"id": 77, "path": root["workflow_path"]}
    api.data[prefix + "/git/commits/" + root["source"]["head"]] = {"sha": root["source"]["head"], "tree": {"sha": root["source"]["tree"]}}
    api.data[prefix + "/git/commits/" + root["controller_head"]] = {"sha": root["controller_head"], "tree": {"sha": root["controller_tree"]}}
    api.contents[(repo, root["workflow_head"], root["workflow_path"])] = WORKFLOW
    jobs, artifacts, anchors = [], [], {}
    for i, (name, path) in enumerate(payloads.items()):
        data = archive(path); api.payloads[10 + i] = data
        jobs.append({"id": 100 + i, "name": STAGES[name], "run_id": RUN, "run_attempt": ATTEMPT, "head_sha": root["workflow_head"],
            "status": "completed", "conclusion": "success", "started_at": "2026-10-21T10:00:00Z", "completed_at": "2026-10-21T10:10:00Z"})
        artifacts.append({"id": 10 + i, "name": f"ci-v3-{name}-{RUN}-{ATTEMPT}", "size_in_bytes": len(data), "expired": False,
            "digest": "sha256:" + sha(data), "created_at": "2026-10-21T10:09:00Z", "updated_at": "2026-10-21T10:09:01Z",
            "workflow_run": {"id": RUN, "head_sha": root["workflow_head"], "repository_id": 99}})
        anchors[name] = {"artifact_id": 10 + i, "artifact_digest": sha(data), "receipt_sha256": file_sha(Path(path) / "receipt.json"), "job_id": 100 + i}
    api.data[prefix + f"/actions/runs/{RUN}/attempts/{ATTEMPT}/jobs"] = {"total_count": len(jobs), "jobs": jobs}
    api.data[prefix + f"/actions/runs/{RUN}/artifacts"] = {"total_count": len(artifacts), "artifacts": artifacts}
    return api, anchors


def validate(project, image, work):
    project, work = Path(project).resolve(), Path(work).resolve()
    marks = {"start": time.perf_counter()}
    require(prepare(project, work / "prep", image) > 0, "no collection")
    prep = work / "prep"; marks["collect"] = time.perf_counter()
    inventory, policy, weights = (read_json(prep / (n + ".json")) for n in ("inventory", "policy", "weights"))
    environment = read_json(prep / "collection-container/child/adapter.json")["environment"]
    isolation = seal({"schema": 3, "kind": "ci-v3-isolation-policy", "source": inventory["source"],
        "profile": "docker-no-network-private-workspace-v1", "fixture_tree_reviewed": True, "review_reference": REVIEW,
        "modules": {m: {"sha256": file_sha(project / m), "reviewed": True, "rationale": "bounded subset; standalone-pass evidence", "mode": "runner-private"}
                    for m in inventory["modules"]}})
    bundle = {"inventory": inventory, "policy": policy, "weights": weights, "environment": environment, "isolation": isolation}
    root = {"schema": 3, "kind": "ci-v3-hosted-admission", "enabled": True, "review_reference": REVIEW,
        "owner_decisions": ["Financial", "Security", "CI"], "experiment_pairs": 1, "workers": 3, "run_id": RUN, "run_attempt": ATTEMPT,
        "repository": inventory["repository"], "source": inventory["source"], "controller_head": "a" * 40, "controller_tree": "b" * 40,
        "workflow_head": "c" * 40, "workflow_path": ".github/workflows/ci_v3_shadow.yml", "workflow_sha256": sha(WORKFLOW), "image": image,
        "pr_number": None, "merge_proof": {"mode": "main-head", "merge_sha": None, "merge_tree": None}, "controller_files_sha256": {},
        "bundle": {"repository": inventory["repository"], "revision": "e" * 40,
                   "files": {n: {"path": n + ".json", "sha256": sha(canonical_bytes(v))} for n, v in bundle.items()}}}
    root_sha = sha(canonical_bytes(root)); payloads = work / "payloads"
    run_plan(root, root_sha, bundle, project, payloads / "plan", RUN, ATTEMPT); marks["plan"] = time.perf_counter()
    api, anchors = build_api(root, {"plan": payloads / "plan"})
    received = work / "received-plan"
    receive(api, root, RUN, ATTEMPT, anchors, received, {"plan": STAGES["plan"]})
    def worker(name):
        started = time.perf_counter()
        run_worker(root, root_sha, bundle, project, received / "plan", name, payloads / name, RUN, ATTEMPT)
        return name, round(time.perf_counter() - started, 2)
    with ThreadPoolExecutor(max_workers=3) as pool:
        durations = dict(pool.map(worker, [n for n in STAGES if n != "plan"]))
    marks["workers"] = time.perf_counter()
    api, anchors = build_api(root, {n: payloads / n for n in STAGES})
    transport = receive(api, root, RUN, ATTEMPT, anchors, work / "received", STAGES)
    proof = aggregate(root, root_sha, bundle, project, work / "received", work / "verified", RUN, ATTEMPT, transport)
    marks["verify"] = time.perf_counter()
    plan = read_json(payloads / "plan/plan.json")
    allocation = {w: sorted(m for m, o in plan["module_workers"].items() if o == w) for w in durations}
    summary = {"scope": "BOUNDED SUBSET - NOT COMPLETE FINCO COVERAGE", "source": inventory["source"], "image": image,
        "nodes": len(inventory["nodes"]), "modules": len(inventory["modules"]), "allocation": allocation,
        "allocated_nodes": {w: sum(1 for n in inventory["nodes"] if n["module"] in mods) for w, mods in allocation.items()},
        "coverage_valid": proof["coverage_valid"], "authoritative_acceptance": proof["authoritative_acceptance"],
        "provenance_authenticated": proof["transport"]["provenance_authenticated"], "provenance_mode": proof["transport"]["provenance_mode"],
        "unique_nodes_verified": proof["execution"]["phase1_proof"]["unique_nodes"],
        "seconds": {"collect": round(marks["collect"] - marks["start"], 2), "plan": round(marks["plan"] - marks["collect"], 2),
                    "workers_wall": round(marks["workers"] - marks["plan"], 2), "per_worker": durations,
                    "verify": round(marks["verify"] - marks["workers"], 2), "total": round(marks["verify"] - marks["start"], 2)}}
    write_json(work / "validation-summary.json", summary)
    return summary


def negative_control(source, image, work, modules, kind):
    """Real containers must REJECT a deliberately failing / unapproved-skip test; returns the observed rejection."""
    work = Path(work); work.mkdir(parents=True, exist_ok=False)
    project = make_subset(source, modules, work / "subset", NEGATIVE[kind])
    try:
        validate(project, image, work / "run")
    except ContractError as exc:
        receipts = {w: read_json(p)["observation"] for w in ("worker-0", "worker-1", "worker-2")
                    if (p := work / "run/payloads" / w / "receipt.json").exists()}
        failed = sorted(w for w, o in receipts.items() if not o["normal_successful_exit"])
        result = {"control": kind, "rejected": True, "reason": str(exc), "workers_not_normal": failed,
                  "container_removed": all(o["container_removed"] for o in receipts.values()),
                  "pytest_codes": {w: (o["pytest_return"] or {}).get("code") for w, o in receipts.items()}}
        write_json(work / "negative-control.json", result)
        return result
    raise ContractError("negative control was ACCEPTED: " + kind)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True); parser.add_argument("--image", required=True); parser.add_argument("--work", required=True)
    parser.add_argument("--module", action="append", required=True); parser.add_argument("--negative", choices=sorted(NEGATIVE))
    args = parser.parse_args(argv)
    if args.negative:
        print(json.dumps(negative_control(args.source, args.image, args.work, args.module, args.negative), indent=1)); return 0
    work = Path(args.work); work.mkdir(parents=True, exist_ok=False)
    project = make_subset(args.source, args.module, work / "subset")
    print(json.dumps(validate(project, args.image, work / "run"), indent=1)); return 0


if __name__ == "__main__":
    sys.exit(main())
