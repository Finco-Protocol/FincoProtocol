"""T01-E exact-source successor (after the accepted F03 leaf): positive identity and adversarial fail-closed controls.

Every negative runs in an ISOLATED clone (a committed variant, or a mutated working tree that is restored afterwards); the evaluated checkout is
never edited and no verdict is cached across mutations.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from tests import f04_financing_scope as Q

from tests import f03_financing_scope as F
from tests import fin_v2_cohorts as C
from tests import t01e_remediation_scope as T

ROOT = Path(__file__).resolve().parents[1]
REMEDIATION = "tax_reference_registry/remediation.py"
SECOND_TEST = "tests/tax_reference_registry/test_remediation.py"


def _git(*args, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd).decode().strip()


@pytest.fixture(scope="module")
def clone(tmp_path_factory):
    root = tmp_path_factory.mktemp("t01e-gov") / "repo"
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
def test_manifest_schema_pins_and_immutable_base():
    d = T.manifest()
    assert d and d["schema_version"] == T.SCHEMA and d["base"] == T.BASE and d["base_tree"] == T.BASE_TREE
    assert set(d["source_blobs"]) == T.OWNED_PATHS and set(d["base_blobs"]) == T.SUPERSEDED
    assert _git("rev-parse", T.BASE + "^{tree}") == T.BASE_TREE
    assert _git("merge-base", "--is-ancestor", T.BASE, "HEAD") == ""
    assert not set(d["base_blobs"]) & T.NEW


def test_owned_set_is_finite_literal_and_has_no_forbidden_path():
    assert T.NEW == frozenset((REMEDIATION, SECOND_TEST, "tests/t01e_remediation_scope.py", "tests/test_t01e_remediation_scope.py"))
    assert T.HANDOFF_PATHS == frozenset((
        F_PATH := "tests/f03_financing_scope.py", "tests/fin_v2_cohorts.py", "tests/test_bess02_scope.py", "tests/test_ci_v4_perf_scope.py",
        "tests/test_r02_ppa_ux_scope.py", "tests/test_post432_l01_l02_scope.py", "tests/test_f03_financing_scope.py"))
    assert len(T.CURRENT_MAPS) == 8 and set(T.HANDOFFS) == T.HANDOFF_PATHS and T.MAP_KEYS == ("tests/fin_v2_cohorts.py",)
    assert not any(p.startswith(T.FORBIDDEN) or "*" in p or ".." in p.split("/") for p in T.OWNED_PATHS | {T.MANIFEST})
    assert F_PATH == T.PREDECESSOR


def test_signature_exactness_and_reviewed_substitutions_hold():
    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()
    from tests import r03_ppa_scope as Y
    for p in T.HANDOFFS:
        if Q.signature_ok() and p in Q.HANDOFFS:
            assert (ROOT / p).read_bytes() == Q.expected_handoff(ROOT, p)
            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]
            continue
        if Y.signature_ok() and p in Y.HANDOFFS:            # the further reviewed R03 substitution of this shared path
            assert (ROOT / p).read_bytes() == Y.expected_handoff(ROOT, p)
            assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]
            continue
        assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)
        assert T._blob((ROOT / p).read_bytes()) == T.manifest()["source_blobs"][p]


def test_registered_exactly_once_directly_after_f03_with_only_the_reviewed_r03_successor_behind_it():
    i = C.COHORT_MODULES.index("tests.t01e_remediation_scope")
    assert C.COHORT_MODULES[i - 1] == "tests.f03_financing_scope"
    assert C.COHORT_MODULES[i + 1:] in ((), ("tests.r03_ppa_scope",), ("tests.r03_ppa_scope", "tests.f04_financing_scope"))
    assert C.COHORT_MODULES.count("tests.t01e_remediation_scope") == 1


def test_current_maps_move_only_the_registry_key():
    pins = T.effective_pins()                  # the CURRENT pins: a reviewed successor's overlay wins while its signature holds
    for p in T.CURRENT_MAPS:
        old = json.loads(_git("show", T.BASE + ":" + p))
        cur = json.loads((ROOT / p).read_text())
        assert set(old) == set(cur) and all(old[k] == cur[k] for k in old if k != "source_blobs")
        changed = {k for k in old["source_blobs"] if old["source_blobs"][k] != cur["source_blobs"][k]}
        assert changed <= set(T.map_keys())
        for k in changed:
            assert cur["source_blobs"][k] == pins[k]


def test_historical_manifests_and_accepted_chain_files_are_byte_identical_to_the_accepted_base():
    for p in T.FROZEN:
        assert (ROOT / p).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + p], cwd=ROOT), p


def test_the_whole_chain_is_exact_and_the_composite_is_valid_on_the_committed_head(clone):
    with C.call_scope():
        assert T.exact_blobs_ok(clone, "HEAD") and F.exact_blobs_ok(clone, "HEAD") and C.valid(clone, "HEAD")


def test_committed_ref_verdict_equals_the_working_tree_verdict(clone):
    # Regression: the committed-ref read used to drop the repository root; both views must agree and a wrong ref must fail.
    assert T.manifest(clone, "HEAD") and T.manifest(clone, "HEAD") == T.manifest(clone)
    assert T.exact_blobs_ok(clone) is T.exact_blobs_ok(clone, "HEAD") is True
    assert not T.exact_blobs_ok(clone, "0" * 40) and not T.exact_blobs_ok(clone, T.BASE) and not T.manifest(clone, T.BASE)


def test_activation_guards_stay_blocked():
    from tax_reference_registry import ActivationBlockedError, activate_country, get_effective_run_profile
    with pytest.raises(ActivationBlockedError):
        activate_country("ZZ")
    with pytest.raises(ActivationBlockedError):
        get_effective_run_profile("ZZ")


# ---------------------------------------------------------------- working-tree tamper is detected (the original defect)
@pytest.mark.parametrize("path", sorted(T.OWNED_PATHS - T.CURRENT_MAPS))
def test_one_byte_in_the_working_tree_of_any_owned_blob_fails_closed(clone, path):
    with _WorkingTree(clone):
        assert T.exact_blobs_ok(clone) and T.signature_ok(clone)
        _tamper(clone, path, lambda b: b + b"\n# tampered\n")
        assert T.exact_blobs_ok(clone) is False and not C.valid(clone), path
    assert T.exact_blobs_ok(clone)                               # restored: the verdict is not poisoned


def test_working_tree_tamper_of_remediation_is_detected_while_head_is_unchanged(clone):
    with _WorkingTree(clone):
        head = _g(clone, "rev-parse", "HEAD")
        _tamper(clone, REMEDIATION, lambda b: b + b"\n# tampered\n")
        assert _g(clone, "rev-parse", "HEAD") == head and _g(clone, "status", "--porcelain").decode().strip()
        assert T.exact_blobs_ok(clone) is False and T.exact_blobs_ok(clone, "HEAD") is True


def test_deleted_or_symlinked_or_executable_owned_file_fails_closed_in_the_working_tree(clone):
    with _WorkingTree(clone):
        (clone / REMEDIATION).unlink()
        assert not T.exact_blobs_ok(clone)
    with _WorkingTree(clone):
        (clone / REMEDIATION).unlink()
        os.symlink((clone / SECOND_TEST), clone / REMEDIATION)
        assert not T.exact_blobs_ok(clone)
    with _WorkingTree(clone):
        (clone / REMEDIATION).chmod(0o755)
        assert not T.exact_blobs_ok(clone)


def test_untracked_foreign_file_in_the_working_tree_fails_closed(clone):
    with _WorkingTree(clone):
        (clone / "app").mkdir(exist_ok=True)
        (clone / "app" / "unreviewed_t01e_extra.py").write_text("x = 1\n")
        assert not T.exact_blobs_ok(clone)


# ---------------------------------------------------------------- committed-ref adversarial variants
@pytest.mark.parametrize("path", sorted(T.OWNED_PATHS | {T.MANIFEST} - T.CURRENT_MAPS))
def test_one_byte_in_any_owned_committed_blob_is_rejected_by_t01e_and_the_composite(clone, path):
    ref = _variant(clone, {path: lambda b: b + b"\n"})
    with C.call_scope():
        assert not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref), path


@pytest.mark.parametrize("path", sorted(T.CURRENT_MAPS))
def test_current_map_tamper_is_rejected_by_the_full_closure(clone, path):
    ref = _variant(clone, {path: lambda b: b + b"\n"})
    with C.call_scope():
        assert not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref), path


@pytest.mark.parametrize("name,fn", [
    ("duplicate_t01e", lambda b: b.replace(b"'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope')", b"'tests.t01e_remediation_scope', 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope')")),
    ("fake_extra", lambda b: b.replace(b"'tests.r03_ppa_scope', 'tests.f04_financing_scope')", b"'tests.r03_ppa_scope', 'tests.fake_scope')")),
    ("swapped_f03_t01e", lambda b: b.replace(b"'tests.f03_financing_scope', 'tests.t01e_remediation_scope'", b"'tests.t01e_remediation_scope', 'tests.f03_financing_scope'")),
    ("t01e_missing", lambda b: b.replace(b", 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope')", b", 'tests.r03_ppa_scope', 'tests.f04_financing_scope')")),
    ("f03_removed", lambda b: b.replace(b"'tests.f03_financing_scope', ", b"")),
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
        assert not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref), path


def test_predecessor_f03_scope_tamper_is_rejected_everywhere(clone):
    ref = _variant(clone, {T.PREDECESSOR: lambda b: b + b"\n"})
    with C.call_scope():
        assert not T.signature_ok(clone, ref) and not F.exact_blobs_ok(clone, ref) and not C.valid(clone, ref)


def test_partially_applied_handoff_is_rejected(clone):
    # registry registered but the F03 forward hook reverted to the accepted BASE bytes (and vice versa)
    old_f03 = subprocess.check_output(["git", "show", T.BASE + ":" + T.PREDECESSOR], cwd=ROOT)
    ref = _variant(clone, {T.PREDECESSOR: lambda b: old_f03})
    with C.call_scope():
        assert not T.signature_ok(clone, ref) and not C.valid(clone, ref)
    old_reg = subprocess.check_output(["git", "show", T.BASE + ":" + T.REGISTRY], cwd=ROOT)
    ref = _variant(clone, {T.REGISTRY: lambda b: old_reg})
    with C.call_scope():
        assert not T.signature_ok(clone, ref) and not C.valid(clone, ref)


def test_forged_manifest_base_tree_pin_and_mode_are_rejected(clone):
    for fn in (lambda b: b.replace(b'"base_tree": "80c62e23', b'"base_tree": "10c62e23', 1),
               lambda b: b.replace(b'"base": "d17f46e5', b'"base": "e17f46e5', 1),
               lambda b: b.replace(REMEDIATION.encode() + b'": "', REMEDIATION.encode() + b'": "0000', 1),
               lambda b: b.replace(b'"tests/fin_v2_cohorts.py": "', b'"tests/fin_v2_cohorts.py": "0000', 1)):
        ref = _variant(clone, {T.MANIFEST: fn})
        with C.call_scope():
            assert not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref)
    ref = _variant(clone, mode=REMEDIATION)
    assert not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref)
    ref = _variant(clone, symlink=SECOND_TEST)
    assert not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref)


def test_wrong_ancestor_and_unknown_protected_paths_are_rejected(clone):
    assert not T.signature_ok(clone, T.BASE)                       # the accepted base carries no successor manifest
    first = _g(clone, "rev-list", "--max-parents=0", "HEAD").decode().split()[0]
    assert not T.signature_ok(clone, first) and not T.exact_blobs_ok(clone, first)
    for path in ("app/v2/react_financing.py", "financial_engine/tax/engine.py", "finco_core/placeholder.py", ".github/workflows/ci_v4_pr.yml"):
        if (ROOT / path).exists():
            ref = _variant(clone, {path: lambda b: b + b"\n"})
        else:
            f = clone / path
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x = 1\n")
            _g(clone, "add", "-A"); _g(clone, "commit", "-q", "-m", "unknown")
            ref = _g(clone, "rev-parse", "HEAD").decode().strip()
            _g(clone, "checkout", "-q", "-f", "HEAD~1"); _g(clone, "clean", "-fdxq")
        with C.call_scope():
            assert not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref), path


def test_allowed_path_is_gated_by_the_cohort_signature_and_never_admits_foreign_paths(clone):
    for p in ("financial_engine/tax/engine.py", "app/v2/router.py", "tax_reference_registry/other.py"):
        assert not T.allowed_path(p)
    assert T.allowed_path(REMEDIATION) and T.allowed_path(T.MANIFEST) and T.protected_blobs() == {}
    bad = _variant(clone, {T.MANIFEST: lambda b: b.replace(b'"base_tree": "80c62e23', b'"base_tree": "10c62e23', 1)})
    assert not T.allowed_path(REMEDIATION, clone, bad)             # with a false signature even an owned path confers no authority


def test_supersession_is_pin_exact_and_cross_path_safe():
    pins = T.manifest()["source_blobs"]
    reg = T.effective_pins()[T.REGISTRY]                   # the CURRENT registry pin (the reviewed R03 successor's while its signature holds)
    assert F.supersedes(T.REGISTRY, reg) and F.effective_pins()[T.REGISTRY] == reg
    assert not F.supersedes(T.REGISTRY, "0" * 40)
    assert not F.supersedes(T.REGISTRY, pins[T.PREDECESSOR])        # a real blob pinned for another path
    assert not F.supersedes(T.REGISTRY, T.manifest()["base_blobs"][T.REGISTRY])      # the accepted F03-only blob is no longer current
    assert not T.supersedes("tests/not_superseded.py", reg)


def test_no_verdict_is_cached_across_refs_or_mutations(clone):
    bad = _variant(clone, {T.REGISTRY: lambda b: b.replace(b", 'tests.t01e_remediation_scope', 'tests.r03_ppa_scope', 'tests.f04_financing_scope')", b", 'tests.r03_ppa_scope', 'tests.f04_financing_scope')")})
    with T.scoped(), F.scoped():
        assert T.signature_ok(clone, "HEAD") and F.exact_blobs_ok(clone, "HEAD")
        assert not T.signature_ok(clone, bad) and not F.exact_blobs_ok(clone, bad)     # same process, same scope, other ref
    assert T.signature_ok(clone, "HEAD")                                                # and the positive verdict was never poisoned
