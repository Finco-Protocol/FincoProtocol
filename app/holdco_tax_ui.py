"""Phase 6C.4 — HoldCo tax audit table helpers.

Pure functions — no mutation, no side effects, no Streamlit rendering.

CAVEAT: Values-only. No formulas. No waterfall wiring.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.tax.holdco_result import HoldCoTaxResult

__all__ = [
    "build_holdco_tax_summary_table",
    "build_holdco_tax_period_table",
    "build_holdco_tax_audit_note",
]


def build_holdco_tax_audit_note() -> str:
    """Return the audit-only disclaimer note for HoldCo tax results.

    Returns
    -------
    str
        Audit-only notice text.
    """
    return (
        "AUDIT-ONLY: HoldCo tax results are not wired into waterfall outputs, "
        "cash taxes, or IRR metrics."
    )


def build_holdco_tax_summary_table(
    result: HoldCoTaxResult,
) -> list[dict]:
    """Build a summary table for a single HoldCoTaxResult.

    Pure function — no mutation, no side effects.

    Parameters
    ----------
    result : HoldCoTaxResult
        A single HoldCo entity's tax result.

    Returns
    -------
    list[dict]
        Single-row list with entity-level totals.
        Columns: Entity Code, Country Code, Tax Year,
        Total Taxable Dividend Income (kEUR), Total Taxable Interest Income (kEUR),
        Total Non-Taxable Principal (kEUR), Total WHT Dividends (kEUR),
        Total WHT Interest (kEUR)
    """
    rows = [
        {
            "Entity Code": result.entity_code,
            "Country Code": result.country_code,
            "Tax Year": result.tax_year,
            "Total Taxable Dividend Income (kEUR)": result.total_taxable_dividend_keur,
            "Total Taxable Interest Income (kEUR)": result.total_taxable_interest_keur,
            "Total Non-Taxable Principal (kEUR)": result.total_non_taxable_principal_keur,
            "Total WHT Dividends (kEUR)": result.total_withholding_tax_dividends_keur,
            "Total WHT Interest (kEUR)": result.total_withholding_tax_interest_keur,
        }
    ]
    return rows


def build_holdco_tax_period_table(
    result: HoldCoTaxResult,
) -> list[dict]:
    """Build a per-period breakdown table for a HoldCoTaxResult.

    Pure function — no mutation, no side effects.

    Parameters
    ----------
    result : HoldCoTaxResult
        A single HoldCo entity's tax result.

    Returns
    -------
    list[dict]
        One row per period with all audit fields.
        Columns: Period, Taxable Dividend Income (kEUR), Taxable Interest Income (kEUR),
        Non-Taxable Principal (kEUR), Deductible OPEX (kEUR),
        Taxable Income Before Limitations (kEUR), WHT Dividends (kEUR),
        WHT Interest (kEUR), Interest Limited (kEUR), Notes, Warnings
    """
    rows = []
    for pr in result.period_results:
        rows.append({
            "Period": pr.period_index,
            "Taxable Dividend Income (kEUR)": pr.taxable_dividend_income_keur,
            "Taxable Interest Income (kEUR)": pr.taxable_interest_income_keur,
            "Non-Taxable Principal (kEUR)": pr.non_taxable_principal_keur,
            "Deductible OPEX (kEUR)": pr.deductible_opex_keur,
            "Taxable Income Before Limitations (kEUR)": pr.taxable_income_before_limitations_keur,
            "WHT Dividends (kEUR)": pr.withholding_tax_dividends_keur,
            "WHT Interest (kEUR)": pr.withholding_tax_interest_keur,
            "Interest Limited (kEUR)": pr.interest_limited_keur,
            "Notes": "; ".join(pr.notes) if pr.notes else "",
            "Warnings": "; ".join(pr.warnings) if pr.warnings else "",
        })
    return rows