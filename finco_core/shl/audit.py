"""domain/shl/audit — SHL Engine audit export utilities."""
from pathlib import Path
from typing import Iterable

from finco_core.shl.result import ShlEngineResult, ShlAuditRow


def to_audit_dataframe(result: ShlEngineResult) -> "pd.DataFrame":
    """Convert ShlEngineResult audit_table to a pandas DataFrame."""
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas is required for to_audit_dataframe")

    rows = []
    for row in result.audit_table:
        rows.append(
            {
                "period_index": row.period_index,
                "excel_col": row.excel_col,
                "operating_period_index": row.operating_period_index,
                "shl_opening_keur": row.shl_opening_keur,
                "drawdown_keur": row.drawdown_keur,
                "shl_closing_keur": row.shl_closing_keur,
                "gross_accrued_keur": row.gross_accrued_keur,
                "cash_int_paid_keur": row.cash_int_paid_keur,
                "pik_capitalized_keur": row.pik_capitalized_keur,
                "post_senior_cash_keur": row.post_senior_cash_keur,
                "cash_consumed_keur": row.cash_consumed_keur,
                "cash_after_shl_keur": row.cash_after_shl_keur,
                "cash_for_distribution_keur": row.cash_for_distribution_keur,
                "pik_triggered": row.pik_triggered,
                "cash_sweep_100_pct": row.cash_sweep_100_pct,
                "reserve_applied": row.reserve_applied,
                "classification": row.classification,
                "warnings": "; ".join(row.warnings) if row.warnings else "",
            }
        )
    return pd.DataFrame(rows)


def to_csv(result: ShlEngineResult, path: Path | str) -> None:
    """Write ShlEngineResult audit table to a CSV file."""
    import csv

    fieldnames = [
        "period_index",
        "excel_col",
        "operating_period_index",
        "shl_opening_keur",
        "drawdown_keur",
        "shl_closing_keur",
        "gross_accrued_keur",
        "cash_int_paid_keur",
        "pik_capitalized_keur",
        "post_senior_cash_keur",
        "cash_consumed_keur",
        "cash_after_shl_keur",
        "cash_for_distribution_keur",
        "pik_triggered",
        "cash_sweep_100_pct",
        "reserve_applied",
        "classification",
        "warnings",
    ]

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in result.audit_table:
            writer.writerow(
                {
                    "period_index": row.period_index,
                    "excel_col": row.excel_col,
                    "operating_period_index": row.operating_period_index,
                    "shl_opening_keur": round(row.shl_opening_keur, 4),
                    "drawdown_keur": round(row.drawdown_keur, 4),
                    "shl_closing_keur": round(row.shl_closing_keur, 4),
                    "gross_accrued_keur": round(row.gross_accrued_keur, 4),
                    "cash_int_paid_keur": round(row.cash_int_paid_keur, 4),
                    "pik_capitalized_keur": round(row.pik_capitalized_keur, 4),
                    "post_senior_cash_keur": round(row.post_senior_cash_keur, 4),
                    "cash_consumed_keur": round(row.cash_consumed_keur, 4),
                    "cash_after_shl_keur": round(row.cash_after_shl_keur, 4),
                    "cash_for_distribution_keur": round(row.cash_for_distribution_keur, 4),
                    "pik_triggered": row.pik_triggered,
                    "cash_sweep_100_pct": row.cash_sweep_100_pct,
                    "reserve_applied": row.reserve_applied,
                    "classification": row.classification,
                    "warnings": "; ".join(row.warnings) if row.warnings else "",
                }
            )


def to_model_summary(result: ShlEngineResult) -> str:
    """Return human-readable summary of the SHL engine result."""
    return (
        f"SHL Engine Result ({result.project_name}):\n"
        f"  Periods: {result.period_count}\n"
        f"  Total gross accrued interest: {result.total_gross_accrued_interest_keur:,.1f} kEUR\n"
        f"  Total cash interest paid:     {result.total_cash_interest_paid_keur:,.1f} kEUR\n"
        f"  Total PIK capitalized:       {result.total_pik_capitalized_keur:,.1f} kEUR\n"
        f"  Total principal repaid:      {result.total_principal_repaid_keur:,.1f} kEUR\n"
        f"  Total SHL DS (incl WHT):     {result.total_shl_debt_service_incl_wht_keur:,.1f} kEUR\n"
        f"  Total cash consumed:         {result.total_cash_consumed_keur:,.1f} kEUR\n"
        f"  PIK periods:                {result.pik_period_count}\n"
        f"  100% cash sweep periods:    {result.cash_sweep_100_pct_period_count}\n"
        f"  Final closing balance:       {result.final_closing_balance_keur:,.1f} kEUR"
    )