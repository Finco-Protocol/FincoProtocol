"""Pure two-tier PPA revenue candidate.  Decimal only, no I/O, no global state, no engine imports.

NOTHING here is reference-verified.  The semantics of the two caps (annual vs lifetime, ceiling vs incremental tranche) are NOT known
from any verified source, so the caller MUST choose ``cap_semantics`` explicitly; there is no default.  Every result carries
``status == "SEMANTICS_UNVERIFIED"`` and ``provenance == "SYNTHETIC_ORACLE_ONLY"``: it is never a parity claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext, ROUND_HALF_EVEN, InvalidOperation
from typing import Mapping, Optional, Tuple

CONTRACT_VERSION = "R01A_PPA_TIERED_V1"
STATUS = "SEMANTICS_UNVERIFIED"
PROVENANCE = "SYNTHETIC_ORACLE_ONLY"
#: Mathematically defined, exploratory modes.  Anything else (rolling, per-month, ...) is refused.
CAP_SEMANTICS = ("CUMULATIVE_LIFETIME_CEILING", "ANNUAL_CEILING", "CUMULATIVE_LIFETIME_INCREMENTAL", "ANNUAL_INCREMENTAL")
_UNITS = {"MWh": Decimal(1), "GWh": Decimal(1000)}
_EUR_Q = Decimal("0.000001")      # EUR rounded half-even to 6 dp, once, per component per period
_PREC = 60


class ContractError(ValueError):
    """Fail-closed input rejection."""


@dataclass(frozen=True)
class Quantity:
    value: Decimal
    unit: str


@dataclass(frozen=True)
class PpaTierInput:
    cap_semantics: Optional[str]
    generation: Tuple[Tuple[int, Decimal], ...]        # (calendar_year, energy) strictly consecutive years
    generation_unit: str
    cap1: Quantity
    cap2: Quantity
    base_price_eur_mwh: Decimal
    reduced_price_eur_mwh: Decimal
    merchant_price_eur_mwh: Tuple[Tuple[int, Decimal], ...]   # explicit nominal price for EVERY generation year
    ppa_start_year: int
    ppa_end_year: int                                   # inclusive
    index_base_year: Optional[int] = None
    index_rate: Decimal = Decimal(0)                    # annual factor, e.g. 0.02
    indexed_fraction: Decimal = Decimal(0)              # 0..1, share of the PPA price that is indexed; merchant is never indexed here


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
    base: TierResult
    reduced: TierResult
    merchant: TierResult
    revenue_eur: Decimal
    revenue_keur: Decimal


def _dec(x, name):
    if isinstance(x, bool) or not isinstance(x, Decimal):
        raise ContractError(f"{name}: Decimal required (no float/int/str)")
    if not x.is_finite():
        raise ContractError(f"{name}: not finite")
    return x


def _mwh(q, name):
    if not isinstance(q, Quantity) or q.unit not in _UNITS:
        raise ContractError(f"{name}: unit must be one of {sorted(_UNITS)}")
    return _dec(q.value, name) * _UNITS[q.unit]


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
        raise ContractError(f"{name}: years must be consecutive (a gap would silently break cumulative accounting)")


def _index_factor(inp, year):
    f = inp.indexed_fraction
    if f == 0:
        return Decimal(1)
    return (1 - f) + f * (1 + inp.index_rate) ** (year - inp.index_base_year)


def _q(x):
    return x.quantize(_EUR_Q, rounding=ROUND_HALF_EVEN)


def _tier(mwh, price):
    eur = _q(mwh * price)
    return TierResult(mwh=mwh, price_eur_mwh=price, revenue_eur=eur, revenue_keur=eur / 1000)


def compute_ppa_tiers(inp: PpaTierInput) -> Tuple[PeriodResult, ...]:
    """Chronological two-tier allocation.  Raises ContractError on any unverifiable or invalid input."""
    if not isinstance(inp, PpaTierInput):
        raise ContractError("input type")
    if inp.cap_semantics not in CAP_SEMANTICS:
        raise ContractError(f"cap_semantics must be chosen explicitly from {CAP_SEMANTICS}; got {inp.cap_semantics!r} ({STATUS})")
    if inp.generation_unit not in _UNITS:
        raise ContractError("generation_unit")
    if not isinstance(inp.cap1, Quantity) or not isinstance(inp.cap2, Quantity) or inp.cap1.unit != inp.cap2.unit:
        raise ContractError("caps must be Quantity objects in ONE common unit (mixed units refused)")
    try:
        with localcontext() as ctx:
            ctx.prec = _PREC
            _check_years(inp.generation, "generation")
            _check_years(inp.merchant_price_eur_mwh, "merchant_price")
            gen_years = [y for y, _ in inp.generation]
            if [y for y, _ in inp.merchant_price_eur_mwh] != gen_years:
                raise ContractError("merchant price unavailable for some year (must cover exactly the generation years)")
            for name, p in (("base", inp.base_price_eur_mwh), ("reduced", inp.reduced_price_eur_mwh)):
                if _dec(p, name) < 0:
                    raise ContractError(f"{name} price negative")
            for y, p in inp.merchant_price_eur_mwh:
                if _dec(p, f"merchant {y}") < 0:
                    raise ContractError("merchant price negative")
            gens = []
            for y, g in inp.generation:
                g = _dec(g, f"generation {y}")
                if g < 0:
                    raise ContractError("negative generation")
                gens.append(g * _UNITS[inp.generation_unit])
            c1, c2 = _mwh(inp.cap1, "cap1"), _mwh(inp.cap2, "cap2")
            if c1 <= 0 or c2 <= 0:
                raise ContractError("caps must be > 0")
            if inp.cap_semantics.endswith("CEILING") and not c1 < c2:
                raise ContractError("ceiling caps must be strictly ascending")
            if (isinstance(inp.ppa_start_year, bool) or isinstance(inp.ppa_end_year, bool)
                    or not isinstance(inp.ppa_start_year, int) or not isinstance(inp.ppa_end_year, int)
                    or inp.ppa_start_year > inp.ppa_end_year):
                raise ContractError("impossible PPA period")
            f, r = _dec(inp.indexed_fraction, "indexed_fraction"), _dec(inp.index_rate, "index_rate")
            if not (0 <= f <= 1) or r <= -1:
                raise ContractError("indexation parameters out of range")
            if f != 0:
                if inp.index_base_year is None or isinstance(inp.index_base_year, bool) or inp.index_base_year > inp.ppa_start_year:
                    raise ContractError("index_base_year required and must not be after the PPA start")
            t1_hi = c1
            t2_hi = c2 if inp.cap_semantics.endswith("CEILING") else c1 + c2
            annual = inp.cap_semantics.startswith("ANNUAL")
            counter = Decimal(0)
            out = []
            prices = dict(inp.merchant_price_eur_mwh)
            for (year, _), g in zip(inp.generation, gens):
                in_ppa = inp.ppa_start_year <= year <= inp.ppa_end_year
                a1 = a2 = Decimal(0)
                if in_ppa:
                    if annual:
                        counter = Decimal(0)
                    a1 = max(Decimal(0), min(counter + g, t1_hi) - min(counter, t1_hi))
                    a2 = max(Decimal(0), min(counter + g, t2_hi) - max(min(counter, t2_hi), t1_hi))
                    counter += g
                merch = g - a1 - a2
                if merch < 0 or a1 + a2 + merch != g:
                    raise ContractError("internal conservation failure")
                k = _index_factor(inp, year) if in_ppa else Decimal(1)
                b = _tier(a1, inp.base_price_eur_mwh * k)
                rd = _tier(a2, inp.reduced_price_eur_mwh * k)
                m = _tier(merch, prices[year])
                eur = b.revenue_eur + rd.revenue_eur + m.revenue_eur
                out.append(PeriodResult(year, g, b, rd, m, eur, eur / 1000))
            return tuple(out)
    except InvalidOperation as e:
        raise ContractError("numeric failure") from e
