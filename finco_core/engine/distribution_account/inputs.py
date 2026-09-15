"""Input dataclasses for canonical DistributionAccount."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class CovenantGatePolicy(str, Enum):
    """Typed policy controlling whether R99/R102 covenant gates apply to a project.

    R99_R102_APPLICABLE: R99/R102 covenant gates are evaluated (Generic Wind Reference-class projects).
    R99_R102_NOT_APPLICABLE: covenant gates are not applicable; gate passes trivially.
        Used for projects where the Generic Wind Reference-specific DA covenant structure does not apply.
    """
    R99_R102_APPLICABLE = "R99_R102_APPLICABLE"
    R99_R102_NOT_APPLICABLE = "R99_R102_NOT_APPLICABLE"


@dataclass(frozen=True)
class R99R102GateInputs:
    """Gate inputs for R99/R102 evaluation."""
    cumulative_fcf_keur: float = 0.0
    senior_debt_outstanding_keur: float = 0.0
    shl_balance_keur: float = 0.0
    current_dscr: float = 0.0
    # future fields can be added here


@dataclass(frozen=True)
class DistributionAccountPeriodInput:
    """Single period input for DistributionAccount engine."""
    period_index: int
    operating_period_index: int
    period_date: date
    opening_distribution_account_balance_keur: float
    post_senior_cash_available_keur: float
    post_shl_cash_available_keur: float
    senior_debt_service_keur: float
    actual_dscr: float
    # All fields below have defaults (must come after non-defaults)
    dsra_top_up_keur: float = 0.0
    target_distribution_dscr: float = 1.0
    r99_gate_inputs: R99R102GateInputs = field(default_factory=R99R102GateInputs)
    r102_gate_inputs: R99R102GateInputs = field(default_factory=R99R102GateInputs)
    project_name: str = ""
    is_reference_wind: bool = False
    is_reference_solar: bool = False
    dsra_required_balance_keur: float = 0.0
    dsra_current_balance_keur: float = 0.0
    jdsra_required_balance_keur: float = 0.0
    jdsra_current_balance_keur: float = 0.0
    enable_r99_r102_runtime: bool = False
    audit_economic_mode: bool = False  # audit-only: bypass R99/R102 governance for economic comparison
    # Phase 9C-fix: distinct from audit_economic_mode — enables gate evaluation for explicit
    # runtime staging (DA wiring via use_distributionaccount_runtime_wiring=True).
    # Still NOT G20 promotion. Still pre-G20 staging. Generic Wind Reference-only. Generic Solar Reference-guarded.
    # dual-run validation uses audit_economic_mode=True (comparison-only, never routed).
    # DA runtime wiring uses runtime_economic_mode=True (staging, explicitly allowed).
    runtime_economic_mode: bool = False
    minimum_cash_reserve_keur: float = 0.0
    senior_tenor_years: int = 0  # explicit lockup policy; 0 = no tenor-based lockup


@dataclass(frozen=True)
class DistributionAccountInputs:
    """Collection of period inputs for DistributionAccount engine."""
    project_name: str
    period_inputs: tuple[DistributionAccountPeriodInput, ...]
    is_reference_wind: bool = False
    is_reference_solar: bool = False
    covenant_gate_policy: CovenantGatePolicy = CovenantGatePolicy.R99_R102_NOT_APPLICABLE
