"""financial_engine.shl.schedule — Multi-period SHL schedule runner (C3B3D1).

Converts a sequence of ShlPeriodInput records + a ShlSchedulePolicy into a
full ShlScheduleResult by calling compute_shl_period for each period.

Supported repayment modes:
  BULLET            — full principal at maturity_period_index
  EXPLICIT_SCHEDULE — per-period scheduled_principal_keur from ShlPeriodInput

Unsupported (fail-closed, later SHL/waterfall scope):
  FCF_WATERFALL / CASH_SWEEP / PIK-then-cash mixed mode — require cash-waterfall
  integration (later SHL/waterfall scope, not C3B3D2 immediate).
"""
from __future__ import annotations

import math
from typing import Sequence

from financial_engine.shl.contracts import (
    ShlPeriodInput,
    ShlPeriodResult,
    ShlRepaymentMode,
    ShlSchedulePolicy,
    ShlScheduleResult,
)
from financial_engine.shl.engine import compute_shl_period


def run_shl_schedule(
    opening_balance_keur: float,
    period_inputs: Sequence[ShlPeriodInput],
    policy: ShlSchedulePolicy,
    maturity_period_index: int | None = None,
) -> ShlScheduleResult:
    """Run the canonical SHL schedule across multiple periods.

    Parameters
    ----------
    opening_balance_keur : float
        SHL balance at model start (before any period-1 drawdown). Must be >= 0.
    period_inputs : Sequence[ShlPeriodInput]
        One ShlPeriodInput per model period, in order.
    policy : ShlSchedulePolicy
        Interest and repayment policy.
    maturity_period_index : int | None
        Required when repayment_mode == BULLET. The 0-based period index at
        which the full outstanding balance is repaid. Must be within the range
        of period_inputs. Ignored for other repayment modes.

    Returns
    -------
    ShlScheduleResult
        Tuple of ShlPeriodResult, one per period.

    Raises
    ------
    NotImplementedError
        When repayment_mode is not BULLET or EXPLICIT_SCHEDULE (C3B3D1 scope).
    TypeError
        When opening_balance_keur is bool, or maturity_period_index is not int.
    ValueError
        When opening_balance_keur is not finite or is negative.
        When BULLET mode is used without maturity_period_index, or
        maturity_period_index is out of range or negative.
    """
    # ── opening balance validation ───────────────────────────────────────────
    if isinstance(opening_balance_keur, bool):
        raise TypeError(
            f"opening_balance_keur must be a float, not bool: {opening_balance_keur!r}"
        )
    if not isinstance(opening_balance_keur, (int, float)):
        raise TypeError(
            f"opening_balance_keur must be numeric, got {type(opening_balance_keur).__name__}"
        )
    if not math.isfinite(opening_balance_keur):
        raise ValueError(
            f"opening_balance_keur must be finite, got {opening_balance_keur!r}"
        )
    if opening_balance_keur < 0:
        raise ValueError(
            f"opening_balance_keur must be >= 0, got {opening_balance_keur!r}"
        )

    if policy.repayment_mode not in (
        ShlRepaymentMode.BULLET,
        ShlRepaymentMode.EXPLICIT_SCHEDULE,
    ):
        raise NotImplementedError(
            f"C3B3D1_DEFERRED: FCF-waterfall repayment requires cash-waterfall "
            f"integration (later SHL/waterfall scope). "
            f"repayment_mode={policy.repayment_mode!r} is not supported in C3B3D1. "
            "Use ShlRepaymentMode.BULLET or ShlRepaymentMode.EXPLICIT_SCHEDULE."
        )

    if policy.repayment_mode == ShlRepaymentMode.BULLET:
        if maturity_period_index is None:
            raise ValueError(
                "maturity_period_index is required when repayment_mode == BULLET"
            )
        # Reject bool before numeric range check (False==0, True==1 in Python)
        if isinstance(maturity_period_index, bool):
            raise TypeError(
                f"maturity_period_index must be int, not bool: {maturity_period_index!r}"
            )
        if not isinstance(maturity_period_index, int):
            raise TypeError(
                f"maturity_period_index must be int, got "
                f"{type(maturity_period_index).__name__!r}: {maturity_period_index!r}"
            )
        if maturity_period_index < 0:
            raise ValueError(
                f"maturity_period_index must be >= 0, got {maturity_period_index!r}"
            )
        n = len(period_inputs)
        if maturity_period_index >= n:
            raise ValueError(
                f"maturity_period_index={maturity_period_index} is out of range "
                f"for {n} period_inputs (valid: 0 to {n - 1})"
            )

    # ── period-index contiguity validation ─────────────────────────────────
    for idx, p_input in enumerate(period_inputs):
        pi = p_input.period_index
        if isinstance(pi, bool) or not isinstance(pi, int):
            raise TypeError(
                f"period_index must be int (not bool, not float): "
                f"got {type(pi).__name__!r} at position {idx}"
            )
        if pi < 0:
            raise ValueError(
                f"period_index must be >= 0: got {pi!r} at position {idx}"
            )
        if pi != idx:
            raise ValueError(
                f"period_inputs must be contiguous starting at 0: "
                f"expected period_index={idx} at position {idx}, "
                f"got period_index={pi}"
            )

    results: list[ShlPeriodResult] = []
    balance = opening_balance_keur

    for idx, p_input in enumerate(period_inputs):
        # Determine scheduled principal for this period
        if policy.repayment_mode == ShlRepaymentMode.BULLET:
            if p_input.period_index == maturity_period_index:
                # Full outstanding balance repaid at maturity.
                # We compute balance_for_interest first to know the PIK addition,
                # then set scheduled_principal to the full pre-principal balance.
                balance_for_interest = balance + p_input.drawdown_keur
                from financial_engine.shl.contracts import ShlInterestPaymentMode
                if policy.payment_mode == ShlInterestPaymentMode.PIK:
                    gross = balance_for_interest * policy.annual_rate * p_input.day_count_fraction
                    pre_principal = balance_for_interest + gross
                else:
                    pre_principal = balance_for_interest
                scheduled_principal = pre_principal
            else:
                scheduled_principal = 0.0
        else:
            # EXPLICIT_SCHEDULE
            scheduled_principal = p_input.scheduled_principal_keur

        result = compute_shl_period(
            opening_balance_keur=balance,
            drawdown_keur=p_input.drawdown_keur,
            day_count_fraction=p_input.day_count_fraction,
            annual_rate=policy.annual_rate,
            payment_mode=policy.payment_mode,
            scheduled_principal_keur=scheduled_principal,
            period_index=p_input.period_index,
        )
        results.append(result)
        balance = result.closing_balance_keur

    return tuple(results)
