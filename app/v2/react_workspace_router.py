"""UX-02 React Core Integration — authorized JSON projections for the integrated React workbook.

Presentation-only read surface over the EXISTING canonical authorities.  It adds NO
economic or persistence authority:

* ``GET /model-react/library``    — the user's own workspace projects plus the public
  reference models, via the SAME repository reads the legacy Library page uses
  (``list_workspace_projects_paged`` / ``get_reference_projects``).  Working-copy
  creation stays on the existing ``POST /library/clone/{id}``; nothing is cloned here.
* ``GET /model-react/workspace``  — one coherent shell snapshot per project: identity,
  composite workbook identity, scenario, freshness, persisted Last Run identity,
  Run Integrity and the four independent status dimensions (SC-03).
* ``GET /model-react/statements`` — the SIX statement destinations (P&L, Balance Sheet,
  Cash Flow, CFADS, Debt, Sponsor Returns) adapted from the canonical statement
  presentation services into the harvested React ``StatementWorkbookSnapshot`` shape.
  Every cell arrives as a server-formatted display string; unavailable values stay
  ``null``-backed "—" and are never substituted with zeros or demo data.
* ``GET /model-react/inputs``     — the canonical Hybrid Inputs grid projection
  (``app.v2.router._build_input_grid_ctx`` — the SAME builder the legacy grid panel
  renders), serialized to JSON, plus the Save tokens (CSRF, composite hash, workbook
  version, scenario) the existing ``POST /v2/workbook/grid/save`` requires.

All mutations remain on the canonical routes: scalar grid saves on
``POST /v2/workbook/grid/save`` (C0 atomic writer, composite CAS, CSRF), cost lines on
``POST /v2/workbook/grid/cost-lines/save``, working-copy creation on
``POST /library/clone/{id}``, and Run on ``POST /v2/workbook/run`` (deliberately not
exposed here — the thin Run-outcome adapter is still deferred, as documented in
``docs/react_migration/ux01_poc_implementation.md``).

Feature flag: the same ``FINCO_MODEL_REACT_V1`` gate as the UX-01 PoC surface.
"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any, Mapping, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import generate_csrf_token, resolve_request_session
from app.v2.react_poc_router import REACT_ASSET_VERSION, react_poc_enabled

router = APIRouter()

REACT_WORKSPACE_VERSION = "ux02-v1"


def _json(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})


def _resolve_project(request: Request, project: str):
    """(user, record, owner) or a ready JSONResponse — the canonical authorization order."""
    user = resolve_request_session(request)
    if user is None:
        return None, None, None, _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    from app.persistence.projects_repository import resolve_accessible_project

    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return None, None, None, _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    return user, record, owner, None


# ───────────────────────────── library ─────────────────────────────

@router.get("/model-react/library")
async def react_workspace_library(request: Request, search: str = "", page: int = 1):
    """Authorized Library read: the caller's own projects + public reference models."""
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user = resolve_request_session(request)
    if user is None:
        return _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)

    import math

    from app.library.router import PAGE_SIZE, _reference_templates
    from app.persistence.projects_repository import list_workspace_projects_paged

    page = max(1, page)
    records, total = list_workspace_projects_paged(
        user_id=user.user_id, page=page, page_size=PAGE_SIZE,
        search=(search or "").strip() or None, role_filter=None)
    references = _reference_templates(search or "", None)

    from app.persistence.workspace_repository import get_workspace_state
    from app.services.project_library_service import is_protected_reference
    from app.workbook.runtime_authority import resolve_runtime_freshness
    from app.workbook.workbook_identity import assemble_consistent_for_get, WorkbookIdentityError
    from app.workbook.registry import WORKBOOK

    def project_entry(record, protected: bool) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "code": record.project_code,
            "name": getattr(record, "project_name", None) or record.project_code,
            "project_type": getattr(record, "project_type", None) or "",
            "template_source": getattr(record, "template_source", None) or "",
            "protected_reference": protected,
            "reference": protected,
        }
        ws = get_workspace_state(record.user_id, record.project_id)
        last_run: dict[str, Any] | None = None
        if ws is not None:
            try:
                identity = assemble_consistent_for_get(record.user_id, record.project_id, WORKBOOK.version)
                freshness = resolve_runtime_freshness(ws, current_composite_hash=identity.composite_hash)
                last_run = {
                    "available": freshness.has_runtime,
                    "freshness": freshness.state.value,
                    "snapshot_id": (getattr(ws, "last_runtime_snapshot_id", None) or "")[:12],
                    "ran_at": (getattr(ws, "last_runtime_at", None).isoformat()[:19].replace("T", " ")
                               if getattr(ws, "last_runtime_at", None) else ""),
                }
            except WorkbookIdentityError:
                last_run = {"available": False, "freshness": "NOT_RUN",
                            "snapshot_id": "", "ran_at": ""}
        entry["last_run"] = last_run
        return entry

    return _json({
        "ok": True,
        "react_workspace": {"version": REACT_WORKSPACE_VERSION},
        "projects": [project_entry(r, False) for r in records],
        "references": [project_entry(r, True) for r in references],
        "page": page,
        "page_size": PAGE_SIZE,
        "total": total,
        "total_pages": max(1, math.ceil(total / PAGE_SIZE)),
        "clone_url": "/library/clone/{source_project_id}",
        "csrf_token": generate_csrf_token(),
    })


# ───────────────────────────── workspace shell ─────────────────────────────

@router.get("/model-react/workspace")
async def react_workspace_shell(request: Request, project: str):
    """One coherent authorized shell snapshot for the integrated React workspace."""
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user, record, owner, failure = _resolve_project(request, project)
    if failure is not None:
        return failure
    assert record is not None and owner is not None

    from app.services.project_library_service import is_protected_reference

    try:
        from app.api.v1_1.institutional import get_run_integrity_checks
        from app.v2.post_run_context import PostRunContextChanged, PostRunRequestContext
        from app.workbook.workbook_identity import WorkbookIdentityError

        context = PostRunRequestContext.capture(owner_id=owner, project_id=record.project_id)
        integrity_state, _report = get_run_integrity_checks(owner, record.project_id, context=context)
        payload = {
            "ok": True,
            "react_workspace": {"version": REACT_WORKSPACE_VERSION},
            "project": {"code": record.project_code,
                        "name": getattr(record, "project_name", None) or record.project_code,
                        "project_type": getattr(record, "project_type", None) or "",
                        "template_source": getattr(record, "template_source", None) or "",
                        "protected_reference": is_protected_reference(record)},
            "workbook": {"version": context.identity.workbook_version,
                         "composite_hash": context.identity.composite_hash,
                         "scenario_id": context.workspace.active_scenario_id,
                         "scenario_name": context.workspace.active_scenario_name},
            "freshness": {"state": context.freshness.state.value,
                          "basis": context.freshness.source,
                          "has_runtime": context.freshness.has_runtime,
                          "is_stale": context.freshness.is_stale},
            "identity": None,
            "integrity": None,
            "integrity_available": integrity_state == "AVAILABLE",
            "status_dimensions": None,
            "engine": {"persisted_version": None, "current_version": None,
                       "currency": None, "treatment": "EVIDENCE_ONLY_D2_PENDING"},
        }
        if context.runtime_result is not None and context.freshness.state.value != "NOT_RUN":
            from app.v2.output_workspace_projection import build_output_workspace_safe

            outputs = build_output_workspace_safe(
                runtime_result=context.runtime_result, workspace=context.workspace,
                freshness=context.freshness, last_run_scenario=None,
                integrity_report=None, statement_projection=context.projection.fs)
            payload["identity"] = outputs.get("identity")
            payload["integrity"] = outputs.get("integrity")
            payload["status_dimensions"] = outputs.get("status_dimensions")
            dimensions = outputs.get("status_dimensions") or {}
            payload["engine"] = {"persisted_version": dimensions.get("engine_persisted_version"),
                                 "current_version": dimensions.get("engine_current_version"),
                                 "currency": dimensions.get("engine_currency"),
                                 "treatment": dimensions.get("engine_superseded_treatment")}
        context.validate_current()
        return _json(payload)
    except (PostRunContextChanged, WorkbookIdentityError, PermissionError):
        return _json({"ok": False, "code": "WORKSPACE_UNAVAILABLE",
                      "message": "The workspace changed while the response was assembled. Reload to refresh."}, 503)


# ───────────────────────────── statements (six destinations) ─────────────────────────────

def _column_labels(table: Optional[Mapping[str, Any]]) -> list[str]:
    if not isinstance(table, Mapping):
        return []
    return [str(c.get("label") or "") for c in table.get("columns") or ()]


def _row_texts(row: Mapping[str, Any]) -> list[str]:
    return [str(c.get("text") or "—") if c.get("v") is not None else "—"
            for c in row.get("cells") or ()]


def _sheet_from_tables(table: Any, annual_table: Any, sheet_id: str, label: str) -> dict[str, Any]:
    """Adapt one canonical statement table (+ its annual view) into the harvested
    ``StatementSheet`` shape.  Cells are the server-formatted display strings; a
    missing annual counterpart renders as unavailable dashes, never zeros."""
    if not isinstance(table, Mapping) or not table.get("available"):
        return {"id": sheet_id, "label": label, "title": (table or {}).get("title") or label,
                "unit": "keur", "rows": [], "available": False,
                "note": (table or {}).get("note") or "This Run persisted no such statement.",
                "unavailable": (table or {}).get("unavailable") or []}
    model_periods = _column_labels(table)
    annual_by_key: dict[str, list[str]] = {}
    annual_periods: list[str] = []
    if isinstance(annual_table, Mapping) and annual_table.get("available"):
        annual_periods = _column_labels(annual_table)
        for row in annual_table.get("rows") or ():
            annual_by_key[str(row.get("key"))] = _row_texts(row)
    rows = []
    for row in table.get("rows") or ():
        key = str(row.get("key"))
        rows.append({
            "id": key,
            "label": str(row.get("label") or ""),
            "model": _row_texts(row),
            "annual": annual_by_key.get(key, ["—"] * len(annual_periods)),
            "kind": "metric" if row.get("total") else "detail",
        })
    return {"id": sheet_id, "label": label, "title": table.get("title") or label,
            "unit": (table.get("rows") or [{}])[0].get("unit", "keur") if table.get("rows") else "keur",
            "rows": rows, "available": bool(table.get("rows")),
            "note": table.get("note") or "", "unavailable": table.get("unavailable") or [],
            "_model_periods": model_periods, "_annual_periods": annual_periods}


def _simple_table_sheet(table: Any, sheet_id: str, label: str) -> dict[str, Any]:
    """Same adaptation for the single-view canonical tables (CFADS)."""
    return _sheet_from_tables(table, None, sheet_id, label)


def _period_band(labels: list[str]) -> list[dict[str, Any]]:
    """Canonical period bands: one band per calendar year, in server label order.
    Computed from the canonical column labels only — no client date arithmetic."""
    bands: list[dict[str, Any]] = []
    for label in labels:
        year = label[-4:] if len(label) >= 4 and label[-4:].isdigit() else label
        if bands and bands[-1]["label"] == year:
            bands[-1]["span"] += 1
        else:
            bands.append({"label": year, "span": 1})
    return bands


def _debt_sheet(outputs: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Debt destination.  Aggregate PF-waterfall Senior lines render as the sheet;
    the Run's own F3 facility schedules render as ``debtRowsByFacility``."""
    debt = outputs.get("debt") or {}
    if not isinstance(debt, Mapping) or debt.get("mode") == "UNAVAILABLE":
        sheet = {"id": "debt", "label": "Debt", "title": "Debt schedules", "unit": "keur",
                 "rows": [], "available": False,
                 "note": (debt or {}).get("note") or "This Run persisted no debt schedule.",
                 "unavailable": []}
        return sheet, {}
    by_facility: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    model_periods: list[str] = []
    for facility in debt.get("facilities") or ():
        operating = facility.get("operating") or {}
        if not operating.get("available"):
            continue
        fid = str(facility.get("id") or "senior")
        facility_rows = [{"id": str(r.get("key")), "label": f"{facility.get('label')} — {r.get('label')}",
                          "model": _row_texts(r), "annual": [],
                          "kind": "metric" if r.get("total") else "detail"}
                         for r in operating.get("rows") or ()]
        by_facility[fid] = facility_rows
        if not rows:
            rows = facility_rows
            model_periods = [str(c.get("label") or "") for c in operating.get("columns") or ()]
    if not rows:
        sheet = {"id": "debt", "label": "Debt", "title": "Debt schedules", "unit": "keur",
                 "rows": [], "available": False,
                 "note": debt.get("note") or "No facility schedule persisted.", "unavailable": []}
        return sheet, {}
    sheet = {"id": "debt", "label": "Debt", "title": "Debt schedules", "unit": "keur",
             "rows": rows, "available": True, "note": debt.get("note") or "",
             "unavailable": []}
    return sheet, {"by_facility": by_facility, "model_periods": model_periods}


@router.get("/model-react/statements")
async def react_workspace_statements(request: Request, project: str):
    """The six canonical statement destinations for the harvested React workbook."""
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user, record, owner, failure = _resolve_project(request, project)
    if failure is not None:
        return failure
    assert record is not None and owner is not None

    try:
        from app.api.v1_1.institutional import get_run_integrity_checks
        from app.persistence.scenario_insight_reads import resolve_last_run_scenario
        from app.v2.output_workspace_projection import build_output_workspace_safe
        from app.v2.post_run_context import PostRunContextChanged, PostRunRequestContext
        from app.workbook.workbook_identity import WorkbookIdentityError

        context = PostRunRequestContext.capture(owner_id=owner, project_id=record.project_id)
        integrity_state, report = get_run_integrity_checks(owner, record.project_id, context=context)
        state = context.freshness.state.value
        outputs: dict[str, Any] = {"statements": [], "cfads": None, "debt": None, "returns": None,
                                   "identity": None, "integrity": None, "status_dimensions": None,
                                   "state": "NOT_RUN"}
        if context.runtime_result is not None and state != "NOT_RUN":
            from app.persistence.scenario_insight_reads import resolve_last_run_scenario as _rlr
            last_run_scenario = _rlr(
                owner, record.project_id,
                getattr(context.workspace, "last_runtime_scenario_id", None)).label
            outputs = build_output_workspace_safe(
                runtime_result=context.runtime_result, workspace=context.workspace,
                freshness=context.freshness, last_run_scenario=last_run_scenario,
                integrity_report=report if integrity_state == "AVAILABLE" else None,
                statement_projection=context.projection.fs)

        statements = outputs.get("statements") or []
        pl = _sheet_from_tables(statements[0] if len(statements) > 0 else None,
                                statements[0].get("annual") if len(statements) > 0 else None,
                                "pl", "Profit & Loss")
        balance = _sheet_from_tables(statements[1] if len(statements) > 1 else None,
                                     statements[1].get("annual") if len(statements) > 1 else None,
                                     "balance", "Balance Sheet")
        cashflow = _sheet_from_tables(statements[2] if len(statements) > 2 else None,
                                      statements[2].get("annual") if len(statements) > 2 else None,
                                      "cashflow", "Cash Flow (PF waterfall)")
        cfads = _simple_table_sheet(outputs.get("cfads"), "cfads", "CFADS")
        debt_sheet, debt_facilities = _debt_sheet(outputs)
        returns = outputs.get("returns") or {}
        distributions = returns.get("distributions") or {}
        sponsor = _simple_table_sheet(
            distributions if distributions.get("available") else None, "sponsor", "Sponsor Returns")

        def periods_of(sheet: dict[str, Any]) -> tuple[list[str], list[str]]:
            return sheet.pop("_model_periods", []), sheet.pop("_annual_periods", [])

        model_periods, annual_periods = periods_of(pl)
        for sheet in (balance, cashflow, cfads, debt_sheet, sponsor):
            mp, ap = periods_of(sheet)
            model_periods = model_periods or mp
            annual_periods = annual_periods or ap
        debt_periods = debt_facilities.get("model_periods") or []
        if not model_periods:
            model_periods = debt_periods

        identity = outputs.get("identity") or {}
        dimensions = outputs.get("status_dimensions") or {}
        snapshot = {
            "annualPeriods": annual_periods,
            "modelPeriods": model_periods,
            "periodBands": _period_band(model_periods),
            "sheets": [pl, balance, cashflow, cfads, debt_sheet, sponsor],
            "debtRowsByFacility": debt_facilities.get("by_facility") or {},
        }
        status = {
            "label": "Last Run",
            "runId": (identity.get("snapshot_id") or "")[:12] or "Not supplied",
            "freshness": state.lower() if state in ("CURRENT", "STALE") else "not run",
            "integrity": "not evaluated",
            "engineVersion": (identity.get("engine_version") or None) if isinstance(identity, Mapping) else None,
            "dataOrigin": "caller-provided",
        }
        payload = {
            "ok": True,
            "react_workspace": {"version": REACT_WORKSPACE_VERSION},
            "project": {"code": record.project_code,
                        "name": getattr(record, "project_name", None) or record.project_code,
                        "protected_reference": False},
            "state": outputs.get("state") or ("NOT_RUN" if state == "NOT_RUN" else "UNAVAILABLE"),
            "message": ("" if outputs.get("state") not in (None, "UNAVAILABLE")
                        else "The persisted Run evidence could not be projected; nothing is estimated."),
            "snapshot": snapshot if outputs.get("state") in ("CURRENT", "STALE") else None,
            "status": status,
            "results": {"available": bool(returns.get("available")),
                        "metrics": returns.get("metrics") or [],
                        "distributions": distributions,
                        "sponsor_table": returns.get("sponsor"),
                        "sponsor_source": returns.get("sponsor_source"),
                        "distribution_source": returns.get("distribution_source"),
                        "scenario": identity.get("scenario") if isinstance(identity, Mapping) else None,
                        "ran_at": identity.get("ran_at") if isinstance(identity, Mapping) else None,
                        "engine_version": identity.get("engine_version") if isinstance(identity, Mapping) else None},
            "freshness": {"state": state, "basis": context.freshness.source,
                          "is_stale": context.freshness.is_stale},
            "integrity": outputs.get("integrity"),
            "integrity_available": integrity_state == "AVAILABLE",
            "status_dimensions": dimensions,
            "banner": outputs.get("banner") or "",
        }
        context.validate_current()
        return _json(payload)
    except (PostRunContextChanged, WorkbookIdentityError, PermissionError):
        return _json({"ok": False, "code": "WORKSPACE_UNAVAILABLE",
                      "message": "The workspace changed while the response was assembled. Reload to refresh."}, 503)


# ───────────────────────────── inputs grid ─────────────────────────────

def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


@router.get("/model-react/inputs")
async def react_workspace_inputs(request: Request, project: str):
    """The canonical Hybrid Inputs grid projection, serialized for the React grid.

    Same builder the legacy grid panel renders (``_build_input_grid_ctx``); the ONLY
    write path remains the existing ``POST /v2/workbook/grid/save``.
    """
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user, record, owner, failure = _resolve_project(request, project)
    if failure is not None:
        return failure
    assert record is not None and owner is not None

    from app.persistence.workspace_repository import get_workspace_state
    from app.services.project_library_service import is_protected_reference

    ws = get_workspace_state(owner, record.project_id)
    if ws is None:
        return _json({"ok": False, "code": "WORKSPACE_NOT_FOUND"}, 404)
    from app.v2.router import _build_input_grid_ctx

    try:
        ctx = _build_input_grid_ctx(record, _pis_with_identity(record, owner, ws), ws, owner,
                                    project_editable=not is_protected_reference(record))
        projection = _jsonable(ctx.get("input_grid"))
    except Exception:  # noqa: BLE001 - presentation adapter fails closed, never fabricates
        return _json({"ok": False, "code": "GRID_PROJECTION_UNAVAILABLE",
                      "message": "The input grid could not be projected. Reload to refresh."}, 503)

    from app.workbook.input_set import ProjectInputSet
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get, WorkbookIdentityError

    try:
        identity = assemble_consistent_for_get(owner, record.project_id, WORKBOOK.version)
        composite_hash = identity.composite_hash
    except WorkbookIdentityError:
        return _json({"ok": False, "code": "WORKSPACE_UNAVAILABLE",
                      "message": "The workspace identity could not be assembled. Reload to refresh."}, 503)
    return _json({
        "ok": True,
        "react_workspace": {"version": REACT_WORKSPACE_VERSION},
        "project": {"code": record.project_code,
                    "name": getattr(record, "project_name", None) or record.project_code,
                    "protected_reference": is_protected_reference(record)},
        "grid": projection,
        "save": {"url": "/v2/workbook/grid/save",
                 "csrf_token": generate_csrf_token(),
                 "content_hash": composite_hash,
                 "workbook_version": WORKBOOK.version,
                 "scenario_id": ws.active_scenario_id,
                 "max_cells": 50,
                 "max_value_chars": 64},
        "cost_line_boundary": {
            "note": "CAPEX/OPEX line items are NOT saved through the scalar grid writer; "
                    "their canonical batch writer (grid/cost-lines/save) is out of this PR's scope.",
            "capex_opex_editable": False,
        },
    })


def _pis_with_identity(record, owner: str, ws):
    """Same PIS assembly the legacy grid panel uses before rendering."""
    from app.v2.router import _build_pis_with_composite_identity

    return _build_pis_with_composite_identity(ws, record, owner)
