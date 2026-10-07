"""EV Charging V1 — Workbook presentation adapter (labels, visibility, bridge).

Presentation only: relabels technology-neutral registry rows with EV charging
terminology, hides generation-only controls that carry neutral engine values
for EV, and injects the transparent charging-bridge display rows. It never
changes values, bindings, snapshot keys, or engine inputs (spec N/V: the PPA
fields are an internal compatibility adapter and must never surface as
PPA/P50/P90 terminology on an EV workbook).
"""
from __future__ import annotations

EV_TEMPLATE_SOURCE = "generic_ev_charging_reference"

# Registry field_id → EV label (units keep registry semantics).
_EV_LABELS: dict[str, str] = {
    "project_setup.technical.capacity_mw": "Installed Charging Capacity (MW)",
    "project_setup.technical.p50_hours": "Equivalent Full-Load Hours (Stabilized)",
    "revenue.ppa.base_tariff": "Charging Price (EUR/MWh)",
    "revenue.ppa.index": "Charging Price Escalation (%/yr)",
    "revenue.ppa.term_years": "Charging Price Schedule Horizon",
    "revenue.ppa.tariff_legacy": "Charging Price (EUR/MWh)",
}

# Generation-only controls: hidden on EV workbooks. Their engine values are
# neutral by the EV adapter (CO2 off, no balancing, merchant-only revenue);
# hiding is presentation-only.
_EV_HIDDEN: frozenset[str] = frozenset({
    "project_setup.technical.capacity_factor",
    "revenue.ppa.production_share",
    "revenue.balancing.merchant_pct",
    "revenue.balancing.cost_eur_per_mwh",
    "revenue.balancing.co2_enabled",
    "revenue.balancing.co2_price_eur_mwh",
    "revenue.merchant.price_curve_json",
})


def is_ev_pis(pis) -> bool:
    """True when the input set belongs to an EV Charging reference/working copy."""
    origin = getattr(pis, "snapshot_origin", None) or {}
    try:
        return str(origin.get("template_source", "")).strip().lower() == EV_TEMPLATE_SOURCE
    except AttributeError:
        return False



def _bridge_rows(pis) -> list[dict]:
    """Transparent charging bridge (spec V): drivers → energy → grid purchase."""
    try:
        capacity = float(pis.get("project_setup.technical.capacity_mw") or 0.0)
        hours = float(pis.get("project_setup.technical.p50_hours") or 0.0)
    except Exception:
        return []
    from app.ev_charging_economics import (
        CHARGING_EFFICIENCY,
        energy_delivered_mwh,
        full_load_hours_for_year,
        grid_energy_purchased_mwh,
        implied_utilisation_pct,
        STABILIZED_FULL_LOAD_HOURS,
    )
    if capacity <= 0 or hours <= 0:
        return []
    # Display contract uses the stabilized year for the standing bridge.
    delivered = energy_delivered_mwh(capacity, 3) if hours == STABILIZED_FULL_LOAD_HOURS else capacity * hours
    purchased = grid_energy_purchased_mwh(capacity, 3) if hours == STABILIZED_FULL_LOAD_HOURS else capacity * hours / CHARGING_EFFICIENCY

    def _row(field_id: str, label: str, value: float, unit: str, help_text: str) -> dict:
        return {
            "field_id": field_id,
            "label": label,
            "unit": unit,
            "field_type": "float",
            "binding_label": "display-only",
            "options": [],
            "section_id": "bridge",
            "section_label": "Charging Bridge",
            "value": round(value, 4),
            "required": False,
            "min_value": None,
            "max_value": None,
            "step": "any",
            "help_text": help_text,
        }

    rows = [
        _row(
            "ev_charging.display.energy_delivered",
            "Energy Delivered (Stabilized)",
            delivered,
            "MWh/yr",
            "Installed Charging Capacity × Equivalent Full-Load Hours.",
        ),
        _row(
            "ev_charging.display.implied_utilisation",
            "Implied Utilisation",
            implied_utilisation_pct(3) if hours == STABILIZED_FULL_LOAD_HOURS else hours / 8760.0 * 100.0,
            "%",
            "Equivalent Full-Load Hours / 8760.",
        ),
        _row(
            "ev_charging.display.grid_energy_purchased",
            "Grid Energy Purchased (Stabilized)",
            purchased,
            "MWh/yr",
            "Energy Delivered / Charging Efficiency (94%).",
        ),
    ]
    del full_load_hours_for_year
    return rows


# ── Assumption Register presentation (UX Correction B2) ──────────────────
# Workflow 04 canonical assumption identities are technology-neutral and are
# NOT changed here.  The rendered register is a presentation surface: on EV
# workbooks the internal compatibility authorities relabel to charging
# terminology and compatibility-only generation/PPA rows are omitted —
# exactly mirroring the workbook field contract above.
_EV_REGISTER_LABELS: dict[str, str] = {
    "revenue.ppa_base_tariff": "Charging Price",
    "revenue.ppa_index": "Charging Price Escalation",
    "revenue.ppa_term_years": "Charging Price Schedule Horizon",
    "technical.operating_hours_p50": "Equivalent Full-Load Hours",
    "technical.capacity_mw": "Installed Charging Capacity",
}

# Compatibility-only rows omitted from the rendered EV register (their
# workbook field counterparts are hidden by _EV_HIDDEN; same contract).
_EV_REGISTER_HIDDEN: frozenset[str] = frozenset({
    "revenue.ppa_production_share",
    "revenue.ppa_tariff_by_operating_period",
    "revenue.ppa_indexation_start_policy",
    "revenue.ppa_indexation_start_date",
    "revenue.market_prices_curve",
    "revenue.market_prices_by_calendar_year_eur_mwh",
    "revenue.first_merchant_operating_period_index",
    "revenue.balancing_cost_pv",
    "revenue.balancing_cost_wind_eur_mwh",
    "revenue.balancing_cost_bess",
    "revenue.balancing_cost_eur_per_mwh",
    "revenue.co2_enabled",
    "revenue.co2_price_eur",
    "revenue.co2_certificate_price_eur_per_mwh",
    "financing.debt_sizing_case.production_yield_scenario",
    "technical.operating_hours_p90_10y",
    "technical.operating_hours_p90_1y",
    "technical.operating_hours_p99_1y",
    "technical.yield_scenario",
})


def apply_ev_register_presentation(rows: list[dict]) -> list[dict]:
    """Return register display rows with EV presentation applied.

    ``rows`` are presentation dicts carrying the canonical ``path``.  Hidden
    compatibility-only rows are omitted; known paths relabel to EV charging
    terminology.  Canonical identities and stored values are untouched.
    """
    out: list[dict] = []
    for row in rows:
        path = str(row.get("path", ""))
        if path in _EV_REGISTER_HIDDEN:
            continue
        relabeled = dict(row)
        if path in _EV_REGISTER_LABELS:
            relabeled["label"] = _EV_REGISTER_LABELS[path]
        out.append(relabeled)
    return out


def apply_ev_presentation(fields: list[dict], pis) -> list[dict]:
    """Return the sheet-field list with EV presentation applied (no-op otherwise)."""
    if not is_ev_pis(pis):
        return fields
    out: list[dict] = []
    for field in fields:
        field_id = str(field.get("field_id", ""))
        if field_id in _EV_HIDDEN:
            continue
        relabeled = dict(field)
        if field_id in _EV_LABELS:
            relabeled["label"] = _EV_LABELS[field_id]
        out.append(relabeled)
        # Inject the bridge + persisted-driver rows after the stabilized hours
        # row on project setup (spec §11: the sheet exposes the true drivers).
        if field_id == "project_setup.technical.capacity_mw":
            out.extend(_bridge_rows(pis))
    return out
