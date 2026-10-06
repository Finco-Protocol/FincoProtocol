"""Model V2 Cost Template Correction G regression matrix.

Decomposition AUTHORITY PRECEDENCE in initial materialization: when a
canonical parent is governed by B.NN.NN decomposition, child applicability
and child economics are authoritative — parent-level default_active is NOT
an independent economic authority and must never short-circuit the
decomposition authority (the previous check queried decomposition_present,
keyed by canonical OpexItem names, with item.parent_code).
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
    CapexFieldState,
    CostProjectState,
    OpexItemState,
    OpexSubLineState,
)
TOL = 1e-9


def _decomposed_state(parent_active: bool, child_states: dict[str, tuple[float, bool]]):
    """Decomposed OPEX parent whose OWN default_active is independently
    configurable; three B.NN.NN children with per-child states."""
    return CostProjectState(
        capacity_mw=64.0,
        project_ref="proj-cg",
        opex_items=(OpexItemState(
            name="Technical Management", parent_code="B.01",
            y1_amount_keur=250.0, annual_inflation=0.02,
            is_active=parent_active,
        ),),
        opex_sub_lines=tuple(
            OpexSubLineState(
                parent_group_code="B.01", business_code=code,
                label=code, amount_keur=amount, inflation_pct=2.0,
                source="reference_seed",
                canonical_parent_key="Technical Management",
                reference_seed=True,
                persisted_source="reference_seed",
                is_active=active,
            )
            for code, (amount, active) in child_states.items()
        ),
    )


def _materialize(state):
    template = extract_client_cost_template(state, template_id="CG", version=1)
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    parent = next(p for p in plan.opex_items if p.name == "Technical Management")
    children = [s for s in plan.opex_sub_lines
                if s.replay_metadata.get("replaces_parent")]
    return parent, children


# A/B. parent default_active must NOT override decomposition children
def test_cg_a_active_parent_all_children_off_parent_zero_inactive():
    """Parent default_active=True, all children OFF → parent 0, inactive
    (Correction F behavior remains green)."""
    state = _decomposed_state(
        parent_active=True,
        child_states={
            "B.01.01": (80.0, False),
            "B.01.02": (70.0, False),
            "B.01.03": (100.0, False),
        },
    )
    parent, children = _materialize(state)
    assert parent.y1_amount_keur == pytest.approx(0.0, abs=TOL)
    assert parent.is_active is False
    assert len(children) == 3 and all(not c.is_active for c in children)


def test_cg_b_inactive_parent_all_children_off_same_result():
    """Parent default_active=False, all children OFF → SAME result as A:
    parent 0 / inactive. Parent applicability is not an independent
    authority once decomposition exists."""
    state = _decomposed_state(
        parent_active=False,
        child_states={
            "B.01.01": (80.0, False),
            "B.01.02": (70.0, False),
            "B.01.03": (100.0, False),
        },
    )
    parent, children = _materialize(state)
    assert parent.y1_amount_keur == pytest.approx(0.0, abs=TOL)
    assert parent.is_active is False


def test_cg_c_inactive_parent_one_child_on():
    """Parent default_active=False, exactly one child ON at 80 → parent 80,
    active. The inactive PARENT flag must not suppress the active child."""
    state = _decomposed_state(
        parent_active=False,
        child_states={
            "B.01.01": (80.0, True),
            "B.01.02": (70.0, False),
            "B.01.03": (100.0, False),
        },
    )
    parent, children = _materialize(state)
    assert parent.y1_amount_keur == pytest.approx(80.0, abs=TOL)
    assert parent.is_active is True


def test_cg_d_inactive_parent_mixed_children():
    """Parent default_active=False, mixed children → parent = sum(active)
    = 180, active; the inactive child's assumptions remain present."""
    state = _decomposed_state(
        parent_active=False,
        child_states={
            "B.01.01": (80.0, True),
            "B.01.02": (70.0, False),
            "B.01.03": (100.0, True),
        },
    )
    parent, children = _materialize(state)
    assert parent.y1_amount_keur == pytest.approx(180.0, abs=TOL)
    assert parent.is_active is True
    by_code = {c.business_code: c for c in children}
    assert by_code["B.01.02"].is_active is False
    assert by_code["B.01.02"].amount_keur == pytest.approx(70.0, abs=TOL)


# E. non-decomposed parent preservation (unchanged behavior)
def test_cg_e_non_decomposed_parent_off_preserved():
    """Non-decomposed parent default_active=False → stored amount/inflation/
    steps retained, parent inactive (existing behavior unchanged)."""
    state = CostProjectState(
        capacity_mw=64.0,
        project_ref="proj-cg-nd",
        opex_items=(OpexItemState(
            name="Land Lease", parent_code="B.07",
            y1_amount_keur=300.0, annual_inflation=-0.01,
            step_changes=((10, 400.0),),
            is_active=False,
        ),),
    )
    template = extract_client_cost_template(state, template_id="CG-E", version=1)
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    parent = plan.opex_items[0]
    assert parent.is_active is False
    assert parent.y1_amount_keur == pytest.approx(300.0, abs=TOL)  # retained
    assert parent.annual_inflation == pytest.approx(-0.01, abs=1e-15)
    assert parent.step_changes == ((10, 400.0),)                   # retained


# F. ACTIVE ZERO decomposition child
def test_cg_f_active_zero_child_parent_active_zero():
    """An ACTIVE decomposition child with amount 0 keeps the parent ACTIVE
    at amount 0 — applicability is any(active child), never inferred from
    amount != 0. ZERO != INACTIVE."""
    state = _decomposed_state(
        parent_active=True,
        child_states={
            "B.01.01": (0.0, True),
            "B.01.02": (70.0, False),
            "B.01.03": (100.0, False),
        },
    )
    parent, children = _materialize(state)
    assert parent.y1_amount_keur == pytest.approx(0.0, abs=TOL)
    assert parent.is_active is True  # an active child exists
    active_child = next(c for c in children if c.business_code == "B.01.01")
    assert active_child.is_active is True
    assert active_child.amount_keur == 0.0


def test_cg_precedence_does_not_depends_on_parent_flag():
    """The decomposition result is IDENTICAL regardless of the parent item's
    own default_active — proof that parent-level applicability no longer
    short-circuits the decomposition authority."""
    from app.services.cost_template import MaterializationPlan

    results = []
    for parent_active in (True, False):
        state = _decomposed_state(
            parent_active=parent_active,
            child_states={
                "B.01.01": (80.0, True),
                "B.01.02": (70.0, False),
                "B.01.03": (100.0, False),
            },
        )
        template = extract_client_cost_template(state, template_id="CG-X", version=1)
        plan = build_materialization_plan(resolve_cost_template(
            template, MaterializationContext(capacity_mw=64.0)))
        parent = next(p for p in plan.opex_items if p.name == "Technical Management")
        results.append((parent.y1_amount_keur, parent.is_active))
    # identical economics and applicability either way: 80 (active child), active
    assert results[0] == results[1] == (pytest.approx(80.0, abs=TOL), True)


def test_cg_plan_to_state_preserves_precedence_result():
    """plan_to_project_state preserves the decomposition-derived parent
    applicability (inactive parent flag on the source item ignored)."""
    state = _decomposed_state(
        parent_active=False,
        child_states={
            "B.01.01": (80.0, True),
            "B.01.02": (70.0, False),
        },
    )
    template = extract_client_cost_template(state, template_id="CG-S", version=1)
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    rebuilt = plan_to_project_state(
        plan, capacity_mw=64.0, project_ref="proj-cg")
    parent = next(o for o in rebuilt.opex_items if o.name == "Technical Management")
    assert parent.y1_amount_keur == pytest.approx(80.0, abs=TOL)
    assert parent.is_active is True
