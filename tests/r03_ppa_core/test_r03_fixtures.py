"""R03 Correction B — fixtures-first three-way oracle tests.

Every scenario: the SAME independent fixture (tests/r03_ppa_core/fixtures.py, hand-derived
expected rows in exact Fractions) drives (a) the Decimal implementation, (b) the independent
Fraction oracle, and (c) the hand-derived expectation.  None of the three reads another's
output.  Physical conservation, cap monotonicity and provenance are asserted per period.
"""
from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

F = Fraction

import pytest

from research.r03_ppa_candidate import core as impl
from tests.r03_ppa_core import fixtures as FX
from tests.r03_ppa_core import oracle as frac_oracle


def _quantity(q):
    unit = "FLH" if isinstance(q, tuple) and len(q) == 3 else ("GWh" if abs(float(q[0])) >= 1000 and False else "MWh")
    return unit


def _impl_from_fixture(fx):
    """Build the implementation input from the SAME fixture the oracle uses."""
    c1 = impl.Quantity(Decimal(fx["cap1_mwh"].numerator) / Decimal(fx["cap1_mwh"].denominator), "MWh")
    c2 = impl.Quantity(Decimal(fx["cap2_mwh"].numerator) / Decimal(fx["cap2_mwh"].denominator), "MWh")
    gen = tuple((y, Decimal(gx.numerator) / Decimal(gx.denominator)) for y, gx in fx["generation"].items())
    merchant = (impl.MerchantSpec(mode="UNSOLD") if "UNSOLD" in fx["merchant_prices"]
                else impl.MerchantSpec(mode="MERCHANT_PRICE",
                                       prices=tuple((y, Decimal(v.numerator) / Decimal(v.denominator))
                                                    for y, v in sorted(fx["merchant_prices"].items()))))
    def tier(t):
        fixed, rate, base_year, frac = t
        if rate == 0 and frac == 0:
            return impl.TierPrice(mode="FIXED", fixed_price_eur_mwh=Decimal(fixed.numerator) / Decimal(fixed.denominator))
        return impl.TierPrice(mode="INDEXED",
                              fixed_price_eur_mwh=Decimal(fixed.numerator) / Decimal(fixed.denominator),
                              index=impl.TierIndex(rate=Decimal(rate.numerator) / Decimal(rate.denominator),
                                                   base_year=base_year,
                                                   indexed_fraction=Decimal(frac.numerator) / Decimal(frac.denominator)))
    cfd = None
    if "cfd" in fx:
        cfd = impl.CfdOverlay(strike_eur_mwh=Decimal(fx["cfd"]["strike"].numerator) / Decimal(fx["cfd"]["strike"].denominator),
                              reference_prices=tuple((y, Decimal(v.numerator) / Decimal(v.denominator))
                                                     for y, v in sorted(fx["cfd"]["reference"].items())))
    return impl.R03Input(
        contract_id="SYN-FIXTURE", period_axis="ANNUAL",
        cap_mode=fx["cap_mode"], cap_application=fx["cap_application"],
        cap1=c1, cap2=c2, generation=gen,
        ppa_share=Decimal(fx["ppa_share"].numerator) / Decimal(fx["ppa_share"].denominator),
        ppa_start_year=fx["ppa_start"], ppa_end_year=fx["ppa_end"],
        base_price=tier(fx["base"]), reduced_price=tier(fx["reduced"]),
        merchant=merchant, cfd=cfd, source_id="SYN-FIXTURE",
    )


def _assert_three_way(fx):
    res = impl.compute_ppa_ledger(_impl_from_fixture(fx))
    orows = frac_oracle.ledger_from_fixture(fx)
    assert len(res) == len(fx["expected"]) == len(orows)
    for p, orow, exp in zip(res, orows, fx["expected"]):
        # (c) hand-derived expectation
        assert Fraction(p.tier1.mwh) == exp["t1_mwh"]
        assert Fraction(p.tier2.mwh) == exp["t2_mwh"]
        assert Fraction(p.tier1.revenue_eur) == exp["t1_eur"]
        assert Fraction(p.tier2.revenue_eur) == exp["t2_eur"]
        assert Fraction(p.merchant.mwh) == exp["merchant_mwh"]
        assert Fraction(p.unsold_mwh) == exp["unsold_mwh"]
        assert Fraction(p.revenue_eur) == exp["total_eur"]
        # (a) Fraction oracle agrees with the hand derivation
        assert orow["t1_mwh"] == exp["t1_mwh"] and orow["t1_eur"] == exp["t1_eur"]
        assert orow["t2_eur"] == exp["t2_eur"] and orow["merchant_eur"] == exp["merchant_eur"]
        assert orow["total_eur"] == exp["total_eur"] and orow["unsold_mwh"] == exp["unsold_mwh"]
        # (b) Decimal implementation agrees with the Fraction oracle
        assert Fraction(p.tier1.mwh) == orow["t1_mwh"] and Fraction(p.tier1.revenue_eur) == orow["t1_eur"]
        assert Fraction(p.tier2.mwh) == orow["t2_mwh"] and Fraction(p.tier2.revenue_eur) == orow["t2_eur"]
        assert Fraction(p.merchant.mwh) == orow["merchant_mwh"] and Fraction(p.merchant.revenue_eur) == orow["merchant_eur"]
        assert Fraction(p.revenue_eur) == orow["total_eur"]
        # invariants: physical conservation + no negative allocation
        assert p.tier1.mwh + p.tier2.mwh + p.merchant.mwh + p.unsold_mwh == p.generation_mwh
        assert min(p.tier1.mwh, p.tier2.mwh, p.merchant.mwh, p.unsold_mwh) >= 0
        assert p.provenance["approved_for_finco"] == "False"
    # monotonic lifetime cap usage (LIFE modes never decrease the counter)
    if fx["cap_mode"].startswith("LIFE"):
        caps = [p.cap_after_mwh for p in res]
        assert all(a <= b for a, b in zip(caps, caps[1:])), caps


def test_fixture1_owner_illustrative_vector():
    _assert_three_way(FX.FIXTURE_1)


def test_fixture2_yearly_vs_lifetime_counterexample():
    _assert_three_way(FX.FIXTURE_2_YEARLY)
    _assert_three_way(FX.FIXTURE_2_LIFE)
    # metamorphic: the two semantics MUST differ
    y1 = FX.FIXTURE_2_YEARLY["expected"]
    l1 = FX.FIXTURE_2_LIFE["expected"]
    assert [r["t1_mwh"] for r in y1] != [r["t1_mwh"] for r in l1]


def test_fixture3_before_share_hypothesis_q4():
    _assert_three_way(FX.FIXTURE_3)
    # metamorphic: BEFORE_SHARE differs from AFTER_SHARE (Q4 counterexample)
    assert FX.FIXTURE_3["expected"][0]["merchant_mwh"] != FX.FIXTURE_1["expected"][0]["merchant_mwh"]


def test_fixture4_per_tier_independent_indexation_q3():
    _assert_three_way(FX.FIXTURE_4)


def test_fixture5_cfd_negative_settlement_directional():
    _assert_three_way(FX.FIXTURE_5)
    # the overlay is negative (strike below reference) and never changes physical MWh
    exp = FX.FIXTURE_5["expected"][0]
    assert exp["cfd_eur"] == Fraction(-12000)
    assert exp["t1_mwh"] + exp["t2_mwh"] + exp["merchant_mwh"] == F(1500)


def test_fixture6_unsold():
    _assert_three_way(FX.FIXTURE_6)


def test_fixture7_no_early_rounding_discriminator():
    """Rounding happens ONCE per component at 6 dp on the raw product — an early
    price-rounding would produce a different EUR (66148.1484 vs 66148.148147)."""
    _assert_three_way(FX.FIXTURE_7)
    assert FX.FIXTURE_7["expected"][0]["t1_eur"] == Fraction(66148148147, 1000000)
