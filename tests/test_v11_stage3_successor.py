"""V11 Stage 3 exact-content successor: recognition of exactly the approved V11 paths on top of the V10 checkpoint, fail-closed
negative controls, separation of states.

Every negative control evaluates the REAL validator in ``tests/v11_stage3_successor.py`` against synthetic commits built from real Git
objects in a disposable clone (parent = the evaluated HEAD). Nothing is committed to the repository itself.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import quarterly_candidate_recognition as R
import v10_native_shadow_successor as V10
import v11_stage3_successor as V

ROOT = Path(__file__).resolve().parent.parent
RECOGNISED = V.v11_recognized()
pytestmark = pytest.mark.skipif(not RECOGNISED and V.OWNER_APPROVAL_SHA256 is None,
                                reason="V11 successor not yet carrying a recorded Financial Owner exact-content decision")


def _git(repo, *args, **kwargs):
    return subprocess.check_output(["git", *args], cwd=repo, **kwargs)


@pytest.fixture(scope="module")
def head():
    return _git(ROOT, "rev-parse", "HEAD").decode().strip()


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    clone = tmp_path_factory.mktemp("v11-successor") / "clone"
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
    problems = V.v11_violations(repo=repo, ref=ref)
    assert problems, "the tampered tree must not be recognised"
    assert not V.v11_recognized(repo=repo, ref=ref)
    assert R.recognized_state(repo=repo, ref=ref) is None
    assert R.candidate_blobs(repo=repo, ref=ref) == {}
    assert not any(R.scope_exempt(p, repo=repo, ref=ref) for p in V.PROTECTED)
    assert V.historical_subject(repo=repo, ref=ref) == ref                 # never relabelled to V10
    if fragment:
        assert any(fragment in p for p in problems), problems
    return problems


# ── the repository as it is ─────────────────────────────────────────────────────

def test_contract_constants_are_exact():
    assert len(V.PROTECTED) == 8
    assert {p for p in V.PROTECTED if not p.startswith("financial_engine/native_v11/")} == {"financial_engine/financing/project.py"}
    assert all(before is None for p, (before, _a) in V.PROTECTED.items() if p.startswith("financial_engine/native_v11/"))
    assert not any(p.endswith(".so") for p in V.PROTECTED)
    assert not any(p.startswith("financial_engine/native_v10/") for p in V.PROTECTED)             # no V10 reseal
    import v9p2a_odr_successor as O
    assert V.PROTECTED["financial_engine/financing/project.py"][0] == O.ODR_AUTHORITIES["financial_engine/financing/project.py"]
    assert set(V10.HISTORICAL_AUTHORITY_MODULES) <= set(V.HISTORICAL_AUTHORITY_MODULES)
    assert "tests/v10_native_shadow_successor.py" in V.HISTORICAL_AUTHORITY_MODULES
    approval = V.expected_approval()
    for denied in ("stage3_activation_authorized", "production_enablement_authorized", "staging_enablement_authorized",
                   "v10_reseal_authorized", "runtime_compilation_authorized", "merge_authorized", "deployment_authorized"):
        assert approval[denied] is False, denied


def test_real_repository_is_exactly_the_v11_successor(head):
    assert V.v11_violations() == []
    assert R.recognized_state() == "V11S3"
    blobs = R.candidate_blobs()
    assert blobs == {**V10.v10_candidate_authorities(), **V.V11_PROTECTED_BLOBS}
    for path, expected in blobs.items():
        assert V.blob(path) == expected, path
    assert V10.v10_recognized() is False                                 # the historical V10 validator is not widened
    assert V10.v10_recognized(ref=V.V10_CHECKPOINT["head"])
    assert V.historical_subject() == V.V10_CHECKPOINT["head"]
    assert not R.scope_exempt("financial_engine/tax/engine.py") and not R.scope_exempt("finco_core/tax/engine.py")


def test_recognition_is_never_approval_activation_or_release():
    import model_v2_governance as governance
    states = V.states()
    assert states["exact_v11_content_recognized"] is True
    assert states["financial_owner_exact_content_decision"] == "RECORDED_NOT_AUTHENTICATED"
    for denied in ("authenticated_owner_attestation", "v10_reseal", "merge_authorized", "financial_release"):
        assert states[denied] is False, denied
    # activation / production enablement only through the separate owner release authority, never through this record
    import v11_stage3_release_authority as release
    assert states["stage3_activation"] is states["production_enablement"] is release.release_recognized()
    assert V.expected_approval()["stage3_activation_authorized"] is False
    for path in V.PROTECTED:
        assert not governance.released_engine_authority_matches(path), path
    for module in (V, R):
        assert not any(hasattr(module, name) for name in ("approve", "admit", "release", "activate", "is_approved", "is_released"))
    from financial_engine.native_v11.config import Stage3Config
    from financial_engine.native_v10.config import NativeConfig
    assert Stage3Config().mode == "off" and NativeConfig().mode == "off" and NativeConfig().stage2_experimental is False


# ── negative controls ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", sorted(V.PROTECTED))
def test_one_byte_change_of_each_protected_blob_is_rejected(repo, tmp_path, head, path):
    ref = mutate(repo, tmp_path, head, {path: show(repo, head, path) + b"\n"})
    assert_rejected(repo, ref, f"V11_BLOB_MISMATCH: {path}")


@pytest.mark.parametrize("path", ["financial_engine/native_v11/stage3.py", "financial_engine/financing/project.py"])
def test_deletion_of_a_protected_path_is_rejected(repo, tmp_path, head, path):
    ref = mutate(repo, tmp_path, head, {path: None})
    assert_rejected(repo, ref, f"V11_BLOB_MISMATCH: {path}")


@pytest.mark.parametrize("path", ["financial_engine/native_v11/extra.py", "financial_engine/tax/atad.py", "finco_core/tax/engine.py",
                                  "domain/revenue/new_module.py"])
def test_an_additional_protected_path_is_rejected(repo, tmp_path, head, path):
    data = show(repo, head, path) + b"\n# extra\n" if path in ("financial_engine/tax/atad.py", "finco_core/tax/engine.py") else b"x = 1\n"
    ref = mutate(repo, tmp_path, head, {path: data})
    assert_rejected(repo, ref, "V11_PROTECTED_SCOPE_INVALID")


@pytest.mark.parametrize("path", ["financial_engine/native_v10/approved_canonical_blobs.json",
                                  "financial_engine/native_v10/fk_v10_manifest.json", "financial_engine/native_v10/kernel_v10.c",
                                  "financial_engine/native_v10/stage2.py"])
def test_a_v10_reseal_or_kernel_change_is_rejected(repo, tmp_path, head, path):
    ref = mutate(repo, tmp_path, head, {path: show(repo, head, path) + b"\n"})
    assert_rejected(repo, ref, "V11_PROTECTED_SCOPE_INVALID")


def test_substituting_the_v10_predecessor_hook_file_is_rejected(repo, tmp_path, head):
    path = "financial_engine/financing/project.py"
    ref = mutate(repo, tmp_path, head, {path: _git(repo, "cat-file", "blob", V.PROTECTED[path][0])})
    assert_rejected(repo, ref, f"V11_BLOB_MISMATCH: {path}")


@pytest.mark.parametrize("path", ["financial_engine/native_v11/_fk_v11_stage3.so", "financial_engine/native_v10/_fk_v10.so"])
def test_a_compiled_artifact_is_rejected(repo, tmp_path, head, path):
    ref = mutate(repo, tmp_path, head, {path: b"\x7fELF"})
    assert_rejected(repo, ref)


@pytest.mark.parametrize("path", ["tests/v10_native_shadow_successor.py", "tests/v9p2a_odr_successor.py",
                                  "tests/finance_integrity_governance.py", "docs/model_v10/v10-native-shadow-content-approval.json"])
def test_a_rewritten_historical_authority_is_rejected(repo, tmp_path, head, path):
    ref = mutate(repo, tmp_path, head, {path: show(repo, head, path) + b"\n"})
    assert_rejected(repo, ref, f"V11_HISTORICAL_GUARD_CHANGED: {path}")


def test_altered_wiring_is_rejected(repo, tmp_path, head):
    path = "tests/quarterly_candidate_recognition.py"
    ref = mutate(repo, tmp_path, head, {path: show(repo, head, path) + b"\n"})
    assert_rejected(repo, ref, f"V11_WIRING_NOT_EXACT: {path}")


def test_an_altered_owner_record_is_rejected(repo, tmp_path, head):
    data = show(repo, head, V.APPROVAL_PATH).replace(b'"merge_authorized": false', b'"merge_authorized": true')
    ref = mutate(repo, tmp_path, head, {V.APPROVAL_PATH: data})
    assert_rejected(repo, ref, "V11_OWNER_RECORD_NOT_EXACT")


def test_a_removed_owner_record_is_rejected(repo, tmp_path, head):
    ref = mutate(repo, tmp_path, head, {V.APPROVAL_PATH: None})
    assert_rejected(repo, ref, "V11_OWNER_EXACT_CONTENT_DECISION_ABSENT")


def test_stage3_default_changed_to_candidate_is_rejected(repo, tmp_path, head):
    path = "financial_engine/native_v11/config.py"
    data = show(repo, head, path).replace(b'mode: str = "off"', b'mode: str = "candidate"')
    ref = mutate(repo, tmp_path, head, {path: data})
    problems = assert_rejected(repo, ref)
    assert "V11_STAGE3_DEFAULT_NOT_OFF" in problems and f"V11_BLOB_MISMATCH: {path}" in problems


@pytest.mark.parametrize("path,addition", [
    ("app/runtime/native_activation.py", b"\nfrom financial_engine.native_v11.config import Stage3Config\n"),
    ("main_web.py", b"\n# stage3_run\n"),
    (".github/workflows/public_safety_and_smoke.yml", b"\n# native_v11\n"),
    ("tools/native_v10_release.py", b"\n# native_v11\n"),
])

# F01 Correction C: a CI workflow listing the native_v11 directory for
# read-only ownership checks is not an activation path. Its exact reviewed
# content is recognized as test-only, and every mutation is rejected.
def test_finval_f01_acceptance_is_exact_nonactivation_workflow(head):
    path = V.F01_TEST_ONLY_WORKFLOW
    assert V.blob(path) == V.F01_TEST_ONLY_BLOB
    assert V._exact_f01_nonactivation_workflow(path, head, V.ROOT)
    assert V.v11_violations() == []


@pytest.mark.parametrize("name,append", [
    ("one_byte", b"\n"),
    ("native_enable", b"\nenv:\n  FINCO_NATIVE_V11_RUN: 'on'\n"),
    ("deploy", b"\n  - run: ./deploy/scripts/release_native.sh\n"),
    ("write_permission", b"\npermissions:\n  contents: write\n"),
    ("elevated_oidc", b"\npermissions:\n  id-token: write\n"),
    ("new_release_step", b"\n  - run: gh release create v0\n"),
])
def test_finval_f01_modified_workflow_is_unreleased_activation(repo, tmp_path, head, name, append):
    path = V.F01_TEST_ONLY_WORKFLOW
    altered = show(repo, head, path) + append
    ref = mutate(repo, tmp_path, head, {path: altered})
    assert not V._exact_f01_nonactivation_workflow(path, ref, repo), name
    problems = assert_rejected(repo, ref, "V11_STAGE3_ACTIVATION_SURFACE")
    assert any(path in problem for problem in problems)


def test_f01_exception_never_whitelists_another_workflow(repo, tmp_path, head):
    path = ".github/workflows/unapproved_v11_activation.yml"
    ref = mutate(repo, tmp_path, head, {path: b"name: release\n# native_v11\n"})
    assert not V._exact_f01_nonactivation_workflow(path, ref, repo)
    assert_rejected(repo, ref, "V11_STAGE3_ACTIVATION_SURFACE")


def test_an_activation_surface_referencing_stage3_is_rejected(repo, tmp_path, head, path, addition):
    ref = mutate(repo, tmp_path, head, {path: show(repo, head, path) + addition})
    assert_rejected(repo, ref, "V11_STAGE3_ACTIVATION_SURFACE")


def test_exact_bytes_without_ancestry_are_rejected(repo, tmp_path, head):
    ref = mutate(repo, tmp_path, head, {}, orphan=True)
    assert all(V.blob(p, ref, repo=repo) == b for p, b in V.V11_PROTECTED_BLOBS.items())
    assert_rejected(repo, ref, "V11_ANCESTRY_INVALID")


@pytest.mark.parametrize("name", ["V10_CHECKPOINT", "SOURCE_CANDIDATE"])
def test_an_altered_or_missing_checkpoint_is_rejected(monkeypatch, name):
    monkeypatch.setattr(V, "_CACHE", {})
    monkeypatch.setattr(V, name, {"head": "0" * 40, "tree": "0" * 40})
    problems = V.v11_violations()
    assert any(p.startswith("V11_CHECKPOINT_MISSING") for p in problems), problems
    assert R.recognized_state() is None


def test_a_checkpoint_with_a_substituted_tree_is_rejected(monkeypatch):
    monkeypatch.setattr(V, "_CACHE", {})
    monkeypatch.setattr(V, "SOURCE_CANDIDATE", {**V.SOURCE_CANDIDATE, "tree": V.V10_CHECKPOINT["tree"]})
    assert any(p.startswith("V11_CHECKPOINT_MISSING") for p in V.v11_violations())


def test_a_stale_or_absent_approval_reference_is_rejected(monkeypatch):
    for name, value in (("OWNER_APPROVAL_SHA256", "0" * 64), ("OWNER_APPROVAL_SHA256", None), ("OWNER_APPROVAL_REFERENCE", None)):
        monkeypatch.setattr(V, "_CACHE", {})
        monkeypatch.setattr(V, name, value)
        problems = V.v11_violations()
        assert problems and R.recognized_state() is None, (name, value)
        monkeypatch.undo()
        monkeypatch.setattr(V, "_CACHE", {})


def test_a_manifest_cannot_authorise_unreviewed_content(monkeypatch):
    path = "financial_engine/native_v11/stage3.py"
    monkeypatch.setattr(V, "_CACHE", {})
    monkeypatch.setattr(V, "PROTECTED", {**V.PROTECTED, path: (None, "1" * 40)})
    problems = V.v11_violations()
    assert f"V11_SOURCE_CANDIDATE_NOT_APPROVED_CONTENT: {path}" in problems and f"V11_BLOB_MISMATCH: {path}" in problems


def test_v10_invalid_at_its_checkpoint_rejects_v11(monkeypatch):
    monkeypatch.setattr(V10, "_CACHE", {})
    monkeypatch.setattr(V, "_CACHE", {})
    monkeypatch.setattr(V10, "OWNER_APPROVAL_SHA256", "0" * 64)
    assert "V11_HISTORICAL_V10_INVALID" in V.v11_violations()
    assert R.recognized_state() is None


def test_the_source_candidate_carries_no_approval_record():
    assert V.blob(V.APPROVAL_PATH, V.SOURCE_CANDIDATE["head"]) is None
    # the candidate predates this successor: it carries no owner decision of any kind
    assert V.blob("tests/v11_stage3_successor.py", V.SOURCE_CANDIDATE["head"]) is None
