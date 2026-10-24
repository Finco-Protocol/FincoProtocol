"""V11 Stage 3 + V10 Stage 1+2 permanent production release authority: recognition of exactly the owner-released release surface on
top of the V11 exact-content checkpoint, the content successor's activation-surface rule delegated to it, fail-closed negative
controls, separation of states.

Every negative control evaluates the REAL validators (``tests/v11_stage3_release_authority.py`` and ``tests/v11_stage3_successor.py``)
against synthetic commits built from real Git objects in a disposable clone (parent = the evaluated HEAD). Nothing is committed to
the repository itself.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import quarterly_candidate_recognition as R
import v11_stage3_release_authority as A
import v11_stage3_successor as V
from test_v11_stage3_successor import mutate, show  # noqa: F401 - shared synthetic-commit harness
from test_v11_stage3_successor import head, repo  # noqa: F401 - fixtures

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(A.OWNER_RELEASE_SHA256 is None or A.RELEASE_CANDIDATE["head"] is None,
                                reason="release authority not yet carrying a recorded Financial Owner release decision")


def assert_release_rejected(repo, ref, fragment=None):  # noqa: F811
    problems = A.release_violations(repo=repo, ref=ref)
    assert problems, "the tampered tree must not be released"
    assert A.released_surfaces(repo=repo, ref=ref) == frozenset()
    assert A.states(repo=repo, ref=ref)["production_enablement"] is False
    if fragment:
        assert any(fragment in p for p in problems), problems
    return problems


def assert_activation_closed(repo, ref):  # noqa: F811
    """Without a recognised release, the referencing release-surface sources are an unreleased activation path."""
    problems = V.v11_violations(repo=repo, ref=ref)
    assert any(p.startswith("V11_STAGE3_ACTIVATION_SURFACE") for p in problems), problems
    assert R.recognized_state(repo=repo, ref=ref) is None
    assert V.states(repo=repo, ref=ref)["stage3_activation"] is False


# ── the repository as it is ─────────────────────────────────────────────────────────

def test_contract_constants_are_exact():
    from tools import native_release as rel

    assert set(A.RELEASE_SURFACE) == {"app/runtime/native_activation.py", "tools/native_release.py",
                                      "deploy/scripts/release_native.sh", "deploy/systemd/finco-web.service",
                                      "deploy/env.example"}
    assert not any(p.startswith(V.PROTECTED_PREFIXES) or p.endswith(".so") for p in A.RELEASE_SURFACE)   # no engine content
    assert not set(A.RELEASE_SURFACE) & set(V.PROTECTED)
    activation = dict(line.split("=", 1) for line in rel.activation_text().splitlines() if line and not line.startswith("#"))
    assert activation == A.ACTIVATION
    for name, path in A.MANIFESTS.items():
        manifest = json.loads((ROOT / path).read_text())
        assert {k: manifest[k] for k in A.RUNTIME_IDENTITIES[name]} == A.RUNTIME_IDENTITIES[name], name
    release = A.expected_release()
    for granted in ("stage3_activation_authorized", "production_enablement_authorized", "v10_stage12_production_release_authorized",
                    "permanent"):
        assert release[granted] is True, granted
    for denied in ("phased_rollout", "pilot_or_canary", "staging_enablement_authorized", "v10_reseal_authorized",
                   "runtime_compilation_authorized", "thread_mode_native_authorized", "merge_authorized"):
        assert release[denied] is False, denied
    assert release["content_approval"] == {"path": V.APPROVAL_PATH, "sha256": V.OWNER_APPROVAL_SHA256,
                                           "protected_blobs": V.V11_PROTECTED_BLOBS}


def test_real_repository_is_exactly_the_released_v11_successor(head):  # noqa: F811
    assert A.release_violations() == []
    assert A.released_surfaces() == frozenset(A.RELEASE_SURFACE)
    assert V.v11_violations() == [] and R.recognized_state() == "V11S3"
    for path, (_before, after) in A.RELEASE_SURFACE.items():
        assert V.blob(path) == after, path
    raw = (ROOT / V.APPROVAL_PATH).read_bytes()                              # the content record is untouched
    assert hashlib.sha256(raw).hexdigest() == V.OWNER_APPROVAL_SHA256
    assert json.loads(raw)["stage3_activation_authorized"] is False           # and still says what it said
    assert hashlib.sha256((ROOT / A.RELEASE_PATH).read_bytes()).hexdigest() == A.OWNER_RELEASE_SHA256


def test_release_states_grant_exactly_the_release_and_nothing_more():
    states, content = A.states(), V.states()
    for granted in ("exact_release_content_recognized", "stage3_activation", "production_enablement",
                    "v10_stage12_production_release"):
        assert states[granted] is True, granted
    assert states["financial_owner_release_decision"] == "RECORDED_NOT_AUTHENTICATED"
    for denied in ("authenticated_owner_attestation", "phased_rollout", "staging_enablement", "v10_reseal", "runtime_compilation",
                   "merge_authorized", "financial_release"):
        assert states[denied] is False, denied
    assert content["stage3_activation"] is content["production_enablement"] is True
    for denied in ("v10_reseal", "merge_authorized", "financial_release", "authenticated_owner_attestation"):
        assert content[denied] is False, denied
    assert not any(hasattr(A, name) for name in ("approve", "admit", "release", "activate", "is_approved", "is_released"))


# ── negative controls ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", sorted(A.RELEASE_SURFACE))
def test_one_byte_change_of_each_release_surface_is_rejected(repo, tmp_path, head, path):  # noqa: F811
    ref = mutate(repo, tmp_path, head, {path: show(repo, head, path) + b"\n"})
    assert_release_rejected(repo, ref, f"V11R_RELEASE_BLOB_MISMATCH: {path}")
    assert_activation_closed(repo, ref)


def test_without_the_owner_release_record_there_is_no_activation_path(repo, tmp_path, head):  # noqa: F811
    ref = mutate(repo, tmp_path, head, {A.RELEASE_PATH: None})
    assert_release_rejected(repo, ref, "V11R_OWNER_RELEASE_DECISION_ABSENT")
    assert_activation_closed(repo, ref)


@pytest.mark.parametrize("change", ["byte", "phased", "merge", "staging"])
def test_a_tampered_release_record_is_rejected(repo, tmp_path, head, change):  # noqa: F811
    record = json.loads(show(repo, head, A.RELEASE_PATH))
    if change == "byte":
        data = show(repo, head, A.RELEASE_PATH) + b" "
    else:
        record[{"phased": "phased_rollout", "merge": "merge_authorized", "staging": "staging_enablement_authorized"}[change]] = True
        data = json.dumps(record, sort_keys=True, indent=2).encode()
    ref = mutate(repo, tmp_path, head, {A.RELEASE_PATH: data})
    assert_release_rejected(repo, ref, "V11R_OWNER_RELEASE_RECORD_NOT_EXACT")
    assert_activation_closed(repo, ref)


def test_a_changed_content_record_is_rejected_by_both(repo, tmp_path, head):  # noqa: F811
    ref = mutate(repo, tmp_path, head, {V.APPROVAL_PATH: show(repo, head, V.APPROVAL_PATH) + b" "})
    assert_release_rejected(repo, ref, "V11R_CONTENT_RECORD_NOT_EXACT")
    assert "V11_OWNER_RECORD_NOT_EXACT" in V.v11_violations(repo=repo, ref=ref)


def test_a_changed_runtime_identity_is_rejected(repo, tmp_path, head):  # noqa: F811
    path = A.MANIFESTS["v11_stage3"]
    manifest = json.loads(show(repo, head, path))
    manifest["build_id"] = "0" * 64
    ref = mutate(repo, tmp_path, head, {path: json.dumps(manifest, indent=2).encode()})
    assert_release_rejected(repo, ref, "V11R_RUNTIME_IDENTITY_MISMATCH: v11_stage3")
    assert f"V11_BLOB_MISMATCH: {path}" in V.v11_violations(repo=repo, ref=ref)


@pytest.mark.parametrize("path", ["deploy/scripts/backup.sh", "app/services/run_service.py", "deploy/systemd/finco-staging.service"])
def test_a_new_unreleased_activation_surface_is_rejected_while_the_release_stays_exact(repo, tmp_path, head, path):  # noqa: F811
    ref = mutate(repo, tmp_path, head, {path: show(repo, head, path) + b"\n# FINCO native_v11 stage3_run\n"})
    assert A.release_violations(repo=repo, ref=ref) == []                   # the released surface itself is intact
    problems = V.v11_violations(repo=repo, ref=ref)
    assert f"V11_STAGE3_ACTIVATION_SURFACE: {[path]}" in problems, problems
    assert R.recognized_state(repo=repo, ref=ref) is None


def test_exact_bytes_without_ancestry_are_rejected(repo, tmp_path, head):  # noqa: F811
    ref = mutate(repo, tmp_path, head, {}, orphan=True)
    assert_release_rejected(repo, ref, "V11R_ANCESTRY_INVALID")


@pytest.mark.parametrize("name", ["CONTENT_CHECKPOINT", "RELEASE_CANDIDATE"])
def test_an_altered_or_missing_release_checkpoint_is_rejected(monkeypatch, name):
    monkeypatch.setattr(A, "_CACHE", {})
    monkeypatch.setattr(V, "_CACHE", {})
    monkeypatch.setattr(A, name, {"head": "0" * 40, "tree": "0" * 40})
    problems = A.release_violations()
    assert any(p.startswith("V11R_CHECKPOINT_MISSING") for p in problems), problems
    assert A.released_surfaces() == frozenset() and R.recognized_state() is None


def test_a_stale_or_absent_release_reference_is_rejected(monkeypatch):
    for name, value in (("OWNER_RELEASE_SHA256", "0" * 64), ("OWNER_RELEASE_SHA256", None), ("OWNER_RELEASE_REFERENCE", None)):
        monkeypatch.setattr(A, "_CACHE", {})
        monkeypatch.setattr(V, "_CACHE", {})
        with monkeypatch.context() as m:
            m.setattr(A, name, value)
            assert A.release_violations() != [] and A.states()["production_enablement"] is False
            assert R.recognized_state() is None
