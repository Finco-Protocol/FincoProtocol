"""R03 — isolated two-tier PPA candidate (ANNUAL period axis, Decimal, fail-closed).

Adapted from the R01A independent core (branch ``feat/r01a-ppa-tiered-independent-core``
@ 4cace462, ``revenue_reference_core/core.py``), renamed to the R03 cap vocabulary and
extended with: per-tier independent indexation, PPA primary share with an explicit
cap-application hypothesis flag, merchant UNSOLD mode, CfD settlement overlay (no extra
physical sale), full-load-hour cap units with mandatory denominator metadata, per-period
source provenance, and cap=0 support where the mode defines it.

NOTHING here is reference-verified.  Q1-Q6 (cap units/window, cap2 meaning, tier
indexation, cap-vs-share order, above-cap tail, calendar edges) are OPEN owner decisions;
every result carries ``approved_for_finco=False`` and status ``SEMANTICS_UNVERIFIED``.
This package is never imported by product code in this task.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, localcontext, ROUND_HALF_EVEN, InvalidOperation
from typing import Mapping, Optional, Tuple

CONTRACT_VERSION = "R03_PPA_ISOLATED_V1"
STATUS = "SEMANTICS_UNVERIFIED"
PROVENANCE = "SYNTHETIC_ORACLE_ONLY"
APPROVED_FOR_FINCO = False

CAP_MODE = ("YEARLY_ABSOLUTE", "LIFE_ABSOLUTE", "YEARLY_INCREMENTAL", "LIFE_INCREMENTAL")
CAP_APPLICATION = ("AFTER_SHARE", "BEFORE_SHARE")   # Q4 hypotheses; NO default
ENERGY_UNIT = ("MWh", "GWh", "FLH")                 # FLH requires denominator_mw metadata
UNITS_TO_MWH = {"MWh": Decimal(1), "GWh": Decimal(1000)}
_PRICE_Q = Decimal("0.000001")                      # EUR, half-even, once per component per period
_PREC = 60


class ContractError(ValueError):
    """Fail-closed input rejection with an explicit reason (never zero-fill)."""


@dataclass(frozen=True)
class Quantity:
    """Energy quantity with explicit unit metadata; FLH carries its own denominator."""
    value: Decimal
    unit: str
    denominator_mw: Optional[Decimal] = None


@dataclass(frozen=True)
class TierIndex:
    """Per-tier independent indexation (Q3 hypothesis): the tier price is indexed by
    (1 + rate) ** (year - base_year) on the ``indexed_fraction`` share of the price."""
    rate: Decimal
    base_year: int
    indexed_fraction: Decimal


@dataclass(frozen=True)
class TierPrice:
    mode: str                                   # FIXED | INDEXED
    fixed_price_eur_mwh: Optional[Decimal] = None
    index: Optional[TierIndex] = None


@dataclass(frozen=True)
class MerchantSpec:
    mode: str                                   # MERCHANT_PRICE | UNSOLD
    prices: Tuple[Tuple[int, Decimal], ...] = ()   # explicit EUR/MWh for EVERY generation year (MERCHANT_PRICE)


@dataclass(frozen=True)
class CfdOverlay:
    """Settlement-only overlay: EUR = (strike - reference[year]) x contracted MWh.  Never an extra sale."""
    strike_eur_mwh: Decimal
    reference_prices: Tuple[Tuple[int, Decimal], ...]


@dataclass(frozen=True)
class R03Input:
    contract_id: str
    cap_mode: str
    cap_application: str                        # Q4 hypothesis; explicit, no default
    cap1: Quantity
    cap2: Quantity
    generation: Tuple[Tuple[int, Decimal], ...]  # (calendar_year, MWh) consecutive
    ppa_share: Decimal                          # 0..1 primary share of generation
    ppa_start_year: int
    ppa_end_year: int                           # inclusive
    base_price: TierPrice
    reduced_price: TierPrice
    merchant: MerchantSpec
    cfd: Optional[CfdOverlay] = None
    source_id: str = "SYNTHETIC"


@dataclass(frozen=True)
class TierResult:
    mwh: Decimal
    price_eur_mwh: Decimal
    revenue_eur: Decimal
    revenue_keur: Decimal


@dataclass(frozen=True)
class PeriodResult:
    year: int
    generation_mwh: Decimal
    ppa_share: Decimal
    eligible_mwh: Decimal
    contract_primary_mwh: Decimal
    cap_before_mwh: Decimal
    cap_after_mwh: Decimal
    tier1: TierResult
    tier2: TierResult
    merchant_mwh: Decimal
    unsold_mwh: Decimal
    merchant: TierResult
    cfd_settlement_eur: Decimal
    revenue_eur: Decimal
    revenue_keur: Decimal
    provenance: Mapping[str, str] = field(default_factory=dict)


def _dec(x, name):
    if isinstance(x, bool) or not isinstance(x, Decimal):
        raise ContractError(f"{name}: Decimal required (no float/int/str)")
    if not x.is_finite():
        raise ContractError(f"{name}: not finite")
    return x


def _q(x):
    return x.quantize(_PRICE_Q, rounding=ROUND_HALF_EVEN)


def _energy(q: Quantity, name) -> Decimal:
    if not isinstance(q, Quantity) or q.unit not in ENERGY_UNIT:
        raise ContractError(f"{name}: unit must be one of {ENERGY_UNIT}")
    v = _dec(q.value, name)
    if q.unit == "FLH":
        if q.denominator_mw is None or not isinstance(q.denominator_mw, Decimal) or not q.denominator_mw.is_finite() or q.denominator_mw <= 0:
            raise ContractError(f"{name}: FLH requires finite denominator_mw > 0")
        return v * q.denominator_mw
    return v * UNITS_TO_MWH[q.unit]


def _check_years(pairs, name):
    if not pairs:
        raise ContractError(f"{name}: empty")
    years = [y for y, _ in pairs]
    if any(isinstance(y, bool) or not isinstance(y, int) for y in years):
        raise ContractError(f"{name}: integer calendar years required")
    if len(set(years)) != len(years):
        raise ContractError(f"{name}: duplicate year")
    if years != sorted(years):
        raise ContractError(f"{name}: years not ascending")
    if any(b - a != 1 for a, b in zip(years, years[1:])):
        raise ContractError(f"{name}: years must be consecutive")


def _tier_price(p: TierPrice, year: int, name) -> Decimal:
    if p.mode == "FIXED":
        if p.fixed_price_eur_mwh is None:
            raise ContractError(f"{name}: FIXED requires a price")
        return _dec(p.fixed_price_eur_mwh, name)
    if p.mode == "INDEXED":
        ix = p.index
        if ix is None or p.fixed_price_eur_mwh is None:
            raise ContractError(f"{name}: INDEXED requires price + index")
        rate = _dec(ix.rate, f"{name} rate")
        frac = _dec(ix.indexed_fraction, f"{name} indexed_fraction")
        if not (0 <= frac <= 1) or rate <= -1:
            raise ContractError(f"{name}: indexation parameters out of range")
        if ix.base_year > year:
            return _dec(p.fixed_price_eur_mwh, name)      # before base year: unindexed
        f = (1 - frac) + frac * (1 + rate) ** (year - ix.base_year)
        return _dec(p.fixed_price_eur_mwh, name) * f
    raise ContractError(f"{name}: mode must be FIXED or INDEXED")


def compute_ppa_ledger(inp: R03Input) -> Tuple[PeriodResult, ...]:
    """Chronological per-year two-tier ledger.  Raises ContractError on any unverifiable input."""
    if not isinstance(inp, R03Input):
        raise ContractError("input type")
    if inp.cap_mode not in CAP_MODE:
        raise ContractError(f"cap_mode must be one of {CAP_MODE}; got {inp.cap_mode!r}")
    if inp.cap_application not in CAP_APPLICATION:
        raise ContractError(f"cap_application must be chosen explicitly from {CAP_APPLICATION} (Q4 open); got {inp.cap_application!r}")
    if not inp.contract_id:
        raise ContractError("contract_id required")
    try:
        with localcontext() as ctx:
            ctx.prec = _PREC
            _check_years(inp.generation, "generation")
            gen_years = [y for y, _ in inp.generation]
            if inp.merchant.mode == "MERCHANT_PRICE":
                if not inp.merchant.prices:
                    raise ContractError("merchant price missing for covered years (EVIDENCE_MISSING; never zero-fill)")
                _check_years(inp.merchant.prices, "merchant prices")
                if [y for y, _ in inp.merchant.prices] != gen_years:
                    raise ContractError("merchant price must cover exactly the generation years (missing != zero)")
            share = _dec(inp.ppa_share, "ppa_share")
            if not (0 <= share <= 1):
                raise ContractError("ppa_share must be 0..1")
            for name, p in (("base", inp.base_price), ("reduced", inp.reduced_price)):
                if p.mode == "FIXED" and p.fixed_price_eur_mwh is not None and _dec(p.fixed_price_eur_mwh, name) < 0:
                    raise ContractError(f"{name} price negative")
            c1, c2 = _energy(inp.cap1, "cap1"), _energy(inp.cap2, "cap2")
            if c1 < 0 or c2 < 0:
                raise ContractError("caps must be >= 0")
            if inp.cap_mode.endswith("ABSOLUTE") and c1 > c2:
                raise ContractError("ceiling mode requires cap1 <= cap2 (tier2 is the second absolute ceiling)")
            if (isinstance(inp.ppa_start_year, bool) or isinstance(inp.ppa_end_year, bool)
                    or not isinstance(inp.ppa_start_year, int) or not isinstance(inp.ppa_end_year, int)
                    or inp.ppa_start_year > inp.ppa_end_year):
                raise ContractError("impossible PPA period")
            if inp.cfd is not None:
                _dec(inp.cfd.strike_eur_mwh, "cfd strike")
                _check_years(inp.cfd.reference_prices, "cfd reference")
                if [y for y, _ in inp.cfd.reference_prices] != gen_years:
                    raise ContractError("cfd reference must cover exactly the generation years")
            cfd_ref = dict(inp.cfd.reference_prices) if inp.cfd else {}
            merch_prices = dict(inp.merchant.prices)
            t1_hi = c1
            t2_hi = c2 if inp.cap_mode.endswith("ABSOLUTE") else c1 + c2
            yearly = inp.cap_mode.startswith("YEARLY")
            counter = Decimal(0)
            out = []
            for year, g_raw in inp.generation:
                g = _dec(g_raw, f"generation {year}")
                if g < 0:
                    raise ContractError("negative generation")
                in_ppa = inp.ppa_start_year <= year <= inp.ppa_end_year
                if yearly:
                    counter = Decimal(0)
                cap_before = counter
                if inp.cap_application == "AFTER_SHARE":
                    eligible = g * share
                else:   # BEFORE_SHARE hypothesis: cap on full generation, share scales contracted MWh
                    eligible = g
                a1 = max(Decimal(0), min(counter + eligible, t1_hi) - min(counter, t1_hi)) if in_ppa else Decimal(0)
                a2 = (max(Decimal(0), min(counter + eligible, t2_hi) - max(min(counter, t2_hi), t1_hi))
                      if in_ppa else Decimal(0))
                if inp.cap_application == "AFTER_SHARE":
                    contracted = a1 + a2
                    merchant_mwh = g - contracted
                else:
                    # BEFORE_SHARE: the PPA share scales the contracted tiers; the share-scaled
                    # remainder is merchant.  Tiers were filled against the full generation.
                    contracted = (a1 + a2) * share
                    merchant_mwh = g - contracted
                    a1, a2 = a1 * share, a2 * share
                counter += eligible if inp.cap_application == "AFTER_SHARE" else g
                cap_after = counter
                unsold = Decimal(0)
                if inp.merchant.mode == "UNSOLD":
                    merchant_mwh_full = merchant_mwh
                    merchant_mwh = Decimal(0)
                    unsold = merchant_mwh_full
                    merch_price = Decimal(0)
                    merch_rev = _q(Decimal(0))
                else:
                    if year not in merch_prices:
                        raise ContractError(f"merchant price missing for {year} (EVIDENCE_MISSING; never zero-fill)")
                    merch_price = _dec(merch_prices[year], f"merchant {year}")
                    if merch_price < 0:
                        raise ContractError("merchant price negative")
                    merch_rev = _q(merchant_mwh * merch_price)
                k = _tier_price(inp.base_price, year, "base") if in_ppa else Decimal(0)
                kp = _tier_price(inp.reduced_price, year, "reduced") if in_ppa else Decimal(0)
                t1 = TierResult(a1, k if in_ppa else Decimal(0), _q(a1 * k), _q(a1 * k) / 1000)
                t2 = TierResult(a2, kp if in_ppa else Decimal(0), _q(a2 * kp), _q(a2 * kp) / 1000)
                merch = TierResult(merchant_mwh, merch_price, merch_rev, merch_rev / 1000)
                cfd_eur = _q(Decimal(0))
                if inp.cfd is not None and in_ppa:
                    ref = _dec(cfd_ref[year], f"cfd reference {year}")
                    cfd_eur = _q((inp.cfd.strike_eur_mwh - ref) * (a1 + a2))
                total = _q(t1.revenue_eur + t2.revenue_eur + merch.revenue_eur + cfd_eur)
                prov = {
                    "contract_id": inp.contract_id,
                    "contract_version": CONTRACT_VERSION,
                    "cap_mode": inp.cap_mode,
                    "cap_application": inp.cap_application,
                    "price_modes": f"base={inp.base_price.mode};reduced={inp.reduced_price.mode}",
                    "merchant_mode": inp.merchant.mode,
                    "cfd": "overlay-settlement" if inp.cfd else "none",
                    "source_id": inp.source_id,
                    "status": STATUS,
                    "provenance": PROVENANCE,
                    "approved_for_finco": "False",
                }
                out.append(PeriodResult(year, g, share,
                                        eligible, a1 + a2, cap_before, cap_after, t1, t2,
                                        merchant_mwh, unsold, merch, cfd_eur, total, total / 1000, prov))
            # global conservation: sum of physical components == total generation
            if any(p.tier1.mwh + p.tier2.mwh + p.merchant.mwh + p.unsold_mwh != p.generation_mwh for p in out):
                raise ContractError("internal conservation failure")
            return tuple(out)
    except InvalidOperation as e:
        raise ContractError("numeric failure") from e
