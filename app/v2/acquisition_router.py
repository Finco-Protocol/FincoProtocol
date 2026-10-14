"""M6 underwriting workspace, release-closed financial outputs, committed-source only."""
from __future__ import annotations

from datetime import date
import math

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.model_v2.acquisition.economics import (
    ACTIVATION_ENABLED, STATUS, AcquisitionPolicyError, AcquisitionTerms,
    TRANSACTION, SHL_POLICY,
)
from app.model_v2.acquisition.evidence import (
    KEY, AcquisitionEvidenceError, validate as validate_evidence,
)
from app.persistence.acquisition_repository import (
    AcquisitionCaseConflict, make_document, read_case, list_cases, save_case,
)

router = APIRouter()


def _num(raw, name):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise AcquisitionCaseConflict("CASE_" + name + "_INVALID") from None
    if not math.isfinite(value):
        raise AcquisitionCaseConflict("CASE_" + name + "_NONFINITE")
    return value


def _terms(form):
    try:
        close = date.fromisoformat(str(form.get("closing_date") or ""))
        exit_raw = str(form.get("exit_date") or "").strip()
        exit_date = date.fromisoformat(exit_raw) if exit_raw else None
    except ValueError:
        raise AcquisitionCaseConflict("CASE_DATE_INVALID") from None
    value = str(form.get("exit_proceeds_keur") or "").strip()
    terms = AcquisitionTerms(
        closing_date=close,
        purchase_price_keur=_num(form.get("purchase_price_keur"), "purchase_price"),
        transaction_costs_keur=_num(form.get("transaction_costs_keur"), "transaction_costs"),
        buyer_discount_rate=_num(form.get("buyer_discount_rate"), "buyer_discount_rate"),
        target_buyer_irr=_num(form.get("target_buyer_irr"), "target_buyer_irr"),
        bid_lower_bound_keur=_num(form.get("bid_lower_bound_keur"), "bid_lower"),
        bid_upper_bound_keur=_num(form.get("bid_upper_bound_keur"), "bid_upper"),
        closing_adjustment_keur=_num(form.get("closing_adjustment_keur"), "closing_adjustment"),
        exit_date=exit_date, exit_proceeds_keur=_num(value, "exit_proceeds") if value else None,
        ownership_fraction=1.0, transaction_type=TRANSACTION,
        shl_policy=SHL_POLICY, future_funding_policy="SOURCE_PROVEN_EQUITY_CALLS",
    )
    terms.check()
    return terms


def _record(request, project):
    from app.v2.router import _get_current_user
    from app.persistence.projects_repository import resolve_accessible_project
    user = _get_current_user(request)
    if not user:
        return None, None, None
    record, owner = resolve_accessible_project(user.user_id, project)
    return user, record, owner


def _history_entry(owner, record, history_id):
    from app.persistence.run_history_repository import get_run_history_entry
    entry = get_run_history_entry(owner, record.project_id, history_id)
    if entry is None:
        raise AcquisitionCaseConflict("CASE_SOURCE_RUN_UNAVAILABLE")
    return entry


def _run_evidence(entry, owner, project_id):
    raw = (entry.runtime_summary or {}).get(KEY)
    if raw is None:
        return None, "EVIDENCE_UNAVAILABLE"
    try:
        evidence = validate_evidence(
            raw, owner_id=owner, project_id=project_id,
            snapshot_id=entry.runtime_snapshot_id, composite_hash=entry.composite_hash,
            scenario_id=entry.last_runtime_scenario_id)
        return evidence, "AVAILABLE_SOURCE_FACTS"
    except (AcquisitionEvidenceError, KeyError, TypeError, ValueError) as exc:
        return None, str(exc)


@router.get("/valuation-acquisition", response_class=HTMLResponse)
async def acquisition_page(request: Request, project: str = "", history_id: str = "",
                           case_id: str = "", saved: str = ""):
    from app.auth import generate_csrf_token
    from app.persistence.run_history_repository import get_run_history
    from app.ui.protected_reference_service import is_protected_reference
    from main_web import templates

    user, record, owner = _record(request, project)
    if user is None:
        return RedirectResponse("/login", status_code=302)
    if record is None:
        return HTMLResponse("Project not found.", status_code=404)
    try:
        history = get_run_history(owner, record.project_id, limit=25)
        cases = list_cases(owner_id=owner, project_id=record.project_id)
        stored = read_case(owner_id=owner, project_id=record.project_id, case_id=case_id) if case_id else None
        if case_id and stored is None:
            return HTMLResponse("Acquisition case not found.", status_code=404)
        if stored:
            history_id = stored["document"]["source"]["history_id"]
        if not history_id and history:
            history_id = history[0].history_id
        selected = _history_entry(owner, record, history_id) if history_id else None
        evidence, evidence_status = (
            _run_evidence(selected, owner, record.project_id)
            if selected else (None, "EVIDENCE_UNAVAILABLE"))
        source_outdated = bool(stored and history
                               and history[0].history_id != history_id)
        if stored and selected:
            doc = stored["document"]["source"]
            if (selected.runtime_snapshot_id, selected.composite_hash,
                selected.last_runtime_scenario_id) != (
                doc["snapshot_id"], doc["composite_hash"], doc["scenario_id"]):
                evidence_status = "CASE_SOURCE_IDENTITY_MISMATCH"
                evidence = None
        # IMPORTANT: no call to evaluate() or enterprise_equity_bridge() on GET.
        # These remain release-closed, tested offline, and NOT model KPIs.
        from dataclasses import asdict
        defaults = asdict(AcquisitionTerms(
            closing_date=date.today(), purchase_price_keur=0.0,
            transaction_costs_keur=0.0, buyer_discount_rate=0.1,
            target_buyer_irr=0.1, bid_lower_bound_keur=0.0,
            bid_upper_bound_keur=100000.0))
        values = stored["document"]["terms"] if stored else defaults
        return templates.TemplateResponse(request=request, name="v2/acquisition.html",
            context={
                "project_code": record.project_code,
                "project_name": record.project_name,
                "history": history, "history_id": history_id, "selected": selected,
                "cases": cases, "stored": stored, "values": values,
                "source_outdated": source_outdated,
                "evidence_status": evidence_status,
                "evidence_rows": evidence["equity_periods"] if evidence else (),
                "project_rows": evidence["project_cashflows"] if evidence else (),
                "status": STATUS, "release_closed": not ACTIVATION_ENABLED,
                "readonly": is_protected_reference(record),
                "csrf_token": generate_csrf_token(), "saved": saved == "1",
            }, headers={"Cache-Control": "private, no-store"})
    except (AcquisitionCaseConflict, ValueError, TypeError) as exc:
        return HTMLResponse("UNAVAILABLE: " + str(exc), status_code=409,
                            headers={"Cache-Control": "private, no-store"})


@router.post("/valuation-acquisition/save")
async def acquisition_save(request: Request):
    from app.auth import validate_csrf_token
    from app.ui.protected_reference_service import is_protected_reference
    from app.v2.router import _get_current_user
    user = _get_current_user(request)
    if user is None:
        return JSONResponse({"error": "UNAUTHENTICATED"}, status_code=401)
    form = await request.form()
    if not validate_csrf_token(form.get("csrf_token")):
        return JSONResponse({"error": "M6_CSRF_INVALID"}, status_code=403)
    project = str(form.get("project") or "").strip()
    user, record, owner = _record(request, project)
    if record is None:
        return JSONResponse({"error": "PROJECT_NOT_FOUND"}, status_code=404)
    if is_protected_reference(record):
        return JSONResponse({"error": "PROTECTED_REFERENCE"}, status_code=409)
    try:
        history_id = str(form.get("history_id") or "")
        entry = _history_entry(owner, record, history_id)
        evidence, reason = _run_evidence(entry, owner, record.project_id)
        if evidence is None:
            raise AcquisitionCaseConflict(reason)
        existing_id = str(form.get("case_id") or "") or None
        expected_revision = int(str(form.get("expected_revision") or "0"))
        terms = _terms(form)
        document = make_document(entry, terms)
        case_id, revision = save_case(
            owner_id=owner, project_id=record.project_id,
            document=document, case_id=existing_id,
            expected_revision=expected_revision)
        from urllib.parse import urlencode
        return RedirectResponse("/v2/valuation-acquisition?" + urlencode({
            "project": record.project_code, "case_id": case_id, "saved": "1"}),
            status_code=303)
    except (AcquisitionCaseConflict, AcquisitionPolicyError, ValueError, TypeError) as exc:
        return JSONResponse({"error": str(exc), "status": STATUS}, status_code=409,
                            headers={"Cache-Control": "private, no-store"})
