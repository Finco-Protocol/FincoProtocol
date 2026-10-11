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
