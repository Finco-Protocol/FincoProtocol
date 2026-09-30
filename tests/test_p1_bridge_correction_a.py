"""PR #150/#155 Correction A — ingress, identity-layout and same-run gates.

  A. dc_electricity_price scales the ENTIRE canonical power-expense
     schedule: y1_amount_keur AND every explicit step_change year.
  B. Same-run identity section and the horizontal statement table occupy
     deterministic, non-overlapping rows; Bound run id / Bound snapshot id
     are physically present (read-back) on P&L, PF Cash Flow, Balance
     Sheet and Tax.
  C. Cross-run statement substitution fails closed BEFORE serialization:
     a mismatched statement package raises CROSS_RUN_STATEMENT_SUBSTITUTION.
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone

import pytest


@pytest.fixture(scope="module")
def solar_bundle():
    import os

    os.environ["FINCO_DB_PATH"] = os.path.join(
        tempfile.mkdtemp(), "corr-a-bundle.db")
    from app.persistence import db

    db.DB_PATH = os.environ["FINCO_DB_PATH"]
    db.init_db()
    from app.export.institutional_workbook import _build_export_bundle

    return _build_export_bundle("generic_solar_reference")


# ── A: dc_electricity_price full-schedule scaling ──────────────────────────

class TestDCElectricityPriceFullSchedule:
    def test_y1_and_all_steps_scale_by_same_factor(self):
        from app.project_factories import create_generic_data_center_reference
        from app.services.sensitivity_service import _apply_shock

        proj = create_generic_data_center_reference()
        power = next(o for o in proj.opex if o.name == "Power Expenses")
        assert power.step_changes, "canonical DC power schedule must carry steps"

        shocked = _apply_shock(proj, "dc_electricity_price", 25.0)
        factor = 1.25
        power_new = next(o for o in shocked.opex if o.name == "Power Expenses")
        assert power_new.y1_amount_keur == pytest.approx(
            power.y1_amount_keur * factor)
        old_steps = dict(power.step_changes)
        new_steps = dict(power_new.step_changes)
        assert set(new_steps) == set(old_steps)
        for year, base_amount in old_steps.items():
            assert new_steps[year] == pytest.approx(base_amount * factor), year

    def test_non_power_opex_untouched(self):
        from app.project_factories import create_generic_data_center_reference
        from app.services.sensitivity_service import _apply_shock

        proj = create_generic_data_center_reference()
        shocked = _apply_shock(proj, "dc_electricity_price", 25.0)
        for old, new in zip(proj.opex, shocked.opex):
            if old.name != "Power Expenses":
                assert new.y1_amount_keur == old.y1_amount_keur, old.name

    def test_base_case_economics_unchanged(self):
        from app.project_factories import create_generic_data_center_reference
        from app.services.sensitivity_service import _apply_shock

        proj = create_generic_data_center_reference()
        shocked = _apply_shock(proj, "dc_electricity_price", 10.0)
        # Revenue-side fields untouched: sensitivity is OPEX-only.
        assert shocked.revenue.market_prices_curve == proj.revenue.market_prices_curve
        assert shocked.capex.total_capex == proj.capex.total_capex
        assert shocked.technical.capacity_mw == proj.technical.capacity_mw


# ── B: identity layout no-collision + read-back ────────────────────────────

class TestIdentityLayoutReadBack:
    def _statement_sheet(self, bundle_builder, sheet_title):
        from openpyxl import Workbook

        wb = Workbook()
        sheet = wb.active
        sheet.title = sheet_title
        bundle_builder(sheet)
        return sheet

    def test_identity_rows_readback_no_collision(self, solar_bundle):
        from app.export.institutional_workbook import (
            _write_pnl_sheet, _write_cash_flow_sheet, _write_balance_sheet,
            _write_tax_sheet,
        )
        from openpyxl import Workbook

        expected_run_id = solar_bundle.run_id
        expected_snapshot = solar_bundle.runtime_snapshot_id
        for writer, title in (
            (_write_pnl_sheet, "P&L"),
            (_write_cash_flow_sheet, "PF Cash Flow"),
            (_write_balance_sheet, "Balance Sheet"),
            (_write_tax_sheet, "Tax"),
        ):
            wb = Workbook()
            sheet = wb.active
            sheet.title = title
            writer(sheet, solar_bundle)

            # Scan the sheet for the identity labels; verify both values are
            # physically present with the exact bound values.
            labels_found = {}
            for row in sheet.iter_rows():
                for cell in row:
                    if cell.value == "Bound run id":
                        labels_found["run_id"] = sheet.cell(
                            row=cell.row, column=cell.column + 1).value
                    if cell.value == "Bound snapshot id":
                        labels_found["snapshot"] = sheet.cell(
                            row=cell.row, column=cell.column + 1).value
            assert labels_found.get("run_id") == expected_run_id, title
            assert labels_found.get("snapshot") == expected_snapshot, title

            # No-collision proof: the identity values are not overwritten by
            # the table (each label appears exactly once with a value cell
            # holding the identity, not a metric header/number).
            run_id_label_count = sum(
                1 for row in sheet.iter_rows() for cell in row
                if cell.value == "Bound run id")
            assert run_id_label_count == 1, (title, run_id_label_count)

    def test_identity_and_table_rows_non_overlapping(self, solar_bundle):
        from app.export.institutional_workbook import _write_pnl_sheet
        from openpyxl import Workbook

        wb = Workbook()
        sheet = wb.active
        _write_pnl_sheet(sheet, solar_bundle)
        identity_rows, table_rows = set(), set()
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value == "Bound run id":
                    identity_rows.add(cell.row)
                if cell.value == "P&L period table":
                    table_rows.add(cell.row)
        assert identity_rows and table_rows
        assert identity_rows.isdisjoint(table_rows)


# ── C: cross-run substitution fails closed ─────────────────────────────────

class TestCrossRunSubstitutionFailClosed:
    def test_mismatched_statement_package_rejected(self, solar_bundle, monkeypatch):
        """Inject a statement package whose run identity differs from the
        workbook run authority — export must fail closed, never serialize."""
        from app.export import institutional_workbook as wb_mod
        from app.export import clean_statements_adapter as adapter_mod

        real_serialize = adapter_mod.serialize_clean_statements

        def _mismatched_serialize(*args, **kwargs):
            view = real_serialize(*args, **kwargs)
            # Substitute a foreign run identity (simulating cross-run import).
            from app.export.clean_statements_adapter import (
                CleanStatementsSerializationView,
            )
            return CleanStatementsSerializationView(
                run_id="foreign_run_999",
                run_identity_hash="foreign_snapshot_999",
                tax_bridge=view.tax_bridge,
                pnl=view.pnl,
                pf_cash_waterfall=view.pf_cash_waterfall,
                balance_sheet=view.balance_sheet,
                status=view.status,
            )

        monkeypatch.setattr(
            adapter_mod, "serialize_clean_statements", _mismatched_serialize)
        with pytest.raises(ValueError, match="CROSS_RUN_STATEMENT_SUBSTITUTION"):
            _build_export_bundle = wb_mod._build_export_bundle
            _build_export_bundle("generic_solar_reference")

    def test_matching_package_serializes(self, solar_bundle):
        from app.export import institutional_workbook as wb_mod

        # The normal path (identity matches) still binds the clean package.
        bundle = wb_mod._build_export_bundle("generic_solar_reference")
        assert bundle.statements is not None
        assert bundle.statements.run_id == bundle.run_id
