"""DSRF commitment fee engine — Generic MVP product extension.

Computes per-period DSRF commitment fee for the DSRF debt-service reserve mode.

CLASSIFICATION: EXPLICIT_GENERIC_MVP_POLICY_POST_SENIOR_CASH
  Neither authoritative workbook (Generic Solar Reference or Generic Wind Reference) contains an operational DSRF
  engine. This module is a deliberate Generic Finco MVP product extension; it is
  NOT workbook-policy-defined. Do NOT claim otherwise.

Policy: DebtServiceReserveSupportMode.DSRF — the facility is undrawn standby;
NO initial cash Project Use at FC. A commitment fee accrues from COD at:
    fee_keur = dsrf_commitment_keur × dsrf_commitment_fee_rate_pa × period_fraction

The commitment fee is a GENERIC FINANCING CASH COST:
  - not EBITDA / OPEX;
  - no effect on Bank/Base CFADS upstream of Senior debt service;
  - no DSCR-denominator impact;
  - no tax deductibility modelled here;
  - deducted from post-senior cash before the DA roll-forward, so the existing
    CF109 covenant gate may react secondarily (via component C: da_available < 0).

Construction periods: fee = 0 (facility not yet active before COD).
Operating periods: fee > 0 when dsrf_commitment_keur > 0 and rate > 0,
    UNTIL the period containing Senior debt maturity (inclusive), then 0.

Day-count: typed via DsrfDayCountConvention (ACT_365 or ACT_360).
ACT_365 is the Generic MVP default convention — NOT workbook-policy-defined.

DSRF draw engine, reimbursement, and replenishment are out of scope for MVP.
DSRF_AVAILABLE_SUPPORT_ONLY_NO_DRAW_ENGINE: the DSRF provides standby liquidity
support in principle; no draw trigger, utilisation, or reimbursement is modelled.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from finco_core.inputs._models import DsrfDayCountConvention

DSRF_AVAILABLE_SUPPORT_ONLY_NO_DRAW_ENGINE = (
    "DSRF_AVAILABLE_SUPPORT_ONLY_NO_DRAW_ENGINE"
)


@dataclass(frozen=True)
class DsrfFeeSchedule:
    """Per-period DSRF commitment fee schedule."""
    period_indices: tuple[int, ...]
    dsrf_commitment_fee_keur: tuple[float, ...]
    total_dsrf_commitment_fee_keur: float


def _period_fraction(start: date, end: date, convention: DsrfDayCountConvention) -> float:
    days = (end - start).days
    divisor = 360.0 if convention == DsrfDayCountConvention.ACT_360 else 365.0
    return days / divisor


def compute_dsrf_fee_schedule(
    period_indices: list[int],
    period_start_dates: list[date],
    period_end_dates: list[date],
    dsrf_commitment_keur: float,
    dsrf_commitment_fee_rate_pa: float,
    senior_last_period_index: int | None = None,
    day_count_convention: DsrfDayCountConvention = DsrfDayCountConvention.ACT_365,
) -> DsrfFeeSchedule:
    """Compute per-period DSRF commitment fee for operating periods.

    Args:
        period_indices: 1-based period indices (operating periods only).
        period_start_dates: Period start dates corresponding to each index.
        period_end_dates: Period end dates corresponding to each index.
        dsrf_commitment_keur: Undrawn DSRF facility size (kEUR).
        dsrf_commitment_fee_rate_pa: Annual commitment fee rate (e.g. 0.01 = 1% p.a.).
        senior_last_period_index: Period index at which Senior debt matures (inclusive).
            Fee is zero for periods after this index. None means fee runs for all periods.
        day_count_convention: ACT_365 (Generic MVP default) or ACT_360.

    Returns:
        DsrfFeeSchedule with per-period fees in kEUR.
    """
    fees: list[float] = []
    for idx, start, end in zip(period_indices, period_start_dates, period_end_dates):
        if senior_last_period_index is not None and idx > senior_last_period_index:
            fees.append(0.0)
            continue
        pf = _period_fraction(start, end, day_count_convention)
        fee = dsrf_commitment_keur * dsrf_commitment_fee_rate_pa * pf
        fees.append(fee)
    total = sum(fees)
    return DsrfFeeSchedule(
        period_indices=tuple(period_indices),
        dsrf_commitment_fee_keur=tuple(fees),
        total_dsrf_commitment_fee_keur=total,
    )
