"""The Finance Integrity governance contract protects unrelated engine modules."""
from __future__ import annotations

from finance_integrity_governance import (
    APPROVED_FINANCE_INTEGRITY_ENGINE_PATHS as APPROVED,
    strictly_frozen_changes,
    unapproved_engine_changes,
)


def test_approved_engine_paths_are_allowed():
    assert unapproved_engine_changes(sorted(APPROVED)) == []


def test_unrelated_engine_modules_stay_protected():
    for path in (
        "financial_engine/tax/engine.py",
        "financial_engine/cfads.py",
        "financial_engine/shl/production.py",
        "financial_engine/operating/model.py",
    ):
        assert unapproved_engine_changes([path]) == [path]


def test_core_and_radar_have_no_exception():
    assert strictly_frozen_changes(["finco_core/tax/engine.py"]) == ["finco_core/tax/engine.py"]
    assert strictly_frozen_changes(["finco_radar/x.py"]) == ["finco_radar/x.py"]


def test_this_branch_stays_within_the_governance_contract():
    assert unapproved_engine_changes() == []
    assert strictly_frozen_changes() == []


def test_allow_list_entries_exist():
    from finance_integrity_governance import REPO
    for path in APPROVED:
        assert (REPO / path).is_file(), path
