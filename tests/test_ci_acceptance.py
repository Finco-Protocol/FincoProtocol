"""CI partition/aggregate adversarial tests; no financial runtime changes."""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools.ci_acceptance import EvidenceError, attest, compare_records, partition_modules, weights_from_junit
from tools.ci_browser_job import REQUIRED, SELECTIONS, manifest, validate_browser_records, validate_consolidation
from tools.ci_acceptance import run_command
from tools.ci_measurement import distribution


HEAD = "a" * 40
TREE = "b" * 40
NODES = ["tests/test_one.py::test_a", "tests/test_one.py::test_b", "tests/test_two.py::test_c"]


def proof():
    control = {"schema": 1, "head": HEAD, "tree": TREE, "pytest_exit": 0,
               "collected": NODES, "selected": NODES, "deselected": [],
               "collection_skips": [["tests/test_browser.py", "Playwright not installed"]],
               "collection_errors": [], "shard": None,
               "outcomes": {node: {"status": "passed", "reason": ""} for node in NODES}}
    shards = []
    for slot, selected in enumerate((NODES[:2], NODES[2:])):
        shard = deepcopy(control)
        shard.update(shard=slot, selected=selected, deselected=sorted(set(NODES) - set(selected)),
                     outcomes={node: control["outcomes"][node] for node in selected})
        shards.append(shard)
    processes = [{"head": HEAD, "tree": TREE, "exit_code": 0, "normal_exit": True,
                  "junit_sha256": "digest", "junit_failures": 0, "environment_sha256": "environment",
                  "elapsed_seconds": 10.0} for _ in range(3)]
    return control, shards, processes


def verify(control, shards, processes, results=None):
    return compare_records(control, shards, processes, HEAD, TREE, results or ["success"] * 3)


def test_valid_complete_whole_module_shadow_proof():
    assert verify(*proof())["equivalent"] is True


@pytest.mark.parametrize("status", ["failure", "cancelled", "timed_out", "skipped", "", None, "in_progress"])
def test_non_success_job_fails_required_aggregate(status):
    with pytest.raises(EvidenceError, match="job"):
        verify(*proof(), ["success", status, "success"])


def test_missing_shard_fails():
    control, shards, processes = proof()
    with pytest.raises(EvidenceError, match="Missing shard"):
        verify(control, shards[:1], processes)


def test_missing_process_artifact_fails():
    control, shards, processes = proof()
    with pytest.raises(EvidenceError, match="process artifact"):
        verify(control, shards, processes[:2])


@pytest.mark.parametrize("field,value", [("head", "wrong"), ("tree", "wrong"), ("pytest_exit", 1),
                                        ("collection_errors", [["module", "ImportError"]]),
                                        ("selected", []), ("shard", 1)])
def test_invalid_shard_attestation_or_collection_fails(field, value):
    control, shards, processes = proof()
    shards[0][field] = value
    with pytest.raises(EvidenceError):
        verify(control, shards, processes)


@pytest.mark.parametrize("field,value", [("exit_code", 124), ("normal_exit", False), ("head", "wrong"),
                                        ("tree", "wrong"), ("junit_sha256", ""), ("junit_failures", 1),
                                        ("environment_sha256", "different")])
def test_invalid_process_or_artifact_fails(field, value):
    control, shards, processes = proof()
    processes[1][field] = value
    with pytest.raises(EvidenceError):
        verify(control, shards, processes)


def test_duplicate_node_fails():
    control, shards, processes = proof()
    shards[0]["selected"].append(NODES[0])
    with pytest.raises(EvidenceError, match="Duplicate"):
        verify(control, shards, processes)


def test_missing_node_outcome_fails():
    control, shards, processes = proof()
    del shards[0]["outcomes"][NODES[0]]
    with pytest.raises(EvidenceError, match="outcomes"):
        verify(control, shards, processes)


def test_unexpected_skip_reason_fails():
    control, shards, processes = proof()
    shards[0]["outcomes"][NODES[0]] = {"status": "skipped", "reason": "unexpected"}
    with pytest.raises(EvidenceError, match="skip/xfail"):
        verify(control, shards, processes)


def test_unexpected_collection_skip_fails():
    control, shards, processes = proof()
    shards[0]["collection_skips"].append(["extra", "missing dependency"])
    with pytest.raises(EvidenceError, match="collection skips"):
        verify(control, shards, processes)


def test_split_module_fixtures_rejected_even_if_node_union_matches():
    control, shards, processes = proof()
    for slot, selected in enumerate(([NODES[0]], NODES[1:])):
        shards[slot]["selected"] = selected
        shards[slot]["deselected"] = sorted(set(NODES) - set(selected))
        shards[slot]["outcomes"] = {node: control["outcomes"][node] for node in selected}
    with pytest.raises(EvidenceError, match="Module fixture split"):
        verify(control, shards, processes)


def test_control_selection_cannot_be_weakened():
    control, shards, processes = proof()
    control["deselected"] = [NODES[0]]
    with pytest.raises(EvidenceError, match="Control unexpectedly"):
        verify(control, shards, processes)


def test_partition_is_deterministic_and_preserves_modules():
    weights = {"tests/test_one.py": 30, "tests/test_two.py": 20}
    plan = partition_modules(NODES, weights)
    assert plan == partition_modules(reversed(NODES), weights)
    assert plan == {"tests/test_one.py": 0, "tests/test_two.py": 1}


def test_unknown_modules_still_partition_without_omission():
    assert set(partition_modules(NODES, {})) == {"tests/test_one.py", "tests/test_two.py"}


def test_source_junit_weights_are_instrumentation_not_financial_inputs(tmp_path):
    xml = tmp_path / "results.xml"
    xml.write_text('<testsuite><testcase classname="tests.test_one.TestClass" time="2.5"/>\n'
                   '<testcase classname="tests.test_one.TestClass" time="3.0"/></testsuite>', encoding="utf-8")
    weights = weights_from_junit(xml, "source-run")
    assert weights["modules"] == {"tests/test_one.py": 5.5}
    assert len(weights["junit_sha256"]) == 64


def test_wrong_git_head_rejected(monkeypatch):
    monkeypatch.setattr("tools.ci_acceptance.git_value", lambda *args: "actual")
    with pytest.raises(EvidenceError, match="Wrong tested SHA"):
        attest("expected")


def test_plugin_real_collection_outcomes_and_module_partition(tmp_path):
    paths = []
    for index in range(2):
        path = tmp_path / f"test_synthetic_{index}.py"
        path.write_text("import pytest\ndef test_pass(): assert True\n"
                        "@pytest.mark.skip(reason='synthetic reason')\ndef test_skip(): pass\n", encoding="utf-8")
        paths.append(str(path))
    weights = tmp_path / "weights.json"
    weights.write_text('{"modules": {}}', encoding="utf-8")
    records = []
    for slot in (None, 0, 1):
        output = tmp_path / f"inventory-{slot}.json"
        command = [sys.executable, "-m", "pytest", "-q", "--confcutdir", str(tmp_path),
                   "-p", "tools.ci_pytest_inventory", f"--ci-inventory={output}",
                   f"--ci-weights={weights}", *paths]
        if slot is not None:
            command.append(f"--ci-shard={slot}")
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        records.append(json.loads(output.read_text(encoding="utf-8")))
    assert len(records[0]["selected"]) == 4
    assert {v["status"] for v in records[0]["outcomes"].values()} == {"passed", "skipped"}
    assert set(records[1]["selected"]).isdisjoint(records[2]["selected"])
    assert set(records[1]["selected"] + records[2]["selected"]) == set(records[0]["selected"])


def test_frozen_financial_namespaces_unmodified():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["git", "diff", "--name-only", "origin/main", "--", "financial_engine", "finco_core", "domain"],
                            cwd=root, text=True, capture_output=True, check=True)
    assert result.stdout.strip() == ""


@pytest.mark.parametrize("role", list(REQUIRED))
def test_missing_mandatory_browser_capture_fails(role, tmp_path):
    (tmp_path / "artifacts").mkdir()
    with pytest.raises(EvidenceError, match="Missing mandatory"):
        manifest(role, tmp_path)


@pytest.mark.parametrize("status", ["failure", "cancelled", "skipped", "", None])
def test_browser_matrix_non_success_cannot_pass(status, tmp_path):
    with pytest.raises(EvidenceError, match="Browser matrix"):
        validate_browser_records(tmp_path, HEAD, TREE, status)


def test_browser_missing_artifact_cannot_pass(tmp_path):
    with pytest.raises(FileNotFoundError):
        validate_browser_records(tmp_path, HEAD, TREE, "success")


def test_existing_browser_selection_is_not_weakened():
    assert SELECTIONS["protocol"] == [
        "tests/test_ui_protocol_shell.py", "tests/test_protocol_roadmap_browser.py",
        "tests/test_crypto_navigation_browser.py", "tests/test_ev_charging_browser.py",
        "tests/test_yield_browser.py", "-k", "not test_api_b04_placeholders_not_links"]
    assert SELECTIONS["import"] == ["tests/test_model_ai_import_browser_c.py"]
    assert SELECTIONS["grid"] == ["tests/test_model_hybrid_inputs_grid_routes.py", "tests/test_model_hybrid_inputs_grid_browser.py"]
    assert SELECTIONS["q4"] == ["tests/test_model_q4_browser.py"]
    assert SELECTIONS["consolidation"] == ["tests/test_model_workspace_consolidation_browser.py"]
    assert REQUIRED["consolidation"] == ["artifacts/workspace-consolidation/prb-*.png"]


def test_required_gate_triggers_do_not_depend_on_changed_paths():
    root = Path(__file__).resolve().parents[1]
    for name in ("public_safety_and_smoke", "protocol_ui_browser", "pr_compile_and_safety", "governance_history", "dependency_security_audit"):
        text = (root / ".github" / "workflows" / (name + ".yml")).read_text(encoding="utf-8")
        assert "pull_request:" in text
        assert "paths:" not in text
        assert "head.sha" in text


def _workflow(name):
    import yaml
    path = Path(__file__).resolve().parents[1] / ".github/workflows" / name
    return yaml.safe_load(path.read_text(encoding="utf-8")), path.read_text(encoding="utf-8")


def test_shadow_does_not_replace_unsharded_gate_or_merge_coverage():
    """CI V2 contract (supersedes the #247 shard/duplicate-merge-run structure).

    The behavioural requirements are unchanged and are asserted directly: the Public Safety suite is ONE
    complete, unsharded, undeselected pytest on the exact HEAD; the synthetic merge is proven to have an
    identical Git tree BEFORE any dependency installation (a mismatch fails closed instead of silently
    testing different code); the mandatory aggregate verifies the artifacts independently of job badges.
    """
    public, public_text = _workflow("public_safety_and_smoke.yml")
    reusable, reusable_text = _workflow("ci_public_job.yml")
    jobs = public["jobs"]
    assert set(jobs) == {"source-safety", "safety-and-smoke", "mandatory-evidence"}      # seven-job budget, no shards
    control = jobs["safety-and-smoke"]
    assert control["uses"].endswith("ci_public_job.yml") and control["with"]["mode"] == "control"
    assert {"merge-sha", "pr-number", "tested-sha"} <= set(control["with"])
    gate = jobs["mandatory-evidence"]
    assert gate["if"] == "always()" and set(gate["needs"]) == {"source-safety", "safety-and-smoke"}
    gate_runs = "\n".join(step.get("run", "") for step in gate["steps"])
    assert "tools.ci_single_gate" in gate_runs and "--source-result" in gate_runs and "--control-result" in gate_runs
    assert "continue-on-error" not in public_text and "continue-on-error" not in reusable_text

    steps = reusable["jobs"]["tests"]["steps"]
    runs = [step.get("run", "") for step in steps]
    index = lambda needle: next(i for i, r in enumerate(runs) if needle in r)   # noqa: E731
    guard, install, pytest_step = index("ci_merge_tree_guard"), index("pip install"), index("ci_pytest_runner.py")
    assert guard < install < pytest_step, "tree equality must be proven before dependencies and before pytest"
    invocation = runs[pytest_step].split("ci_pytest_runner.py", 1)[1]      # pytest's own arguments only
    import re
    assert not re.search(r"(?<!\S)(-k|-m|-x|--lf|--deselect|--ignore|--maxfail|--ci-shard)\b", invocation), invocation
    assert "--ci-inventory=artifacts/inventory.json" in invocation and "--junitxml=artifacts/results.xml" in invocation
    assert "$MODE" not in runs[pytest_step] and "shard" not in invocation, "no per-mode selection branches"
    assert "ci_pytest_runner.py" in runs[pytest_step]                           # the supervisor stays authoritative


def test_ci_workflows_do_not_reintroduce_shadow_or_duplicate_execution_paths():
    public, _ = _workflow("public_safety_and_smoke.yml")
    reusable, reusable_text = _workflow("ci_public_job.yml")
    assert "--ci-shard" not in reusable_text and "shadow" not in "".join(public["jobs"])
    assert not any(name in public["jobs"] for name in ("merge-result-integration", "shadow-shards"))


@pytest.mark.parametrize("markers,expected", [(True, 0), (False, 1)])
def test_full_progress_is_not_normal_process_exit_proof(markers, expected, tmp_path, monkeypatch):
    monkeypatch.setattr("tools.ci_acceptance.attest", lambda value: {"head": HEAD, "tree": TREE})
    monkeypatch.setattr("tools.ci_acceptance.environment_digest", lambda: "environment")
    code = "# ci_pytest_runner.py\nprint('100%')\n"
    if markers:
        code += "print('PYTEST_MAIN_RETURNED FINCO_CI_MARKER after pytest.main rc=0')\n"
        code += "print('PYTHON_PROCESS_EXITED FINCO_CI_SUPERVISOR child exit code 0')\n"
    output = tmp_path / "process.json"
    result = run_command(argparse.Namespace(expected=HEAD, label="synthetic", output=output,
                                           junit=None, command=[sys.executable, "-c", code]))
    record = json.loads(output.read_text(encoding="utf-8"))
    assert result == expected
    assert record["normal_exit"] == markers


def test_measurement_nearest_rank_p90_does_not_invent_samples():
    assert distribution([]) is None
    assert distribution([1, 2, 3]) == {"samples": 3, "median": 2, "p90_nearest_rank": 3, "maximum": 3}


def test_accepted_consolidation_gates_both_browser_matrices():
    """CI V2 contract: ONE runner, SIX isolated supervised role processes, tree-equality instead of a second matrix.

    The #247 structure (two six-role matrices) is replaced; what it protected is asserted directly: every
    mandatory role (including the 17-node consolidation module) runs in its own fresh Python/pytest process
    with its own temp dir, a role failure fails the job, and the fail-closed aggregate runs after all roles.
    """
    browser, text = _workflow("protocol_ui_browser.yml")
    assert list(browser["jobs"]) == ["mandatory-browser-evidence"]                      # stable required context
    steps = {step.get("name", ""): step for step in browser["jobs"]["mandatory-browser-evidence"]["steps"]}
    roles = next(step for name, step in steps.items() if name.startswith("All SIX mandatory browser roles"))
    script = roles["run"]
    assert "for role in protocol import grid q4 outputs consolidation; do" in script
    assert set("protocol import grid q4 outputs consolidation".split()) == set(REQUIRED) == {
        *REQUIRED} and "consolidation" in SELECTIONS
    assert 'python -m tools.ci_browser_job "$role" --expected "$HEAD_SHA"' in script      # fresh process per role
    assert 'TMPDIR="$RUNNER_TEMP/finco-browser-$role"' in script                          # isolated temp per role
    assert 'mv artifacts "evidence/browser-$role"' in script                              # per-role evidence bundle
    assert script.index("done") < script.index("ci_browser_job aggregate")                 # aggregate after every role
    assert "set -euo pipefail" in script and "--job-result success" in script
    assert "continue-on-error" not in text and "merge-result-browser" not in browser["jobs"]
    names = list(steps)
    guard, install = (next(i for i, n in enumerate(names) if k in n) for k in ("synthetic merge tree", "Install and attest"))
    assert guard < install, "tree equality is proven before any dependency or Chromium installation"
    assert any(step.get("with", {}).get("name") == "model-workspace-consolidation-browser" for step in steps.values())
    assert any(step.get("with", {}).get("if-no-files-found") == "error" for step in steps.values())


def test_consolidation_missing_collection_rejected(tmp_path):
    with pytest.raises(EvidenceError, match="collection"):
        validate_consolidation(tmp_path, {"selected": [], "collected": [], "outcomes": {}},
                               {"normal_exit": True, "exit_code": 0})


@pytest.mark.parametrize("status", ["skipped", "xfail", "failed", "error", "xpass"])
def test_consolidation_non_pass_result_rejected(tmp_path, status):
    nodes = [f"tests/test_model_workspace_consolidation_browser.py::test_{i}" for i in range(17)]
    outcomes = {node: {"status": "passed"} for node in nodes}
    outcomes[nodes[-1]] = {"status": status}
    with pytest.raises(EvidenceError, match="failed/skipped"):
        validate_consolidation(tmp_path, {"selected": nodes, "collected": nodes,
                                         "deselected": [], "outcomes": outcomes},
                               {"normal_exit": True, "exit_code": 0})


def test_consolidation_missing_junit_fails_closed(tmp_path):
    nodes = [f"tests/test_model_workspace_consolidation_browser.py::test_{i}" for i in range(17)]
    with pytest.raises(EvidenceError, match="JUnit"):
        validate_consolidation(tmp_path, {"selected": nodes, "collected": nodes,
                                         "deselected": [], "outcomes": {n: {"status": "passed"} for n in nodes}},
                               {"normal_exit": True, "exit_code": 0})
