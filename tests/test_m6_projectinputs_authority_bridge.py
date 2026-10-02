"""M6 canonical ProjectInputs authority bridge regression tests.

This suite proves that the project-owned sizing/repayment contract maps to the
already-shipped senior-debt M6 engine without changing legacy defaults.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from app.project_factories import (
    create_generic_data_center_reference,
    create_generic_ev_charging_reference,
    create_generic_solar_reference,
    create_generic_wind_reference,
)
from finco_core.inputs import (
    DebtSizingMode,
    FinancingParams,
    GearingBasisMode,
    GearingCapRepaymentMethod as ProjectRepaymentMethod,
    project_inputs_from_dict,
    project_inputs_to_dict,
)
from financial_engine.adapters.project_inputs import from_project_inputs
from financial_engine.financing.project_uses import compute_project_uses
from financial_engine.orchestrator import run_operating_model
from financial_engine.senior_debt.policy import (
    GearingCapRepaymentMethod as EngineRepaymentMethod,
    SeniorDebtSizingMode,
)
from financial_engine.senior_debt.project_adapter import (
    build_senior_debt_contract_from_project_inputs,
)
from financial_engine.senior_debt.solver import (
    DSCR_SCULPTING_INFEASIBLE,
    solve_senior_debt,
)
import m6_scenarios as sc


def _m6_project(repayment: ProjectRepaymentMethod, *, gearing: float = 0.40):
    base = create_generic_solar_reference()
    return replace(
        base,
        financing=replace(
            base.financing,
            debt_sizing_mode=DebtSizingMode.GEARING_CAP,
            gearing_basis_mode=GearingBasisMode.TOTAL_PROJECT_USES,
            gearing_ratio=gearing,
            gearing_cap_repayment_method=repayment,
        ),
    )


def _contract(project):
    operating = from_project_inputs(project)
    op_result = run_operating_model(operating)
    policy, inputs = build_senior_debt_contract_from_project_inputs(
        project, tuple(op_result.periods)
    )
    debt_periods = tuple(
        p for p in op_result.periods
        if p.is_operation
        and policy.repayment_start_period_index <= p.period_index
        <= policy.maturity_period_index
    )
    return policy, inputs, debt_periods


def _solve(project, pre_tax_value: float):
    policy, inputs, debt_periods = _contract(project)
    pre_tax = {p.period_index: pre_tax_value for p in debt_periods}
    tax_fn = sc.make_tax_fn(pre_tax)
    result = solve_senior_debt(
        policy=policy,
        inputs=inputs,
        periods=debt_periods,
        tax_cfads_fn=tax_fn,
    )
    return result, policy, inputs


def test_legacy_payload_shape_and_default_are_unchanged():
    project = create_generic_solar_reference()
    payload = project_inputs_to_dict(project)
    assert "gearing_cap_repayment_method" not in payload["financing"]

    restored = project_inputs_from_dict(deepcopy(payload))
    assert restored.financing.gearing_cap_repayment_method is ProjectRepaymentMethod.LEVEL_PRINCIPAL
    assert restored.financing.debt_sizing_mode is DebtSizingMode.FLAT_DSCR_SCULPTED
    assert project_inputs_to_dict(restored) == payload


def test_frozen_default_mode_and_repayment_default_remain_legacy_safe():
    financing = FinancingParams()
    assert financing.resolved_debt_sizing_mode() is DebtSizingMode.FROZEN_EXCEL_SCHEDULE
    assert financing.gearing_cap_repayment_method is ProjectRepaymentMethod.LEVEL_PRINCIPAL


def test_existing_flat_dscr_mapping_with_gearing_basis_stays_combined_minimum():
    project = create_generic_solar_reference()
    policy, inputs, _ = _contract(project)
    assert project.financing.debt_sizing_mode is DebtSizingMode.FLAT_DSCR_SCULPTED
    assert policy.sizing_mode is SeniorDebtSizingMode.COMBINED_MINIMUM
    assert policy.maximum_gearing == pytest.approx(project.financing.gearing_ratio)
    assert inputs.eligible_project_cost_keur == pytest.approx(
        compute_project_uses(project).total_project_uses_keur
    )


def test_existing_flat_dscr_mapping_without_gearing_basis_stays_dscr_only():
    base = create_generic_solar_reference()
    project = replace(
        base,
        financing=replace(base.financing, gearing_basis_mode=None),
    )
    policy, inputs, _ = _contract(project)
    assert policy.sizing_mode is SeniorDebtSizingMode.DSCR_SCULPTED
    assert policy.maximum_gearing is None
    assert inputs.eligible_project_cost_keur == 0.0


@pytest.mark.parametrize(
    ("project_method", "engine_method"),
    [
        (ProjectRepaymentMethod.LEVEL_PRINCIPAL, EngineRepaymentMethod.LEVEL_PRINCIPAL),
        (ProjectRepaymentMethod.DSCR_SCULPTED, EngineRepaymentMethod.DSCR_SCULPTED),
    ],
)
def test_gearing_cap_project_mode_maps_exactly_to_engine_policy(
    project_method, engine_method
):
    project = _m6_project(project_method)
    policy, inputs, _ = _contract(project)
    uses = compute_project_uses(project)

    assert policy.sizing_mode is SeniorDebtSizingMode.GEARING_CAP
    assert policy.gearing_cap_repayment_method is engine_method
    assert policy.maximum_gearing == pytest.approx(project.financing.gearing_ratio)
    assert inputs.eligible_project_cost_keur == pytest.approx(uses.total_project_uses_keur)


def test_level_and_m6_sculpted_keep_same_gearing_sized_debt_but_different_repayment():
    level = _m6_project(ProjectRepaymentMethod.LEVEL_PRINCIPAL, gearing=0.40)
    sculpted = _m6_project(ProjectRepaymentMethod.DSCR_SCULPTED, gearing=0.40)

    level_result, level_policy, level_inputs = _solve(level, 10_000.0)
    sculpt_result, sculpt_policy, sculpt_inputs = _solve(sculpted, 10_000.0)

    expected = compute_project_uses(level).total_project_uses_keur * 0.40
    assert level_policy.sizing_mode is SeniorDebtSizingMode.GEARING_CAP
    assert sculpt_policy.sizing_mode is SeniorDebtSizingMode.GEARING_CAP
    assert level_inputs.eligible_project_cost_keur == pytest.approx(
        sculpt_inputs.eligible_project_cost_keur
    )
    assert level_result.debt_size_keur == pytest.approx(expected)
    assert sculpt_result.debt_size_keur == pytest.approx(expected)
    assert level_result.debt_size_keur == pytest.approx(sculpt_result.debt_size_keur)
    assert level_result.binding_constraint == "GEARING"
    assert sculpt_result.binding_constraint == "GEARING"
    assert level_result.senior_principal_keur != pytest.approx(
        sculpt_result.senior_principal_keur
    )


def test_infeasible_m6_still_fails_with_canonical_reason():
    project = _m6_project(ProjectRepaymentMethod.DSCR_SCULPTED, gearing=0.75)
    result, policy, _ = _solve(project, 10.0)

    assert policy.sizing_mode is SeniorDebtSizingMode.GEARING_CAP
    assert result.diagnostics.is_authoritative is False
    assert result.diagnostics.termination_reason == DSCR_SCULPTING_INFEASIBLE


def test_non_gearing_mode_cannot_carry_non_default_gearing_repayment():
    base = create_generic_solar_reference()
    with pytest.raises(
        ValueError, match="GEARING_CAP_REPAYMENT_METHOD_REQUIRES_GEARING_CAP"
    ):
        replace(
            base.financing,
            gearing_cap_repayment_method=ProjectRepaymentMethod.DSCR_SCULPTED,
        )


def test_gearing_cap_requires_canonical_total_project_uses_basis():
    base = create_generic_solar_reference()
    with pytest.raises(ValueError, match="GEARING_CAP_REQUIRES_TOTAL_PROJECT_USES"):
        replace(
            base.financing,
            debt_sizing_mode=DebtSizingMode.GEARING_CAP,
            gearing_basis_mode=None,
        )


@pytest.mark.parametrize(
    "method",
    [ProjectRepaymentMethod.LEVEL_PRINCIPAL, ProjectRepaymentMethod.DSCR_SCULPTED],
)
def test_gearing_cap_serialization_round_trip(method):
    project = _m6_project(method)
    payload = project_inputs_to_dict(project)
    assert payload["financing"]["debt_sizing_mode"] == "gearing_cap"
    assert payload["financing"]["gearing_cap_repayment_method"] == method.value

    restored = project_inputs_from_dict(deepcopy(payload))
    assert restored.financing.debt_sizing_mode is DebtSizingMode.GEARING_CAP
    assert restored.financing.gearing_cap_repayment_method is method
    assert project_inputs_to_dict(restored) == payload


def test_unknown_sizing_mode_fails_closed_on_deserialization():
    payload = project_inputs_to_dict(_m6_project(ProjectRepaymentMethod.LEVEL_PRINCIPAL))
    payload["financing"]["debt_sizing_mode"] = "not_a_mode"
    with pytest.raises(ValueError):
        project_inputs_from_dict(payload)


def test_unknown_repayment_mode_fails_closed_on_deserialization():
    payload = project_inputs_to_dict(_m6_project(ProjectRepaymentMethod.LEVEL_PRINCIPAL))
    payload["financing"]["gearing_cap_repayment_method"] = "not_a_repayment_method"
    with pytest.raises(ValueError):
        project_inputs_from_dict(payload)


@pytest.mark.parametrize(
    "factory",
    [
        create_generic_solar_reference,
        create_generic_wind_reference,
        create_generic_data_center_reference,
        create_generic_ev_charging_reference,
    ],
)
def test_reference_projects_remain_defaulted_and_do_not_serialize_new_field(factory):
    project = factory()
    assert project.financing.debt_sizing_mode is DebtSizingMode.FLAT_DSCR_SCULPTED
    assert project.financing.gearing_cap_repayment_method is ProjectRepaymentMethod.LEVEL_PRINCIPAL
    payload = project_inputs_to_dict(project)
    assert "gearing_cap_repayment_method" not in payload["financing"]
