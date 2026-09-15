"""Offline interest limitation / fiscal reintegration mechanics.

This module reproduces the Excel R57/R58/R59/R54/R34 audit chain without
changing runtime tax calculations. It is intentionally input-driven: callers
must provide gross SHL interest, EBITDA, and the thin-cap gate per period.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence


class InterestLimitationSignConvention(Enum):
    """How the Excel R54 helper amount affects taxable income."""

    ADD_BACK = "add_back"
    SUBTRACT_FROM_TI = "subtract_from_ti"


@dataclass(frozen=True)
class InterestLimitationConfig:
    """Configuration for the offline interest limitation calculation."""

    enabled: bool = True
    absolute_cap_keur: float = 3000.0
    ebitda_pct_cap: float = 0.30
    ratio_4to1_enabled: bool = False
    ratio_4to1_denom: float = 1.0
    thin_cap_gate_mode: str = "explicit_period_flags"
    sign_convention: InterestLimitationSignConvention = (
        InterestLimitationSignConvention.ADD_BACK
    )
    carryforward_enabled: bool = False
    jurisdiction: str = "XA"
    notes: str = ""

    def __post_init__(self) -> None:
        if self.absolute_cap_keur < 0:
            raise ValueError("absolute_cap_keur must be non-negative")
        if self.ebitda_pct_cap < 0:
            raise ValueError("ebitda_pct_cap must be non-negative")
        if self.ratio_4to1_denom < 0:
            raise ValueError("ratio_4to1_denom must be non-negative")
        if self.carryforward_enabled:
            raise ValueError("interest limitation carryforward is not implemented")


@dataclass(frozen=True)
class InterestLimitationPeriodInput:
    """Single-period inputs for reproducing reference fiscal-reintegration mechanics."""

    period_index: int
    gross_shl_interest_keur: float
    ebitda_keur: float
    thin_cap_active: bool
    ratio_adjustment_keur: float | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.gross_shl_interest_keur < 0:
            raise ValueError("gross_shl_interest_keur must be non-negative")


@dataclass(frozen=True)
class InterestLimitationPeriodResult:
    """Audit output matching the Excel fiscal reintegration helper rows."""

    period_index: int
    gross_shl_interest_keur: float
    ebitda_keur: float
    thin_cap_active: bool
    excess_absolute_cap_keur: float
    excess_ebitda_cap_keur: float
    ratio_adjustment_keur: float
    combined_non_deductible_keur: float
    fiscal_reintegration_keur: float
    taxable_income_adjustment_keur: float


@dataclass(frozen=True)
class InterestLimitationResult:
    """Full schedule result for offline R34/R54 parity tests."""

    periods: tuple[InterestLimitationPeriodResult, ...]
    config: InterestLimitationConfig

    @property
    def total_gross_shl_interest_keur(self) -> float:
        return sum(period.gross_shl_interest_keur for period in self.periods)

    @property
    def total_combined_non_deductible_keur(self) -> float:
        return sum(period.combined_non_deductible_keur for period in self.periods)

    @property
    def total_fiscal_reintegration_keur(self) -> float:
        return sum(period.fiscal_reintegration_keur for period in self.periods)

    @property
    def total_taxable_income_adjustment_keur(self) -> float:
        return sum(period.taxable_income_adjustment_keur for period in self.periods)


def compute_interest_limitation_period(
    period_input: InterestLimitationPeriodInput,
    config: InterestLimitationConfig,
) -> InterestLimitationPeriodResult:
    """Compute one spreadsheet-style R34/R54 fiscal reintegration period."""

    gross_interest = period_input.gross_shl_interest_keur

    if not config.enabled:
        return InterestLimitationPeriodResult(
            period_index=period_input.period_index,
            gross_shl_interest_keur=gross_interest,
            ebitda_keur=period_input.ebitda_keur,
            thin_cap_active=period_input.thin_cap_active,
            excess_absolute_cap_keur=0.0,
            excess_ebitda_cap_keur=0.0,
            ratio_adjustment_keur=0.0,
            combined_non_deductible_keur=0.0,
            fiscal_reintegration_keur=0.0,
            taxable_income_adjustment_keur=0.0,
        )

    if period_input.thin_cap_active:
        excess_absolute = max(gross_interest - config.absolute_cap_keur, 0.0)
        excess_ebitda = max(
            gross_interest - config.ebitda_pct_cap * period_input.ebitda_keur,
            0.0,
        )
    else:
        excess_absolute = 0.0
        excess_ebitda = 0.0

    ratio_adjustment = _ratio_adjustment(period_input, config)
    combined = min(max(excess_absolute, excess_ebitda) + ratio_adjustment, gross_interest)
    fiscal_reintegration = _apply_sign_convention(combined, config.sign_convention)

    return InterestLimitationPeriodResult(
        period_index=period_input.period_index,
        gross_shl_interest_keur=gross_interest,
        ebitda_keur=period_input.ebitda_keur,
        thin_cap_active=period_input.thin_cap_active,
        excess_absolute_cap_keur=excess_absolute,
        excess_ebitda_cap_keur=excess_ebitda,
        ratio_adjustment_keur=ratio_adjustment,
        combined_non_deductible_keur=combined,
        fiscal_reintegration_keur=fiscal_reintegration,
        taxable_income_adjustment_keur=fiscal_reintegration,
    )


def compute_interest_limitation_schedule(
    period_inputs: Sequence[InterestLimitationPeriodInput],
    config: InterestLimitationConfig,
) -> InterestLimitationResult:
    """Compute an offline interest limitation schedule."""

    return InterestLimitationResult(
        periods=tuple(
            compute_interest_limitation_period(period_input, config)
            for period_input in period_inputs
        ),
        config=config,
    )


def _ratio_adjustment(
    period_input: InterestLimitationPeriodInput,
    config: InterestLimitationConfig,
) -> float:
    if period_input.ratio_adjustment_keur is not None:
        return period_input.ratio_adjustment_keur
    if not config.ratio_4to1_enabled:
        return 0.0
    return -period_input.gross_shl_interest_keur * config.ratio_4to1_denom


def _apply_sign_convention(
    combined_amount_keur: float,
    sign_convention: InterestLimitationSignConvention,
) -> float:
    if sign_convention is InterestLimitationSignConvention.ADD_BACK:
        return abs(combined_amount_keur)
    if sign_convention is InterestLimitationSignConvention.SUBTRACT_FROM_TI:
        return -abs(combined_amount_keur)
    raise ValueError(f"Unsupported sign convention: {sign_convention}")


__all__ = [
    "InterestLimitationSignConvention",
    "InterestLimitationConfig",
    "InterestLimitationPeriodInput",
    "InterestLimitationPeriodResult",
    "InterestLimitationResult",
    "compute_interest_limitation_period",
    "compute_interest_limitation_schedule",
]
