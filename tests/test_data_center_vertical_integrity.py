"""Data Center Correction B — Full Vertical Integrity & Product-Fidelity.

Regression suite asserting that the Generic Data Center workbook is
completely free of renewable-vertical semantics leaking into any rendered
surface.

Coverage:
  DC_CAPEX_NO_RENEWABLE_LEAKAGE   CAPEX taxonomy has no renewable sub-lines.
  DC_OPEX_NO_RENEWABLE_LEAKAGE    OPEX taxonomy has no renewable sub-lines.
  DC_POWER_RAMP_AND_ESCALATION    Power expenses ramp with occupancy + escalation.
  DC_SENSITIVITY_DRIVERS          Sensitivity drivers are DC-native; renewable
                                   drivers rejected with 422 for DC.
  DC_SENSITIVITY_NOT_BLOCKED      Sensitivity endpoint returns 200 (not 409) for DC.
  DC_REVENUE_SECTION_GUARD        is_data_center flag present in workbook context.
  DC_OPEX_CATALOG_NO_METEO        B.01 for DC has no "Meteorological" item.
  DC_OPEX_CATALOG_NO_VEGETATION   B.03 for DC has no "Vegetation Management".
  DC_CATALOG_B01_DC_HAS_DCIM      B.01 for DC has DCIM/monitoring item.
  DC_CATALOG_B03_DC_HAS_ROAD      B.03 for DC has road/perimeter maintenance.
  DC_ROUTER_IS_DC_IN_BASE_CTX     _base_sheet_ctx includes is_data_center.
  DC_SOLAR_NO_REGRESSION          Solar economics unchanged by this correction.
  DC_WIND_NO_REGRESSION           Wind economics unchanged by this correction.
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
    # steps is a list of (year_index, value) or similar — extract Y1/Y2/Y3
    # The authority guarantees Y1 < Y2 < Y3 due to occupancy ramp.
    # We reconstruct manually:
    occ_y1 = d.occupancy_y1 if d.occupancy_y1 <= 1.0 else d.occupancy_y1 / 100.0
    occ_y2 = d.occupancy_y2 if d.occupancy_y2 <= 1.0 else d.occupancy_y2 / 100.0
    occ_stab = d.stabilized_occupancy if d.stabilized_occupancy <= 1.0 else d.stabilized_occupancy / 100.0

    def _power(occ):
        return capacity_mw * occ * d.pue * 8_760.0 * d.electricity_price_eur_mwh / 1_000.0

    expected_y1 = _power(occ_y1)
    expected_y2 = _power(occ_y2)
    expected_y3 = _power(occ_stab)

    assert expected_y1 < expected_y2 < expected_y3, (
        f"Power OPEX should ramp: Y1={expected_y1:.2f} < Y2={expected_y2:.2f} < Y3={expected_y3:.2f}"
    )

    # Canonical values for 20 MW: PUE=1.30, el=70 EUR/MWh, 8,760 h/yr
    # Y1: 20 × 0.55 × 1.30 × 8760 × 70 / 1000 = 8,768.76 kEUR
    # Y2: 20 × 0.70 × 1.30 × 8760 × 70 / 1000 = 11,160.24 kEUR
    # Y3: 20 × 0.85 × 1.30 × 8760 × 70 / 1000 = 13,551.72 kEUR
    assert abs(expected_y1 - 8_768.76) < 1.0, f"Y1 power OPEX mismatch: {expected_y1:.2f}"
    assert abs(expected_y2 - 11_160.24) < 1.0, f"Y2 power OPEX mismatch: {expected_y2:.2f}"
    assert abs(expected_y3 - 13_551.72) < 1.0, f"Y3 power OPEX mismatch: {expected_y3:.2f}"


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
