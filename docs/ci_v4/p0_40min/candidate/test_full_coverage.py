"""Explicit candidate tests; synthetic evidence, never a FULL acceptance claim."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
from tools.ci_v3_real_contract import envelope
from tools.ci_v3_pytest_config import PLUGINS
from tools.ci_v3_schema import ContractError, seal
from tools.ci_v3_calibrate import STEADY_STATE_CONTRACT

spec = importlib.util.spec_from_file_location("full_candidate", Path(__file__).with_name("full_coverage.py"))
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)


def reseal(value):
    return seal({k: v for k, v in value.items() if k != "digest"})


def reenvelope(value):
    return envelope("ci-v3-pytest-report", **{k: v for k, v in value.items() if k not in ("schema", "kind", "digest")})


def phases(nodes):
    return [{"nodeid": n, "when": w, "outcome": "passed", "reason": "", "wasxfail": None}
            for n in nodes for w in ("setup", "call", "teardown")]


def xml(nodes):
    suite = ET.Element("testsuite", tests=str(len(nodes)), failures="0", errors="0", skipped="0")
    for node in nodes:
        module, name = node.split("::", 1)
        ET.SubElement(suite, "testcase", classname=module[:-3].replace("/", "."), name=name, time="0.001")
    return ET.tostring(suite)


def fixture(workers=8):
    ids = [f"tests/test_{i:02d}.py::test_value[opaque::{i}]" for i in range(12)]
    modules = [n.split("::")[0] for n in ids]
    src = {"head": "a" * 40, "tree": "b" * 40}
    ctx = {"source": src, "repository": "Finco-Protocol/FincoProtocol", "run_id": "12345", "attempt": 1}
    inv = seal({"schema": 1, "kind": "ci-v3-inventory", "authority": "offline-prototype", "repository": ctx["repository"],
        "source": src, "nodes": [{"nodeid": n, "module": n.split("::")[0], "fixture_unit": n.split("::")[0],
        "execution_owner": "plan.module_workers", "optional_overlap_ownership": "policy.module_overlaps", "domain": "F",
        "confidence": "unresolved", "mandatory": True, "obligations": ["full-regression"], "dependency_evidence": "synthetic"} for n in ids],
        "modules": {m: {"isolation_review": "unproven", "dependency_evidence": {}} for m in modules}, "collection_skips": []})
    policy = seal({"schema": 1, "kind": "ci-v3-policy", "authority": "offline-prototype", "inventory_digest": inv["digest"],
                   "new_nodes": "fail-closed", "selective_execution": False, "allowed_nonpass": {}, "module_overlaps": {}})
    weights = seal({"schema": 1, "kind": "ci-v3-weights", "source": src, "inventory_digest": inv["digest"], "modules_ms": dict.fromkeys(modules, 1000)})
    bundle = F.make_plan(inv, policy, weights, ctx, "c" * 64, "d" * 64, workers=workers)
    collection = {"source": src, "complete": True, "errors": [], "nodes": ids, "skips": []}
    base = {"collection": collection, "selected": ids, "deselected": [], "phases": phases(ids), "pytest_exitstatus": 0}
    reports = []
    for index in range(workers):
        owned = [n for n in ids if bundle["plan"]["module_workers"][n.split("::")[0]] == f"worker-{index}"]
        report = envelope("ci-v3-pytest-report", context=ctx, mode="worker", worker=f"worker-{index}", collection=collection,
            selected=owned, deselected=sorted(set(ids)-set(owned)), phases=phases(owned), pytest_exitstatus=0,
            unauthorized_deselection=[], environment={"synthetic": True}, pytest_plugins=list(PLUGINS), plugin_registrations=[])
        reports.append({"index": index, "report": report, "junit": xml(owned),
            "calibration": {"context": ctx, "contract": STEADY_STATE_CONTRACT, "samples_s": [0.1, 0.1, 0.1]},
            "binding": {"context": ctx, "worker": index,
            "bundle_digest": bundle["digest"], "image_digest": "c"*64, "runtime_archive_digest": "d"*64},
            "process": {"normal_successful_exit": True, "container_removed": True, "source_bytes_unchanged": True,
            "descendant_cleanup": {"cleanup_verified": True, "survivors_observed": [], "survivors_remaining": []}}})
    return deepcopy((bundle, reports, base, xml(ids), {"synthetic": True}, []))


@pytest.mark.parametrize("workers", [8, 10, 12])
def test_all_nodes_once_and_opaque_parameters_preserved(workers):
    result = F.verify(*fixture(workers))
    assert result["collected"] == result["executed"] == 12
    assert result["counts"] == {"passed": 12}
    assert result["hosted_full"] == "NOT_PROVEN"
    assert result["activation"] == "NOT_ACTIVATED"


@pytest.mark.parametrize("attack", ["missing_worker", "duplicate_worker", "wrong_sha", "wrong_tree", "wrong_attempt",
    "wrong_run", "runtime", "archive", "missing_node", "extra_node", "duplicate_node", "missing_phase", "duplicate_phase",
    "failure", "skip", "xfail", "exit", "timeout", "source_changed", "cleanup", "survivor", "container",
    "plugins", "plugin_bytes", "environment", "collection_error", "collection_incomplete", "collection_skip", "deselected",
    "forged_junit", "junit_duplicate", "junit_dtd", "xml_count", "stale_seal", "historical_removed", "unapproved_transition",
    "calibration_missing", "calibration_forged", "calibration_attempt"])
def test_adversarial_evidence_fails_closed(attack):
    bundle, workers, baseline, native, env, plugins = fixture()
    w = workers[0]; r = w["report"]
    if attack == "missing_worker": workers.pop()
    elif attack == "duplicate_worker": workers[-1] = deepcopy(w)
    elif attack in ("wrong_sha", "wrong_tree", "wrong_attempt", "wrong_run"):
        ctx = deepcopy(r["context"])
        if attack == "wrong_sha": ctx["source"]["head"] = "e"*40
        elif attack == "wrong_tree": ctx["source"]["tree"] = "e"*40
        elif attack == "wrong_attempt": ctx["attempt"] = 2
        else: ctx["run_id"] = "99999"
        r["context"] = ctx
    elif attack == "runtime": w["binding"]["image_digest"] = "e"*64
    elif attack == "archive": w["binding"]["runtime_archive_digest"] = "e"*64
    elif attack == "missing_node": r["selected"].pop()
    elif attack == "extra_node": r["selected"].append("tests/test_foreign.py::test_x")
    elif attack == "duplicate_node": r["selected"].append(r["selected"][0])
    elif attack == "missing_phase": r["phases"].pop()
    elif attack == "duplicate_phase": r["phases"].append(deepcopy(r["phases"][0]))
    elif attack in ("failure", "skip", "xfail"):
        r["phases"][1]["outcome"] = "failed" if attack == "failure" else "skipped"
        if attack == "xfail": r["phases"][1]["wasxfail"] = "invented exemption"
    elif attack == "exit": r["pytest_exitstatus"] = 1
    elif attack == "timeout": w["process"]["timed_out"] = True
    elif attack == "source_changed": w["process"]["source_bytes_unchanged"] = False
    elif attack == "cleanup": w["process"]["descendant_cleanup"]["cleanup_verified"] = False
    elif attack == "survivor": w["process"]["descendant_cleanup"]["survivors_observed"] = [999]
    elif attack == "container": w["process"]["container_removed"] = False
    elif attack == "plugins": r["pytest_plugins"] = []
    elif attack == "plugin_bytes": r["plugin_registrations"] = [{"registration": "fake", "module": "fake", "implementation": "fake", "file_sha256": "e"*64}]
    elif attack == "environment": r["environment"] = {"different": True}
    elif attack == "collection_error": r["collection"]["errors"] = [{"nodeid": "tests", "reason": "error"}]
    elif attack == "collection_incomplete": r["collection"]["complete"] = False
    elif attack == "collection_skip": r["collection"]["skips"] = [{"nodeid": "tests/test_new.py", "reason": "skip"}]
    elif attack == "deselected": r["unauthorized_deselection"] = [r["selected"][0]]
    elif attack == "forged_junit": w["junit"] = xml([])
    elif attack == "junit_duplicate": w["junit"] = xml(r["selected"]+[r["selected"][0]])
    elif attack == "junit_dtd": w["junit"] = b'<!DOCTYPE foo>'+w["junit"]
    elif attack == "xml_count": w["junit"] = w["junit"].replace(b'failures="0"', b'failures="1"')
    elif attack == "stale_seal": bundle["runtime_archive_digest"] = "e"*64
    elif attack == "calibration_missing": del w["calibration"]
    elif attack == "calibration_forged": w["calibration"]["samples_s"] = [1, 1, 1]
    elif attack == "calibration_attempt": w["calibration"]["context"] = {**w["calibration"]["context"], "attempt": 2}
    elif attack == "historical_removed":
        node = "tests/test_removed.py::test_x"
        baseline["selected"].append(node); baseline["collection"]["nodes"].append(node)
        baseline["phases"] += phases([node]); native = xml(baseline["selected"])
    elif attack == "unapproved_transition":
        baseline["phases"][1]["outcome"] = "skipped"
        suite = ET.fromstring(native);case = suite.find("testcase");ET.SubElement(case, "skipped")
        suite.set("skipped", "1");native = ET.tostring(suite)
    if attack != "stale_seal": w["report"] = reenvelope(r)
    with pytest.raises((ContractError, ValueError)):
        F.verify(bundle, workers, baseline, native, env, plugins)


def service_fixture():
    bundle, *_ = fixture()
    ctx = bundle["context"]; repo = {"full_name": ctx["repository"]}
    run = {"id": 12345, "run_attempt": 1, "head_sha": "a"*40, "path": ".github/workflows/ci_v4_full.yml",
           "event": "workflow_dispatch", "repository": repo, "head_repository": repo}
    names = ["plan"]+[f"worker-{i}" for i in range(8)]
    jobs, artifacts, archives = [], [], {}
    for i, name in enumerate(names):
        jobs.append({"name": name, "run_id": 12345, "run_attempt": 1, "status": "completed", "conclusion": "success"})
        archive = ("synthetic bytes "+name).encode(); archives[100+i] = archive
        artifacts.append({"id": 100+i, "name": "public-ci-v4-full-"+name+"-attempt-1", "expired": False,
            "workflow_run": {"id": 12345, "head_sha": "a"*40}, "digest": "sha256:"+hashlib.sha256(archive).hexdigest()})
    return deepcopy((bundle, run, jobs, artifacts, archives))


def test_service_archive_binding_positive():
    assert F.verify_service_artifacts(*service_fixture()) is True


@pytest.mark.parametrize("attack", ["attempt", "sha", "run", "fork", "event", "path", "missing", "duplicate",
    "expired", "digest", "bytes", "producer", "producer_attempt", "producer_run", "artifact_run", "artifact_sha"])
def test_service_tamper_rejected(attack):
    b, run, jobs, artifacts, archives = service_fixture()
    if attack == "attempt": run["run_attempt"] = 2
    elif attack == "sha": run["head_sha"] = "e"*40
    elif attack == "run": run["id"] = 999
    elif attack == "fork": run["head_repository"] = {"full_name": "foreign/fork"}
    elif attack == "event": run["event"] = "pull_request_target"
    elif attack == "path": run["path"] = ".github/workflows/ci_v4_pr.yml"
    elif attack == "missing": artifacts.pop()
    elif attack == "duplicate": artifacts.append(deepcopy(artifacts[0]))
    elif attack == "expired": artifacts[0]["expired"] = True
    elif attack == "digest": artifacts[0]["digest"] = "sha256:"+"e"*64
    elif attack == "bytes": archives[100] += b"forged"
    elif attack == "producer": jobs[0]["conclusion"] = "failure"
    elif attack == "producer_attempt": jobs[0]["run_attempt"] = 2
    elif attack == "producer_run": jobs[0]["run_id"] = 999
    elif attack == "artifact_run": artifacts[0]["workflow_run"]["id"] = 999
    elif attack == "artifact_sha": artifacts[0]["workflow_run"]["head_sha"] = "e"*40
    with pytest.raises(ContractError): F.verify_service_artifacts(b, run, jobs, artifacts, archives)


@pytest.mark.parametrize("status", ["skipped", "xfail"])
def test_consistent_new_nonpass_cannot_be_laundered_through_native_xml(status):
    b, workers, baseline, native, env, plugins = fixture()
    baseline = deepcopy(baseline)
    w = workers[0]; node = w["report"]["selected"][0]
    baseline["selected"].remove(node)
    baseline["collection"]["nodes"] = [n for n in baseline["collection"]["nodes"] if n != node]
    baseline["phases"] = [p for p in baseline["phases"] if p["nodeid"] != node]
    native = xml(baseline["selected"])
    r = w["report"]
    for phase in r["phases"]:
        if phase["nodeid"] == node and phase["when"] == "call":
            phase.update(outcome="skipped", reason="invented skip", wasxfail="invented skip" if status == "xfail" else None)
    w["report"] = reenvelope(r)
    suite = ET.fromstring(w["junit"])
    case = next(c for c in suite if c.get("name") == node.split("::", 1)[1])
    ET.SubElement(case, "skipped", type="pytest.xfail" if status == "xfail" else "pytest.skip", message="invented skip")
    suite.set("skipped", "1"); w["junit"] = ET.tostring(suite)
    with pytest.raises(ContractError, match="new nonpass"):
        F.verify(b, workers, baseline, native, env, plugins)
