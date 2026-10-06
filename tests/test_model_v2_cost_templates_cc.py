"""Model V2 Cost Template Correction C regression matrix.

Contingency applicability roundtrip, client OPEX persisted-source
preservation, all-inactive decomposition semantics, parent-level
applicability, derived-runtime applicability lock, and true scalar-metadata
immutability.
"""
from __future__ import annotations

import json

import pytest

from app.services.cost_template import (
    CapexFieldState,
    CapexSubLineState,
    ContingencyState,
    CostDriver,
    CostProjectState,
    CapexTemplateItem,
    CostTemplate,
    ItemClassification,
    TemplateKind,
    MaterializationContext,
    MaterializationPlan,
    OpexItemState,
    OpexSubLineState,
    TemplateKind,
    build_generic_cost_template,
    build_materialization_plan,
    cost_template_from_json,
    cost_template_to_json,
    extract_client_cost_template,
    plan_to_project_state,
    resolve_cost_template,
    rescale_materialization_plan,
)


def _capex_meta_state(capex_active: bool) -> CostProjectState:
    return CostProjectState(
        capacity_mw=64.0,
        project_ref="proj-cc",
        contingency=ContingencyState(
            capex_pct=6.0, capex_active=capex_active, lineage={"basis": "x"}),
        capex_fields=(CapexFieldState(
            field_name="contingencies", parent_code="C.13",
            label="Contingency", amount_keur=0.0),),
    )


def _opex_cont_state(pct, active: bool) -> CostProjectState:
    return CostProjectState(
        capacity_mw=64.0,
        project_ref="proj-cc-opex",
        contingency=ContingencyState(opex_pct=pct, opex_active=active),
        opex_items=(OpexItemState(
            name="OPEX Contingency", parent_code="B.13",
            y1_amount_keur=0.0,
            percentage_of_opex=(pct / 100.0) if pct is not None else 0.0,
        ),),
    )


# ---------------------------------------------------------------------------
# CONTINGENCY (defects 1 + 2)
# ---------------------------------------------------------------------------

def test_cc1_capex_6pct_inactive_roundtrip():
    """CAPEX 6.0% inactive → template → JSON → plan → state = 6.0% inactive."""
    state = _capex_meta_state(capex_active=False)
    template = extract_client_cost_template(state, template_id="CC1", version=1)
    c13 = next(i for i in template.capex_items if i.parent_code == "C.13")
    assert c13.driver_value == pytest.approx(6.0, abs=1e-12)
    payload = cost_template_to_json(template)
    plan = build_materialization_plan(resolve_cost_template(
        cost_template_from_json(payload), MaterializationContext(capacity_mw=64.0)))
    assert plan.contingency.capex_pct == pytest.approx(6.0, abs=1e-12)
    assert plan.contingency.capex_active is False
    rebuilt = plan_to_project_state(
        plan, capacity_mw=64.0, project_ref="proj-cc")
    assert rebuilt.contingency.capex_pct == pytest.approx(6.0, abs=1e-12)
    assert rebuilt.contingency.capex_active is False


def test_cc2_opex_6pct_inactive_preserves_pct():
    """Defect 2: 6.0% INACTIVE keeps the configured 6.0% authority (never
    forgotten, never re-derived from the runtime item fraction)."""
    state = _opex_cont_state(6.0, active=False)
    template = extract_client_cost_template(state, template_id="CC2", version=1)
    b13 = next(i for i in template.opex_items if i.parent_code == "B.13")
    assert b13.driver is CostDriver.PERCENT_OF_OPEX
    assert b13.driver_value == pytest.approx(6.0, abs=1e-12)
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    assert plan.opex_items[0].percentage_of_opex == pytest.approx(0.06, abs=1e-12)
    assert plan.contingency.opex_pct == pytest.approx(6.0, abs=1e-12)
    assert plan.contingency.opex_active is False


def test_cc3_opex_0pct_inactive_roundtrip():
    """0.0% INACTIVE retains the explicit zero authority."""
    state = _opex_cont_state(0.0, active=False)
    template = extract_client_cost_template(state, template_id="CC3", version=1)
    b13 = next(i for i in template.opex_items if i.parent_code == "B.13")
    assert b13.driver is CostDriver.PERCENT_OF_OPEX
    assert b13.driver_value == pytest.approx(0.0, abs=1e-15)
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    assert plan.contingency.opex_pct == pytest.approx(0.0, abs=1e-15)
    assert plan.contingency.opex_active is False


def test_cc4_zero_active_distinct_from_zero_inactive():
    a = extract_client_cost_template(
        _opex_cont_state(0.0, active=True), template_id="CC4A", version=1)
    i = next(x for x in a.opex_items if x.parent_code == "B.13")
    plan_a = build_materialization_plan(resolve_cost_template(
        a, MaterializationContext(capacity_mw=64.0)))
    inact = extract_client_cost_template(
        _opex_cont_state(0.0, active=False), template_id="CC4B", version=1)
    plan_b = build_materialization_plan(resolve_cost_template(
        inact, MaterializationContext(capacity_mw=64.0)))
    assert plan_a.opex_items[0].percentage_of_opex == pytest.approx(
        plan_b.opex_items[0].percentage_of_opex, abs=1e-15)  # same economics
    assert plan_a.contingency.opex_active is True
    assert plan_b.contingency.opex_active is False        # distinct states
    assert cost_template_to_json(a) != cost_template_to_json(inact)


def test_cc5_none_stays_missing():
    """opex_pct=None + no positive core pct → no PERCENT_OF_OPEX authority."""
    state = CostProjectState(
        capacity_mw=64.0,
        project_ref="proj-cc-none",
        contingency=ContingencyState(opex_pct=None, opex_active=True),
        opex_items=(OpexItemState(
            name="Technical Management", parent_code="B.01",
            y1_amount_keur=250.0, annual_inflation=0.02,
        ),),
    )
    template = extract_client_cost_template(state, template_id="CC5", version=1)
    assert not any(i.driver is CostDriver.PERCENT_OF_OPEX
                   for i in template.opex_items)


def test_cc6_plan_to_state_preserves_flags():
    """plan_to_project_state carries capex_active/opex_active exactly."""
    state = _capex_meta_state(capex_active=False)
    template = extract_client_cost_template(state, template_id="CC6", version=1)
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    rebuilt = plan_to_project_state(
        plan, capacity_mw=64.0, project_ref="proj-cc")
    assert rebuilt.contingency.capex_active is False
    state_active = _capex_meta_state(capex_active=True)
    t2 = extract_client_cost_template(state_active, template_id="CC6b", version=1)
    plan2 = build_materialization_plan(resolve_cost_template(
        t2, MaterializationContext(capacity_mw=64.0)))
    rebuilt2 = plan_to_project_state(
        plan2, capacity_mw=64.0, project_ref="proj-cc")
    assert rebuilt2.contingency.capex_active is True


# ---------------------------------------------------------------------------
# OPEX REPLACEMENT SOURCE (defect 3)
# ---------------------------------------------------------------------------

def _opex_seed_state() -> CostProjectState:
    return CostProjectState(
        capacity_mw=64.0,
        project_ref="proj-src",
        opex_sub_lines=(
            OpexSubLineState(
                parent_group_code="B.02", business_code="B.02.01",
                label="Preventive Maintenance", amount_keur=140.0,
                inflation_pct=2.0, source="reference_seed",
                canonical_parent_key="Maintenance", reference_seed=True,
                persisted_source="reference_seed",
            ),
            OpexSubLineState(
                parent_group_code="B.02", business_code="B.02.02",
                label="Corrective Maintenance (edited)", amount_keur=90.0,
                inflation_pct=2.0, source="user_override",
                canonical_parent_key="Maintenance", reference_seed=True,
                persisted_source="user_override",
            ),
            OpexSubLineState(
                parent_group_code="B.01", business_code="B.01.U005",
                label="Extra service", amount_keur=60.0, inflation_pct=2.0,
                source="user",
            ),
        ),
    )


def test_cc7_client_reference_seed_materializes_reference_seed():
    state = _opex_seed_state()
    template = extract_client_cost_template(state, template_id="CC7", version=1)
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    seeded = next(s for s in plan.opex_sub_lines if s.business_code == "B.02.01")
    assert seeded.source == "reference_seed"
    assert seeded.replay_metadata["reference_seed"] is True
    assert seeded.replay_metadata["canonical_key"] == "Maintenance"
    # runtime replacement predicate (existing OPEX fold authority):
    assert seeded.source in {"reference_seed", "user_override"}
    assert seeded.replay_metadata.get("reference_seed") is True
    assert seeded.replay_metadata.get("canonical_key")


def test_cc8_client_user_override_materializes_user_override():
    state = _opex_seed_state()
    template = extract_client_cost_template(state, template_id="CC8", version=1)
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    override = next(s for s in plan.opex_sub_lines if s.business_code == "B.02.02")
    assert override.source == "user_override"
    assert override.replay_metadata["reference_seed"] is True
    assert override.replay_metadata["canonical_key"] == "Maintenance"
    assert override.source in {"reference_seed", "user_override"}


def test_cc10_user_ucode_remains_user_additive():
    state = _opex_seed_state()
    template = extract_client_cost_template(state, template_id="CC10", version=1)
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    urow = next(s for s in plan.opex_sub_lines if s.business_code == "B.01.U005")
    assert urow.source == "user"
    assert urow.replay_metadata.get("replaces_parent") in (None, False)
    assert not urow.replay_metadata.get("reference_seed")


# ---------------------------------------------------------------------------
# ALL-INACTIVE DECOMPOSITION (defect 4)
# ---------------------------------------------------------------------------

def _capex_two_children_state(all_inactive: bool):
    from app.services.cost_template import CapexSubLineState as S

    return CostProjectState(
        capacity_mw=64.0,
        project_ref="proj-all-off",
        capex_fields=(CapexFieldState(
            field_name="production_units", parent_code="C.01",
            label="Production Units", amount_keur=1000.0),),
        capex_sub_lines=(
            S(parent_category_code="C.01", business_code="C.01.U001",
              label="A", amount_keur=600.0, is_active=not all_inactive),
            S(parent_category_code="C.01", business_code="C.01.U002",
              label="B", amount_keur=400.0, is_active=not all_inactive),
        ),
    )


def _extract_and_materialize(state, template_id):
    template = extract_client_cost_template(state, template_id=template_id, version=1)
    return build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0))), template


def test_cc11_all_inactive_capex_children_parent_zero():
    """All decomposition children OFF → canonical field subtotal 0; both
    child assumptions remain stored with their economics."""
    plan, template = _extract_and_materialize(
        _capex_two_children_state(all_inactive=True), "CC11")
    field = next(f for f in plan.capex_fields if f.parent_code == "C.01")
    assert field.amount_keur == pytest.approx(0.0, abs=1e-12)
    assert field.is_active is False
    # children retained with economics
    assert len(plan.capex_sub_lines) == 2
    assert all(not s.is_active for s in plan.capex_sub_lines)
    assert sum(s.amount_keur for s in plan.capex_sub_lines) == pytest.approx(
        1000.0, abs=1e-9)


def test_cc13_reactivate_one_child_restores_subtotal():
    """Reactivating one child → parent = that child's configured amount."""
    from app.services.cost_template import CapexSubLinePlan

    plan, template = _extract_and_materialize(
        _capex_two_children_state(all_inactive=True), "CC13")
    # reactivate C.01.U001 (its stored economics unchanged)
    subs = []
    for s in plan.capex_sub_lines:
        if s.business_code == "C.01.U001":
            subs.append(CapexSubLinePlan(
                parent_category_code=s.parent_category_code,
                business_code=s.business_code,
                label=s.label,
                amount_keur=s.amount_keur,
                schedule_json=s.schedule_json,
                source=s.source,
                replay_metadata=s.replay_metadata,
                scalar_metadata=dict(s.scalar_metadata),
                is_active=True,
            ))
        else:
            subs.append(s)
    reactivated = MaterializationPlan(
        template_id=plan.template_id, template_version=plan.template_version,
        capex_fields=plan.capex_fields,
        capex_sub_lines=tuple(subs),
        opex_items=plan.opex_items,
        opex_sub_lines=plan.opex_sub_lines,
        contingency=plan.contingency,
    )
    # Correction C (defect 4): reconciliation runs over the final child set
    # (the rescale pass is the canonical reconciler; same capacity = no
    # scaling, pure reconciliation).
    reactivated = rescale_materialization_plan(
        reactivated, template=template, new_capacity_mw=64.0)
    field = next(f for f in reactivated.capex_fields if f.parent_code == "C.01")
    assert field.amount_keur == pytest.approx(600.0, abs=1e-9)


def test_cc12_all_inactive_opex_children_parent_zero():
    """All seeded OPEX decomposition children OFF → canonical OpexItem 0."""
    from app.services.cost_template import OpexTemplateItem
    from app.services.cost_template import OpexSubLinePlan

    t = build_generic_cost_template("generic_solar_reference")
    resolved = resolve_cost_template(t, MaterializationContext(capacity_mw=64.0))
    plan = build_materialization_plan(resolved)
    # turn OFF every B.01 decomposition child
    subs = []
    for s in plan.opex_sub_lines:
        if s.parent_group_code == "B.01":
            subs.append(OpexSubLinePlan(
                parent_group_code=s.parent_group_code,
                business_code=s.business_code,
                label=s.label,
                amount_keur=s.amount_keur,
                inflation_pct=s.inflation_pct,
                source=s.source,
                replay_metadata=s.replay_metadata,
                is_active=False,
            ))
        else:
            subs.append(s)
    all_off = MaterializationPlan(
        template_id=plan.template_id, template_version=plan.template_version,
        capex_fields=plan.capex_fields,
        capex_sub_lines=plan.capex_sub_lines,
        opex_items=plan.opex_items,
        opex_sub_lines=tuple(subs),
        contingency=plan.contingency,
    )
    # rescale reconciliation recomputes parents from the FINAL ACTIVE set
    rescaled = rescale_materialization_plan(
        all_off, template=t, new_capacity_mw=64.0)
    parent = next(p for p in rescaled.opex_items if p.name == "Technical Management")
    assert parent.y1_amount_keur == pytest.approx(0.0, abs=1e-12)
    # children retained
    assert all(not s.is_active for s in rescaled.opex_sub_lines
               if s.parent_group_code == "B.01")


# ---------------------------------------------------------------------------
# PARENT-LEVEL APPLICABILITY (defect 5)
# ---------------------------------------------------------------------------

def test_cc14_capex_parent_off_excludes_economics_retains_config():
    from app.services.cost_template import CapexTemplateItem

    template = CostTemplate.create(
        template_id="CC14", version=1, name="T", technology="solar",
        kind=TemplateKind.GENERIC,
        capex_items=(
            CapexTemplateItem(
                item_id="capex.grid_connection", parent_code="C.03",
                label="Grid Connection", driver=CostDriver.ABSOLUTE_KEUR,
                amount_keur=1200.0, default_active=False),
            CapexTemplateItem(
                item_id="capex.epc_contract", parent_code="C.02",
                label="EPC", driver=CostDriver.ABSOLUTE_KEUR,
                amount_keur=800.0),
        ),
    )
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    off = next(f for f in plan.capex_fields if f.parent_code == "C.03")
    on = next(f for f in plan.capex_fields if f.parent_code == "C.02")
    assert off.is_active is False
    assert off.amount_keur == pytest.approx(1200.0, abs=1e-9)  # config retained
    assert on.is_active is True
    assert on.amount_keur == pytest.approx(800.0, abs=1e-9)


def test_cc15_opex_parent_off_retains_config():
    from app.services.cost_template import OpexTemplateItem

    template = CostTemplate.create(
        template_id="CC15", version=1, name="T", technology="solar",
        kind=TemplateKind.GENERIC,
        opex_items=(
            OpexTemplateItem(
                item_id="opex.land", parent_code="B.07", label="Land Lease",
                driver=CostDriver.ABSOLUTE_KEUR, y1_amount_keur=300.0,
                annual_inflation=-0.01, default_active=False),
            OpexTemplateItem(
                item_id="opex.am", parent_code="B.01", label="Asset Mgmt",
                driver=CostDriver.ABSOLUTE_KEUR, y1_amount_keur=150.0,
                annual_inflation=0.02),
        ),
    )
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    off = next(p for p in plan.opex_items if p.name == "Land Lease")
    on = next(p for p in plan.opex_items if p.name == "Asset Mgmt")
    assert off.is_active is False
    assert off.y1_amount_keur == pytest.approx(300.0, abs=1e-9)  # retained
    assert off.annual_inflation == pytest.approx(-0.01, abs=1e-15)
    assert on.is_active is True


def test_cc16_reactivation_restores_exact_economics():
    from app.services.cost_template import CapexFieldPlan

    template = CostTemplate.create(
        template_id="CC16", version=1, name="T", technology="solar",
        kind=TemplateKind.GENERIC,
        capex_items=(CapexTemplateItem(
            item_id="capex.grid", parent_code="C.03", label="Grid",
            driver=CostDriver.ABSOLUTE_KEUR, amount_keur=1200.0,
            default_active=False),),
    )
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    # reactivate: rebuild the plan field with is_active=True (project action)
    reactivated_fields = [
        CapexFieldPlan(
            field_name=f.field_name, parent_code=f.parent_code,
            label=f.label, amount_keur=f.amount_keur,
            y0_share=f.y0_share, spending_profile=f.spending_profile,
            asset_class=f.asset_class,
            useful_life_override=f.useful_life_override,
            is_depreciable=f.is_depreciable, is_active=True,
        ) for f in plan.capex_fields
    ]
    reactivated = MaterializationPlan(
        template_id=plan.template_id, template_version=plan.template_version,
        capex_fields=tuple(reactivated_fields),
        capex_sub_lines=plan.capex_sub_lines,
        opex_items=plan.opex_items,
        opex_sub_lines=plan.opex_sub_lines,
        contingency=plan.contingency,
    )
    rebuilt = plan_to_project_state(
        reactivated, capacity_mw=64.0, project_ref="r")
    assert rebuilt.capex_fields[0].amount_keur == pytest.approx(1200.0, abs=1e-9)
    assert rebuilt.capex_fields[0].is_active is True


# ---------------------------------------------------------------------------
# DERIVED RUNTIME (defect 6)
# ---------------------------------------------------------------------------

def test_cc17_derived_capex_cannot_be_disabled():
    for parent in ("C.17", "C.18"):
        with pytest.raises(ValueError,
                           match="COST_TEMPLATE_DERIVED_APPLICABILITY_ILLEGAL"):
            CostTemplate.create(
                template_id="T", version=1, name="T", technology="solar",
                kind=TemplateKind.GENERIC,
                capex_items=(CapexTemplateItem(
                    item_id=f"d{parent}", parent_code=parent, label="Derived",
                    driver=CostDriver.DERIVED_RUNTIME,
                    classification=ItemClassification.DERIVED_RUNTIME,
                    default_active=False),),
            )
        # active derived rows remain legal
        CostTemplate.create(
            template_id="T", version=1, name="T", technology="solar",
            kind=TemplateKind.GENERIC,
            capex_items=(CapexTemplateItem(
                item_id=f"d{parent}", parent_code=parent, label="Derived",
                driver=CostDriver.DERIVED_RUNTIME,
                classification=ItemClassification.DERIVED_RUNTIME,
                default_active=True),),
        )


def test_cc18_derived_opex_cannot_be_disabled():
    from app.services.cost_template import OpexTemplateItem

    with pytest.raises(ValueError, match="COST_TEMPLATE_DERIVED_APPLICABILITY_ILLEGAL"):
        CostTemplate.create(
            template_id="T", version=1, name="T", technology="solar",
            kind=TemplateKind.GENERIC,
            opex_items=(OpexTemplateItem(
                item_id="opex.derived", parent_code="B.08",
                label="Derived power expenses",
                driver=CostDriver.DERIVED_RUNTIME,
                classification=ItemClassification.DERIVED_RUNTIME,
                default_active=False),),
        )


# ---------------------------------------------------------------------------
# IMMUTABILITY (defect 7)
# ---------------------------------------------------------------------------

def _meta_template():
    src_meta = {"vat_rate_pct": 25.0}
    from app.services.cost_template import CapexTemplateItem

    item = CapexTemplateItem(
        item_id="capex.meta", parent_code="C.01", label="X",
        driver=CostDriver.ABSOLUTE_KEUR, amount_keur=1.0,
        scalar_metadata=src_meta,
    )
    t = CostTemplate.create(template_id="T", version=1, name="T",
                            technology="solar", kind=TemplateKind.GENERIC,
                            capex_items=(item,))
    return src_meta, item, t


def test_cc19_external_source_mutation_isolated():
    src_meta, item, t = _meta_template()
    src_meta["vat_rate_pct"] = 20.0  # hostile external mutation
    assert item.scalar_metadata["vat_rate_pct"] == 25.0


def test_cc20_direct_mutation_impossible():
    _src, item, _t = _meta_template()
    with pytest.raises(TypeError):
        item.scalar_metadata["vat_rate_pct"] = 20.0
    with pytest.raises(TypeError):
        item.scalar_metadata["new_key"] = 1.0


def test_cc21_canonical_json_stable_after_attempts():
    src_meta, _item, t = _meta_template()
    before = cost_template_to_json(t)
    src_meta["vat_rate_pct"] = 20.0
    try:
        t.capex_items[0].scalar_metadata["vat_rate_pct"] = 20.0
    except TypeError:
        pass
    assert cost_template_to_json(t) == before


def test_cc22_json_roundtrip_preserves_metadata():
    _src, _item, t = _meta_template()
    rebuilt = cost_template_from_json(cost_template_to_json(t))
    assert rebuilt.capex_items[0].scalar_metadata["vat_rate_pct"] == 25.0
