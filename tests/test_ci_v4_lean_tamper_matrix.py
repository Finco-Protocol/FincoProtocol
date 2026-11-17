"""CI V4 Lean B1: the ONE central negative tamper matrix, one row per invariant class, driven through the real central gate.

Risk protected: PRs run a single central provenance gate (``tools/ci_v4_governance_gate.py``) instead of every historical per-cohort test, so that
gate must demonstrably fail closed for each tamper class AND for the intended reason, and must not fail on noise.

Method (an A/B/A design in an isolated FULL-history clone; the repository under test is never touched):
  A  pristine clone                      -> gate PASS (asserted once; a failing baseline fails every row, never skips)
  B  exactly ONE injected change         -> gate FAIL, plus causal attribution (see below)
  A' hard-reset restoration              -> gate PASS again
Benign controls (mtime-only touch, identical-byte rewrite, gitignored file) must keep PASS: a bare FAIL on arbitrary change proves nothing.

Attribution classes (what the evidence supports, stated honestly):
  direct       the injected path is the ONLY path the registry's own primitives implicate (unowned path / unowned untracked guarded path)
  cohort_named the injected file is a cohort manifest and that exact cohort reports "not exact"
  pinned       the injected path is pinned by at least one cohort manifest or the mutation-security inventory; the A/B/A contrast (only that
               change differs) is the causal evidence because the gate revokes every signed sibling at once (all-or-nothing exactness)
  exception    the gate fails closed through an exception that names the injected file

Further classes the CLI cannot express (wrong ref/tree, memo across mutation, planned-vs-executed, selector self-narrowing) are driven through the
real registry / aggregator / selector in the same A/B/A form. Nothing here selects, skips, deletes or relaxes any test.
"""
import copy
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tests import ci_v4_lean_b1_scope as B1

ROOT = Path(__file__).resolve().parents[1]
GATE = [sys.executable, "-m", "tools.ci_v4_governance_gate"]
GIT_ID = ["-c", "user.name=lean-matrix", "-c", "user.email=noreply@users.noreply.github.com", "-c", "commit.gpgsign=false"]
GUARDED_DIRS = ("app/", "financial_engine/", "finco_core/", "domain/", ".github/", "main_web.py")
EVIDENCE = os.environ.get("FINCO_LEAN_MATRIX_EVIDENCE")          # opt-in: append one JSON line per row to this path; unset = write nothing


# ------------------------------------------------------------------------------------------------------------------ helpers
def _git(cwd, *args, check=True):
    return subprocess.run(["git", *GIT_ID, *args], cwd=str(cwd), capture_output=True, check=check)


def _out(cwd, *args):
    return _git(cwd, *args).stdout.decode().strip()


def _env(clone):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env["PYTHONPATH"] = str(clone)           # the clone's own tests/ and tools/ decide, never the repository running pytest
    return env


def run_gate(clone, tag):
    out = Path(str(clone) + "-" + tag + ".json")
    out.unlink(missing_ok=True)
    started = time.monotonic()
    proc = subprocess.run(GATE + ["--output", str(out)], cwd=str(clone), env=_env(clone), capture_output=True, text=True, timeout=900)
    record = json.loads(out.read_text()) if out.exists() else {"verdict": "NO_RECORD", "stderr": proc.stderr[-300:]}
    return {"verdict": record.get("verdict"), "rc": proc.returncode, "record": record, "wall_s": round(time.monotonic() - started, 1)}


def restore(clone):
    _git(clone, "reset", "-q", "--hard", "HEAD")
    _git(clone, "clean", "-fdxq")
    _git(clone, "checkout", "-q", "--detach", HEAD_OF[str(clone)])
    assert _out(clone, "status", "--porcelain") == ""


HEAD_OF = {}

PROBE = r'''
import json, subprocess, sys
sys.path.insert(0, ".")
from tests import fin_v2_cohorts as C
mods = C.cohorts()
out = {"error": None}
try:
    with C.call_scope():
        out["not_exact"] = sorted(m.__name__ for m in mods if not m.exact_blobs_ok())
        changed = subprocess.check_output(["git", "diff", "--name-only", C.PARENT, "--"], text=True).splitlines()
        out["unallowed"] = sorted(p for p in changed if not any(m.allowed_path(p) for m in mods))
        owned = set().union(*(set(m.manifest().get("source_blobs", {})) for m in mods))
        unt = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "--"] + %(guard)r, text=True).splitlines()
        out["untracked_unowned"] = sorted(p for p in unt if p not in owned)
except Exception as exc:
    out["error"] = type(exc).__name__ + ": " + str(exc)
print(json.dumps(out))
''' % {"guard": list(GUARDED_DIRS)}

PINS = r'''
import json, sys
sys.path.insert(0, ".")
from tests import fin_v2_cohorts as C
from tests import model_mutation_security_successor as S
pins, manifests = {}, {}
for m in C.cohorts():
    if getattr(m, "MANIFEST", None):
        manifests[m.MANIFEST] = m.__name__
    for p in m.manifest().get("source_blobs", {}):
        pins.setdefault(p, []).append(m.__name__)
print(json.dumps({"pins": pins, "manifests": manifests, "inventory": sorted(S.BLOBS)}))
'''


def probe(clone):
    proc = subprocess.run([sys.executable, "-c", PROBE], cwd=str(clone), env=_env(clone), capture_output=True, text=True, timeout=600)
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def clone(tmp_path_factory):
    shallow = subprocess.run(["git", "rev-parse", "--is-shallow-repository"], cwd=str(ROOT), capture_output=True, text=True).stdout.strip()
    assert shallow == "false", "the tamper matrix needs a FULL-history checkout (CI: fetch-depth 0); a shallow clone cannot judge provenance"
    root = tmp_path_factory.mktemp("lean-matrix") / "repo"
    _git(ROOT, "clone", "-q", "--no-hardlinks", str(ROOT), str(root))
    HEAD_OF[str(root)] = _out(root, "rev-parse", "HEAD")
    return root


@pytest.fixture(scope="module")
def pristine(clone):
    """A: the untouched clone must PASS the real gate; otherwise every row is meaningless and FAILS (never skips)."""
    g = run_gate(clone, "baseline")
    assert g["verdict"] == "PASS" and g["rc"] == 0, g
    assert g["record"]["registered"] and len(g["record"]["cohorts"]) == len(g["record"]["registered"]) and all(g["record"]["cohorts"].values())
    assert B1.__name__ in g["record"]["cohorts"]
    pins = json.loads(subprocess.run([sys.executable, "-c", PINS], cwd=str(clone), env=_env(clone), capture_output=True, text=True).stdout.strip().splitlines()[-1])
    return {"gate": g, **pins}


def _record(row, cls, a, b, a2, attribution):
    if EVIDENCE:
        with open(EVIDENCE, "a") as f:
            f.write(json.dumps({"row": row, "class": cls, "pristine": a["verdict"], "mutated": b["verdict"], "mutated_wall_s": b["wall_s"],
                                "restored": a2["verdict"], "restored_wall_s": a2["wall_s"], "attribution": attribution}, sort_keys=True) + "\n")


# ------------------------------------------------------------------------------------------------------------------ mutations
def _append(path, data=b"#\n"):
    def f(clone):
        p = clone / path
        p.write_bytes(p.read_bytes() + data)
    return f


def _chmod(path):
    return lambda clone: (clone / path).chmod(0o755)


def _symlink(path, target):
    def f(clone):
        p = clone / path
        p.unlink()
        p.symlink_to(target)
    return f


def _delete(path):
    return lambda clone: _git(clone, "rm", "-q", path)


def _new_untracked(path):
    def f(clone):
        (clone / path).parent.mkdir(parents=True, exist_ok=True)
        (clone / path).write_text("unreviewed = True\n")
    return f


def _new_tracked(path):
    def f(clone):
        _new_untracked(path)(clone)
        _git(clone, "add", path)
    return f


def _text_sub(path, old, new, count=1):
    def f(clone):
        p = clone / path
        text = p.read_bytes().decode()
        assert text.count(old) == count, (path, old, text.count(old))
        p.write_bytes(text.replace(old, new).encode())
    return f


def _manifest_edit(edit):
    def f(clone):
        p = clone / B1.MANIFEST
        d = json.loads(p.read_text())
        edit(d)
        p.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")          # still canonical: only the forged VALUE differs
    return f


def _forge_map_key(clone):
    p = clone / "docs/ci_v4/SOURCE_SUCCESSOR.json"
    d = json.loads(p.read_text())
    d["source_blobs"][B1.REGISTRY] = "0" * 40
    p.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")


def _restore_predecessor_base_bytes(clone):
    base = subprocess.run(["git", "show", B1.BASE + ":" + B1.PREDECESSOR], cwd=str(clone), capture_output=True, check=True).stdout
    (clone / B1.PREDECESSOR).write_bytes(base)             # the C06 forward hook to B1 removed again


REG = "tests/fin_v2_cohorts.py"
TAIL = "'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope')"
# row id, invariant class, mutation, injected path, attribution class
ROWS = [
    ("guarded_byte_product", "guarded_byte", _append("app/v2/router.py"), "app/v2/router.py", "pinned"),
    ("guarded_byte_ci_control", "guarded_byte", _append("tools/ci_v4_select.py"), "tools/ci_v4_select.py", "pinned"),
    ("policy_self_narrowing_byte", "policy_self_narrowing", _append("docs/ci_v4/ci-v4-policy.json", b" "), "docs/ci_v4/ci-v4-policy.json", "pinned"),
    ("git_exec_mode", "git_exec_mode", _chmod("app/v2/router.py"), "app/v2/router.py", "pinned"),
    ("symlink_swap", "symlink", _symlink("app/v2/capex_router.py", "router.py"), "app/v2/capex_router.py", "pinned"),
    ("deleted_pinned_file", "deleted_pinned", _delete("app/v2/grid_router.py"), "app/v2/grid_router.py", "exception"),
    ("untracked_guarded_path", "untracked_guarded", _new_untracked("app/lean_matrix_untracked.py"), "app/lean_matrix_untracked.py", "direct"),
    ("unowned_tracked_file", "unowned_tracked", _new_tracked("docs/ci_v4/lean_matrix_unowned.md"), "docs/ci_v4/lean_matrix_unowned.md", "direct"),
    ("forged_manifest_pin", "forged_manifest", _manifest_edit(lambda d: d["source_blobs"].__setitem__("docs/ci_v4/lean_b1/README.md", "0" * 40)),
     B1.MANIFEST, "cohort_named"),
    ("forged_manifest_base_tree", "forged_manifest", _manifest_edit(lambda d: d.__setitem__("base_tree", "0" * 40)), B1.MANIFEST, "cohort_named"),
    ("registry_cohort_removed", "registry", _text_sub(REG, "'tests.f03_financing_scope', ", ""), REG, "pinned"),
    ("registry_duplicate_registration", "registry", _text_sub(REG, TAIL, "'tests.ci_v4_lean_b3_scope', " + TAIL), REG, "pinned"),
    ("registry_b1_unregistered", "registry", _text_sub(REG, ", 'tests.ci_v4_lean_b1_scope'", ""), REG, "pinned"),
    ("registry_parent_forged", "registry", lambda clone: _text_sub(REG, re.search(r"PARENT = '[0-9a-f]+'", (clone / REG).read_text()).group(0),
                                                                    "PARENT = '%s'" % HEAD_OF[str(clone)])(clone), REG, "pinned"),
    ("successor_hook_removed", "successor_handoff", _restore_predecessor_base_bytes, B1.PREDECESSOR, "pinned"),
    ("successor_discovery_dropped", "successor_handoff", _text_sub("tests/u1_scope.py", ", 'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope')", ")"), "tests/u1_scope.py", "pinned"),
    ("current_map_key_forged", "current_map", _forge_map_key, "docs/ci_v4/SOURCE_SUCCESSOR.json", "pinned"),
]
assert len({r[0] for r in ROWS}) == len(ROWS)


def _attribute(clone, pristine, mutated_gate, injected, kind):
    """Evidence for WHY the gate failed; returns (class_reached, details). Asserts the claimed class."""
    rec = mutated_gate["record"]
    if kind == "exception":
        assert rec.get("error") and os.path.basename(injected).split(".")[0] in rec["error"], rec
        return "exception", rec["error"][:160]
    p = probe(clone)
    assert p["error"] is None, p
    if kind == "direct":
        implicated = set(p["unallowed"]) | set(p["untracked_unowned"])
        assert implicated == {injected}, implicated
        return "direct", sorted(implicated)
    if kind == "cohort_named":
        owner = pristine["manifests"][injected]
        assert owner in p["not_exact"] and owner == B1.__name__, (owner, p["not_exact"][:5])
        return "cohort_named", owner
    assert pristine["pins"].get(injected) or injected in pristine["inventory"] or injected == B1.PREDECESSOR, injected
    assert p["not_exact"], p
    return "pinned", {"pinned_by": len(pristine["pins"].get(injected, [])), "cohorts_not_exact": len(p["not_exact"])}


@pytest.mark.parametrize("row,cls,mutate,injected,kind", ROWS, ids=[r[0] for r in ROWS])
def test_one_injected_change_fails_the_central_gate_for_its_own_reason_and_restoration_passes(clone, pristine, row, cls, mutate, injected, kind):
    restore(clone)
    mutate(clone)
    b = run_gate(clone, "b-" + row)
    assert b["verdict"] == "FAIL" and b["rc"] == 1, (row, b["verdict"], b["rc"])      # the authoritative gate verdict, not a helper bool
    attribution = _attribute(clone, pristine, b, injected, kind)
    restore(clone)
    a2 = run_gate(clone, "r-" + row)
    assert a2["verdict"] == "PASS" and a2["rc"] == 0, (row, a2["verdict"])
    _record(row, cls, pristine["gate"], b, a2, attribution)


# ------------------------------------------------------------------------------------------------------------------ benign controls
def _touch(clone):
    os.utime(clone / "app/v2/router.py", (1_000_000_000, 1_000_000_000))


def _rewrite_same(clone):
    p = clone / "tools/ci_v4_select.py"
    p.write_bytes(p.read_bytes())


def _ignored_file(clone):
    (clone / "tests/zz_lean_matrix_benign.pyc").write_bytes(b"\0")


@pytest.mark.parametrize("name,fn", [("mtime_only", _touch), ("identical_bytes", _rewrite_same), ("gitignored_file", _ignored_file)])
def test_benign_changes_keep_the_gate_green_so_a_fail_is_never_noise(clone, pristine, name, fn):
    restore(clone)
    fn(clone)
    g = run_gate(clone, "benign-" + name)
    assert g["verdict"] == "PASS" and g["rc"] == 0, (name, g["record"].get("error"), g["verdict"])
    restore(clone)


# ------------------------------------------------------------------------------------------------------------------ wrong ref / tree
def _variant_commit(clone, path="app/v2/router.py"):
    """A second commit that differs from HEAD by ONE byte of one pinned file; the checkout is returned to the pristine HEAD."""
    good = HEAD_OF[str(clone)]
    restore(clone)
    p = clone / path
    p.write_bytes(p.read_bytes() + b"#\n")
    _git(clone, "add", path)
    _git(clone, "commit", "-q", "-m", "lean matrix: one-byte variant")
    bad = _out(clone, "rev-parse", "HEAD")
    _git(clone, "checkout", "-q", "--detach", good)
    _git(clone, "reset", "-q", "--hard", good)
    assert _out(clone, "diff", "--name-only", good, bad) == path and _out(clone, "status", "--porcelain") == ""
    return good, bad


def _lib(clone, code):
    proc = subprocess.run([sys.executable, "-c", "import json,sys\nsys.path.insert(0,'.')\n" + code], cwd=str(clone), env=_env(clone), capture_output=True,
                          text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-400:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_wrong_ref_and_tree_are_judged_by_the_ref_not_by_the_checkout(clone, pristine):
    good, bad = _variant_commit(clone)
    got = _lib(clone, "from tests import fin_v2_cohorts as C\n"
                      "print(json.dumps([C.valid(None,%r), C.valid(None,%r), C.valid(None,'refs/heads/does-not-exist')]))" % (good, bad))
    # the checkout is the pristine HEAD in all three calls; only the REF differs (one byte of one pinned file, or a ref that does not exist)
    assert got == [True, False, False], got
    restore(clone)


def test_the_gate_cli_has_no_ref_input_so_the_ref_class_is_proved_through_the_registry_not_the_cli(tmp_path):
    """Behavioural: the CLI refuses a ``--ref`` argument (it judges the checkout only), which is why the row above drives the registry API."""
    proc = subprocess.run(GATE + ["--ref", "HEAD", "--output", str(tmp_path / "x.json")], cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 2 and "unrecognized arguments" in proc.stderr and not (tmp_path / "x.json").exists()


# ------------------------------------------------------------------------------------------------------------------ memo across mutation
def test_no_verdict_survives_a_mutation_a_scope_exit_or_a_different_ref(clone, pristine):
    good, bad = _variant_commit(clone)
    code = r"""
from tests import fin_v2_cohorts as C
import subprocess
def mutate(): open('app/v2/router.py', 'a').write('#\n')
def restore(): subprocess.run(['git', 'checkout', '--', 'app/v2/router.py'], check=True)
a = {}
a['no_scope'] = [C.valid()]; mutate(); a['no_scope'].append(C.valid()); restore(); a['no_scope'].append(C.valid())
with C.call_scope():
    a['scope_two_refs'] = [C.valid(None, %r), C.valid(None, %r)]       # memo is keyed by ref: one scope, two refs, two verdicts
with C.call_scope():
    a['scope_first'] = C.valid()
mutate()
a['after_scope_exit'] = C.valid()                                      # nothing outlives the outermost scope: the mutation is seen
restore()
a['restored'] = C.valid()
print(json.dumps(a))
""" % (good, bad)
    a = _lib(clone, code)
    assert a["no_scope"] == [True, False, True], a
    assert a["scope_two_refs"] == [True, False], a
    assert a["scope_first"] is True and a["after_scope_exit"] is False and a["restored"] is True, a
    restore(clone)


# ------------------------------------------------------------------------------------------------------------------ planned vs executed
SHA, TREE = "a" * 40, "b" * 40


def _plan_and_shards():
    from tools import ci_v4_select as S
    policy = json.loads((ROOT / "docs/ci_v4/ci-v4-policy.json").read_text())
    plan = S.select(["README.md"], copy.deepcopy(policy), root=ROOT, head_sha=SHA, tree_sha=TREE, base_sha="c" * 40)
    shards = [{"shard": i, "sha": SHA, "tree": TREE, "plan_digest": plan["digest"], "modules": m, "wall_s": 10.0}
              for i, m in enumerate(plan["schedule"]["shards"])]
    return plan, shards


def _junit(tmp_path, modules, status=None, name="j.xml", extra=()):
    rows = []
    for m in modules:
        body = {"failed": "<failure message='x'/>", "skipped": "<skipped message='s'/>"}.get((status or {}).get(m), "")
        rows.append("<testcase classname='%s' name='test_one' time='0.1'>%s</testcase>" % (m[:-3].replace("/", "."), body))
    rows += ["<testcase classname='%s' name='test_x' time='0.1'/>" % c for c in extra]
    p = tmp_path / name
    p.write_text("<testsuites><testsuite>%s</testsuite></testsuites>" % "".join(rows))
    return p


@pytest.mark.parametrize("variant,problem", [
    ("complete", None),
    ("selected_but_never_executed", "never executed"),
    ("skipped_is_not_pass", "skipped"),
    ("foreign_node_outside_selection", "outside the selection"),
    ("duplicate_node_across_junit", "duplicate node"),
    ("shard_bound_to_other_sha", "different sha"),
])
def test_planned_versus_executed_mismatch_fails_and_only_the_complete_run_passes(tmp_path, variant, problem):
    from tools import ci_v4_aggregate as A
    plan, shards = _plan_and_shards()
    mods = plan["pytest_modules"]
    status, extra, files = None, (), None
    if variant == "selected_but_never_executed":
        files = [_junit(tmp_path, mods[1:])]
    elif variant == "skipped_is_not_pass":
        files = [_junit(tmp_path, mods, {mods[0]: "skipped"})]
    elif variant == "foreign_node_outside_selection":
        files = [_junit(tmp_path, mods, extra=("tests.test_not_selected_anywhere",))]
    elif variant == "duplicate_node_across_junit":
        files = [_junit(tmp_path, mods, name="a.xml"), _junit(tmp_path, mods[:1], name="b.xml")]
    elif variant == "shard_bound_to_other_sha":
        shards = [dict(s, sha="d" * 40) for s in shards]
    files = files or [_junit(tmp_path, mods)]
    result = A.aggregate(plan, shards, files)
    if problem is None:
        assert result["verdict"] == "PASS" and result["counts"]["passed"] == len(mods) and not result["problems"]
    else:
        assert result["verdict"] == "FAIL" and any(problem in p for p in result["problems"]), result["problems"]
        if variant == "skipped_is_not_pass":
            assert result["skipped_label"] == "SKIPPED (not PASS)" and result["skipped_ids"]


def test_a_tampered_plan_is_refused_by_the_aggregator():
    from tools import ci_v4_aggregate as A
    plan, shards = _plan_and_shards()
    plan = dict(plan, pytest_modules=plan["pytest_modules"][1:])          # the digest no longer matches the content
    with pytest.raises(A.AggregateError):
        A.aggregate(plan, shards, [])


# ------------------------------------------------------------------------------------------------------------------ selector self-narrowing
def _select(policy, changed):
    from tools import ci_v4_select as S
    return S.select(changed, copy.deepcopy(policy), root=ROOT, head_sha=SHA, tree_sha=TREE, base_sha="c" * 40)


def test_a_pr_cannot_narrow_its_own_selection_and_an_identical_head_policy_is_accepted():
    from tools import ci_v4_select as S
    policy = json.loads((ROOT / "docs/ci_v4/ci-v4-policy.json").read_text())
    changed = ["app/v2/router.py"]
    base = _select(policy, changed)
    assert base["tier"] == "risk" and "risk_finance" in base["suites"] and len(base["pytest_modules"]) > 50
    kw = dict(root=ROOT, head_sha=SHA, tree_sha=TREE, base_sha="c" * 40)
    same = S.compare_with_head_policy(base, copy.deepcopy(policy), changed, **kw)             # benign control: identical head policy
    assert S.covers(same, base)
    narrowed_suite = copy.deepcopy(policy)
    narrowed_suite["suites"]["risk_finance"]["modules"] = narrowed_suite["suites"]["risk_finance"]["modules"][:-1]
    with pytest.raises(S.PolicyError, match="selects less"):
        S.compare_with_head_policy(base, narrowed_suite, changed, **kw)
    downtiered = copy.deepcopy(policy)
    for rule in downtiered["rules"]:
        if rule["id"] == "application_surface":
            rule["tier"] = "fast"
    with pytest.raises(S.PolicyError):
        S.compare_with_head_policy(base, downtiered, changed, **kw)


def test_a_narrower_head_policy_runs_the_union_never_less_than_the_trusted_base():
    from tools import ci_v4_select as S
    policy = json.loads((ROOT / "docs/ci_v4/ci-v4-policy.json").read_text())
    changed = ["app/v2/router.py"]
    base = _select(policy, changed)
    head = copy.deepcopy(policy)
    head["suites"]["risk_finance"]["modules"] = head["suites"]["risk_finance"]["modules"][:-1]
    head_plan = _select(head, changed)
    assert not S.covers(head_plan, base)                                                      # the head policy alone WOULD be narrower
    union = S.union_plan(base, head_plan, policy, ROOT)
    assert set(union["pytest_modules"]) >= set(base["pytest_modules"]) and union["head_policy_narrower"]["flag"] is True
    assert S.covers(union, base)
