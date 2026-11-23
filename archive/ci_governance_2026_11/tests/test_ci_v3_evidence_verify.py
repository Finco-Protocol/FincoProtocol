"""Independent positive and adversarial evidence controls for the offline verifier."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from tests.ci_v3_synthetic_evidence import PARAM, UNRESOLVED, bundle, reseal, xml_for
from tools.ci_v3_evidence_verify import verify_execution
from tools.ci_v3_schema import ContractError, canonical_bytes, write_json


def verify(data):
    return verify_execution(**data)


def change_worker(data, mutate, slot=0):
    evidence, xml = data["workers"][slot]
    mutate(evidence)
    data["workers"][slot] = reseal(evidence), xml


def change_xml(data, xml, slot=0, update_checksum=True):
    evidence, _ = data["workers"][slot]
    if update_checksum:
        evidence["junit_sha256"] = hashlib.sha256(xml).hexdigest()
    data["workers"][slot] = reseal(evidence), xml


def test_complete_three_worker_evidence_is_coverage_only():
    result = verify(bundle())
    assert result["coverage_valid"] is True
    assert result["authoritative_acceptance"] is False
    assert result["mode"] == "simulated"
    assert result["unique_nodes"] == result["executions"] == 5


def test_authorized_whole_module_overlap_is_in_expected_multiset():
    result = verify(bundle(overlap=True))
    assert result["unique_nodes"] == 5 and result["executions"] == 7


@pytest.mark.parametrize("mutation,match", [
    (lambda e: e["executions"].pop(), "multiset"),
    (lambda e: e["executions"].append(deepcopy(e["executions"][0])), "multiset"),
    (lambda e: e["executions"][0].update(nodeid="tests/test_foreign.py::test_foreign"), "foreign"),
    (lambda e: e["executions"][0].update(nodeid=PARAM[:-1]), "truncated"),
    (lambda e: e["executions"][1].update(nodeid=e["executions"][0]["nodeid"]), "multiset"),
    (lambda e: e["executions"][0].update(status="failed"), "failed"),
    (lambda e: e["executions"][0].update(status="xpass"), "xpass"),
    (lambda e: e["executions"][0].update(status="xfail", reason="unexpected"), "unexpected"),
    (lambda e: e["executions"][0].update(status="skipped", reason="unexpected"), "unexpected"),
    (lambda e: e["collection"]["skips"].pop(), "skip mismatch"),
    (lambda e: e["collection"]["skips"].append({"nodeid": "unknown", "reason": "unexpected"}), "skip mismatch"),
    (lambda e: e["collection"]["errors"].append("collection failed"), "collection incomplete"),
    (lambda e: e["process"].update(exit_code=1), "return marker"),
    (lambda e: e["process"].update(exit_code=124, timed_out=True), "return marker"),
    (lambda e: e["process"].update(timed_out=True), "timeout"),
    (lambda e: e["process"].update(normal_exit=False), "normal exit"),
    (lambda e: e["process"].pop("pytest_return_code"), "return marker"),
    (lambda e: e["process"].update(child_exit_code=1), "return marker"),
    (lambda e: e["process"].update(pytest_returned_ms=5), "marker order"),
    (lambda e: e.update(job_result="failure", aggregate_result="success"), "failed/incomplete"),
    (lambda e: e.update(complete=False), "incomplete"),
])
def test_mandatory_mutations_reach_specific_failure_paths(mutation, match):
    data = bundle()
    # Break shared references before mutation, as real files are independent documents.
    data["workers"][0] = deepcopy(data["workers"][0])
    change_worker(data, mutation)
    with pytest.raises(ContractError, match=match):
        verify(data)


def test_omitted_unresolved_node_rejected():
    data = bundle()
    change_worker(data, lambda e: e["executions"].clear(), slot=1)
    with pytest.raises(ContractError, match="multiset"):
        verify(data)


@pytest.mark.parametrize("field,value", [
    ("source", {"head": "f" * 40, "tree": "b" * 40}),
    ("source", {"head": "a" * 40, "tree": "f" * 40}),
    ("inventory_digest", "f" * 64), ("policy_digest", "f" * 64), ("plan_digest", "f" * 64),
    ("environment_digest", "f" * 64), ("run_id", "stale-run"), ("attempt", 2),
    ("repository", "foreign/repository"), ("workflow", "foreign/workflow"),
    ("evaluator", "foreign-evaluator"), ("mode", "recorded"),
])
def test_source_digest_and_artifact_lineage_mutations(field, value):
    data = bundle(); data["workers"][0] = deepcopy(data["workers"][0])
    change_worker(data, lambda e: e["context"].update({field: value}))
    with pytest.raises(ContractError, match="lineage"):
        verify(data)


def test_missing_worker_and_duplicate_worker_identity_rejected():
    data = bundle(); data["workers"].pop()
    with pytest.raises(ContractError, match="missing/extra worker"):
        verify(data)
    data = bundle(); change_worker(data, lambda e: e.update(worker="worker-0"), slot=1)
    with pytest.raises(ContractError, match="duplicate worker"):
        verify(data)


@pytest.mark.parametrize("mode", ["truncated", "checksum", "wrong-identity", "missing-skip", "count", "failure", "doctype"])
def test_junit_mutations_rejected_after_valid_other_evidence(mode):
    data = bundle(); raw = data["workers"][0][1]
    root = ET.fromstring(raw)
    if mode == "truncated":
        raw = raw[:len(raw)//2]
    elif mode == "checksum":
        change_xml(data, raw + b" ", update_checksum=False)
    elif mode == "wrong-identity":
        root.find("testcase/properties/property").set("value", json.dumps(["node", "substitute"]))
    elif mode == "missing-skip":
        root.remove(list(root)[-1]); root.set("tests", "2"); root.set("skipped", "0")
    elif mode == "count":
        root.set("tests", "99")
    elif mode == "failure":
        ET.SubElement(root.find("testcase"), "failure", message="real failure")
    elif mode == "doctype":
        raw = b'<!DOCTYPE testsuite [<!ENTITY x "bad">]>' + raw
    if mode != "checksum":
        change_xml(data, raw if mode in ("truncated", "doctype") else ET.tostring(root))
    with pytest.raises(ContractError, match="JUnit"):
        verify(data)


def test_new_unknown_test_not_silently_dropped_and_fresh_collection_required():
    data = bundle(); data["collection"]["nodes"] = [*data["collection"]["nodes"], "tests/test_new.py::test_added"]
    with pytest.raises(ContractError, match="reconciliation"):
        verify(data)
    data = bundle(); data["collection"] = None
    with pytest.raises(ContractError, match="collection missing"):
        verify(data)


def test_trusted_inputs_cannot_be_replaced_by_worker_supplied_policy():
    data = bundle(); data["policy"]["new_nodes"] = "ignore"
    data["policy"] = reseal(data["policy"])
    with pytest.raises(ContractError, match="fail closed"):
        verify(data)


def test_simulation_cannot_be_admitted_as_recorded_evidence():
    data = bundle(); data["trust"]["context"] = deepcopy(data["trust"]["context"])
    data["trust"]["context"]["mode"] = "recorded"
    with pytest.raises(ContractError, match="lineage"):
        verify(data)


def test_cli_rejects_truncated_evidence_and_cannot_hide_worker_failure(tmp_path):
    data = bundle(); root = tmp_path / "workers"
    for key in ("inventory", "policy", "plan", "collection", "trust"):
        write_json(tmp_path / (key + ".json"), data[key])
    for record, xml in data["workers"]:
        directory = root / record["worker"]; directory.mkdir(parents=True)
        write_json(directory / "execution.json", record); (directory / "results.xml").write_bytes(xml)
    command = [sys.executable, "-m", "tools.ci_v3_evidence_verify"]
    for key in ("inventory", "policy", "plan", "collection", "trust"):
        command += ["--" + key, str(tmp_path / (key + ".json"))]
    command += ["--evidence", str(root), "--output", str(tmp_path / "proof.json")]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0 and "AUTHORITATIVE_ACCEPTANCE=false" in result.stdout
    (root / "worker-1/execution.json").write_text('{"schema":')
    result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    assert result.returncode == 1 and "truncated" in result.stderr
    assert json.loads((tmp_path / "proof.json").read_text())["coverage_valid"] is False


def test_known_node_moved_to_another_worker_is_not_coverage_equivalence():
    data = bundle()
    first, xml = data["workers"][0]
    first["executions"][0]["nodeid"] = UNRESOLVED
    data["workers"][0] = reseal(first), xml
    with pytest.raises(ContractError, match="wrong owner"):
        verify(data)


def test_missing_and_foreign_junit_collection_skips_are_distinct_failures():
    data = bundle(); root = ET.fromstring(data["workers"][0][1])
    identity = list(root)[-1].find("properties/property")
    identity.set("value", json.dumps(["collection-skip", "foreign-skip"]))
    change_xml(data, ET.tostring(root))
    with pytest.raises(ContractError, match="unexpected JUnit collection skip"):
        verify(data)


def test_explicit_historical_skip_requires_exact_status_and_full_reason():
    data = bundle(); reason = "approved existing condition\nwith full detail"
    data["policy"]["allowed_nonpass"] = {PARAM: {"status": "skipped", "reason": reason}}
    data["policy"] = reseal(data["policy"])
    data["plan"]["policy_digest"] = data["policy"]["digest"]; data["plan"] = reseal(data["plan"])
    context = deepcopy(data["trust"]["context"])
    context.update(policy_digest=data["policy"]["digest"], plan_digest=data["plan"]["digest"])
    data["trust"]["context"] = context
    for slot, (record, xml) in enumerate(data["workers"]):
        record["context"] = deepcopy(context)
        for execution in record["executions"]:
            if execution["nodeid"] == PARAM:
                execution.update(status="skipped", reason=reason)
        data["workers"][slot] = record, xml
        change_xml(data, xml_for(record["executions"], record["collection"]["skips"]), slot=slot)
    assert verify(data)["executions"] == 5
    change_worker(data, lambda e: e["executions"][0].update(reason="shortened"))
    with pytest.raises(ContractError, match="unexpected skip"):
        verify(data)


def test_long_opaque_parameter_ids_survive_json_and_junit_without_truncation():
    data = bundle()
    long_node = PARAM[:-1] + "-" + "opaque" * 25000 + "]"
    for item in data["inventory"]["nodes"]:
        if item["nodeid"] == PARAM:
            item["nodeid"] = long_node
    data["inventory"]["nodes"].sort(key=lambda n: n["nodeid"])
    data["inventory"] = reseal(data["inventory"])
    data["policy"]["inventory_digest"] = data["inventory"]["digest"]; data["policy"] = reseal(data["policy"])
    data["plan"].update(inventory_digest=data["inventory"]["digest"], policy_digest=data["policy"]["digest"])
    data["plan"] = reseal(data["plan"])
    context = deepcopy(data["trust"]["context"])
    context.update(inventory_digest=data["inventory"]["digest"], policy_digest=data["policy"]["digest"], plan_digest=data["plan"]["digest"])
    data["trust"]["context"] = context
    data["collection"]["nodes"] = sorted(long_node if n == PARAM else n for n in data["collection"]["nodes"])
    for slot, (record, xml) in enumerate(data["workers"]):
        record["context"] = deepcopy(context)
        record["collection"] = deepcopy(data["collection"])
        for execution in record["executions"]:
            if execution["nodeid"] == PARAM:
                execution["nodeid"] = long_node
        data["workers"][slot] = record, xml
        change_xml(data, xml_for(record["executions"], record["collection"]["skips"]), slot=slot)
    assert verify(data)["executions"] == 5


def test_junit_testcase_hidden_inside_properties_is_rejected():
    data = bundle(); root = ET.fromstring(data["workers"][0][1])
    ET.SubElement(root.find("testcase/properties"), "testcase", name="hidden")
    change_xml(data, ET.tostring(root))
    with pytest.raises(ContractError, match="JUnit"):
        verify(data)
