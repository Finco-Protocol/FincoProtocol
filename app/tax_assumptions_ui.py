"""Phase 6D.1 — Tax assumptions UI helpers (visibility/governance only).

Pure functions — no mutation, no side effects, no Streamlit rendering.

CAVEAT: Values-only. No persistence. No active model wiring.
"""
from __future__ import annotations

import pandas as pd
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.tax.templates.inputs import TaxTemplate, TaxTemplateOverride, ResolvedTaxConfig

__all__ = [
    "build_tax_template_summary_table",
    "build_tax_template_tiers_table",
    "build_tax_depreciation_rules_table",
    "build_tax_override_table",
    "build_resolved_tax_config_summary",
    "build_tax_assumptions_audit_note",
]


def build_tax_assumptions_audit_note() -> str:
    """Return the audit-only disclaimer for tax assumptions helpers.

    Returns
    -------
    str
        Audit-only notice text.
    """
    return (
        "AUDIT-ONLY: Tax assumptions helpers are visibility/governance tools "
        "and do not modify active model outputs."
    )


def build_tax_template_summary_table(
    templates: tuple[TaxTemplate, ...],
) -> pd.DataFrame:
    """Build a summary table for one or more TaxTemplate objects.

    Pure function — no mutation, no side effects.

    Parameters
    ----------
    templates : tuple[TaxTemplate, ...]
        One or more tax templates.

    Returns
    -------
    pd.DataFrame
        One row per template. Columns: Template Code, Country Code, Tax Year,
        CIT Structure, Base CIT Rate, Progressive Tiers Count, Loss Carryforward
        Years, Has Interest Limitation, Has WHT Dividend, Has WHT Interest, Notes
    """
    rows = []
    for tmpl in templates:
        n_tiers = len(tmpl.cit_tiers)
        if n_tiers == 0:
            cit_structure = "None"
        elif n_tiers == 1:
            cit_structure = "Flat"
        else:
            cit_structure = "Progressive"

        base_rate = tmpl.cit_tiers[0].tax_rate if n_tiers > 0 else None

        rows.append({
            "Template Code": tmpl.template_name,
            "Country Code": tmpl.country_code,
            "Tax Year": tmpl.tax_year,
            "CIT Structure": cit_structure,
            "Base CIT Rate": base_rate,
            "Progressive Tiers Count": n_tiers,
            "Loss Carryforward Years": tmpl.loss_carryforward_years,
            "Has Interest Limitation": tmpl.interest_limitation_pct_ebitda is not None,
            "Has WHT Dividend": tmpl.withholding_tax_dividends > 0.0,
            "Has WHT Interest": tmpl.withholding_tax_interest > 0.0,
            "Notes": tmpl.metadata_dict.get("notes", ""),
        })
    return pd.DataFrame(rows)


def build_tax_template_tiers_table(
    template: TaxTemplate,
) -> pd.DataFrame:
    """Build a per-tier breakdown table for one TaxTemplate.

    Pure function — no mutation, no side effects.

    Parameters
    ----------
    template : TaxTemplate
        A single tax template.

    Returns
    -------
    pd.DataFrame
        One row per CIT tier. Columns: Tier #, Min Profit (kEUR),
        Max Profit (kEUR), Tax Rate.
        Unbounded final tier shows "Unlimited" in Max Profit (kEUR).
    """
    rows = []
    for i, tier in enumerate(template.cit_tiers):
        max_display = "Unlimited" if tier.max_profit_keur is None else tier.max_profit_keur
        rows.append({
            "Tier #": i + 1,
            "Min Profit (kEUR)": tier.min_profit_keur,
            "Max Profit (kEUR)": max_display,
            "Tax Rate": tier.tax_rate,
        })
    return pd.DataFrame(rows)


def build_tax_depreciation_rules_table(
    template: TaxTemplate,
) -> pd.DataFrame:
    """Build a depreciation rules table for one TaxTemplate.

    Pure function — no mutation, no side effects.

    Parameters
    ----------
    template : TaxTemplate
        A single tax template.

    Returns
    -------
    pd.DataFrame
        One row per depreciation rule. Columns: Asset Category, Method,
        Useful Life, Annual Rate, Max Deductible Rate, Deductible, Notes.
    """
    rows = []
    for rule in template.depreciation_rules:
        rows.append({
            "Asset Category": rule.asset_category,
            "Method": rule.method,
            "Useful Life": rule.useful_life_years,
            "Annual Rate": rule.annual_rate,
            "Max Deductible Rate": rule.max_deductible_rate,
            "Deductible": rule.deductible,
            "Notes": rule.notes,
        })
    return pd.DataFrame(rows)


def build_tax_override_table(
    overrides: tuple[TaxTemplateOverride, ...],
) -> pd.DataFrame:
    """Build an override summary table.

    Pure function — no mutation, no side effects.

    Parameters
    ----------
    overrides : tuple[TaxTemplateOverride, ...]
        One or more override objects.

    Returns
    -------
    pd.DataFrame
        One row per override. Columns: Override Path, Override Value,
        Source (override_name), Notes (reason).
    """
    rows = []
    for ovr in overrides:
        rows.append({
            "Override Path": ovr.field_path,
            "Override Value": ovr.override_value,
            "Source": ovr.override_name,
            "Notes": ovr.reason,
        })
    return pd.DataFrame(rows)


def build_resolved_tax_config_summary(
    resolved: ResolvedTaxConfig,
) -> pd.DataFrame:
    """Build a summary row for a ResolvedTaxConfig.

    Pure function — no mutation, no side effects.

    Parameters
    ----------
    resolved : ResolvedTaxConfig
        A single resolved tax configuration.

    Returns
    -------
    pd.DataFrame
        Single-row DataFrame with effective configuration summary.
        Columns: Template Code, Country Code, Tax Year, Override Count,
        Effective CIT Structure, Metadata.
    """
    n_tiers = len(resolved.resolved_template.cit_tiers)
    if n_tiers == 0:
        cit_structure = "None"
    elif n_tiers == 1:
        cit_structure = "Flat"
    else:
        cit_structure = "Progressive"

    rows = [{
        "Template Code": resolved.resolved_template.template_name,
        "Country Code": resolved.resolved_template.country_code,
        "Tax Year": resolved.resolved_template.tax_year,
        "Override Count": len(resolved.overrides),
        "Effective CIT Structure": cit_structure,
        "Metadata": dict(resolved.resolved_metadata),
    }]
    return pd.DataFrame(rows)