"""Signed source-evidence review tickets and explicit approved-change sealing.

No financial writers here.  The only persisted mutation is delegated to the
canonical WorkbookUpdateService C0 path by the authenticated Apply route.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Mapping
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.auth import SECRET_KEY
from app.model_import.intake import IntakeError, normalize_value
from app.model_import.mapping import STRUCTURED_FIELD_OWNERS, UNSUPPORTED_FOR_APPLY, validate_candidate
from app.workbook.registry import WORKBOOK
from app.workbook.update_service import (
    BatchApplyError, FieldValidationError, WorkbookUpdateService,
    _assert_batch_field_applicable,
)

_TTL_SECONDS = 900
_MAX_TICKET_CHARS = 200_000
_MAX_ROWS = 150


class ImportReviewError(ValueError):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


def _serializer(stage: str):
    return URLSafeTimedSerializer(SECRET_KEY, salt=f"finco-model-import-v1-{stage}")


def seal_preview(
    *,
    owner: str, project_id: str, scenario_id: str | None,
    content_hash: str, workbook_version: str, digest: str,
    proposals: list[dict],
) -> str:
    if len(proposals) > _MAX_ROWS:
        raise ImportReviewError("IMPORT_PROPOSAL_LIMIT_EXCEEDED")
    # Only source and audit data; browser-supplied canonical mappings are
    # re-evaluated at confirmation, never treated as write authority.
    rows = [{
        "id": p["id"], "source_cell": p["source_cell"],
        "sheet": p["sheet"], "original_value": p["original_value"],
        "label": p["label"], "source_unit": p["source_unit"],
        "field_id": p["field_id"], "status": p["status"],
        "reason": p["reason"], "method": p["mapping_method"],
        # Audit-only provenance; the server re-derives every authoritative value at confirmation.
        "category": p.get("category"), "confidence_class": p.get("confidence_class"),
        "explanation": list(p.get("explanation") or ())[:4], "unit_origin": p.get("unit_origin"),
        "section": p.get("section", ""),
        # The ORIGINAL automatic outcome, so a later user correction can be shown against it.
        "suggested_normalized": p.get("normalized_value"),
    } for p in proposals]
    body = {
        "kind": "preview", "owner": owner, "project_id": project_id,
        "scenario_id": scenario_id, "content_hash": content_hash,
        "workbook_version": workbook_version, "digest": digest, "rows": rows,
    }
    token = _serializer("preview").dumps(body)
    if len(token) > _MAX_TICKET_CHARS:
        raise ImportReviewError("IMPORT_REVIEW_TICKET_TOO_LARGE")
    return token


def _unseal(ticket: str, *, kind: str, owner: str, project_id: str) -> dict:
    if not isinstance(ticket, str) or len(ticket) > _MAX_TICKET_CHARS:
        raise ImportReviewError("IMPORT_REVIEW_TICKET_INVALID")
    try:
        body = _serializer(kind).loads(ticket, max_age=_TTL_SECONDS)
    except (BadSignature, SignatureExpired) as exc:
        raise ImportReviewError("IMPORT_REVIEW_EXPIRED_OR_TAMPERED") from exc
    if (not isinstance(body, dict) or body.get("kind") != kind
            or body.get("owner") != owner or body.get("project_id") != project_id):
        raise ImportReviewError("IMPORT_REVIEW_OWNER_MISMATCH")
    return body


def unseal_preview(ticket: str, *, owner: str, project_id: str) -> dict:
    return _unseal(ticket, kind="preview", owner=owner, project_id=project_id)


def resolve_review(
    *,
    ticket: str, owner: str, project_id: str,
    selections: Mapping[str, Any],
    project_type: str, template_source: str,
) -> tuple[dict, list[dict]]:
    """Only checked rows enter a signed final proposal; reject entire invalid set."""
    preview = unseal_preview(ticket, owner=owner, project_id=project_id)
    approved = []
    seen_fields: set[str] = set()
    seen_paths: set[str] = set()
    rows = preview.get("rows")
    if not isinstance(rows, list) or len(rows) > _MAX_ROWS:
        raise ImportReviewError("IMPORT_REVIEW_ROWS_INVALID")
    for row in rows:
        idx = row["id"]
        if f"keep_{idx}" not in selections:
            continue
        if row.get("reason") == "IMPORT_FORMULA_NOT_AUTHORITATIVE" or (
                str(row.get("original_value", "")).startswith("=FORMULA_NOT_AUTHORIZED")):
            raise ImportReviewError("IMPORT_FORMULA_NOT_AUTHORITATIVE")
        field_id = str(selections.get(f"field_{idx}", "") or "")
        if not field_id:
            raise ImportReviewError("IMPORT_MAPPING_UNRESOLVED", str(idx))
        if field_id in seen_fields:
            raise ImportReviewError("IMPORT_DUPLICATE_TARGET", field_id)
        seen_fields.add(field_id)
        allowed, why = validate_candidate(field_id=field_id, project_type=project_type, template_source=template_source)
        if not allowed:
            # Forged, structured (own writer) or inapplicable targets never reach the canonical batch writer.
            raise ImportReviewError(why if why != "OK" else "IMPORT_FIELD_INVALID", field_id)
        try:
            spec = WORKBOOK.field(field_id)
            _assert_batch_field_applicable(
                field_id, project_type=project_type,
                template_source=template_source,
            )
            manual_value = str(selections.get(f"manual_{idx}", "") or "").strip()
            extracted_unit = str(row.get("source_unit") or "").strip()
            unit_key = f"unit_{idx}"
            # A submitted unit is the user's explicit choice; a missing key is NOT a correction, so the unit
            # extracted from the file stays in force (never silently replaced by "unspecified").
            chosen_unit = str(selections.get(unit_key) or "").strip() if unit_key in selections else extracted_unit
            normalized = manual_value
            if not normalized:
                # The source value is always from the signed original evidence.
                normalized = normalize_value(field_id, row["original_value"], chosen_unit)
            validation = WorkbookUpdateService.validate_field_update(field_id, normalized)
            if not validation.is_valid:
                raise FieldValidationError(validation.error, validation.error_class)
            if spec.engine_path:
                if spec.engine_path in seen_paths:
                    raise ImportReviewError("IMPORT_DUPLICATE_CANONICAL_AUTHORITY", spec.engine_path)
                seen_paths.add(spec.engine_path)
        except (KeyError, BatchApplyError, IntakeError, FieldValidationError) as exc:
            raise ImportReviewError(getattr(exc, "code", "IMPORT_FIELD_INVALID"), str(exc)) from exc
        suggested_field = str(row.get("field_id") or "")
        unit_corrected = (not manual_value) and chosen_unit.casefold() != extracted_unit.casefold()
        field_remapped = field_id != suggested_field
        corrections, notes = [], []
        if field_remapped:
            corrections.append("FIELD_REMAPPED")
            notes.append(f"field changed from {suggested_field or 'no suggestion'} to {field_id}")
        if unit_corrected:
            corrections.append("SOURCE_UNIT_CORRECTED")
            notes.append(f"source unit changed from {extracted_unit or 'unspecified'} to {chosen_unit or 'unspecified'}")
        if manual_value:
            corrections.append("VALUE_OVERRIDDEN")
            notes.append("FINCO value entered manually; the source unit selection was not used")
        canonical_unit = spec.unit or ""
        approved.append({
            "source_id": idx, "sheet": row["sheet"], "cell": row["source_cell"],
            "label": row["label"], "field_id": field_id,
            "value": normalized, "unit": canonical_unit,
            "original_value": row["original_value"],
            # ── lossless provenance: original extraction vs what the user approved ───────────────
            "extracted_unit": extracted_unit, "chosen_unit": chosen_unit, "canonical_unit": canonical_unit,
            "source_unit": chosen_unit,                                  # legacy key: the unit actually used
            "normalized_value": normalized,
            "suggested_field_id": suggested_field, "suggested_method": row.get("method"),
            "suggested_normalized": row.get("suggested_normalized"),
            "unit_corrected": unit_corrected, "field_remapped": field_remapped, "value_overridden": bool(manual_value),
            "corrections": corrections, "correction_note": "; ".join(notes),
            "mapping_origin": "user_reviewed" if corrections else "automatic",
            "normalization": ("manual FINCO value entered by the user" if manual_value else
                              f'{row["original_value"]} {chosen_unit or "(no unit)"} -> {normalized} {canonical_unit}'.strip()
                              + (f' (source unit corrected by the user from {extracted_unit or "unspecified"})' if unit_corrected else "")),
            "category": row.get("category"), "confidence_class": row.get("confidence_class"),
            "explanation": list(row.get("explanation") or ())[:4],
            # An untouched row keeps its original automatic method; any user correction is user-reviewed.
            "method": "manual_reviewed" if corrections else row.get("method"),
        })
    if not approved or len(approved) > 50:
        raise ImportReviewError("IMPORT_APPROVED_FIELD_COUNT_INVALID", str(len(approved)))
    return preview, approved


def seal_approved(preview: dict, approved: list[dict]) -> str:
    if not (1 <= len(approved) <= 50):
        raise ImportReviewError("IMPORT_APPROVED_FIELD_COUNT_INVALID")
    body = {
        "kind": "approved",
        "owner": preview["owner"], "project_id": preview["project_id"],
        "scenario_id": preview["scenario_id"],
        "content_hash": preview["content_hash"],
        "workbook_version": preview["workbook_version"],
        "digest": preview["digest"], "source_count": len(preview["rows"]), "approved": approved,
        "approval_event": "USER_CONFIRMED_REVIEW",
        "approved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    token = _serializer("approved").dumps(body)
    if len(token) > _MAX_TICKET_CHARS:
        raise ImportReviewError("IMPORT_APPROVED_TICKET_TOO_LARGE")
    return token


def unseal_approved(ticket: str, *, owner: str, project_id: str) -> dict:
    body = _unseal(ticket, kind="approved", owner=owner, project_id=project_id)
    approved = body.get("approved")
    if not isinstance(approved, list) or not 1 <= len(approved) <= 50:
        raise ImportReviewError("IMPORT_APPROVED_FIELD_COUNT_INVALID")
    ids = [p["field_id"] for p in approved]
    if len(ids) != len(set(ids)):
        raise ImportReviewError("IMPORT_DUPLICATE_TARGET")
    return body
