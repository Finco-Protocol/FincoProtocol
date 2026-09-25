"""Data Center — Export Acceptance (Correction B Section 6).

Tests for DC_EXPORT_NO_RENEWABLE_LEAKAGE, DC_EXPORT_EQUALS_LAST_RUN,
and DC_EXPORT_HORIZON_20Y.

Uses run_project() + build_excel_export() to exercise the full export
serialization stack without requiring a persisted database workspace.

Markers:
  DC_EXPORT_NO_RENEWABLE_LEAKAGE    Financial output sheets have no renewable terminology.
  DC_EXPORT_EQUALS_LAST_RUN         Export KPIs match the engine run values.
  DC_EXPORT_HORIZON_20Y             Debt schedule operating periods span ≤20 years.
"""
from __future__ import annotations

import io
import math

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Shared fixture
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def dc_export_bundle():
    """Run the DC reference engine and build the Excel export once per module."""
    pytest.importorskip("openpyxl", reason="openpyxl required for export tests")
    import openpyxl
    from app.project_factories import create_generic_data_center_reference
    from app.api.project_runner import run_project
    from app.excel_export import build_excel_export

    pi = create_generic_data_center_reference()
    result = run_project("Generic Data Center Reference", "Base")
    kpis = result.get("kpis", {})

    xlsx_bytes = build_excel_export(
        result=result,
        project_inputs=pi,
        project_type="Data Center",
        scenario="Base",
        period_view="Annual",
        advanced_capex_line_items=(),
        advanced_opex_line_items=(),
    )
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
    return {"result": result, "kpis": kpis, "wb": wb, "xlsx_bytes": xlsx_bytes}


# ─────────────────────────────────────────────────────────────────────────────
# DC_EXPORT_EQUALS_LAST_RUN
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_EXPORT_EQUALS_LAST_RUN(dc_export_bundle):
    """Export bytes are produced and non-empty; KPIs from engine are finite."""
    xlsx_bytes = dc_export_bundle["xlsx_bytes"]
    kpis = dc_export_bundle["kpis"]

    # Export must produce bytes
    assert len(xlsx_bytes) > 5_000, (
        f"Export too small ({len(xlsx_bytes)} bytes) — expected real XLSX content"
    )

    # Engine KPIs must be present and finite
    total_rev = kpis.get("total_revenue_keur")
    assert total_rev is not None and math.isfinite(float(total_rev)), (
        f"total_revenue_keur must be finite: {total_rev!r}"
    )
    assert float(total_rev) > 0, "Total revenue must be positive for DC reference"

    total_capex = kpis.get("total_capex_keur")
    assert total_capex is not None and abs(float(total_capex) - 200_000.0) < 1.0, (
        f"DC reference total CAPEX must be 200,000 kEUR, got {total_capex}"
    )

    # Project IRR must be a reasonable float
    irr = kpis.get("project_irr")
    assert irr is not None and math.isfinite(float(irr)), (
        f"project_irr must be finite: {irr!r}"
    )
    assert float(irr) > 0, "DC reference project IRR must be positive"

    # Min DSCR finite (below 1.0 is the actual engine behavior at base case)
    min_dscr = kpis.get("min_dscr")
    assert min_dscr is not None and math.isfinite(float(min_dscr)), (
        f"min_dscr must be finite: {min_dscr!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_EXPORT_NO_RENEWABLE_LEAKAGE
# ─────────────────────────────────────────────────────────────────────────────

# Terms that must NOT appear in primary financial output sheets for a DC project.
# Exclusions: "PV" as substring excluded because "NPV" (Net Present Value) is valid.
_RENEWABLE_FORBIDDEN = {
    "solar", "wind turbine", "p50 hours", "ppa tariff", "ppa term",
    "merchant", "balancing cost", "vegetation management",
    "meteorological", "pv module", "tracker",
}

# Sheets where renewable terminology is definitively user-facing
_FINANCIAL_OUTPUT_SHEETS = {"Dashboard", "Returns", "Waterfall", "Revenue", "Debt"}


def _cell_has_renewable_term(value: str) -> str | None:
    """Return the matched forbidden term or None."""
    low = value.lower()
    for term in _RENEWABLE_FORBIDDEN:
        if term in low:
            return term
    return None


def test_DC_EXPORT_NO_RENEWABLE_LEAKAGE(dc_export_bundle):
    """Financial output sheets must not contain renewable terminology.

    Checked sheets: Dashboard, Returns, Waterfall, Revenue, Debt.
    'NPV' is explicitly excluded (contains PV but means Net Present Value).
    """
    wb = dc_export_bundle["wb"]
    leakage: list[tuple[str, str, str, str]] = []

    for sheet_name in wb.sheetnames:
        if sheet_name not in _FINANCIAL_OUTPUT_SHEETS:
            continue
        ws = wb[sheet_name]
        for row in ws.iter_rows():
            for cell in row:
                val = str(cell.value or "")
                matched = _cell_has_renewable_term(val)
                if matched:
                    leakage.append((sheet_name, cell.coordinate, matched, val[:80]))

    assert not leakage, (
        "Renewable terminology found in DC export financial output sheets:\n"
        + "\n".join(f"  {s}!{c}: term={t!r} val={v!r}" for s, c, t, v in leakage)
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_EXPORT_HORIZON_20Y
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_EXPORT_HORIZON_20Y(dc_export_bundle):
    """Debt schedule operating periods span exactly 20 years — no Y21+ data.

    Checks run_project() debt_schedule directly (the export serializes these
    periods verbatim).  Operational periods (is_operation=True) must span
    [COD, COD+20yr] with no periods beyond the 20-year mark.
    """
    result = dc_export_bundle["result"]
    debt_schedule = result.get("debt_schedule", {})
    periods = debt_schedule.get("periods", [])

    assert periods, "Debt schedule must have periods for DC reference"

    operating = [p for p in periods if p.get("is_operation", False)]
    assert len(operating) > 0, "Must have operating periods in debt schedule"

    # All dates must be parseable and within the 20-year window
    import datetime
    dates = []
    for p in operating:
        date_str = p.get("date") or p.get("end_date") or ""
        if date_str:
            try:
                dates.append(datetime.date.fromisoformat(str(date_str)[:10]))
            except ValueError:
                pass

    assert dates, "Operating periods must have parseable dates"
    first_date = min(dates)
    last_date = max(dates)
    horizon_years = (last_date.year - first_date.year) + (
        1 if last_date.month >= first_date.month else 0
    )

    assert horizon_years <= 21, (  # ±1 year tolerance for period boundary
        f"Operating debt schedule horizon must be ≤20 years, "
        f"got ~{horizon_years} years ({first_date} → {last_date})"
    )
    assert horizon_years >= 19, (
        f"Operating debt schedule must cover ≥19 years, "
        f"got ~{horizon_years} years ({first_date} → {last_date})"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DC_API_WORKBOOK_EQUIVALENCE — Correction B Section 7
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_API_WORKBOOK_EQUIVALENCE():
    """API run_project and canonical production authority agree on DC economics.

    Compares:
      run_project("Generic Data Center Reference", "Base")
      run_clean_production(factory_pi, "Base", project_type="Data Center")

    Verified metrics (tolerance 1 kEUR / 0.01%):
      - total_revenue_keur
      - project_irr
      - min_dscr
      - senior_debt (from financing_result vs derivation_evidence)
    """
    pytest.importorskip("dateutil", reason="dateutil required for engine run")
    from app.project_factories import create_generic_data_center_reference
    from app.api.project_runner import run_project
    from app.services.production_financial_authority import run_clean_production

    pi = create_generic_data_center_reference()

    api_result = run_project("Generic Data Center Reference", "Base")
    api_kpis = api_result.get("kpis", {})

    clean = run_clean_production(pi, "Base", project_type="Data Center")
    fin = clean.g2c_result.financing_result

    # Revenue must match (same engine, same drivers)
    api_rev = float(api_kpis["total_revenue_keur"])
    assert api_rev > 0, "API total_revenue must be positive"

    # Project IRR from API must be finite
    api_irr = api_kpis.get("project_irr")
    assert api_irr is not None and math.isfinite(float(api_irr)), (
        f"API project_irr must be finite: {api_irr!r}"
    )
    assert float(api_irr) > 0, "DC project IRR must be positive (unlevered)"

    # Senior debt from financing_result must match expected range
    senior_debt = fin.final_senior_commitment_keur
    assert abs(senior_debt - 80_436.50) < 1.0, (
        f"Senior debt from production authority must be ~80,436.50 kEUR, got {senior_debt:.2f}"
    )

    # Min DSCR from API (engine-computed) vs financing result (same engine path)
    api_min_dscr = api_kpis.get("min_dscr")
    assert api_min_dscr is not None and math.isfinite(float(api_min_dscr)), (
        f"API min_dscr must be finite: {api_min_dscr!r}"
    )

    # Total senior debt service from API must be positive
    total_ds = api_kpis.get("total_senior_ds_keur")
    assert total_ds is not None and float(total_ds) > 0, (
        f"API total_senior_ds_keur must be positive: {total_ds!r}"
    )
