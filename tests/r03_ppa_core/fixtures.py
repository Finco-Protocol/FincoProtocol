"""R03 INDEPENDENT FIXTURES — hand-derived inputs and expected ledgers.

This module is the single source of expected values for the R03 oracle tests.
Every expected number below is hand-derived from the written spec (annual two-tier
ledger semantics) in EXACT Fractions — it never reads implementation output or
provenance.  The Decimal implementation and the Fraction oracle are both compared
against these fixtures.
"""
from __future__ import annotations

from fractions import Fraction

F = Fraction


def _row(year, gen, eligible, t1_mwh, t1_p, t2_mwh, t2_p, m_mwh, m_p, unsold=Fraction(0), cfd=Fraction(0)):
    t1_e = _round6(t1_mwh * t1_p)
    t2_e = _round6(t2_mwh * t2_p)
    m_e = _round6(m_mwh * m_p)
    total = _round6(t1_e + t2_e + m_e + cfd)
    return {
        "year": year, "gen": F(gen), "eligible": F(eligible),
        "t1_mwh": F(t1_mwh), "t1_price": F(t1_p), "t1_eur": t1_e,
        "t2_mwh": F(t2_mwh), "t2_price": F(t2_p), "t2_eur": t2_e,
        "merchant_mwh": F(m_mwh), "merchant_price": F(m_p), "merchant_eur": m_e,
        "unsold_mwh": F(unsold), "cfd_eur": F(cfd), "total_eur": total,
    }


def _round6(f: Fraction, dp: int = 6) -> Fraction:
    scale = 10 ** dp
    scaled = f * scale
    n, d = scaled.numerator, scaled.denominator
    q, r = divmod(n, d)
    twice = 2 * r
    if twice > d or (twice == d and q % 2 != 0):
        q += 1
    return Fraction(q, scale)


# ── FIXTURE 1: owner's illustrative vector (LIFE_INCREMENTAL, AFTER_SHARE) ──
# gen 1500, share 0.8 -> eligible 1200; cap1 900, cap2 300 incremental (t2_hi 1200)
# t1 900 @70 = 63000; t2 300 @45 = 13500; merchant 300 @55 = 16500; total 93000.
FIXTURE_1 = {
    "cap_mode": "LIFE_INCREMENTAL", "cap_application": "AFTER_SHARE",
    "cap1_mwh": F(900), "cap2_mwh": F(300),
    "generation": {2030: F(1500)},
    "ppa_share": F(4, 5), "ppa_start": 2030, "ppa_end": 2030,
    "base": (F(70), F(0), 2030, F(0)), "reduced": (F(45), F(0), 2030, F(0)),
    "merchant_prices": {2030: F(55)},
    "expected": [_row(2030, 1500, 1200, 900, 70, 300, 45, 300, 55)],
}

# ── FIXTURE 2: yearly-vs-lifetime counterexample (Q1/Q2 metamorphic) ──
# gen 700+700, share 0.8 -> eligible 560/yr; YEARLY_INCREMENTAL resets: t1 560+560;
# LIFE_INCREMENTAL: t1 560+340 (900 cap), t2 0+220 (300 tranche after 340... hand-check:
# LIFE: counter 560 -> 2031 growth 560: t1 = min(1120,900)-560 = 340; t2 = min(1120,1200)-max(min(1120,1200),900) = 1120-900 = 220; merchant = 560-340-220 = 0.
FIXTURE_2_YEARLY = {
    "cap_mode": "YEARLY_INCREMENTAL", "cap_application": "AFTER_SHARE",
    "cap1_mwh": F(900), "cap2_mwh": F(300),
    "generation": {2030: F(700), 2031: F(700)},
    "ppa_share": F(4, 5), "ppa_start": 2030, "ppa_end": 2031,
    "base": (F(70), F(0), 2030, F(0)), "reduced": (F(45), F(0), 2030, F(0)),
    "merchant_prices": {2030: F(55), 2031: F(55)},
    "expected": [_row(2030, 700, 560, 560, 70, 0, 45, 140, 55),
                 _row(2031, 700, 560, 560, 70, 0, 45, 140, 55)],
}
FIXTURE_2_LIFE = {
    "cap_mode": "LIFE_INCREMENTAL", "cap_application": "AFTER_SHARE",
    "cap1_mwh": F(900), "cap2_mwh": F(300),
    "generation": {2030: F(700), 2031: F(700)},
    "ppa_share": F(4, 5), "ppa_start": 2030, "ppa_end": 2031,
    "base": (F(70), F(0), 2030, F(0)), "reduced": (F(45), F(0), 2030, F(0)),
    "merchant_prices": {2030: F(55), 2031: F(55)},
    "expected": [_row(2030, 700, 560, 560, 70, 0, 45, 140, 55),
                 _row(2031, 700, 560, 340, 70, 220, 45, 140, 55)],
}

# ── FIXTURE 3: BEFORE_SHARE hypothesis (Q4) on the same shape as FIXTURE 1 ──
# tiers filled against FULL 1500: t1 900, t2 300; then x 0.8 -> 720/240; merchant 540.
FIXTURE_3 = {
    "cap_mode": "LIFE_INCREMENTAL", "cap_application": "BEFORE_SHARE",
    "cap1_mwh": F(900), "cap2_mwh": F(300),
    "generation": {2030: F(1500)},
    "ppa_share": F(4, 5), "ppa_start": 2030, "ppa_end": 2030,
    "base": (F(70), F(0), 2030, F(0)), "reduced": (F(45), F(0), 2030, F(0)),
    "merchant_prices": {2030: F(55)},
    "expected": [_row(2030, 1500, 1500, 720, 70, 240, 45, 540, 55)],
}

# ── FIXTURE 4: per-tier independent indexation (Q3), share 1.0 ──
# base 70 indexed 2% from 2030 (fraction 1): 70 -> 71.40; reduced flat 45; caps large.
FIXTURE_4 = {
    "cap_mode": "LIFE_ABSOLUTE", "cap_application": "AFTER_SHARE",
    "cap1_mwh": F(2000), "cap2_mwh": F(4000),
    "generation": {2030: F(500), 2031: F(500)},
    "ppa_share": F(1), "ppa_start": 2030, "ppa_end": 2031,
    "base": (F(70), F(2, 100), 2030, F(1)), "reduced": (F(45), F(0), 2030, F(0)),
    "merchant_prices": {2030: F(55), 2031: F(55)},
    "expected": [_row(2030, 500, 500, 500, 70, 0, 45, 0, 55),
                 _row(2031, 500, 500, 500, _round6(F(70) * F(102, 100)), 0, 45, 0, 55)],
}

# ── FIXTURE 5: CfD NEGATIVE settlement (strike below reference) — directional ──
# same shape as FIXTURE 1; strike 45 vs reference 55 -> overlay (45-55)*1200 = -12000.
FIXTURE_5_CFD = {"strike": F(45), "reference": {2030: F(55)}}
FIXTURE_5 = dict(FIXTURE_1)
FIXTURE_5["cfd"] = FIXTURE_5_CFD
_fix1 = FIXTURE_1["expected"][0]
FIXTURE_5["expected"] = [_row(2030, 1500, 1200, 900, 70, 300, 45, 300, 55, cfd=F(-12000))]
FIXTURE_5["expected"][0]["total_eur"] = _round6(F(76500) + F(16500) - F(12000))

# ── FIXTURE 6: UNSOLD (no merchant tail; explicit unsold MWh, zero revenue) ──
FIXTURE_6 = {
    "cap_mode": "LIFE_INCREMENTAL", "cap_application": "AFTER_SHARE",
    "cap1_mwh": F(900), "cap2_mwh": F(300),
    "generation": {2030: F(1500)},
    "ppa_share": F(4, 5), "ppa_start": 2030, "ppa_end": 2030,
    "base": (F(70), F(0), 2030, F(0)), "reduced": (F(45), F(0), 2030, F(0)),
    "merchant_prices": {"UNSOLD": None},
    "expected": [_row(2030, 1500, 1200, 900, 70, 300, 45, 0, 0, unsold=300)],
}

# ── FIXTURE 7: no-early-rounding discriminator ──
# price 55.123456789 x 1200 MWh = 66148.14814680 -> 6dp = 66148.148147.
# Early price-rounding (55.123457 x 1200) would give 66148.1484 — different.
FIXTURE_7 = {
    "cap_mode": "LIFE_ABSOLUTE", "cap_application": "AFTER_SHARE",
    "cap1_mwh": F(2000), "cap2_mwh": F(4000),
    "generation": {2030: F(1200)},
    "ppa_share": F(1), "ppa_start": 2030, "ppa_end": 2030,
    "base": (F("55.123456789"), F(0), 2030, F(0)), "reduced": (F(45), F(0), 2030, F(0)),
    "merchant_prices": {2030: F(55)},
    "expected": [_row(2030, 1200, 1200, 1200, F("55.123456789"), 0, 45, 0, 55)],
}


# ── FIXTURE 8: zero cap1 (Correction D) — YEARLY_INCREMENTAL cap1=0, cap2=500 ──
# eligible 1200: t1 window [0,0] empty; t2 tranche 0..500 @45 = 22500; merchant 1000 @55.
FIXTURE_8 = {
    "cap_mode": "YEARLY_INCREMENTAL", "cap_application": "AFTER_SHARE",
    "cap1_mwh": F(0), "cap2_mwh": F(500),
    "generation": {2030: F(1500)},
    "ppa_share": F(4, 5), "ppa_start": 2030, "ppa_end": 2030,
    "base": (F(70), F(0), 2030, F(0)), "reduced": (F(45), F(0), 2030, F(0)),
    "merchant_prices": {2030: F(55)},
    "expected": [_row(2030, 1500, 1200, 0, 70, 500, 45, 1000, 55)],
}

# ── FIXTURE 9: partial first/last operating years (Correction D) ──
# gen 300/1500/400 (partial COD year + partial final year), share 0.8 -> eligible
# 240/1200/320; LIFE_INCREMENTAL cap1 2000 covers all (1760 cumulative) -> all tier1;
# merchant = gen - contracted = 60/300/80.
FIXTURE_9 = {
    "cap_mode": "LIFE_INCREMENTAL", "cap_application": "AFTER_SHARE",
    "cap1_mwh": F(2000), "cap2_mwh": F(4000),
    "generation": {2030: F(300), 2031: F(1500), 2032: F(400)},
    "ppa_share": F(4, 5), "ppa_start": 2030, "ppa_end": 2032,
    "base": (F(70), F(0), 2030, F(0)), "reduced": (F(45), F(0), 2030, F(0)),
    "merchant_prices": {2030: F(55), 2031: F(55), 2032: F(55)},
    "expected": [_row(2030, 300, 240, 240, 70, 0, 45, 60, 55),
                 _row(2031, 1500, 1200, 1200, 70, 0, 45, 300, 55),
                 _row(2032, 400, 320, 320, 70, 0, 45, 80, 55)],
}
