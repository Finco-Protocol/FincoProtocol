"""RC-3 / C2 negative controls: the PPA-01 candidate recognition stays fail-closed and is never an approval or a release.

These tests drive the REAL governance code (tests/ppa01_candidate_authority.py, the central frozen-scope guards, the historical anchor, the pin maps)
with synthetic Git repositories and mutated fact sets. No predicate is mocked to always succeed.
"""
from __future__ import annotations

import copy
import subprocess
from pathlib import Path

import pytest

import model_v2_governance as governance
import finance_integrity_governance as fig
import tests.m7_rc3_candidate_successor as M7
from tests import ppa01_candidate_authority as P
from tests import rc3_historical_anchor as anchor

ROOT = Path(__file__).resolve().parent.parent
PATHS = sorted(P.PPA01_CANDIDATE_AUTHORITIES)
GOOD_RECORD = {
    "independent_reviewer": "Jane Example (independent financial reviewer)", "financial_owner": "John Example (financial owner)",
    "reviewed_source_head": P.PPA01_REVIEWED_SOURCE_HEAD, "accepted_blobs": dict(P.PPA01_CANDIDATE_AUTHORITIES),
    "scope": "CANDIDATE_CONTENT_ONLY", "decision_reference": "SYNTHETIC-TEST-REFERENCE",
}


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True).stdout.strip()


def _blob_bytes(blob):
    return subprocess.run(["git", "cat-file", "blob", blob], cwd=ROOT, capture_output=True, check=True).stdout


def _repo(tmp_path, files, name="synthetic"):
    repo = tmp_path / name
    repo.mkdir()
    git(repo, "init", "-q")
    for key, val in (("core.autocrlf", "false"), ("user.name", "Synthetic Reviewer"), ("user.email", "noreply@users.noreply.github.com")):
        git(repo, "config", key, val)
    _write_commit(repo, files, "baseline")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


def _write_commit(repo, files, message):
    for path, data in files.items():
        target = Path(repo) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data if isinstance(data, bytes) else data.encode())
        git(repo, "add", path)
    git(repo, "commit", "-q", "-m", message)


def _candidate_files():
    return {p: _blob_bytes(b) for p, b in P.PPA01_CANDIDATE_AUTHORITIES.items()}


@pytest.fixture(scope="module")
def facts():
    return P.collect()


KNOWN_GOOD_MAIN = "5be8c4b149712dd39b38b54c6fabcf3fcf47ef0d"       # immutable main after PR #313: carries exactly the PPA-01 candidate


@pytest.fixture(scope="module")
def known_good_facts():
    assert subprocess.run(["git", "merge-base", "--is-ancestor", KNOWN_GOOD_MAIN, "HEAD"], cwd=ROOT).returncode == 0
    good = P.collect(ref=KNOWN_GOOD_MAIN)
    assert P.content_violations(good) == []                              # the baseline really IS the reviewed candidate
    return good


def _bad(facts, fn, **changes):
    mutated = copy.deepcopy(facts)
    mutated.update(changes)
    problems = fn(mutated)
    assert problems, changes
    return problems


# 1 ─ identity recognised, approval and release are NOT granted
def test_exact_candidate_is_recognised_but_neither_approved_nor_released(facts):
    assert P.content_violations(facts) == []
    assert P.candidate_content_matches_exactly() is True
    assert facts["record"] is None
    assert P.candidate_is_financially_approved() is False
    assert P.candidate_is_released() is False
    assert any("FINANCIAL_OWNER_APPROVAL_REQUIRED" in p for p in P.acceptance_violations(facts))


def test_the_candidate_slice_is_exactly_three_literal_paths_and_blobs():
    assert P.PPA01_CANDIDATE_AUTHORITIES == {
        "domain/revenue/multistream_runtime.py": "b1896bdb156a53c8371286bb4198381d0c7904fe",
        "domain/revenue/revenue_config.py": "d62fc2c7d97986d2c0aed6c0ac9068759011e1ef",
        "finco_core/revenue/generation.py": "8e23a949e72acc6422a6c7cd46f034b31f81fdfb",
    }
    assert all("*" not in p and not p.endswith("/") for p in P.PPA01_CANDIDATE_AUTHORITIES)


# 2-4 ─ one changed byte in any of the three blobs (fact level AND real Git level), 5 ─ any omitted path
@pytest.mark.parametrize("path", PATHS)
def test_a_changed_or_missing_blob_is_rejected_at_fact_level(facts, path):
    assert any(path in p for p in _bad(facts, P.content_violations, blobs={**facts["blobs"], path: "1" * 40}))
    assert any(path in p for p in _bad(facts, P.content_violations, blobs={**facts["blobs"], path: None}))
    _bad(facts, P.content_violations, source_blobs={**facts["source_blobs"], path: "2" * 40})
    assert any("partial slice" in p for p in _bad(
        facts, P.content_violations, protected_changes=[c for c in facts["protected_changes"] if c != path]))


@pytest.mark.parametrize("path", PATHS)
def test_one_changed_byte_rejects_the_whole_candidate_in_real_git(tmp_path, monkeypatch, path):
    original = {p: b"historical baseline of " + p.encode() + b"\n" for p in PATHS}
    repo = _repo(tmp_path, original)
    exact = _candidate_files()
    _write_commit(repo, exact, "exact candidate")
    assert P.candidate_blobs_match(repo=repo) and all(P.frozen_scope_exempt(p, repo=repo) for p in PATHS)
    _write_commit(repo, {path: exact[path] + b"\n# one unreviewed byte\n"}, "one more edit")
    assert not P.candidate_blobs_match(repo=repo)
    assert not any(P.frozen_scope_exempt(p, repo=repo) for p in PATHS)             # a broken candidate exempts NOTHING, not even the intact paths
    monkeypatch.setattr(governance, "REPO", repo)
    assert fig.strictly_frozen_changes(["finco_core/revenue/generation.py"]) == ["finco_core/revenue/generation.py"]


@pytest.mark.parametrize("omitted", PATHS)
def test_an_incomplete_candidate_is_rejected_in_real_git(tmp_path, omitted):
    repo = _repo(tmp_path, {p: b"baseline " + p.encode() for p in PATHS})
    _write_commit(repo, {p: d for p, d in _candidate_files().items() if p != omitted}, "two of three")
    assert not P.candidate_blobs_match(repo=repo)
    assert not any(P.frozen_scope_exempt(p, repo=repo) for p in PATHS)


# 6-8 ─ extra protected paths are never inherited from the candidate
@pytest.mark.parametrize("extra", ["domain/revenue/plan.py", "domain/other/new.py", "finco_core/inputs/_models.py", "finco_core/revenue/other.py",
                                   "financial_engine/waterfall/unreviewed.py", "financial_engine/revenue/new.py"])
def test_any_additional_protected_path_is_rejected(facts, extra, tmp_path, monkeypatch):
    assert any(extra in p for p in _bad(facts, P.content_violations, protected_changes=[*facts["protected_changes"], extra]))
    assert not P.frozen_scope_exempt(extra)
    repo = _repo(tmp_path, {p: b"baseline " + p.encode() for p in PATHS})
    _write_commit(repo, _candidate_files(), "exact candidate")
    monkeypatch.setattr(governance, "REPO", repo)
    if extra.startswith("finco_core/"):
        assert fig.strictly_frozen_changes([*PATHS, extra]) == [extra]
    if extra.startswith("financial_engine/"):
        assert fig.unapproved_engine_changes([*PATHS, extra]) == [extra]
    assert not fig.approved_frozen_path(extra)


def test_the_candidate_is_not_a_released_exemption_for_stream_guards():
    for path in PATHS:
        assert not fig.approved_frozen_path(path), path                              # stream guards still see it as not approved
        assert not governance.released_engine_authority_matches(path), path          # no historical pin map was extended


# 9-10 ─ historical WF07 and Revenue V3 pins are immutable and independently judged
def test_historical_pin_maps_are_byte_identical_to_their_accepted_checkpoint():
    historical = subprocess.run(["git", "show", f"{M7.RC2_CHECKPOINT}:tests/model_v2_governance.py"], cwd=ROOT, capture_output=True, text=True,
                                check=True).stdout
    assert (ROOT / "tests" / "model_v2_governance.py").read_text(encoding="utf-8") == historical
    assert governance.WF07_REVENUE_AUTHORITIES["domain/revenue/multistream_runtime.py"] == "94e1559472d0f3051fb7faccf3b67ce44337188f"
    assert governance.WF07_REVENUE_AUTHORITIES["finco_core/revenue/generation.py"] == "e2502c6ba8557dd68d6bbcd44c1b55208f1942ed"
    assert governance.REVENUE_V3_CANDIDATE_AUTHORITIES == {
        "domain/revenue/advanced_products.py": "d4ab263422aac5571e52bee4925fe36588e853cc",
        "domain/revenue/multistream_runtime.py": "83beda4eb296b02baf2ebd6659fec243ab196206",
        "finco_core/revenue/generation.py": "35670dc7b5ab4ce01177f9df817a4776c10569ab"}
    for path, blob in P.PPA01_CANDIDATE_AUTHORITIES.items():                         # the candidate blobs are in NO historical map
        for authorities in (governance.WF07_REVENUE_AUTHORITIES, governance.REVENUE_V2_ADVANCED_AUTHORITIES,
                            governance.REVENUE_V3_CANDIDATE_AUTHORITIES, governance.F3_5_A_JUNIOR_AUTHORITIES,
                            governance.WF04_NUMERIC_PRECISION_AUTHORITIES, governance.DEVELOPER_ECONOMICS_V1_AUTHORITIES):
            assert authorities.get(path) != blob


@pytest.mark.parametrize("path, kind", [("domain/revenue/multistream_runtime.py", "WF07"), ("finco_core/revenue/generation.py", "WF07"),
                                        ("domain/revenue/multistream_runtime.py", "V3"), ("finco_core/revenue/generation.py", "V3")])
def test_a_mutated_historical_pin_content_is_neither_released_nor_the_candidate(tmp_path, path, kind):
    pin = (governance.WF07_REVENUE_AUTHORITIES if kind == "WF07" else governance.REVENUE_V3_CANDIDATE_AUTHORITIES)[path]
    repo = _repo(tmp_path, {path: _blob_bytes(pin)})
    assert governance.released_engine_authority_matches(path, repo=repo)                # the exact historical blob is the released authority
    assert not P.frozen_scope_exempt(path, repo=repo)                                   # ... and is never mistaken for the candidate
    _write_commit(repo, {path: _blob_bytes(pin) + b"\n# mutation\n"}, "mutate")
    assert not governance.released_engine_authority_matches(path, repo=repo)
    assert not P.frozen_scope_exempt(path, repo=repo)


# 11 ─ M7 coexistence: eleven reviewed blobs stay exact; neither slice confers approval on the other
def test_m7_eleven_blobs_are_unchanged_and_coexist_without_cross_approval():
    assert len(M7.M7_RC3_CANDIDATE_AUTHORITIES) == 11
    assert not set(M7.M7_RC3_CANDIDATE_AUTHORITIES) & set(P.PPA01_CANDIDATE_AUTHORITIES)      # no path overlap: the M7 map was not extended
    facts = M7.collect()
    assert any(p in facts["frozen_changes"] for p in PATHS)                              # raw M7 facts DO see the PPA-01 slice ...
    m7_only = dict(facts, frozen_changes=[p for p in facts["frozen_changes"] if p not in P.PPA01_CANDIDATE_AUTHORITIES])
    assert M7.content_violations(m7_only) == []                                          # ... which is excluded only as its own exact slice
    assert M7.content_violations(facts) != []                                            # without the exclusion M7 rejects unlisted changes
    assert M7.current_acceptance_granted() is False and P.candidate_is_financially_approved() is False


def test_a_substituted_ppa01_slice_is_not_excluded_from_the_m7_facts():
    facts = M7.collect()
    m7_only = dict(facts, frozen_changes=[p for p in facts["frozen_changes"] if p not in P.PPA01_CANDIDATE_AUTHORITIES])
    changed = dict(m7_only, frozen_changes=[*m7_only["frozen_changes"], "finco_core/revenue/generation.py"])     # as if the candidate were not excluded
    assert any("generation.py" in p for p in M7.content_violations(changed))


# 12 ─ approval and release stay BLOCKED without a complete independent record
def test_release_is_blocked_without_a_complete_independent_record_and_each_defect_is_rejected(known_good_facts):
    # KNOWN-GOOD baseline = immutable main after PR #313 (carries exactly the PPA-01 candidate), not today's moving integration HEAD; the live HEAD
    # content is still judged by test_exact_candidate_is_recognised_but_neither_approved_nor_released.
    accepted = copy.deepcopy(known_good_facts)
    accepted["record"] = copy.deepcopy(GOOD_RECORD)
    assert P.acceptance_violations(accepted) == []                                       # only a synthetic record in a synthetic fact set
    assert any("RELEASE_NOT_AUTHORIZED" in p for p in P.release_violations(accepted))    # approval alone never releases
    released = copy.deepcopy(accepted)
    released["record"]["release_authorized"] = True
    assert P.release_violations(released) == []                                          # explicit, separate, recorded
    defects = {
        "independent_reviewer": ["", None, "Claude", "the AI agent", "self-review by author"],
        "financial_owner": ["", None, "Anthropic assistant"],
        "reviewed_source_head": ["0" * 40, "", None],
        "accepted_blobs": [{**GOOD_RECORD["accepted_blobs"], PATHS[0]: "4" * 40}, {}, None],
        "scope": ["PRODUCTION_ACTIVATION", None],
        "decision_reference": ["", None],
    }
    for key, values in defects.items():
        for value in values:
            mutated = copy.deepcopy(accepted)
            mutated["record"][key] = value
            assert P.acceptance_violations(mutated), (key, value)
    mutated = copy.deepcopy(accepted)
    mutated["record"] = "approved"
    assert P.acceptance_violations(mutated)
    changed = copy.deepcopy(accepted)
    changed["blobs"][PATHS[1]] = "5" * 40                                                # a valid record never covers changed content
    assert any(PATHS[1] in p for p in P.acceptance_violations(changed))


def test_missing_or_malformed_facts_never_authorise(facts):
    assert P.content_violations({}) and P.acceptance_violations({}) and P.release_violations({})
    for key in facts:
        assert P.acceptance_violations({k: v for k, v in facts.items() if k != key}), key
    assert P.content_violations(dict(facts, source_head_ancestor=False))


# 13 ─ missing historical provenance fails closed
def test_the_historical_anchor_falls_back_to_head_when_provenance_is_missing(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {"README.md": "x"})
    monkeypatch.setattr(anchor, "REPO", repo)
    monkeypatch.setattr(anchor, "STREAM_TIPS", ("0" * 40, "1" * 40))
    assert anchor.anchored_head() == "HEAD"                                              # unknown tips: evaluate the FULL current tree
    git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    real_tip = git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(anchor, "STREAM_TIPS", (real_tip,))
    assert anchor.anchored_head() == "HEAD"                                              # origin/main missing: fail closed
    assert anchor.anchored_head("f" * 40) == "HEAD"


# 14 ─ a historical-stream (Radar/Crypto/...) financial change is still seen and rejected; the candidate commit is not attributed to it
def test_the_anchor_attributes_only_the_pre_candidate_history_to_historical_streams(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {"README.md": "x", **{p: b"baseline " + p.encode() for p in PATHS}})
    git(repo, "checkout", "-q", "-b", "rc")
    _write_commit(repo, {"app/radar/feature.py": "ok"}, "benign stream work")
    tip = git(repo, "rev-parse", "HEAD")
    _write_commit(repo, _candidate_files(), "PPA-01 candidate")
    monkeypatch.setattr(anchor, "REPO", repo)
    monkeypatch.setattr(anchor, "STREAM_TIPS", (tip,))
    assert anchor.anchored_head() == tip
    assert anchor.changed_paths("finco_core", "domain", "financial_engine") == []        # the candidate is not a historical-stream change
    # an UNAUTHORIZED frozen change made by a historical stream before the tip is still reported
    repo2 = _repo(tmp_path, {"README.md": "x"}, name="synthetic2")
    git(repo2, "checkout", "-q", "-b", "rc")
    _write_commit(repo2, {"finco_core/inputs/sneaky.py": "x = 1"}, "stream edits frozen core")
    tip2 = git(repo2, "rev-parse", "HEAD")
    _write_commit(repo2, {"docs/later.md": "later"}, "later")
    monkeypatch.setattr(anchor, "REPO", repo2)
    monkeypatch.setattr(anchor, "STREAM_TIPS", (tip2,))
    assert anchor.changed_paths("finco_core") == ["finco_core/inputs/sneaky.py"]
    monkeypatch.setattr(governance, "REPO", repo2)
    assert fig.strictly_frozen_changes(["finco_core/inputs/sneaky.py"]) == ["finco_core/inputs/sneaky.py"]


@pytest.mark.parametrize("path", ["finco_radar/other.py", "finco_yield/x.py", "app/radar_rwa/x.py", "app/crypto_access.py",
                                  "app/crypto_resource_access.py", "finco_core/tax/engine.py", "financial_engine/tax/atad.py"])
def test_previously_frozen_surfaces_remain_rejected(path):
    assert not governance.approved_by_active_model_v2_scope(path)
    assert not fig.approved_frozen_path(path)
    assert not P.frozen_scope_exempt(path)
    if path.startswith(("finco_radar/", "finco_core/")):
        assert fig.strictly_frozen_changes([path]) == [path]


def test_the_anchor_lifecycle_switches_to_head_once_its_tip_has_landed(tmp_path, monkeypatch):
    """Lifecycle of the historical anchor in an ISOLATED synthetic fixture: usable while the tip is pending, plain HEAD after it has landed.

    This is the lifecycle claim only. It deliberately says nothing about whether the CURRENT repository has any financial change: that is a
    separate fact judged by the authoritative current-integration gates, and it is no longer true "forever" once a new financial PR exists.
    """
    repo = _repo(tmp_path, {"README.md": "x", **{p: b"baseline " + p.encode() for p in PATHS}})
    git(repo, "checkout", "-q", "-b", "rc")
    _write_commit(repo, {"app/radar/feature.py": "ok"}, "benign stream work")
    tip = git(repo, "rev-parse", "HEAD")
    _write_commit(repo, _candidate_files(), "candidate after the historical tip")
    monkeypatch.setattr(anchor, "REPO", repo)
    monkeypatch.setattr(anchor, "STREAM_TIPS", (tip,))
    assert anchor.anchored_head() == tip                                   # pending: the historical tip is not on origin/main yet
    git(repo, "update-ref", "refs/remotes/origin/main", tip)               # the historical stream lands on main
    assert anchor.anchored_head() == "HEAD"                                # landed: the original guards evaluate the full current HEAD again
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert anchor.anchored_head() == "HEAD"
    monkeypatch.setattr(anchor, "STREAM_TIPS", ("0" * 40,))
    assert anchor.anchored_head() == "HEAD"                                # unknown provenance fails closed


def test_the_real_anchor_returns_to_head_after_integration_and_keeps_historical_proof():
    """Immutable historical proof for the REAL repository (independent of whatever the current integration changes)."""
    assert anchor.anchored_head() == "HEAD"                                # every historical tip has landed on main
    historical_tip = anchor.PPA01_PRE_INTEGRATION_TIP
    assert subprocess.run(["git", "merge-base", "--is-ancestor", historical_tip, "HEAD"], cwd=ROOT).returncode == 0
    assert subprocess.run(["git", "merge-base", "--is-ancestor", historical_tip, "origin/main"], cwd=ROOT).returncode == 0
    assert git(ROOT, "diff", "--name-only", P.PPA01_PUBLICATION_BASE, historical_tip,
               "--", "finco_core", "domain", "financial_engine") == ""
