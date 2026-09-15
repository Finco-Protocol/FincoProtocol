"""financial_engine.senior_debt.sculpting — DSCR sculpting and schedule construction.

Sculpting formula per repayment period t:

    maximum_debt_service_t = max(0, canonical_cfads_t / target_dscr)
    principal_t            = max(0, maximum_debt_service_t - interest_t)
    principal_t            = min(principal_t, opening_balance_t)   # cap at balance
    closing_balance_t      = opening_balance_t - principal_t

Periods before repayment_start or after maturity: principal = 0.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class PeriodDebtRow:
    period_index: int
    opening_keur: float
    interest_keur: float
    principal_keur: float
    debt_service_keur: float
    closing_keur: float
    dscr: float | None  # None when debt_service = 0


def build_schedule(
    *,
    opening_debt_keur: float,
    period_indices: tuple[int, ...],
    interest_by_period: dict[int, float],
    cfads_by_period: dict[int, float],
    target_dscr: float,
    repayment_start_index: int,
    maturity_index: int,
) -> tuple[PeriodDebtRow, ...]:
    """Build DSCR-sculpted debt schedule from a given opening balance.

    Returns one PeriodDebtRow per period in period_indices order.
    Principal is only repaid in [repayment_start_index, maturity_index].
    """
    rows: list[PeriodDebtRow] = []
    balance = opening_debt_keur

    for idx in period_indices:
        interest = interest_by_period.get(idx, 0.0)
        cfads = cfads_by_period.get(idx, 0.0)

        in_repayment = repayment_start_index <= idx <= maturity_index

        if in_repayment and balance > 0.0:
            max_ds = max(0.0, cfads / target_dscr) if target_dscr > 0.0 else 0.0
            principal = max(0.0, max_ds - interest)
            principal = min(principal, balance)
        else:
            principal = 0.0

        debt_service = interest + principal
        closing = balance - principal

        if debt_service > 0.0:
            dscr: float | None = cfads / debt_service if math.isfinite(cfads) else None
        else:
            dscr = None

        rows.append(PeriodDebtRow(
            period_index=idx,
            opening_keur=balance,
            interest_keur=interest,
            principal_keur=principal,
            debt_service_keur=debt_service,
            closing_keur=closing,
            dscr=dscr,
        ))
        balance = closing

    return tuple(rows)


def build_level_principal_schedule(
    *,
    opening_debt_keur: float,
    period_indices: tuple[int, ...],
    interest_by_period: dict[int, float],
    cfads_by_period: dict[int, float],
    repayment_start_index: int,
    maturity_index: int,
) -> tuple[PeriodDebtRow, ...]:
    """Build level-principal (straight-line) repayment schedule for GEARING_CAP.

    Equal principal in each repayment period; no CFADS sculpting.
    """
    repayment_periods = [
        idx for idx in period_indices
        if repayment_start_index <= idx <= maturity_index
    ]
    n = len(repayment_periods)
    level_principal = (opening_debt_keur / n) if n > 0 else 0.0

    rows: list[PeriodDebtRow] = []
    balance = opening_debt_keur
    repayment_set = set(repayment_periods)

    for idx in period_indices:
        interest = interest_by_period.get(idx, 0.0)
        cfads = cfads_by_period.get(idx, 0.0)

        if idx in repayment_set and balance > 0.0:
            principal = min(level_principal, balance)
        else:
            principal = 0.0

        debt_service = interest + principal
        closing = balance - principal

        if debt_service > 0.0:
            dscr: float | None = cfads / debt_service if math.isfinite(cfads) else None
        else:
            dscr = None

        rows.append(PeriodDebtRow(
            period_index=idx,
            opening_keur=balance,
            interest_keur=interest,
            principal_keur=principal,
            debt_service_keur=debt_service,
            closing_keur=closing,
            dscr=dscr,
        ))
        balance = closing

    return tuple(rows)


def build_explicit_schedule(
    *,
    opening_debt_keur: float,
    period_indices: tuple[int, ...],
    interest_by_period: dict[int, float],
    cfads_by_period: dict[int, float],
    explicit_principal_by_period: dict[int, float],
) -> tuple[PeriodDebtRow, ...]:
    """Build schedule from an explicit principal map. No resizing."""
    rows: list[PeriodDebtRow] = []
    balance = opening_debt_keur

    for idx in period_indices:
        interest = interest_by_period.get(idx, 0.0)
        cfads = cfads_by_period.get(idx, 0.0)
        principal = min(explicit_principal_by_period.get(idx, 0.0), balance)
        principal = max(0.0, principal)

        debt_service = interest + principal
        closing = balance - principal

        if debt_service > 0.0:
            dscr: float | None = cfads / debt_service if math.isfinite(cfads) else None
        else:
            dscr = None

        rows.append(PeriodDebtRow(
            period_index=idx,
            opening_keur=balance,
            interest_keur=interest,
            principal_keur=principal,
            debt_service_keur=debt_service,
            closing_keur=closing,
            dscr=dscr,
        ))
        balance = closing

    return tuple(rows)
