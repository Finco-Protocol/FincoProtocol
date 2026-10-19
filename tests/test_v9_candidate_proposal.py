"""Negative controls for proposal bytes; no financial release authorization."""
import copy

import pytest

from tests import v9_candidate_proposal as guard


def fixture():
    entries = {p: {"candidate": f"{i + 1:040x}", "predecessor": f"{i + 10:040x}"}
               for i, p in enumerate(guard.PATHS)}
    manifest = {"base": guard.BASE, "files": entries, **{name: False for name in guard.STATES}}
    facts = {"base": guard.BASE, "head": "a" * 40, "ancestor": True,
             "blobs": {p: v["candidate"] for p, v in entries.items()},
             "predecessors": {p: v["predecessor"] for p, v in entries.items()},
             "changes": {p: "M" for p in guard.PATHS}, "closed": True, "quarterly_closed": True}
    return manifest, facts


def test_exact_synthetic_proposal_bytes_are_not_financial_approval():
    manifest, facts = fixture()
    assert guard.violations(manifest, facts) == []
    assert all(manifest[name] is False for name in guard.STATES)


@pytest.mark.parametrize("path", guard.PATHS)
def test_changed_blob_is_rejected(path):
    manifest, facts = fixture()
    facts["blobs"][path] = "f" * 40
    assert guard.violations(manifest, facts)


@pytest.mark.parametrize("path", guard.PATHS)
def test_missing_path_is_rejected(path):
    manifest, facts = fixture()
    del manifest["files"][path]
    assert guard.violations(manifest, facts)


@pytest.mark.parametrize("path", ["finco_core/inputs/_models.py", "financial_engine/tax/engine.py",
    "domain/revenue/revenue_config.py", "app/v2/router.py", "tests/model_v2_governance.py",
    ".github/workflows/public-safety.yml"])
def test_unrelated_financial_product_governance_and_ci_changes_rejected(path):
    manifest, facts = fixture()
    facts["changes"][path] = "M"
    assert guard.violations(manifest, facts)


@pytest.mark.parametrize("state", guard.STATES)
def test_proposal_cannot_turn_on_any_approval_or_release(state):
    manifest, facts = fixture()
    manifest[state] = True
    assert guard.violations(manifest, facts)


@pytest.mark.parametrize("field", ["base", "head", "ancestor", "changes", "closed", "quarterly_closed"])
def test_missing_or_invalid_provenance_and_activation_fail_closed(field):
    manifest, facts = fixture()
    facts[field] = None
    assert guard.violations(manifest, facts)


def test_wrong_predecessor_and_additional_manifest_file_rejected():
    manifest, facts = fixture()
    path = guard.PATHS[0]
    manifest["files"][path]["predecessor"] = "e" * 40
    assert guard.violations(manifest, facts)
    manifest, facts = fixture()
    manifest["files"]["financial_engine/extra.py"] = copy.deepcopy(manifest["files"][path])
    assert guard.violations(manifest, facts)


def test_literal_closed_state_cannot_be_dynamic_or_truthy():
    assert guard.false_literals("ACTIVATION_ENABLED = False", ("ACTIVATION_ENABLED",))
    for source in ("ACTIVATION_ENABLED = 0", "ACTIVATION_ENABLED = bool(0)",
                   "ACTIVATION_ENABLED = True", "# missing", "invalid = ("):
        assert not guard.false_literals(source, ("ACTIVATION_ENABLED",))


def test_repository_matches_only_the_declared_unapproved_proposal():
    assert guard.repository_violations() == []


def test_missing_git_reference_is_rejected_without_approval():
    assert guard.repository_violations(ref="0" * 40)
