"""Pure input summary builders — used by both UI and Excel export."""
from __future__ import annotations
import pandas as pd


def _get_technology(project_inputs):
    """Get technology from project inputs with fallback chain."""
    technical = getattr(project_inputs, 'technical', None)
    info = getattr(project_inputs, 'info', None)
    if technical:
        for field in ('technology', 'technology_type', 'pv_technology'):
            val = getattr(technical, field, None)
            if val and val != 'n/a':
                return val
    if info:
        for field in ('technology', 'project_type', 'name'):
            val = getattr(info, field, None)
            if val and val != 'n/a':
                return val
    return 'n/a'


def _get_p50_hours(technical):
    """Get P50 hours with field name fallback."""
    for field in ('p50_hours', 'operating_hours_p50', 'full_load_hours', 'equivalent_hours'):
        val = getattr(technical, field, None)
        if val is not None:
            return val
    return 'n/a'


def _get_availability(technical):
    """Get availability with field name fallback."""
    for field in ('availability', 'plant_availability', 'capex_availability'):
        val = getattr(technical, field, None)
        if val is not None:
            return val
    return 'n/a'


def _get_degradation(technical):
    """Get degradation with field name fallback."""
    for field in ('degradation', 'pv_degradation', 'annual_degradation'):
        val = getattr(technical, field, None)
        if val is not None:
            return val
    return 'n/a'


def build_inputs_summary_table(project_inputs) -> pd.DataFrame:
    """Build a clean summary table of key project inputs."""
    if project_inputs is None:
        return pd.DataFrame(columns=["Field", "Value"])
    info = getattr(project_inputs, 'info', None)
    technical = getattr(project_inputs, 'technical', None)
    revenue = getattr(project_inputs, 'revenue', None)
    financing = getattr(project_inputs, 'financing', None)
    capex = getattr(project_inputs, 'capex', None)
    opex = getattr(project_inputs, 'opex', None)
    rows = []
    if info:
        rows.extend([
            ("Name", getattr(info, 'name', 'n/a')),
            ("Code", getattr(info, 'code', 'n/a')),
            ("Country", getattr(info, 'country_iso', 'n/a')),
            ("Horizon Years", getattr(info, 'horizon_years', 'n/a')),
            ("Construction Months", getattr(info, 'construction_months', 'n/a')),
            ("PPA Term (years)", getattr(revenue, 'ppa_term_years', 'n/a') if revenue else 'n/a'),
            ("Financial Close", str(getattr(info, 'financial_close', 'n/a'))),
        ])
    if technical:
        rows.extend([
            ("Technology", _get_technology(project_inputs)),
            ("Capacity (MW)", getattr(technical, 'capacity_mw', 'n/a')),
            ("P50 Hours", _get_p50_hours(technical)),
            ("Availability", _get_availability(technical)),
            ("Degradation", _get_degradation(technical)),
        ])
    if revenue:
        rows.extend([
            ("PPA Tariff", getattr(revenue, 'ppa_base_tariff', 'n/a')),
            ("PPA Index", getattr(revenue, 'ppa_index', 'n/a')),
        ])
    if financing:
        all_in_rate = (
            getattr(financing, 'base_rate', 0.0) + getattr(financing, 'margin_bps', 0) / 10_000
        )
        rows.extend([
            ("Target DSCR", getattr(financing, 'target_dscr', 'n/a')),
            ("Gearing (%, indicative input)", getattr(financing, 'gearing_ratio', 'n/a') * 100 if getattr(financing, 'gearing_ratio', None) is not None else 'n/a'),
            ("Senior Tenor (years)", getattr(financing, 'senior_tenor_years', 'n/a')),
            ("All-in Rate", all_in_rate),
        ])
    if capex:
        rows.append(("Total CapEx (kEUR)", getattr(capex, 'total_capex', getattr(capex, 'total_capex_keur', 'n/a'))))
    if opex:
        rows.append(("Year 1 OPEX (kEUR)", sum(getattr(item, 'y1_amount_keur', 0.0) for item in opex)))
    if not rows:
        return pd.DataFrame(columns=["Field", "Value"])
    return pd.DataFrame(rows, columns=["Field", "Value"])


def build_capex_summary_table(project_inputs) -> pd.DataFrame:
    """Build CapEx summary table."""
    if project_inputs is None:
        return pd.DataFrame(columns=["Field", "Value"])
    capex = getattr(project_inputs, 'capex', None)
    if capex is None:
        return pd.DataFrame(columns=["Field", "Value"])
    total_capex = getattr(capex, 'total_capex', None) or getattr(capex, 'total_capex_keur', 'n/a')
    sculpt_capex = getattr(capex, 'sculpt_capex_keur', 'n/a')
    rows = [
        ("Total CapEx (kEUR)", total_capex),
        ("Sculpt CapEx (kEUR)", sculpt_capex),
    ]
    return pd.DataFrame(rows, columns=["Field", "Value"])


def build_capex_items_table(project_inputs) -> pd.DataFrame:
    """Build CapEx items table if available — safe, no None() calls."""
    if project_inputs is None:
        return pd.DataFrame(columns=["Name", "Asset Class", "Amount (kEUR)", "Life (years)"])
    capex = getattr(project_inputs, 'capex', None)
    if capex is None:
        return pd.DataFrame(columns=["Name", "Asset Class", "Amount (kEUR)", "Life (years)"])
    # Safe: check if callable before calling
    capex_items_attr = getattr(capex, 'capex_items', None)
    if callable(capex_items_attr):
        items = capex_items_attr()
    else:
        items = (
            getattr(capex, 'asset_items', None)
            or getattr(capex, 'items', None)
            or getattr(capex, 'capex_items', None)
            or []
        )
    if not items:
        return pd.DataFrame(columns=["Name", "Asset Class", "Amount (kEUR)", "Life (years)"])
    rows = []
    for item in items:
        rows.append((
            getattr(item, 'name', getattr(item, 'description', 'n/a')),
            str(getattr(item, 'asset_class', 'n/a')),
            getattr(item, 'amount_keur', getattr(item, 'total_keur', 'n/a')),
            getattr(item, 'useful_life_override', getattr(item, 'useful_life_years', 'n/a')),
        ))
    return pd.DataFrame(rows, columns=["Name", "Asset Class", "Amount (kEUR)", "Life (years)"])
