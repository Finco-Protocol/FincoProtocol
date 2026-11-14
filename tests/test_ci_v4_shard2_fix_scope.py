"""CI V4 shard-2 fix exact-source successor (after the accepted C06 added-line CAPEX profile successor): positive identity and adversarial fail-closed controls.

Every negative runs in an ISOLATED clone (a committed variant, or a mutated working tree that is restored afterwards); the evaluated checkout is never
edited and no verdict is cached across mutations. A CI-specific block proves the change is CI-only and finite: exactly the reviewed ``tools/`` modules,
policy files and tests move, every other CI V4 file, workflow, historical manifest and the byte-frozen ``module_weights.json`` stay identical to accepted
main, and no older cohort's forbidden-prefix rule was widened (the older guards stay byte-identical and the ``tools/`` admission is a literal two-path set).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests import f03_financing_scope as F
from tests import fin_v2_cohorts as C
from tests import f04_financing_scope as Q
from tests import r04_ppa_scope as P
from tests import c06_cost_workspace_scope as K
from tests import ci_v4_scope as V
from tests import ci_v4_shard2_fix_scope as T

ROOT = Path(__file__).resolve().parents[1]
ACTIVATE = "tools/ci_v4_activate.py"
SCHEDULE = "tools/ci_v4_schedule.py"
SHARD = "tools/ci_v4_shard.py"
SPLIT_POLICY = "docs/ci_v4/node_split_policy.json"
NODE_WEIGHTS = "docs/ci_v4/node_weights.json"
CI_MAP = "docs/ci_v4/SOURCE_SUCCESSOR.json"
# The composite ``C.valid`` is a conjunction over every registered cohort's exact verdict, this one included, so each tamper below asserts THIS cohort's verdict
# for every path (cheap) and the whole composite for one representative of each kind (a tool, a policy, a test, the registry, a handoff, a map, a frozen file).
COMPOSITE_PATHS = frozenset((
    SCHEDULE, SHARD, SPLIT_POLICY, NODE_WEIGHTS, "tests/test_ci_v4_schedule.py", "tests/fin_v2_cohorts.py", "tests/c06_cost_workspace_scope.py",
    "tests/u1_scope.py", "tests/ci_v4_shard2_fix_scope.py", CI_MAP, "docs/react_migration/c06_cost_workspace/SOURCE_SUCCESSOR.json",
    "docs/ci_v4/shard2_fix/SOURCE_SUCCESSOR.json", "docs/ci_v4/module_weights.json", "tools/ci_v4_select.py", ".github/workflows/ci_v4_pr.yml"))
TAIL = ("tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope",
        "tests.c06_cost_workspace_scope", "tests.ci_v4_shard2_fix_scope")


def _git(*args, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd).decode().strip()


def _base(path):
    return subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT)


@pytest.fixture(scope="module")
def clone(tmp_path_factory):
    root = tmp_path_factory.mktemp("ci-v4-shard2-gov") / "repo"
    subprocess.check_call(["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(root)])
    subprocess.check_call(["git", "checkout", "-q", "--detach", _git("rev-parse", "HEAD")], cwd=root)
    return root


def _g(root, *args):
    return subprocess.check_output(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args], cwd=root)


def _variant(root, edits=None, mode=None, remove=(), symlink=None, add=None):
    """Commit one mutated copy of the evaluated HEAD in the isolated clone and return its sha; the clone is restored afterwards."""
    base = _g(root, "rev-parse", "HEAD").decode().strip()
    try:
        for path, fn in (edits or {}).items():
            f = root / path
            f.write_bytes(fn(f.read_bytes()))
        for path, data in (add or {}).items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_bytes(data)
        for path in remove:
            (root / path).unlink()
        if symlink:
            (root / symlink).unlink()
            os.symlink("/etc/hostname", root / symlink)
        _g(root, "add", "-A")
        if mode:
            _g(root, "update-index", "--chmod=+x", mode)
        _g(root, "commit", "-q", "--allow-empty", "-m", "variant")
        return _g(root, "rev-parse", "HEAD").decode().strip()
    finally:
        _g(root, "checkout", "-q", "-f", base)
        _g(root, "clean", "-fdxq")


class _WorkingTree:
    """Mutate the clone's WORKING TREE only (HEAD stays the accepted commit) and always restore it, so ``ref=None`` verdicts are judged on disk."""

    def __init__(self, root):
        self.root = root

    def __enter__(self):
        return self.root

    def __exit__(self, *exc):
        _g(self.root, "checkout", "-q", "-f", "HEAD")
        _g(self.root, "clean", "-fdxq")


def _tamper(root, path, fn):
    f = root / path
    f.write_bytes(fn(f.read_bytes()))


# ---------------------------------------------------------------- positive identity
def test_manifest_schema_pins_modes_and_immutable_base():
    d = T.manifest()
    assert d and d["schema_version"] == T.SCHEMA and d["base"] == T.BASE and d["base_tree"] == T.BASE_TREE and d["authorization"] == T.AUTHORIZATION
    assert set(d["source_blobs"]) == T.OWNED_PATHS and set(d["base_blobs"]) == T.SUPERSEDED
    assert d["source_modes"] == {p: "100644" for p in T.OWNED_PATHS} and d["base_modes"] == {p: "100644" for p in T.SUPERSEDED}
    assert _git("rev-parse", T.BASE + "^{tree}") == T.BASE_TREE
    assert _git("merge-base", "--is-ancestor", T.BASE, "HEAD") == ""
    assert not set(d["base_blobs"]) & T.NEW
    raw = (ROOT / T.MANIFEST).read_bytes()
    assert raw == (json.dumps(json.loads(raw), indent=2, sort_keys=True) + "\n").encode()          # canonical bytes only


def test_owned_set_is_finite_literal_and_admits_no_forbidden_path_except_the_two_tools():
    assert T.CI_TOOL_PATHS == frozenset((ACTIVATE, SCHEDULE, SHARD))
    assert T.SOURCE_PATHS == frozenset((ACTIVATE, SCHEDULE, SHARD, SPLIT_POLICY, NODE_WEIGHTS, "tests/test_ci_v4_activate.py", "tests/test_ci_v4_nodes.py",
                                       "tests/test_ci_v4_schedule.py"))
    assert T.NEW == frozenset(("tests/ci_v4_shard2_fix_scope.py", "tests/test_ci_v4_shard2_fix_scope.py"))
    assert T.HANDOFF_PATHS == frozenset((
        "tests/c06_cost_workspace_scope.py", "tests/fin_v2_cohorts.py", "tests/test_bess02_scope.py", "tests/test_c06_cost_workspace_scope.py",
        "tests/test_ci_v4_perf_scope.py", "tests/test_f03_financing_scope.py", "tests/test_f04_financing_scope.py",
        "tests/test_post413_o1_scope.py", "tests/test_post432_l01_l02_scope.py", "tests/test_r02_ppa_ux_scope.py", "tests/test_r03_ppa_scope.py", "tests/test_r04_ppa_scope.py",
        "tests/test_t01e_remediation_scope.py", "tests/test_ux_pr1_scope.py", "tests/u1_scope.py", "tests/u2_scope.py", "tests/ux_pr1_scope.py",
        "tests/ux_pr2b_scope.py",
        "tests/ux_pr2c_scope.py", "tests/ux_pr3b1_scope.py"))
    assert len(T.CURRENT_MAPS) == 8 and set(T.HANDOFFS) == T.HANDOFF_PATHS
    assert set(T.MAP_KEYS) == {T.REGISTRY} | T.SOURCE_PATHS | T.HANDOFF_PATHS
    for p in T.OWNED_PATHS | {T.MANIFEST}:
        assert not (p.startswith(T.FORBIDDEN) and p not in T.CI_TOOL_PATHS) and "*" not in p and ".." not in p.split("/"), p
    assert not any(p.startswith((".github/", "financial_engine/", "finco_core/", "domain/", "app/", "main_web.py")) for p in T.OWNED_PATHS | {T.MANIFEST})
    assert T.PREDECESSOR == "tests/c06_cost_workspace_scope.py"
    assert SPLIT_POLICY in T.SOURCE_PATHS and "docs/ci_v4/module_weights.json" not in T.OWNED_PATHS and "docs/ci_v4/module_weights.json" in T.FROZEN


def test_signature_exactness_and_reviewed_substitutions_hold():
    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()
    for p in T.HANDOFFS:
        assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)
        assert T._blob((ROOT / p).read_bytes()) == T.manifest()["source_blobs"][p]
    assert K.reviewed_edits_ok() and K.signature_ok()


def test_registered_exactly_once_as_the_terminal_cohort_after_c06():
    assert C.COHORT_MODULES[-7:] == TAIL
    assert C.COHORT_MODULES.count("tests.ci_v4_shard2_fix_scope") == 1 and len(set(C.COHORT_MODULES)) == len(C.COHORT_MODULES)


def test_current_maps_move_only_this_cohorts_own_keys():
    pins = T.manifest()["source_blobs"]
    for p in T.CURRENT_MAPS:
        old = json.loads(_base(p))
        cur = json.loads((ROOT / p).read_text())
        assert set(old) == set(cur) and all(old[k] == cur[k] for k in old if k != "source_blobs")
        assert set(old["source_blobs"]) == set(cur["source_blobs"])
        changed = {k for k in old["source_blobs"] if old["source_blobs"][k] != cur["source_blobs"][k]}
        assert changed <= set(T.MAP_KEYS)
        for k in changed:
            assert cur["source_blobs"][k] == pins[k]
    # In the CI V4 map exactly the pins of the paths this cohort moves (and that the map carries) differ from the accepted-main map: the six CI paths included.
    old, cur = json.loads(_base(CI_MAP))["source_blobs"], json.loads((ROOT / CI_MAP).read_text())["source_blobs"]
    moved = {k for k in old if old[k] != cur[k]}
    assert moved == {k for k in T.MAP_KEYS if k in old and old[k] != pins[k]} and T.SOURCE_PATHS <= moved


def test_historical_manifests_and_accepted_chain_files_are_byte_identical_to_the_accepted_base():
    for p in T.FROZEN:
        assert (ROOT / p).read_bytes() == _base(p), p
        assert _git("ls-tree", T.BASE, "--", p).split()[0] == "100644"


def test_the_whole_chain_is_exact_and_the_composite_is_valid_on_the_committed_head(clone):
    with C.call_scope():
        assert T.exact_blobs_ok(clone, "HEAD") and K.exact_blobs_ok(clone, "HEAD") and P.exact_blobs_ok(clone, "HEAD") and Q.exact_blobs_ok(clone, "HEAD")
        assert F.exact_blobs_ok(clone, "HEAD") and V.exact_blobs_ok(clone, "HEAD") and C.valid(clone, "HEAD")


def test_committed_ref_verdict_equals_the_working_tree_verdict(clone):
    assert T.manifest(clone, "HEAD") and T.manifest(clone, "HEAD") == T.manifest(clone)
    assert T.exact_blobs_ok(clone) is T.exact_blobs_ok(clone, "HEAD") is True
    assert not T.exact_blobs_ok(clone, "0" * 40) and not T.exact_blobs_ok(clone, T.BASE) and not T.manifest(clone, T.BASE)


# ---------------------------------------------------------------- the accepted ancestor, with and without this successor
def _gate(worktree, out):
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    rc = subprocess.call([sys.executable, "-m", "tools.ci_v4_governance_gate", "--output", str(out)], cwd=worktree, env=env, stdout=subprocess.DEVNULL)
    return rc, json.loads(Path(out).read_text())


@pytest.fixture()
def ancestor(clone, tmp_path):
    """A detached worktree of the ACCEPTED main commit (BASE): its own code, its own registry, no successor."""
    anc = tmp_path / "ancestor"
    _g(clone, "worktree", "add", "-q", "--detach", str(anc), T.BASE)
    try:
        yield anc
    finally:
        _g(clone, "worktree", "remove", "--force", str(anc))


def test_the_accepted_ancestor_is_fully_valid_under_its_own_code_and_has_no_successor(ancestor, tmp_path):
    assert not (ancestor / "tests/ci_v4_shard2_fix_scope.py").exists() and not (ancestor / T.MANIFEST).exists()
    rc, rec = _gate(ancestor, tmp_path / "gate.json")
    assert rc == 0 and rec["verdict"] == "PASS" and rec["composite_valid"] is True and not rec["mutation_violations"] and all(rec["cohorts"].values())
    assert "tests.ci_v4_shard2_fix_scope" not in rec["registered"] and rec["registered"][-1] == "tests.c06_cost_workspace_scope"


def test_without_this_successor_the_accepted_chain_refuses_the_same_change_set(ancestor, tmp_path):
    """The hosted-proven wall: copy exactly the reviewed CI files and the regenerated CI V4 map onto the accepted ancestor WITHOUT the successor and the
    central gate is red (composite false, F03/C06/CI V4 not exact). Only the registered successor admits them."""
    for p in sorted(T.SOURCE_PATHS | {CI_MAP}):
        shutil.copyfile(ROOT / p, ancestor / p)
    _g(ancestor, "add", "-A")
    rc, rec = _gate(ancestor, tmp_path / "gate.json")
    assert rc == 1 and rec["verdict"] == "FAIL" and rec["composite_valid"] is False
    bad = {k for k, v in rec["cohorts"].items() if not v}
    assert {"tests.f03_financing_scope", "tests.c06_cost_workspace_scope", "tests.ci_v4_scope"} <= bad


# ---------------------------------------------------------------- CI-only / finite-scope proof
def _changed_vs_base():
    return set(_git("diff", "--name-only", "--no-renames", T.BASE).splitlines())


def test_the_change_set_is_the_owned_set_and_touches_no_engine_app_workflow_or_foreign_ci_path():
    changed = _changed_vs_base()
    assert changed <= T.OWNED_PATHS | {T.MANIFEST}
    for p in changed:
        assert not p.startswith(("app/", "financial_engine/", "finco_core/", "domain/", ".github/", "migrations/", "research/", "frontend/", "static/", "main_web.py")), p
        if p.startswith("tools/"):
            assert p in T.CI_TOOL_PATHS, p                                    # exactly the two reviewed tools, never another tools/ path
    assert {p for p in changed if p.startswith("tools/")} == set(T.CI_TOOL_PATHS) == {ACTIVATE, SCHEDULE, SHARD}
    for p in ("docs/ci_v4/module_weights.json", "docs/ci_v4/ci-v4-policy.json", "docs/ci_v4/correction_p/SOURCE_SUCCESSOR.json",
              ".github/workflows/ci_v4_pr.yml", ".github/workflows/ci_v4_full.yml", ".github/workflows/ci_v4_release_gate.yml",
              "tools/ci_v4_select.py", "tools/ci_v4_governance_gate.py", "tools/ci_v4_nodes.py", "tools/ci_v4_aggregate.py"):
        assert p not in changed and (ROOT / p).read_bytes() == _base(p), p


def test_no_older_cohort_forbidden_prefix_or_ci_allowlist_was_widened():
    """The older guards that police ``tools/`` and ``.github/`` are byte-identical to accepted main; this cohort never edits their prefix rules."""
    for p in ("tests/ci_v4_scope.py", "tests/f03_financing_scope.py", "tests/f04_financing_scope.py", "tests/r04_ppa_scope.py", "tests/r03_ppa_scope.py",
              "tests/t01e_remediation_scope.py", "tests/ci_v4_perf_scope.py", "tests/bess02_scope.py"):
        assert p in T.FROZEN and (ROOT / p).read_bytes() == _base(p), p
    assert V.CI_PREFIXES == (".github/", "tools/") and "tools/" in F.FORBIDDEN and ".github/" in F.FORBIDDEN
    assert {"tools/ci_v4_schedule.py", "tools/ci_v4_shard.py"} <= V.CI_PATHS            # the pre-existing literal CI V4 paths: the same files, no new path
    assert not T.allowed_path("tools/ci_v4_select.py") and not T.allowed_path("tools/ci_v4_nodes.py") and not T.allowed_path("tools/ci_v4_new.py") and not T.allowed_path(".github/workflows/ci_v4_pr.yml")
    assert T.allowed_path(SCHEDULE) and T.allowed_path(SHARD) and T.allowed_path(ACTIVATE)


def test_the_three_reviewed_tools_stay_inside_the_reviewed_surface():
    for p in (ACTIVATE, SCHEDULE, SHARD):
        diff = _git("diff", "--unified=0", T.BASE, "--", p)
        added = "\n".join(l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
        for forbidden in ("os.system", "eval(", "exec(", "shell=True", "urllib", "requests", "socket", "GITHUB_TOKEN", "secrets.", "os.environ["):
            assert forbidden not in added, (p, forbidden)
    assert "_DIAGNOSTIC_WRAPPER_CODE" in (ROOT / SHARD).read_text() and "pytest_command(" in (ROOT / ACTIVATE).read_text()


def test_node_split_policy_is_the_closed_reviewed_allowlist():
    pol = json.loads((ROOT / SPLIT_POLICY).read_text())
    assert pol["enabled_in_required_pr_gate"] is True
    assert set(pol["modules"]) == {"tests/test_rcux_governance.py", "tests/test_wf06b_scope.py", "tests/test_u1_scope.py"}
    u1 = pol["modules"]["tests/test_u1_scope.py"]
    assert u1["verdict"] == "SPLIT_SAFE" and u1["granularity"] == "node" and len(u1["isolation_proof"]) > 200
    assert "tests/test_u1_scope.py" in pol["not_split"] and pol["not_split"]["tests/test_u1_scope.py"].startswith("SUPERSEDED")
    assert set(pol["not_split"]) == {"tests/test_u1_scope.py", "tests/test_post413_o1_scope.py", "tests/test_u2_scope.py"}
    for m in pol["modules"]:
        assert (ROOT / m).is_file()


def test_node_weights_carry_provenance_and_no_censored_node_is_a_measured_zero():
    w = json.loads((ROOT / NODE_WEIGHTS).read_text())
    assert w["sources"] and all(len(s["sha"]) == 40 and len(s["artifact_sha256"]) == 64 and s["run_id"] for s in w["sources"])
    assert all("NOT a completed sample" in c["reason"] for c in w["censored"]) and len(w["censored"]) >= 3
    u1 = {k: v for k, v in w["nodes"].items() if k.startswith("tests/test_u1_scope.py::")}
    assert len(u1) == 100 and all(isinstance(v, float) or isinstance(v, int) for v in u1.values()) and all(v >= 0 for v in u1.values())
    assert max(u1.values()) == 1990.455 and round(sum(u1.values()), 1) == 4113.3
    assert all(c["elapsed_s_lower_bound"] > 0 for c in w["censored"] if "elapsed_s_lower_bound" in c)      # a cancelled run is a lower bound, never a zero
    assert any(s["run_id"] == 43569255310 and s["modules"] == ["tests/test_u1_scope.py"] for s in w["sources"])


# ---------------------------------------------------------------- working-tree tamper is detected
@pytest.mark.parametrize("path", sorted(T.OWNED_PATHS - T.CURRENT_MAPS))
def test_one_byte_in_the_working_tree_of_any_owned_blob_fails_closed(clone, path):
    with _WorkingTree(clone):
        assert T.exact_blobs_ok(clone) and T.signature_ok(clone)
        _tamper(clone, path, lambda b: b + b"\n# tampered\n")
        assert T.exact_blobs_ok(clone) is False, path
        if path in COMPOSITE_PATHS:
            assert not C.valid(clone), path
    assert T.exact_blobs_ok(clone)                               # restored: the verdict is not poisoned


def test_working_tree_tamper_of_the_scheduler_is_detected_while_head_is_unchanged(clone):
    with _WorkingTree(clone):
        head = _g(clone, "rev-parse", "HEAD")
        _tamper(clone, SCHEDULE, lambda b: b + b"\n# tampered\n")
        assert _g(clone, "rev-parse", "HEAD") == head and _g(clone, "status", "--porcelain").decode().strip()
        assert T.exact_blobs_ok(clone) is False and T.exact_blobs_ok(clone, "HEAD") is True


def test_deleted_or_symlinked_or_executable_owned_file_fails_closed_in_the_working_tree(clone):
    with _WorkingTree(clone):
        (clone / SCHEDULE).unlink()
        assert not T.exact_blobs_ok(clone)
    with _WorkingTree(clone):
        (clone / SCHEDULE).unlink()
        os.symlink((clone / SHARD), clone / SCHEDULE)
        assert not T.exact_blobs_ok(clone)
    with _WorkingTree(clone):
        (clone / SHARD).chmod(0o755)
        assert not T.exact_blobs_ok(clone)


def test_untracked_foreign_ci_tool_in_the_working_tree_fails_closed(clone):
    with _WorkingTree(clone):
        (clone / "tools" / "ci_v4_unreviewed_extra.py").write_text("x = 1\n")
        assert not T.exact_blobs_ok(clone) and not V.exact_blobs_ok(clone) and not C.valid(clone)


# ---------------------------------------------------------------- committed-ref adversarial variants
@pytest.mark.parametrize("path", sorted(T.OWNED_PATHS | {T.MANIFEST} - T.CURRENT_MAPS))
def test_one_byte_in_any_owned_committed_blob_is_rejected_by_the_chain_and_the_composite(clone, path):
    ref = _variant(clone, {path: lambda b: b + b"\n"})
    with C.call_scope():
        assert not T.exact_blobs_ok(clone, ref), path
        if path in COMPOSITE_PATHS:
            assert not C.valid(clone, ref), path


@pytest.mark.parametrize("path", sorted(T.CURRENT_MAPS))
def test_current_map_tamper_is_rejected_by_the_full_closure(clone, path):
    ref = _variant(clone, {path: lambda b: b + b"\n"})
    with C.call_scope():
        assert not T.exact_blobs_ok(clone, ref), path
        if path in COMPOSITE_PATHS:
            assert not C.valid(clone, ref), path


@pytest.mark.parametrize("name,fn", [
    ("duplicate_s2", lambda b: b.replace(b"'tests.c06_cost_workspace_scope', 'tests.ci_v4_shard2_fix_scope')", b"'tests.c06_cost_workspace_scope', 'tests.ci_v4_shard2_fix_scope', 'tests.ci_v4_shard2_fix_scope')")),
    ("fake_extra", lambda b: b.replace(b"'tests.ci_v4_shard2_fix_scope')", b"'tests.ci_v4_shard2_fix_scope', 'tests.fake_scope')")),
    ("swapped_c06_s2", lambda b: b.replace(b"'tests.c06_cost_workspace_scope', 'tests.ci_v4_shard2_fix_scope')", b"'tests.ci_v4_shard2_fix_scope', 'tests.c06_cost_workspace_scope')")),
    ("c06_removed", lambda b: b.replace(b"'tests.c06_cost_workspace_scope', ", b"")),
    ("s2_missing", lambda b: b.replace(b", 'tests.ci_v4_shard2_fix_scope')", b")")),
    ("r04_removed", lambda b: b.replace(b"'tests.r04_ppa_scope', ", b"")),
    ("f04_removed", lambda b: b.replace(b"'tests.f04_financing_scope', ", b"")),
    ("r03_removed", lambda b: b.replace(b"'tests.r03_ppa_scope', ", b"")),
    ("earlier_reordered", lambda b: b.replace(b"'tests.fin_v2_3_scope', 'tests.fin_v2_ci_scope'", b"'tests.fin_v2_ci_scope', 'tests.fin_v2_3_scope'")),
])
def test_registry_mutations_are_rejected(clone, name, fn):
    ref = _variant(clone, {T.REGISTRY: fn})
    assert T.REGISTRY in subprocess.check_output(["git", "diff", "--name-only", "HEAD", ref], cwd=clone).decode().splitlines()
    with C.call_scope():
        assert not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref), name


@pytest.mark.parametrize("path", sorted(T.FROZEN))
def test_historical_and_accepted_chain_files_must_stay_byte_identical(clone, path):
    ref = _variant(clone, {path: lambda b: b + b"\n"})
    with C.call_scope():
        assert not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref), path
        if path in COMPOSITE_PATHS:
            assert not C.valid(clone, ref), path


def test_predecessor_c06_scope_tamper_is_rejected_everywhere(clone):
    ref = _variant(clone, {T.PREDECESSOR: lambda b: b + b"\n"})
    with C.call_scope():
        assert not T.signature_ok(clone, ref) and not K.exact_blobs_ok(clone, ref) and not C.valid(clone, ref)


def test_partially_applied_handoff_is_rejected(clone):
    # the C06 forward hook reverted to the accepted BASE bytes (and the registry likewise), each while this cohort stays registered
    ref = _variant(clone, {T.PREDECESSOR: lambda b: _base(T.PREDECESSOR)})
    with C.call_scope():
        assert not T.signature_ok(clone, ref) and not C.valid(clone, ref)
    ref = _variant(clone, {T.REGISTRY: lambda b: _base(T.REGISTRY)})
    with C.call_scope():
        assert not T.signature_ok(clone, ref) and not C.valid(clone, ref)


def test_forged_manifest_base_tree_pin_and_mode_are_rejected(clone):
    tree = T.BASE_TREE.encode()
    for fn in (lambda b: b.replace(b'"base_tree": "' + tree[:8], b'"base_tree": "1' + tree[1:8], 1),
               lambda b: b.replace(b'"base": "' + T.BASE.encode()[:8], b'"base": "3' + T.BASE.encode()[1:8], 1),
               lambda b: b.replace(SCHEDULE.encode() + b'": "', SCHEDULE.encode() + b'": "0000', 1),
               lambda b: b.replace(SPLIT_POLICY.encode() + b'": "', SPLIT_POLICY.encode() + b'": "0000', 1),
               lambda b: b.replace(NODE_WEIGHTS.encode() + b'": "', NODE_WEIGHTS.encode() + b'": "0000', 1),
               lambda b: b.replace(b'"tests/fin_v2_cohorts.py": "', b'"tests/fin_v2_cohorts.py": "0000', 1),
               lambda b: b.replace(b'"source_modes"', b'"source_modez"', 1),
               lambda b: b.replace(b'"100644"', b'"100755"', 1)):
        ref = _variant(clone, {T.MANIFEST: fn})
        with C.call_scope():
            assert not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref)
    ref = _variant(clone, mode=SCHEDULE)
    assert not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref)
    ref = _variant(clone, symlink=SHARD)
    assert not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref)


def test_manifest_with_a_dropped_added_or_swapped_pin_is_rejected(clone):
    def edit(fn):
        def run(b):
            d = json.loads(b)
            fn(d)
            return (json.dumps(d, indent=2, sort_keys=True) + "\n").encode()
        return run
    forged = [
        edit(lambda d: d["source_blobs"].pop(SCHEDULE)),
        edit(lambda d: d["source_blobs"].update({"tools/ci_v4_select.py": "0" * 40})),                       # an extra path: a foreign CI tool
        edit(lambda d: d["source_blobs"].update({SCHEDULE: d["source_blobs"][SHARD], SHARD: d["source_blobs"][SCHEDULE]})),
        edit(lambda d: d["base_blobs"].pop(SPLIT_POLICY)),
        edit(lambda d: d.update({"extra": 1})),
    ]
    for fn in forged:
        ref = _variant(clone, {T.MANIFEST: fn})
        with C.call_scope():
            assert not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref)
    non_canonical = _variant(clone, {T.MANIFEST: lambda b: b.replace(b"\n", b"\r\n", 1)})
    assert not T.signature_ok(clone, non_canonical)


def test_wrong_ancestor_and_unknown_protected_paths_are_rejected(clone):
    assert not T.signature_ok(clone, T.BASE)                       # the accepted base carries no successor manifest
    first = _g(clone, "rev-list", "--max-parents=0", "HEAD").decode().split()[0]
    assert not T.signature_ok(clone, first) and not T.exact_blobs_ok(clone, first)
    for path in ("app/v2/react_financing.py", "financial_engine/tax/engine.py", "finco_core/placeholder.py", ".github/workflows/ci_v4_pr.yml",
                 "tools/ci_v4_select.py", "tools/ci_v4_governance_gate.py", "tools/ci_v4_nodes.py", "docs/ci_v4/module_weights.json",
                 "docs/ci_v4/ci-v4-policy.json", "static/react/finco-react.css"):
        if (ROOT / path).exists():
            ref = _variant(clone, {path: lambda b: b + b"\n"})
        else:
            ref = _variant(clone, add={path: b"x = 1\n"})
        with C.call_scope():
            assert not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref), path


@pytest.mark.parametrize("extra", ["tools/ci_v4_unreviewed.py", "tools/other_tool.py", "tools/ci_v4/__init__.py", ".github/workflows/ci_v4_extra.yml",
                                   "docs/ci_v4/node_split_extra.json", "docs/ci_v4/shard2_fix/EXTRA.json"])
def test_a_new_unreviewed_ci_path_is_never_admitted_by_a_prefix_or_wildcard(clone, extra):
    ref = _variant(clone, add={extra: b"{}\n" if extra.endswith(".json") else b"x = 1\n"})
    with C.call_scope():
        assert not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref), extra
        assert not T.allowed_path(extra, clone, ref)


def test_allowed_path_is_gated_by_the_cohort_signature_and_never_admits_foreign_paths(clone):
    for p in ("financial_engine/tax/engine.py", "app/v2/router.py", "tools/ci_v4_select.py", ".github/workflows/ci_v4_pr.yml", "docs/ci_v4/module_weights.json"):
        assert not T.allowed_path(p)
    assert T.allowed_path(SCHEDULE) and T.allowed_path(T.MANIFEST) and T.protected_blobs() == {}
    tree = T.BASE_TREE.encode()
    bad = _variant(clone, {T.MANIFEST: lambda b: b.replace(b'"base_tree": "' + tree[:8], b'"base_tree": "1' + tree[1:8], 1)})
    assert not T.allowed_path(SCHEDULE, clone, bad)                 # with a false signature even an owned path confers no authority


def test_supersession_is_pin_exact_and_cross_path_safe():
    with C.call_scope():      # ONE registry-wide read for this call: every link's verdict is evaluated once, not once per assertion
        pins = T.manifest()["source_blobs"]
        sched, shard, reg = pins[SCHEDULE], pins[SHARD], pins[T.REGISTRY]
        assert T.supersedes(SCHEDULE, sched) and T.supersedes(SHARD, shard) and T.supersedes(T.REGISTRY, reg)
        # C06 supersedes these paths ONLY by forwarding to this successor, and only for the exact current pin.
        assert K.supersedes(SCHEDULE, sched) is True and K.supersedes(SHARD, shard) is True and K.supersedes(T.REGISTRY, reg) is True
        stale = T.manifest()["base_blobs"][SCHEDULE]                        # the scheduler accepted on main is no longer current anywhere in the chain
        assert K.supersedes(SCHEDULE, stale) is False and K.supersedes(SCHEDULE, "0" * 40) is False and K.supersedes(SCHEDULE, shard) is False
        assert not T.supersedes(SCHEDULE, "0" * 40) and not T.supersedes(SCHEDULE, shard) and not T.supersedes(SCHEDULE, stale)
        assert not T.supersedes("tests/not_superseded.py", reg) and not T.supersedes("tools/ci_v4_select.py", reg)


def test_forwarded_supersession_needs_a_valid_successor_signature(clone):
    """The C06 answer for the CI paths is the successor's alone: a committed variant whose successor signature is false confers nothing."""
    pin = T.manifest(clone, "HEAD")["source_blobs"][SCHEDULE]
    with T.scoped(), K.scoped():
        assert K.supersedes(SCHEDULE, pin, clone, "HEAD") is True
    tree = T.BASE_TREE.encode()
    for edit in (lambda b: b.replace(b'"base_tree": "' + tree[:8], b'"base_tree": "1' + tree[1:8], 1),          # forged base tree
                 lambda b: b.replace(b'"' + SCHEDULE.encode() + b'": "', b'"' + SCHEDULE.encode() + b'": "0000', 1)):   # forged scheduler pin
        bad = _variant(clone, {T.MANIFEST: edit})
        with T.scoped(), K.scoped():
            assert K.supersedes(SCHEDULE, pin, clone, bad) is False


def test_no_verdict_is_cached_across_refs_or_mutations(clone):
    bad = _variant(clone, {T.REGISTRY: lambda b: b.replace(b", 'tests.ci_v4_shard2_fix_scope')", b")")})
    with T.scoped(), K.scoped():
        assert T.signature_ok(clone, "HEAD") and K.exact_blobs_ok(clone, "HEAD")
        assert not T.signature_ok(clone, bad) and not K.exact_blobs_ok(clone, bad)     # same process, same scope, other ref
    assert T.signature_ok(clone, "HEAD")                                                # and the positive verdict was never poisoned


def test_forged_current_map_key_and_stale_scheduler_are_rejected(clone):
    old = _base(SCHEDULE)
    ref = _variant(clone, {SCHEDULE: lambda b: old})            # the accepted scheduler served while this manifest pins the new bytes
    with C.call_scope():
        assert not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref)
    key = SCHEDULE.encode()
    ref = _variant(clone, {CI_MAP: lambda b: b.replace(b'"' + key + b'": "', b'"' + key + b'": "0000', 1)})
    with C.call_scope():
        assert not T.exact_blobs_ok(clone, ref) and not V.exact_blobs_ok(clone, ref) and not C.valid(clone, ref)


def test_c06_historical_manifest_and_ledger_stay_byte_identical_and_c06_itself_stays_valid():
    for p in ("docs/react_migration/c06_cost_workspace/SOURCE_SUCCESSOR.json", "docs/react_migration/c06_cost_workspace/C06_LEDGER.md"):
        assert (ROOT / p).read_bytes() == _base(p), p
    with C.call_scope():
        assert K.signature_ok() and K.exact_blobs_ok() and K.reviewed_edits_ok()


def test_older_cohort_hooks_only_follow_this_successor_while_its_signature_holds(clone):
    """The bounded hooks added to the older cohorts (U1, U2, PR1, PR2b, PR2c, PR3b1) confer nothing for a path of this successor when its signature is false."""
    from tests import u2_scope as U2, ux_pr3b1_scope as U3
    tree = T.BASE_TREE.encode()
    bad = _variant(clone, {T.MANIFEST: lambda b: b.replace(b'"base_tree": "' + tree[:8], b'"base_tree": "1' + tree[1:8], 1)})
    with C.call_scope():
        assert not T.signature_ok(clone, bad)
        for path in (SCHEDULE, SPLIT_POLICY, NODE_WEIGHTS, T.REGISTRY):
            value = T.manifest(clone, "HEAD")["source_blobs"][path]
            assert U2.supersedes(path, value, clone, bad) is False and U3.supersedes(path, value, clone, bad) is False, path


# ---------------------------------------------------------------- post413_o1: the accepted U2 -> C06 lineage of CostWorkbench / CostLinesGridView
U2_MAP = "docs/react_migration/u2_workbench/U2_EXACT_SOURCE.json"
C06_MANIFEST = "docs/react_migration/c06_cost_workspace/SOURCE_SUCCESSOR.json"
COST_WORKBENCH = "frontend/src/app/CostWorkbench.tsx"


def _json_pin(path, key, value):
    def run(raw):
        d = json.loads(raw)
        d["source_blobs"][key] = value
        return (json.dumps(d, indent=2, sort_keys=True) + "\n").encode()
    return run


def test_o1_audit_accepts_the_registered_u2_to_c06_lineage_with_an_authenticated_link():
    """Positive control for the reviewed finite expectation: the clean head passes and the two U2-signed presentation paths that C06 moved are both
    recognised, each through C06's recorded BASE blob (= U2's signed pin) and C06's own pin (= the evaluated bytes)."""
    from tests import test_post413_o1_scope as T1
    with C.call_scope():
        evidence = T1._audit_shared_sibling_pins()
        assert set(evidence[U2_MAP]["u2"]) == T1.U2_LATER_PRESENTATION == {COST_WORKBENCH, "frontend/src/app/editing/CostLinesGridView.tsx"}
        signed = json.loads((ROOT / U2_MAP).read_text())["source_blobs"]
        c06 = json.loads((ROOT / C06_MANIFEST).read_text())
        for p in T1.U2_LATER_PRESENTATION:
            assert c06["base_blobs"][p] == signed[p] and T1._c06_continues(p, signed[p], ROOT, None)
            assert not T1._c06_continues(p, "0" * 40, ROOT, None) and not T1._c06_continues(p, c06["source_blobs"][p], ROOT, None)      # only the signed link


@pytest.mark.parametrize("name", ["forged_u2_pin", "stale_u2_pin", "foreign_path_in_u2_map", "unsigned_bytes", "forged_c06_base_link"])
def test_o1_audit_still_rejects_every_tampering_of_the_u2_to_c06_lineage(clone, name):
    from tests import test_post413_o1_scope as T1
    with C.call_scope():
        assert T1._audit_shared_sibling_pins(clone, "HEAD")            # the clean committed head passes: a rejection below is caused by the tamper
    stale = json.loads(subprocess.check_output(["git", "show", T1.O.BASE + ":" + U2_MAP], cwd=ROOT))["source_blobs"][COST_WORKBENCH]      # the o1 BASE value
    base = json.loads((ROOT / C06_MANIFEST).read_text())["base_blobs"][COST_WORKBENCH]
    edits = {
        "forged_u2_pin": {U2_MAP: _json_pin(U2_MAP, COST_WORKBENCH, "0" * 40)},
        "stale_u2_pin": {U2_MAP: _json_pin(U2_MAP, COST_WORKBENCH, stale)},
        "foreign_path_in_u2_map": {U2_MAP: _json_pin(U2_MAP, "frontend/src/app/ForeignSibling.tsx", "0" * 40)},
        "unsigned_bytes": {COST_WORKBENCH: lambda b: b + b"\n"},
        "forged_c06_base_link": {C06_MANIFEST: lambda b: b.replace(b'"' + COST_WORKBENCH.encode() + b'": "' + base[:8].encode(), b'"' + COST_WORKBENCH.encode() + b'": "0000' + base[4:8].encode(), 1)},
    }[name]
    ref = _variant(clone, edits)
    # The audit either raises, or (a pin equal to the historical one is simply "not moved") stops admitting the path as a later signed U2 successor.
    try:
        with C.call_scope():
            admitted = set(T1._audit_shared_sibling_pins(clone, ref)[U2_MAP]["u2"])
    except AssertionError:
        admitted = None
    assert admitted != T1.U2_LATER_PRESENTATION, name
    with C.call_scope():                                              # and the registered chain itself refuses the tampered commit
        assert not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref), name
