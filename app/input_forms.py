"""Editable input forms for Solar and Wind demo projects."""
from __future__ import annotations
from dataclasses import replace, fields, is_dataclass
from typing import Any

from app.capex_overrides import scale_capex_items
from app.streamlit_compat import require_streamlit


def _safe_replace(obj, updates: dict[str, Any]) -> Any:
    """Replace only fields that exist on the dataclass. Ignore unknown fields."""
    if not is_dataclass(obj):
        return obj
    valid_fields = {f.name for f in fields(obj)}
    filtered = {k: v for k, v in updates.items() if k in valid_fields and v is not None}
    if not filtered:
        return obj
    return replace(obj, **filtered)


def apply_project_overrides(project_inputs, overrides: dict[str, Any]) -> Any:
    """Apply overrides to a ProjectInputs dataclass using dataclasses.replace().
    
    Only modifies nested objects for keys present in overrides.
    Preserves all unmodified fields. Ignores unknown field names.
    """
    if not overrides:
        return project_inputs
    
    section_map = {
        'technical': project_inputs.technical,
        'revenue': project_inputs.revenue,
        'capex': project_inputs.capex,
        'financing': project_inputs.financing,
        'tax': project_inputs.tax,
        'info': project_inputs.info,
    }
    
    for section, old_obj in section_map.items():
        if section in overrides and overrides[section]:
            new_obj = _safe_replace(old_obj, overrides[section])
            project_inputs = replace(project_inputs, **{section: new_obj})
    
    return project_inputs


def render_project_input_form(project_inputs, project_type: str):
    """Dispatch to Solar or Wind form. Returns (modified_inputs, was_modified)."""
    if project_type == "Solar":
        return render_solar_input_form(project_inputs)
    elif project_type == "Wind":
        return render_wind_input_form(project_inputs)
    return project_inputs, False


def render_solar_input_form(project_inputs) -> tuple[Any, bool]:
    """Render editable form for Solar project.
    
    Returns (modified_project_inputs, was_modified).
    """
    st = require_streamlit("app.input_forms")
    st.subheader("Solar Project Inputs")
    
    # Technical
    st.markdown("**Technical**")
    tech_cols = st.columns(2)
    with tech_cols[0]:
        capacity = st.number_input(
            "Capacity (MW)", value=float(project_inputs.technical.capacity_mw),
            min_value=0.1, max_value=2000.0, step=1.0, key="solar_capacity"
        )
        availability = st.number_input(
            "Availability (%)", value=float(_get_availability_val(project_inputs.technical) * 100),
            min_value=80.0, max_value=99.9, step=0.1, key="solar_avail"
        )
    with tech_cols[1]:
        p50_h = st.number_input(
            "P50 Hours", value=float(_get_p50_val(project_inputs.technical)),
            min_value=500.0, max_value=3500.0, step=50.0, key="solar_p50"
        )
        degradation = st.number_input(
            "Degradation (%/yr)", value=float(_get_degradation_val(project_inputs.technical) * 100),
            min_value=0.0, max_value=2.0, step=0.05, key="solar_deg"
        )
    
    # Revenue
    st.markdown("**Revenue**")
    rev_cols = st.columns(2)
    with rev_cols[0]:
        tariff = st.number_input(
            "PPA Tariff (EUR/MWh)", value=float(project_inputs.revenue.ppa_base_tariff),
            min_value=0.0, max_value=500.0, step=1.0, key="solar_tariff"
        )
    with rev_cols[1]:
        ppa_term = st.number_input(
            "PPA Term (years)", value=int(project_inputs.revenue.ppa_term_years),
            min_value=5, max_value=40, step=1, key="solar_ppa_term"
        )
    
    # CapEx
    st.markdown("**CapEx**")
    capex_cols = st.columns(2)
    with capex_cols[0]:
        total_capex = st.number_input(
            "Total CapEx (kEUR)", value=float(_get_total_capex_val(project_inputs.capex)),
            min_value=0.0, step=1000.0, key="solar_total_capex"
        )
        target_total_capex = total_capex  # explicit alias; total_capex is read-only
    with capex_cols[1]:
        sculpt_capex = st.number_input(
            "Sculpt CapEx (kEUR)", value=float(getattr(project_inputs.capex, 'sculpt_capex_keur', 0.0)),
            min_value=0.0, step=1000.0, key="solar_sculpt_capex"
        )

    # Financing
    st.markdown("**Financing**")
    fin_cols = st.columns(3)
    with fin_cols[0]:
        target_dscr = st.number_input(
            "Target DSCR", value=float(project_inputs.financing.target_dscr),
            min_value=1.0, max_value=3.0, step=0.05, key="solar_dscr"
        )
    with fin_cols[1]:
        senior_tenor = st.number_input(
            "Senior Tenor (years)", value=int(project_inputs.financing.senior_tenor_years),
            min_value=1, max_value=30, step=1, key="solar_tenor"
        )
    with fin_cols[2]:
        all_in_rate = st.number_input(
            "All-in Rate (%)", value=float(_all_in_rate_display(project_inputs.financing) * 100),
            min_value=0.0, max_value=20.0, step=0.1, key="solar_rate"
        )
    
    # Tax
    st.markdown("**Tax**")
    corp_tax = st.number_input(
        "Corporate Tax Rate (%)", value=float(project_inputs.tax.corporate_rate * 100),
        min_value=0.0, max_value=50.0, step=0.5, key="solar_corp_tax"
    )
    
    modified = st.button("Apply Solar inputs and rerun", key="apply_solar")
    
    if modified:
        # Solar overrides - use first-existing field semantics
        solar_technical_overrides = {
            'capacity_mw': capacity,
        }
        solar_technical_overrides.update(_build_single_field_update(
            project_inputs.technical, ('availability', 'plant_availability', 'capex_availability'), availability / 100))
        solar_technical_overrides.update(_build_single_field_update(
            project_inputs.technical, ('p50_hours', 'operating_hours_p50', 'full_load_hours', 'equivalent_hours'), p50_h))
        solar_technical_overrides.update(_build_single_field_update(
            project_inputs.technical, ('degradation', 'pv_degradation', 'annual_degradation'), degradation / 100))

        solar_capex_overrides = {}
        solar_capex_overrides.update(_build_single_field_update(
            project_inputs.capex, ('sculpt_capex_keur',), sculpt_capex))
        # Scale individual CapexItem amounts proportionally to match target total_capex.
        # This actually changes model outputs (depreciation, debt sizing) unlike the
        # read-only total_capex property which safe_replace silently ignores.
        if target_total_capex > 0 and target_total_capex != project_inputs.capex.total_capex:
            scaled_capex = scale_capex_items(project_inputs.capex, target_total_capex)
            project_inputs = replace(project_inputs, capex=scaled_capex)

        solar_fin_overrides = {
            'target_dscr': target_dscr,
            'senior_tenor_years': senior_tenor,
        }
        solar_fin_overrides.update(_all_in_rate_update(project_inputs.financing, all_in_rate / 100))

        solar_tax_overrides = {}
        solar_tax_overrides.update(_build_single_field_update(
            project_inputs.tax, ('corporate_rate',), corp_tax / 100))

        overrides = {
            'technical': solar_technical_overrides,
            'revenue': {
                'ppa_base_tariff': tariff,
                'ppa_term_years': ppa_term,
            },
            'capex': solar_capex_overrides,
            'financing': solar_fin_overrides,
            'tax': solar_tax_overrides,
        }
        return apply_project_overrides(project_inputs, overrides), True
    
    return project_inputs, False


def render_wind_input_form(project_inputs) -> tuple[Any, bool]:
    """Render editable form for Wind project."""
    st = require_streamlit("app.input_forms")
    st.subheader("Wind Project Inputs")
    
    tech_cols = st.columns(2)
    with tech_cols[0]:
        capacity = st.number_input(
            "Capacity (MW)", value=float(project_inputs.technical.capacity_mw),
            min_value=0.1, max_value=3000.0, step=1.0, key="wind_capacity"
        )
        availability = st.number_input(
            "Availability (%)", value=float(_get_availability_val(project_inputs.technical) * 100),
            min_value=80.0, max_value=99.9, step=0.1, key="wind_avail"
        )
    with tech_cols[1]:
        p50_h = st.number_input(
            "P50 Hours", value=float(_get_p50_val(project_inputs.technical)),
            min_value=1500.0, max_value=4500.0, step=50.0, key="wind_p50"
        )
        degradation = st.number_input(
            "Degradation (%/yr)", value=float(_get_degradation_val(project_inputs.technical) * 100),
            min_value=0.0, max_value=2.0, step=0.05, key="wind_deg"
        )
    
    st.markdown("**Revenue**")
    rev_cols = st.columns(2)
    with rev_cols[0]:
        tariff = st.number_input(
            "PPA Tariff (EUR/MWh)", value=float(project_inputs.revenue.ppa_base_tariff),
            min_value=0.0, max_value=500.0, step=1.0, key="wind_tariff"
        )
    with rev_cols[1]:
        ppa_term = st.number_input(
            "PPA Term (years)", value=int(project_inputs.revenue.ppa_term_years),
            min_value=5, max_value=40, step=1, key="wind_ppa_term"
        )
    
    st.markdown("**CapEx**")
    capex_cols = st.columns(2)
    with capex_cols[0]:
        total_capex = st.number_input(
            "Total CapEx (kEUR)", value=float(_get_total_capex_val(project_inputs.capex)),
            min_value=0.0, step=1000.0, key="wind_total_capex"
        )
        target_total_capex = total_capex  # explicit alias; total_capex is read-only
    with capex_cols[1]:
        sculpt_capex = st.number_input(
            "Sculpt CapEx (kEUR)", value=float(getattr(project_inputs.capex, 'sculpt_capex_keur', 0.0)),
            min_value=0.0, step=1000.0, key="wind_sculpt_capex"
        )

    st.markdown("**Financing**")
    fin_cols = st.columns(3)
    with fin_cols[0]:
        target_dscr = st.number_input(
            "Target DSCR", value=float(project_inputs.financing.target_dscr),
            min_value=1.0, max_value=3.0, step=0.05, key="wind_dscr"
        )
    with fin_cols[1]:
        senior_tenor = st.number_input(
            "Senior Tenor (years)", value=int(project_inputs.financing.senior_tenor_years),
            min_value=1, max_value=30, step=1, key="wind_tenor"
        )
    with fin_cols[2]:
        all_in_rate = st.number_input(
            "All-in Rate (%)", value=float(_all_in_rate_display(project_inputs.financing) * 100),
            min_value=0.0, max_value=20.0, step=0.1, key="wind_rate"
        )
    
    st.markdown("**Tax**")
    corp_tax = st.number_input(
        "Corporate Tax Rate (%)", value=float(project_inputs.tax.corporate_rate * 100),
        min_value=0.0, max_value=50.0, step=0.5, key="wind_corp_tax"
    )
    
    modified = st.button("Apply Wind inputs and rerun", key="apply_wind")
    
    if modified:
        # Wind overrides - use first-existing field semantics
        wind_technical_overrides = {
            'capacity_mw': capacity,
        }
        wind_technical_overrides.update(_build_single_field_update(
            project_inputs.technical, ('availability', 'plant_availability', 'capex_availability'), availability / 100))
        wind_technical_overrides.update(_build_single_field_update(
            project_inputs.technical, ('p50_hours', 'operating_hours_p50', 'full_load_hours', 'equivalent_hours'), p50_h))
        wind_technical_overrides.update(_build_single_field_update(
            project_inputs.technical, ('degradation', 'pv_degradation', 'annual_degradation'), degradation / 100))

        wind_capex_overrides = {}
        wind_capex_overrides.update(_build_single_field_update(
            project_inputs.capex, ('sculpt_capex_keur',), sculpt_capex))
        # Scale individual CapexItem amounts proportionally to match target total_capex.
        if target_total_capex > 0 and target_total_capex != project_inputs.capex.total_capex:
            scaled_capex = scale_capex_items(project_inputs.capex, target_total_capex)
            project_inputs = replace(project_inputs, capex=scaled_capex)

        wind_fin_overrides = {
            'target_dscr': target_dscr,
            'senior_tenor_years': senior_tenor,
        }
        wind_fin_overrides.update(_all_in_rate_update(project_inputs.financing, all_in_rate / 100))

        wind_tax_overrides = {}
        wind_tax_overrides.update(_build_single_field_update(
            project_inputs.tax, ('corporate_rate',), corp_tax / 100))

        overrides = {
            'technical': wind_technical_overrides,
            'revenue': {
                'ppa_base_tariff': tariff,
                'ppa_term_years': ppa_term,
            },
            'capex': wind_capex_overrides,
            'financing': wind_fin_overrides,
            'tax': wind_tax_overrides,
        }
        return apply_project_overrides(project_inputs, overrides), True
    
    return project_inputs, False


def _first_existing_field(obj, candidates: tuple[str, ...]) -> str | None:
    """Return the first field name in candidates that exists on obj."""
    for name in candidates:
        if hasattr(obj, name):
            return name
    return None


def _get_first_existing(obj, candidates: tuple[str, ...], default=None):
    """Return the value of the first existing field, or default."""
    for name in candidates:
        if hasattr(obj, name):
            val = getattr(obj, name)
            if val is not None:
                return val
    return default


def _build_single_field_update(obj, candidates: tuple[str, ...], value):
    """Return {existing_field_name: value} for the first existing field. {} if none."""
    field = _first_existing_field(obj, candidates)
    if field is None:
        return {}
    return {field: value}


def _all_in_rate_display(financing) -> float:
    if hasattr(financing, "all_in_rate"):
        return getattr(financing, "all_in_rate", 0.0) or 0.0
    base = getattr(financing, "base_rate", 0.0) or 0.0
    margin = getattr(financing, "margin_bps", 0) or 0
    return base + margin / 10000.0


def _dataclass_field_names(obj):
    return {f.name for f in fields(obj)} if is_dataclass(obj) else set()


def _all_in_rate_update(financing, user_value: float) -> dict:
    field_names = _dataclass_field_names(financing)

    if "all_in_rate" in field_names:
        return {"all_in_rate": user_value}

    if "base_rate" in field_names and "margin_bps" in field_names:
        margin_bps = getattr(financing, "margin_bps", 0) or 0
        return {"base_rate": max(0.0, user_value - margin_bps / 10000.0)}

    if "base_rate" in field_names:
        return {"base_rate": user_value}

    return {}


# Helpers for safe field access (mirror input_helpers.py)
def _get_availability_val(technical):
    for field in ('availability', 'plant_availability', 'capex_availability'):
        val = getattr(technical, field, None)
        if val is not None:
            return val
    return 0.98

def _get_p50_val(technical):
    for field in ('p50_hours', 'operating_hours_p50', 'full_load_hours', 'equivalent_hours'):
        val = getattr(technical, field, None)
        if val is not None:
            return val
    return 1500.0

def _get_degradation_val(technical):
    for field in ('degradation', 'pv_degradation', 'annual_degradation'):
        val = getattr(technical, field, None)
        if val is not None:
            return val
    return 0.005


def _get_total_capex_val(capex):
    """Get total capex using fallback chain."""
    for field in ('total_capex_keur', 'total_capex'):
        val = getattr(capex, field, None)
        if val is not None:
            return val
    return 0.0
