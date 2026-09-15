"""financial_engine.shl.engine — Pure canonical SHL period engine (C3B3D1).

Period-start draw convention: the drawdown is included in the interest basis
for the period in which it is drawn.

Balance roll-forward identity:
    balance_for_interest  = opening_balance + drawdown
    gross_interest        = balance_for_interest × annual_rate × day_count_fraction
    cash_interest         = gross_interest   if CASH_PAID  else 0
    pik_interest          = gross_interest   if PIK        else 0
    closing_balance       = opening_balance + drawdown + pik_interest - scheduled_principal

No project-name or project-code dispatch. No imports from app, finco_core
waterfall, or any production runtime.
"""
from __future__ import annotations

import math

from financial_engine.shl.contracts import (
    ShlInterestPaymentMode,
    ShlPeriodResult,
)


def compute_shl_period(
    opening_balance_keur: float,
    drawdown_keur: float,
    day_count_fraction: float,
    annual_rate: float,
    payment_mode: ShlInterestPaymentMode,
    scheduled_principal_keur: float,
    period_index: int,
) -> ShlPeriodResult:
    """Compute one period of the canonical SHL schedule.

    Parameters
    ----------
    opening_balance_keur : float
        SHL balance at period start, before any drawdown. Must be >= 0.
    drawdown_keur : float
        New SHL drawn at period start. Must be >= 0.
    day_count_fraction : float
        Day-count fraction for this period. Must be > 0.
    annual_rate : float
        Annual simple interest rate. Must be >= 0 and finite.
    payment_mode : ShlInterestPaymentMode
        CASH_PAID or PIK.
    scheduled_principal_keur : float
        Principal repaid this period. Must be >= 0. Must not exceed the
        period-end balance (opening + drawdown + pik_interest). Validated
        before returning.
    period_index : int
        0-based period index (for output labelling only).

    Returns
    -------
    ShlPeriodResult

    Raises
    ------
    ValueError
        - opening_balance_keur < 0
        - drawdown_keur < 0
        - annual_rate < 0 or not finite
        - day_count_fraction < 0 or not finite
        - any input is NaN or Inf (checked individually)
        - scheduled_principal_keur > balance (closing would go negative)
    """
    # ── input validation ────────────────────────────────────────────────────
    _validate_finite("opening_balance_keur", opening_balance_keur)
    _validate_finite("drawdown_keur", drawdown_keur)
    _validate_finite("day_count_fraction", day_count_fraction)
    _validate_finite("annual_rate", annual_rate)
    _validate_finite("scheduled_principal_keur", scheduled_principal_keur)

    if opening_balance_keur < 0:
        raise ValueError(
            f"opening_balance_keur must be >= 0, got {opening_balance_keur!r} "
            f"(period_index={period_index})"
        )
    if drawdown_keur < 0:
        raise ValueError(
            f"drawdown_keur must be >= 0, got {drawdown_keur!r} "
            f"(period_index={period_index})"
        )
    if annual_rate < 0:
        raise ValueError(
            f"annual_rate must be >= 0, got {annual_rate!r} "
            f"(period_index={period_index})"
        )
    if day_count_fraction < 0:
        raise ValueError(
            f"day_count_fraction must be >= 0, got {day_count_fraction!r} "
            f"(period_index={period_index})"
        )

    # ── period-start draw convention ────────────────────────────────────────
    balance_for_interest = opening_balance_keur + drawdown_keur
    gross_accrued_interest = balance_for_interest * annual_rate * day_count_fraction

    # ── interest settlement ─────────────────────────────────────────────────
    if payment_mode == ShlInterestPaymentMode.CASH_PAID:
        cash_interest = gross_accrued_interest
        pik_interest = 0.0
    elif payment_mode == ShlInterestPaymentMode.PIK:
        cash_interest = 0.0
        pik_interest = gross_accrued_interest
    else:
        raise NotImplementedError(
            f"Unsupported payment_mode: {payment_mode!r}. "
            "Only CASH_PAID and PIK are supported in C3B3D1."
        )

    # ── balance after PIK before principal ─────────────────────────────────
    pre_principal_balance = balance_for_interest + pik_interest

    # ── principal validation ────────────────────────────────────────────────
    if scheduled_principal_keur < 0:
        raise ValueError(
            f"scheduled_principal_keur must be >= 0, got {scheduled_principal_keur!r} "
            f"(period_index={period_index})"
        )
    if scheduled_principal_keur > pre_principal_balance + 1e-9:
        raise ValueError(
            f"scheduled_principal_keur ({scheduled_principal_keur!r}) exceeds "
            f"outstanding balance ({pre_principal_balance!r}) at period_index={period_index}. "
            "Principal cannot exceed outstanding balance."
        )
    # Clamp to zero to absorb floating-point dust
    actual_principal = min(scheduled_principal_keur, pre_principal_balance)
    actual_principal = max(actual_principal, 0.0)

    # ── closing balance ─────────────────────────────────────────────────────
    closing_balance = pre_principal_balance - actual_principal
    closing_balance = max(closing_balance, 0.0)  # absorb floating-point dust

    return ShlPeriodResult(
        period_index=period_index,
        opening_balance_keur=opening_balance_keur,
        gross_accrued_interest_keur=gross_accrued_interest,
        cash_interest_keur=cash_interest,
        pik_interest_keur=pik_interest,
        scheduled_principal_keur=actual_principal,
        closing_balance_keur=closing_balance,
    )


def _validate_finite(name: str, value: float) -> None:
    """Raise ValueError if value is NaN or Inf."""
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a float, not bool: {value!r}")
    if not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric, got {type(value).__name__}")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
