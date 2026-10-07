"""Model V2 Revenue Correction A regression matrix (A–Q).

Period-allocation, lifecycle-authority, contract-alignment, unavailable-
total, legacy-equivalence and numeric/period validation corrections.
"""
from __future__ import annotations

import pytest

from domain.revenue.plan import (
    RevenueAllocationGroup,
    RevenuePlan,
    RevenueStream,
    RevenueStreamType,
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
from test_model_v2_revenue_plan import (
    TOL,
    _cfd,
    _merchant,
    _ppa,
    _stream,
)


def _fit_premium(premium=12.0, floor=0.0, cap=0.0, term=0):
    return FeedInTariffParams(fit_enabled=True, fit_type="premium",
                              premium_eur_mwh=premium,
                              premium_floor_eur_mwh=floor,
                              premium_cap_eur_mwh=cap,
                              fit_term_years=term)


def _fit_fixed(price=80.0, term=0, index=0.0):
    return FeedInTariffParams(fit_enabled=True, fit_type="fixed_fit",
                              fit_price_eur_mwh=price, fit_term_years=term,
                              fit_index=index)


def _delayed_ppa_plan(share=0.6, start=2, term=2, price=57.0):
    return RevenuePlan.create((
        _stream("ppa", RevenueStreamType.PPA, volume_share=share,
                ppa=_ppa(share=share, price=price),
                start_year=start, term_years=term),
        _stream("m", RevenueStreamType.MERCHANT, volume_share=None,
                merchant=_merchant()),
    ))


def test_ca_a_merchant_holds_100pct_before_delayed_ppa_starts():
    """CA-A: residual Merchant is 100% before the PPA contract begins."""
    r1 = evaluate_revenue_plan(_delayed_ppa_plan(), 1, 100_000.0, technology="solar")
    by_id = {s.stream_id: s for s in r1.stream_results}
    assert by_id["ppa"].status is StreamPeriodStatus.NOT_STARTED
    assert by_id["m"].allocated_generation_mwh == pytest.approx(100_000.0, abs=TOL)
    assert r1.unallocated_generation_mwh == pytest.approx(0.0, abs=TOL)


def test_ca_b_merchant_residual_while_ppa_active():
    """CA-B: while the PPA is active the merchant takes the 40% residual."""
    for year in (2, 3):
        r = evaluate_revenue_plan(_delayed_ppa_plan(), year, 100_000.0, technology="solar")
        by_id = {s.stream_id: s for s in r.stream_results}
        assert by_id["ppa"].status is StreamPeriodStatus.ACTIVE
        assert by_id["ppa"].allocated_generation_mwh == pytest.approx(60_000.0, abs=TOL)
        assert by_id["m"].allocated_generation_mwh == pytest.approx(40_000.0, abs=TOL)


def test_ca_c_merchant_returns_to_100pct_after_ppa_expiry():
    """CA-C: after PPA expiry (start 2, term 2 → ends Y3) merchant is 100%."""
    r4 = evaluate_revenue_plan(_delayed_ppa_plan(), 4, 100_000.0, technology="solar")
    by_id = {s.stream_id: s for s in r4.stream_results}
    assert by_id["ppa"].status is StreamPeriodStatus.EXPIRED
    assert by_id["m"].allocated_generation_mwh == pytest.approx(100_000.0, abs=TOL)


def _sequential_ppa_plan():
    return RevenuePlan.create((
        _stream("ppa_a", RevenueStreamType.PPA, volume_share=0.7, ppa=_ppa(price=50.0),
                start_year=1, term_years=10),
        _stream("ppa_b", RevenueStreamType.PPA, volume_share=0.7, ppa=_ppa(price=55.0),
                start_year=11, term_years=10),
    ))


def test_ca_d_sequential_non_overlapping_ppas_accepted():
    """CA-D: 70% Y1-Y10 + 70% Y11-Y20 never overlap → valid."""
    runs = [evaluate_revenue_plan(_sequential_ppa_plan(), y, 100_000.0)
            for y in (1, 10, 11, 20)]
    for r in runs:
        # sequential contracts are accepted; exactly one PPA is active per year
        active = [s for s in r.stream_results if s.status is StreamPeriodStatus.ACTIVE]
        assert len(active) == 1
    assert runs[2].stream_results[1].price_eur_mwh == pytest.approx(55.0, abs=TOL)


def test_ca_e_partially_overlapping_shares_rejected_with_offending_year():
    """CA-E: 70% Y1-Y10 + 40% Y5-Y15 → 110% in Y5-Y10 → fail closed."""
    with pytest.raises(ValueError,
                       match="REVENUE_ALLOCATION_EXCEEDS_ELIGIBLE_GENERATION.*year 5"):
        RevenuePlan.create((
            _stream("ppa_a", RevenueStreamType.PPA, volume_share=0.7, ppa=_ppa(),
                    start_year=1, term_years=10),
            _stream("ppa_b", RevenueStreamType.PPA, volume_share=0.4, ppa=_ppa(),
                    start_year=5, term_years=11),
        ))


def test_ca_e2_exact_100pct_overlap_and_boundaries_accepted():
    """CA-E2: exactly 100% simultaneous coverage is valid; boundary years exact."""
    plan = RevenuePlan.create((
        _stream("ppa_a", RevenueStreamType.PPA, volume_share=0.6, ppa=_ppa(),
                start_year=1, term_years=10),
        _stream("ppa_b", RevenueStreamType.PPA, volume_share=0.4, ppa=_ppa(),
                start_year=5, term_years=10),
    ))
    for year in (5, 10):
        # Y5-Y10: 60% + 40% simultaneously → fully allocated
        assert evaluate_revenue_plan(plan, year, 100_000.0).status is PlanPeriodStatus.OK
    for year in (1, 11, 14):
        # outside the overlap window the plan genuinely leaves volume unsold
        r = evaluate_revenue_plan(plan, year, 100_000.0)
        assert r.status is PlanPeriodStatus.PARTIALLY_UNALLOCATED
    r4 = evaluate_revenue_plan(plan, 4, 100_000.0)
    r5 = evaluate_revenue_plan(plan, 5, 100_000.0)
    active4 = {s.stream_id for s in r4.stream_results if s.status is StreamPeriodStatus.ACTIVE}
    active5 = {s.stream_id for s in r5.stream_results if s.status is StreamPeriodStatus.ACTIVE}
    assert active4 == {"ppa_a"}
    assert active5 == {"ppa_a", "ppa_b"}
    r10 = evaluate_revenue_plan(plan, 10, 100_000.0)
    r11 = evaluate_revenue_plan(plan, 11, 100_000.0)
    active10 = {s.stream_id for s in r10.stream_results if s.status is StreamPeriodStatus.ACTIVE}
    active11 = {s.stream_id for s in r11.stream_results if s.status is StreamPeriodStatus.ACTIVE}
    assert "ppa_a" in active10 and "ppa_a" not in active11


def test_ca_f_delayed_start_cfd_settles_through_stream_term():
    """CA-F: the RevenueStream owns lifecycle. A CfD starting Y5 with a 10-year
    term settles through Y14 even when the nested CfDParams carries a shorter
    legacy term clock (which is neutralized)."""
    nested_short_term = CfDParams(cfd_enabled=True, strike_price_eur_mwh=70.0,
                                  cfd_term_years=3)
    plan = RevenuePlan.create((
        _stream("m", RevenueStreamType.MERCHANT, volume_share=None, merchant=_merchant()),
        _stream("cfd", RevenueStreamType.CFD, volume_share=1.0, cfd=nested_short_term,
                reference_stream_id="m", start_year=5, term_years=10),
    ), market_price=_merchant())
    before = evaluate_revenue_plan(plan, 4, 100_000.0)
    assert before.stream_results[0].status is StreamPeriodStatus.NOT_STARTED
    for year in (5, 9, 12, 14):
        r = evaluate_revenue_plan(plan, year, 100_000.0)
        cfd = {s.stream_id: s for s in r.stream_results}["cfd"]
        assert cfd.status is StreamPeriodStatus.ACTIVE, year
        assert cfd.support_or_settlement_keur == pytest.approx(
            (70.0 - 65.0) * 100_000 / 1000, abs=TOL), year
    after = evaluate_revenue_plan(plan, 15, 100_000.0)
    assert after.stream_results[0].status is StreamPeriodStatus.EXPIRED
    assert after.stream_results[0].stream_revenue_keur == 0.0


def test_ca_g_mismatched_fit_types_rejected():
    """CA-G: FIT_FIXED requires fixed_fit params; FIT_PREMIUM requires premium;
    awarded tariffs use the fixed-tariff authority."""
    with pytest.raises(ValueError, match="REVENUE_STREAM_FIT_TYPE_MISMATCH"):
        RevenuePlan.create((_stream("fit", RevenueStreamType.FIT_FIXED, volume_share=1.0,
                                    fit=_fit_premium(premium=12.0)),))
    with pytest.raises(ValueError, match="REVENUE_STREAM_FIT_TYPE_MISMATCH"):
        RevenuePlan.create((_stream("prem", RevenueStreamType.FIT_PREMIUM, volume_share=1.0,
                                    fit=_fit_fixed(price=80.0)),))
    with pytest.raises(ValueError, match="REVENUE_STREAM_AUCTION_AUTHORITY_MISMATCH"):
        RevenuePlan.create((_stream("a", RevenueStreamType.AUCTION_AWARDED_TARIFF,
                                    volume_share=1.0, fit=_fit_premium(premium=12.0)),))


def test_ca_h_unsupported_ppa_delivery_types_fail_closed():
    """CA-H: baseload/shaped/synthetic are not pay-as-produced — fail closed."""
    for ppa_type in ("baseload", "shaped", "synthetic"):
        params = PPAParams(ppa_enabled=True, ppa_base_price_eur_mwh=57.0,
                           ppa_type=ppa_type)
        with pytest.raises(ValueError, match="REVENUE_STREAM_PPA_TYPE_UNSUPPORTED"):
            RevenuePlan.create((_stream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                                        ppa=params),))


def test_ca_i_unavailable_single_stream_yields_unavailable_total_not_zero():
    """CA-I: an unavailable-only plan has total_revenue None, not 0."""
    stream = _stream("idx", RevenueStreamType.INDEXED_FIT, volume_share=1.0,
                     indexed_fit_base_tariff_eur_mwh=50.0,
                     indexed_fit_index_factors=(1.0,))
    plan = RevenuePlan.create((stream,))
    r = evaluate_revenue_plan(plan, 5, 100_000.0)  # beyond the factor schedule
    assert r.total_revenue_keur is None
    assert r.available_revenue_subtotal_keur == pytest.approx(0.0, abs=TOL)
    assert r.status is PlanPeriodStatus.HAS_UNAVAILABLE_STREAMS


def test_ca_i2_mixed_available_and_unavailable_does_not_expose_subtotal_as_total():
    plan = RevenuePlan.create((
        _stream("ppa", RevenueStreamType.PPA, volume_share=0.6,
                ppa=_ppa(share=0.6, price=57.0)),
        _stream("idx", RevenueStreamType.INDEXED_FIT, volume_share=0.4,
                indexed_fit_base_tariff_eur_mwh=50.0,
                indexed_fit_index_factors=(1.0,)),
    ))
    r = evaluate_revenue_plan(plan, 2, 100_000.0)
    assert r.total_revenue_keur is None
    expected_ppa = 60_000 * 57.0 / 1000
    assert r.available_revenue_subtotal_keur == pytest.approx(expected_ppa, abs=TOL)
    assert r.available_revenue_subtotal_keur != pytest.approx(
        expected_ppa + 50.0 * 40_000 / 1000)
    assert r.status is PlanPeriodStatus.HAS_UNAVAILABLE_STREAMS


def test_ca_j_true_economic_zero_remains_zero():
    """CA-J: an available stream priced at zero yields a legitimate 0.0 total."""
    plan = RevenuePlan.create((_stream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                                       ppa=_ppa(price=0.0)),))
    r = evaluate_revenue_plan(plan, 1, 100_000.0)
    assert r.total_revenue_keur is not None
    assert r.total_revenue_keur == pytest.approx(0.0, abs=TOL)
    assert r.status is PlanPeriodStatus.OK
    assert r.stream_results[0].status is StreamPeriodStatus.ACTIVE


def test_ca_k_l_legacy_ppa_merchant_exact_equivalence_across_periods():
    """CA-K/L: adapter == legacy for Y1, last active PPA year, first post-PPA
    year and a later merchant-only year — residual returns to 100%."""
    legacy_ppa = PPAParams(ppa_enabled=True, ppa_base_price_eur_mwh=57.0,
                           ppa_price_index=0.0, ppa_term_years=3,
                           ppa_volume_share=0.6, balancing_cost_pct=0.0)
    legacy = RevenueConfig(
        ppa=legacy_ppa,
        merchant=MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0,
                                price_escalation_annual=0.0),
    )
    plan = revenue_plan_from_legacy_config(legacy)
    for year in (1, 3, 4, 12):
        gen = 100_000.0 + year
        r = evaluate_revenue_plan(plan, year, gen, technology="solar")
        legacy_total = legacy.total_annual_revenue_keur(gen, year, technology="solar")
        assert r.total_revenue_keur == pytest.approx(legacy_total, abs=1e-9), year
    r4 = evaluate_revenue_plan(plan, 4, 100_000.0, technology="solar")
    merchant = {s.stream_id: s for s in r4.stream_results}["merchant"]
    assert merchant.allocated_generation_mwh == pytest.approx(100_000.0, abs=TOL)


def test_ca_m_legacy_premium_fails_closed():
    """CA-M: legacy premium stacking is not representable → fail closed."""
    legacy = RevenueConfig(
        merchant=MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0),
        fit=FeedInTariffParams(fit_enabled=True, fit_type="premium",
                               premium_eur_mwh=12.0),
    )
    with pytest.raises(ValueError, match="LEGACY_PREMIUM_NOT_EQUIVALENT"):
        revenue_plan_from_legacy_config(legacy)


def test_ca_n_legacy_merchant_plus_fixed_fit_stacking_fails_closed():
    """CA-N: Merchant + Fixed FiT monetizes the same MWh twice → fail closed."""
    legacy = RevenueConfig(
        merchant=MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0),
        fit=FeedInTariffParams(fit_enabled=True, fit_type="fixed_fit",
                               fit_price_eur_mwh=80.0),
    )
    with pytest.raises(ValueError, match="LEGACY_REVENUE_STACKING_NOT_REPRESENTABLE"):
        revenue_plan_from_legacy_config(legacy)


def test_ca_o_single_effective_allocation_group_enforced():
    """CA-O: multi-group generation is explicitly deferred (fail closed),
    group declarations are validated, and a single declared group works."""
    ok = RevenuePlan.create(
        (_stream("ppa", RevenueStreamType.PPA, volume_share=1.0, ppa=_ppa()),),
        allocation_groups=(RevenueAllocationGroup("generation"),),
    )
    assert evaluate_revenue_plan(ok, 1, 1000.0).status is PlanPeriodStatus.OK

    multi = RevenuePlan(streams=(
        _stream("ppa", RevenueStreamType.PPA, volume_share=1.0, ppa=_ppa(),
                allocation_group="gen_a"),
        _stream("m", RevenueStreamType.MERCHANT, volume_share=None,
                merchant=_merchant(), allocation_group="gen_b"),
    ))
    with pytest.raises(ValueError, match="REVENUE_PLAN_MULTIPLE_ALLOCATION_GROUPS_DEFERRED"):
        multi.validate()

    dup = RevenuePlan(
        streams=(_stream("ppa", RevenueStreamType.PPA, volume_share=1.0, ppa=_ppa()),),
        allocation_groups=(RevenueAllocationGroup("generation"),
                           RevenueAllocationGroup("generation")),
    )
    with pytest.raises(ValueError, match="REVENUE_ALLOCATION_GROUP_DUPLICATE"):
        dup.validate()

    undeclared = RevenuePlan(
        streams=(_stream("ppa", RevenueStreamType.PPA, volume_share=1.0, ppa=_ppa()),),
        allocation_groups=(RevenueAllocationGroup("other"),),
    )
    with pytest.raises(ValueError, match="REVENUE_ALLOCATION_GROUP_UNDECLARED"):
        undeclared.validate()

    unused = RevenuePlan(
        streams=(_stream("ppa", RevenueStreamType.PPA, volume_share=1.0, ppa=_ppa()),),
        allocation_groups=(RevenueAllocationGroup("generation"),
                           RevenueAllocationGroup("spare")),
    )
    with pytest.raises(ValueError, match="REVENUE_ALLOCATION_GROUP_UNUSED"):
        unused.validate()


def test_ca_p_nonfinite_economic_values_fail_closed():
    """CA-P: NaN / infinity in used economics fail closed."""
    bad_ppa = PPAParams(ppa_enabled=True, ppa_base_price_eur_mwh=float("nan"))
    with pytest.raises(ValueError, match="REVENUE_STREAM_VALUE_INVALID"):
        RevenuePlan.create((_stream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                                    ppa=bad_ppa),))
    bad_bal = PPAParams(ppa_enabled=True, ppa_base_price_eur_mwh=57.0,
                        balancing_cost_pct=1.5)
    with pytest.raises(ValueError, match="REVENUE_STREAM_VALUE_INVALID"):
        RevenuePlan.create((_stream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                                    ppa=bad_bal),))
    bad_capture = MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0,
                                 capture_rate_solar=float("inf"))
    with pytest.raises(ValueError, match="REVENUE_STREAM_VALUE_INVALID"):
        RevenuePlan.create((_stream("m", RevenueStreamType.MERCHANT, volume_share=None,
                                    merchant=bad_capture),))
    bad_curve = MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0,
                               price_scenario="custom",
                               custom_price_curve=(60.0, float("inf")))
    with pytest.raises(ValueError, match="REVENUE_STREAM_VALUE_INVALID"):
        RevenuePlan.create((_stream("m", RevenueStreamType.MERCHANT, volume_share=None,
                                    merchant=bad_curve),))
    bad_strike = CfDParams(cfd_enabled=True, strike_price_eur_mwh=float("nan"))
    with pytest.raises(ValueError, match="REVENUE_STREAM_VALUE_INVALID"):
        RevenuePlan.create((_stream("cfd", RevenueStreamType.CFD, volume_share=1.0,
                                    cfd=bad_strike),), market_price=_merchant())
    with pytest.raises(ValueError, match="REVENUE_STREAM_VALUE_INVALID"):
        RevenuePlan.create((_stream(
            "idx", RevenueStreamType.INDEXED_FIT, volume_share=1.0,
            indexed_fit_base_tariff_eur_mwh=50.0,
            indexed_fit_index_factors=(1.0, float("nan"))),))


def test_ca_q_start_year_term_and_period_validation():
    """CA-Q: start_year integer >= 1; term 0 invalid (None = unlimited);
    evaluation year must be a positive integer."""
    for bad_start in (0, -1, 1.5, True):
        with pytest.raises(ValueError, match="REVENUE_STREAM_START_INVALID"):
            RevenuePlan.create((_stream(
                "ppa", RevenueStreamType.PPA, volume_share=1.0, ppa=_ppa(),
                start_year=bad_start),))
    with pytest.raises(ValueError, match="REVENUE_STREAM_TERM_INVALID"):
        RevenuePlan.create((_stream(
            "ppa", RevenueStreamType.PPA, volume_share=1.0, ppa=_ppa(), term_years=0),))
    plan = RevenuePlan.create((_stream(
        "ppa", RevenueStreamType.PPA, volume_share=1.0, ppa=_ppa(), term_years=None),))
    assert evaluate_revenue_plan(plan, 500, 1000.0).status is PlanPeriodStatus.OK
    for bad_year in (0, -1, 1.5, True):
        with pytest.raises(ValueError, match="REVENUE_PLAN_YEAR_INVALID"):
            evaluate_revenue_plan(plan, bad_year, 1000.0)


def test_ca_overlay_reference_structurally_validated():
    """Overlay references must point at a merchant market authority at plan
    validation time, not be discovered during evaluation."""
    with pytest.raises(ValueError, match="REVENUE_OVERLAY_REFERENCE_NOT_A_MARKET_AUTHORITY"):
        RevenuePlan.create((
            _stream("ppa", RevenueStreamType.PPA, volume_share=0.5, ppa=_ppa()),
            _stream("cfd", RevenueStreamType.CFD, volume_share=0.5, cfd=_cfd(),
                    reference_stream_id="ppa"),
        ), market_price=_merchant())
    disabled = MerchantParams(merchant_enabled=False, base_price_eur_mwh=65.0)
    with pytest.raises(ValueError, match="REVENUE_OVERLAY_REFERENCE_NOT_A_MARKET_AUTHORITY"):
        RevenuePlan.create((
            _stream("m", RevenueStreamType.MERCHANT, volume_share=None, merchant=disabled),
            _stream("cfd", RevenueStreamType.CFD, volume_share=1.0, cfd=_cfd(),
                    reference_stream_id="m"),
        ))
