"""Assemble the reproducible isolation/admission PROPOSAL from current evidence. It approves nothing.

Output: an owner-reviewable bundle (inventory, policy, weights, isolation, environment, in the exact shape the closed
admission root references) plus a sealed summary with exact node-identity digests, image provenance, the unresolved
module reassessment against the previous evidence, and the owner decisions that remain. `admission_ready` is false until
every listed blocker is cleared by someone other than this tool."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from tools.ci_v3_schema import ContractError, digest, read_json, require, seal, write_json

BUNDLE = ("inventory", "policy", "weights", "isolation", "environment")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def reassess(previous_modules, classification_modules):
    """Previous Phase 3B unresolved modules -> what they are now, with the reason."""
    rows = []
    for name, old in sorted(previous_modules.items()):
        if old.get("category") in ("standalone-pass", "not-collected-helper", "collection-skipped", "stable-pass"):
            continue
        new = classification_modules.get(name)
        rows.append({"module": name, "previous_category": old["category"], "current_category": new["category"] if new else "absent",
                     "current_mode": new["mode"] if new else None, "current_reason": new["reason"] if new else "module no longer exists",
                     "resolved": bool(new) and new["category"] in ("stable-pass", "target-concurrency-stability-validated")})
    return rows


def owner_decisions(summary, nonpass, equivalence, calibration, image, threads=()):
    decisions = []
    if nonpass["allowed_nonpass"]:
        decisions.append({"owner": "Financial+CI", "decision": f"approve or reject the exact {len(nonpass['allowed_nonpass'])} runtime skip/xfail records "
                          f"(digest {nonpass['digest'][:16]}); every record is identical to the sequential control",
                          "blocking": True})
    for kind in ("rejected", "needs_owner_decision", "control_nonpass_not_reproduced"):
        if nonpass[kind]:
            decisions.append({"owner": "CI", "decision": f"{len(nonpass[kind])} nonpass record(s) in `{kind}`: resolve before admission", "blocking": True})
    blocked = summary["unresolved_modules"]
    if blocked:
        decisions.append({"owner": "CI", "decision": "resolve or explicitly accept each unresolved module: " + ", ".join(blocked), "blocking": True})
    if not equivalence["fully_equivalent"]:
        decisions.append({"owner": "Security+CI", "decision": "accept or remove each environment difference: " + ", ".join(equivalence["unaccepted_differences"]), "blocking": True})
    if calibration is None or not calibration.get("meets_test_assumption"):
        decisions.append({"owner": "CI", "decision": "run tools/ci_v3_calibrate.py inside the approved image on the target hosted runner class; "
                          "tests/test_p0a_model_execution.py needs worker cold start <= 0.6 s", "blocking": True})
    if image.get("registry_digest") is None:
        decisions.append({"owner": "Security+CI", "decision": "authorize publication of the execution image and record its registry digest", "blocking": True})
    if threads:
        decisions.append({"owner": "Security+CI", "decision": "decide whether to approve these exact daemon threads left alive by application startup ("
                          + ", ".join(t["name"] for t in threads) + "); without an approved isolation.allowed_daemon_threads entry (reason + approval_reference) "
                          "every worker that boots the application is rejected by the leak gate", "blocking": True})
    decisions.append({"owner": "Financial", "decision": "acknowledge the disclosed modification of tests/test_golden_flow_correction_b.py "
                      "(isolated precondition fixture; assertions pinned by tests/test_golden_flow_correction_b_guard.py)", "blocking": False})
    return decisions


def build(prepared, classification, nonpass, image, environment_equivalence, calibration, previous, image_files, threads=(), historical=()):
    inventory, isolation = prepared["inventory"], classification["proposal"]
    ids = sorted(n["nodeid"] for n in inventory["nodes"])
    require(len(ids) == len(set(ids)), "duplicate node identities")
    require(set(isolation["modules"]) == set(prepared["isolation"]["modules"]), "classification does not cover the collected modules")
    policy_body = {k: v for k, v in prepared["policy"].items() if k != "digest"}
    policy = seal({**policy_body, "allowed_nonpass": dict(nonpass["allowed_nonpass"]), "authority": "proposal-not-approved"})
    bundle = {"inventory": inventory, "policy": policy, "weights": prepared["weights"], "isolation": isolation, "environment": prepared["environment"]}
    files = {name: sha(json.dumps(value, sort_keys=True).encode()) for name, value in bundle.items()}
    blockers = []
    summary = classification["summary"]
    if summary["unresolved_blocking_admission"]:
        blockers.append(f"{summary['unresolved_blocking_admission']} unresolved modules")
    if not environment_equivalence["fully_equivalent"]:
        blockers.append("environment not proven equivalent")
    if image.get("registry_digest") is None:
        blockers.append("image not published")
    if calibration is None or not calibration.get("meets_test_assumption"):
        blockers.append("hosted-runner calibration absent or failing")
    earlier = summary["categories"].get("historical-only-needs-current-execution", 0)
    if earlier:
        blockers.append(f"{earlier} modules have only earlier-source (historical) evidence")
    if any(not h["applies_to_this_source"] for h in historical):
        blockers.append("earlier execution evidence does not apply to the current source")
    if threads:
        blockers.append("daemon thread policy not approved")
    blockers += ["no owner has reviewed isolation", "nonpass policy not approved"]
    return bundle, seal({"schema": 1, "kind": "ci-v3-admission-proposal", "authority": "proposal-not-approved", "admission_ready": False,
        "source": inventory["source"], "inventory": {"digest": inventory["digest"], "nodes": len(ids), "node_ids_sha256": sha("\n".join(ids).encode()),
                                                       "modules": len(inventory["modules"]), "collection_skips": len(prepared["collection"]["skips"])},
        "evidence_scope": {"current_source": inventory["source"], "historical": list(historical),
                           "statement": "Historical executions are independently verifiable against their own source but were not run on the current source; "
                                        "they are not equivalence evidence for it, even for modules whose test file is unchanged."},
        "bundle_sha256": files, "image": {**image, "files_sha256": image_files},
        "classification": {"categories": summary["categories"], "unresolved_modules": summary["unresolved_modules"]},
        "nonpass": {"proposed": len(nonpass["allowed_nonpass"]), "digest": nonpass["digest"], "control": nonpass["control"],
                    "coverage_equivalence": nonpass["coverage_equivalence"]},
        "environment_equivalence_digest": environment_equivalence["digest"], "calibration": calibration,
        "previous_unresolved_reassessment": reassess(previous, isolation["modules"]) if previous else [],
        "daemon_thread_proposal": {"authority": "proposal-not-approved", "observed_after_pytest_returned": list(threads),
                                   "active_policy_field": "isolation.allowed_daemon_threads = {name: {reason, approval_reference}}; default empty"},
        "owner_decisions": owner_decisions(summary, nonpass, environment_equivalence, calibration, image, threads), "admission_blockers": blockers})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("prepared", "classification", "nonpass-policy", "image-dir", "environment-equivalence", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--calibration"); parser.add_argument("--repo", default="."); parser.add_argument("--historical-manifest", action="append", default=[]); parser.add_argument("--observed-threads", help="JSON list of {name, daemon} from a rejected worker's pytest-return.json"); parser.add_argument("--previous", help="previous module-classification.json")
    args = parser.parse_args(argv)
    p, c, i = Path(args.prepared), Path(args.classification), Path(args.image_dir)
    try:
        prepared = {k: read_json(p / (k + ".json")) for k in ("inventory", "policy", "weights", "isolation", "collection")}
        prepared["environment"] = read_json(p / "collection-container/child/adapter.json")["environment"]
        classification = {"proposal": read_json(c / "isolation-proposal.json"), "summary": read_json(c / "summary.json")}
        previous = read_json(args.previous)["modules"] if args.previous else None
        calibration = read_json(args.calibration) if args.calibration else None
        from tools.ci_v3_evidence import applicability
        head = prepared["inventory"]["source"]["head"]
        historical = []
        for manifest_file in args.historical_manifest:
            old = read_json(manifest_file); info = applicability(args.repo, old, head)
            historical.append({"manifest_digest": old["digest"], "source": old["source"], "applies_to_this_source": info["applies_to_published_head"],
                               "unreviewed_change_classes": info["unreviewed_change_classes"], "unreviewed_changed_paths": len(info["unreviewed_changes"])})
        bundle, proposal = build(prepared, classification, read_json(args.nonpass_policy), read_json(i / "image.json"),
                                 read_json(args.environment_equivalence), calibration, previous,
                                 {f.name: sha(f.read_bytes()) for f in sorted(i.iterdir()) if f.is_file()},
                                 [t for t in json.loads(Path(args.observed_threads).read_text()) if t["daemon"]] if args.observed_threads else (), historical)
    except (ContractError, OSError, KeyError) as exc:
        print("CI_V3_PROPOSAL_REJECTED: " + str(exc)); return 1
    out = Path(args.output); out.mkdir(parents=True, exist_ok=False)
    for name, value in bundle.items():
        write_json(out / "bundle" / (name + ".json"), value)
    write_json(out / "proposal.json", proposal)
    print(json.dumps({"admission_ready": proposal["admission_ready"], "blockers": proposal["admission_blockers"], "owner_decisions": len(proposal["owner_decisions"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
