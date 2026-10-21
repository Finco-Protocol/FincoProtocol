"""Transport/provenance attacks against an independently retained controller anchor."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from tests.test_ci_v3_real_adapter import actual_bundle
from tools.ci_v3_observed_verify import verify_observed
from tools.ci_v3_real_contract import envelope
from tools.ci_v3_schema import ContractError, digest, read_json, seal, write_json


@pytest.fixture
def transferred(actual_bundle, tmp_path):
    root = tmp_path / "transferred"
    shutil.copytree(actual_bundle["root"], root)
    return {**actual_bundle, "root": root}


def verify(data):
    return verify_observed(data["root"], data["anchor"], data["trust"], data["producer"])


def reseal(value):
    return {**{k: v for k, v in value.items() if k != "digest"},
            "digest": digest({k: v for k, v in value.items() if k != "digest"})}


@pytest.mark.parametrize("attack", ["missing-execution", "duplicate-execution", "unexpected-deselection",
    "collection-only-pass", "failed-test-hidden", "wrong-sha", "wrong-tree", "wrong-attempt", "wrong-junit-identity"])
def test_evidence_and_self_reported_checksum_changes_do_not_authenticate(transferred, attack):
    data = transferred; directory = data["root"] / "workers/worker-0"
    execution = read_json(directory / "execution.json")
    if attack == "wrong-junit-identity":
        xml = (directory / "results.xml").read_bytes().replace(b"literal::id", b"substituted-id")
        (directory / "results.xml").write_bytes(xml)
        execution["junit_sha256"] = hashlib.sha256(xml).hexdigest()
    elif attack in ("wrong-sha", "wrong-tree", "wrong-attempt"):
        if attack == "wrong-attempt":
            execution["context"]["attempt"] += 1
        else:
            execution["context"]["source"]["head" if attack == "wrong-sha" else "tree"] = "f" * 40
    elif attack == "duplicate-execution":
        execution["executions"].append(deepcopy(execution["executions"][0]))
    elif attack == "missing-execution":
        execution["executions"].pop()
    else:
        report = read_json(directory / "adapter.json")
        if attack == "collection-only-pass":
            report["phases"] = []
        elif attack == "unexpected-deselection":
            report["selected"].pop()
        else:
            report["phases"][1]["outcome"] = "failed"
        write_json(directory / "adapter.json", reseal(report))
    write_json(directory / "execution.json", reseal(execution))
    # A valid local checksum/seal of altered claims is still not the parent receipt.
    assert read_json(directory / "execution.json")["digest"] == reseal(execution)["digest"]
    with pytest.raises(ContractError, match="independently pinned parent observation"):
        verify(data)


def test_replacing_receipt_and_its_accompanying_pin_is_not_independent_authority(transferred):
    data = transferred; receipt = read_json(data["root"] / "observations.json")
    receipt["context"]["attempt"] += 1
    write_json(data["root"] / "observations.json", reseal(receipt))
    attacker_sha = hashlib.sha256((data["root"] / "observations.json").read_bytes()).hexdigest()
    write_json(data["root"] / "receipt-pin.json", {"observations_sha256": attacker_sha})
    with pytest.raises(ContractError, match="independent parent receipt anchor"):
        verify(data)


def test_incomplete_artifact_transfer_is_rejected(transferred):
    (transferred["root"] / "workers/worker-1/native.xml").unlink()
    with pytest.raises(ContractError, match="artifact differs"):
        verify(transferred)


def test_missing_worker_is_rejected(transferred):
    parent = transferred["root"] / "workers"
    old, new = parent / "worker-1", parent / "missing-worker"
    assert old.resolve().is_relative_to(transferred["root"].resolve())
    assert new.resolve().is_relative_to(transferred["root"].resolve())
    old.rename(new)
    with pytest.raises(ContractError, match="missing/foreign worker"):
        verify(transferred)


@pytest.mark.parametrize("field", ["head", "tree", "attempt"])
def test_wrong_independent_source_or_attempt_does_not_match_receipt(transferred, field):
    transferred["trust"] = deepcopy(transferred["trust"])
    if field == "attempt":
        transferred["trust"]["context"]["attempt"] = 2
    else:
        transferred["trust"]["context"]["source"][field] = "f" * 40
    with pytest.raises(ContractError, match="source/run/attempt"):
        verify(transferred)


def test_simulated_evidence_cannot_be_relabelled_real(transferred):
    data = transferred; receipt = read_json(data["root"] / "observations.json")
    receipt["context"]["mode"] = "simulated"
    write_json(data["root"] / "observations.json", reseal(receipt))
    data["anchor"] = hashlib.sha256((data["root"] / "observations.json").read_bytes()).hexdigest()
    data["trust"] = deepcopy(data["trust"]); data["trust"]["context"]["mode"] = "simulated"
    with pytest.raises(ContractError, match="simulated process evidence"):
        verify(data)


def test_unapproved_evaluator_content_is_rejected(transferred):
    transferred["producer"] = {"evaluator": "unknown", "files_sha256": {}}
    with pytest.raises(ContractError, match="producer content"):
        verify(transferred)
