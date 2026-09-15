"""domain/waterfall/ — Compatibility shim — V2-4.

Authoritative implementation moved to finco_core.waterfall.
Uses lazy __getattr__ delegation to avoid circular imports during
finco_core.waterfall initialization.
"""

__all__ = [
    "compute_waterfall",
    "WaterfallResult",
    "distribution_after_lockup",
    "reserve_account_balances",
    "dsra_funding",
    "run_waterfall",
]


def __getattr__(name: str):
    import finco_core.waterfall as _wf
    try:
        return getattr(_wf, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
