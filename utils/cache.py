"""
Deprecated compatibility shim. Use app.cache directly.

This module re-exports from app.cache for backward compatibility with
any code that imports from utils.cache. New code should import directly
from app.cache.
"""
import warnings

# Re-export all cached functions from canonical app.cache
from app.cache import (
    hash_inputs_for_cache,
    hash_engine_for_cache,
    cached_generation_schedule,
    cached_revenue_schedule,
    cached_opex_schedule_annual,
    cached_model_state,
    cached_run_waterfall_v3,
    clear_all_caches,
)

__all__ = [
    "hash_inputs_for_cache",
    "hash_engine_for_cache",
    "cached_generation_schedule",
    "cached_revenue_schedule",
    "cached_opex_schedule_annual",
    "cached_model_state",
    "cached_run_waterfall_v3",
    "clear_all_caches",
    "invalidate_waterfall_cache",
    "get_waterfall_cache",
    "compute_waterfall_cached",
    "WaterfallCache",
    "deprecated",
]


def invalidate_waterfall_cache():
    """Alias for clear_all_caches(). Deprecated; use app.cache.clear_all_caches()."""
    warnings.warn(
        "utils.cache.invalidate_waterfall_cache is deprecated; use app.cache.clear_all_caches",
        DeprecationWarning,
        stacklevel=2,
    )
    return clear_all_caches()


# Backward-compat shims for utils/__init__.py re-exports

class WaterfallCache:
    """Placeholder compatibility shim. In new code use app.cache directly."""

    def __init__(self):
        warnings.warn(
            "utils.cache.WaterfallCache is deprecated and is a no-op placeholder",
            DeprecationWarning,
            stacklevel=2,
        )

    def get(self, inputs_key: str):
        return None

    def set(self, inputs_key: str, result: dict):
        pass

    def clear(self):
        clear_all_caches()

    def invalidate_if_changed(self, inputs_key: str) -> bool:
        return False


def get_waterfall_cache() -> WaterfallCache:
    warnings.warn(
        "utils.cache.get_waterfall_cache is deprecated; use app.cache.clear_all_caches directly",
        DeprecationWarning,
        stacklevel=2,
    )
    return WaterfallCache()


def deprecated(msg: str):
    """Decorator to mark functions as deprecated."""
    def wrapper(func):
        def inner(*args, **kwargs):
            warnings.warn(f"{func.__name__} is deprecated. {msg}", DeprecationWarning, stacklevel=2)
            return func(*args, **kwargs)
        inner.__name__ = func.__name__
        return inner
    return wrapper


def compute_waterfall_cached(*args, **kwargs):
    warnings.warn(
        "utils.cache.compute_waterfall_cached is deprecated; "
        "use app.waterfall_core.run_waterfall_v3_core or app.cache.cached_run_waterfall_v3",
        DeprecationWarning,
        stacklevel=2,
    )
    from app.waterfall_core import run_waterfall_v3_core
    return run_waterfall_v3_core(*args, **kwargs)