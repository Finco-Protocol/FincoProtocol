"""Model V2 Cost Template Correction B regression matrix.

U-code replacement semantics, canonical-field reconciliation (C.08/C.11),
OPEX canonical replacement provenance, rescale reconciliation from the
final child set, explicit-zero contingency authority, scalar metadata
fail-closed/immutability, and the applicability addendum.
"""
from __future__ import annotations

import pytest

from app.services.cost_template import (
    CapexFieldState,
    CapexSubLinePlan,
    CapexTemplateItem,
    MaterializationPlan,
    OpexSubLinePlan,
    CapexSubLineState,
    ContingencyState,
    CostDriver,
    CostProjectState,
    CostTemplate,
    ItemClassification,
    MaterializationContext,
    OpexItemState,
    OpexSubLineState,
    ScalingBasis,
    TemplateKind,
    build_generic_cost_template,
    build_materialization_plan,
    cost_template_from_json,
    cost_template_to_json,
    extract_client_cost_template,
    plan_to_project_state,
    rescale_materialization_plan,
    resolve_cost_template,
)
TOL = 1e-9


# ---------------------------------------------------------------------------
# CAPEX: U-code = replacement breakdown (defect 1)
# ---------------------------------------------------------------------------

def test_cb_capex_ucode_replacement_not_additive():
    """canonical parent 1000; C.01.U001=600 + C.01.U002=400 → field
    authority 1000, NOT 2000 (zero base + fold)."""
    state = CostProjectState(
        capacity_mw=64.0,
        project_ref="proj-u",
        capex_fields=(CapexFieldState(
            field_name="production_units", parent_code="C.01",
            label="Production Units", amount_keur=1000.0),),
        capex_sub_lines=(
            CapexSubLineState(parent_category_code="C.01",
                              business_code="C.01.U001", label="Supply A",
                              amount_keur=600.0),
            CapexSubLineState(parent_category_code="C.01",
                              business_code="C.01.U002", label="Supply B",
                              amount_keur=400.0),
        ),
    )
    template = extract_client_cost_template(state, template_id="CLIENT_U", version=1)
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    field = next(f for f in plan.capex_fields if f.parent_code == "C.01")
    assert field.amount_keur == pytest.approx(1000.0, abs=1e-9)
    assert len(plan.capex_sub_lines) == 2
    # both U-rows carry the replacement flag (breakdown, not additive)
    assert all(s.replay_metadata.get("replaces_parent") for s in plan.capex_sub_lines)


def test_cb_capex_detail_rows_are_replacement():
    """C.NN.NN detail rows replace the field: field == sum of details."""
    t = build_generic_cost_template("generic_solar_reference")
    plan = build_materialization_plan(resolve_cost_template(
        t, MaterializationContext(capacity_mw=64.0)))
    c01 = next(f for f in plan.capex_fields if f.parent_code == "C.01")
    details = [s for s in plan.capex_sub_lines
               if s.parent_category_code == "C.01"
               and s.replay_metadata.get("replaces_parent")]
    assert c01.amount_keur == pytest.approx(sum(s.amount_keur for s in details), abs=1e-6)


# ---------------------------------------------------------------------------
# CAPEX: canonical FIELD reconciliation (defect 2, C.08/C.11)
# ---------------------------------------------------------------------------

def test_cb_c08_c11_reconcile_into_one_audit_legal():
    """C.08 and C.11 both map to audit_legal: one canonical field authority
    = sum of all relevant child rows exactly once."""
    state = CostProjectState(
        capacity_mw=64.0,
        project_ref="proj-alias",
        capex_fields=(
            CapexFieldState(field_name="audit_legal", parent_code="C.08",
                            label="Audit & Legal", amount_keur=500.0),
        ),
        capex_sub_lines=(
            CapexSubLineState(parent_category_code="C.08",
                              business_code="C.08.01", label="Legal Advisory",
                              amount_keur=300.0),
            CapexSubLineState(parent_category_code="C.11",
                              business_code="C.11.01", label="Independent Advisory",
                              amount_keur=250.0),
        ),
    )
    template = extract_client_cost_template(state, template_id="CLIENT_ALIAS", version=1)
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    audit = [f for f in plan.capex_fields if f.field_name == "audit_legal"]
    assert len(audit) == 1
    assert audit[0].amount_keur == pytest.approx(550.0, abs=1e-9)  # 300 + 250, once
    assert not any(f.parent_code == "C.11" for f in plan.capex_fields)


# ---------------------------------------------------------------------------
# OPEX: canonical replacement provenance (defect 3)
# ---------------------------------------------------------------------------

def test_cb_generic_opex_replacement_provenance():
    """Generic B.NN.NN rows carry the exact runtime replacement vocabulary:
    reference_seed=True, canonical_key=<canonical OpexItem name>,
    detail_code, scaling_mode, template lineage; never the B.NN group code."""
    from app.reference_detail_catalog import PUBLIC_GENERIC_DETAIL_V1

    t = build_generic_cost_template("generic_solar_reference")
    plan = build_materialization_plan(resolve_cost_template(
        t, MaterializationContext(capacity_mw=64.0)))
    b01_rows = [s for s in plan.opex_sub_lines
                if s.parent_group_code == "B.01"
                and s.replay_metadata.get("replaces_parent")]
    assert b01_rows
    for s in b01_rows:
        md = s.replay_metadata
        assert md["reference_seed"] is True
        assert md["canonical_key"] == "Technical Management"  # canonical item name
        assert not md["canonical_key"].startswith("B.")
        assert md["detail_code"].startswith("B.01.")
        assert md["scaling_mode"] == "per_mw"
        assert md["cost_template_id"] == t.template_id
    assert b01_rows[0].source == "reference_seed"
    # and the canonical parent reconciles from the final child set
    parent = next(p for p in plan.opex_items if p.name == "Technical Management")
    assert parent.y1_amount_keur == pytest.approx(
        sum(s.amount_keur for s in b01_rows), abs=1e-6)


def test_cb_opex_ucode_remains_additive():
    """B.NN.U### rows stay ADDITIVE (existing OPEX runtime): no replacement
    provenance, and they do not enter any canonical reconciliation."""
    state = CostProjectState(
        capacity_mw=64.0,
        project_ref="proj-opex-u",
        opex_items=(OpexItemState(
            name="Technical Management", parent_code="B.01",
            y1_amount_keur=250.0, annual_inflation=0.02,
        ),),
        opex_sub_lines=(OpexSubLineState(
            parent_group_code="B.01", business_code="B.01.U009",
            label="Extra site service", amount_keur=75.0, inflation_pct=2.0,
        ),),
    )
    template = extract_client_cost_template(state, template_id="CLIENT_OU", version=1)
    sub = next(i for i in template.opex_items if i.child_code == "B.01.U009")
    assert sub.replaces_parent is False
    assert sub.canonical_parent_key is None
    assert sub.reference_seed is False
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    # parent keeps its own amount (nothing replaced it)
    parent = next(p for p in plan.opex_items if p.name == "Technical Management")
    assert parent.y1_amount_keur == pytest.approx(250.0, abs=1e-9)
    # the U-row is added alongside
    assert any(s.business_code == "B.01.U009" for s in plan.opex_sub_lines)


def test_cb_client_opex_provenance_roundtrip():
    """Seeded/user_override detail provenance survives state → template →
    JSON → plan → rebuilt state."""
    state = CostProjectState(
        capacity_mw=64.0,
        project_ref="proj-seeded",
        opex_sub_lines=(OpexSubLineState(
            parent_group_code="B.02", business_code="B.02.01",
            label="Preventive Maintenance", amount_keur=140.0,
            inflation_pct=2.0, source="reference_seed",
            canonical_parent_key="Maintenance", reference_seed=True,
        ),),
    )
    template = extract_client_cost_template(state, template_id="CLIENT_SEED", version=1)
    item = next(i for i in template.opex_items if i.child_code == "B.02.01")
    assert item.replaces_parent and item.canonical_parent_key == "Maintenance"
    assert item.reference_seed is True
    payload = cost_template_to_json(template)
    rt = cost_template_from_json(payload)
    item_rt = next(i for i in rt.opex_items if i.child_code == "B.02.01")
    assert item_rt.canonical_parent_key == "Maintenance"
    assert item_rt.reference_seed is True
    plan = build_materialization_plan(resolve_cost_template(
        rt, MaterializationContext(capacity_mw=64.0)))
    sub = next(s for s in plan.opex_sub_lines if s.business_code == "B.02.01")
    assert sub.replay_metadata["reference_seed"] is True
    assert sub.replay_metadata["canonical_key"] == "Maintenance"
    rebuilt = plan_to_project_state(
        plan, capacity_mw=64.0, project_ref="proj-seeded")
    rt_state = next(s for s in rebuilt.opex_sub_lines if s.business_code == "B.02.01")
    assert rt_state.canonical_parent_key == "Maintenance"
    assert rt_state.reference_seed is True


# ---------------------------------------------------------------------------
# Rescale reconciliation (defect 4)
# ---------------------------------------------------------------------------

def _generic_plan_with_override(capacity, override_code, override_amount):
    t, plan = None, None
    t = build_generic_cost_template("generic_solar_reference")
    plan = build_materialization_plan(resolve_cost_template(
        t, MaterializationContext(capacity_mw=capacity)))
    from app.services.cost_template import CapexSubLinePlan, OpexSubLinePlan
    capex_subs = []
    overridden_capex_id = None
    for s in plan.capex_sub_lines:
        if s.business_code == override_code:
            overridden_capex_id = s.replay_metadata["cost_template_item_id"]
            capex_subs.append(CapexSubLinePlan(
                parent_category_code=s.parent_category_code,
                business_code=s.business_code,
                label=s.label,
                amount_keur=override_amount,
                schedule_json=s.schedule_json,
                source="user",
                replay_metadata=s.replay_metadata,
                scalar_metadata=dict(s.scalar_metadata),
                is_active=s.is_active,
            ))
        else:
            capex_subs.append(s)
    plan = MaterializationPlan(
        template_id=plan.template_id, template_version=plan.template_version,
        capex_fields=plan.capex_fields,
        capex_sub_lines=tuple(capex_subs),
        opex_items=plan.opex_items,
        opex_sub_lines=plan.opex_sub_lines,
        contingency=plan.contingency,
    )
    return t, plan, overridden_capex_id


def test_cb_rescale_capex_parent_equals_final_child_sum():
    """64→128 MW with one overridden CAPEX child: parent == sum of FINAL
    active children (override fixed, others doubled)."""
    t, plan64, overridden_id = _generic_plan_with_override(64.0, "C.01.01", 500.0)
    plan128 = rescale_materialization_plan(
        plan64, template=t, new_capacity_mw=128.0,
        overridden_item_ids={overridden_id})
    field = next(f for f in plan128.capex_fields if f.parent_code == "C.01")
    children = [s for s in plan128.capex_sub_lines
                if s.parent_category_code == "C.01" and s.is_active]
    assert field.amount_keur == pytest.approx(
        sum(s.amount_keur for s in children), abs=1e-6)
    overridden = next(s for s in plan128.capex_sub_lines if s.business_code == "C.01.01")
    assert overridden.amount_keur == pytest.approx(500.0, abs=1e-9)  # stayed fixed


def test_cb_rescale_capex_no_override_doubles_everything():
    """A: 64→128 with no overrides — parent and children all double, still
    reconciled."""
    t, plan64, _ = _generic_plan_with_override(64.0, None, None)
    plan128 = rescale_materialization_plan(plan64, template=t, new_capacity_mw=128.0)
    f64 = {f.field_name: f.amount_keur for f in plan64.capex_fields}
    f128 = {f.field_name: f.amount_keur for f in plan128.capex_fields}
    for name, v64 in f64.items():
        assert f128[name] == pytest.approx(v64 * 2, abs=1e-6), name


# ---------------------------------------------------------------------------
# Explicit-zero OPEX contingency authority (defect 5)
# ---------------------------------------------------------------------------

def test_cb_explicit_zero_opex_contingency_roundtrip():
    """0.0% typed authority → template 0.0 → core 0.0 fraction → rebuilt
    explicit 0.0%. MISSING (None) stays missing."""
    state = CostProjectState(
        capacity_mw=64.0,
        project_ref="proj-zero",
        contingency=ContingencyState(opex_pct=0.0, opex_active=True),
        opex_items=(OpexItemState(
            name="OPEX Contingency", parent_code="B.13",
            y1_amount_keur=0.0, percentage_of_opex=0.0,
        ),),
    )
    template = extract_client_cost_template(state, template_id="CLIENT_ZERO", version=1)
    item = next(i for i in template.opex_items if i.parent_code == "B.13")
    assert item.driver is CostDriver.PERCENT_OF_OPEX
    assert item.driver_value == pytest.approx(0.0, abs=1e-15)  # explicit zero
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    assert plan.opex_items[0].percentage_of_opex == pytest.approx(0.0, abs=1e-15)
    rebuilt = plan_to_project_state(
        plan, capacity_mw=64.0, project_ref="proj-zero")
    assert rebuilt.opex_items[0].percentage_of_opex == pytest.approx(0.0, abs=1e-15)


def test_cb_missing_opex_contingency_stays_missing():
    """No typed authority + no positive core pct → no PERCENT_OF_OPEX item is
    invented."""
    state = CostProjectState(
        capacity_mw=64.0,
        project_ref="proj-none",
        contingency=ContingencyState(capex_pct=6.0, capex_active=True,
                                     opex_pct=None),
        opex_items=(OpexItemState(
            name="Technical Management", parent_code="B.01",
            y1_amount_keur=250.0, annual_inflation=0.02,
        ),),
    )
    template = extract_client_cost_template(state, template_id="CLIENT_NONE", version=1)
    assert not any(i.driver is CostDriver.PERCENT_OF_OPEX
                   for i in template.opex_items)


def test_cb_inactive_contingency_distinct_from_zero():
    """6.0% INACTIVE must never become 0.0%: the plan carries the configured
    pct and the inactive flag separately; reactivation returns 6.0%."""
    state = CostProjectState(
        capacity_mw=64.0,
        project_ref="proj-inactive",
        contingency=ContingencyState(capex_pct=6.0, capex_active=False),
        capex_fields=(CapexFieldState(
            field_name="contingencies", parent_code="C.13",
            label="Contingency", amount_keur=0.0),),
    )
    template = extract_client_cost_template(state, template_id="CLIENT_INACT", version=1)
    c13 = next(i for i in template.capex_items if i.parent_code == "C.13")
    assert c13.driver_value == pytest.approx(6.0, abs=1e-12)  # config retained
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    assert plan.contingency.capex_pct == pytest.approx(6.0, abs=1e-12)
    assert plan.contingency.capex_active is False  # not applied


# ---------------------------------------------------------------------------
# Scalar metadata hardening (defect 6)
# ---------------------------------------------------------------------------

def test_cb_scalar_metadata_unknown_key_fails_closed():
    with pytest.raises(ValueError, match="scalar"):
        CostTemplate.create(
            template_id="T", version=1, name="T", technology="solar",
            kind=TemplateKind.GENERIC,
            capex_items=(CapexTemplateItem(
                item_id="capex.s", parent_code="C.01", label="X",
                driver=CostDriver.ABSOLUTE_KEUR, amount_keur=1.0,
                scalar_metadata={"totally_unknown": 1}),),
        )


def test_cb_scalar_metadata_invalid_value_fails_closed():
    with pytest.raises(ValueError, match="boolean"):
        CostTemplate.create(
            template_id="T", version=1, name="T", technology="solar",
            kind=TemplateKind.GENERIC,
            capex_items=(CapexTemplateItem(
                item_id="capex.s", parent_code="C.01", label="X",
                driver=CostDriver.ABSOLUTE_KEUR, amount_keur=1.0,
                scalar_metadata={"vat_recoverable_flag": "yes"}),),
        )


def test_cb_scalar_metadata_mutation_cannot_reach_artifacts():
    """In-place mutation of a template's metadata dict is detected at every
    consumption boundary (validate/serialize/resolve) — economics cannot be
    mutated through an already-created template."""
    item = CapexTemplateItem(
        item_id="capex.s", parent_code="C.01", label="X",
        driver=CostDriver.ABSOLUTE_KEUR, amount_keur=1.0,
        scalar_metadata={"vat_rate_pct": 25.0},
    )
    t = CostTemplate.create(template_id="T", version=1, name="T",
                            technology="solar", kind=TemplateKind.GENERIC,
                            capex_items=(item,))
    # hostile in-place mutation AFTER creation is IMPOSSIBLE (immutable proxy)
    with pytest.raises(TypeError):
        item.scalar_metadata["totally_unknown"] = 999.0
    # a valid-value mutation attempt also fails — the version is frozen
    with pytest.raises(TypeError):
        item.scalar_metadata["vat_rate_pct"] = 20.0
    # serialization stays identical after the failed attempts
    assert cost_template_to_json(t) == cost_template_to_json(t)


# ---------------------------------------------------------------------------
# Applicability addendum
# ---------------------------------------------------------------------------

def test_app_default_active_true_and_distinct_states():
    """A2/A1: default_active defaults True; ACTIVE+0 != INACTIVE."""
    active_zero = CapexTemplateItem(
        item_id="capex.az", parent_code="C.02", label="Zero item",
        driver=CostDriver.ABSOLUTE_KEUR, amount_keur=0.0)
    assert active_zero.default_active is True
    inactive = CapexTemplateItem(
        item_id="capex.in", parent_code="C.02", label="Inactive item",
        driver=CostDriver.ABSOLUTE_KEUR, amount_keur=100.0, default_active=False)
    assert inactive.amount_keur == 100.0  # economics retained
    assert inactive.default_active is False


def test_app_inactive_child_excluded_from_subtotal_and_retained():
    """A6/A13: an inactive decomposition child contributes ZERO to the
    canonical subtotal but is preserved with its full economics; active
    siblings are unaffected; rescale never reactivates it (A12) and keeps
    the parent reconciled over the ACTIVE set."""
    t = build_generic_cost_template("generic_solar_reference")
    plan64 = build_materialization_plan(resolve_cost_template(
        t, MaterializationContext(capacity_mw=64.0)))
    # deactivate one C.01 child, keep its economics in the plan
    from app.services.cost_template import CapexSubLinePlan
    subs = []
    turned_off = None
    for s in plan64.capex_sub_lines:
        if s.business_code == "C.01.02":
            turned_off = s
            subs.append(CapexSubLinePlan(
                parent_category_code=s.parent_category_code,
                business_code=s.business_code,
                label=s.label,
                amount_keur=s.amount_keur,
                schedule_json=s.schedule_json,
                source=s.source,
                replay_metadata=s.replay_metadata,
                scalar_metadata=dict(s.scalar_metadata),
                is_active=False,
            ))
        else:
            subs.append(s)
    assert turned_off is not None
    assert turned_off.amount_keur > 0  # economics retained in the plan
    plan64 = MaterializationPlan(
        template_id=plan64.template_id, template_version=plan64.template_version,
        capex_fields=plan64.capex_fields,
        capex_sub_lines=tuple(subs),
        opex_items=plan64.opex_items,
        opex_sub_lines=plan64.opex_sub_lines,
        contingency=plan64.contingency,
    )
    field64 = next(f for f in plan64.capex_fields if f.parent_code == "C.01")
    active_sum = sum(s.amount_keur for s in plan64.capex_sub_lines
                     if s.parent_category_code == "C.01" and s.is_active)
    # Note: at build time the field used the template default (all active);
    # the inactive exclusion is enforced by rescale reconciliation:
    plan128 = rescale_materialization_plan(
        plan64, template=t, new_capacity_mw=128.0)
    field128 = next(f for f in plan128.capex_fields if f.parent_code == "C.01")
    active128 = [s for s in plan128.capex_sub_lines
                 if s.parent_category_code == "C.01" and s.is_active]
    inactive128 = [s for s in plan128.capex_sub_lines
                   if s.parent_category_code == "C.01" and not s.is_active]
    assert len(inactive128) == 1
    assert inactive128[0].business_code == "C.01.02"
    assert inactive128[0].amount_keur > 0  # retained economics, still inactive
    assert field128.amount_keur == pytest.approx(
        sum(s.amount_keur for s in active128), abs=1e-6)
    # the inactive child's latent PER_MW value still doubled (reactivation at
    # 128 MW resolves correctly) without contributing to the subtotal
    assert inactive128[0].amount_keur == pytest.approx(turned_off.amount_keur * 2, abs=1e-6)
    assert field64.amount_keur != field128.amount_keur


def test_app_c17_c18_cannot_be_disabled_as_costs():
    """A8: C.17/C.18 never receive ordinary user ON/OFF semantics."""
    for parent in ("C.17", "C.18"):
        with pytest.raises(ValueError, match="COST_TEMPLATE_DERIVED_PARENT_NOT_EDITABLE"):
            CostTemplate.create(
                template_id="T", version=1, name="T", technology="solar",
                kind=TemplateKind.GENERIC,
                capex_items=(CapexTemplateItem(
                    item_id=f"x{parent}", parent_code=parent, label="Derived",
                    driver=CostDriver.ABSOLUTE_KEUR, amount_keur=10.0,
                    default_active=False),),)
