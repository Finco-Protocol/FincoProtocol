"""finco_core.validation — Input validation layer.

V2-4: Authoritative. finco_core.validation.validators is a compatibility shim.

Covers: boundary validation for ProjectInputs and FinancingParams. Called before
RunConfiguration is built. Produces typed validation errors; does not raise
exceptions into engine code.
"""
from finco_core.validation.validators import (
    ValidationIssue,
    ModelWarning,
    MODEL_WARNING_CODES,
    validate_project_inputs,
    validate_portfolio_inputs,
    warn_model_unrealistic,
    dscr_reconciliation_fields,
)

__all__ = [
    "ValidationIssue",
    "ModelWarning",
    "MODEL_WARNING_CODES",
    "validate_project_inputs",
    "validate_portfolio_inputs",
    "warn_model_unrealistic",
    "dscr_reconciliation_fields",
]
