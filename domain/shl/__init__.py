"""domain/shl/ — Compatibility shim — V2-4.

Authoritative implementation moved to finco_core.shl.
Uses lazy __getattr__ delegation to avoid circular imports during
finco_core.shl initialization.
"""

__all__ = [
    "ShlEngine",
    "ShlEngineInputs",
    "ShlPeriodInput",
    "ShlPeriodResult",
    "ShlEngineResult",
    "ShlAuditRow",
    "ShlTaxInterface",
    "to_audit_dataframe",
    "to_csv",
    "to_model_summary",
    "ShlRuntimeAdapter",
    "run_canonical_shl",
]


def __getattr__(name: str):
    # Delegate to finco_core.shl for canonical symbols
    try:
        import finco_core.shl as _shl
        return getattr(_shl, name)
    except AttributeError:
        pass
    # Fallback: try domain.shl submodules for audit/runtime_adapter (not in finco_core.shl.__init__)
    _SUBMODULE_MAP = {
        "to_audit_dataframe": "domain.shl.audit",
        "to_csv": "domain.shl.audit",
        "to_model_summary": "domain.shl.audit",
        "ShlRuntimeAdapter": "domain.shl.runtime_adapter",
        "run_canonical_shl": "domain.shl.runtime_adapter",
    }
    if name in _SUBMODULE_MAP:
        import importlib
        mod = importlib.import_module(_SUBMODULE_MAP[name])
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
