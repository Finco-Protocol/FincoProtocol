"""Read-only V3 Run & Scenario workspace.

One GET-only HTMX partial. Project-scoped authorized reads, immutable Run
evidence, no new repository, no write/Run/Save routes.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.v2.run_workspace_v3_projection import (
    build_kpi_sections, build_lineage, build_period_grid,
)

router = APIRouter()
NO_STORE = {"Cache-Control": "private, no-store"}
MAX_SELECT = 3
MAX_ID = 128
HISTORY_LIMIT = 25


def _error(status: int, reason: str) -> HTMLResponse:
    return HTMLResponse(
        f'<p role="alert">{reason}</p>', status_code=status, headers=NO_STORE)


def _history_side(entry, *, state: str = "HISTORICAL") -> dict:
    return {
        "entry": entry, "id": entry.history_id,
        "snapshot_id": entry.runtime_snapshot_id,
        "scenario": entry.active_scenario_name or "UNAVAILABLE",
        "ran_at": entry.ran_at, "origin": entry.runtime_origin or "UNAVAILABLE",
        "engine_version": entry.engine_version or "UNAVAILABLE",
        "workbook_version": entry.workbook_version or "UNAVAILABLE",
        "runtime_summary": entry.runtime_summary,
        "debt_schedule": entry.debt_schedule,
        "sponsor_schedule": entry.sponsor_schedule,
        "distribution_schedule": entry.distribution_schedule,
        "integrity_evidence": entry.integrity_evidence,
        "last_runtime_identity": entry.last_runtime_identity,
        "composite_hash": entry.composite_hash,
        "state": state,
        "history_id": entry.history_id,
    }


def _last_side(ws, entry, *, freshness: str) -> dict:
    if entry is not None:
        data = _history_side(entry, state=freshness)
        data["id"] = "last"
        return data
    identity = getattr(ws, "last_runtime_identity", None) or {}
    # The run-bound identity, never the current active scenario selection.
    return {
        "entry": None, "id": "last",
        "snapshot_id": getattr(ws, "last_runtime_snapshot_id", None),
        "scenario": identity.get("scenario_name") or "UNAVAILABLE",
        "ran_at": getattr(ws, "last_runtime_at", None),
        "origin": identity.get("runtime_origin") or "UNAVAILABLE",
        "engine_version": identity.get("engine_version") or "UNAVAILABLE",
        "workbook_version": identity.get("workbook_version") or "UNAVAILABLE",
        "runtime_summary": getattr(ws, "last_runtime_summary", None) or {},
        "debt_schedule": getattr(ws, "last_debt_schedule", None) or {},
        "sponsor_schedule": getattr(ws, "last_sponsor_schedule", None) or {},
        "distribution_schedule": getattr(ws, "last_distribution_schedule", None) or {},
        "integrity_evidence": getattr(ws, "last_integrity_evidence", None) or {},
        "last_runtime_identity": identity,
        "composite_hash": getattr(ws, "last_runtime_composite_hash", None),
        "state": freshness, "history_id": None,
    }


@router.get("/workbook/run-workspace-v3", response_class=HTMLResponse)
async def run_workspace_v3(request: Request, project: Optional[str] = None):
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.run_history_repository import (
        RunHistoryError, get_run_history, get_run_history_entry,
    )
    from app.v2.router import (
        _build_pis_with_composite_identity, _get_current_user, _templates,
    )
    from app.services.project_library_service import is_protected_reference
    from app.workbook.runtime_authority import resolve_runtime_freshness

    user = _get_current_user(request)
    if not user:
        return _error(401, "Unauthenticated.")
    code = (project or "").strip()
    if not code or len(code) > 160:
        return _error(400, "Project required.")
    record, owner = resolve_accessible_project(user.user_id, code)
    if record is None:
        return _error(404, "Project not found.")
    if is_protected_reference(record):
        return _error(409, "Create a Working Copy of this protected reference to compare Runs.")
    ws = get_workspace_state(user_id=owner, project_id=record.project_id)
    if ws is None:
        return _error(404, "No workspace state.")

    params = request.query_params
    requested = [value.strip() for value in params.getlist("run") if value.strip()]
    if len(requested) > MAX_SELECT or any(len(value) > MAX_ID for value in requested):
        return _error(422, "RUN_WORKSPACE_SELECTION_INVALID")
    if len(set(requested)) != len(requested):
        return _error(422, "RUN_WORKSPACE_DUPLICATE_RUN")

    try:
        history = list(get_run_history(owner, record.project_id, limit=HISTORY_LIMIT))
    except RunHistoryError:
        return _error(422, "RUN_HISTORY_PAYLOAD_MALFORMED")

    last_snapshot = str(getattr(ws, "last_runtime_snapshot_id", "") or "")
    has_last = bool(last_snapshot and getattr(ws, "last_runtime_at", None))
    last_entry = next((e for e in history if
                       last_snapshot and e.runtime_snapshot_id == last_snapshot), None)
    if "run" not in params and "reference" not in params:
        candidate = ["last"] if has_last else []
        candidate += [e.history_id for e in history if not (
            has_last and e.runtime_snapshot_id == last_snapshot)]
        requested = candidate[:2]

    if len(requested) > MAX_SELECT:
        return _error(422, "RUN_WORKSPACE_SELECTION_INVALID")

    entries = {}
    for selection in requested:
        if selection == "last":
            if not has_last:
                return _error(422, "LAST_RUN_UNAVAILABLE")
            continue
        try:
            entry = get_run_history_entry(owner, record.project_id, selection)
        except RunHistoryError:
            return _error(422, "RUN_HISTORY_PAYLOAD_MALFORMED")
        if entry is None:
            return _error(404, "Run not found in this authorized project.")
        entries[selection] = entry

    # One committed snapshot cannot occupy two comparison columns, even if
    # canonical Last and the ledger expose different selector identifiers.
    if has_last and "last" in requested and any(
        e.runtime_snapshot_id == last_snapshot for e in entries.values()
    ):
        return _error(422, "RUN_WORKSPACE_DUPLICATE_SNAPSHOT")
    snapshots = [e.runtime_snapshot_id for e in entries.values()]
    if len(set(snapshots)) != len(snapshots):
        return _error(422, "RUN_WORKSPACE_DUPLICATE_SNAPSHOT")

    pis = _build_pis_with_composite_identity(ws, record, owner)
    freshness = resolve_runtime_freshness(
        ws, current_composite_hash=pis.content_hash).state.value
    if freshness not in ("CURRENT", "STALE"):
        freshness = "UNAVAILABLE"

    sides = [
        _last_side(ws, last_entry, freshness=freshness)
        if selection == "last" else _history_side(entries[selection])
        for selection in requested
    ]
    raw_reference = params.get("reference", "")
    reference_id = raw_reference or (requested[0] if requested else "")
    if reference_id not in requested and requested:
        return _error(422, "RUN_WORKSPACE_REFERENCE_INVALID")
    reference = requested.index(reference_id) if requested else 0

    try:
        offset = int(params.get("offset", "0"))
        if not 0 <= offset <= 10000:
            raise ValueError()
    except (ValueError, TypeError):
        return _error(422, "RUN_WORKSPACE_OFFSET_INVALID")
    changed = params.get("changed") == "1"
    unavailable = params.get("unavailable") == "1"

    for side in sides:
        evidence = side.get("integrity_evidence")
        try:
            from app.v2.credit_decision_projection import _integrity, RunInput
            if side["entry"] is not None:
                integrity = _integrity(RunInput(entry=side["entry"]))
                side["integrity"] = integrity["status"]
            else:
                side["integrity"] = "UNAVAILABLE"   # no invented ledger evidence
        except Exception:
            side["integrity"] = "UNAVAILABLE"
        side["evidence"] = ("RECORDED" if evidence else "PARTIAL / UNAVAILABLE")
        side["detail_url"] = (
            "/v2/workbook/run-history/detail?" + urlencode(
                {"project": record.project_code, "history_id": side["history_id"]})
            if side["history_id"] else
            "/v2/workbook?" + urlencode({"project": record.project_code}))
        side["statements_url"] = (
            "/v2/workbook/run-history/statements?" + urlencode(
                {"project": record.project_code, "history_id": side["history_id"]})
            if side["history_id"] else
            "/v2/workbook?" + urlencode({"project": record.project_code}) + "#outputs")

    sections, lineage, periods = [], [], None
    if len(sides) in (2, 3):
        try:
            sections = build_kpi_sections(sides, reference, changed, unavailable)
            lineage = build_lineage(sides, reference)
            periods = build_period_grid(sides, reference, changed, unavailable, offset)
        except (ValueError, TypeError, KeyError):
            return _error(422, "RUN_WORKSPACE_EVIDENCE_INVALID")

    options = []
    if has_last:
        options.append({
            "id": "last", "label": "Canonical Last Run · " + str(
                getattr(ws, "last_runtime_at", "") or "")[:19],
            "state": freshness,
        })
    for entry in history:
        options.append({
            "id": entry.history_id,
            "label": str(entry.ran_at or "")[:16] + " · " +
                     str(entry.active_scenario_name or "UNAVAILABLE") +
                     " · " + entry.history_id[:8],
            "state": "HISTORICAL",
        })

    next_url = None
    if periods is not None and periods["next_offset"] is not None:
        args = [("project", record.project_code)] + [("run", rid) for rid in requested]
        args += [("reference", reference_id), ("offset", str(periods["next_offset"]))]
        if changed:
            args.append(("changed", "1"))
        if unavailable:
            args.append(("unavailable", "1"))
        next_url = "/v2/workbook/run-workspace-v3?" + urlencode(args)

    return _templates.TemplateResponse(
        request=request, name="partials/run_workspace_v3.html",
        context={
            "project_code": record.project_code, "project_name": record.project_name,
            "options": options, "selected": requested,
            "slots": (requested + ["", "", ""])[:3],
            "reference_id": reference_id, "sides": sides, "reference": reference,
            "sections": sections, "lineage": lineage, "periods": periods,
            "changed": changed, "unavailable": unavailable, "next_url": next_url,
        }, headers=NO_STORE)
