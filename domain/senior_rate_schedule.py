"""Senior debt rate and day-count schedule helpers.

V2-2 compatibility shim. Authoritative definitions have moved to:
    finco_core.inputs.senior_rate_schedule

All names are re-exported unchanged. Existing callers require no modification.
"""
from finco_core.inputs.senior_rate_schedule import (  # noqa: F401
    SeniorRateMode,
    SeniorDayCountConvention,
    SeniorHedgeConfig,
    SeniorRateSchedule,
    SeniorDebtInterestConfig,
    build_senior_period_rate_schedule,
    senior_period_fraction,
)
