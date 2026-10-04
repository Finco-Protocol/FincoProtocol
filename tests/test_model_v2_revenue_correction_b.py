"""Model V2 Revenue Correction B regression matrix.

Legacy CfD adapter fail-closed semantics, plan-level market authority
validation, exactly-one-price-authority rule, coherent allocation
tolerances, empty plan / zero generation / one-way CfD / auction expiry
behaviors, and the vacuous-assertion quality gate.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from domain.revenue.plan import (
    ContractRole,
    RevenuePlan,
    RevenueStream,
    RevenueStreamType,
)
from domain.revenue.plan_engine import (
    MWH_IDENTITY_TOLERANCE_ABSOLUTE,
    PlanPeriodStatus,
    StreamPeriodStatus,
    evaluate_revenue_plan,
)
from domain.revenue.plan import SHARE_ALLOCATION_TOLERANCE
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
    _fit_fixed,
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


# ---------------------------------------------------------------------------
# Legacy CfD adapter — fail closed for EVERY enabled legacy CfD
# ---------------------------------------------------------------------------

def test_cb_q_legacy_zero_volume_cfd_fail_closed():
    """CB-Q: the legacy CfD authority interprets cfd_volume_mwh_annual == 0
    as UNLIMITED settlement volume, so a zero-volume legacy CfD is NOT
    equivalent to a plan overlay over 100% of generation. This regression
    protects against future silent semantic migration."""
    legacy = RevenueConfig(
        merchant=MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0),
        cfd=CfDParams(cfd_enabled=True, strike_price_eur_mwh=70.0,
                      cfd_volume_mwh_annual=0.0),
    )
    with pytest.raises(ValueError, match="LEGACY_CFD_NOT_REPRESENTABLE"):
        revenue_plan_from_legacy_config(legacy)


def test_cb_r_legacy_fixed_volume_cfd_fail_closed():
    """CB-R: fixed annual MWh legacy CfD never converts either."""
    legacy = RevenueConfig(
        merchant=MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0),
        cfd=CfDParams(cfd_enabled=True, strike_price_eur_mwh=70.0,
                      cfd_volume_mwh_annual=80_000.0),
    )
    with pytest.raises(ValueError, match="LEGACY_CFD_NOT_REPRESENTABLE"):
        revenue_plan_from_legacy_config(legacy)


def test_cb_r2_legacy_cfd_error_independent_of_merchant_presence():
    """The CfD refusal is unconditional — not gated on reference availability."""
    cfd_only = RevenueConfig(
        cfd=CfDParams(cfd_enabled=True, strike_price_eur_mwh=70.0),
    )
    with pytest.raises(ValueError, match="LEGACY_CFD_NOT_REPRESENTABLE"):
        revenue_plan_from_legacy_config(cfd_only)


# ---------------------------------------------------------------------------
# Plan-level market price authority (validated at construction)
# ---------------------------------------------------------------------------

def _overlay_only_plan(mp):
    return RevenuePlan.create((
        _stream("cfd", RevenueStreamType.CFD, volume_share=1.0, cfd=_cfd(strike=70.0)),
    ), market_price=mp)


def test_cb_s_t_u_plan_level_market_authority_rejected_at_validation():
    """CB-S/T/U: NaN / +inf / negative base price / non-finite curve members
    / out-of-range capture fail during RevenuePlan validation."""
    with pytest.raises(ValueError, match="REVENUE_PLAN_MARKET_AUTHORITY_INVALID"):
        _overlay_only_plan(MerchantParams(merchant_enabled=True,
                                          base_price_eur_mwh=float("nan")))
    with pytest.raises(ValueError, match="REVENUE_PLAN_MARKET_AUTHORITY_INVALID"):
        _overlay_only_plan(MerchantParams(merchant_enabled=True,
                                          base_price_eur_mwh=float("inf")))
    with pytest.raises(ValueError, match="REVENUE_PLAN_MARKET_AUTHORITY_INVALID"):
        _overlay_only_plan(MerchantParams(merchant_enabled=True,
                                          base_price_eur_mwh=-5.0))
    with pytest.raises(ValueError, match="REVENUE_PLAN_MARKET_AUTHORITY_INVALID"):
        _overlay_only_plan(MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0,
                                          price_scenario="custom",
                                          custom_price_curve=(60.0, float("nan"))))
    with pytest.raises(ValueError, match="REVENUE_PLAN_MARKET_AUTHORITY_INVALID"):
        _overlay_only_plan(MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0,
                                          price_scenario="custom",
                                          custom_price_curve=(60.0, float("+inf"))))
    with pytest.raises(ValueError, match="REVENUE_PLAN_MARKET_AUTHORITY_INVALID"):
        _overlay_only_plan(MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0,
                                          price_cannibalization_pct=float("inf")))
    with pytest.raises(ValueError, match="REVENUE_PLAN_MARKET_AUTHORITY_INVALID"):
        _overlay_only_plan(MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0,
                                          capture_rate_solar=1.5))


def test_cb_s2_plan_level_market_authority_type_checked():
    """A non-MerchantParams market authority fails closed (malformed type)."""
    with pytest.raises(ValueError, match="REVENUE_PLAN_MARKET_AUTHORITY_INVALID"):
        _overlay_only_plan("not-an-authority")


def test_cb_s3_unsupported_market_scenario_fails_closed_and_custom_requires_curve():
    """CB §5: only the explicitly understood merchant scenarios are accepted;
    custom requires a usable curve — no silent fallback to base price."""
    with pytest.raises(ValueError, match="REVENUE_PLAN_MARKET_SCENARIO_UNSUPPORTED"):
        _overlay_only_plan(MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0,
                                          price_scenario="mega_bull"))
    with pytest.raises(ValueError, match="REVENUE_PLAN_MARKET_CUSTOM_CURVE_REQUIRED"):
        _overlay_only_plan(MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0,
                                          price_scenario="custom",
                                          custom_price_curve=()))


def test_cb_s4_valid_plan_level_market_authority_still_evaluates():
    """The hardening must not reject a well-formed authority (base scenario)."""
    plan = _overlay_only_plan(MerchantParams(merchant_enabled=True,
                                             base_price_eur_mwh=65.0))
    r = evaluate_revenue_plan(plan, 1, 100_000.0)
    assert r.stream_results[0].support_or_settlement_keur == pytest.approx(500.0, abs=TOL)


# ---------------------------------------------------------------------------
# Exactly one price authority per stream
# ---------------------------------------------------------------------------

def test_cb_v_extra_typed_authority_rejected():
    """CB-V: extras beyond the stream's single applicable authority fail
    closed with a typed error — never silently ignored."""
    with pytest.raises(ValueError, match="REVENUE_STREAM_MULTIPLE_PRICE_AUTHORITIES"):
        RevenuePlan.create((_stream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                                    ppa=_ppa(), merchant=_merchant()),))
    with pytest.raises(ValueError, match="REVENUE_STREAM_MULTIPLE_PRICE_AUTHORITIES"):
        RevenuePlan.create((_stream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                                    ppa=_ppa(), fit=_fit_fixed()),))
    with pytest.raises(ValueError, match="REVENUE_STREAM_MULTIPLE_PRICE_AUTHORITIES"):
        RevenuePlan.create((_stream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                                    ppa=_ppa(), cfd=_cfd()),))
    with pytest.raises(ValueError, match="REVENUE_STREAM_MULTIPLE_PRICE_AUTHORITIES"):
        RevenuePlan.create((_stream("m", RevenueStreamType.MERCHANT, volume_share=None,
                                    merchant=_merchant(), fit=_fit_fixed()),))
    with pytest.raises(ValueError, match="REVENUE_STREAM_MULTIPLE_PRICE_AUTHORITIES"):
        RevenuePlan.create((_stream("cfd", RevenueStreamType.CFD, volume_share=1.0,
                                    cfd=_cfd(), ppa=_ppa()),))
    # Indexed FiT must use only its explicit indexed fields
    with pytest.raises(ValueError, match="REVENUE_STREAM_MULTIPLE_PRICE_AUTHORITIES"):
        RevenuePlan.create((_stream(
            "idx", RevenueStreamType.INDEXED_FIT, volume_share=1.0,
            indexed_fit_base_tariff_eur_mwh=50.0,
            indexed_fit_index_factors=(1.0,), merchant=_merchant()),))


def test_cb_v2_single_authority_still_accepted():
    """The rule must not reject well-formed single-authority streams."""
    RevenuePlan.create((_stream("ppa", RevenueStreamType.PPA, volume_share=1.0,
                                ppa=_ppa()),))
    RevenuePlan.create((_stream("m", RevenueStreamType.MERCHANT, volume_share=None,
                                merchant=_merchant()),))
    RevenuePlan.create((_stream("cfd", RevenueStreamType.CFD, volume_share=1.0,
                                cfd=_cfd()),), market_price=_merchant())


# ---------------------------------------------------------------------------
# Allocation tolerance coherence
# ---------------------------------------------------------------------------

def test_cb_aa_share_tolerance_and_mwh_identity_coherent():
    """CB-AA: a plan accepted by SHARE validation (within the named
    dimensionless tolerance) must not fail its MWh allocation identity at
    realistic generation volumes."""
    epsilon = SHARE_ALLOCATION_TOLERANCE / 2.0  # inside the share tolerance
    plan = RevenuePlan.create((
        _stream("ppa_a", RevenueStreamType.PPA, volume_share=0.5 + epsilon,
                ppa=_ppa(price=50.0)),
        _stream("ppa_b", RevenueStreamType.PPA, volume_share=0.5, ppa=_ppa(price=55.0)),
    ))
    huge_generation = 50_000_000.0  # 50 TWh: epsilon × generation ≫ 1e-9 MWh
    r = evaluate_revenue_plan(plan, 1, huge_generation)
    allocated = sum(
        s.allocated_generation_mwh for s in r.stream_results
        if s.contract_role is ContractRole.PRIMARY_ALLOCATION
        and s.status is StreamPeriodStatus.ACTIVE
    )
    # identity holds within the SCALED tolerance (share epsilon × generation),
    # never within the raw absolute floor alone
    scaled_tolerance = max(
        MWH_IDENTITY_TOLERANCE_ABSOLUTE,
        SHARE_ALLOCATION_TOLERANCE * huge_generation,
    )
    assert abs(allocated + r.unallocated_generation_mwh - huge_generation) <= scaled_tolerance
    assert r.status is PlanPeriodStatus.OK


def test_cb_aa2_beyond_share_tolerance_still_fails_closed():
    over = RevenuePlan(streams=(
        _stream("ppa_a", RevenueStreamType.PPA,
                volume_share=0.5 + SHARE_ALLOCATION_TOLERANCE * 10.0,
                ppa=_ppa(price=50.0)),
        _stream("ppa_b", RevenueStreamType.PPA, volume_share=0.5, ppa=_ppa(price=55.0)),
    ))
    with pytest.raises(ValueError, match="REVENUE_ALLOCATION_EXCEEDS_ELIGIBLE_GENERATION"):
        over.validate()


# ---------------------------------------------------------------------------
# Empty plan / zero generation
# ---------------------------------------------------------------------------

def test_cb_w_empty_plan_is_legal_and_intentional():
    """CB-W: a zero-stream plan is legal at this domain layer; positive
    generation is honestly reported as unsold — never a crash."""
    plan = RevenuePlan.create(())
    r = evaluate_revenue_plan(plan, 1, 100_000.0)
    assert r.total_revenue_keur is not None
    assert r.total_revenue_keur == pytest.approx(0.0, abs=TOL)
    assert r.available_revenue_subtotal_keur == pytest.approx(0.0, abs=TOL)
    assert r.unallocated_generation_mwh == pytest.approx(100_000.0, abs=TOL)
    assert r.status is PlanPeriodStatus.PARTIALLY_UNALLOCATED
    assert r.stream_results == ()


def test_cb_w2_empty_plan_zero_generation_is_ok():
    plan = RevenuePlan.create(())
    r = evaluate_revenue_plan(plan, 1, 0.0)
    assert r.total_revenue_keur == pytest.approx(0.0, abs=TOL)
    assert r.unallocated_generation_mwh == 0.0
    assert r.status is PlanPeriodStatus.OK


def test_cb_x_zero_generation_is_economic_zero_not_missing():
    """CB-X: eligible generation 0.0 on a valid plan → economic zeros with
    allocation identity intact (distinct from MISSING authority)."""
    plan = RevenuePlan.create((
        _stream("ppa", RevenueStreamType.PPA, volume_share=0.6,
                ppa=_ppa(share=0.6, price=57.0)),
        _stream("m", RevenueStreamType.MERCHANT, volume_share=None,
                merchant=_merchant()),
    ))
    r = evaluate_revenue_plan(plan, 1, 0.0)
    assert r.total_revenue_keur is not None
    assert r.total_revenue_keur == pytest.approx(0.0, abs=TOL)
    for s in r.stream_results:
        assert s.allocated_generation_mwh == 0.0
        assert s.stream_revenue_keur == 0.0
        assert s.stream_revenue_keur is not None  # economic zero, not unavailable
    assert r.unallocated_generation_mwh == 0.0
    assert r.status is PlanPeriodStatus.OK


# ---------------------------------------------------------------------------
# One-way CfD / auction expiry
# ---------------------------------------------------------------------------

def _cfd_plan(strike, two_way, ref=65.0):
    return RevenuePlan.create((
        _stream("cfd", RevenueStreamType.CFD, volume_share=1.0,
                cfd=_cfd(strike=strike, two_way=two_way), reference_stream_id="m",
                term_years=10),
        _stream("m", RevenueStreamType.MERCHANT, volume_share=None,
                merchant=_merchant(price=ref)),
    ), market_price=_merchant(price=ref))


def test_cb_y_one_way_cfd_clips_negative_settlement_to_zero():
    """CB-Y: one-way CfD with reference ABOVE strike settles exactly 0.0 (no
    negative generator flow); reference below strike keeps the in-payment."""
    r = evaluate_revenue_plan(_cfd_plan(strike=60.0, two_way=False), 1, 100_000.0)
    cfd = {s.stream_id: s for s in r.stream_results}["cfd"]
    assert cfd.support_or_settlement_keur == pytest.approx(0.0, abs=TOL)
    assert cfd.support_or_settlement_keur >= 0.0

    r2 = evaluate_revenue_plan(_cfd_plan(strike=70.0, two_way=False), 1, 100_000.0)
    cfd2 = {s.stream_id: s for s in r2.stream_results}["cfd"]
    assert cfd2.support_or_settlement_keur == pytest.approx(
        (70.0 - 65.0) * 100_000 / 1000, abs=TOL)


def test_cb_z_auction_active_then_expired_economic_zero():
    """CB-Z: awarded tariff ACTIVE through its stream term, EXPIRED
    immediately after; expired contribution is economic zero, not
    UNAVAILABLE; no silent continuation."""
    plan = RevenuePlan.create((_stream(
        "auction", RevenueStreamType.AUCTION_AWARDED_TARIFF,
        volume_share=1.0, fit=_fit_fixed(price=61.0, index=0.02),
        start_year=1, term_years=12,
    ),))
    during = evaluate_revenue_plan(plan, 12, 100_000.0).stream_results[0]
    assert during.status is StreamPeriodStatus.ACTIVE
    assert during.price_eur_mwh == pytest.approx(61.0 * 1.02 ** 11, abs=TOL)
    after = evaluate_revenue_plan(plan, 13, 100_000.0).stream_results[0]
    assert after.status is StreamPeriodStatus.EXPIRED
    assert after.stream_revenue_keur == 0.0
    assert after.stream_revenue_keur is not None


# ---------------------------------------------------------------------------
# Quality gate: no vacuous assertions anywhere in the Revenue feature
# ---------------------------------------------------------------------------

def test_cb_no_vacuous_assertions():
    repo_root = Path(__file__).resolve().parents[1]
    revenue_files = [
        "domain/revenue/plan.py",
        "domain/revenue/plan_engine.py",
        "domain/revenue/legacy_plan_adapter.py",
        "tests/test_model_v2_revenue_plan.py",
        "tests/test_model_v2_revenue_correction_a.py",
        "tests/test_model_v2_revenue_correction_b.py",
    ]
    for rel in revenue_files:
        src = (repo_root / rel).read_text(encoding="utf-8")
        # needles are assembled so this scan's own source cannot trip them
        needles = {
            "vacuous boolean-literal assertion": "or" + " True",
            "vacuous constant assertion": "assert" + " True",
            "unconditional skip": "pytest.mark." + "skip(",
            "swallowed exception": "except Exception:" + "\n" + "        " + "pass",
        }
        for label, needle in needles.items():
            assert needle not in src, f"{rel}: {label}"


def test_cb_no_unit_conversion_errors_in_legacy_equivalence():
    """Units sanity: legacy RevenueConfig and plan totals are both kEUR —
    the equivalence comparison is like-for-like (no ×1000 drift)."""
    legacy = RevenueConfig.create_ppa_merchant_mix(ppa_share=0.7, ppa_price=57.0,
                                                   merchant_price=65.0)
    plan = revenue_plan_from_legacy_config(legacy)
    r = evaluate_revenue_plan(plan, 1, 100_000.0, technology="solar")
    assert r.total_revenue_keur == pytest.approx(
        legacy.total_annual_revenue_keur(100_000.0, 1, technology="solar"), abs=1e-9)
    # magnitude check that the unit is really kEUR
    assert 1000.0 < r.total_revenue_keur < 100_000.0
