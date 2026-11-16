"""CI V5-3 gate exact-source successor (after the V5-2B cohort): positive identity and adversarial fail-closed controls.

Risk protected: the V5-2C trust checkpoint and the V5-3 gate enter the protected V4 provenance graph through ONE finite, terminal ownership successor. It must own exactly
its finite file set (five new files, eight REPLACED V5 files, the literal shared-governance handoffs and the eight current maps), promote no epoch, change no
CI V4 control file and no product source, and every forged manifest, registry state, handoff, hook, mode, ref, delta or extra path must be rejected with the
right layer attributed. Every negative runs in an ISOLATED clone (a committed variant); the evaluated checkout is never edited and no verdict is cached across
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
from tests import ci_v5_bootstrap_scope as V5
from tests import ci_v4_full_recovery_scope as T
from tests import ci_v5_gate_scope as H5
from tests import ci_v5_hardening_scope as H4
from tests import fin_v2_cohorts as C
from tests import r04_ppa_scope as P

ROOT = Path(__file__).resolve().parents[1]
MODULE = "tests/ci_v4_full_recovery_scope.py"
OWN_TEST = "tests/test_ci_v4_full_recovery_scope.py"
TRUST_ANCHOR = "docs/ci_v5/epoch.json"
DELTA = "docs/ci_v5/delta.json"
SHADOW = ".github/workflows/ci_v5_shadow.yml"
NEW_FILES = frozenset((MODULE, OWN_TEST, "docs/ci_v5/full_recovery/FULL_RECOVERY_REPORT.md"))
REPLACED_FILES = frozenset(("docs/ci_v5/delta.json", "tests/test_ci_v3_outcome_reconciliation.py", "tests/fin_truth_b1/test_source_successor.py"))


def _git(*args, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd).decode().strip()


@pytest.fixture(scope="module")
def clone(tmp_path_factory):
    root = tmp_path_factory.mktemp("v5g-gov") / "repo"
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
    """Rejected by the cohort's own exactness AND by the composite (the V4 verdict that gates the PR)."""
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
    assert T.NEW == NEW_FILES and T.REPLACED == REPLACED_FILES and len(T.CURRENT_MAPS) == 8 and set(T.HANDOFFS) == T.HANDOFF_PATHS
    assert not T.NEW & T.SUPERSEDED and not T.REPLACED & T.HANDOFF_PATHS
    assert T.MAP_KEYS == ("tests/fin_v2_cohorts.py", "tests/u1_scope.py")
    assert T.PREDECESSOR == "tests/ci_v5_gate_scope.py" and T.REGISTRY == "tests/fin_v2_cohorts.py"
    assert not any(p.startswith(T.FORBIDDEN) or "*" in p or ".." in p.split("/") or p.startswith("/") for p in T.OWNED_PATHS | {T.MANIFEST})
    for path in T.SUPERSEDED:
        assert data["base_blobs"][path] == _git("rev-parse", T.BASE + ":" + path)
    assert _git("rev-parse", T.BASE + "^{tree}") == T.BASE_TREE


def test_tools_and_github_are_admitted_only_as_literal_bootstrap_ci_paths_and_no_new_ci_path_exists():
    owned = T.OWNED_PATHS | {T.MANIFEST}
    assert {p for p in owned if p.startswith(T.NEW_ONLY_PREFIXES)} == set(T.CI_PATHS) and set(T.CI_PATHS) - {".github/workflows/ci_v5_gate.yml"} <= set(V5.CI_PATHS)   # the ONE new CI path is the separate pull_request_target gate workflow
    assert T.CI_PATHS <= T.NEW | T.REPLACED and not {p for p in T.HANDOFF_PATHS | T.CURRENT_MAPS if p.startswith(T.NEW_ONLY_PREFIXES)}
    assert not any(p.startswith(("financial_engine/", "finco_core/", "domain/", "app/", "frontend/", "static/", "research/")) for p in owned)
    assert not [p for p in owned if p.startswith((".github/", "tools/"))] and not T.CI_PATHS      # this cohort touches no CI path at all


def test_no_v5_authority_no_epoch_promotion_and_every_v4_control_file_stays_byte_equal():
    assert TRUST_ANCHOR not in T.OWNED_PATHS | {T.MANIFEST} and not (ROOT / TRUST_ANCHOR).exists()
    assert SHADOW not in T.OWNED_PATHS and SHADOW not in T.FROZEN      # the shadow workflow is unchanged by this PR
    assert not (T.OWNED_PATHS | {T.MANIFEST}) & set(T.FROZEN)
    for path in T.FROZEN:
        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT), path
    assert {"tools/ci_v4_select.py", "docs/ci_v4/ci-v4-policy.json", ".github/workflows/ci_v4_pr.yml", "tools/ci_v4_aggregate.py", "tools/ci_v4_schedule.py",
            "docs/ci_v4/module_weights.json", "docs/ci_v4/node_split_policy.json", "tools/ci_v4_governance_gate.py"} <= set(T.FROZEN)
    text = (ROOT / "docs/ci_v5/README.md").read_text(encoding="utf-8")
    assert "SHADOW LANE STAYS OBSERVATIONAL" in text and "PROMOTION_REQUIRES_OWNER" in text and "FULL_PROVENANCE_BLOCKED" in text and "ACTIVATION_PREPARED_NOT_VERIFIED" in text


def test_signature_exactness_and_reviewed_substitutions_hold(clone):
    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()
    for p in T.HANDOFFS:
        assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)
        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]
    for p in T.REPLACED:
        assert T._blob((ROOT / p).read_bytes()) == T.manifest()["source_blobs"][p]
    for ref in (None, "HEAD"):
        with C.call_scope():
            assert T.signature_ok(clone, ref) and T.exact_blobs_ok(clone, ref) and V5.exact_blobs_ok(clone, ref) and C.valid(clone, ref)


def test_registered_exactly_once_as_the_terminal_cohort_after_the_v5_3_gate():
    assert C.COHORT_MODULES == T.BASE_COHORTS + (T.__name__,) and C.COHORT_MODULES.count(T.__name__) == 1
    assert len(C.COHORT_MODULES) == len(T.BASE_COHORTS) + 1                       # exactly ONE module gained; no hardcoded total
    assert C.COHORT_MODULES[-2:] == ("tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope")
    assert H5.SUCCESSOR == T.__name__ and H5._next() is T and H4.SUCCESSOR == H5.__name__ and H4._next() is H5 and V5.SUCCESSOR == H4.__name__ and V5._next() is H4 and B3.SUCCESSOR == V5.__name__ and B3._next() is V5
    assert B2.SUCCESSOR == B3.__name__ and B2._next() is B3 and B1.SUCCESSOR == B2.__name__ and B1._next() is B2 and K.SUCCESSOR == B1.__name__ and K._next() is B1


def test_the_chain_c06_b1_b2_b3_v5_v5_2b_verifies_through_each_real_verifier():
    with C.call_scope():
        assert K.signature_ok() and B1.signature_ok() and B2.signature_ok() and B3.signature_ok() and V5.signature_ok() and H4.signature_ok() and H5.signature_ok() and T.signature_ok()
        assert P.exact_blobs_ok() and all(m.exact_blobs_ok() for m in C.cohorts()) and C.valid()
        pin = T.effective_pins()[T.REGISTRY]
        for layer in (H5, H4, V5, B3, B2, B1, K):
            assert layer.supersedes(T.REGISTRY, pin), layer.__name__
        assert H5.effective_pins()[T.REGISTRY] == pin and H4.effective_pins()[T.REGISTRY] == pin and V5.effective_pins()[T.REGISTRY] == pin and B3.effective_pins()[T.REGISTRY] == pin and B2.effective_pins()[T.REGISTRY] == pin
        assert set(H5.closure_paths()) >= set(T.closure_paths()) and set(H4.closure_paths()) >= set(H5.closure_paths()) and set(V5.closure_paths()) >= set(H4.closure_paths()) and set(B3.closure_paths()) >= set(V5.closure_paths())
        assert set(B2.closure_paths()) >= set(B3.closure_paths()) and set(B1.closure_paths()) >= set(B2.closure_paths()) and set(K.closure_paths()) >= set(B1.closure_paths())


def test_current_maps_move_only_their_registry_and_u1_keys():
    pins = T.effective_pins()
    for p in T.CURRENT_MAPS:
        old = json.loads(_git("show", T.BASE + ":" + p))
        cur = json.loads((ROOT / p).read_text())
        assert set(old) == set(cur) and all(old[k] == cur[k] for k in old if k != "source_blobs")
        changed = {k for k in old["source_blobs"] if old["source_blobs"][k] != cur["source_blobs"][k]}
        assert changed <= set(T.MAP_KEYS)
        assert all(cur["source_blobs"][k] == pins[k] for k in changed)


def test_the_u1_discovery_list_names_this_successor_exactly_once_and_last():
    from tests import u1_scope as U
    assert U.RECONCILED_SUCCESSORS[-1] == "tests.ci_v4_full_recovery_scope" and U.RECONCILED_SUCCESSORS.count("tests.ci_v4_full_recovery_scope") == 1


# -------------------------------------------------------------------------------------------------------------- tamper (committed refs)
@pytest.mark.parametrize("path", sorted((T.OWNED_PATHS | {T.MANIFEST}) - T.CURRENT_MAPS))
def test_one_byte_in_any_owned_committed_blob_is_rejected(clone, path):
    assert _rejected_by_signature(clone, _variant(clone, {path: lambda b: b + b"\n"})), path


@pytest.mark.parametrize("path", sorted(T.CURRENT_MAPS))
def test_current_map_tamper_is_rejected_by_the_full_closure(clone, path):
    assert _rejected_by_closure(clone, _variant(clone, {path: lambda b: b + b"\n"})), path


def test_a_changed_current_map_pin_is_rejected(clone):
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
    tail = b"'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope')"
    for name, fn in (
        ("duplicate_fr", lambda b: b.replace(tail, b"'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v5_gate_scope', 'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_full_recovery_scope')")),
        ("fake_extra", lambda b: b.replace(tail, tail[:-1] + b", 'tests.fake_scope')")),
        ("swapped_g6_fr", lambda b: b.replace(tail, b"'tests.ci_v4_lean_b3_scope', 'tests.ci_v5_bootstrap_scope', 'tests.ci_v5_hardening_scope', 'tests.ci_v4_full_recovery_scope', 'tests.ci_v5_gate_scope')")),
        ("h5_missing", lambda b: b.replace(b", 'tests.ci_v5_hardening_scope'", b"")),
        ("g6_missing", lambda b: b.replace(b", 'tests.ci_v5_gate_scope'", b"")),
        ("fr_missing", lambda b: b.replace(b", 'tests.ci_v4_full_recovery_scope'", b"")),
        ("v5_missing", lambda b: b.replace(b", 'tests.ci_v5_bootstrap_scope'", b"")),
        ("b3_missing", lambda b: b.replace(b", 'tests.ci_v4_lean_b3_scope'", b"")),
        ("r04_removed", lambda b: b.replace(b"'tests.r04_ppa_scope', ", b"")),
        ("earlier_reordered", lambda b: b.replace(b"'tests.fin_v2_3_scope', 'tests.fin_v2_ci_scope'", b"'tests.fin_v2_ci_scope', 'tests.fin_v2_3_scope'")),
    ):
        ref = _variant(clone, {T.REGISTRY: fn})
        assert _g(clone, "diff", "--name-only", "HEAD", ref).decode().split() == [T.REGISTRY], name        # the ONLY difference is the registry
        assert _rejected(clone, ref), name


def test_partially_applied_handoff_is_rejected(clone):
    """Each shared governance handoff reverted alone (the other files keep their reviewed bytes) leaves an inconsistent state that is rejected."""
    for path in (T.PREDECESSOR, T.REGISTRY, "tests/u1_scope.py", "tests/ci_v4_lean_b3_scope.py", "tests/ci_v4_lean_b2_scope.py", "tests/ci_v4_lean_b1_scope.py",
                 "tests/c06_cost_workspace_scope.py"):
        old = subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT)
        assert _rejected(clone, _variant(clone, {path: lambda b, old=old: old})), path


def test_a_compromised_v5_3_forward_hook_is_rejected(clone):
    """The bootstrap hook is the only link from the V5 bootstrap to this cohort: renaming its successor, or removing the overlay, must fail the chain."""
    assert H5.SUCCESSOR == "tests.ci_v4_full_recovery_scope"
    for fn in (lambda b: b.replace(b"SUCCESSOR = 'tests.ci_v4_full_recovery_scope'", b"SUCCESSOR = 'tests.ci_v5_other_scope'"),
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
              edit(lambda d: d["source_blobs"].__setitem__(SHADOW, "0" * 40)),      # (the delta pin is superseded by the V5-3 cohort)
              edit(lambda d: d["source_blobs"].__setitem__(T.PREDECESSOR, "0" * 40)), edit(lambda d: d["base_blobs"].__setitem__(T.REGISTRY, "0" * 40)),
              edit(lambda d: d["source_modes"].__setitem__(MODULE, "100755")), edit(lambda d: d["base_modes"].__setitem__(T.REGISTRY, "100755")),
              edit(lambda d: d["source_blobs"].pop(OWN_TEST)), edit(lambda d: d["source_blobs"].__setitem__(TRUST_ANCHOR, "1" * 40)),
              edit(lambda d: d.__setitem__("extra", 1)), edit(lambda d: d.__setitem__("authorization", "broader")),
              edit(lambda d: d.__setitem__("schema_version", "OTHER")), lambda b: b.rstrip(b"\n"), lambda b: b.replace(b"  ", b"   ", 1))
    for fn in forged:
        assert _rejected(clone, _variant(clone, {T.MANIFEST: fn}))


def test_mode_symlink_deletion_rename_and_owned_file_removal_are_rejected(clone):
    assert _rejected(clone, _variant(clone, mode=MODULE))
    assert _rejected(clone, _variant(clone, mode="tools/ci_v5_epoch.py"))
    assert _rejected(clone, _variant(clone, symlink=OWN_TEST))
    assert _rejected(clone, _variant(clone, symlink="tools/ci_v5_shadow.py"))
    assert _rejected(clone, _variant(clone, remove=(MODULE,)))
    assert _rejected(clone, _variant(clone, remove=("tools/ci_v5_b5.py",)))
    assert _rejected(clone, _variant(clone, remove=(DELTA,)))
    assert _rejected(clone, _variant(clone, rename=("docs/ci_v5/README.md", "docs/ci_v5/README_RENAMED.md")))
    assert _rejected(clone, _variant(clone, rename=("docs/ci_v5/epoch.candidate.json", TRUST_ANCHOR)))        # promotion of the candidate to the trust anchor


def test_added_or_unowned_paths_are_rejected_and_the_trust_anchor_is_never_admitted(clone):
    for path in ("tools/ci_v5_extra.py", ".github/workflows/ci_v5_extra.yml", TRUST_ANCHOR, "docs/ci_v5/gate_3/EXTRA.md", "app/ci_v5_extra.py",
                 "tests/test_ci_v5_unowned.py", "tools/ci_v4_extra.py"):
        assert _rejected_by_closure(clone, _variant(clone, add=(path,))), path
    assert not T.allowed_path(TRUST_ANCHOR) and not T.allowed_path("tools/ci_v5_extra.py") and not T.allowed_path(".github/workflows/ci_v5_extra.yml")


def test_an_incorrect_delta_is_rejected(clone):
    def drop_one(raw):
        d = json.loads(raw)
        d["changes"].pop()
        return (json.dumps(d, indent=1, sort_keys=True) + "\n").encode()
    assert _rejected_by_signature(clone, _variant(clone, {DELTA: drop_one}))
    assert _rejected_by_signature(clone, _variant(clone, {DELTA: lambda b: b.replace(b'"op": "add"', b'"op": "modify"', 1)}))


def test_wrong_ancestor_and_older_refs_are_rejected(clone):
    assert not T.signature_ok(clone, T.BASE) and not T.exact_blobs_ok(clone, T.BASE)              # accepted main carries no V5-3 manifest
    first = _g(clone, "rev-list", "--max-parents=0", "HEAD").decode().split()[0]
    assert not T.signature_ok(clone, first) and not T.exact_blobs_ok(clone, first)
    assert not T.signature_ok(clone, "0" * 40) and not T.signature_ok(clone, "refs/heads/does-not-exist") and not T.exact_blobs_ok(clone, "not-a-ref")


def test_an_untracked_file_in_the_worktree_is_rejected_and_the_state_restores(clone):
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
    for p in ("financial_engine/tax/engine.py", "app/v2/router.py", "tools/ci_v4_select.py", "docs/ci_v4/ci-v4-policy.json", TRUST_ANCHOR):
        assert not T.allowed_path(p)
    assert T.allowed_path(DELTA) and T.allowed_path(T.MANIFEST) and T.protected_blobs() == {}
    bad = _variant(clone, {T.MANIFEST: lambda b: b.replace(b'"base_tree": "48f3ded7', b'"base_tree": "08f3ded7', 1)})
    assert not T.allowed_path(DELTA, clone, bad)                       # with a false signature even an owned path confers no authority


def test_supersession_is_pin_exact_and_cross_path_safe():
    pins = T.manifest()["source_blobs"]
    reg = pins[T.REGISTRY]
    assert V5.supersedes(T.REGISTRY, reg) and B3.supersedes(T.REGISTRY, reg) and B2.supersedes(T.REGISTRY, reg) and K.supersedes(T.REGISTRY, reg) and P.supersedes(T.REGISTRY, reg)
    assert not V5.supersedes(T.REGISTRY, "0" * 40) and not K.supersedes(T.REGISTRY, "0" * 40)
    assert not V5.supersedes(T.REGISTRY, pins[T.PREDECESSOR])                       # a real blob pinned for another path
    assert not V5.supersedes(T.REGISTRY, T.manifest()["base_blobs"][T.REGISTRY])    # the accepted bootstrap-era registry blob is no longer current
    assert not V5.supersedes("docs/ci_v4/module_weights.json", _git("rev-parse", T.BASE + ":docs/ci_v4/module_weights.json"))


def test_no_verdict_is_cached_across_refs_or_mutations(clone):
    bad = _variant(clone, {T.REGISTRY: lambda b: b.replace(b", 'tests.ci_v5_hardening_scope'", b"")})
    with T.scoped(), V5.scoped(), B3.scoped(), K.scoped():
        assert T.signature_ok(clone, "HEAD") and V5.exact_blobs_ok(clone, "HEAD")
        assert not T.signature_ok(clone, bad) and not T.exact_blobs_ok(clone, bad)               # same process, same scope, other ref
        assert T.signature_ok(clone, "HEAD")                                                      # and back: the positive verdict was never poisoned
    assert T.signature_ok(clone, "HEAD") and not T.signature_ok(clone, bad)


def test_the_registry_tail_is_one_finite_sequence_and_full_recovery_is_terminal(monkeypatch):
    """C06 -> B1 -> B2 -> B3 -> V5_BOOTSTRAP -> V5_2B -> V5_3 -> FULL_RECOVERY is the ONLY accepted tail: any permutation, duplicate, extra cohort or truncation fails every layer present."""
    exact = C.COHORT_MODULES
    assert exact[-8:] == ("tests.c06_cost_workspace_scope", "tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope",
                          "tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope")
    layers = (K, B1, B2, B3, V5, H4, H5, T)
    with C.call_scope():
        assert all(m.signature_ok() for m in layers)
    c06, b1, b2, b3, v5, h5, g6, fr = exact[-8:]
    head = exact[:-8]
    variants = {"b2_b3_swapped": head + (c06, b1, b3, b2, v5, h5, g6, fr), "b1_b2_swapped": head + (c06, b2, b1, b3, v5, h5, g6, fr), "b3_v5_swapped": head + (c06, b1, b2, v5, b3, h5, g6, fr),
                "v5_h5_swapped": head + (c06, b1, b2, b3, h5, v5, g6, fr), "h5_g6_swapped": head + (c06, b1, b2, b3, v5, g6, h5, fr), "g6_duplicated": exact + (g6,),
                "v5_duplicated": head + (c06, b1, b2, b3, v5, v5, h5, g6, fr), "fr_duplicated": exact + (fr,), "g6_fr_swapped": head + (c06, b1, b2, b3, v5, h5, fr, g6), "fr_dropped": head + (c06, b1, b2, b3, v5, h5, g6), "unknown_extra_cohort": exact + ("tests.not_a_reviewed_cohort",), "g6_before_c06": head + (g6, c06, b1, b2, b3, v5, h5, fr),
                "c06_dropped": head + (b1, b2, b3, v5, h5, g6, fr), "b3_dropped": head + (c06, b1, b2, v5, h5, g6, fr), "b1_dropped": head + (c06, b2, b3, v5, h5, g6, fr),
                "v5_dropped": head + (c06, b1, b2, b3, h5, g6, fr), "h5_dropped": head + (c06, b1, b2, b3, v5, g6, fr)}
    for name, tail in variants.items():
        monkeypatch.setattr(C, "COHORT_MODULES", tail)
        for layer in layers:
            if layer.__name__ in tail:
                assert not layer.signature_ok(), (name, layer.__name__)
    monkeypatch.setattr(C, "COHORT_MODULES", exact)
    with C.call_scope():
        assert all(m.signature_ok() for m in layers)                       # state A restored: accepted again
