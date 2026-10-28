"""RC-UX (Audit A GAP-R14) — read-only JSON adapter for the React "Compare Projects" page.

The Decision-Support cross-project comparison of the LATEST SUCCESSFUL Last Run of up to five of the user's own projects.  Nothing is calculated here:
the rows are ``app.v2.decision_support_projection.build_cross_project_rows`` / ``sort_cross_project_rows`` over the persisted Last Run summaries, built
from the same per-project payload the Legacy ``/v2/compare-projects`` page assembles.  A project without a successful Run is returned as unavailable
(``runnable`` false, every metric "—"); a template is not a project and is never compared.  Zero database writes, no engine execution.

* ``GET /model-react/compare-projects?code=A&code=B[&sort=metric][&technology=solar]`` — columns, the metric catalog, the picker and what was left out.

Feature flag: ``FINCO_MODEL_REACT_V1``.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from app.v2.react_projects import _gate, _json, _own_records

router = APIRouter()

#: ``sort`` ascends for these (cost-like) metrics, descends for every other one — the Legacy rule.
ASCENDING = ("total_capex_keur", "total_tax_keur")


@router.get("/model-react/compare-projects")
async def react_compare_projects(request: Request, code: list[str] = Query(default=[]), sort: str = "", technology: str = ""):
    user, refused = _gate(request)
    if refused is not None:
        return refused
    from app.model_v2.project_metadata import perspective_value, stage_value
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.project_library_service import is_protected_reference
    from app.v2.decision_support_projection import (
        CROSS_PROJECT_MAX, _CROSS_METRICS, build_cross_project_rows, sort_cross_project_rows,
    )
    from app.v2.react_projects import country_label
    from app.v2.router import _ds_capacity, _ds_country, _ds_meta_label, _ds_run_state

    wanted: list[str] = []
    for raw in code:
        value = str(raw).strip()
        if value and value not in wanted:
            wanted.append(value)
    payloads: list[dict[str, Any]] = []
    left_out: list[dict[str, str]] = []
    resolved = 0
    for value in wanted:
        if resolved >= CROSS_PROJECT_MAX:
            left_out.append({"code": value, "reason": "LIMIT"})
            continue
        record, owner = resolve_accessible_project(user.user_id, value)
        if record is None:
            left_out.append({"code": value, "reason": "NOT_FOUND"})
            continue
        if is_protected_reference(record):
            left_out.append({"code": value, "reason": "TEMPLATE"})          # a template is a starting model, not a project
            continue
        resolved += 1
        try:
            ws = get_workspace_state(owner, record.project_id)
        except Exception:  # noqa: BLE001 - an evidence read failure is "unavailable", never a guess
            ws = None
        ran_at = getattr(ws, "last_runtime_at", None) if ws else None
        base = getattr(record, "baseline_snapshot", None) or {}
        try:
            capacity = float(base.get("capacity_mw")) if base.get("capacity_mw") else None
        except (TypeError, ValueError):
            capacity = None
        payloads.append({
            "project_code": record.project_code, "project_name": record.project_name, "technology": record.project_type or "",
            # React projects store the market as `country_market` (a code); the Legacy `country_iso`/`country` keys are absent.
            "country": (country_label(base.get("country_market")) or _ds_country(record)), "capacity_display": _ds_capacity(record), "capacity_mw": capacity,
            "stage": _ds_meta_label(record, "project_stage", stage_value),
            "perspective": _ds_meta_label(record, "model_perspective", perspective_value),
            "run_state": _ds_run_state(ws, record, owner),
            "run_identity": str(getattr(ws, "last_runtime_composite_hash", "") or "")[:8] if ws else "",
            "runnable": bool(ran_at is not None), "ran_at_display": (str(ran_at)[:16].replace("T", " ") if ran_at else ""),
            "runtime_summary": (getattr(ws, "last_runtime_summary", None) or {}) if ws else {},
            "sponsor_summary": ((getattr(ws, "last_sponsor_schedule", None) or {}).get("summary", {})) if ws else {},
            "debt_summary": ((getattr(ws, "last_debt_schedule", None) or {}).get("summary", {})) if ws else {},
        })
    rows = build_cross_project_rows(payloads)
    metric_keys = {key for key, _label, _kind in _CROSS_METRICS} | {"capex_per_mw"}
    sort_key = sort if sort in metric_keys else ""
    if sort_key:
        rows = sort_cross_project_rows(rows, sort_key, descending=sort_key not in ASCENDING)
    technologies = sorted({r.technology for r in rows if r.technology != "—"})
    if technology:
        rows = [r for r in rows if r.technology == technology]
    run_by_code = {p["project_code"]: p for p in payloads}

    def _moic_overlay(code: str) -> dict[str, str]:
        """MOIC a Run PUBLISHED on its sponsor schedule summary (same source the returns projection and the workbook read).  A value that is
        absent or not a finite number stays unavailable ("—"); nothing is estimated or defaulted to zero."""
        summary = (run_by_code.get(code) or {}).get("sponsor_summary") or {}
        out: dict[str, str] = {}
        for key, source in (("pure_equity_moic", "pure_equity_moic"), ("sponsor_moic", "total_sponsor_moic")):
            raw = summary.get(source)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw == raw and abs(raw) != float("inf"):
                out[key] = f"{float(raw):.2f}x"
        return out
    catalog = [{"key": "total_capex_keur", "label": "Total CAPEX (kEUR)"}, {"key": "capex_per_mw", "label": "CAPEX / MW"}] + [
        {"key": key, "label": label} for key, label, _kind in _CROSS_METRICS if key != "total_capex_keur"]
    picker = [{"code": r.project_code, "name": r.project_name, "technology": r.project_type or ""} for r in _own_records(user.user_id, archived=False)[:100]]
    return _json({
        "ok": True, "max_projects": CROSS_PROJECT_MAX, "metrics": catalog, "sort": sort_key, "technology": technology, "technologies": technologies,
        "columns": [{
            "code": r.project_code, "name": r.project_name, "technology": r.technology, "country": r.country, "capacity": r.capacity_display,
            "stage": r.stage, "perspective": r.perspective, "run_state": r.run_state, "run_identity": r.run_identity, "runnable": r.runnable,
            "ran_at": r.ran_at_display, "ebitda_margin": r.ebitda_margin,
            "metrics": {**dict(r.metrics), **({k: v for k, v in _moic_overlay(r.project_code).items() if dict(r.metrics).get(k) in (None, "", "—")} if r.runnable else {})},
            "run_url": f"/v2/model-react/{r.project_code}#results" if run_by_code.get(r.project_code, {}).get("runnable") else None,
        } for r in rows],
        "left_out": left_out, "picker": picker,
        "basis": "The latest successful Run of each project, as saved. A project without a Run is shown as unavailable; nothing is calculated here.",
    })
