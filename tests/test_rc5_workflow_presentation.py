"""Application presentation regressions; no replacement financial calculation."""
from types import SimpleNamespace as NS

import pytest


def _opex_vm(pct):
    from app.ui.opex_view_model import build_opex_view_model
    ctx = NS(name="Controlled Wind", code="controlled-wind", capacity_mw=40,
             operating_hours_p50=2500, opex_contingency_pct=6,
             opex_contingency_applied=False, opex_detail_items=[
                 {"code": "B.02", "name": "Maintenance", "children": [
                     {"code": "B.02.01", "name": "Maintenance", "budget_y1_keur": 550}]},
                 {"code": "B.13", "name": "Contingencies", "is_contingency": True,
                  "children": []}])
    return build_opex_view_model(ctx, is_user_project=True, display_years=3,
                                 contingency_pct=pct, contingency_source="project")


@pytest.mark.parametrize("pct,amount,total", [(5, 27.5, 577.5), (0, 0, 550), (None, 0, 550)])
def test_b13_parent_and_projection_use_applied_contingency_once(pct, amount, total):
    from app.ui.opex_sheet_projection import build_opex_sheet_projection
    vm = _opex_vm(pct)
    b13 = next(g for g in build_opex_sheet_projection(vm, []) if g.code == "B.13")
    assert b13.subtotal_y1 == amount
    assert b13.year_rows == vm.contingency_by_year
    assert vm.y1_total_opex == total
    assert sum(g.subtotal_y1 for g in build_opex_sheet_projection(vm, [])) == total
    if pct is None:
        assert vm.reference_contingency_pct == 6


def test_reference_cards_disclose_saved_date_and_unknown_engine():
    from app.library.model_home import build_reference_cards
    rec = NS(project_id="ref", project_code="reference", project_name="Example",
             project_type="Wind", is_protected=True)
    ws = NS(last_runtime_summary={"min_dscr": 0.94}, last_runtime_at="2026-09-26T10:00:00Z",
            last_runtime_identity={}, replay_metadata={})
    card = build_reference_cards([rec], {"ref": ws})[0]
    assert card.last_run_at_display == "2026-09-26"
    assert card.engine_currency == "ENGINE_IDENTITY_UNKNOWN"
    assert card.kpis[0][2] == "0.94x"  # never silently refresh an old financial value


def test_persisted_export_uses_record_identity_not_template():
    from app.project_factories import create_generic_wind_reference
    from app.services.v2_export_service import _build_persisted_bundle, _RuntimeResultAdapter
    rec = NS(project_id="owned-project", project_code="renamed-wind", project_name="Renamed Wind",
             project_type="Wind", project_origin="user_created", template_source="generic_wind_reference",
             baseline_snapshot=None)
    ws = NS(last_runtime_composite_hash="run-hash", last_runtime_identity={"engine_version": "saved-engine"})
    bundle = _build_persisted_bundle(
        "generic_wind_reference", project_record=rec,
        project_inputs=create_generic_wind_reference(), current_snapshot={},
        result_adapter=_RuntimeResultAdapter({"project_irr": 0.12}, {"periods": []}),
        statements_adapter=None, runtime_origin="canonical_last_run", scenario_id="saved-scenario",
        scenario_name="Saved Downside", export_authority="CANONICAL_LAST_RUN",
        working_changed_since_run=True, run_id="saved-run", run_at="2026-09-26T10:00:00Z",
        snapshot_id="saved-snapshot", runtime_timestamp="2026-09-26T10:00:00Z", ws=ws)
    assert bundle.project_key == "renamed-wind"
    assert bundle.project_name == "Renamed Wind"
    assert bundle.active_project == "renamed-wind"
    assert bundle.scenario_id == "saved-scenario"
    assert bundle.run_id == "saved-run"
    assert bundle.engine_version == "saved-engine"
    assert all(row["active_project"] == "renamed-wind" for row in bundle.runtime_rows)
    assert all(row["project"] == "Renamed Wind" for row in bundle.runtime_rows)
    assert next(row["value"] for row in bundle.runtime_rows if row["metric"] == "active_project") == "Renamed Wind"


def test_download_name_is_readable_and_header_safe():
    from app.export.filename import model_results_filename
    assert model_results_filename("Renamed Wind", "Downside", "snapshot-123") == "finco-Renamed-Wind-Downside-results-snapshot-123.xlsx"
    name = model_results_filename('../../Project\r\nInjected: "x"', "a/b", "snapshot")
    assert not any(c in name for c in '/\\\r\n"')
    assert "phase10" not in name and "skeleton" not in name
