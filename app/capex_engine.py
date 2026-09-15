"""CAPEX line-item engine — structured CAPEX with timing, groups, and manual overrides.

Mirrors the OPEX line-item philosophy for consistency.

Design principles:
- Immutable dataclasses (frozen=True) for all data structures
- CapexLineItem — individual CAPEX line with code, group, amount, timing
- CapexScheduleEntry — single year's computed value + metadata
- generate_capex_schedule() — build per-year schedule from line items
- build_capex_line_items_from_defaults() — project defaults

Backward compatible: current capex inputs remain unchanged at domain layer.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AssetClass(str, Enum):
    """CAPEX asset classification."""
    GENERATION = "generation"
    GRID = "grid"
    DEVELOPMENT = "development"
    EPC = "epc"
    CONTINGENCY = "contingency"
    LAND = "land"
    OTHER = "other"


class TimingProfile(str, Enum):
    """CAPEX timing profile — which periods draw down the capex amount."""
    UPFRONT = "upfront"           # 100% in period 0 / FC
    ELEVATED = "elevated"        # FC to COD (elevated draw)
    ANNUITY = "annuity"          # Equal amounts per period
    CUSTOM = "custom"           # Explicit per-period fractions


@dataclass(frozen=True)
class CapexLineItem:
    """A single CAPEX line item.

    Examples:
        - Grid connection, amount=5200 kEUR, elevated timing
        - EPC contract, amount=28000 kEUR, upfront
        - Contingency, amount=1400 kEUR, custom
    """
    code: str
    """Short code, e.g. 'GRID-CONN', 'EPC'."""

    name: str
    """Human-readable name, e.g. 'Grid Connection'."""

    group: str
    """Grouping label, e.g. 'Electrical', 'EPC', 'Development'."""

    subgroup: str = ""
    """Optional subgroup, e.g. 'Primary', 'Secondary'."""

    description: str = ""
    """Free-text description of the capex item."""

    amount_keur: float = 0.0
    """Total CAPEX amount in kEUR."""

    asset_class: AssetClass = AssetClass.OTHER
    """Asset classification for categorization."""

    timing_profile: TimingProfile = TimingProfile.UPFRONT
    """Timing draw profile."""

    timing_fractions: tuple[float, ...] = field(default_factory=lambda: (1.0,))
    """Per-period draw fractions when timing_profile=CUSTOM.
    Index = period index (0-based). Sum should be <= 1.0 (residual to equity)."""

    is_manual: bool = False
    """True if this line was manually entered (vs derived from defaults)."""

    notes: str = ""
    """Free-text notes for this capex line."""

    def has_manual_overrides(self) -> bool:
        """Return True if any year has a non-None manual override."""
        return False  # placeholder for future manual override per year


@dataclass(frozen=True)
class CapexScheduleEntry:
    """A single period's CAPEX draw for one line item."""
    capex_code: str
    capex_name: str
    group: str
    period_index: int       # 0-based period index
    draw_keur: float
    is_manual: bool
    notes: str = ""


@dataclass(frozen=True)
class CapexSchedule:
    """Full CAPEX schedule for all line items across all periods."""
    entries: tuple[CapexScheduleEntry, ...] = field(default_factory=lambda: ())
    """All individual entries."""

    total_by_period: tuple[float, ...] = field(default_factory=lambda: ())
    """Total CAPEX draw per period (kEUR)."""

    has_manual_items: bool = False
    """True if any line item is manual."""


def _draw_fractions(profile: TimingProfile, tenor: int,
                    custom_fractions: tuple[float, ...] = ()) -> list[float]:
    """Return per-period draw fractions for a given profile and tenor."""
    if profile == TimingProfile.UPFRONT:
        return [1.0] + [0.0] * (tenor - 1)
    elif profile == TimingProfile.ELEVATED:
        # Draw 80% in period 0 (FC), 20% in period 1 (COD), 0 thereafter
        result = [0.0] * tenor
        if tenor >= 1:
            result[0] = 0.80
        if tenor >= 2:
            result[1] = 0.20
        return result
    elif profile == TimingProfile.ANNUITY:
        frac = 1.0 / tenor if tenor > 0 else 1.0
        return [frac] * tenor
    elif profile == TimingProfile.CUSTOM:
        # Pad or trim custom_fractions to tenor
        fractions = list(custom_fractions)
        while len(fractions) < tenor:
            fractions.append(0.0)
        return fractions[:tenor]
    else:
        return [0.0] * tenor


def generate_capex_schedule(
    items: tuple[CapexLineItem, ...],
    tenor_periods: int = 28,
) -> CapexSchedule:
    """Generate a full CAPEX schedule from line items.

    Parameters
    ----------
    items : tuple[CapexLineItem, ...]
        CAPEX line items
    tenor_periods : int
        Number of financial periods (default 28 = 14-year semiannual)
    """
    if not items:
        return CapexSchedule()

    entries: list[CapexScheduleEntry] = []
    total_by_period = [0.0] * tenor_periods
    has_manual = any(i.is_manual for i in items)

    for item in items:
        fractions = _draw_fractions(item.timing_profile, tenor_periods, item.timing_fractions)
        for period_idx, frac in enumerate(fractions):
            draw = item.amount_keur * frac
            if draw <= 0.0:
                continue
            entry = CapexScheduleEntry(
                capex_code=item.code,
                capex_name=item.name,
                group=item.group,
                period_index=period_idx,
                draw_keur=draw,
                is_manual=item.is_manual,
                notes=item.notes,
            )
            entries.append(entry)
            total_by_period[period_idx] += draw

    return CapexSchedule(
        entries=tuple(entries),
        total_by_period=tuple(total_by_period),
        has_manual_items=has_manual,
    )


# =============================================================================
# DEFAULT BUILDER
# =============================================================================

def build_capex_line_items_from_defaults(
    technology: str = "solar",
    scale_mw: float = 50.0,
) -> tuple[CapexLineItem, ...]:
    """Build default CAPEX line items from technology type and scale.

    Mirrors the solar/wind default patterns from analyzed Excel models
    (Generic Wind Reference/Generic Solar Reference) — grid connection, BoS, EPC, development, contingency.

    Parameters
    ----------
    technology : str
        "solar" or "wind"
    scale_mw : float
        Installed capacity in MW (used to scale amounts)
    """
    if technology.lower() == "solar":
        # Grid connection (110kV)
        grid = CapexLineItem(
            code="GRID",
            name="Grid Connection (110kV)",
            group="Electrical",
            description="110kV grid connection and substation works",
            amount_keur=2800.0 + scale_mw * 40.0,
            asset_class=AssetClass.GRID,
            timing_profile=TimingProfile.ELEVATED,
        )
        # BoS (Balance of System)
        bos = CapexLineItem(
            code="BOS",
            name="Balance of System",
            group="Construction",
            description="Mounting systems, cabling, transformers",
            amount_keur=12000.0 + scale_mw * 120.0,
            asset_class=AssetClass.GENERATION,
            timing_profile=TimingProfile.ELEVATED,
        )
        # EPC contract
        epc = CapexLineItem(
            code="EPC",
            name="EPC Contract",
            group="Construction",
            description="Engineering, procurement, construction",
            amount_keur=35000.0 + scale_mw * 400.0,
            asset_class=AssetClass.EPC,
            timing_profile=TimingProfile.UPFRONT,
        )
        # Development costs
        dev = CapexLineItem(
            code="DEV",
            name="Development Costs",
            group="Development",
            description="Permits, licenses, development management",
            amount_keur=1800.0 + scale_mw * 20.0,
            asset_class=AssetClass.DEVELOPMENT,
            timing_profile=TimingProfile.UPFRONT,
        )
        # Contingency
        contingency = CapexLineItem(
            code="CONT",
            name="Contingency",
            group="Risk",
            description="10% contingency reserve",
            amount_keur=2500.0 + scale_mw * 35.0,
            asset_class=AssetClass.CONTINGENCY,
            timing_profile=TimingProfile.CUSTOM,
            timing_fractions=(0.5, 0.5),  # 50% upfront, 50% elevated
        )
        return (grid, bos, epc, dev, contingency)

    elif technology.lower() == "wind":
        grid = CapexLineItem(
            code="GRID",
            name="Grid Connection (110kV)",
            group="Electrical",
            description="110kV grid connection and substation works",
            amount_keur=3200.0 + scale_mw * 55.0,
            asset_class=AssetClass.GRID,
            timing_profile=TimingProfile.ELEVATED,
        )
        bos = CapexLineItem(
            code="BOS",
            name="Balance of System",
            group="Construction",
            description="Wind turbine foundations, cabling, transformers",
            amount_keur=18000.0 + scale_mw * 180.0,
            asset_class=AssetClass.GENERATION,
            timing_profile=TimingProfile.ELEVATED,
        )
        epc = CapexLineItem(
            code="EPC",
            name="EPC Contract",
            group="Construction",
            description="Engineering, procurement, construction",
            amount_keur=48000.0 + scale_mw * 550.0,
            asset_class=AssetClass.EPC,
            timing_profile=TimingProfile.UPFRONT,
        )
        dev = CapexLineItem(
            code="DEV",
            name="Development Costs",
            group="Development",
            description="Permits, licenses, development management",
            amount_keur=2200.0 + scale_mw * 30.0,
            asset_class=AssetClass.DEVELOPMENT,
            timing_profile=TimingProfile.UPFRONT,
        )
        contingency = CapexLineItem(
            code="CONT",
            name="Contingency",
            group="Risk",
            description="10% contingency reserve",
            amount_keur=3000.0 + scale_mw * 45.0,
            asset_class=AssetClass.CONTINGENCY,
            timing_profile=TimingProfile.CUSTOM,
            timing_fractions=(0.4, 0.6),
        )
        return (grid, bos, epc, dev, contingency)

    else:
        # Generic fallback
        return (
            CapexLineItem(
                code="CAP",
                name="CAPEX",
                group="General",
                description="General capital expenditure",
                amount_keur=10000.0 + scale_mw * 200.0,
                asset_class=AssetClass.OTHER,
                timing_profile=TimingProfile.UPFRONT,
            ),
        )