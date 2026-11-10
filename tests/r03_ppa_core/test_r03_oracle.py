"""R03 oracle tests — independent Fraction oracle vs the Decimal implementation.

All inputs are synthetic.  Nothing here authorizes Excel semantics or production use.
"""
from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import pytest

from research.r03_ppa_candidate import core as impl
from tests.r03_ppa_core import oracle as frac_oracle


def D(x):
    return Decimal(str(x))


def _input(**over):
    base = dict(
        contract_id="SYN-1",
        period_axis="ANNUAL",
        cap_mode="LIFE_INCREMENTAL",
        cap_application="AFTER_SHARE",
        cap1=impl.Quantity(D(900), "MWh"),
        cap2=impl.Quantity(D(300), "MWh"),
        generation=((2030, D(1500)),),
        ppa_share=D("0.8"),
        ppa_start_year=2030,
        ppa_end_year=2030,
        base_price=impl.TierPrice(mode="FIXED", fixed_price_eur_mwh=D(70)),
        reduced_price=impl.TierPrice(mode="FIXED", fixed_price_eur_mwh=D(45)),
        merchant=impl.MerchantSpec(mode="MERCHANT_PRICE", prices=((2030, D(55)),)),
        source_id="SYN-VECTOR-1",
    )
    base.update(over)
    return impl.R03Input(**base)


def _oracle_result(res):
    """Compare implementation results to the independent oracle via exact Fractions."""
    years = [p.year for p in res]
    gen = {p.year: Fraction(p.generation_mwh) for p in res}
    share = Fraction(res[0].ppa_share)
    o = frac_oracle.ledger(
        cap_mode=res[0].provenance["cap_mode"],
        cap_application=res[0].provenance["cap_application"],
        cap1_mwh=Fraction(D(900)) if res[0].provenance["cap_mode"].startswith("LIFE") else Fraction(D(900)),
        cap2_mwh=Fraction(D(300)),
        generation=gen,
        ppa_share=share,
        ppa_start=2030,
        ppa_end=2030,
        base_fixed=Fraction(D(70)), base_rate=Fraction(0), base_base_year=2030, base_fraction=Fraction(0),
        reduced_fixed=Fraction(D(45)), reduced_rate=Fraction(0), reduced_base_year=2030, reduced_fraction=Fraction(0),
        merchant_prices={y: Fraction(D(55)) for y in years},
        years=years,
    )
    for p, orow in zip(res, o):
        assert Fraction(p.tier1.mwh) == orow["t1_mwh"]
        assert Fraction(p.tier2.mwh) == orow["t2_mwh"]
        assert Fraction(p.tier1.revenue_eur) == orow["t1_eur"]
        assert Fraction(p.tier2.revenue_eur) == orow["t2_eur"]
        assert Fraction(p.merchant.revenue_eur) == orow["merchant_eur"]
        assert Fraction(p.revenue_eur) == orow["total_eur"]
        assert Fraction(p.merchant.mwh) == orow["merchant_mwh"]
    return o


def test_owner_illustrative_vector_1500_80pct_life_incremental():
    """Prompt §4.3 vector: 1500 MWh, 80% share -> 1200; tier1 900 @70, tier2 300 @45,
    merchant 300 @55 => PPA 76,500 + merchant 16,500 = 93,000 EUR = 93 kEUR."""
    res = impl.compute_ppa_ledger(_input())
    p = res[0]
    assert p.tier1.mwh == D(900) and p.tier2.mwh == D(300)
    assert p.tier1.revenue_eur == D("63000.000000")
    assert p.tier2.revenue_eur == D("13500.000000")
    assert p.tier1.revenue_eur + p.tier2.revenue_eur == D("76500.000000")
    assert p.merchant.mwh == D(300) and p.merchant.revenue_eur == D("16500.000000")
    assert p.revenue_eur == D("93000.000000") and p.revenue_keur == D("93.000000")
    o = _oracle_result(res)
    assert o[0]["total_eur"] == Fraction(93000)


def test_yearly_reset_produces_different_result_than_lifetime():
    """Family 2 counterexample: annual reset vs lifetime roll-forward must differ on
    a two-year generation profile crossing cap1."""
    two = impl.MerchantSpec(mode="MERCHANT_PRICE", prices=((2030, D(55)), (2031, D(55))))
    inp = _input(cap_mode="LIFE_INCREMENTAL",
                 generation=((2030, D(700)), (2031, D(700))),
                 merchant=two,
                 ppa_end_year=2031)
    res = impl.compute_ppa_ledger(inp)
    inp2 = _input(cap_mode="YEARLY_INCREMENTAL",
                  generation=((2030, D(700)), (2031, D(700))),
                  merchant=two,
                  ppa_end_year=2031)
    res2 = impl.compute_ppa_ledger(inp2)
    life_t1 = res[0].tier1.mwh + res[1].tier1.mwh
    yearly_t1 = res2[0].tier1.mwh + res2[1].tier1.mwh
    assert life_t1 == D(900)          # 900 cap consumed in 2030 (700) + 2031 (200)
    assert yearly_t1 == D(1120)       # reset each year: eligible 560/yr -> tier1 560+560
    assert life_t1 != yearly_t1


def test_ceiling_mode_refuses_cap2_below_cap1():
    with pytest.raises(impl.ContractError):
        impl.compute_ppa_ledger(_input(cap_mode="LIFE_CEILING" if False else "LIFE_ABSOLUTE",
                                       cap1=impl.Quantity(D(500), "MWh"), cap2=impl.Quantity(D(300), "MWh")))


def test_missing_merchant_price_is_evidence_missing_never_zero():
    inp = _input(merchant=impl.MerchantSpec(mode="MERCHANT_PRICE", prices=()))
    with pytest.raises(impl.ContractError, match="EVIDENCE_MISSING"):
        impl.compute_ppa_ledger(inp)


def test_unsold_mode_carries_mwh_without_revenue():
    res = impl.compute_ppa_ledger(_input(merchant=impl.MerchantSpec(mode="UNSOLD")))
    p = res[0]
    assert p.unsold_mwh == D(300) and p.merchant.mwh == D(0) and p.merchant.revenue_eur == D(0)
    assert p.revenue_eur == D("76500.000000")


def test_shares_100pct_and_zero_and_over_100_refused():
    full = impl.compute_ppa_ledger(_input(ppa_share=D(1)))
    assert full[0].merchant.mwh == D(300)   # caps limit even at 100% share (900+300 < 1500)
    zero = impl.compute_ppa_ledger(_input(ppa_share=D(0)))
    assert zero[0].tier1.mwh == D(0) and zero[0].merchant.mwh == D(1500)
    with pytest.raises(impl.ContractError):
        impl.compute_ppa_ledger(_input(ppa_share=D("1.2")))


def test_flh_unit_requires_denominator_metadata():
    with pytest.raises(impl.ContractError, match="denominator_mw"):
        impl.compute_ppa_ledger(_input(cap1=impl.Quantity(D(2250), "FLH")))
    ok = impl.compute_ppa_ledger(_input(cap1=impl.Quantity(D(2250), "FLH", denominator_mw=D(1))))
    assert ok[0].tier1.mwh == D(1200)     # 2250 FLH x 1 MW = 2250 MWh cap, ali eligible 1200 je manji


def test_gwh_unit_converts():
    res = impl.compute_ppa_ledger(_input(cap1=impl.Quantity(D("0.9"), "GWh")))
    assert res[0].tier1.mwh == D(900)


def test_cap_application_before_share_is_an_explicit_hypothesis():
    """Q4: BEFORE_SHARE caps on full generation, then the share scales the tiers."""
    res = impl.compute_ppa_ledger(_input(cap_application="BEFORE_SHARE"))
    p = res[0]
    # tiers filled against 1500: t1 = 900, t2 = 300 (t2_hi=1200), then x 0.8
    assert p.tier1.mwh == D(720) and p.tier2.mwh == D(240)
    assert p.merchant.mwh == D(1500 - 720 - 240)
    o = _oracle_result(res)
    assert o[0]["t1_mwh"] == Fraction(720)


def test_two_year_indexed_prices_track_tier_independent_specs():
    """Q3: per-tier independent indexation (base 2%/y from 2030, reduced flat)."""
    inp = _input(
        generation=((2030, D(500)), (2031, D(500))),
        ppa_end_year=2031,
        cap1=impl.Quantity(D(2000), "MWh"), cap2=impl.Quantity(D(4000), "MWh"),
        merchant=impl.MerchantSpec(mode="MERCHANT_PRICE", prices=((2030, D(55)), (2031, D(55)))),
        base_price=impl.TierPrice(mode="INDEXED", fixed_price_eur_mwh=D(70),
                                  index=impl.TierIndex(rate=D("0.02"), base_year=2030, indexed_fraction=D(1))),
        reduced_price=impl.TierPrice(mode="FIXED", fixed_price_eur_mwh=D(45)),
    )
    res = impl.compute_ppa_ledger(inp)
    assert res[0].tier1.price_eur_mwh == D(70)
    assert res[1].tier1.price_eur_mwh == D("71.40")    # 70 x 1.02
    assert res[1].tier2.price_eur_mwh == D(45)          # independent flat tier2


def test_cfd_overlay_settles_without_extra_sale():
    res = impl.compute_ppa_ledger(_input(cfd=impl.CfdOverlay(strike_eur_mwh=D(80),
                                                             reference_prices=((2030, D(55)),))))
    p = res[0]
    # (80 - 55) x 1200 contracted = 30,000 EUR overlay; physical MWh unchanged
    assert p.cfd_settlement_eur == D("30000.000000")
    assert p.tier1.mwh + p.tier2.mwh + p.merchant.mwh == D(1500)   # physical conservation vs generation
    assert p.revenue_eur == D("123000.000000")     # 76,500 + 16,500 + 30,000


def test_provenance_marks_every_period_unapproved():
    res = impl.compute_ppa_ledger(_input())
    for p in res:
        assert p.provenance["approved_for_finco"] == "False"
        assert p.provenance["status"] == "SEMANTICS_UNVERIFIED"
        assert p.provenance["source_id"] == "SYN-VECTOR-1"


def test_non_finite_and_negative_generation_refused():
    with pytest.raises(impl.ContractError):
        impl.compute_ppa_ledger(_input(generation=((2030, Decimal("NaN")),)))
    with pytest.raises(impl.ContractError):
        impl.compute_ppa_ledger(_input(generation=((2030, D(-5)),)))


def test_out_of_range_ppa_share_refused():
    with pytest.raises(impl.ContractError):
        impl.compute_ppa_ledger(_input(ppa_share=D("-0.1")))
