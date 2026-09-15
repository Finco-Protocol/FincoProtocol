"""domain/tax/ — Compatibility shim — V2-4.

Authoritative implementation moved to finco_core.tax.
Uses lazy __getattr__ delegation to avoid circular imports during
finco_core.tax initialization.
"""

__all__ = [
    # Phase 1-4 existing
    "taxable_profit",
    "tax_liability",
    "apply_loss_carryforward",
    "atad_limit",
    "fiscal_reintegration",
    # Phase 6A
    "get_builtin_tax_templates",
    "resolve_tax_template",
    "CITTier",
    "TaxDepreciationRule",
    "TaxTemplate",
    "TaxTemplateOverride",
    "ResolvedTaxConfig",
    # Phase 6B.1
    "calculate_progressive_cit",
    "get_tax_depreciation_rate",
    "calculate_tax_depreciation_keur",
    "calculate_taxable_income_keur",
    # Phase 6B.2
    "TaxDepreciationPeriod",
    "TaxDepreciationSchedule",
    "build_tax_depreciation_schedule",
    # Phase 6B.3
    "TaxLossPeriod",
    "TaxLossCarryforwardSchedule",
    "build_tax_loss_carryforward_schedule",
    # Phase 6B.4
    "SPVTaxEngineInputs",
    "SPVTaxPeriodResult",
    "SPVTaxResult",
    "run_spv_tax_engine",
    # Phase 6C.1 — HoldCo schema
    "HoldCoTaxInputs",
    "WithholdingTaxConfig",
    "InterestDeductibilityConfig",
    "IntercompanyTaxFlow",
    "HoldCoTaxPeriodResult",
    "HoldCoTaxResult",
    # Phase 6C.2 — HoldCo tax calculation primitives
    "calculate_withholding_tax_keur",
    "calculate_holdco_taxable_income_before_limitations",
    "exclude_shl_principal_from_taxable_income",
    "calculate_interest_limitation_keur",
    "calculate_deductible_interest_after_limitation_keur",
]


def __getattr__(name: str):
    import finco_core.tax as _tax
    try:
        return getattr(_tax, name)
    except AttributeError:
        pass
    # Fallback to domain.tax.engine for atad_adjustment (may not be in finco_core.tax top-level)
    if name == "atad_adjustment":
        from domain.tax.engine import atad_adjustment
        return atad_adjustment
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
