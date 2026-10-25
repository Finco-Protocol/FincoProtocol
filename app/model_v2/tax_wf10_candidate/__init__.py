"""WF-10 tax candidate — package exports (release-closed candidate).

This package is not released financial authority, is never imported by
any production path, and adds no product surface. See ``contracts.py``
for the typed scope and ``docs/model_v2/WF10_TAX_OWNER_DECISIONS.md``
for the open financial decisions.
"""
from app.model_v2.tax_wf10_candidate.contracts import (  # noqa: F401
    ACTIVATION_ENABLED,
    DEPRECIATION_METHODS,
    INTERCOMPANY_FLOW_TYPES,
    INTEREST_LIMITATION_COMBINATIONS,
    NONRECOVERABLE_TREATMENTS,
    RATE_SCHEDULE_MODES,
    TAX_ENTITY_KINDS,
    VAT_PHASES,
    WHT_FLOW_TYPES,
    DepreciationAsset,
    IntercompanyFlow,
    InterestLimitationInputs,
    OpeningLossVintage,
    TaxCandidateBook,
    TaxEntityBook,
    TaxEntityIdentity,
    TaxLossCarryforwardConfig,
    TaxRateSchedule,
    TaxRateWindow,
    VatConfig,
    VatPeriodInput,
    WithholdingRule,
    canonical_json,
    require_release,
)

__all__ = [
    "ACTIVATION_ENABLED", "require_release",
    "TAX_ENTITY_KINDS", "RATE_SCHEDULE_MODES", "DEPRECIATION_METHODS",
    "VAT_PHASES", "NONRECOVERABLE_TREATMENTS", "WHT_FLOW_TYPES",
    "INTERCOMPANY_FLOW_TYPES", "INTEREST_LIMITATION_COMBINATIONS",
    "TaxEntityIdentity", "TaxRateWindow", "TaxRateSchedule",
    "TaxLossCarryforwardConfig", "OpeningLossVintage",
    "InterestLimitationInputs", "DepreciationAsset",
    "VatConfig", "VatPeriodInput", "WithholdingRule",
    "IntercompanyFlow", "TaxEntityBook", "TaxCandidateBook",
    "canonical_json",
]
