"""V8-B1: the candidate is recognised by exact content only, and recognition is not approval."""
from __future__ import annotations

import subprocess

import pytest

from tests import v8b1_solver_candidate as C


def _hash(data: bytes) -> str:
    return subprocess.run(["git", "hash-object", "--stdin"], input=data, capture_output=True, check=True).stdout.decode().strip()


def test_the_worktree_solver_is_exactly_the_recognised_candidate_and_the_predecessor_is_the_main_blob():
    assert _hash((C.ROOT / C.PATH).read_bytes()) == C.CANDIDATE_BLOB
    assert C.predecessor_is_the_main_blob()
    assert C.recognises(C.PATH, C.CANDIDATE_BLOB)


def test_recognition_is_not_approval():
    assert C.APPROVED is False


@pytest.mark.parametrize("mutation", [lambda b: b + b"\n# extra\n", lambda b: b.replace(b"converged or iteration == max_iter", b"True", 1),
                                      lambda b: b[:-1], lambda b: b.replace(b"abs_tol", b"abs_tol * 2", 1)])
def test_any_further_change_to_the_solver_loses_recognition(mutation):
    original = (C.ROOT / C.PATH).read_bytes()
    changed = mutation(original)
    assert changed != original and not C.recognises(C.PATH, _hash(changed))


@pytest.mark.parametrize("path", ["financial_engine/senior_debt/solver.pyc", "financial_engine/senior_debt/policy.py",
                                  "financial_engine/orchestrator.py", "financial_engine/senior_debt/solver.py.bak"])
def test_no_other_path_inherits_recognition(path):
    assert not C.recognises(path, C.CANDIDATE_BLOB)


def test_the_predecessor_blob_is_not_the_candidate():
    assert C.PREDECESSOR_BLOB != C.CANDIDATE_BLOB and not C.recognises(C.PATH, C.PREDECESSOR_BLOB)
