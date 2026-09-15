"""Bankable depreciation framework — tax/book separation, granular asset classes.

Architecture:
  CapexLineItem (app.capex_engine)
      ↓
  map_capex_line_item_to_depreciation_basis(item, profile)
      ↓
  generate_tax_and_book_schedule(basis_items, profile, total_periods)
      ↓
  TaxDepreciationSchedule + BookDepreciationSchedule
      ↓
  WaterfallRunConfig(tax_depreciation_schedule=..., book_depreciation_schedule=...)
      ↓
  waterfall_core → tax_shield from TAX schedule only
"""
from __future__ import annotations

import logging
import warnings
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class BankableAssetClass(str, Enum):
    """Granular asset classes for bankable depreciation."""
    SOLAR_MODULES = "solar_modules"
    WIND_TURBINES = "wind_turbines"
    INVERTERS = "inverters"
    MOUNTING_STRUCTURES = "mounting_structures"
    GRID_CONNECTION = "grid_connection"
    TRANSFORMER = "transformer"
    CIVIL_WORKS = "civil_works"
    DEVELOPMENT_SOFT = "development_soft"
    LAND = "land"
    CONTINGENCY = "contingency"
    OTHER = "other"


class DepreciationConvention(str, Enum):
    FULL_YEAR = "full_year"
    HALF_YEAR = "half_year"
    DAY_FRACTION = "day_fraction"  # pro-rata using period day_fraction
    COD_MONTH = "cod_month"


class DepreciationMethod(str, Enum):
    STRAIGHT_LINE = "straight_line"
    DECLINING_BALANCE = "declining_balance"
    NON_DEPRECIABLE = "non_depreciable"


# ---- Jurisdiction profiles ----

@dataclass
class AssetDepreciationRule:
    """Depreciation rule for one asset class in a given profile."""
    asset_class: BankableAssetClass
    tax_life_years: int
    book_life_years: int
    tax_method: DepreciationMethod = DepreciationMethod.STRAIGHT_LINE
    book_method: DepreciationMethod = DepreciationMethod.STRAIGHT_LINE
    tax_convention: DepreciationConvention = DepreciationConvention.DAY_FRACTION
    book_convention: DepreciationConvention = DepreciationConvention.DAY_FRACTION


@dataclass
class DepreciationProfile:
    """A jurisdiction-specific depreciation profile."""
    country: str
    regime: str  # e.g. "CIT", "IBL"
    asset_rules: dict[BankableAssetClass, AssetDepreciationRule]
    contingency_treatment: str = "proportional"  # "proportional" or "non_depreciable"
    source: str = ""
    notes: str = ""

    def rule_for(self, asset_class: BankableAssetClass) -> Optional[AssetDepreciationRule]:
        return self.asset_rules.get(asset_class)

    def tax_life(self, asset_class: BankableAssetClass) -> int:
        rule = self.rule_for(asset_class)
        return rule.tax_life_years if rule else 10

    def book_life(self, asset_class: BankableAssetClass) -> int:
        rule = self.rule_for(asset_class)
        return rule.book_life_years if rule else 10


@dataclass
class DepreciationBasisItem:
    """A single line item in the depreciation basis."""
    name: str
    code: str
    asset_class: BankableAssetClass
    amount_keur: float
    is_depreciable: bool = True


@dataclass
class TaxDepreciationEntry:
    """Tax depreciation for one period."""
    period: int
    asset_class: BankableAssetClass
    basis_amount_keur: float
    depreciation_keur: float
    accumulated_keur: float
    remaining_basis_keur: float


@dataclass
class BookDepreciationEntry:
    """Book depreciation for one period."""
    period: int
    asset_class: BankableAssetClass
    basis_amount_keur: float
    depreciation_keur: float
    accumulated_keur: float
    remaining_basis_keur: float


@dataclass
class TaxDepreciationSchedule:
    """Tax depreciation schedule — feeds waterfall tax shield."""
    entries: list[TaxDepreciationEntry]  # flat list of all entries across all periods
    total_periods: int
    profile_name: str

    def total_by_period(self, period: int) -> float:
        return sum(e.depreciation_keur for e in self.entries if e.period == period)

    def total_by_asset_class(self, asset_class: BankableAssetClass) -> list[float]:
        result = [0.0] * self.total_periods
        for e in self.entries:
            if e.asset_class == asset_class:
                result[e.period] = e.depreciation_keur
        return result


@dataclass
class BookDepreciationSchedule:
    """Book depreciation schedule — for reporting, NOT waterfall."""
    entries: list[BookDepreciationEntry]
    total_periods: int
    profile_name: str

    def total_by_period(self, period: int) -> float:
        return sum(e.depreciation_keur for e in self.entries if e.period == period)

    def total_by_asset_class(self, asset_class: BankableAssetClass) -> list[float]:
        """Return list of book depreciation per period for given asset class.
        
        Zero-filled where no entries exist for that asset class in a given period.
        """
        result = [0.0] * self.total_periods
        for e in self.entries:
            if e.asset_class == asset_class:
                result[e.period] = e.depreciation_keur
        return result


class DepreciationMappingWarning(UserWarning):
    """Raised when an asset class cannot be mapped."""
    pass


# ---- Default profiles ----

def _solar_profile() -> DepreciationProfile:
    rules = {
        BankableAssetClass.SOLAR_MODULES: AssetDepreciationRule(
            BankableAssetClass.SOLAR_MODULES, tax_life_years=20, book_life_years=25),
        BankableAssetClass.INVERTERS: AssetDepreciationRule(
            BankableAssetClass.INVERTERS, tax_life_years=10, book_life_years=10),
        BankableAssetClass.MOUNTING_STRUCTURES: AssetDepreciationRule(
            BankableAssetClass.MOUNTING_STRUCTURES, tax_life_years=20, book_life_years=25),
        BankableAssetClass.GRID_CONNECTION: AssetDepreciationRule(
            BankableAssetClass.GRID_CONNECTION, tax_life_years=20, book_life_years=20),
        BankableAssetClass.TRANSFORMER: AssetDepreciationRule(
            BankableAssetClass.TRANSFORMER, tax_life_years=20, book_life_years=20),
        BankableAssetClass.CIVIL_WORKS: AssetDepreciationRule(
            BankableAssetClass.CIVIL_WORKS, tax_life_years=20, book_life_years=25),
        BankableAssetClass.DEVELOPMENT_SOFT: AssetDepreciationRule(
            BankableAssetClass.DEVELOPMENT_SOFT, tax_life_years=5, book_life_years=5),
        BankableAssetClass.LAND: AssetDepreciationRule(
            BankableAssetClass.LAND, tax_life_years=0, book_life_years=0,
            tax_method=DepreciationMethod.NON_DEPRECIABLE,
            book_method=DepreciationMethod.NON_DEPRECIABLE),
        BankableAssetClass.CONTINGENCY: AssetDepreciationRule(
            BankableAssetClass.CONTINGENCY, tax_life_years=5, book_life_years=5),
        BankableAssetClass.OTHER: AssetDepreciationRule(
            BankableAssetClass.OTHER, tax_life_years=10, book_life_years=10),
    }
    return DepreciationProfile(
        country="Generic Market A", regime="IBL",
        asset_rules=rules, contingency_treatment="proportional",
        source="Generic Market An IB Law / Tax Authority",
        notes="Default solar profile for Generic Market An IB regime")


def _wind_profile() -> DepreciationProfile:
    rules = {
        # Wind turbines: separate asset class (20y tax / 25y book)
        BankableAssetClass.WIND_TURBINES: AssetDepreciationRule(
            BankableAssetClass.WIND_TURBINES, tax_life_years=20, book_life_years=25),
        BankableAssetClass.INVERTERS: AssetDepreciationRule(
            BankableAssetClass.INVERTERS, tax_life_years=10, book_life_years=10),
        BankableAssetClass.MOUNTING_STRUCTURES: AssetDepreciationRule(
            BankableAssetClass.MOUNTING_STRUCTURES, tax_life_years=20, book_life_years=25),
        BankableAssetClass.GRID_CONNECTION: AssetDepreciationRule(
            BankableAssetClass.GRID_CONNECTION, tax_life_years=20, book_life_years=20),
        BankableAssetClass.TRANSFORMER: AssetDepreciationRule(
            BankableAssetClass.TRANSFORMER, tax_life_years=20, book_life_years=20),
        BankableAssetClass.CIVIL_WORKS: AssetDepreciationRule(
            BankableAssetClass.CIVIL_WORKS, tax_life_years=20, book_life_years=25),
        BankableAssetClass.DEVELOPMENT_SOFT: AssetDepreciationRule(
            BankableAssetClass.DEVELOPMENT_SOFT, tax_life_years=5, book_life_years=5),
        BankableAssetClass.LAND: AssetDepreciationRule(
            BankableAssetClass.LAND, tax_life_years=0, book_life_years=0,
            tax_method=DepreciationMethod.NON_DEPRECIABLE,
            book_method=DepreciationMethod.NON_DEPRECIABLE),
        BankableAssetClass.CONTINGENCY: AssetDepreciationRule(
            BankableAssetClass.CONTINGENCY, tax_life_years=5, book_life_years=5),
        BankableAssetClass.OTHER: AssetDepreciationRule(
            BankableAssetClass.OTHER, tax_life_years=10, book_life_years=10),
    }
    return DepreciationProfile(
        country="Generic Market A", regime="IBL",
        asset_rules=rules, contingency_treatment="proportional",
        source="Generic Market An IB Law / Tax Authority",
        notes="Default wind profile for Generic Market An IB regime")


PROFILES = {
    "solar_generic_market_a_ibl": _solar_profile,
    "wind_generic_market_a_ibl": _wind_profile,
}


def get_profile(name: str) -> DepreciationProfile:
    """Get a named profile, or return solar default."""
    if name in PROFILES:
        return PROFILES[name]()
    logger.warning("Unknown depreciation profile %r, using solar default", name)
    return _solar_profile()


# ---- Asset class mapping ----

def _is_inverter(item_name: str, item_code: str) -> bool:
    name_lower = item_name.lower()
    code_lower = item_code.lower()
    inverter_keywords = ["inverter", "dc/ac", "power electronics", "pv inverter",
                         "string inverter", "central inverter", "optimizer"]
    return any(kw in name_lower or kw in code_lower for kw in inverter_keywords)


def _is_land(item_name: str, item_code: str) -> bool:
    name_lower = item_name.lower()
    code_lower = item_code.lower()
    return "land" in name_lower or "zemlji" in name_lower or "zemlja" in name_lower


def map_capex_line_item_to_basis(item, profile: DepreciationProfile, project_type: str = "Solar") -> DepreciationBasisItem:
    """Map a CapexLineItem to a DepreciationBasisItem with granular asset class.

    This function inspects item.asset_class, item.code, and item.name to determine
    the bankable asset class.
    """
    name = getattr(item, 'name', '') or ''
    code = getattr(item, 'code', '') or ''
    amount = getattr(item, 'amount_keur', 0.0) or 0.0
    orig_class = getattr(item, 'asset_class', None)

    # Determine bankable asset class
    if _is_land(name, code):
        ac = BankableAssetClass.LAND
    elif _is_inverter(name, code):
        ac = BankableAssetClass.INVERTERS
    elif orig_class is not None:
        # Map legacy AssetClass to bankable
        orig_str = orig_class.name.upper() if hasattr(orig_class, 'name') else str(orig_class).upper()
        # GENERATION maps to SOLAR_MODULES for Solar, WIND_TURBINES for Wind
        gen_class = BankableAssetClass.WIND_TURBINES if project_type.lower() == "wind" else BankableAssetClass.SOLAR_MODULES
        mapping = {
            "GENERATION": gen_class,
            "GRID": BankableAssetClass.GRID_CONNECTION,
            "DEVELOPMENT": BankableAssetClass.DEVELOPMENT_SOFT,
            "EPC": BankableAssetClass.CIVIL_WORKS,
            "CONTINGENCY": BankableAssetClass.CONTINGENCY,
            "LAND": BankableAssetClass.LAND,
            "OTHER": BankableAssetClass.OTHER,
        }
        ac = mapping.get(orig_str, BankableAssetClass.OTHER)
        if ac == BankableAssetClass.OTHER and orig_str != "OTHER":
            warnings.warn(
                DepreciationMappingWarning(
                    f"asset_class {orig_class!r} not in mapping, treating as OTHER. "
                    f"item={name!r} code={code!r}"))
    else:
        ac = BankableAssetClass.OTHER
        warnings.warn(
            DepreciationMappingWarning(
                f"unknown asset class for {name!r} ({code!r}), using OTHER"))

    # OTHER is depreciable using explicit 10y fallback
    # LAND is non-depreciable
    # CONTINGENCY is handled via explicit proportional allocation
    is_depreciable = (
        ac not in (BankableAssetClass.LAND,) and
        not (profile.rule_for(ac) and
             profile.rule_for(ac).tax_method == DepreciationMethod.NON_DEPRECIABLE)
    )

    return DepreciationBasisItem(
        name=name, code=code, asset_class=ac,
        amount_keur=amount, is_depreciable=is_depreciable)


def _generate_asset_schedule(
    asset_class: BankableAssetClass,
    amount_keur: float,
    rule: AssetDepreciationRule,
    profile: DepreciationProfile,
    total_periods: int,
    day_fractions: list[float],
    tax_entries: list[TaxDepreciationEntry],
    book_entries: list[BookDepreciationEntry],
    source: str = "direct"
) -> None:
    """Generate tax and book entries for one asset class."""
    if amount_keur <= 0 or rule.tax_life_years <= 0:
        return

    # Validate convention/method before generation
    if rule.tax_convention not in (DepreciationConvention.DAY_FRACTION, DepreciationConvention.FULL_YEAR):
        raise NotImplementedError(
            f"tax_convention {rule.tax_convention.value!r} not implemented. "
            f"Supported: day_fraction, full_year. "
            f"HALF_YEAR, COD_MONTH are future extensions."
        )
    if rule.tax_method not in (DepreciationMethod.STRAIGHT_LINE, DepreciationMethod.NON_DEPRECIABLE):
        raise NotImplementedError(
            f"tax_method {rule.tax_method.value!r} not implemented. "
            f"Supported: straight_line, non_depreciable. "
            f"declining_balance is a future extension."
        )

    # Tax schedule
    tax_remaining = amount_keur
    for p in range(total_periods):
        df = day_fractions[p] if p < len(day_fractions) else 1.0
        depr = (amount_keur / max(1, rule.tax_life_years)) * df if p < rule.tax_life_years else 0.0
        depr = min(depr, tax_remaining)
        tax_remaining -= depr
        tax_entries.append(TaxDepreciationEntry(
            period=p, asset_class=asset_class,
            basis_amount_keur=amount_keur,
            depreciation_keur=round(depr, 4),
            accumulated_keur=round(amount_keur - tax_remaining, 4),
            remaining_basis_keur=round(max(0, tax_remaining), 4)
        ))

    # Validate book convention/method
    if rule.book_convention not in (DepreciationConvention.DAY_FRACTION, DepreciationConvention.FULL_YEAR):
        raise NotImplementedError(
            f"book_convention {rule.book_convention.value!r} not implemented. "
            f"Supported: day_fraction, full_year. "
            f"HALF_YEAR, COD_MONTH are future extensions."
        )
    if rule.book_method not in (DepreciationMethod.STRAIGHT_LINE, DepreciationMethod.NON_DEPRECIABLE):
        raise NotImplementedError(
            f"book_method {rule.book_method.value!r} not implemented. "
            f"Supported: straight_line, non_depreciable."
        )

    # Book schedule
    book_remaining = amount_keur
    for p in range(total_periods):
        df = day_fractions[p] if p < len(day_fractions) else 1.0
        depr = (amount_keur / max(1, rule.book_life_years)) * df if p < rule.book_life_years else 0.0
        depr = min(depr, book_remaining)
        book_remaining -= depr
        book_entries.append(BookDepreciationEntry(
            period=p, asset_class=asset_class,
            basis_amount_keur=amount_keur,
            depreciation_keur=round(depr, 4),
            accumulated_keur=round(amount_keur - book_remaining, 4),
            remaining_basis_keur=round(max(0, book_remaining), 4)
        ))



def to_waterfall_depreciation_schedule(tax_schedule: TaxDepreciationSchedule) -> dict:
    """Convert TaxDepreciationSchedule to waterfall-compatible dict format.

    Returns a dict with:
      - total_by_period: list of floats (annual tax depreciation per period)
      - profile_name: str
      - total_periods: int

    This is the bridge between depreciation_bankable and the existing
    WaterfallRunConfig(advanced_capex_depreciation_schedule=...) integration.

    BookDepreciationSchedule is NOT included — it is for reporting only.

    Usage:
        from app.depreciation_bankable import (
            generate_tax_and_book_schedule, get_profile, to_waterfall_depreciation_schedule
        )
        tax_sched, book_sched = generate_tax_and_book_schedule(basis_items, profile, 20)
        waterfall_depr = to_waterfall_depreciation_schedule(tax_sched)
        # waterfall_depr["total_by_period"] can be used in WaterfallRunConfig
    """
    total_by_period = [tax_schedule.total_by_period(p) for p in range(tax_schedule.total_periods)]
    return {
        "total_by_period": total_by_period,
        "profile_name": tax_schedule.profile_name,
        "total_periods": tax_schedule.total_periods,
        # Include per-asset-class breakdown for Excel export
        "by_asset_class": {
            ac.value: tax_schedule.total_by_asset_class(ac)
            for ac in set(e.asset_class for e in tax_schedule.entries)
        }
    }


def build_bankable_waterfall_schedule(
    capex_line_items,
    profile_name: str = "solar_generic_market_a_ibl",
    total_periods: int = 20,
    convention: DepreciationConvention = DepreciationConvention.FULL_YEAR,
    day_fractions: Optional[list[float]] = None,
    project_type: str = "Solar",
) -> dict:
    """One-step bridge: CapexLineItems → waterfall-compatible depreciation dict.

    Args:
        capex_line_items: list of CapexLineItem from app.capex_engine
        profile_name: name of DepreciationProfile to use
        total_periods: number of annual periods
        convention: DepreciationConvention — MUST be FULL_YEAR for runtime bridge.
            FULL_YEAR ensures generate_tax_and_book_schedule() returns ANNUAL amounts
            (not day-fraction-pro-rated). waterfall_core then applies day_fraction
            exactly once as the single authoritative application point.
        project_type: "Solar" or "Wind" — used to map GENERATION CapexLineItem
            to WIND_TURBINES or SOLAR_MODULES respectively.

    Returns:
        dict for WaterfallRunConfig(advanced_capex_depreciation_schedule=...)
        Contains: total_by_period, by_asset_class, profile_name, total_periods

    Note:
        Book depreciation is generated but NOT passed to waterfall — it is
        stored in the result for Excel export reporting only.
    """
    profile = get_profile(profile_name)
    basis_items = [map_capex_line_item_to_basis(item, profile, project_type) for item in capex_line_items]
    # convention parameter is passed through to generate_tax_and_book_schedule.
    # For runtime: use FULL_YEAR (day_fraction applied in waterfall_core).
    # For testing: can pass DAY_FRACTION with explicit day_fractions.
    tax_sched, book_sched = generate_tax_and_book_schedule(
        basis_items, profile, total_periods=total_periods,
        convention=convention,
        day_fractions=day_fractions,
    )
    return WaterfallDepreciationSchedule(to_waterfall_depreciation_schedule(tax_sched))

def generate_tax_and_book_schedule(
    basis_items: list[DepreciationBasisItem],
    profile: DepreciationProfile,
    total_periods: int,
    convention: DepreciationConvention = DepreciationConvention.DAY_FRACTION,
    day_fractions: Optional[list[float]] = None,
) -> tuple[TaxDepreciationSchedule, BookDepreciationSchedule]:
    """Generate tax and book depreciation schedules from basis items.

    Args:
        basis_items: list of DepreciationBasisItem from map_capex_line_item_to_basis()
        profile: DepreciationProfile for tax and book lives/methods
        total_periods: number of annual periods
        day_fractions: optional per-period day fractions (0..1) for DAY_FRACTION convention

    Returns:
        (TaxDepreciationSchedule, BookDepreciationSchedule)
    """
    if day_fractions is None:
        day_fractions = [1.0] * total_periods

    # When FULL_YEAR convention is requested, set day_fractions to all-1.0
    # to produce annual (non-pro-rated) depreciation amounts.
    # This ensures generate_tax_and_book_schedule() returns ANNUAL amounts,
    # and waterfall_core applies day_fraction exactly once.
    if convention == DepreciationConvention.FULL_YEAR:
        day_fractions = [1.0] * total_periods

    tax_entries: list[TaxDepreciationEntry] = []
    book_entries: list[BookDepreciationEntry] = []

    # Handle contingency proportional allocation
    contingency_items = [b for b in basis_items if b.asset_class == BankableAssetClass.CONTINGENCY]
    depreciable_items = [b for b in basis_items
                         if b.is_depreciable and b.asset_class != BankableAssetClass.CONTINGENCY]
    total_depr_basis = sum(b.amount_keur for b in depreciable_items)

    for item in basis_items:
        if item.asset_class == BankableAssetClass.CONTINGENCY:
            # Allocate proportionally to depreciable asset classes
            if total_depr_basis > 0 and item.amount_keur > 0:
                for di in depreciable_items:
                    alloc_pct = di.amount_keur / total_depr_basis
                    alloc_amount = item.amount_keur * alloc_pct
                    rule = profile.rule_for(di.asset_class)
                    if not rule or rule.tax_method == DepreciationMethod.NON_DEPRECIABLE:
                        continue
                    _generate_asset_schedule(
                        di.asset_class, alloc_amount, rule, profile,
                        total_periods, day_fractions, tax_entries, book_entries, "contingency"
                    )
            continue

        if not item.is_depreciable:
            continue

        rule = profile.rule_for(item.asset_class)
        if not rule:
            logger.warning("No depreciation rule for %s, treating as OTHER 10y",
                          item.asset_class.value)
            rule = AssetDepreciationRule(item.asset_class, 10, 10)

        if rule.tax_method == DepreciationMethod.NON_DEPRECIABLE:
            continue

        _generate_asset_schedule(
            item.asset_class, item.amount_keur, rule, profile,
            total_periods, day_fractions, tax_entries, book_entries, "direct"
        )

    tax_sched = TaxDepreciationSchedule(
        entries=tax_entries, total_periods=total_periods,
        profile_name=f"{profile.country}_{profile.regime}")
    book_sched = BookDepreciationSchedule(
        entries=book_entries, total_periods=total_periods,
        profile_name=f"{profile.country}_{profile.regime}")

    return tax_sched, book_sched

class WaterfallDepreciationSchedule:
    """Bridge wrapper: dict from to_waterfall_depreciation_schedule() → waterfall-compatible object.
    
    waterfall_core accesses schedule.total_by_period as a list.
    to_waterfall_depreciation_schedule() returns a plain dict.
    This wrapper provides the attribute access waterfall_core expects.
    """
    def __init__(self, data: dict):
        self._data = data
    
    @property
    def total_by_period(self) -> list[float]:
        return self._data["total_by_period"]
    
    @property
    def profile_name(self) -> str:
        return self._data.get("profile_name", "unknown")
    
    @property
    def total_periods(self) -> int:
        return self._data.get("total_periods", len(self._data["total_by_period"]))
    
    @property
    def by_asset_class(self) -> dict:
        return self._data.get("by_asset_class", {})
