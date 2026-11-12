"""R04 exact-source successor (after the accepted R03 leaf): positive identity and adversarial fail-closed controls.

Every negative runs in an ISOLATED clone (a committed variant, or a mutated working tree that is restored afterwards); the evaluated checkout is
never edited and no verdict is cached across mutations.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests import f03_financing_scope as F
from tests import fin_v2_cohorts as C
from tests import r04_ppa_scope as T
from tests import f04_financing_scope as P

ROOT = Path(__file__).resolve().parents[1]
REMEDIATION = "research/r04_ppa_global_cap/core.py"
SECOND_TEST = "tests/r04_ppa_global_cap/oracle.py"


def _git(*args, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd).decode().strip()


@pytest.fixture(scope="module")
def clone(tmp_path_factory):
    root = tmp_path_factory.mktemp("r04-gov") / "repo"
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
    assert T.SOURCE_PATHS == frozenset(("research/r04_ppa_global_cap/README.md", "research/r04_ppa_global_cap/__init__.py",
                                        "research/r04_ppa_global_cap/core.py"))
    assert len(T.NEW) == 10 and "tests/r04_ppa_scope.py" in T.NEW and "tests/test_r04_ppa_scope.py" in T.NEW
    assert all(p.startswith(("research/r04_ppa_global_cap/", "tests/r04_ppa_global_cap/")) or p in ("tests/r04_ppa_scope.py", "tests/test_r04_ppa_scope.py")
               for p in T.NEW)
    assert T.HANDOFF_PATHS == frozenset((
        "tests/f04_financing_scope.py", "tests/fin_v2_cohorts.py", "tests/test_bess02_scope.py", "tests/test_ci_v4_perf_scope.py",
        "tests/test_r02_ppa_ux_scope.py", "tests/test_post432_l01_l02_scope.py", "tests/test_f03_financing_scope.py",
        "tests/test_t01e_remediation_scope.py", "tests/test_r03_ppa_scope.py", "tests/test_f04_financing_scope.py"))
    assert len(T.CURRENT_MAPS) == 8 and set(T.HANDOFFS) == T.HANDOFF_PATHS and T.MAP_KEYS == ("tests/fin_v2_cohorts.py",)
    assert not any(p.startswith(T.FORBIDDEN) or "*" in p or ".." in p.split("/") for p in T.OWNED_PATHS | {T.MANIFEST})
    assert T.PREDECESSOR == "tests/f04_financing_scope.py"


def test_signature_exactness_and_reviewed_substitutions_hold():
    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()
    for p in T.HANDOFFS:
        assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)
        assert T._blob((ROOT / p).read_bytes()) == T.manifest()["source_blobs"][p]


def test_registered_exactly_once_as_the_terminal_cohort_after_f04():
    assert C.COHORT_MODULES[-5:] == ("tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")
    assert C.COHORT_MODULES.count("tests.r04_ppa_scope") == 1


def test_current_maps_move_only_the_registry_key():
    pins = T.manifest()["source_blobs"]
    for p in T.CURRENT_MAPS:
        old = json.loads(_git("show", T.BASE + ":" + p))
        cur = json.loads((ROOT / p).read_text())
        assert set(old) == set(cur) and all(old[k] == cur[k] for k in old if k != "source_blobs")
        changed = {k for k in old["source_blobs"] if old["source_blobs"][k] != cur["source_blobs"][k]}
        assert changed <= set(T.MAP_KEYS)
        for k in changed:
            assert cur["source_blobs"][k] == pins[k]


def test_historical_manifests_and_accepted_chain_files_are_byte_identical_to_the_accepted_base():
    for p in T.FROZEN:
        assert (ROOT / p).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + p], cwd=ROOT), p


def test_the_whole_chain_is_exact_and_the_composite_is_valid_on_the_committed_head(clone):
    with C.call_scope():
        assert T.exact_blobs_ok(clone, "HEAD") and P.exact_blobs_ok(clone, "HEAD") and F.exact_blobs_ok(clone, "HEAD") and C.valid(clone, "HEAD")


def test_committed_ref_verdict_equals_the_working_tree_verdict(clone):
    # Regression: the committed-ref read used to drop the repository root; both views must agree and a wrong ref must fail.
    assert T.manifest(clone, "HEAD") and T.manifest(clone, "HEAD") == T.manifest(clone)
    assert T.exact_blobs_ok(clone) is T.exact_blobs_ok(clone, "HEAD") is True
    assert not T.exact_blobs_ok(clone, "0" * 40) and not T.exact_blobs_ok(clone, T.BASE) and not T.manifest(clone, T.BASE)


def test_no_production_path_imports_the_isolated_candidate_and_it_imports_no_product_code():
    import re
    files = _git("ls-files", "--", "*.py", "*.ts", "*.tsx", "*.js", "*.mjs", "*.html").split("\n")
    pat = re.compile(r"r04_ppa_global_cap")
    offenders = [f for f in files if f and not f.startswith(("research/r04_ppa_global_cap/", "tests/")) and pat.search((ROOT / f).read_text(errors="ignore"))]
    assert offenders == []
    core = (ROOT / "research/r04_ppa_global_cap/core.py").read_text()
    for forbidden in ("import app", "from app", "financial_engine", "finco_core", "main_web", "tax_reference_registry", "domain."):
        assert forbidden not in core, forbidden
    assert '"wired_into_save_or_run": False' in core


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
    ("duplicate_r04", lambda b: b.replace(b"'tests.r04_ppa_scope')", b"'tests.r04_ppa_scope', 'tests.r04_ppa_scope')")),
    ("fake_extra", lambda b: b.replace(b"'tests.r04_ppa_scope')", b"'tests.r04_ppa_scope', 'tests.fake_scope')")),
    ("swapped_f04_r04", lambda b: b.replace(b"'tests.f04_financing_scope', 'tests.r04_ppa_scope')", b"'tests.r04_ppa_scope', 'tests.f04_financing_scope')")),
    ("r04_missing", lambda b: b.replace(b", 'tests.r04_ppa_scope')", b")")),
    ("f04_removed", lambda b: b.replace(b"'tests.f04_financing_scope', ", b"")),
    ("r03_removed", lambda b: b.replace(b"'tests.r03_ppa_scope', ", b"")),
    ("t01e_removed", lambda b: b.replace(b"'tests.t01e_remediation_scope', ", b"")),
    ("f03_removed", lambda b: b.replace(b"'tests.f03_financing_scope', ", b"")),
    ("earlier_reordered", lambda b: b.replace(b"'tests.fin_v2_3_scope', 'tests.fin_v2_ci_scope'", b"'tests.fin_v2_ci_scope', 'tests.fin_v2_3_scope'")),
])
def test_registry_mutations_are_rejected(clone, name, fn):
    ref = _variant(clone, {T.REGISTRY: fn})
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
    for fn in (lambda b: b.replace(b'"base_tree": "3047a090', b'"base_tree": "1047a090', 1),
               lambda b: b.replace(b'"base": "2cce0343', b'"base": "3cce0343', 1),
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
    bad = _variant(clone, {T.MANIFEST: lambda b: b.replace(b'"base_tree": "3047a090', b'"base_tree": "1047a090', 1)})
    assert not T.allowed_path(REMEDIATION, clone, bad)             # with a false signature even an owned path confers no authority


def test_supersession_is_pin_exact_and_cross_path_safe():
    pins = T.manifest()["source_blobs"]
    reg = pins[T.REGISTRY]
    assert P.supersedes(T.REGISTRY, reg) and F.supersedes(T.REGISTRY, reg) and F.effective_pins()[T.REGISTRY] == reg
    assert not F.supersedes(T.REGISTRY, "0" * 40)
    assert not F.supersedes(T.REGISTRY, pins[T.PREDECESSOR])        # a real blob pinned for another path
    assert not F.supersedes(T.REGISTRY, T.manifest()["base_blobs"][T.REGISTRY])      # the accepted R03 blob is no longer current
    assert not P.supersedes(T.REGISTRY, T.manifest()["base_blobs"][T.REGISTRY])
    assert not T.supersedes("tests/not_superseded.py", reg)


def test_no_verdict_is_cached_across_refs_or_mutations(clone):
    bad = _variant(clone, {T.REGISTRY: lambda b: b.replace(b", 'tests.r04_ppa_scope')", b")")})
    with T.scoped(), F.scoped():
        assert T.signature_ok(clone, "HEAD") and F.exact_blobs_ok(clone, "HEAD")
        assert not T.signature_ok(clone, bad) and not F.exact_blobs_ok(clone, bad)     # same process, same scope, other ref
    assert T.signature_ok(clone, "HEAD")                                                # and the positive verdict was never poisoned


# ---------------------------------------------------------------- PHASE 1: baseline ownership of the production revenue paths (no runtime change)
KEY_PRODUCTION_PATHS = ("domain/revenue/multistream_runtime.py", "domain/revenue/plan.py", "domain/revenue/plan_engine.py",
                        "app/workbook/revenue_multistream.py", "app/workbook/revenue_contracts_service.py", "finco_core/revenue/generation.py",
                        "finco_core/engine/period_engine.py", "frontend/src/app/workflow/PpaContractsEditor.tsx",
                        "frontend/src/app/workflow/ModelWorkflowValidation.ts", "static/react/finco-react.js")


def test_baseline_table_is_exactly_the_accepted_base_state_and_authorizes_no_change():
    assert set(KEY_PRODUCTION_PATHS) <= set(T.BASELINE)
    for p, (mode, blob) in T.BASELINE.items():
        line = _git("ls-tree", T.BASE, "--", p).split()
        assert (line[0], line[2]) == (mode, blob) and mode == "100644", p
        assert (ROOT / p).is_file() and not (ROOT / p).is_symlink()
        assert T._blob((ROOT / p).read_bytes()) == blob, p
        assert p not in T.OWNED_PATHS and p not in T.SUPERSEDED and p not in T.HANDOFFS and not T.allowed_path(p), p   # asserted, never pre-authorized
        assert p not in T.manifest()["source_blobs"] and p not in T.manifest()["base_blobs"]
    assert not set(T.BASELINE) & set(T.FROZEN)


@pytest.mark.parametrize("path", sorted(T.BASELINE))
def test_one_byte_in_any_baseline_production_path_fails_closed_in_the_cohort_and_the_composite(clone, path):
    ref = _variant(clone, {path: lambda b: b + b"\n"})
    with C.call_scope():
        assert not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref), path


@pytest.mark.parametrize("path", sorted(T.BASELINE))
def test_mode_symlink_and_deletion_of_a_baseline_production_path_fail_closed(clone, path):
    assert not T.signature_ok(clone, _variant(clone, mode=path)), path
    assert not T.signature_ok(clone, _variant(clone, symlink=path)), path
    assert not T.signature_ok(clone, _variant(clone, remove=(path,))), path


@pytest.mark.parametrize("path", KEY_PRODUCTION_PATHS)
def test_working_tree_drift_of_a_baseline_path_is_judged_on_disk(clone, path):
    with _WorkingTree(clone):
        assert T.exact_blobs_ok(clone)
        _tamper(clone, path, lambda b: b + b"\n# drift\n")
        assert T.exact_blobs_ok(clone) is False and T.signature_ok(clone) is False
    with _WorkingTree(clone):
        (clone / path).chmod(0o755)
        assert T.exact_blobs_ok(clone) is False
    assert T.exact_blobs_ok(clone)


def test_mode_drift_of_a_frozen_accepted_chain_file_is_now_rejected_too(clone):
    for p in T.FROZEN[:6]:
        assert not T.signature_ok(clone, _variant(clone, mode=p)), p


def test_an_unowned_new_revenue_or_foreign_path_is_outside_the_closed_set(clone):
    for path in ("domain/revenue/r04_unowned.py", "app/workbook/r04_unowned.py", "finco_core/revenue/r04_unowned.py"):
        f = clone / path
        f.write_text("x = 1\n")
        _g(clone, "add", "-A")
        _g(clone, "commit", "-q", "-m", "unowned")
        ref = _g(clone, "rev-parse", "HEAD").decode().strip()
        _g(clone, "checkout", "-q", "-f", "HEAD~1")
        _g(clone, "clean", "-fdxq")
        with C.call_scope():
            assert not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref), path
        assert not T.allowed_path(path, clone, ref)


def test_a_future_paired_change_cannot_be_smuggled_through_this_cohort(clone):
    # Moving a baseline path without moving its table entry, or adding it to the manifest without a reviewed successor, is refused.
    p = "domain/revenue/multistream_runtime.py"
    new = _variant(clone, {p: lambda b: b + b"\n"})
    assert not T.signature_ok(clone, new)
    forged = _variant(clone, {T.MANIFEST: lambda b: b.replace(b'"base_blobs": {', b'"base_blobs": {\n    "' + p.encode() + b'": "' + b"0" * 40 + b'",', 1)})
    assert not T.signature_ok(clone, forged) and not T.exact_blobs_ok(clone, forged)
