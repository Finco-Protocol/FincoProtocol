"""CI V4 Lean B2 exact-source successor (after the accepted B1 leaf): positive identity and adversarial fail-closed controls.

Risk protected: B2 moves bytes of the protected provenance graph (the U1 provenance tests, the registry, two forward hooks and the current maps). It
must own exactly its finite file set, change no CI control file, make the U1 read-only nodes share ONE call scope without ever scoping a mutation, and
every forged manifest, registry state, handoff, mode or ref must be rejected. Every negative runs in an ISOLATED clone (a committed variant); the
evaluated checkout is never edited and no verdict is cached across mutations.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests import c06_cost_workspace_scope as K
from tests import ci_v4_lean_b1_scope as B
from tests import ci_v4_lean_b2_scope as T
from tests import fin_v2_cohorts as C
from tests import r04_ppa_scope as P

ROOT = Path(__file__).resolve().parents[1]
MODULE = "tests/ci_v4_lean_b2_scope.py"
OWN_TEST = "tests/test_ci_v4_lean_b2_scope.py"
U1_TESTS = "tests/test_u1_scope.py"
README = "docs/ci_v4/lean_b2/README.md"      # a B2-owned path no later successor hands off: its pin is still judged by B2 itself
SCOPED_NODES = ("test_positive_cohort_is_exact_registered_and_closed",
                "test_no_path_outside_the_superseded_set_is_ever_admitted_by_supersession",
                "test_integration_reference_is_main_after_414_and_everything_unowned_equals_it")


def _git(*args, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd).decode().strip()


@pytest.fixture(scope="module")
def clone(tmp_path_factory):
    root = tmp_path_factory.mktemp("b1-gov") / "repo"
    subprocess.check_call(["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(root)])
    subprocess.check_call(["git", "checkout", "-q", "--detach", _git("rev-parse", "HEAD")], cwd=root)
    return root


def _g(root, *args):
    return subprocess.check_output(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args], cwd=root)


def _variant(root, edits=None, mode=None, remove=(), symlink=None):
    """Commit one mutated copy of the evaluated HEAD in the isolated clone and return its sha; the clone is restored afterwards."""
    base = _g(root, "rev-parse", "HEAD").decode().strip()
    try:
        for path, fn in (edits or {}).items():
            f = root / path
            f.write_bytes(fn(f.read_bytes()))
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


def _rejected(clone, ref):
    with C.call_scope():
        return not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref)


def _rejected_by_closure(clone, ref):
    """Current-map bytes are judged ONLY by the full closure (the signature never reads a foreign map), so a map tamper is rejected by exactness and the composite."""
    with C.call_scope():
        return T.signature_ok(clone, "HEAD") and not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref)


# -------------------------------------------------------------------------------------------------------------- positive identity
def test_literal_closed_paths_and_immutable_predecessor_blobs():
    data = T.manifest()
    assert set(data["source_blobs"]) == T.OWNED_PATHS and set(data["base_blobs"]) == T.SUPERSEDED
    assert set(data["source_modes"]) == T.OWNED_PATHS and set(data["base_modes"]) == T.SUPERSEDED
    assert len(T.CURRENT_MAPS) == 8 and set(T.HANDOFFS) == T.HANDOFF_PATHS
    assert T.MAP_KEYS == ("tests/fin_v2_cohorts.py", "tests/u1_scope.py", "tests/test_u1_scope.py")
    assert T.PREDECESSOR == "tests/ci_v4_lean_b1_scope.py" and T.REGISTRY == "tests/fin_v2_cohorts.py"
    assert not any(p.startswith(T.FORBIDDEN) or "*" in p or ".." in p.split("/") or p.startswith("/") for p in T.OWNED_PATHS | {T.MANIFEST})
    for path in T.SUPERSEDED:
        assert data["base_blobs"][path] == _git("rev-parse", T.BASE + ":" + path)
    assert _git("rev-parse", T.BASE + "^{tree}") == T.BASE_TREE


def test_it_owns_no_selector_policy_workflow_tool_or_product_source():
    """B2 changes no CI control file, no tools/ or .github/ path and no product path, and every CI V4 control file stays byte-equal to accepted main."""
    assert not (T.OWNED_PATHS | {T.MANIFEST}) & set(T.FROZEN)
    assert not any(p.startswith((".github/", "tools/", "app/", "financial_engine/", "finco_core/", "domain/", "frontend/", "static/", "research/"))
                   for p in T.OWNED_PATHS | {T.MANIFEST})
    for path in T.FROZEN:
        if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml') and T._p0_pins_frozen_edit(
                path, T._blob((ROOT / path).read_bytes()), ROOT, None):      # P1: exactly these two control blobs, only at the exact P0 pin
            continue
        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT), path
    assert {"tools/ci_v4_select.py", "docs/ci_v4/ci-v4-policy.json", ".github/workflows/ci_v4_pr.yml", "tools/ci_v4_aggregate.py",
            "tools/ci_v4_schedule.py", "docs/ci_v4/module_weights.json", "docs/ci_v4/node_split_policy.json"} <= set(T.FROZEN)


def test_signature_exactness_and_reviewed_substitutions_hold(clone):
    from tests.fin_v2_cohorts import call_scope
    with call_scope():  # one read-only enumeration; ends before any fixture teardown or mutation
        assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()
        T3 = T._next()
        T4 = T3._next() if T3 is not None and T3.signature_ok() else None
        T5 = T4._next() if T4 is not None and T4.signature_ok() else None
        T6 = T5._next() if T5 is not None and T5.signature_ok() else None
        T7 = T6._next() if T6 is not None and T6.signature_ok() else None
        for p in T.HANDOFFS:
            from tests import ci_v4_p0_scope as P0
            if P0.signature_ok() and p in P0.HANDOFFS:
                assert (ROOT / p).read_bytes() == P0.expected_handoff(ROOT, p)
                assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]
                continue
            if T7 is not None and T7.signature_ok() and p in T7.HANDOFFS:      # the reviewed FULL-recovery substitution of this shared path
                assert (ROOT / p).read_bytes() == T7.expected_handoff(ROOT, p)
            elif T6 is not None and T6.signature_ok() and p in T6.HANDOFFS:      # the reviewed V5-3 substitution of this shared path
                assert (ROOT / p).read_bytes() == T6.expected_handoff(ROOT, p)
            elif T5 is not None and T5.signature_ok() and p in T5.HANDOFFS:      # the reviewed V5-2B substitution of this shared path
                assert (ROOT / p).read_bytes() == T5.expected_handoff(ROOT, p)
            elif T4 is not None and T4.signature_ok() and p in T4.HANDOFFS:      # the reviewed V5 bootstrap substitution of this shared path
                assert (ROOT / p).read_bytes() == T4.expected_handoff(ROOT, p)
            elif T3 is not None and T.SUCCESSOR in C.COHORT_MODULES and T3.signature_ok() and p in T3.HANDOFFS:      # the reviewed B3 substitution of this shared path
                assert (ROOT / p).read_bytes() == T3.expected_handoff(ROOT, p)
            else:
                assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)
            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]
        for ref in (None, "HEAD"):
            with C.call_scope():
                assert T.signature_ok(clone, ref) and T.exact_blobs_ok(clone, ref) and B.exact_blobs_ok(clone, ref) and C.valid(clone, ref)


def test_registered_exactly_once_as_the_terminal_cohort_after_b1():
    assert C.COHORT_MODULES.count(T.__name__) == 1
    assert C.COHORT_MODULES[-3:] in (("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope"), ("tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope"), ("tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope"), ("tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope"), ("tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope"), ("tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope"), ('tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope'))
    assert B.SUCCESSOR == T.__name__ and K.SUCCESSOR == B.__name__ and K._next() is B
    from tests import ci_v4_lean_b3_scope as T3
    if T.SUCCESSOR in C.COHORT_MODULES:
        assert C.COHORT_MODULES[-1] in (T.SUCCESSOR, "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope", 'tests.ci_v4_p0_scope') and T3.PREDECESSOR == "tests/ci_v4_lean_b2_scope.py"


def test_b1_c06_and_every_older_cohort_still_follow_the_chain():
    with C.call_scope():
        assert B.signature_ok() and K.signature_ok() and P.exact_blobs_ok() and all(m.exact_blobs_ok() for m in C.cohorts()) and C.valid()
        pin = T.effective_pins()[U1_TESTS]
        assert B.supersedes(U1_TESTS, pin) and K.supersedes(U1_TESTS, pin) and B.effective_pins()[U1_TESTS] == pin
        assert set(B.closure_paths()) >= set(T.closure_paths()) and set(K.closure_paths()) >= set(B.closure_paths())


def test_current_maps_move_only_their_registry_u1_and_u1_test_keys():
    pins = T.effective_pins()
    for p in T.CURRENT_MAPS:
        old = json.loads(_git("show", T.BASE + ":" + p))
        cur = json.loads((ROOT / p).read_text())
        assert set(old) == set(cur) and all(old[k] == cur[k] for k in old if k != "source_blobs")
        assert set(cur["source_blobs"]) == set(old["source_blobs"])
        changed = {k for k in old["source_blobs"] if old["source_blobs"][k] != cur["source_blobs"][k]}
        legacy_keys = set(T.MAP_KEYS)
        if changed - legacy_keys:
            from tests import ci_v4_p0_scope as P0
            assert changed - legacy_keys <= set(P0.MAP_EXTRA_KEYS.get(p, ()))
            assert P0.exact_blobs_ok() and (ROOT / p).read_bytes() == P0.expected_map(ROOT, p)
        assert all(cur["source_blobs"][k] == pins[k] for k in changed)


def test_the_u1_discovery_list_names_this_successor_exactly_once_and_last():
    from tests import u1_scope as U
    assert U.RECONCILED_SUCCESSORS[-2:] in (("tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope"), ("tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope"), ("tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope"), ("tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope"), ("tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope"), ("tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope"), ("tests.ci_v4_full_recovery_scope", "tests.ci_v4_p0_scope"))
    assert U.RECONCILED_SUCCESSORS.count("tests.ci_v4_lean_b2_scope") == 1


# -------------------------------------------------------------------------------------------------------------- the one behavioural change
_MUTATING = ("_flip", "wt", "_tree", "unlink", "chmod", "write_text", "write_bytes", "worktree", "checkout", "reset", "commit", "clean", "symlink")


def _functions():
    import ast
    tree = ast.parse((ROOT / U1_TESTS).read_text())
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def _mutation_markers(node):
    import ast
    seen = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id in _MUTATING:
            seen.add(n.id)
        elif isinstance(n, ast.Attribute) and n.attr in _MUTATING:
            seen.add(n.attr)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in _MUTATING:
            seen.add(n.value)
        elif isinstance(n, ast.arg) and n.arg in _MUTATING:
            seen.add(n.arg)
    return seen


@pytest.mark.parametrize("name", SCOPED_NODES)
def test_u1_scoped_nodes_are_one_call_scope_around_a_read_only_body(name):
    """The ONLY behavioural change: the public test is `with C.call_scope(): _body()`; the body is the unchanged original, takes no fixture and contains no mutation."""
    import ast
    fns = _functions()
    public, body = fns[name], fns["_" + name[len("test_"):]]
    assert [a.arg for a in public.args.args] == [] and [a.arg for a in body.args.args] == []
    assert len(public.body) == 1 and isinstance(public.body[0], ast.With) and len(public.body[0].body) == 1
    item = public.body[0].items[0].context_expr
    assert ast.unparse(item) == "C.call_scope()" and len(public.body[0].items) == 1
    call = public.body[0].body[0]
    assert isinstance(call, ast.Expr) and ast.unparse(call.value) == "_" + name[len("test_"):] + "()"
    assert not _mutation_markers(body), (name, _mutation_markers(body))


def test_the_mutation_detector_is_not_vacuous_and_tamper_nodes_stay_outside_any_scope():
    fns = _functions()
    assert _mutation_markers(fns["test_one_altered_byte_in_any_owned_file_fails_closed"])         # the detector sees a real mutation node
    assert _mutation_markers(fns["test_protected_and_unowned_code_modified_after_signing_fails_closed"])
    import ast
    for name, node in fns.items():
        if name.startswith("test_") and name not in SCOPED_NODES and _mutation_markers(node):
            assert not any(isinstance(x, ast.Attribute) and x.attr == "call_scope" for x in ast.walk(node)), name       # no tamper / worktree node sits inside a shared scope
    for name in ("test_older_cohorts_still_exact_through_the_bounded_hooks",):
        assert name in fns                                                  # the pre-existing read-only scope is untouched


def test_u1_assertion_count_is_unchanged_by_the_wrappers():
    """The wrappers add no assertion and remove none: each helper body is byte-equal to the original node body of accepted main."""
    import ast
    old = ast.parse(_git("show", T.BASE + ":" + U1_TESTS))
    olds = {n.name: n for n in old.body if isinstance(n, ast.FunctionDef)}
    fns = _functions()
    for name in SCOPED_NODES:
        helper = fns["_" + name[len("test_"):]]
        assert ast.dump(ast.Module(body=helper.body, type_ignores=[])) == ast.dump(ast.Module(body=olds[name].body, type_ignores=[])), name
    for name, node in olds.items():
        if name.startswith("test_") and name not in SCOPED_NODES:
            assert ast.dump(node) == ast.dump(fns[name]), name


def test_call_scope_memo_is_dropped_on_exit_and_a_later_mutation_is_judged_fresh(clone):
    with C.call_scope():
        assert C.valid(clone) and T.exact_blobs_ok(clone)
    assert not C._CALL and not T._SCOPE
    target = clone / "app/cost_line_ledger/opex_bases.py"
    try:
        target.write_bytes(target.read_bytes() + b"\n")
        assert not C.valid(clone) and not T.exact_blobs_ok(clone) and not T.exact_blobs_ok(clone)      # never answered from an earlier scope
    finally:
        _g(clone, "checkout", "-q", "-f", "HEAD")
        _g(clone, "clean", "-fdxq")
    with C.call_scope():
        assert C.valid(clone)


# -------------------------------------------------------------------------------------------------------------- tamper (committed refs)
@pytest.mark.parametrize("path", sorted((T.OWNED_PATHS | {T.MANIFEST}) - T.CURRENT_MAPS))
def test_one_byte_in_any_owned_committed_blob_is_rejected(clone, path):
    assert _rejected(clone, _variant(clone, {path: lambda b: b + b"\n"})), path


@pytest.mark.parametrize("path", sorted(T.CURRENT_MAPS))
def test_current_map_tamper_is_rejected_by_the_full_closure(clone, path):
    assert _rejected_by_closure(clone, _variant(clone, {path: lambda b: b + b"\n"})), path


@pytest.mark.parametrize("path", sorted(T.FROZEN))
def test_every_ci_v4_control_file_must_stay_byte_identical_to_the_accepted_base(clone, path):
    assert _rejected(clone, _variant(clone, {path: lambda b: b + b"\n"})), path


def test_registry_mutations_are_rejected(clone):
    tail = b"'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope')"
    for name, fn in (
        ("duplicate", lambda b: b.replace(tail, b"'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope')")),
        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", 'tests.fake_scope')")),
        ("swapped_b1_b2", lambda b: b.replace(tail, b"'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b1_scope')")),
        ("b2_missing", lambda b: b.replace(b", 'tests.ci_v4_lean_b2_scope'", b"")),
        ("b1_missing", lambda b: b.replace(b"'tests.ci_v4_lean_b1_scope', ", b"")),
        ("c06_missing", lambda b: b.replace(b"'tests.c06_cost_workspace_scope', ", b"")),
        ("r04_removed", lambda b: b.replace(b"'tests.r04_ppa_scope', ", b"")),
        ("earlier_reordered", lambda b: b.replace(b"'tests.fin_v2_3_scope', 'tests.fin_v2_ci_scope'", b"'tests.fin_v2_ci_scope', 'tests.fin_v2_3_scope'")),
    ):
        ref = _variant(clone, {T.REGISTRY: fn})
        assert _g(clone, "diff", "--name-only", "HEAD", ref).decode().split() == [T.REGISTRY], name
        assert _rejected(clone, ref), name


def test_partially_applied_handoff_is_rejected(clone):
    old_pred = subprocess.check_output(["git", "show", T.BASE + ":" + T.PREDECESSOR], cwd=ROOT)       # B1 forward hook reverted
    assert _rejected(clone, _variant(clone, {T.PREDECESSOR: lambda b: old_pred}))
    old_reg = subprocess.check_output(["git", "show", T.BASE + ":" + T.REGISTRY], cwd=ROOT)           # registry reverted, B1 files remain
    assert _rejected(clone, _variant(clone, {T.REGISTRY: lambda b: old_reg}))
    old_u1 = subprocess.check_output(["git", "show", T.BASE + ":tests/u1_scope.py"], cwd=ROOT)         # discovery list reverted
    assert _rejected(clone, _variant(clone, {"tests/u1_scope.py": lambda b: old_u1}))
    old_tests = subprocess.check_output(["git", "show", T.BASE + ":" + U1_TESTS], cwd=ROOT)           # the U1 wrappers reverted, hooks remain
    assert _rejected(clone, _variant(clone, {U1_TESTS: lambda b: old_tests}))
    old_c06 = subprocess.check_output(["git", "show", T.BASE + ":tests/c06_cost_workspace_scope.py"], cwd=ROOT)    # C06 third-state acceptance reverted
    assert _rejected(clone, _variant(clone, {"tests/c06_cost_workspace_scope.py": lambda b: old_c06}))


def test_forged_manifest_base_tree_pin_and_mode_are_rejected(clone):
    def edit(fn):
        def f(raw):
            d = json.loads(raw)
            fn(d)
            return (json.dumps(d, indent=2, sort_keys=True) + "\n").encode()
        return f
    forged = (edit(lambda d: d.__setitem__("base", "0" * 40)), edit(lambda d: d.__setitem__("base_tree", "0" * 40)),
              edit(lambda d: d["source_blobs"].__setitem__(README, "0" * 40)), edit(lambda d: d["base_blobs"].__setitem__(T.REGISTRY, "0" * 40)),
              edit(lambda d: d["source_modes"].__setitem__(MODULE, "100755")), edit(lambda d: d["base_modes"].__setitem__(T.REGISTRY, "100755")),
              edit(lambda d: d["source_blobs"].pop(OWN_TEST)), edit(lambda d: d.__setitem__("extra", 1)),
              edit(lambda d: d.__setitem__("authorization", "broader")), edit(lambda d: d.__setitem__("schema_version", "OTHER")),
              lambda b: b.rstrip(b"\n"), lambda b: b.replace(b"  ", b"   ", 1))                       # non-canonical bytes
    for fn in forged:
        assert _rejected(clone, _variant(clone, {T.MANIFEST: fn}))


def test_mode_symlink_deletion_and_unowned_paths_are_rejected(clone):
    assert _rejected(clone, _variant(clone, mode=MODULE))
    assert _rejected(clone, _variant(clone, symlink=OWN_TEST))
    assert _rejected(clone, _variant(clone, remove=(MODULE,)))
    for path in ("tools/ci_v4_lean_extra.py", ".github/workflows/lean_b2.yml", "app/lean_b2_extra.py", "docs/ci_v4/lean_b2/EXTRA.md", "tests/test_lean_unowned.py"):
        f = clone / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x = 1\n")
        _g(clone, "add", "-A")
        _g(clone, "commit", "-q", "-m", "unowned")
        ref = _g(clone, "rev-parse", "HEAD").decode().strip()
        _g(clone, "checkout", "-q", "-f", "HEAD~1")
        _g(clone, "clean", "-fdxq")
        assert _rejected_by_closure(clone, ref), path            # an unowned path leaves the source signature intact; exactness and the composite reject it


def test_wrong_ancestor_and_older_refs_are_rejected(clone):
    assert not T.signature_ok(clone, T.BASE) and not T.exact_blobs_ok(clone, T.BASE)              # accepted main carries no B2 manifest
    first = _g(clone, "rev-list", "--max-parents=0", "HEAD").decode().split()[0]
    assert not T.signature_ok(clone, first) and not T.exact_blobs_ok(clone, first)


def test_allowed_path_is_gated_by_the_cohort_signature_and_never_admits_foreign_paths(clone):
    for p in ("financial_engine/tax/engine.py", "app/v2/router.py", "tools/ci_v4_select.py", "docs/ci_v4/ci-v4-policy.json"):
        assert not T.allowed_path(p)
    assert T.allowed_path(MODULE) and T.allowed_path(OWN_TEST) and T.allowed_path(T.MANIFEST) and T.protected_blobs() == {}
    bad = _variant(clone, {T.MANIFEST: lambda b: b.replace(b'"base_tree": "af0a7144', b'"base_tree": "0f0a7144', 1)})
    assert not T.allowed_path(MODULE, clone, bad)                    # with a false signature even an owned path confers no authority


def test_supersession_is_pin_exact_and_cross_path_safe():
    pins = T.manifest()["source_blobs"]
    reg = T.effective_pins()[T.REGISTRY]            # the CURRENT registry pin (the B3 successor overlay wins while its signature holds)
    assert B.supersedes(T.REGISTRY, reg) and K.supersedes(T.REGISTRY, reg) and P.supersedes(T.REGISTRY, reg)
    assert not B.supersedes(T.REGISTRY, pins[T.REGISTRY])       # B2's own registry pin is superseded by B3 and no longer current
    assert not B.supersedes(T.REGISTRY, "0" * 40) and not K.supersedes(U1_TESTS, "0" * 40)
    assert not B.supersedes(T.REGISTRY, pins[T.PREDECESSOR])         # a real blob pinned for another path
    assert not B.supersedes(U1_TESTS, pins[T.REGISTRY]) and not B.supersedes(T.REGISTRY, pins[U1_TESTS])
    assert not B.supersedes(T.REGISTRY, T.manifest()["base_blobs"][T.REGISTRY])      # the accepted B1-era registry blob is no longer current
    assert not B.supersedes(U1_TESTS, T.manifest()["base_blobs"][U1_TESTS])          # nor is the accepted-main U1 test blob


def test_no_verdict_is_cached_across_refs_or_mutations(clone):
    bad = _variant(clone, {T.REGISTRY: lambda b: b.replace(b", 'tests.ci_v4_lean_b2_scope'", b"")})
    with T.scoped(), K.scoped():
        assert T.signature_ok(clone, "HEAD") and K.exact_blobs_ok(clone, "HEAD")
        assert not T.signature_ok(clone, bad) and not T.exact_blobs_ok(clone, bad)               # same process, same scope, other ref
    assert T.signature_ok(clone, "HEAD")                                                          # and the positive verdict was never poisoned
