"""CI V4 aggregation: executed == selected, never a hidden skip/forged shard/tampered plan."""
import copy
import json
from pathlib import Path

import pytest

from tools import ci_v4_aggregate as A
from tools import ci_v4_select as S

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "docs/ci_v4/ci-v4-policy.json").read_text())
SHA, TREE = "a" * 40, "b" * 40


@pytest.fixture()
def plan():
    return S.select(["README.md"], copy.deepcopy(POLICY), root=ROOT, head_sha=SHA, tree_sha=TREE, base_sha="c" * 40)


def _junit(tmp_path, modules, status=None, name="j.xml", extra=None):
    rows = []
    for m in modules:
        cls = m[:-3].replace("/", ".")
        body = {"failed": "<failure message='x'/>", "skipped": "<skipped message='s'/>", "error": "<error message='e'/>"}.get((status or {}).get(m), "")
        rows.append("<testcase classname='%s' name='test_one' time='0.1'>%s</testcase>" % (cls, body))
    for cls in extra or []:
        rows.append("<testcase classname='%s' name='test_x' time='0.1'/>" % cls)
    p = tmp_path / name
    p.write_text("<testsuites><testsuite>%s</testsuite></testsuites>" % "".join(rows))
    return p


def _shards(plan, **over):
    out = []
    for i, mods in enumerate(plan["schedule"]["shards"]):
        r = {"shard": i, "sha": SHA, "tree": TREE, "plan_digest": plan["digest"], "modules": mods, "wall_s": 100.0}
        r.update(over)
        out.append(r)
    return out


def test_complete_selection_passes(plan, tmp_path):
    res = A.aggregate(plan, _shards(plan), [_junit(tmp_path, plan["pytest_modules"])])
    assert res["verdict"] == "PASS" and res["counts"]["passed"] == len(plan["pytest_modules"])
    assert res["not_selected"]["label"] == "NOT SELECTED (not PASS)"


def test_selected_module_never_executed_fails(plan, tmp_path):
    res = A.aggregate(plan, _shards(plan), [_junit(tmp_path, plan["pytest_modules"][1:])])
    assert res["verdict"] == "FAIL" and any("never executed" in p for p in res["problems"])


def test_skip_is_not_a_pass(plan, tmp_path):
    res = A.aggregate(plan, _shards(plan), [_junit(tmp_path, plan["pytest_modules"], {plan["pytest_modules"][0]: "skipped"})])
    assert res["verdict"] == "FAIL" and res["skipped_ids"]


@pytest.mark.parametrize("kind", ["failed", "error"])
def test_failure_or_error_fails(plan, tmp_path, kind):
    res = A.aggregate(plan, _shards(plan), [_junit(tmp_path, plan["pytest_modules"], {plan["pytest_modules"][-1]: kind})])
    assert res["verdict"] == "FAIL"


def test_foreign_executed_nodes_fail(plan, tmp_path):
    res = A.aggregate(plan, _shards(plan), [_junit(tmp_path, plan["pytest_modules"], extra=["tests.test_not_selected_v9"])])
    assert res["verdict"] == "FAIL"


def test_duplicate_nodes_across_shards_fail(plan, tmp_path):
    j = _junit(tmp_path, plan["pytest_modules"])
    k = _junit(tmp_path, plan["pytest_modules"][:1], name="k.xml")
    assert A.aggregate(plan, _shards(plan), [j, k])["verdict"] == "FAIL"


def test_shard_bound_to_other_sha_fails(plan, tmp_path):
    res = A.aggregate(plan, _shards(plan, sha="d" * 40), [_junit(tmp_path, plan["pytest_modules"])])
    assert res["verdict"] == "FAIL" and any("different sha" in p for p in res["problems"])


def test_tampered_plan_is_refused(plan, tmp_path):
    forged = dict(plan, pytest_modules=plan["pytest_modules"][:2])
    with pytest.raises(A.AggregateError):
        A.aggregate(forged, _shards(plan), [_junit(tmp_path, plan["pytest_modules"])])


def test_full_record_only_from_full_plan(plan, tmp_path):
    res = A.aggregate(plan, _shards(plan), [_junit(tmp_path, plan["pytest_modules"])])
    with pytest.raises(A.AggregateError):
        A.full_record(res, plan, 1, 1, "2026-11-04T00:00:00Z", 10)


def test_skip_outside_no_skip_modules_is_listed_as_skipped_not_pass(tmp_path):
    plan = S.select(["financial_engine/senior_debt/__init__.py"], copy.deepcopy(POLICY), root=ROOT, head_sha=SHA, tree_sha=TREE, base_sha="c" * 40)
    soft = next(m for m in plan["pytest_modules"] if m not in plan["no_skip_modules"])
    res = A.aggregate(plan, _shards(plan), [_junit(tmp_path, plan["pytest_modules"], {soft: "skipped"})])
    assert res["verdict"] == "PASS" and res["counts"]["skipped"] == 1 and res["skipped_label"] == "SKIPPED (not PASS)"
    assert res["counts"]["passed"] == len(plan["pytest_modules"]) - 1     # the skipped node is NOT counted as passed
    hard = plan["no_skip_modules"][0]
    res = A.aggregate(plan, _shards(plan), [_junit(tmp_path, plan["pytest_modules"], {hard: "skipped"}, name="h.xml")])
    assert res["verdict"] == "FAIL"


def test_changed_test_module_may_not_skip(tmp_path):
    plan = S.select(["tests/test_goal_seek_v1.py"], copy.deepcopy(POLICY), root=ROOT, head_sha=SHA, tree_sha=TREE, base_sha="c" * 40)
    assert "tests/test_goal_seek_v1.py" in plan["no_skip_modules"]


def test_changed_browser_module_is_not_no_skip_in_a_shard():
    plan = S.select(["tests/test_model_workspace_consolidation_browser.py"], copy.deepcopy(POLICY), root=ROOT, head_sha=SHA, tree_sha=TREE, base_sha="c" * 40)
    assert "tests/test_model_workspace_consolidation_browser.py" in plan["pytest_modules"]
    assert "tests/test_model_workspace_consolidation_browser.py" not in plan["no_skip_modules"]
