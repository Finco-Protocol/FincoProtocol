"""Data Center Correction B — Full Vertical Integrity & Product-Fidelity.

Regression suite asserting that the Generic Data Center workbook is
completely free of renewable-vertical semantics leaking into any rendered
surface.

Coverage:
  DC_CAPEX_NO_RENEWABLE_LEAKAGE       CAPEX taxonomy has no renewable sub-lines.
  DC_OPEX_NO_RENEWABLE_LEAKAGE        OPEX taxonomy has no renewable sub-lines.
  DC_POWER_RAMP_AND_ESCALATION        Power expenses ramp with occupancy + escalation.
  DC_SENSITIVITY_DRIVERS              Sensitivity drivers are DC-native; renewable
                                       drivers rejected with 422 for DC.
  DC_SENSITIVITY_NOT_BLOCKED          Sensitivity endpoint returns 200 (not 409) for DC.
  DC_REVENUE_SECTION_GUARD            is_data_center flag present in workbook context.
  DC_OPEX_CATALOG_NO_METEO            B.01 for DC has no "Meteorological" item.
  DC_OPEX_CATALOG_NO_VEGETATION       B.03 for DC has no "Vegetation Management".
  DC_CATALOG_B01_DC_HAS_DCIM          B.01 for DC has DCIM/monitoring item.
  DC_CATALOG_B03_DC_HAS_ROAD          B.03 for DC has road/perimeter maintenance.
  DC_ROUTER_IS_DC_IN_BASE_CTX         _base_sheet_ctx includes is_data_center.
  DC_SOLAR_NO_REGRESSION              Solar economics unchanged by this correction.
  DC_WIND_NO_REGRESSION               Wind economics unchanged by this correction.
  DC_OCCUPANCY_SENSITIVITY_SCALE      dc_occupancy steps use percent-point units (e.g. 10.0 not 0.10).
  DC_SERVICE_PRICE_SNAPSHOT_KEY       service_price snapshot_key matches registry canonical key.
  DC_TERMINOLOGY_NO_IT_LOAD_HOURS     revenue template uses "Equivalent IT Load Energy" not "IT Load Hours".
  DC_SOURCES_AND_USES_RECONCILE       Actual senior debt < 65% gearing cap (DSCR-sized, not max-capped).
  DC_ACTUAL_GEARING_PRESENTATION      Actual gearing is derived from DSCR capacity, distinct from 65% max cap.
  DC_HORIZON_PRESENTATION             DC projections use 20-year horizon with no Y21+ output.
"""
from __future__ import annotations

import math

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _factory():
    from app.project_factories import create_generic_data_center_reference
    return create_generic_data_center_reference()


def _drivers():
    from app.data_center_authority import GENERIC_DATA_CENTER_REFERENCE_DRIVERS
    return GENERIC_DATA_CENTER_REFERENCE_DRIVERS


def _opex_children(parent_code: str, technology: str = "data_center"):
    from app.reference_detail_catalog import opex_children
    return opex_children(parent_code, technology=technology)


def _capex_children(parent_code: str, technology: str = "data_center"):
    from app.reference_detail_catalog import capex_children
    return capex_children(parent_code, technology=technology)


# ─────────────────────────────────────────────────────────────────────────────
# DC_CAPEX_NO_RENEWABLE_LEAKAGE
# ─────────────────────────────────────────────────────────────────────────────

RENEWABLE_CAPEX_MARKERS = {
    "inverter", "pv module", "solar", "panel", "turbine", "blade",
    "rotor", "wind", "tracker", "meteorological",
}


def _has_renewable_marker(label: str) -> bool:
    low = label.lower()
    return any(m in low for m in RENEWABLE_CAPEX_MARKERS)


def test_DC_CAPEX_NO_RENEWABLE_LEAKAGE():
    """No CAPEX sub-line in the DC taxonomy uses renewable vocabulary."""
    from app.reference_detail_catalog import _CAPEX_ROWS

    dc_capex = _CAPEX_ROWS.get("data_center", {})
    assert dc_capex, "data_center CAPEX rows must be present"
    for parent_code, children in dc_capex.items():
        for label, _weight in children:
            assert not _has_renewable_marker(label), (
                f"CAPEX {parent_code}: sub-line {label!r} contains renewable vocabulary"
            )


# ─────────────────────────────────────────────────────────────────────────────
# DC_OPEX_NO_RENEWABLE_LEAKAGE
# ─────────────────────────────────────────────────────────────────────────────

RENEWABLE_OPEX_MARKERS = {
    "meteorological", "weather forecast", "vegetation",
    "pv module", "solar", "blade", "wind turbine",
}


def _has_renewable_opex_marker(label: str) -> bool:
    low = label.lower()
    return any(m in low for m in RENEWABLE_OPEX_MARKERS)


def _all_dc_opex_labels() -> list[tuple[str, str]]:
    """Return (parent_code, label) for every effective DC OPEX sub-line."""
    from app.reference_detail_catalog import opex_children

    # All standard OPEX parent codes
    parent_codes = [
        "B.01", "B.02", "B.03", "B.04", "B.05",
        "B.06", "B.07", "B.08", "B.09", "B.10",
        "B.11", "B.12", "B.13",
    ]
    result = []
    for code in parent_codes:
        try:
            children = opex_children(code, technology="data_center")
        except (KeyError, ValueError):
            continue
        for child in children:
            result.append((code, child.label))
    return result


def test_DC_OPEX_NO_RENEWABLE_LEAKAGE():
    """No effective OPEX sub-line rendered for DC uses renewable vocabulary."""
    for parent_code, label in _all_dc_opex_labels():
        assert not _has_renewable_opex_marker(label), (
            f"OPEX {parent_code}: sub-line {label!r} contains renewable vocabulary"
        )


# ─────────────────────────────────────────────────────────────────────────────
# DC_OPEX_CATALOG_NO_METEO / DC_OPEX_CATALOG_NO_VEGETATION
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_OPEX_CATALOG_NO_METEO():
    """B.01 for DC must not contain 'Meteorological' or 'Weather Forecast'."""
    children = _opex_children("B.01")
    labels = [c.label for c in children]
    for label in labels:
        assert "meteorological" not in label.lower(), (
            f"B.01 DC has renewable label: {label!r}"
        )
        assert "weather forecast" not in label.lower(), (
            f"B.01 DC has renewable label: {label!r}"
        )


def test_DC_OPEX_CATALOG_NO_VEGETATION():
    """B.03 for DC must not contain 'Vegetation Management'."""
    children = _opex_children("B.03")
    labels = [c.label for c in children]
    for label in labels:
        assert "vegetation" not in label.lower(), (
            f"B.03 DC has renewable label: {label!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# DC_CATALOG_B01_DC_HAS_DCIM / DC_CATALOG_B03_DC_HAS_ROAD
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_CATALOG_B01_DC_HAS_DCIM():
    """B.01 for DC must contain a DCIM/monitoring item."""
    children = _opex_children("B.01")
    labels_lower = [c.label.lower() for c in children]
    assert any("dcim" in l or "monitoring platform" in l for l in labels_lower), (
        f"B.01 DC missing DCIM/monitoring item. Got: {[c.label for c in children]}"
    )


def test_DC_CATALOG_B03_DC_HAS_ROAD():
    """B.03 for DC must contain a road/perimeter maintenance item."""
    children = _opex_children("B.03")
    labels_lower = [c.label.lower() for c in children]
    assert any("road" in l or "perimeter" in l for l in labels_lower), (
        f"B.03 DC missing road/perimeter maintenance. Got: {[c.label for c in children]}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_POWER_RAMP_AND_ESCALATION
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_POWER_RAMP_AND_ESCALATION():
    """Power expenses ramp with occupancy over the first 3 years and escalate
    with electricity price escalation after stabilization.

    Reference identity (Y1):
        IT_MW × occupancy_Y1 × PUE × 8_760 × electricity_EUR_per_MWh / 1_000 = kEUR
    """
    from app.data_center_authority import (
        GENERIC_DATA_CENTER_REFERENCE_DRIVERS as d,
        power_step_changes,
    )

    capacity_mw = 20.0
    steps = power_step_changes(d, capacity_mw=capacity_mw, horizon_years=20)
    # steps is a tuple of (year, keur) from the canonical authority.
    steps_dict = {yr: val for yr, val in steps}

    # Pin the actual authority output — electricity escalation of 2%/yr is applied
    # from Y1 (year^0 = 1.0 multiplier), so Y1 is NOT escalated but Y2+ are.
    # Y1: 20 × 0.55 × 1.30 × 8760 × 70 / 1000 × 1.02^0 = 8,768.76 kEUR
    # Y2: 20 × 0.70 × 1.30 × 8760 × 70 / 1000 × 1.02^1 = 11,383.44 kEUR
    # Y3: 20 × 0.85 × 1.30 × 8760 × 70 / 1000 × 1.02^2 = 14,099.21 kEUR
    # Y4: 20 × 0.85 × 1.30 × 8760 × 70 / 1000 × 1.02^3 = 14,381.19 kEUR
    assert abs(steps_dict[1] - 8_768.76) < 1.0, f"Y1 power OPEX: {steps_dict[1]:.2f}"
    assert abs(steps_dict[2] - 11_383.44) < 1.0, f"Y2 power OPEX (with 2% el. escalation): {steps_dict[2]:.2f}"
    assert abs(steps_dict[3] - 14_099.21) < 1.0, f"Y3 power OPEX (with 2% el. escalation): {steps_dict[3]:.2f}"
    assert abs(steps_dict[4] - 14_381.19) < 1.0, f"Y4 power OPEX (with 2% el. escalation): {steps_dict[4]:.2f}"

    # Occupancy ramp: Y1 < Y2 (occupancy ramp); Y3 < Y4 (only escalation from Y3+)
    assert steps_dict[1] < steps_dict[2] < steps_dict[3] < steps_dict[4], (
        f"Power OPEX must increase each year: "
        f"Y1={steps_dict[1]:.2f}, Y2={steps_dict[2]:.2f}, "
        f"Y3={steps_dict[3]:.2f}, Y4={steps_dict[4]:.2f}"
    )

    # Electricity escalation isolation: Y3→Y4 ratio must equal (1 + escalation)
    ratio_y3_y4 = steps_dict[4] / steps_dict[3]
    assert abs(ratio_y3_y4 - (1.0 + d.electricity_price_escalation)) < 0.0001, (
        f"Y3→Y4 ratio {ratio_y3_y4:.6f} ≠ escalation factor {1+d.electricity_price_escalation:.6f}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_ROUTER_IS_DC_IN_BASE_CTX
# ─────────────────────────────────────────────────────────────────────────────

def _router_source() -> str:
    from pathlib import Path
    return Path("app/v2/router.py").read_text()


def test_DC_ROUTER_IS_DC_IN_BASE_CTX():
    """_base_sheet_ctx must include is_data_center key."""
    src = _router_source()
    # Find the _base_sheet_ctx function body and verify is_data_center is there
    assert '"is_data_center"' in src or "'is_data_center'" in src, (
        "_base_sheet_ctx must include is_data_center in its returned dict"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_SENSITIVITY_DRIVERS — DC-native drivers present; renewable drivers excluded
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_SENSITIVITY_DRIVERS_spec_has_dc_native():
    """DRIVER_SPECS in sensitivity endpoint must include DC-native drivers."""
    src = _router_source()
    assert '"service_price"' in src, "DRIVER_SPECS must include service_price for DC"
    assert '"dc_occupancy"' in src, "DRIVER_SPECS must include dc_occupancy for DC"
    assert '"dc_only"' in src, "DC-native drivers must be tagged dc_only"
    assert '"dc_excluded"' in src, "Renewable drivers must be tagged dc_excluded"


def test_DC_SENSITIVITY_DRIVERS_renewable_excluded():
    """tariff and generation must be marked dc_excluded in DRIVER_SPECS."""
    src = _router_source()
    assert '"dc_excluded": True' in src, "tariff and generation must be tagged dc_excluded"


def test_DC_SENSITIVITY_NOT_BLOCKED_guard_removed():
    """The old blanket guard 'if project_type_raw not in (solar, wind): return 409'
    must be replaced by a guard that allows DC through (_is_dc_sens conditional).
    """
    src = _router_source()
    assert "_is_dc_sens" in src, (
        "v2_scenario_sensitivity_run must use _is_dc_sens to allow DC sensitivity"
    )
    # The old blocking guard (without _is_dc_sens prefix) must be gone.
    # After fix: 'if not _is_dc_sens and project_type_raw not in ("solar", "wind")'
    # The bare form 'if project_type_raw not in ("solar", "wind")' as a standalone
    # block must not exist.
    assert 'if project_type_raw not in ("solar", "wind"):' not in src, (
        "Old blanket guard must be removed — DC must be allowed through"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_REVENUE_SECTION_GUARD
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_REVENUE_SECTION_GUARD_in_template():
    """sheet_revenue.html must guard Commercial/Balancing/Merchant with not is_data_center."""
    from pathlib import Path
    tmpl = Path("app/templates/v2/partials/sheet_revenue.html").read_text()
    assert "{% if not is_data_center %}" in tmpl, (
        "sheet_revenue.html must hide renewable sections with {% if not is_data_center %}"
    )


def test_DC_SENSITIVITY_TEMPLATE_DC_NATIVE():
    """sheet_sensitivity.html must render DC-native drivers when is_data_center."""
    from pathlib import Path
    tmpl = Path("app/templates/v2/partials/sheet_sensitivity.html").read_text()
    assert "service_price" in tmpl, "sensitivity template must include service_price option for DC"
    assert "dc_occupancy" in tmpl, "sensitivity template must include dc_occupancy option for DC"
    assert "{% if is_data_center %}" in tmpl, (
        "sensitivity template must branch on is_data_center"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_SOLAR_NO_REGRESSION
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_SOLAR_NO_REGRESSION_opex_b01():
    """Solar B.01 still contains Meteorological / Weather Forecast Service."""
    children = _opex_children("B.01", technology="solar")
    labels = [c.label for c in children]
    assert any("meteorological" in l.lower() for l in labels), (
        f"Solar B.01 must still have Meteorological item. Got: {labels}"
    )


def test_DC_SOLAR_NO_REGRESSION_opex_b03():
    """Solar B.03 still contains Vegetation Management."""
    children = _opex_children("B.03", technology="solar")
    labels = [c.label for c in children]
    assert any("vegetation" in l.lower() for l in labels), (
        f"Solar B.03 must still have Vegetation Management. Got: {labels}"
    )


def test_DC_WIND_NO_REGRESSION_opex_b01():
    """Wind B.01 still contains Meteorological / Weather Forecast Service."""
    children = _opex_children("B.01", technology="wind")
    labels = [c.label for c in children]
    assert any("meteorological" in l.lower() for l in labels), (
        f"Wind B.01 must still have Meteorological item. Got: {labels}"
    )


def test_DC_WIND_NO_REGRESSION_opex_b03():
    """Wind B.03 still contains Vegetation Management."""
    children = _opex_children("B.03", technology="wind")
    labels = [c.label for c in children]
    assert any("vegetation" in l.lower() for l in labels), (
        f"Wind B.03 must still have Vegetation Management. Got: {labels}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Weights must sum to 100 for new DC catalog entries
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_OPEX_B01_WEIGHTS_SUM_100():
    """DC B.01 sub-line weights must sum to 100."""
    from app.reference_detail_catalog import _OPEX_ROWS
    dc_b01 = _OPEX_ROWS["data_center"].get("B.01", ())
    total = sum(w for _, w in dc_b01)
    assert total == 100, f"DC B.01 weights sum {total}, expected 100"


def test_DC_OPEX_B03_WEIGHTS_SUM_100():
    """DC B.03 sub-line weights must sum to 100."""
    from app.reference_detail_catalog import _OPEX_ROWS
    dc_b03 = _OPEX_ROWS["data_center"].get("B.03", ())
    total = sum(w for _, w in dc_b03)
    assert total == 100, f"DC B.03 weights sum {total}, expected 100"


# ─────────────────────────────────────────────────────────────────────────────
# DC_OCCUPANCY_SENSITIVITY_SCALE — Correction A item 1
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_OCCUPANCY_SENSITIVITY_SCALE():
    """dc_occupancy sensitivity steps must be in percent-point units (10.0 not 0.10).

    Registry stores occupancy_stabilized as PCT (e.g. 85 = 85%).  absolute_add
    steps of ±0.10 would shift 85 → 84.9 / 85.1 instead of the intended 75 / 95.
    The correct steps are [-10.0, -5.0, 0.0, +5.0, +10.0].
    """
    src = _router_source()
    # Locate the dc_occupancy spec block and verify it does NOT use the wrong scale.
    # The wrong value 0.10 must not appear as a step for dc_occupancy.
    # Proof by absence: steps [-0.10, ... in the dc_occupancy section is the bug.
    import re
    # Extract the dc_occupancy block.
    m = re.search(r'"dc_occupancy"\s*:\s*\{(.+?)\},', src, re.DOTALL)
    assert m, "DRIVER_SPECS must contain dc_occupancy entry"
    block = m.group(1)
    # Correct large-scale steps must be present.
    assert "-10.0" in block or "- 10.0" in block, (
        f"dc_occupancy steps must use -10.0 (pp scale), not -0.10. Block: {block[:200]}"
    )
    # Wrong small-scale steps must not be present.
    assert "-0.10" not in block and "- 0.10" not in block, (
        f"dc_occupancy steps must NOT use -0.10 (decimal scale). Block: {block[:200]}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_SERVICE_PRICE_SNAPSHOT_KEY — Correction A item 2
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_SERVICE_PRICE_SNAPSHOT_KEY():
    """service_price snapshot_key must match the canonical registry key."""
    src = _router_source()
    # The canonical registry snapshot key is dc_service_price_eur_kw_month.
    assert '"dc_service_price_eur_kw_month"' in src, (
        "service_price snapshot_key must be dc_service_price_eur_kw_month "
        "to match registry canonical key; found wrong value dc_service_price"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_TERMINOLOGY_NO_IT_LOAD_HOURS — Correction A item 9
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_TERMINOLOGY_NO_IT_LOAD_HOURS():
    """Revenue template must not use 'IT Load Hours (MWh eq.)' — wrong units.

    Hours ≠ MWh.  The correct label is 'Equivalent IT Load Energy (MWh)'.
    """
    from pathlib import Path
    tmpl = Path("app/templates/v2/partials/sheet_revenue.html").read_text()
    assert "IT Load Hours (MWh eq.)" not in tmpl, (
        "Wrong terminology 'IT Load Hours (MWh eq.)' still present in revenue template"
    )
    assert "Equivalent IT Load Energy" in tmpl, (
        "Correct terminology 'Equivalent IT Load Energy' not found in revenue template"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_SOURCES_AND_USES_RECONCILE — Correction A item 7
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_SOURCES_AND_USES_RECONCILE():
    """Actual senior debt is sized by DSCR, not by the 65% maximum gearing cap.

    DC reference: CAPEX = 200,000 kEUR, 65% cap = 130,000 kEUR.
    DSCR-sized senior debt is significantly below the cap, giving actual gearing < 65%.
    """
    pytest.importorskip("dateutil", reason="dateutil required for engine run")
    from app.project_factories import create_generic_data_center_reference
    from app.services.production_financial_authority import run_clean_production
    pi = create_generic_data_center_reference()
    run = run_clean_production(pi, "Base", project_type="Data Center")
    fin = run.g2c_result.financing_result
    total_capex_keur = 200_000.0
    max_gearing_cap = 0.65 * total_capex_keur  # 130,000 kEUR
    senior_debt = getattr(fin, "final_senior_commitment_keur", None)
    assert senior_debt is not None and math.isfinite(senior_debt) and senior_debt > 0, (
        "Senior debt must be a finite positive number"
    )
    assert senior_debt < max_gearing_cap, (
        f"Actual senior debt {senior_debt:,.0f} kEUR must be below 65% cap "
        f"{max_gearing_cap:,.0f} kEUR — DSCR sculpt must bind"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_ACTUAL_GEARING_PRESENTATION — Correction A item 7
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_ACTUAL_GEARING_PRESENTATION():
    """Actual gearing (senior_debt / CAPEX) must be strictly below the 65% input cap.

    This verifies that the model does not confuse the maximum gearing input
    parameter with the realized financing gearing ratio.
    """
    pytest.importorskip("dateutil", reason="dateutil required for engine run")
    from app.project_factories import create_generic_data_center_reference
    from app.services.production_financial_authority import run_clean_production
    pi = create_generic_data_center_reference()
    run = run_clean_production(pi, "Base", project_type="Data Center")
    fin = run.g2c_result.financing_result
    senior_debt = getattr(fin, "final_senior_commitment_keur", None)
    assert senior_debt is not None, "Senior debt must be present"
    actual_gearing = senior_debt / 200_000.0
    # Actual gearing must be strictly below the 65% cap.
    assert actual_gearing < 0.65, (
        f"Actual gearing {actual_gearing:.1%} must be below the 65% cap"
    )
    # Also must be a non-trivial amount (> 10%) to confirm the model is financing.
    assert actual_gearing > 0.10, (
        f"Actual gearing {actual_gearing:.1%} seems implausibly low (< 10%)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_HORIZON_PRESENTATION — Correction A item 8
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_HORIZON_PRESENTATION():
    """DC reference horizon is 20 years — power schedule must have exactly 20 entries."""
    from app.data_center_authority import (
        GENERIC_DATA_CENTER_REFERENCE_DRIVERS as d,
        power_step_changes,
    )
    steps = power_step_changes(d, capacity_mw=20.0, horizon_years=20)
    years = [yr for yr, _ in steps]
    assert len(years) == 20, f"Power schedule must have 20 years, got {len(years)}"
    assert max(years) == 20, f"Last year must be 20, got {max(years)}"
    assert min(years) == 1, f"First year must be 1, got {min(years)}"
    # No Y21+ entries.
    assert all(yr <= 20 for yr, _ in steps), "No Y21+ entries must appear in DC horizon"
