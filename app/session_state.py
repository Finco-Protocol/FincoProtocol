"""Session state schema — typed access to Streamlit session state.

S2-3: Clean, typed session state management.
All session state fields are documented and centrally defined.
"""
from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class SessionSchema:
    """Typed schema for all Streamlit session state fields.

    Usage in pages:
        from app.session_state import get_schema
        schema = get_schema(st.session_state)
        if schema.inputs_key != schema.last_inputs_key:
            runner.invalidate_cache()

    Or as a decorator pattern:
        @require_schema
        def my_page(st, schema, ...):
            ...
    """
    # Project identification
    project_name: str = ""
    project_code: str = ""

    # Caching
    inputs_key: str = ""          # Hash of current inputs (for cache invalidation)
    last_inputs_key: str = ""     # Previous inputs key (detect changes)
    waterfall_cached: bool = False

    # UI state
    active_page: str = ""
    sidebarCollapsed: bool = False

    # Chart selections
    selected_chart: str = "waterfall"
    selected_periods: list[int] = field(default_factory=list)

    # Waterfall results (large object, cached separately)
    waterfall_result_key: str = ""

    # Monte Carlo / sensitivity
    mc_runs: int = 500
    mc_seed: int = 42
    sensitivity_params: dict = field(default_factory=dict)

    # Theme
    dark_mode: bool = False

    # Last updated timestamp
    last_update_ts: float = 0.0

    def has_inputs_changed(self) -> bool:
        """Return True if inputs have changed since last computation."""
        return self.inputs_key != self.last_inputs_key

    def mark_clean(self) -> None:
        """Mark current inputs as clean (last_inputs_key = inputs_key)."""
        self.last_inputs_key = self.inputs_key


# Global schema instance (for type hints, not actual session state)
_schema_example = SessionSchema()


def get_schema(state: Any) -> SessionSchema:
    """Extract typed SessionSchema from raw Streamlit session state.

    Args:
        state: Streamlit session state (st.session_state)

    Returns:
        SessionSchema with all fields populated from state
    """
    return SessionSchema(
        project_name=getattr(state, "project_name", ""),
        project_code=getattr(state, "project_code", ""),
        inputs_key=getattr(state, "inputs_key", ""),
        last_inputs_key=getattr(state, "last_inputs_key", ""),
        waterfall_cached=getattr(state, "waterfall_cached", False),
        active_page=getattr(state, "active_page", ""),
        sidebarCollapsed=getattr(state, "sidebarCollapsed", False),
        selected_chart=getattr(state, "selected_chart", "waterfall"),
        selected_periods=list(getattr(state, "selected_periods", [])),
        waterfall_result_key=getattr(state, "waterfall_result_key", ""),
        mc_runs=int(getattr(state, "mc_runs", 500)),
        mc_seed=int(getattr(state, "mc_seed", 42)),
        sensitivity_params=dict(getattr(state, "sensitivity_params", {})),
        dark_mode=bool(getattr(state, "dark_mode", False)),
        last_update_ts=float(getattr(state, "last_update_ts", 0.0)),
    )


def update_schema(state: Any, schema: SessionSchema) -> None:
    """Write back SessionSchema fields to Streamlit session state.

    Args:
        state: Streamlit session state (st.session_state)
        schema: SessionSchema with updated values
    """
    state.project_name = schema.project_name
    state.project_code = schema.project_code
    state.inputs_key = schema.inputs_key
    state.last_inputs_key = schema.last_inputs_key
    state.waterfall_cached = schema.waterfall_cached
    state.active_page = schema.active_page
    state.sidebarCollapsed = schema.sidebarCollapsed
    state.selected_chart = schema.selected_chart
    state.selected_periods = schema.selected_periods
    state.waterfall_result_key = schema.waterfall_result_key
    state.mc_runs = schema.mc_runs
    state.mc_seed = schema.mc_seed
    state.sensitivity_params = schema.sensitivity_params
    state.dark_mode = schema.dark_mode
    state.last_update_ts = schema.last_update_ts


__all__ = ["SessionSchema", "get_schema", "update_schema"]