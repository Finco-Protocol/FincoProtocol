"""CI V4 Lean B2 exact-source successor (after the accepted B1 cohort): positive identity and adversarial fail-closed controls.

Risk protected: B2 carries the data-only scheduling-weight refresh inside a protected provenance graph; it must own exactly its finite file
set, change no CI control file, and every forged manifest, registry state, handoff, mode or ref must be rejected. Every negative runs in an
ISOLATED clone (a committed variant); the evaluated checkout is never edited and no verdict is cached across mutations.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests import ci_v4_lean_b1_scope as B1
from tests import ci_v4_lean_b2_scope as T
from tests import fin_v2_cohorts as C

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = "docs/ci_v4/module_weights.json"


def _git(*args, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd).decode().strip()


@pytest.fixture(scope="module")
def clone(tmp_path_factory):
    root = tmp_path_factory.mktemp("b2-gov") / "repo"
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
    assert len(T.CURRENT_MAPS) >= 8 and set(T.HANDOFFS) == T.HANDOFF_PATHS
    assert {"tests/fin_v2_cohorts.py", "tests/u1_scope.py", "docs/ci_v4/module_weights.json"} <= set(T.MAP_KEYS)
    assert T.PREDECESSOR == "tests/ci_v4_lean_b1_scope.py" and T.REGISTRY == "tests/fin_v2_cohorts.py"
    assert not any(p.startswith(T.FORBIDDEN) or "*" in p or ".." in p.split("/") or p.startswith("/") for p in T.OWNED_PATHS | {T.MANIFEST})
    for path in T.SUPERSEDED:
        assert data["base_blobs"][path] == _git("rev-parse", T.BASE + ":" + path)
    assert _git("rev-parse", T.BASE + "^{tree}") == T.BASE_TREE


def test_the_refresh_is_data_only_and_no_control_file_is_owned():
    """B2 is additive: the weights move by one reviewed handoff; every other CI V4 control file stays byte-equal to BASE; nothing else is owned."""
    assert WEIGHTS in T.HANDOFF_PATHS and WEIGHTS in T.MAP_KEYS
    assert not (T.OWNED_PATHS | {T.MANIFEST}) & set(T.FROZEN)
    assert not any(p.startswith((".github/", "tools/", "app/", "financial_engine/", "finco_core/", "domain/", "frontend/", "static/", "research/"))
                   for p in T.OWNED_PATHS | {T.MANIFEST} - {WEIGHTS})
    for path in T.FROZEN:
        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + path], cwd=ROOT), path


def test_signature_exactness_and_reviewed_substitutions_hold(clone):
    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()
    for p in T.HANDOFFS:
        assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)
        assert T._blob((ROOT / p).read_bytes()) == T.effective_pins()[p]
    for ref in (None, "HEAD"):
        with C.call_scope():
            assert T.signature_ok(clone, ref) and T.exact_blobs_ok(clone, ref) and B1.exact_blobs_ok(clone, ref) and C.valid(clone, ref)


def test_registered_exactly_once_as_the_terminal_cohort_after_b1():
    assert C.COHORT_MODULES == T.BASE_COHORTS + (T.__name__,) and C.COHORT_MODULES.count(T.__name__) == 1
    assert C.COHORT_MODULES[-2:] == ("tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope")
    assert B1.SUCCESSOR == T.__name__ and B1._next() is T


def test_the_b1_forward_hook_is_installed_and_the_u1_discovery_list_names_this_successor():
    assert B1.HANDOFF_PATHS is not None and "tests/ci_v4_lean_b1_scope.py" in T.HANDOFF_PATHS
    from tests import u1_scope as U
    assert U.RECONCILED_SUCCESSORS[-1] == "tests.ci_v4_lean_b2_scope"
    assert U.RECONCILED_SUCCESSORS.count("tests.ci_v4_lean_b2_scope") == 1


def test_the_weights_refresh_is_honest_and_selection_neutral():
    import json as _json
    d = _json.loads((ROOT / WEIGHTS).read_text())
    old = _json.loads(_git("show", T.BASE + ":" + WEIGHTS))
    assert set(d["modules"]) == set(old["modules"]) and set(d["nodes"]) == set(old["nodes"])
    assert d["modules"]["tests/test_u1_scope.py"] > 3000.0 and old["modules"]["tests/test_u1_scope.py"] < 1000.0
    assert "43692118132" in d["source"] and "DERIVED" in d["source"]


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


def test_weights_mutations_are_rejected(clone):
    for name, fn in (
        ("one_weight_changed", lambda b: b.replace(b'"tests/test_u1_scope.py": 3944.0', b'"tests/test_u1_scope.py": 100.0')),
        ("u1_weight_deleted", lambda b: b.replace(b'"tests/test_u1_scope.py": 3944.0, ', b"")),
        ("source_underrated", lambda b: b.replace(b"DERIVED", b"measured on all workers")),
        ("one_module_added", lambda b: b.replace(b'"tests/test_u1_scope.py": 3944.0', b'"tests/test_u1_scope.py": 3944.0, "tests/fake_module.py": 1.0')),
    ):
        ref = _variant(clone, {WEIGHTS: fn})
        assert _g(clone, "diff", "--name-only", "HEAD", ref).decode().split() == [WEIGHTS], name
        assert _rejected(clone, ref), name


def test_partially_applied_handoff_is_rejected(clone):
    old_pred = subprocess.check_output(["git", "show", T.BASE + ":" + T.PREDECESSOR], cwd=ROOT)       # B1 forward hook reverted
    assert _rejected(clone, _variant(clone, {T.PREDECESSOR: lambda b: old_pred}))
    old_reg = subprocess.check_output(["git", "show", T.BASE + ":" + T.REGISTRY], cwd=ROOT)           # registry reverted, B2 files remain
    assert _rejected(clone, _variant(clone, {T.REGISTRY: lambda b: old_reg}))
    old_u1 = subprocess.check_output(["git", "show", T.BASE + ":tests/u1_scope.py"], cwd=ROOT)         # discovery list reverted
    assert _rejected(clone, _variant(clone, {"tests/u1_scope.py": lambda b: old_u1}))


def test_forged_manifest_pin_base_mode_and_canonical_bytes_are_rejected(clone):
    def edit(fn):
        def f(raw):
            d = json.loads(raw)
            fn(d)
            return (json.dumps(d, indent=2, sort_keys=True) + "\n").encode()
        return f
    forged = (edit(lambda d: d.__setitem__("base", "0" * 40)), edit(lambda d: d.__setitem__("base_tree", "0" * 40)),
              edit(lambda d: d["source_blobs"].__setitem__(WEIGHTS, "0" * 40)), edit(lambda d: d["base_blobs"].__setitem__(T.REGISTRY, "0" * 40)),
              edit(lambda d: d["source_modes"].__setitem__(WEIGHTS, "100755")), edit(lambda d: d["base_modes"].__setitem__(T.REGISTRY, "100755")),
              edit(lambda d: d["source_blobs"].pop("tests/ci_v4_lean_b2_scope.py")), edit(lambda d: d.__setitem__("extra", 1)),
              edit(lambda d: d.__setitem__("authorization", "broader")), edit(lambda d: d.__setitem__("schema_version", "OTHER")),
              lambda b: b.rstrip(b"\n"), lambda b: b.replace(b"  ", b"   ", 1))
    for fn in forged:
        assert _rejected(clone, _variant(clone, {T.MANIFEST: fn}))


def test_mode_symlink_deletion_and_unowned_paths_are_rejected(clone):
    assert _rejected(clone, _variant(clone, mode=WEIGHTS))
    assert _rejected(clone, _variant(clone, remove=(WEIGHTS,)))
    for path in ("tools/ci_v4_lean_extra.py", ".github/workflows/lean_b2.yml", "docs/ci_v4/lean_b2/EXTRA.md", "tests/test_lean_b2_unowned.py"):
        f = clone / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x = 1\n")
        _g(clone, "add", "-A")
        _g(clone, "commit", "-q", "-m", "unowned")
        ref = _g(clone, "rev-parse", "HEAD").decode().strip()
        _g(clone, "checkout", "-q", "-f", "HEAD~1")
        _g(clone, "clean", "-fdxq")
        assert _rejected_by_closure(clone, ref), path


def test_wrong_ancestor_and_older_refs_are_rejected(clone):
    assert not T.signature_ok(clone, T.BASE) and not T.exact_blobs_ok(clone, T.BASE)              # accepted main carries no B2 manifest
    first = _g(clone, "rev-list", "--max-parents=0", "HEAD").decode().split()[0]
    assert not T.signature_ok(clone, first) and not T.exact_blobs_ok(clone, first)


def test_allowed_path_is_gated_by_the_cohort_signature_and_never_admits_foreign_paths(clone):
    for p in ("financial_engine/tax/engine.py", "app/v2/router.py", "tools/ci_v4_select.py", "docs/ci_v4/ci-v4-policy.json"):
        assert not T.allowed_path(p)
    assert T.allowed_path(WEIGHTS) and T.allowed_path(T.MANIFEST) and T.protected_blobs() == {}
    bad = _variant(clone, {T.MANIFEST: lambda b: b.replace(b'"base_tree": "af0a7144', b'"base_tree": "03a7144', 1)})
    assert not T.allowed_path(WEIGHTS, clone, bad)


def test_supersession_is_pin_exact_and_cross_path_safe():
    pins = T.manifest()["source_blobs"]
    reg = pins[T.REGISTRY]
    assert B1.supersedes(T.REGISTRY, reg)
    assert not B1.supersedes(T.REGISTRY, "0" * 40)
    assert not B1.supersedes(T.REGISTRY, pins[T.PREDECESSOR])
    assert not B1.supersedes(T.REGISTRY, T.manifest()["base_blobs"][T.REGISTRY])
