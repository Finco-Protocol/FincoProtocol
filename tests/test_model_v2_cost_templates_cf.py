"""Model V2 Cost Template Correction F regression matrix.

Initial materialization (build_materialization_plan, NOT rescale) derives
decomposed OPEX canonical-parent applicability from the ACTIVE child set:

  parent amount = sum(active children)
  parent active = any(active child)
"""
from __future__ import annotations

import pytest

from app.services.cost_template import (
    MaterializationContext,
    build_materialization_plan,
    extract_client_cost_template,
    plan_to_project_state,
    resolve_cost_template,
)
from app.services.cost_template import (
    CapexSubLineState,
    CostProjectState,
    OpexItemState,
    OpexSubLineState,
)
TOL = 1e-9


def _decomposed_opex_state(child_states: dict[str, bool]) -> CostProjectState:
    """Client state with a canonical Technical Management parent and three
    B.NN.NN decomposition children whose active states are given."""
    return CostProjectState(
        capacity_mw=64.0,
        project_ref="proj-cf",
        opex_items=(OpexItemState(
            name="Technical Management", parent_code="B.01",
            y1_amount_keur=250.0, annual_inflation=0.02,
        ),),
        opex_sub_lines=tuple(
            OpexSubLineState(
                parent_group_code="B.01", business_code=code,
                label=label, amount_keur=amount, inflation_pct=2.0,
                source="reference_seed",
                canonical_parent_key="Technical Management",
                reference_seed=True,
                persisted_source="reference_seed",
                is_active=active,
            )
            for code, (label, amount, active) in child_states.items()
        ),
    )


def _materialize_parent(state: CostProjectState):
    template = extract_client_cost_template(state, template_id="CF", version=1)
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    parent = next(p for p in plan.opex_items if p.name == "Technical Management")
    children = [s for s in plan.opex_sub_lines
                if s.replay_metadata.get("replaces_parent")]
    return parent, children, plan


def test_cf1_all_children_off_parent_zero_and_inactive():
    """CF case C: all replacement children OFF → parent amount 0 AND
    parent is_active False — at INITIAL materialization, no rescale."""
    state = _decomposed_opex_state({
        "B.01.01": ("Asset Management", 80.0, False),
        "B.01.02": ("Operations Management", 70.0, False),
        "B.01.03": ("Performance Monitoring", 100.0, False),
    })
    parent, children, _plan = _materialize_parent(state)
    assert parent.y1_amount_keur == pytest.approx(0.0, abs=TOL)
    assert parent.is_active is False
    # latent child assumptions retained
    assert len(children) == 3
    assert all(s.amount_keur > 0 for s in children)
    assert all(not s.is_active for s in children)


def test_cf2_one_child_on_parent_active_with_that_amount():
    """CF case E variant: exactly one child ON → parent amount = that
    child's configured amount, parent active."""
    state = _decomposed_opex_state({
        "B.01.01": ("Asset Management", 80.0, True),
        "B.01.02": ("Operations Management", 70.0, False),
        "B.01.03": ("Performance Monitoring", 100.0, False),
    })
    parent, children, _plan = _materialize_parent(state)
    assert parent.is_active is True
    assert parent.y1_amount_keur == pytest.approx(80.0, abs=TOL)


def test_cf3_mixed_children_inactive_retained_active_contribute():
    """CF case B: mixed active/inactive — inactive children remain present
    with their assumptions; only active children enter the parent amount."""
    state = _decomposed_opex_state({
        "B.01.01": ("Asset Management", 80.0, True),
        "B.01.02": ("Operations Management", 70.0, False),
        "B.01.03": ("Performance Monitoring", 100.0, True),
    })
    parent, children, _plan = _materialize_parent(state)
    assert parent.is_active is True
    assert parent.y1_amount_keur == pytest.approx(180.0, abs=TOL)  # 80 + 100
    by_code = {s.business_code: s for s in children}
    assert by_code["B.01.02"].is_active is False
    assert by_code["B.01.02"].amount_keur == pytest.approx(70.0, abs=TOL)  # retained
    assert by_code["B.01.01"].is_active is True
    assert by_code["B.01.03"].is_active is True


def test_cf_all_children_active_parent_full_sum():
    """CF case A: all children active → parent = full sum, parent active."""
    state = _decomposed_opex_state({
        "B.01.01": ("Asset Management", 80.0, True),
        "B.01.02": ("Operations Management", 70.0, True),
        "B.01.03": ("Performance Monitoring", 100.0, True),
    })
    parent, children, _plan = _materialize_parent(state)
    assert parent.is_active is True
    assert parent.y1_amount_keur == pytest.approx(250.0, abs=TOL)


def test_cf_plan_to_state_preserves_parent_applicability():
    """plan_to_project_state preserves the corrected parent applicability in
    both directions (all-OFF and mixed)."""
    off_state = _decomposed_opex_state({
        "B.01.01": ("Asset Management", 80.0, False),
        "B.01.02": ("Operations Management", 70.0, False),
    })
    template = extract_client_cost_template(off_state, template_id="CF-S", version=1)
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    rebuilt = plan_to_project_state(
        plan, capacity_mw=64.0, project_ref="proj-cf")
    parent = next(o for o in rebuilt.opex_items if o.name == "Technical Management")
    assert parent.y1_amount_keur == pytest.approx(0.0, abs=TOL)
    assert parent.is_active is False

    mixed_state = _decomposed_opex_state({
        "B.01.01": ("Asset Management", 80.0, True),
        "B.01.02": ("Operations Management", 70.0, False),
    })
    template2 = extract_client_cost_template(mixed_state, template_id="CF-M", version=1)
    plan2 = build_materialization_plan(resolve_cost_template(
        template2, MaterializationContext(capacity_mw=64.0)))
    rebuilt2 = plan_to_project_state(
        plan2, capacity_mw=64.0, project_ref="proj-cf")
    parent2 = next(o for o in rebuilt2.opex_items if o.name == "Technical Management")
    assert parent2.y1_amount_keur == pytest.approx(80.0, abs=TOL)
    assert parent2.is_active is True


def test_cf_capex_parity_unchanged():
    """CAPEX decomposed applicability (already correct) still holds at
    initial materialization: all children OFF → field 0 + inactive."""
    from app.services.cost_template import CapexFieldState

    state = CostProjectState(
        capacity_mw=64.0,
        project_ref="proj-cf-capex",
        capex_fields=(CapexFieldState(
            field_name="production_units", parent_code="C.01",
            label="Production Units", amount_keur=1000.0),),
        capex_sub_lines=(
            CapexSubLineState(parent_category_code="C.01",
                              business_code="C.01.U001", label="A",
                              amount_keur=600.0, is_active=False),
            CapexSubLineState(parent_category_code="C.01",
                              business_code="C.01.U002", label="B",
                              amount_keur=400.0, is_active=False),
        ),
    )
    template = extract_client_cost_template(state, template_id="CF-CAP", version=1)
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    field = next(f for f in plan.capex_fields if f.parent_code == "C.01")
    assert field.amount_keur == pytest.approx(0.0, abs=TOL)
    assert field.is_active is False
