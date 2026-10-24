"""G6: the production policy-run memo can never serve a candidate-computed result to a canonical Run
(or the reverse), and with V10 off its key is byte-for-byte the pre-V10 key."""
from __future__ import annotations

import hashlib

import pytest

from app.services import production_financial_authority as pfa
from financial_engine.native_v10.config import NativeConfig, native_run


@pytest.fixture(autouse=True)
def _isolated_memo(monkeypatch):
    monkeypatch.setattr(pfa, "_POLICY_RUN_CACHE", {})


def _pre_v10_key(effective_inputs, policy) -> str:
    """The key formula at the research base (dd1af63), recomputed independently."""
    import financial_engine.orchestrator as orch
    import financial_engine.senior_debt.solver as solver
    import financial_engine.shl.production as shl

    engine_identity = tuple(id(getattr(m, n, None)) for m, n in (
        (solver, "_backward_dscr_capacity"), (solver, "_solve_dscr"), (solver, "_solve_combined"),
        (shl, "compute_shareholder_loan_schedules"), (orch, "compute_shareholder_loan_schedules"),
        (orch, "run_project_model")))
    material = repr(effective_inputs) + "|" + repr(policy) + "|" + repr(engine_identity)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def test_off_key_is_unchanged():
    inputs, policy = ("inputs", 1.0, -0.0), ("policy", "v1")
    value = pfa._memoised_policy_run(inputs, policy, lambda: "computed")
    assert value == "computed"
    assert list(pfa._POLICY_RUN_CACHE) == [_pre_v10_key(inputs, policy)]


def test_candidate_and_canonical_results_never_cross():
    calls = []

    def compute(tag):
        def run():
            calls.append(tag)
            return tag
        return run

    inputs, policy = ("same-inputs",), ("same-policy",)
    assert pfa._memoised_policy_run(inputs, policy, compute("off")) == "off"
    with native_run(NativeConfig(mode="candidate")):
        assert pfa._memoised_policy_run(inputs, policy, compute("stage1")) == "stage1"
    with native_run(NativeConfig(mode="candidate", stage2_experimental=True)):
        assert pfa._memoised_policy_run(inputs, policy, compute("stage2")) == "stage2"
    # each configuration is served only its own entry
    assert pfa._memoised_policy_run(inputs, policy, compute("off-again")) == "off"
    with native_run(NativeConfig(mode="candidate")):
        assert pfa._memoised_policy_run(inputs, policy, compute("stage1-again")) == "stage1"
    assert calls == ["off", "stage1", "stage2"]
    assert len(pfa._POLICY_RUN_CACHE) == 3
