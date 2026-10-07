"""Model V2 Revenue Correction C regression matrix.

Merchant authority consistency (stream-level scenario contract through the
ONE shared validator), indexed-field exclusivity, and the locked custom-
curve post-horizon policy.
"""
from __future__ import annotations

import pytest

from domain.revenue.plan import RevenuePlan, RevenueStream, RevenueStreamType
from domain.revenue.plan_engine import evaluate_revenue_plan
from domain.revenue.revenue_config import (
    CfDParams,
    FeedInTariffParams,
    MerchantParams,
    PPAParams,
)
from test_model_v2_revenue_plan import (
    TOL,
    _cfd,
    _fit_fixed,
    _merchant,
    _ppa,
    _stream,
)


# ---------------------------------------------------------------------------
# A / B / C / D — merchant stream scenario contract (shared validator)
# ---------------------------------------------------------------------------

def test_cc_a_merchant_stream_unknown_scenario_fails_closed():
    """CC-A: an unknown price_scenario on a MERCHANT stream fails closed —
    no silent fall-through to the base-price path."""
    with pytest.raises(ValueError, match="REVENUE_STREAM_MARKET_SCENARIO_UNSUPPORTED"):
        RevenuePlan.create((_stream(
            "m", RevenueStreamType.MERCHANT, volume_share=None,
            merchant=MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0,
                                    price_scenario="mega_bull")),))


def test_cc_b_merchant_stream_custom_with_empty_curve_fails_closed():
    """CC-B: custom scenario with an empty curve fails closed on a MERCHANT
    stream — no silent fallback to base price."""
    with pytest.raises(ValueError, match="REVENUE_STREAM_MARKET_CUSTOM_CURVE_REQUIRED"):
        RevenuePlan.create((_stream(
            "m", RevenueStreamType.MERCHANT, volume_share=None,
            merchant=MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0,
                                    price_scenario="custom",
                                    custom_price_curve=())),))


def test_cc_c_merchant_stream_base_scenario_accepted():
    plan = RevenuePlan.create((_stream(
        "m", RevenueStreamType.MERCHANT, volume_share=None,
        merchant=_merchant(price=65.0)),))
    r = evaluate_revenue_plan(plan, 1, 100_000.0, technology="solar")
    assert r.total_revenue_keur == pytest.approx(100_000 * 65.0 * 0.85 / 1000, abs=TOL)


def test_cc_d_merchant_stream_custom_curve_accepted():
    plan = RevenuePlan.create((_stream(
        "m", RevenueStreamType.MERCHANT, volume_share=None,
        merchant=MerchantParams(merchant_enabled=True, price_scenario="custom",
                                custom_price_curve=(70.0, 72.0),
                                capture_rate_solar=0.85)),))
    r1 = evaluate_revenue_plan(plan, 1, 100_000.0, technology="solar").stream_results[0]
    r2 = evaluate_revenue_plan(plan, 2, 100_000.0, technology="solar").stream_results[0]
    assert r1.price_eur_mwh == pytest.approx(70.0, abs=TOL)
    assert r2.price_eur_mwh == pytest.approx(72.0, abs=TOL)


def test_cc_e_merchant_stream_nonfinite_economics_still_fail_closed():
    """The shared validator preserves Correction B numeric hardening."""
    with pytest.raises(ValueError, match="REVENUE_STREAM_VALUE_INVALID"):
        RevenuePlan.create((_stream(
            "m", RevenueStreamType.MERCHANT, volume_share=None,
            merchant=MerchantParams(merchant_enabled=True, base_price_eur_mwh=float("inf"))),))
    with pytest.raises(ValueError, match="REVENUE_STREAM_VALUE_INVALID"):
        RevenuePlan.create((_stream(
            "m", RevenueStreamType.MERCHANT, volume_share=None,
            merchant=MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0,
                                    capture_rate_wind=1.5)),))


# ---------------------------------------------------------------------------
# E / F / G / H — indexed-field exclusivity
# ---------------------------------------------------------------------------

def test_cc_e_indexed_tariff_on_ppa_stream_fails_closed():
    with pytest.raises(ValueError, match="REVENUE_STREAM_INDEXED_FIELDS_ON_NON_INDEXED"):
        RevenuePlan.create((_stream(
            "ppa", RevenueStreamType.PPA, volume_share=1.0, ppa=_ppa(),
            indexed_fit_base_tariff_eur_mwh=50.0),))


def test_cc_f_indexed_factors_on_merchant_stream_fails_closed():
    with pytest.raises(ValueError, match="REVENUE_STREAM_INDEXED_FIELDS_ON_NON_INDEXED"):
        RevenuePlan.create((_stream(
            "m", RevenueStreamType.MERCHANT, volume_share=None, merchant=_merchant(),
            indexed_fit_index_factors=(1.0,)),))


def test_cc_g_indexed_fields_on_cfd_stream_fail_closed():
    with pytest.raises(ValueError, match="REVENUE_STREAM_INDEXED_FIELDS_ON_NON_INDEXED"):
        RevenuePlan.create((_stream(
            "cfd", RevenueStreamType.CFD, volume_share=1.0, cfd=_cfd(),
            indexed_fit_base_tariff_eur_mwh=50.0,
            indexed_fit_index_factors=(1.0,)),), market_price=_merchant())
    with pytest.raises(ValueError, match="REVENUE_STREAM_INDEXED_FIELDS_ON_NON_INDEXED"):
        RevenuePlan.create((_stream(
            "fit", RevenueStreamType.FIT_FIXED, volume_share=1.0,
            fit=_fit_fixed(), indexed_fit_index_factors=(1.0,)),))
    with pytest.raises(ValueError, match="REVENUE_STREAM_INDEXED_FIELDS_ON_NON_INDEXED"):
        RevenuePlan.create((_stream(
            "prem", RevenueStreamType.FIT_PREMIUM, volume_share=1.0,
            fit=FeedInTariffParams(fit_enabled=True, fit_type="premium",
                                   premium_eur_mwh=12.0),
            indexed_fit_index_factors=(1.0,)),))


def test_cc_h_valid_indexed_fit_still_accepted():
    """CC-H: a well-formed INDEXED_FIT stream (indexed fields only) remains
    valid — the exclusivity rule must not regress the valid path."""
    plan = RevenuePlan.create((_stream(
        "idx", RevenueStreamType.INDEXED_FIT, volume_share=1.0,
        indexed_fit_base_tariff_eur_mwh=50.0,
        indexed_fit_index_factors=(1.0, 1.05),
    ),))
    r1 = evaluate_revenue_plan(plan, 1, 100_000.0).stream_results[0]
    r2 = evaluate_revenue_plan(plan, 2, 100_000.0).stream_results[0]
    assert r1.price_eur_mwh == pytest.approx(50.0, abs=TOL)
    assert r2.price_eur_mwh == pytest.approx(52.5, abs=TOL)


# ---------------------------------------------------------------------------
# I — plan-level market authority validation preserved
# ---------------------------------------------------------------------------

def test_cc_i_plan_level_market_authority_validation_preserved():
    """CC-I: the shared validator kept every Correction B plan-level rule."""
    with pytest.raises(ValueError, match="REVENUE_PLAN_MARKET_SCENARIO_UNSUPPORTED"):
        RevenuePlan.create((
            _stream("cfd", RevenueStreamType.CFD, volume_share=1.0, cfd=_cfd()),
        ), market_price=MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0,
                                       price_scenario="mega_bull"))
    with pytest.raises(ValueError, match="REVENUE_PLAN_MARKET_CUSTOM_CURVE_REQUIRED"):
        RevenuePlan.create((
            _stream("cfd", RevenueStreamType.CFD, volume_share=1.0, cfd=_cfd()),
        ), market_price=MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0,
                                       price_scenario="custom",
                                       custom_price_curve=()))
    with pytest.raises(ValueError, match="REVENUE_PLAN_MARKET_AUTHORITY_INVALID"):
        RevenuePlan.create((
            _stream("cfd", RevenueStreamType.CFD, volume_share=1.0, cfd=_cfd()),
        ), market_price=MerchantParams(merchant_enabled=True,
                                       base_price_eur_mwh=float("nan")))


# ---------------------------------------------------------------------------
# J — custom curve post-horizon policy lock (existing MerchantParams contract)
# ---------------------------------------------------------------------------

def test_cc_j_custom_curve_beyond_horizon_uses_legacy_fallback():
    """CC-J: INSIDE the supplied curve horizon the explicit curve values are
    authoritative; AFTER the supplied custom horizon the existing
    MerchantParams fallback (base × escalation growth, reduced by linear
    cannibalization, floored at zero) is preserved unchanged in Workflow 02.
    This test locks that existing domain contract — it is not a new policy."""
    curve = (70.0, 72.0)
    merchant = MerchantParams(merchant_enabled=True, price_scenario="custom",
                              custom_price_curve=curve,
                              base_price_eur_mwh=65.0,
                              price_escalation_annual=0.02,
                              price_cannibalization_pct=0.0)
    plan = RevenuePlan.create((_stream(
        "m", RevenueStreamType.MERCHANT, volume_share=None, merchant=merchant),))
    for year in (1, 2):
        expected = merchant.price_at_year(year)  # the existing authority
        got = evaluate_revenue_plan(plan, year, 100_000.0).stream_results[0].price_eur_mwh
        assert got == pytest.approx(expected, abs=TOL)
        assert got == pytest.approx(curve[year - 1], abs=TOL)
    for year in (3, 5):
        expected = merchant.price_at_year(year)  # legacy fallback path
        got = evaluate_revenue_plan(plan, year, 100_000.0).stream_results[0].price_eur_mwh
        assert got == pytest.approx(expected, abs=TOL)
        assert got == pytest.approx(65.0 * 1.02 ** (year - 1), abs=TOL)
