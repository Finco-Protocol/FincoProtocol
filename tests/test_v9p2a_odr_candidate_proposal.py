"""The V9-P2a / OD-R successor proposal describes exact bytes only and grants nothing."""
from __future__ import annotations

from pathlib import Path
import os
import subprocess

import pytest

from tests import v9p2a_odr_candidate_proposal as proposal

ROOT = Path(__file__).resolve().parent.parent


def test_proposal_names_exactly_the_changed_protected_paths():
    assert set(proposal.CANDIDATE_BLOBS) == set(proposal.PREDECESSOR_BLOBS)
    for path, before in proposal.PREDECESSOR_BLOBS.items():
        assert proposal.blob(path, proposal.PREDECESSOR_MAIN) == before
    # Historical evidence: the Correction B proposal described the content of its own checkpoint, judged there (the current HEAD carries the
    # later, separately owner-accepted OD-R content recognised by ``v9p2a_odr_successor``, never by this proposal).
    assert proposal.content_matches_proposal(proposal.CANDIDATE_CHECKPOINT)
    assert proposal.candidate_violations(proposal.CANDIDATE_CHECKPOINT) == []


def test_proposal_grants_no_approval_and_is_not_wired_into_any_guard():
    states = proposal.states()
    for key in ("protected_content_approved", "independent_financial_review",
                "wired_into_current_authority_guards", "product_activation", "financial_release"):
        assert states[key] is False
    for guard in sorted((ROOT / "tests").glob("*.py")):
        if guard.name.startswith(("test_v9p2a_odr_candidate_proposal", "v9p2a_odr_candidate_proposal")):
            continue
        assert "v9p2a_odr_candidate_proposal" not in guard.read_text(encoding="utf-8", errors="replace"), guard.name


def _git(repo, *args, **kwargs):
    return subprocess.check_output(["git", *args], cwd=repo, **kwargs)


@pytest.fixture(scope="module")
def candidate_repo(tmp_path_factory):
    repo = tmp_path_factory.mktemp("odr-proposal") / "clone"
    subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(ROOT), str(repo)], check=True)
    _git(repo, "config", "user.name", "Synthetic")
    _git(repo, "config", "user.email", "noreply@users.noreply.github.com")
    return repo


def _mutated_commit(repo, tmp_path, changes, *, orphan=False):
    """Real Git objects in a disposable clone; never edit the source checkout."""
    env = dict(os.environ, GIT_INDEX_FILE=str(tmp_path / "mutation-index"))
    parent = proposal.CANDIDATE_CHECKPOINT
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


def test_historical_quarterly_state_and_candidate_recognition_are_not_approval():
    from tests.quarterly_candidate_recognition import recognized_state
    from tests.model_v2_governance import released_engine_authority_matches

    assert recognized_state(ref=proposal.PREDECESSOR_MAIN) == "RC7C"
    assert recognized_state(ref=proposal.INTEGRATION_MAIN) == "RC7C"
    # the proposal's own content never became a recognised current-authority state
    assert recognized_state(ref=proposal.CANDIDATE_CHECKPOINT) is None
    assert proposal.states(proposal.CANDIDATE_CHECKPOINT)["chained_candidate_recognized"] is True
    # the current HEAD is not the proposal content and the proposal does not recognise it
    assert not proposal.content_matches_proposal()
    assert proposal.states()["chained_candidate_recognized"] is False
    for path in proposal.CANDIDATE_BLOBS:
        assert not released_engine_authority_matches(path)
    for ref in (proposal.CANDIDATE_CHECKPOINT, "HEAD"):
        for name in ("protected_content_approved", "independent_financial_review",
                     "wired_into_current_authority_guards", "product_activation", "financial_release"):
            assert proposal.states(ref)[name] is False


@pytest.mark.parametrize("path", tuple(proposal.CANDIDATE_BLOBS))
def test_one_byte_mutation_of_each_protected_blob_fails(candidate_repo, tmp_path, path):
    original = _git(candidate_repo, "show", f"{proposal.CANDIDATE_CHECKPOINT}:{path}")
    ref = _mutated_commit(candidate_repo, tmp_path, {path: original + b"\n"})
    bad = proposal.candidate_violations(ref, repo=candidate_repo)
    assert f"ODR_CANDIDATE_BLOB_MISMATCH: {path}" in bad
    assert not proposal.candidate_recognized(ref, repo=candidate_repo)


@pytest.mark.parametrize("path", (
    "financial_engine/unreviewed_odr_extra.py", "finco_core/inputs/unreviewed_extra.py",
    "domain/revenue/unreviewed_extra.py", "app/v2/router.py", "tests/model_v2_governance.py",
))
def test_unlisted_financial_application_or_guard_change_fails(candidate_repo, tmp_path, path):
    original = subprocess.run(["git", "show", f"{proposal.CANDIDATE_CHECKPOINT}:{path}"],
                              cwd=candidate_repo, capture_output=True).stdout
    ref = _mutated_commit(candidate_repo, tmp_path, {path: original + b"\n# synthetic\n"})
    assert "ODR_UNLISTED_CHANGE" in proposal.candidate_violations(ref, repo=candidate_repo)
    assert not proposal.candidate_recognized(ref, repo=candidate_repo)


def test_missing_candidate_file_fails(candidate_repo, tmp_path):
    path = "financial_engine/shl/maturity_authority.py"
    ref = _mutated_commit(candidate_repo, tmp_path, {path: None})
    assert f"ODR_CANDIDATE_BLOB_MISMATCH: {path}" in proposal.candidate_violations(ref, repo=candidate_repo)


def test_stale_manifest_cannot_authorize_itself(monkeypatch):
    changed = dict(proposal.CANDIDATE_BLOBS)
    path = "financial_engine/financing/project.py"
    changed[path] = proposal.SUPERSEDED_CANDIDATE_BLOBS[path]
    monkeypatch.setattr(proposal, "CANDIDATE_BLOBS", changed)
    assert f"ODR_MANIFEST_STALE: {path}" in proposal.candidate_violations()
    assert not proposal.candidate_recognized()


def test_missing_git_provenance_fails(tmp_path):
    assert proposal.candidate_violations(repo=tmp_path) == ["ODR_REF_UNAVAILABLE"]
    assert not proposal.candidate_recognized("not-a-ref")


def test_missing_predecessor_history_fails(tmp_path):
    repo = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--no-local", "--depth=1", "--no-checkout", str(ROOT), str(repo)],
                   check=True, capture_output=True)
    assert any(message.startswith("ODR_PREDECESSOR_MISSING:")
               for message in proposal.candidate_violations(repo=repo))
    assert not proposal.candidate_recognized(repo=repo)


def test_exact_bytes_without_ancestry_are_rejected(candidate_repo, tmp_path):
    ref = _mutated_commit(candidate_repo, tmp_path, {}, orphan=True)
    assert proposal.content_matches_proposal(ref, repo=candidate_repo)
    assert any(message.startswith("ODR_ANCESTRY_INVALID:")
               for message in proposal.candidate_violations(ref, repo=candidate_repo))


def test_financial_evidence_and_application_content_cannot_change(candidate_repo, tmp_path):
    paths = ("docs/model_v2/V9P2A_ODR_ACCEPTANCE_EVIDENCE.json", "app/services/production_financial_authority.py")
    changes = {path: _git(candidate_repo, "show", f"{proposal.CANDIDATE_CHECKPOINT}:{path}") + b"\n"
               for path in paths}
    ref = _mutated_commit(candidate_repo, tmp_path, changes)
    bad = proposal.candidate_violations(ref, repo=candidate_repo)
    assert any(message.startswith("ODR_EVIDENCE_BLOB_MISMATCH:") for message in bad)
    assert any(message.startswith("ODR_APPLICATION_BLOB_MISMATCH:") for message in bad)


def test_opened_flag_and_forged_approval_record_grant_nothing(candidate_repo, tmp_path):
    path = "app/workbook/junior_debt_config.py"
    original = _git(candidate_repo, "show", f"{proposal.CANDIDATE_CHECKPOINT}:{path}")
    changed = original.replace(b"ACTIVATION_ENABLED = False", b"ACTIVATION_ENABLED = True")
    assert changed != original
    ref = _mutated_commit(candidate_repo, tmp_path, {
        path: changed,
        "docs/model_v2/ODR_FINANCIAL_ACCEPTANCE.json": b'{"approved":true}\n',
    })
    assert not proposal.candidate_recognized(ref, repo=candidate_repo)
    states = proposal.states(ref, repo=candidate_repo)
    assert states["chained_candidate_recognized"] is False
    for name in ("protected_content_approved", "independent_financial_review", "product_activation", "financial_release"):
        assert states[name] is False
