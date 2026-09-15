"""Immutable input models for the generic hierarchical OPEX engine.

All types are frozen dataclasses.  No project-specific identifiers appear here;
category codes and subitem codes are arbitrary string keys used as references.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ._types import (
    OpexActivationMode,
    OpexAmountBasis,
    OpexCategoryCalculationType,
    OpexEscalationConvention,
)


@dataclass(frozen=True)
class OpexActivationSchedule:
    """Annual flag vector for MANUAL activation, with optional period-half overrides.

    annual_flags:
        Tuple of bool, indexed 0-based (index 0 = operating year 1).
        Length must be >= the model horizon.

    period_overrides:
        Tuple of ((year_1based: int, half_1_or_2: int), active: bool).
        A period override takes precedence over the annual flag for that specific half.
        An annual flag of True covers both H1 and H2 unless a period override supersedes it.
        An annual flag of False covers both H1 and H2 unless a period override supersedes it.

    Example — annual Y5 ON, but H1 of Y5 explicitly OFF:
        annual_flags=(True, ..., True, ...),   # index 4 (Y5) = True
        period_overrides=(((5, 1), False),)    # Y5-H1 overridden to False
        → Y5-H1: False (override), Y5-H2: True (annual flag)
    """

    annual_flags: tuple[bool, ...]
    period_overrides: tuple[tuple[tuple[int, int], bool], ...] = field(
        default_factory=lambda: ()
    )


@dataclass(frozen=True)
class OpexSubitemInput:
    """A single OPEX line item within a category.

    code:                Arbitrary reference key, unique within the parent category.
    name:                Human-readable label.
    base_amount_keur:    Annual budget in kEUR (at the base escalation year).
    amount_basis:        Interpretation of base_amount_keur.
    activation_mode:     How activation is resolved each year / period.
    activation_schedule: Required when activation_mode == MANUAL.
    """

    code: str
    name: str
    base_amount_keur: float
    amount_basis: OpexAmountBasis = OpexAmountBasis.ANNUAL_RUN_RATE
    activation_mode: OpexActivationMode = OpexActivationMode.ALWAYS
    activation_schedule: OpexActivationSchedule | None = None


@dataclass(frozen=True)
class OpexCategoryInput:
    """Configuration for one OPEX category.

    For SUBITEM_SUM categories:
        annual = SUMPRODUCT(active subitems) × escalation_factor(year, inflation, convention)
        subitems must be non-empty; percentage_rate / percentage_base_codes are unused.

    For PERCENTAGE_OF_SELECTED_BASES categories (e.g. contingency):
        annual = percentage_rate × SUM(annual values of each code in percentage_base_codes)
        subitems must be empty.
        Base codes may reference other categories or external annual series in the context.
        No self-reference or circular dependency is allowed.
    """

    code: str
    name: str
    calculation_type: OpexCategoryCalculationType = OpexCategoryCalculationType.SUBITEM_SUM
    inflation_rate: float = 0.0
    escalation_convention: OpexEscalationConvention = OpexEscalationConvention.YEAR_1_AS_BASE
    subitems: tuple[OpexSubitemInput, ...] = field(default_factory=lambda: ())
    percentage_rate: float = 0.0
    percentage_base_codes: tuple[str, ...] = field(default_factory=lambda: ())


@dataclass(frozen=True)
class OpexCalculationContext:
    """Externally resolved parameters that the OPEX engine needs but does not own.

    The engine never accesses project state, scenario names, or debt-solver outputs.
    These are the clean resolved values derived upstream from the selected scenario.

    senior_debt_tenor_years:
        Integer ≥ 1.  Required for any SENIOR_DEBT_TENOR_ACTIVE subitem.
        Semantics: the contractual/scheduled senior debt tenor length in years.
        Active = (operating_year_index <= senior_debt_tenor_years).
        This is NOT 'senior debt outstanding' — it avoids a circular dependency
        (OPEX → CFADS → debt sizing → outstanding → OPEX).

    external_annual_series:
        Supplemental year-by-year value series (kEUR) referenced by
        PERCENTAGE_OF_SELECTED_BASES categories but not themselves OPEX categories
        (e.g. D=Salary, F=Taxes in a contingency base).
        Stored as a tuple of (code, values_y1_to_yn) pairs.
        Values are 0-indexed (index 0 = operating year 1).
    """

    senior_debt_tenor_years: int = 0
    external_annual_series: tuple[tuple[str, tuple[float, ...]], ...] = field(
        default_factory=lambda: ()
    )


@dataclass(frozen=True)
class OpexModelInput:
    """Top-level container for a fully resolved, immutable OPEX input set.

    Represents the output of: Base Project Inputs + one selected Scenario Overlay
    = Resolved Immutable Inputs.  The calculator sees only this object plus context.
    """

    categories: tuple[OpexCategoryInput, ...]
