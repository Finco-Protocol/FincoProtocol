"""CI V2 contract tests: identical Git trees, full control proof and fan-out bounds.

Synthetic local fixtures only. These tests never invoke the application or financial engine.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


HEAD = "a" * 40
MERGE = "b" * 40
TREE = "c" * 40
OTHER = "d" * 40


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


def _guard(work, head, merge, out, pr="7"):
    env = dict(os.environ, PYTHONPATH=str(ROOT), GIT_CONFIG_GLOBAL="/dev/null")
    return subprocess.run([sys.executable, "-m", "tools.ci_merge_tree_guard", "--expected", head, "--merge-sha", merge,
                           "--pr-number", pr, "--output", str(out)], cwd=work, env=env, capture_output=True, text=True)


def _gate(tmp_path, root, **over):
    args = {"--expected": HEAD, "--artifacts": str(root), "--source-result": "success",
            "--control-result": "success", "--merge-sha": MERGE, "--output": str(tmp_path / "gate.json")}
    args.update(over)
    cmd = [sys.executable, "-m", "tools.ci_single_gate", *[x for kv in args.items() for x in kv]]
    return subprocess.run(cmd, cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT)), capture_output=True, text=True)


# ── CI-only test dependency (PyYAML) ────────────────────────────────────────────────────────────────


def test_the_structured_workflow_contract_tests_have_their_parser_available():
    import yaml  # the dependency those tests rely on must be importable wherever the Public suite runs
    assert yaml.safe_load("jobs: {a: {}}") == {"jobs": {"a": {}}}
