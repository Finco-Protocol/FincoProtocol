"""Synthetic public tax template package."""
from finco_core.tax.templates.inputs import (
    CITTier,
    TaxDepreciationRule,
    TaxTemplate,
    TaxTemplateOverride,
    ResolvedTaxConfig,
)
from finco_core.tax.templates.calculations import (
    calculate_progressive_cit,
    get_tax_depreciation_rate,
)
from finco_core.tax.templates.schedules import (
    build_tax_depreciation_schedule,
    build_tax_loss_carryforward_schedule,
)
from finco_core.tax.templates.registry import (
    MARKET_A_SIMPLE_2026,
    MARKET_B_INFRA_2026,
    get_builtin_tax_templates,
)
from finco_core.tax.templates.resolver import resolve_tax_template

__all__ = [
    "CITTier",
    "TaxDepreciationRule",
    "TaxTemplate",
    "TaxTemplateOverride",
    "ResolvedTaxConfig",
    "calculate_progressive_cit",
    "get_tax_depreciation_rate",
    "build_tax_depreciation_schedule",
    "build_tax_loss_carryforward_schedule",
    "MARKET_A_SIMPLE_2026",
    "MARKET_B_INFRA_2026",
    "get_builtin_tax_templates",
    "resolve_tax_template",
]
