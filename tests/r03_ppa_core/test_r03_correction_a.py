"""R03 Correction A — completion oracle families (a-g) + engine-authority A/B.

Every numeric expectation here is hand-audited (Fractions or exact Decimals) and
synthetic.  The engine A/B uses the ACCEPTED price authority
(`RevenueParams.tariff_at_year`) only on the already-supported indexed-tariff subset;
it proves numerical consistency of R03's INDEXED mode with live semantics, NOT Excel
parity and NOT production activation.
"""
from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import pytest

from research.r03_ppa_candidate import core as impl
from tests.r03_ppa_core.test_r03_oracle import D, _input, _oracle_result


# ── family: DATED curve mode ──

def test_dated_curve_prices_and_missing_point_refusal():
    inp = _input(
        base_price=impl.TierPrice(mode="DATED", dated_curve=((2030, D(70)), (2031, D(72)))),
        merchant=impl.MerchantSpec(mode="MERCHANT_PRICE", prices=((2030, D(55)), (2031, D(55)))),
        generation=((2030, D(600)), (2031, D(600))),
        cap1=impl.Quantity(D(5000), "MWh"), cap2=impl.Quantity(D(9000), "MWh"),
        ppa_end_year=2031,
    )
    res = impl.compute_ppa_ledger(inp)
    assert res[0].tier1.price_eur_mwh == D(70) and res[1].tier1.price_eur_mwh == D(72)
    missing = _input(
        base_price=impl.TierPrice(mode="DATED", dated_curve=((2030, D(70)),)),
        merchant=impl.MerchantSpec(mode="MERCHANT_PRICE", prices=((2030, D(55)), (2031, D(55)))),
        generation=((2030, D(600)), (2031, D(600))),
        ppa_end_year=2031,
    )
    with pytest.raises(impl.ContractError, match="EVIDENCE_MISSING"):
        impl.compute_ppa_ledger(missing)


def test_dated_curve_non_monotonic_refused():
    with pytest.raises(impl.ContractError, match="non-monotonic"):
        impl.compute_ppa_ledger(_input(
            base_price=impl.TierPrice(mode="DATED", dated_curve=((2030, D(72)), (2031, D(70)))),
            merchant=impl.MerchantSpec(mode="MERCHANT_PRICE", prices=((2030, D(55)), (2031, D(55)))),
            generation=((2030, D(600)), (2031, D(600))),
            ppa_end_year=2031,
        ))


# ── family: floor/cap ordering (after indexation, before rounding) ──

def test_price_cap_clamps_indexed_price_before_rounding():
    inp = _input(
        base_price=impl.TierPrice(mode="INDEXED", fixed_price_eur_mwh=D(100),
                                  index=impl.TierIndex(rate=D("0.5"), base_year=2030, indexed_fraction=D(1)),
                                  price_cap=D(120)),
        merchant=impl.MerchantSpec(mode="MERCHANT_PRICE", prices=((2030, D(55)), (2031, D(55)))),
        generation=((2030, D(600)), (2031, D(600))),
        cap1=impl.Quantity(D(5000), "MWh"), cap2=impl.Quantity(D(9000), "MWh"),
        ppa_end_year=2031,
    )
    res = impl.compute_ppa_ledger(inp)
    assert res[0].tier1.price_eur_mwh == D(100)
    # 100 x 1.5 = 150 would exceed the cap: clamped to 120 BEFORE the EUR multiply
    assert res[1].tier1.price_eur_mwh == D(120)
    assert res[1].tier1.mwh == D(480)                              # eligible 600 x 0.8
    assert res[1].tier1.revenue_eur == D(480) * D(120)             # clamp BEFORE the EUR multiply


def test_price_floor_lifts_degenerating_price():
    res = impl.compute_ppa_ledger(_input(
        base_price=impl.TierPrice(mode="INDEXED", fixed_price_eur_mwh=D(10),
                                  index=impl.TierIndex(rate=D("-0.5"), base_year=2030, indexed_fraction=D(1)),
                                  price_floor=D(8)),
        merchant=impl.MerchantSpec(mode="MERCHANT_PRICE", prices=((2030, D(55)), (2031, D(55)))),
        generation=((2030, D(600)), (2031, D(600))),
        cap1=impl.Quantity(D(5000), "MWh"), cap2=impl.Quantity(D(9000), "MWh"),
        ppa_end_year=2031,
    ))
    assert res[1].tier1.price_eur_mwh == D(8)     # 10 x 0.5 = 5 -> floored at 8


def test_floor_above_cap_refused():
    with pytest.raises(impl.ContractError, match="floor above cap"):
        impl.compute_ppa_ledger(_input(
            base_price=impl.TierPrice(mode="FIXED", fixed_price_eur_mwh=D(70), price_floor=D(90), price_cap=D(80)),
        ))


# ── family: period axis ──

def test_monthly_axis_is_typed_not_supported():
    with pytest.raises(impl.ContractError, match="NOT_SUPPORTED"):
        impl.compute_ppa_ledger(_input(period_axis="MONTHLY"))


# ── family: portfolio primary-window validation ──

def _contract(cid, start, end):
    return _input(contract_id=cid, ppa_start_year=start, ppa_end_year=end,
                  merchant=impl.MerchantSpec(mode="MERCHANT_PRICE", prices=((y, D(55)) for y in (2030, 2031, 2032))))


def test_overlapping_primary_windows_hard_refused():
    with pytest.raises(impl.ContractError, match="overlapping primary windows"):
        impl.validate_primary_windows([_contract("A", 2030, 2031), _contract("B", 2031, 2032)])


def test_sequential_disjoint_windows_allowed():
    ids = impl.validate_primary_windows([_contract("A", 2030, 2030), _contract("B", 2031, 2031)])
    assert ids == ("A", "B")


def test_duplicate_contract_id_refused():
    with pytest.raises(impl.ContractError, match="duplicate contract id"):
        impl.validate_primary_windows([_contract("A", 2030, 2030), _contract("A", 2031, 2031)])


def test_stale_and_foreign_provenance_refused():
    res = impl.compute_ppa_ledger(_input())
    impl.verify_provenance(res, contract_id="SYN-1")
    with pytest.raises(impl.ContractError, match="foreign provenance"):
        impl.verify_provenance(res, contract_id="OTHER")
    forged = [r for r in res]
    bad = res[0].provenance | {"approved_for_finco": "True"}
    forged[0] = impl.PeriodResult(**{**res[0].__dict__, "provenance": bad})
    with pytest.raises(impl.ContractError, match="forged"):
        impl.verify_provenance(forged, contract_id="SYN-1")


# ── family: engine-authority A/B (accepted indexed-tariff semantics) ──

def test_ab_indexed_mode_matches_accepted_engine_authority():
    """R03 INDEXED (fraction=1, base_year = PPA start) must reproduce the accepted
    `RevenueParams.tariff_at_year` factor (1+rate)^(operating_year-1) exactly on the
    supported subset.  Solar and Wind share this authority (same price semantics)."""
    from finco_core.inputs._models import RevenueParams
    engine = RevenueParams(ppa_base_tariff=70.0, ppa_index=0.02, ppa_term_years=12)
    for start in (2030, 2031):
        op_years = (1, 2, 3)
        cal = [start + (op - 1) for op in op_years]   # consecutive calendar years
        inp = _input(
            generation=tuple((y, D(600)) for y in cal),
            ppa_start_year=start,
            ppa_end_year=cal[-1],
            cap1=impl.Quantity(D(5000), "MWh"), cap2=impl.Quantity(D(9000), "MWh"),
            merchant=impl.MerchantSpec(mode="MERCHANT_PRICE", prices=tuple((y, D(55)) for y in cal)),
            base_price=impl.TierPrice(mode="INDEXED", fixed_price_eur_mwh=D(70),
                                      index=impl.TierIndex(rate=D("0.02"), base_year=start, indexed_fraction=D(1),
                                      indexation_timing="PER_CALENDAR_YEAR")),
        )
        res = impl.compute_ppa_ledger(inp)
        for p, op in zip(res, op_years):
            expected = D(engine.tariff_at_year(op))
            assert p.tier1.price_eur_mwh == expected, (start, op, p.tier1.price_eur_mwh, expected)


def test_no_engine_or_product_imports_in_research_package():
    """Static containment proof: the isolated package imports nothing from the live
    engine, domain, app or finco_core layers."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    banned = ("financial_engine", "finco_core", "domain", "app", "frontend", "domain.revenue")
    for f in (root / "research" / "r03_ppa_candidate").glob("*.py"):
        src = f.read_text(encoding="utf-8")
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                for b in banned:
                    assert not stripped.split()[1].startswith(b), (f.name, line)


def test_unapproved_indexation_timing_refused():
    """Q3/Q6: per-anniversary and per-12-month variants are explicit owner hypotheses —
    refused HYPOTHESIS_NOT_APPROVED, never silently chosen."""
    with pytest.raises(impl.ContractError, match="HYPOTHESIS_NOT_APPROVED"):
        impl.compute_ppa_ledger(_input(
            base_price=impl.TierPrice(mode="INDEXED", fixed_price_eur_mwh=D(70),
                                      index=impl.TierIndex(rate=D("0.02"), base_year=2030,
                                                           indexed_fraction=D(1),
                                                           indexation_timing="PER_ANNIVERSARY")),
        ))
    with pytest.raises(impl.ContractError, match="HYPOTHESIS_NOT_APPROVED"):
        impl.compute_ppa_ledger(_input(
            base_price=impl.TierPrice(mode="INDEXED", fixed_price_eur_mwh=D(70),
                                      index=impl.TierIndex(rate=D("0.02"), base_year=2030,
                                                           indexed_fraction=D(1),
                                                           indexation_timing="PER_12_MONTHS")),
        ))
