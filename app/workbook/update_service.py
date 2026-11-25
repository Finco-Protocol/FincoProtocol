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
from enum import Enum
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


class FieldErrorClass(str, Enum):
    """Typed outcome of a failed field-value validation.

    Product behaviour (UI decoration, Smart Panel summary) must branch on this
    value — never on the human-readable error text, which is presentation only.
    """
    REQUIRED_MISSING = "REQUIRED_MISSING"   # required field submitted empty
    INVALID = "INVALID"                     # not coercible / not an allowed option / semantic reject
    OUT_OF_BOUNDS = "OUT_OF_BOUNDS"         # coercible but outside registry min/max


class FieldValidationError(WorkbookUpdateError):
    """Value fails type, required, bounds, or options validation.

    ``error_class`` is None for rejections that are not a value-classification
    outcome (e.g. the Senior scalar authority gate).
    """

    def __init__(self, message: str = "", error_class: Optional[FieldErrorClass] = None):
        super().__init__(message)
        self.error_class = error_class


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
    error_class: Optional[FieldErrorClass] = None

    def __post_init__(self) -> None:
        if (self.error is None) != (self.error_class is None):
            raise ValueError(
                "FieldValidationResult: error and error_class must be set together."
            )

    @property
    def is_valid(self) -> bool:
        return self.error is None


class BatchApplyError(WorkbookUpdateError):
    """Typed, fail-closed batch rejection."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


# Capacity save calls post-CAS reference seeded rescaling: it is NOT atomic.
_BATCH_CASCADE_FIELDS = frozenset({
    "project_setup.technical.capacity_mw",
    # Project name also lives on the projects row, outside the scalar draft.
    "project_setup.identity.project_name",
})


def _assert_batch_field_applicable(field_id: str, *, project_type: str, template_source: str) -> None:
    """Shared V2 registry + technology boundaries; no guesswork on applicability."""
    from app.workbook.registry import (
        DATA_CENTER_FIELD_IDS, DC_RENEWABLE_EXCLUDED_FIELD_IDS,
        DC_DERIVED_OPEX_FIELD_ID, EV_CHARGING_FIELD_IDS,
        EV_RENEWABLE_EXCLUDED_FIELD_IDS, is_data_center_project_type,
    )

    if field_id in _BATCH_CASCADE_FIELDS:
        raise BatchApplyError("BATCH_FIELD_REQUIRES_ATOMIC_CASCADE_SUPPORT", field_id)

    template = (template_source or "").strip().lower()
    dc = is_data_center_project_type(project_type) or template == "generic_data_center_reference"
    ev = (project_type or "").strip().lower() in ("ev charging", "ev_charging") or template == "generic_ev_charging_reference"
    if dc and (field_id in DC_RENEWABLE_EXCLUDED_FIELD_IDS or field_id == DC_DERIVED_OPEX_FIELD_ID):
        raise BatchApplyError("BATCH_FIELD_NOT_APPLICABLE", field_id)
    if not dc and field_id in DATA_CENTER_FIELD_IDS:
        raise BatchApplyError("BATCH_FIELD_NOT_APPLICABLE", field_id)
    if ev and field_id in EV_RENEWABLE_EXCLUDED_FIELD_IDS:
        raise BatchApplyError("BATCH_FIELD_NOT_APPLICABLE", field_id)
    if not ev and field_id in EV_CHARGING_FIELD_IDS:
        raise BatchApplyError("BATCH_FIELD_NOT_APPLICABLE", field_id)



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

        # --- RC-7B: release-closed operating/debt frequency selection ----
        # Every write path (single field, batch) passes here: a non-empty 3/3
        # selection is refused while the admission gate is closed, and any
        # value must be the strict versioned contract (empty = released 6/6).
        if field_id == "project_setup.calendar.operating_frequency" and (raw_value or "").strip():
            from app.workbook import quarterly_frequency_config as _q
            if not _q.ACTIVATION_ENABLED:
                raise NonEditableFieldError("QUARTERLY_ADMISSION_CLOSED: matched 3/3 is release-closed")
            try:
                _q.parse_config(raw_value.strip())
            except ValueError as exc:
                return FieldValidationResult(field_id=field_id, raw_value=raw_value, typed_value=None,
                                             spec=spec, error=str(exc), error_class=FieldErrorClass.INVALID)

        # --- 3. Type coercion -------------------------------------------
        stripped = raw_value.strip() if raw_value else ""
        if not stripped:
            # Empty value — check required.
            if spec.required:
                return FieldValidationResult(
                    field_id=field_id, raw_value=raw_value, typed_value=None,
                    spec=spec, error=f"{spec.label} is required.",
                    error_class=FieldErrorClass.REQUIRED_MISSING,
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
                error_class=FieldErrorClass.INVALID,
            )

        # --- 4. Options validation (SELECT) ------------------------------
        if spec.options and typed not in spec.options:
            return FieldValidationResult(
                field_id=field_id, raw_value=raw_value, typed_value=typed,
                spec=spec,
                error=(
                    f"{spec.label}: {typed!r} is not a valid option. "
                    f"Allowed: {', '.join(spec.options)}"
                ),
                error_class=FieldErrorClass.INVALID,
            )

        # --- 5. Bounds validation ----------------------------------------
        if spec.min_value is not None and isinstance(typed, (int, float)):
            if typed < spec.min_value:
                return FieldValidationResult(
                    field_id=field_id, raw_value=raw_value, typed_value=typed,
                    spec=spec,
                    error=f"{spec.label} must be ≥ {spec.min_value} (got {typed}).",
                    error_class=FieldErrorClass.OUT_OF_BOUNDS,
                )
        if spec.max_value is not None and isinstance(typed, (int, float)):
            if typed > spec.max_value:
                return FieldValidationResult(
                    field_id=field_id, raw_value=raw_value, typed_value=typed,
                    spec=spec,
                    error=f"{spec.label} must be ≤ {spec.max_value} (got {typed}).",
                    error_class=FieldErrorClass.OUT_OF_BOUNDS,
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
                    error_class=FieldErrorClass.INVALID,
                )

        if field_id == "project_setup.bess.configuration":
            from app.workbook.bess_config import canonical_json, ACTIVATION_ENABLED
            try:
                if not ACTIVATION_ENABLED:
                    raise ValueError("BESS_FINANCIAL_ACTIVATION_RELEASE_CLOSED")
                typed = canonical_json(typed)
            except ValueError as exc:
                return FieldValidationResult(field_id, raw_value, None, spec, str(exc), FieldErrorClass.INVALID)
        if field_id == "revenue.multistream.contracts":
            from app.workbook.revenue_multistream import canonical_json
            try:
                typed = canonical_json(typed)
            except ValueError as exc:
                return FieldValidationResult(field_id=field_id, raw_value=raw_value,
                    typed_value=None, spec=spec, error=str(exc), error_class=FieldErrorClass.INVALID)
        if field_id == "investor.agreement.common_equity":
            return FieldValidationResult(field_id=field_id, raw_value=raw_value,
                typed_value=None, spec=spec, error="Use Investor agreement Save for scenario/version CAS",
                error_class=FieldErrorClass.INVALID)
        if field_id == "debt.financing.instruments":
            from app.workbook.multisenior_config import canonical_json
            try:
                typed = canonical_json(typed)
            except ValueError as exc:
                return FieldValidationResult(field_id=field_id, raw_value=raw_value,
                    typed_value=None, spec=spec, error=str(exc), error_class=FieldErrorClass.INVALID)
        if field_id == "debt.valuation.configuration":
            from app.workbook.financial_core_config import canonical_json
            try:
                typed = canonical_json(typed)
            except ValueError as exc:
                return FieldValidationResult(field_id=field_id, raw_value=raw_value,
                    typed_value=None, spec=spec, error=str(exc), error_class=FieldErrorClass.INVALID)
        if field_id == "debt.bankability.configuration":
            from app.workbook.bankability_config import parse_config
            try:
                parse_config(typed)
            except ValueError as exc:
                return FieldValidationResult(field_id=field_id, raw_value=raw_value,
                    typed_value=None, spec=spec, error=str(exc), error_class=FieldErrorClass.INVALID)
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
            raise FieldValidationError(validation.error, validation.error_class)

        try:
            if validation.field_id == "debt.senior.interest_rate_pct":
                from app.input_adapter import assert_rate_unit
                try:
                    assert_rate_unit(dict(pis.snapshot_origin))
                except ValueError as exc:
                    raise FieldValidationError(str(exc), FieldErrorClass.INVALID) from exc
            # The unit marker is already part of snapshot_origin and is
            # preserved by with_value. The atomic writer retains it in the
            # SAME snapshot as the value; batch Save may not invent provenance.
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
            raise FieldValidationError(validation.error, validation.error_class)

        if field_id == "debt.bankability.configuration":
            from app.workbook.bankability_config import parse_config, workspace_fees_editable
            if parse_config(validation.typed_value).get("fees") is not None:
                current_pis = ProjectInputSet.from_snapshot(dict(ws.draft_snapshot or {}))
                try:
                    if not workspace_fees_editable(current_pis.to_projectinputs(), ws):
                        raise ValueError("Materialized CAPEX or explicit construction pricing owns fees; no competing fee override is permitted.")
                except ValueError as exc:
                    raise FieldValidationError(str(exc)) from exc

        if field_id == "debt.senior.interest_rate_pct":
            from app.input_adapter import assert_rate_unit
            try:
                assert_rate_unit(dict(ws.draft_snapshot))
            except ValueError as exc:
                raise FieldValidationError(str(exc), FieldErrorClass.INVALID) from exc

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

        # --- C1F-A-1 / P1-OPEX-02: refuse scalar edits on line-owned active CAPEX/OPEX categories ---
        if field_id.startswith(("capex.", "opex.")):
            line_owned = find_line_owned_cost_fields(ws.project_id, [field_id])
            if field_id in line_owned and _is_diagnosed_legacy_repair(ws, field_id):
                # Legacy recovery: the stored value of THIS field is itself diagnosed invalid
                # (draft cannot be materialised). The replacement has already passed field
                # validation; repairing corrupt state is not editing active cost authority.
                line_owned = {}
            if field_id in line_owned:
                raise FieldValidationError(
                    f"COST_CATEGORY_LINE_OWNED: {line_owned[field_id]}",
                    FieldErrorClass.INVALID,
                )

        # --- E2E-01 / C1F-A-5: enforce positive senior gearing and horizon > senior tenor on proposed state ---
        if field_id in (
            "debt.senior.gearing_pct",
            "debt.senior.tenor_years",
            "project_setup.technical.horizon_years",
        ):
            snap = dict(ws.draft_snapshot or {})
            snap[validation.spec.snapshot_key] = str(validation.typed_value)
            validate_proposed_financing_horizon_snapshot(snap)

        # --- OD-P90-01: enforce bidirectional P90 <= P50 against complete proposed state at Save ---
        if field_id in ("project_setup.technical.p90_10y_hours", "project_setup.technical.p50_hours"):
            snap = dict(ws.draft_snapshot or {})
            snap[validation.spec.snapshot_key] = str(validation.typed_value)
            validate_proposed_p90_p50_snapshot(snap)

        # --- C1-Q-02 & OD-R04-02: validate proposed PPA book & global P50 cap atomically ---
        if field_id == "revenue.multistream.contracts" or field_id.startswith("project_setup.technical."):
            snap = dict(ws.draft_snapshot or {})
            snap[validation.spec.snapshot_key] = (
                validation.typed_value.isoformat()
                if hasattr(validation.typed_value, "isoformat")
                else str(validation.typed_value)
            )
            if (snap.get("rev_multistream_config_json") or "").strip():
                _validate_ppa_book_against_proposed_snapshot(snap)

        # --- P1-REV-03: reject competing dual nonzero balancing charges at Save ---
        if field_id in ("revenue.balancing.merchant_pct", "revenue.balancing.cost_eur_per_mwh"):
            from finco_core.revenue.generation import validate_balancing_cost_inputs
            snap_bal = dict(ws.draft_snapshot or {})
            snap_bal[validation.spec.snapshot_key] = str(validation.typed_value)
            try:
                pi_bal = ProjectInputSet.from_snapshot(snap_bal).to_projectinputs()
                validate_balancing_cost_inputs(pi_bal.revenue)
            except ValueError as exc:
                raise FieldValidationError(str(exc), FieldErrorClass.INVALID) from exc

        # --- R-1: early finite derived-amount refusal (advisory) ----------
        # A capacity edit rescales the reference-seeded PER_MW lines.  A rolled-back dry run gives the user an
        # early, specific refusal for the expected overflow case.  It is NOT the safeguard: the authoritative
        # finiteness check runs again INSIDE the single write transaction below, on the state actually written.
        _capacity_finalizer = None
        if field_id == "project_setup.technical.capacity_mw":
            from app.services.reference_seed_service import (
                NonFiniteDerivedAmountError, preflight_capacity_rescale, rescale_snapshot_in_transaction)
            try:
                preflight_capacity_rescale(
                    user_id=ws.user_id, project_code=project_record.project_code,
                    capacity_mw=float(validation.typed_value))
            except NonFiniteDerivedAmountError as exc:
                raise FieldValidationError(str(exc), FieldErrorClass.INVALID) from exc
            _capacity_value_mw = float(validation.typed_value)

            def _capacity_finalizer(cursor, snapshot):  # noqa: E306 - runs inside v2_atomic_draft_update's transaction
                return rescale_snapshot_in_transaction(
                    cursor, project_record=project_record, snapshot=snapshot, capacity_mw=_capacity_value_mw)

        # --- Atomic compare-and-swap ------------------------------------
        # v2_atomic_draft_update opens a single exclusive-lock transaction:
        # 1. Reads draft_snapshot_json from DB
        # 2. Builds canonical ProjectInputSet and compares content_hash
        # 3. Applies field_id / typed_value to that PIS (inside transaction)
        # 4. Persists resulting snapshot and canonical new content_hash
        # Returns None when the canonical hash of the persisted draft no longer
        # matches expected_content_hash (concurrent or legacy write detected).
        try:
            result = v2_atomic_draft_update(
                user_id=ws.user_id,
                project_id=ws.project_id,
                expected_content_hash=content_hash,
                field_id=field_id,
                typed_value=validation.typed_value,
                in_transaction_finalizer=_capacity_finalizer,
            )
        except ValueError as exc:
            if field_id == "project_setup.technical.capacity_mw":
                from app.services.reference_seed_service import NonFiniteDerivedAmountError as _NonFinite
                if isinstance(exc, _NonFinite):
                    # Raised inside the transaction: the whole Save (capacity, sub-lines, snapshot) rolled back.
                    raise FieldValidationError(str(exc), FieldErrorClass.INVALID) from exc
            from finco_core.inputs.financing_instruments import FinancingError
            if isinstance(exc, FinancingError):
                raise FieldValidationError(str(exc)) from exc
            if field_id == "debt.bankability.configuration" or (ws.draft_snapshot or {}).get("bankability_config_json"):
                raise FieldValidationError(str(exc)) from exc
            if (field_id == "revenue.multistream.contracts"
                    or (ws.draft_snapshot or {}).get("rev_multistream_config_json")
                    or str(exc).startswith("REVENUE_V2")):
                raise FieldValidationError(str(exc)) from exc
            raise
        if result is None:
            raise StaleContentError(
                f"Draft has changed since the page loaded (expected {content_hash[:8]}…). "
                "Reload and try again."
            )

        # The capacity edit, the sub-line rescale and the reconciled snapshot were committed together above.
        return ProjectInputSet.from_snapshot(result.draft_snapshot, workbook=WORKBOOK)


    @staticmethod
    def apply_batch_draft_update(
        *,
        ws,
        updates: list[tuple[str, str]],
        content_hash: str,
        workbook_version: str,
        expected_scenario_id: Optional[str],
        project_record,
        actor_user_id: str,
        reject_line_owned: bool = False,
        in_tx_after_apply: Optional[Any] = None,
    ) -> ProjectInputSet:
        """Atomic canonical update of a bounded *approved* set of fields.

        Uses the existing Workspace V2 persistence authority exactly once;
        each validation and ownership invariant is rechecked under BEGIN
        EXCLUSIVE before any financial state is persisted.  No auto-run.
        """
        from app.persistence.workspace_repository import v2_atomic_batch_draft_update
        from app.services.project_library_service import is_protected_reference

        if workbook_version != WORKBOOK.version:
            raise VersionMismatchError("BATCH_WORKBOOK_VERSION_MISMATCH")
        if is_protected_reference(project_record):
            raise ProtectedReferenceError("BATCH_PROTECTED_REFERENCE")
        if actor_user_id != ws.user_id or actor_user_id != project_record.user_id:
            raise BatchApplyError("BATCH_OWNER_MISMATCH")
        if project_record.project_id != ws.project_id:
            raise BatchApplyError("BATCH_OWNER_MISMATCH")
        if ws.active_scenario_id != expected_scenario_id:
            raise StaleContentError("BATCH_SCENARIO_MISMATCH")
        if not isinstance(updates, list) or not 1 <= len(updates) <= 50:
            raise BatchApplyError("BATCH_UPDATES_INVALID", "Expected 1-50 approved updates.")
        if not isinstance(content_hash, str) or len(content_hash) != 64:
            raise BatchApplyError("BATCH_HASH_INVALID")

        seen_ids: set[str] = set()
        seen_paths: set[str] = set()
        for item in updates:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise BatchApplyError("BATCH_UPDATE_SHAPE_INVALID")
            field_id, raw_value = item
            if not isinstance(field_id, str) or not isinstance(raw_value, str):
                raise BatchApplyError("BATCH_UPDATE_TYPE_INVALID")
            if field_id in seen_ids:
                raise BatchApplyError("BATCH_DUPLICATE_FIELD", field_id)
            seen_ids.add(field_id)
            validation = WorkbookUpdateService.validate_field_update(field_id, raw_value)
            if not validation.is_valid:
                raise FieldValidationError(validation.error, validation.error_class)
            _assert_batch_field_applicable(
                field_id, project_type=project_record.project_type or "",
                template_source=project_record.template_source or "",
            )
            path = validation.spec.engine_path
            if path is not None:
                if path in seen_paths:
                    raise BatchApplyError("BATCH_CONFLICTING_CANONICAL_AUTHORITY", path)
                seen_paths.add(path)

        # OD-P90-01: check bidirectional P90 <= P50 against complete proposed state atomically
        if "project_setup.technical.p90_10y_hours" in seen_ids or "project_setup.technical.p50_hours" in seen_ids:
            snap = dict(ws.draft_snapshot or {})
            for fid, raw_v in updates:
                spec_i = WORKBOOK.field(fid)
                if spec_i.snapshot_key:
                    snap[spec_i.snapshot_key] = raw_v
            validate_proposed_p90_p50_snapshot(snap)

        if reject_line_owned:
            line_owned = find_line_owned_cost_fields(ws.project_id, seen_ids)
            if line_owned:
                first_fid, first_reason = next(iter(line_owned.items()))
                raise BatchApplyError("COST_CATEGORY_LINE_OWNED", f"{first_fid}: {first_reason}")

        # C1-Q-02 & OD-R04-02: validate proposed PPA book & global P50 cap atomically
        if (
            "revenue.multistream.contracts" in seen_ids
            or any(fid.startswith("project_setup.technical.") for fid in seen_ids)
        ):
            snap = dict(ws.draft_snapshot or {})
            for fid, raw_v in updates:
                spec_i = WORKBOOK.field(fid)
                if spec_i.snapshot_key:
                    snap[spec_i.snapshot_key] = raw_v
            if (snap.get("rev_multistream_config_json") or "").strip():
                _validate_ppa_book_against_proposed_snapshot(snap)

        # E2E-01 / C1F-A-5: validate complete proposed gearing and horizon > senior tenor atomically
        if seen_ids & {
            "debt.senior.gearing_pct",
            "debt.senior.tenor_years",
            "project_setup.technical.horizon_years",
        }:
            snap_fh = dict(ws.draft_snapshot or {})
            for fid, raw_v in updates:
                spec_i = WORKBOOK.field(fid)
                if spec_i.snapshot_key:
                    snap_fh[spec_i.snapshot_key] = raw_v
            validate_proposed_financing_horizon_snapshot(snap_fh)

        # P1-REV-03: reject competing dual nonzero balancing charges atomically on batch save
        if seen_ids & {"revenue.balancing.merchant_pct", "revenue.balancing.cost_eur_per_mwh"}:
            from finco_core.revenue.generation import validate_balancing_cost_inputs
            snap_bal = dict(ws.draft_snapshot or {})
            for fid, raw_v in updates:
                spec_i = WORKBOOK.field(fid)
                if spec_i.snapshot_key:
                    snap_bal[spec_i.snapshot_key] = raw_v
            try:
                pi_bal = ProjectInputSet.from_snapshot(snap_bal).to_projectinputs()
                validate_balancing_cost_inputs(pi_bal.revenue)
            except ValueError as exc:
                raise FieldValidationError(str(exc), FieldErrorClass.INVALID) from exc

        result = v2_atomic_batch_draft_update(
            user_id=actor_user_id,
            project_id=ws.project_id,
            expected_workspace_id=ws.workspace_id,
            expected_scenario_id=expected_scenario_id,
            expected_content_hash=content_hash,
            expected_workbook_version=workbook_version,
            updates=updates,
            in_tx_after_apply=in_tx_after_apply,
        )
        return ProjectInputSet.from_snapshot(result.draft_snapshot, workbook=WORKBOOK)


def validate_proposed_financing_horizon_snapshot(proposed_snapshot: Mapping[str, Any]) -> None:
    """E2E-01 / C1F-A-5: validate positive senior gearing and horizon > senior tenor on proposed state.

    Evaluates the complete proposed snapshot so paired atomic batch edits (e.g. increasing
    horizon_years and tenor_years together) succeed in either input order while invalid
    combinations fail closed before any DB write.
    """
    raw_gear = proposed_snapshot.get("gearing_pct")
    if raw_gear is not None and str(raw_gear).strip() != "":
        try:
            gear_f = float(str(raw_gear).strip())
        except (TypeError, ValueError):
            gear_f = None
        if gear_f is not None and gear_f <= 0.0:
            raise FieldValidationError(
                "ZERO_SENIOR_GEARING_NOT_SUPPORTED: explicit zero senior gearing (0%) is not supported "
                "until genuine all-equity no-debt economics are approved.",
                FieldErrorClass.INVALID,
            )

    raw_horizon = proposed_snapshot.get("horizon_years")
    raw_tenor = proposed_snapshot.get("tenor_years")
    if (
        raw_horizon is not None and str(raw_horizon).strip() != ""
        and raw_tenor is not None and str(raw_tenor).strip() != ""
    ):
        try:
            horizon_f = float(str(raw_horizon).strip())
            tenor_f = float(str(raw_tenor).strip())
        except (TypeError, ValueError):
            return
        if horizon_f <= tenor_f:
            raise FieldValidationError(
                f"DEBT_TENOR_EXCEEDS_HORIZON: project horizon ({int(horizon_f)} years) "
                f"must be strictly longer than senior debt tenor ({int(tenor_f)} years).",
                FieldErrorClass.INVALID,
            )


def validate_proposed_p90_p50_snapshot(proposed_snapshot: Mapping[str, Any]) -> None:
    """OD-P90-01: enforce canonical P90 <= P50 and finite/positive invariants on proposed snapshot state.

    Absent/blank operating_hours_p90_10y is permitted (legacy 0.9 * P50 fallback applies only in
    effective inputs without mutating saved state). When explicit operating_hours_p90_10y is present,
    both P50 and P90 must be finite, > 0, and P90 <= P50.
    """
    import math as _math

    raw_p90 = proposed_snapshot.get("operating_hours_p90_10y")
    if raw_p90 is None or (isinstance(raw_p90, str) and not raw_p90.strip()):
        return
    if isinstance(raw_p90, bool):
        raise FieldValidationError(
            "P90-10y operating hours must be a positive finite number.",
            FieldErrorClass.INVALID,
        )
    try:
        p90_f = float(raw_p90)
    except (TypeError, ValueError) as exc:
        raise FieldValidationError(
            f"P90-10y operating hours must be numeric (got {raw_p90!r}).",
            FieldErrorClass.INVALID,
        ) from exc
    if not _math.isfinite(p90_f) or p90_f <= 0:
        raise FieldValidationError(
            f"P90-10y operating hours must be positive and finite (got {raw_p90!r}).",
            FieldErrorClass.OUT_OF_RANGE if _math.isfinite(p90_f) else FieldErrorClass.NON_FINITE,
        )

    raw_p50 = proposed_snapshot.get("p50_hours")
    if raw_p50 is None or (isinstance(raw_p50, str) and not raw_p50.strip()):
        return
    if isinstance(raw_p50, bool):
        raise FieldValidationError(
            "P50 operating hours must be a positive finite number.",
            FieldErrorClass.INVALID,
        )
    try:
        p50_f = float(raw_p50)
    except (TypeError, ValueError) as exc:
        raise FieldValidationError(
            f"P50 operating hours must be numeric (got {raw_p50!r}).",
            FieldErrorClass.INVALID,
        ) from exc
    if not _math.isfinite(p50_f) or p50_f <= 0:
        raise FieldValidationError(
            f"P50 operating hours must be positive and finite (got {raw_p50!r}).",
            FieldErrorClass.OUT_OF_RANGE if _math.isfinite(p50_f) else FieldErrorClass.NON_FINITE,
        )

    if p90_f > p50_f:
        raise FieldValidationError(
            f"P90_EXCEEDS_P50: P90-10y operating hours ({p90_f:g}) cannot exceed P50 operating hours ({p50_f:g}).",
            FieldErrorClass.INVALID,
        )


def _validate_ppa_book_against_proposed_snapshot(proposed_snapshot: dict) -> None:
    """C1-Q-02: enforce canonical PPA contract book invariants against proposed timeline."""
    ms_json = (proposed_snapshot.get("rev_multistream_config_json") or "").strip()
    if not ms_json:
        return
    try:
        from app.input_adapter import build_projectinputs_from_snapshot
        from domain.revenue.multistream_runtime import parse_config
        from finco_core.engine.date_authority import dated_life_end_exclusive
        from finco_core.engine.period_engine import PeriodEngine, PeriodFrequency

        proposed_pi = build_projectinputs_from_snapshot(proposed_snapshot)
        info = proposed_pi.info
        freq_val = getattr(info.period_frequency, "value", str(info.period_frequency)).upper()
        freq = PeriodFrequency.ANNUAL if freq_val == "ANNUAL" else PeriodFrequency.SEMESTRIAL
        engine = PeriodEngine(
            financial_close=info.financial_close,
            construction_months=info.construction_months,
            horizon_years=info.horizon_years,
            ppa_years=proposed_pi.revenue.ppa_term_years,
            frequency=freq,
            cod_date=info.cod_date,
            period_axis_convention=getattr(info.period_axis_convention, "value", info.period_axis_convention),
            dated_life_end_exclusive=(
                dated_life_end_exclusive(
                    info.cod_date,
                    info.horizon_years,
                    ms_json,
                    date_authority_version=getattr(info, "date_authority_version", None),
                )
                if freq is PeriodFrequency.SEMESTRIAL
                else None
            ),
        )
        multistream = parse_config(ms_json)
        _date_aware = engine.dated_life_end_exclusive is not None
        multistream.validate_axis(engine.periods(), project_cod=proposed_pi.info.cod_date, date_aware=_date_aware)
        if getattr(multistream, "has_absolute_annual_quantity", False):
            if _date_aware:
                from finco_core.engine.date_authority import assert_grid_conserves_operating_life
                assert_grid_conserves_operating_life(proposed_pi, engine)
            multistream.validate_global_p50_cap(proposed_pi)
    except FieldValidationError:
        raise
    except Exception as exc:
        raise FieldValidationError(
            f"Proposed project timeline is incompatible with the saved PPA contract book: {exc}",
            FieldErrorClass.INVALID,
        ) from exc


def _is_diagnosed_legacy_repair(ws, field_id: str) -> bool:
    """True only when the current stored draft is diagnosed unrepairable-by-load and ``field_id`` is one of its issues."""
    try:
        from app.workbook.draft_recovery import diagnose_draft

        recovery = diagnose_draft(dict(ws.draft_snapshot or {}))
    except Exception:  # noqa: BLE001 - fail closed: no bypass
        return False
    if recovery is None:
        return False
    return any(getattr(i, "field_id", None) == field_id for i in recovery.issues)


def find_line_owned_cost_fields(project_id: str | None, field_ids, *, cur=None) -> dict[str, str]:
    """C1F-A-1: identify CAPEX/OPEX scalar fields whose category is owned by active cost lines.

    Active cost lines take precedence at canonical Run (apply_user_sub_lines_replacing_base /
    opex_fold_provenance). Writing a category scalar cannot change Run numbers, so callers
    must refuse or mark the field not-applicable rather than confirming Applied/STALE.
    """
    if not project_id:
        return {}
    fids = [f for f in field_ids if isinstance(f, str) and (f.startswith("capex.") or f.startswith("opex."))]
    if not fids:
        return {}

    blocked: dict[str, str] = {}
    capex_fids = [f for f in fids if f.startswith("capex.")]
    if capex_fids:
        from app.persistence.capex_sub_lines import (
            CAPEX_CATEGORY_TO_FIELD,
            CapexSubLine,
            get_active_sub_lines_for_project as get_active_capex_lines,
        )
        if cur is not None:
            _crows = cur.execute(
                "SELECT * FROM capex_sub_lines WHERE project_id = ? AND is_active = 1",
                (project_id,),
            ).fetchall()
            active_capex = tuple(CapexSubLine.from_row(r) for r in _crows)
        else:
            active_capex = get_active_capex_lines(project_id)
        if active_capex:
            owned_capex_attrs = {
                CAPEX_CATEGORY_TO_FIELD.get(row.parent_category_code)
                for row in active_capex
                if row.parent_category_code in CAPEX_CATEGORY_TO_FIELD
            }
            for fid in capex_fids:
                try:
                    spec = WORKBOOK.field(fid)
                except KeyError:
                    continue
                ep = spec.engine_path or ""
                if fid == "capex.total_capex_keur" or ep == "capex.total_capex":
                    blocked[fid] = "Active CAPEX cost lines own total CAPEX and take precedence at Run; edit cost lines instead."
                elif ep.startswith("capex."):
                    attr = ep.split(".")[1]
                    if attr in owned_capex_attrs:
                        blocked[fid] = (
                            f"Active CAPEX cost lines own category {attr!r} and take precedence at Run; "
                            "edit the individual cost lines instead."
                        )

    opex_fids = [f for f in fids if f.startswith("opex.")]
    if opex_fids:
        from app.persistence.opex_sub_lines import OpexSubLine
        from app.services.opex_sub_lines_integration import _load_all_sub_lines, opex_fold_provenance
        if cur is not None:
            _orows = cur.execute(
                "SELECT * FROM opex_sub_lines WHERE project_id = ?",
                (project_id,),
            ).fetchall()
            all_opex = tuple(OpexSubLine.from_row(r) for r in _orows)
        else:
            all_opex = _load_all_sub_lines(project_id)
        if all_opex:
            prov = opex_fold_provenance(all_opex)
            # Only a group whose canonical key is replaced by reference-seeded lines is shadowed
            # (same authority as opex_group_authority_notes / the Run fold). Independently
            # effective categories stay writable.
            from app.ui.opex_sheet_projection import CANONICAL_OPEX_GROUPS
            from app.v2.opex_assembly import _OPEX_NAME_TO_CODE

            replaced_codes = {
                _OPEX_NAME_TO_CODE[name]
                for name in prov.get("replaced_canonical_keys") or ()
                if name in _OPEX_NAME_TO_CODE
            }
            shadowed_fields = {
                f"opex.lines.{g.field_suffix}"
                for g in CANONICAL_OPEX_GROUPS
                if g.field_suffix and g.code in replaced_codes
            }
            for fid in opex_fids:
                if fid in shadowed_fields:
                    blocked[fid] = (
                        "Active OPEX cost lines replace this category's base scalar at Run; "
                        "edit the individual OPEX cost lines instead."
                    )
                elif fid == "opex.summary.y1_total_keur" and prov.get("replaces_aggregate"):
                    blocked[fid] = (
                        "Active OPEX cost lines replace the aggregate OPEX scalar at Run; "
                        "edit the individual OPEX cost lines instead."
                    )
    return blocked

