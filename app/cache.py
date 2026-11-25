"""App-level caching with optional Streamlit compatibility.

Production FINCO Model is served by ``main_web:app`` and must import without
Streamlit installed. This module preserves the historical cache API shape for
legacy shells, but falls back to a headless-safe decorator when Streamlit is
unavailable.
"""
from __future__ import annotations

import sys
import threading
from functools import lru_cache, wraps
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.inputs import ProjectInputs
    from domain.period_engine import PeriodEngine


def _active_streamlit_runtime():
    """The Streamlit module ONLY when a Streamlit runtime is actually serving this process, else ``None``.

    FINCO45C (FINCO44-NEW-06 / C3-E-04): the FastAPI path (``main_web``/``main_api``) must never initialise
    ``st.cache_data`` outside a Streamlit runtime - doing so at import time logged "No runtime found" warnings on API
    start. Streamlit is never imported here: when a legacy Streamlit shell runs, it has already imported it.
    """
    st = sys.modules.get("streamlit")
    if st is None:
        return None
    try:
        from streamlit import runtime as st_runtime
        return st if st_runtime.exists() else None
    except Exception:  # noqa: BLE001 - any doubt -> headless fallback (same values, no Streamlit cache)
        return None


def cache_data(*decorator_args, **decorator_kwargs):
    """Cache decorator: Streamlit's ``st.cache_data`` inside a live Streamlit runtime, else a headless fallback.

    The choice is made per call, lazily: the Streamlit-cached function is created on the first call made INSIDE a
    Streamlit runtime (never at import), so API processes never touch Streamlit. The fallback keeps the historical
    behaviour (``lru_cache`` keyed by the arguments, uncached when they are unhashable). ``clear()`` invalidates both.
    """

    def decorator(func):
        cached_func = lru_cache(maxsize=None)(func)
        streamlit_cached: list = []
        lock = threading.Lock()

        def _streamlit_version(st):
            with lock:
                if not streamlit_cached:
                    streamlit_cached.append(st.cache_data(*decorator_args, **decorator_kwargs)(func))
                return streamlit_cached[0]

        @wraps(func)
        def wrapper(*args, **kwargs):
            st = _active_streamlit_runtime()
            if st is not None:
                return _streamlit_version(st)(*args, **kwargs)
            try:
                return cached_func(*args, **kwargs)
            except TypeError:
                return func(*args, **kwargs)

        def clear() -> None:
            cached_func.cache_clear()
            with lock:
                if streamlit_cached:
                    streamlit_cached[0].clear()

        wrapper.clear = clear
        return wrapper

    return decorator


def hash_inputs_for_cache(inputs: "ProjectInputs") -> int:
    """Deterministic hash for ProjectInputs for cache keying."""
    return hash(
        (
            inputs.info.name,
            inputs.info.country_iso,
            inputs.capex.total_capex,
            inputs.financing.gearing_ratio,
            inputs.financing.senior_tenor_years,
            inputs.financing.use_senior_sweep_cash_cap_for_shl,
            inputs.revenue.ppa_base_tariff,
            inputs.revenue.ppa_term_years,
            inputs.info.cod_date.toordinal() if hasattr(inputs.info.cod_date, "toordinal") else 0,
        )
    )


def hash_engine_for_cache(engine: "PeriodEngine") -> int:
    """Deterministic hash for PeriodEngine for cache keying."""
    dated_end = getattr(engine, "dated_life_end_exclusive", None)
    base = (
        getattr(engine, "fc", getattr(engine, "anchor_date", None)),
        getattr(engine, "construction_months", None),
        getattr(engine, "horizon_years", getattr(engine, "num_periods", None)),
        getattr(engine, "ppa_years", None),
        getattr(engine, "freq", getattr(engine, "periods_per_year", None)),
    )
    if dated_end is not None:
        base = base + (("dated_life_end_exclusive", dated_end.isoformat()),)
    return hash(base)


@cache_data(
    show_spinner=False,
    hash_funcs={
        "ProjectInputs": hash_inputs_for_cache,
        "PeriodEngine": hash_engine_for_cache,
    },
)
def cached_generation_schedule(
    inputs: "ProjectInputs",
    engine: "PeriodEngine",
    yield_scenario: str = "P50",
) -> dict[int, float]:
    """Cached generation schedule."""
    from domain.revenue.generation import full_generation_schedule

    return full_generation_schedule(inputs, engine, yield_scenario)


@cache_data(
    show_spinner=False,
    hash_funcs={
        "ProjectInputs": hash_inputs_for_cache,
        "PeriodEngine": hash_engine_for_cache,
    },
)
def cached_revenue_schedule(
    inputs: "ProjectInputs",
    engine: "PeriodEngine",
) -> dict[int, float]:
    """Cached revenue schedule."""
    from domain.revenue.generation import full_revenue_schedule

    return full_revenue_schedule(inputs, engine)


@cache_data(
    show_spinner=False,
    hash_funcs={
        "ProjectInputs": hash_inputs_for_cache,
    },
)
def cached_opex_schedule_annual(
    inputs: "ProjectInputs",
    horizon_years: int = 30,
) -> dict[int, float]:
    """Cached annual OPEX schedule."""
    from domain.opex.projections import opex_schedule_annual

    return opex_schedule_annual(inputs, horizon_years)


@cache_data(
    show_spinner=False,
    hash_funcs={
        "ProjectInputs": hash_inputs_for_cache,
        "PeriodEngine": hash_engine_for_cache,
    },
)
def cached_model_state(
    inputs: "ProjectInputs",
    engine: "PeriodEngine",
):
    """Cached model state with all precomputed schedules."""
    from domain.model_state import build_model_state

    return build_model_state(inputs, engine)


@cache_data(
    show_spinner="Calculating waterfall...",
    hash_funcs={
        "ProjectInputs": hash_inputs_for_cache,
        "PeriodEngine": hash_engine_for_cache,
    },
)
def cached_run_waterfall_v3(
    inputs: "ProjectInputs",
    engine: "PeriodEngine",
    rate_per_period: float,
    tenor_periods: int,
    target_dscr: float = 1.15,
    lockup_dscr: float = 1.10,
    tax_rate: float = 0.10,
    dsra_months: int = 6,
    shl_amount: float = 0.0,
    shl_rate: float = 0.0,
    shl_idc_keur: float = 0.0,
    shl_repayment_method: str = "bullet",
    shl_tenor_years: int = 0,
    shl_wht_rate: float = 0.0,
    discount_rate_project: float = 0.0641,
    discount_rate_equity: float = 0.0965,
    fixed_debt_keur: float | None = None,
    fixed_ds_keur: float | None = None,
    rate_schedule: list[float] | None = None,
    equity_irr_method: str = "equity_only",
    share_capital_keur: float = 0.0,
    sculpt_capex_keur: float = 0.0,
    debt_sizing_method: str = "dscr_sculpt",
    dscr_schedule: list[float] | None = None,
):
    """Cached waterfall computation."""
    from app.waterfall_core import run_waterfall_v3_core

    return run_waterfall_v3_core(
        inputs=inputs,
        engine=engine,
        rate_per_period=rate_per_period,
        tenor_periods=tenor_periods,
        target_dscr=target_dscr,
        lockup_dscr=lockup_dscr,
        tax_rate=tax_rate,
        dsra_months=dsra_months,
        shl_amount=shl_amount,
        shl_rate=shl_rate,
        shl_idc_keur=shl_idc_keur,
        shl_repayment_method=shl_repayment_method,
        shl_tenor_years=shl_tenor_years,
        shl_wht_rate=shl_wht_rate,
        discount_rate_project=discount_rate_project,
        discount_rate_equity=discount_rate_equity,
        fixed_debt_keur=fixed_debt_keur,
        fixed_ds_keur=fixed_ds_keur,
        rate_schedule=rate_schedule,
        equity_irr_method=equity_irr_method,
        share_capital_keur=share_capital_keur,
        sculpt_capex_keur=sculpt_capex_keur,
        debt_sizing_method=debt_sizing_method,
        dscr_schedule=dscr_schedule,
    )


def clear_all_caches() -> None:
    """Invalidate all caches."""
    cached_generation_schedule.clear()
    cached_revenue_schedule.clear()
    cached_opex_schedule_annual.clear()
    cached_model_state.clear()
    cached_run_waterfall_v3.clear()


__all__ = [
    "hash_inputs_for_cache",
    "hash_engine_for_cache",
    "cached_generation_schedule",
    "cached_revenue_schedule",
    "cached_opex_schedule_annual",
    "cached_model_state",
    "cached_run_waterfall_v3",
    "clear_all_caches",
]
