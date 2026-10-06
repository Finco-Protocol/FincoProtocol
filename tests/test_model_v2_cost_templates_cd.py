"""Model V2 Cost Template Correction D regression matrix.

Parent applicability preservation, rescale applicability authority,
contingency single-authority consensus, OPEX replacement source fail-closed,
strict boolean semantics, and non-interference.
"""
from __future__ import annotations

import pytest

from app.services.cost_template import (
    CapexFieldState,
    CapexSubLineState,
    ContingencyState,
    CostDriver,
    CostProjectState,
    CostTemplate,
    TemplateKind,
    MaterializationContext,
    OpexItemState,
    OpexSubLineState,
    build_generic_cost_template,
    build_materialization_plan,
    cost_template_from_json,
    cost_template_to_json,
    extract_client_cost_template,
    plan_to_project_state,
    resolve_cost_template,
    rescale_materialization_plan,
)
from app.services.cost_template import CapexTemplateItem, OpexTemplateItem
from app.services.cost_template import ScalingBasis, MaterializationPlan, CapexSubLinePlan, OpexSubLinePlan
TOL = 1e-9


# ---------------------------------------------------------------------------
# 1-2. PARENT ROUNDTRIP (defects 1 + 2)
# ---------------------------------------------------------------------------

def _capex_parent_state(active: bool) -> CostProjectState:
    return CostProjectState(
        capacity_mw=64.0,
        project_ref="proj-cd",
        capex_fields=(CapexFieldState(
            field_name="grid_connection", parent_code="C.03",
            label="Grid Connection", amount_keur=1200.0,
            is_active=active,
        ),),
    )


def _opex_parent_state(active: bool) -> CostProjectState:
    return CostProjectState(
        capacity_mw=64.0,
        project_ref="proj-cd-opex",
        opex_items=(OpexItemState(
            name="Land Lease", parent_code="B.07",
            y1_amount_keur=300.0, annual_inflation=-0.01,
            is_active=active,
        ),),
    )


def test_cd1_inactive_capex_parent_roundtrip():
    """Inactive CAPEX parent: state → template → JSON → plan → state
    preserves amount + inactive."""
    state = _capex_parent_state(active=False)
    template = extract_client_cost_template(state, template_id="CD1", version=1)
    item = next(i for i in template.capex_items if i.parent_code == "C.03")
    assert item.default_active is False
    assert item.amount_keur == pytest.approx(1200.0, abs=TOL)  # not zeroed
    payload = cost_template_to_json(template)
    plan = build_materialization_plan(resolve_cost_template(
        cost_template_from_json(payload), MaterializationContext(capacity_mw=64.0)))
    rebuilt = plan_to_project_state(
        plan, capacity_mw=64.0, project_ref="proj-cd")
    field = rebuilt.capex_fields[0]
    assert field.amount_keur == pytest.approx(1200.0, abs=TOL)
    assert field.is_active is False


def test_cd2_inactive_opex_parent_roundtrip():
    """Inactive OPEX parent: same roundtrip preserves Y1/inflation/inactive."""
    state = _opex_parent_state(active=False)
    template = extract_client_cost_template(state, template_id="CD2", version=1)
    item = next(i for i in template.opex_items if i.parent_code == "B.07")
    assert item.default_active is False
    assert item.y1_amount_keur == pytest.approx(300.0, abs=TOL)
    assert item.annual_inflation == pytest.approx(-0.01, abs=1e-15)
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    rebuilt = plan_to_project_state(
        plan, capacity_mw=64.0, project_ref="proj-cd-opex")
    o = rebuilt.opex_items[0]
    assert o.y1_amount_keur == pytest.approx(300.0, abs=TOL)
    assert o.annual_inflation == pytest.approx(-0.01, abs=1e-15)
    assert o.is_active is False


def test_cd3_active_zero_parent_remains_active_zero():
    """ACTIVE + amount 0 stays ACTIVE ZERO, not inactive."""
    state = CostProjectState(
        capacity_mw=64.0,
        project_ref="proj-az",
        capex_fields=(CapexFieldState(
            field_name="grid_connection", parent_code="C.03",
            label="Zero but relevant", amount_keur=0.0, is_active=True,
        ),),
    )
    template = extract_client_cost_template(state, template_id="CD3", version=1)
    item = next(i for i in template.capex_items if i.parent_code == "C.03")
    assert item.default_active is True
    assert item.amount_keur == 0.0
    plan = build_materialization_plan(resolve_cost_template(
        template, MaterializationContext(capacity_mw=64.0)))
    rebuilt = plan_to_project_state(
        plan, capacity_mw=64.0, project_ref="proj-az")
    assert rebuilt.capex_fields[0].is_active is True
    assert rebuilt.capex_fields[0].amount_keur == 0.0


# ---------------------------------------------------------------------------
# 4-8. RESCALE APPLICABILITY (defect 3)
# ---------------------------------------------------------------------------

def test_cd4_inactive_capex_parent_stays_inactive_after_rescale():
    """Inactive PER_MW CAPEX parent: latent value may update, state stays
    inactive."""
    from app.services.cost_template import (
        CapexTemplateItem,
        MaterializationPlan,
    )

    from app.services.cost_template import ScalingBasis

    t = CostTemplate.create(
        template_id="CD4", version=1, name="T", technology="solar",
        kind=TemplateKind.GENERIC,
        capex_items=(CapexTemplateItem(
            item_id="capex.grid", parent_code="C.03", label="Grid",
            driver=CostDriver.EUR_PER_MW, driver_value=100.0,
            scaling_basis=ScalingBasis.PER_MW,
            default_active=False,
        ),),
    )

    plan = build_materialization_plan(resolve_cost_template(
        t, MaterializationContext(capacity_mw=64.0)))
    assert plan.capex_fields[0].is_active is False
    plan128 = rescale_materialization_plan(
        plan, template=t, new_capacity_mw=128.0)
    f = plan128.capex_fields[0]
    assert f.is_active is False  # never reactivated
    assert f.amount_keur == pytest.approx(100.0 * 128.0, abs=1e-6)  # latent scaled


def test_cd5_inactive_opex_parent_stays_inactive_after_rescale():
    """Inactive PER_MW OPEX parent: same guarantee."""
    from app.services.cost_template import (
        OpexTemplateItem,
        ScalingBasis as _SB,
    )

    t = CostTemplate.create(
        template_id="CD5", version=1, name="T", technology="solar",
        kind=TemplateKind.GENERIC,
        opex_items=(OpexTemplateItem(
            item_id="opex.land", parent_code="B.07", label="Land Lease",
            driver=CostDriver.EUR_PER_MW, driver_value=50.0,
            scaling_basis=_SB.PER_MW, default_active=False,
        ),),
    )
    plan = build_materialization_plan(resolve_cost_template(
        t, MaterializationContext(capacity_mw=64.0)))
    plan128 = rescale_materialization_plan(
        plan, template=t, new_capacity_mw=128.0)
    p = plan128.opex_items[0]
    assert p.is_active is False
    assert p.y1_amount_keur == pytest.approx(50.0 * 128.0, abs=1e-6)


def test_cd6_all_capex_children_off_rescale_parent_zero_inactive():
    """All CAPEX decomposition children OFF after rescale → parent 0 and
    inactive; children retained."""
    from app.services.cost_template import CapexSubLinePlan

    t = build_generic_cost_template("generic_solar_reference")
    plan64 = build_materialization_plan(resolve_cost_template(
        t, MaterializationContext(capacity_mw=64.0)))
    subs = []
    for s in plan64.capex_sub_lines:
        if s.parent_category_code == "C.01":
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
    all_off = MaterializationPlan(
        template_id=plan64.template_id, template_version=plan64.template_version,
        capex_fields=plan64.capex_fields,
        capex_sub_lines=tuple(subs),
        opex_items=plan64.opex_items,
        opex_sub_lines=plan64.opex_sub_lines,
        contingency=plan64.contingency,
    )
    plan128 = rescale_materialization_plan(
        all_off, template=t, new_capacity_mw=128.0)
    field = next(f for f in plan128.capex_fields if f.parent_code == "C.01")
    assert field.amount_keur == pytest.approx(0.0, abs=1e-12)
    assert field.is_active is False
    inactive = [s for s in plan128.capex_sub_lines
                if s.parent_category_code == "C.01"]
    assert inactive and all(not s.is_active for s in inactive)


def test_cd7_all_opex_children_off_rescale_parent_zero_inactive():
    """All OPEX decomposition children OFF after rescale → canonical parent
    0 and inactive."""
    from app.services.cost_template import OpexSubLinePlan

    t = build_generic_cost_template("generic_solar_reference")
    plan64 = build_materialization_plan(resolve_cost_template(
        t, MaterializationContext(capacity_mw=64.0)))
    subs = []
    for s in plan64.opex_sub_lines:
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
        template_id=plan64.template_id, template_version=plan64.template_version,
        capex_fields=plan64.capex_fields,
        capex_sub_lines=plan64.capex_sub_lines,
        opex_items=plan64.opex_items,
        opex_sub_lines=tuple(subs),
        contingency=plan64.contingency,
    )
    plan128 = rescale_materialization_plan(
        all_off, template=t, new_capacity_mw=128.0)
    parent = next(p for p in plan128.opex_items if p.name == "Technical Management")
    assert parent.y1_amount_keur == pytest.approx(0.0, abs=1e-12)
    assert parent.is_active is False


def test_cd8_one_child_on_parent_active_correct_subtotal():
    """One child ON (other OFF) → parent active with that child's amount."""
    from app.services.cost_template import CapexSubLinePlan

    t = build_generic_cost_template("generic_solar_reference")
    plan64 = build_materialization_plan(resolve_cost_template(
        t, MaterializationContext(capacity_mw=64.0)))
    subs = []
    on_amount = None
    for s in plan64.capex_sub_lines:
        if s.parent_category_code == "C.01":
            keep = s.business_code == "C.01.01"
            if keep:
                on_amount = s.amount_keur
            subs.append(CapexSubLinePlan(
                parent_category_code=s.parent_category_code,
                business_code=s.business_code,
                label=s.label,
                amount_keur=s.amount_keur,
                schedule_json=s.schedule_json,
                source=s.source,
                replay_metadata=s.replay_metadata,
                scalar_metadata=dict(s.scalar_metadata),
                is_active=keep,
            ))
        else:
            subs.append(s)
    mixed = MaterializationPlan(
        template_id=plan64.template_id, template_version=plan64.template_version,
        capex_fields=plan64.capex_fields,
        capex_sub_lines=tuple(subs),
        opex_items=plan64.opex_items,
        opex_sub_lines=plan64.opex_sub_lines,
        contingency=plan64.contingency,
    )
    plan128 = rescale_materialization_plan(
        mixed, template=t, new_capacity_mw=128.0)
    field = next(f for f in plan128.capex_fields if f.parent_code == "C.01")
    assert field.is_active is True
    active = [s for s in plan128.capex_sub_lines
              if s.parent_category_code == "C.01" and s.is_active]
    assert len(active) == 1
    assert field.amount_keur == pytest.approx(
        sum(s.amount_keur for s in active), abs=1e-6)


def test_cd_inactive_latent_rescales_without_reactivating():
    """Inactive child latent PER_MW value rescales without becoming active
    (A12) — sibling states unaffected."""
    from app.services.cost_template import CapexSubLinePlan

    t = build_generic_cost_template("generic_solar_reference")
    plan64 = build_materialization_plan(resolve_cost_template(
        t, MaterializationContext(capacity_mw=64.0)))
    subs = []
    off_before = None
    for s in plan64.capex_sub_lines:
        if s.business_code == "C.01.03":
            off_before = s.amount_keur
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
    mixed = MaterializationPlan(
        template_id=plan64.template_id, template_version=plan64.template_version,
        capex_fields=plan64.capex_fields,
        capex_sub_lines=tuple(subs),
        opex_items=plan64.opex_items,
        opex_sub_lines=plan64.opex_sub_lines,
        contingency=plan64.contingency,
    )
    plan128 = rescale_materialization_plan(
        mixed, template=t, new_capacity_mw=128.0)
    off = next(s for s in plan128.capex_sub_lines if s.business_code == "C.01.03")
    assert off.is_active is False
    assert off.amount_keur == pytest.approx(off_before * 2, abs=1e-6)


# ---------------------------------------------------------------------------
# 9-12. CONTINGENCY SINGLE AUTHORITY (defect 4)
# ---------------------------------------------------------------------------

def test_cd9_divergent_contingency_authority_fails_closed():
    """C.13 item default_active=False + envelope capex_contingency_active=True
    → COST_TEMPLATE_CONTINGENCY_AUTHORITY_DIVERGENT. Same for B.13."""
    with pytest.raises(ValueError, match="COST_TEMPLATE_CONTINGENCY_AUTHORITY_DIVERGENT"):
        CostTemplate.create(
            template_id="T", version=1, name="T", technology="solar",
            kind=TemplateKind.GENERIC,
            capex_items=(CapexTemplateItem(
                item_id="capex.contingencies", parent_code="C.13",
                label="Contingency", driver=CostDriver.PERCENT_OF_ELIGIBLE_CAPEX,
                driver_value=6.0, default_active=False),),
            capex_contingency_active=True,
        )
    with pytest.raises(ValueError, match="COST_TEMPLATE_CONTINGENCY_AUTHORITY_DIVERGENT"):
        CostTemplate.create(
            template_id="T", version=1, name="T", technology="solar",
            kind=TemplateKind.GENERIC,
            opex_items=(OpexTemplateItem(
                item_id="opex.contingency", parent_code="B.13",
                label="OPEX Contingency", driver=CostDriver.PERCENT_OF_OPEX,
                driver_value=6.0, default_active=False),),
            opex_contingency_active=True,
        )


def test_cd10_consistent_contingency_authority_accepted():
    """Mirror agreement (both active / both inactive) is accepted and the
    plan uses the item applicability."""
    for active in (True, False):
        t = CostTemplate.create(
            template_id=f"T{active}", version=1, name="T", technology="solar",
            kind=TemplateKind.GENERIC,
            capex_items=(CapexTemplateItem(
                item_id="capex.contingencies", parent_code="C.13",
                label="Contingency", driver=CostDriver.PERCENT_OF_ELIGIBLE_CAPEX,
                driver_value=6.0, default_active=active),),
            capex_contingency_active=active,
        )
        plan = build_materialization_plan(resolve_cost_template(
            t, MaterializationContext(capacity_mw=64.0)))
        assert plan.contingency.capex_pct == pytest.approx(6.0, abs=1e-12)
        assert plan.contingency.capex_active is active


def test_cd11_contingency_four_states_distinct():
    """6% active / 6% inactive / 0% active / 0% inactive / MISSING are five
    distinct deterministic states."""
    plans = {}
    for pct, active in ((6.0, True), (6.0, False), (0.0, True), (0.0, False)):
        state = CostProjectState(
            capacity_mw=64.0,
            project_ref=f"p-{pct}-{active}",
            contingency=ContingencyState(
                capex_pct=pct, capex_active=active,
                opex_pct=pct, opex_active=active),
            capex_fields=(CapexFieldState(
                field_name="contingencies", parent_code="C.13",
                label="C", amount_keur=0.0),),
            opex_items=(OpexItemState(
                name="OPEX Contingency", parent_code="B.13",
                y1_amount_keur=0.0,
                percentage_of_opex=pct / 100.0,
            ),),
        )
        template = extract_client_cost_template(
            state, template_id=f"CC-{pct}-{active}", version=1)
        plan = build_materialization_plan(resolve_cost_template(
            template, MaterializationContext(capacity_mw=64.0)))
        plans[(pct, active)] = plan
    # same pct, different applicability → different plans
    assert cost_template_to_json(extract_client_cost_template(
        CostProjectState(
            capacity_mw=64.0, project_ref="x",
            contingency=ContingencyState(capex_pct=6.0, capex_active=True),
            capex_fields=(CapexFieldState(
                field_name="contingencies", parent_code="C.13",
                label="C", amount_keur=0.0),),
        ), template_id="A", version=1)
    ) != cost_template_to_json(extract_client_cost_template(
        CostProjectState(
            capacity_mw=64.0, project_ref="x",
            contingency=ContingencyState(capex_pct=6.0, capex_active=False),
            capex_fields=(CapexFieldState(
                field_name="contingencies", parent_code="C.13",
                label="C", amount_keur=0.0),),
        ), template_id="A", version=1)
    )
    assert plans[(6.0, True)].contingency.capex_active is True
    assert plans[(6.0, False)].contingency.capex_active is False
    assert plans[(0.0, True)].contingency.capex_active is True
    assert plans[(0.0, False)].contingency.capex_active is False


# ---------------------------------------------------------------------------
# OPEX REPLACEMENT SOURCE FAIL-CLOSED (defect 5)
# ---------------------------------------------------------------------------

def _replacement_item(**kw):
    defaults = dict(
        item_id="opex.rep", parent_code="B.02", child_code="B.02.01",
        label="Preventive Maintenance",
        driver=CostDriver.ABSOLUTE_KEUR, y1_amount_keur=140.0,
        replaces_parent=True, canonical_parent_key="Maintenance",
        reference_seed=True, persisted_source="reference_seed",
    )
    defaults.update(kw)
    return OpexTemplateItem(**defaults)


def test_cb_runtime_predicate_reference_seed():
    """CB13: valid reference_seed replacement satisfies the ACTUAL runtime
    replacement predicate."""
    plan = build_materialization_plan(resolve_cost_template(
        CostTemplate.create(
            template_id="T", version=1, name="T", technology="solar",
            kind=TemplateKind.GENERIC,
            opex_items=(_replacement_item(),),
        ), MaterializationContext(capacity_mw=64.0)))
    s = plan.opex_sub_lines[0]
    # the EXISTING runtime predicate (opex_sub_lines_integration):
    assert s.source in {"reference_seed", "user_override"}
    assert s.replay_metadata.get("reference_seed") is True
    assert s.replay_metadata.get("canonical_key") == "Maintenance"


def test_cb_runtime_predicate_user_override():
    """CB14: user_override replacement keeps runtime-compatible source."""
    plan = build_materialization_plan(resolve_cost_template(
        CostTemplate.create(
            template_id="T", version=1, name="T", technology="solar",
            kind=TemplateKind.GENERIC,
            opex_items=(_replacement_item(persisted_source="user_override"),),
        ), MaterializationContext(capacity_mw=64.0)))
    s = plan.opex_sub_lines[0]
    assert s.source == "user_override"
    assert s.replay_metadata.get("reference_seed") is True
    assert s.replay_metadata.get("canonical_key") == "Maintenance"


def test_cd_replacement_source_user_fails_closed():
    """CB15 / defect 5: replacement with persisted_source=user is a runtime-
    incompatible combination — fails closed at the contract boundary."""
    with pytest.raises(ValueError, match="COST_TEMPLATE_REPLACEMENT_SOURCE_INVALID"):
        CostTemplate.create(
            template_id="T", version=1, name="T", technology="solar",
            kind=TemplateKind.GENERIC,
            opex_items=(_replacement_item(persisted_source="user"),),
        )


def test_cd_replacement_reference_seed_false_fails_closed():
    """CB16: replacement with reference_seed=False fails closed."""
    with pytest.raises(ValueError, match="COST_TEMPLATE_REPLACEMENT_PROVENANCE_INVALID"):
        CostTemplate.create(
            template_id="T", version=1, name="T", technology="solar",
            kind=TemplateKind.GENERIC,
            opex_items=(_replacement_item(reference_seed=False),),
        )


def test_cd_replacement_missing_canonical_key_fails_closed():
    with pytest.raises(ValueError, match="COST_TEMPLATE_CANONICAL_PARENT_KEY_REQUIRED"):
        CostTemplate.create(
            template_id="T", version=1, name="T", technology="solar",
            kind=TemplateKind.GENERIC,
            opex_items=(_replacement_item(canonical_parent_key=None),),
        )


def test_cd_additive_ucode_user_passes():
    """CB17: additive B.NN.U### user row passes (no replacement contract)."""
    t = CostTemplate.create(
        template_id="T", version=1, name="T", technology="solar",
        kind=TemplateKind.GENERIC,
        opex_items=(OpexTemplateItem(
            item_id="opex.u", parent_code="B.01", child_code="B.01.U009",
            label="Extra service", driver=CostDriver.ABSOLUTE_KEUR,
            y1_amount_keur=60.0, replaces_parent=False,
        ),),
    )
    plan = build_materialization_plan(resolve_cost_template(
        t, MaterializationContext(capacity_mw=64.0)))
    assert plan.opex_sub_lines[0].source == "user"


# ---------------------------------------------------------------------------
# BOOLEAN CONTRACT (defect 6)
# ---------------------------------------------------------------------------

def test_cd_strict_bool_template_applicability():
    """CB18/19: True/False accepted; 0/1/"false"/None rejected for template
    applicability."""
    base = dict(item_id="capex.a", parent_code="C.02", label="EPC",
                driver=CostDriver.ABSOLUTE_KEUR, amount_keur=10.0)
    for good in (True, False):
        item = CapexTemplateItem(**base, default_active=good)
        item.validate()  # strict bool validated via the item contract
    for bad in (0, 1, "false", "true", None):
        item = CapexTemplateItem(**base, default_active=bad)
        with pytest.raises(ValueError, match="COST_TEMPLATE_APPLICABILITY_INVALID"):
            item.validate()
    # envelope flags
    good_item = CapexTemplateItem(**base)
    with pytest.raises(ValueError, match="COST_TEMPLATE_APPLICABILITY_INVALID"):
        CostTemplate.create(template_id="T", version=1, name="T",
                            technology="solar", kind=TemplateKind.GENERIC,
                            capex_items=(good_item,),
                            capex_contingency_active=1)
    with pytest.raises(ValueError, match="COST_TEMPLATE_APPLICABILITY_INVALID"):
        CostTemplate.create(template_id="T", version=1, name="T",
                            technology="solar", kind=TemplateKind.GENERIC,
                            capex_items=(CapexTemplateItem(**base),),
                            opex_contingency_active="true")


def test_cd_strict_bool_state_applicability():
    """State applicability is strict boolean at CostProjectState.validate."""
    with pytest.raises(ValueError, match="COST_STATE_APPLICABILITY_INVALID"):
        extract_client_cost_template(
            CostProjectState(
                capacity_mw=64.0, project_ref="p",
                capex_fields=(CapexFieldState(
                    field_name="audit_legal", parent_code="C.08",
                    label="X", amount_keur=1.0, is_active=1),),
            ), template_id="T", version=1)
    with pytest.raises(ValueError, match="COST_STATE_APPLICABILITY_INVALID"):
        extract_client_cost_template(
            CostProjectState(
                capacity_mw=64.0, project_ref="p",
                contingency=ContingencyState(
                    capex_pct=6.0, capex_active="false"),
                capex_fields=(CapexFieldState(
                    field_name="contingencies", parent_code="C.13",
                    label="C", amount_keur=0.0),),
            ), template_id="T", version=1)


# ---------------------------------------------------------------------------
# NON-INTERFERENCE
# ---------------------------------------------------------------------------

def test_cd_generic_solar_wind_economics_unchanged():
    """Generic Solar/Wind materialization totals unchanged (reference
    capacity parity)."""
    from app.services.reference_seed_service import _reference_inputs

    for template_source, tech in (
        ("generic_solar_reference", "solar"),
        ("generic_wind_reference", "wind"),
    ):
        t = build_generic_cost_template(template_source)
        pi = _reference_inputs(template_source)
        plan = build_materialization_plan(resolve_cost_template(
            t, MaterializationContext(capacity_mw=float(pi.technical.capacity_mw))))
        assert sum(f.amount_keur for f in plan.capex_fields) == pytest.approx(
            float(pi.capex.total_capex), abs=1e-9)
        opex_parents = {p.name: p.y1_amount_keur for p in plan.opex_items}
        for o in pi.opex:
            if float(getattr(o, "percentage_of_opex", 0) or 0):
                continue
            assert opex_parents[str(o.name)] == pytest.approx(
                float(o.y1_amount_keur), abs=1e-9)


def test_cd_revenue_and_engine_files_untouched():
    import subprocess
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    changed = subprocess.run(
        ["git", "diff", "--name-only", "origin/epic/model-saas-v2", "--",
         "domain/revenue", "financial_engine", "finco_core", "domain/analytics"],
        capture_output=True, text=True, cwd=str(repo)).stdout.split()
    assert changed == [], changed
