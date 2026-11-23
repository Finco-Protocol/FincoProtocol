"""R-LIVE Python 3.10 exact-content successor (issue #348): recognition of exactly one changed R-LIVE blob on top of the PR #346
checkpoint, fail-closed negative controls, PR #346 history preserved.

Every negative control evaluates the REAL validator in ``tests/r_live_lifecycle_py310_successor.py`` against synthetic commits built
from real Git objects in a disposable clone (parent = the evaluated HEAD). Nothing is committed to the repository itself.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import r_live_lifecycle_content_authority as A
import r_live_lifecycle_governance as adapter
import r_live_lifecycle_py310_successor as S

ROOT = Path(__file__).resolve().parent.parent
RECOGNISED = S.py310_violations() == []
recorded = pytest.mark.skipif(not RECOGNISED and S.OWNER_APPROVAL_SHA256 is None,
                              reason="R-LIVE 3.10 successor not yet carrying a recorded Financial Owner exact-content decision")
WARMING = "app/radar_rwa/r_live_warming.py"
STORE = "app/radar_rwa/r_live_snapshot_store.py"


def _git(repo, *args, **kwargs):
    return subprocess.check_output(["git", *args], cwd=repo, **kwargs)


@pytest.fixture(scope="module")
def head():
    return _git(ROOT, "rev-parse", "HEAD").decode().strip()


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    clone = tmp_path_factory.mktemp("rlive310-successor") / "clone"
    subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(ROOT), str(clone)], check=True)
    # the clone has no working tree: park its HEAD on an unrelated empty commit so every evaluated ref is judged on committed
    # bytes only (both authorities check working bytes only for the checkout HEAD)
    empty = _git(clone, "hash-object", "-t", "tree", "-w", "--stdin", input=b"").decode().strip()
    env = dict(os.environ, GIT_AUTHOR_NAME="Synthetic", GIT_AUTHOR_EMAIL="noreply@users.noreply.github.com",
               GIT_COMMITTER_NAME="Synthetic", GIT_COMMITTER_EMAIL="noreply@users.noreply.github.com")
    parked = _git(clone, "commit-tree", empty, input=b"parked HEAD\n", env=env).decode().strip()
    _git(clone, "update-ref", "--no-deref", "HEAD", parked)
    return clone


def mutate(repo, tmp_path, parent, changes):
    env = dict(os.environ, GIT_INDEX_FILE=str(tmp_path / "mutation-index"))
    _git(repo, "read-tree", parent, env=env)
    for path, data in changes.items():
        if data is None:
            _git(repo, "update-index", "--force-remove", path, env=env)
        else:
            sha = _git(repo, "hash-object", "-w", "--stdin", input=data).decode().strip()
            _git(repo, "update-index", "--add", "--cacheinfo", "100644", sha, path, env=env)
    tree = _git(repo, "write-tree", env=env).decode().strip()
    env.update(GIT_AUTHOR_NAME="Synthetic", GIT_AUTHOR_EMAIL="noreply@users.noreply.github.com",
               GIT_COMMITTER_NAME="Synthetic", GIT_COMMITTER_EMAIL="noreply@users.noreply.github.com")
    return _git(repo, "commit-tree", tree, "-p", parent, input=b"synthetic mutation\n", env=env).decode().strip()


def show(repo, ref, path):
    return _git(repo, "show", f"{ref}:{path}")


def assert_rejected(repo, ref, fragment=None):
    problems = S.py310_violations(repo=repo, ref=ref)
    assert problems, "the tampered tree must not be recognised"
    assert not any(S.py310_content_matches(p, repo=repo, ref=ref) for p in S.APPROVED_BLOBS)
    assert not any(adapter.reviewed_lifecycle_content_matches(p, repo=repo, ref=ref) for p in S.APPROVED_BLOBS)
    assert S.historical_subject(repo=repo, ref=ref) == ref                 # never relabelled to PR #346
    if fragment:
        assert any(fragment in p for p in problems), problems
    return problems


# ── contract constants (always) ───────────────────────────────────────────────

def test_contract_is_one_changed_blob_on_the_pr346_pair():
    assert S.PR346_CHECKPOINT["head"] == "0b57031ae6949d8e7d187a1932c4451e213238f7"
    assert {p: before for p, (before, _a) in S.BLOBS.items()} == A.APPROVED_LIFECYCLE_BLOBS     # PR #346 pins unchanged
    assert S.APPROVED_BLOBS[STORE] == A.APPROVED_LIFECYCLE_BLOBS[STORE]
    assert S.APPROVED_BLOBS[WARMING] == "c29fe4cdfe4e07df6ecd82a2a714f13f4b78d7e9" != A.APPROVED_LIFECYCLE_BLOBS[WARMING]
    assert S.SCOPE_CHANGED == {WARMING}
    assert S.APPROVAL_PATH != A.APPROVAL_PATH
    assert A.OWNER_APPROVAL_REFERENCE == "conversation:2026-10-22:PR346:Correction-D:section-1"     # history not edited
    record = S.expected_approval()
    assert record["Financial"]["approved"] is True
    assert not any(v for k, v in record.items() if k.endswith("_authorized"))


def test_the_source_candidate_is_exact_and_carries_no_approval_record():
    candidate = S.SOURCE_CANDIDATE["head"]
    assert _git(ROOT, "rev-parse", candidate + "^{tree}").decode().strip() == S.SOURCE_CANDIDATE["tree"]
    for path, pin in S.APPROVED_BLOBS.items():
        assert _git(ROOT, "rev-parse", f"{candidate}:{path}").decode().strip() == pin
    assert subprocess.run(["git", "cat-file", "-e", f"{candidate}:{S.APPROVAL_PATH}"], cwd=ROOT).returncode != 0
    diff = _git(ROOT, "diff", S.PR346_CHECKPOINT["head"], candidate, "--", WARMING).decode()
    changed = [line for line in diff.splitlines() if line[:1] in "+-" and not line.startswith(("+++", "---"))]
    assert changed == ["-                if self._failure is not None and sys.exception() is None:",
                       "+                if self._failure is not None and sys.exc_info()[1] is None:   "
                       "# == sys.exception() (3.11+), 3.10-safe"]


def test_pr346_is_recognised_on_its_own_bytes_at_its_checkpoint():
    for path in A.APPROVED_LIFECYCLE_BLOBS:
        assert A.reviewed_lifecycle_content_matches(path, repo=ROOT, ref=S.PR346_CHECKPOINT["head"])


def test_pending_decision_is_never_recognised(monkeypatch):
    monkeypatch.setattr(S, "_CACHE", {})
    monkeypatch.setattr(S, "OWNER_APPROVAL_SHA256", None)
    monkeypatch.setattr(S, "OWNER_APPROVAL_REFERENCE", None)
    assert "RLIVE310_OWNER_EXACT_CONTENT_DECISION_ABSENT" in S.py310_violations()
    assert not S.py310_content_matches(WARMING)
    assert S.historical_subject() != S.PR346_CHECKPOINT["head"]


@pytest.mark.parametrize("name", ["app/radar_rwa/new_sibling.py", WARMING + "/child", STORE + ".old",
                                  "app/radar_rwa/r_live_warming", "financial_engine/unapproved.py"])
def test_no_namespace_or_filename_prefix_authority(name):
    assert not S.py310_content_matches(name)
    assert not adapter.reviewed_lifecycle_content_matches(name, repo=ROOT)


# ── the repository as it is (requires the recorded decision) ─────────────────────

@recorded
def test_head_is_recognised_and_pr346_history_is_judged_at_its_checkpoint():
    assert S.py310_violations() == []
    assert all(adapter.reviewed_lifecycle_content_matches(p, repo=ROOT) for p in S.APPROVED_BLOBS)
    assert all(adapter.approved_frozen_path(p) for p in S.APPROVED_BLOBS)
    assert adapter.model_v2_frozen_violations(list(S.APPROVED_BLOBS)) == []
    assert not any(A.reviewed_lifecycle_content_matches(p, repo=ROOT) for p in S.APPROVED_BLOBS)  # PR #346 never relabelled
    assert S.historical_subject() == S.PR346_CHECKPOINT["head"]


@recorded
def test_a_one_byte_working_change_revokes_both_paths(tmp_path, monkeypatch):
    original = (ROOT / WARMING).read_bytes()
    try:
        (ROOT / WARMING).write_bytes(original + b"\n")
        problems = S.py310_violations()
        assert f"RLIVE310_WORKING_BLOB_MISMATCH: {WARMING}" in problems
        assert not any(S.py310_content_matches(p) for p in S.APPROVED_BLOBS)
    finally:
        (ROOT / WARMING).write_bytes(original)
    assert S.py310_violations() == []


# ── negative controls against the real validator (requires the recorded decision) ─────────────────────

@recorded
def test_the_head_itself_is_recognised_in_the_clone(repo, head):
    assert S.py310_violations(repo=repo, ref=head) == []


@recorded
@pytest.mark.parametrize("path", [WARMING, STORE])
def test_a_one_byte_committed_change_revokes_the_pair(repo, tmp_path, head, path):
    ref = mutate(repo, tmp_path, head, {path: show(repo, head, path) + b"\n"})
    assert_rejected(repo, ref, f"RLIVE310_BLOB_MISMATCH: {path}")


@recorded
def test_the_superseded_pr346_warming_blob_is_not_this_successor(repo, tmp_path, head):
    ref = mutate(repo, tmp_path, head, {WARMING: _git(repo, "cat-file", "blob", S.BLOBS[WARMING][0])})
    assert f"RLIVE310_BLOB_MISMATCH: {WARMING}" in S.py310_violations(repo=repo, ref=ref)
    assert not any(S.py310_content_matches(p, repo=repo, ref=ref) for p in S.APPROVED_BLOBS)
    # restoring the exact PR #346 pair stays what PR #346 itself approved - judged by its own unchanged authority
    assert all(A.reviewed_lifecycle_content_matches(p, repo=repo, ref=ref) for p in A.APPROVED_LIFECYCLE_BLOBS)


@recorded
@pytest.mark.parametrize("path", [WARMING, STORE])
def test_a_deleted_path_is_rejected(repo, tmp_path, head, path):
    assert_rejected(repo, mutate(repo, tmp_path, head, {path: None}), f"RLIVE310_BLOB_MISMATCH: {path}")


@recorded
@pytest.mark.parametrize("path", ["app/radar_rwa/new_sibling.py", "app/radar_rwa/multi_source_evidence.py"])
def test_any_other_radar_change_is_out_of_scope(repo, tmp_path, head, path):
    data = (show(repo, head, path) if path.endswith("evidence.py") else b"") + b"\n# unapproved\n"
    assert_rejected(repo, mutate(repo, tmp_path, head, {path: data}), "RLIVE310_SCOPE_INVALID")


@recorded
@pytest.mark.parametrize("path", list(S.HISTORICAL))
def test_a_rewritten_pr346_authority_or_record_is_rejected(repo, tmp_path, head, path):
    ref = mutate(repo, tmp_path, head, {path: show(repo, head, path) + b"\n"})
    problems = S.py310_violations(repo=repo, ref=ref)
    assert f"RLIVE310_HISTORICAL_GUARD_CHANGED: {path}" in problems
    assert not any(S.py310_content_matches(p, repo=repo, ref=ref) for p in S.APPROVED_BLOBS)


@recorded
def test_altered_adapter_is_rejected(repo, tmp_path, head):
    path = "tests/r_live_lifecycle_governance.py"
    ref = mutate(repo, tmp_path, head, {path: show(repo, head, path) + b"\n"})
    assert_rejected(repo, ref, f"RLIVE310_WIRING_NOT_EXACT: {path}")


@recorded
@pytest.mark.parametrize("attack", ["byte", "missing", "reference", "blob-map", "unapproved", "merge_authorized",
                                    "runtime_activation_authorized", "wrong-scope"])
def test_owner_record_mutations_are_rejected(repo, tmp_path, head, attack):
    import json
    raw = show(repo, head, S.APPROVAL_PATH)
    if attack == "byte":
        data = raw + b" "
    elif attack == "missing":
        data = None
    else:
        record = json.loads(raw)
        if attack == "reference":
            record["Financial"]["reference"] = "forged-or-stale-reference"
        elif attack == "blob-map":
            record["blobs"][WARMING] = "f" * 40
        elif attack == "unapproved":
            record["Financial"]["approved"] = False
        elif attack == "wrong-scope":
            record["scope"] = "app/radar_rwa/**"
        else:
            record[attack] = True
        data = (json.dumps(record, indent=2) + "\n").encode()
    assert_rejected(repo, mutate(repo, tmp_path, head, {S.APPROVAL_PATH: data}))


@recorded
@pytest.mark.parametrize("attack", ["missing-checkpoint", "wrong-checkpoint-tree", "missing-candidate", "unrelated-target"])
def test_provenance_uncertainty_fails_closed(repo, tmp_path, head, monkeypatch, attack):
    monkeypatch.setattr(S, "_CACHE", {})
    ref = head
    if attack == "missing-checkpoint":
        monkeypatch.setattr(S, "PR346_CHECKPOINT", {"head": "f" * 40, "tree": "e" * 40})
    elif attack == "wrong-checkpoint-tree":
        monkeypatch.setattr(S, "PR346_CHECKPOINT", {**S.PR346_CHECKPOINT, "tree": "f" * 40})
    elif attack == "missing-candidate":
        monkeypatch.setattr(S, "SOURCE_CANDIDATE", {"head": "f" * 40, "tree": "e" * 40})
    else:
        tree = _git(repo, "rev-parse", head + "^{tree}").decode().strip()
        env = dict(os.environ, GIT_AUTHOR_NAME="Synthetic", GIT_AUTHOR_EMAIL="noreply@users.noreply.github.com",
                   GIT_COMMITTER_NAME="Synthetic", GIT_COMMITTER_EMAIL="noreply@users.noreply.github.com")
        ref = _git(repo, "commit-tree", tree, input=b"unrelated same-content tree\n", env=env).decode().strip()
    assert_rejected(repo, ref)


@recorded
def test_bad_ref_and_invalid_repo_fail_closed(repo, tmp_path):
    assert S.py310_violations(repo=repo, ref="no-such-ref") == ["RLIVE310_REF_UNAVAILABLE"]
    assert S.py310_violations(repo=tmp_path / "not-a-repo") == ["RLIVE310_REF_UNAVAILABLE"]
