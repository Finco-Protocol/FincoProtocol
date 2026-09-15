"""
finco_core — FINCO Protocol v2 financial engine core package.

This package is the extraction target for the validated financial engine
from FINCO Protocol (Legacy Engine Baseline SHA: b52d39c).

It has zero dependencies on finco_app, finco_parity, or any UI framework.
All imports flow inward: finco_app depends on finco_core, never the reverse.

Subpackages (populated during V2-2 through V2-5):
    inputs      — ProjectInputs, FinancingParams, ProjectInfo, RunConfiguration
    engine      — FinancialEngine, EngineResult (waterfall, tax, SHL, debt)
    debt        — Senior debt schedule, sculpting, covenant engine
    tax         — TaxEngine, LossCarryforward, Generic Market An CIT §16
    depreciation — Book and tax depreciation, ledger
    shl         — Shareholder loan engine, canonical wiring
    waterfall   — WaterfallEngine, WaterfallPeriod, WaterfallResult
    sponsor     — Sponsor cashflow, multi-investor waterfall
    audit       — AuditResult typed contract (no post-engine mutation)
    exports     — ExportResult typed contract
    validation  — Input validation, boundary checks
"""
