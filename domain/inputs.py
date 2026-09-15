"""Generic project-finance input models for the runtime engine.

V2-2 compatibility shim. Authoritative definitions have moved to:
    finco_core.inputs

All names are re-exported unchanged. Existing callers require no modification.
"""
from finco_core.inputs import (  # noqa: F401
    PeriodFrequency,
    PeriodAxisConvention,
    EquityIRRMethod,
    DebtSizingMethod,
    DebtSizingMode,
    SHLRepaymentMethod,
    YieldScenario,
    AssetClass,
    ASSET_CLASS_USEFUL_LIFE,
    ProjectInfo,
    CapexItem,
    CapexStructure,
    OpexItem,
    TechnicalParams,
    RevenueAdjustmentSchedule,
    RevenueParams,
    DebtSizingCaseConfig,
    FinancingParams,
    TaxParams,
    OpeningTaxLossVintageParams,
    TaxDepreciationMode,
    ShlInterestDeductibilityMode,
    TaxLossUtilisationGate,
    TaxPeriodisationMode,
    ShlAccountingTreatment,
    ShlPaymentMethod,
    ProjectInputs,
    hash_inputs_for_cache,
)
