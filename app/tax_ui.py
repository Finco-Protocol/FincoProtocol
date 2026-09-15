"""Phase 6B.5 — Audit/export helpers for SPV tax engine results.

Pure helper functions — no mutation, no Streamlit rendering, no model integration.

CAVEAT: These helpers produce export/UI-ready tables only.
SPV tax engine results are NOT yet wired into waterfall outputs or IRR metrics.
"""
from __future__ import annotations

import pandas as pd

from domain.tax import SPVTaxResult

__all__ = [
    "build_spv_tax_summary_table",
    "build_spv_tax_period_table",
    "build_tax_audit_note",
]


def build_spv_tax_summary_table(result: SPVTaxResult) -> pd.DataFrame:
    """Build a one-row summary DataFrame from an SPVTaxResult.

    Pure function: no mutation of result.

    Parameters
    ----------
    result : SPVTaxResult
        Tax engine output for one SPV entity.

    Returns
    -------
    pd.DataFrame
        Single-row DataFrame with columns:
        - Entity Code
        - Country Code
        - Tax Year
        - Total Taxable Income Before Losses (kEUR)
        - Total Loss Used (kEUR)
        - Total Taxable Income After Losses (kEUR)
        - Total CIT Payable (kEUR)
        - Ending Loss Carryforward (kEUR)
    """
    df = pd.DataFrame([{
        "Entity Code": result.entity_code,
        "Country Code": result.country_code,
        "Tax Year": result.tax_year,
        "Total Taxable Income Before Losses (kEUR)": round(result.total_taxable_income_before_losses_keur, 2),
        "Total Loss Used (kEUR)": round(result.total_loss_used_keur, 2),
        "Total Taxable Income After Losses (kEUR)": round(result.total_taxable_income_after_losses_keur, 2),
        "Total CIT Payable (kEUR)": round(result.total_cit_payable_keur, 2),
        "Ending Loss Carryforward (kEUR)": round(result.ending_loss_carryforward_keur, 2),
    }])
    return df


def build_spv_tax_period_table(result: SPVTaxResult) -> pd.DataFrame:
    """Build a per-period detail DataFrame from an SPVTaxResult.

    Pure function: no mutation of result.

    Parameters
    ----------
    result : SPVTaxResult
        Tax engine output for one SPV entity.

    Returns
    -------
    pd.DataFrame
        Multi-row DataFrame (one row per period) with columns:
        - Period
        - EBITDA (kEUR)
        - Deductible Interest (kEUR)
        - Book Depreciation (kEUR)
        - Tax Depreciation (kEUR)
        - Non-Deductible Depreciation (kEUR)
        - Taxable Income Before Losses (kEUR)
        - Loss Used (kEUR)
        - Taxable Income After Losses (kEUR)
        - CIT Payable (kEUR)
        - Closing Loss Carryforward (kEUR)
        - Effective Tax Rate
    """
    rows = []
    for p in result.periods:
        rows.append({
            "Period": p.period,
            "EBITDA (kEUR)": round(p.ebitda_keur, 2),
            "Deductible Interest (kEUR)": round(p.deductible_interest_keur, 2),
            "Book Depreciation (kEUR)": round(p.book_depreciation_keur, 2),
            "Tax Depreciation (kEUR)": round(p.tax_depreciation_keur, 2),
            "Non-Deductible Depreciation (kEUR)": round(p.non_deductible_depreciation_keur, 2),
            "Taxable Income Before Losses (kEUR)": round(p.taxable_income_before_losses_keur, 2),
            "Loss Used (kEUR)": round(p.loss_used_keur, 2),
            "Taxable Income After Losses (kEUR)": round(p.taxable_income_after_losses_keur, 2),
            "CIT Payable (kEUR)": round(p.cit_payable_keur, 2),
            "Closing Loss Carryforward (kEUR)": round(p.closing_loss_carryforward_keur, 2),
            "Effective Tax Rate": round(p.effective_tax_rate, 6),
        })
    return pd.DataFrame(rows)


def build_tax_audit_note() -> str:
    """Return the audit-only notice for tax engine results.

    Returns
    -------
    str
        Audit notice text.
    """
    return (
        "AUDIT-ONLY: SPV tax engine results are not yet wired into "
        "waterfall outputs or IRR metrics."
    )