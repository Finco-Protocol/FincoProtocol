"""Model V2 Workflow 05 — canonical input composition + runtime bridge.

Acceptance markers:

  MODEL_V2_COMPOSITION_LEGACY_PARITY    — no V2 selections: base inputs pass
                                          through untouched, exact legacy economics
  MODEL_V2_COMPOSITION_REVENUE_BRIDGE   — RevenuePlan composes onto canonical
                                          RevenueParams (PPA + merchant)
  MODEL_V2_COMPOSITION_COST_BRIDGE      — CostTemplate materialization plan
                                          composes onto canonical CAPEX/OPEX
  MODEL_V2_COMPOSITION_IDENTITY        — deterministic composition hash;
                                          economically relevant V2 state
                                          changes it, presentation does not
  MODEL_V2_COMPOSITION_SCENARIO_ISOLATION — scenario overrides ride the
                                          context only; base state and base
                                          inputs are never mutated
  MODEL_V2_COMPOSITION_FAIL_CLOSED     — unsupported/non-finite/invalid V2
                                          state fails before engine execution
  MODEL_V2_REGISTER_INTEGRATION        — Workflow 04 register accepts the
                                          composed plan through RegisterContext
"""
from __future__ import annotations

import math

import pytest

from app.services.model_v2_composition import (
    CompositionErrorCode,
    CompositionStatus,
    CostTemplateSelection,
    ModelV2CompositionContext,
    ModelV2WorkingState,
    RevenuePlanBridgeError,
    RevenuePlanSelection,
    compose_project_inputs,
)
from domain.revenue.plan import RevenuePlan, RevenueStream, RevenueStreamType
from domain.revenue.revenue_config import (
    CfDParams,
    FeedInTariffParams,
    MerchantParams,
    PPAParams,
)
from app.project_factories import (
    create_generic_solar_reference,
    create_generic_wind_reference,
)
from app.services.cost_template.materialize import CapexFieldPlan, OpexItemPlan


def _plan(ppa_price=57.0, merchant_price=65.0):
    ppa = PPAParams(ppa_enabled=True, ppa_base_price_eur_mwh=ppa_price,
                    ppa_term_years=15, ppa_volume_share=0.7, ppa_price_index=0.02)
    mkt = MerchantParams(merchant_enabled=True, base_price_eur_mwh=merchant_price,
                         price_escalation_annual=0.02)
    from domain.revenue.plan import ContractRole  # noqa: F401
    return RevenuePlan.create((
        RevenueStream("ppa", RevenueStreamType.PPA, volume_share=0.7,
                      ppa=ppa, term_years=15),
        RevenueStream("merchant", RevenueStreamType.MERCHANT,
                      volume_share=None, merchant=mkt),
    ))


def _state(plan=None, cost_selection=None, ref="wc-1"):
    return ModelV2WorkingState(
        working_copy_ref=ref,
        revenue_plan_selection=(
            RevenuePlanSelection(plan=plan, source_ref="test") if plan else None),
        cost_template_selection=cost_selection,
    )


_CTX = dict(capacity_mw=64.0)


# ---------------------------------------------------------------------------
# LEGACY PARITY
# ---------------------------------------------------------------------------

class TestLegacyParity:
    def test_solar_legacy_passthrough_exact(self):
        """MODEL_V2_COMPOSITION_LEGACY_PARITY: no V2 selections → the base
        ProjectInputs pass through untouched."""
        pi = create_generic_solar_reference()
        result = compose_project_inputs(
            _state(), ModelV2CompositionContext(**_CTX), pi)
        assert result.status is CompositionStatus.LEGACY_PASSTHROUGH
        assert result.project_inputs.revenue.ppa_base_tariff == \
            pi.revenue.ppa_base_tariff
        assert result.project_inputs.capex.total_capex == pi.capex.total_capex
        assert result.revenue_plan is None
        assert result.cost_template_identity is None
        assert result.composed

    def test_solar_legacy_economics_identical(self):
        """Legacy parity: composed (passthrough) inputs reproduce the base
        revenue tariff path exactly."""
        pi = create_generic_solar_reference()
        result = compose_project_inputs(
            _state(), ModelV2CompositionContext(**_CTX), pi)
        for year in (1, 5, 10):
            assert result.project_inputs.revenue.tariff_at_year(year) == \
                pi.revenue.tariff_at_year(year)

    def test_wind_legacy_passthrough_exact(self):
        pi = create_generic_wind_reference()
        result = compose_project_inputs(
            _state(ref="wc-w"), ModelV2CompositionContext(**_CTX), pi)
        assert result.status is CompositionStatus.LEGACY_PASSTHROUGH
        assert result.project_inputs.capex.total_capex == pi.capex.total_capex
        assert result.project_inputs.revenue.market_prices_curve == \
            pi.revenue.market_prices_curve


# ---------------------------------------------------------------------------
# REVENUE BRIDGE
# ---------------------------------------------------------------------------

class TestRevenueBridge:
    def test_revenue_plan_composes_canonical_fields(self):
        """MODEL_V2_COMPOSITION_REVENUE_BRIDGE: PPA + merchant plan composes
        onto the canonical RevenueParams the engine already reads."""
        pi = create_generic_solar_reference()
        result = compose_project_inputs(
            _state(_plan()), ModelV2CompositionContext(**_CTX), pi)
        assert result.status is CompositionStatus.COMPOSED
        rev = result.project_inputs.revenue
        assert rev.ppa_base_tariff == pytest.approx(57.0, abs=1e-12)
        assert rev.ppa_term_years == pytest.approx(15.0, abs=1e-12)
        assert rev.ppa_index == pytest.approx(0.02, abs=1e-12)
        assert rev.ppa_production_share == pytest.approx(0.7, abs=1e-12)
        # merchant curve expanded through the existing price_at_year authority
        assert len(rev.market_prices_curve) == pi.info.horizon_years
        assert rev.market_prices_curve[0] == pytest.approx(65.0, abs=1e-12)
        # provenance exposed
        layers = {d.layer for d in result.diagnostics}
        assert "revenue_plan" in layers

    def test_revenue_bridge_does_not_mutate_base_inputs(self):
        pi = create_generic_solar_reference()
        before = (pi.revenue.ppa_base_tariff,
                  tuple(pi.revenue.market_prices_curve))
        compose_project_inputs(
            _state(_plan()), ModelV2CompositionContext(**_CTX), pi)
        assert (pi.revenue.ppa_base_tariff,
                tuple(pi.revenue.market_prices_curve)) == before

    def test_revenue_bridge_cfd_fails_closed(self):
        """CfD streams have no canonical ProjectInputs authority yet — the
        composition fails closed instead of approximating."""
        plan = RevenuePlan.create((
            RevenueStream("cfd", RevenueStreamType.CFD, volume_share=1.0,
                          cfd=CfDParams(cfd_enabled=True, strike_price_eur_mwh=70.0),
                          reference_stream_id="m", term_years=10),
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=65.0)),
        ), market_price=MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0))
        with pytest.raises(RevenuePlanBridgeError,
                           match="REVENUE_PLAN_STREAM_UNSUPPORTED"):
            compose_project_inputs(
                _state(plan), ModelV2CompositionContext(**_CTX),
                create_generic_solar_reference())

    def test_revenue_bridge_fit_fails_closed(self):
        plan = RevenuePlan.create((
            RevenueStream("fit", RevenueStreamType.FIT_FIXED, volume_share=1.0,
                          fit=FeedInTariffParams(fit_enabled=True,
                                                 fit_type="fixed_fit",
                                                 fit_price_eur_mwh=80.0)),
        ))
        with pytest.raises(RevenuePlanBridgeError,
                           match="REVENUE_PLAN_STREAM_UNSUPPORTED"):
            compose_project_inputs(
                _state(plan), ModelV2CompositionContext(**_CTX),
                create_generic_solar_reference())

    def test_revenue_bridge_nonfinite_fails_closed(self):
        bad_ppa = PPAParams(ppa_enabled=True,
                            ppa_base_price_eur_mwh=float("nan"))
        with pytest.raises(ValueError,
                           match="REVENUE_STREAM_VALUE_INVALID"):
            plan = RevenuePlan.create((
                RevenueStream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                              ppa=bad_ppa),
            ))
            compose_project_inputs(
                _state(plan), ModelV2CompositionContext(**_CTX),
                create_generic_solar_reference())

    def test_revenue_bridge_missing_merchant_curve_fails_closed(self):
        with pytest.raises(ValueError,
                           match="REVENUE_STREAM_MARKET_CUSTOM_CURVE_REQUIRED"):
            plan = RevenuePlan.create((
                RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                              merchant=MerchantParams(merchant_enabled=True,
                                                      base_price_eur_mwh=65.0,
                                                      price_scenario="custom",
                                                      custom_price_curve=())),
            ))
            compose_project_inputs(
                _state(plan), ModelV2CompositionContext(**_CTX),
                create_generic_solar_reference())


# ---------------------------------------------------------------------------
# COST BRIDGE
# ---------------------------------------------------------------------------

class _FakeCapexFieldPlan:
    def __init__(self, field_name, parent_code, label, amount_keur):
        self.field_name = field_name
        self.parent_code = parent_code
        self.label = label
        self.amount_keur = amount_keur
        self.y0_share = 0.0
        self.spending_profile = ()
        self.asset_class = None
        self.useful_life_override = None
        self.is_depreciable = True
        self.is_active = True


class _FakeOpexItemPlan:
    def __init__(self, parent_code, name, y1_amount_keur, annual_inflation=0.0):
        self.parent_code = parent_code
        self.name = name
        self.y1_amount_keur = y1_amount_keur
        self.annual_inflation = annual_inflation
        self.step_changes = ()
        self.percentage_of_opex = 0.0
        self.is_active = True


class _FakeMaterializationPlan:
    def __init__(self, capex_fields, opex_items, template_id="CLIENT_T",
                 version=1):
        self.template_id = template_id
        self.template_version = version
        self.capex_fields = capex_fields
        self.capex_sub_lines = ()
        self.opex_items = opex_items
        self.opex_sub_lines = ()
        # Correction A (defect B): contingency authority carrier.
        self.contingency = None


def _cost_selection(plan):
    return CostTemplateSelection(
        template_id=plan.template_id, version=plan.template_version,
        materialization_plan=plan, source_ref="test")


class TestCostBridge:
    def test_cost_plan_composes_canonical_fields(self):
        """MODEL_V2_COMPOSITION_COST_BRIDGE: materialization field plans
        compose onto the canonical CapexStructure / OpexItem authorities."""
        pi = create_generic_solar_reference()
        from app.services.cost_template.materialize import (
            CapexFieldPlan, OpexItemPlan,
        )

        plan = _FakeMaterializationPlan(
            capex_fields=(
                CapexFieldPlan(field_name="production_units",
                               parent_code="C.01", label="PV Supply",
                               amount_keur=9000.0),
                CapexFieldPlan(field_name="grid_connection",
                               parent_code="C.03", label="Grid",
                               amount_keur=3000.0),
            ),
            opex_items=(
                OpexItemPlan(parent_code="B.01",
                             name="Technical Management",
                             y1_amount_keur=250.0, annual_inflation=0.02),
            ),
        )
        result = compose_project_inputs(
            _state(cost_selection=_cost_selection(plan)),
            ModelV2CompositionContext(**_CTX), pi)
        assert result.status is CompositionStatus.COMPOSED
        assert result.cost_template_identity == ("CLIENT_T", 1)
        capex = result.project_inputs.capex
        assert capex.production_units.amount_keur == pytest.approx(9000.0, abs=1e-9)
        assert capex.grid_connection.amount_keur == pytest.approx(3000.0, abs=1e-9)
        # untouched fields keep base economics
        assert capex.epc_contract.amount_keur == \
            pi.capex.epc_contract.amount_keur
        opex_names = {o.name: o for o in result.project_inputs.opex}
        assert opex_names["Technical Management"].y1_amount_keur == \
            pytest.approx(250.0, abs=1e-9)
        assert opex_names["Technical Management"].annual_inflation == \
            pytest.approx(0.02, abs=1e-12)

    def test_cost_bridge_does_not_mutate_base_inputs(self):
        pi = create_generic_solar_reference()
        before = pi.capex.production_units.amount_keur
        plan = _FakeMaterializationPlan(
            capex_fields=(CapexFieldPlan(
                field_name="production_units", parent_code="C.01",
                label="PV Supply", amount_keur=999.0),),
            opex_items=(),
        )
        compose_project_inputs(
            _state(cost_selection=_cost_selection(plan)),
            ModelV2CompositionContext(**_CTX), pi)
        assert pi.capex.production_units.amount_keur == before

    def test_cost_bridge_unknown_field_fails_closed(self):
        plan = _FakeMaterializationPlan(
            capex_fields=(CapexFieldPlan(
                field_name="not_a_field", parent_code="C.01",
                label="?", amount_keur=1.0),),
            opex_items=(),
        )
        with pytest.raises(ValueError, match="unknown CapexStructure field"):
            compose_project_inputs(
                _state(cost_selection=_cost_selection(plan)),
                ModelV2CompositionContext(**_CTX),
                create_generic_solar_reference())

    def test_cost_bridge_unknown_asset_class_fails_closed(self):
        plan = _FakeMaterializationPlan(
            capex_fields=(CapexFieldPlan(
                field_name="production_units", parent_code="C.01",
                label="PV", amount_keur=1.0, asset_class="unobtanium"),),
            opex_items=(),
        )
        with pytest.raises(ValueError, match="unknown depreciation asset class"):
            compose_project_inputs(
                _state(cost_selection=_cost_selection(plan)),
                ModelV2CompositionContext(**_CTX),
                create_generic_solar_reference())


# ---------------------------------------------------------------------------
# COMPOSITE IDENTITY
# ---------------------------------------------------------------------------

class TestCompositionIdentity:
    def test_identity_deterministic(self):
        pi = create_generic_solar_reference()
        r1 = compose_project_inputs(
            _state(_plan()), ModelV2CompositionContext(**_CTX), pi)
        r2 = compose_project_inputs(
            _state(_plan()), ModelV2CompositionContext(**_CTX), pi)
        assert r1.composition_hash == r2.composition_hash
        assert len(r1.composition_hash) == 64

    def test_identity_revenue_plan_changes_hash(self):
        pi = create_generic_solar_reference()
        h_plan = compose_project_inputs(
            _state(_plan()), ModelV2CompositionContext(**_CTX), pi).composition_hash
        h_legacy = compose_project_inputs(
            _state(), ModelV2CompositionContext(**_CTX), pi).composition_hash
        assert h_plan != h_legacy

    def test_identity_scenario_changes_hash(self):
        pi = create_generic_solar_reference()
        base = compose_project_inputs(
            _state(), ModelV2CompositionContext(**_CTX), pi).composition_hash
        scoped = compose_project_inputs(
            _state(), ModelV2CompositionContext(
                capacity_mw=64.0, scenario_id="S1",
                scenario_overrides={"capex.C.01.amount_keur": 1.0}), pi)
        assert scoped.composition_hash != base

    def test_identity_cost_template_changes_hash(self):
        pi = create_generic_solar_reference()
        plan_a = _FakeMaterializationPlan(
            capex_fields=(CapexFieldPlan(
                field_name="production_units", parent_code="C.01",
                label="PV", amount_keur=1.0),),
            opex_items=(), template_id="T-A", version=1)
        plan_b = _FakeMaterializationPlan(
            capex_fields=(CapexFieldPlan(
                field_name="production_units", parent_code="C.01",
                label="PV", amount_keur=2.0),),
            opex_items=(), template_id="T-A", version=2)
        ha = compose_project_inputs(
            _state(cost_selection=_cost_selection(plan_a)),
            ModelV2CompositionContext(**_CTX), pi).composition_hash
        hb = compose_project_inputs(
            _state(cost_selection=_cost_selection(plan_b)),
            ModelV2CompositionContext(**_CTX), pi).composition_hash
        assert ha != hb


# ---------------------------------------------------------------------------
# SCENARIO ISOLATION + FAIL-CLOSED
# ---------------------------------------------------------------------------

class TestScenarioIsolation:
    def test_scenario_overrides_never_mutate_base_state_or_inputs(self):
        """MODEL_V2_COMPOSITION_SCENARIO_ISOLATION: overrides ride the
        context; the base Working Copy state and the base inputs are
        unchanged after a scenario composition."""
        pi = create_generic_solar_reference()
        state = _state()
        ctx = ModelV2CompositionContext(
            capacity_mw=64.0, scenario_id="S1",
            scenario_overrides={"capex.C.01.amount_keur": 5000.0})
        result = compose_project_inputs(state, ctx, pi)
        # base untouched
        assert pi.capex.production_units.amount_keur == 3000.0  # base value
        assert state.revenue_plan_selection is None
        assert state.cost_template_selection is None
        # the scenario context is recorded in the result provenance
        layers = {d.layer for d in result.diagnostics}
        assert "scenario" in layers


class TestFailClosed:
    def test_empty_working_copy_ref_fails(self):
        with pytest.raises(ValueError, match="WORKING_STATE_INVALID"):
            compose_project_inputs(
                ModelV2WorkingState(working_copy_ref="  "),
                ModelV2CompositionContext(**_CTX),
                create_generic_solar_reference())

    def test_none_plan_selection_fails(self):
        with pytest.raises(ValueError, match="REVENUE_PLAN_SELECTION_INVALID"):
            RevenuePlanSelection(plan=None)

    def test_cost_template_none_plan_fails(self):
        with pytest.raises(ValueError, match="COST_TEMPLATE_SELECTION_INVALID"):
            CostTemplateSelection(template_id="T", version=1,
                                  materialization_plan=None)

    def test_cost_template_bad_version_fails(self):
        with pytest.raises(ValueError, match="COST_TEMPLATE_SELECTION_INVALID"):
            CostTemplateSelection(template_id="T", version=0,
                                  materialization_plan=object())

    def test_context_bad_capacity_fails(self):
        for bad in (0, -1.0, float("nan"), float("inf"), True):
            with pytest.raises(ValueError, match="COMPOSITION_CONTEXT_INVALID"):
                ModelV2CompositionContext(capacity_mw=bad)

    def test_composition_failure_is_typed_and_raised(self):
        """Composition failure raises BEFORE any engine execution — a failed
        composition can never produce a Last Run input."""
        plan = RevenuePlan.create((
            RevenueStream("cfd", RevenueStreamType.CFD, volume_share=1.0,
                          cfd=CfDParams(cfd_enabled=True,
                                        strike_price_eur_mwh=70.0),
                          reference_stream_id="m", term_years=10),
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=65.0)),
        ), market_price=MerchantParams(merchant_enabled=True,
                                       base_price_eur_mwh=65.0))
        error = None
        try:
            compose_project_inputs(
                _state(plan), ModelV2CompositionContext(**_CTX),
                create_generic_solar_reference())
        except RevenuePlanBridgeError as exc:
            error = exc
        assert error is not None
        assert error.code is CompositionErrorCode.REVENUE_PLAN_STREAM_UNSUPPORTED


# ---------------------------------------------------------------------------
# Workflow 04 register integration
# ---------------------------------------------------------------------------

def test_register_integration_accepts_composed_plan():
    """MODEL_V2_REGISTER_INTEGRATION: the Workflow 04 RegisterContext
    accepts the composed RevenuePlan (WORKING_COPY context, never
    RUN_BOUND) and the register builds without recomputing economics."""
    from app.model_v2.assumption_register import (
        AssumptionContextKind, RegisterContext, build_assumption_register,
    )

    pi = create_generic_solar_reference()
    result = compose_project_inputs(
        _state(_plan()), ModelV2CompositionContext(**_CTX), pi)
    context = RegisterContext(
        context_kind=AssumptionContextKind.WORKING_COPY,
        revenue_plan=result.revenue_plan,
        revenue_plan_source_ref="model_v2_composition",
    )
    register = build_assumption_register(result.project_inputs, context)
    assert register is not None
    entries_text = str(register)
    assert "revenue.plan.stream.ppa" in entries_text
