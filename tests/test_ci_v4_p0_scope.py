"""Finite P0 candidate admission: positive closure and independent tamper controls.

No workflow is activated, no old manifest is repinned, no historical test is
removed. Committed variants are data; the mutated Python is never executed.
"""
import json
from pathlib import Path
import subprocess

import pytest
from tests import ci_v4_p0_scope as T
from tests import ci_v4_full_recovery_scope as F
from tests import fin_v2_cohorts as C

ROOT = Path(__file__).resolve().parents[1]
MODULE = "tests/ci_v4_p0_scope.py"


def git(root, *args):
    return subprocess.check_output(["git", "-c", "user.name=scope-test", "-c",
        "user.email=noreply@users.noreply.github.com", "-c", "commit.gpgsign=false", *args], cwd=root)


@pytest.fixture(scope="module")
def subject(tmp_path_factory):
    root = tmp_path_factory.mktemp("p0-source") / "subject"
    git(ROOT, "clone", "--quiet", "--shared", str(ROOT), str(root))
    return root


def rejected(root, path, transform=None, mode=False, remove=False, symlink=False):
    head = git(root, "rev-parse", "HEAD").decode().strip()
    f = root / path
    try:
        if remove: f.unlink()
        elif symlink: f.unlink(); f.symlink_to("README.md")
        elif mode: f.chmod(f.stat().st_mode | 0o111)
        else: f.write_bytes(transform(f.read_bytes()))
        git(root, "add", "-A")
        git(root, "commit", "--quiet", "--allow-empty", "-m", "negative variant")
        ref = git(root, "rev-parse", "HEAD").decode().strip()
        with C.call_scope():
            return not T.exact_blobs_ok(root, ref) and not C.valid(root, ref)
    finally:
        git(root, "reset", "--hard", "--quiet", head)
        git(root, "clean", "-fdxq")


def test_current_source_has_one_registered_terminal_successor():
    assert C.COHORT_MODULES == T.BASE_COHORTS + (T.__name__,)
    assert C.COHORT_MODULES.count(T.__name__) == 1
    assert F._next() is T and F.SUCCESSOR == T.__name__
    assert T.BASE == "955952c1bc16b21ce342121c5224a19d3e105aa7"
    assert git(ROOT, "rev-parse", T.BASE + "^{tree}").decode().strip() == T.BASE_TREE
    with C.call_scope():
        assert T.signature_ok() and T.reviewed_edits_ok() and T.exact_blobs_ok()
        assert all(m.exact_blobs_ok() for m in C.cohorts())
        assert C.valid()


def test_literal_file_set_modes_handoffs_and_frozen_control_sources():
    d = T.manifest()
    assert set(d["source_blobs"]) == T.OWNED_PATHS
    assert set(d["base_blobs"]) == T.SUPERSEDED
    assert set(T.HANDOFFS) == T.HANDOFF_PATHS
    assert not T.CI_PATHS and T.REPLACED == {'tests/conftest.py', 'tests/test_rc7c_candidate_successor.py', 'tests/test_v9p2a_odr_successor.py'}
    assert not any(p.startswith(T.FORBIDDEN) or "*" in p for p in T.OWNED_PATHS)
    for p in T.HANDOFFS:
        assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)
    for p in T.FROZEN:
        assert (ROOT / p).read_bytes() == git(ROOT, "show", T.BASE + ":" + p)
    for p in T.CURRENT_MAPS:
        assert (ROOT / p).read_bytes() == T.expected_map(ROOT, p)
    assert not T.allowed_path("docs/ci_v5/epoch.json")
    assert not T.allowed_path("tools/ci_v4_extra.py")


@pytest.mark.parametrize("path", sorted(T.OWNED_PATHS | {T.MANIFEST}))
def test_one_byte_in_each_owned_file_fails_closed(subject, path):
    assert rejected(subject, path, lambda b: b + b"\n"), path


@pytest.mark.parametrize("attack", ["base", "tree", "pin", "mode", "extra", "authorization"])
def test_forged_source_manifest_is_rejected(subject, attack):
    def change(raw):
        d = json.loads(raw)
        if attack == "base": d["base"] = "0" * 40
        elif attack == "tree": d["base_tree"] = "0" * 40
        elif attack == "pin": d["source_blobs"][MODULE] = "0" * 40
        elif attack == "mode": d["source_modes"][MODULE] = "100755"
        elif attack == "extra": d["source_blobs"]["app/unapproved.py"] = "0" * 40
        elif attack == "authorization": d["authorization"] += " broader"
        return (json.dumps(d, indent=2, sort_keys=True) + "\n").encode()
    assert rejected(subject, T.MANIFEST, change)


@pytest.mark.parametrize("attack", ["mode", "delete", "symlink"])
def test_file_identity_changes_rejected(subject, attack):
    assert rejected(subject, MODULE, mode=attack == "mode", remove=attack == "delete", symlink=attack == "symlink")


@pytest.mark.parametrize("name", ["duplicate", "missing", "swapped"])
def test_terminal_registry_attacks_rejected(subject, name):
    def change(raw):
        tail = b"'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope')"
        assert raw.count(tail) == 1
        new = {"duplicate": tail[:-1] + b", 'tests.ci_v4_p0_scope')",
               "missing": b"'tests.ci_v4_full_recovery_scope')",
               "swapped": b"'tests.ci_v4_p0_scope', 'tests.ci_v4_full_recovery_scope')"}[name]
        return raw.replace(tail, new)
    assert rejected(subject, T.REGISTRY, change)


def test_positive_negative_restoration_and_ref_separation(subject):
    doc = "docs/ci_v4/p0_40min/candidate/full_coverage.py"
    raw = (subject / doc).read_bytes()
    with C.call_scope(): assert T.exact_blobs_ok(subject)
    try:
        (subject / doc).write_bytes(raw + b"\n")
        with C.call_scope():
            assert not T.exact_blobs_ok(subject)
            assert T.exact_blobs_ok(subject, "HEAD")
        assert not C._CALL
    finally: (subject / doc).write_bytes(raw)
    with C.call_scope(): assert T.exact_blobs_ok(subject)
    assert not C._CALL


def test_foreign_path_fails_full_closure(subject):
    p = "docs/ci_v4/p0_40min/UNAPPROVED.md"
    try:
        (subject / p).write_text("synthetic negative control\n")
        with C.call_scope():
            assert T.signature_ok(subject)
            assert not T.exact_blobs_ok(subject) and not C.valid(subject)
    finally: (subject / p).unlink()
