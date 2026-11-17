"""CI V5 bootstrap exact-source successor (after the accepted B3 cohort): positive identity and adversarial fail-closed controls.

Risk protected: the CI V5 SHADOW foundation + B5 report enter the protected V4 provenance graph through ONE finite, terminal, one-time ownership
bridge. It must own exactly its finite file set (the nine PR files plus its own module and test), promote no epoch, change no CI V4 control file and
no product source, and every forged manifest, registry state, handoff, hook, mode, ref, delta or extra path must be rejected with the right layer
attributed. Every negative runs in an ISOLATED clone (a committed variant); the evaluated checkout is never edited and no verdict is cached across
mutations. This is NOT V5 activation: no V5 verdict gains authority here.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests import c06_cost_workspace_scope as K
from tests import ci_v4_lean_b1_scope as B1
from tests import ci_v4_lean_b2_scope as B2
from tests import ci_v4_lean_b3_scope as B3
from tests import ci_v5_bootstrap_scope as T
from tests import ci_v5_hardening_scope as H5
from tests import fin_v2_cohorts as C
from tests import r04_ppa_scope as P

ROOT = Path(__file__).resolve().parents[1]
MODULE = "tests/ci_v5_bootstrap_scope.py"
OWN_TEST = "tests/test_ci_v5_bootstrap_scope.py"
TRUST_ANCHOR = "docs/ci_v5/epoch.json"
CANDIDATE = "docs/ci_v5/epoch.candidate.json"
DELTA = "docs/ci_v5/delta.json"
SHADOW = ".github/workflows/ci_v5_shadow.yml"
PR_FILES = frozenset((".github/workflows/ci_v5_shadow.yml", "docs/ci_v5/README.md", "docs/ci_v5/delta.json", "docs/ci_v5/epoch.candidate.json",
                      "tests/test_ci_v5_foundation.py", "tools/ci_v5_b5.py", "tools/ci_v5_candidate.py", "tools/ci_v5_epoch.py", "tools/ci_v5_shadow.py"))


def _git(*args, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd).decode().strip()


@pytest.fixture(scope="module")
def clone(tmp_path_factory):
    root = tmp_path_factory.mktemp("v5b-gov") / "repo"
    subprocess.check_call(["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(root)])
    subprocess.check_call(["git", "checkout", "-q", "--detach", _git("rev-parse", "HEAD")], cwd=root)
    return root


def _g(root, *args):
    return subprocess.check_output(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args], cwd=root)


def _variant(root, edits=None, mode=None, remove=(), symlink=None, rename=None, add=None):
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
        if rename:
            (root / rename[1]).parent.mkdir(parents=True, exist_ok=True)
            (root / rename[0]).rename(root / rename[1])
        for path in add or ():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_text("x = 1\n")
        _g(root, "add", "-A")
        if mode:
            _g(root, "update-index", "--chmod=+x", mode)
        _g(root, "commit", "-q", "--allow-empty", "-m", "variant")
        return _g(root, "rev-parse", "HEAD").decode().strip()
    finally:
        _g(root, "checkout", "-q", "-f", base)
        _g(root, "clean", "-fdxq")


def _rejected(clone, ref):
    """Rejected by the bridge's own exactness AND by the composite (the V4 verdict that gates the PR)."""
    with C.call_scope():
        return not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref)


def _rejected_by_signature(clone, ref):
    with C.call_scope():
        return not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref)


def _rejected_by_closure(clone, ref):
    """An unowned path leaves the source signature intact; the full closure (changed-set) and the composite reject it."""
    with C.call_scope():
        return T.signature_ok(clone, "HEAD") and not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref)


# -------------------------------------------------------------------------------------------------------------- positive identity
def test_literal_closed_paths_and_immutable_predecessor_blobs():
    data = T.manifest()
    assert set(data["source_blobs"]) == T.OWNED_PATHS and set(data["base_blobs"]) == T.SUPERSEDED
    assert set(data["source_modes"]) == T.OWNED_PATHS and set(data["base_modes"]) == T.SUPERSEDED
    assert len(T.CURRENT_MAPS) == 8 and set(T.HANDOFFS) == T.HANDOFF_PATHS
    assert T.MAP_KEYS == ("tests/fin_v2_cohorts.py", "tests/u1_scope.py")
    assert T.PREDECESSOR == "tests/ci_v4_lean_b3_scope.py" and T.REGISTRY == "tests/fin_v2_cohorts.py"
    assert not any(p.startswith(T.FORBIDDEN) or "*" in p or ".." in p.split("/") or p.startswith("/") for p in T.OWNED_PATHS | {T.MANIFEST})
    for path in T.SUPERSEDED:
        assert data["base_blobs"][path] == _git("rev-parse", T.BASE + ":" + path)
    assert _git("rev-parse", T.BASE + "^{tree}") == T.BASE_TREE


def test_only_the_literal_pr_files_enter_tools_and_github_and_nothing_else_is_widened():
    """``tools/`` and ``.github/`` are admitted ONLY as the literal NEW paths; no handoff, prefix or pattern reaches them."""
    owned = T.OWNED_PATHS | {T.MANIFEST}
    assert {p for p in owned if p.startswith(T.NEW_ONLY_PREFIXES)} == {p for p in PR_FILES if p.startswith(T.NEW_ONLY_PREFIXES)}
    assert not {p for p in T.HANDOFF_PATHS | T.CURRENT_MAPS if p.startswith(T.NEW_ONLY_PREFIXES)}
    assert T.NEW == PR_FILES | {MODULE, OWN_TEST}
    assert not any(p.startswith(("financial_engine/", "finco_core/", "domain/", "app/", "frontend/", "static/", "research/")) for p in owned)


def test_no_v5_authority_no_epoch_promotion_and_every_v4_control_file_stays_byte_equal():
    """The bridge is not activation: the trust anchor is never owned or present; the V4 selector / policy / schedule / required workflows / weights are frozen."""
    assert TRUST_ANCHOR not in T.OWNED_PATHS | {T.MANIFEST} and not (ROOT / TRUST_ANCHOR).exists()
    assert CANDIDATE in T.NEW and (ROOT / CANDIDATE).exists()
    assert SHADOW in T.NEW and SHADOW not in T.FROZEN                         # the ONE new workflow is non-required; no second workflow is owned
    assert len([p for p in T.NEW if p.startswith(".github/workflows/")]) == 1
    assert not (T.OWNED_PATHS | {T.MANIFEST}) & set(T.FROZEN)
    for path in T.FROZEN:
        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT), path
    assert {"tools/ci_v4_select.py", "docs/ci_v4/ci-v4-policy.json", ".github/workflows/ci_v4_pr.yml", "tools/ci_v4_aggregate.py", "tools/ci_v4_schedule.py",
            "docs/ci_v4/module_weights.json", "docs/ci_v4/node_split_policy.json", "tools/ci_v4_governance_gate.py"} <= set(T.FROZEN)
    assert "CANDIDATE_UNTRUSTED" in (ROOT / "docs/ci_v5/README.md").read_text(encoding="utf-8")


def test_signature_exactness_and_reviewed_substitutions_hold(clone):
    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()
    from tests import ci_v4_full_recovery_scope as FR
    from tests import ci_v5_gate_scope as G6
    for p in T.HANDOFFS:
        from tests import ci_v4_p0_scope as P0
        if P0.signature_ok() and p in P0.HANDOFFS:
            assert (ROOT / p).read_bytes() == P0.expected_handoff(ROOT, p)
            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]
            continue
        if FR.signature_ok() and p in FR.HANDOFFS:                       # the reviewed FULL-recovery successor substitutes the final state of this shared path (literal, pin-exact)
            assert (ROOT / p).read_bytes() == FR.expected_handoff(ROOT, p)
        elif G6.signature_ok() and p in G6.HANDOFFS:                       # the reviewed V5-3 successor substitutes the final state of this shared path (literal, pin-exact)
            assert (ROOT / p).read_bytes() == G6.expected_handoff(ROOT, p)
        elif H5.signature_ok() and p in H5.HANDOFFS:                     # the reviewed V5-2B successor further substitutes this shared path (literal, pin-exact)
            assert (ROOT / p).read_bytes() == H5.expected_handoff(ROOT, p)
        else:
            assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)
        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]
    for ref in (None, "HEAD"):
        with C.call_scope():
            assert T.signature_ok(clone, ref) and T.exact_blobs_ok(clone, ref) and B3.exact_blobs_ok(clone, ref) and C.valid(clone, ref)


def test_registered_exactly_once_after_b3_with_only_the_reviewed_v5_2b_behind_it():
    assert C.COHORT_MODULES in (T.BASE_COHORTS + (T.__name__,), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, "tests.ci_v5_gate_scope"), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope"), T.BASE_COHORTS + (T.__name__, T.SUCCESSOR, "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope") + ('tests.ci_v4_p0_scope',)) and C.COHORT_MODULES.count(T.__name__) == 1
    assert len(C.COHORT_MODULES) == len(T.BASE_COHORTS) + 4                       # exactly the reviewed V5-2B and V5-3 modules gained after the bootstrap; no hardcoded total
    assert C.COHORT_MODULES[-5:] == ("tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope")
    assert T._next() is H5 and T.SUCCESSOR == H5.__name__
    assert B3.SUCCESSOR == T.__name__ and B3._next() is T and B2.SUCCESSOR == B3.__name__ and B2._next() is B3
    assert B1.SUCCESSOR == B2.__name__ and B1._next() is B2 and K.SUCCESSOR == B1.__name__ and K._next() is B1


def test_the_chain_c06_b1_b2_b3_v5_verifies_through_each_real_verifier():
    with C.call_scope():
        assert K.signature_ok() and B1.signature_ok() and B2.signature_ok() and B3.signature_ok() and T.signature_ok()
        assert P.exact_blobs_ok() and all(m.exact_blobs_ok() for m in C.cohorts()) and C.valid()
        pin = T.effective_pins()[T.REGISTRY]
        for layer in (B3, B2, B1, K):
            assert layer.supersedes(T.REGISTRY, pin), layer.__name__
        assert B3.effective_pins()[T.REGISTRY] == pin and B2.effective_pins()[T.REGISTRY] == pin
        assert set(B3.closure_paths()) >= set(T.closure_paths()) and set(B2.closure_paths()) >= set(B3.closure_paths())
        assert set(B1.closure_paths()) >= set(B2.closure_paths()) and set(K.closure_paths()) >= set(B1.closure_paths())


def test_current_maps_move_only_their_registry_and_u1_keys():
    pins = T.effective_pins()
    for p in T.CURRENT_MAPS:
        old = json.loads(_git("show", T.BASE + ":" + p))
        cur = json.loads((ROOT / p).read_text())
        assert set(old) == set(cur) and all(old[k] == cur[k] for k in old if k != "source_blobs")
        changed = {k for k in old["source_blobs"] if old["source_blobs"][k] != cur["source_blobs"][k]}
        assert changed <= set(T.MAP_KEYS)
        assert all(cur["source_blobs"][k] == pins[k] for k in changed)


def test_the_u1_discovery_list_names_this_successor_exactly_once_and_then_only_v5_2b():
    from tests import u1_scope as U
    assert U.RECONCILED_SUCCESSORS[-4:] == ("tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope") and U.RECONCILED_SUCCESSORS.count("tests.ci_v5_bootstrap_scope") == 1


# -------------------------------------------------------------------------------------------------------------- tamper (committed refs)
@pytest.mark.parametrize("path", sorted((T.OWNED_PATHS | {T.MANIFEST}) - T.CURRENT_MAPS))
def test_one_byte_in_any_owned_committed_blob_is_rejected(clone, path):
    assert _rejected_by_signature(clone, _variant(clone, {path: lambda b: b + b"\n"})), path


@pytest.mark.parametrize("path", sorted(T.CURRENT_MAPS))
def test_current_map_tamper_is_rejected_by_the_full_closure(clone, path):
    assert _rejected_by_closure(clone, _variant(clone, {path: lambda b: b + b"\n"})), path


def test_a_changed_current_map_pin_is_rejected(clone):
    """One moved key forged to a plausible but wrong blob in a current map (the shared registry pin) is rejected by the closure."""
    path = "docs/ci_v4/SOURCE_SUCCESSOR.json"

    def forge(raw):
        d = json.loads(raw)
        d["source_blobs"][T.MAP_KEYS[0]] = d["source_blobs"][T.MAP_KEYS[1]]
        return (json.dumps(d, sort_keys=True, indent=2) + "\n").encode()
    assert _rejected_by_closure(clone, _variant(clone, {path: forge}))


@pytest.mark.parametrize("path", sorted(T.FROZEN))
def test_every_ci_v4_control_file_must_stay_byte_identical_to_the_accepted_base(clone, path):
    assert _rejected_by_signature(clone, _variant(clone, {path: lambda b: b + b"\n"})), path


def test_registry_mutations_are_rejected(clone):
    tail = b"'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope')"
    for name, fn in (
        ("duplicate_v5", lambda b: b.replace(tail, b"'tests.ci_v4_lean_b2_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope')")),
        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", 'tests.fake_scope')")),
        ("swapped_b3_v5", lambda b: b.replace(tail, b"'tests.ci_v4_lean_b2_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope')")),
        ("v5_2b_missing", lambda b: b.replace(b", 'tests.ci_v5_hardening_scope'", b"")),
        ("v5_3_missing", lambda b: b.replace(b", 'tests.ci_v5_gate_scope'", b"")),
        ("fr_missing", lambda b: b.replace(b", 'tests.ci_v4_full_recovery_scope'", b"")),
        ("v5_missing", lambda b: b.replace(b", 'tests.ci_v5_bootstrap_scope'", b"")),
        ("b3_missing", lambda b: b.replace(b", 'tests.ci_v4_lean_b3_scope'", b"")),
        ("b2_missing", lambda b: b.replace(b", 'tests.ci_v4_lean_b2_scope'", b"")),
        ("r04_removed", lambda b: b.replace(b"'tests.r04_ppa_scope', ", b"")),
        ("earlier_reordered", lambda b: b.replace(b"'tests.fin_v2_3_scope', 'tests.fin_v2_ci_scope'", b"'tests.fin_v2_ci_scope', 'tests.fin_v2_3_scope'")),
    ):
        ref = _variant(clone, {T.REGISTRY: fn})
        assert _g(clone, "diff", "--name-only", "HEAD", ref).decode().split() == [T.REGISTRY], name        # the ONLY difference is the registry
        assert _rejected(clone, ref), name


def test_partially_applied_handoff_is_rejected(clone):
    """Each shared governance handoff reverted alone (the other files keep their bridge bytes) leaves an inconsistent state that is rejected."""
    for path in (T.PREDECESSOR, T.REGISTRY, "tests/u1_scope.py", "tests/ci_v4_lean_b2_scope.py", "tests/ci_v4_lean_b1_scope.py", "tests/c06_cost_workspace_scope.py"):
        old = subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT)
        assert _rejected(clone, _variant(clone, {path: lambda b, old=old: old})), path


def test_a_compromised_b3_forward_hook_is_rejected(clone):
    """The B3 hook is the only link from B3 to this cohort: renaming its successor, or removing the overlay, must fail the chain."""
    assert B3.SUCCESSOR == "tests.ci_v5_bootstrap_scope"
    for fn in (lambda b: b.replace(b"SUCCESSOR = 'tests.ci_v5_bootstrap_scope'", b"SUCCESSOR = 'tests.ci_v5_other_scope'"),
               lambda b: b.replace(b"pins.update(_next_pins(root, ref))", b"pass"),
               lambda b: b.replace(b"return N.reviewed_edits_ok(root, ref) if nxt else True", b"return True")):
        ref = _variant(clone, {T.PREDECESSOR: fn})
        assert _g(clone, "diff", "--name-only", "HEAD", ref).decode().split() == [T.PREDECESSOR]
        assert _rejected(clone, ref)


def test_forged_manifest_base_tree_pin_and_mode_are_rejected(clone):
    def edit(fn):
        def f(raw):
            d = json.loads(raw)
            fn(d)
            return (json.dumps(d, indent=2, sort_keys=True) + "\n").encode()
        return f
    forged = (edit(lambda d: d.__setitem__("base", "0" * 40)), edit(lambda d: d.__setitem__("base_tree", "0" * 40)),
              edit(lambda d: d["source_blobs"].__setitem__(CANDIDATE, "0" * 40)),      # DELTA and SHADOW are further pinned (and judged) by the V5-2B successor: their bootstrap-era pins are shadowed
              edit(lambda d: d["source_blobs"].__setitem__(T.PREDECESSOR, "0" * 40)),
              edit(lambda d: d["base_blobs"].__setitem__(T.REGISTRY, "0" * 40)),
              edit(lambda d: d["source_modes"].__setitem__(MODULE, "100755")), edit(lambda d: d["base_modes"].__setitem__(T.REGISTRY, "100755")),
              edit(lambda d: d["source_blobs"].pop(OWN_TEST)), edit(lambda d: d["source_blobs"].__setitem__(TRUST_ANCHOR, "1" * 40)),
              edit(lambda d: d.__setitem__("extra", 1)), edit(lambda d: d.__setitem__("authorization", "broader")),
              edit(lambda d: d.__setitem__("schema_version", "OTHER")), lambda b: b.rstrip(b"\n"), lambda b: b.replace(b"  ", b"   ", 1))
    for fn in forged:
        assert _rejected(clone, _variant(clone, {T.MANIFEST: fn}))


def test_mode_symlink_deletion_rename_and_owned_file_removal_are_rejected(clone):
    assert _rejected(clone, _variant(clone, mode=MODULE))                              # executable bit on the cohort module
    assert _rejected(clone, _variant(clone, mode="tools/ci_v5_epoch.py"))              # executable bit on an owned PR file
    assert _rejected(clone, _variant(clone, symlink=OWN_TEST))                         # symlink replacing an owned file
    assert _rejected(clone, _variant(clone, symlink="tools/ci_v5_shadow.py"))
    assert _rejected(clone, _variant(clone, remove=(MODULE,)))                         # removed cohort module
    assert _rejected(clone, _variant(clone, remove=("tools/ci_v5_b5.py",)))            # removed owned PR file
    assert _rejected(clone, _variant(clone, remove=(DELTA,)))                          # removed delta
    assert _rejected(clone, _variant(clone, rename=("docs/ci_v5/README.md", "docs/ci_v5/README_RENAMED.md")))   # renamed owned file
    assert _rejected(clone, _variant(clone, rename=(CANDIDATE, "docs/ci_v5/epoch.json")))                       # promotion of the candidate to the trust anchor


def test_added_or_unowned_paths_are_rejected_and_the_trust_anchor_is_never_admitted(clone):
    for path in ("tools/ci_v5_extra.py", ".github/workflows/ci_v5_extra.yml", TRUST_ANCHOR, "docs/ci_v5/bootstrap/EXTRA.md", "app/ci_v5_extra.py",
                 "tests/test_ci_v5_unowned.py", "tools/ci_v4_extra.py"):
        ref = _variant(clone, add=(path,))
        assert _rejected_by_closure(clone, ref), path
    assert not T.allowed_path(TRUST_ANCHOR) and not T.allowed_path("tools/ci_v5_extra.py") and not T.allowed_path(".github/workflows/ci_v5_extra.yml")


def test_an_incorrect_delta_or_candidate_is_rejected(clone):
    def drop_one(raw):
        d = json.loads(raw)
        d["changes"].pop()
        return (json.dumps(d, indent=1, sort_keys=True) + "\n").encode()
    assert _rejected_by_signature(clone, _variant(clone, {DELTA: drop_one}))                     # delta missing one protected change
    assert _rejected_by_signature(clone, _variant(clone, {DELTA: lambda b: b.replace(b'"op": "add"', b'"op": "modify"', 1)}))
    assert _rejected_by_signature(clone, _variant(clone, {CANDIDATE: lambda b: b.replace(b'"entries": [', b'"entries": [\n  "100644 ' + b"0" * 40 + b'\\ttests/x.py",', 1)}))


def test_wrong_ancestor_and_older_refs_are_rejected(clone):
    assert not T.signature_ok(clone, T.BASE) and not T.exact_blobs_ok(clone, T.BASE)              # accepted main carries no V5 bootstrap manifest
    first = _g(clone, "rev-list", "--max-parents=0", "HEAD").decode().split()[0]
    assert not T.signature_ok(clone, first) and not T.exact_blobs_ok(clone, first)
    assert not T.signature_ok(clone, "0" * 40) and not T.signature_ok(clone, "refs/heads/does-not-exist") and not T.exact_blobs_ok(clone, "not-a-ref")


def test_an_untracked_file_in_the_worktree_is_rejected_and_the_state_restores(clone):
    """A/B/A on the WORKTREE mode: pristine A exact; an untracked file B rejected; restored A' exact again (no verdict leaks)."""
    with C.call_scope():
        assert T.exact_blobs_ok(clone, None)
    stray = clone / "tools" / "ci_v5_untracked_stray.py"
    stray.write_text("x = 1\n")
    try:
        with C.call_scope():
            assert not T.exact_blobs_ok(clone, None) and T.signature_ok(clone, None)
    finally:
        stray.unlink()
    with C.call_scope():
        assert T.exact_blobs_ok(clone, None)


def test_allowed_path_is_gated_by_the_cohort_signature_and_never_admits_foreign_paths(clone):
    for p in ("financial_engine/tax/engine.py", "app/v2/router.py", "tools/ci_v4_select.py", "docs/ci_v4/ci-v4-policy.json", "docs/ci_v5/epoch.json"):
        assert not T.allowed_path(p)
    assert T.allowed_path(DELTA) and T.allowed_path(T.MANIFEST) and T.protected_blobs() == {}
    bad = _variant(clone, {T.MANIFEST: lambda b: b.replace(b'"base_tree": "a66f9799', b'"base_tree": "066f9799', 1)})
    assert not T.allowed_path(DELTA, clone, bad)                       # with a false signature even an owned path confers no authority


def test_supersession_is_pin_exact_and_cross_path_safe():
    pins = T.manifest()["source_blobs"]
    reg = T.effective_pins()[T.REGISTRY]                                             # the CURRENT pin: the V5-2B overlay wins for the registry it superseded
    assert reg != pins[T.REGISTRY] and not B3.supersedes(T.REGISTRY, pins[T.REGISTRY])   # the bootstrap-era registry pin is no longer current
    assert B3.supersedes(T.REGISTRY, reg) and B2.supersedes(T.REGISTRY, reg) and K.supersedes(T.REGISTRY, reg) and P.supersedes(T.REGISTRY, reg)
    assert not B3.supersedes(T.REGISTRY, "0" * 40) and not K.supersedes(T.REGISTRY, "0" * 40)
    assert not B3.supersedes(T.REGISTRY, pins[T.PREDECESSOR])                       # a real blob pinned for another path
    assert not B3.supersedes(T.REGISTRY, T.manifest()["base_blobs"][T.REGISTRY])    # the accepted B3-era registry blob is no longer current
    weights = _git("rev-parse", T.BASE + ":docs/ci_v4/module_weights.json")
    assert not B3.supersedes("docs/ci_v4/module_weights.json", weights)             # the frozen weights file is never a superseded path


def test_no_verdict_is_cached_across_refs_or_mutations(clone):
    bad = _variant(clone, {T.REGISTRY: lambda b: b.replace(b", 'tests.ci_v5_bootstrap_scope'", b"")})
    with T.scoped(), B3.scoped(), K.scoped():
        assert T.signature_ok(clone, "HEAD") and B3.exact_blobs_ok(clone, "HEAD")
        assert not T.signature_ok(clone, bad) and not T.exact_blobs_ok(clone, bad)               # same process, same scope, other ref
        assert T.signature_ok(clone, "HEAD")                                                      # and back: the positive verdict was never poisoned
    assert T.signature_ok(clone, "HEAD") and not T.signature_ok(clone, bad)


def test_the_registry_tail_is_one_finite_sequence_and_full_recovery_is_terminal(monkeypatch):
    """C06 -> B1 -> B2 -> B3 -> V5_BOOTSTRAP -> V5_2B -> V5_3 -> FULL_RECOVERY is the ONLY accepted tail: any permutation, duplicate, extra cohort or truncation fails every layer present."""
    from tests import ci_v4_full_recovery_scope as FR
    from tests import ci_v5_gate_scope as G6
    exact = C.COHORT_MODULES
    assert exact[-8:] == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope", "tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope")
    layers = (K, B1, B2, B3, T, H5, G6, FR)
    with C.call_scope():
        assert all(m.signature_ok() for m in layers)
    c06, b1, b2, b3, v5, h5, g6, fr = exact[-8:]
    head = exact[:-8]
    variants = {"b2_b3_swapped": head + (c06, b1, b3, b2, v5, h5, g6, fr), "b1_b2_swapped": head + (c06, b2, b1, b3, v5, h5, g6, fr), "b3_v5_swapped": head + (c06, b1, b2, v5, b3, h5, g6, fr),
                "v5_h5_swapped": head + (c06, b1, b2, b3, h5, v5, g6, fr), "h5_g6_swapped": head + (c06, b1, b2, b3, v5, g6, h5, fr), "g6_duplicated": exact + (g6,), "v5_duplicated": head + (c06, b1, b2, b3, v5, v5, h5, g6, fr),
                "fr_duplicated": exact + (fr,), "g6_fr_swapped": head + (c06, b1, b2, b3, v5, h5, fr, g6), "fr_dropped": head + (c06, b1, b2, b3, v5, h5, g6), "unknown_extra_cohort": exact + ("tests.not_a_reviewed_cohort",), "g6_before_c06": head + (g6, c06, b1, b2, b3, v5, h5, fr),
                "c06_dropped": head + (b1, b2, b3, v5, h5, g6, fr), "b3_dropped": head + (c06, b1, b2, v5, h5, g6, fr), "b1_dropped": head + (c06, b2, b3, v5, h5, g6, fr), "v5_dropped": head + (c06, b1, b2, b3, h5, g6, fr), "h5_dropped": head + (c06, b1, b2, b3, v5, g6, fr)}
    for name, tail in variants.items():
        monkeypatch.setattr(C, "COHORT_MODULES", tail)
        for layer in layers:
            if layer.__name__ in tail:
                assert not layer.signature_ok(), (name, layer.__name__)
    monkeypatch.setattr(C, "COHORT_MODULES", exact)
    with C.call_scope():
        assert all(m.signature_ok() for m in layers)                       # state A restored: accepted again
