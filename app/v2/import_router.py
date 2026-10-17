"""Workflow C: authenticated read-only CSV/XLSX intake and review surface.

The C0 transaction must pass independent focused acceptance before mutation
routes are enabled. Upload and review never run the financial engine.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.templating import Jinja2Templates

from app.auth import (
    generate_csrf_token, resolve_request_session, validate_csrf_token,
)
from app.model_import.intake import MAX_UPLOAD_BYTES, IntakeError, extract_proposals
from app.model_import.mapping import STRUCTURED_FIELD_OWNERS
from app.model_import.migration_ux import scenario_review_matrix, scenario_review_acknowledged
from app.persistence.projects_repository import resolve_accessible_project
from app.persistence.workspace_repository import get_workspace_state
from app.services.project_library_service import is_protected_reference
from app.utils.workbook_flag import require_v2_active
from app.workbook.input_set import ProjectInputSet
from app.workbook.registry import WORKBOOK
from app.workbook.specs import BindingStatus, FieldKind, SourceOfTruth
from app.workbook.update_service import _assert_batch_field_applicable, BatchApplyError
from app.workbook.workbook_identity import assemble_consistent_for_get

router = APIRouter()
_templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates" / "v2"))


def _field_options(project) -> list[dict]:
    options = []
    for spec in WORKBOOK.all_fields():
        if spec.field_id in STRUCTURED_FIELD_OWNERS:
            continue            # structured documents keep their own writers (Revenue contracts / Financing)
        if (spec.binding_status != BindingStatus.BOUND
                or spec.kind != FieldKind.INPUT
                or spec.source_of_truth != SourceOfTruth.INPUT_SET
                or not spec.editable or not spec.persisted or spec.runtime_only):
            continue
        try:
            _assert_batch_field_applicable(
                spec.field_id, project_type=project.project_type or "",
                template_source=project.template_source or "")
        except BatchApplyError:
            continue
        options.append({
            "id": spec.field_id, "label": spec.label, "unit": spec.unit or "",
            "register_path": spec.engine_path or "",
        })
    return options


EXACT_MAPPING_METHODS = frozenset({"exact_field_id", "unique_exact_registry_label"})


def _context(request, user, project, ws, *, stage, proposals=None, error=None,
             detected=0, totals=None, digest=None):
    pis = ProjectInputSet.from_snapshot(ws.draft_snapshot, workbook=WORKBOOK)
    identity = assemble_consistent_for_get(ws.user_id, project.project_id, WORKBOOK.version)
    rows = []
    from collections import Counter
    from app.workbook.update_service import WorkbookUpdateService
    for p in proposals or []:
        q = dict(p)
        q["current_value"] = pis.get(p["field_id"]) if p["field_id"] else None
        if q["status"] == "ready" and q["normalized_value"] is not None:
            check = WorkbookUpdateService.validate_field_update(q["field_id"], q["normalized_value"])
            if check.is_valid and check.typed_value == q["current_value"]:
                q["status"] = "unchanged"
        # Bulk selection is limited to rows that validated independently: a mapped, normalised, non-duplicate,
        # non-ambiguous target with no outstanding reason.  Everything else needs a deliberate per-row choice.
        q["bulk_selectable"] = bool(
            q.get("field_id") and q.get("normalized_value") is not None and q["status"] in ("ready", "needs_review")
            and not q.get("duplicate_target") and "ambiguous" not in q.get("mapping_method", "")
            and q.get("reason") in (None, "") and q.get("confidence_class") in ("exact", "exact_label", "high", "medium"))
        rows.append(q)
    queue = lambda p: p["status"] in ("unsupported", "unsupported_for_apply", "invalid") or p.get("duplicate_target") or "ambiguous" in p.get("mapping_method", "")  # noqa: E731
    return {
        "request": request, "user": user,
        "project": project, "project_code": project.project_code,
        "stage": stage, "csrf_token": generate_csrf_token(),
        "error": error, "proposals": rows, "detected": detected,
        "totals": dict(Counter(r["status"] for r in rows)) if rows else (totals or {}),
        # UX-026: "exact" is every unambiguous exact match (the field id, or a registry label that matches one field exactly) - the same notion the review
        # table calls "exact label". The counters come only from the proposals the import transaction produced.
        "exact_count": sum(p["mapping_method"] in EXACT_MAPPING_METHODS for p in proposals or []),
        "ambiguous_count": sum("ambiguous" in p["mapping_method"] or p["reason"] == "IMPORT_DUPLICATE_TARGET_REQUIRES_REVIEW" for p in proposals or []),
        "categories": [c for c in ("CAPEX", "OPEX", "REVENUE", "FINANCING", "TAX", "GENERAL", "UNMAPPED")
                       if any(r.get("category") == c for r in rows)],
        "category_counts": dict(Counter(r.get("category") for r in rows)),
        "bulk_selectable_count": sum(r["bulk_selectable"] for r in rows),
        "attention_count": sum(bool(queue(r)) for r in rows),
        "digest": digest or "",
        "content_hash": identity.composite_hash,
        "workbook_version": WORKBOOK.version,
        "active_scenario_id": ws.active_scenario_id,
        "fields": _field_options(project),
        "apply_available": True,
    }


@router.get("/workbook/import", response_class=HTMLResponse)
async def model_input_import_page(request: Request, project: str = "",
                                  _: None = Depends(require_v2_active)):
    user = resolve_request_session(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None or owner != user.user_id or is_protected_reference(record):
        return RedirectResponse(url="/library", status_code=302)
    ws = get_workspace_state(owner, record.project_id)
    if ws is None:
        return RedirectResponse(url="/library", status_code=302)
    return _templates.TemplateResponse(
        request=request, name="import_review.html",
        context=_context(request, user, record, ws, stage="upload"))


@router.post("/workbook/import/preview", response_class=HTMLResponse)
async def model_input_import_preview(
    request: Request,
    project: str = Form(...),
    csrf_token: str = Form(...),
    encoding: str = Form("utf-8-sig"),
    upload: UploadFile = File(...),
    _: None = Depends(require_v2_active),
):
    user = resolve_request_session(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None or owner != user.user_id or is_protected_reference(record):
        return RedirectResponse(url="/library", status_code=302)
    ws = get_workspace_state(owner, record.project_id)
    if ws is None:
        return RedirectResponse(url="/library", status_code=302)
    if not validate_csrf_token(csrf_token):
        return _templates.TemplateResponse(
            request=request, name="import_review.html",
            context=_context(request, user, record, ws, stage="upload", error="IMPORT_CSRF_INVALID"),
            status_code=403)
    try:
        header_length = request.headers.get("content-length")
        if header_length and int(header_length) > MAX_UPLOAD_BYTES + 16 * 1024:
            raise IntakeError("IMPORT_BODY_SIZE_INVALID")
        data = await upload.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise IntakeError("IMPORT_FILE_SIZE_INVALID")
        result = extract_proposals(
            data, upload.filename or "", encoding=encoding,
            project_type=record.project_type or "",
            template_source=record.template_source or "",
        )
        if result["detected"] > 150:
            raise IntakeError("IMPORT_PROPOSAL_LIMIT_EXCEEDED")
        ctx = _context(
            request, user, record, ws, stage="review",
            proposals=result["proposals"], detected=result["detected"],
            totals=result["totals"], digest=hashlib.sha256(data).hexdigest(),
        )
        from app.model_import.review import seal_preview
        ctx["preview_ticket"] = seal_preview(
            owner=owner, project_id=record.project_id,
            scenario_id=ws.active_scenario_id,
            content_hash=ctx["content_hash"], workbook_version=WORKBOOK.version,
            digest=ctx["digest"], proposals=result["proposals"],
        )
        return _templates.TemplateResponse(
            request=request, name="import_review.html", context=ctx)
    except (IntakeError, ValueError) as exc:
        code = getattr(exc, "code", "IMPORT_PARSE_REJECTED")
        return _templates.TemplateResponse(
            request=request, name="import_review.html",
            context=_context(request, user, record, ws, stage="upload", error=code),
            status_code=422)
    finally:
        await upload.close()


@router.post("/workbook/import/confirm", response_class=HTMLResponse)
async def model_input_import_confirm(
    request: Request,
    project: str = Form(...),
    csrf_token: str = Form(...),
    preview_ticket: str = Form(...),
    _: None = Depends(require_v2_active),
):
    """Second explicit review boundary: approve, validate, then seal a final set.

    This route never writes financial inputs or runs a model.
    """
    from app.model_import.review import (
        ImportReviewError, resolve_review, seal_approved,
    )
    user = resolve_request_session(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None or owner != user.user_id or is_protected_reference(record):
        return RedirectResponse(url="/library", status_code=302)
    ws = get_workspace_state(owner, record.project_id)
    if ws is None:
        return RedirectResponse(url="/library", status_code=302)
    if not validate_csrf_token(csrf_token):
        return _templates.TemplateResponse(
            request=request, name="import_review.html",
            context=_context(request, user, record, ws, stage="upload", error="IMPORT_CSRF_INVALID"),
            status_code=403)
    try:
        form = await request.form()
        preview, approved = resolve_review(
            ticket=preview_ticket, owner=owner, project_id=record.project_id,
            selections=form, project_type=record.project_type or "",
            template_source=record.template_source or "",
        )
        current = assemble_consistent_for_get(owner, record.project_id, WORKBOOK.version)
        if (preview["scenario_id"] != ws.active_scenario_id
                or preview["content_hash"] != current.composite_hash
                or preview["workbook_version"] != WORKBOOK.version):
            raise ImportReviewError("IMPORT_PREVIEW_STALE")
        pis = ProjectInputSet.from_snapshot(ws.draft_snapshot, workbook=WORKBOOK)
        for row in approved:
            old = pis.get(row["field_id"])
            row["current_value"] = None if old is None else str(old)
            check = __import__("app.workbook.update_service", fromlist=["WorkbookUpdateService"]).WorkbookUpdateService.validate_field_update(row["field_id"], row["value"])
            row["changed"] = check.typed_value != old
        ctx = _context(request, user, record, ws, stage="confirm")
        ctx["approved"] = approved
        ctx["approved_ticket"] = seal_approved(preview, approved)
        ctx["unchecked_count"] = max(0, len(preview["rows"]) - len(approved))
        ctx["approved_count"] = len(approved)
        ctx["changed_count"] = sum(bool(r["changed"]) for r in approved)
        ctx["migration"] = preview.get("migration")
        ctx["manifest_token"] = str(form.get("manifest_token", "") or "")
        return _templates.TemplateResponse(
            request=request, name="import_review.html", context=ctx)
    except (ImportReviewError, IntakeError, ValueError) as exc:
        code = getattr(exc, "code", "IMPORT_REVIEW_INVALID")
        return _templates.TemplateResponse(
            request=request, name="import_review.html",
            context=_context(request, user, record, ws, stage="upload", error=code),
            status_code=409 if code == "IMPORT_PREVIEW_STALE" else 422)


@router.post("/workbook/import/apply", response_class=HTMLResponse)
async def model_input_import_apply(
    request: Request,
    project: str = Form(...),
    csrf_token: str = Form(...),
    approved_ticket: str = Form(...),
    _: None = Depends(require_v2_active),
):
    """Explicit authenticated Apply: ONLY the C0 canonical batch writer."""
    from app.model_import.review import ImportReviewError, unseal_approved
    from app.workbook.update_service import (
        WorkbookUpdateService, BatchApplyError, FieldValidationError,
        StaleContentError, VersionMismatchError, ProtectedReferenceError,
        NonEditableFieldError, UnknownFieldError,
    )
    user = resolve_request_session(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None or owner != user.user_id or is_protected_reference(record):
        return RedirectResponse(url="/library", status_code=302)
    ws = get_workspace_state(owner, record.project_id)
    if ws is None:
        return RedirectResponse(url="/library", status_code=302)
    if not validate_csrf_token(csrf_token):
        return _templates.TemplateResponse(
            request=request, name="import_review.html",
            context=_context(request, user, record, ws, stage="upload", error="IMPORT_CSRF_INVALID"),
            status_code=403)
    try:
        form = await request.form()
        signed = unseal_approved(approved_ticket, owner=owner, project_id=record.project_id)
        approved = signed["approved"]
        # Capture the exact pre-CAS values for truthful changed-field reporting.
        # The submitted composite CAS prevents a concurrent different snapshot
        # from being applied against this review's approved set.
        before_pis = ProjectInputSet.from_snapshot(ws.draft_snapshot, workbook=WORKBOOK)
        # Server repeats canonical field validation inside the C0 transaction.
        changes = [(item["field_id"], item["value"]) for item in approved]
        WorkbookUpdateService.apply_batch_draft_update(
            ws=ws, updates=changes,
            content_hash=signed["content_hash"],
            workbook_version=signed["workbook_version"],
            expected_scenario_id=signed["scenario_id"],
            project_record=record, actor_user_id=user.user_id,
        )
        fresh = get_workspace_state(owner, record.project_id)
        if fresh is None:
            raise ImportReviewError("IMPORT_POST_APPLY_READ_UNAVAILABLE")
        pis = ProjectInputSet.from_snapshot(fresh.draft_snapshot, workbook=WORKBOOK)
        from app.workbook.runtime_authority import resolve_runtime_freshness
        identity = assemble_consistent_for_get(owner, record.project_id, WORKBOOK.version)
        freshness = resolve_runtime_freshness(
            fresh, current_composite_hash=identity.composite_hash)
        saved = [{
            "field_id": item["field_id"],
            "source": f'{item["sheet"]}!{item["cell"]}',
            "label": item.get("label"), "original_value": item.get("original_value"),
            "source_unit": item.get("source_unit"), "normalization": item.get("normalization"),
            "extracted_unit": item.get("extracted_unit"), "chosen_unit": item.get("chosen_unit"),
            "canonical_unit": item.get("canonical_unit"), "unit_corrected": item.get("unit_corrected"),
            "field_remapped": item.get("field_remapped"), "value_overridden": item.get("value_overridden"),
            "suggested_field_id": item.get("suggested_field_id"), "corrections": item.get("corrections") or [],
            "correction_note": item.get("correction_note"), "mapping_origin": item.get("mapping_origin"),
            "previous_value": before_pis.get(item["field_id"]),
            "method": item.get("method"), "confidence_class": item.get("confidence_class"),
            "explanation": item.get("explanation") or [],
            "actual_value": pis.get(item["field_id"]),
            "approved_value": item["value"],
        } for item in approved]
        ctx = _context(request, user, record, fresh, stage="result")
        ctx["saved"] = saved
        ctx["applied_count"] = sum(
            before_pis.get(item["field_id"]) != pis.get(item["field_id"])
            for item in approved
        )
        ctx["skipped_count"] = max(0, int(signed.get("source_count", len(saved))) - len(saved))
        ctx["freshness_state"] = freshness.state.value
        # Provenance of the transaction: who approved what, when, and the new canonical identity it produced.
        # Diagnostic only: nothing from the uploaded workbook is persisted by this route.
        ctx["approval_event"] = signed.get("approval_event")
        ctx["approved_at"] = signed.get("approved_at")
        ctx["transaction_identity"] = identity.composite_hash
        migration = signed.get("migration")
        if isinstance(migration, dict):
            _attach_migration_result(ctx, migration=migration, signed=signed, approved=approved, owner=owner, record=record,
                                     identity_hash=identity.composite_hash, manifest_token=str(form.get("manifest_token", "") or ""))
        return _templates.TemplateResponse(
            request=request, name="import_review.html", context=ctx)
    except (ImportReviewError, BatchApplyError, FieldValidationError,
            StaleContentError, VersionMismatchError, ProtectedReferenceError,
            NonEditableFieldError, UnknownFieldError, ValueError) as exc:
        code = getattr(exc, "code", type(exc).__name__)
        return _templates.TemplateResponse(
            request=request, name="import_review.html",
            context=_context(request, user, record, ws, stage="upload", error=code),
            status_code=409 if isinstance(exc, (StaleContentError, VersionMismatchError)) else 422)


# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════
# Excel migration V3: macro-aware assessment, scenario-aware slices, reconciliation, portfolio manifest.
# Additive.  Reuses the signed C0 review tickets and the canonical batch writer above; adds NO writer, NO engine
# call and NO persistence.  The uploaded workbook is read in memory only and is never stored.
# ═══════════════════════════════════════════════════════════════════════════════════════════════════════════
_MAX_RENDERED_ITEMS_PER_CLASS = 120
_MIGRATION_TEMPLATE = "import_migration.html"


def _migration_guard(request: Request, project: str):
    """(user, record, owner, ws) for an owned, non-reference project - or a redirect response."""
    user = resolve_request_session(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None or owner != user.user_id or is_protected_reference(record):
        return RedirectResponse(url="/library", status_code=302)
    ws = get_workspace_state(owner, record.project_id)
    if ws is None:
        return RedirectResponse(url="/library", status_code=302)
    return user, record, owner, ws


def _migration_base(request, user, record, ws, *, stage, error=None, manifest_token="", **extra):
    return {"request": request, "user": user, "project": record, "project_code": record.project_code, "stage": stage,
            "csrf_token": generate_csrf_token(), "error": error, "manifest_token": manifest_token,
            "active_scenario_id": ws.active_scenario_id, "active_scenario_name": ws.active_scenario_name, **extra}


def _plan_view(plan: dict) -> dict:
    """Bounded, template-safe projection of the plan (no private proposal payloads)."""
    grouped: dict[str, list] = {}
    for item in plan["items"]:
        grouped.setdefault(item["class"], []).append(item)
    return {c: grouped.get(c, [])[:_MAX_RENDERED_ITEMS_PER_CLASS] for c in plan["class_counts"]}


def _safe_manifest(token, owner):
    from app.model_import.migration_portfolio import ManifestError, unseal_manifest
    try:
        return unseal_manifest(token, owner=owner), None
    except ManifestError as exc:
        return unseal_manifest(None, owner=owner), exc.code


def _attach_migration_result(ctx, *, migration, signed, approved, owner, record, identity_hash, manifest_token):
    """After a committed Apply: expose source-scenario provenance, the changed-not-run state and the applied evidence."""
    from datetime import datetime, timezone
    from app.model_import.migration_portfolio import ManifestError, mark, seal_manifest
    from app.model_import.review import seal_applied
    applied_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ctx["migration"] = migration
    ctx["applied_ticket"] = seal_applied(
        owner=owner, project_id=record.project_id, scenario_id=signed["scenario_id"], project_code=record.project_code,
        migration={k: migration.get(k) for k in ("kind", "workbook_sha256", "slice", "target")},
        applied=approved, transaction_identity=identity_hash, applied_at=applied_at,
        reconciliation_basis=list(migration.get("basis") or ()))
    ctx["history_options"] = _history_options(owner, record.project_id)
    if manifest_token:
        manifest, _ = _safe_manifest(manifest_token, owner)
        try:
            ctx["manifest_token"] = seal_manifest(mark(manifest, migration["workbook_sha256"], review_status="SCALARS_APPLIED"))
        except (ManifestError, KeyError):
            ctx["manifest_token"] = manifest_token


def _history_options(owner, project_id):
    from app.persistence.run_history_repository import get_run_history
    entries = get_run_history(owner, project_id) or []
    return [{"history_id": e.history_id, "ran_at": e.ran_at, "snapshot": e.runtime_snapshot_id,
             "scenario": e.active_scenario_name or "default"} for e in entries][:10]        # get_run_history is newest first


@router.post("/workbook/import/assess", response_class=HTMLResponse)
async def model_migration_assess(
    request: Request,
    project: str = Form(...),
    csrf_token: str = Form(...),
    manifest_token: str = Form(""),
    upload: UploadFile = File(...),
    _: None = Depends(require_v2_active),
):
    """Inspect an XLSX/XLSM in memory (no execution) and show the migration plan.  Writes nothing, runs nothing."""
    from app.model_import.migration_plan import build_plan
    from app.model_import.migration_portfolio import ManifestError, entry_from_plan, seal_manifest, upsert
    from app.model_import.review import ImportReviewError, seal_preview
    from app.model_import.workbook_inspect import inspect_workbook
    guard = _migration_guard(request, project)
    if isinstance(guard, RedirectResponse):
        return guard
    user, record, owner, ws = guard
    if not validate_csrf_token(csrf_token):
        return _templates.TemplateResponse(
            request=request, name=_MIGRATION_TEMPLATE,
            context=_migration_base(request, user, record, ws, stage="upload", error="IMPORT_CSRF_INVALID"), status_code=403)
    try:
        header_length = request.headers.get("content-length")
        if header_length and int(header_length) > MAX_UPLOAD_BYTES + 16 * 1024:
            raise IntakeError("IMPORT_BODY_SIZE_INVALID")
        data = await upload.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise IntakeError("IMPORT_FILE_SIZE_INVALID")
        insp = inspect_workbook(data, upload.filename or "")
        plan = build_plan(insp, project_type=record.project_type or "", template_source=record.template_source or "",
                          project_code=record.project_code, target_scenario_id=ws.active_scenario_id,
                          target_scenario_name=ws.active_scenario_name)
        identity = assemble_consistent_for_get(owner, record.project_id, WORKBOOK.version)
        for sl in plan["slices"]:
            sl["ticket"] = None
            if not sl["apply_eligible"]:
                continue
            sl["ticket"] = seal_preview(
                owner=owner, project_id=record.project_id, scenario_id=ws.active_scenario_id,
                content_hash=identity.composite_hash, workbook_version=WORKBOOK.version, digest=insp.digest,
                proposals=sl["_proposals"],
                migration={"kind": "EXCEL_MIGRATION_V3", "workbook_sha256": insp.digest,
                           "slice": {"key": sl["key"], "label": sl["label"], "kind": sl["kind"], "resolution": sl["resolution"]},
                           "target": plan["target"], "confirmation_required": True,
                           "basis": plan["reconciliation_basis"]})
        manifest, manifest_error = _safe_manifest(manifest_token, owner)
        manifest = upsert(manifest, entry_from_plan(plan, insp.report, candidate_project_code=record.project_code))
        ctx = _migration_base(
            request, user, record, ws, stage="assess", manifest_token=seal_manifest(manifest), report=insp.report, plan=plan,
            plan_view=_plan_view(plan), scenario_rows=scenario_review_matrix(plan), manifest=manifest, manifest_error=manifest_error,
            classes=list(plan["class_counts"]), max_items=_MAX_RENDERED_ITEMS_PER_CLASS)
        return _templates.TemplateResponse(request=request, name=_MIGRATION_TEMPLATE, context=ctx)
    except (IntakeError, ImportReviewError, ManifestError, ValueError) as exc:
        code = getattr(exc, "code", "IMPORT_ASSESS_REJECTED")
        return _templates.TemplateResponse(
            request=request, name=_MIGRATION_TEMPLATE,
            context=_migration_base(request, user, record, ws, stage="upload", error=code), status_code=422)
    finally:
        await upload.close()


@router.post("/workbook/import/review-slice", response_class=HTMLResponse)
async def model_migration_review_slice(
    request: Request,
    project: str = Form(...),
    csrf_token: str = Form(...),
    slice_ticket: str = Form(...),
    source_target_ack: str = Form(""),
    manifest_token: str = Form(""),
    _: None = Depends(require_v2_active),
):
    """Open one scenario slice in the EXISTING review UI.  The signed ticket is the only source; nothing is re-read."""
    from collections import Counter
    from app.model_import.migration_portfolio import ManifestError, mark, seal_manifest
    from app.model_import.review import ImportReviewError, rows_to_proposals, unseal_preview
    guard = _migration_guard(request, project)
    if isinstance(guard, RedirectResponse):
        return guard
    user, record, owner, ws = guard
    if not validate_csrf_token(csrf_token):
        return _templates.TemplateResponse(
            request=request, name="import_review.html",
            context=_context(request, user, record, ws, stage="upload", error="IMPORT_CSRF_INVALID"), status_code=403)
    try:
        if not scenario_review_acknowledged(source_target_ack):
            raise ImportReviewError("IMPORT_SOURCE_SCENARIO_ACK_REQUIRED")
        preview = unseal_preview(slice_ticket, owner=owner, project_id=record.project_id)
        migration = preview.get("migration")
        if not isinstance(migration, dict):
            raise ImportReviewError("IMPORT_REVIEW_TICKET_NOT_A_MIGRATION_SLICE")
        current = assemble_consistent_for_get(owner, record.project_id, WORKBOOK.version)
        if (preview["scenario_id"] != ws.active_scenario_id or preview["content_hash"] != current.composite_hash
                or preview["workbook_version"] != WORKBOOK.version):
            raise ImportReviewError("IMPORT_PREVIEW_STALE")
        proposals = rows_to_proposals(preview["rows"])
        ctx = _context(request, user, record, ws, stage="review", proposals=proposals, detected=len(proposals),
                       totals=dict(Counter(p["status"] for p in proposals)), digest=preview["digest"])
        ctx["preview_ticket"] = slice_ticket
        ctx["migration"] = migration
        ctx["manifest_token"] = manifest_token
        if manifest_token:
            manifest, _ = _safe_manifest(manifest_token, owner)
            try:
                ctx["manifest_token"] = seal_manifest(mark(manifest, migration["workbook_sha256"], review_status="REVIEW_IN_PROGRESS"))
            except (ManifestError, KeyError):
                pass
        return _templates.TemplateResponse(request=request, name="import_review.html", context=ctx)
    except (ImportReviewError, ValueError) as exc:
        code = getattr(exc, "code", "IMPORT_REVIEW_INVALID")
        return _templates.TemplateResponse(
            request=request, name="import_review.html",
            context=_context(request, user, record, ws, stage="upload", error=code),
            status_code=409 if code == "IMPORT_PREVIEW_STALE" else 422)


@router.post("/workbook/import/reconcile", response_class=HTMLResponse)
async def model_migration_reconcile(
    request: Request,
    project: str = Form(...),
    csrf_token: str = Form(...),
    applied_ticket: str = Form(...),
    history_id: str = Form(""),
    conventions_attested: str = Form(""),
    abs_tolerance: str = Form("0"),
    rel_tolerance: str = Form("0"),
    manifest_token: str = Form(""),
    _: None = Depends(require_v2_active),
):
    """Compare source outputs with a COMMITTED native Run through P0-B3.  Reads only; never starts a Run."""
    from app.model_import.migration_portfolio import ManifestError, mark, seal_manifest
    from app.model_import.migration_reconcile import reconcile_output, reconciliation_summary
    from app.model_import.review import ImportReviewError, unseal_applied
    from app.persistence.run_history_repository import get_run_history
    from app.workbook.runtime_authority import resolve_runtime_freshness
    from app.workbook.update_service import WorkbookUpdateService
    guard = _migration_guard(request, project)
    if isinstance(guard, RedirectResponse):
        return guard
    user, record, owner, ws = guard
    if not validate_csrf_token(csrf_token):
        return _templates.TemplateResponse(
            request=request, name=_MIGRATION_TEMPLATE,
            context=_migration_base(request, user, record, ws, stage="upload", error="IMPORT_CSRF_INVALID"), status_code=403)
    try:
        evidence = unseal_applied(applied_ticket, owner=owner, project_id=record.project_id)
        try:
            from decimal import Decimal
            if any(Decimal(str(v)) < 0 for v in (abs_tolerance, rel_tolerance)):
                raise ValueError
        except Exception as exc:                         # noqa: BLE001 - any malformed tolerance is a typed rejection
            raise ImportReviewError("RECONCILE_TOLERANCE_INVALID") from exc
        entries = list(get_run_history(owner, record.project_id) or [])
        # get_run_history is newest first.  The default is the newest committed Run OF THE TARGET SCENARIO.
        entry = (next((e for e in entries if e.history_id == history_id), None) if history_id else
                 next((e for e in entries if (e.active_scenario_id or None) == (evidence["scenario_id"] or None)), None))
        if history_id and entry is None:
            raise ImportReviewError("RECONCILE_RUN_NOT_IN_THIS_PROJECT")     # cross-project / forged run id
        identity = assemble_consistent_for_get(owner, record.project_id, WORKBOOK.version)
        freshness = resolve_runtime_freshness(ws, current_composite_hash=identity.composite_hash)
        pis = ProjectInputSet.from_snapshot(ws.draft_snapshot, workbook=WORKBOOK)
        intact = True
        for a in evidence["applied"]:
            check = WorkbookUpdateService.validate_field_update(a["field_id"], a["value"])
            if not check.is_valid or check.typed_value != pis.get(a["field_id"]):
                intact = False
        run_current = bool(entry is not None and freshness.state.value == "CURRENT"
                           and entry.runtime_snapshot_id == ws.last_runtime_snapshot_id
                           and entry.composite_hash == identity.composite_hash)
        scenario_ok = bool(entry is not None and (entry.active_scenario_id or None) == (evidence["scenario_id"] or None)
                           and ws.active_scenario_id == evidence["scenario_id"])
        run = ({} if entry is None else {
            "history_id": entry.history_id, "runtime_snapshot_id": entry.runtime_snapshot_id, "ran_at": entry.ran_at,
            "engine_version": entry.engine_version, "composite_hash": entry.composite_hash,
            "active_scenario_id": entry.active_scenario_id, "runtime_summary": entry.runtime_summary})
        applied_cells = {a["cell"] for a in evidence["applied"]}
        rows = [reconcile_output(
            output={**o, "workbook_sha256": evidence["migration"].get("workbook_sha256")}, applied_cells=applied_cells,
            applied_fields=evidence["applied"], run=run, run_current=run_current, applied_values_intact=intact,
            scenario_ok=scenario_ok, slice_key=(evidence["migration"].get("slice") or {}).get("key", ""),
            attested=(conventions_attested == "on"), abs_tolerance=abs_tolerance or "0", rel_tolerance=rel_tolerance or "0",
            project_code=record.project_code) for o in evidence["reconciliation_basis"]]
        summary = reconciliation_summary(rows)
        token = manifest_token
        if manifest_token:
            manifest, _ = _safe_manifest(manifest_token, owner)
            try:
                token = seal_manifest(mark(manifest, evidence["migration"]["workbook_sha256"], reconciliation={
                    "status": summary["status"], "comparable": summary["comparable"]}))
            except (ManifestError, KeyError):
                token = manifest_token
        manifest_view, _ = _safe_manifest(token, owner) if token else (None, None)
        ctx = _migration_base(
            request, user, record, ws, stage="reconcile", manifest_token=token, manifest=manifest_view, rows=rows, summary=summary,
            run=({k: v for k, v in run.items() if k != "runtime_summary"} if run else None),
            freshness=freshness.state.value, applied_ticket=applied_ticket, intact=intact, run_current=run_current,
            history_options=_history_options(owner, record.project_id), attested=(conventions_attested == "on"),
            applied_count=len(evidence["applied"]), evidence_migration=evidence["migration"],
            abs_tolerance=abs_tolerance, rel_tolerance=rel_tolerance)
        return _templates.TemplateResponse(request=request, name=_MIGRATION_TEMPLATE, context=ctx)
    except (ImportReviewError, ValueError) as exc:
        code = getattr(exc, "code", "RECONCILE_REJECTED")
        return _templates.TemplateResponse(
            request=request, name=_MIGRATION_TEMPLATE,
            context=_migration_base(request, user, record, ws, stage="upload", error=code), status_code=422)


@router.post("/workbook/import/manifest", response_class=HTMLResponse)
async def model_migration_manifest(
    request: Request,
    project: str = Form(...),
    csrf_token: str = Form(...),
    manifest_token: str = Form(...),
    download: str = Form(""),
    _: None = Depends(require_v2_active),
):
    """Show (or download as JSON) the signed, value-free portfolio manifest.  Holds no server state."""
    from fastapi.responses import Response
    from app.model_import.migration_portfolio import ManifestError, manifest_json, unseal_manifest
    guard = _migration_guard(request, project)
    if isinstance(guard, RedirectResponse):
        return guard
    user, record, owner, ws = guard
    if not validate_csrf_token(csrf_token):
        return _templates.TemplateResponse(
            request=request, name=_MIGRATION_TEMPLATE,
            context=_migration_base(request, user, record, ws, stage="upload", error="IMPORT_CSRF_INVALID"), status_code=403)
    try:
        manifest = unseal_manifest(manifest_token, owner=owner)
    except ManifestError as exc:
        return _templates.TemplateResponse(
            request=request, name=_MIGRATION_TEMPLATE,
            context=_migration_base(request, user, record, ws, stage="upload", error=exc.code), status_code=422)
    if download == "json":
        return Response(manifest_json(manifest), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="finco-migration-manifest.json"'})
    return _templates.TemplateResponse(
        request=request, name=_MIGRATION_TEMPLATE,
        context=_migration_base(request, user, record, ws, stage="manifest", manifest_token=manifest_token, manifest=manifest))
