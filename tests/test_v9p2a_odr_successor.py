"""V9-P2a / OD-R exact-content successor: recognition of exactly six protected paths, fail-closed negative controls, separation of states.

Every negative control evaluates the REAL validator in ``tests/v9p2a_odr_successor.py`` against synthetic commits built from real Git objects in a
disposable clone (parent = the evaluated HEAD). Nothing is committed to the repository itself.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import quarterly_candidate_recognition as R
import rc7b_postmerge_successor as B
import rc7c_candidate_successor as C
import v9p2a_odr_successor as O

ROOT = Path(__file__).resolve().parent.parent
SIX = tuple(sorted(O.ODR_AUTHORITIES))
NEW_PATHS = ("financial_engine/shareholder_waterfall/model.py", "financial_engine/shl/maturity_authority.py",
             "financial_engine/shl/production.py")          # OD-R paths outside the twelve RC-7C paths


def _git(repo, *args, **kwargs):
    return subprocess.check_output(["git", *args], cwd=repo, **kwargs)


@pytest.fixture(scope="module")
def head():
    return _git(ROOT, "rev-parse", "HEAD").decode().strip()


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    clone = tmp_path_factory.mktemp("odr-successor") / "clone"
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
    problems = O.odr_violations(repo=repo, ref=ref)
    assert problems, "the tampered tree must not be recognised"
    assert not O.odr_recognized(repo=repo, ref=ref)
    assert R.recognized_state(repo=repo, ref=ref) is None
    assert R.candidate_blobs(repo=repo, ref=ref) == {}
    assert not any(R.scope_exempt(p, repo=repo, ref=ref) for p in (*SIX, *C.RC7C_CANDIDATE_AUTHORITIES))
    assert O.historical_subject(repo=repo, ref=ref) == ref               # never relabelled to RC-7C
    if fragment:
        assert any(fragment in p for p in problems), problems
    return problems


# ── the repository as it is ─────────────────────────────────────────────────────

def test_contract_constants_are_exact():
    assert len(SIX) == 6 and set(O.APPROVED_NEW_BLOBS) | set(O.PRESERVED_BLOBS) == set(SIX)
    assert not set(O.APPROVED_NEW_BLOBS) & set(O.PRESERVED_BLOBS)
    assert O.APPROVED_NEW_BLOBS == {
        "financial_engine/shl/maturity_authority.py": "b5fc2715cf4fb769878eb0534c95eb150479328f",
        "financial_engine/financing/generic_product_policy.py": "b7df63cd5be886d5971213c03f9bfff046913ae1",
        "financial_engine/financing/project.py": "3bc6c097b218d27be216cdd86133f2772a82ad70",
        "financial_engine/shareholder_waterfall/model.py": "9520b09b135c7fe39d3d4fac6a0c2462b7c1c4ca",
    }
    assert O.PRESERVED_BLOBS == {
        "financial_engine/orchestrator.py": "85c8008f2b4a656fd28eea1169689b19131576e4",
        "financial_engine/shl/production.py": "9bb852c235a988bff994c4327b3b63dd6d77ae20",
    }
    for path, superseded in O.SUPERSEDED_BLOBS.items():
        assert O.ODR_AUTHORITIES[path] != superseded
    assert set(O.ODR_AUTHORITIES) - set(C.RC7C_CANDIDATE_AUTHORITIES) == {
        "financial_engine/shareholder_waterfall/model.py", "financial_engine/shl/maturity_authority.py", "financial_engine/shl/production.py"}


def test_real_repository_is_exactly_the_odr_successor(head):
    assert O.odr_violations() == []
    assert R.recognized_state() == "ODR"
    blobs = R.candidate_blobs()
    assert blobs == {**C.RC7C_CANDIDATE_AUTHORITIES, **O.ODR_AUTHORITIES} and len(blobs) == 15
    for path, expected in blobs.items():
        assert O.blob(path) == expected, path
    assert C.rc7c_recognized() is False and B.postmerge_recognized() is False          # the historical validators are not widened
    assert C.rc7c_recognized(ref=O.RC7C_INTEGRATION_MAIN) and C.rc7c_recognized(ref=O.RC7C_MAIN)
    assert O.historical_subject() == O.RC7C_INTEGRATION_MAIN
    assert not R.scope_exempt("financial_engine/tax/engine.py") and not R.scope_exempt("finco_core/tax/engine.py")


def test_recognition_is_never_approval_activation_or_release():
    import finance_integrity_governance as fig
    import model_v2_governance as governance
    states = O.states()
    assert states["exact_odr_content_recognized"] is True
    assert states["financial_owner_exact_content_decision"] == "RECORDED_NOT_AUTHENTICATED"
    for denied in ("authenticated_owner_attestation", "merge_authorized", "product_activation", "od_r_default_policy", "financial_release"):
        assert states[denied] is False, denied
    for path in SIX:
        assert not governance.released_engine_authority_matches(path), path
    # recognition grants no approved-frozen exemption; production.py's exemption is the pre-existing path-only Finance Integrity allow-list
    assert {p for p in SIX if fig.approved_frozen_path(p)} == {"financial_engine/shl/production.py"}
    for module in (O, R):
        assert not any(hasattr(module, name) for name in ("approve", "admit", "release", "is_approved", "is_released", "is_admitted"))
    policy = (ROOT / O.POLICY_PATH).read_text(encoding="utf-8")
    assert O.SELECTOR_DEFAULT in policy


# ── negative controls ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", SIX)
def test_one_byte_change_of_each_protected_blob_is_rejected(repo, tmp_path, head, path):
    ref = mutate(repo, tmp_path, head, {path: show(repo, head, path) + b"\n"})
    assert_rejected(repo, ref, f"ODR_BLOB_MISMATCH: {path}")


@pytest.mark.parametrize("path", sorted(O.SUPERSEDED_BLOBS))
def test_superseded_candidate_content_is_rejected(repo, tmp_path, head, path):
    ref = mutate(repo, tmp_path, head, {path: _git(repo, "cat-file", "blob", O.SUPERSEDED_BLOBS[path])})
    assert_rejected(repo, ref, f"ODR_BLOB_MISMATCH: {path}")


def test_removal_of_a_protected_file_is_rejected(repo, tmp_path, head):
    path = "financial_engine/shl/maturity_authority.py"
    ref = mutate(repo, tmp_path, head, {path: None})
    assert_rejected(repo, ref, f"ODR_BLOB_MISMATCH: {path}")


@pytest.mark.parametrize("path", ["financial_engine/unreviewed_odr_extra.py", "financial_engine/tax/engine.py",
                                  "finco_core/inputs/unreviewed_extra.py", "domain/unreviewed_extra.py"])
def test_an_extra_protected_financial_path_is_rejected(repo, tmp_path, head, path):
    original = subprocess.run(["git", "show", f"{head}:{path}"], cwd=repo, capture_output=True).stdout
    ref = mutate(repo, tmp_path, head, {path: original + b"\n# synthetic\n"})
    assert_rejected(repo, ref, "ODR_PROTECTED_SCOPE_INVALID")


@pytest.mark.parametrize("path", ["finco_core/engine/period_engine.py", "financial_engine/senior_debt/project_adapter.py"])
def test_a_changed_unrelated_rc7c_path_is_rejected(repo, tmp_path, head, path):
    ref = mutate(repo, tmp_path, head, {path: show(repo, head, path) + b"\n"})
    problems = assert_rejected(repo, ref, f"ODR_RC7C_BLOB_CHANGED: {path}")
    assert any("ODR_PROTECTED_SCOPE_INVALID" in p for p in problems)


@pytest.mark.parametrize("path", O.HISTORICAL_AUTHORITY_MODULES)
def test_a_changed_historical_authority_module_is_rejected(repo, tmp_path, head, path):
    ref = mutate(repo, tmp_path, head, {path: show(repo, head, path) + b"\n# synthetic\n"})
    assert_rejected(repo, ref, f"ODR_HISTORICAL_GUARD_CHANGED: {path}")


def test_a_widened_recognition_hub_is_rejected(repo, tmp_path, head):
    path = "tests/quarterly_candidate_recognition.py"
    ref = mutate(repo, tmp_path, head, {path: show(repo, head, path) + b"\n# synthetic widening\n"})
    assert_rejected(repo, ref, f"ODR_WIRING_NOT_EXACT: {path}")


def test_changed_application_provenance_is_rejected(repo, tmp_path, head):
    path = "app/services/production_financial_authority.py"
    ref = mutate(repo, tmp_path, head, {path: show(repo, head, path) + b"\n"})
    assert_rejected(repo, ref, f"ODR_APPLICATION_BLOB_MISMATCH: {path}")


@pytest.mark.parametrize("path", ["app/workbook/quarterly_frequency_config.py", "app/workbook/junior_debt_config.py",
                                  "app/workbook/bess_config.py", "domain/revenue/advanced_products.py"])
def test_an_opened_activation_flag_is_rejected(repo, tmp_path, head, path):
    original = show(repo, head, path)
    opened = original.replace(b"ACTIVATION_ENABLED = False", b"ACTIVATION_ENABLED = True")
    assert opened != original
    ref = mutate(repo, tmp_path, head, {path: opened})
    problems = O.odr_violations(repo=repo, ref=ref)
    assert any("ACTIVATION_NOT_CLOSED" in p or "ODR_PROTECTED_SCOPE_INVALID" in p for p in problems), problems
    assert R.recognized_state(repo=repo, ref=ref) is None


def test_exact_bytes_without_ancestry_are_rejected(repo, tmp_path, head):
    ref = mutate(repo, tmp_path, head, {}, orphan=True)
    assert all(O.blob(p, ref, repo=repo) == b for p, b in O.ODR_AUTHORITIES.items())
    assert_rejected(repo, ref, "ODR_ANCESTRY_INVALID")


@pytest.mark.parametrize("name", ["RC7C_MAIN", "RC7C_INTEGRATION_MAIN", "REVIEWED_CANDIDATE"])
def test_an_altered_or_missing_checkpoint_is_rejected(monkeypatch, name):
    monkeypatch.setattr(O, "_CACHE", {})
    monkeypatch.setattr(O, name, "0" * 40)
    problems = O.odr_violations()
    assert any(p.startswith("ODR_CHECKPOINT_MISSING") for p in problems), problems
    assert R.recognized_state() is None


def test_a_substituted_predecessor_checkpoint_is_rejected(monkeypatch):
    monkeypatch.setattr(O, "_CACHE", {})
    monkeypatch.setattr(O, "RC7C_INTEGRATION_MAIN", O.RC7C_MAIN)          # an existing ancestor, but not the #333 integration
    problems = O.odr_violations()
    assert "ODR_INTEGRATION_LINEAGE_INVALID" in problems, problems


def test_a_manifest_cannot_authorise_unreviewed_content(monkeypatch):
    path = "financial_engine/financing/project.py"
    monkeypatch.setattr(O, "_CACHE", {})
    monkeypatch.setattr(O, "ODR_AUTHORITIES", {**O.ODR_AUTHORITIES, path: O.SUPERSEDED_BLOBS[path]})
    problems = O.odr_violations()
    assert f"ODR_MANIFEST_NOT_REVIEWED_CONTENT: {path}" in problems and f"ODR_BLOB_MISMATCH: {path}" in problems


def test_missing_history_is_rejected(tmp_path):
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--no-local", "--depth=1", "--no-checkout", str(ROOT), str(shallow)], check=True, capture_output=True)
    problems = O.odr_violations(repo=shallow)
    assert any(p.startswith("ODR_CHECKPOINT_MISSING") for p in problems), problems
    assert O.odr_violations(repo=tmp_path) == ["ODR_REF_UNAVAILABLE"]
