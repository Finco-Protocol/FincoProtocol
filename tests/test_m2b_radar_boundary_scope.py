"""Cohort #49 (M2-B Model/Radar boundary) positive closure and negative tamper tests."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest
from tests import ci_v4_p0_scope as P0
from tests import fin_v2_cohorts as C
from tests import m2b_radar_boundary_scope as T

ROOT = Path(__file__).resolve().parents[1]
MODULE = "tests/m2b_radar_boundary_scope.py"


def git(root, *args):
    return subprocess.check_output(
        ["git", "-c", "user.name=scope-test", "-c", "user.email=noreply@users.noreply.github.com", "-c", "commit.gpgsign=false", *args],
        cwd=root,
    )


@pytest.fixture(scope="module")
def subject(tmp_path_factory):
    root = tmp_path_factory.mktemp("m2b-source") / "subject"
    git(ROOT, "clone", "--quiet", "--shared", str(ROOT), str(root))
    return root


def rejected(root, path, transform=None, mode=False, remove=False, symlink=False, check_composite=False):
    head = git(root, "rev-parse", "HEAD").decode().strip()
    f = root / path
    try:
        if remove:
            f.unlink()
        elif symlink:
            f.unlink()
            f.symlink_to("README.md")
        elif mode:
            f.chmod(f.stat().st_mode | 0o111)
        else:
            f.write_bytes(transform(f.read_bytes()))
        # Verify physical working-tree rejection before committing
        with T.scoped():
            wt_rejected = not T.exact_blobs_ok(root)
        git(root, "add", "-A")
        git(root, "commit", "--quiet", "--allow-empty", "-m", "negative variant")
        ref = git(root, "rev-parse", "HEAD").decode().strip()
        with T.scoped():
            ref_rejected = not T.exact_blobs_ok(root, ref)
        if check_composite:
            with C.call_scope():
                ref_rejected = ref_rejected and (not C.valid(root, ref))
        return wt_rejected and ref_rejected
    finally:
        git(root, "reset", "--hard", "--quiet", head)
        git(root, "clean", "-fdxq")


def test_m2b_cohort49_positive_closure_and_composite_valid():
    assert C.COHORT_MODULES == T.BASE_COHORTS + (T.__name__,)
    assert C.COHORT_MODULES.count(T.__name__) == 1
    assert P0._next() is T and P0.SUCCESSOR == T.__name__
    assert git(ROOT, "rev-parse", T.BASE + "^{tree}").decode().strip() == T.BASE_TREE
    with C.call_scope():
        assert T.signature_ok() and T.reviewed_edits_ok() and T.exact_blobs_ok()
        assert all(m.exact_blobs_ok() for m in C.cohorts())
        assert C.valid()


def test_m2b_forbidden_and_frozen_invariants():
    assert not any(p.startswith(T.FORBIDDEN) or "*" in p for p in T.OWNED_PATHS | {T.MANIFEST})
    for p in T.FROZEN:
        assert (ROOT / p).read_bytes() == git(ROOT, "show", T.BASE + ":" + p)
    for p in T.HANDOFFS:
        assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)
    for p in T.CURRENT_MAPS:
        assert (ROOT / p).read_bytes() == T.expected_map(ROOT, p)
    assert not T.allowed_path("financial_engine/__init__.py")
    assert not T.allowed_path("app/v2/router.py")
    assert not T.allowed_path(".github/workflows/ci_v4_pr.yml")


@pytest.mark.parametrize("path", [
    "main_web.py",
    "main_api.py",
    "app/protocol_ui/router.py",
    "app/internal_auth_introspect.py",
    "tests/test_m2b_model_radar_boundary.py",
    MODULE,
    T.MANIFEST,
])
def test_owned_file_tamper_fails_closed(subject, path):
    assert rejected(subject, path, lambda b: b + b"\n", check_composite=(path == "main_web.py")), path


@pytest.mark.parametrize("path", [
    "financial_engine/__init__.py",
    "app/auth.py",
    ".github/workflows/ci_v4_pr.yml",
])
def test_unrelated_protected_or_app_file_tamper_fails_closed(subject, path):
    assert rejected(subject, path, lambda b: b + b"\n", check_composite=(path == "financial_engine/__init__.py")), path


@pytest.mark.parametrize("attack", ["base", "tree", "pin", "mode", "extra", "authorization"])
def test_forged_manifest_rejected(subject, attack):
    def change(raw):
        d = json.loads(raw)
        if attack == "base":
            d["base"] = "0" * 40
        elif attack == "tree":
            d["base_tree"] = "0" * 40
        elif attack == "pin":
            d["source_blobs"]["main_web.py"] = "0" * 40
        elif attack == "mode":
            d["source_modes"]["main_web.py"] = "100755"
        elif attack == "extra":
            d["source_blobs"]["app/unapproved.py"] = "0" * 40
        elif attack == "authorization":
            d["authorization"] += " broader"
        return (json.dumps(d, indent=2, sort_keys=True) + "\n").encode()
    assert rejected(subject, T.MANIFEST, change, check_composite=(attack == "pin"))


@pytest.mark.parametrize("attack", ["mode", "delete", "symlink"])
def test_file_identity_tamper_rejected(subject, attack):
    assert rejected(subject, "app/internal_auth_introspect.py", mode=attack == "mode", remove=attack == "delete", symlink=attack == "symlink")
