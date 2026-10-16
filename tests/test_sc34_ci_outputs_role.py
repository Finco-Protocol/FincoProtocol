"""PR #292: the established `outputs` browser role now requires BOTH Chromium acceptance modules (fail-closed)."""
from __future__ import annotations

import json
import shutil
import sys

import pytest

from tests.test_model_workspace_consolidation import (
    _workspace_ci_matrix, _workspace_ci_outputs_evidence, _workspace_ci_role_evidence)
from tools.ci_acceptance import EvidenceError
from tools.ci_browser_job import OUTPUTS_ACCEPTANCE, REQUIRED, SELECTIONS, validate_browser_records

HEAD, TREE = "a" * 40, "b" * 40
STATEMENTS = "tests.model_statements_tree_acceptance"
WORKSPACE = "tests.model_outputs_workspace_acceptance"


def validate(tmp_path):
    return validate_browser_records(tmp_path, HEAD, TREE, "success")


def fresh(tmp_path, **outputs_kwargs):
    _workspace_ci_matrix(tmp_path, "browser", HEAD, TREE)
    if outputs_kwargs:
        folder = tmp_path / "browser-outputs"
        shutil.rmtree(folder)
        _workspace_ci_role_evidence(tmp_path, "browser", "outputs", HEAD, TREE)
        folder = tmp_path / "browser-outputs"
        _rewrite_outputs(folder, **outputs_kwargs)
    return tmp_path


def _rewrite_outputs(folder, **kwargs):
    """Rebuild the role folder with the tampered evidence and a manifest that matches it (so only the content is wrong)."""
    import hashlib
    _workspace_ci_outputs_evidence(folder, **kwargs)
    manifest = {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob("*") if p.is_file() and p.name != "manifest.json"}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_all_six_roles_and_every_existing_selection_are_preserved():
    assert set(REQUIRED) == {"protocol", "import", "grid", "q4", "outputs", "consolidation"}
    assert SELECTIONS["import"] == ["tests/test_model_ai_import_browser_c.py", "tests/test_model_import_v2_browser.py"]
    assert SELECTIONS["q4"] == ["tests/test_model_q4_browser.py"] and "outputs" not in SELECTIONS
    assert "artifacts/outputs-workspace/browser-results.json" in REQUIRED["outputs"] and "artifacts/outputs-workspace/*.png" in REQUIRED["outputs"]
    assert "artifacts/statements-tree/browser-results.json" in REQUIRED["outputs"] and "artifacts/statements-tree/*.png" in REQUIRED["outputs"]


def test_complete_evidence_for_both_modules_passes(tmp_path):
    fresh(tmp_path)
    proof = validate(tmp_path)
    assert set(proof["mandatory_roles"]) == set(REQUIRED)


@pytest.mark.parametrize("module", [WORKSPACE, STATEMENTS])
def test_a_failing_check_in_either_module_fails_the_gate(tmp_path, module):
    fresh(tmp_path, fail=module, exit_code=1)
    with pytest.raises(EvidenceError, match="exited abnormally|failed or incomplete"):
        validate(tmp_path)


@pytest.mark.parametrize("module", [WORKSPACE, STATEMENTS])
def test_missing_module_results_fail(tmp_path, module):
    fresh(tmp_path)
    folder = tmp_path / "browser-outputs" / OUTPUTS_ACCEPTANCE[module]["folder"]
    (folder / "browser-results.json").unlink()
    _rewrite_manifest(tmp_path / "browser-outputs")
    with pytest.raises(EvidenceError, match="Missing mandatory outputs evidence|Missing browser results"):
        validate(tmp_path)


def _rewrite_manifest(folder):
    import hashlib
    manifest = {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob("*") if p.is_file() and p.name != "manifest.json"}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_missing_statements_evidence_cannot_hide_behind_the_original_module(tmp_path):
    fresh(tmp_path)
    folder = tmp_path / "browser-outputs"
    shutil.rmtree(folder / "statements-tree")
    _rewrite_manifest(folder)
    with pytest.raises(EvidenceError, match="Missing mandatory"):
        validate(tmp_path)


def test_role_record_must_name_exactly_both_modules(tmp_path):
    fresh(tmp_path)
    folder = tmp_path / "browser-outputs"
    record = json.loads((folder / "outputs-role.json").read_text())
    record["modules"].pop(STATEMENTS)
    (folder / "outputs-role.json").write_text(json.dumps(record))
    _rewrite_manifest(folder)
    with pytest.raises(EvidenceError, match="exactly the mandatory"):
        validate(tmp_path)
    (folder / "outputs-role.json").unlink()
    _rewrite_manifest(folder)
    with pytest.raises(EvidenceError, match="Missing mandatory|Missing outputs role record"):
        validate(tmp_path)


def test_required_statement_check_must_be_recorded_as_pass(tmp_path):
    fresh(tmp_path, drop=STATEMENTS)
    with pytest.raises(EvidenceError, match="Required browser check not recorded as PASS"):
        validate(tmp_path)


def test_wrong_schema_and_tampered_screenshot_fail(tmp_path):
    fresh(tmp_path)
    folder = tmp_path / "browser-outputs"
    results = folder / "statements-tree" / "browser-results.json"
    data = json.loads(results.read_text())
    data["schema"] = "something.else"
    results.write_text(json.dumps(data))
    _rewrite_manifest(folder)
    with pytest.raises(EvidenceError, match="Wrong browser results schema"):
        validate(tmp_path)
    data["schema"] = OUTPUTS_ACCEPTANCE[STATEMENTS]["schema"]
    results.write_text(json.dumps(data))
    shot = sorted((folder / "statements-tree").glob("*.png"))[0]
    shot.write_bytes(shot.read_bytes() + b"x")                    # content changed after its hash was recorded
    _rewrite_manifest(folder)
    with pytest.raises(EvidenceError, match="screenshot changed|Incomplete|Truncated|Invalid"):
        validate(tmp_path)


def test_a_wrong_head_or_tree_for_the_role_is_still_rejected(tmp_path):
    fresh(tmp_path)
    with pytest.raises(EvidenceError, match="Wrong browser source"):
        validate_browser_records(tmp_path, "c" * 40, TREE, "success")


def test_runner_executes_both_modules_and_fails_if_either_fails(tmp_path, monkeypatch):
    from tools import ci_outputs_role as R
    calls = []

    class Done:
        def __init__(self, code):
            self.returncode = code

    def fake_run(cmd):
        calls.append(cmd[2])
        return Done(1 if cmd[2] == WORKSPACE else 0)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(R.subprocess, "run", fake_run)
    assert R.main() == 1
    assert calls == [WORKSPACE, STATEMENTS]                         # the second module still runs after the first fails
    record = json.loads((tmp_path / "artifacts" / "outputs-role.json").read_text())["modules"]
    assert record[WORKSPACE]["exit_code"] == 1 and record[STATEMENTS]["exit_code"] == 0
    monkeypatch.setattr(R.subprocess, "run", lambda cmd: Done(0))
    assert R.main() == 0


def test_job_command_for_the_outputs_role_is_the_two_module_runner():
    import inspect
    from tools import ci_browser_job
    text = inspect.getsource(ci_browser_job.main)
    assert '"tools.ci_outputs_role"' in text and "tests.model_outputs_workspace_acceptance" not in text
    from tools import ci_outputs_role
    assert [m for m, _ in ci_outputs_role.MODULES] == [WORKSPACE, STATEMENTS]
    assert sys.executable
