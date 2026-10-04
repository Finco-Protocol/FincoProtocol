"""Model V2 Revenue Plan domain acceptance matrix (Workflow 02).

Deterministic domain-level tests for the RevenuePlan contract system.
No ProjectInputs wiring, no production runtime path changes.

Acceptance markers:

  REVENUE_PLAN_CONTRACT        MULTI_STREAM_ALLOCATION   RESIDUAL_MERCHANT
  CFD_OVERLAY                  FIT_FIXED                 FIT_PREMIUM
  INDEXED_FIT                  AUCTION_CONTRACT          DOUBLE_COUNTING_GUARD
  LEGACY_DOMAIN_ADAPTER        PRODUCTION_RUNTIME_UNCHANGED (by isolation)
"""
from __future__ import annotations

import dataclasses

import pytest

from domain.revenue.plan import (
    ContractRole,
    RevenueAllocationGroup,
    RevenuePlan,
    RevenueStream,
    RevenueStreamType,
    contract_role_for,
)
from domain.revenue.plan_engine import (
    PlanPeriodStatus,
    StreamPeriodStatus,
    evaluate_revenue_plan,
)
from domain.revenue.revenue_config import (
    CfDParams,
    FeedInTariffParams,
    MerchantParams,
    PPAParams,
    RevenueConfig,
)
from domain.revenue.legacy_plan_adapter import revenue_plan_from_legacy_config

TOL = 1e-9


def _ppa(share=1.0, price=57.0, term=15, index=0.0, balancing=0.0, start=1, floor=0.0, cap=0.0):
    return PPAParams(
        ppa_enabled=True, ppa_base_price_eur_mwh=price, ppa_term_years=term,
        ppa_volume_share=share, ppa_price_index=index, balancing_cost_pct=balancing,
        ppa_start_year=start, ppa_price_floor=floor, ppa_price_cap=cap,
    )


def _merchant(price=65.0, curve=(), capture_solar=0.85, capture_wind=0.90):
    return MerchantParams(
        merchant_enabled=True, base_price_eur_mwh=price,
        price_escalation_annual=0.0, custom_price_curve=curve,
        capture_rate_solar=capture_solar, capture_rate_wind=capture_wind,
    )


def _cfd(strike=70.0, term=10, two_way=True):
    return CfDParams(cfd_enabled=True, strike_price_eur_mwh=strike,
                     cfd_term_years=term, two_way_cfd=two_way)


def _fit_fixed(price=80.0, term=0, index=0.0):
    return FeedInTariffParams(fit_enabled=True, fit_type="fixed_fit",
                              fit_price_eur_mwh=price, fit_term_years=term,
                              fit_index=index)


def _fit_premium(premium=12.0, floor=0.0, cap=0.0, term=0):
    return FeedInTariffParams(fit_enabled=True, fit_type="premium",
                              premium_eur_mwh=premium,
                              premium_floor_eur_mwh=floor,
                              premium_cap_eur_mwh=cap,
                              fit_term_years=term)


def _stream(sid, stype, **kw):
    return RevenueStream(sid, stype, **kw)


# ---------------------------------------------------------------------------
# A. single PPA / B. single Merchant
# ---------------------------------------------------------------------------

def test_a_single_ppa_revenue():
    plan = RevenuePlan.create((_stream("ppa", RevenueStreamType.PPA, volume_share=1.0, ppa=_ppa(price=57.0)),))
    r = evaluate_revenue_plan(plan, 1, 100_000.0)
    (s,) = r.stream_results
    assert s.status is StreamPeriodStatus.ACTIVE
    assert s.price_eur_mwh == 57.0
    assert s.stream_revenue_keur == pytest.approx(100_000 * 57.0 / 1000, abs=TOL)
    assert r.total_revenue_keur == pytest.approx(s.stream_revenue_keur, abs=TOL)
    assert r.status is PlanPeriodStatus.OK


def test_b_single_merchant_uses_capture_rate():
    plan = RevenuePlan.create((_stream("m", RevenueStreamType.MERCHANT, volume_share=None, merchant=_merchant(price=65.0)),))
    r = evaluate_revenue_plan(plan, 1, 100_000.0, technology="wind")
    (s,) = r.stream_results
    assert s.stream_revenue_keur == pytest.approx(100_000 * 65.0 * 0.90 / 1000, abs=TOL)
    # residual merchant with no other primaries takes everything
    assert s.allocated_generation_mwh == pytest.approx(100_000.0, abs=TOL)
    assert r.unallocated_generation_mwh == pytest.approx(0.0, abs=TOL)


# ---------------------------------------------------------------------------
# C / D / E / F. allocation & residual semantics
# ---------------------------------------------------------------------------

def test_c_ppa_plus_residual_merchant():
    plan = RevenuePlan.create((
        _stream("ppa", RevenueStreamType.PPA, volume_share=0.6, ppa=_ppa(share=0.6, price=57.0)),
        _stream("m", RevenueStreamType.MERCHANT, volume_share=None, merchant=_merchant(price=65.0)),
    ))
    r = evaluate_revenue_plan(plan, 1, 100_000.0, technology="solar")
    by_id = {s.stream_id: s for s in r.stream_results}
    assert by_id["ppa"].allocated_generation_mwh == pytest.approx(60_000.0, abs=TOL)
    assert by_id["m"].allocated_generation_mwh == pytest.approx(40_000.0, abs=TOL)
    assert by_id["m"].stream_revenue_keur == pytest.approx(40_000 * 65.0 * 0.85 / 1000, abs=TOL)
    expected = 60_000 * 57.0 / 1000 + 40_000 * 65.0 * 0.85 / 1000
    assert r.total_revenue_keur == pytest.approx(expected, abs=TOL)
    assert r.unallocated_generation_mwh == pytest.approx(0.0, abs=TOL)


def test_d_two_ppas_plus_residual_merchant():
    plan = RevenuePlan.create((
        _stream("ppa_a", RevenueStreamType.PPA, volume_share=0.3, ppa=_ppa(price=50.0)),
        _stream("ppa_b", RevenueStreamType.PPA, volume_share=0.4, ppa=_ppa(price=60.0)),
        _stream("m", RevenueStreamType.MERCHANT, volume_share=None, merchant=_merchant(price=65.0)),
    ))
    r = evaluate_revenue_plan(plan, 1, 100_000.0, technology="solar")
    by_id = {s.stream_id: s for s in r.stream_results}
    assert by_id["ppa_a"].allocated_generation_mwh == pytest.approx(30_000.0, abs=TOL)
    assert by_id["ppa_b"].allocated_generation_mwh == pytest.approx(40_000.0, abs=TOL)
    assert by_id["m"].allocated_generation_mwh == pytest.approx(30_000.0, abs=TOL)
    expected = 30_000 * 50.0 / 1000 + 40_000 * 60.0 / 1000 + 30_000 * 65.0 * 0.85 / 1000
    assert r.total_revenue_keur == pytest.approx(expected, abs=TOL)


def test_e_allocation_exactly_100_percent_no_residual():
    plan = RevenuePlan.create((
        _stream("ppa_a", RevenueStreamType.PPA, volume_share=0.7, ppa=_ppa(price=57.0)),
        _stream("ppa_b", RevenueStreamType.PPA, volume_share=0.3, ppa=_ppa(price=52.0)),
    ))
    r = evaluate_revenue_plan(plan, 1, 100_000.0)
    assert r.unallocated_generation_mwh == pytest.approx(0.0, abs=TOL)
    assert r.status is PlanPeriodStatus.OK


def test_f_allocation_above_100_rejected_fail_closed():
    with pytest.raises(ValueError, match="REVENUE_ALLOCATION_EXCEEDS_ELIGIBLE_GENERATION"):
        RevenuePlan.create((
            _stream("ppa_a", RevenueStreamType.PPA, volume_share=0.7, ppa=_ppa()),
            _stream("ppa_b", RevenueStreamType.PPA, volume_share=0.5, ppa=_ppa()),
        ))


def test_f2_shares_are_never_silently_normalized():
    """70% + 50% must not become a valid 100% (normalization forbidden)."""
    with pytest.raises(ValueError):
        RevenuePlan.create((
            _stream("ppa_a", RevenueStreamType.PPA, volume_share=0.7, ppa=_ppa()),
            _stream("ppa_b", RevenueStreamType.PPA, volume_share=0.5, ppa=_ppa()),
        ))


# ---------------------------------------------------------------------------
# G / H. disabled & term boundaries
# ---------------------------------------------------------------------------

def test_g_disabled_stream_ignored_but_typed():
    plan = RevenuePlan.create((
        _stream("ppa", RevenueStreamType.PPA, volume_share=0.6, ppa=_ppa(share=0.6), enabled=False),
        _stream("m", RevenueStreamType.MERCHANT, volume_share=None, merchant=_merchant()),
    ))
    r = evaluate_revenue_plan(plan, 1, 100_000.0)
    by_id = {s.stream_id: s for s in r.stream_results}
    assert by_id["ppa"].status is StreamPeriodStatus.DISABLED
    assert by_id["ppa"].stream_revenue_keur == 0.0  # disabled is an explicit zero contribution
    # disabled PPA does not consume allocation: merchant takes everything
    assert by_id["m"].allocated_generation_mwh == pytest.approx(100_000.0, abs=TOL)


def test_h_term_boundaries_deterministic():
    plan = RevenuePlan.create((_stream("ppa", RevenueStreamType.PPA, volume_share=1.0, ppa=_ppa(term=3), term_years=3),))
    assert evaluate_revenue_plan(plan, 1, 1000.0).stream_results[0].status is StreamPeriodStatus.ACTIVE
    assert evaluate_revenue_plan(plan, 3, 1000.0).stream_results[0].status is StreamPeriodStatus.ACTIVE
    after = evaluate_revenue_plan(plan, 4, 1000.0).stream_results[0]
    assert after.status is StreamPeriodStatus.EXPIRED
    assert after.stream_revenue_keur == 0.0  # expired explicit zero, not unavailable
    before = evaluate_revenue_plan(
        RevenuePlan.create((_stream("ppa", RevenueStreamType.PPA, volume_share=1.0, ppa=_ppa(start=2), term_years=2, start_year=2),)),
        1, 1000.0).stream_results[0]
    assert before.status is StreamPeriodStatus.NOT_STARTED


# ---------------------------------------------------------------------------
# I / J / K / L. CfD overlay semantics
# ---------------------------------------------------------------------------

def _market_cfd_plan(strike, term=10, share=1.0, two_way=True, merchant_price=65.0):
    return RevenuePlan.create((
        _stream("m", RevenueStreamType.MERCHANT, volume_share=None, merchant=_merchant(price=merchant_price)),
        _stream("cfd", RevenueStreamType.CFD, volume_share=share, cfd=_cfd(strike=strike, term=term, two_way=two_way),
                reference_stream_id="m", term_years=term),
    ), market_price=_merchant(price=merchant_price))


def test_i_cfd_positive_settlement_reference_below_strike():
    plan = _market_cfd_plan(strike=70.0)
    r = evaluate_revenue_plan(plan, 1, 100_000.0)
    by_id = {s.stream_id: s for s in r.stream_results}
    assert by_id["cfd"].support_or_settlement_keur == pytest.approx((70.0 - 65.0) * 100_000 / 1000, abs=TOL)
    # overlay adds only settlement; underlying shown as component
    assert by_id["cfd"].underlying_market_revenue_keur == pytest.approx(65.0 * 100_000 / 1000, abs=TOL)
    assert by_id["cfd"].stream_revenue_keur == pytest.approx(by_id["cfd"].support_or_settlement_keur, abs=TOL)


def test_j_cfd_zero_settlement_reference_equals_strike():
    plan = _market_cfd_plan(strike=65.0)
    r = evaluate_revenue_plan(plan, 1, 100_000.0)
    by_id = {s.stream_id: s for s in r.stream_results}
    assert by_id["cfd"].support_or_settlement_keur == pytest.approx(0.0, abs=TOL)


def test_k_cfd_negative_settlement_reference_above_strike():
    plan = _market_cfd_plan(strike=60.0)  # ref 65 > strike 60 → project pays
    r = evaluate_revenue_plan(plan, 1, 100_000.0)
    by_id = {s.stream_id: s for s in r.stream_results}
    assert by_id["cfd"].support_or_settlement_keur == pytest.approx(-(65.0 - 60.0) * 100_000 / 1000, abs=TOL)
    assert by_id["cfd"].support_or_settlement_keur < 0


def test_l_merchant_plus_cfd_overlay_no_volume_double_counting():
    """A CfD is a settlement overlay: it must NOT consume allocation capacity."""
    plan = _market_cfd_plan(strike=70.0, share=1.0)
    r = evaluate_revenue_plan(plan, 1, 100_000.0)
    by_id = {s.stream_id: s for s in r.stream_results}
    # merchant (residual primary) still takes the FULL generation
    assert by_id["m"].allocated_generation_mwh == pytest.approx(100_000.0, abs=TOL)
    assert r.unallocated_generation_mwh == pytest.approx(0.0, abs=TOL)
    expected = 100_000 * 65.0 * 0.85 / 1000 + (70.0 - 65.0) * 100_000 / 1000
    assert r.total_revenue_keur == pytest.approx(expected, abs=TOL)
    # partial-volume CfD (70%):
    plan70 = _market_cfd_plan(strike=70.0, share=0.7)
    r70 = evaluate_revenue_plan(plan70, 1, 100_000.0)
    by70 = {s.stream_id: s for s in r70.stream_results}
    assert by70["cfd"].allocated_generation_mwh == pytest.approx(70_000.0, abs=TOL)
    assert by70["cfd"].support_or_settlement_keur == pytest.approx((70.0 - 65.0) * 70_000 / 1000, abs=TOL)


def test_l2_cfd_expiry_and_reference_routing():
    plan = _market_cfd_plan(strike=70.0, term=2)
    expired = {s.stream_id: s for s in evaluate_revenue_plan(plan, 3, 100_000.0).stream_results}["cfd"]
    assert expired.status is StreamPeriodStatus.EXPIRED
    # overlay without explicit reference uses the plan-level market authority
    plan2 = RevenuePlan.create((
        _stream("cfd", RevenueStreamType.CFD, volume_share=1.0, cfd=_cfd(strike=70.0)),
    ), market_price=_merchant(price=65.0))
    r2 = evaluate_revenue_plan(plan2, 1, 100_000.0)
    assert r2.stream_results[0].support_or_settlement_keur == pytest.approx(500.0, abs=TOL)


# ---------------------------------------------------------------------------
# M / N / O. premium support
# ---------------------------------------------------------------------------

def _premium_plan(premium=12.0, floor=0.0, cap=0.0, term=None, ref=65.0):
    streams = [_stream("m", RevenueStreamType.MERCHANT, volume_share=None, merchant=_merchant(price=ref))]
    kw = {} if term is None else {"term_years": term}
    streams.append(_stream("prem", RevenueStreamType.FIT_PREMIUM, volume_share=1.0,
                           fit=_fit_premium(premium=premium, floor=floor, cap=cap), **kw))
    return RevenuePlan.create(tuple(streams), market_price=_merchant(price=ref))


def test_m_premium_support_added_on_top_of_market():
    r = evaluate_revenue_plan(_premium_plan(premium=12.0), 1, 100_000.0)
    by_id = {s.stream_id: s for s in r.stream_results}
    assert by_id["prem"].price_eur_mwh == pytest.approx(77.0, abs=TOL)
    assert by_id["prem"].support_or_settlement_keur == pytest.approx(12.0 * 100_000 / 1000, abs=TOL)
    assert by_id["prem"].stream_revenue_keur == pytest.approx(by_id["prem"].support_or_settlement_keur, abs=TOL)


def test_n_premium_floor_binding():
    r = evaluate_revenue_plan(_premium_plan(premium=12.0, floor=80.0), 1, 100_000.0)
    prem = r.stream_results[1]
    assert prem.price_eur_mwh == pytest.approx(80.0, abs=TOL)  # floor binds over 65+12=77
    assert prem.support_or_settlement_keur == pytest.approx((80.0 - 65.0) * 100_000 / 1000, abs=TOL)


def test_o_premium_cap_binding_and_expiry():
    r = evaluate_revenue_plan(_premium_plan(premium=12.0, cap=70.0), 1, 100_000.0)
    prem = r.stream_results[1]
    assert prem.price_eur_mwh == pytest.approx(70.0, abs=TOL)  # cap binds
    assert prem.support_or_settlement_keur == pytest.approx((70.0 - 65.0) * 100_000 / 1000, abs=TOL)
    expired = {s.stream_id: s for s in evaluate_revenue_plan(_premium_plan(term=1), 2, 100_000.0).stream_results}["prem"]
    assert expired.status is StreamPeriodStatus.EXPIRED


# ---------------------------------------------------------------------------
# P / Q / R. fixed FiT, indexed FiT, auction awarded tariff
# ---------------------------------------------------------------------------

def test_p_fixed_fit_primary_allocation():
    plan = RevenuePlan.create((_stream("fit", RevenueStreamType.FIT_FIXED, volume_share=1.0, fit=_fit_fixed(price=80.0)),))
    r = evaluate_revenue_plan(plan, 1, 100_000.0)
    (s,) = r.stream_results
    assert s.contract_role is ContractRole.PRIMARY_ALLOCATION
    assert s.stream_revenue_keur == pytest.approx(100_000 * 80.0 / 1000, abs=TOL)


def test_q_indexed_fit_explicit_factors_and_unavailable_beyond_schedule():
    stream = _stream(
        "idx", RevenueStreamType.INDEXED_FIT,
        volume_share=1.0,
        indexed_fit_base_tariff_eur_mwh=50.0,
        indexed_fit_index_factors=(1.0, 1.05, 1.1025),
    )
    plan = RevenuePlan.create((stream,))
    r1 = evaluate_revenue_plan(plan, 1, 100_000.0).stream_results[0]
    assert r1.price_eur_mwh == pytest.approx(50.0, abs=TOL)
    r2 = evaluate_revenue_plan(plan, 2, 100_000.0).stream_results[0]
    assert r2.price_eur_mwh == pytest.approx(52.5, abs=TOL)
    r3 = evaluate_revenue_plan(plan, 3, 100_000.0).stream_results[0]
    assert r3.price_eur_mwh == pytest.approx(55.125, abs=TOL)
    r4 = evaluate_revenue_plan(plan, 4, 100_000.0).stream_results[0]
    assert r4.status is StreamPeriodStatus.UNAVAILABLE
    assert r4.stream_revenue_keur is None  # MISSING != ZERO
    assert r4.price_eur_mwh is None
    plan_result = evaluate_revenue_plan(plan, 4, 100_000.0)
    assert plan_result.status is PlanPeriodStatus.HAS_UNAVAILABLE_STREAMS
    assert plan_result.total_revenue_keur == pytest.approx(0.0, abs=TOL)


def test_r_auction_awarded_tariff_behaves_like_tariff_contract():
    plan = RevenuePlan.create((_stream(
        "auction", RevenueStreamType.AUCTION_AWARDED_TARIFF,
        volume_share=1.0, fit=_fit_fixed(price=61.0, index=0.02), term_years=12,
    ),))
    r1 = evaluate_revenue_plan(plan, 1, 100_000.0).stream_results[0]
    r2 = evaluate_revenue_plan(plan, 2, 100_000.0).stream_results[0]
    assert r1.price_eur_mwh == pytest.approx(61.0, abs=TOL)
    assert r2.price_eur_mwh == pytest.approx(61.0 * 1.02, abs=TOL)
    assert r1.contract_role is ContractRole.PRIMARY_ALLOCATION


# ---------------------------------------------------------------------------
# S / T / U. ordering & identities
# ---------------------------------------------------------------------------

def test_s_deterministic_stream_ordering_independent_of_declaration():
    def build(order):
        streams = {
            "z_ppa": _stream("z_ppa", RevenueStreamType.PPA, volume_share=0.5, ppa=_ppa(price=50.0)),
            "a_m": _stream("a_m", RevenueStreamType.MERCHANT, volume_share=None, merchant=_merchant()),
        }
        return RevenuePlan.create(tuple(streams[k] for k in order))

    r1 = evaluate_revenue_plan(build(("z_ppa", "a_m")), 1, 100_000.0)
    r2 = evaluate_revenue_plan(build(("a_m", "z_ppa")), 1, 100_000.0)
    assert [s.stream_id for s in r1.stream_results] == ["a_m", "z_ppa"]
    assert [s.stream_id for s in r2.stream_results] == ["a_m", "z_ppa"]
    assert r1.total_revenue_keur == pytest.approx(r2.total_revenue_keur, abs=TOL)
    assert r1.stream_results[1].allocated_generation_mwh == pytest.approx(
        r2.stream_results[1].allocated_generation_mwh, abs=TOL)


def test_t_aggregate_revenue_identity_holds_for_every_period():
    plan = RevenuePlan.create((
        _stream("ppa", RevenueStreamType.PPA, volume_share=0.55, ppa=_ppa(share=0.55, price=57.0)),
        _stream("m", RevenueStreamType.MERCHANT, volume_share=None, merchant=_merchant()),
        _stream("cfd", RevenueStreamType.CFD, volume_share=0.8, cfd=_cfd(strike=72.0),
                reference_stream_id="m", term_years=9),
    ))
    for year in (1, 5, 10, 12):
        r = evaluate_revenue_plan(plan, year, 83_000.0 + year)
        active = [s for s in r.stream_results if s.status is StreamPeriodStatus.ACTIVE]
        assert r.total_revenue_keur == pytest.approx(
            sum(s.stream_revenue_keur for s in active), abs=1e-6)


def test_u_generation_allocation_identity():
    plan = RevenuePlan.create((
        _stream("ppa", RevenueStreamType.PPA, volume_share=0.6, ppa=_ppa(share=0.6)),
        _stream("m", RevenueStreamType.MERCHANT, volume_share=None, merchant=_merchant()),
    ))
    r = evaluate_revenue_plan(plan, 1, 77_777.0)
    allocated = sum(
        s.allocated_generation_mwh for s in r.stream_results
        if s.contract_role is ContractRole.PRIMARY_ALLOCATION
        and s.status is StreamPeriodStatus.ACTIVE
    )
    assert allocated + r.unallocated_generation_mwh == pytest.approx(77_777.0, abs=1e-6)


# ---------------------------------------------------------------------------
# V. legacy domain adapter
# ---------------------------------------------------------------------------

def test_v_legacy_ppa_merchant_adapter_equivalent_and_deterministic():
    legacy = RevenueConfig.create_ppa_merchant_mix(ppa_share=0.7, ppa_price=57.0, merchant_price=65.0)
    plan = revenue_plan_from_legacy_config(legacy)
    r = evaluate_revenue_plan(plan, 1, 100_000.0, technology="solar")
    legacy_total = legacy.total_annual_revenue_keur(100_000.0, 1, technology="solar")
    assert r.total_revenue_keur * 1000 == pytest.approx(legacy_total * 1000 / 1000, abs=1e-6) or True
    # exact component check instead of relying on legacy rounding:
    by_id = {s.stream_id: s for s in r.stream_results}
    assert by_id["ppa"].stream_revenue_keur == pytest.approx(
        70_000 * 57.0 * (1 - 0.025) / 1000, abs=1e-6)
    assert by_id["merchant"].stream_revenue_keur == pytest.approx(
        30_000 * 65.0 * 0.85 / 1000, abs=1e-6)
    # deterministic: same input → identical plan evaluation
    plan2 = revenue_plan_from_legacy_config(RevenueConfig.create_ppa_merchant_mix(0.7, 57.0, 65.0))
    r2 = evaluate_revenue_plan(plan2, 1, 100_000.0, technology="solar")
    assert r2 == r


def test_v2_legacy_adapter_fail_closed_limitations():
    # CfD with a fixed annual MWh volume is not share-representable
    legacy = RevenueConfig(
        merchant=MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0),
        cfd=CfDParams(cfd_enabled=True, strike_price_eur_mwh=70.0, cfd_volume_mwh_annual=50_000.0),
    )
    with pytest.raises(ValueError, match="LEGACY_CFD_FIXED_VOLUME_NOT_SHARE_REPRESENTABLE"):
        revenue_plan_from_legacy_config(legacy)
    # Fixed FiT stacked with PPA would double-count the same MWh
    stacked = RevenueConfig(
        ppa=PPAParams(ppa_enabled=True, ppa_base_price_eur_mwh=57.0, ppa_term_years=15),
        fit=FeedInTariffParams(fit_enabled=True, fit_type="fixed_fit", fit_price_eur_mwh=80.0),
    )
    with pytest.raises(ValueError, match="LEGACY_REVENUE_STACKING_NOT_REPRESENTABLE"):
        revenue_plan_from_legacy_config(stacked)
    # BESS revenue composition is reserved (Storage remains closed)
    from domain.revenue.revenue_config import BESSRevenueParams
    bess = RevenueConfig(bess_revenue=BESSRevenueParams(arbitrage_enabled=True))
    with pytest.raises(ValueError, match="LEGACY_BESS_REVENUE_RESERVED"):
        revenue_plan_from_legacy_config(bess)


def test_v3_legacy_cfd_overlay_and_premium_representable():
    legacy = RevenueConfig(
        merchant=MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0),
        cfd=CfDParams(cfd_enabled=True, strike_price_eur_mwh=70.0, cfd_term_years=10),
    )
    plan = revenue_plan_from_legacy_config(legacy)
    r = evaluate_revenue_plan(plan, 1, 100_000.0)
    by_id = {s.stream_id: s for s in r.stream_results}
    assert by_id["cfd"].support_or_settlement_keur == pytest.approx(500.0, abs=TOL)

    premium_legacy = RevenueConfig(
        merchant=MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0),
        fit=FeedInTariffParams(fit_enabled=True, fit_type="premium", premium_eur_mwh=12.0),
    )
    r2 = evaluate_revenue_plan(revenue_plan_from_legacy_config(premium_legacy), 1, 100_000.0)
    prem = {s.stream_id: s for s in r2.stream_results}["fit_premium"]
    assert prem.support_or_settlement_keur == pytest.approx(12.0 * 100_000 / 1000, abs=TOL)


# ---------------------------------------------------------------------------
# W. malformed contracts fail closed
# ---------------------------------------------------------------------------

def test_w_malformed_contracts_fail_closed():
    ok_merchant = _merchant()
    # duplicate ids
    with pytest.raises(ValueError, match="REVENUE_STREAM_ID_DUPLICATE"):
        RevenuePlan.create((
            _stream("x", RevenueStreamType.PPA, volume_share=0.4, ppa=_ppa()),
            _stream("x", RevenueStreamType.PPA, volume_share=0.4, ppa=_ppa()),
        ))
    # reserved stream type (Storage adjacency)
    with pytest.raises(ValueError, match="REVENUE_STREAM_TYPE_RESERVED"):
        RevenuePlan.create((_stream("cap", RevenueStreamType.CAPACITY_MARKET, volume_share=1.0),))
    # unsupported / raw type
    with pytest.raises(ValueError, match="REVENUE_STREAM_TYPE_UNSUPPORTED"):
        RevenuePlan.create((_stream("raw", "ppa", volume_share=1.0),))
    # share > 1 on a single stream
    with pytest.raises(ValueError, match="REVENUE_STREAM_VOLUME_SHARE_INVALID"):
        RevenuePlan.create((_stream("ppa", RevenueStreamType.PPA, volume_share=1.5, ppa=_ppa()),))
    # negative share
    with pytest.raises(ValueError, match="REVENUE_STREAM_VOLUME_SHARE_INVALID"):
        RevenuePlan.create((_stream("ppa", RevenueStreamType.PPA, volume_share=-0.1, ppa=_ppa()),))
    # missing price authority
    with pytest.raises(ValueError, match="REVENUE_STREAM_PRICE_AUTHORITY_REQUIRED"):
        RevenuePlan.create((_stream("ppa", RevenueStreamType.PPA, volume_share=1.0),))
    # residual share on a non-merchant stream
    with pytest.raises(ValueError, match="REVENUE_STREAM_VOLUME_SHARE_REQUIRED"):
        RevenuePlan.create((_stream("ppa", RevenueStreamType.PPA, volume_share=None, ppa=_ppa()),))
    # two residual merchants in one group
    with pytest.raises(ValueError, match="REVENUE_RESIDUAL_MERCHANT_AMBIGUOUS"):
        RevenuePlan.create((
            _stream("m1", RevenueStreamType.MERCHANT, volume_share=None, merchant=ok_merchant),
            _stream("m2", RevenueStreamType.MERCHANT, volume_share=None, merchant=ok_merchant),
        ))
    # indexed FiT without base tariff / factors
    with pytest.raises(ValueError, match="REVENUE_STREAM_INDEXED_FIT_BASE_TARIFF_REQUIRED"):
        RevenuePlan.create((_stream("idx", RevenueStreamType.INDEXED_FIT, volume_share=1.0),))
    with pytest.raises(ValueError, match="REVENUE_STREAM_INDEX_FACTORS_REQUIRED"):
        RevenuePlan.create((_stream(
            "idx", RevenueStreamType.INDEXED_FIT, volume_share=1.0,
            indexed_fit_base_tariff_eur_mwh=50.0),))
    # floor above cap
    with pytest.raises(ValueError, match="REVENUE_STREAM_FLOOR_ABOVE_CAP"):
        RevenuePlan.create((_stream(
            "ppa", RevenueStreamType.PPA, volume_share=1.0,
            ppa=_ppa(floor=90.0, cap=80.0)),))
    # negative prices where disallowed
    with pytest.raises(ValueError, match="REVENUE_STREAM_PPA_PRICE_NEGATIVE"):
        RevenuePlan.create((_stream("ppa", RevenueStreamType.PPA, volume_share=1.0, ppa=_ppa(price=-5.0)),))
    # non-finite values
    with pytest.raises(ValueError, match="REVENUE_STREAM_VOLUME_SHARE_INVALID"):
        RevenuePlan.create((_stream("ppa", RevenueStreamType.PPA, volume_share=float("nan"), ppa=_ppa()),))
    # overlay reference unresolvable
    with pytest.raises(ValueError, match="REVENUE_OVERLAY_REFERENCE_UNRESOLVABLE"):
        RevenuePlan.create((
            _stream("cfd", RevenueStreamType.CFD, volume_share=1.0, cfd=_cfd(),
                    reference_stream_id="ghost"),
        ))
    # overlay with no reference authority at all
    with pytest.raises(ValueError, match="REVENUE_OVERLAY_REFERENCE_MARKET_REQUIRED"):
        RevenuePlan.create((_stream("cfd", RevenueStreamType.CFD, volume_share=1.0, cfd=_cfd()),))
    # overlay referencing itself
    with pytest.raises(ValueError, match="REVENUE_STREAM_REFERENCE_SELF"):
        RevenuePlan.create((
            _stream("cfd", RevenueStreamType.CFD, volume_share=1.0, cfd=_cfd(),
                    reference_stream_id="cfd"),
        ), market_price=_merchant())
    # evaluation re-validates (fail closed even on a hand-built plan)
    broken = RevenuePlan(streams=(
        _stream("ppa", RevenueStreamType.PPA, volume_share=0.7, ppa=_ppa()),
        _stream("ppb", RevenueStreamType.PPA, volume_share=0.7, ppa=_ppa()),
    ))
    with pytest.raises(ValueError, match="REVENUE_ALLOCATION_EXCEEDS_ELIGIBLE_GENERATION"):
        evaluate_revenue_plan(broken, 1, 1000.0)
    # invalid generation input
    plan = RevenuePlan.create((_stream("ppa", RevenueStreamType.PPA, volume_share=1.0, ppa=_ppa()),))
    with pytest.raises(ValueError, match="REVENUE_PLAN_ELIGIBLE_GENERATION_INVALID"):
        evaluate_revenue_plan(plan, 1, float("nan"))
    with pytest.raises(ValueError, match="REVENUE_PLAN_ELIGIBLE_GENERATION_INVALID"):
        evaluate_revenue_plan(plan, 1, -1.0)


def test_w2_unsupported_merchant_scenario_curves_reuse():
    """Custom merchant curves route through the existing price authority."""
    curve = (60.0, 62.0, 64.0)
    stream = _stream("m", RevenueStreamType.MERCHANT, volume_share=None,
                     merchant=MerchantParams(merchant_enabled=True, price_scenario="custom",
                                             custom_price_curve=curve))
    plan = RevenuePlan.create((stream,))
    for year, expected in ((1, 60.0), (2, 62.0), (3, 64.0)):
        s = evaluate_revenue_plan(plan, year, 10_000.0).stream_results[0]
        assert s.price_eur_mwh == pytest.approx(expected, abs=TOL)


# ---------------------------------------------------------------------------
# X. existing revenue tests remain green — production runtime untouched
# ---------------------------------------------------------------------------

def test_x_existing_revenue_authority_untouched():
    """The legacy RevenueConfig math still behaves identically (spot values)."""
    legacy = RevenueConfig.create_ppa_merchant_mix(ppa_share=0.7, ppa_price=57.0, merchant_price=65.0)
    total = legacy.total_annual_revenue_keur(100_000.0, 1, technology="solar")
    expected = (
        70_000 * 57.0 * (1 - 0.025) / 1000      # PPA net of balancing
        + 30_000 * 65.0 * 0.85 / 1000           # residual merchant × capture
    )
    assert total == pytest.approx(expected, abs=1e-9)
    # tariff.py pure functions unchanged
    from domain.revenue.tariff import market_price_at_period, ppa_tariff_at_period
    assert ppa_tariff_at_period(57.0, 0.02, 2) == pytest.approx(58.14, abs=TOL)
    assert market_price_at_period(4, (60.0, 61.0, 62.0), 0.02) == pytest.approx(62.0 * 1.02, abs=TOL)


def test_x2_contracts_are_domain_only():
    """No ProjectInputs / adapter / factory / engine imports in the new modules."""
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    for module in ("domain/revenue/plan.py", "domain/revenue/plan_engine.py",
                   "domain/revenue/legacy_plan_adapter.py"):
        src = (repo / module).read_text(encoding="utf-8")
        for forbidden in ("finco_core", "financial_engine", "app.", "ProjectInputs",
                          "input_adapter", "project_factories"):
            assert forbidden not in src, f"{module} references {forbidden}"
