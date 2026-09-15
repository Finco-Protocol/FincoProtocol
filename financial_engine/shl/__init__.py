"""financial_engine.shl — Canonical SHL accrual/balance schedule (C3B3D1 + C3B3D2B0/B1).

Pure, identity-blind, immutable. No imports from app, finco_core waterfall,
fastapi, jinja2, requests, openpyxl, or pandas.

C3B3D1: canonical schedule runner (BULLET/EXPLICIT_SCHEDULE repayment).
C3B3D2B0: clean operating waterfall primitive (no mode dispatch, no mode enum).
C3B3D2B1: typed day-count convention, production schedule chaining, cash seam.
"""
from financial_engine.shl.contracts import (
    ShlDayCountConvention,
    ShlInterestRateMode,
    ShlInterestPaymentMode,
    ShlRepaymentMode,
    ShlSchedulePolicy,
    ShlPeriodInput,
    ShlPeriodResult,
    ShlScheduleResult,
    ShlWaterfallPolicy,
)
from financial_engine.shl.day_count import compute_shl_dcf
from financial_engine.shl.engine import compute_shl_period
from financial_engine.shl.production import (
    ShlConstructionInput,
    ShlFullScheduleResult,
    ShlOperatingPeriodInput,
    compute_shl_schedule,
)
from financial_engine.shl.schedule import run_shl_schedule
from financial_engine.shl.waterfall import (
    ShlWaterfallPeriodResult,
    compute_shl_dcf_actual_365_inclusive,
    compute_shl_waterfall_period,
)

__all__ = [
    # Contracts
    "ShlDayCountConvention",
    "ShlInterestRateMode",
    "ShlInterestPaymentMode",
    "ShlRepaymentMode",
    "ShlSchedulePolicy",
    "ShlPeriodInput",
    "ShlPeriodResult",
    "ShlScheduleResult",
    "ShlWaterfallPolicy",
    # C3B3D1: canonical schedule engine
    "compute_shl_period",
    "run_shl_schedule",
    # C3B3D2B0: clean operating waterfall
    "ShlWaterfallPeriodResult",
    "compute_shl_dcf_actual_365_inclusive",
    "compute_shl_waterfall_period",
    # C3B3D2B1: typed DCF + production schedule
    "compute_shl_dcf",
    "ShlConstructionInput",
    "ShlOperatingPeriodInput",
    "ShlFullScheduleResult",
    "compute_shl_schedule",
]
