"""B1 canonical-path comparisons and narrowly bounded error re-decision."""
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.project_factories import create_default_data_center_project
import financial_engine.financing.project as project
from financial_engine.financing.generic_product_policy import (
    DEFAULT_GENERIC_FINANCING_POLICY, apply_generic_financing_policy,
)
from financial_engine.senior_debt.policy import SeniorDebtSizingMode
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


def test_capacity_runs_once_on_accepted_input_and_funded_iterations_unchanged(monkeypatch):
    inputs = inner_inputs()
    original = project.run_senior_debt_model
    calls = []

    def capture(model_input):
        calls.append(model_input)
        return original(model_input)

    monkeypatch.setattr(project, "run_senior_debt_model", capture)
    kwargs = dict(source_id="", baseline_commit_sha="", convergence_tolerance_keur=1e-7,
                  maximum_iterations=50, _typed_shl_context=None, _u2_period_financing_income=None)
    canonical = project._run_shl_senior_fixed_point(inputs, **kwargs, defer_capacity=False)
    baseline_calls = calls[:]
    calls.clear()
    candidate = project.run_project_financing_model(inputs)
    assert flatten(candidate) == flatten(canonical)
    is_capacity = lambda mi: mi.senior_debt_policy.sizing_mode is SeniorDebtSizingMode.DSCR_SCULPTED
    assert sum(map(is_capacity, calls)) == 1
    assert sum(map(is_capacity, baseline_calls)) == canonical.fixed_point_iteration_count
    assert [mi for mi in calls if not is_capacity(mi)] == [mi for mi in baseline_calls if not is_capacity(mi)]
    assert calls[-1] == [mi for mi in baseline_calls if is_capacity(mi)][-1]


def test_named_maturity_failure_redecides_once_without_masking_original_evidence(monkeypatch):
    calls = []

    def reject(inputs, **kwargs):
        calls.append(kwargs["defer_capacity"])
        residual = "12.123456789012" if kwargs["defer_capacity"] else "13.123456789012"
        raise ValueError(f"SHL_MATURITY_RESIDUAL_FAILS_CLOSED: closing balance {residual} kEUR")

    monkeypatch.setattr(project, "_run_shl_senior_fixed_point", reject)
    with pytest.raises(ValueError, match="13.123456789012"):
        project.run_project_financing_model(inner_inputs())
    assert calls == [True, False]


@pytest.mark.parametrize("error", [ValueError("invalid input"), RuntimeError("programming defect"),
                                  TypeError("bad type"), AssertionError("broken invariant")])
def test_unrelated_errors_are_not_swallowed_or_retried(monkeypatch, error):
    calls = []

    def reject(inputs, **kwargs):
        calls.append(kwargs["defer_capacity"])
        raise error

    monkeypatch.setattr(project, "_run_shl_senior_fixed_point", reject)
    with pytest.raises(type(error)) as caught:
        project.run_project_financing_model(inner_inputs())
    assert caught.value is error
    assert calls == [True]


def test_missing_capacity_evidence_still_refuses(monkeypatch):
    original = project.run_senior_debt_model

    def missing(model_input):
        if model_input.senior_debt_policy.sizing_mode is SeniorDebtSizingMode.DSCR_SCULPTED:
            return SimpleNamespace(senior_debt=None)
        return original(model_input)

    monkeypatch.setattr(project, "run_senior_debt_model", missing)
    with pytest.raises(RuntimeError, match="G2A DSCR capacity result is unavailable"):
        project.run_project_financing_model(inner_inputs())
