"""CI V4 Lean B3 exact-source successor (after the accepted B2 cohort): positive identity and adversarial fail-closed controls.

Risk protected: B3 carries the WARN-ONLY test-admission report machinery inside the protected provenance graph (the scheduling weights are
NOT part of it: they stay FROZEN to the accepted-main bytes). It must own exactly its finite file set, change no CI control file, and every forged manifest, registry state, handoff, mode
or ref must be rejected. Every negative runs in an ISOLATED clone (a committed variant); the evaluated checkout is never edited and no verdict
is cached across mutations.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests import c06_cost_workspace_scope as K
from tests import ci_v4_lean_b1_scope as B1
from tests import ci_v4_lean_b2_scope as B
from tests import ci_v4_lean_b3_scope as T
from tests import fin_v2_cohorts as C
from tests import r04_ppa_scope as P

ROOT = Path(__file__).resolve().parents[1]
MODULE = "tests/ci_v4_lean_b3_scope.py"
OWN_TEST = "tests/test_ci_v4_lean_b3_scope.py"
WEIGHTS = "docs/ci_v4/module_weights.json"      # NOT B3-owned (Correction A revert); FROZEN-adjacent control file
REPORT = "tests/ci_v4_lean_report.py"


def _git(*args, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd).decode().strip()


@pytest.fixture(scope="module")
def clone(tmp_path_factory):
    root = tmp_path_factory.mktemp("b3-gov") / "repo"
    subprocess.check_call(["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(root)])
    subprocess.check_call(["git", "checkout", "-q", "--detach", _git("rev-parse", "HEAD")], cwd=root)
    return root


def _g(root, *args):
    return subprocess.check_output(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args], cwd=root)


def _variant(root, edits=None, mode=None, remove=(), symlink=None):
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
    with C.call_scope():
        return T.signature_ok(clone, "HEAD") and not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref)


# -------------------------------------------------------------------------------------------------------------- positive identity
def test_literal_closed_paths_and_immutable_predecessor_blobs():
    data = T.manifest()
    assert set(data["source_blobs"]) == T.OWNED_PATHS and set(data["base_blobs"]) == T.SUPERSEDED
    assert set(data["source_modes"]) == T.OWNED_PATHS and set(data["base_modes"]) == T.SUPERSEDED
    assert len(T.CURRENT_MAPS) == 8 and set(T.HANDOFFS) == T.HANDOFF_PATHS
    assert T.MAP_KEYS == ("tests/fin_v2_cohorts.py", "tests/u1_scope.py")
    assert T.PREDECESSOR == "tests/ci_v4_lean_b2_scope.py" and T.REGISTRY == "tests/fin_v2_cohorts.py"
    assert not any(p.startswith(T.FORBIDDEN) or "*" in p or ".." in p.split("/") or p.startswith("/") for p in T.OWNED_PATHS | {T.MANIFEST})
    for path in T.SUPERSEDED:
        assert data["base_blobs"][path] == _git("rev-parse", T.BASE + ":" + path)
    assert _git("rev-parse", T.BASE + "^{tree}") == T.BASE_TREE


def test_the_report_is_opt_in_and_the_scheduling_weights_stay_frozen():
    """The report machinery never gates; the scheduling weights are FROZEN like every other CI V4 control file (byte-equal to BASE)."""
    assert WEIGHTS in T.FROZEN and WEIGHTS not in T.HANDOFF_PATHS and WEIGHTS not in T.MAP_KEYS and WEIGHTS not in T.OWNED_PATHS
    assert REPORT in T.HANDOFF_PATHS
    assert not (T.OWNED_PATHS | {T.MANIFEST}) & set(T.FROZEN)
    assert not any(p.startswith((".github/", "tools/", "app/", "financial_engine/", "finco_core/", "domain/", "frontend/", "static/", "research/"))
                   for p in T.OWNED_PATHS | {T.MANIFEST})
    for path in T.FROZEN:
        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT), path
    assert {"tools/ci_v4_select.py", "docs/ci_v4/ci-v4-policy.json", ".github/workflows/ci_v4_pr.yml", "tools/ci_v4_aggregate.py",
            "tools/ci_v4_schedule.py", "docs/ci_v4/node_split_policy.json"} <= set(T.FROZEN)


def test_signature_exactness_and_reviewed_substitutions_hold(clone):
    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()
    N = T._next()
    for p in T.HANDOFFS:
        if N is not None and N.signature_ok() and p in N.HANDOFFS:      # the reviewed V5 bootstrap substitution of this shared path
            assert (ROOT / p).read_bytes() == N.expected_handoff(ROOT, p)
        else:
            assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)
        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]
    for ref in (None, "HEAD"):
        with C.call_scope():
            assert T.signature_ok(clone, ref) and T.exact_blobs_ok(clone, ref) and B.exact_blobs_ok(clone, ref) and C.valid(clone, ref)


def test_registered_exactly_once_after_b2_with_only_the_reviewed_v5_bootstrap_behind_it():
    assert C.COHORT_MODULES in (T.BASE_COHORTS + (T.__name__,), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR)) and C.COHORT_MODULES.count(T.__name__) == 1
    assert C.COHORT_MODULES[-3:] in (("tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope"),)
    assert B.SUCCESSOR == T.__name__ and B._next() is T and B1.SUCCESSOR == B.__name__ and B1._next() is B


def test_b2_b1_and_every_older_cohort_still_follow_the_chain():
    with C.call_scope():
        assert B.signature_ok() and B1.signature_ok() and K.signature_ok() and P.exact_blobs_ok() and all(m.exact_blobs_ok() for m in C.cohorts()) and C.valid()
        pin = T.effective_pins()[T.REGISTRY]
        assert B.supersedes(T.REGISTRY, pin) and K.supersedes(T.REGISTRY, pin) and B.effective_pins()[T.REGISTRY] == pin
        assert set(B.closure_paths()) >= set(T.closure_paths()) and set(K.closure_paths()) >= set(B.closure_paths())


def test_current_maps_move_only_their_registry_and_u1_keys():
    pins = T.effective_pins()
    for p in T.CURRENT_MAPS:
        old = json.loads(_git("show", T.BASE + ":" + p))
        cur = json.loads((ROOT / p).read_text())
        assert set(old) == set(cur) and all(old[k] == cur[k] for k in old if k != "source_blobs")
        changed = {k for k in old["source_blobs"] if old["source_blobs"][k] != cur["source_blobs"][k]}
        assert changed <= set(T.MAP_KEYS)
        assert all(cur["source_blobs"][k] == pins[k] for k in changed)


def test_the_weights_file_is_untouched_by_this_successor():
    d = json.loads((ROOT / WEIGHTS).read_text())
    old = json.loads(_git("show", T.BASE + ":" + WEIGHTS))
    assert d == old      # the data-only weights refresh was reverted (Correction A stop rule): B3 moves no weights byte


def test_the_u1_discovery_list_names_this_successor_exactly_once_and_then_only_the_v5_bootstrap():
    from tests import u1_scope as U
    assert U.RECONCILED_SUCCESSORS[-2:] == ("tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope")
    assert U.RECONCILED_SUCCESSORS.count("tests.ci_v4_lean_b3_scope") == 1


def test_the_admission_report_is_warn_only_and_exit_neutral():
    """The B3 machinery is opt-in and never gates: the report's exit-code policy is always 0 and every unknown stays UNKNOWN."""
    import json as _json
    src = (ROOT / REPORT).read_text(encoding="utf-8")
    assert "def test_admission_report(" in src and "exit_code_policy" in src
    assert "always 0: informational, never a gate" in src


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




def test_partially_applied_handoff_is_rejected(clone):
    old_pred = subprocess.check_output(["git", "show", T.BASE + ":" + T.PREDECESSOR], cwd=ROOT)       # B2 forward hook reverted
    assert _rejected(clone, _variant(clone, {T.PREDECESSOR: lambda b: old_pred}))
    old_reg = subprocess.check_output(["git", "show", T.BASE + ":" + T.REGISTRY], cwd=ROOT)           # registry reverted, B3 files remain
    assert _rejected(clone, _variant(clone, {T.REGISTRY: lambda b: old_reg}))
    old_u1 = subprocess.check_output(["git", "show", T.BASE + ":tests/u1_scope.py"], cwd=ROOT)         # discovery list reverted
    assert _rejected(clone, _variant(clone, {"tests/u1_scope.py": lambda b: old_u1}))
    old_report = subprocess.check_output(["git", "show", T.BASE + ":" + REPORT], cwd=ROOT)             # the B3 report machinery reverted
    assert _rejected(clone, _variant(clone, {REPORT: lambda b: old_report}))


def test_forged_manifest_base_tree_pin_and_mode_are_rejected(clone):
    def edit(fn):
        def f(raw):
            d = json.loads(raw)
            fn(d)
            return (json.dumps(d, indent=2, sort_keys=True) + "\n").encode()
        return f
    forged = (edit(lambda d: d.__setitem__("base", "0" * 40)), edit(lambda d: d.__setitem__("base_tree", "0" * 40)),
              edit(lambda d: d["source_blobs"].__setitem__(WEIGHTS, "0" * 40)), edit(lambda d: d["source_blobs"].__setitem__(REPORT, "0" * 40)),
              edit(lambda d: d["source_blobs"].__setitem__("tests/ci_v4_lean_b1_scope.py", "0" * 40)), edit(lambda d: d["source_blobs"].__setitem__("tests/c06_cost_workspace_scope.py", "0" * 40)),
              edit(lambda d: d["base_blobs"].__setitem__(T.REGISTRY, "0" * 40)),
              edit(lambda d: d["source_modes"].__setitem__(MODULE, "100755")), edit(lambda d: d["base_modes"].__setitem__(T.REGISTRY, "100755")),
              edit(lambda d: d["source_blobs"].pop(OWN_TEST)), edit(lambda d: d.__setitem__("extra", 1)),
              edit(lambda d: d.__setitem__("authorization", "broader")), edit(lambda d: d.__setitem__("schema_version", "OTHER")),
              lambda b: b.rstrip(b"\n"), lambda b: b.replace(b"  ", b"   ", 1))
    for fn in forged:
        assert _rejected(clone, _variant(clone, {T.MANIFEST: fn}))


def test_mode_symlink_deletion_and_unowned_paths_are_rejected(clone):
    assert _rejected(clone, _variant(clone, mode=MODULE))
    assert _rejected(clone, _variant(clone, symlink=OWN_TEST))
    assert _rejected(clone, _variant(clone, remove=(MODULE,)))
    for path in ("tools/ci_v4_lean_extra.py", ".github/workflows/lean_b3.yml", "app/lean_b3_extra.py", "docs/ci_v4/lean_b3/EXTRA.md", "tests/test_lean_b3_unowned.py"):
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
    assert not T.signature_ok(clone, T.BASE) and not T.exact_blobs_ok(clone, T.BASE)              # accepted main carries no B3 manifest
    first = _g(clone, "rev-list", "--max-parents=0", "HEAD").decode().split()[0]
    assert not T.signature_ok(clone, first) and not T.exact_blobs_ok(clone, first)


def test_allowed_path_is_gated_by_the_cohort_signature_and_never_admits_foreign_paths(clone):
    for p in ("financial_engine/tax/engine.py", "app/v2/router.py", "tools/ci_v4_select.py", "docs/ci_v4/ci-v4-policy.json"):
        assert not T.allowed_path(p)
    assert T.allowed_path(REPORT) and T.allowed_path(T.MANIFEST) and T.protected_blobs() == {}
    assert not T.allowed_path(WEIGHTS)      # weights are not B3-owned after the Correction A revert
    bad = _variant(clone, {T.MANIFEST: lambda b: b.replace(b'"base_tree": "d702f6c1', b'"base_tree": "0702f6c1', 1)})
    assert not T.allowed_path(WEIGHTS, clone, bad)                    # with a false signature even an owned path confers no authority


def test_supersession_is_pin_exact_and_cross_path_safe():
    pins = T.effective_pins()          # the CURRENT pins: the V5 bootstrap overlay wins for the paths it superseded
    reg = pins[T.REGISTRY]
    assert reg != T.manifest()["source_blobs"][T.REGISTRY]                                     # the B3-era registry pin is no longer current
    assert not B.supersedes(T.REGISTRY, T.manifest()["source_blobs"][T.REGISTRY])
    assert B.supersedes(T.REGISTRY, reg) and K.supersedes(T.REGISTRY, reg) and P.supersedes(T.REGISTRY, reg)
    assert not B.supersedes(T.REGISTRY, "0" * 40) and not K.supersedes(T.REGISTRY, "0" * 40)
    assert not B.supersedes(T.REGISTRY, pins[T.PREDECESSOR])         # a real blob pinned for another path
    weights_blob = _git("rev-parse", T.BASE + ":" + WEIGHTS)
    assert not B.supersedes(WEIGHTS, pins[T.REGISTRY]) and not B.supersedes(T.REGISTRY, weights_blob)
    assert not B.supersedes(T.REGISTRY, T.manifest()["base_blobs"][T.REGISTRY])      # the accepted B2-era registry blob is no longer current
    assert not B.supersedes(WEIGHTS, weights_blob)                                    # the frozen weights file is never a superseded path


def test_no_verdict_is_cached_across_refs_or_mutations(clone):
    bad = _variant(clone, {T.REGISTRY: lambda b: b.replace(b", 'tests.ci_v4_lean_b3_scope'", b"")})
    with T.scoped(), K.scoped():
        assert T.signature_ok(clone, "HEAD") and K.exact_blobs_ok(clone, "HEAD")
        assert not T.signature_ok(clone, bad) and not T.exact_blobs_ok(clone, bad)               # same process, same scope, other ref
    assert T.signature_ok(clone, "HEAD")                                                          # and the positive verdict was never poisoned


def test_the_registry_tail_is_one_finite_sequence_for_c06_b1_b2_b3_and_the_v5_bootstrap(monkeypatch):
    """C06 -> B1 -> B2 -> B3 -> V5_BOOTSTRAP is the ONLY accepted tail: any permutation, duplicate, extra cohort or reordered truncation fails the signature of every layer."""
    from tests import ci_v5_bootstrap_scope as V
    exact = C.COHORT_MODULES
    assert exact[-5:] == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope")
    layers = (K, B1, B, T, V)
    with C.call_scope():
        assert all(m.signature_ok() for m in layers)                       # state A: the pristine registry is accepted by every layer
    c06, b1, b2, b3, v5 = exact[-5:]
    head = exact[:-5]
    variants = {
        "b2_b3_swapped": head + (c06, b1, b3, b2, v5),
        "b1_b2_swapped": head + (c06, b2, b1, b3, v5),
        "b3_v5_swapped": head + (c06, b1, b2, v5, b3),
        "v5_duplicated": exact + (v5,),
        "b3_duplicated": exact + (b3,),
        "unknown_extra_cohort": exact + ("tests.not_a_reviewed_cohort",),
        "v5_before_c06": head + (v5, c06, b1, b2, b3),
        "c06_dropped": head + (b1, b2, b3, v5),
        "b3_dropped": head + (c06, b1, b2, v5),
    }
    for name, tail in variants.items():
        monkeypatch.setattr(C, "COHORT_MODULES", tail)
        for layer in layers:
            # a layer that is not itself in the sequence is not judged here; every layer present must refuse a tail it was not reviewed for
            if layer.__name__ in tail:
                assert not layer.signature_ok(), (name, layer.__name__)
    monkeypatch.setattr(C, "COHORT_MODULES", exact)
    with C.call_scope():
        assert all(m.signature_ok() for m in layers)                       # state A restored: accepted again
