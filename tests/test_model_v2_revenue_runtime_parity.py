"""Model V2 Revenue Runtime Parity (Workflow 05B, Correction A) matrix.

Proves the runtime-parity bridge maps RevenuePlan structures onto the
canonical RevenueParams fields THE PRODUCTION PATH ACTUALLY READS
(from_project_inputs → clean RevenueInput → orchestrator →
revenue_decomposition_schedule) with exact economics, that a selected plan
fully supersedes stale base revenue authority, and that every structure the
production chain cannot express exactly fails closed with a typed seam.

Markers:

  RUNTIME_PARITY_PPA            RUNTIME_PARITY_MERCHANT
  RUNTIME_PARITY_FIT            RUNTIME_PARITY_INDEXED_FIT
  RUNTIME_PARITY_AUCTION        RUNTIME_PARITY_CFD_SEAM_MISSING
  RUNTIME_PARITY_PREMIUM_SEAM_MISSING
  RUNTIME_PARITY_LIFECYCLE      RUNTIME_PARITY_ALLOCATION
  RUNTIME_PARITY_IDENTITY       RUNTIME_PARITY_NO_FROZEN_DIFF
  RUNTIME_PARITY_SUPERSESSION   RUNTIME_PARITY_PRODUCTION_E2E
  RUNTIME_PARITY_BALANCING_SEAM RUNTIME_PARITY_PERIOD_AXIS
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from app.project_factories import (
    create_generic_solar_reference,
    create_generic_wind_reference,
)
from app.services.model_v2_composition import (
    CompositionStatus,
    ModelV2CompositionContext,
    ModelV2WorkingState,
    RevenuePlanSelection,
    RevenuePlanBridgeError,
    compose_project_inputs,
)
from domain.revenue.plan import RevenuePlan, RevenueStream, RevenueStreamType
from domain.revenue.revenue_config import (
    CfDParams,
    FeedInTariffParams,
    MerchantParams,
    PPAParams,
)
from domain.revenue.plan_engine import evaluate_revenue_plan
from finco_core.engine.period_engine import PeriodEngine
from finco_core.revenue.generation import full_generation_schedule

TOL = 1e-9
_CTX = dict(capacity_mw=64.0)
_WIND_CAPTURE = 0.90


def _solar():
    return create_generic_solar_reference()


def _wind():
    """Wind reference with the class-B EUR/MWh balancing authority zeroed —
    it survives composition untouched (project physical assumption); zeroed
    here to isolate the revenue-mapping parity this file proves."""
    pi = create_generic_wind_reference()
    return replace(pi, revenue=replace(
        pi.revenue, balancing_cost_wind_eur_mwh=0.0))


def _stale_solar():
    """Adversarial base: every plan-governed revenue field populated with
    values that CONFLICT with any selected plan (Correction A §3)."""
    pi = create_generic_solar_reference()
    rev = replace(
        pi.revenue,
        ppa_base_tariff=11.0,
        ppa_term_years=7.0,
        ppa_index=0.09,
        ppa_production_share=0.42,
        ppa_tariff_by_operating_period=(99.0, 98.0, 97.0),
        ppa_indexation_start_policy="AFTER_FIRST_FULL_OPERATING_YEAR",
        ppa_indexation_start_date=None,
        first_merchant_operating_period_index=7,
        market_prices_curve=(123.0, 124.0),
        market_inflation=0.33,
        market_price_calendar_start_year=2030,
        market_prices_by_calendar_year_eur_mwh=(210.0, 211.0, 212.0),
        balancing_cost_pv=0.07,
    )
    return replace(pi, revenue=rev)


def _aligned_solar():
    """Reference project with COD on the semestrial boundary (Dec 31) so a
    finite term anniversary lands exactly on a period start — the only
    grain on which the date-anchored engine window is model-year exact."""
    import datetime
    pi = create_generic_solar_reference()
    return replace(
        pi,
        info=replace(pi.info,
                     financial_close=datetime.date(2029, 12, 31),
                     construction_months=12,
                     cod_date=datetime.date(2030, 12, 31),
                     # keep the SHL maturity period index on the shifted grid
                     horizon_years=26),
    )


def _compose(plan, pi=None, **kw):
    state = ModelV2WorkingState(
        working_copy_ref="wc-05b",
        revenue_plan_selection=RevenuePlanSelection(plan=plan, source_ref="test"),
    )
    ctx = ModelV2CompositionContext(**_CTX)
    return compose_project_inputs(state, ctx, pi or _solar(), **kw)


def _wind_compose(plan):
    state = ModelV2WorkingState(
        working_copy_ref="wc-05b-w",
        revenue_plan_selection=RevenuePlanSelection(plan=plan, source_ref="test"),
    )
    ctx = ModelV2CompositionContext(**_CTX)
    return compose_project_inputs(state, ctx, _wind(), technology="wind")


# ---------------------------------------------------------------------------
# Production-path trace authority (Correction A §2)
# ---------------------------------------------------------------------------

class TestProductionPathContract:
    def test_clean_revenue_contract_has_no_per_period_tariff_field(self):
        """The clean RevenueInput contract — the ONLY revenue surface the
        production adapter forwards — has no per-period tariff schedule
        field. A composed ppa_tariff_by_operating_period can never reach
        the engine; the bridge must never claim parity through it."""
        import financial_engine.inputs as fe_inputs
        import financial_engine.adapters.project_inputs as adapter

        assert "ppa_tariff_by_operating_period" not in (
            fe_inputs.RevenueInput.__dataclass_fields__)
        src = open(adapter.__file__, encoding="utf-8").read()
        assert "ppa_tariff_by_operating_period" not in src
        assert "ppa_indexation_start_policy" in src  # sanity: adapter parsed

    def test_composed_schedule_neutralized_in_composed_inputs(self):
        """A base per-period schedule never survives a V2 selection (the
        orchestrator would feed it to tariff_at_operating_period)."""
        plan = RevenuePlan.create((
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=70.0)),
        ))
        r = _compose(plan, _stale_solar())
        assert r.project_inputs.revenue.ppa_tariff_by_operating_period == ()


# ---------------------------------------------------------------------------
# Supersession — a selected plan is THE revenue authority (Correction A §3/§8)
# ---------------------------------------------------------------------------

GOVERNED_FIELDS = (
    "ppa_base_tariff", "ppa_term_years", "ppa_index", "ppa_production_share",
    "ppa_tariff_by_operating_period", "ppa_indexation_start_policy",
    "ppa_indexation_start_date", "market_prices_curve", "market_inflation",
    "market_price_calendar_start_year", "market_prices_by_calendar_year_eur_mwh",
    "first_merchant_operating_period_index", "balancing_cost_pv",
)


class TestSupersession:
    def test_merchant_only_replaces_stale_base_ppa(self):
        """MERCHANT ONLY: no stale base PPA revenue authority survives."""
        plan = RevenuePlan.create((
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=70.0,
                                                  price_escalation_annual=0.01)),
        ))
        rev = _compose(plan, _stale_solar()).project_inputs.revenue
        assert rev.ppa_base_tariff == pytest.approx(0.0, abs=TOL)
        assert rev.ppa_term_years == pytest.approx(0.0, abs=TOL)
        assert rev.ppa_index == pytest.approx(0.0, abs=TOL)
        assert rev.ppa_production_share == pytest.approx(0.0, abs=TOL)
        assert rev.market_prices_curve[0] == pytest.approx(70.0 * 0.85, abs=TOL)
        assert rev.market_inflation == pytest.approx(0.01, abs=TOL)

    def test_ppa_only_replaces_stale_base_merchant(self):
        """PPA ONLY: no stale base merchant-price economics survive — the
        unallocated-volume fallback cannot fabricate revenue (100% share,
        full horizon → no unallocated volume)."""
        plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=57.0,
                                        ppa_price_index=0.03,
                                        balancing_cost_pct=0.0)),
        ))
        rev = _compose(plan, _stale_solar()).project_inputs.revenue
        assert rev.ppa_base_tariff == pytest.approx(57.0, abs=TOL)
        assert rev.ppa_index == pytest.approx(0.03, abs=TOL)
        assert rev.ppa_production_share == pytest.approx(1.0, abs=TOL)
        assert rev.market_prices_curve == ()
        assert rev.market_inflation == pytest.approx(0.0, abs=TOL)

    def test_higher_precedence_base_schedules_neutralized(self):
        """Correction A §8: calendar merchant schedule, per-period tariff
        schedule, indexation policy and first-merchant switch all take
        precedence over the scalar/curve fields — a V2 selection must
        explicitly supersede every one of them."""
        plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=57.0,
                                        balancing_cost_pct=0.0)),
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=65.0)),
        ))
        rev = _compose(plan, _stale_solar()).project_inputs.revenue
        assert rev.ppa_tariff_by_operating_period == ()
        assert rev.ppa_indexation_start_policy is None
        assert rev.ppa_indexation_start_date is None
        assert rev.first_merchant_operating_period_index is None
        assert rev.market_price_calendar_start_year is None
        assert rev.market_prices_by_calendar_year_eur_mwh == ()

    def test_class_b_authorities_survive_selection(self):
        """Class-B (orthogonal) authorities — CO2, EUR/MWh balancing — are
        NOT plan-governed: a selection neither touches nor neutralizes
        them."""
        pi = create_generic_wind_reference()
        plan = RevenuePlan.create((
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=70.0)),
        ))
        rev = _compose(plan, pi).project_inputs.revenue
        assert rev.balancing_cost_wind_eur_mwh == pytest.approx(
            pi.revenue.balancing_cost_wind_eur_mwh, abs=TOL)
        assert rev.co2_enabled is pi.revenue.co2_enabled

    def test_merchant_balancing_percentage_neutralized(self):
        """Correction A §5 (second half): a merchant-only plan cannot
        inherit a stale base balancing percentage it does not represent."""
        plan = RevenuePlan.create((
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=70.0)),
        ))
        rev = _compose(plan, _stale_solar()).project_inputs.revenue
        assert rev.balancing_cost_pv == pytest.approx(0.0, abs=TOL)


# ---------------------------------------------------------------------------
# PPA parity
# ---------------------------------------------------------------------------

class TestPPAParity:
    def test_100_ppa(self):
        """100% PPA at 57 EUR/MWh → ppa_base_tariff=57, share=1.0, full-
        horizon term (no unallocated volume, no merchant needed)."""
        plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=57.0,
                                        ppa_price_index=0.02,
                                        balancing_cost_pct=0.0),),
        ))
        r = _compose(plan)
        rev = r.project_inputs.revenue
        assert rev.ppa_base_tariff == pytest.approx(57.0, abs=TOL)
        assert rev.ppa_production_share == pytest.approx(1.0, abs=TOL)
        assert rev.ppa_term_years == pytest.approx(25.0, abs=TOL)

    def test_partial_ppa_residual_merchant(self):
        """70% PPA + residual merchant: canonical share=0.7, merchant curve
        carries the capture-embedded plan price."""
        plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=0.7,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=57.0,
                                        balancing_cost_pct=0.0)),
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=65.0)),
        ))
        r = _compose(plan)
        rev = r.project_inputs.revenue
        assert rev.ppa_production_share == pytest.approx(0.7, abs=TOL)
        assert rev.ppa_base_tariff == pytest.approx(57.0, abs=TOL)
        assert rev.market_prices_curve[0] == pytest.approx(65.0 * 0.85, abs=TOL)

    def test_indexed_ppa(self):
        """Indexed PPA: plan ppa_price_index maps to runtime ppa_index
        (same analytic authority, same year-granular mapping)."""
        plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=50.0,
                                        ppa_price_index=0.03,
                                        balancing_cost_pct=0.0),),
        ))
        r = _compose(plan)
        assert r.project_inputs.revenue.ppa_index == pytest.approx(0.03, abs=TOL)

    def test_term_limited_ppa_with_merchant(self):
        """Finite PPA term + merchant: tail years sell 100% merchant —
        exactly the plan's post-term semantics."""
        plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=0.7,
                          term_years=10,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=57.0,
                                        balancing_cost_pct=0.0)),
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=65.0)),
        ))
        r = _compose(plan, _aligned_solar())
        rev = r.project_inputs.revenue
        assert rev.ppa_term_years == pytest.approx(10.0, abs=TOL)
        assert rev.ppa_production_share == pytest.approx(0.7, abs=TOL)


# ---------------------------------------------------------------------------
# Merchant parity
# ---------------------------------------------------------------------------

class TestMerchantParity:
    def test_merchant_only(self):
        plan = RevenuePlan.create((
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=65.0)),
        ))
        r = _compose(plan)
        rev = r.project_inputs.revenue
        assert rev.market_prices_curve[0] == pytest.approx(65.0 * 0.85, abs=TOL)

    def test_merchant_capture_wind(self):
        """Wind capture rate (0.90) embedded into the runtime curve."""
        plan = RevenuePlan.create((
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=65.0,
                                                  capture_rate_wind=0.90)),
        ))
        r = _wind_compose(plan)
        assert r.project_inputs.revenue.market_prices_curve[0] == \
            pytest.approx(65.0 * _WIND_CAPTURE, abs=TOL)

    def test_merchant_custom_curve(self):
        curve_vals = (70.0, 72.0, 75.0)
        plan = RevenuePlan.create((
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(
                              merchant_enabled=True, price_scenario="custom",
                              custom_price_curve=curve_vals,
                              capture_rate_solar=0.85)),
        ))
        r = _compose(plan)
        rev = r.project_inputs.revenue
        for i, expected in enumerate(curve_vals):
            assert rev.market_prices_curve[i] == pytest.approx(expected * 0.85, abs=TOL)
        # plan authority drives the post-curve years (base + escalation),
        # never a truncated curve
        assert len(rev.market_prices_curve) == _solar().info.horizon_years


# ---------------------------------------------------------------------------
# Fixed FiT / auction — volume share + lifecycle exactness (Correction A §4)
# ---------------------------------------------------------------------------

class TestFixedTariffAllocation:
    def test_100pct_fit_does_not_inherit_stale_base_share(self):
        """A 100% FiT must not inherit the base 70% PPA share."""
        plan = RevenuePlan.create((
            RevenueStream("fit", RevenueStreamType.FIT_FIXED, volume_share=1.0,
                          fit=FeedInTariffParams(fit_enabled=True,
                                                 fit_type="fixed_fit",
                                                 fit_price_eur_mwh=80.0,
                                                 fit_index=0.0)),
        ))
        rev = _compose(plan, _stale_solar()).project_inputs.revenue
        assert rev.ppa_production_share == pytest.approx(1.0, abs=TOL)
        assert rev.ppa_base_tariff == pytest.approx(80.0, abs=TOL)
        assert rev.ppa_term_years == pytest.approx(25.0, abs=TOL)

    def test_40pct_fit_keeps_40pct_share_with_merchant(self):
        """A 40% FiT must not become 100% tariff allocation."""
        plan = RevenuePlan.create((
            RevenueStream("fit", RevenueStreamType.FIT_FIXED, volume_share=0.4,
                          fit=FeedInTariffParams(fit_enabled=True,
                                                 fit_type="fixed_fit",
                                                 fit_price_eur_mwh=80.0)),
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=65.0)),
        ))
        rev = _compose(plan, _stale_solar()).project_inputs.revenue
        assert rev.ppa_production_share == pytest.approx(0.4, abs=TOL)

    def test_partial_fit_without_merchant_fails_closed(self):
        """40% FiT and no merchant: the runtime would sell the residual at
        the tariff fallback price — fail closed, never approximate."""
        plan = RevenuePlan.create((
            RevenueStream("fit", RevenueStreamType.FIT_FIXED, volume_share=0.4,
                          fit=FeedInTariffParams(fit_enabled=True,
                                                 fit_type="fixed_fit",
                                                 fit_price_eur_mwh=80.0)),
        ))
        with pytest.raises(RevenuePlanBridgeError,
                           match="RUNTIME_UNALLOCATED_VOLUME_WITHOUT_MERCHANT"):
            _compose(plan)

    def test_term_limited_fit_without_merchant_fails_closed(self):
        """A finite FiT term with no merchant authority: post-term tail
        volume cannot earn 'nothing' in the runtime."""
        plan = RevenuePlan.create((
            RevenueStream("fit", RevenueStreamType.FIT_FIXED, volume_share=1.0,
                          term_years=12,
                          fit=FeedInTariffParams(fit_enabled=True,
                                                 fit_type="fixed_fit",
                                                 fit_price_eur_mwh=80.0)),
        ))
        with pytest.raises(RevenuePlanBridgeError,
                           match="RUNTIME_UNALLOCATED_VOLUME_WITHOUT_MERCHANT"):
            _compose(plan, _aligned_solar())

    def test_fit_term_not_inherited_from_stale_base_ppa(self):
        """A finite FiT term must be the stream's own term, never the base
        PPA term (stale base carries term 7)."""
        plan = RevenuePlan.create((
            RevenueStream("fit", RevenueStreamType.FIT_FIXED, volume_share=1.0,
                          term_years=12,
                          fit=FeedInTariffParams(fit_enabled=True,
                                                 fit_type="fixed_fit",
                                                 fit_price_eur_mwh=80.0)),
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=65.0)),
        ))
        rev = _compose(plan, _aligned_solar()).project_inputs.revenue
        assert rev.ppa_term_years == pytest.approx(12.0, abs=TOL)

    def test_auction_awarded_tariff_maps_to_fixed_tariff_authority(self):
        plan = RevenuePlan.create((
            RevenueStream("auc", RevenueStreamType.AUCTION_AWARDED_TARIFF,
                          volume_share=1.0,
                          fit=FeedInTariffParams(fit_enabled=True,
                                                 fit_type="fixed_fit",
                                                 fit_price_eur_mwh=90.0,
                                                 fit_index=0.01)),
        ))
        rev = _compose(plan).project_inputs.revenue
        assert rev.ppa_base_tariff == pytest.approx(90.0, abs=TOL)
        assert rev.ppa_index == pytest.approx(0.01, abs=TOL)
        assert rev.ppa_production_share == pytest.approx(1.0, abs=TOL)

    def test_delayed_start_tariff_fails_closed(self):
        """Delayed-start tariff: the runtime PPA window opens at COD — the
        pre-start volume cannot be released to merchant."""
        plan = RevenuePlan.create((
            RevenueStream("fit", RevenueStreamType.FIT_FIXED, volume_share=1.0,
                          start_year=4,
                          fit=FeedInTariffParams(fit_enabled=True,
                                                 fit_type="fixed_fit",
                                                 fit_price_eur_mwh=80.0)),
        ))
        with pytest.raises(RevenuePlanBridgeError,
                           match="RUNTIME_DELAYED_START_TARIFF_SEAM_MISSING"):
            _compose(plan)

    def test_fractional_term_fails_closed(self):
        """Fractional term: plan grain is model years, engine window is
        date-anchored — boundary half-periods would diverge."""
        plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                          term_years=12.5,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=57.0,
                                        balancing_cost_pct=0.0)),
        ))
        with pytest.raises(RevenuePlanBridgeError,
                           match="RUNTIME_TARIFF_TERM_GRAIN_SEAM_MISSING"):
            _compose(plan)

    def test_misaligned_integer_term_fails_closed(self):
        """Integer term whose COD anniversary falls inside an operating
        period: the date-anchored engine window would price the partial
        period at the tariff while the plan has the year inactive."""
        plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=0.7,
                          term_years=10,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=57.0,
                                        balancing_cost_pct=0.0)),
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=65.0)),
        ))
        # reference project COD (2031-03-01) never lands on a period start
        with pytest.raises(RevenuePlanBridgeError,
                           match="RUNTIME_TARIFF_TERM_ALIGNMENT_SEAM_MISSING"):
            _compose(plan)


# ---------------------------------------------------------------------------
# Indexed FiT — MISSING != ZERO (Correction A §4 of the defects, §6 here)
# ---------------------------------------------------------------------------

class TestIndexedFit:
    def _plan(self, factors=(1.0, 1.02, 1.04), term=5):
        return RevenuePlan.create((
            RevenueStream("ifit", RevenueStreamType.INDEXED_FIT,
                          volume_share=1.0, term_years=term,
                          indexed_fit_base_tariff_eur_mwh=75.0,
                          indexed_fit_index_factors=factors),
        ))

    def test_missing_active_factor_fails_closed_never_zero(self):
        """An ACTIVE indexed-FiT year without a factor raises the typed
        seam — it never composes a zero tariff and never reports COMPOSED."""
        plan = self._plan(factors=(1.0, 1.02), term=5)
        with pytest.raises(RevenuePlanBridgeError,
                           match="RUNTIME_INDEXED_FIT_AUTHORITY_MISSING"):
            _compose(plan)

    def test_complete_factors_still_fail_closed_on_schedule_seam(self):
        """Even with full factor coverage, a per-year indexed schedule
        cannot reach the engine (clean RevenueInput forwards no such
        field) — documented production seam, fail closed."""
        plan = self._plan(factors=tuple(1.0 + 0.01 * i for i in range(5)),
                          term=5)
        with pytest.raises(RevenuePlanBridgeError,
                           match="RUNTIME_INDEXED_FIT_SCHEDULE_SEAM_MISSING"):
            _compose(plan)

    def test_missing_authority_object_fails_closed(self):
        """The plan contract itself refuses an indexed-FiT stream without a
        base tariff (REVENUE_STREAM_INDEXED_FIT_BASE_TARIFF_REQUIRED) —
        fail closed at the domain boundary, before composition."""
        with pytest.raises(ValueError,
                           match="REVENUE_STREAM_INDEXED_FIT_BASE_TARIFF_REQUIRED"):
            RevenuePlan.create((
                RevenueStream("ifit", RevenueStreamType.INDEXED_FIT,
                              volume_share=1.0,
                              indexed_fit_base_tariff_eur_mwh=None,
                              indexed_fit_index_factors=()),
            ))


# ---------------------------------------------------------------------------
# Fail-closed seams — overlays, multiple tariff paths, balancing
# ---------------------------------------------------------------------------

class TestSeams:
    def test_cfd_seam_missing_fail_closed(self):
        plan = RevenuePlan.create((
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=65.0)),
            RevenueStream("cfd", RevenueStreamType.CFD, volume_share=1.0,
                          cfd=CfDParams(cfd_enabled=True,
                                        strike_price_eur_mwh=60.0),
                          reference_stream_id="m"),
        ))
        with pytest.raises(RevenuePlanBridgeError,
                           match="REVENUE_PLAN_STREAM_UNSUPPORTED"):
            _compose(plan)

    def test_premium_seam_missing_fail_closed(self):
        plan = RevenuePlan.create((
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=65.0)),
            RevenueStream("prem", RevenueStreamType.FIT_PREMIUM,
                          volume_share=1.0,
                          fit=FeedInTariffParams(fit_enabled=True,
                                                 fit_type="premium",
                                                 premium_eur_mwh=12.0),
                          reference_stream_id="m"),
        ))
        with pytest.raises(RevenuePlanBridgeError,
                           match="REVENUE_PLAN_STREAM_UNSUPPORTED.*overlay"):
            _compose(plan)

    def test_ppa_plus_fit_fails_closed(self):
        """PPA + FiT: the single runtime tariff path cannot carry two
        simultaneously-active fixed-tariff contracts."""
        plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=0.7,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=57.0,
                                        balancing_cost_pct=0.0)),
            RevenueStream("fit", RevenueStreamType.FIT_FIXED, volume_share=0.3,
                          fit=FeedInTariffParams(fit_enabled=True,
                                                 fit_type="fixed_fit",
                                                 fit_price_eur_mwh=80.0)),
        ))
        with pytest.raises(RevenuePlanBridgeError,
                           match="RUNTIME_TARIFF_PATH_MULTIPLE_UNSUPPORTED"):
            _compose(plan)

    def test_sequential_tariff_streams_fail_closed(self):
        """Correction A §10: sequential fixed-tariff contracts (non-
        overlapping windows) are NOT exactly representable by the single
        canonical tariff/share path when shares or windows differ — fail
        closed, never advertise concatenation as support."""
        plan = RevenuePlan.create((
            RevenueStream("fit1", RevenueStreamType.FIT_FIXED,
                          volume_share=1.0, term_years=10,
                          fit=FeedInTariffParams(fit_enabled=True,
                                                 fit_type="fixed_fit",
                                                 fit_price_eur_mwh=80.0)),
            RevenueStream("fit2", RevenueStreamType.FIT_FIXED,
                          volume_share=0.6, start_year=11, term_years=10,
                          fit=FeedInTariffParams(fit_enabled=True,
                                                 fit_type="fixed_fit",
                                                 fit_price_eur_mwh=85.0)),
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=65.0)),
        ))
        with pytest.raises(RevenuePlanBridgeError,
                           match="RUNTIME_TARIFF_PATH_MULTIPLE_UNSUPPORTED"):
            _compose(plan)

    def test_ppa_balancing_semantic_mismatch_fails_closed(self):
        """Correction A §5: plan PPA balancing deducts from PPA revenue;
        the frozen core deducts balancing_cost_pv from MERCHANT revenue
        only. The mapping is NOT semantically equivalent — fail closed."""
        plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=57.0,
                                        balancing_cost_pct=0.025)),
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=65.0)),
        ))
        with pytest.raises(RevenuePlanBridgeError,
                           match="RUNTIME_PPA_BALANCING_SEAM_MISSING"):
            _compose(plan)

    def test_ppa_imbalance_penalty_semantic_mismatch_fails_closed(self):
        """A non-zero imbalance penalty shares the same PPA-only deduction
        basis mismatch and must never be mapped to merchant balancing."""
        plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=57.0,
                                        balancing_cost_pct=0.0,
                                        imbalance_penalty_pct=0.01)),
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=65.0)),
        ))
        with pytest.raises(RevenuePlanBridgeError,
                           match="RUNTIME_PPA_BALANCING_SEAM_MISSING"):
            _compose(plan)


# ---------------------------------------------------------------------------
# Correction B — merchant count / lifecycle / allocation, PPA floor/cap
# ---------------------------------------------------------------------------

class TestMerchantExpressibilityBoundary:
    def _merchant(self, price=65.0, **stream_kw):
        return RevenueStream(
            "m", RevenueStreamType.MERCHANT,
            merchant=MerchantParams(merchant_enabled=True,
                                    base_price_eur_mwh=price),
            **stream_kw)

    def test_two_explicit_merchant_streams_fail_closed(self):
        with pytest.raises(RevenuePlanBridgeError,
                           match="RUNTIME_MULTIPLE_MERCHANT_STREAMS_UNSUPPORTED"):
            _compose(RevenuePlan.create((
                self._merchant(60.0, volume_share=0.5),
                RevenueStream("m2", RevenueStreamType.MERCHANT,
                              volume_share=0.5,
                              merchant=MerchantParams(
                                  merchant_enabled=True,
                                  base_price_eur_mwh=70.0)),
            )))

    def test_residual_plus_explicit_merchant_fails_closed(self):
        """The domain permits a residual + explicit merchant pair; the
        runtime has ONE merchant price path — fail closed."""
        with pytest.raises(RevenuePlanBridgeError,
                           match="RUNTIME_MULTIPLE_MERCHANT_STREAMS_UNSUPPORTED"):
            _compose(RevenuePlan.create((
                self._merchant(60.0, volume_share=None),
                RevenueStream("m2", RevenueStreamType.MERCHANT,
                              volume_share=0.5,
                              merchant=MerchantParams(
                                  merchant_enabled=True,
                                  base_price_eur_mwh=70.0)),
            )))

    def test_merchant_only_explicit_half_fails_closed(self):
        """Merchant-only explicit 0.5: the plan leaves 50% unallocated
        (zero revenue); the runtime would sell 100% — fail closed."""
        plan = RevenuePlan.create((
            self._merchant(65.0, volume_share=0.5),
        ))
        with pytest.raises(RevenuePlanBridgeError,
                           match="RUNTIME_MERCHANT_ALLOCATION_SEAM_MISSING"):
            _compose(plan)

    def test_explicit_merchant_alongside_tariff_fails_closed(self):
        plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=0.7,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=57.0,
                                        balancing_cost_pct=0.0)),
            self._merchant(65.0, volume_share=0.3),
        ))
        with pytest.raises(RevenuePlanBridgeError,
                           match="RUNTIME_MERCHANT_ALLOCATION_SEAM_MISSING"):
            _compose(plan)

    def test_merchant_only_explicit_full_volume_supported(self):
        """Merchant-only explicit 1.0 == the runtime residual — supported,
        production-proven."""
        plan = RevenuePlan.create((
            self._merchant(70.0, volume_share=1.0),
        ))
        composed = _compose(plan).project_inputs
        assert _production_revenue_keur(composed) == pytest.approx(
            _expected_plan_revenue_keur(plan, composed), rel=1e-9)

    def test_delayed_merchant_fails_closed(self):
        plan = RevenuePlan.create((
            self._merchant(65.0, volume_share=None, start_year=3),
        ))
        with pytest.raises(RevenuePlanBridgeError,
                           match="RUNTIME_MERCHANT_LIFECYCLE_SEAM_MISSING"):
            _compose(plan)

    def test_finite_term_merchant_fails_closed(self):
        plan = RevenuePlan.create((
            self._merchant(65.0, volume_share=None, term_years=10),
        ))
        with pytest.raises(RevenuePlanBridgeError,
                           match="RUNTIME_MERCHANT_LIFECYCLE_SEAM_MISSING"):
            _compose(plan)

    def test_finite_term_merchant_with_tariff_fails_closed(self):
        plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=0.7,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=57.0,
                                        balancing_cost_pct=0.0)),
            self._merchant(65.0, volume_share=None, term_years=15),
        ))
        with pytest.raises(RevenuePlanBridgeError,
                           match="RUNTIME_MERCHANT_LIFECYCLE_SEAM_MISSING"):
            _compose(plan)


class TestPPAFloorCap:
    def test_nonzero_floor_fails_closed(self):
        plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=57.0,
                                        ppa_price_floor=45.0,
                                        balancing_cost_pct=0.0)),
        ))
        with pytest.raises(RevenuePlanBridgeError,
                           match="RUNTIME_PPA_FLOOR_CAP_SEAM_MISSING"):
            _compose(plan)

    def test_nonzero_cap_fails_closed(self):
        plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=57.0,
                                        ppa_price_cap=70.0,
                                        balancing_cost_pct=0.0)),
        ))
        with pytest.raises(RevenuePlanBridgeError,
                           match="RUNTIME_PPA_FLOOR_CAP_SEAM_MISSING"):
            _compose(plan)

    def test_zero_floor_cap_ppa_e2e_remains_green(self):
        plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=57.0,
                                        ppa_price_floor=0.0,
                                        ppa_price_cap=0.0,
                                        ppa_price_index=0.02,
                                        balancing_cost_pct=0.0)),
        ))
        composed = _compose(plan).project_inputs
        assert _production_revenue_keur(composed) == pytest.approx(
            _expected_plan_revenue_keur(plan, composed), rel=1e-9)


# ---------------------------------------------------------------------------
# Identity — economic hash semantics
# ---------------------------------------------------------------------------

class TestIdentity:
    def test_label_change_does_not_change_hash(self):
        """Label/counterparty are presentation metadata — changing them
        does NOT change the composition hash."""
        p1 = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=57.0,
                                        balancing_cost_pct=0.0),
                          counterparty="Utility A"),
        ))
        p2 = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=57.0,
                                        balancing_cost_pct=0.0),
                          counterparty="Utility B"),
        ))
        h1 = _compose(p1, _solar()).composition_hash
        h2 = _compose(p2, _solar()).composition_hash
        assert h1 == h2

    def test_economic_change_changes_hash(self):
        p1 = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=57.0,
                                        balancing_cost_pct=0.0)),
        ))
        p2 = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=58.0,
                                        balancing_cost_pct=0.0)),
        ))
        h1 = _compose(p1, _solar()).composition_hash
        h2 = _compose(p2, _solar()).composition_hash
        assert h1 != h2


# ---------------------------------------------------------------------------
# Production E2E — compose → run_clean_production → canonical revenue
# (Correction A §9). Expected economics come from the Workflow 02 plan
# engine over the SAME generation authority the runtime uses — no finance
# formula is reimplemented here.
# ---------------------------------------------------------------------------

def _expected_plan_revenue_keur(plan, composed_pi, technology="solar"):
    """Total plan-level revenue over the horizon, evaluated by the
    Workflow 02 authority on the runtime's own generation schedule."""
    engine = PeriodEngine(
        composed_pi.info.financial_close,
        composed_pi.info.construction_months,
        composed_pi.info.horizon_years,
        int(composed_pi.revenue.ppa_term_years),
    )
    gen_by_period = full_generation_schedule(composed_pi, engine)
    gen_by_year: dict[int, float] = {}
    for period in engine.periods():
        if period.is_operation:
            gen_by_year[period.year_index] = (
                gen_by_year.get(period.year_index, 0.0)
                + gen_by_period[period.index])
    total = 0.0
    for year in sorted(gen_by_year):
        result = evaluate_revenue_plan(plan, year, gen_by_year[year],
                                       technology=technology)
        assert result.total_revenue_keur is not None, (
            f"plan unavailable in year {year}")
        total += result.total_revenue_keur
    return total


def _production_revenue_keur(composed_pi):
    from app.services.production_financial_authority import (
        run_clean_production,
    )
    run = run_clean_production(composed_pi)
    periods = run.financial_statements_result.income_statement_periods
    return sum(p.revenue_keur for p in periods)


class TestProductionE2E:
    def test_merchant_only_e2e(self):
        plan = RevenuePlan.create((
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=70.0,
                                                  capture_rate_solar=0.85)),
        ))
        composed = _compose(plan).project_inputs
        assert _production_revenue_keur(composed) == pytest.approx(
            _expected_plan_revenue_keur(plan, composed), rel=1e-9)

    def test_ppa_only_e2e(self):
        plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=57.0,
                                        ppa_price_index=0.02,
                                        balancing_cost_pct=0.0)),
        ))
        composed = _compose(plan).project_inputs
        assert _production_revenue_keur(composed) == pytest.approx(
            _expected_plan_revenue_keur(plan, composed), rel=1e-9)

    def test_ppa_plus_residual_merchant_e2e(self):
        plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=0.7,
                          term_years=10,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=57.0,
                                        balancing_cost_pct=0.0)),
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=65.0)),
        ))
        composed = _compose(plan, _aligned_solar()).project_inputs
        assert _production_revenue_keur(composed) == pytest.approx(
            _expected_plan_revenue_keur(plan, composed), rel=1e-9)

    def test_fixed_fit_e2e(self):
        plan = RevenuePlan.create((
            RevenueStream("fit", RevenueStreamType.FIT_FIXED, volume_share=1.0,
                          fit=FeedInTariffParams(fit_enabled=True,
                                                 fit_type="fixed_fit",
                                                 fit_price_eur_mwh=80.0,
                                                 fit_index=0.01)),
        ))
        composed = _compose(plan).project_inputs
        assert _production_revenue_keur(composed) == pytest.approx(
            _expected_plan_revenue_keur(plan, composed), rel=1e-9)

    def test_auction_e2e(self):
        plan = RevenuePlan.create((
            RevenueStream("auc", RevenueStreamType.AUCTION_AWARDED_TARIFF,
                          volume_share=1.0,
                          fit=FeedInTariffParams(fit_enabled=True,
                                                 fit_type="fixed_fit",
                                                 fit_price_eur_mwh=90.0)),
        ))
        composed = _compose(plan).project_inputs
        assert _production_revenue_keur(composed) == pytest.approx(
            _expected_plan_revenue_keur(plan, composed), rel=1e-9)

    def test_calendar_schedule_supersession_reaches_production(self):
        """Correction A §8 E2E: a populated base calendar-year merchant
        schedule must NOT reach production over a selected plan curve."""
        plan = RevenuePlan.create((
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=70.0,
                                                  price_escalation_annual=0.0)),
        ))
        composed = _compose(plan, _stale_solar()).project_inputs
        assert _production_revenue_keur(composed) == pytest.approx(
            _expected_plan_revenue_keur(plan, composed), rel=1e-9)
        # ...and the production revenue is NOT the stale schedule's economics
        assert composed.revenue.market_prices_by_calendar_year_eur_mwh == ()

    def test_wind_merchant_e2e(self):
        plan = RevenuePlan.create((
            RevenueStream("m", RevenueStreamType.MERCHANT, volume_share=None,
                          merchant=MerchantParams(merchant_enabled=True,
                                                  base_price_eur_mwh=65.0,
                                                  capture_rate_wind=0.90)),
        ))
        composed = _wind_compose(plan).project_inputs
        assert _production_revenue_keur(composed) == pytest.approx(
            _expected_plan_revenue_keur(plan, composed, technology="wind"),
            rel=1e-9)


# ---------------------------------------------------------------------------
# Period axis (Correction A §3) — tariff selection is year-granular
# ---------------------------------------------------------------------------

class TestPeriodAxis:
    def test_semestrial_periods_share_the_operating_year_tariff(self):
        """ANNUAL/SEMESTRIAL proof: both semestrial periods of operating
        year Y carry the year-Y indexed tariff — the canonical
        operating-year mapping, never a per-period escalation."""
        plan = RevenuePlan.create((
            RevenueStream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                          ppa=PPAParams(ppa_enabled=True,
                                        ppa_base_price_eur_mwh=50.0,
                                        ppa_price_index=0.03,
                                        balancing_cost_pct=0.0)),
        ))
        composed = _compose(plan).project_inputs
        engine = PeriodEngine(
            composed.info.financial_close,
            composed.info.construction_months,
            composed.info.horizon_years,
            int(composed.revenue.ppa_term_years),
        )
        from finco_core.revenue.generation import revenue_decomposition_schedule
        decomposition = revenue_decomposition_schedule(composed, engine)
        by_year: dict[int, list[float]] = {}
        for period in engine.periods():
            if period.is_operation:
                by_year.setdefault(period.year_index, []).append(
                    decomposition[period.index]["ppa_tariff_eur_mwh"])
        for year, tariffs in by_year.items():
            expected = 50.0 * 1.03 ** (year - 1)
            assert len(tariffs) == 2  # semestrial production axis
            for t in tariffs:
                assert t == pytest.approx(expected, rel=1e-12)


# ---------------------------------------------------------------------------
# Legacy passthrough + protected namespaces
# ---------------------------------------------------------------------------

class TestLegacyPassthrough:
    def test_no_selection_returns_base_unchanged(self):
        state = ModelV2WorkingState(working_copy_ref="wc-05b")
        ctx = ModelV2CompositionContext(**_CTX)
        base = _solar()
        r = compose_project_inputs(state, ctx, base)
        assert r.status is CompositionStatus.LEGACY_PASSTHROUGH
        assert r.project_inputs is base


class TestNoFrozenDiff:
    def test_zero_frozen_and_unauthorized_changes(self):
        import sys
        sys.path.insert(0, "tests")
        import model_v2_governance as gov
        changed = gov.changed_paths_vs_main()
        assert gov.model_v2_frozen_violations(changed) == []
        # Engine files outside the shared approved allow-list must stay untouched.
        import finance_integrity_governance as fig
        assert fig.unapproved_engine_changes(changed) == []
        # The branch-wide scope-completeness contract only exists while a temporary
        # ACTIVE epic scope exists; frozen/engine protection above always applies.
        if gov.active_scope() is not None:
            assert gov.unauthorized_model_v2_changes(changed) == []
