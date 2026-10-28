"""RC-UX (Audit A GAP-R17) — read-only construction-timing planner for the React Inputs > Studios.

The workbook's authoritative inputs are the Commercial Operation Date (``cod_date``) and the Construction Duration in months
(``construction_months``).  The construction START is DERIVED (COD minus the duration, month-end clamped) and the engine requires
``start + duration == COD``.  This module does the calendar arithmetic ON THE SERVER with the model's own convention
(``dateutil.relativedelta``: N calendar months, the day clamped to the last day of a shorter month), so the browser performs no date arithmetic:

* ``GET /model-react/construction-timing?project=CODE`` — the saved COD, duration, the derived start and whether the engine can reproduce it.
* ``... &start=YYYY-MM-DD&months=N`` — plan a COD from a start date and a duration (start-driven mode).
* ``... &start=YYYY-MM-DD&end=YYYY-MM-DD`` — plan from a start and an explicit end (the duration must be a whole number of months).

Nothing is saved: the plan returns the two field values the user may then Save through the existing atomic grid writer.  A combination the engine could
not reproduce exactly is refused here, with the nearest representable end dates, instead of failing at the next Run.
Feature flag: ``FINCO_MODEL_REACT_V1``.
"""
from __future__ import annotations

import calendar
from datetime import date
from typing import Any, Optional

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import resolve_request_session
from app.v2.react_poc_router import react_poc_enabled

router = APIRouter()

COD_FIELD = "project_setup.technical.cod_date"
MONTHS_FIELD = "project_setup.technical.construction_months"
MIN_MONTHS, MAX_MONTHS = 1, 120


def _json(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "private, no-store"})


def parse_iso(text: Any) -> Optional[date]:
    try:
        value = str(text or "").strip()
        return date.fromisoformat(value) if len(value) == 10 else None
    except ValueError:
        return None


def add_months(day: date, months: int) -> date:
    return day + relativedelta(months=months)


def representable(cod: date, months: int) -> bool:
    """The engine's rule: (COD - n months) + n months must give back the COD."""
    return add_months(add_months(cod, -months), months) == cod


def whole_months_between(start: date, end: date) -> Optional[int]:
    n = (end.year - start.year) * 12 + (end.month - start.month)
    return n if n > 0 and add_months(start, n) == end else None


def describe(months: int) -> str:
    if months % 12 == 0:
        years = months // 12
        return f"{years} year" + ("" if years == 1 else "s")
    return f"{months} month" + ("" if months == 1 else "s")


def suggestions(cod: date, months: int) -> list[str]:
    """Nearest end dates the engine can reproduce for this duration: the last day of the month, then the same day one month earlier / later."""
    last = date(cod.year, cod.month, calendar.monthrange(cod.year, cod.month)[1])
    out: list[str] = []
    for candidate in (last, add_months(cod, -1), add_months(cod, 1)):
        if candidate != cod and representable(candidate, months) and candidate.isoformat() not in out:
            out.append(candidate.isoformat())
    return out


def plan(*, start: Optional[date], months: Optional[int], end: Optional[date], saved_cod: Optional[date], saved_months: Optional[int]) -> dict[str, Any]:
    """The server's plan for a candidate (start + months) or (start + end); never saved here."""
    if start is None:
        return {"ok": False, "message": "Enter a valid start date."}
    if end is not None and months is None:
        months = whole_months_between(start, end)
        if months is None:
            return {"ok": False, "message": "The end date must be a whole number of months after the start date."}
    if months is None or not isinstance(months, int):
        return {"ok": False, "message": "Enter a positive duration that is a whole number of months (for example 15 years or 18 months)."}
    if not MIN_MONTHS <= months <= MAX_MONTHS:
        return {"ok": False, "message": f"Construction can last from {MIN_MONTHS} to {MAX_MONTHS} months."}
    cod = end if end is not None else add_months(start, months)
    if cod <= start:
        return {"ok": False, "message": "The end date must be after the start date."}
    if not representable(cod, months):
        return {"ok": False, "message": f"This end date cannot be represented exactly with a {describe(months)} duration (month-end). Choose another date or duration.",
                "suggestions": suggestions(cod, months)}
    derived = add_months(cod, -months)
    return {"ok": True, "cod_date": cod.isoformat(), "construction_months": months, "duration": describe(months), "derived_start": derived.isoformat(),
            "month_end_adjusted": derived != start,
            "changed": (saved_cod is None or saved_months is None or cod != saved_cod or months != saved_months),
            "cells": [{"field_id": COD_FIELD, "value": cod.isoformat()}, {"field_id": MONTHS_FIELD, "value": str(months)}]}


@router.get("/model-react/construction-timing")
async def react_construction_timing(request: Request, project: str = "", start: str = "", months: str = "", end: str = ""):
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user = resolve_request_session(request)
    if user is None:
        return _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.project_library_service import is_protected_reference
    from app.workbook.service import WorkbookService

    record, owner = resolve_accessible_project(user.user_id, (project or "").strip())
    if record is None:
        return _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    ws = get_workspace_state(owner, record.project_id)
    if ws is None:
        return _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    try:
        pis = WorkbookService.build_draft_input_set_from_workspace(ws)
        saved_cod, raw_months = parse_iso(pis.get(COD_FIELD)), pis.get(MONTHS_FIELD)
        saved_months = int(float(str(raw_months))) if raw_months not in (None, "") and float(str(raw_months)).is_integer() else None
    except Exception:  # noqa: BLE001 - never invent timing
        return _json({"ok": False, "code": "TIMING_UNAVAILABLE", "message": "The construction timing could not be read. Reload to try again."}, 503)
    saved: dict[str, Any] = {"cod_date": saved_cod.isoformat() if saved_cod else None, "construction_months": saved_months}
    if saved_cod is not None and saved_months is not None and MIN_MONTHS <= saved_months <= MAX_MONTHS:
        derived = add_months(saved_cod, -saved_months)
        saved.update({"derived_start": derived.isoformat(), "duration": describe(saved_months), "engine_reproducible": representable(saved_cod, saved_months),
                      "month_end_adjusted": derived.day != saved_cod.day})
    else:
        saved.update({"derived_start": None, "duration": None, "engine_reproducible": False, "month_end_adjusted": False})
    payload: dict[str, Any] = {"ok": True, "project": {"code": record.project_code, "protected_reference": is_protected_reference(record)},
                               "saved": saved, "limits": {"min_months": MIN_MONTHS, "max_months": MAX_MONTHS}, "plan": None,
                               "basis": "Dates are calculated by the server with the model's calendar-month convention. Nothing is saved until you press Save."}
    if start.strip():
        try:
            month_count = int(months) if months.strip() and float(months).is_integer() else None
        except ValueError:
            month_count = None
        payload["plan"] = plan(start=parse_iso(start), months=month_count, end=parse_iso(end) if end.strip() else None,
                               saved_cod=saved_cod, saved_months=saved_months)
    return _json(payload)
