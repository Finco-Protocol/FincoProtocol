"""Audit row dataclass for DistributionAccount CSV export.

Follows the same pattern as domain/shl/audit.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class DistributionAuditRow:
    """Single-period audit row for DistributionAccount.

    Suitable for CSV export.
    """
    period_index: int
    project_name: str
    operating_period_index: int
    period_date: date

    # Balance
    opening_balance_keur: float
    closing_balance_keur: float

    # Cash flows
    cash_available_for_distribution_keur: float
    equity_distribution_candidate_keur: float
    equity_distribution_paid_keur: float
    cash_swept_to_shl_keur: float
    cash_retained_keur: float
    dsra_top_up_keur: float

    # Gate results
    r99_gate_passed: bool
    r102_gate_passed: bool
    dscr_gate_passed: bool
    lockup_gate_passed: bool
    reference_scope_guard_passed: bool

    # Status
    blocked_reason: str
    is_reference_wind: bool
    is_reference_solar: bool

    def to_csv_row(self) -> dict:
        return {
            "period_index": self.period_index,
            "project_name": self.project_name,
            "operating_period_index": self.operating_period_index,
            "period_date": str(self.period_date),
            "opening_balance_keur": f"{self.opening_balance_keur:.2f}",
            "closing_balance_keur": f"{self.closing_balance_keur:.2f}",
            "cash_available_for_distribution_keur": f"{self.cash_available_for_distribution_keur:.2f}",
            "equity_distribution_candidate_keur": f"{self.equity_distribution_candidate_keur:.2f}",
            "equity_distribution_paid_keur": f"{self.equity_distribution_paid_keur:.2f}",
            "cash_swept_to_shl_keur": f"{self.cash_swept_to_shl_keur:.2f}",
            "cash_retained_keur": f"{self.cash_retained_keur:.2f}",
            "dsra_top_up_keur": f"{self.dsra_top_up_keur:.2f}",
            "r99_gate_passed": self.r99_gate_passed,
            "r102_gate_passed": self.r102_gate_passed,
            "dscr_gate_passed": self.dscr_gate_passed,
            "lockup_gate_passed": self.lockup_gate_passed,
            "reference_scope_guard_passed": self.reference_scope_guard_passed,
            "blocked_reason": self.blocked_reason,
            "is_reference_wind": self.is_reference_wind,
            "is_reference_solar": self.is_reference_solar,
        }


def from_period_result(
    period_result,
    project_name: str,
    operating_period_index: int,
    period_date,
    is_reference_wind: bool,
    is_reference_solar: bool,
) -> DistributionAuditRow:
    """Convert a DistributionAccountPeriodResult into a DistributionAuditRow."""
    return DistributionAuditRow(
        period_index=period_result.period_index,
        project_name=project_name,
        operating_period_index=operating_period_index,
        period_date=period_date,
        opening_balance_keur=period_result.opening_distribution_account_balance_keur,
        closing_balance_keur=period_result.closing_distribution_account_balance_keur,
        cash_available_for_distribution_keur=period_result.cash_available_for_distribution_keur,
        equity_distribution_candidate_keur=period_result.equity_distribution_candidate_keur,
        equity_distribution_paid_keur=period_result.equity_distribution_paid_keur,
        cash_swept_to_shl_keur=period_result.cash_swept_to_shl_keur,
        cash_retained_keur=period_result.cash_retained_keur,
        dsra_top_up_keur=period_result.dsra_top_up_keur,
        r99_gate_passed=period_result.r99_gate_result.passed,
        r102_gate_passed=period_result.r102_gate_result.passed,
        dscr_gate_passed=period_result.dscr_gate_result.passed,
        lockup_gate_passed=period_result.lockup_gate_result.passed,
        reference_scope_guard_passed=period_result.generic_solar_reference_gate_result.passed,
        blocked_reason=period_result.blocked_reason,
        is_reference_wind=is_reference_wind,
        is_reference_solar=is_reference_solar,
    )


def to_audit_rows(
    result,
    period_dates: dict[int, any],
) -> list[DistributionAuditRow]:
    """Convert DistributionAccountResult into a list of DistributionAuditRow.

    Args:
        result: DistributionAccountResult from DistributionAccountEngine.compute()
        period_dates: dict mapping period_index -> date for each period.
                     Only periods in result.period_results are included.
    """
    rows = []
    for period_result in result.period_results:
        period_date = period_dates.get(period_result.period_index, None)
        audit_row = from_period_result(
            period_result=period_result,
            project_name=result.project_name,
            operating_period_index=period_result.period_index,  # proxy
            period_date=period_date,
            is_reference_wind=result.is_reference_wind,
            is_reference_solar=result.is_reference_solar,
        )
        rows.append(audit_row)
    return rows


def to_csv(result, path: Path | str, period_dates: dict[int, any] = None) -> None:
    """Write DistributionAccountResult audit rows to a CSV file.

    Args:
        result: DistributionAccountResult
        path: output CSV path
        period_dates: optional dict mapping period_index -> date. If None, date is omitted.
    """
    import csv

    rows = to_audit_rows(result, period_dates or {})
    fieldnames = [
        "period_index", "project_name", "operating_period_index", "period_date",
        "opening_balance_keur", "closing_balance_keur",
        "cash_available_for_distribution_keur",
        "equity_distribution_candidate_keur", "equity_distribution_paid_keur",
        "cash_swept_to_shl_keur", "cash_retained_keur", "dsra_top_up_keur",
        "r99_gate_passed", "r102_gate_passed", "dscr_gate_passed",
        "lockup_gate_passed", "reference_scope_guard_passed",
        "blocked_reason", "is_reference_wind", "is_reference_solar",
    ]

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_csv_row())


def to_model_summary(result) -> str:
    """Return human-readable summary of DistributionAccountResult."""
    return (
        f"DistributionAccount Result ({result.project_name}):\n"
        f"  Periods: {len(result.period_results)}\n"
        f"  Generic Wind Reference: {result.is_reference_wind} | Generic Solar Reference: {result.is_reference_solar}\n"
        f"  Total equity distribution candidate: {result.total_equity_distribution_candidate_keur:,.1f} kEUR\n"
        f"  Total equity distribution paid:       {result.total_equity_distribution_paid_keur:,.1f} kEUR\n"
        f"  Total cash swept to SHL:              {result.total_cash_swept_to_shl_keur:,.1f} kEUR\n"
        f"  Total cash retained:                  {result.total_cash_retained_keur:,.1f} kEUR\n"
        f"  Final closing balance:                {result.final_closing_balance_keur:,.1f} kEUR"
    )