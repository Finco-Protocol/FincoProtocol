"""MVP G2B — Simple Sponsor Returns (clean, downstream-only, no circular dependency)."""

from financial_engine.sponsor_returns.contracts import (
    ReturnMetricStatus,
    SponsorCashFlowPeriod,
    SponsorReturnResult,
    SponsorDistributionPolicy,
)
from financial_engine.sponsor_returns.model import run_project_sponsor_returns_model

__all__ = [
    "ReturnMetricStatus",
    "SponsorCashFlowPeriod",
    "SponsorReturnResult",
    "SponsorDistributionPolicy",
    "run_project_sponsor_returns_model",
]
