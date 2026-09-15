"""Illustrative synthetic tax-template registry for public demos."""
from __future__ import annotations

from finco_core.tax.templates.inputs import CITTier, TaxDepreciationRule, TaxTemplate


MARKET_A_SIMPLE_2026 = TaxTemplate(
    country_code="XA",
    template_name="Generic Market A 2026 (Illustrative)",
    tax_year=2026,
    cit_tiers=(CITTier(min_profit_keur=0.0, max_profit_keur=None, tax_rate=0.20),),
    depreciation_rules=(
        TaxDepreciationRule(
            asset_category="buildings",
            method="straight_line",
            annual_rate=None,
            useful_life_years=20.0,
            max_deductible_rate=None,
            bonus_depreciation_pct=0.0,
            deductible=True,
            notes="Synthetic 20-year straight-line assumption",
        ),
        TaxDepreciationRule(
            asset_category="equipment",
            method="straight_line",
            annual_rate=None,
            useful_life_years=10.0,
            max_deductible_rate=None,
            bonus_depreciation_pct=0.0,
            deductible=True,
            notes="Synthetic 10-year straight-line assumption",
        ),
    ),
    withholding_tax_dividends=0.05,
    withholding_tax_interest=0.02,
    loss_carryforward_years=5,
    thin_cap_ratio=4.0,
    interest_limitation_pct_ebitda=0.30,
    metadata=(("note", "synthetic illustrative profile — not tax advice"),),
)

MARKET_B_INFRA_2026 = TaxTemplate(
    country_code="XB",
    template_name="Generic Market B Infrastructure 2026 (Illustrative)",
    tax_year=2026,
    cit_tiers=(CITTier(min_profit_keur=0.0, max_profit_keur=None, tax_rate=0.22),),
    depreciation_rules=(
        TaxDepreciationRule(
            asset_category="infrastructure",
            method="straight_line",
            annual_rate=None,
            useful_life_years=25.0,
            max_deductible_rate=0.04,
            bonus_depreciation_pct=0.0,
            deductible=True,
            notes="Synthetic infrastructure assumption",
        ),
        TaxDepreciationRule(
            asset_category="equipment",
            method="declining_balance",
            annual_rate=0.20,
            useful_life_years=10.0,
            max_deductible_rate=None,
            bonus_depreciation_pct=0.0,
            deductible=True,
            notes="Synthetic equipment assumption",
        ),
    ),
    withholding_tax_dividends=0.06,
    withholding_tax_interest=0.03,
    loss_carryforward_years=6,
    thin_cap_ratio=3.5,
    interest_limitation_pct_ebitda=0.30,
    metadata=(("note", "synthetic illustrative profile — not tax advice"),),
)

_BUILTIN_TEMPLATES = (MARKET_A_SIMPLE_2026, MARKET_B_INFRA_2026)


def get_builtin_tax_templates() -> tuple[TaxTemplate, ...]:
    return _BUILTIN_TEMPLATES
