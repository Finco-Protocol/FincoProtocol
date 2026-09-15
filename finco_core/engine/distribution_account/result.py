"""Result dataclasses for canonical DistributionAccount.

Add these to the existing result.py which already has R99InputResult.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


BLOCKED_REASONS = {
    "R99_BLOCKED": "R99 gate not promoted to runtime — audit-only",
    "R102_BLOCKED": "R102 gate not promoted to runtime — audit-only",
    "DSCR_GATE_FAILED": "DSCR below target_distribution_dscr threshold",
    "REFERENCE_SCOPE_NOT_SUPPORTED": "Generic Solar Reference project — Generic Wind Reference-specific gates blocked",
    "NEGATIVE_CASH": "Insufficient cash for distribution",
    "DISTRIBUTION_ACCOUNT_NOT_PROMOTED": "DistributionAccount not in runtime — audit-only mode",
    "LOCKUP": "Period locked — DSRA/JDSRA below target or construction period",
    "SENIOR_TENOR": "Within senior debt tenor — distributions blocked",
    "COVENANT_GATE_NOT_APPLICABLE": "R99/R102 covenant gates not applicable to this project",
}


@dataclass(frozen=True)
class DistributionGateResult:
    """Result of a single gate evaluation."""
    gate_name: str
    passed: bool
    blocked_reason: str = ""
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class DistributionAccountPeriodResult:
    """Single period result from DistributionAccount engine."""
    period_index: int
    opening_distribution_account_balance_keur: float
    closing_distribution_account_balance_keur: float
    cash_available_for_distribution_keur: float
    equity_distribution_candidate_keur: float
    equity_distribution_paid_keur: float = 0.0
    cash_swept_to_shl_keur: float = 0.0
    cash_retained_keur: float = 0.0
    dsra_top_up_keur: float = 0.0
    r99_gate_result: DistributionGateResult = field(default=None)  # type: ignore[assignment]
    r102_gate_result: DistributionGateResult = field(default=None)  # type: ignore[assignment]
    dscr_gate_result: DistributionGateResult = field(default=None)  # type: ignore[assignment]
    lockup_gate_result: DistributionGateResult = field(default=None)  # type: ignore[assignment]
    generic_solar_reference_gate_result: DistributionGateResult = field(default=None)  # type: ignore[assignment]
    covenant_gate_result: DistributionGateResult = field(default=None)  # type: ignore[assignment]
    blocked_reason: str = ""
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class DistributionAccountResult:
    """Full result from DistributionAccount engine across all periods."""
    project_name: str
    period_results: tuple[DistributionAccountPeriodResult, ...]
    total_equity_distribution_candidate_keur: float
    total_equity_distribution_paid_keur: float
    total_cash_swept_to_shl_keur: float
    total_cash_retained_keur: float
    final_closing_balance_keur: float
    is_reference_wind: bool
    is_reference_solar: bool


@dataclass(frozen=True)
class R99InputResult:
    """Audit result for one Generic Wind Reference R99/R102 input-engine period."""

    r69_fcf_banks_keur: float
    r84_fcf_junior_keur: float
    r98_distribution_account_keur: float
    r99_fcf_for_distribution_keur: float
    r100_carryforward_keur: float
    r102_fcf_for_shl_keur: float
    fcf_for_shl_keur: float
    locked: bool
    lockup_reasons: tuple[str, ...] = ()
