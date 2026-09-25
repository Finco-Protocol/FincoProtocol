"""
app.ui.inputs_summary — Canonical Inputs Control Tower summary adapter.

Builds CAPEX and OPEX summary numbers from the canonical CapexViewModel
and OpexViewModel, which are the same computation paths used by the
detailed CAPEX and OPEX sheets.  Inputs summary values are therefore
guaranteed to match the detail-sheet figures for the same project state.

The V2 router delegates all financial aggregation to this adapter.
No CAPEX/OPEX field lists, no formulas, and no ViewModel construction
may appear in app/v2/router.py.
"""
from __future__ import annotations

from typing import Any

from app.ui.capex_view_model import build_capex_view_model
from app.ui.opex_view_model import build_opex_view_model
from app.ui.project_context import build_project_context_for_record


def build_inputs_summary(project_record: Any, pis: Any, ws: Any) -> dict[str, Any]:
    """
    Return an Inputs-sheet summary dict built from canonical ViewModels.

    Args:
        project_record: ProjectRecord (project_code, project_name,
                        project_type, project_origin, template_source).
        pis:            ProjectInputSet — current draft; .to_snapshot()
                        yields the legacy snapshot for ProjectContext.
        ws:             WorkspaceStateRecord — provides runtime metadata
                        (last_runtime_snapshot_id, last_runtime_at, dirty).

    Returns:
        dict with keys:
          capex_hard_keur, capex_financing_keur, capex_reserve_keur,
          capex_total_keur, capex_per_mw_keur,
          opex_y1_keur, opex_per_mw_keur, opex_per_mwh_eur,
          runtime_snapshot_id, last_run_at.

    All financial values use the canonical ViewModel formulas:
      opex_per_mwh_eur  = y1_total_opex_keur × 1000 / p50_annual_mwh   (EUR/MWh)
      capex_per_mw_keur = total_capex_keur / capacity_mw                (k€/MW)
    """
    snapshot = pis.to_snapshot()
    project_ctx = build_project_context_for_record(
        project_code=project_record.project_code,
        project_name=project_record.project_name,
        project_type=project_record.project_type,
        project_origin=project_record.project_origin,
        template_source=project_record.template_source,
        baseline_snapshot=snapshot,
    )

    is_user = not (
        project_record.project_origin == "factory_template"
        and (project_record.template_source or "").strip().lower() in ("generic_wind_reference", "generic_solar_reference", "generic_storage_reference", "generic_ev_charging_reference")
    )

    # Load active user sub-lines so Inputs summary matches CAPEX and OPEX detail sheets.
    from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
    sub_lines = get_active_sub_lines_for_project(project_record.project_id)
    capex_vm = build_capex_view_model(project_ctx, is_user_project=is_user, sub_lines=sub_lines)
    from app.persistence.opex_sub_lines import get_active_sub_lines_for_project as _get_opex_sub_lines
    opex_sub_lines = _get_opex_sub_lines(project_record.project_id)
    opex_vm = build_opex_view_model(project_ctx, is_user_project=is_user, sub_lines=opex_sub_lines)

    return {
        "capex_hard_keur": capex_vm.hard_capex_keur,
        "capex_financing_keur": capex_vm.financing_keur,
        "capex_reserve_keur": capex_vm.reserve_keur,
        "capex_total_keur": capex_vm.total_capex_keur,
        "capex_per_mw_keur": capex_vm.total_per_mw,
        "opex_y1_keur": opex_vm.y1_total_opex,
        "opex_per_mw_keur": opex_vm.opex_per_mw_y1,
        "opex_per_mwh_eur": opex_vm.opex_per_mwh_y1,
        "runtime_snapshot_id": ws.last_runtime_snapshot_id,
        "last_run_at": getattr(ws, "last_runtime_at", None),
    }
