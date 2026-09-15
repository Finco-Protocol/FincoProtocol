"""Helpers for full-model Excel extract parity.

The raw workbooks are not runtime dependencies, but compact JSON extracts carry
the full cash-flow and SHL lifecycle tables. This module contains the pure
transformations from those extracted rows into calculation-ready series.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from finco_core.sponsor.xirr import xirr


def rows_from_columns(columns: list[str], raw_rows: list[list[Any]]) -> list[dict[str, Any]]:
    """Return row dictionaries from compact `[columns] + rows` fixture shape."""
    return [
        {column: value for column, value in zip(columns, row)}
        for row in raw_rows
    ]


def project_cash_flow_rows(extract: dict[str, Any]) -> list[dict[str, Any]]:
    """Return full-model project cash-flow rows keyed by column name."""
    return rows_from_columns(extract["project_cf_columns"], extract["project_cf"])


def shl_lifecycle_rows(extract: dict[str, Any]) -> list[dict[str, Any]]:
    """Return full-model SHL lifecycle rows keyed by column name."""
    return rows_from_columns(extract["shl_columns"], extract["shl"])


def period_diagnostic_rows(extract: dict[str, Any]) -> list[dict[str, Any]]:
    """Return full-model CF/DS/P&L/Dep operating rows keyed by column name."""
    return rows_from_columns(extract["period_diagnostic_columns"], extract["period_diagnostics"])


def period_diagnostic_by_date(extract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return full-model operating period diagnostics keyed by period end date."""
    return {
        str(row["date"]): row
        for row in period_diagnostic_rows(extract)
    }


def project_irr_from_extract(extract: dict[str, Any]) -> float | None:
    """Calculate project IRR from extracted full-model project cash flows."""
    return _xirr_from_named_rows(project_cash_flow_rows(extract), "project_irr_cf")


def unlevered_project_irr_from_extract(extract: dict[str, Any]) -> float | None:
    """Calculate unlevered project IRR from extracted full-model cash flows."""
    return _xirr_from_named_rows(project_cash_flow_rows(extract), "unlevered_project_irr_cf")


def sponsor_equity_shl_rows_from_extract(extract: dict[str, Any]) -> list[dict[str, Any]]:
    """Return sponsor equity + SHL rows using Excel cash-flow convention."""
    rows = []
    for row in extract["shl"]:
        cash_flow = float(row[4] or 0.0) + float(row[5] or 0.0) + float(row[7] or 0.0)
        rows.append({
            "date": row[0],
            "cash_flow_keur": cash_flow,
            "shl_principal_flow_keur": row[4],
            "paid_net_interest_keur": row[5],
            "net_dividend_keur": row[7],
        })
    return rows


def sponsor_equity_shl_irr_from_extract(extract: dict[str, Any]) -> float | None:
    """Calculate sponsor equity + SHL IRR from extracted SHL rows."""
    return _xirr_from_cash_flow_rows(sponsor_equity_shl_rows_from_extract(extract))


def sponsor_equity_shl_irr_from_financial_close(
    extract: dict[str, Any],
    financial_close: date,
) -> float | None:
    """Calculate sponsor IRR with first SHL investment timed at financial close."""
    shl_rows = extract.get("shl", [])
    if not shl_rows:
        return None

    cash_flows = [
        float(shl_rows[0][4] or 0.0)
        + float(shl_rows[0][5] or 0.0)
        + float(shl_rows[0][7] or 0.0)
    ]
    dates = [financial_close]
    for row in shl_rows[1:]:
        cash_flows.append(float(row[4] or 0.0) + float(row[5] or 0.0) + float(row[7] or 0.0))
        dates.append(date.fromisoformat(str(row[0])))
    return xirr(cash_flows, dates)


def shl_lifecycle_by_date(extract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return SHL lifecycle rows keyed by date, using app diagnostic names."""
    return {
        row[0]: {
            "date": row[0],
            "opening_balance_keur": row[1],
            "closing_balance_keur": row[2],
            "gross_interest_keur": row[3],
            "principal_paid_keur": max(0.0, row[4]),
            "cash_interest_paid_keur": row[5],
            "pik_or_capitalized_interest_keur": row[6],
            "distribution_keur": max(0.0, row[7]),
        }
        for row in extract["shl"]
    }


def _xirr_from_named_rows(rows: list[dict[str, Any]], cash_flow_key: str) -> float | None:
    cash_flows = [float(row[cash_flow_key]) for row in rows]
    dates = [date.fromisoformat(str(row["date"])) for row in rows]
    return xirr(cash_flows, dates)


def _xirr_from_cash_flow_rows(rows: list[dict[str, Any]]) -> float | None:
    cash_flows = [float(row["cash_flow_keur"]) for row in rows]
    dates = [date.fromisoformat(str(row["date"])) for row in rows]
    return xirr(cash_flows, dates)


__all__ = [
    "project_cash_flow_rows",
    "project_irr_from_extract",
    "period_diagnostic_by_date",
    "period_diagnostic_rows",
    "rows_from_columns",
    "shl_lifecycle_by_date",
    "shl_lifecycle_rows",
    "sponsor_equity_shl_irr_from_extract",
    "sponsor_equity_shl_irr_from_financial_close",
    "sponsor_equity_shl_rows_from_extract",
    "unlevered_project_irr_from_extract",
]
