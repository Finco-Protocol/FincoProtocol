"""domain/depreciation/ — Compatibility shim — V2-4.

Authoritative implementation moved to finco_core.depreciation.
Uses lazy __getattr__ delegation to avoid circular imports during
finco_core.depreciation initialization.
"""

__all__ = [
    "AssetClassConfig",
    "DepreciationLedgerInput",
    "DepreciationLedgerResult",
    "DepreciationPeriodResult",
    "DepreciationPolicy",
    "build_depreciation_ledger",
    "straight_line_depreciation_for_period",
    "DepreciationEngine",
    "DepreciationEngineInputs",
    "DepreciationEngineResult",
    "DepreciationAuditRow",
]


def __getattr__(name: str):
    import finco_core.depreciation as _dep
    try:
        return getattr(_dep, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
