"""Result types for the generic hierarchical OPEX engine.

All types are frozen dataclasses to preserve audit-trail integrity.
Results expose enough detail for line-by-line reconciliation against
any source model.
"""
from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Annual result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubitemAnnualResult:
    """Per-subitem contribution to a category in one operating year."""

    code: str
    name: str
    base_amount_keur: float
    active: bool
    escalation_factor: float
    annual_keur: float  # = base_amount_keur × active × escalation_factor


@dataclass(frozen=True)
class CategoryAnnualResult:
    """Per-category annual OPEX and the subitem breakdown driving it."""

    code: str
    name: str
    subitems: tuple[SubitemAnnualResult, ...]   # empty for PERCENTAGE categories
    annual_keur: float


@dataclass(frozen=True)
class OpexAnnualResult:
    """Full OPEX annual result for one operating year."""

    year_index: int  # 1-based
    categories: tuple[CategoryAnnualResult, ...]
    total_keur: float


# ---------------------------------------------------------------------------
# Period result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubitemPeriodResult:
    """Per-subitem contribution to a category in one model period."""

    code: str
    name: str
    active: bool
    period_keur: float  # prorated by day_fraction


@dataclass(frozen=True)
class CategoryPeriodResult:
    """Per-category period OPEX and the subitem breakdown driving it."""

    code: str
    name: str
    subitems: tuple[SubitemPeriodResult, ...]   # empty for PERCENTAGE categories
    period_keur: float


@dataclass(frozen=True)
class OpexPeriodResult:
    """Full OPEX result for one model period."""

    period_index: int
    year_index: int    # 1-based operating year
    period_in_year: int  # 1 or 2 (semestrial), 1 for annual
    day_fraction: float
    categories: tuple[CategoryPeriodResult, ...]
    total_keur: float
