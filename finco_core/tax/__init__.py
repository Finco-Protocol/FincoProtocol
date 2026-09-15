"""finco_core.tax — Tax engine.

V2-4: Authoritative. finco_core.tax.* are compatibility shims.

Critical invariant: LCF methodology is NOT calibrated to the Excel Golden
Model where Excel is wrong. Finco intentionally keeps the correct Generic Market An
§16 treatment.
"""
from finco_core.tax.engine import (
    taxable_profit,
    tax_liability,
    apply_loss_carryforward,
    atad_limit,
    is_tax_payment_period,
    atad_adjustment,
)
from finco_core.tax.reintegration import fiscal_reintegration
from finco_core.tax.engine_inputs import SPVTaxEngineInputs
from finco_core.tax.engine_result import SPVTaxPeriodResult, SPVTaxResult
from finco_core.tax.engine_runner import run_spv_tax_engine
from finco_core.tax.holdco_inputs import (
    HoldCoTaxInputs,
    WithholdingTaxConfig,
    InterestDeductibilityConfig,
    IntercompanyTaxFlow,
)
from finco_core.tax.holdco_result import HoldCoTaxPeriodResult, HoldCoTaxResult
from finco_core.tax.holdco_calculations import (
    calculate_withholding_tax_keur,
    calculate_holdco_taxable_income_before_limitations,
    exclude_shl_principal_from_taxable_income,
    calculate_interest_limitation_keur,
    calculate_deductible_interest_after_limitation_keur,
)
from finco_core.tax.templates import (
    CITTier,
    TaxDepreciationRule,
    TaxTemplate,
    TaxTemplateOverride,
    ResolvedTaxConfig,
    calculate_progressive_cit,
    get_tax_depreciation_rate,
    build_tax_depreciation_schedule,
    build_tax_loss_carryforward_schedule,
    resolve_tax_template,
)
from finco_core.tax.templates.schedules import (
    TaxDepreciationPeriod,
    TaxDepreciationSchedule,
    TaxLossPeriod,
    TaxLossCarryforwardSchedule,
)
from finco_core.tax.templates.calculations import (
    calculate_taxable_income_keur,
    calculate_tax_depreciation_keur,
)
from finco_core.tax.templates.registry import get_builtin_tax_templates

__all__ = [
    "taxable_profit",
    "tax_liability",
    "apply_loss_carryforward",
    "atad_limit",
    "atad_adjustment",
    "is_tax_payment_period",
    "fiscal_reintegration",
    "get_builtin_tax_templates",
    "resolve_tax_template",
    "CITTier",
    "TaxDepreciationRule",
    "TaxTemplate",
    "TaxTemplateOverride",
    "ResolvedTaxConfig",
    "calculate_progressive_cit",
    "get_tax_depreciation_rate",
    "calculate_tax_depreciation_keur",
    "calculate_taxable_income_keur",
    "TaxDepreciationPeriod",
    "TaxDepreciationSchedule",
    "build_tax_depreciation_schedule",
    "TaxLossPeriod",
    "TaxLossCarryforwardSchedule",
    "build_tax_loss_carryforward_schedule",
    "SPVTaxEngineInputs",
    "SPVTaxPeriodResult",
    "SPVTaxResult",
    "run_spv_tax_engine",
    "HoldCoTaxInputs",
    "WithholdingTaxConfig",
    "InterestDeductibilityConfig",
    "IntercompanyTaxFlow",
    "HoldCoTaxPeriodResult",
    "HoldCoTaxResult",
    "calculate_withholding_tax_keur",
    "calculate_holdco_taxable_income_before_limitations",
    "exclude_shl_principal_from_taxable_income",
    "calculate_interest_limitation_keur",
    "calculate_deductible_interest_after_limitation_keur",
]
