"""CI V4 aggregation: executed == selected, never a hidden skip/forged shard/tampered plan."""
import copy
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
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


# Exact collection-skip shape from run 42042550762, junit-shard-2.xml.
BROWSER = "tests/test_model_workspace_productivity_v1_browser.py"
COLLECTION = '''<testcase classname="" name="tests.test_model_workspace_productivity_v1_browser" time="0.000"><skipped message="collection skipped">('/home/runner/work/FincoProtocol/FincoProtocol/tests/test_model_workspace_productivity_v1_browser.py', 19, 'Skipped: playwright not installed in this workflow')</skipped></testcase>'''


def _collection_fixture(tmp_path, xml=COLLECTION, no_skip=False):
    from tools.ci_v4_schedule import plan_digest
    p = {"tier": "risk", "tested_sha": SHA, "tested_tree": TREE, "pytest_modules": [BROWSER],
         "no_skip_modules": [BROWSER] if no_skip else [], "schedule": {"shards": [[BROWSER]]},
         "rule_ids": [], "triggers": [], "not_selected": {"count": 0}}
    p["digest"] = plan_digest(p)
    j = tmp_path / "junit-shard-0.xml"
    j.write_text("<testsuite>" + xml + "</testsuite>")
    return p, j


def test_actual_collection_skip_is_attributed_and_remains_skipped(tmp_path):
    p, j = _collection_fixture(tmp_path)
    assert A._module_of("", {BROWSER[:-3].replace("/", "."): BROWSER}) is None
    r = A.aggregate(p, _shards(p), [j])
    assert r["verdict"] == "PASS", r["problems"]
    assert r["counts"] == {"passed": 0, "skipped": 1, "failed": 0, "error": 0}
    assert r["skipped_ids"] == ["::tests.test_model_workspace_productivity_v1_browser"]
    assert r["skipped_cases"] == [{"id": r["skipped_ids"][0], "module": BROWSER, "status": "SKIPPED",
                                   "reason": "playwright not installed in this workflow"}]


@pytest.mark.parametrize("xml", [
    "",  # selected regular module without any case still fails
    COLLECTION.replace("classname=\"\"", "classname=\"tests.test_foreign\""),
    COLLECTION.replace("name=\"tests.test_model_workspace_productivity_v1_browser\"", "name=\"tests.test_foreign\""),
    COLLECTION.replace(".py', 19", "_foreign.py', 19"),
    COLLECTION.replace("message=\"collection skipped\"", "message=\"ordinary skip\""),
    COLLECTION.replace("message=\"collection skipped\"", "type=\"pytest.skip\" message=\"collection skipped\""),
    COLLECTION.replace("<skipped", "<failure").replace("</skipped>", "</failure>"),
    COLLECTION.replace("<skipped", "<error").replace("</skipped>", "</error>"),
    COLLECTION.replace("</testcase>", "<failure message='hidden'/></testcase>"),
    COLLECTION.replace("</testcase>", "<skipped message='collection skipped'/></testcase>"),
    COLLECTION.replace("time=\"0.000\"", "file=\"tests/test_foreign.py\""),
    COLLECTION.replace("('/home", "['/home").replace("workflow')", "workflow']"),
    COLLECTION.replace("19,", "0,"),
    COLLECTION.replace("19,", "True,"),
    COLLECTION.replace("Skipped: playwright", "playwright"),
    COLLECTION.replace("/tests/test_", "/../tests/test_"),
    COLLECTION.replace("('/home/runner/work/FincoProtocol/FincoProtocol/", "('"),
    COLLECTION.replace("('/home", "not_a_tuple('/home"),
    COLLECTION.replace("('/home", "('/home/") ,
    COLLECTION.replace("</skipped>", "<unexpected/></skipped>"),
    COLLECTION.replace("</skipped>", "</skipped>") + "<testcase classname='' name='test_foreign'/>",
])
def test_foreign_forged_or_missing_collection_evidence_fails(tmp_path, xml):
    p, j = _collection_fixture(tmp_path, xml)
    assert A.aggregate(p, _shards(p), [j])["verdict"] == "FAIL"


def test_collection_skip_no_skip_duplicate_and_binding_invariants(tmp_path):
    p, j = _collection_fixture(tmp_path, no_skip=True)
    assert A.aggregate(p, _shards(p), [j])["verdict"] == "FAIL"
    p, j = _collection_fixture(tmp_path)
    assert A.aggregate(p, _shards(p), [j], pytest_tier_skip_policy=0)["verdict"] == "FAIL"
    assert A.aggregate(p, _shards(p), [j, j])["verdict"] == "FAIL"
    assert A.aggregate(p, _shards(p) * 2, [j])["verdict"] == "FAIL"
    assert A.aggregate(p, [], [j])["verdict"] == "FAIL"
    for key in ("sha", "tree", "plan_digest"):
        assert A.aggregate(p, _shards(p, **{key: "d" * 40}), [j])["verdict"] == "FAIL"
    p["pytest_modules"] = []
    with pytest.raises(A.AggregateError, match="digest mismatch"):
        A.aggregate(p, _shards(p), [j])


def test_mixed_real_and_collection_skips_preserve_all_counts(tmp_path):
    ordinary = "<testcase classname='tests.test_model_workspace_productivity_v1_browser' name='test_one'><skipped type='pytest.skip' message='ordinary reason'/></testcase>"
    p, j = _collection_fixture(tmp_path, COLLECTION + ordinary)
    r = A.aggregate(p, _shards(p), [j])
    assert r["verdict"] == "PASS" and r["counts"]["skipped"] == 2 and r["counts"]["passed"] == 0
    assert {c["reason"] for c in r["skipped_cases"]} == {"ordinary reason", "playwright not installed in this workflow"}


def test_collection_skip_cannot_replace_exact_node_evidence(tmp_path):
    p, j = _collection_fixture(tmp_path)
    p["node_split"] = {"modules": {BROWSER: {}}, "schema": "invalid"}
    from tools.ci_v4_schedule import plan_digest
    p["digest"] = plan_digest(p)
    r = A.aggregate(p, _shards(p), [j])
    assert r["verdict"] == "FAIL" and any("never executed" in x for x in r["problems"])


def test_fresh_pytest_process_emits_supported_collection_shape(tmp_path):
    # Real producer, independent of the repository's conftest/plugins and Playwright installation.
    (tmp_path / "test_optional.py").write_text("import pytest\npytest.importorskip('finco_intentionally_absent_dependency', reason='optional dependency absent')\n")
    j = tmp_path / "actual.xml"
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "--noconftest", "--junitxml=" + str(j), "test_optional.py"],
                          cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 5, proc.stdout + proc.stderr
    c = next(ET.parse(j).iter("testcase"))
    assert c.get("classname") == "" and c.get("name") == "test_optional"
    case = A.read_junit(j)[0]
    assert A._collection_skip_module(case, {"test_optional": "test_optional.py"}, set(), set()) == "test_optional.py"
    assert case["skip_reason"] == "optional dependency absent"


@pytest.mark.parametrize("mutation", [None, "subject", "trusted", "other_pr", "other_base"])
def test_workflow_authenticates_only_exact_correction_h_successor(tmp_path, mutation):
    import os
    import shutil
    import yaml
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci_v4_pr.yml").read_text())
    step = next(s for s in workflow["jobs"]["gate"]["steps"] if s.get("name", "").startswith("Aggregate ("))
    base = "1f418d76654944f217d50731138c251c4958e9c1"
    old = subprocess.check_output(["git", "show", base + ":tools/ci_v4_aggregate.py"], cwd=ROOT)
    for role, raw in (("trusted", old), ("subject", (ROOT / "tools/ci_v4_aggregate.py").read_bytes())):
        d = tmp_path / role / "tools"
        d.mkdir(parents=True)
        (d / "__init__.py").write_text("")
        (d / "ci_v4_aggregate.py").write_bytes(raw + (b"\n" if mutation == role else b""))
    p, j = _collection_fixture(tmp_path)
    pd = tmp_path / "ev/ci-v4-plan"; pd.mkdir(parents=True)
    (pd / "ci-v4-plan.json").write_text(json.dumps(p))
    sd = tmp_path / "ev/shards"; sd.mkdir()
    shutil.copyfile(j, sd / j.name)
    (sd / "shard-0.json").write_text(json.dumps(_shards(p)[0]))
    env = {**os.environ, "NODE_SPLIT": "false", "BASE_SHA": "c" * 40 if mutation == "other_base" else base,
           "PR_NUMBER": "424" if mutation == "other_pr" else "423",
           "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]}
    env.pop("PYTHONPATH", None)
    proc = subprocess.run(["bash", "-c", step["run"]], cwd=tmp_path, env=env, capture_output=True, text=True)
    if mutation is None:
        assert proc.returncode == 0, proc.stdout + proc.stderr
        result = json.loads((tmp_path / "result/ci-v4-result.json").read_text())
        assert result["verdict"] == "PASS" and result["counts"]["skipped"] == 1 and result["counts"]["passed"] == 0
        assert (pd / "ci-v4-plan.json").read_text() == json.dumps(p)
    else:
        assert proc.returncode != 0, proc.stdout + proc.stderr
        if mutation in ("trusted", "subject"):
            assert "FAILED" in proc.stdout
            assert not (tmp_path / "result").exists()
        else:
            assert "authenticated exact" not in proc.stdout
