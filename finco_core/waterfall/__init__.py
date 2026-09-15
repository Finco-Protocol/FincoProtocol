"""finco_core.waterfall — Waterfall engine.

V2-4: Authoritative. finco_core.waterfall.* are compatibility shims.

Post-engine mutation is prohibited. cf_after_tax_keur is computed once by
the waterfall and never overridden. The tax bridge is reconciliation-only
(cash_tax_bridge_reconciliation_keur), per Phase 0 Z2.
"""
from finco_core.waterfall.waterfall_engine import WaterfallPeriod, run_waterfall
from finco_core.waterfall.cash_flow import (
    WaterfallResult,
    compute_waterfall,
    distribution_after_lockup,
)
from finco_core.waterfall.dsra_engine import DSRAEngineResult, run_dsra_engine
from finco_core.waterfall.shl_engine import SHLPeriodResult, compute_shl_period_v3
from finco_core.waterfall.tax_engine import TaxPeriodResult, compute_period_tax
from finco_core.waterfall.reserves import reserve_account_balances, dsra_funding

__all__ = [
    # waterfall_engine
    "WaterfallPeriod",
    "run_waterfall",
    # cash_flow
    "WaterfallResult",
    "compute_waterfall",
    "distribution_after_lockup",
    # dsra_engine
    "DSRAEngineResult",
    "run_dsra_engine",
    # shl_engine
    "SHLPeriodResult",
    "compute_shl_period_v3",
    # tax_engine
    "TaxPeriodResult",
    "compute_period_tax",
    # reserves
    "reserve_account_balances",
    "dsra_funding",
]
