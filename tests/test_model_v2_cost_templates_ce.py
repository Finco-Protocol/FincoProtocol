"""Model V2 Cost Template Correction E regression matrix.

Strict-boolean state applicability: None is NOT accepted (required field),
extraction never masks malformed input, True/False remain valid.
"""
from __future__ import annotations

import pytest

from app.services.cost_template import (
    CapexFieldState,
    CapexSubLineState,
    ContingencyState,
    CostProjectState,
    MaterializationContext,
    OpexItemState,
    OpexSubLineState,
    extract_client_cost_template,
    build_materialization_plan,
    plan_to_project_state,
    resolve_cost_template,
)
TOL = 1e-9


def _state(**overrides) -> CostProjectState:
    """A minimal valid state with one of each applicability-bearing row;
    per-test overrides inject the malformed value."""
    base = dict(
        capacity_mw=64.0,
        project_ref="proj-ce",
        capex_fields=(CapexFieldState(
            field_name="grid_connection", parent_code="C.03",
            label="Grid", amount_keur=100.0),),
        opex_items=(OpexItemState(
            name="Land Lease", parent_code="B.07",
            y1_amount_keur=50.0, annual_inflation=0.02),),
        capex_sub_lines=(CapexSubLineState(
            parent_category_code="C.01", business_code="C.01.U001",
            label="User row", amount_keur=30.0),),
        opex_sub_lines=(OpexSubLineState(
            parent_group_code="B.01", business_code="B.01.U001",
            label="User service", amount_keur=20.0, inflation_pct=2.0),),
        contingency=ContingencyState(capex_pct=6.0, opex_pct=6.0),
    )
    base.update(overrides)
    return CostProjectState(**base)


def _assert_applicability_invalid(state, label):
    """The malformed applicability value must fail closed at validate and
    never reach extraction (no truthiness masking)."""
    with pytest.raises(ValueError, match="COST_STATE_APPLICABILITY_INVALID") as exc:
        state.validate()
    assert label in str(exc.value)
    with pytest.raises(ValueError, match="COST_STATE_APPLICABILITY_INVALID"):
        extract_client_cost_template(state, template_id="T", version=1)


# ---------------------------------------------------------------------------
# A-F. None applicability fails closed on every required field
# ---------------------------------------------------------------------------

def test_ce_a_capex_field_is_active_none_fails():
    _assert_applicability_invalid(
        _state(capex_fields=(CapexFieldState(
            field_name="grid_connection", parent_code="C.03",
            label="Grid", amount_keur=100.0, is_active=None),)),
        "CapexFieldState.is_active")


def test_ce_b_opex_item_is_active_none_fails():
    _assert_applicability_invalid(
        _state(opex_items=(OpexItemState(
            name="Land Lease", parent_code="B.07",
            y1_amount_keur=50.0, annual_inflation=0.02, is_active=None),)),
        "OpexItemState.is_active")


def test_ce_c_capex_subline_is_active_none_fails():
    _assert_applicability_invalid(
        _state(capex_sub_lines=(CapexSubLineState(
            parent_category_code="C.01", business_code="C.01.U001",
            label="User row", amount_keur=30.0, is_active=None),)),
        "CapexSubLineState.is_active")


def test_ce_d_opex_subline_is_active_none_fails():
    _assert_applicability_invalid(
        _state(opex_sub_lines=(OpexSubLineState(
            parent_group_code="B.01", business_code="B.01.U001",
            label="User service", amount_keur=20.0, inflation_pct=2.0,
            is_active=None),)),
        "OpexSubLineState.is_active")


def test_ce_e_contingency_capex_active_none_fails():
    _assert_applicability_invalid(
        _state(contingency=ContingencyState(
            capex_pct=6.0, opex_pct=6.0,
            capex_active=None, opex_active=True)),
        "ContingencyState.capex_active")


def test_ce_f_contingency_opex_active_none_fails():
    _assert_applicability_invalid(
        _state(contingency=ContingencyState(
            capex_pct=6.0, opex_pct=6.0,
            capex_active=True, opex_active=None)),
        "ContingencyState.opex_active")


# ---------------------------------------------------------------------------
# G. True/False remain valid; extraction preserves exact values
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("capex_active", [True, False])
@pytest.mark.parametrize("opex_active", [True, False])
def test_ce_g_bool_values_valid_and_preserved(capex_active, opex_active):
    state = CostProjectState(
        capacity_mw=64.0,
        project_ref="proj-ce-g",
        capex_fields=(CapexFieldState(
            field_name="grid_connection", parent_code="C.03",
            label="Grid", amount_keur=1200.0, is_active=capex_active),),
        opex_items=(OpexItemState(
            name="Land Lease", parent_code="B.07",
            y1_amount_keur=300.0, annual_inflation=0.02,
            is_active=opex_active),),
    )
    template = extract_client_cost_template(state, template_id="CE-G", version=1)
    cap = next(i for i in template.capex_items if i.parent_code == "C.03")
    opex = next(i for i in template.opex_items if i.parent_code == "B.07")
    assert cap.default_active is capex_active
    assert opex.default_active is opex_active
    assert cap.amount_keur == pytest.approx(1200.0, abs=TOL)  # never zeroed
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    rebuilt = plan_to_project_state(
        plan, capacity_mw=64.0, project_ref="proj-ce-g")
    assert rebuilt.capex_fields[0].is_active is capex_active
    assert rebuilt.opex_items[0].is_active is opex_active


def test_ce_g2_nonzero_int_applicability_fails():
    """0/1 are ints, not bools — fail closed even though bool(1) is truthy."""
    for bad in (0, 1):
        _assert_applicability_invalid(
            _state(capex_fields=(CapexFieldState(
                field_name="grid_connection", parent_code="C.03",
                label="Grid", amount_keur=100.0, is_active=bad),)),
            "CapexFieldState.is_active")


def test_ce_h_string_applicability_fails():
    for bad in ("false", "true"):
        _assert_applicability_invalid(
            _state(opex_items=(OpexItemState(
                name="Land Lease", parent_code="B.07",
                y1_amount_keur=300.0, annual_inflation=0.02,
                is_active=bad),)),
            "OpexItemState.is_active")


def test_ce_extraction_does_not_mask_malformed_subline():
    """Extraction calls validate first: a malformed sub-line applicability
    cannot slip through bool() coercion into the template."""
    state = _state(opex_sub_lines=(OpexSubLineState(
        parent_group_code="B.01", business_code="B.01.U001",
        label="User service", amount_keur=20.0, inflation_pct=2.0,
        is_active=None),))
    with pytest.raises(ValueError, match="COST_STATE_APPLICABILITY_INVALID"):
        extract_client_cost_template(state, template_id="CE-MASK", version=1)
