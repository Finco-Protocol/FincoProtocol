"""An exact revenue authority blob is not a namespace or future-edit exemption."""
import hashlib
import subprocess

import pytest
import model_v2_governance as governance
from tests import rc3_authority_states as authority_states
from finance_integrity_governance import unapproved_engine_changes, strictly_frozen_changes, approved_frozen_path
from tests.test_financing_f3_governance import git

PATHS = {
    "financial_engine/adapters/project_inputs.py", "financial_engine/orchestrator.py",
    "financial_engine/revenue_multistream.py", "finco_core/inputs/revenue_multistream.py",
    "finco_core/inputs/serialization.py", "finco_core/revenue/generation.py",
    "domain/revenue/multistream_runtime.py",
}


# Two of the seven historical WF07 paths now carry the integrated, RELEASE-CLOSED M7 candidate (PR #284). The historical pins are judged at the
# commit where they were accepted; the M7 content is judged separately as a candidate, never as a released authority.
CHECKPOINT = authority_states.historical_checkpoint()
M7_PATHS = frozenset(PATHS) & frozenset(authority_states.M7_CANDIDATE)
# Two more of the seven paths now carry the integrated, RELEASE-CLOSED PPA-01 candidate (PR #293 via the RC-3 integration, #294). Recognised by exact
# content in tests/ppa01_candidate_authority.py; never a released authority, never an approval.
from tests import ppa01_candidate_authority as ppa01
PPA01_PATHS = frozenset(PATHS) & frozenset(ppa01.PPA01_CANDIDATE_AUTHORITIES)


def _released_blob(path):
    """The historically released blob of a WF07 path (original pin or its reviewed successor), as pinned in the governance maps."""
    return governance.F3_5_A_JUNIOR_AUTHORITIES.get(
        path, governance.REVENUE_V3_CANDIDATE_AUTHORITIES.get(
            path, governance.REVENUE_V2_ADVANCED_AUTHORITIES.get(path, governance.WF07_REVENUE_AUTHORITIES[path])))


def test_exact_seven_content_pins_only():
    assert set(governance.WF07_REVENUE_AUTHORITIES) == PATHS
    assert M7_PATHS == {"financial_engine/adapters/project_inputs.py", "financial_engine/orchestrator.py"}
    assert PPA01_PATHS == {"domain/revenue/multistream_runtime.py", "finco_core/revenue/generation.py"}
    for path, blob in governance.WF07_REVENUE_AUTHORITIES.items():
        assert "*" not in path
        # HISTORICAL_RELEASED: the original seven WF07 pins (and their reviewed successors) at the checkpoint where they were accepted.
        assert git(governance.REPO, "rev-parse", CHECKPOINT + ":" + path) == _released_blob(path)
        assert governance.released_engine_authority_matches(path, ref=CHECKPOINT)
        assert governance.WF07_REVENUE_AUTHORITIES[path] == blob
    # Current content: five paths are still exactly the released authority ...
    from rc7b_quarterly_candidate_authority import RC7B_CANDIDATE_AUTHORITIES
    from rc7b_postmerge_successor import current_expected_blob, superseded as superseded_by_gate_r
    for path in PATHS - M7_PATHS - PPA01_PATHS:
        if superseded_by_gate_r(path, repo=governance.REPO):
            # RC-7B: an ACTIVE Gate R (signed record + authentic independent review + exact twelve blobs) recognises the superseding candidate.
            # It is a release-closed candidate only: never the released pin, never an approved frozen path.
            assert git(governance.REPO, "rev-parse", "HEAD:" + path) == RC7B_CANDIDATE_AUTHORITIES[path]
            assert authority_states.authority_state(path) == authority_states.INTEGRATED_RELEASE_CLOSED_CANDIDATE
            assert not governance.released_engine_authority_matches(path)
            assert not approved_frozen_path(path)
            continue
        assert git(governance.REPO, "rev-parse", "HEAD:" + path) == _released_blob(path)
        assert authority_states.authority_state(path) == authority_states.HISTORICAL_RELEASED
        assert governance.released_engine_authority_matches(path)
        assert approved_frozen_path(path)
    # ... and the two M7 paths are the exact release-closed candidate: present, byte-identical, NOT released, NOT activated.
    for path in M7_PATHS:
        # RC-7B Gate R: the two shared paths are the superseding quarterly candidate only while a complete, authentic Gate R is active.
        assert git(governance.REPO, "rev-parse", "HEAD:" + path) == current_expected_blob(path, authority_states.M7_CANDIDATE[path], repo=governance.REPO)
        assert authority_states.authority_state(path) == authority_states.INTEGRATED_RELEASE_CLOSED_CANDIDATE
        assert not governance.released_engine_authority_matches(path)       # candidate presence is never release approval
        assert not approved_frozen_path(path)
    # ... and the two PPA-01 paths are the exact release-closed candidate: byte-identical to the reviewed blobs, NOT released, NOT approved.
    for path in PPA01_PATHS:
        assert git(governance.REPO, "rev-parse", "HEAD:" + path) == ppa01.PPA01_CANDIDATE_AUTHORITIES[path]
        assert git(governance.REPO, "rev-parse", "HEAD:" + path) != _released_blob(path)    # a different blob from the historical release
        assert authority_states.authority_state(path) == authority_states.INTEGRATED_RELEASE_CLOSED_CANDIDATE
        assert not governance.released_engine_authority_matches(path)
        assert not approved_frozen_path(path)
    assert authority_states.release_closed_violations() == []
    # the released-authority guard still rejects the candidate; a path superseded by an ACTIVE Gate R is recognised instead (never released)
    from rc7b_postmerge_successor import without_superseded as without_gate_r_superseded
    assert without_gate_r_superseded(unapproved_engine_changes(list(PATHS)), repo=governance.REPO) == sorted(
        p for p in M7_PATHS if not superseded_by_gate_r(p, repo=governance.REPO))
    assert strictly_frozen_changes(list(PATHS)) == []


@pytest.mark.parametrize("path", sorted(PATHS))
def test_every_further_edit_invalidates_authorization(path, tmp_path, monkeypatch):
    repo = tmp_path / "synthetic"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "config", "user.name", "Synthetic Reviewer")
    git(repo, "config", "user.email", "noreply@users.noreply.github.com")
    # Synthetic HISTORICAL_RELEASED case: the content accepted at the historical checkpoint (not whatever HEAD carries now).
    original = subprocess.run(["git", "-C", str(governance.REPO), "show", CHECKPOINT + ":" + path],
                              check=True, capture_output=True).stdout
    target = repo / path
    target.parent.mkdir(parents=True)
    target.write_bytes(original)
    git(repo, "add", path)
    git(repo, "commit", "-m", "Exact reviewed content")
    assert governance.released_engine_authority_matches(path, repo=repo)
    target.write_bytes(original + b"\n# Unapproved change\n")
    git(repo, "add", path)
    git(repo, "commit", "-m", "Unapproved change")
    assert not governance.released_engine_authority_matches(path, repo=repo)
    monkeypatch.setattr(governance, "REPO", repo)
    assert not approved_frozen_path(path)
    if path.startswith("financial_engine/"):
        assert unapproved_engine_changes([path]) == [path]
    if path.startswith("finco_core/"):
        assert strictly_frozen_changes([path]) == [path]


@pytest.mark.parametrize("path", ["financial_engine/revenue_multistream.py.bak", "finco_core/revenue/other.py",
    "finco_core/inputs/_models.py/unapproved", "financial_engine/senior_debt/new.py", "finco_radar/other.py"])
def test_unrelated_files_remain_blocked(path):
    assert not governance.approved_by_active_model_v2_scope(path)


def test_advanced_revenue_successor_is_one_exact_blob_without_rewriting_wf07_history():
    path = "domain/revenue/multistream_runtime.py"
    assert governance.WF07_REVENUE_AUTHORITIES[path] == "94e1559472d0f3051fb7faccf3b67ce44337188f"
    assert governance.REVENUE_V2_ADVANCED_AUTHORITIES == {
        path: "48465ce2a298fa1383a7eabcb921eb9fbe4610cb",
    }
    # The reviewed V2/V3 successors are judged at the commit where they were accepted. HEAD now carries the release-closed PPA-01 candidate.
    assert git(governance.REPO, "rev-parse", CHECKPOINT + ":" + path) in {
        governance.REVENUE_V2_ADVANCED_AUTHORITIES[path], governance.REVENUE_V3_CANDIDATE_AUTHORITIES[path]}
    assert governance.released_engine_authority_matches(path, ref=CHECKPOINT)
    assert git(governance.REPO, "rev-parse", "HEAD:" + path) == ppa01.PPA01_CANDIDATE_AUTHORITIES[path]
    assert not governance.released_engine_authority_matches(path) and not approved_frozen_path(path)


def test_revenue_successor_rejects_extra_byte_and_unlisted_domain_path(tmp_path, monkeypatch):
    repo = tmp_path / "synthetic-revenue-successor"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "config", "user.name", "Synthetic Reviewer")
    git(repo, "config", "user.email", "noreply@users.noreply.github.com")
    path = "domain/revenue/multistream_runtime.py"
    original = subprocess.run(["git", "-C", str(governance.REPO), "show", CHECKPOINT + ":" + path],
                              check=True, capture_output=True).stdout        # the reviewed Revenue V2/V3 content at its own checkpoint
    target = repo / path
    target.parent.mkdir(parents=True)
    target.write_bytes(original)
    git(repo, "add", path)
    git(repo, "commit", "-m", "Exact Revenue V2 candidate")
    assert governance.released_engine_authority_matches(path, repo=repo)
    target.write_bytes(original + b"x")
    git(repo, "add", path)
    git(repo, "commit", "-m", "Changed Revenue V2 content")
    assert not governance.released_engine_authority_matches(path, repo=repo)
    monkeypatch.setattr(governance, "REPO", repo)
    assert not approved_frozen_path(path)
    assert not approved_frozen_path("domain/revenue/unapproved.py")


V3_PATHS = {
    "domain/revenue/advanced_products.py": "d4ab263422aac5571e52bee4925fe36588e853cc",
    "domain/revenue/multistream_runtime.py": "83beda4eb296b02baf2ebd6659fec243ab196206",
    "finco_core/revenue/generation.py": "35670dc7b5ab4ce01177f9df817a4776c10569ab",
}


def test_revenue_v3_candidate_is_exactly_three_blobs_and_does_not_rewrite_history():
    assert governance.REVENUE_V3_CANDIDATE_AUTHORITIES == V3_PATHS
    assert all("*" not in p for p in V3_PATHS)
    # Historical maps are untouched by the successor.
    assert governance.WF07_REVENUE_AUTHORITIES["finco_core/revenue/generation.py"] == "e2502c6ba8557dd68d6bbcd44c1b55208f1942ed"
    assert governance.WF07_REVENUE_AUTHORITIES["domain/revenue/multistream_runtime.py"] == "94e1559472d0f3051fb7faccf3b67ce44337188f"
    assert governance.REVENUE_V2_ADVANCED_AUTHORITIES == {"domain/revenue/multistream_runtime.py": "48465ce2a298fa1383a7eabcb921eb9fbe4610cb"}
    for path, blob in V3_PATHS.items():
        # HISTORICAL_RELEASED at the checkpoint where the reviewed V3 successor was accepted (never rewritten by the PPA-01 candidate).
        assert git(governance.REPO, "rev-parse", CHECKPOINT + ":" + path) == blob
        assert governance.released_engine_authority_matches(path, ref=CHECKPOINT)
        if path in PPA01_PATHS:
            assert git(governance.REPO, "rev-parse", "HEAD:" + path) == ppa01.PPA01_CANDIDATE_AUTHORITIES[path]
            assert not governance.released_engine_authority_matches(path)
        else:
            assert git(governance.REPO, "rev-parse", "HEAD:" + path) == blob
            assert governance.released_engine_authority_matches(path)
    # HEAD's finco_core/revenue/generation.py is the exact PPA-01 candidate: exempt from the strict freeze only as a candidate, not as a release.
    assert strictly_frozen_changes(["finco_core/revenue/generation.py"]) == []


@pytest.mark.parametrize("path", sorted(V3_PATHS))
def test_revenue_v3_candidate_rejects_any_further_byte_and_other_paths(path, tmp_path, monkeypatch):
    repo = tmp_path / "synthetic-v3"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "config", "user.name", "Synthetic Reviewer")
    git(repo, "config", "user.email", "noreply@users.noreply.github.com")
    original = subprocess.run(["git", "-C", str(governance.REPO), "show", CHECKPOINT + ":" + path], check=True, capture_output=True).stdout
    target = repo / path
    target.parent.mkdir(parents=True)
    target.write_bytes(original)
    git(repo, "add", path)
    git(repo, "commit", "-m", "Exact Revenue V3 candidate")
    assert governance.released_engine_authority_matches(path, repo=repo)
    target.write_bytes(original + b"\n# unreviewed\n")
    git(repo, "add", path)
    git(repo, "commit", "-m", "Changed")
    assert not governance.released_engine_authority_matches(path, repo=repo)
    monkeypatch.setattr(governance, "REPO", repo)
    assert not approved_frozen_path(path)
    if path.startswith("finco_core/"):
        assert strictly_frozen_changes([path]) == [path]


def test_revenue_v3_successor_authorizes_no_other_revenue_path():
    for other in ("domain/revenue/plan.py", "domain/revenue/plan_engine.py", "domain/revenue/other.py",
                  "finco_core/revenue/other.py", "finco_core/revenue/generation.py.bak", "financial_engine/revenue/new.py"):
        assert not governance.released_engine_authority_matches(other), other


@pytest.mark.parametrize("path", sorted(M7_PATHS))
def test_m7_candidate_is_exact_content_release_closed_and_never_inherits_released_authority(path, tmp_path, monkeypatch):
    """INTEGRATED_RELEASE_CLOSED_CANDIDATE: one additional byte (or the historical blob) is not the candidate; nothing here is a release."""
    repo = tmp_path / "synthetic"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "config", "user.name", "Synthetic Reviewer")
    git(repo, "config", "user.email", "noreply@users.noreply.github.com")
    # Known-good candidate = the literal M7 candidate blob object (immutable), not whatever the current integration HEAD carries; a later
    # integration may legitimately supersede it. The live HEAD state is judged by test_exact_seven_content_pins_only.
    candidate = subprocess.run(["git", "-C", str(governance.REPO), "cat-file", "blob", authority_states.M7_CANDIDATE[path]],
                               check=True, capture_output=True).stdout
    assert hashlib.sha1(b"blob %d\0" % len(candidate) + candidate).hexdigest() == authority_states.M7_CANDIDATE[path]
    historical =subprocess.run(["git", "-C", str(governance.REPO), "show", CHECKPOINT + ":" + path], check=True, capture_output=True).stdout
    target = repo / path
    target.parent.mkdir(parents=True)
    # the synthetic repo has no release flags, so a candidate can only exist where the real flags are closed: judge content only
    target.write_bytes(candidate)
    git(repo, "add", path)
    git(repo, "commit", "-m", "Exact candidate content")
    assert authority_states.candidate_matches(path, repo=repo)
    assert not governance.released_engine_authority_matches(path, repo=repo)          # a candidate is never a released authority
    target.write_bytes(candidate + b"\n# Unreviewed change\n")
    git(repo, "add", path)
    git(repo, "commit", "-m", "One further edit")
    assert not authority_states.candidate_matches(path, repo=repo)                    # one more byte invalidates the candidate
    assert authority_states.authority_state(path, repo=repo) == authority_states.UNAUTHORIZED
    target.write_bytes(historical)
    git(repo, "add", path)
    git(repo, "commit", "-m", "Historical released content")
    assert governance.released_engine_authority_matches(path, repo=repo)              # released state is independent of the candidate
    assert not authority_states.candidate_matches(path, repo=repo)
    assert authority_states.authority_state(path, repo=repo) == authority_states.HISTORICAL_RELEASED


def test_unknown_future_edits_inherit_no_m7_permission():
    for path in ("financial_engine/bess_new.py", "financial_engine/tax/engine.py.bak", "finco_core/inputs/bess_native2.py",
                 "domain/bess/other.py", "financial_engine/senior_debt/new.py"):
        assert not authority_states.candidate_matches(path)
        assert not governance.released_engine_authority_matches(path)
    assert authority_states.ACTIVATED_FINANCIAL_AUTHORITY not in {authority_states.authority_state(p) for p in authority_states.M7_CANDIDATE}


def test_historical_wf07_pins_are_not_rewritten_by_the_m7_candidate():
    assert governance.WF07_REVENUE_AUTHORITIES["financial_engine/adapters/project_inputs.py"] == "fe09548f59497884af492a0ea8139bbbfffbeb05"
    assert governance.WF07_REVENUE_AUTHORITIES["financial_engine/orchestrator.py"] == "67f9ec6aa3fcb6a8d8acf59cf4c75bcac58b3301"
    for path in M7_PATHS:
        assert authority_states.M7_CANDIDATE[path] != governance.WF07_REVENUE_AUTHORITIES[path]
        for authorities in (governance.F3_5_A_JUNIOR_AUTHORITIES, governance.REVENUE_V3_CANDIDATE_AUTHORITIES,
                            governance.REVENUE_V2_ADVANCED_AUTHORITIES, governance.WF04_NUMERIC_PRECISION_AUTHORITIES):
            assert authorities.get(path) != authority_states.M7_CANDIDATE[path]
