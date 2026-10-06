"""Model V2 Runtime Composition Correction A regression matrix.

Cost applicability preservation, contingency authority via the existing
FINCO authority, composition-hash payload binding, OPEX partial
reconciliation, finite guards, and scenario context wording.
"""
from __future__ import annotations

import dataclasses
import json

import pytest

from app.services.model_v2_composition import (
    CompositionStatus,
    CostBridgeError,
    CostTemplateSelection,
    ModelV2CompositionContext,
    ModelV2WorkingState,
    RevenuePlanSelection,
    compose_project_inputs,
)
from app.services.cost_template.materialize import (
    CapexFieldPlan,
    MaterializationContext,
    MaterializationPlan,
    OpexItemPlan,
    build_materialization_plan,
    rescale_materialization_plan,
    resolve_cost_template,
)
from app.project_factories import create_generic_solar_reference
from app.services.cost_template.generic import build_generic_cost_template
from domain.revenue.plan import RevenuePlan, RevenueStream, RevenueStreamType
from domain.revenue.revenue_config import PPAParams
TOL = 1e-9

_CTX = dict(capacity_mw=64.0)


def _merchant(price=65.0):
    from domain.revenue.revenue_config import MerchantParams
    return MerchantParams(merchant_enabled=True,
                          base_price_eur_mwh=price,
                          price_escalation_annual=0.02)


def _plan(ppa_price=57.0, merchant_price=65.0):
    from domain.revenue.revenue_config import PPAParams
    ppa = PPAParams(ppa_enabled=True,
                    ppa_base_price_eur_mwh=ppa_price,
                    ppa_term_years=15, ppa_volume_share=0.7,
                    ppa_price_index=0.02)
    mkt = _merchant(merchant_price)
    return RevenuePlan.create((
        RevenueStream('ppa', RevenueStreamType.PPA,
                      volume_share=0.7, ppa=ppa, term_years=15),
        RevenueStream('merchant', RevenueStreamType.MERCHANT,
                      volume_share=None, merchant=mkt),
    ))


def _state(plan=None, cost_selection=None, ref='wc-ca'):
    return ModelV2WorkingState(
        working_copy_ref=ref,
        revenue_plan_selection=(
            RevenuePlanSelection(plan=plan, source_ref='test')
            if plan else None),
        cost_template_selection=cost_selection,
    )
from domain.revenue.revenue_config import PPAParams
from domain.revenue.plan import RevenuePlan, RevenueStream, RevenueStreamType

_CTX = dict(capacity_mw=64.0)


def _capex_plan(**kw):
    return CostTemplateSelection(
        template_id=kw.pop("template_id", "CLIENT_T"),
        version=kw.pop("version", 1),
        materialization_plan=_FakeCapexPlan(**kw),
        source_ref="test")


class _FakeCapexPlan:
    def __init__(self, *, prod_amount=9000.0, prod_active=True,
                 contingency=None):
        self.template_id = "CLIENT_T"
        self.template_version = 1
        self.capex_fields = (
            CapexFieldPlan(field_name="production_units",
                           parent_code="C.01", label="PV Supply",
                           amount_keur=prod_amount, is_active=prod_active),
            CapexFieldPlan(field_name="grid_connection",
                           parent_code="C.03", label="Grid",
                           amount_keur=3000.0),
        )
        self.capex_sub_lines = ()
        self.opex_items = ()
        self.opex_sub_lines = ()
        self.contingency = contingency


def _compose_cost(selection, pi):
    return compose_project_inputs(
        _state(cost_selection=selection), ModelV2CompositionContext(**_CTX),
        pi)


# ---------------------------------------------------------------------------
# DEFECT A — cost applicability preserved (inactive → zero, plan untouched)
# ---------------------------------------------------------------------------

class _FakeContingencyPlan:
    def __init__(self, capex_pct=None, opex_pct=None,
                 capex_active=True, opex_active=True):
        self.capex_pct = capex_pct
        self.opex_pct = opex_pct
        self.capex_active = capex_active
        self.opex_active = opex_active


class _FakeMaterializationPlan:
    def __init__(self, capex_fields=(), opex_items=(), *,
                 contingency=None, template_id="CLIENT_T", version=1):
        self.template_id = template_id
        self.template_version = version
        self.capex_fields = capex_fields
        self.capex_sub_lines = ()
        self.opex_items = opex_items
        self.opex_sub_lines = ()
        self.contingency = contingency


def _capex_plan(**kw):
    """Build a CostTemplateSelection over a fake CAPEX materialization plan
    for the solar reference (production_units + grid_connection fields)."""
    pi = create_generic_solar_reference()
    prod = kw.pop("prod_amount", float(pi.capex.production_units.amount_keur))
    prod_active = kw.pop("prod_active", True)
    contingency = kw.pop("contingency", None)
    selection = CostTemplateSelection(
        template_id=kw.pop("template_id", "CLIENT_T"),
        version=kw.pop("version", 1),
        materialization_plan=_FakeMaterializationPlan(
            capex_fields=(
                CapexFieldPlan(field_name="production_units",
                               parent_code="C.01", label="PV Supply",
                               amount_keur=prod, is_active=prod_active),
                CapexFieldPlan(field_name="grid_connection",
                               parent_code="C.03", label="Grid",
                               amount_keur=3000.0),
            ),
            contingency=contingency,
        ),
        source_ref="test")
    return selection


# ---------------------------------------------------------------------------
# DEFECT A — cost applicability preserved (inactive → zero, plan untouched)
# ---------------------------------------------------------------------------

def test_ca_inactive_capex_parent_zero_contribution():
    pi = create_generic_solar_reference()
    base_amount = float(pi.capex.production_units.amount_keur)
    selection = _capex_plan(prod_amount=base_amount, prod_active=False)
    result = _compose_cost(selection, pi)
    assert result.project_inputs.capex.production_units.amount_keur == 0.0
    assert result.project_inputs.capex.grid_connection.amount_keur == \
        pytest.approx(3000.0, abs=TOL)  # active siblings unaffected
    # plan latent economics preserved (not mutated)
    assert selection.materialization_plan.capex_fields[0].amount_keur == \
        base_amount
    assert selection.materialization_plan.capex_fields[0].is_active is False


def test_ca_all_decomposition_children_inactive_capex():
    """All decomposition children inactive → canonical field subtotal 0
    (Workflow 03 presence/active-sum authority, no parent fallback)."""
    t = build_generic_cost_template("generic_solar_reference")
    resolved = resolve_cost_template(
        t, MaterializationContext(capacity_mw=64.0))
    plan = build_materialization_plan(resolved)
    subs = tuple(
        dataclasses.replace(s, is_active=False)
        if s.parent_category_code == "C.01" else s
        for s in plan.capex_sub_lines
    )
    all_off = MaterializationPlan(
        template_id=plan.template_id, template_version=plan.template_version,
        capex_fields=plan.capex_fields,
        capex_sub_lines=subs,
        opex_items=plan.opex_items,
        opex_sub_lines=plan.opex_sub_lines,
        contingency=plan.contingency,
    )
    # rescale at the SAME capacity forces the reconciliation pass over the
    # final child set (pure reconciliation: same capacity, no scaling)
    reconciled = rescale_materialization_plan(
        all_off, template=t, new_capacity_mw=64.0)
    field = next(f for f in reconciled.capex_fields if f.parent_code == "C.01")
    assert field.amount_keur == pytest.approx(0.0, abs=TOL)
    assert field.is_active is False


def test_ca_inactive_opex_parent_zero_contribution():
    """Inactive non-decomposed OPEX parent → contributes zero while the
    active siblings are unaffected."""
    pi = create_generic_solar_reference()
    plan = _FakeMaterializationPlan(
        opex_items=(
            OpexItemPlan(parent_code="B.01", name="Technical Management",
                         y1_amount_keur=250.0, annual_inflation=0.02,
                         is_active=False),
            OpexItemPlan(parent_code="B.01", name="Insurance",
                         y1_amount_keur=100.0, annual_inflation=0.01,
                         is_active=True),
        ),
    )
    selection = CostTemplateSelection(
        template_id="CLIENT_T", version=1, materialization_plan=plan,
        source_ref="test")
    result = _compose_cost(selection, pi)
    opex = {o.name: o for o in result.project_inputs.opex}
    assert opex["Technical Management"].y1_amount_keur == 0.0
    assert opex["Insurance"].y1_amount_keur == pytest.approx(100.0, abs=TOL)


def test_ca_inactive_to_active_recomposition_restores_exact_value():
    """Reactivation: re-composing from the authoritative plan with
    is_active=True restores the exact configured economics."""
    pi = create_generic_solar_reference()
    configured = 9000.0
    r1 = _compose_cost(
        _capex_plan(prod_amount=configured, prod_active=False), pi)
    assert r1.project_inputs.capex.production_units.amount_keur == 0.0
    r2 = _compose_cost(
        _capex_plan(prod_amount=configured, prod_active=True), pi)
    assert r2.project_inputs.capex.production_units.amount_keur == \
        pytest.approx(configured, abs=TOL)


def test_ca_base_inputs_immutable_through_cost_composition():
    pi = create_generic_solar_reference()
    before = float(pi.capex.production_units.amount_keur)
    selection = _capex_plan(prod_amount=9999.0, prod_active=True)
    _compose_cost(selection, pi)
    assert float(pi.capex.production_units.amount_keur) == before


# ---------------------------------------------------------------------------
# DEFECT B — contingency authority via the existing FINCO authority
# ---------------------------------------------------------------------------

def _with_contingency(selection, contingency):
    plan = selection.materialization_plan
    plan.contingency = contingency
    return selection


def test_ca_contingency_active_applied_through_authority():
    """Active 6.0% template authority replaces the base contingency amount
    through the existing apply_capex_contingency authority."""
    pi = create_generic_solar_reference()
    base_cont = float(pi.capex.contingencies.amount_keur)
    selection = _with_contingency(
        _capex_plan(), _FakeContingencyPlan(capex_pct=6.0, capex_active=True))
    result = _compose_cost(selection, pi)
    composed_cont = float(
        result.project_inputs.capex.contingencies.amount_keur)
    # the authority computes the eligible basis from the COMPOSED capex
    # before contingency: production_units stays 3000, grid becomes 3000
    composed_pre_contingency_total = 33000.0 - 2000.0 + 3000.0
    expected = 6.0 / 100.0 * composed_pre_contingency_total
    assert composed_cont == pytest.approx(expected, abs=1e-6)
    assert composed_cont == pytest.approx(2040.0, abs=1e-6)
    # base contingency replaced by the selected template authority
    assert composed_cont != base_cont or base_cont == 0.0


def test_ca_contingency_inactive_contributes_zero():
    """INACTIVE contingency retains the configured percentage in the plan
    but contributes ZERO to the composed economics."""
    pi = create_generic_solar_reference()
    plan = _FakeMaterializationPlan(
        contingency=_FakeContingencyPlan(capex_pct=6.0, capex_active=False),
    )
    selection = CostTemplateSelection(
        template_id="CLIENT_T", version=1, materialization_plan=plan,
        source_ref="test")
    result = _compose_cost(selection, pi)
    assert result.project_inputs.capex.contingencies.amount_keur == 0.0
    assert plan.contingency.capex_pct == pytest.approx(6.0, abs=1e-12)


def test_ca_contingency_explicit_zero_is_zero():
    pi = create_generic_solar_reference()
    plan = _FakeMaterializationPlan(
        contingency=_FakeContingencyPlan(capex_pct=0.0, capex_active=True),
    )
    selection = CostTemplateSelection(
        template_id="CLIENT_T", version=1, materialization_plan=plan,
        source_ref="test")
    result = _compose_cost(selection, pi)
    assert result.project_inputs.capex.contingencies.amount_keur == 0.0


def test_ca_contingency_missing_leaves_base_unchanged():
    """Missing contingency authority → base contingency survives unchanged
    (never silently invented or wiped)."""
    pi = create_generic_solar_reference()
    base_cont = float(pi.capex.contingencies.amount_keur)
    plan = _FakeMaterializationPlan()
    selection = CostTemplateSelection(
        template_id="CLIENT_T", version=1, materialization_plan=plan,
        source_ref="test")
    result = _compose_cost(selection, pi)
    assert float(result.project_inputs.capex.contingencies.amount_keur) == \
        base_cont


def test_ca_opex_contingency_active_via_authority():
    pi = create_generic_solar_reference()
    plan = _FakeMaterializationPlan(
        contingency=_FakeContingencyPlan(opex_pct=3.0, opex_active=True),
    )
    selection = CostTemplateSelection(
        template_id="CLIENT_T", version=1, materialization_plan=plan,
        source_ref="test")
    result = _compose_cost(selection, pi)
    contingency_opex = [o for o in result.project_inputs.opex
                        if getattr(o, "percentage_of_opex", 0.0)]
    assert contingency_opex
    assert contingency_opex[0].percentage_of_opex == pytest.approx(
        0.03, abs=1e-12)


def test_ca_opex_contingency_inactive_zero_contribution():
    pi = create_generic_solar_reference()
    plan = _FakeMaterializationPlan(
        contingency=_FakeContingencyPlan(opex_pct=3.0, opex_active=False),
    )
    selection = CostTemplateSelection(
        template_id="CLIENT_T", version=1, materialization_plan=plan,
        source_ref="test")
    result = _compose_cost(selection, pi)
    contingency_opex = [o for o in result.project_inputs.opex
                        if getattr(o, "percentage_of_opex", 0.0)]
    assert not contingency_opex  # zero contribution


# ---------------------------------------------------------------------------
# DEFECT C — composition hash binds the materialization payload
# ---------------------------------------------------------------------------

def test_ca_hash_changes_with_capex_amount():
    pi = create_generic_solar_reference()
    h1 = _compose_cost(_capex_plan(prod_amount=9000.0), pi).composition_hash
    h2 = _compose_cost(_capex_plan(prod_amount=8000.0), pi).composition_hash
    assert h1 != h2


def test_ca_hash_changes_with_contingency():
    pi = create_generic_solar_reference()
    p1 = _FakeMaterializationPlan(
        contingency=_FakeContingencyPlan(capex_pct=6.0, capex_active=True),
    )
    p2 = _FakeMaterializationPlan(
        contingency=_FakeContingencyPlan(capex_pct=3.0, capex_active=True),
    )
    s1 = CostTemplateSelection(template_id="CLIENT_T", version=1,
                               materialization_plan=p1, source_ref="t")
    s2 = CostTemplateSelection(template_id="CLIENT_T", version=1,
                               materialization_plan=p2, source_ref="t")
    h1 = _compose_cost(s1, pi).composition_hash
    h2 = _compose_cost(s2, pi).composition_hash
    assert h1 != h2


def test_ca_hash_identity_mismatch_fails_closed():
    pi = create_generic_solar_reference()
    plan = _FakeMaterializationPlan()
    selection = CostTemplateSelection(
        template_id="OTHER_T", version=1, materialization_plan=plan,
        source_ref="test")
    with pytest.raises(CostBridgeError, match="does not match"):
        _compose_cost(selection, pi)
    selection_v = CostTemplateSelection(
        template_id="CLIENT_T", version=2, materialization_plan=plan,
        source_ref="test")
    with pytest.raises(CostBridgeError, match="does not match"):
        _compose_cost(selection_v, pi)


def test_ca_identical_state_byte_identical_hash():
    pi = create_generic_solar_reference()
    h1 = _compose_cost(_capex_plan(prod_amount=9000.0), pi).composition_hash
    h2 = _compose_cost(_capex_plan(prod_amount=9000.0), pi).composition_hash
    assert h1 == h2


# ---------------------------------------------------------------------------
# DEFECT D — OPEX partial reconciliation
# ---------------------------------------------------------------------------

def test_ca_opex_partial_authority_preserves_unrelated_base_item():
    """The plan modifies ONE OPEX item; unrelated base OPEX items survive
    unchanged (partial reconciliation authority)."""
    pi = create_generic_solar_reference()
    plan = _FakeMaterializationPlan(
        opex_items=(
            OpexItemPlan(parent_code="B.01", name="Technical Management",
                         y1_amount_keur=250.0, annual_inflation=0.02,
                         is_active=True),
        ),
    )
    selection = CostTemplateSelection(
        template_id="CLIENT_T", version=1, materialization_plan=plan,
        source_ref="test")
    result = _compose_cost(selection, pi)
    opex = {o.name: o for o in result.project_inputs.opex}
    assert opex["Technical Management"].y1_amount_keur == pytest.approx(
        250.0, abs=TOL)
    unrelated = [n for n in opex if n != "Technical Management"]
    assert unrelated, "base OPEX items must survive"
    base_by_name = {str(o.name): o for o in pi.opex}
    for n in unrelated:
        if n in base_by_name:
            assert opex[n].y1_amount_keur == \
                pytest.approx(base_by_name[n].y1_amount_keur, abs=TOL), n


# ---------------------------------------------------------------------------
# DEFECT E — non-finite cost values fail closed
# ---------------------------------------------------------------------------

def test_ca_nonfinite_cost_values_fail_closed():
    pi = create_generic_solar_reference()
    for bad in (float("nan"), float("inf"), float("-inf")):
        selection = CostTemplateSelection(
            template_id="CLIENT_T", version=1,
            materialization_plan=_FakeMaterializationPlan(
                capex_fields=(CapexFieldPlan(
                    field_name="production_units", parent_code="C.01",
                    label="PV", amount_keur=bad),),
            ),
            source_ref="t")
        with pytest.raises(CostBridgeError, match="COST_TEMPLATE_VALUE_INVALID"):
            _compose_cost(selection, pi)


def test_ca_nonfinite_opex_y1_fails_closed():
    from app.services.cost_template.materialize import (
        CapexFieldPlan, OpexItemPlan,
    )

    plan = _FakeMaterializationPlan(
        opex_items=(
            OpexItemPlan(parent_code="B.01", name="Technical Management",
                         y1_amount_keur=float("inf"), is_active=True),
        ),
    )
    selection = CostTemplateSelection(
        template_id="CLIENT_T", version=1, materialization_plan=plan,
        source_ref="test")
    with pytest.raises(CostBridgeError, match="COST_TEMPLATE_VALUE_INVALID"):
        _compose_cost(selection, create_generic_solar_reference())


# ---------------------------------------------------------------------------
# DEFECT 7 — scenario context is carried, never applied by this module
# ---------------------------------------------------------------------------

def test_ca_scenario_context_carried_not_applied():
    """Scenario overrides are carried for the downstream scenario authority;
    this module never applies them and the base inputs remain untouched."""
    pi = create_generic_solar_reference()
    before = float(pi.capex.production_units.amount_keur)
    ctx = ModelV2CompositionContext(
        capacity_mw=64.0, scenario_id="S1",
        scenario_overrides={"capex.production_units.amount_keur": 99999.0})
    result = compose_project_inputs(_state(), ctx, pi)
    assert float(pi.capex.production_units.amount_keur) == before  # untouched
    carried = [d for d in result.diagnostics if d.layer == "scenario"]
    assert carried and "carried" in carried[0].detail
    assert result.context.scenario_overrides == ctx.scenario_overrides
    assert result.context.scenario_id == "S1"


# ===========================================================================
# CORRECTION B — fail-closed contingency types, plan identity, economic hash,
# scenario-contract wording
# ===========================================================================

import math
from pathlib import Path
from types import SimpleNamespace

from app.contingency_authority import apply_capex_contingency, apply_opex_contingency
from app.services.cost_template.materialize import ContingencyPlan
from app.services.model_v2_composition import CompositionErrorCode

_REPO = Path(__file__).resolve().parents[1]


def _code(exc_info) -> CompositionErrorCode:
    return exc_info.value.code


def _selection_with_contingency(**cont_kw):
    plan = _FakeMaterializationPlan(
        capex_fields=(CapexFieldPlan(field_name="production_units",
                                     parent_code="C.01", label="PV",
                                     amount_keur=3000.0),),
        contingency=_FakeContingencyPlan(**cont_kw))
    return CostTemplateSelection(template_id="CLIENT_T", version=1,
                                 materialization_plan=plan, source_ref="t")


# ---- B1: contingency type coercion fails closed ---------------------------

_BAD_PCTS = [True, False, "6", "6.0", float("nan"), float("inf"),
             float("-inf"), -0.5, 100.5, None.__class__, [6.0]]


@pytest.mark.parametrize("bad", _BAD_PCTS)
def test_cb_b1_bad_capex_pct_fails_closed(bad):
    with pytest.raises(CostBridgeError) as exc:
        _compose_cost(_selection_with_contingency(capex_pct=bad),
                      create_generic_solar_reference())
    assert _code(exc) is CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID
    assert "COST_TEMPLATE_VALUE_INVALID" in str(exc.value)


@pytest.mark.parametrize("bad", _BAD_PCTS)
def test_cb_b1_bad_opex_pct_fails_closed(bad):
    with pytest.raises(CostBridgeError) as exc:
        _compose_cost(_selection_with_contingency(opex_pct=bad),
                      create_generic_solar_reference())
    assert _code(exc) is CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID


@pytest.mark.parametrize("kw", [
    dict(capex_pct=True, capex_active=False),
    dict(capex_pct="6", capex_active=False),
    dict(capex_pct=float("nan"), capex_active=False),
    dict(opex_pct=True, opex_active=False),
    dict(opex_pct=float("inf"), opex_active=False),
])
def test_cb_b1_inactive_contingency_is_still_validated(kw):
    """Latent economics of an INACTIVE contingency must still be valid."""
    with pytest.raises(CostBridgeError) as exc:
        _compose_cost(_selection_with_contingency(**kw),
                      create_generic_solar_reference())
    assert _code(exc) is CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID


@pytest.mark.parametrize("kw", [
    dict(capex_pct=6.0, capex_active="false"),
    dict(capex_pct=6.0, capex_active=1),
    dict(capex_pct=6.0, capex_active=0),
    dict(capex_pct=6.0, capex_active=None),
    dict(opex_pct=2.0, opex_active=1),
    dict(opex_pct=2.0, opex_active="true"),
    dict(opex_pct=2.0, opex_active=None),
])
def test_cb_b1_non_bool_active_flags_fail_closed(kw):
    with pytest.raises(CostBridgeError) as exc:
        _compose_cost(_selection_with_contingency(**kw),
                      create_generic_solar_reference())
    assert _code(exc) is CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID


def test_cb_b1_absent_active_flag_attribute_fails_closed():
    plan = _FakeMaterializationPlan(
        contingency=SimpleNamespace(capex_pct=6.0, opex_pct=None,
                                    opex_active=True))      # capex_active absent
    selection = CostTemplateSelection(template_id="CLIENT_T", version=1,
                                      materialization_plan=plan, source_ref="t")
    with pytest.raises(CostBridgeError) as exc:
        _compose_cost(selection, create_generic_solar_reference())
    assert _code(exc) is CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID


def test_cb_b1_valid_inactive_pct_retained_zero_contribution():
    pi = create_generic_solar_reference()
    selection = _selection_with_contingency(capex_pct=6.0, capex_active=False,
                                            opex_pct=2.0, opex_active=False)
    result = _compose_cost(selection, pi)
    assert selection.materialization_plan.contingency.capex_pct == 6.0   # retained
    assert selection.materialization_plan.contingency.opex_pct == 2.0
    assert result.project_inputs.capex.contingencies.amount_keur == 0.0
    assert all(float(o.percentage_of_opex or 0.0) == 0.0
               for o in result.project_inputs.opex
               if o.name == "Contingency")


def test_cb_b1_valid_active_applied_exactly_by_existing_authority():
    pi = create_generic_solar_reference()
    selection = _selection_with_contingency(capex_pct=6.0, opex_pct=2.0)
    result = _compose_cost(selection, pi)
    # Reproduce through the existing authority from the same pre-contingency inputs.
    pre = _compose_cost(_selection_with_contingency(), pi).project_inputs
    expected_capex = apply_capex_contingency(pre.capex, 6.0)
    expected_opex = apply_opex_contingency(pre.opex, 2.0)
    assert result.project_inputs.capex.contingencies.amount_keur == \
        expected_capex.contingencies.amount_keur
    assert result.project_inputs.opex == expected_opex


def test_cb_b1_int_percentage_is_valid_and_exact():
    pi = create_generic_solar_reference()
    a = _compose_cost(_selection_with_contingency(capex_pct=6), pi)
    b = _compose_cost(_selection_with_contingency(capex_pct=6.0), pi)
    assert a.project_inputs.capex.contingencies.amount_keur == \
        b.project_inputs.capex.contingencies.amount_keur


# ---- B2: plan identity must be present and exact --------------------------

def _plan_without(attr):
    plan = _FakeMaterializationPlan()
    delattr(plan, attr)
    return plan


@pytest.mark.parametrize("attr", ["template_id", "template_version"])
def test_cb_b2_missing_plan_identity_fails_closed(attr):
    selection = CostTemplateSelection(
        template_id="CLIENT_T", version=1,
        materialization_plan=_plan_without(attr), source_ref="t")
    with pytest.raises(CostBridgeError) as exc:
        _compose_cost(selection, create_generic_solar_reference())
    assert _code(exc) is CompositionErrorCode.COST_TEMPLATE_UNRESOLVED
    assert "<absent>" in str(exc.value)


def test_cb_b2_mismatched_plan_identity_fails_closed():
    pi = create_generic_solar_reference()
    for plan, sel_id, sel_ver in (
            (_FakeMaterializationPlan(template_id="OTHER"), "CLIENT_T", 1),
            (_FakeMaterializationPlan(version=2), "CLIENT_T", 1)):
        selection = CostTemplateSelection(
            template_id=sel_id, version=sel_ver, materialization_plan=plan,
            source_ref="t")
        with pytest.raises(CostBridgeError) as exc:
            _compose_cost(selection, pi)
        assert _code(exc) is CompositionErrorCode.COST_TEMPLATE_UNRESOLVED


def test_cb_b2_bool_plan_version_does_not_alias_integer_one():
    plan = _FakeMaterializationPlan()
    plan.template_version = True            # True == 1 must not satisfy identity
    selection = CostTemplateSelection(template_id="CLIENT_T", version=1,
                                      materialization_plan=plan, source_ref="t")
    with pytest.raises(CostBridgeError) as exc:
        _compose_cost(selection, create_generic_solar_reference())
    assert _code(exc) is CompositionErrorCode.COST_TEMPLATE_UNRESOLVED


def test_cb_b2_exact_identity_succeeds():
    result = _compose_cost(
        CostTemplateSelection(template_id="CLIENT_T", version=1,
                              materialization_plan=_FakeMaterializationPlan(),
                              source_ref="t"),
        create_generic_solar_reference())
    assert result.cost_template_identity == ("CLIENT_T", 1)


# ---- B3: composition hash binds economics, not presentation ---------------

def _hash_plan(*, label="PV Supply", parent_code="C.01", amount=9000.0,
               y0=0.0, profile=(), asset_class=None, life=None,
               depreciable=True, capex_active=True,
               opex_name="Insurance", opex_parent="B.01", opex_amount=100.0,
               inflation=0.01, steps=((5, 120.0),), opex_pct=0.0,
               opex_active=True, cont_capex=6.0, cont_opex=2.0,
               cont_capex_active=True, cont_opex_active=True,
               lineage=None, basis=None, sub_lines=(), template_id="CLIENT_T",
               version=1, source_ref="t", scalar_metadata=None):
    plan = _FakeMaterializationPlan(
        capex_fields=(CapexFieldPlan(
            field_name="production_units", parent_code=parent_code,
            label=label, amount_keur=amount, y0_share=y0,
            spending_profile=profile, asset_class=asset_class,
            useful_life_override=life, is_depreciable=depreciable,
            is_active=capex_active),),
        opex_items=(OpexItemPlan(
            parent_code=opex_parent, name=opex_name, y1_amount_keur=opex_amount,
            annual_inflation=inflation, step_changes=steps,
            percentage_of_opex=opex_pct, is_active=opex_active),),
        contingency=ContingencyPlan(
            capex_pct=cont_capex, opex_pct=cont_opex,
            eligible_capex_basis_keur=basis, lineage=lineage or {},
            capex_active=cont_capex_active, opex_active=cont_opex_active),
        template_id=template_id, version=version)
    plan.capex_sub_lines = sub_lines
    return CostTemplateSelection(template_id=template_id, version=version,
                                 materialization_plan=plan, source_ref=source_ref)


def _h(**kw):
    return _compose_cost(_hash_plan(**kw),
                         create_generic_solar_reference()).composition_hash


def test_cb_b3_presentation_only_changes_keep_the_same_hash():
    base = _h()
    assert _h(label="Totally different label") == base
    assert _h(parent_code="C.99") == base            # not consumed by composition
    assert _h(opex_parent="B.99") == base
    assert _h(lineage={"note": "x", "src": "y"}) == base
    assert _h(basis=12345.0) == base                 # authority derives its own basis
    assert _h(sub_lines=("granule",)) == base        # persistence-side only
    assert _h(source_ref="other") == base            # lineage wrapper metadata
    assert _h(amount=9000) == base                   # 9000 == 9000.0 economics


@pytest.mark.parametrize("kw", [
    dict(amount=8000.0),
    dict(y0=0.4, profile=(0.6,)),
    dict(profile=(0.5, 0.5)),
    dict(asset_class="solar_panels"),
    dict(life=20),
    dict(depreciable=False),
    dict(capex_active=False),
    dict(opex_amount=101.0),
    dict(inflation=0.02),
    dict(steps=((5, 130.0),)),
    dict(steps=((6, 120.0),)),
    dict(steps=()),
    dict(opex_pct=0.05),
    dict(opex_active=False),
    dict(opex_name="Other Insurance"),
    dict(cont_capex=3.0),
    dict(cont_opex=1.0),
    dict(cont_capex_active=False),
    dict(cont_opex_active=False),
    dict(template_id="CLIENT_T2"),
    dict(version=2),
])
def test_cb_b3_economic_changes_change_the_hash(kw):
    assert _h(**kw) != _h()


def test_cb_b3_identical_state_byte_identical_hash_and_digest():
    pi = create_generic_solar_reference()
    s1, s2 = _hash_plan(), _hash_plan()
    a = compose_project_inputs(_state(cost_selection=s1),
                               ModelV2CompositionContext(**_CTX), pi)
    b = compose_project_inputs(_state(cost_selection=s2),
                               ModelV2CompositionContext(**_CTX), pi)
    assert a.composition_hash == b.composition_hash
    assert _state(cost_selection=s1).selection_digest() == \
        _state(cost_selection=s2).selection_digest()
    # label-only change is invisible to BOTH identity digests
    assert _state(cost_selection=_hash_plan(label="x")).selection_digest() == \
        _state(cost_selection=s1).selection_digest()


def test_cb_b3_payload_excludes_presentation_fields():
    from app.services.model_v2_composition.contracts import economic_cost_payload
    blob = json.dumps(economic_cost_payload(
        _hash_plan(label="LABEL_SENTINEL", lineage={"k": "LINEAGE_SENTINEL"},
                   sub_lines=("SUBLINE_SENTINEL",))), sort_keys=True)
    for sentinel in ("LABEL_SENTINEL", "LINEAGE_SENTINEL", "SUBLINE_SENTINEL"):
        assert sentinel not in blob
    assert "production_units" in blob and "Insurance" in blob   # identities kept


# ---- B4: scenario contract wording matches the code -----------------------

_W05_FILES = (
    "app/services/model_v2_composition/contracts.py",
    "app/services/model_v2_composition/compose.py",
    "app/services/model_v2_composition/__init__.py",
    "docs/model_v2/RUNTIME_COMPOSITION_CONTRACT.md",
)


def test_cb_b4_no_stale_scenario_apply_wording():
    for rel in _W05_FILES:
        text = (_REPO / rel).read_text(encoding="utf-8").lower()
        for stale in ("applied last", "applied to the composed",
                      "applied to the composed result",
                      "are applied last", "into the composed result only"):
            assert stale not in text, (rel, stale)


def test_cb_b4_contract_states_carried_not_applied_and_economic_hash():
    doc = (_REPO / "docs/model_v2/RUNTIME_COMPOSITION_CONTRACT.md"
           ).read_text(encoding="utf-8")
    assert "CARRIED" in doc and "does NOT" in doc and "downstream" in doc
    assert "economic CostTemplate materialization payload" in doc
    assert "COST_TEMPLATE_UNRESOLVED" in doc and "strict" in doc


def test_cb_b4_compose_has_no_scenario_mathematics():
    pi = create_generic_solar_reference()
    ctx = ModelV2CompositionContext(
        capacity_mw=64.0, scenario_id="S1",
        scenario_overrides={"capex.production_units.amount_keur": 1.0})
    result = compose_project_inputs(_state(cost_selection=_hash_plan()), ctx, pi)
    # the carried override is NOT applied: composed amount equals the plan's amount
    assert result.project_inputs.capex.production_units.amount_keur == 9000.0
    assert result.context.scenario_overrides == ctx.scenario_overrides
