"""CI V4 Lean B1 exact-source successor (after the accepted C06 leaf): positive identity and adversarial fail-closed controls.

Risk protected: B1 adds evidence/test sources to a protected provenance graph; it must own exactly its finite file set, change no CI control file,
and every forged manifest, registry state, handoff, mode or ref must be rejected. Every negative runs in an ISOLATED clone (a committed variant);
the evaluated checkout is never edited and no verdict is cached across mutations.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests import c06_cost_workspace_scope as K
from tests import ci_v4_lean_b1_scope as T
from tests import fin_v2_cohorts as C
from tests import r04_ppa_scope as P

ROOT = Path(__file__).resolve().parents[1]
REPORT = "tests/ci_v4_lean_report.py"
MATRIX = "tests/test_ci_v4_lean_tamper_matrix.py"
README = "docs/ci_v4/lean_b1/README.md"      # a B1-owned path no later successor hands off: its pin is still judged by B1 itself


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
    assert T.MAP_KEYS == ("tests/fin_v2_cohorts.py", "tests/u1_scope.py")
    assert T.PREDECESSOR == "tests/c06_cost_workspace_scope.py" and T.REGISTRY == "tests/fin_v2_cohorts.py"
    assert not any(p.startswith(T.FORBIDDEN) or "*" in p or ".." in p.split("/") or p.startswith("/") for p in T.OWNED_PATHS | {T.MANIFEST})
    for path in T.SUPERSEDED:
        assert data["base_blobs"][path] == _git("rev-parse", T.BASE + ":" + path)
    assert _git("rev-parse", T.BASE + "^{tree}") == T.BASE_TREE


def test_it_owns_no_selector_policy_workflow_tool_or_product_source():
    """B1 is additive evidence: no CI control file, no tools/ or .github/ path and no product path is owned, and every CI V4 control file stays byte-equal."""
    assert not (T.OWNED_PATHS | {T.MANIFEST}) & set(T.FROZEN)
    assert not any(p.startswith((".github/", "tools/", "app/", "financial_engine/", "finco_core/", "domain/", "frontend/", "static/", "research/"))
                   for p in T.OWNED_PATHS | {T.MANIFEST})
    T2 = T._next()
    T3 = T2._next() if T2 is not None and T2.signature_ok() else None
    for path in T.FROZEN:
        if T3 is not None and T2 is not None and T2.SUCCESSOR in C.COHORT_MODULES and T3.signature_ok() and path in T3.HANDOFFS:      # the reviewed B3 successor owns this control file's further substitution
            assert (ROOT / path).read_bytes() == T3.expected_handoff(ROOT, path), path
            continue
        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT), path
    assert {"tools/ci_v4_select.py", "docs/ci_v4/ci-v4-policy.json", ".github/workflows/ci_v4_pr.yml", "tools/ci_v4_aggregate.py",
            "tools/ci_v4_schedule.py", "docs/ci_v4/module_weights.json"} <= set(T.FROZEN)


def test_signature_exactness_and_reviewed_substitutions_hold(clone):
    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()
    N = T._next()
    N2 = N._next() if N is not None and N.signature_ok() else None
    N3 = N2._next() if N2 is not None and N2.signature_ok() else None
    N4 = N3._next() if N3 is not None and N3.signature_ok() else None
    N5 = N4._next() if N4 is not None and N4.signature_ok() else None
    N6 = N5._next() if N5 is not None and N5.signature_ok() else None
    for p in T.HANDOFFS:
        from tests import ci_v4_p0_scope as P0
        if P0.signature_ok() and p in P0.HANDOFFS:
            assert (ROOT / p).read_bytes() == P0.expected_handoff(ROOT, p)
            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]
            continue
        if N6 is not None and N6.signature_ok() and p in N6.HANDOFFS:      # the further reviewed FULL-recovery substitution of this shared path
            assert (ROOT / p).read_bytes() == N6.expected_handoff(ROOT, p)
            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]
            continue
        if N5 is not None and N5.signature_ok() and p in N5.HANDOFFS:      # the further reviewed V5-3 substitution of this shared path
            assert (ROOT / p).read_bytes() == N5.expected_handoff(ROOT, p)
            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]
            continue
        if N4 is not None and N4.signature_ok() and p in N4.HANDOFFS:      # the further reviewed V5-2B substitution of this shared path
            assert (ROOT / p).read_bytes() == N4.expected_handoff(ROOT, p)
            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]
            continue
        if N3 is not None and N3.signature_ok() and p in N3.HANDOFFS:      # the further reviewed V5 bootstrap substitution of this shared path
            assert (ROOT / p).read_bytes() == N3.expected_handoff(ROOT, p)
            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]
            continue
        if N2 is not None and N is not None and N.SUCCESSOR in C.COHORT_MODULES and N2.signature_ok() and p in N2.HANDOFFS:      # the further reviewed B3 substitution of this shared path
            assert (ROOT / p).read_bytes() == N2.expected_handoff(ROOT, p)
            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]
            continue
        if N is not None and N.signature_ok() and p in N.HANDOFFS:                  # the further reviewed B2 substitution of this shared path
            assert (ROOT / p).read_bytes() == N.expected_handoff(ROOT, p)
            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]
            continue
        assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)
        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]
    for ref in (None, "HEAD"):
        with C.call_scope():
            assert T.signature_ok(clone, ref) and T.exact_blobs_ok(clone, ref) and K.exact_blobs_ok(clone, ref) and C.valid(clone, ref)


def test_registered_exactly_once_as_the_terminal_cohort_after_c06():
    assert C.COHORT_MODULES in (T.BASE_COHORTS + (T.__name__,), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR),
                                T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, "tests.ci_v4_lean_b3_scope"),
                                T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope"),
                                T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope"),
                                T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope"), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope"), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope") + ('tests.ci_v4_p0_scope',)) and C.COHORT_MODULES.count(T.__name__) == 1
    assert C.COHORT_MODULES[C.COHORT_MODULES.index(T.__name__) - 1] == "tests.c06_cost_workspace_scope"
    assert K.SUCCESSOR == T.__name__ and K._next() is T


def test_c06_and_every_older_cohort_still_follow_the_chain():
    with C.call_scope():
        assert K.signature_ok() and P.exact_blobs_ok() and all(m.exact_blobs_ok() for m in C.cohorts()) and C.valid()
        assert K.supersedes(T.REGISTRY, T.effective_pins()[T.REGISTRY]) and K.effective_pins()[T.REGISTRY] == T.effective_pins()[T.REGISTRY]
        assert set(K.closure_paths()) >= set(T.closure_paths())


def test_current_maps_move_only_their_registry_and_u1_discovery_keys():
    pins = T.effective_pins()
    for p in T.CURRENT_MAPS:
        old = json.loads(_git("show", T.BASE + ":" + p))
        cur = json.loads((ROOT / p).read_text())
        assert set(old) == set(cur) and all(old[k] == cur[k] for k in old if k != "source_blobs")
        changed = {k for k in old["source_blobs"] if old["source_blobs"][k] != cur["source_blobs"][k]}
        assert changed <= set(T.map_keys())
        assert all(cur["source_blobs"][k] == pins[k] for k in changed)


def test_the_u1_discovery_list_names_this_successor_exactly_once_and_last():
    from tests import u1_scope as U
    assert tuple(m for m in U.RECONCILED_SUCCESSORS[-9:] if m not in ("tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope", "tests.ci_v4_p0_scope")) == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope")
    assert U.RECONCILED_SUCCESSORS.count("tests.ci_v4_lean_b1_scope") == 1


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
    tail = b"'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope')"
    for name, fn in (
        ("duplicate", lambda b: b.replace(tail, b"'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b1_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope')")),
        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", 'tests.fake_scope')")),
        ("swapped_c06_b1", lambda b: b.replace(tail, b"'tests.ci_v4_lean_b1_scope', 'tests.c06_cost_workspace_scope', 'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope')")),
        ("b1_missing", lambda b: b.replace(b", 'tests.ci_v4_lean_b1_scope'", b"")),
        ("c06_missing", lambda b: b.replace(b"'tests.c06_cost_workspace_scope', ", b"")),
        ("r04_removed", lambda b: b.replace(b"'tests.r04_ppa_scope', ", b"")),
        ("earlier_reordered", lambda b: b.replace(b"'tests.fin_v2_3_scope', 'tests.fin_v2_ci_scope'", b"'tests.fin_v2_ci_scope', 'tests.fin_v2_3_scope'")),
    ):
        ref = _variant(clone, {T.REGISTRY: fn})
        assert _g(clone, "diff", "--name-only", "HEAD", ref).decode().split() == [T.REGISTRY], name
        assert _rejected(clone, ref), name


def test_partially_applied_handoff_is_rejected(clone):
    old_pred = subprocess.check_output(["git", "show", T.BASE + ":" + T.PREDECESSOR], cwd=ROOT)       # C06 forward hook reverted
    assert _rejected(clone, _variant(clone, {T.PREDECESSOR: lambda b: old_pred}))
    old_reg = subprocess.check_output(["git", "show", T.BASE + ":" + T.REGISTRY], cwd=ROOT)           # registry reverted, B1 files remain
    assert _rejected(clone, _variant(clone, {T.REGISTRY: lambda b: old_reg}))
    old_u1 = subprocess.check_output(["git", "show", T.BASE + ":tests/u1_scope.py"], cwd=ROOT)         # discovery list reverted
    assert _rejected(clone, _variant(clone, {"tests/u1_scope.py": lambda b: old_u1}))


def test_forged_manifest_base_tree_pin_and_mode_are_rejected(clone):
    def edit(fn):
        def f(raw):
            d = json.loads(raw)
            fn(d)
            return (json.dumps(d, indent=2, sort_keys=True) + "\n").encode()
        return f
    forged = (edit(lambda d: d.__setitem__("base", "0" * 40)), edit(lambda d: d.__setitem__("base_tree", "0" * 40)),
              edit(lambda d: d["source_blobs"].__setitem__(README, "0" * 40)), edit(lambda d: d["base_blobs"].__setitem__(T.REGISTRY, "0" * 40)),
              edit(lambda d: d["source_modes"].__setitem__(REPORT, "100755")), edit(lambda d: d["base_modes"].__setitem__(T.REGISTRY, "100755")),
              edit(lambda d: d["source_blobs"].pop(MATRIX)), edit(lambda d: d.__setitem__("extra", 1)),
              edit(lambda d: d.__setitem__("authorization", "broader")), edit(lambda d: d.__setitem__("schema_version", "OTHER")),
              lambda b: b.rstrip(b"\n"), lambda b: b.replace(b"  ", b"   ", 1))                       # non-canonical bytes
    for fn in forged:
        assert _rejected(clone, _variant(clone, {T.MANIFEST: fn}))


def test_mode_symlink_deletion_and_unowned_paths_are_rejected(clone):
    assert _rejected(clone, _variant(clone, mode=REPORT))
    assert _rejected(clone, _variant(clone, symlink=MATRIX))
    assert _rejected(clone, _variant(clone, remove=(REPORT,)))
    for path in ("tools/ci_v4_lean_extra.py", ".github/workflows/lean_b1.yml", "app/lean_b1_extra.py", "docs/ci_v4/lean_b1/EXTRA.md", "tests/test_lean_unowned.py"):
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
    assert not T.signature_ok(clone, T.BASE) and not T.exact_blobs_ok(clone, T.BASE)              # accepted main carries no B1 manifest
    first = _g(clone, "rev-list", "--max-parents=0", "HEAD").decode().split()[0]
    assert not T.signature_ok(clone, first) and not T.exact_blobs_ok(clone, first)


def test_allowed_path_is_gated_by_the_cohort_signature_and_never_admits_foreign_paths(clone):
    for p in ("financial_engine/tax/engine.py", "app/v2/router.py", "tools/ci_v4_select.py", "docs/ci_v4/ci-v4-policy.json"):
        assert not T.allowed_path(p)
    assert T.allowed_path(REPORT) and T.allowed_path(MATRIX) and T.allowed_path(T.MANIFEST) and T.protected_blobs() == {}
    bad = _variant(clone, {T.MANIFEST: lambda b: b.replace(b'"base_tree": "d3c7bcf2', b'"base_tree": "03c7bcf2', 1)})
    assert not T.allowed_path(REPORT, clone, bad)                    # with a false signature even an owned path confers no authority


def test_supersession_is_pin_exact_and_cross_path_safe():
    pins = T.manifest()["source_blobs"]
    reg = T.effective_pins()[T.REGISTRY]
    assert K.supersedes(T.REGISTRY, reg) and P.supersedes(T.REGISTRY, reg)
    assert not K.supersedes(T.REGISTRY, "0" * 40)
    assert not K.supersedes(T.REGISTRY, pins[T.PREDECESSOR])         # a real blob pinned for another path
    assert not K.supersedes(T.REGISTRY, T.manifest()["base_blobs"][T.REGISTRY])      # the accepted C06-era registry blob is no longer current


def test_no_verdict_is_cached_across_refs_or_mutations(clone):
    bad = _variant(clone, {T.REGISTRY: lambda b: b.replace(b", 'tests.ci_v4_lean_b1_scope'", b"")})
    with T.scoped(), K.scoped():
        assert T.signature_ok(clone, "HEAD") and K.exact_blobs_ok(clone, "HEAD")
        assert not T.signature_ok(clone, bad) and not T.exact_blobs_ok(clone, bad)               # same process, same scope, other ref
    assert T.signature_ok(clone, "HEAD")                                                          # and the positive verdict was never poisoned
