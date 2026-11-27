"""RC-UX (Audit A GAP-R16) — read-only JSON adapter for the OPEX year projection (Y1 .. Yn) shown in React Inputs > Studios.

No arithmetic of its own: the rows are the SAME ``OpexViewModel`` / ``OpexSheetGroup`` projection the Legacy OPEX sheet renders
(``app.v2.router._build_opex_vm_ctx`` over the saved Working Copy: per-line amounts, per-line escalation, applied contingency), passed through
unchanged.  A year a group has no value for is ``null`` — never zero.

* ``GET /model-react/opex-projection?project=CODE`` — groups × years, the contingency and total rows, the Y1 KPIs and the escalation basis.

Read-only (GET), requires the feature flag and a session; shared and protected projects are readable (the same as the Legacy sheet).
Feature flag: ``FINCO_MODEL_REACT_V1``.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import time
from typing import Any, Mapping, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import resolve_request_session

router = APIRouter()


@dataclass(frozen=True)
class _OpexReadSnapshot:
    """Point-in-time consistent read state (committed read-only tx, no write lock held)."""

    owner_id: str
    project_id: str
    record: Any
    ws: Any
    identity: Any
    scenario_record: Any
    matched_run: Any
    token: str


_KNOWN_PREVIEW_ERROR_CODES = (
    "Q4_SCENARIO_SOURCE_CHANGED_REPREVIEW_REQUIRED",
    "Q4_SCENARIO_OVERRIDE_AUTHORITY_INVALID",
    "Q4_WORKBOOK_MAPPING_CHANGED",
    "Q4_SCENARIO_OVERRIDE_VALUE_INVALID",
    "Q4_SCENARIO_ENGINE_INPUT_MISMATCH",
    "SCENARIO_OVERRIDE_UNBOUND",
    "SCENARIO_NOT_FOUND",
    "SCENARIO_ARCHIVED",
    "SCENARIO_PROJECT_MISMATCH",
    "UNSUPPORTED_CURRENCY_EUR_ONLY",
    "DUAL_BALANCING_COST_BASIS_FORBIDDEN",
    "UNKNOWN_YIELD_SCENARIO",
    "OPERATING_PREVIEW_SCENARIO_UNAVAILABLE",
    "OPERATING_PREVIEW_STATE_CHANGED",
    "OPERATING_PREVIEW_IDENTITY_UNAVAILABLE",
    "OPERATING_PREVIEW_SCOPE_MISMATCH",
    "OPERATING_PREVIEW_UNSUPPORTED_PROJECT_TYPE",
    "BESS_FINANCIAL_ACTIVATION_RELEASE_CLOSED",
)


def _extract_preview_error_code(exc: Exception) -> str:
    msg = str(exc)
    for code in _KNOWN_PREVIEW_ERROR_CODES:
        if msg.startswith(code) or code in msg:
            return code
    return "OPERATING_PREVIEW_UNAVAILABLE"


def _capture_opex_read_snapshot(owner_id: str, project_id: str) -> _OpexReadSnapshot:
    """Capture workspace, project, composite identity, active scenario, and matched Run in one BEGIN DEFERRED tx."""
    from app.persistence.db import get_connection
    from app.persistence.records import ProjectRecord, ScenarioRecord, WorkspaceStateRecord
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import WorkbookIdentityError, assemble_transactional

    conn = get_connection()
    try:
        conn.execute("BEGIN DEFERRED")
        cur = conn.cursor()
        cur.execute("SELECT * FROM projects WHERE project_id=? AND user_id=?", (project_id, owner_id))
        project_row = cur.fetchone()
        cur.execute("SELECT * FROM workspace_states WHERE user_id=? AND project_id=?", (owner_id, project_id))
        workspace_row = cur.fetchone()
        if project_row is None or workspace_row is None:
            raise WorkbookIdentityError("Workspace or project not found for OPEX preview")
        if project_row["project_code"] != workspace_row["project_code"]:
            raise WorkbookIdentityError("Project binding mismatch between project and workspace_states")
        identity = assemble_transactional(
            draft_snapshot_json=workspace_row["draft_snapshot_json"] or "{}",
            project_id=project_id,
            user_id=owner_id,
            active_scenario_id=workspace_row["active_scenario_id"],
            active_scenario_name=workspace_row["active_scenario_name"],
            cursor=cur,
            workbook_version=WORKBOOK.version,
        )
        scenario_row = None
        if workspace_row["active_scenario_id"]:
            cur.execute(
                "SELECT * FROM scenarios WHERE scenario_id=? AND user_id=?",
                (workspace_row["active_scenario_id"], owner_id),
            )
            scenario_row = cur.fetchone()
        history_row = None
        last_snap_id = workspace_row["last_runtime_snapshot_id"]
        if last_snap_id:
            cur.execute(
                "SELECT history_id, runtime_snapshot_id, last_runtime_scenario_id, active_scenario_id, active_scenario_name, ran_at "
                "FROM model_run_history WHERE user_id=? AND project_id=? AND runtime_snapshot_id=? "
                "ORDER BY ran_at DESC, history_id DESC LIMIT 1",
                (owner_id, project_id, last_snap_id),
            )
            history_row = cur.fetchone()
        token = hashlib.sha256(
            json.dumps(
                [
                    dict(project_row),
                    dict(workspace_row),
                    dict(scenario_row) if scenario_row is not None else None,
                    identity.composite_hash,
                ],
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        conn.execute("COMMIT")
        return _OpexReadSnapshot(
            owner_id=owner_id,
            project_id=project_id,
            record=ProjectRecord.from_row(project_row),
            ws=WorkspaceStateRecord.from_row(workspace_row),
            identity=identity,
            scenario_record=ScenarioRecord.from_row(scenario_row) if scenario_row is not None else None,
            matched_run=dict(history_row) if history_row is not None else None,
            token=token,
        )
    except Exception:
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def _json(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "private, no-store"})


def _series(values, years: int) -> list[Optional[float]]:
    """The server's per-year values padded with ``None`` (unavailable) up to the displayed years."""
    out: list[Optional[float]] = [None if v is None else float(v) for v in list(values)[:years]]
    return out + [None] * (years - len(out))


def _preview_error_payload(
    *,
    code: str,
    message: str,
    content_hash: Optional[str],
    freshness_info: dict[str, Any],
) -> dict[str, Any]:
    return {
        "available": False,
        "status": "OPERATING_PREVIEW_UNAVAILABLE",
        "code": code,
        "message": message,
        "unit": "kEUR",
        "authority": "CANONICAL_OPERATING_MODEL_PHASE_2A",
        "fingerprint": {"content_hash": content_hash},
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


def _runtime_project_admitted(project_type_raw: str) -> bool:
    t = (project_type_raw or "").strip().lower()
    if t in ("solar", "wind", "data center", "data_center", "datacenter", "ev charging", "ev_charging"):
        return True
    if t == "storage":
        try:
            from app.workbook.bess_config import is_bess_enabled
            return bool(is_bess_enabled())
        except Exception:  # noqa: BLE001
            return False
    return False


def build_operating_preview(
    record,
    ws,
    owner: str,
    *,
    _snapshot: _OpexReadSnapshot | None = None,
) -> dict[str, Any]:
    """Read-only pre-financing canonical operating preview (Phase 2A ``run_operating_model``).

    Assembles effective ``ProjectInputs`` via the same pre-financing pipeline as Run
    (EUR currency guard, project-type admission, Run-identical scenario/Q4 authority,
    CAPEX/OPEX sub-line folds, B.13 contingency, annual OPEX exceptions) using a
    point-in-time consistent read snapshot and post-computation optimistic coherence
    verification without holding SQLite write locks or mutating workspace / Run History.
    """
    from dataclasses import replace as _dc_replace
    from app.opex_annual_exceptions import (
        apply_annual_exceptions_to_opex,
        effective_raw as _opex_ann_effective_raw,
    )
    from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
    from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex
    from app.workbook.runtime_authority import resolve_runtime_freshness
    from app.workbook.scenario_override_authority import resolve_effective_scenario_inputs
    from app.workbook.service import WorkbookService
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import run_operating_model

    started = time.perf_counter()
    default_freshness = {
        "state": "STALE",
        "matches_last_run": False,
        "owner_id": owner,
        "project_id": getattr(record, "project_id", None),
        "scenario_id": getattr(ws, "active_scenario_id", None),
        "last_run_scenario_id": getattr(ws, "last_runtime_scenario_id", None),
        "last_run_history_id": None,
        "last_run_ran_at": None,
        "is_draft_preview": True,
    }

    if (
        getattr(ws, "user_id", owner) != owner
        or getattr(ws, "project_id", None) != getattr(record, "project_id", None)
    ):
        return _preview_error_payload(
            code="OPERATING_PREVIEW_SCOPE_MISMATCH",
            message="Canonical operating preview is unavailable: workspace owner/project scope mismatch.",
            content_hash=None,
            freshness_info=default_freshness,
        )

    try:
        snap_before = _snapshot if _snapshot is not None else _capture_opex_read_snapshot(owner, record.project_id)
    except Exception as exc:  # noqa: BLE001 - fail closed when identity cannot be assembled
        return _preview_error_payload(
            code="OPERATING_PREVIEW_IDENTITY_UNAVAILABLE",
            message=f"Canonical operating preview is unavailable: identity could not be assembled ({type(exc).__name__}).",
            content_hash=None,
            freshness_info=default_freshness,
        )

    snap_ws = snap_before.ws
    current_hash = snap_before.identity.composite_hash

    if (
        dict(getattr(ws, "draft_snapshot", None) or {}) != dict(snap_ws.draft_snapshot or {})
        or getattr(ws, "active_scenario_id", None) != snap_ws.active_scenario_id
        or getattr(ws, "last_runtime_composite_hash", None) != snap_ws.last_runtime_composite_hash
        or getattr(ws, "last_runtime_snapshot_id", None) != snap_ws.last_runtime_snapshot_id
    ):
        return _preview_error_payload(
            code="OPERATING_PREVIEW_STATE_CHANGED",
            message="Canonical operating preview is unavailable because workspace state changed concurrently.",
            content_hash=None,
            freshness_info=default_freshness,
        )

    fresh = resolve_runtime_freshness(snap_ws, current_composite_hash=current_hash)
    fresh_state = str(fresh.state.value) if hasattr(fresh.state, "value") else str(fresh.state)

    last_runtime_identity = getattr(snap_ws, "last_runtime_identity", None)
    runtime_incoherent = False
    if last_runtime_identity is not None and (
        not isinstance(last_runtime_identity, Mapping)
        or last_runtime_identity.get("composite_hash") != getattr(snap_ws, "last_runtime_composite_hash", None)
    ):
        runtime_incoherent = True
    if getattr(snap_ws, "last_runtime_snapshot_id", None) and snap_before.matched_run is None:
        runtime_incoherent = True
    matched_run = snap_before.matched_run
    matched_run_scen = (
        (matched_run.get("last_runtime_scenario_id") or matched_run.get("active_scenario_id"))
        if matched_run is not None
        else None
    )
    last_run_scenario_id = (
        matched_run_scen
        if matched_run is not None
        else getattr(snap_ws, "last_runtime_scenario_id", None)
    )
    if (
        matched_run is not None
        and getattr(snap_ws, "last_runtime_scenario_id", None)
        and matched_run_scen != snap_ws.last_runtime_scenario_id
    ):
        runtime_incoherent = True

    if runtime_incoherent:
        fresh_state = "STALE"

    matches_last_run = bool(
        fresh_state == "CURRENT"
        and not runtime_incoherent
        and (
            last_run_scenario_id == snap_ws.active_scenario_id
            or fresh.source == "pre_scenario_base_equivalence"
        )
    )
    freshness_info = {
        "state": fresh_state,
        "basis": "runtime_identity_incoherent" if runtime_incoherent else fresh.source,
        "matches_last_run": matches_last_run,
        "owner_id": owner,
        "project_id": snap_before.record.project_id,
        "scenario_id": snap_ws.active_scenario_id,
        "last_run_scenario_id": last_run_scenario_id,
        "last_run_history_id": matched_run.get("history_id") if (matched_run is not None and not runtime_incoherent) else None,
        "last_run_ran_at": matched_run.get("ran_at") if (matched_run is not None and not runtime_incoherent) else None,
        "is_draft_preview": True,
    }
    if runtime_incoherent:
        return _preview_error_payload(
            code="OPERATING_PREVIEW_IDENTITY_UNAVAILABLE",
            message="Canonical operating preview cannot verify Last Run freshness identity.",
            content_hash=None,
            freshness_info=freshness_info,
        )

    try:
        if not _runtime_project_admitted(getattr(snap_before.record, "project_type", "")):
            raise ValueError(
                f"OPERATING_PREVIEW_UNSUPPORTED_PROJECT_TYPE: {getattr(snap_before.record, 'project_type', 'Unknown')!r} working-copy runtime is not supported."
            )

        pis = WorkbookService.build_draft_input_set_from_workspace(snap_ws)
        draft_currency = str((pis.to_snapshot() or {}).get("currency") or "EUR").strip().upper()
        if draft_currency and draft_currency != "EUR":
            raise ValueError(
                f"UNSUPPORTED_CURRENCY_EUR_ONLY: Working Copy specifies {draft_currency!r}, "
                "which has no FX conversion authority; only EUR models can be Run."
            )

        override = WorkbookService.to_projectinputs(pis)
        sc_rec = None
        scenario_overrides = None
        if snap_ws.active_scenario_id:
            sc_rec = snap_before.scenario_record
            override, _ = resolve_effective_scenario_inputs(
                pis,
                override,
                project_id=snap_before.record.project_id,
                sc_rec=sc_rec,
            )
            scenario_overrides = (
                sc_rec.overrides
                if (sc_rec is not None and not getattr(sc_rec, "is_base_case", False))
                else None
            )

        folded_capex = apply_user_sub_lines_replacing_base(
            override.capex,
            project_id=snap_before.record.project_id,
            scenario_overrides=scenario_overrides,
        )
        if folded_capex is not override.capex:
            override = _dc_replace(override, capex=folded_capex)

        folded_opex = apply_user_sub_lines_to_opex(
            override.opex,
            project_id=snap_before.record.project_id,
            scenario_overrides=scenario_overrides,
        )
        if folded_opex is not override.opex:
            override = _dc_replace(override, opex=folded_opex)

        ann_raw = _opex_ann_effective_raw(
            pis.snapshot_origin, sc_rec if snap_ws.active_scenario_id else None
        )
        if ann_raw:
            override = _dc_replace(
                override,
                opex=apply_annual_exceptions_to_opex(
                    override.opex, ann_raw, horizon_years=override.info.horizon_years
                ),
            )

        snap_mid = _capture_opex_read_snapshot(owner, snap_before.record.project_id)
        if (
            snap_mid.token != snap_before.token
            or snap_mid.identity.composite_hash != current_hash
            or snap_mid.ws.active_scenario_id != snap_ws.active_scenario_id
        ):
            return _preview_error_payload(
                code="OPERATING_PREVIEW_STATE_CHANGED",
                message="Canonical operating preview aborted because workspace state changed during materialisation.",
                content_hash=None,
                freshness_info={**freshness_info, "state": "STALE", "matches_last_run": False},
            )

        op_input = from_project_inputs(override)
        op_result = run_operating_model(op_input)

        snap_after = _capture_opex_read_snapshot(owner, snap_before.record.project_id)
        if (
            snap_after.token != snap_before.token
            or snap_after.identity.composite_hash != current_hash
            or snap_after.ws.active_scenario_id != snap_ws.active_scenario_id
        ):
            return _preview_error_payload(
                code="OPERATING_PREVIEW_STATE_CHANGED",
                message="Canonical operating preview discarded because workspace state changed during calculation.",
                content_hash=None,
                freshness_info={**freshness_info, "state": "STALE", "matches_last_run": False},
            )
    except Exception as exc:  # noqa: BLE001 - fail closed; never fabricate operating preview
        code = _extract_preview_error_code(exc)
        return _preview_error_payload(
            code=code,
            message=f"Canonical operating preview is unavailable: {exc}",
            content_hash=current_hash,
            freshness_info=freshness_info,
        )

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
            "scenario_id": snap_ws.active_scenario_id,
            "eval_ms": round((time.perf_counter() - started) * 1000.0, 2),
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
    user = resolve_request_session(request)
    if user is None:
        return _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    from app.persistence.projects_repository import resolve_accessible_project

    record, owner = resolve_accessible_project(user.user_id, (project or "").strip())
    if record is None:
        return _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    try:
        from app.v2.router import _build_opex_vm_ctx
        from app.workbook.service import WorkbookService

        snap_before = _capture_opex_read_snapshot(owner, record.project_id)
        ws = snap_before.ws
        pis = WorkbookService.build_draft_input_set_from_workspace(ws)
        try:
            ctx = _build_opex_vm_ctx(snap_before.record, pis, ws=ws, workspace_owner=owner)
            vm, groups = ctx["opex_vm"], ctx["opex_sheet_groups"]
            years = int(vm.display_years)
            rows = [{"code": g.code, "name": g.display_name, "derived": bool(g.is_derived), "has_data": bool(g.has_vm_data),
                     "escalation": g.escalation_display, "values": _series(g.year_rows, years) if g.has_vm_data else [None] * years}
                    for g in groups]
            escalation = ctx.get("opex_escalation_summary") or {}
            years_list = list(range(1, years + 1))
            contingency_out = {"rate_pct": float(vm.contingency_rate), "by_year": _series(vm.contingency_by_year, years)}
            totals_out = {"excluding_contingency": _series(vm.total_excl_contingency, years), "including_contingency": _series(vm.total_incl_contingency, years)}
            kpis_out = {"year1_total_keur": vm.y1_total_opex, "final_year_total_keur": vm.final_year_total_opex,
                        "per_mw_year1_keur": vm.opex_per_mw_y1, "per_mwh_year1_eur": vm.opex_per_mwh_y1}
            esc_out = {"value": escalation.get("value"), "label": escalation.get("label")}
        except Exception as vm_exc:  # noqa: BLE001 - surface typed input refusal inside operating_preview rather than 503
            if _extract_preview_error_code(vm_exc) == "OPERATING_PREVIEW_UNAVAILABLE":
                raise
            years_list = []
            rows = []
            contingency_out = {"rate_pct": 0.0, "by_year": []}
            totals_out = {"excluding_contingency": [], "including_contingency": []}
            kpis_out = {"year1_total_keur": None, "final_year_total_keur": None,
                        "per_mw_year1_keur": None, "per_mwh_year1_eur": None}
            esc_out = {"value": None, "label": None}
        operating_preview = build_operating_preview(snap_before.record, ws, owner, _snapshot=snap_before)

        snap_after = _capture_opex_read_snapshot(owner, record.project_id)
        if (
            snap_after.token != snap_before.token
            or operating_preview.get("code") == "OPERATING_PREVIEW_STATE_CHANGED"
        ):
            return _json(
                {
                    "ok": False,
                    "code": "OPEX_PROJECTION_STATE_CHANGED",
                    "message": "The workspace changed while the OPEX projection was assembled. Reload to refresh.",
                },
                503,
            )

        payload = {
            "ok": True,
            "project": {
                "code": snap_before.record.project_code,
                "project_id": snap_before.record.project_id,
                "owner_id": owner,
                "protected_reference": bool(getattr(snap_before.record, "is_protected", False)),
            },
            "identity": {
                "content_hash": snap_before.identity.composite_hash,
                "scenario_id": ws.active_scenario_id,
            },
            "unit": "kEUR", "years": years_list, "rows": rows,
            "contingency": contingency_out,
            "totals": totals_out,
            "kpis": kpis_out,
            "escalation": esc_out,
            "basis": (
                "The saved project's nominal annual OPEX budget (full-year rates per operating year for editable lines, "
                "each line's escalation and the applied contingency; not prorated for partial COD). Not a Run result."
            ),
            "operating_preview": operating_preview,
        }
    except Exception:  # noqa: BLE001 - fail closed; never fabricate a projection
        return _json({"ok": False, "code": "OPEX_PROJECTION_UNAVAILABLE", "message": "The OPEX projection could not be built. Reload to try again."}, 503)
    return _json(payload)
