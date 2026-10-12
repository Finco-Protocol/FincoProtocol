"""CI V2 contract tests: identical Git trees, full control proof and fan-out bounds.

Synthetic local fixtures only. These tests never invoke the application or financial engine.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.ci_acceptance import EvidenceError
from tools.ci_merge_tree_guard import prove_merge_tree
from tools import ci_single_gate


HEAD = "a" * 40
MERGE = "b" * 40
TREE = "c" * 40
OTHER = "d" * 40


class FakeGit:
    def __init__(self, head=HEAD, head_tree=TREE, merge=MERGE, merge_tree=TREE):
        self.head, self.head_tree = head, head_tree
        self.merge, self.merge_tree = merge, merge_tree
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        if args == ("rev-parse", "HEAD"):
            return self.head
        if args == ("rev-parse", "HEAD^{tree}"):
            return self.head_tree
        if args == ("rev-parse", "FETCH_HEAD"):
            return self.merge
        if args == ("rev-parse", "FETCH_HEAD^{tree}"):
            return self.merge_tree
        if args == ("fetch", "--no-tags", "origin", "refs/pull/250/merge"):
            return ""
        raise AssertionError(f"Unexpected Git invocation: {args}")


def test_same_tree_pr_allows_single_complete_execution():
    git = FakeGit()
    proof = prove_merge_tree(HEAD, MERGE, "250", git)
    assert proof["mode"] == "identical-tree" and proof["merge_tree"] == TREE
    assert ("fetch", "--no-tags", "origin", "refs/pull/250/merge") in git.calls


def test_different_synthetic_merge_tree_fails_closed():
    with pytest.raises(EvidenceError, match="DIFFERENT TREES"):
        prove_merge_tree(HEAD, MERGE, "250", FakeGit(merge_tree=OTHER))


def test_merge_sha_changed_during_fetch_fails_closed():
    with pytest.raises(EvidenceError, match="moved"):
        prove_merge_tree(HEAD, MERGE, "250", FakeGit(merge=OTHER))


@pytest.mark.parametrize("head,merge,number", [
    ("bad", MERGE, "250"), (HEAD, MERGE, ""), (HEAD, "", "250"),
    (HEAD, MERGE, "0"), (HEAD, MERGE, "250_invalid"),
])
def test_missing_or_invalid_revision_provenance_is_rejected(head, merge, number):
    with pytest.raises(EvidenceError):
        prove_merge_tree(head, merge, number, FakeGit())


def test_main_push_never_fetches_synthetic_merge():
    git = FakeGit()
    proof = prove_merge_tree(HEAD, git_run=git)
    assert proof["mode"] == "main-head" and proof["merge_sha"] is None
    assert not any(args[0] == "fetch" for args in git.calls)


def _write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _evidence(tmp_path, merge_sha=MERGE):
    root = tmp_path / "evidence"
    safe = root / "public-source-safety"
    control = root / "public-verification-results"
    for stage in ("scan", "compile"):
        _write(safe / f"{stage}.json",
               {"head": HEAD, "tree": TREE, "exit_code": 0, "normal_exit": True})
    _write(control / "merge-tree.json", {"head": HEAD, "tree": TREE,
           "mode": "identical-tree" if merge_sha else "main-head",
           "merge_sha": merge_sha or None, "merge_tree": TREE if merge_sha else None,
           "equivalent": True})
    names = ["test_alpha", "test_beta"]
    inventory = {"head": HEAD, "tree": TREE, "shard": None, "collected": names,
                 "selected": names, "deselected": [], "collection_errors": 0,
                 "collection_skips": [["tests/optional.py", "Skipped: existing browser dependency"]],
                 "pytest_exit": 0, "outcomes": {n: {"status": "passed"} for n in names}}
    _write(control / "inventory.json", inventory)
    junit = b'<testsuites><testsuite tests="3" failures="0" errors="0"><testcase name="test_alpha"/><testcase name="test_beta"/><testcase name="optional"><skipped/></testcase></testsuite></testsuites>'
    (control / "results.xml").write_bytes(junit)
    proc = {"head": HEAD, "tree": TREE, "label": "control", "exit_code": 0,
            "normal_exit": True, "environment_sha256": "digest",
            "process_markers": {"pytest_return_code": 0, "child_exit_code": 0},
            "junit_sha256": hashlib.sha256(junit).hexdigest(), "junit_failures": 0}
    _write(control / "process.json", proc)
    return root


def test_full_control_passes_provenance_and_inventory(tmp_path, monkeypatch):
    root = _evidence(tmp_path)
    monkeypatch.setattr(ci_single_gate, "attest", lambda expected: {"head": expected, "tree": TREE})
    proof = ci_single_gate.verify_control(root, HEAD, "success", "success", MERGE)
    assert proof["selected_test_ids"] == 2 and proof["collection_skips"] == 1
    assert proof["pytest_rc"] == proof["supervisor_child_rc"] == 0


@pytest.mark.parametrize("target,value,match", [
    ("process.json", {"process_markers": {"pytest_return_code": 1, "child_exit_code": 0}}, "markers"),
    ("process.json", {"normal_exit": False}, "normally"),
    ("inventory.json", {"deselected": ["test_beta"]}, "unsharded"),
    ("merge-tree.json", {"merge_tree": OTHER}, "byte-identical"),
    ("process.json", {"junit_sha256": "tampered"}, "JUnit"),
])
def test_full_control_refuses_missing_or_tampered_proof(tmp_path, monkeypatch, target, value, match):
    root = _evidence(tmp_path)
    monkeypatch.setattr(ci_single_gate, "attest", lambda expected: {"head": expected, "tree": TREE})
    path = root / "public-verification-results" / target
    payload = json.loads(path.read_text())
    payload.update(value)
    _write(path, payload)
    with pytest.raises(EvidenceError, match=match):
        ci_single_gate.verify_control(root, HEAD, "success", "success", MERGE)


def test_missing_job_statuses_fail_even_with_valid_artifacts(tmp_path, monkeypatch):
    root = _evidence(tmp_path)
    monkeypatch.setattr(ci_single_gate, "attest", lambda expected: {"head": expected, "tree": TREE})
    with pytest.raises(EvidenceError, match="Required jobs"):
        ci_single_gate.verify_control(root, HEAD, "success", "skipped", MERGE)


def test_default_workflows_keep_the_7_job_budget_and_six_browser_roles():
    root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    public = (root / "public_safety_and_smoke.yml").read_text()
    browser = (root / "protocol_ui_browser.yml").read_text()
    public_job = (root / "ci_public_job.yml").read_text()
    assert "shadow-shards:" not in public
    assert "merge-result-integration:" not in public
    assert "mode: control" in public
    assert "--ci-shard" not in public_job
    assert "mandatory-evidence:" in public and "source-safety:" in public
    assert "mandatory-browser-evidence:" in browser
    assert "merge-result-browser:" not in browser
    assert "f3-evidence:" not in browser
    assert "protocol import grid q4 outputs consolidation" in browser
    assert "ci_browser_job aggregate" in browser
    assert "ci_merge_tree_guard" in public_job and "ci_merge_tree_guard" in browser


# ── real Git + CLI behaviour (not mocks): the guard and the single gate fail closed as processes ────────

import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def _git(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="ci-test.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="ci-test.invalid", GIT_CONFIG_GLOBAL="/dev/null")
    return subprocess.check_output(["git", *args], cwd=cwd, env=env, text=True).strip()


def _repo_with_merge_ref(tmp_path, same_tree: bool):
    """origin(bare) with refs/pull/7/merge, and a clone checked out at the PR HEAD."""
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    subprocess.check_call(["git", "init", "-q", "--bare", str(origin)])
    subprocess.check_call(["git", "init", "-q", str(work)])
    (work / "a.txt").write_text("base\n")
    _git(work, "add", "."); _git(work, "commit", "-qm", "base")
    (work / "a.txt").write_text("head\n")
    _git(work, "commit", "-qam", "head")
    head = _git(work, "rev-parse", "HEAD")
    if same_tree:                                    # a normal merge of an ancestor: identical content tree
        _git(work, "checkout", "-q", "-b", "merge", "HEAD~1")
        _git(work, "merge", "--no-ff", "-q", "-m", "merge", head)
    else:                                            # the merge result contains extra main content
        _git(work, "checkout", "-q", "-b", "merge", "HEAD")
        (work / "b.txt").write_text("from main\n")
        _git(work, "add", "."); _git(work, "commit", "-qm", "main moved")
    merge = _git(work, "rev-parse", "HEAD")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "origin", f"{merge}:refs/pull/7/merge")
    _git(work, "checkout", "-q", "--detach", head)
    return work, head, merge


def _guard(work, head, merge, out, pr="7"):
    env = dict(os.environ, PYTHONPATH=str(ROOT), GIT_CONFIG_GLOBAL="/dev/null")
    return subprocess.run([sys.executable, "-m", "tools.ci_merge_tree_guard", "--expected", head, "--merge-sha", merge,
                           "--pr-number", pr, "--output", str(out)], cwd=work, env=env, capture_output=True, text=True)


def test_real_git_identical_tree_passes_and_writes_proof(tmp_path):
    work, head, merge = _repo_with_merge_ref(tmp_path, same_tree=True)
    assert _git(work, "rev-parse", f"{head}^{{tree}}") == _git(work, "rev-parse", f"{merge}^{{tree}}")
    out = tmp_path / "proof.json"
    result = _guard(work, head, merge, out)
    assert result.returncode == 0, result.stderr
    proof = json.loads(out.read_text())
    assert proof["mode"] == "identical-tree" and proof["merge_sha"] == merge and proof["equivalent"] is True


def test_real_git_changed_tree_fails_closed_with_no_proof_file(tmp_path):
    work, head, merge = _repo_with_merge_ref(tmp_path, same_tree=False)
    out = tmp_path / "proof.json"
    result = _guard(work, head, merge, out)
    assert result.returncode == 1 and "DIFFERENT TREES" in result.stderr
    assert not out.exists(), "a failed guard must not leave an acceptable proof behind"


def test_real_git_moved_merge_ref_and_wrong_head_fail_closed(tmp_path):
    work, head, merge = _repo_with_merge_ref(tmp_path, same_tree=True)
    assert _guard(work, head, "e" * 40, tmp_path / "p.json").returncode == 1          # event pinned a different merge
    assert _guard(work, "f" * 40, merge, tmp_path / "p.json").returncode == 1         # wrong tested HEAD


def _gate(tmp_path, root, **over):
    args = {"--expected": HEAD, "--artifacts": str(root), "--source-result": "success",
            "--control-result": "success", "--merge-sha": MERGE, "--output": str(tmp_path / "gate.json")}
    args.update(over)
    cmd = [sys.executable, "-m", "tools.ci_single_gate", *[x for kv in args.items() for x in kv]]
    return subprocess.run(cmd, cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT)), capture_output=True, text=True)


@pytest.mark.parametrize("breaker", ["missing_inventory", "missing_junit", "missing_process", "malformed_json",
                                     "missing_merge_proof", "missing_safety_record", "failed_supervisor"])
def test_single_gate_rejects_missing_or_malformed_evidence(tmp_path, monkeypatch, breaker):
    # the CLI wraps this verifier in an exit-code boundary (EvidenceError|OSError|KeyError|JSONDecodeError -> 1)
    root = _evidence(tmp_path)
    control = root / "public-verification-results"
    monkeypatch.setattr(ci_single_gate, "attest", lambda expected: {"head": expected, "tree": TREE})
    if breaker == "missing_inventory":
        (control / "inventory.json").unlink()
    elif breaker == "missing_junit":
        (control / "results.xml").unlink()
    elif breaker == "missing_process":
        (control / "process.json").unlink()
    elif breaker == "malformed_json":
        (control / "inventory.json").write_text("{not json")
    elif breaker == "missing_merge_proof":
        (control / "merge-tree.json").unlink()
    elif breaker == "missing_safety_record":
        (root / "public-source-safety" / "scan.json").unlink()
    else:
        proc = json.loads((control / "process.json").read_text())
        proc.update(exit_code=1, normal_exit=False, process_markers={"pytest_return_code": 1, "child_exit_code": 1})
        _write(control / "process.json", proc)
    with pytest.raises((EvidenceError, OSError, KeyError, json.JSONDecodeError)):
        ci_single_gate.verify_control(root, HEAD, "success", "success", MERGE)


@pytest.mark.parametrize("source,control", [("failure", "success"), ("success", "failure"), ("cancelled", "success"),
                                            ("success", "cancelled"), ("skipped", "success"), ("success", ""), ("", "success")])
def test_single_gate_rejects_any_non_success_job_result(tmp_path, monkeypatch, source, control):
    root = _evidence(tmp_path)
    monkeypatch.setattr(ci_single_gate, "attest", lambda expected: {"head": expected, "tree": TREE})
    with pytest.raises(EvidenceError, match="Required jobs"):
        ci_single_gate.verify_control(root, HEAD, source, control, MERGE)


def test_single_gate_rejects_a_sharded_or_partially_selected_public_run(tmp_path, monkeypatch):
    root = _evidence(tmp_path)
    monkeypatch.setattr(ci_single_gate, "attest", lambda expected: {"head": expected, "tree": TREE})
    path = root / "public-verification-results" / "inventory.json"
    inv = json.loads(path.read_text())
    _write(path, {**inv, "shard": 0})
    with pytest.raises(EvidenceError, match="unsharded"):
        ci_single_gate.verify_control(root, HEAD, "success", "success", MERGE)
    _write(path, {**inv, "selected": inv["selected"][:1], "outcomes": {inv["selected"][0]: {"status": "passed"}}})
    with pytest.raises(EvidenceError):
        ci_single_gate.verify_control(root, HEAD, "success", "success", MERGE)
