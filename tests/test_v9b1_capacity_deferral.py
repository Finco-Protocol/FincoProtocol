"""Correction A: every canonical intermediate capacity gate remains decisive."""
import ast
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

from app.project_factories import create_default_data_center_project
import financial_engine.financing.project as project
from financial_engine.financing.generic_product_policy import (
    DEFAULT_GENERIC_FINANCING_POLICY, apply_generic_financing_policy,
)
from financial_engine.senior_debt.policy import SeniorDebtSizingMode
from financial_engine.senior_debt.models import SeniorDebtNonConvergenceError
from tools.validate_v9b1 import flatten, run_case


BASELINE = json.loads(Path(__file__).with_name("v9b1_baseline.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(BASELINE["results"]))
def test_full_research_matrix_against_immutable_main(name):
    expected = BASELINE["results"][name]
    actual = run_case(name)
    assert {key: actual[key] for key in expected} == expected


def test_baseline_is_exact_main_with_31_feasible_and_18_rejected():
    assert BASELINE["baseline"] == "5be8c4b149712dd39b38b54c6fabcf3fcf47ef0d"
    assert sum(row["status"] == "feasible" for row in BASELINE["results"].values()) == 31
    assert sum(row["status"] == "rejected" for row in BASELINE["results"].values()) == 18


@pytest.mark.parametrize("name", sorted(BASELINE["extended_results"]))
def test_four_vertical_and_m6_exact_main_parity(name):
    expected = BASELINE["extended_results"][name]
    actual = run_case(name)
    assert {key: actual[key] for key in expected} == expected


def inner_inputs():
    inputs, _, _ = apply_generic_financing_policy(
        create_default_data_center_project(), DEFAULT_GENERIC_FINANCING_POLICY)
    return replace(inputs, financing=replace(inputs.financing, construction_financing=None))


def test_entire_inner_body_matches_immutable_capacity_first_baseline():
    repo = Path(__file__).resolve().parents[1]
    original = subprocess.check_output([
        "git", "show", BASELINE["baseline"] + ":financial_engine/financing/project.py"], cwd=repo)
    baseline = next(n for n in ast.parse(original).body
                    if isinstance(n, ast.FunctionDef) and n.name == "run_project_financing_model")
    current = next(n for n in ast.parse((repo / "financial_engine/financing/project.py").read_text()).body
                   if isinstance(n, ast.FunctionDef) and n.name == "_run_shl_senior_fixed_point")

    def numerical_body(function):
        start = next(i for i, node in enumerate(function.body)
                     if isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id == "uses" for target in node.targets))
        return ast.dump(ast.Module(body=function.body[start:], type_ignores=[]), include_attributes=False)

    assert numerical_body(current) == numerical_body(baseline)


def test_every_capacity_gate_precedes_funded_iteration(monkeypatch):
    inputs = inner_inputs()
    original = project.run_senior_debt_model
    calls = []

    def capture(model_input):
        calls.append(model_input)
        return original(model_input)

    monkeypatch.setattr(project, "run_senior_debt_model", capture)
    candidate = project.run_project_financing_model(inputs)
    is_capacity = lambda mi: mi.senior_debt_policy.sizing_mode is SeniorDebtSizingMode.DSCR_SCULPTED
    assert sum(map(is_capacity, calls)) == candidate.fixed_point_iteration_count
    assert is_capacity(calls[0])
    for index, model_input in enumerate(calls):
        if is_capacity(model_input):
            assert index + 1 < len(calls) and not is_capacity(calls[index + 1])


def test_synthetic_counterexample_old_deferral_succeeds_but_capacity_first_rejects(monkeypatch):
    """Injected control-flow proof, NOT a genuine economic input counterexample."""
    original = project.run_senior_debt_model
    model_inputs = []

    def record(model_input):
        model_inputs.append(model_input)
        return original(model_input)

    with monkeypatch.context() as scope:
        scope.setattr(project, "run_senior_debt_model", record)
        normal = project.run_project_financing_model(inner_inputs())
    is_capacity = lambda mi: mi.senior_debt_policy.sizing_mode is SeniorDebtSizingMode.DSCR_SCULPTED
    capacities = [mi for mi in model_inputs if is_capacity(mi)]
    funded = [mi for mi in model_inputs if not is_capacity(mi)]
    assert len(capacities) >= 2 and capacities[0].shareholder_loan is None
    assert capacities[-1].shareholder_loan is not None
    events = []
    failure = ValueError("SHL_MATURITY_RESIDUAL_FAILS_CLOSED: synthetic early capacity residual=11.25")

    def injected(model_input):
        events.append("capacity" if is_capacity(model_input) else "funded")
        if is_capacity(model_input) and model_input.shareholder_loan is None:
            raise failure
        return original(model_input)

    # A test-only old-order fixture executes the exact recorded funded inputs,
    # skips intermediate capacities, then accepts the final capacity. The private
    # review evidence additionally runs this injection on actual e7661945 source.
    for model_input in funded:
        funded_result = injected(model_input)
    assert injected(capacities[-1]).senior_debt is not None
    assert funded_result.senior_debt.debt_size_keur == normal.final_senior_commitment_keur
    events.clear()
    monkeypatch.setattr(project, "run_senior_debt_model", injected)
    with pytest.raises(ValueError) as caught:
        project.run_project_financing_model(inner_inputs())
    assert caught.value is failure
    assert events == ["capacity"]  # no funded work, retry or result publication

@pytest.mark.parametrize("error", [
    ValueError("SHL_MATURITY_RESIDUAL_FAILS_CLOSED: synthetic residual=11.25"),
    SeniorDebtNonConvergenceError("MAX_ITERATIONS_REACHED: synthetic capacity"),
    ValueError("SHL_LIMITATION_GROSS_INTEREST_MISMATCH: synthetic capacity"),
    ValueError("G2C_FINAL_INTEREST_MERGED_SHL_MISMATCH: synthetic capacity"),
    ValueError("BASE_BANK_AXIS_MISMATCH: synthetic capacity"),
    ValueError("Input validation failed: synthetic capacity"),
    OverflowError("synthetic numerical overflow"), RuntimeError("programming defect"),
    TypeError("bad type"), AssertionError("broken invariant"),
])
def test_all_early_capacity_failures_escape_unchanged_before_funded_work(monkeypatch, error):
    calls = []

    def reject(model_input):
        calls.append(model_input)
        raise error

    monkeypatch.setattr(project, "run_senior_debt_model", reject)
    with pytest.raises(type(error)) as caught:
        project.run_project_financing_model(inner_inputs())
    assert caught.value is error
    assert len(calls) == 1
    assert calls[0].senior_debt_policy.sizing_mode is SeniorDebtSizingMode.DSCR_SCULPTED


def test_missing_capacity_evidence_still_refuses(monkeypatch):
    original = project.run_senior_debt_model

    def missing(model_input):
        if model_input.senior_debt_policy.sizing_mode is SeniorDebtSizingMode.DSCR_SCULPTED:
            return SimpleNamespace(senior_debt=None)
        return original(model_input)

    monkeypatch.setattr(project, "run_senior_debt_model", missing)
    with pytest.raises(RuntimeError, match="G2A DSCR capacity result is unavailable"):
        project.run_project_financing_model(inner_inputs())
