"""Senior debt sculpting configuration.

V2-2 compatibility shim. Authoritative definitions have moved to:
    finco_core.inputs.senior_sculpting

All names are re-exported unchanged. Existing callers require no modification.
"""
from finco_core.inputs.senior_sculpting import (  # noqa: F401
    SeniorSculptingMode,
    SeniorFinalRepaymentPolicy,
    SeniorPrincipalCapPolicy,
    SeniorReserveTreatment,
    SeniorSculptingConfig,
    validate_explicit_debt_service_schedule,
)
