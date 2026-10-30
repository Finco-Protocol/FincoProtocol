"""RC-5 / Correction B: the pinned CI budget successor is recognised by exact path and exact blob only (never a .github/ exception)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests import test_m3_two_driver_sensitivity as m3
from tests.test_rc3_integration_inventory import (
    CI200_WORKFLOW_BLOB, CI340_WORKFLOW_BLOB, INTEGRATION_HEAD, RC3_CI_WORKFLOW_BLOB, RC5_CI_WORKFLOW_BLOB, ci200_reference_text,
    ci200_workflow_successor_violations, ci340_workflow_successor_violations, current_workflow_chain_violations, git_blob_sha, rc5_reference_text,
    rc5_workflow_successor_violations,
)

WORKFLOW = ".github/workflows/ci_public_job.yml"
ROOT = Path(__file__).resolve().parent.parent


def _rc3_text():
    return subprocess.run(["git", "show", f"{INTEGRATION_HEAD}:{WORKFLOW}"], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def _head_text():
    """The HISTORICAL RC-5 workflow, derived from the pinned RC-3 reference by the fixed RC-5 edits (not read from the current worktree)."""
    return rc5_reference_text(_rc3_text())


def _current_text():
    return (ROOT / WORKFLOW).read_text(encoding="utf-8")


def test_the_pinned_successor_is_recognised_and_only_at_its_exact_path():
    assert m3.reviewed_ci_workflow_candidate(WORKFLOW) is True
    for other in (".github/workflows/public_safety_and_smoke.yml", ".github/workflows/ci_public_job.yml.bak", ".github/workflows/ci_public_job.yaml",
                  ".github/", ".github/workflows/", "finco_core/revenue/generation.py", "financial_engine/orchestrator.py"):
        assert m3.reviewed_ci_workflow_candidate(other) is False, other


def test_the_historical_rc3_reference_and_the_rc5_pin_are_independently_fixed():
    blob = lambda ref: subprocess.run(["git", "rev-parse", f"{ref}:{WORKFLOW}"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()  # noqa: E731
    assert blob(INTEGRATION_HEAD) == RC3_CI_WORKFLOW_BLOB == "036a5aef7cf9738b8bf7bf2f6294f24a998a928c"
    assert RC5_CI_WORKFLOW_BLOB == "0fa7e2bec303bb94053fe7799186e666dd1e06a9"
    assert git_blob_sha(_head_text()) == RC5_CI_WORKFLOW_BLOB                       # the historical RC-5 state is content-pinned
    assert rc5_workflow_successor_violations(_rc3_text(), _head_text()) == []
    assert blob("HEAD") in (RC5_CI_WORKFLOW_BLOB, CI200_WORKFLOW_BLOB, CI340_WORKFLOW_BLOB)   # HEAD is RC-5, CI-200M or the exact CI-340M successor
    assert CI200_WORKFLOW_BLOB == "f843237cae125867b8978fb2cc38665dcf0c64d8"
    assert current_workflow_chain_violations(_rc3_text(), _current_text()) == []


@pytest.mark.parametrize("label, mutate", [
    ("arbitrary change", lambda t: t + "\n# unreviewed\n"),
    ("budget raised", lambda t: t.replace("FINCO_CI_PYTEST_BUDGET_S: '6000'", "FINCO_CI_PYTEST_BUDGET_S: '6001'")),
    ("timeout raised", lambda t: t.replace("timeout-minutes: 130", "timeout-minutes: 131")),
    ("grace changed", lambda t: t.replace("FINCO_CI_EXIT_GRACE_S: '240'", "FINCO_CI_EXIT_GRACE_S: '241'")),
    ("stall changed", lambda t: t.replace("FINCO_CI_STALL_S: '300'", "FINCO_CI_STALL_S: '900'")),
    ("permissions changed", lambda t: t.replace("jobs:", "permissions:\n  contents: write\njobs:", 1)),
    ("test selection -k", lambda t: t.replace("tools/ci_pytest_runner.py", "tools/ci_pytest_runner.py -k fast", 1)),
    ("test deselected", lambda t: t.replace("tools/ci_pytest_runner.py", "tools/ci_pytest_runner.py --deselect tests/x.py::t", 1)),
    ("junit evidence removed", lambda t: t.replace("--junitxml=artifacts/results.xml", "")),
    ("artifact check relaxed", lambda t: t.replace("if-no-files-found: error", "if-no-files-found: ignore")),
    ("failure tolerated", lambda t: t.replace("steps:", "continue-on-error: true\n    steps:", 1)),
])
def test_any_other_workflow_change_is_rejected(label, mutate):
    mutated = mutate(_head_text())
    assert mutated != _head_text(), label
    assert rc5_workflow_successor_violations(_rc3_text(), mutated), label


def test_missing_or_wrong_blob_evidence_is_rejected(monkeypatch):
    real = m3._checked_git

    def lie(index, wrong):
        def fake(*args):
            fake.calls = getattr(fake, "calls", 0) + 1
            value = real(*args)
            return wrong if args[:1] == ("hash-object",) and index == "worktree" or (
                args[:1] == ("rev-parse",) and args[1].startswith("HEAD:") and index == "head") or (
                args[:1] == ("rev-parse",) and args[1].startswith(INTEGRATION_HEAD) and index == "rc3") else value
        return fake
    for kind in ("worktree", "head", "rc3"):
        monkeypatch.setattr(m3, "_checked_git", lie(kind, "0" * 40))
        assert m3.reviewed_ci_workflow_candidate(WORKFLOW) is False, kind
    monkeypatch.setattr(m3, "_checked_git", lambda *a: None)                                  # git facts unavailable: fail closed
    assert m3.reviewed_ci_workflow_candidate(WORKFLOW) is False


def test_the_authorised_rc5_budgets_are_unchanged_in_the_historical_state():
    text = _head_text()
    for needle in ("timeout-minutes: 130", "FINCO_CI_PYTEST_BUDGET_S: '6000'", "FINCO_CI_EXIT_GRACE_S: '240'", "FINCO_CI_STALL_S: '300'",
                   "FULL, UNSHARDED, EXACT HEAD"):
        assert needle in text, needle


def test_the_historical_ci200_budgets_and_their_fit():
    text = ci200_reference_text(_head_text())                                          # derived from the pinned RC-5 text, never the worktree
    assert ci200_workflow_successor_violations(_head_text(), text) == []
    assert git_blob_sha(text) == CI200_WORKFLOW_BLOB
    for needle in ("timeout-minutes: 220", "FINCO_CI_PYTEST_BUDGET_S: '12000'", "FINCO_CI_EXIT_GRACE_S: '240'", "FINCO_CI_STALL_S: '300'",
                   "FULL, UNSHARDED, EXACT HEAD"):
        assert needle in text, needle
    assert 12000 + 240 + 15 * 60 <= 220 * 60


def test_the_current_ci340_budgets_fit_under_the_hosted_ceiling():
    ci200 = ci200_reference_text(_head_text())
    text = _current_text()
    assert ci340_workflow_successor_violations(ci200, text) == []
    assert git_blob_sha(text) == CI340_WORKFLOW_BLOB
    for needle in ("timeout-minutes: 340", "FINCO_CI_PYTEST_BUDGET_S: '19200'", "FINCO_CI_EXIT_GRACE_S: '240'", "FINCO_CI_STALL_S: '300'",
                   "FULL, UNSHARDED, EXACT HEAD"):
        assert needle in text, needle
    assert 19200 + 240 + 15 * 60 <= 340 * 60 <= 360 * 60                                # inside the 360-minute GitHub-hosted job ceiling


@pytest.mark.parametrize("label, mutate", [
    ("timeout raised beyond the hosted ceiling", lambda t: t.replace("timeout-minutes: 340", "timeout-minutes: 440")),
    ("timeout raised by one", lambda t: t.replace("timeout-minutes: 340", "timeout-minutes: 341")),
    ("budget raised", lambda t: t.replace("FINCO_CI_PYTEST_BUDGET_S: '19200'", "FINCO_CI_PYTEST_BUDGET_S: '19201'")),
    ("budget does not fit", lambda t: t.replace("FINCO_CI_PYTEST_BUDGET_S: '19200'", "FINCO_CI_PYTEST_BUDGET_S: '20000'")),
    ("grace changed", lambda t: t.replace("FINCO_CI_EXIT_GRACE_S: '240'", "FINCO_CI_EXIT_GRACE_S: '241'")),
    ("stall changed", lambda t: t.replace("FINCO_CI_STALL_S: '300'", "FINCO_CI_STALL_S: '900'")),
    ("arbitrary change", lambda t: t + "\n# unreviewed\n"),
    ("failure tolerated", lambda t: t.replace("steps:", "continue-on-error: true\n    steps:", 1)),
    ("test selection -k", lambda t: t.replace("tools/ci_pytest_runner.py", "tools/ci_pytest_runner.py -k fast", 1)),
])
def test_any_other_ci340_change_is_rejected(label, mutate):
    ci200 = ci200_reference_text(_head_text())
    mutated = mutate(_current_text())
    assert mutated != _current_text(), label
    assert ci340_workflow_successor_violations(ci200, mutated), label
    assert current_workflow_chain_violations(_rc3_text(), mutated), label
