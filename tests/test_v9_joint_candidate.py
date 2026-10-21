"""V9 stays disabled; numerical proposals never replace unproved canonical decisions."""
from __future__ import annotations

import ast
import dataclasses as dc
from pathlib import Path
import subprocess
import pickle
from types import SimpleNamespace
from decimal import Decimal, localcontext

import pytest

from app.project_factories import create_default_solar_project
from app.services import production_financial_authority as pfa
from financial_engine.financing import v9_candidate as candidate
from financial_engine.financing.v9_numerics import Anderson, JointSettings, ProposalRefused
from tools.v9_joint_acceptance import flatten

BASE = "5996453b8d5bbfaa48bc06922fc6963cf94d2f84"


def test_g2a_function_is_entirely_unchanged_from_current_main():
    root = Path(__file__).resolve().parents[1]
    path = "financial_engine/financing/project.py"
    old = subprocess.check_output(["git", "show", BASE + ":" + path], cwd=root)
    now = (root / path).read_text()

    def body(text):
        return ast.dump(next(node for node in ast.parse(text).body
                            if isinstance(node, ast.FunctionDef)
                            and node.name == "run_project_financing_model"), include_attributes=False)
    assert body(old) == body(now)


def test_activation_and_all_financial_approvals_are_closed():
    assert candidate.ACTIVATION_ENABLED is False
    assert candidate.FINANCIAL_PRECISION_APPROVED is False
    assert candidate.INTERMEDIATE_FAILURE_EQUIVALENCE_PROVED is False
    with pytest.raises(ProposalRefused, match="ACTIVATION_CLOSED"):
        candidate.require_production_activation()


@pytest.mark.parametrize("settings", [dict(maximum_iterations=0), dict(maximum_iterations=51),
    dict(maximum_iterations=True), dict(depth=0), dict(accelerate=1),
    dict(terminal_switch=float("nan")), dict(terminal_switch=0)])
def test_invalid_settings_refused(settings):
    with pytest.raises(ValueError):
        JointSettings(**settings)


@pytest.mark.parametrize("vector", [(float("nan"),) * 6, (float("inf"),) * 6, (-1.,) * 6, (1.,) * 5])
def test_invalid_mapped_state_refused_not_clipped(vector):
    with pytest.raises(ProposalRefused):
        Anderson(JointSettings()).step(vector)


@pytest.mark.parametrize("proposal", [(float("nan"),) * 6, (-1.,) * 6, (1e100,) * 6])
def test_bad_acceleration_falls_back_to_exact_plain_map(monkeypatch, proposal):
    acceleration = Anderson(JointSettings(terminal_switch=1e-12))
    acceleration.step((0.,) * 6)
    acceleration.step((1.,) * 6)
    monkeypatch.setattr(acceleration, "_extrapolate", lambda: proposal)
    mapped = (1.1,) * 6
    value, plain = acceleration.step(mapped)
    assert value == mapped and plain
    assert acceleration.refused == 1


def test_terminal_phase_cannot_accept_accelerated_convergence():
    acceleration = Anderson(JointSettings())
    acceleration.step((1.,) * 6)
    value, plain = acceleration.step((1.000001,) * 6)
    assert plain and acceleration.terminal and value == (1.000001,) * 6


def test_linear_numerical_proposal_against_independent_decimal_fixed_point():
    with localcontext() as context:
        context.prec = 60
        expected = Decimal(100) / (Decimal(1) - Decimal("0.02"))
        acceleration = Anderson(JointSettings())
        state = (0.,) * 6
        for _ in range(15):
            state, plain = acceleration.step(tuple(100. + .02 * v for v in state))
        assert plain
        assert max(abs(Decimal.from_float(v) - expected) for v in state) < Decimal("1e-12")


def test_peak_period_switch_preserves_original_target_authority():
    inputs = create_default_solar_project()
    policy = candidate.DEFAULT_GENERIC_FINANCING_POLICY
    joint = candidate.JointContext(inputs, policy, JointSettings())
    targets = []
    for due in ((100., 30., 20.), (100., 20., 30.)):
        inner = SimpleNamespace(project_model_result=SimpleNamespace(
            senior_debt=SimpleNamespace(senior_debt_service_keur=due)))
        targets.append(joint.target(inner))
    expected = float(Decimal(30) * Decimal(inputs.financing.dsra_months) * Decimal(2) / Decimal(12))
    assert targets == [expected, expected]


@pytest.mark.parametrize("change", ["inputs", "source", "base", "income"])
def test_precomputed_financing_binding_rejects_wrong_snapshot(change):
    inputs = create_default_solar_project()
    result = object()
    binding = candidate.FinancingBinding(candidate._identity(inputs, "run", "base"), result)
    assert binding.consume(inputs, "run", "base", ()) is result
    wrong = dc.replace(inputs, financing=dc.replace(inputs.financing, gearing_ratio=.5)) if change == "inputs" else inputs
    with pytest.raises(ProposalRefused, match="BINDING_MISMATCH"):
        binding.consume(wrong, "other" if change == "source" else "run",
                        "other" if change == "base" else "base", (object(),) if change == "income" else ())


def test_successful_proposal_does_not_override_early_canonical_rejection(monkeypatch):
    inputs = create_default_solar_project()
    fake = SimpleNamespace(authority_metadata={})
    monkeypatch.setattr(candidate, "_proposal", lambda *args: (object(), inputs, object(), {}))
    monkeypatch.setattr(pfa, "_assemble_clean_run", lambda *args: fake)
    rejection = ValueError("SHL_MATURITY_RESIDUAL_FAILS_CLOSED: synthetic skipped outer state")
    calls = []

    def reject(*args, **kwargs):
        calls.append("canonical")
        raise rejection
    monkeypatch.setattr(pfa, "run_clean_production", reject)
    with pytest.raises(ValueError) as error:
        candidate.evaluate_candidate(inputs)
    assert error.value is rejection
    assert calls == ["canonical"]


def test_real_joint_trajectory_skips_a_synthetic_outer_failure_but_guard_rejects(monkeypatch):
    """Injected control-flow counterexample; NOT a genuine economic input defect."""
    from finco_core.construction import stage_b2
    real = stage_b2.run_stage_b2_provisional
    inputs = create_default_solar_project()
    canonical_configs, joint_configs = [], []

    def record(target):
        def run(config):
            target.append(pickle.dumps(config, protocol=5))
            return real(config)
        return run

    with monkeypatch.context() as scope:
        scope.setattr(stage_b2, "run_stage_b2_provisional", record(canonical_configs))
        pfa._POLICY_RUN_CACHE.clear()
        pfa.run_clean_production(inputs, project_type="Solar")
    with monkeypatch.context() as scope:
        scope.setattr(stage_b2, "run_stage_b2_provisional", record(joint_configs))
        _, details = candidate.evaluate_candidate(inputs, project_type="Solar", verify_canonical=False)
        assert details["candidate_eligible"]
    target = next(config for config in canonical_configs if config not in joint_configs)

    def reject_skipped_state(config):
        if pickle.dumps(config, protocol=5) == target:
            raise ValueError("V9_SYNTHETIC_OUTER_FUNDING_REFUSAL: residual=11.25 kEUR")
        return real(config)

    monkeypatch.setattr(stage_b2, "run_stage_b2_provisional", reject_skipped_state)
    pfa._POLICY_RUN_CACHE.clear()
    with pytest.raises(pfa.CleanProductionRunUnavailable) as baseline_error:
        pfa.run_clean_production(inputs, project_type="Solar")
    _, details = candidate.evaluate_candidate(inputs, project_type="Solar", verify_canonical=False)
    assert details["result_kind"] == "NON_AUTHORITATIVE_PROPOSAL_ONLY"
    pfa._POLICY_RUN_CACHE.clear()
    with pytest.raises(pfa.CleanProductionRunUnavailable) as guarded_error:
        candidate.evaluate_candidate(inputs, project_type="Solar")
    assert str(guarded_error.value) == str(baseline_error.value)
    assert guarded_error.value.reason_code == baseline_error.value.reason_code


@pytest.mark.parametrize("failure", [ProposalRefused("V9_JOINT_BUDGET_EXHAUSTED"),
    ValueError("financial capacity refusal"), RuntimeError("non-convergence"),
    TypeError("unexpected programming error")])
def test_failed_proposal_is_redecided_once_not_financially_accepted(monkeypatch, failure):
    def fail(*args):
        raise failure
    monkeypatch.setattr(candidate, "_proposal", fail)
    result = object()
    calls = []

    def canonical(*args, **kwargs):
        calls.append("canonical")
        return result
    monkeypatch.setattr(pfa, "run_clean_production", canonical)
    actual, evidence = candidate.evaluate_candidate(create_default_solar_project(), verify_canonical=False)
    assert actual is result and calls == ["canonical"]
    assert evidence["result_kind"] == "CANONICAL_REDECISION"
    assert evidence["proposal_error"]["type"] == type(failure).__qualname__


def test_forced_real_senior_nonconvergence_preserves_canonical_rejection(monkeypatch):
    import financial_engine.senior_debt.solver as solver
    from financial_engine.senior_debt.models import SeniorDebtNonConvergenceError

    def refuse(*args, **kwargs):
        raise SeniorDebtNonConvergenceError("V9_FORCED_NONCONVERGENCE: no feasible result")

    monkeypatch.setattr(solver, "solve_senior_debt", refuse)
    inputs = create_default_solar_project()
    pfa._POLICY_RUN_CACHE.clear()
    with pytest.raises(pfa.CleanProductionRunUnavailable) as original:
        pfa.run_clean_production(inputs, project_type="Solar")
    pfa._POLICY_RUN_CACHE.clear()
    with pytest.raises(pfa.CleanProductionRunUnavailable) as guarded:
        candidate.evaluate_candidate(inputs, project_type="Solar")
    assert str(guarded.value) == str(original.value)
    assert guarded.value.reason_code == original.value.reason_code


def test_guarded_solar_is_bit_identical_and_retains_all_canonical_evidence():
    inputs = create_default_solar_project()
    pfa._POLICY_RUN_CACHE.clear()
    expected = pfa.run_clean_production(inputs, project_type="Solar")
    pfa._POLICY_RUN_CACHE.clear()
    actual, evidence = candidate.evaluate_candidate(inputs, project_type="Solar")
    assert flatten(actual) == flatten(expected)
    assert evidence["candidate_eligible"] and evidence["canonical_validation_required"]
    assert evidence["result_kind"] == "CANONICAL_REDECISION"


def test_forced_budget_exhaustion_returns_exact_original_solar():
    inputs = create_default_solar_project()
    pfa._POLICY_RUN_CACHE.clear()
    expected = pfa.run_clean_production(inputs, project_type="Solar")
    pfa._POLICY_RUN_CACHE.clear()
    actual, evidence = candidate.evaluate_candidate(inputs, project_type="Solar", settings=JointSettings(maximum_iterations=1))
    assert flatten(actual) == flatten(expected)
    assert "V9_JOINT_BUDGET_EXHAUSTED" in evidence["proposal_error"]["text"]


def test_request_local_acceleration_state_is_not_shared():
    a, b = Anderson(JointSettings()), Anderson(JointSettings())
    a.step((1.,) * 6)
    assert b.previous is None and b.history == []


def test_guard_scope_closes_and_is_not_reused_by_another_run(monkeypatch):
    from financial_engine.run_scope import current_run_scope
    scopes = []

    def decline(*args):
        raise ProposalRefused("controlled")

    def canonical(*args, **kwargs):
        scopes.append(current_run_scope())
        assert scopes[-1] is not None
        return object()

    monkeypatch.setattr(candidate, "_proposal", decline)
    monkeypatch.setattr(pfa, "run_clean_production", canonical)
    assert current_run_scope() is None
    for _ in range(2):
        candidate.evaluate_candidate(create_default_solar_project())
        assert current_run_scope() is None
    assert scopes[0] is not scopes[1]


def test_no_default_product_caller_imports_candidate_entry():
    root = Path(__file__).resolve().parents[1]
    for path in (root / "app").rglob("*.py"):
        assert "financing.v9_candidate" not in path.read_text(encoding="utf-8"), path
