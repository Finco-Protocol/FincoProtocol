"""Phase 6A — Tax template result types.

All result types are defined in inputs.py. This module re-exports them
for logical grouping (result module = outputs of template resolution).
"""
from __future__ import annotations

from finco_core.tax.templates.inputs import (
    CITTier,
    TaxDepreciationRule,
    TaxTemplate,
    TaxTemplateOverride,
    ResolvedTaxConfig,
)

__all__ = [
    "CITTier",
    "TaxDepreciationRule",
    "TaxTemplate",
    "TaxTemplateOverride",
    "ResolvedTaxConfig",
]
