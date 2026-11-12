"""R03 INDEPENDENT oracle — exact Fractions, written from the spec text only.

Deliberately shares NO code with research/r03_ppa_candidate/core.py: this module
re-derives the annual two-tier ledger in exact rational arithmetic so the Decimal
implementation can be cross-checked without comparing a thing to itself.
Rounding mirrors the contract: each EUR component quantized to 6 dp, half-even,
once per component per period.
"""
from __future__ import annotations

from fractions import Fraction
from typing import Dict, List, Tuple

EUR_DP = 6


def _round_half_even(f: Fraction, dp: int = EUR_DP) -> Fraction:
    """Exact decimal rounding of a Fraction to dp places, half-even, no float."""
    scale = 10 ** dp
    scaled = f * scale
    n, d = scaled.numerator, scaled.denominator
    q, r = divmod(n, d)
    twice = 2 * r
    if twice > d or (twice == d and q % 2 != 0):
        q += 1
    return Fraction(q, scale)


def index_factor(rate: Fraction, base_year: int, fraction: Fraction, year: int) -> Fraction:
    """PER_CALENDAR_YEAR hypothesis only (mirrors the implementation's explicit tag);
    per-anniversary / per-12-month / monthly-proration variants are refused upstream."""
    if fraction == 0 or year < base_year:
        return Fraction(1)
    return (1 - fraction) + fraction * (1 + rate) ** (year - base_year)


def tier_price(fixed: Fraction, rate: Fraction, base_year: int, fraction: Fraction, year: int) -> Fraction:
    return fixed * index_factor(rate, base_year, fraction, year)


def ledger(
    *,
    cap_mode: str,
    cap_application: str,
    cap1_mwh: Fraction,
    cap2_mwh: Fraction,
    generation: Dict[int, Fraction],
    ppa_share: Fraction,
    ppa_start: int,
    ppa_end: int,
    base_fixed: Fraction,
    base_rate: Fraction,
    base_base_year: int,
    base_fraction: Fraction,
    reduced_fixed: Fraction,
    reduced_rate: Fraction,
    reduced_base_year: int,
    reduced_fraction: Fraction,
    merchant_mode: str = "MERCHANT_PRICE",
    merchant_prices: Dict[int, Fraction],
    cfd_strike: Fraction = Fraction(0),
    cfd_reference: Dict[int, Fraction] = None,
    years: List[int] = None,
) -> List[dict]:
    """Exact per-period ledger.  Returns dicts of Fractions keyed by period."""
    cfd_reference = cfd_reference or {}
    t1_hi = cap1_mwh
    t2_hi = cap2_mwh if cap_mode.endswith("CEILING") else cap1_mwh + cap2_mwh
    yearly = cap_mode.startswith("YEARLY")
    counter = Fraction(0)
    out: List[dict] = []
    for y in years:
        g = generation[y]
        if yearly:
            counter = Fraction(0)
        in_ppa = ppa_start <= y <= ppa_end
        if cap_application == "AFTER_SHARE":
            eligible = g * ppa_share
        else:
            eligible = g
        if in_ppa:
            a1 = max(Fraction(0), min(counter + eligible, t1_hi) - min(counter, t1_hi))
            a2 = max(Fraction(0), min(counter + eligible, t2_hi) - max(min(counter, t2_hi), t1_hi))
        else:
            a1 = a2 = Fraction(0)
        if cap_application == "AFTER_SHARE":
            contracted = a1 + a2
            merchant = g - contracted
        else:
            contracted = (a1 + a2) * ppa_share
            merchant = g - contracted
            a1, a2 = a1 * ppa_share, a2 * ppa_share
        counter += eligible if cap_application == "AFTER_SHARE" else g
        if merchant_mode == "UNSOLD":
            m_mwh, m_price, m_eur, unsold = Fraction(0), Fraction(0), Fraction(0), merchant
        else:
            m_mwh, m_price, m_eur, unsold = merchant, merchant_prices[y], _round_half_even(merchant * merchant_prices[y]), Fraction(0)
        if in_ppa:
            p1 = tier_price(base_fixed, base_rate, base_base_year, base_fraction, y)
            p2 = tier_price(reduced_fixed, reduced_rate, reduced_base_year, reduced_fraction, y)
        else:
            p1 = p2 = Fraction(0)
        e1 = _round_half_even(a1 * p1)
        e2 = _round_half_even(a2 * p2)
        cfd = _round_half_even((cfd_strike - cfd_reference.get(y, Fraction(0))) * (a1 + a2)) if in_ppa and cfd_strike else Fraction(0)
        total = _round_half_even(e1 + e2 + m_eur + cfd)
        out.append({
            "year": y, "gen": g, "eligible": eligible, "contracted": contracted,
            "t1_mwh": a1, "t1_price": p1, "t1_eur": e1,
            "t2_mwh": a2, "t2_price": p2, "t2_eur": e2,
            "merchant_mwh": m_mwh, "merchant_price": m_price, "merchant_eur": m_eur,
            "unsold_mwh": unsold, "cfd_eur": cfd, "total_eur": total,
            "cap_before": counter - (eligible if cap_application == "AFTER_SHARE" else g),
            "cap_after": counter,
        })
    return out


def ledger_from_fixture(fx: dict) -> List[dict]:
    """Run the exact Fraction ledger from an INDEPENDENT fixture dict (fixtures.py).
    The fixture carries inputs AND hand-derived expected rows; this function computes
    the oracle's own ledger from the inputs alone."""
    merchant_prices = fx["merchant_prices"]
    merchant_mode = "UNSOLD" if "UNSOLD" in merchant_prices else "MERCHANT_PRICE"
    if merchant_mode == "MERCHANT_PRICE":
        prices = {y: merchant_prices[y] for y in sorted(k for k in merchant_prices if k != "UNSOLD")}
    else:
        prices = {}
    cfd = fx.get("cfd") or {}
    return ledger(
        cap_mode=fx["cap_mode"], cap_application=fx["cap_application"],
        cap1_mwh=fx["cap1_mwh"], cap2_mwh=fx["cap2_mwh"],
        generation=fx["generation"], ppa_share=fx["ppa_share"],
        ppa_start=fx["ppa_start"], ppa_end=fx["ppa_end"],
        base_fixed=fx["base"][0], base_rate=fx["base"][1], base_base_year=fx["base"][2], base_fraction=fx["base"][3],
        reduced_fixed=fx["reduced"][0], reduced_rate=fx["reduced"][1], reduced_base_year=fx["reduced"][2], reduced_fraction=fx["reduced"][3],
        merchant_mode=merchant_mode, merchant_prices=prices,
        cfd_strike=cfd.get("strike", Fraction(0)), cfd_reference=cfd.get("reference", {}),
        years=sorted(fx["generation"]),
    )
