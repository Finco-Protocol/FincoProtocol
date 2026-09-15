"""Generic hierarchical OPEX engine.

Public API for the clean hierarchical OPEX calculation layer.  Import from
this package; do not import from private submodules directly.

Quick-start
-----------
>>> from finco_core.opex.hierarchical import (
...     OpexModelInput, OpexCategoryInput, OpexSubitemInput,
...     OpexActivationSchedule, OpexCalculationContext,
...     OpexActivationMode, OpexEscalationConvention,
...     OpexCategoryCalculationType,
...     validate_opex_model_input, has_errors, compute_annual, compute_periods,
... )
"""
from __future__ import annotations

from ._calculator import (
    OpexInputValidationError,
    compute_annual,
    compute_periods,
)
from ._inputs import (
    OpexActivationSchedule,
    OpexCalculationContext,
    OpexCategoryInput,
    OpexModelInput,
    OpexSubitemInput,
)
from ._results import (
    CategoryAnnualResult,
    CategoryPeriodResult,
    OpexAnnualResult,
    OpexPeriodResult,
    SubitemAnnualResult,
    SubitemPeriodResult,
)
from ._types import (
    OpexActivationMode,
    OpexAmountBasis,
    OpexCategoryCalculationType,
    OpexEscalationConvention,
)
from ._validation import (
    OpexValidationIssue,
    ValidationSeverity,
    has_errors,
    validate_opex_model_input,
)

__all__ = [
    # types
    "OpexAmountBasis",
    "OpexActivationMode",
    "OpexEscalationConvention",
    "OpexCategoryCalculationType",
    # inputs
    "OpexActivationSchedule",
    "OpexSubitemInput",
    "OpexCategoryInput",
    "OpexCalculationContext",
    "OpexModelInput",
    # results
    "SubitemAnnualResult",
    "CategoryAnnualResult",
    "OpexAnnualResult",
    "SubitemPeriodResult",
    "CategoryPeriodResult",
    "OpexPeriodResult",
    # validation
    "OpexValidationIssue",
    "ValidationSeverity",
    "validate_opex_model_input",
    "has_errors",
    # calculation
    "compute_annual",
    "compute_periods",
    "OpexInputValidationError",
]
