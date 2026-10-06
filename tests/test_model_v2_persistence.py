"""Model V2 Workflow 07 — V2 persistence + typed restore.

Acceptance markers:

  MODEL_V2_PERSISTENCE_LEGACY_ABSENCE   — legacy projects never acquire
                                          invented V2 state (load/save/reopen)
  MODEL_V2_PERSISTENCE_REVENUE_ROUNDTRIP — every Workflow 02 typed
                                          RevenuePlan shape round-trips exactly
  MODEL_V2_PERSISTENCE_COST_ROUNDTRIP   — CostTemplateSelection
                                          (identity + materialization plan)
                                          round-trips exactly
  MODEL_V2_PERSISTENCE_IDENTITY_STABILITY — save → reload → compose yields
                                          the SAME economic composition
                                          identity; economic edits change it;
                                          presentation-only cost metadata
                                          does not
  MODEL_V2_PERSISTENCE_FAIL_CLOSED     — unknown schema/version, invalid
                                          enums, malformed numerics, NaN/Inf,
                                          bool-as-number and missing identity
                                          all fail closed
  MODEL_V2_PERSISTENCE_CANONICAL_BYTES — deterministic serialization:
                                          same state → same bytes regardless
                                          of dict ordering
"""
from __future__ import annotations

import json

import pytest

from app.model_v2.persistence import (
    MODEL_V2_RUN_BINDING_SCHEMA,
    ModelV2RunStaleness,
    MODEL_V2_WORKING_STATE_SCHEMA,
    MODEL_V2_WORKING_STATE_SCHEMA_VERSION,
    ModelV2PersistenceError,
    build_run_binding_payload,
    materialization_plan_from_payload,
    materialization_plan_to_payload,
    plan_from_payload,
    plan_to_payload,
    read_workspace_run_binding,
    resolve_model_v2_staleness,
    validate_run_binding_payload,
    working_state_from_json,
    working_state_from_payload,
    working_state_to_json,
    working_state_to_payload,
)
from app.persistence.db import init_db
from app.persistence.projects_repository import save_project
from app.persistence.workspace_repository import (
    clear_workspace_model_v2_state,
    get_workspace_model_v2_state,
    get_workspace_state,
    save_workspace_state,
    set_workspace_model_v2_state,
)
from app.services.cost_template.materialize import (
    CapexFieldPlan,
    CapexSubLinePlan,
    ContingencyPlan,
    MaterializationPlan,
    OpexItemPlan,
    OpexSubLinePlan,
)
from app.services.model_v2_composition import (
    CostTemplateSelection,
    ModelV2CompositionContext,
    ModelV2WorkingState,
    RevenuePlanSelection,
    compose_project_inputs,
)
from app.services.model_v2_composition.contracts import (
    CompositionStatus,
    economic_cost_payload,
)
from domain.revenue.plan import RevenuePlan, RevenueStream, RevenueStreamType
from domain.revenue.revenue_config import (
    CfDParams,
    FeedInTariffParams,
    MerchantParams,
    PPAParams,
)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _ppa(**over):
    base = dict(
        ppa_enabled=True, ppa_base_price_eur_mwh=57.0, ppa_price_index=0.02,
        ppa_price_floor=40.0, ppa_price_cap=95.0, ppa_term_years=15,
        ppa_volume_share=0.7, ppa_counterparty="Utility Co",
        balancing_cost_pct=0.025, imbalance_penalty_pct=0.01,
        offtaker_credit_rating="BBB", termination_fee_keur=120.0,
    )
    base.update(over)
    return PPAParams(**base)


def _merchant(**over):
    base = dict(
        merchant_enabled=True, market_zone="XB", base_price_eur_mwh=65.0,
        price_escalation_annual=0.02, price_volatility_pct=0.05,
        price_cannibalization_pct=0.01, capture_rate_solar=0.82,
        capture_rate_wind=0.9, capture_rate_bess=1.0, price_scenario="base",
    )
    base.update(over)
    return MerchantParams(**base)


def _fit(**over):
    base = dict(
        fit_enabled=True, fit_type="fixed_fit", fit_price_eur_mwh=70.0,
        fit_term_years=12, fit_index=0.01, fit_scheme="EEG",
        eligible_capacity_mw=20.0, annual_production_cap_mwh=25000.0,
    )
    base.update(over)
    return FeedInTariffParams(**base)


def _cfd(**over):
    base = dict(
        cfd_enabled=True, strike_price_eur_mwh=48.0,
        reference_price_type="day_ahead", cfd_term_years=10,
        cfd_volume_mwh_annual=100000.0, two_way_cfd=True,
        cfd_counterparty="government", cfd_guarantee="state",
    )
    base.update(over)
    return CfDParams(**base)


def _state(plan=None, cost_selection=None, ref="solar-64"):
    return ModelV2WorkingState(
        working_copy_ref=ref,
        revenue_plan_selection=(
            RevenuePlanSelection(plan=plan, source_ref="test-src") if plan else None),
        cost_template_selection=cost_selection,
    )


def _plan_ppa_merchant():
    return RevenuePlan.create((
        RevenueStream("ppa", RevenueStreamType.PPA, volume_share=0.7,
                      ppa=_ppa(), term_years=15, counterparty="Utility Co"),
        RevenueStream("merchant", RevenueStreamType.MERCHANT,
                      volume_share=None, merchant=_merchant()),
    ))


def _cost_plan(**contingency_over):
    contingency = None
    if contingency_over.get("present", True):
        contingency = ContingencyPlan(
            capex_pct=contingency_over.get("capex_pct", 6.0),
            opex_pct=contingency_over.get("opex_pct", 3.0),
            eligible_capex_basis_keur=contingency_over.get("basis", 80000.0),
            lineage={"source": "cost_template", "template_id": "T-COST",
                     "template_version": 3},
            capex_active=contingency_over.get("capex_active", True),
            opex_active=contingency_over.get("opex_active", True),
        )
    return MaterializationPlan(
        template_id="T-COST",
        template_version=3,
        capex_fields=(
            CapexFieldPlan(
                field_name="development_cost", parent_code="C.01",
                label="Development", amount_keur=1500.0, y0_share=1.0,
                spending_profile=(0.6, 0.4), asset_class="intangible",
                useful_life_override=None, is_depreciable=True, is_active=True),
            CapexFieldPlan(
                field_name="grid_connection", parent_code="C.04",
                label="Grid", amount_keur=9000.0, y0_share=1.0,
                spending_profile=(), asset_class=None,
                useful_life_override=25, is_depreciable=True,
                is_active=contingency_over.get("capex_active", True)),
            CapexFieldPlan(
                field_name="audit_legal", parent_code="C.08",
                label="Audit & Legal (latent)", amount_keur=420.0,
                y0_share=1.0, spending_profile=(), asset_class=None,
                useful_life_override=None, is_depreciable=True,
                is_active=False),
        ),
        capex_sub_lines=(
            CapexSubLinePlan(
                parent_category_code="C.04", business_code="C.04.U001",
                label="Substation child", amount_keur=6000.0,
                schedule_json='{"profile":[0.5,0.5]}', source="user",
                replay_metadata={"cost_template_id": "T-COST",
                                 "cost_template_version": 3,
                                 "template_derived": True},
                scalar_metadata={"vat_pct": 19.0},
                is_active=True),
        ),
        opex_items=(
            OpexItemPlan(
                parent_code="B.01", name="O&M", y1_amount_keur=180.0,
                annual_inflation=0.02,
                step_changes=((5, 30.0), (10, 55.5)),
                percentage_of_opex=0.0, is_active=True),
            OpexItemPlan(
                parent_code="B.07", name="Insurance (latent)",
                y1_amount_keur=95.0, annual_inflation=0.015,
                step_changes=(), percentage_of_opex=0.0, is_active=False),
            OpexItemPlan(
                parent_code="B.13", name="Contingency OPEX",
                y1_amount_keur=0.0, annual_inflation=0.0, step_changes=(),
                percentage_of_opex=0.03, is_active=True),
        ),
        opex_sub_lines=(
            OpexSubLinePlan(
                parent_group_code="B.01", business_code="B.01.U001",
                label="Technician child", amount_keur=120.0,
                inflation_pct=2.0, source="user",
                replay_metadata={"cost_template_id": "T-COST"},
                is_active=True),
        ),
        contingency=contingency,
    )


def _cost_selection(**over):
    return CostTemplateSelection(
        template_id="T-COST", version=3,
        materialization_plan=_cost_plan(**over), source_ref="cost-src")


def _canonical_plan_eq(a: RevenuePlan, b: RevenuePlan) -> bool:
    """Economic plan equality in the canonical (stream-id-sorted) order the
    Workflow 02/05 identity authorities use."""
    return (
        a.ordered_streams() == b.ordered_streams()
        and a.allocation_groups == b.allocation_groups
        and a.market_price == b.market_price
    )


def _assert_state_round_trips(state: ModelV2WorkingState) -> ModelV2WorkingState:
    payload = working_state_to_payload(state)
    restored = working_state_from_payload(payload)
    assert restored.working_copy_ref == state.working_copy_ref
    assert restored.schema == state.schema
    if state.revenue_plan_selection is None:
        assert restored.revenue_plan_selection is None
    else:
        assert restored.revenue_plan_selection.source_ref == \
            state.revenue_plan_selection.source_ref
        assert restored.revenue_plan_selection.scenario_id == \
            state.revenue_plan_selection.scenario_id
        assert _canonical_plan_eq(
            restored.revenue_plan_selection.plan,
            state.revenue_plan_selection.plan)
    if state.cost_template_selection is None:
        assert restored.cost_template_selection is None
    else:
        assert restored.cost_template_selection.template_id == \
            state.cost_template_selection.template_id
        assert restored.cost_template_selection.version == \
            state.cost_template_selection.version
        assert restored.cost_template_selection.materialization_plan == \
            state.cost_template_selection.materialization_plan
        assert restored.cost_template_selection.source_ref == \
            state.cost_template_selection.source_ref
    # selection digest is the canonical economic identity — it must survive
    assert restored.selection_digest() == state.selection_digest()
    # serialization is idempotent: re-encoding the restored state yields
    # the exact same bytes
    assert working_state_to_json(restored) == working_state_to_json(state)
    return restored


# ---------------------------------------------------------------------------
# EMPTY / LEGACY
# ---------------------------------------------------------------------------


class TestLegacyAbsence:
    def test_empty_payload_is_absence_never_invented_state(self):
        assert working_state_from_json(None) is None
        assert working_state_from_json("") is None
        assert working_state_from_json("   ") is None

    def test_state_without_selections_serializes_explicit_absence(self):
        payload = working_state_to_payload(_state())
        assert payload["revenue_plan_selection"] is None
        assert payload["cost_template_selection"] is None
        restored = working_state_from_payload(payload)
        assert restored.revenue_plan_selection is None
        assert restored.cost_template_selection is None
        assert restored.selection_digest() == _state().selection_digest()


class TestLegacyProjectPersistence:
    @pytest.fixture()
    def db_path(self, tmp_path, monkeypatch):
        from app.persistence import db
        path = str(tmp_path / "legacy.db")
        monkeypatch.setattr(db, "DB_PATH", path)
        init_db()
        return path

    def test_legacy_workspace_has_no_v2_state_through_save_reload(self, db_path):
        rec = save_project(user_id="legacy-u", project_code="old-farm",
                           project_name="Old Farm",
                           source_project_template="generic_solar_reference")
        save_workspace_state(
            user_id="legacy-u", project_id=rec.project_id,
            project_code="old-farm",
            draft_snapshot={"active_project": "old-farm"},
            saved_snapshot={"active_project": "old-farm"})

        ws = get_workspace_state("legacy-u", rec.project_id)
        assert ws.model_v2_working_state_json == ""
        assert get_workspace_model_v2_state("legacy-u", rec.project_id) is None

        # a legacy save/re-save never materializes V2 selections
        save_workspace_state(
            user_id="legacy-u", project_id=rec.project_id,
            project_code="old-farm",
            draft_snapshot={"active_project": "old-farm", "capacity_mw": "42"},
            saved_snapshot={"active_project": "old-farm", "capacity_mw": "42"})
        ws = get_workspace_state("legacy-u", rec.project_id)
        assert ws.model_v2_working_state_json == ""
        assert get_workspace_model_v2_state("legacy-u", rec.project_id) is None

    def test_v2_state_survives_unrelated_legacy_saves(self, db_path):
        rec = save_project(user_id="legacy-u", project_code="mix-farm",
                           project_name="Mix Farm",
                           source_project_template="generic_solar_reference")
        save_workspace_state(
            user_id="legacy-u", project_id=rec.project_id,
            project_code="mix-farm", draft_snapshot={}, saved_snapshot={})
        set_workspace_model_v2_state(
            user_id="legacy-u", project_id=rec.project_id,
            state=_state(_plan_ppa_merchant(), ref="mix-farm"))
        # legacy-shape save (no V2 argument) must merge-preserve the payload
        save_workspace_state(
            user_id="legacy-u", project_id=rec.project_id,
            project_code="mix-farm",
            draft_snapshot={"capacity_mw": "64"}, saved_snapshot={})
        loaded = get_workspace_model_v2_state("legacy-u", rec.project_id)
        assert loaded is not None
        assert loaded.selection_digest() == \
            _state(_plan_ppa_merchant(), ref="mix-farm").selection_digest()

    def test_working_copy_ref_binding_enforced_on_write_and_read(self, db_path):
        rec = save_project(user_id="legacy-u", project_code="bound-farm",
                           project_name="Bound Farm",
                           source_project_template="generic_solar_reference")
        save_workspace_state(
            user_id="legacy-u", project_id=rec.project_id,
            project_code="bound-farm", draft_snapshot={}, saved_snapshot={})
        foreign = _state(_plan_ppa_merchant(), ref="another-project")
        with pytest.raises(ModelV2PersistenceError, match="WORKING_COPY_REF_MISMATCH"):
            set_workspace_model_v2_state(
                user_id="legacy-u", project_id=rec.project_id, state=foreign)
        # no partial write happened
        assert get_workspace_model_v2_state("legacy-u", rec.project_id) is None

    def test_clear_returns_to_exact_legacy_absence(self, db_path):
        rec = save_project(user_id="legacy-u", project_code="clear-farm",
                           project_name="Clear Farm",
                           source_project_template="generic_solar_reference")
        save_workspace_state(
            user_id="legacy-u", project_id=rec.project_id,
            project_code="clear-farm", draft_snapshot={"k": 1}, saved_snapshot={})
        set_workspace_model_v2_state(
            user_id="legacy-u", project_id=rec.project_id,
            state=_state(_plan_ppa_merchant(), ref="clear-farm"))
        cleared = clear_workspace_model_v2_state(
            user_id="legacy-u", project_id=rec.project_id)
        assert cleared.model_v2_working_state_json == ""
        assert cleared.draft_snapshot == {"k": 1}
        assert get_workspace_model_v2_state("legacy-u", rec.project_id) is None


# ---------------------------------------------------------------------------
# REVENUE round-trips
# ---------------------------------------------------------------------------


class TestRevenuePlanRoundTrip:
    def test_ppa_plan_round_trips(self):
        plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=0.7,
                          ppa=_ppa(), term_years=15),
        ))
        _assert_state_round_trips(_state(plan))

    def test_merchant_plan_round_trips(self):
        plan = RevenuePlan.create((
            RevenueStream("merchant", RevenueStreamType.MERCHANT,
                          volume_share=None, merchant=_merchant()),
        ))
        _assert_state_round_trips(_state(plan))

    def test_multi_stream_plan_round_trips(self):
        _assert_state_round_trips(_state(_plan_ppa_merchant()))

    def test_cfd_overlay_plan_round_trips(self):
        plan = RevenuePlan.create((
            RevenueStream("merchant", RevenueStreamType.MERCHANT,
                          volume_share=None, merchant=_merchant()),
            RevenueStream("cfd", RevenueStreamType.CFD, volume_share=0.5,
                          cfd=_cfd(), reference_stream_id="merchant",
                          start_year=2, term_years=10),
        ))
        restored = _assert_state_round_trips(_state(plan))
        stream = restored.revenue_plan_selection.plan.stream_by_id("cfd")
        assert stream.cfd == _cfd()
        assert stream.reference_stream_id == "merchant"
        assert stream.is_active(1) is False
        assert stream.is_active(2) is True
        assert stream.is_active(11) is True   # start + term - 1 = 11
        assert stream.is_active(12) is False

    def test_fit_variants_round_trip(self):
        fixed = RevenuePlan.create((
            RevenueStream("fit", RevenueStreamType.FIT_FIXED,
                          volume_share=1.0, fit=_fit(), term_years=12),
        ))
        _assert_state_round_trips(_state(fixed))
        premium = RevenuePlan.create((
            RevenueStream("merchant", RevenueStreamType.MERCHANT,
                          volume_share=None, merchant=_merchant()),
            RevenueStream("prem", RevenueStreamType.FIT_PREMIUM,
                          volume_share=1.0,
                          fit=_fit(fit_type="premium", premium_eur_mwh=12.0,
                                   premium_cap_eur_mwh=200.0,
                                   premium_floor_eur_mwh=5.0),
                          reference_stream_id="merchant"),
        ))
        _assert_state_round_trips(_state(premium))
        indexed = RevenuePlan.create((
            RevenueStream("idx", RevenueStreamType.INDEXED_FIT,
                          volume_share=1.0,
                          indexed_fit_base_tariff_eur_mwh=68.5,
                          indexed_fit_index_factors=(1.0, 1.05, 1.1025),
                          term_years=3),
        ))
        restored = _assert_state_round_trips(_state(indexed))
        stream = restored.revenue_plan_selection.plan.stream_by_id("idx")
        assert stream.indexed_fit_index_factors == (1.0, 1.05, 1.1025)
        auction = RevenuePlan.create((
            RevenueStream("awd", RevenueStreamType.AUCTION_AWARDED_TARIFF,
                          volume_share=0.8, fit=_fit(fit_price_eur_mwh=61.4),
                          term_years=20),
        ))
        _assert_state_round_trips(_state(auction))

    def test_explicit_zero_survives(self):
        plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=0.7,
                          ppa=_ppa(ppa_price_floor=0.0, ppa_price_cap=0.0,
                                   termination_fee_keur=0.0,
                                   ppa_price_index=0.0),
                          term_years=15),
        ))
        payload = working_state_to_payload(_state(plan))
        ppa_payload = _stream_payload(payload, "ppa")["ppa"]
        assert ppa_payload["ppa_price_floor"] == 0.0
        assert ppa_payload["ppa_price_floor"] is not None
        restored = working_state_from_payload(payload)
        r_stream = restored.revenue_plan_selection.plan.stream_by_id("ppa")
        assert r_stream.ppa.ppa_price_floor == 0.0
        assert r_stream.ppa.termination_fee_keur == 0.0

    def test_none_volume_share_survives_as_residual(self):
        plan = _plan_ppa_merchant()
        restored = _assert_state_round_trips(_state(plan))
        merchant = restored.revenue_plan_selection.plan.stream_by_id("merchant")
        assert merchant.volume_share is None
        assert merchant.contract_role.value == "primary_allocation"

    def test_disabled_stream_survives(self):
        plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=0.7,
                          ppa=_ppa(), term_years=15),
            RevenueStream("ppa-old", RevenueStreamType.PPA, volume_share=0.5,
                          ppa=_ppa(ppa_base_price_eur_mwh=44.0),
                          term_years=15, enabled=False, start_year=1),
        ))
        restored = _assert_state_round_trips(_state(plan))
        disabled = restored.revenue_plan_selection.plan.stream_by_id("ppa-old")
        assert disabled.enabled is False
        assert disabled.is_active(3) is False
        # latent economics retained
        assert disabled.ppa.ppa_base_price_eur_mwh == 44.0

    def test_lifecycle_survives(self):
        plan = RevenuePlan.create((
            RevenueStream("delayed", RevenueStreamType.FIT_FIXED,
                          volume_share=1.0, fit=_fit(), start_year=3,
                          term_years=4.5),
        ))
        restored = _assert_state_round_trips(_state(plan))
        stream = restored.revenue_plan_selection.plan.stream_by_id("delayed")
        assert stream.start_year == 3
        assert stream.term_years == 4.5
        assert stream.is_active(2) is False
        assert stream.is_active(3) is True
        assert stream.is_active(6) is True   # start + term - 1 = 6.5
        assert stream.is_active(7) is False

    def test_unlimited_term_none_is_distinct_from_zero(self):
        plan = RevenuePlan.create((
            RevenueStream("forever", RevenueStreamType.PPA, volume_share=1.0,
                          ppa=_ppa(), term_years=None),
        ))
        restored = _assert_state_round_trips(_state(plan))
        stream = restored.revenue_plan_selection.plan.stream_by_id("forever")
        assert stream.term_years is None
        assert stream.end_year is None
        assert stream.is_active(999) is True


# ---------------------------------------------------------------------------
# COST round-trips
# ---------------------------------------------------------------------------


class TestCostTemplateSelectionRoundTrip:
    def test_template_identity_and_version_round_trip(self):
        restored = _assert_state_round_trips(_state(cost_selection=_cost_selection()))
        assert restored.cost_template_selection.template_id == "T-COST"
        assert restored.cost_template_selection.version == 3

    def test_active_capex_fields_round_trip(self):
        plan = _cost_selection().materialization_plan
        restored = _assert_state_round_trips(_state(cost_selection=_cost_selection()))
        r_plan = restored.cost_template_selection.materialization_plan
        assert r_plan.capex_fields[0].spending_profile == (0.6, 0.4)
        assert r_plan.capex_fields[1].useful_life_override == 25
        assert r_plan.capex_fields[1].asset_class is None
        assert r_plan.capex_fields == plan.capex_fields

    def test_inactive_capex_latent_value_survives(self):
        restored = _assert_state_round_trips(_state(cost_selection=_cost_selection()))
        latent = next(f for f in restored.cost_template_selection
                      .materialization_plan.capex_fields
                      if f.field_name == "audit_legal")
        assert latent.is_active is False
        assert latent.amount_keur == 420.0  # latent value retained, not zeroed

    def test_opex_inflation_and_step_changes_round_trip(self):
        restored = _assert_state_round_trips(_state(cost_selection=_cost_selection()))
        om = next(o for o in restored.cost_template_selection
                  .materialization_plan.opex_items if o.name == "O&M")
        assert om.annual_inflation == 0.02
        assert om.step_changes == ((5, 30.0), (10, 55.5))
        assert isinstance(om.step_changes[0], tuple)
        assert om.step_changes[0][0] == 5

    def test_inactive_opex_survives(self):
        restored = _assert_state_round_trips(_state(cost_selection=_cost_selection()))
        latent = next(o for o in restored.cost_template_selection
                      .materialization_plan.opex_items
                      if o.name == "Insurance (latent)")
        assert latent.is_active is False
        assert latent.y1_amount_keur == 95.0

    def test_percentage_of_opex_round_trip(self):
        restored = _assert_state_round_trips(_state(cost_selection=_cost_selection()))
        cont = next(o for o in restored.cost_template_selection
                    .materialization_plan.opex_items if o.name == "Contingency OPEX")
        assert cont.percentage_of_opex == 0.03  # fraction preserved (not 3.0)

    def test_contingency_active_and_inactive_round_trip(self):
        active = _assert_state_round_trips(
            _state(cost_selection=_cost_selection()))
        contingency = active.cost_template_selection.materialization_plan.contingency
        assert contingency.capex_pct == 6.0
        assert contingency.capex_active is True
        assert contingency.opex_active is True
        assert contingency.lineage == {"source": "cost_template",
                                       "template_id": "T-COST",
                                       "template_version": 3}

        inactive = _assert_state_round_trips(_state(cost_selection=_cost_selection(
            capex_active=False, opex_active=False)))
        contingency = inactive.cost_template_selection.materialization_plan.contingency
        # INACTIVE retains the configured percentage — distinct from 0.0
        assert contingency.capex_pct == 6.0
        assert contingency.capex_active is False
        assert contingency.opex_active is False

    def test_explicit_zero_pct_contingency_survives_as_zero(self):
        restored = _assert_state_round_trips(_state(cost_selection=_cost_selection(
            capex_pct=0.0, opex_pct=0.0)))
        contingency = restored.cost_template_selection.materialization_plan.contingency
        assert contingency.capex_pct == 0.0
        assert contingency.capex_pct is not None  # 0% is legitimate ZERO, not MISSING
        assert contingency.opex_pct == 0.0

    def test_absent_contingency_stays_absent(self):
        restored = _assert_state_round_trips(_state(cost_selection=_cost_selection(
            present=False)))
        assert restored.cost_template_selection.materialization_plan.contingency is None

    def test_sub_line_plans_and_metadata_round_trip(self):
        restored = _assert_state_round_trips(_state(cost_selection=_cost_selection()))
        plan = restored.cost_template_selection.materialization_plan
        sub = plan.capex_sub_lines[0]
        assert sub.schedule_json == '{"profile":[0.5,0.5]}'  # carried verbatim
        assert sub.replay_metadata["cost_template_id"] == "T-COST"
        assert sub.scalar_metadata == {"vat_pct": 19.0}
        osub = plan.opex_sub_lines[0]
        assert osub.inflation_pct == 2.0  # persistence percent unit preserved

    def test_real_template_materialization_round_trips(self):
        """Integration: a plan produced by the real Workflow 03 authority
        (resolve + build) round-trips through persistence."""
        from app.services.cost_template.generic import build_generic_cost_template
        from app.services.cost_template.materialize import (
            MaterializationContext,
            build_materialization_plan,
            resolve_cost_template,
        )

        template = build_generic_cost_template("generic_solar_reference")
        resolved = resolve_cost_template(
            template, MaterializationContext(capacity_mw=64.0))
        real_plan = build_materialization_plan(resolved)
        selection = CostTemplateSelection(
            template_id=template.template_id, version=template.version,
            materialization_plan=real_plan, source_ref="generic")
        restored = _assert_state_round_trips(_state(cost_selection=selection))
        assert restored.cost_template_selection.materialization_plan == real_plan
        assert economic_cost_payload(restored.cost_template_selection) == \
            economic_cost_payload(selection)


# ---------------------------------------------------------------------------
# IDENTITY
# ---------------------------------------------------------------------------


class TestIdentityStability:
    def test_no_op_round_trip_preserves_composition_hash(self):
        from app.project_factories import create_generic_solar_reference
        from app.services.cost_template.generic import build_generic_cost_template
        from app.services.cost_template.materialize import (
            MaterializationContext, build_materialization_plan,
            resolve_cost_template)

        template = build_generic_cost_template("generic_solar_reference")
        real_plan = build_materialization_plan(resolve_cost_template(
            template, MaterializationContext(capacity_mw=64.0)))
        real_selection = CostTemplateSelection(
            template_id=template.template_id, version=template.version,
            materialization_plan=real_plan, source_ref="generic")

        state = _state(_plan_ppa_merchant(), cost_selection=real_selection)
        context = ModelV2CompositionContext(capacity_mw=64.0)
        base = create_generic_solar_reference()
        before = compose_project_inputs(state, context, base)

        restored = working_state_from_json(working_state_to_json(state))
        after = compose_project_inputs(restored, context, base)

        assert before.composition_hash == after.composition_hash
        assert before.status is CompositionStatus.COMPOSED
        assert after.status is CompositionStatus.COMPOSED

    def test_economic_edit_changes_identity(self):
        state = _state(_plan_ppa_merchant())
        edited_plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=0.7,
                          ppa=_ppa(ppa_base_price_eur_mwh=58.0), term_years=15),
            RevenueStream("merchant", RevenueStreamType.MERCHANT,
                          volume_share=None, merchant=_merchant()),
        ))
        edited = _state(edited_plan)
        assert edited.selection_digest() != state.selection_digest()

    def test_cost_presentation_label_edit_does_not_change_identity(self):
        """Cost labels are excluded by the canonical economic cost payload —
        a presentation-only relabel must not change the economic identity."""
        selection = _cost_selection()
        relabeled_plan = _cost_plan()
        relabeled_capex = list(relabeled_plan.capex_fields)
        relabeled_capex[0] = CapexFieldPlan(
            field_name=relabeled_capex[0].field_name,
            parent_code=relabeled_capex[0].parent_code,
            label="Development (renamed presentation only)",
            amount_keur=relabeled_capex[0].amount_keur,
            y0_share=relabeled_capex[0].y0_share,
            spending_profile=relabeled_capex[0].spending_profile,
            asset_class=relabeled_capex[0].asset_class,
            useful_life_override=relabeled_capex[0].useful_life_override,
            is_depreciable=relabeled_capex[0].is_depreciable,
            is_active=relabeled_capex[0].is_active,
        )
        relabeled_plan = MaterializationPlan(
            template_id=relabeled_plan.template_id,
            template_version=relabeled_plan.template_version,
            capex_fields=tuple(relabeled_capex),
            capex_sub_lines=relabeled_plan.capex_sub_lines,
            opex_items=relabeled_plan.opex_items,
            opex_sub_lines=relabeled_plan.opex_sub_lines,
            contingency=relabeled_plan.contingency,
        )
        relabeled = CostTemplateSelection(
            template_id="T-COST", version=3, materialization_plan=relabeled_plan,
            source_ref="cost-src")
        assert economic_cost_payload(relabeled) == economic_cost_payload(selection)
        assert _state(cost_selection=relabeled).selection_digest() == \
            _state(cost_selection=selection).selection_digest()

    def test_declaration_order_does_not_change_identity_or_bytes(self):
        plan = _plan_ppa_merchant()
        reordered = RevenuePlan.create(
            tuple(reversed(plan.streams)))
        a = working_state_to_json(_state(plan))
        b = working_state_to_json(_state(reordered))
        assert a == b


# ---------------------------------------------------------------------------
# MALFORMED — fail closed
# ---------------------------------------------------------------------------


def _stream_payload(payload: dict, stream_id: str) -> dict:
    for stream in payload["revenue_plan_selection"]["plan"]["streams"]:
        if stream["stream_id"] == stream_id:
            return stream
    raise AssertionError(f"stream {stream_id!r} not found in payload")


def _valid_payload() -> dict:
    return working_state_to_payload(_state(_plan_ppa_merchant()))


class TestFailClosed:
    def test_unknown_schema_fails_closed(self):
        payload = _valid_payload()
        payload["_schema"] = "finco.model-v2.working-state-99"
        with pytest.raises(ModelV2PersistenceError, match="UNKNOWN_SCHEMA"):
            working_state_from_payload(payload)

    def test_future_schema_version_fails_closed(self):
        payload = _valid_payload()
        payload["schema_version"] = MODEL_V2_WORKING_STATE_SCHEMA_VERSION + 1
        with pytest.raises(ModelV2PersistenceError, match="UNSUPPORTED_VERSION"):
            working_state_from_payload(payload)

    def test_unknown_top_level_key_fails_closed(self):
        payload = _valid_payload()
        payload["unexpected_future_field"] = {"economic": 1}
        with pytest.raises(ModelV2PersistenceError, match="unsupported key"):
            working_state_from_payload(payload)

    def test_unknown_nested_key_fails_closed(self):
        payload = _valid_payload()
        payload["revenue_plan_selection"]["plan"]["streams"][0][
            "new_economic_field"] = 1.0
        with pytest.raises(ModelV2PersistenceError, match="unsupported key"):
            working_state_from_payload(payload)

    def test_invalid_enum_fails_closed(self):
        payload = _valid_payload()
        for stream in payload["revenue_plan_selection"]["plan"]["streams"]:
            stream["stream_type"] = "crypto_miner"
        with pytest.raises(ModelV2PersistenceError, match="stream_type"):
            working_state_from_payload(payload)

    def test_malformed_numeric_fails_closed(self):
        payload = _valid_payload()
        _stream_payload(payload, "ppa")["ppa"]["ppa_base_price_eur_mwh"] = "fifty-seven"
        with pytest.raises(ModelV2PersistenceError, match="ppa_base_price_eur_mwh"):
            working_state_from_payload(payload)

    def test_nan_and_inf_fail_closed(self):
        raw = working_state_to_json(_state(_plan_ppa_merchant()))
        assert raw.find("57.0") >= 0
        field_idx = raw.index("ppa_base_price_eur_mwh")
        for bad in ("NaN", "Infinity", "-Infinity"):
            corrupted = raw[:field_idx] +                 raw[field_idx:].replace("57.0", bad, 1)
            with pytest.raises(ModelV2PersistenceError):
                working_state_from_json(corrupted)

    def test_bool_as_number_fails_closed(self):
        payload = _valid_payload()
        _stream_payload(payload, "ppa")["ppa"]["ppa_base_price_eur_mwh"] = True
        with pytest.raises(ModelV2PersistenceError, match="ppa_base_price_eur_mwh"):
            working_state_from_payload(payload)

    def test_bool_as_int_year_fails_closed(self):
        payload = _valid_payload()
        _stream_payload(payload, "ppa")["start_year"] = True
        with pytest.raises(ModelV2PersistenceError, match="start_year"):
            working_state_from_payload(payload)

    def test_missing_required_identity_fails_closed(self):
        payload = _valid_payload()
        del payload["cost_template_selection"]
        with pytest.raises(ModelV2PersistenceError, match="missing required"):
            working_state_from_payload(payload)

        payload = _valid_payload()
        del payload["working_copy_ref"]
        with pytest.raises(ModelV2PersistenceError):
            working_state_from_payload(payload)

    def test_empty_template_id_fails_closed(self):
        payload = _valid_payload()
        payload["cost_template_selection"] = {
            "template_id": "", "version": 1, "source_ref": "",
            "materialization_plan": materialization_plan_to_payload(_cost_plan()),
        }
        with pytest.raises(ValueError):
            working_state_from_payload(payload)

    def test_missing_materialization_key_fails_closed(self):
        payload = materialization_plan_to_payload(_cost_plan())
        del payload["capex_fields"]
        with pytest.raises(ModelV2PersistenceError, match="missing required"):
            materialization_plan_from_payload(payload)

    def test_corrupted_json_fails_closed(self):
        with pytest.raises(ModelV2PersistenceError, match="not valid JSON"):
            working_state_from_json('{"_schema": "finco.model-v2.working-state",')

    def test_economically_invalid_plan_fails_closed_on_restore(self):
        """A payload whose decoded plan no longer satisfies the domain
        contract fails closed (domain validation re-runs on restore)."""
        payload = _valid_payload()
        streams = payload["revenue_plan_selection"]["plan"]["streams"]
        # give the merchant an explicit zero share -> non-merchant residual
        # rule violation is avoided; instead duplicate a share overlap > 1.0
        payload["revenue_plan_selection"]["plan"]["streams"] = [
            streams[0],
            dict(streams[0], stream_id="ppa-clone"),
        ]
        with pytest.raises(ValueError):
            working_state_from_payload(payload)


    def test_numeric_string_curve_fails_closed(self):
        """A numeric STRING must never masquerade as economics: float()
        coercion downstream would accept it and flip the canonical
        identity."""
        payload = _valid_payload()
        merchant = None
        for stream in payload["revenue_plan_selection"]["plan"]["streams"]:
            if stream["stream_id"] == "merchant":
                merchant = stream
        merchant["merchant"]["custom_price_curve"] = ["70", "71"]
        with pytest.raises(ModelV2PersistenceError, match="custom_price_curve"):
            working_state_from_payload(payload)

    def test_allocation_group_extra_key_fails_closed(self):
        payload = _valid_payload()
        payload["revenue_plan_selection"]["plan"]["allocation_groups"] = [
            {"group_id": "generation", "description": "", "share": 1.0}]
        with pytest.raises(ModelV2PersistenceError, match="unsupported key"):
            working_state_from_payload(payload)

    def test_malformed_step_pair_fails_closed_typed(self):
        payload = materialization_plan_to_payload(_cost_plan())
        payload["opex_items"][0]["step_changes"] = [[5]]
        with pytest.raises(ModelV2PersistenceError, match="step_changes"):
            materialization_plan_from_payload(payload)

    def test_encode_rejects_float_useful_life(self):
        """Encode-side strictness mirrors the decoder: a plan carrying a
        float useful-life can never be persisted (it would be permanently
        unreadable)."""
        bad = _cost_plan()
        field = bad.capex_fields[1]
        bad_field = CapexFieldPlan(
            field_name=field.field_name, parent_code=field.parent_code,
            label=field.label, amount_keur=field.amount_keur,
            y0_share=field.y0_share, spending_profile=field.spending_profile,
            asset_class=field.asset_class, useful_life_override=25.5,
            is_depreciable=field.is_depreciable, is_active=field.is_active)
        bad = MaterializationPlan(
            template_id=bad.template_id, template_version=bad.template_version,
            capex_fields=(bad_field,), capex_sub_lines=bad.capex_sub_lines,
            opex_items=bad.opex_items, opex_sub_lines=bad.opex_sub_lines,
            contingency=bad.contingency)
        with pytest.raises(ModelV2PersistenceError, match="useful_life_override"):
            materialization_plan_to_payload(bad)

    def test_non_json_native_object_fails_closed_on_encode(self):
        class NotSerializable:
            pass

        # Metadata dicts are not domain-validated — a non-JSON-native object
        # must fail closed on encode (no pickle, no arbitrary Python
        # object representations).
        bad_plan = _cost_plan()
        bad_sub_line = CapexSubLinePlan(
            parent_category_code="C.04", business_code="C.04.U999",
            label="bad", amount_keur=1.0,
            scalar_metadata={"blob": NotSerializable()})
        bad_plan = MaterializationPlan(
            template_id=bad_plan.template_id,
            template_version=bad_plan.template_version,
            capex_fields=bad_plan.capex_fields,
            capex_sub_lines=bad_plan.capex_sub_lines + (bad_sub_line,),
            opex_items=bad_plan.opex_items,
            opex_sub_lines=bad_plan.opex_sub_lines,
            contingency=bad_plan.contingency)
        with pytest.raises(ModelV2PersistenceError, match="JSON-native"):
            working_state_to_json(_state(
                cost_selection=CostTemplateSelection(
                    template_id="T-COST", version=3,
                    materialization_plan=bad_plan, source_ref="x")))


# ---------------------------------------------------------------------------
# DETERMINISTIC SERIALIZATION
# ---------------------------------------------------------------------------


class TestDeterministicSerialization:
    def test_same_state_same_bytes(self):
        a = working_state_to_json(_state(_plan_ppa_merchant(), _cost_selection()))
        b = working_state_to_json(_state(_plan_ppa_merchant(), _cost_selection()))
        assert a == b

    def test_decoded_dict_key_order_does_not_matter(self):
        payload = _valid_payload()
        reordered = {k: payload[k] for k in reversed(list(payload.keys()))}
        restored_a = working_state_from_payload(payload)
        restored_b = working_state_from_payload(reordered)
        assert restored_a.selection_digest() == restored_b.selection_digest()
        assert working_state_to_json(restored_a) == working_state_to_json(restored_b)

    def test_non_finite_in_metadata_fails_closed_on_encode(self):
        """NaN cannot enter domain-validated plan economics (validators
        reject it), but free-form metadata dicts are not domain-validated —
        the canonical encoder is the final guard there."""
        nan_plan = _cost_plan()
        nan_sub_line = CapexSubLinePlan(
            parent_category_code="C.04", business_code="C.04.U998",
            label="nan", amount_keur=1.0,
            scalar_metadata={"vat_pct": float("nan")})
        nan_plan = MaterializationPlan(
            template_id=nan_plan.template_id,
            template_version=nan_plan.template_version,
            capex_fields=nan_plan.capex_fields,
            capex_sub_lines=nan_plan.capex_sub_lines + (nan_sub_line,),
            opex_items=nan_plan.opex_items,
            opex_sub_lines=nan_plan.opex_sub_lines,
            contingency=nan_plan.contingency)
        with pytest.raises(ModelV2PersistenceError, match="canonically"):
            working_state_to_json(_state(
                cost_selection=CostTemplateSelection(
                    template_id="T-COST", version=3,
                    materialization_plan=nan_plan, source_ref="x")))


# ---------------------------------------------------------------------------
# RUN BINDING payload validation
# ---------------------------------------------------------------------------


class TestRunBindingPayload:
    def test_build_and_validate_round_trip(self):
        state = _state(_plan_ppa_merchant())
        payload = build_run_binding_payload(
            state=state, composition_hash="a" * 64, snapshot_id="snap-1",
            scenario_id="sc-7")
        validated = validate_run_binding_payload(payload)
        assert validated["economic_identity"] == state.selection_digest()
        assert validated["scenario_id"] == "sc-7"
        assert validated["_schema"] == MODEL_V2_RUN_BINDING_SCHEMA

    def test_unknown_key_fails_closed(self):
        payload = build_run_binding_payload(
            state=_state(_plan_ppa_merchant()), composition_hash="a" * 64,
            snapshot_id="snap-1")
        payload["tampered"] = 1
        with pytest.raises(ModelV2PersistenceError, match="unsupported key"):
            validate_run_binding_payload(payload)

    def test_non_hex_identity_fails_closed(self):
        payload = build_run_binding_payload(
            state=_state(_plan_ppa_merchant()), composition_hash="a" * 64,
            snapshot_id="snap-1")
        payload["economic_identity"] = "not-a-digest"
        with pytest.raises(ModelV2PersistenceError, match="SHA-256"):
            validate_run_binding_payload(payload)

    def test_scenario_id_type_fails_closed(self):
        payload = build_run_binding_payload(
            state=_state(_plan_ppa_merchant()), composition_hash="a" * 64,
            snapshot_id="snap-1")
        payload["scenario_id"] = {"evil": True}
        with pytest.raises(ModelV2PersistenceError, match="scenario_id"):
            validate_run_binding_payload(payload)

    def test_snapshot_id_required(self):
        payload = build_run_binding_payload(
            state=_state(_plan_ppa_merchant()), composition_hash="a" * 64,
            snapshot_id="snap-1")
        del payload["snapshot_id"]
        with pytest.raises(ModelV2PersistenceError, match="missing required"):
            validate_run_binding_payload(payload)

    def test_future_version_fails_closed(self):
        payload = build_run_binding_payload(
            state=_state(_plan_ppa_merchant()), composition_hash="a" * 64,
            snapshot_id="snap-1")
        payload["schema_version"] = 99
        with pytest.raises(ModelV2PersistenceError, match="UNSUPPORTED_VERSION"):
            validate_run_binding_payload(payload)

    def test_read_workspace_binding_absent_vs_present(self):
        assert read_workspace_run_binding(None) is None
        assert read_workspace_run_binding({}) is None
        assert read_workspace_run_binding({"model_v2": None}) is None
        payload = build_run_binding_payload(
            state=_state(_plan_ppa_merchant()), composition_hash="a" * 64,
            snapshot_id="snap-1")
        assert read_workspace_run_binding({"model_v2": payload}) == payload
        with pytest.raises(ModelV2PersistenceError):
            read_workspace_run_binding({"model_v2": {"broken": True}})


# ---------------------------------------------------------------------------
# STALENESS semantics
# ---------------------------------------------------------------------------


class TestStalenessSemantics:
    def _binding(self, state):
        return build_run_binding_payload(
            state=state, composition_hash="a" * 64, snapshot_id="snap-x",
            scenario_id=None)

    def test_no_binding_is_not_applicable(self):
        result = resolve_model_v2_staleness(
            current_state=_state(_plan_ppa_merchant()), run_binding=None)
        assert result.state is ModelV2RunStaleness.NOT_APPLICABLE
        assert result.is_stale is False

    def test_same_economics_is_current(self):
        state = _state(_plan_ppa_merchant(), _cost_selection())
        result = resolve_model_v2_staleness(
            current_state=state, run_binding=self._binding(state))
        assert result.state.value == "current"
        assert result.bound_scenario_id is None

    def test_removed_selections_are_stale(self):
        state = _state(_plan_ppa_merchant(), _cost_selection())
        result = resolve_model_v2_staleness(
            current_state=None, run_binding=self._binding(state))
        assert result.is_stale
        assert "removed" in result.reason

    def test_economic_edit_is_stale(self):
        state = _state(_plan_ppa_merchant(), _cost_selection())
        edited = _state(
            RevenuePlan.create((
                RevenueStream("ppa", RevenueStreamType.PPA, volume_share=0.7,
                              ppa=_ppa(ppa_term_years=16), term_years=16),
                RevenueStream("merchant", RevenueStreamType.MERCHANT,
                              volume_share=None, merchant=_merchant()),
            )),
            _cost_selection())
        result = resolve_model_v2_staleness(
            current_state=edited, run_binding=self._binding(state))
        assert result.is_stale

    def test_cost_economic_edit_is_stale(self):
        state = _state(cost_selection=_cost_selection(capex_pct=6.0))
        edited = _state(cost_selection=_cost_selection(capex_pct=7.5))
        assert resolve_model_v2_staleness(
            current_state=edited, run_binding=self._binding(state)).is_stale

    def test_cost_contingency_deactivation_is_stale(self):
        state = _state(cost_selection=_cost_selection(capex_active=True))
        edited = _state(cost_selection=_cost_selection(capex_active=False))
        assert resolve_model_v2_staleness(
            current_state=edited, run_binding=self._binding(state)).is_stale

    def test_cost_label_edit_is_not_stale(self):
        state = _state(cost_selection=_cost_selection())
        relabeled_selection = CostTemplateSelection(
            template_id="T-COST", version=3,
            materialization_plan=MaterializationPlan(
                template_id="T-COST", template_version=3,
                capex_fields=tuple(
                    CapexFieldPlan(
                        field_name=f.field_name, parent_code=f.parent_code,
                        label=f"{f.label} (relabeled)",
                        amount_keur=f.amount_keur, y0_share=f.y0_share,
                        spending_profile=f.spending_profile,
                        asset_class=f.asset_class,
                        useful_life_override=f.useful_life_override,
                        is_depreciable=f.is_depreciable, is_active=f.is_active)
                    for f in _cost_plan().capex_fields),
                capex_sub_lines=_cost_plan().capex_sub_lines,
                opex_items=_cost_plan().opex_items,
                opex_sub_lines=_cost_plan().opex_sub_lines,
                contingency=_cost_plan().contingency),
            source_ref="cost-src")
        result = resolve_model_v2_staleness(
            current_state=_state(cost_selection=relabeled_selection),
            run_binding=self._binding(state))
        assert result.state.value == "current"

    def test_scenario_context_distinct_from_base_identity(self):
        """A scenario run binds its scenario id; the base economic identity
        comparison stays scenario-independent."""
        state = _state(_plan_ppa_merchant())
        scenario_binding = build_run_binding_payload(
            state=state, composition_hash="b" * 64, snapshot_id="snap-sc",
            scenario_id="sc-9")
        result = resolve_model_v2_staleness(
            current_state=state, run_binding=scenario_binding)
        assert result.state.value == "current"
        assert result.bound_scenario_id == "sc-9"
