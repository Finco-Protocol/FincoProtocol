"""
app.workbook.update_service — canonical V2 field edit pipeline.

Architecture position
---------------------
This module is the ONLY path by which a V2 field value may be changed.

  Browser POST (semantic field_id, raw string value)
      ↓
  WorkbookUpdateService.validate_field_update()   ← pure validation
      ↓
  ProjectInputSet.with_value()                    ← immutable update
      ↓
  WorkbookUpdateService.apply_draft_update()      ← persist draft
      ↓
  updated ProjectInputSet + new content_hash

Design invariants
-----------------
- No legacy snapshot keys may appear in this module.
- All field resolution goes through WORKBOOK.field(field_id).
- Type coercion uses the same _coerce_value logic as ProjectInputSet.from_snapshot
  (imported here to avoid duplication, not duplicated).
- Optimistic concurrency: apply_draft_update() raises StaleContentError if the
  caller's content_hash does not match the current draft state.
- Protected-reference guard: apply_draft_update() raises ProtectedReferenceError
  if the project is a Generic Wind Reference/Generic Solar Reference seeded original.
- This service is pure Python — no HTTP, no Jinja, no FastAPI dependencies.
- Draft persistence calls save_workspace_state() with only draft_snapshot updated;
  saved_snapshot and all runtime fields are preserved.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.workbook.input_set import ProjectInputSet, ProjectInputSetError, _coerce_value
from app.workbook.registry import WORKBOOK
from app.workbook.specs import BindingStatus, FieldKind, FieldSpec, FieldType, SourceOfTruth


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------

class WorkbookUpdateError(ValueError):
    """Base for all WorkbookUpdateService errors."""


class UnknownFieldError(WorkbookUpdateError):
    """field_id does not exist in the WORKBOOK registry."""


class NonEditableFieldError(WorkbookUpdateError):
    """Field cannot be edited (DISPLAY_ONLY, TEMPLATE_LOCKED, etc.)."""


class FieldValidationError(WorkbookUpdateError):
    """Value fails type, required, bounds, or options validation."""


class StaleContentError(WorkbookUpdateError):
    """Optimistic concurrency: caller's content_hash is stale."""


class ProtectedReferenceError(WorkbookUpdateError):
    """Project is a protected reference (Generic Wind Reference/Generic Solar Reference) and cannot be mutated."""


class VersionMismatchError(WorkbookUpdateError):
    """Submitted workbook_version does not match the current WORKBOOK version.

    The browser's registry is stale — it must reload before editing.
    """


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FieldValidationResult:
    field_id: str
    raw_value: str
    typed_value: Any          # None if raw is empty/whitespace
    spec: FieldSpec
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return self.error is None


# ---------------------------------------------------------------------------
# WorkbookUpdateService
# ---------------------------------------------------------------------------

# SourceOfTruth values that are never writable by users.
_NON_EDITABLE_SOURCES: frozenset[SourceOfTruth] = frozenset({
    SourceOfTruth.ENGINE,
    SourceOfTruth.TEMPLATE,
    SourceOfTruth.DERIVED_UI,
})

# BindingStatus values that are never user-editable via the V2 edit API.
# PARTIAL is explicitly excluded: partial fields are not fully connected to the
# engine and must not be presented as authoritative editable inputs until their
# engine binding is resolved and promoted to BOUND.
_NON_EDITABLE_BINDINGS: frozenset[BindingStatus] = frozenset({
    BindingStatus.DISPLAY_ONLY,
    BindingStatus.TEMPLATE_LOCKED,
    BindingStatus.PARTIAL,
    BindingStatus.UNSUPPORTED,
})

# FieldKind values that can be written.
_WRITABLE_KINDS: frozenset[FieldKind] = frozenset({FieldKind.INPUT})


class WorkbookUpdateService:
    """Pure static service for the V2 field edit pipeline.

    No HTTP, no HTML, no Jinja.  Every method is a static function.
    """

    @staticmethod
    def validate_field_update(field_id: str, raw_value: str) -> FieldValidationResult:
        """Validate a single field update.

        Parameters
        ----------
        field_id : str
            Semantic field identifier from the WORKBOOK registry.
        raw_value : str
            Raw string value from the browser (not yet typed).

        Returns
        -------
        FieldValidationResult
            If `.is_valid` is True, `.typed_value` contains the coerced value
            (or None for empty/whitespace input).  If False, `.error` contains
            a human-readable reason.

        Raises
        ------
        UnknownFieldError
            If field_id does not exist in WORKBOOK.
        NonEditableFieldError
            If the field is not writable (DISPLAY_ONLY, TEMPLATE_LOCKED, kind
            != INPUT, source_of_truth not INPUT_SET, editable=False, etc.).
        """
        # --- 1. Resolve spec ---------------------------------------------
        try:
            spec = WORKBOOK.field(field_id)
        except KeyError:
            raise UnknownFieldError(
                f"Unknown field: {field_id!r}. "
                "Only semantic field IDs from the WORKBOOK registry are accepted."
            )

        # --- 2. Editability gate -----------------------------------------
        if spec.binding_status in _NON_EDITABLE_BINDINGS:
            raise NonEditableFieldError(
                f"Field {field_id!r} is {spec.binding_status.value} and cannot be edited."
            )
        if spec.source_of_truth in _NON_EDITABLE_SOURCES:
            raise NonEditableFieldError(
                f"Field {field_id!r} source_of_truth={spec.source_of_truth.value}; "
                "not user-editable."
            )
        if spec.kind not in _WRITABLE_KINDS:
            raise NonEditableFieldError(
                f"Field {field_id!r} kind={spec.kind.value}; only INPUT fields are writable."
            )
        if not spec.editable:
            raise NonEditableFieldError(
                f"Field {field_id!r} has editable=False in the registry."
            )
        if spec.runtime_only:
            raise NonEditableFieldError(
                f"Field {field_id!r} is runtime_only and cannot be persisted."
            )
        if not spec.persisted:
            raise NonEditableFieldError(
                f"Field {field_id!r} is not persisted and cannot be stored in the draft."
            )

        # --- 3. Type coercion -------------------------------------------
        stripped = raw_value.strip() if raw_value else ""
        if not stripped:
            # Empty value — check required.
            if spec.required:
                return FieldValidationResult(
                    field_id=field_id, raw_value=raw_value, typed_value=None,
                    spec=spec, error=f"{spec.label} is required."
                )
            return FieldValidationResult(
                field_id=field_id, raw_value=raw_value, typed_value=None,
                spec=spec
            )

        try:
            typed = _coerce_value(stripped, spec)
        except ProjectInputSetError as exc:
            # exc.args[0] is already a user-displayable message (no snapshot internals).
            return FieldValidationResult(
                field_id=field_id, raw_value=raw_value, typed_value=None,
                spec=spec,
                error=str(exc),
            )

        # --- 4. Options validation (SELECT) ------------------------------
        if spec.options and typed not in spec.options:
            return FieldValidationResult(
                field_id=field_id, raw_value=raw_value, typed_value=typed,
                spec=spec,
                error=(
                    f"{spec.label}: {typed!r} is not a valid option. "
                    f"Allowed: {', '.join(spec.options)}"
                )
            )

        # --- 5. Bounds validation ----------------------------------------
        if spec.min_value is not None and isinstance(typed, (int, float)):
            if typed < spec.min_value:
                return FieldValidationResult(
                    field_id=field_id, raw_value=raw_value, typed_value=typed,
                    spec=spec,
                    error=f"{spec.label} must be ≥ {spec.min_value} (got {typed})."
                )
        if spec.max_value is not None and isinstance(typed, (int, float)):
            if typed > spec.max_value:
                return FieldValidationResult(
                    field_id=field_id, raw_value=raw_value, typed_value=typed,
                    spec=spec,
                    error=f"{spec.label} must be ≤ {spec.max_value} (got {typed})."
                )

        # --- 6. Merchant curve semantic validation -----------------------
        if field_id == "revenue.merchant.price_curve_json" and typed is not None:
            from app.input_adapter import validate_merchant_curve_json
            try:
                validate_merchant_curve_json(str(typed))
            except ValueError as exc:
                return FieldValidationResult(
                    field_id=field_id, raw_value=raw_value, typed_value=None,
                    spec=spec,
                    error=f"Merchant Price Curve: {exc}",
                )

        return FieldValidationResult(
            field_id=field_id, raw_value=raw_value, typed_value=typed, spec=spec
        )

    @staticmethod
    def apply_field_to_pis(
        pis: ProjectInputSet,
        validation: FieldValidationResult,
    ) -> ProjectInputSet:
        """Apply a validated update to a ProjectInputSet.

        Returns a new ProjectInputSet with the field updated.

        Raises
        ------
        FieldValidationError
            If the validation result has an error.
        WorkbookUpdateError
            If ProjectInputSet.with_value() rejects the update (should not
            happen after validate_field_update passes, but guards against
            registry drift).
        """
        if not validation.is_valid:
            raise FieldValidationError(validation.error)

        try:
            return pis.with_value(validation.field_id, validation.typed_value)
        except ProjectInputSetError as exc:
            raise WorkbookUpdateError(
                f"ProjectInputSet rejected update for {validation.field_id!r}: {exc}"
            ) from exc

    @staticmethod
    def apply_draft_update(
        *,
        ws,
        field_id: str,
        raw_value: str,
        content_hash: str,
        workbook_version: str,
        project_record,
    ) -> ProjectInputSet:
        """Full edit pipeline: validate → version check → CAS persist.

        Parameters
        ----------
        ws : WorkspaceStateRecord
            Current workspace state.  Used for protected-reference check and
            to seed the atomic compare-and-swap.
        field_id : str
            Semantic field_id from the WORKBOOK registry.  Legacy snapshot
            keys are rejected by validate_field_update.
        raw_value : str
            Raw string value from the browser (not yet type-coerced).
        content_hash : str
            SHA-256 of the ProjectInputSet as seen by the browser.
            Matched atomically against the persisted draft at write time.
        workbook_version : str
            WORKBOOK registry version submitted by the browser.  Must match
            the current WORKBOOK.version; mismatch means the browser has a
            stale registry and must reload.
        project_record : ProjectRecord
            Used for protected-reference check.

        Returns
        -------
        ProjectInputSet
            The updated ProjectInputSet after atomic persistence.

        Raises
        ------
        ProtectedReferenceError
            Project is Generic Wind Reference/Generic Solar Reference seeded original — no writes allowed.
        VersionMismatchError
            Submitted workbook_version doesn't match WORKBOOK.version.
        StaleContentError
            content_hash doesn't match the current persisted draft at write
            time (concurrent edit detected by atomic CAS).
        UnknownFieldError, NonEditableFieldError, FieldValidationError
            Propagated from validate_field_update / apply_field_to_pis.
        """
        from app.ui.protected_reference_service import is_protected_reference
        from app.persistence.workspace_repository import v2_atomic_draft_update

        # --- Protected reference guard (before any DB work) -------------
        if is_protected_reference(project_record):
            raise ProtectedReferenceError(
                f"Project {getattr(project_record, 'project_code', '?')!r} is a protected "
                "reference (Generic Wind Reference/Generic Solar Reference). Create a working copy before editing."
            )

        # --- Workbook version check -------------------------------------
        current_version = WORKBOOK.version
        if workbook_version != current_version:
            raise VersionMismatchError(
                f"Your browser has workbook version {workbook_version!r} but the "
                f"server is running {current_version!r}. Reload the page before editing."
            )

        # --- Validate field (pure, no DB) --------------------------------
        # Raises UnknownFieldError / NonEditableFieldError before any DB work.
        # FieldValidationError raised here if value fails type/bounds/options.
        validation = WorkbookUpdateService.validate_field_update(field_id, raw_value)
        if not validation.is_valid:
            raise FieldValidationError(validation.error)

        # --- R8/N02: Senior scalar authority gate (before ANY persistence) --
        # A source-calibrated non-uniform period schedule cannot honour a
        # scalar edit; reject the Save before the CAS so no decorative value
        # is ever persisted for the Senior rate / target-DSCR controls.
        if field_id in ("debt.senior.interest_rate_pct",
                        "debt.senior.target_dscr"):
            from app.input_adapter import assert_debt_scalar_edit_allowed

            current_pis = ProjectInputSet.from_snapshot(
                dict(ws.draft_snapshot or {}))
            try:
                assert_debt_scalar_edit_allowed(current_pis, field_id)
            except FieldValidationError:
                raise
            except ValueError as exc:
                # Fail closed (R8/N02): an unresolvable authority or a
                # calibrated schedule must not accept a decorative scalar.
                raise FieldValidationError(str(exc)) from exc

        # --- Atomic compare-and-swap ------------------------------------
        # v2_atomic_draft_update opens a single exclusive-lock transaction:
        # 1. Reads draft_snapshot_json from DB
        # 2. Builds canonical ProjectInputSet and compares content_hash
        # 3. Applies field_id / typed_value to that PIS (inside transaction)
        # 4. Persists resulting snapshot and canonical new content_hash
        # Returns None when the canonical hash of the persisted draft no longer
        # matches expected_content_hash (concurrent or legacy write detected).
        result = v2_atomic_draft_update(
            user_id=ws.user_id,
            project_id=ws.project_id,
            expected_content_hash=content_hash,
            field_id=field_id,
            typed_value=validation.typed_value,
        )
        if result is None:
            raise StaleContentError(
                f"Draft has changed since the page loaded (expected {content_hash[:8]}…). "
                "Reload and try again."
            )

        return ProjectInputSet.from_snapshot(result.draft_snapshot, workbook=WORKBOOK)
