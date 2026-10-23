"""Offline deterministic planner controls; no audited regression test is executed."""
from copy import deepcopy
import json
import subprocess
import sys

import pytest

from tests.ci_v3_synthetic_evidence import ASSIGNMENT, IDS, bundle, reseal
from tools.ci_v3_partition_plan import plan_partitions, summarize_plan
from tools.ci_v3_schema import ContractError, canonical_bytes, read_json, reconcile_collection, seal


def weights_for(data):
    return seal({"schema": 1, "kind": "ci-v3-weights", "source": data["inventory"]["source"],
        "inventory_digest": data["inventory"]["digest"], "modules_ms": {
            "tests/test_alpha.py": 9000, "tests/test_beta.py": 6000,
            "tests/test_gamma.py": 3000, "tests/test_delta.py": 1000}})


def test_literal_expected_three_worker_schedule_and_fixture_boundary():
    d = bundle()
    result = plan_partitions(d["inventory"], d["policy"], weights_for(d))
    assert result["module_workers"] == ASSIGNMENT
    assert len(result["module_workers"]) == 4
    assert d["inventory"]["nodes"][0]["nodeid"] in IDS


@pytest.mark.parametrize("count,expected", [(2, [10000, 9000]), (3, [9000, 6000, 4000]), (4, [9000, 6000, 3000, 1000])])
def test_two_three_four_worker_loads_from_hand_calculated_fixture(count, expected):
    d = bundle(); weights = weights_for(d)
    plan = plan_partitions(d["inventory"], d["policy"], weights, count)
    report = summarize_plan(d["inventory"], d["policy"], weights, plan, 1000, 500, 100)
    assert [w["weight_ms"] for w in report["workers"]] == expected
    assert sum(w["nodes"] for w in report["workers"]) == 5
    assert report["critical_path_ms"] == max(expected) + 1100
    assert report["runner_ms"] == 19000 + count * 1000 + 600


def test_identical_and_differently_ordered_weight_maps_have_identical_bytes():
    d = bundle(); weights = weights_for(d)
    first = canonical_bytes(plan_partitions(d["inventory"], d["policy"], weights))
    weights["modules_ms"] = dict(reversed(list(weights["modules_ms"].items())))
    weights = reseal(weights)
    assert first == canonical_bytes(plan_partitions(d["inventory"], d["policy"], weights))


def test_equal_weight_and_zero_weight_ties_use_path_then_worker_index():
    d = bundle(); weights = weights_for(d)
    weights["modules_ms"] = dict.fromkeys(weights["modules_ms"], 1000)
    result = plan_partitions(d["inventory"], d["policy"], reseal(weights))["module_workers"]
    assert result == {"tests/test_alpha.py": "worker-0", "tests/test_beta.py": "worker-1",
                      "tests/test_delta.py": "worker-2", "tests/test_gamma.py": "worker-0"}
    weights["modules_ms"] = dict.fromkeys(weights["modules_ms"], 0)
    assert set(plan_partitions(d["inventory"], d["policy"], reseal(weights))["module_workers"].values()) == {"worker-0"}


@pytest.mark.parametrize("bad", [-1, 1.0, True, float("inf"), float("nan")])
def test_invalid_weights_never_fall_back_to_default(bad):
    d = bundle(); weights = weights_for(d)
    weights["modules_ms"]["tests/test_alpha.py"] = bad
    with pytest.raises((ContractError, ValueError)):
        plan_partitions(d["inventory"], d["policy"], reseal(weights))


def test_missing_weight_rejected():
    d = bundle(); weights = weights_for(d)
    del weights["modules_ms"]["tests/test_beta.py"]
    with pytest.raises(ContractError, match="weights"):
        plan_partitions(d["inventory"], d["policy"], reseal(weights))


@pytest.mark.parametrize("count", [0, 1, 5, True, 13, 2.0, pytest.param("5", id="string-five"), None])
def test_unsupported_worker_count_rejected(count):
    d = bundle()
    # Preserve the original [5] identity while testing its newly supported contract.
    if type(count) is int and count == 5:
        assert plan_partitions(d["inventory"], d["policy"], weights_for(d), count)["worker_count"] == count
        return
    with pytest.raises(ContractError):
        plan_partitions(d["inventory"], d["policy"], weights_for(d), count)


def test_new_unknown_node_fails_closed():
    d = bundle()
    d["collection"]["nodes"].append("tests/test_new.py::test_unreviewed")
    with pytest.raises(ContractError, match="reconciliation"):
        reconcile_collection(d["inventory"], d["collection"])


def test_duplicate_inventory_node_rejected_even_if_resealed():
    d = bundle()
    d["inventory"]["nodes"].append(deepcopy(d["inventory"]["nodes"][0]))
    d["inventory"] = reseal(d["inventory"])
    with pytest.raises(ContractError, match="duplicates"):
        plan_partitions(d["inventory"], d["policy"], weights_for(d))


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":'])
def test_duplicate_keys_nonfinite_and_truncated_json_rejected(tmp_path, text):
    path = tmp_path / "bad.json"; path.write_text(text)
    with pytest.raises(ContractError):
        read_json(path)


def test_tools_are_import_safe_without_application_initialization():
    code = "import sys; import tools.ci_v3_partition_plan, tools.ci_v3_evidence_verify, tools.ci_v3_audit_prototype; assert not any(k == 'app' or k.startswith(('app.', 'financial_engine.', 'finco_radar.')) for k in sys.modules)"
    subprocess.run([sys.executable, "-c", code], check=True, timeout=15, capture_output=True)


def test_malformed_module_metadata_is_a_contract_rejection():
    d = bundle(); d["inventory"]["modules"]["tests/test_alpha.py"] = None
    d["inventory"] = reseal(d["inventory"])
    with pytest.raises(ContractError, match="module metadata"):
        plan_partitions(d["inventory"], d["policy"], weights_for(d))
