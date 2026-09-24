"""Phase 57A-9B: CAPEX user-added sub-lines — schema helpers + pure contract.

This module holds the schema-side helpers for user-added CAPEX
sub-lines. The runtime side (save/load, Run integration, Excel
export) is intentionally NOT in this module — those land in
57A-9C, 57A-9D, and 57A-9E respectively.

What this module does:

- Defines ``CapexSubLine``, the in-memory record shape.
- Defines ``CAPEX_CATEGORY_TO_FIELD``, the locked per-category
  mapping from C.NN category code to ``CapexStructure`` field
  name. C.17 / C.18 are explicitly rejected (read-only).
- Provides pure validators (``validate_parent_category``,
  ``validate_business_code``) and a pure counter
  (``generate_next_business_code``) that operate on whatever
  sequence the caller passes (a list of existing codes, a
  database cursor, etc.).
- Provides CRUD-style helpers that take an explicit
  ``sqlite3.Cursor`` (``create_sub_line``,
  ``list_sub_lines_for_project``, ``soft_delete_sub_line``).
  These do not import the model layer and do not call any
  service. They are the lowest level of the persistence stack.
- Provides ``assert_project_allows_capex_sub_lines`` which
  enforces the ``project_origin`` invariant (factory_template
  is rejected with ``PermissionError``).
- Provides pure helpers
  (``resolve_effective_sub_line_amount``,
  ``fold_sub_lines_into_capex``) that pin the **override
  replaces default** aggregation contract from the Claude
  delta review of 57A-9A. ``fold_sub_lines_into_capex`` is a
  factory no-op (returns the input ``capex`` unchanged when
  no user sub-lines are provided).

What this module does NOT do:

- Does NOT modify the existing ``update_scenario_overrides``
  behavior. The scenario-override allowlist extension is
  landed in 57A-9C.
- Does NOT wire into the Run pipeline. The
  ``_apply_user_sub_lines_to_capex`` invocation point is
  pinned in 57A-9D.
- Does NOT touch the Excel export. The materialization into
  ``advanced_capex_line_items`` is pinned in 57A-9E.
- Does NOT touch ``domain/inputs.py`` or any model /
  waterfall / factory code.
- Does NOT touch any template, CSS, or JS.

The schema and the locked mapping are documented in
``docs/phase57a9a_capex_add_line_persistence_design_gate.md``
(merged in PR #505) and re-stated in
``docs/phase57a9b_capex_sub_lines_schema.md``.
"""

from __future__ import annotations

import re
import uuid

from app.persistence.db import get_cursor
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Locked per-category mapping (Phase 57A-9A §6.4 + Claude delta review).
# C.01..C.16 map to the 15 named CapexItem fields. C.17 / C.18 are
# explicitly rejected (read-only, no per-line mapping).
# C.08 and C.11 BOTH fold into audit_legal — this is a deliberate
# ambiguity from the source data, not a bug. The mapping is locked
# at this point and any change requires a new design PR.
# ---------------------------------------------------------------------------

CAPEX_CATEGORY_TO_FIELD: Mapping[str, str] = {
    "C.01": "production_units",
    "C.02": "epc_contract",
    "C.03": "grid_connection",
    "C.04": "ops_prep",
    "C.05": "epc_other",
    "C.06": "insurances",
    "C.07": "lease_tax",
    "C.08": "audit_legal",
    "C.09": "construction_mgmt_a",
    "C.10": "commissioning",
    "C.11": "audit_legal",  # C.08 and C.11 both fold additively
    "C.12": "construction_mgmt_b",
    "C.13": "contingencies",
    "C.14": "taxes",
    "C.15": "project_acquisition",
    "C.16": "project_rights",
}

ALLOWED_PARENT_CATEGORIES: frozenset[str] = frozenset(
    CAPEX_CATEGORY_TO_FIELD.keys()
)

REJECTED_PARENT_CATEGORIES: frozenset[str] = frozenset({"C.17", "C.18"})

SCALAR_CAPEX_METADATA_REPLAY_KEY = "_scalar_capex_metadata"

APPROVED_SCALAR_CAPEX_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "contingency_pct",
        "vat_recoverable_flag",
        "vat_rate_pct",
        "vat_basis_mode",
        "vat_jurisdiction_code",
        "wht_rate_pct",
        "wht_treatment_mode",
        "wht_gross_up_flag",
        "wht_jurisdiction_code",
        "depreciation_asset_class",
        "depreciation_useful_life_years",
        "depreciable_flag",
        "depreciation_basis_mode",
    }
)

NON_PERSISTED_APPROVED_METADATA_KEYS: frozenset[str] = frozenset({"cost_per_mw"})

SCALAR_CAPEX_METADATA_EXPORT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("contingency_pct", "Contingency %"),
    ("vat_recoverable_flag", "VAT Recoverable Flag"),
    ("vat_rate_pct", "VAT Rate %"),
    ("vat_basis_mode", "VAT Basis Mode"),
    ("vat_jurisdiction_code", "VAT Jurisdiction"),
    ("wht_rate_pct", "WHT Rate %"),
    ("wht_treatment_mode", "WHT Treatment Mode"),
    ("wht_gross_up_flag", "WHT Gross-up Flag"),
    ("wht_jurisdiction_code", "WHT Jurisdiction"),
    ("depreciation_asset_class", "Depreciation Asset Class"),
    ("depreciation_useful_life_years", "Depreciation Useful Life (Years)"),
    ("depreciable_flag", "Depreciable Flag"),
    ("depreciation_basis_mode", "Depreciation Basis Mode"),
)


# ---------------------------------------------------------------------------
# Business code format: C.NN.U### (U prefix marks user-added).
# 3-digit zero-padded counter, per (project_id, parent_category_code).
# ---------------------------------------------------------------------------

_BUSINESS_CODE_RE = re.compile(r"^C\.(\d{2})\.U(\d{3})$")
_REFERENCE_DETAIL_CODE_RE = re.compile(r"^C\.\d{2}\.\d{2}$")
_PARENT_CODE_RE = re.compile(r"^C\.(\d{2})$")


# ---------------------------------------------------------------------------
# Record shape
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CapexSubLine:
    """In-memory record for a user-added CAPEX sub-line.

    Mirrors the ``capex_sub_lines`` table exactly. The ``id`` and
    ``created_at`` / ``updated_at`` fields are populated by the
    persistence layer on insert; the rest are caller-supplied.
    """

    sub_line_id: str
    project_id: str
    parent_category_code: str
    business_code: str
    display_order: int
    label: str
    amount_keur: float = 0.0
    comments: str = ""
    schedule_json: str = "{}"
    scalar_metadata: dict[str, Any] = field(default_factory=dict)
    source: str = "user"
    is_active: bool = True
    governance_state: dict[str, Any] = field(default_factory=dict)
    replay_metadata: dict[str, Any] = field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    id: Optional[int] = None  # populated by the DB on insert

    @classmethod
    def from_row(cls, row: Any) -> "CapexSubLine":
        """Build a record from a sqlite3.Row (or any dict-like row)."""
        # sqlite3.Row supports both index and key access. We use
        # ``row[k]`` so the helper works for both Row and dict.
        def _get(key: str, default: Any = None) -> Any:
            try:
                return row[key]
            except (KeyError, IndexError):
                return default

        import json as _json

        raw_replay_metadata = _json.loads(
            _get("replay_metadata_json", "{}") or "{}"
        )
        replay_metadata, scalar_metadata = _split_scalar_metadata_payload(
            raw_replay_metadata
        )

        return cls(
            id=_get("id"),
            sub_line_id=_get("sub_line_id"),
            project_id=_get("project_id"),
            parent_category_code=_get("parent_category_code"),
            business_code=_get("business_code"),
            display_order=int(_get("display_order", 0) or 0),
            label=_get("label", "") or "",
            amount_keur=float(_get("amount_keur", 0.0) or 0.0),
            comments=_get("comments", "") or "",
            schedule_json=_get("schedule_json", "{}") or "{}",
            scalar_metadata=scalar_metadata,
            source=_get("source", "user") or "user",
            is_active=bool(_get("is_active", 0)),
            governance_state=_json.loads(_get("governance_state_json", "{}") or "{}"),
            replay_metadata=replay_metadata,
            created_at=_get("created_at"),
            updated_at=_get("updated_at"),
        )


def sanitize_scalar_capex_metadata(
    scalar_metadata: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate and normalize persisted scalar CAPEX metadata."""
    if not scalar_metadata:
        return {}
    if not isinstance(scalar_metadata, Mapping):
        raise ValueError("scalar_metadata must be a mapping when provided")

    metadata = dict(scalar_metadata)
    unknown = sorted(
        key
        for key in metadata.keys()
        if key not in APPROVED_SCALAR_CAPEX_METADATA_KEYS
        and key not in NON_PERSISTED_APPROVED_METADATA_KEYS
    )
    if unknown:
        raise ValueError(
            f"Unsupported scalar CAPEX metadata keys: {unknown}. "
            f"Approved keys are {sorted(APPROVED_SCALAR_CAPEX_METADATA_KEYS)}"
        )

    blocked = sorted(
        key for key in metadata.keys() if key in NON_PERSISTED_APPROVED_METADATA_KEYS
    )
    if blocked:
        raise ValueError(
            f"Derived-only CAPEX metadata keys cannot be persisted: {blocked}"
        )

    normalized: dict[str, Any] = {}
    for key, value in metadata.items():
        if value is None or value == "":
            continue
        if key in {"vat_recoverable_flag", "wht_gross_up_flag", "depreciable_flag"}:
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be a boolean")
            normalized[key] = value
        elif key in {"contingency_pct", "vat_rate_pct", "wht_rate_pct"}:
            if not isinstance(value, (int, float)):
                raise ValueError(f"{key} must be numeric")
            value = float(value)
            if value < 0 or value > 100:
                raise ValueError(f"{key} must be between 0 and 100")
            normalized[key] = value
        elif key == "depreciation_useful_life_years":
            if not isinstance(value, (int, float)) or int(value) != value or int(value) <= 0:
                raise ValueError(
                    "depreciation_useful_life_years must be a positive integer"
                )
            normalized[key] = int(value)
        else:
            if not isinstance(value, str):
                raise ValueError(f"{key} must be a string")
            normalized[key] = value.strip()
    return normalized


def _split_scalar_metadata_payload(
    replay_metadata: Optional[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    replay = dict(replay_metadata or {})
    raw_scalar = replay.pop(SCALAR_CAPEX_METADATA_REPLAY_KEY, {})
    if not isinstance(raw_scalar, Mapping):
        raw_scalar = {}
    return replay, sanitize_scalar_capex_metadata(raw_scalar)


def _pack_scalar_metadata_payload(
    replay_metadata: Optional[Mapping[str, Any]],
    scalar_metadata: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    replay = dict(replay_metadata or {})
    clean_scalar = sanitize_scalar_capex_metadata(scalar_metadata)
    if clean_scalar:
        replay[SCALAR_CAPEX_METADATA_REPLAY_KEY] = clean_scalar
    else:
        replay.pop(SCALAR_CAPEX_METADATA_REPLAY_KEY, None)
    return replay


# ---------------------------------------------------------------------------
# Pure validators
# ---------------------------------------------------------------------------


def validate_parent_category(code: Any) -> str:
    """Validate a parent category code (e.g. ``"C.02"``).

    Returns the code unchanged on success. Raises
    ``ValueError`` for an unknown / malformed / rejected code.
    Specifically:
      - The code must be a non-empty string.
      - It must match ``C.NN`` where NN is a 2-digit integer.
      - It must be in ``ALLOWED_PARENT_CATEGORIES`` (C.01..C.16).
      - ``C.17`` and ``C.18`` are explicitly rejected with a
        clear error message (they are read-only in the
        C.01..C.18 catalogue).
      - Any other ``C.NN`` (e.g. ``C.99``) is rejected as
        unknown (never silently dropped).
    """
    if not isinstance(code, str) or not code:
        raise ValueError(
            f"parent_category_code must be a non-empty string, got {code!r}"
        )
    m = _PARENT_CODE_RE.match(code)
    if not m:
        raise ValueError(
            f"parent_category_code must match C.NN (NN is 2 digits), "
            f"got {code!r}"
        )
    if code in REJECTED_PARENT_CATEGORIES:
        raise ValueError(
            f"parent_category_code {code!r} is rejected: "
            f"C.17 and C.18 are read-only in the CAPEX catalogue "
            f"and do not accept user-added sub-lines"
        )
    if code not in ALLOWED_PARENT_CATEGORIES:
        raise ValueError(
            f"parent_category_code {code!r} is not a known CAPEX "
            f"category; allowed categories are "
            f"{sorted(ALLOWED_PARENT_CATEGORIES)}"
        )
    return code


def validate_business_code(code: Any) -> str:
    """Validate a business code (e.g. ``"C.02.U001"``).

    Returns the code unchanged on success. Raises
    ``ValueError`` for a malformed / non-user-prefixed /
    out-of-range code. The format is ``C.NN.U###``:
      - ``C`` literal prefix.
      - ``NN`` is the 2-digit zero-padded parent category
        number (must be 01..16; the parent itself is
        separately validated when the line is created).
      - ``U`` literal prefix marking "user-added" — keeps
        the namespace disjoint from the template
        ``C.NN.NN`` codes.
      - ``###`` is the 3-digit zero-padded counter.
    """
    if not isinstance(code, str) or not code:
        raise ValueError(
            f"business_code must be a non-empty string, got {code!r}"
        )
    m = _BUSINESS_CODE_RE.match(code)
    if not m:
        raise ValueError(
            f"business_code {code!r} does not match the required "
            f"format C.NN.U### (NN=2 digits, ###=3 digits)"
        )
    return code


def category_for_field_name(field_name: str) -> str:
    """Return the canonical C.NN category code for a CapexStructure field.

    Raises ``KeyError`` if the field is not in the mapping. Some
    fields (C.08 / C.11) are both mapped to ``audit_legal``;
    the reverse mapping is therefore ambiguous, so this helper
    returns the FIRST category code in ``CAPEX_CATEGORY_TO_FIELD``
    that maps to the given field (insertion order is preserved
    in Python 3.7+). Callers that need a deterministic
    one-to-one reverse mapping should use
    ``_first_category_for_field_name`` explicitly OR maintain
    a separate reverse-mapping table.
    """
    for code, field in CAPEX_CATEGORY_TO_FIELD.items():
        if field == field_name:
            return code
    raise KeyError(
        f"CapexStructure field {field_name!r} is not in the "
        f"CAPEX_CATEGORY_TO_FIELD mapping; allowed fields are "
        f"{sorted(set(CAPEX_CATEGORY_TO_FIELD.values()))}"
    )


# ---------------------------------------------------------------------------
# Pure counter: generate next business code
# ---------------------------------------------------------------------------


def _counter_for_existing_codes(
    existing_codes: Iterable[str],
    parent_category_code: str,
) -> int:
    """Return the next 1-based counter for the given parent category.

    Iterates ``existing_codes`` (which may include soft-deleted
    rows — soft-deleted codes still occupy their counter slot
    so audit trails remain readable and re-using the same code
    after delete is impossible). Returns the smallest positive
    integer N such that ``C.<NN>.U<NNN>`` is NOT in
    ``existing_codes``. If no codes exist for the parent, the
    counter starts at 1.
    """
    max_seen = 0
    matched_any = False
    for code in existing_codes:
        try:
            validate_business_code(code)
        except ValueError:
            # Silently skip malformed codes (defensive — a
            # corrupted DB row should not break the counter).
            continue
        m = _BUSINESS_CODE_RE.match(code)
        assert m is not None  # validate_business_code already checked
        code_parent = f"C.{m.group(1)}"
        if code_parent != parent_category_code:
            continue
        matched_any = True
        counter = int(m.group(2))
        if counter > max_seen:
            max_seen = counter
    if not matched_any:
        return 1
    return max_seen + 1


def generate_next_business_code(
    existing_codes: Iterable[str],
    parent_category_code: str,
) -> str:
    """Generate the next business code for the given parent category.

    The parent category is validated first (rejects C.17 / C.18
    and any unknown code). The counter starts at 1 for a fresh
    parent and increments past the highest existing counter for
    that parent. Gaps are preserved on soft-delete: if
    ``C.02.U001`` is soft-deleted, the next call still returns
    ``C.02.U002`` (the gap is the audit trail, not a free slot).

    ``existing_codes`` may be any iterable of strings (the
    in-memory list from a previous query, the result of
    ``SELECT business_code FROM capex_sub_lines``, etc.). This
    keeps the helper testable without a database.
    """
    validate_parent_category(parent_category_code)
    counter = _counter_for_existing_codes(existing_codes, parent_category_code)
    # ``parent_category_code`` is e.g. "C.02"; we want "C.02.U001".
    nn = parent_category_code.split(".")[1]
    return f"C.{nn}.U{counter:03d}"


# ---------------------------------------------------------------------------
# Factory project guard
# ---------------------------------------------------------------------------


def assert_project_allows_capex_sub_lines(project_record: Any) -> None:
    """Raise ``PermissionError`` if the project forbids sub-lines.

    Allowed origins (per Phase 57A-9A §5.5):
      - ``user_project`` — user-created project.
      - ``saved_baseline`` — user-cloned copy of a factory
        template, mutable.

    Rejected origins:
      - ``factory_template`` — Generic Wind Reference, Generic Solar Reference, Generic Wind,
        Generic Solar. Read-only; sub-lines cannot be added.

    The check uses the project record's ``project_origin`` field
    and (defensively) the ``is_readonly`` field. A
    ``factory_template`` with ``is_readonly=False`` is still
    rejected (defense in depth).

    The function returns ``None`` on success.
    """
    if project_record is None:
        raise PermissionError(
            "Cannot add CAPEX sub-lines: project record is None"
        )
    origin = getattr(project_record, "project_origin", None)
    is_readonly = bool(getattr(project_record, "is_readonly", False))
    if origin == "factory_template" or is_readonly:
        raise PermissionError(
            f"Cannot add CAPEX sub-lines to a {origin!r} project "
            f"(is_readonly={is_readonly}). Sub-lines are only "
            f"allowed on user_project or saved_baseline origins. "
            f"Factory templates (Generic Wind Reference, Generic Solar Reference, Generic Wind, "
            f"Generic Solar) are read-only."
        )
    if origin not in ("user_project", "user_created", "saved_baseline"):
        raise PermissionError(
            f"Cannot add CAPEX sub-lines: unknown project_origin "
            f"{origin!r}; expected one of 'user_project', 'user_created', "
            f"'saved_baseline', 'factory_template'"
        )


# ---------------------------------------------------------------------------
# Pure aggregation helpers (Claude delta review fix)
# ---------------------------------------------------------------------------


def resolve_effective_sub_line_amount(
    default_amount_keur: float,
    scenario_override_amount_keur: Optional[float],
) -> float:
    """Resolve the effective amount for a single sub-line.

    Claude delta review fix to Phase 57A-9A §6.5: a scenario
    override **REPLACES** the default amount. It is NOT a
    delta adjustment (the user does not write
    "amount + 100"; they write the new amount).

    Semantics:
      - ``scenario_override_amount_keur is None`` → returns
        ``default_amount_keur``.
      - ``scenario_override_amount_keur`` is a number →
        returns that number (even if it is 0, negative, or
        larger than the default).

    This helper is pure (no I/O, no DB, no project context).
    It is the single source of truth for the override
    semantic. ``fold_sub_lines_into_capex`` uses it; the
    future Run integration in 57A-9D uses it; nothing else
    should redefine the semantic.

    Examples:
        >>> resolve_effective_sub_line_amount(50.0, None)
        50.0
        >>> resolve_effective_sub_line_amount(50.0, 999.0)
        999.0
        >>> resolve_effective_sub_line_amount(50.0, 0.0)
        0.0
        >>> # NOT a delta:
        >>> resolve_effective_sub_line_amount(50.0, 999.0) != (50.0 + 999.0)
        True
    """
    if scenario_override_amount_keur is None:
        result = float(default_amount_keur)
    else:
        result = float(scenario_override_amount_keur)
    # Defense-in-depth: the effective amount must always be finite.
    # _extract_sub_line_overrides guards before this point; this guard
    # catches any remaining path (e.g. non-finite default_amount_keur).
    import math
    if not math.isfinite(result):
        raise ValueError(
            f"resolve_effective_sub_line_amount: computed non-finite amount "
            f"({result!r}); refusing to use as CAPEX economics."
        )
    return result


def fold_sub_lines_into_capex(
    capex: Any,
    user_sub_lines: Sequence[CapexSubLine],
    scenario_overrides: Optional[Mapping[str, float]] = None,
) -> Any:
    """Fold user sub-lines into a CapexStructure (pure helper).

    Aggregation rule (Claude delta review fix):
      - Factory project no-op: if ``user_sub_lines`` is empty
        (the typical case for Generic Wind Reference/Generic Solar Reference/Generic
        Solar/Generic Wind factory templates), the helper
        returns ``capex`` unchanged. This is the
        Generic Wind Reference/Generic Solar Reference parity guarantee.
      - Otherwise, for each sub-line:
          1. Look up the parent's ``CapexStructure`` field
             via ``CAPEX_CATEGORY_TO_FIELD``. Unknown
             categories raise ``ValueError`` — never silent
             drop.
          2. Resolve the effective amount via
             ``resolve_effective_sub_line_amount`` (override
             REPLACES default, not a delta).
          3. The effective amount is added to the existing
             ``CapexItem.amount_keur`` value of the field.
             So the field ends up as
             ``base + sum(effective_sub_line_amounts)``.
      - Soft-deleted sub-lines (``is_active=False``) are
        EXCLUDED from the sum.
      - Multiple sub-lines under the same parent category
        fold additively into the same field. C.08 / C.11
        both fold into ``audit_legal`` — the additive
        accumulation is intentional and locked.

    The ``capex`` argument is a ``CapexStructure`` (or any
    object with the same 15 named fields). The function
    returns a NEW ``CapexStructure`` of the same type, with
    selected ``CapexItem.amount_keur`` fields updated. The
    input ``capex`` is not mutated (``CapexStructure`` is
    frozen, so a new instance is the only option).

    The ``scenario_overrides`` argument maps ``sub_line_id``
    (UUID) → override amount. Sub-line IDs not in the
    mapping fall back to the default amount.
    """
    # Factory no-op: empty user sub-lines (the typical factory
    # project case) returns capex unchanged.
    if not user_sub_lines:
        return capex

    overrides: Mapping[str, float] = scenario_overrides or {}

    # Compute per-field deltas. Initialized to 0 for every
    # field that appears in the mapping. We only mutate
    # fields that have a non-zero delta at the end.
    deltas: dict[str, float] = {field: 0.0 for field in set(CAPEX_CATEGORY_TO_FIELD.values())}
    for sub in user_sub_lines:
        if not sub.is_active:
            continue
        validate_parent_category(sub.parent_category_code)
        field_name = CAPEX_CATEGORY_TO_FIELD[sub.parent_category_code]
        effective = resolve_effective_sub_line_amount(
            sub.amount_keur,
            overrides.get(sub.sub_line_id),
        )
        deltas[field_name] += effective

    # If every delta is zero, the capex is unchanged (avoids
    # the cost of a new CapexStructure when nothing moved).
    if all(abs(v) < 1e-12 for v in deltas.values()):
        return capex

    # Build a new CapexStructure. ``CapexStructure`` is a
    # frozen dataclass, so we use ``dataclasses.replace``.
    import dataclasses
    import copy
    updates: dict[str, Any] = {}
    for field_name, delta in deltas.items():
        if abs(delta) < 1e-12:
            continue
        existing_item = getattr(capex, field_name)
        # CapexItem has a single amount field; we make a
        # shallow copy with the new amount.
        new_item = dataclasses.replace(existing_item, amount_keur=existing_item.amount_keur + delta)
        updates[field_name] = new_item
    return dataclasses.replace(capex, **updates)


# ---------------------------------------------------------------------------
# DB-backed helpers (lowest layer of the persistence stack)
# ---------------------------------------------------------------------------


def list_sub_lines_for_project(
    cur: Any,
    project_id: str,
    include_inactive: bool = False,
) -> Tuple[CapexSubLine, ...]:
    """List all sub-lines for a project, ordered by category + display_order.

    By default, only ``is_active=1`` rows are returned. Pass
    ``include_inactive=True`` to include soft-deleted rows (for
    audit / replay).
    """
    if include_inactive:
        cur.execute(
            """
            SELECT * FROM capex_sub_lines
            WHERE project_id = ?
            ORDER BY parent_category_code ASC, display_order ASC
            """,
            (project_id,),
        )
    else:
        cur.execute(
            """
            SELECT * FROM capex_sub_lines
            WHERE project_id = ? AND is_active = 1
            ORDER BY parent_category_code ASC, display_order ASC
            """,
            (project_id,),
        )
    return tuple(CapexSubLine.from_row(row) for row in cur.fetchall())


def list_business_codes_for_project(cur: Any, project_id: str) -> Tuple[str, ...]:
    """Return all business codes for a project (active + soft-deleted).

    Used by ``generate_next_business_code`` to compute the next
    counter — soft-deleted codes occupy their slot to keep the
    audit trail readable.
    """
    cur.execute(
        "SELECT business_code FROM capex_sub_lines WHERE project_id = ?",
        (project_id,),
    )
    return tuple(row[0] for row in cur.fetchall())


def create_sub_line(
    cur: Any,
    *,
    project_id: str,
    parent_category_code: str,
    label: str,
    amount_keur: float = 0.0,
    business_code: Optional[str] = None,
    comments: str = "",
    schedule_json: str = "{}",
    scalar_metadata: Optional[Mapping[str, Any]] = None,
    source: str = "user",
    replay_metadata: Optional[dict] = None,
    governance_state: Optional[dict] = None,
) -> CapexSubLine:
    """Insert a new sub-line row.

    Validates the parent category (C.01..C.16, C.17/C.18 rejected,
    unknown rejected) and the business code format. If no
    ``business_code`` is provided, the next counter for the
    parent is computed from the existing rows in the table.
    Returns the persisted record (with the database-assigned
    ``id``, ``created_at``, and ``updated_at``).

    The caller is responsible for opening the transaction and
    for the ``assert_project_allows_capex_sub_lines`` check
    before calling this function. This function does NOT
    enforce the project-origin invariant on its own because
    that requires a project record lookup.
    """
    validate_parent_category(parent_category_code)
    if not isinstance(label, str) or not label.strip():
        raise ValueError(f"label must be a non-empty string, got {label!r}")
    if not isinstance(amount_keur, (int, float)):
        raise ValueError(
            f"amount_keur must be a number, got {amount_keur!r} "
            f"of type {type(amount_keur).__name__}"
        )

    if business_code is None:
        existing = list_business_codes_for_project(cur, project_id)
        business_code = generate_next_business_code(existing, parent_category_code)
    elif source == "reference_seed" and _REFERENCE_DETAIL_CODE_RE.match(business_code):
        # Public generic seeded detail rows have the stable C.xx.xx taxonomy.
        # User-created rows remain restricted to the C.xx.Uxxx namespace.
        pass
    else:
        validate_business_code(business_code)

    sub_line_id = str(uuid.uuid4())

    # Compute display_order: max for the parent + 1, or 1 if none.
    cur.execute(
        """
        SELECT COALESCE(MAX(display_order), 0) FROM capex_sub_lines
        WHERE project_id = ? AND parent_category_code = ?
        """,
        (project_id, parent_category_code),
    )
    row = cur.fetchone()
    max_order = int(row[0]) if row and row[0] is not None else 0
    display_order = max_order + 1

    # Timestamps. We use the same ISO-8601 UTC pattern as the
    # rest of the persistence layer.
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    import json as _json
    clean_scalar_metadata = sanitize_scalar_capex_metadata(scalar_metadata)
    packed_replay_metadata = _pack_scalar_metadata_payload(
        replay_metadata, clean_scalar_metadata
    )
    cur.execute(
        """
        INSERT INTO capex_sub_lines (
            sub_line_id, project_id, parent_category_code, business_code,
            display_order, label, amount_keur, comments, schedule_json,
            source, is_active, governance_state_json, replay_metadata_json,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
        """,
        (
            sub_line_id,
            project_id,
            parent_category_code,
            business_code,
            display_order,
            label,
            float(amount_keur),
            comments,
            schedule_json,
            source,
            _json.dumps(governance_state or {}),
            _json.dumps(packed_replay_metadata),
            now,
            now,
        ),
    )
    inserted_id = cur.lastrowid
    return CapexSubLine(
        id=inserted_id,
        sub_line_id=sub_line_id,
        project_id=project_id,
        parent_category_code=parent_category_code,
        business_code=business_code,
        display_order=display_order,
        label=label,
        amount_keur=float(amount_keur),
        comments=comments,
        schedule_json=schedule_json,
        scalar_metadata=clean_scalar_metadata,
        source=source,
        is_active=True,
        governance_state=governance_state or {},
        replay_metadata=dict(replay_metadata or {}),
        created_at=now,
        updated_at=now,
    )


def soft_delete_sub_line(
    cur: Any,
    *,
    project_id: str,
    sub_line_id: str,
) -> bool:
    """Soft-delete a sub-line by setting ``is_active = 0``.

    Returns ``True`` if a row was updated, ``False`` if no
    matching active row was found. The row is kept in the
    table for audit / replay; the ``business_code`` slot is
    NOT released (gaps are preserved on soft-delete).
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    cur.execute(
        """
        UPDATE capex_sub_lines
        SET is_active = 0, updated_at = ?
        WHERE project_id = ? AND sub_line_id = ? AND is_active = 1
        """,
        (now, project_id, sub_line_id),
    )
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# High-level save/load helpers (Phase 57A-9C wiring)
# ---------------------------------------------------------------------------


def replace_sub_lines_for_project(
    cur: Any,
    *,
    project_id: str,
    sub_lines: Sequence[CapexSubLine],
) -> list[CapexSubLine]:
    """Replace the project's active sub-lines with the given set.

    This is the **save flow** wiring for Phase 57A-9C. The
    pattern is the standard Phase 53G audit-friendly one:
    rows are NEVER hard-deleted, only soft-deleted
    (``is_active = 0``). The audit / replay trail in the
    table is preserved across saves.

    Behavior per input sub-line:

    1. If the input carries a ``sub_line_id`` and a row
       with that UUID already exists for the project
       (active OR soft-deleted), the existing row is
       **updated in place**: ``is_active`` is set back
       to 1, all the user-editable fields are refreshed
       (label, amount, comments, schedule_json,
       display_order, business_code, source,
       governance_state, replay_metadata), and
       ``updated_at`` is bumped. The original ``id`` and
       ``created_at`` are preserved. This is the
       audit-replay-safe update path.
    2. If the input carries a ``sub_line_id`` and no row
       with that UUID exists for the project, a new
       row is INSERTed.
    3. If the input does NOT carry a ``sub_line_id``, a
       fresh UUID is generated and a new row is
       INSERTed.

    After all upserts, any active row whose
    ``sub_line_id`` is NOT in the new set is
    soft-deleted (``is_active = 0``). This is the
    "remove" semantic for sub-lines that the caller
    no longer includes. For an empty input list
    (``capex_sub_lines=[]``), this step soft-deletes
    every active row for the project, while leaving
    historical soft-deleted rows untouched for audit.

    The ``business_code`` is auto-computed for any
    sub-line whose ``business_code`` is empty (new
    lines) but the existing one is reused when
    supplied (round-trip).

    Returns the list of upserted records (with their
    database-assigned ``id``, ``created_at``,
    ``updated_at``).
    """
    import json as _json
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Upsert each input sub-line.
    upserted: list[CapexSubLine] = []
    new_sub_line_ids: list[str] = []
    for sub in sub_lines:
        # Determine the target sub_line_id: caller-supplied
        # or freshly generated. The caller-supplied path is
        # the round-trip-preservation path; the generated
        # path is for new lines.
        if sub.sub_line_id:
            target_id = sub.sub_line_id
        else:
            target_id = str(uuid.uuid4())
            new_sub_line_ids.append(target_id)

        # Determine the target business_code: caller-supplied
        # or auto-computed. The auto-compute counts ALL
        # existing rows (active + soft-deleted) so the gap
        # on soft-delete is preserved.
        if sub.business_code:
            validate_business_code(sub.business_code)
            business_code = sub.business_code
        else:
            existing = list_business_codes_for_project(cur, project_id)
            business_code = generate_next_business_code(
                existing, sub.parent_category_code,
            )
        clean_scalar_metadata = sanitize_scalar_capex_metadata(sub.scalar_metadata)
        packed_replay_metadata = _pack_scalar_metadata_payload(
            sub.replay_metadata, clean_scalar_metadata
        )

        # Determine the target display_order: caller-supplied
        # or auto-computed. The auto-compute uses the max
        # across all rows for the parent so it is stable
        # across soft-deletes.
        if sub.display_order and sub.display_order > 0:
            display_order = sub.display_order
        else:
            cur.execute(
                """
                SELECT COALESCE(MAX(display_order), 0)
                FROM capex_sub_lines
                WHERE project_id = ? AND parent_category_code = ?
                """,
                (project_id, sub.parent_category_code),
            )
            row = cur.fetchone()
            max_order = (
                int(row[0]) if row and row[0] is not None else 0
            )
            display_order = max_order + 1

        # Look up an existing row for this sub_line_id.
        # The lookup spans active + soft-deleted rows so
        # the in-place update path can re-activate a row
        # that was previously soft-deleted.
        cur.execute(
            """
            SELECT id, created_at FROM capex_sub_lines
            WHERE project_id = ? AND sub_line_id = ?
            """,
            (project_id, target_id),
        )
        existing_row = cur.fetchone()

        if existing_row is not None:
            # In-place update. The id and created_at are
            # preserved; is_active is flipped back to 1;
            # all user-editable fields are refreshed;
            # updated_at is bumped. NO hard delete.
            existing_id, existing_created_at = existing_row
            cur.execute(
                """
                UPDATE capex_sub_lines
                SET parent_category_code = ?,
                    business_code = ?,
                    display_order = ?,
                    label = ?,
                    amount_keur = ?,
                    comments = ?,
                    schedule_json = ?,
                    source = ?,
                    is_active = 1,
                    governance_state_json = ?,
                    replay_metadata_json = ?,
                    updated_at = ?
                WHERE project_id = ? AND sub_line_id = ?
                """,
                (
                    sub.parent_category_code,
                    business_code,
                    display_order,
                    sub.label,
                    float(sub.amount_keur),
                    sub.comments or "",
                    sub.schedule_json or "{}",
                    sub.source or "user",
                    _json.dumps(sub.governance_state or {}),
                    _json.dumps(packed_replay_metadata),
                    now_iso,
                    project_id,
                    target_id,
                ),
            )
            rec = CapexSubLine(
                id=existing_id,
                sub_line_id=target_id,
                project_id=project_id,
                parent_category_code=sub.parent_category_code,
                business_code=business_code,
                display_order=display_order,
                label=sub.label,
                amount_keur=float(sub.amount_keur),
                comments=sub.comments or "",
                schedule_json=sub.schedule_json or "{}",
                scalar_metadata=clean_scalar_metadata,
                source=sub.source or "user",
                is_active=True,
                governance_state=sub.governance_state or {},
                replay_metadata=dict(sub.replay_metadata or {}),
                created_at=existing_created_at,
                updated_at=now_iso,
            )
        else:
            # INSERT a brand-new row.
            cur.execute(
                """
                INSERT INTO capex_sub_lines (
                    sub_line_id, project_id, parent_category_code,
                    business_code, display_order, label, amount_keur,
                    comments, schedule_json, source, is_active,
                    governance_state_json, replay_metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    target_id,
                    project_id,
                    sub.parent_category_code,
                    business_code,
                    display_order,
                    sub.label,
                    float(sub.amount_keur),
                    sub.comments or "",
                    sub.schedule_json or "{}",
                    sub.source or "user",
                    _json.dumps(sub.governance_state or {}),
                    _json.dumps(packed_replay_metadata),
                    now_iso,
                    now_iso,
                ),
            )
            new_id = cur.lastrowid
            rec = CapexSubLine(
                id=new_id,
                sub_line_id=target_id,
                project_id=project_id,
                parent_category_code=sub.parent_category_code,
                business_code=business_code,
                display_order=display_order,
                label=sub.label,
                amount_keur=float(sub.amount_keur),
                comments=sub.comments or "",
                schedule_json=sub.schedule_json or "{}",
                scalar_metadata=clean_scalar_metadata,
                source=sub.source or "user",
                is_active=True,
                governance_state=sub.governance_state or {},
                replay_metadata=dict(sub.replay_metadata or {}),
                created_at=now_iso,
                updated_at=now_iso,
            )
        upserted.append(rec)

    # 2. Soft-delete active rows that are NOT in the new
    # set. This is the "remove" semantic: caller dropped a
    # sub-line, or caller passed an empty list. We only
    # flip is_active; we never hard-delete.
    new_ids_for_set: set[str] = {
        s.sub_line_id for s in sub_lines if s.sub_line_id
    }
    new_ids_for_set.update(new_sub_line_ids)
    if new_ids_for_set:
        placeholders = ",".join("?" for _ in new_ids_for_set)
        cur.execute(
            f"""
            UPDATE capex_sub_lines
            SET is_active = 0, updated_at = ?
            WHERE project_id = ? AND is_active = 1
              AND sub_line_id NOT IN ({placeholders})
            """,
            (now_iso, project_id, *new_ids_for_set),
        )
    else:
        # No incoming sub_lines at all. Soft-delete every
        # active row for the project.
        cur.execute(
            """
            UPDATE capex_sub_lines
            SET is_active = 0, updated_at = ?
            WHERE project_id = ? AND is_active = 1
            """,
            (now_iso, project_id),
        )

    return upserted


def soft_delete_sub_line_for_project(
    cur: Any,
    *,
    project_id: str,
    sub_line_id: str,
) -> bool:
    """Soft-delete a single sub-line by id.

    This is the canonical alias of ``soft_delete_sub_line``,
    used by the save flow to mark a removed line in-memory
    and then ask the persistence layer to mark it inactive.
    """
    return soft_delete_sub_line(
        cur, project_id=project_id, sub_line_id=sub_line_id,
    )


def get_active_sub_lines_for_project(
    project_id: str,
) -> list[CapexSubLine]:
    """Read active sub-lines for a project (load flow).

    Convenience wrapper that opens a short-lived cursor.
    For callers that already hold a cursor, use
    ``list_sub_lines_for_project`` directly. The wrapper
    returns a list (not a tuple) for ergonomics in the
    save/load flow; the underlying helper returns a tuple.
    """
    with get_cursor() as cur:
        return list(
            list_sub_lines_for_project(cur, project_id, include_inactive=False)
        )


def update_sub_line(
    cur: Any,
    *,
    project_id: str,
    sub_line_id: str,
    label: str,
    amount_keur: float,
    comments: str = "",
    display_order: Optional[int] = None,
    row_version: str,
) -> Optional[CapexSubLine]:
    """Update an active sub-line, guarded by row_version (updated_at).

    ``row_version`` must equal the current ``updated_at`` value for the row.
    Returns the updated ``CapexSubLine`` on success, or ``None`` if no
    matching active row with that ``updated_at`` was found (concurrent edit
    or stale token).

    The caller is responsible for opening the transaction.
    """
    if not isinstance(label, str) or not label.strip():
        raise ValueError(f"label must be a non-empty string, got {label!r}")
    if not isinstance(amount_keur, (int, float)):
        raise ValueError(f"amount_keur must be a number, got {amount_keur!r}")

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    if display_order is not None:
        cur.execute(
            """
            UPDATE capex_sub_lines
            SET label = ?, amount_keur = ?, comments = ?,
                source = CASE WHEN source = 'reference_seed' THEN 'user_override' ELSE source END,
                display_order = ?, updated_at = ?
            WHERE project_id = ? AND sub_line_id = ?
              AND is_active = 1 AND updated_at = ?
            """,
            (
                label, float(amount_keur), comments or "",
                display_order, now,
                project_id, sub_line_id, row_version,
            ),
        )
    else:
        cur.execute(
            """
            UPDATE capex_sub_lines
            SET label = ?, amount_keur = ?, comments = ?,
                source = CASE WHEN source = 'reference_seed' THEN 'user_override' ELSE source END,
                updated_at = ?
            WHERE project_id = ? AND sub_line_id = ?
              AND is_active = 1 AND updated_at = ?
            """,
            (
                label, float(amount_keur), comments or "",
                now,
                project_id, sub_line_id, row_version,
            ),
        )
    if cur.rowcount == 0:
        return None
    cur.execute(
        "SELECT * FROM capex_sub_lines WHERE project_id = ? AND sub_line_id = ?",
        (project_id, sub_line_id),
    )
    row = cur.fetchone()
    return CapexSubLine.from_row(row) if row else None


def deactivate_sub_line_with_version(
    cur: Any,
    *,
    project_id: str,
    sub_line_id: str,
    row_version: str,
) -> bool:
    """Soft-delete a sub-line, guarded by row_version (updated_at).

    Returns ``True`` if the row was deactivated, ``False`` if no matching
    active row with that ``updated_at`` was found (concurrent edit or stale
    token).  The caller is responsible for opening the transaction.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    cur.execute(
        """
        UPDATE capex_sub_lines
        SET is_active = 0, updated_at = ?
        WHERE project_id = ? AND sub_line_id = ?
          AND is_active = 1 AND updated_at = ?
        """,
        (now, project_id, sub_line_id, row_version),
    )
    return cur.rowcount > 0


class ReorderConflictError(ValueError):
    """Raised when a reorder operation detects stale, unknown, duplicate, or
    missing row IDs. The transaction must be rolled back by the caller."""


def reorder_sub_lines(
    cur: Any,
    *,
    project_id: str,
    parent_category_code: str,
    ordered_rows: Sequence[Mapping[str, str]],
) -> list[CapexSubLine]:
    """Atomically reorder active sub-lines within a group.

    ``ordered_rows`` is the complete ordered set of active rows for the group,
    each as ``{"sub_line_id": str, "row_version": str}`` where ``row_version``
    is the ``updated_at`` timestamp (optimistic-lock token).

    Validation rules (ALL must pass or ReorderConflictError is raised):
    - No duplicate sub_line_id in the submitted list.
    - The submitted IDs exactly equal the current active ID set for the group
      (no unknown, no missing, no inactive IDs).
    - Every submitted row_version must equal the row's current updated_at.

    On success:
    - All active rows in the group receive unique contiguous display_order
      values 1..N in the submitted order.
    - No gaps, no duplicates.

    The caller is responsible for ensuring this function runs inside an
    exclusive transaction so the read-then-write is atomic.
    """
    validate_parent_category(parent_category_code)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    # 1. Load current active rows for the group.
    cur.execute(
        """
        SELECT sub_line_id, updated_at FROM capex_sub_lines
        WHERE project_id = ? AND parent_category_code = ? AND is_active = 1
        """,
        (project_id, parent_category_code),
    )
    db_rows = {r["sub_line_id"]: r["updated_at"] for r in cur.fetchall()}
    current_ids: set[str] = set(db_rows.keys())

    # 2. Validate submitted list.
    submitted_ids: list[str] = [r["sub_line_id"] for r in ordered_rows]
    submitted_versions: dict[str, str] = {
        r["sub_line_id"]: r["row_version"] for r in ordered_rows
    }

    # 2a. Duplicate IDs in the submitted list.
    if len(submitted_ids) != len(set(submitted_ids)):
        seen: set[str] = set()
        dups = [sid for sid in submitted_ids if sid in seen or seen.add(sid)]  # type: ignore[func-returns-value]
        raise ReorderConflictError(
            f"Duplicate sub_line_id(s) in reorder request: {dups!r}."
        )

    submitted_id_set = set(submitted_ids)

    # 2b. Unknown or inactive IDs (not in current active set).
    unknown = submitted_id_set - current_ids
    if unknown:
        raise ReorderConflictError(
            f"Unknown or inactive sub_line_id(s): {sorted(unknown)!r}. "
            "Reload the page and try again."
        )

    # 2c. Missing active IDs (active row not present in submitted list).
    missing = current_ids - submitted_id_set
    if missing:
        raise ReorderConflictError(
            f"Missing active sub_line_id(s) from reorder request: {sorted(missing)!r}. "
            "Submit the complete active set for the group."
        )

    # 2d. Stale row_version for any row.
    stale = [
        sid for sid in submitted_ids
        if submitted_versions[sid] != db_rows[sid]
    ]
    if stale:
        raise ReorderConflictError(
            f"Stale row_version for sub_line_id(s): {stale!r}. "
            "Reload and try again."
        )

    # 3. Update display_order 1..N (contiguous, no gaps).
    for new_order, sid in enumerate(submitted_ids, start=1):
        cur.execute(
            """
            UPDATE capex_sub_lines
            SET display_order = ?, updated_at = ?
            WHERE project_id = ? AND sub_line_id = ?
              AND parent_category_code = ? AND is_active = 1
            """,
            (new_order, now, project_id, sid, parent_category_code),
        )

    # 4. Read back in new order.
    cur.execute(
        """
        SELECT * FROM capex_sub_lines
        WHERE project_id = ? AND parent_category_code = ? AND is_active = 1
        ORDER BY display_order ASC
        """,
        (project_id, parent_category_code),
    )
    return [CapexSubLine.from_row(row) for row in cur.fetchall()]


__all__ = [
    "ALLOWED_PARENT_CATEGORIES",
    "APPROVED_SCALAR_CAPEX_METADATA_KEYS",
    "CAPEX_CATEGORY_TO_FIELD",
    "CapexSubLine",
    "NON_PERSISTED_APPROVED_METADATA_KEYS",
    "REJECTED_PARENT_CATEGORIES",
    "SCALAR_CAPEX_METADATA_EXPORT_COLUMNS",
    "assert_project_allows_capex_sub_lines",
    "category_for_field_name",
    "create_sub_line",
    "deactivate_sub_line_with_version",
    "fold_sub_lines_into_capex",
    "generate_next_business_code",
    "get_active_sub_lines_for_project",
    "list_business_codes_for_project",
    "list_sub_lines_for_project",
    "replace_sub_lines_for_project",
    "ReorderConflictError",
    "reorder_sub_lines",
    "resolve_effective_sub_line_amount",
    "sanitize_scalar_capex_metadata",
    "soft_delete_sub_line",
    "soft_delete_sub_line_for_project",
    "update_sub_line",
    "validate_business_code",
    "validate_parent_category",
]
