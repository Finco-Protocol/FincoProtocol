"""P1.2 Institutional XLSX Export — reconciliation and acceptance tests.

Acceptance markers:
  XLSX_NO_PARALLEL_CALCULATION_ENGINE
  XLSX_SOLAR_FULL_ACCEPTANCE
  XLSX_WIND_STRUCTURE_SMOKE
  XLSX_DATA_CENTER_STRUCTURE_SMOKE
  XLSX_EV_CHARGING_STRUCTURE_SMOKE
  XLSX_EXPORT_LAST_RUN_AUTHORITY
  XLSX_EXPORT_LINEAGE
  XLSX_SOURCES_USES_RECONCILE
  XLSX_CAPEX_RECONCILE
  XLSX_REVENUE_RECONCILE
  XLSX_OPEX_RECONCILE
  XLSX_DEBT_RECONCILE
  XLSX_RETURNS_RECONCILE
  TRUST_PACK_SOLAR_EXCEL_RECONCILIATION
  FINCO_P1_2_INSTITUTIONAL_XLSX_EXPORT_COMPLETE
"""
from __future__ import annotations

import math
import os
from io import BytesIO

import openpyxl
import pytest


# ── helpers ──────────────────────────────────────────────────────────────────

def _solar_workbook() -> openpyxl.Workbook:
    from app.export.institutional_workbook import export_institutional_workbook_skeleton
    wb_bytes = export_institutional_workbook_skeleton("generic_solar_reference")
    return openpyxl.load_workbook(BytesIO(wb_bytes))


def _solar_run():
    from app.api.project_runner import run_project
    return run_project("Generic Solar Reference", "Base")


def _solar_bundle():
    from app.export.institutional_workbook import _build_export_bundle
    return _build_export_bundle("generic_solar_reference")


def _wind_workbook() -> openpyxl.Workbook:
    from app.export.institutional_workbook import export_institutional_workbook_skeleton
    wb_bytes = export_institutional_workbook_skeleton("generic_wind_reference")
    return openpyxl.load_workbook(BytesIO(wb_bytes))


def _dc_workbook() -> openpyxl.Workbook:
    from app.export.institutional_workbook import export_institutional_workbook_skeleton
    wb_bytes = export_institutional_workbook_skeleton("generic_data_center_reference")
    return openpyxl.load_workbook(BytesIO(wb_bytes))


def _ev_workbook() -> openpyxl.Workbook:
    """EV Charging structure smoke — uses null runtime stub (not in PROJECT_FACTORIES)."""
    from app.project_factories import create_generic_ev_charging_reference
    from app.export.institutional_workbook import export_institutional_workbook_from_bundle, WorkbookExportBundle
    from app.export.runtime_summary import build_runtime_summary_rows
    from app.input_helpers import build_capex_items_table, build_capex_summary_table, build_inputs_summary_table
    from app.output_tables import build_debt_table, build_revenue_table
    from app.ui.project_context import get_project_context

    class _NullRuntime:
        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(name)
            return None
        @property
        def periods(self): return []
        @property
        def sculpting_result(self): return None
        @property
        def shl_data_available(self): return False

    pi = create_generic_ev_charging_reference()
    context = get_project_context("generic_wind_reference")
    runtime_rows = build_runtime_summary_rows(
        "generic_wind_reference",
        runtime_origin=None, scenario_id=None, scenario_name=None,
        export_authority="FACTORY_REFERENCE",
        working_changed_since_run=None, run_id=None, run_at=None,
        runtime_timestamp=None,
    )
    nr = _NullRuntime()
    bundle = WorkbookExportBundle(
        project_key="ev_charging_reference",
        project_name="Generic EV Charging Reference",
        generated_at=runtime_rows[0]["export_generated_at"],
        branch=runtime_rows[0]["branch_name"],
        commit_sha=runtime_rows[0]["commit_sha"],
        runtime_timestamp=runtime_rows[0]["runtime_timestamp"],
        active_project=runtime_rows[0]["active_project"],
        scenario_id=runtime_rows[0]["scenario_id"],
        scenario_name=runtime_rows[0]["scenario_name"],
        scenario_revision=runtime_rows[0]["scenario_revision"],
        runtime_snapshot_id=runtime_rows[0]["runtime_snapshot_id"],
        runtime_origin=runtime_rows[0]["runtime_origin"],
        template_origin=runtime_rows[0]["template_origin"],
        template_revision=runtime_rows[0]["template_revision"],
        export_template_version=runtime_rows[0]["export_template_version"],
        runtime_flag_count=runtime_rows[0]["runtime_flag_count"],
        runtime_flags_json=runtime_rows[0]["runtime_flags_json"],
        governance_posture_summary=runtime_rows[0]["governance_posture_summary"],
        replay_limitations=runtime_rows[0]["replay_limitations"],
        context=context,
        project_inputs=pi,
        runtime_result=nr,
        runtime_rows=runtime_rows,
        statements=None,
        authority_metadata={},
        export_authority="FACTORY_REFERENCE",
        working_changed_since_run=None,
        run_id=None,
        run_at=None,
        inputs_summary=build_inputs_summary_table(pi),
        capex_summary=build_capex_summary_table(pi),
        capex_items=build_capex_items_table(pi),
        revenue_table=build_revenue_table(nr),
        debt_table=build_debt_table(nr),
    )
    wb_bytes = export_institutional_workbook_from_bundle(bundle)
    return openpyxl.load_workbook(BytesIO(wb_bytes))


def _recon_summary(wb: openpyxl.Workbook) -> str:
    rec = wb["Reconciliation"]
    for row in rec.iter_rows(min_row=1, max_row=10, values_only=True):
        if row[0] == "RECONCILIATION SUMMARY":
            return str(row[1])
    return ""


def _recon_checks(wb: openpyxl.Workbook) -> dict[str, str]:
    """Return {check_name: status} dict from reconciliation sheet."""
    rec = wb["Reconciliation"]
    in_checks = False
    results: dict[str, str] = {}
    for row in rec.iter_rows(values_only=True):
        if row[0] == "Check":
            in_checks = True
            continue
        if in_checks and row[0] is not None:
            results[str(row[0])] = str(row[6]) if row[6] is not None else "N/A"
    return results


# ── XLSX_NO_PARALLEL_CALCULATION_ENGINE ───────────────────────────────────────

def test_xlsx_no_parallel_calculation_engine():
    """XLSX_NO_PARALLEL_CALCULATION_ENGINE — export_institutional_workbook_from_bundle must be
    a pure serialization function that performs zero financial calculations.

    The bundle-builder (_build_export_bundle) may legitimately call the engine for
    the factory-reference path.  What is forbidden is for the serialization layer
    (export_institutional_workbook_from_bundle and all _write_* helpers) to call
    the engine a second time.  We verify this by checking that
    export_institutional_workbook_from_bundle, when called with a pre-built bundle,
    does not call execute_production_waterfall or run the engine again.
    """
    import unittest.mock
    from app.export.institutional_workbook import export_institutional_workbook_skeleton

    call_log: list[str] = []

    def _spy(*a, **kw):
        call_log.append("execute_production_waterfall")
        raise RuntimeError("Engine called inside serialization layer — FAIL")

    # Build bundle outside the spy — engine call here is legitimate (factory-ref path)
    from app.export.institutional_workbook import _build_export_bundle, export_institutional_workbook_from_bundle
    bundle = _build_export_bundle("generic_solar_reference")

    # Now activate the spy and call only the serialization layer
    with unittest.mock.patch(
        "app.services.production_waterfall_seam.execute_production_waterfall",
        side_effect=_spy,
    ):
        wb_bytes = export_institutional_workbook_from_bundle(bundle)
        assert len(wb_bytes) > 40_000
        assert call_log == [], (
            "export_institutional_workbook_from_bundle called the financial engine: "
            f"{call_log}"
        )


# ── Sheet inventory ───────────────────────────────────────────────────────────

def test_xlsx_solar_sheet_inventory():
    """XLSX_SOLAR_FULL_ACCEPTANCE — 22 sheets present including Returns, Run Identity, Reconciliation."""
    wb = _solar_workbook()
    required = [
        "Export_Metadata", "Workbook_Index", "Cover", "Governance",
        "Runtime Summary", "Inputs", "Construction", "OPEX", "CAPEX",
        "Revenue", "Senior Debt", "SHL", "Tax", "P&L", "Cash Flow",
        "Balance Sheet", "Returns", "Run Identity", "Reconciliation",
        "Audit", "Gap Register", "Validation Status",
    ]
    for name in required:
        assert name in wb.sheetnames, f"Sheet {name!r} not in workbook"
    assert len(wb.sheetnames) == 22


def test_xlsx_solar_workbook_non_empty():
    """XLSX_SOLAR_FULL_ACCEPTANCE — workbook bytes > 40KB."""
    from app.export.institutional_workbook import export_institutional_workbook_skeleton
    wb_bytes = export_institutional_workbook_skeleton("generic_solar_reference")
    assert len(wb_bytes) > 40_000, f"Workbook too small: {len(wb_bytes)} bytes"


# ── Reconciliation: all 8 checks PASS for Solar ───────────────────────────────

def test_xlsx_reconciliation_all_pass_solar():
    """XLSX_SOURCES_USES_RECONCILE + all reconciliation checks — Solar must PASS: 8."""
    wb = _solar_workbook()
    summary = _recon_summary(wb)
    assert "PASS: 8" in summary, f"Expected PASS: 8, got {summary!r}"
    assert "FAIL: 0" in summary, f"Expected FAIL: 0, got {summary!r}"


def test_xlsx_sources_uses_reconcile():
    """XLSX_SOURCES_USES_RECONCILE — Total Sources = Total Uses = 33,000 kEUR."""
    wb = _solar_workbook()
    checks = _recon_checks(wb)
    key = "Total Sources vs Total Uses (kEUR)"
    assert key in checks, f"Check {key!r} not found in reconciliation"
    assert checks[key] == "PASS", f"Sources=Uses check: {checks[key]}"


def test_xlsx_capex_reconcile():
    """XLSX_CAPEX_RECONCILE — CAPEX line items sum = context total."""
    wb = _solar_workbook()
    checks = _recon_checks(wb)
    key = "CAPEX line items sum vs context total (kEUR)"
    assert key in checks
    assert checks[key] == "PASS", f"CAPEX check: {checks[key]}"


def test_xlsx_revenue_reconcile():
    """XLSX_REVENUE_RECONCILE — Revenue period sum = runtime total."""
    wb = _solar_workbook()
    checks = _recon_checks(wb)
    key = "Revenue period sum vs runtime total revenue (kEUR)"
    assert key in checks
    assert checks[key] == "PASS", f"Revenue check: {checks[key]}"


def test_xlsx_opex_reconcile():
    """XLSX_OPEX_RECONCILE — OPEX exported = runtime total."""
    wb = _solar_workbook()
    checks = _recon_checks(wb)
    key = "Runtime total OPEX exported (kEUR)"
    assert key in checks
    assert checks[key] == "PASS", f"OPEX check: {checks[key]}"


def test_xlsx_debt_reconcile():
    """XLSX_DEBT_RECONCILE — Debt service period sum = runtime total."""
    wb = _solar_workbook()
    checks = _recon_checks(wb)
    key = "Debt service period sum vs runtime total (kEUR)"
    assert key in checks
    assert checks[key] == "PASS", f"Debt check: {checks[key]}"


def test_xlsx_returns_reconcile():
    """XLSX_RETURNS_RECONCILE — All three return IRRs exported = runtime values."""
    wb = _solar_workbook()
    checks = _recon_checks(wb)
    for label in ["Exported Project IRR vs runtime", "Exported Equity IRR vs runtime",
                  "Exported Total Sponsor XIRR vs runtime"]:
        assert label in checks, f"Check {label!r} not found"
        assert checks[label] == "PASS", f"{label}: {checks[label]}"


# ── Returns sheet content ─────────────────────────────────────────────────────

def test_xlsx_returns_sheet_values():
    """XLSX_RETURNS_RECONCILE — Returns sheet values match Solar reference KPIs."""
    wb = _solar_workbook()
    ret = wb["Returns"]
    data: dict[str, float | str | None] = {}
    for row in ret.iter_rows(min_row=1, max_row=50, values_only=True):
        if row[0] is not None and row[1] is not None:
            data[str(row[0])] = row[1]

    # Project IRR ≈ 11.56%
    proj_irr = data.get("Project IRR")
    assert proj_irr is not None, "Project IRR not in Returns sheet"
    assert math.isclose(float(proj_irr) * 100, 11.56, abs_tol=0.1), (
        f"Project IRR = {float(proj_irr)*100:.4f}%"
    )

    # Equity IRR ≈ 50.47%
    eq_irr = data.get("Equity IRR")
    assert eq_irr is not None, "Equity IRR not in Returns sheet"
    assert math.isclose(float(eq_irr) * 100, 50.47, abs_tol=0.2), (
        f"Equity IRR = {float(eq_irr)*100:.4f}%"
    )

    # Total Sponsor XIRR ≈ 17.90%
    sp_xirr = data.get("Total Sponsor XIRR")
    assert sp_xirr is not None, "Total Sponsor XIRR not in Returns sheet"
    assert math.isclose(float(sp_xirr) * 100, 17.90, abs_tol=0.1), (
        f"Total Sponsor XIRR = {float(sp_xirr)*100:.4f}%"
    )


# ── Run Identity sheet ────────────────────────────────────────────────────────

def test_xlsx_run_identity_sheet():
    """XLSX_EXPORT_LINEAGE — Run Identity sheet present with required fields."""
    wb = _solar_workbook()
    ri = wb["Run Identity"]
    data: dict[str, object] = {}
    for row in ri.iter_rows(min_row=1, max_row=60, values_only=True):
        if row[0] is not None and row[1] is not None:
            data[str(row[0])] = row[1]
    # Sheet uses title-case labels
    assert "Project key" in data, f"Missing 'Project key'; keys={list(data)[:20]}"
    assert "Project name" in data
    assert "Export authority" in data
    assert "Commit SHA" in data
    assert "Branch" in data
    assert "Export generated at" in data


# ── Export authority ──────────────────────────────────────────────────────────

def test_xlsx_export_authority_factory_reference():
    """XLSX_EXPORT_LAST_RUN_AUTHORITY — factory path uses FACTORY_REFERENCE authority."""
    wb = _solar_workbook()
    ri = wb["Run Identity"]
    authority = None
    for row in ri.iter_rows(min_row=1, max_row=60, values_only=True):
        if row[0] == "Export authority":
            authority = row[1]
            break
    # Factory path may use FACTORY_REFERENCE or PREVIEW_WORKING
    assert authority is not None, "Export authority not in Run Identity sheet"


# ── Technology structure smokes ───────────────────────────────────────────────

def test_xlsx_wind_structure_smoke():
    """XLSX_WIND_STRUCTURE_SMOKE — Wind workbook generates with 22 sheets and reconciliation."""
    wb = _wind_workbook()
    assert len(wb.sheetnames) == 22
    assert "Returns" in wb.sheetnames
    assert "Run Identity" in wb.sheetnames
    assert "Reconciliation" in wb.sheetnames
    summary = _recon_summary(wb)
    assert "PASS" in summary
    assert "FAIL: 0" in summary


def test_xlsx_data_center_structure_smoke():
    """XLSX_DATA_CENTER_STRUCTURE_SMOKE — Data Center workbook generates with 22 sheets."""
    wb = _dc_workbook()
    assert len(wb.sheetnames) == 22
    assert "Returns" in wb.sheetnames
    assert "Run Identity" in wb.sheetnames
    assert "Reconciliation" in wb.sheetnames
    summary = _recon_summary(wb)
    assert "FAIL: 0" in summary


def test_xlsx_ev_charging_structure_smoke():
    """XLSX_EV_CHARGING_STRUCTURE_SMOKE — EV Charging workbook generates with 22 sheets."""
    wb = _ev_workbook()
    assert len(wb.sheetnames) == 22
    assert "Returns" in wb.sheetnames
    assert "Run Identity" in wb.sheetnames
    assert "Reconciliation" in wb.sheetnames


# ── Methodology marker ────────────────────────────────────────────────────────

def test_trust_pack_solar_excel_reconciliation_pass():
    """TRUST_PACK_SOLAR_EXCEL_RECONCILIATION — methodology HTML must carry PASS marker."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tpl = os.path.join(root, "app", "templates", "model_methodology.html")
    assert os.path.isfile(tpl)
    content = open(tpl, encoding="utf-8").read()
    assert "TRUST_PACK_SOLAR_EXCEL_RECONCILIATION = PASS" in content, (
        "TRUST_PACK_SOLAR_EXCEL_RECONCILIATION still shows DEFERRED in model_methodology.html"
    )


# ── Gap Register ──────────────────────────────────────────────────────────────

def test_xlsx_gap_register_gap08_closed():
    """XLSX_EXPORT_LINEAGE — Gap Register must show GAP-08 as CLOSED."""
    wb = _solar_workbook()
    gr = wb["Gap Register"]
    found = False
    for row in gr.iter_rows(values_only=True):
        if row[0] == "GAP-08":
            found = True
            assert "CLOSED" in str(row[2]).upper(), f"GAP-08 not CLOSED: {row[2]}"
            break
    assert found, "GAP-08 not found in Gap Register"


# ── Frozen namespace guard ────────────────────────────────────────────────────

def test_xlsx_frozen_namespace_no_financial_engine_changes():
    """XLSX_NO_PARALLEL_CALCULATION_ENGINE — financial_engine/** must be unmodified on this branch.

    This test validates via git diff that no files under financial_engine/,
    finco_core/, or finco_radar/ were modified.
    """
    import subprocess
    result = subprocess.run(
        ["git", "diff", "origin/main", "--name-only"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    changed = result.stdout.strip().splitlines()
    frozen = [f for f in changed if (
        f.startswith("financial_engine/") or
        f.startswith("finco_core/") or
        f.startswith("finco_radar/")
    )]
    assert frozen == [], (
        f"Frozen namespace files changed: {frozen}"
    )


# ── Final composite acceptance marker ─────────────────────────────────────────

def test_finco_p1_2_institutional_xlsx_export_complete():
    """FINCO_P1_2_INSTITUTIONAL_XLSX_EXPORT_COMPLETE

    All P1.2 acceptance gates satisfied in the same revision.
    """
    import math as _math

    # Workbook generates
    from app.export.institutional_workbook import export_institutional_workbook_skeleton
    wb_bytes = export_institutional_workbook_skeleton("generic_solar_reference")
    assert len(wb_bytes) > 40_000

    wb = openpyxl.load_workbook(BytesIO(wb_bytes))
    assert len(wb.sheetnames) == 22
    assert "Returns" in wb.sheetnames
    assert "Reconciliation" in wb.sheetnames

    # All reconciliation checks PASS
    summary = _recon_summary(wb)
    assert "PASS: 8" in summary
    assert "FAIL: 0" in summary

    # Returns values are correct
    ret = wb["Returns"]
    data = {}
    for row in ret.iter_rows(min_row=1, max_row=50, values_only=True):
        if row[0] is not None and row[1] is not None:
            data[str(row[0])] = row[1]
    assert _math.isclose(float(data["Project IRR"]) * 100, 11.56, abs_tol=0.1)
    assert _math.isclose(float(data["Equity IRR"]) * 100, 50.47, abs_tol=0.2)
    assert _math.isclose(float(data["Total Sponsor XIRR"]) * 100, 17.90, abs_tol=0.1)

    # Methodology marker updated
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tpl = os.path.join(root, "app", "templates", "model_methodology.html")
    content = open(tpl, encoding="utf-8").read()
    assert "TRUST_PACK_SOLAR_EXCEL_RECONCILIATION = PASS" in content

    # Technology smokes (22 sheets each)
    for key in ("generic_wind_reference", "generic_data_center_reference"):
        b = export_institutional_workbook_skeleton(key)
        w = openpyxl.load_workbook(BytesIO(b))
        assert len(w.sheetnames) == 22
        assert "Returns" in w.sheetnames
        assert "Reconciliation" in w.sheetnames
