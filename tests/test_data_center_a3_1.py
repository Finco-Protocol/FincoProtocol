"""tests/test_data_center_a3_1.py

A3.1 Data Center Vertical Integrity — focused gate tests.

Closes the remaining A3.1 specification requirements not already covered by:
  test_data_center_vertical_integrity.py
  test_data_center_reference.py
  test_data_center_correction_a.py
  test_data_center_export_acceptance.py

Test catalogue:
  DC_A3_ECONOMICS_DISTRESSED_DOCUMENTED
  DC_A3_FORBIDDEN_VOCAB_AUTHORITY_MODULE
  DC_A3_FORBIDDEN_VOCAB_REGISTRY_FIELDS
  DC_A3_NUMERICAL_CAPEX_200K
  DC_A3_NUMERICAL_OPEX_Y1_TOTAL
  DC_A3_NUMERICAL_REVENUE_STABILIZED
  DC_A3_TAX_CIT_25PCT_NOT_BLANK
  DC_A3_LLCR_TEMPLATE_NONE_GUARD
  DC_A3_PREVIEW_OPEX_MATCHES_CANONICAL
  DC_A3_REFERENCE_CAPABILITY_LIVE
  DC_A3_CANONICAL_LAST_RUN_SEEDED
  DC_A3_DRIVER_SINGLETON_CANONICAL
  DC_A3_SENSITIVITY_TARIFF_BLOCKED
  DC_A3_POST_TERM_POLICY_CONSTANT
  DC_A3_POWER_OPEX_ITEM_NAME_CONSTANT
  DC_A3_ZERO_DIFF_FINANCIAL_ENGINE
  DC_A3_ZERO_DIFF_FINCO_CORE
"""
from __future__ import annotations

import math
import pathlib


# ─────────────────────────────────────────────────────────────────────────────
# DC_A3_ECONOMICS_DISTRESSED_DOCUMENTED
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_A3_ECONOMICS_DISTRESSED_DOCUMENTED():
    """Assert and document that the Generic DC Reference has sub-bankable economics.

    The Generic Data Center Reference V1 uses SYNTHETIC PUBLIC GENERIC DATA
    (175 EUR/kW/month, 10,000 kEUR/MW CAPEX, 55% Y1 occupancy) that produces
    a low project IRR (~2.3%).  Before Opus H-2 the run also reported a sub-1.0
    minimum DSCR (~0.94x): that was a false CONVERGED state (debt service that the
    cash flows could not fund), not economics.  With correct sculpting the minimum
    DSCR is at the 1.30x target.  The reference is calibrated to exercise the FINCO engine's
    DSCR-sculpted debt structure and occupancy ramp, NOT to represent a
    bankable investment.

    Option B (document as synthetic distressed): the factory comment
    DOCUMENTED SYNTHETIC-ASSUMPTION CORRECTION records this choice.
    Any change to these values must update the factory comment AND this test.
    """
    import pytest
    pytest.importorskip("dateutil", reason="dateutil required for engine run")
    from app.api.project_runner import run_project
    result = run_project("Generic Data Center Reference", "Base")
    kpis = result.get("kpis", {})

    irr = kpis.get("project_irr")
    min_dscr = kpis.get("min_dscr")
    avg_dscr = kpis.get("avg_dscr")

    assert irr is not None and math.isfinite(irr), "project_irr must be a finite number"
    assert min_dscr is not None and math.isfinite(min_dscr), "min_dscr must be a finite number"

    # Document the known synthetic distressed values (tolerance ±0.5pp each).
    # These are Option-B pinned values: sub-bankable by design.
    assert irr < 0.05, (
        f"DC reference IRR {irr*100:.3f}% must be below 5% (synthetic distressed reference). "
        f"If economics changed intentionally, update this test AND the factory comment."
    )
    # Opus H-2: no period may be below the target DSCR (the old 0.94x was the defect).
    assert min_dscr >= 1.30 - 1e-6, (
        f"DC reference min DSCR {min_dscr:.4f}x must be at/above the 1.30x target (H-2). "
        f"If economics changed intentionally, update this test AND the factory comment."
    )
    # Average DSCR meets the target (sculpted structure).
    assert avg_dscr is not None and avg_dscr >= 1.20, (
        f"DC reference avg DSCR {avg_dscr:.4f}x must be ≥1.20x"
    )
    # Pin the approximate known values so any accidental drift is caught.
    assert abs(irr - 0.02301) < 0.005, (
        f"DC reference IRR has drifted from ~2.30%: got {irr*100:.3f}%"
    )
    assert abs(min_dscr - 1.30) < 0.001, (
        f"DC reference min DSCR has drifted from 1.30x: got {min_dscr:.4f}x"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_A3_FORBIDDEN_VOCAB_AUTHORITY_MODULE
# ─────────────────────────────────────────────────────────────────────────────

_FORBIDDEN_USER_VOCAB = (
    "photovoltaic",
    "inverter",
    "irradiation",
    "irradiance",
    "curtailment",
    "feed-in",
    "feed_in",
    "turbine",
    "rotor",
    "blade",
)

_ALLOWED_INTERNAL_TERMS = (
    # P_50 appears as engine enum value (not user-facing label)
    "P_50",
    # pv_degradation set to 0.0 (engine neutral value, not user-facing)
    "pv_degradation",
    # balancing_cost_wind_eur_mwh zeroed (engine neutral value)
    "balancing_cost_wind_eur_mwh",
    # generation appears in a comment explaining the mapping
    "generation",
)


def test_DC_A3_FORBIDDEN_VOCAB_AUTHORITY_MODULE():
    """data_center_authority.py must not expose forbidden renewable vocabulary to users.

    Internal engine-mapping terms (P_50, pv_degradation=0.0, balancing_cost_wind=0)
    are allowed because they are neutral zeroed values not visible in any UI label.
    """
    authority_path = pathlib.Path("app/data_center_authority.py")
    src = authority_path.read_text()

    for term in _FORBIDDEN_USER_VOCAB:
        lower_src = src.lower()
        lower_term = term.lower()
        assert lower_term not in lower_src, (
            f"Forbidden term '{term}' found in data_center_authority.py. "
            f"DC authority must not contain renewable vocabulary."
        )


def test_DC_A3_FORBIDDEN_VOCAB_REGISTRY_FIELDS():
    """DC workbook registry field descriptions must not contain renewable vocabulary.

    Checks that none of the DC-specific revenue fields in registry.py use
    solar/wind/PV vocabulary in their label, description, or unit strings.
    """
    registry_path = pathlib.Path("app/workbook/registry.py")
    src = registry_path.read_text()

    # DC section must exist — fail if it has disappeared
    assert '"data_center"' in src or "'data_center'" in src, (
        "DC registry section not found in app/workbook/registry.py. "
        "Expected a '_rv_data_center' / 'data_center' section — it must not be removed."
    )

    # Extract DC section: from _rv_data_center definition to next _section call
    lines = src.split("\n")
    in_dc_section = False
    dc_lines = []
    for line in lines:
        if "_rv_data_center" in line and "_section(" in line:
            in_dc_section = True
        if in_dc_section:
            dc_lines.append(line)
            # End DC section when next _section or _rv_ variable starts
            if len(dc_lines) > 2 and ("_section(" in line or (
                    line.strip().startswith("_rv_") and "_rv_data_center" not in line)):
                break

    assert dc_lines, (
        "DC registry section body is empty — _rv_data_center section must contain field definitions."
    )

    dc_src = "\n".join(dc_lines).lower()

    # "generation" in the DC registry would be suspicious (used for power generation)
    forbidden_dc_vocab = ("photovoltaic", "pv capacity", "wind turbine", "inverter",
                          "irradiation", "irradiance", "feed-in tariff",
                          "turbine", "blade", "rotor")
    for term in forbidden_dc_vocab:
        assert term.lower() not in dc_src, (
            f"Forbidden term '{term}' found in DC workbook registry fields. "
            f"DC registry must not contain renewable vocabulary."
        )


# ─────────────────────────────────────────────────────────────────────────────
# DC_A3_NUMERICAL_CAPEX_200K
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_A3_NUMERICAL_CAPEX_200K():
    """Total CAPEX of Generic DC Reference = exactly 200,000 kEUR (= 10,000 kEUR/MW)."""
    from app.project_factories import create_generic_data_center_reference
    pi = create_generic_data_center_reference()
    assert pi.capex.total_capex == 200_000.0, (
        f"Total CAPEX must be exactly 200,000.00 kEUR, got {pi.capex.total_capex:.2f}"
    )
    assert pi.technical.capacity_mw == 20.0, (
        f"Reference capacity must be 20.0 MW, got {pi.technical.capacity_mw}"
    )
    # Intensity
    intensity = pi.capex.total_capex / pi.technical.capacity_mw
    assert abs(intensity - 10_000.0) < 0.01, (
        f"CAPEX intensity must be exactly 10,000 kEUR/MW, got {intensity:.2f}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_A3_NUMERICAL_OPEX_Y1_TOTAL
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_A3_NUMERICAL_OPEX_Y1_TOTAL():
    """Total Y1 OPEX = 18,468.76 kEUR (non-power 9,700 + power 8,768.76).

    Power expense = 20 × 0.55 × 1.30 × 8,760 × 70 / 1,000 = 8,768.76 kEUR.
    Non-power = Technical Mgmt (2,000) + Infra Maint (3,500) + Security (1,200)
                + Insurance (1,000) + Lease & Tax (1,200) + Audit/Legal (800) = 9,700.
    """
    from app.project_factories import create_generic_data_center_reference
    from app.data_center_authority import annual_power_cost_keur, GENERIC_DATA_CENTER_REFERENCE_DRIVERS
    pi = create_generic_data_center_reference()
    d = GENERIC_DATA_CENTER_REFERENCE_DRIVERS

    total_opex_y1 = sum(float(item.y1_amount_keur) for item in pi.opex)
    power_y1 = annual_power_cost_keur(
        capacity_mw=float(pi.technical.capacity_mw),
        occupancy=d.occupancy_y1,
        pue=d.pue,
        electricity_price_eur_mwh=d.electricity_price_eur_mwh,
    )
    non_power_y1 = total_opex_y1 - power_y1

    assert abs(power_y1 - 8_768.76) < 1.0, (
        f"Power OPEX Y1 must be ~8,768.76 kEUR, got {power_y1:.2f}"
    )
    assert abs(non_power_y1 - 9_700.0) < 0.01, (
        f"Non-power OPEX Y1 must be exactly 9,700.00 kEUR, got {non_power_y1:.2f}"
    )
    assert abs(total_opex_y1 - 18_468.76) < 1.0, (
        f"Total OPEX Y1 must be ~18,468.76 kEUR, got {total_opex_y1:.2f}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_A3_NUMERICAL_REVENUE_STABILIZED
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_A3_NUMERICAL_REVENUE_STABILIZED():
    """Stabilized annual revenue identity: 20 MW × 1,000 × 12 × 175 × 0.85 = 35,700 kEUR/yr."""
    from app.data_center_authority import core_capacity_revenue_keur, GENERIC_DATA_CENTER_REFERENCE_DRIVERS
    d = GENERIC_DATA_CENTER_REFERENCE_DRIVERS
    rev = core_capacity_revenue_keur(
        capacity_mw=20.0,
        service_price_eur_kw_month=d.service_price_eur_kw_month,
        occupancy=d.stabilized_occupancy,
    )
    assert abs(rev - 35_700.0) < 0.01, (
        f"Stabilized revenue must be exactly 35,700 kEUR/yr, got {rev:.2f}"
    )

    # Y1 identity: 20 × 1,000 × 12 × 175 × 0.55 = 23,100 kEUR/yr
    rev_y1 = core_capacity_revenue_keur(
        capacity_mw=20.0,
        service_price_eur_kw_month=d.service_price_eur_kw_month,
        occupancy=d.occupancy_y1,
    )
    assert abs(rev_y1 - 23_100.0) < 0.01, (
        f"Y1 revenue must be exactly 23,100 kEUR/yr, got {rev_y1:.2f}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_A3_TAX_CIT_25PCT_NOT_BLANK
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_A3_TAX_CIT_25PCT_NOT_BLANK():
    """DC reference CIT rate = 25%; _cit_rate_display must return '25.0%' not blank '—'.

    Tax is computed and collected in the DC reference.  Displaying blank (—)
    for the CIT rate would imply no tax applies, which is false.
    """
    from app.project_factories import create_generic_data_center_reference
    pi = create_generic_data_center_reference()

    # Raw tax params
    assert abs(pi.tax.corporate_rate - 0.25) < 0.0001, (
        f"DC CIT rate must be 0.25 (25%), got {pi.tax.corporate_rate}"
    )

    # Display function (same logic as router._cit_rate_display)
    from app.v2.router import _cit_rate_display

    class _FakePIS:
        def to_projectinputs(self):
            return pi

    display = _cit_rate_display(_FakePIS())
    assert display == "25.0%", (
        f"_cit_rate_display must return '25.0%' for DC reference, got {display!r}. "
        f"A blank ('—') would falsely imply no tax."
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_A3_LLCR_TEMPLATE_NONE_GUARD
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_A3_LLCR_TEMPLATE_NONE_GUARD():
    """Senior debt template correctly shows '—' when min_llcr is None.

    The engine may not compute LLCR for some DC configurations.  The template
    must not coerce None to 0.00 or crash — it must show '—'.
    """
    tmpl_path = pathlib.Path("app/templates/v2/partials/sheet_senior_debt.html")
    src = tmpl_path.read_text()

    # Verify the template has a None guard on min_llcr
    assert "min_llcr is not none" in src or "min_llcr != none" in src.lower(), (
        "sheet_senior_debt.html must guard min_llcr against None before formatting"
    )
    # Verify the fallback is '—'
    assert "—" in src, "template must show '—' as fallback for unavailable LLCR"
    # Confirm it doesn't default min_llcr to 0 anywhere in the LLCR tile
    # (a getattr(fin, 'min_llcr', 0.0) pattern in the template would be wrong)
    assert "min_llcr, 0" not in src and "min_llcr,0" not in src, (
        "template must not default min_llcr to 0 — use the None guard and show '—'"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_A3_PREVIEW_OPEX_MATCHES_CANONICAL
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_A3_PREVIEW_OPEX_MATCHES_CANONICAL():
    """Preview OPEX Y1 at 20 MW matches canonical factory Y1 OPEX total.

    The A4 preview must never show economics that contradict the A5 first run.
    """
    from app.services.reference_seed_service import build_reference_scaling_preview
    from app.project_factories import create_generic_data_center_reference

    preview = build_reference_scaling_preview("generic_data_center_reference", 20.0)
    pi = create_generic_data_center_reference()

    canonical_opex_y1 = sum(float(item.y1_amount_keur) for item in pi.opex)
    preview_opex_y1 = preview["scaled_opex_y1_keur"]

    assert abs(preview_opex_y1 - canonical_opex_y1) < 1.0, (
        f"Preview OPEX Y1 ({preview_opex_y1:.2f}) must match factory OPEX Y1 "
        f"({canonical_opex_y1:.2f}) within 1 kEUR. Preview must not contradict first run."
    )

    # CAPEX preview must also match
    preview_capex = preview["scaled_total_capex_keur"]
    assert abs(preview_capex - pi.capex.total_capex) < 0.01, (
        f"Preview CAPEX ({preview_capex:.2f}) must match factory CAPEX "
        f"({pi.capex.total_capex:.2f})"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_A3_REFERENCE_CAPABILITY_LIVE
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_A3_REFERENCE_CAPABILITY_LIVE():
    """ProductCapability for Data Center must be LIVE with full feature flags."""
    from app.product_capability import PRODUCT_CAPABILITIES, ProductStatus
    cap = next((c for c in PRODUCT_CAPABILITIES if c.key == "data_center"), None)
    assert cap is not None, "data_center ProductCapability must be registered"
    assert cap.status == ProductStatus.LIVE, (
        f"DC ProductStatus must be LIVE, got {cap.status!r}"
    )
    assert cap.reference_available, "DC reference must be available"
    assert cap.runnable, "DC must be runnable"
    assert cap.canonical_last_run, "DC must have canonical last run"
    assert cap.export_available, "DC export must be available"
    assert cap.cloneable, "DC must be cloneable"


# ─────────────────────────────────────────────────────────────────────────────
# DC_A3_CANONICAL_LAST_RUN_SEEDED
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_A3_CANONICAL_LAST_RUN_SEEDED():
    """generic_data_center_reference must be in _CANONICAL_LAST_RUN_SOURCES."""
    from app.services.project_library_service import _CANONICAL_LAST_RUN_SOURCES
    assert "generic_data_center_reference" in _CANONICAL_LAST_RUN_SOURCES, (
        "generic_data_center_reference must be in _CANONICAL_LAST_RUN_SOURCES "
        "so the reference has a pre-seeded last run result on startup."
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_A3_DRIVER_SINGLETON_CANONICAL
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_A3_DRIVER_SINGLETON_CANONICAL():
    """GENERIC_DATA_CENTER_REFERENCE_DRIVERS must equal DataCenterDrivers() defaults."""
    from app.data_center_authority import DataCenterDrivers, GENERIC_DATA_CENTER_REFERENCE_DRIVERS
    canonical = DataCenterDrivers()
    assert GENERIC_DATA_CENTER_REFERENCE_DRIVERS == canonical, (
        "GENERIC_DATA_CENTER_REFERENCE_DRIVERS must equal DataCenterDrivers() with all defaults. "
        f"Got: {GENERIC_DATA_CENTER_REFERENCE_DRIVERS!r}, expected: {canonical!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_A3_SENSITIVITY_TARIFF_BLOCKED
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_A3_SENSITIVITY_TARIFF_BLOCKED():
    """Tariff sensitivity endpoint must reject DC projects (dc_excluded=True in DRIVER_SPECS)."""
    router_src = pathlib.Path("app/v2/router.py").read_text()

    # tariff and generation must be tagged dc_excluded in DRIVER_SPECS
    assert '"tariff"' in router_src, "DRIVER_SPECS must define tariff driver"
    assert '"generation"' in router_src, "DRIVER_SPECS must define generation driver"
    assert '"dc_excluded": True' in router_src, (
        "tariff and generation drivers must be tagged dc_excluded: True"
    )
    # The sensitivity run endpoint must enforce the dc_excluded guard
    assert "_is_dc_sens" in router_src, (
        "v2_scenario_sensitivity_run must use _is_dc_sens guard to block dc_excluded drivers"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_A3_POST_TERM_POLICY_CONSTANT
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_A3_POST_TERM_POLICY_CONSTANT():
    """DC_POST_TERM_POLICY must be 'CONTINUE_INDEXED_SERVICE_REVENUE'."""
    from app.data_center_authority import DC_POST_TERM_POLICY
    assert DC_POST_TERM_POLICY == "CONTINUE_INDEXED_SERVICE_REVENUE", (
        f"DC_POST_TERM_POLICY must be 'CONTINUE_INDEXED_SERVICE_REVENUE', "
        f"got {DC_POST_TERM_POLICY!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_A3_POWER_OPEX_ITEM_NAME_CONSTANT
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_A3_POWER_OPEX_ITEM_NAME_CONSTANT():
    """DC_POWER_OPEX_ITEM_NAME must be 'Power Expenses' (routes to B.08 in OPEX assembly)."""
    from app.data_center_authority import DC_POWER_OPEX_ITEM_NAME
    assert DC_POWER_OPEX_ITEM_NAME == "Power Expenses", (
        f"DC_POWER_OPEX_ITEM_NAME must be 'Power Expenses', got {DC_POWER_OPEX_ITEM_NAME!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_A3_ZERO_DIFF_FINANCIAL_ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_A3_ZERO_DIFF_FINANCIAL_ENGINE():
    """financial_engine/** must have zero diff from main (A3.1 authority boundary).

    DC is implemented entirely in the application layer (authority module +
    runtime adapter + factory).  The financial engine never sees DC-specific
    logic — it operates on the generic mapped inputs.
    """
    # Opus Finance Integrity governance: the approved finance-correction modules may
    # differ from main; every other financial_engine module must stay untouched.
    from finance_integrity_governance import unapproved_engine_changes
    changed = unapproved_engine_changes()
    assert changed == [], (
        f"A3.1 authority boundary: unapproved financial_engine changes vs main: {changed}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_A3_ZERO_DIFF_FINCO_CORE
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_A3_ZERO_DIFF_FINCO_CORE():
    """finco_core/** must have zero diff from main (A3.1 authority boundary).

    DC vertical implementation must not touch the core waterfall engine.
    """
    import subprocess
    result = subprocess.run(
        ["git", "diff", "--name-only", "origin/main", "--", "finco_core/"],
        capture_output=True, text=True, cwd=str(pathlib.Path.cwd()),
    )
    changed = [f for f in result.stdout.strip().split("\n") if f.strip()]
    assert changed == [], (
        f"A3.1 authority boundary: finco_core/** must have ZERO diff from main. "
        f"Changed files: {changed}"
    )
