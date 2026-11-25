"""RC-UX (Audit A GAP-R16) — read-only JSON adapter for the OPEX year projection (Y1 .. Yn) shown in React Inputs > Studios.

No arithmetic of its own: the rows are the SAME ``OpexViewModel`` / ``OpexSheetGroup`` projection the Legacy OPEX sheet renders
(``app.v2.router._build_opex_vm_ctx`` over the saved Working Copy: per-line amounts, per-line escalation, applied contingency), passed through
unchanged.  A year a group has no value for is ``null`` — never zero.

* ``GET /model-react/opex-projection?project=CODE`` — groups × years, the contingency and total rows, the Y1 KPIs and the escalation basis.

Read-only (GET), requires the feature flag and a session; shared and protected projects are readable (the same as the Legacy sheet).
Feature flag: ``FINCO_MODEL_REACT_V1``.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import resolve_request_session
from app.v2.react_poc_router import react_poc_enabled

router = APIRouter()


def _json(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "private, no-store"})


def _series(values, years: int) -> list[Optional[float]]:
    """The server's per-year values padded with ``None`` (unavailable) up to the displayed years."""
    out: list[Optional[float]] = [None if v is None else float(v) for v in list(values)[:years]]
    return out + [None] * (years - len(out))


def build_operating_preview(record, ws, owner: str) -> dict[str, Any]:
    """Read-only pre-financing canonical operating preview (Phase 2A ``run_operating_model``).

    Assembles effective ``ProjectInputs`` via the same pre-financing pipeline as Run
    (scenario overrides, CAPEX/OPEX sub-line folds, B.13 contingency, annual OPEX
    exceptions) and evaluates ``run_operating_model`` without running financing, debt,
    SHL, tax solvers, or mutating workspace / Run History.
    """
    from dataclasses import replace as _dc_replace
    from app.opex_annual_exceptions import (
        apply_annual_exceptions_to_opex,
        effective_raw as _opex_ann_effective_raw,
    )
    from app.persistence.run_history_repository import get_latest_history_entry
    from app.persistence.scenarios_repository import get_scenario, resolve_scenario_snapshot
    from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
    from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex
    from app.workbook.input_set import ProjectInputSet
    from app.workbook.registry import WORKBOOK
    from app.workbook.runtime_authority import resolve_runtime_freshness
    from app.workbook.scenario_revenue_authority import bind_scenario_tariff
    from app.workbook.service import WorkbookService
    from app.workbook.workbook_identity import assemble_consistent_for_get
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import run_operating_model

    try:
        current_hash = assemble_consistent_for_get(owner, record.project_id, WORKBOOK.version).composite_hash
    except Exception:  # noqa: BLE001
        current_hash = None
    fresh = resolve_runtime_freshness(ws, current_composite_hash=current_hash)
    fresh_state = str(fresh.state.value) if hasattr(fresh.state, "value") else str(fresh.state)
    latest_run = get_latest_history_entry(ws.user_id, record.project_id)
    freshness_info = {
        "state": fresh_state,
        "matches_last_run": fresh_state == "CURRENT",
        "last_run_history_id": getattr(latest_run, "history_id", None) if latest_run is not None else None,
        "last_run_ran_at": getattr(latest_run, "ran_at", None) if latest_run is not None else None,
        "is_draft_preview": True,
    }

    try:
        pis = WorkbookService.build_draft_input_set_from_workspace(ws)
        override = WorkbookService.to_projectinputs(pis)
        sc_rec = None
        scenario_overrides = None
        if ws.active_scenario_id:
            sc_rec = get_scenario(scenario_id=ws.active_scenario_id, user_id=owner)
            if sc_rec is None or sc_rec.archived or sc_rec.project_id != record.project_id:
                raise ValueError("OPERATING_PREVIEW_SCENARIO_UNAVAILABLE")
            scenario_overrides = sc_rec.overrides
            if not sc_rec.is_base_case:
                if (sc_rec.replay_metadata or {}).get("action") == "q4_finding_whatif_v1":
                    effective_snap = resolve_scenario_snapshot(
                        dict(sc_rec.base_input_set or {}), dict(sc_rec.overrides or {})
                    )
                    override = WorkbookService.to_projectinputs(ProjectInputSet.from_snapshot(effective_snap))
                elif any(
                    key in (sc_rec.overrides or {})
                    for key in ("tariff_eur_mwh", "rev_multistream_config_json", "bess_native_config_json")
                ):
                    effective_snap = bind_scenario_tariff(dict(pis.snapshot_origin), sc_rec.overrides)
                    override = WorkbookService.to_projectinputs(WorkbookService.build_input_set(effective_snap))

        folded_capex = apply_user_sub_lines_replacing_base(
            override.capex,
            project_id=record.project_id,
            scenario_overrides=scenario_overrides,
        )
        if folded_capex is not override.capex:
            override = _dc_replace(override, capex=folded_capex)

        folded_opex = apply_user_sub_lines_to_opex(
            override.opex,
            project_id=record.project_id,
            scenario_overrides=scenario_overrides,
        )
        if folded_opex is not override.opex:
            override = _dc_replace(override, opex=folded_opex)

        ann_raw = _opex_ann_effective_raw(pis.snapshot_origin, sc_rec if ws.active_scenario_id else None)
        if ann_raw:
            override = _dc_replace(
                override,
                opex=apply_annual_exceptions_to_opex(
                    override.opex, ann_raw, horizon_years=override.info.horizon_years
                ),
            )

        op_input = from_project_inputs(override)
        op_result = run_operating_model(op_input)
    except Exception as exc:  # noqa: BLE001 - fail closed; never fabricate operating preview
        return {
            "available": False,
            "status": "OPERATING_PREVIEW_UNAVAILABLE",
            "code": "OPERATING_PREVIEW_UNAVAILABLE",
            "message": f"Canonical operating preview is unavailable for the current inputs ({type(exc).__name__}).",
            "unit": "kEUR",
            "authority": "CANONICAL_OPERATING_MODEL_PHASE_2A",
            "fingerprint": {"content_hash": current_hash},
            "freshness": freshness_info,
            "periods": [],
            "calendar_years": [],
            "operating_years": [],
            "kpis": None,
            "scope_note": (
                "Pre-financing canonical operating preview (revenue, OPEX, EBITDA). "
                "Depreciation, EBIT, tax, financing, DSCR and SHL require a full Run."
            ),
        }

    periods_out: list[dict[str, Any]] = []
    cal_map: dict[int, dict[str, Any]] = {}
    op_map: dict[int, dict[str, Any]] = {}
    for p in op_result.periods:
        cal_year = int(p.period_end.year)
        op_yr = int(round(p.year_index)) if p.is_operation else 0
        rev = float(p.revenue_keur)
        opex = float(p.opex_keur)
        ebitda = float(p.ebitda_keur)
        periods_out.append({
            "period_index": int(p.period_index),
            "period_start": p.period_start.isoformat(),
            "period_end": p.period_end.isoformat(),
            "calendar_year": cal_year,
            "operating_year": op_yr,
            "is_construction": bool(p.is_construction),
            "is_operation": bool(p.is_operation),
            "day_fraction": float(p.day_fraction),
            "operating_expenses_keur": opex,
            "revenue_keur": rev,
            "ebitda_keur": ebitda,
        })
        c_row = cal_map.setdefault(
            cal_year,
            {
                "calendar_year": cal_year,
                "has_operation": False,
                "operating_expenses_keur": 0.0,
                "revenue_keur": 0.0,
                "ebitda_keur": 0.0,
            },
        )
        c_row["has_operation"] = bool(c_row["has_operation"] or p.is_operation)
        c_row["operating_expenses_keur"] += opex
        c_row["revenue_keur"] += rev
        c_row["ebitda_keur"] += ebitda
        if p.is_operation and op_yr >= 1:
            o_row = op_map.setdefault(
                op_yr,
                {
                    "operating_year": op_yr,
                    "operating_expenses_keur": 0.0,
                    "revenue_keur": 0.0,
                    "ebitda_keur": 0.0,
                },
            )
            o_row["operating_expenses_keur"] += opex
            o_row["revenue_keur"] += rev
            o_row["ebitda_keur"] += ebitda

    cal_years = [cal_map[y] for y in sorted(cal_map)]
    op_years = [op_map[y] for y in sorted(op_map)]
    op_cal_years = [r for r in cal_years if r["has_operation"]]
    kpis = {
        "first_operating_calendar_year_opex_keur": op_cal_years[0]["operating_expenses_keur"] if op_cal_years else None,
        "first_operating_calendar_year": op_cal_years[0]["calendar_year"] if op_cal_years else None,
        "final_operating_calendar_year_opex_keur": op_cal_years[-1]["operating_expenses_keur"] if op_cal_years else None,
        "first_operating_year_opex_keur": op_years[0]["operating_expenses_keur"] if op_years else None,
        "final_operating_year_opex_keur": op_years[-1]["operating_expenses_keur"] if op_years else None,
        "total_operating_opex_keur": sum(r["operating_expenses_keur"] for r in op_years),
        "total_operating_revenue_keur": sum(r["revenue_keur"] for r in op_years),
        "total_operating_ebitda_keur": sum(r["ebitda_keur"] for r in op_years),
    }
    return {
        "available": True,
        "status": "OK",
        "unit": "kEUR",
        "authority": "CANONICAL_OPERATING_MODEL_PHASE_2A",
        "date_authority_version": getattr(override.info, "date_authority_version", None) or "LEGACY_CALENDAR/v0",
        "fingerprint": {
            "content_hash": current_hash,
            "input_fingerprint": getattr(op_result, "input_fingerprint", None),
        },
        "freshness": freshness_info,
        "periods": periods_out,
        "calendar_years": cal_years,
        "operating_years": op_years,
        "kpis": kpis,
        "scope_note": (
            "Calculated from the pre-financing canonical operating model (Phase 2A) over the current saved inputs, "
            "prorated by actual period dates/day-fractions. Depreciation, EBIT, tax, financing, DSCR and SHL require "
            "a full Run. Read-only: does not commit, mutate workspace or create Run History."
        ),
    }


@router.get("/model-react/opex-projection")
async def react_opex_projection(request: Request, project: str = ""):
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user = resolve_request_session(request)
    if user is None:
        return _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state

    record, owner = resolve_accessible_project(user.user_id, (project or "").strip())
    if record is None:
        return _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    ws = get_workspace_state(owner, record.project_id)
    if ws is None:
        return _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    try:
        from app.v2.router import _build_opex_vm_ctx
        from app.workbook.service import WorkbookService

        pis = WorkbookService.build_draft_input_set_from_workspace(ws)
        ctx = _build_opex_vm_ctx(record, pis, ws=ws, workspace_owner=owner)
        vm, groups = ctx["opex_vm"], ctx["opex_sheet_groups"]
        years = int(vm.display_years)
        rows = [{"code": g.code, "name": g.display_name, "derived": bool(g.is_derived), "has_data": bool(g.has_vm_data),
                 "escalation": g.escalation_display, "values": _series(g.year_rows, years) if g.has_vm_data else [None] * years}
                for g in groups]
        escalation = ctx.get("opex_escalation_summary") or {}
        operating_preview = build_operating_preview(record, ws, owner)
        payload = {
            "ok": True, "project": {"code": record.project_code, "protected_reference": bool(getattr(record, "is_protected", False))},
            "unit": "kEUR", "years": list(range(1, years + 1)), "rows": rows,
            "contingency": {"rate_pct": float(vm.contingency_rate), "by_year": _series(vm.contingency_by_year, years)},
            "totals": {"excluding_contingency": _series(vm.total_excl_contingency, years), "including_contingency": _series(vm.total_incl_contingency, years)},
            "kpis": {"year1_total_keur": vm.y1_total_opex, "final_year_total_keur": vm.final_year_total_opex,
                     "per_mw_year1_keur": vm.opex_per_mw_y1, "per_mwh_year1_eur": vm.opex_per_mwh_y1},
            "escalation": {"value": escalation.get("value"), "label": escalation.get("label")},
            "basis": (
                "The saved project's nominal annual OPEX budget (full-year rates per operating year for editable lines, "
                "each line's escalation and the applied contingency; not prorated for partial COD). Not a Run result."
            ),
            "operating_preview": operating_preview,
        }
    except Exception:  # noqa: BLE001 - fail closed; never fabricate a projection
        return _json({"ok": False, "code": "OPEX_PROJECTION_UNAVAILABLE", "message": "The OPEX projection could not be built. Reload to try again."}, 503)
    return _json(payload)
