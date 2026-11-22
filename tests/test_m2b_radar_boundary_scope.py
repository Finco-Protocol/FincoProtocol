"""Cohort #49 (M2-B Model/Radar boundary) positive closure and negative tamper tests."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest
from tests import ci_v4_p0_scope as P0
from tests import fin_v2_cohorts as C
from tests import m2b_radar_boundary_scope as T

ROOT = Path(__file__).resolve().parents[1]
MODULE = "tests/m2b_radar_boundary_scope.py"


def git(root, *args):
    return subprocess.check_output(
        ["git", "-c", "user.name=scope-test", "-c", "user.email=noreply@users.noreply.github.com", "-c", "commit.gpgsign=false", *args],
        cwd=root,
    )


@pytest.fixture(scope="module")
def subject(tmp_path_factory):
    root = tmp_path_factory.mktemp("m2b-source") / "subject"
    git(ROOT, "clone", "--quiet", "--shared", str(ROOT), str(root))
    return root


def rejected(root, path, transform=None, mode=False, remove=False, symlink=False, check_composite=False):
    head = git(root, "rev-parse", "HEAD").decode().strip()
    f = root / path
    try:
        if remove:
            f.unlink()
        elif symlink:
            f.unlink()
            f.symlink_to("README.md")
        elif mode:
            f.chmod(f.stat().st_mode | 0o111)
        else:
            f.write_bytes(transform(f.read_bytes()))
        # Verify physical working-tree rejection before committing
        with T.scoped():
            wt_rejected = not T.exact_blobs_ok(root)
        git(root, "add", "-A")
        git(root, "commit", "--quiet", "--allow-empty", "-m", "negative variant")
        ref = git(root, "rev-parse", "HEAD").decode().strip()
        with T.scoped():
            ref_rejected = not T.exact_blobs_ok(root, ref)
        if check_composite:
            with C.call_scope():
                ref_rejected = ref_rejected and (not C.valid(root, ref))
        return wt_rejected and ref_rejected
    finally:
        git(root, "reset", "--hard", "--quiet", head)
        git(root, "clean", "-fdxq")


def test_m2b_cohort49_positive_closure_and_composite_valid():
    assert C.COHORT_MODULES == T.BASE_COHORTS + (T.__name__,)
    assert C.COHORT_MODULES.count(T.__name__) == 1
    assert P0._next() is T and P0.SUCCESSOR == T.__name__
    assert git(ROOT, "rev-parse", T.BASE + "^{tree}").decode().strip() == T.BASE_TREE
    with C.call_scope():
        assert T.signature_ok() and T.reviewed_edits_ok() and T.exact_blobs_ok()
        assert all(m.exact_blobs_ok() for m in C.cohorts())
        assert C.valid()


def test_m2b_forbidden_and_frozen_invariants():
    assert not any(p.startswith(T.FORBIDDEN) or "*" in p for p in T.OWNED_PATHS | {T.MANIFEST})
    for p in T.FROZEN:
        assert (ROOT / p).read_bytes() == git(ROOT, "show", T.BASE + ":" + p)
    for p in T.HANDOFFS:
        assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)
    for p in T.CURRENT_MAPS:
        assert (ROOT / p).read_bytes() == T.expected_map(ROOT, p)
    assert not T.allowed_path("financial_engine/__init__.py")
    assert not T.allowed_path("app/v2/router.py")
    assert T.CI_PATHS == frozenset((".github/workflows/ci_v4_pr.yml", "tools/ci_v4_nodes.py"))
    assert not any(p.startswith((".github/", "tools/")) and p not in T.CI_PATHS for p in T.OWNED_PATHS | {T.MANIFEST})
    assert not T.allowed_path(".github/workflows/ci_v4_release_gate.yml")
    assert not T.allowed_path("tools/ci_v4_select.py")


@pytest.mark.parametrize("path", [
    "main_web.py",
    "main_api.py",
    "app/protocol_ui/router.py",
    "app/internal_auth_introspect.py",
    ".github/workflows/ci_v4_pr.yml",
    "tools/ci_v4_nodes.py",
    "tests/test_m2b_model_radar_boundary.py",
    MODULE,
    T.MANIFEST,
])
def test_owned_file_tamper_fails_closed(subject, path):
    assert rejected(subject, path, lambda b: b + b"\n", check_composite=(path == "main_web.py")), path


@pytest.mark.parametrize("path", [
    "financial_engine/__init__.py",
    "app/auth.py",
])
def test_unrelated_protected_or_app_file_tamper_fails_closed(subject, path):
    assert rejected(subject, path, lambda b: b + b"\n", check_composite=(path == "financial_engine/__init__.py")), path


@pytest.mark.parametrize("attack", ["base", "tree", "pin", "mode", "extra", "authorization"])
def test_forged_manifest_rejected(subject, attack):
    def change(raw):
        d = json.loads(raw)
        if attack == "base":
            d["base"] = "0" * 40
        elif attack == "tree":
            d["base_tree"] = "0" * 40
        elif attack == "pin":
            d["source_blobs"]["main_web.py"] = "0" * 40
        elif attack == "mode":
            d["source_modes"]["main_web.py"] = "100755"
        elif attack == "extra":
            d["source_blobs"]["app/unapproved.py"] = "0" * 40
        elif attack == "authorization":
            d["authorization"] += " broader"
        return (json.dumps(d, indent=2, sort_keys=True) + "\n").encode()
    assert rejected(subject, T.MANIFEST, change, check_composite=(attack == "pin"))


@pytest.mark.parametrize("attack", ["mode", "delete", "symlink"])
def test_file_identity_tamper_rejected(subject, attack):
    assert rejected(subject, "app/internal_auth_introspect.py", mode=attack == "mode", remove=attack == "delete", symlink=attack == "symlink")


@pytest.mark.parametrize("mutation", [None, "subject", "trusted", "other_pr", "other_base"])
def test_correction_e_workflow_authenticates_only_exact_nodes_successor(tmp_path, mutation):
    """Exact mirror of Correction H: ci_v4_pr.yml authenticates ONLY the exact SHA-256
    predecessor->successor transition of tools/ci_v4_nodes.py for PR #475 and base 707e68b2."""
    import hashlib
    import os
    import yaml

    wf = yaml.safe_load((ROOT / ".github/workflows/ci_v4_pr.yml").read_text(encoding="utf-8"))
    plan_step = next(s for s in wf["jobs"]["plan"]["steps"] if s.get("name", "").startswith("Exact node collection"))
    shard_step = next(s for s in wf["jobs"]["shards"]["steps"] if s.get("name", "").startswith("Trusted base tools"))
    gate_step = next(s for s in wf["jobs"]["gate"]["steps"] if s.get("name", "").startswith("Aggregate ("))
    for step in (plan_step, shard_step, gate_step):
        assert 'if [ "$PR_NUMBER" = 475 ] && [ "$BASE_SHA" = 707e68b290694c57b470f4a112c190abb3d02ac9 ]; then' in step["run"]

    base = "707e68b290694c57b470f4a112c190abb3d02ac9"
    old_bytes = git(ROOT, "show", f"{base}:tools/ci_v4_nodes.py")
    new_bytes = (ROOT / "tools/ci_v4_nodes.py").read_bytes()
    old_sha = hashlib.sha256(old_bytes).hexdigest()
    new_sha = hashlib.sha256(new_bytes).hexdigest()

    for role, raw in (("trusted", old_bytes), ("subject", new_bytes)):
        d = tmp_path / role / "tools"
        d.mkdir(parents=True)
        (d / "ci_v4_nodes.py").write_bytes(raw + (b"\n" if mutation == role else b""))

    # Execute the exact guard block from ci_v4_pr.yml (up to cp)
    snippet = (
        "set -euo pipefail\n"
        f"if [ \"$PR_NUMBER\" = 475 ] && [ \"$BASE_SHA\" = {base} ]; then\n"
        f"  printf '%s  %s\n' {old_sha} trusted/tools/ci_v4_nodes.py | sha256sum -c -\n"
        f"  printf '%s  %s\n' {new_sha} subject/tools/ci_v4_nodes.py | sha256sum -c -\n"
        "  cp subject/tools/ci_v4_nodes.py trusted/tools/ci_v4_nodes.py\n"
        "  echo 'Correction E: authenticated exact whole-module collection-skip node-plugin successor (SKIPPED, never PASS)'\n"
        "fi\n"
    )
    env = {
        **os.environ,
        "BASE_SHA": "c" * 40 if mutation == "other_base" else base,
        "PR_NUMBER": "476" if mutation == "other_pr" else "475",
    }
    proc = subprocess.run(["bash", "-c", snippet], cwd=tmp_path, env=env, capture_output=True, text=True)
    if mutation is None:
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "Correction E: authenticated exact" in proc.stdout
        assert (tmp_path / "trusted/tools/ci_v4_nodes.py").read_bytes() == new_bytes
    elif mutation in ("trusted", "subject"):
        assert proc.returncode != 0
        assert "FAILED" in proc.stdout
        assert (tmp_path / "trusted/tools/ci_v4_nodes.py").read_bytes() != new_bytes
    else:
        assert proc.returncode == 0
        assert "Correction E: authenticated exact" not in proc.stdout
        assert (tmp_path / "trusted/tools/ci_v4_nodes.py").read_bytes() == old_bytes


def test_ci_v4_nodes_collection_skip_and_fail_closed_contract(tmp_path):
    """Whole-module pytest.importorskip succeeds and reconciles as SKIPPED (never PASS) in aggregate;
    genuinely empty 0-test whole modules, split modules, and no_skip modules still FAIL CLOSED."""
    import os
    import sys
    from tools import ci_v4_aggregate as AGG
    from tools import ci_v4_nodes as NODES

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_ok.py").write_text("def test_pass():\n    assert True\n", encoding="utf-8")
    (tmp_path / "tests/test_browser_skip.py").write_text(
        "import pytest\npytest.importorskip('finco_absent_playwright_dep_xyz', reason='playwright not installed')\n"
        "def test_never_collected():\n    assert False\n",
        encoding="utf-8",
    )
    (tmp_path / "tests/test_empty_zero.py").write_text("# 0 tests, no skip\n", encoding="utf-8")

    def run_shard(whole_mods, split_spec=None, tag="ok"):
        assign = tmp_path / f"assign_{tag}.json"
        ev = tmp_path / f"ev_{tag}.json"
        junit = tmp_path / f"junit-shard-0-{tag}.xml"
        assign.write_text(json.dumps({
            "schema": NODES.ASSIGN_SCHEMA,
            "tested_sha": "a" * 40,
            "tested_tree": "b" * 40,
            "plan_digest": "c" * 40,
            "shard": 0,
            "whole": whole_mods,
            "split": split_spec or {},
        }))
        env = {k: v for k, v in os.environ.items() if not k.startswith("FINCO_CI_V4_NODE_")}
        env.update(
            PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
            PYTHONPATH=str(ROOT),
            FINCO_CI_V4_NODE_ASSIGN=str(assign),
            FINCO_CI_V4_NODE_EVIDENCE=str(ev),
        )
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", "-p", "tools.ci_v4_nodes",
             "--junitxml", str(junit), *whole_mods, *(split_spec or {}).keys()],
            cwd=tmp_path, env=env, capture_output=True, text=True,
        )
        return proc, ev, junit

    # 1. Genuine module-level importorskip on non-split whole module -> PASSes shard, recorded in collection_skipped
    p1, ev1, j1 = run_shard(["tests/test_ok.py", "tests/test_browser_skip.py"], tag="skip_ok")
    assert p1.returncode == 0, p1.stdout + p1.stderr
    ev_data = json.loads(ev1.read_text())
    assert "tests/test_browser_skip.py" in ev_data["collection_skipped"]
    cases = AGG.read_junit(j1)
    selected = {"tests.test_ok": "tests/test_ok.py", "tests.test_browser_skip": "tests/test_browser_skip.py"}
    skip_cases = [c for c in cases if c["status"] == "skipped"]
    assert len(skip_cases) == 1
    assert AGG._collection_skip_module(skip_cases[0], selected, set(), set()) == "tests/test_browser_skip.py"
    # Refused if module is in no_skip_modules or split_modules!
    assert AGG._collection_skip_module(skip_cases[0], selected, {"tests/test_browser_skip.py"}, set()) is None
    assert AGG._collection_skip_module(skip_cases[0], selected, set(), {"tests/test_browser_skip.py"}) is None

    # 2. Genuinely empty 0-test whole module STILL FAILS CLOSED
    p2, _, _ = run_shard(["tests/test_ok.py", "tests/test_empty_zero.py"], tag="empty_fail")
    assert p2.returncode != 0
    assert "collected no node" in (p2.stdout + p2.stderr)

    # 3. Split module that collection-skips STILL FAILS CLOSED
    p3, _, _ = run_shard(
        ["tests/test_ok.py"],
        split_spec={"tests/test_browser_skip.py": {"count": 1, "digest": NODES.ids_digest(["tests/test_browser_skip.py::test_never_collected"]), "keep": ["tests/test_browser_skip.py::test_never_collected"]}},
        tag="split_skip_fail",
    )
    assert p3.returncode != 0
    assert "differs from the planned inventory" in (p3.stdout + p3.stderr)
