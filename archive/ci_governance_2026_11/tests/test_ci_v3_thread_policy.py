"""Background threads left alive when pytest returns: closed by default, tolerated only by exact owner-approved name."""
import pytest

from tools.ci_v3_hosted_controller import worker_request
from tools.ci_v3_isolation import validate_allowed_daemon_threads
from tools.ci_v3_real_child import classify_threads
from tools.ci_v3_schema import ContractError

APPROVED = {"demo-cleanup": {"reason": "app startup daemon", "approval_reference": "OWNER-REF-1"}}


def test_default_policy_rejects_every_live_thread():
    assert classify_threads([("demo-cleanup", True), ("worker", False)], {}) == (["demo-cleanup", "worker"], [])


def test_only_an_exact_named_daemon_thread_is_tolerated():
    unapproved, approved = classify_threads([("demo-cleanup", True), ("demo-cleanup-2", True), ("other", True)], APPROVED)
    assert approved == ["demo-cleanup"] and unapproved == ["demo-cleanup-2", "other"]


def test_a_non_daemon_thread_is_never_tolerated_even_if_named():
    assert classify_threads([("demo-cleanup", False)], APPROVED) == (["demo-cleanup"], [])


@pytest.mark.parametrize("bad", [[], "x", {"": {"reason": "r", "approval_reference": "a"}}, {"t": "reason"},
    {"t": {"reason": "r"}}, {"t": {"reason": "r", "approval_reference": None}}, {"t": {"reason": " ", "approval_reference": "a"}},
    {"t": {"reason": "r", "approval_reference": "a", "extra": 1}}])
def test_malformed_or_unreferenced_allowlist_entries_are_rejected(bad):
    with pytest.raises(ContractError):
        validate_allowed_daemon_threads(bad)


def test_valid_allowlist_and_empty_default_are_accepted():
    assert validate_allowed_daemon_threads({}) == {} and validate_allowed_daemon_threads(APPROVED) == APPROVED


def test_worker_request_takes_the_allowlist_from_the_approved_bundle_only():
    bundle = {"inventory": {"nodes": []}, "isolation": {"allowed_daemon_threads": APPROVED}}
    assert worker_request({"c": 1}, "worker-0", bundle, ["tests/test_a.py"])["allowed_daemon_threads"] == APPROVED
    assert worker_request({"c": 1}, "worker-0", {"inventory": {}, "isolation": {}}, [])["allowed_daemon_threads"] == {}
