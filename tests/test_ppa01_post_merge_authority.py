"""Post-merge candidate identity is independent of a moving branch-delta base."""
import copy
import subprocess
from pathlib import Path

import pytest

from tests import ppa01_candidate_authority as P
from tests.rc3_authority_states import RELEASE_FLAGS, authority_state, INTEGRATED_RELEASE_CLOSED_CANDIDATE
from tests.test_ppa01_candidate_authority import git, _write_commit

MERGED_MAIN = "4483b30904a30cd3f5406506283202e2ebeaf427"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def inherited(tmp_path):
    repo = tmp_path / "inherited"
    subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(ROOT), str(repo)], check=True, capture_output=True)
    for key, value in (("core.autocrlf", "false"), ("user.name", "Synthetic Reviewer"),
                       ("user.email", "noreply@users.noreply.github.com")):
        git(repo, "config", key, value)
    git(repo, "checkout", "-q", "--detach", MERGED_MAIN)
    git(repo, "update-ref", "refs/remotes/origin/main", MERGED_MAIN)
    return repo


def assert_closed_candidate(repo, ref="HEAD"):
    facts = P.collect(repo=repo, ref=ref)
    assert facts["protected_changes"] == sorted(P.PPA01_CANDIDATE_AUTHORITIES)
    assert facts["branch_protected_changes"] == []
    assert P.content_violations(facts) == []
    assert not P.candidate_is_financially_approved(repo=repo, ref=ref)
    assert not P.candidate_is_released(repo=repo, ref=ref)
    for path in P.PPA01_CANDIDATE_AUTHORITIES:
        assert authority_state(path, repo=repo, ref=ref) == INTEGRATED_RELEASE_CLOSED_CANDIDATE


def test_head_equal_main_and_inherited_feature_and_integration_branches(inherited):
    assert git(inherited, "rev-parse", "HEAD") == git(inherited, "rev-parse", "origin/main")
    assert_closed_candidate(inherited)
    git(inherited, "checkout", "-q", "-b", "feature")
    _write_commit(inherited, {"docs/synthetic_feature.md": "nonfinancial\n"}, "feature")
    assert_closed_candidate(inherited)
    git(inherited, "checkout", "-q", "-b", "synthetic-integration", MERGED_MAIN)
    _write_commit(inherited, {"docs/synthetic_integration.md": "nonfinancial\n"}, "integration")
    git(inherited, "merge", "-q", "--no-ff", "feature", "-m", "normal integration")
    assert_closed_candidate(inherited)


def test_original_published_candidate_keeps_its_exact_identity(inherited):
    assert_closed_candidate(inherited, ref=P.PPA01_REVIEWED_SOURCE_HEAD)


@pytest.mark.parametrize("path", sorted(P.PPA01_CANDIDATE_AUTHORITIES))
def test_one_byte_or_missing_candidate_file_after_landing_is_rejected(inherited, path):
    original = subprocess.check_output(["git", "show", "HEAD:" + path], cwd=inherited)
    _write_commit(inherited, {path: original + b"\n# unreviewed\n"}, "mutation")
    assert P.content_violations(P.collect(repo=inherited))
    assert not P.candidate_is_released(repo=inherited)
    git(inherited, "rm", "-q", path)
    git(inherited, "commit", "-q", "-m", "missing candidate file")
    assert P.content_violations(P.collect(repo=inherited))


@pytest.mark.parametrize("extra", ["domain/revenue/unreviewed.py", "finco_core/unreviewed.py", "financial_engine/unreviewed.py"])
def test_extra_protected_change_is_rejected_even_if_main_moves_over_it(inherited, extra):
    _write_commit(inherited, {extra: "x = 1\n"}, "unreviewed financial change")
    assert any(extra in error for error in P.content_violations(P.collect(repo=inherited)))
    git(inherited, "update-ref", "refs/remotes/origin/main", "HEAD")
    facts = P.collect(repo=inherited)
    assert facts["branch_protected_changes"] == []
    assert any(extra in error for error in P.content_violations(facts))


@pytest.mark.parametrize("path,name", sorted(RELEASE_FLAGS.items()))
def test_reopened_activation_flag_never_becomes_an_accepted_candidate(inherited, path, name):
    source = subprocess.check_output(["git", "show", "HEAD:" + path], cwd=inherited).decode()
    changed = source.replace(name + " = False", name + " = True", 1)
    assert changed != source
    _write_commit(inherited, {path: changed}, "unauthorized activation")
    assert any("release flags" in error for error in P.content_violations(P.collect(repo=inherited)))
    assert not P.candidate_is_financially_approved(repo=inherited)


def test_altered_historical_pin_and_missing_origin_fail_closed(inherited):
    path = "tests/model_v2_governance.py"
    source = subprocess.check_output(["git", "show", "HEAD:" + path], cwd=inherited)
    _write_commit(inherited, {path: source.replace(b"94e1559472d0f3051fb7faccf3b67ce44337188f", b"0" * 40)}, "alter historical pin")
    assert any("historical" in error for error in P.content_violations(P.collect(repo=inherited)))
    git(inherited, "update-ref", "-d", "refs/remotes/origin/main")
    assert P.content_violations(P.collect(repo=inherited))


def test_wrong_source_ancestry_missing_objects_and_incomplete_facts_fail_closed(inherited):
    facts = P.collect(repo=inherited)
    assert not P.content_violations(facts)
    for key, value in (("publication_base_valid", False), ("source_head_ancestor", False),
                       ("historical_authorities_unchanged", False), ("release_closed_violations", None)):
        changed = copy.deepcopy(facts); changed[key] = value
        assert P.content_violations(changed)
    assert P.content_violations(P.collect(repo=inherited, ref="f" * 40))
    assert P.content_violations(P.collect(repo=inherited, base_ref="missing-origin"))
    for key in facts:
        if key != "record" and key != "branch_protected_changes":
            assert P.content_violations({k: v for k, v in facts.items() if k != key}), key
