"""V10 dormant native-shadow exact-content successor: recognition of exactly the approved V10 paths on top of the OD-R checkpoint,
fail-closed negative controls, separation of states.

Every negative control evaluates the REAL validator in ``tests/v10_native_shadow_successor.py`` against synthetic commits built from real
Git objects in a disposable clone (parent = the evaluated HEAD). Nothing is committed to the repository itself.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import quarterly_candidate_recognition as R
import v9p2a_odr_successor as O
import v10_native_shadow_successor as V

ROOT = Path(__file__).resolve().parent.parent
RECOGNISED = V.v10_recognized()
pytestmark = pytest.mark.skipif(not RECOGNISED and V.OWNER_APPROVAL_SHA256 is None,
                                reason="V10 successor not yet carrying a recorded Financial Owner exact-content decision")


def _git(repo, *args, **kwargs):
    return subprocess.check_output(["git", *args], cwd=repo, **kwargs)


@pytest.fixture(scope="module")
def head():
    return _git(ROOT, "rev-parse", "HEAD").decode().strip()


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    clone = tmp_path_factory.mktemp("v10-successor") / "clone"
    subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(ROOT), str(clone)], check=True)
    _git(clone, "config", "user.name", "Synthetic")
    _git(clone, "config", "user.email", "noreply@users.noreply.github.com")
    return clone


def mutate(repo, tmp_path, parent, changes, *, orphan=False):
    env = dict(os.environ, GIT_INDEX_FILE=str(tmp_path / "mutation-index"))
    _git(repo, "read-tree", parent, env=env)
    for path, data in changes.items():
        if data is None:
            _git(repo, "update-index", "--force-remove", path, env=env)
        else:
            sha = _git(repo, "hash-object", "-w", "--stdin", input=data).decode().strip()
            _git(repo, "update-index", "--add", "--cacheinfo", "100644", sha, path, env=env)
    tree = _git(repo, "write-tree", env=env).decode().strip()
    parents = [] if orphan else ["-p", parent]
    return _git(repo, "commit-tree", tree, *parents, input=b"synthetic mutation\n").decode().strip()


def show(repo, ref, path):
    return _git(repo, "show", f"{ref}:{path}")


def assert_rejected(repo, ref, fragment=None):
    problems = V.v10_violations(repo=repo, ref=ref)
    assert problems, "the tampered tree must not be recognised"
    assert not V.v10_recognized(repo=repo, ref=ref)
    assert R.recognized_state(repo=repo, ref=ref) is None
    assert R.candidate_blobs(repo=repo, ref=ref) == {}
    assert not any(R.scope_exempt(p, repo=repo, ref=ref) for p in V.PROTECTED)
    assert V.historical_subject(repo=repo, ref=ref) == ref                 # never relabelled to OD-R
    if fragment:
        assert any(fragment in p for p in problems), problems
    return problems


# ── the repository as it is ─────────────────────────────────────────────────────

def test_contract_constants_are_exact():
    assert len(V.PROTECTED) == 18
    assert {p for p in V.PROTECTED if not p.startswith("financial_engine/native_v10/")} == {
        "financial_engine/senior_debt/solver.py", "financial_engine/shl/production.py"}
    assert all(before is None for p, (before, _a) in V.PROTECTED.items() if p.startswith("financial_engine/native_v10/"))
    assert not any(p.endswith(".so") for p in V.PROTECTED)
    assert V.PROTECTED["financial_engine/shl/production.py"][0] == O.ODR_AUTHORITIES["financial_engine/shl/production.py"]
    assert V.APPLICATION["app/services/production_financial_authority.py"][0] == O.APPLICATION_BLOBS[
        "app/services/production_financial_authority.py"][1]
    assert set(O.HISTORICAL_AUTHORITY_MODULES) <= set(V.HISTORICAL_AUTHORITY_MODULES)
    assert "tests/v9p2a_odr_successor.py" in V.HISTORICAL_AUTHORITY_MODULES
    approval = V.expected_approval()
    for denied in ("native_replace_mode_authorized", "candidate_then_canonical_authorized", "native_activation_authorized",
                   "runtime_compilation_authorized", "stage3_authorized", "merge_authorized", "deployment_authorized"):
        assert approval[denied] is False, denied


def test_real_repository_is_exactly_the_v10_successor(head):
    assert V.v10_violations() == []
    assert R.recognized_state() == "V10"
    blobs = R.candidate_blobs()
    assert blobs == {**O.odr_candidate_authorities(), **V.V10_PROTECTED_BLOBS}
    for path, expected in blobs.items():
        assert V.blob(path) == expected, path
    assert O.odr_recognized() is False                               # the historical OD-R validator is not widened
    assert O.odr_recognized(ref=V.ODR_CHECKPOINT["head"])
    assert V.historical_subject() == V.ODR_CHECKPOINT["head"]
    assert not R.scope_exempt("financial_engine/tax/engine.py") and not R.scope_exempt("finco_core/tax/engine.py")


def test_recognition_is_never_approval_activation_or_release():
    import finance_integrity_governance as fig
    import model_v2_governance as governance
    states = V.states()
    assert states["exact_v10_content_recognized"] is True
    assert states["financial_owner_exact_content_decision"] == "RECORDED_NOT_AUTHENTICATED"
    for denied in ("authenticated_owner_attestation", "native_replace_mode", "native_activation", "stage2_default_enabled",
                   "merge_authorized", "financial_release"):
        assert states[denied] is False, denied
    for path in V.PROTECTED:
        assert not governance.released_engine_authority_matches(path), path
    # recognition grants no approved-frozen exemption: only the two engine files already on the path-only allow-list keep it
    assert {p for p in V.PROTECTED if fig.approved_frozen_path(p)} == {
        "financial_engine/shl/production.py", "financial_engine/senior_debt/solver.py"}
    for module in (V, R):
        assert not any(hasattr(module, name) for name in ("approve", "admit", "release", "activate", "is_approved", "is_released"))
    from financial_engine.native_v10.config import NativeConfig
    assert NativeConfig().mode == "off" and NativeConfig().stage2_experimental is False


# ── negative controls ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", sorted(V.PROTECTED))
def test_one_byte_change_of_each_protected_blob_is_rejected(repo, tmp_path, head, path):
    ref = mutate(repo, tmp_path, head, {path: show(repo, head, path) + b"\n"})
    assert_rejected(repo, ref, f"V10_BLOB_MISMATCH: {path}")


@pytest.mark.parametrize("path", sorted(V.APPLICATION))
def test_one_byte_change_of_each_application_blob_is_rejected(repo, tmp_path, head, path):
    ref = mutate(repo, tmp_path, head, {path: show(repo, head, path) + b"\n"})
    assert_rejected(repo, ref, f"V10_BLOB_MISMATCH: {path}")


@pytest.mark.parametrize("path", ["financial_engine/native_v10/dispatch.py", "financial_engine/shl/production.py"])
def test_deletion_of_a_protected_path_is_rejected(repo, tmp_path, head, path):
    ref = mutate(repo, tmp_path, head, {path: None})
    assert_rejected(repo, ref, f"V10_BLOB_MISMATCH: {path}")


@pytest.mark.parametrize("path", ["financial_engine/native_v10/extra.py", "financial_engine/tax/atad.py", "finco_core/tax/engine.py",
                                  "domain/revenue/new_module.py"])
def test_an_additional_protected_path_is_rejected(repo, tmp_path, head, path):
    data = show(repo, head, path) + b"\n# extra\n" if path in ("financial_engine/tax/atad.py", "finco_core/tax/engine.py") else b"x = 1\n"
    ref = mutate(repo, tmp_path, head, {path: data})
    assert_rejected(repo, ref, "V10_PROTECTED_SCOPE_INVALID")


def test_substituting_the_odr_predecessor_content_is_rejected(repo, tmp_path, head):
    path = "financial_engine/shl/production.py"
    ref = mutate(repo, tmp_path, head, {path: _git(repo, "cat-file", "blob", V.PROTECTED[path][0])})
    assert_rejected(repo, ref, f"V10_BLOB_MISMATCH: {path}")


def test_a_compiled_artifact_is_rejected(repo, tmp_path, head):
    ref = mutate(repo, tmp_path, head, {"financial_engine/native_v10/_fk_v10.so": b"\x7fELF"})
    assert_rejected(repo, ref)


@pytest.mark.parametrize("path", ["tests/v9p2a_odr_successor.py", "tests/finance_integrity_governance.py",
                                  "tests/r_live_lifecycle_content_authority.py"])
def test_a_rewritten_historical_authority_is_rejected(repo, tmp_path, head, path):
    ref = mutate(repo, tmp_path, head, {path: show(repo, head, path) + b"\n# rewritten\n"})
    assert_rejected(repo, ref, f"V10_HISTORICAL_GUARD_CHANGED: {path}")


def test_altered_wiring_is_rejected(repo, tmp_path, head):
    path = "tests/quarterly_candidate_recognition.py"
    ref = mutate(repo, tmp_path, head, {path: show(repo, head, path) + b"\n"})
    assert_rejected(repo, ref, f"V10_WIRING_NOT_EXACT: {path}")


def test_an_altered_owner_record_is_rejected(repo, tmp_path, head):
    data = show(repo, head, V.APPROVAL_PATH).replace(b'"merge_authorized": false', b'"merge_authorized": true')
    ref = mutate(repo, tmp_path, head, {V.APPROVAL_PATH: data})
    assert_rejected(repo, ref, "V10_OWNER_RECORD_NOT_EXACT")


def test_a_removed_owner_record_is_rejected(repo, tmp_path, head):
    ref = mutate(repo, tmp_path, head, {V.APPROVAL_PATH: None})
    assert_rejected(repo, ref, "V10_OWNER_EXACT_CONTENT_DECISION_ABSENT")


def test_native_default_changed_to_candidate_is_rejected(repo, tmp_path, head):
    path = "financial_engine/native_v10/config.py"
    data = show(repo, head, path).replace(b'mode: str = "off"', b'mode: str = "candidate"')
    ref = mutate(repo, tmp_path, head, {path: data})
    problems = assert_rejected(repo, ref)
    assert "V10_NATIVE_DEFAULT_NOT_OFF" in problems and f"V10_BLOB_MISMATCH: {path}" in problems


def test_shadow_enabled_in_a_workflow_is_rejected(repo, tmp_path, head):
    path = ".github/workflows/public_safety_and_smoke.yml"
    data = show(repo, head, path) + b"\nenv:\n  FINCO_NATIVE_V10_SHADOW: stage2\n"
    ref = mutate(repo, tmp_path, head, {path: data})
    assert_rejected(repo, ref, "V10_SHADOW_ENABLED_IN_WORKFLOW")


def test_exact_bytes_without_ancestry_are_rejected(repo, tmp_path, head):
    ref = mutate(repo, tmp_path, head, {}, orphan=True)
    assert all(V.blob(p, ref, repo=repo) == b for p, b in V.V10_PROTECTED_BLOBS.items())
    assert_rejected(repo, ref, "V10_ANCESTRY_INVALID")


@pytest.mark.parametrize("name", ["ODR_CHECKPOINT", "SOURCE_CANDIDATE"])
def test_an_altered_or_missing_checkpoint_is_rejected(monkeypatch, name):
    monkeypatch.setattr(V, "_CACHE", {})
    monkeypatch.setattr(V, name, {"head": "0" * 40, "tree": "0" * 40})
    problems = V.v10_violations()
    assert any(p.startswith("V10_CHECKPOINT_MISSING") for p in problems), problems
    assert R.recognized_state() is None


def test_a_checkpoint_with_a_substituted_tree_is_rejected(monkeypatch):
    monkeypatch.setattr(V, "_CACHE", {})
    monkeypatch.setattr(V, "SOURCE_CANDIDATE", {**V.SOURCE_CANDIDATE, "tree": V.ODR_CHECKPOINT["tree"]})
    assert any(p.startswith("V10_CHECKPOINT_MISSING") for p in V.v10_violations())


def test_a_stale_or_absent_approval_reference_is_rejected(monkeypatch):
    for name, value in (("OWNER_APPROVAL_SHA256", "0" * 64), ("OWNER_APPROVAL_SHA256", None), ("OWNER_APPROVAL_REFERENCE", None)):
        monkeypatch.setattr(V, "_CACHE", {})
        monkeypatch.setattr(V, name, value)
        problems = V.v10_violations()
        assert problems and R.recognized_state() is None, (name, value)
        monkeypatch.undo()
        monkeypatch.setattr(V, "_CACHE", {})


def test_a_manifest_cannot_authorise_unreviewed_content(monkeypatch):
    path = "financial_engine/native_v10/dispatch.py"
    monkeypatch.setattr(V, "_CACHE", {})
    monkeypatch.setattr(V, "PROTECTED", {**V.PROTECTED, path: (None, "1" * 40)})
    problems = V.v10_violations()
    assert f"V10_SOURCE_CANDIDATE_NOT_APPROVED_CONTENT: {path}" in problems and f"V10_BLOB_MISMATCH: {path}" in problems


def test_the_source_candidate_carries_no_approval_record():
    assert V.blob(V.APPROVAL_PATH, V.SOURCE_CANDIDATE["head"]) is None
    assert V.blob("tests/v10_native_shadow_successor.py", V.SOURCE_CANDIDATE["head"]) is None
