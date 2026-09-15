"""Canonical KPI extraction for reporting surfaces.

This module is read-only glue: it does not run the model and does not
recalculate financial metrics. It centralizes the WaterfallResult fields used by
executive, IC, credit, lender, and export reporting surfaces.
"""
from __future__ import annotations

from typing import Any


CANONICAL_REPORT_KPI_FIELDS: tuple[str, ...] = (
    "project_irr",
    "equity_irr",
    "equity_npv",
    "actual_avg_dscr",
    "min_dscr",
    "min_llcr",
    "min_plcr",
    "total_distribution_keur",
    "total_revenue_keur",
    "total_ebitda_keur",
    "total_opex_keur",
    "total_tax_keur",
    "total_senior_ds_keur",
    "periods_in_lockup",
)


def build_canonical_report_kpis(result: Any) -> dict[str, Any]:
    """Return report KPIs directly from WaterfallResult attributes."""
    return {
        field: getattr(result, field, None)
        for field in CANONICAL_REPORT_KPI_FIELDS
    }
