"""Senior debt sculpting configuration.

Authoritative location: finco_core.inputs.senior_sculpting (V2-2).
Legacy location finco_core.inputs.senior_sculpting re-exports from here.

This module defines a default-off configuration surface for future senior debt
sculpting alignment. The first runtime-supported mode is intentionally narrow:
an explicit debt-service schedule that reuses existing interest calculation and
opening balance policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SeniorSculptingMode(Enum):
    """Supported senior sculpting basis modes."""

    LEGACY = "legacy"
    EXPLICIT_DEBT_SERVICE_SCHEDULE = "explicit_debt_service_schedule"
    EXPLICIT_PRINCIPAL_SCHEDULE = "explicit_principal_schedule"
    EXCEL_AVAILABLE_CFADS = "excel_available_cfads"


class SeniorFinalRepaymentPolicy(Enum):
    """How the final senior period should be handled."""

    LEGACY_RESIDUAL = "legacy_residual"
    CAP_AT_EXPLICIT_SCHEDULE = "cap_at_explicit_schedule"
    FULL_BALANCE_AT_MATURITY = "full_balance_at_maturity"


class SeniorPrincipalCapPolicy(Enum):
    """Principal repayment cap policy."""

    CAP_AT_OPENING_BALANCE = "cap_at_opening_balance"
    CAP_AT_EXPLICIT_AVAILABLE_CASH = "cap_at_explicit_available_cash"


class SeniorReserveTreatment(Enum):
    """Reserve treatment for senior sculpting basis calculations."""

    LEGACY = "legacy"
    INCLUDE_DSRA_MOVEMENTS = "include_dsra_movements"
    EXCLUDE_RESERVE_MOVEMENTS = "exclude_reserve_movements"


@dataclass(frozen=True)
class SeniorSculptingConfig:
    """Opt-in senior debt sculpting basis configuration."""

    enabled: bool = False
    mode: SeniorSculptingMode = SeniorSculptingMode.LEGACY
    explicit_debt_service_schedule: tuple[float, ...] = ()
    explicit_principal_schedule: tuple[float, ...] = ()
    target_dscr_schedule: tuple[float, ...] = ()
    available_senior_cfads_schedule: tuple[float, ...] = ()
    debt_service_availability_schedule: tuple[float, ...] = ()
    final_repayment_policy: SeniorFinalRepaymentPolicy = SeniorFinalRepaymentPolicy.LEGACY_RESIDUAL
    principal_cap_policy: SeniorPrincipalCapPolicy = SeniorPrincipalCapPolicy.CAP_AT_OPENING_BALANCE
    reserve_treatment: SeniorReserveTreatment = SeniorReserveTreatment.LEGACY


def validate_explicit_debt_service_schedule(
    config: SeniorSculptingConfig,
    tenor_periods: int,
) -> tuple[float, ...]:
    """Validate and return the explicit senior debt-service schedule."""
    if len(config.explicit_debt_service_schedule) < tenor_periods:
        raise ValueError("explicit_debt_service_schedule must cover tenor_periods")
    schedule = config.explicit_debt_service_schedule[:tenor_periods]
    if any(value < 0 for value in schedule):
        raise ValueError("explicit_debt_service_schedule values must be non-negative")
    return schedule
