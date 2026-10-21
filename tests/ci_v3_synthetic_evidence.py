"""Small hand-authored adversarial data; no planner or audit producer imports."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import xml.etree.ElementTree as ET

from tools.ci_v3_schema import EVALUATOR, seal, skip_key

HEAD, TREE = "a" * 40, "b" * 40
PARAM = "tests/test_alpha.py::TestDebt::test_case[original::opaque-parameter]"
PLAIN = "tests/test_alpha.py::TestDebt::test_plain"
UNRESOLVED = "tests/test_beta.py::test_unresolved[opaque-parameter-2]"
RADAR = "tests/test_gamma.py::test_market"
GOVERNANCE = "tests/test_delta.py::test_authority"
IDS = sorted([PARAM, PLAIN, UNRESOLVED, RADAR, GOVERNANCE])
ASSIGNMENT = {"tests/test_alpha.py": "worker-0", "tests/test_beta.py": "worker-1",
              "tests/test_gamma.py": "worker-2", "tests/test_delta.py": "worker-2"}


def reseal(value):
    return seal({k: v for k, v in value.items() if k != "digest"})


def xml_for(records, skips):
    # Fixture construction only: identities and expected ownership are literal,
    # not inferred by the planner or checked with a duplicate verifier algorithm.
    root = ET.Element("testsuite", tests=str(len(records) + len(skips)), failures="0", errors="0",
                      skipped=str(sum(r["status"] != "passed" for r in records) + len(skips)))
    for kind, identity, status, reason in (
        [("node", r["nodeid"], r["status"], r["reason"]) for r in records]
        + [("collection-skip", skip_key(s), "skipped", s["reason"]) for s in skips]
    ):
        case = ET.SubElement(root, "testcase", name="fixture")
        props = ET.SubElement(case, "properties")
        ET.SubElement(props, "property", name="ci_v3_identity", value=json.dumps([kind, identity]))
        if status != "passed":
            ET.SubElement(props, "property", name="ci_v3_reason", value=json.dumps(reason))
            ET.SubElement(case, "skipped", type="pytest.xfail" if status == "xfail" else "pytest.skip")
    return ET.tostring(root, encoding="utf-8")


def bundle(overlap=False):
    modules = sorted(ASSIGNMENT)
    nodes = []
    for node in IDS:
        module = node.split("::", 1)[0]
        domain = {"tests/test_alpha.py": "Model", "tests/test_beta.py": "F",
                  "tests/test_gamma.py": "Radar", "tests/test_delta.py": "Governance"}[module]
        nodes.append({"nodeid": node, "module": module, "fixture_unit": module,
            "execution_owner": "plan.module_workers", "optional_overlap_ownership": "policy.module_overlaps",
            "domain": domain, "confidence": "unresolved" if domain == "F" else "candidate-static",
            "mandatory": True, "obligations": ["full-regression"], "dependency_evidence": "synthetic-literal"})
    inventory = seal({"schema": 1, "kind": "ci-v3-inventory", "authority": "offline-prototype",
        "repository": "Finco-Protocol/FincoProtocol", "source": {"head": HEAD, "tree": TREE},
        "nodes": nodes, "modules": {m: {"isolation_review": "unproven", "dependency_evidence": {}} for m in modules},
        "collection_skips": [{"nodeid": "tests/test_optional.py", "reason": "existing optional dependency"}]})
    policy = seal({"schema": 1, "kind": "ci-v3-policy", "authority": "offline-prototype",
        "inventory_digest": inventory["digest"], "new_nodes": "fail-closed", "selective_execution": False,
        "allowed_nonpass": {}, "module_overlaps": {"tests/test_alpha.py": ["worker-2"]} if overlap else {}})
    plan = seal({"schema": 1, "kind": "ci-v3-plan", "authority": "offline-prototype",
        "source": inventory["source"], "inventory_digest": inventory["digest"], "policy_digest": policy["digest"],
        "weights_digest": "c" * 64, "worker_count": 3, "module_workers": ASSIGNMENT})
    context = {"repository": inventory["repository"], "pr_number": 1, "workflow": "offline/test",
        "run_id": "independent-fixture", "attempt": 1, "mode": "simulated", "evaluator": EVALUATOR,
        "source": inventory["source"], "environment_digest": "d" * 64,
        "inventory_digest": inventory["digest"], "policy_digest": policy["digest"], "plan_digest": plan["digest"],
        "merge_proof": {"mode": "identical-tree", "merge_sha": "e" * 40, "merge_tree": TREE}}
    collection = {"source": inventory["source"], "complete": True, "errors": [], "nodes": IDS,
                  "skips": inventory["collection_skips"]}
    # Literal expected lists make the positive oracle independent of assignment logic.
    expected = [[PARAM, PLAIN], [UNRESOLVED], [RADAR, GOVERNANCE] + ([PARAM, PLAIN] if overlap else [])]
    workers = []
    for number, ids in enumerate(expected):
        records = [{"nodeid": n, "status": "passed", "reason": ""} for n in ids]
        xml = xml_for(records, inventory["collection_skips"])
        workers.append((seal({"schema": 1, "kind": "ci-v3-worker-evidence", "worker": "worker-%d" % number,
            "context": context, "complete": True, "job_result": "success", "collection": collection,
            "executions": records, "junit_sha256": hashlib.sha256(xml).hexdigest(),
            "process": {"exit_code": 0, "pytest_return_code": 0, "child_exit_code": 0, "normal_exit": True,
                        "timed_out": False, "pytest_started_ms": 1, "pytest_returned_ms": 2,
                        "child_exited_ms": 3, "elapsed_ms": 4}}), xml))
    return deepcopy({"inventory": inventory, "policy": policy, "plan": plan, "collection": collection,
                     "workers": workers, "trust": {"schema": 1, "kind": "ci-v3-trust-input", "context": context}})
