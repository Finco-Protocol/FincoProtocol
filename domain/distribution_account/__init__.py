"""Compatibility shim — V2-4.

Authoritative implementation moved to finco_core.engine.distribution_account.

Uses __getattr__ lazy delegation to avoid circular import during
finco_core.engine.distribution_account initialization.
"""


def __getattr__(name: str):
    import finco_core.engine.distribution_account as _da
    try:
        return getattr(_da, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
