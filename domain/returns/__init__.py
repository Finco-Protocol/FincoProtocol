"""domain/returns/ — Compatibility shim — V2-4.

Authoritative implementation moved to finco_core.sponsor (xirr, xnpv, sponsor_cashflows).
Uses lazy __getattr__ delegation to avoid circular imports during
finco_core.sponsor initialization.
"""

__all__ = ["xirr", "xirr_bisection", "robust_xirr", "xnpv", "xnpv_schedule"]


def __getattr__(name: str):
    import finco_core.sponsor as _sponsor
    try:
        return getattr(_sponsor, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
