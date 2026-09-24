"""
CAPEX View Model — spreadsheet-style display layer for CAPEX grids.

Transforms ProjectContext.capex_detail_items into template-ready dataclasses.
No engine logic, no persistence, no routes.

canonical source: C.01–C.18 structure (Generic Wind Reference + Generic Solar Reference mapping, PR #849).

Editability contract:
  - Group header rows (C.01, C.02, …)   → never editable (display only)
  - C.13 Contingencies sub-lines         → is_contingency=True, is_derived=True, read-only
  - C.17 Financing Costs sub-lines       → is_financing=True, is_derived=True, read-only
  - C.18 Reserve Accounts sub-lines      → is_reserve=True, is_derived=True, read-only
  - All other sub-lines, user project    → is_editable=True, is_read_only=False
  - All other sub-lines, non-user        → is_editable=False, is_read_only=True (template lock)
  - is_custom lines (future)             → editable while is_active is True
  - Per-MW column                        → always derived, never submitted

Mutation contract:
  See AddCapexLineCommand / UpdateCapexLineCommand / DeactivateCapexLineCommand.
  These are typed intent objects — persistence is out of scope for this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from app.ui.project_context import ProjectContext
    from app.persistence.capex_sub_lines import CapexSubLine

# Lazy import cache — populated on first call to build_capex_view_model
_CAPEX_CATEGORY_TO_FIELD: "dict[str, str] | None" = None


def _get_cat_field_map() -> "dict[str, str]":
    global _CAPEX_CATEGORY_TO_FIELD
    if _CAPEX_CATEGORY_TO_FIELD is None:
        from app.persistence.capex_sub_lines import CAPEX_CATEGORY_TO_FIELD
        _CAPEX_CATEGORY_TO_FIELD = CAPEX_CATEGORY_TO_FIELD
    return _CAPEX_CATEGORY_TO_FIELD

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Groups that are always backend-computed / read-only
_READONLY_GROUP_CODES = frozenset({"C.17", "C.18"})

_FINANCING_CODE = "C.17"
_RESERVE_CODE = "C.18"
_CONTINGENCY_CODE = "C.13"

# ValidationStatus values (string literals, template-safe)
VALIDATION_OK = "ok"
VALIDATION_UNMAPPED = "unmapped"
VALIDATION_PARTIAL = "partial"
VALIDATION_MISMATCH = "mismatch"
VALIDATION_BACKEND = "backend_calculated"
VALIDATION_UNKNOWN = "unknown"

_MAPPING_STATUS_MAP: dict[str, str] = {
    "mapped": VALIDATION_OK,
    "unmapped": VALIDATION_UNMAPPED,
    "partial": VALIDATION_PARTIAL,
    "model_mismatch": VALIDATION_MISMATCH,
    "backend_calculated": VALIDATION_BACKEND,
    "scope_mismatch": VALIDATION_PARTIAL,
}


# ---------------------------------------------------------------------------
# Dataclasses — Line
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapexLineVM:
    """Single sub-line row in the CAPEX Excel grid."""

    # Identity
    row_id: str          # Deterministic: "{project_code}:{parent_code}:{code}"
    code: str
    parent_code: str
    name: str

    # Provenance
    source: str          # "excel_reference" | "app_input" | "computed_runtime" | "factory" | …
    unit: str            # Always "kEUR" for CAPEX
    notes: str           # Comments or mapping notes from source data
    display_order: int   # 1-based position within parent group
    validation_status: str  # VALIDATION_* constant

    # Primary amount (kEUR) — editable for editable lines, display-only otherwise
    amount_keur: float

    # Derived display column — never submitted to engine
    per_mw: float

    # Structural flags
    is_group: bool               # True = group header row (not a data row)
    is_editable: bool            # True iff user may change amount_keur
    is_read_only: bool           # True iff value must never be changed by user
    is_derived: bool             # True iff value is computed (not primary input)
    is_contingency: bool         # True for C.13 sub-lines
    is_financing: bool           # True for C.17 sub-lines
    is_reserve: bool             # True for C.18 sub-lines
    is_readonly_financing: bool  # True for C.17 or C.18 sub-lines (legacy alias)

    # User-managed line items
    is_custom: bool   # True = user-added line (not in Excel template)
    is_active: bool   # False = user has deactivated this line (excluded from totals)

    # Custom-row identity (empty string for reference rows)
    sub_line_id: str = ""    # UUID from capex_sub_lines table
    row_version: str = ""    # updated_at timestamp — optimistic-lock token


# ---------------------------------------------------------------------------
# Dataclasses — Group
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapexGroupVM:
    """Group header (C.01, C.02, …) with its sub-lines."""

    code: str
    name: str
    lines: tuple[CapexLineVM, ...]

    # Derived totals — only active lines included
    subtotal_keur: float
    subtotal_per_mw: float

    # Group-level flags
    is_readonly: bool       # True for C.17, C.18
    is_contingency: bool    # True for C.13
    is_financing: bool      # True for C.17
    is_reserve: bool        # True for C.18
    is_alias: bool = False  # True for alias groups (e.g. C.11 shares audit_legal with C.08)
    alias_allows_custom_rows: bool = False  # True when alias group may hold user custom sub-lines (C.11)


# ---------------------------------------------------------------------------
# Dataclasses — ViewModel
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapexViewModel:
    """Full CAPEX sheet view model, ready for template iteration."""

    project_name: str
    capacity_mw: float

    groups: tuple[CapexGroupVM, ...]  # C.01–C.18 in Excel order

    # Aggregated totals (active lines only)
    hard_capex_keur: float    # sum of groups C.01–C.16
    hard_capex_per_mw: float
    financing_keur: float     # C.17 subtotal
    reserve_keur: float       # C.18 subtotal
    total_capex_keur: float   # hard + financing + reserve
    total_per_mw: float

    # Segmented totals across all active lines
    editable_total_keur: float  # sum of active lines where is_editable=True
    derived_total_keur: float   # sum of active lines where is_derived=True

    is_user_project: bool


# ---------------------------------------------------------------------------
# Mutation contract
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AddCapexLineCommand:
    """
    Intent to add a custom sub-line under an existing CAPEX group.

    Persistence is out of scope — this dataclass documents the mutation surface
    for future storage and validation layers.
    """
    project_code: str
    parent_group_code: str   # e.g. "C.05"
    name: str
    amount_keur: float
    notes: str = ""


@dataclass(frozen=True)
class UpdateCapexLineCommand:
    """Intent to update an existing editable CAPEX sub-line amount."""
    project_code: str
    line_code: str           # e.g. "C.05.01"
    new_amount_keur: float
    notes: str = ""


@dataclass(frozen=True)
class DeactivateCapexLineCommand:
    """
    Intent to deactivate a custom CAPEX sub-line (excluded from totals).
    Only is_custom=True lines may be deactivated.
    """
    project_code: str
    line_code: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_per_mw(amount_keur: float, capacity_mw: float) -> float:
    if capacity_mw > 0:
        return amount_keur / capacity_mw
    return 0.0


def _make_row_id(project_code: str, parent_code: str, line_code: str) -> str:
    """Deterministic, stable row identity — safe for HTML id attributes."""
    return f"{project_code}:{parent_code}:{line_code}"


def _map_validation_status(mapping_status: str | None) -> str:
    if not mapping_status:
        return VALIDATION_UNKNOWN
    return _MAPPING_STATUS_MAP.get(mapping_status, VALIDATION_UNKNOWN)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_capex_view_model(
    project_ctx: "ProjectContext",
    is_user_project: bool = False,
    sub_lines: "Sequence[CapexSubLine] | None" = None,
) -> CapexViewModel:
    """
    Build a CapexViewModel from ProjectContext.capex_detail_items.

    Args:
        project_ctx:     Populated ProjectContext (frozen dataclass).
        is_user_project: True iff the current session user owns this project
                         and may edit line-item amounts.
        sub_lines:       Optional list of active CapexSubLine records to inject
                         as custom rows into the appropriate groups.  Only
                         active rows (is_active=True) are included; the caller
                         is responsible for filtering.

    Returns:
        Fully populated CapexViewModel — all derived fields computed here.
    """
    capacity_mw: float = project_ctx.capacity_mw
    project_code: str = project_ctx.code
    groups: list[CapexGroupVM] = []

    # ── R2: sub-line field tracking ──────────────────────────────────────────
    # Mirrors the logic in apply_user_sub_lines_replacing_base: when any
    # active sub-line exists for a CapexStructure field, that field's base
    # is zeroed in the canonical run-input (REPLACE semantics).  The display
    # must agree: base = 0 for those fields, amounts come from custom rows.
    _cat_field_map = _get_cat_field_map()
    _fields_with_sub_lines: set[str] = set()
    if sub_lines:
        for _sl in sub_lines:
            if getattr(_sl, "is_active", True):
                _fn = _cat_field_map.get(_sl.parent_category_code)
                if _fn:
                    _fields_with_sub_lines.add(_fn)

    # Field-owner map: first group code that maps to each field = owner.
    # Any later group mapping the same field is an alias.
    _field_owner: dict[str, str] = {}
    for _code, _fname in _cat_field_map.items():
        if _fname not in _field_owner:
            _field_owner[_fname] = _code

    def _is_alias(group_code: str) -> bool:
        fn = _cat_field_map.get(group_code)
        return fn is not None and _field_owner.get(fn) != group_code

    # Index sub-lines by parent_category_code for O(1) lookup per group.
    sub_lines_by_group: dict[str, list[CapexSubLine]] = {}
    if sub_lines:
        for sl in sub_lines:
            sub_lines_by_group.setdefault(sl.parent_category_code, []).append(sl)
        # Stable sort within each group by display_order then business_code.
        for code in sub_lines_by_group:
            sub_lines_by_group[code].sort(
                key=lambda s: (s.display_order, s.business_code)
            )

    for cat in project_ctx.capex_detail_items:
        group_code: str = cat["code"]
        group_name: str = cat["name"]
        is_backend_group: bool = cat.get("is_backend_calculated", False)
        group_is_readonly = group_code in _READONLY_GROUP_CODES or is_backend_group
        group_is_contingency = group_code == _CONTINGENCY_CODE
        group_is_financing = group_code == _FINANCING_CODE
        group_is_reserve = group_code == _RESERVE_CODE
        # R2: canonical group amount from CapexStructure (set by _build_capex_detail_items)
        app_group_amount: float | None = cat.get("app_group_amount_keur")
        is_alias_group: bool = _is_alias(group_code)

        lines: list[CapexLineVM] = []
        # A reference-seeded working copy persists the public generic children
        # themselves.  Do not render the base projection beside them: it would
        # make a decomposition look additive even though run semantics replace
        # the canonical parent with its children.
        group_sub_lines = sub_lines_by_group.get(group_code, [])
        has_reference_seed = any(
            getattr(sl, "replay_metadata", {}).get("reference_seed") is True
            for sl in group_sub_lines
        )
        context_children = () if has_reference_seed else cat.get("children", ())
        for order, child in enumerate(context_children, start=1):
            child_code: str = child["code"]
            # R2: prefer canonical app_amount_keur; fall back to Excel ref (reference display)
            _canon_child = child.get("app_amount_keur")
            amount_keur: float = float(
                _canon_child if _canon_child is not None else child.get("amount_keur") or 0.0
            )
            per_mw: float = _safe_per_mw(amount_keur, capacity_mw)

            child_backend: bool = child.get("is_backend_calculated", False)

            is_derived = (
                group_is_readonly
                or child_backend
                or group_is_contingency
            )
            is_read_only = is_derived or not is_user_project
            is_editable = is_user_project and not is_derived

            notes_raw = child.get("comments", "") or ""
            mapping_note = child.get("mapping_note", "") or ""
            notes = notes_raw if notes_raw else mapping_note

            lines.append(CapexLineVM(
                row_id=_make_row_id(project_code, group_code, child_code),
                code=child_code,
                parent_code=group_code,
                name=child["name"],
                source=child.get("source_type", "unknown") or "unknown",
                unit="kEUR",
                notes=notes,
                display_order=order,
                validation_status=_map_validation_status(
                    child.get("mapping_status")
                ),
                amount_keur=amount_keur,
                per_mw=per_mw,
                is_group=False,
                is_editable=is_editable,
                is_read_only=is_read_only,
                is_derived=is_derived,
                is_contingency=group_is_contingency,
                is_financing=group_is_financing,
                is_reserve=group_is_reserve,
                is_readonly_financing=group_is_financing or group_is_reserve,
                is_custom=False,   # future: set from user-stored overrides
                is_active=True,    # future: set from user-stored deactivation
            ))

        # Inject user-added custom sub-lines for this group.
        # C.11 is a valid persisted parent; alias status only affects base-amount
        # computation, NOT eligibility for custom sub-lines.
        if not group_is_readonly and not group_is_contingency:
            for sl in group_sub_lines:
                sl_amount = float(sl.amount_keur or 0.0)
                lines.append(CapexLineVM(
                    row_id=_make_row_id(project_code, group_code, sl.business_code),
                    code=sl.business_code,
                    parent_code=group_code,
                    name=sl.label,
                    source="user",
                    unit="kEUR",
                    notes=sl.comments or "",
                    display_order=sl.display_order,
                    validation_status=VALIDATION_OK,
                    amount_keur=sl_amount,
                    per_mw=_safe_per_mw(sl_amount, capacity_mw),
                    is_group=False,
                    is_editable=is_user_project,
                    is_read_only=not is_user_project,
                    is_derived=False,
                    is_contingency=False,
                    is_financing=False,
                    is_reserve=False,
                    is_readonly_financing=False,
                    is_custom=True,
                    is_active=True,
                    sub_line_id=sl.sub_line_id,
                    row_version=sl.updated_at or "",
                ))

        active_lines = [ln for ln in lines if ln.is_active]
        custom_subtotal = sum(ln.amount_keur for ln in active_lines if ln.is_custom)

        # R2: effective canonical base for this group's subtotal.
        #
        # Rule 1 (alias): Alias groups (e.g. C.11 sharing audit_legal with C.08)
        #   have canonical base = 0.  The owner group (C.08) holds the base.
        #   Custom rows under C.11 still contribute their own amounts.
        #
        # Rule 2 (sub-lines replace base): When any active sub-line exists for
        #   the field mapped to this group (REPLACE semantics in
        #   apply_user_sub_lines_replacing_base), the base is zeroed in the run
        #   path.  The display must agree: base = 0, custom rows are the total.
        #
        # Rule 3 (no sub-lines, owner): Use app_group_amount_keur (canonical
        #   registry amount from _build_capex_detail_items).
        field_name = _cat_field_map.get(group_code)
        field_has_sub_lines = field_name in _fields_with_sub_lines if field_name else False
        if is_alias_group or field_has_sub_lines:
            effective_base: float | None = 0.0
        else:
            effective_base = app_group_amount

        if effective_base is not None:
            subtotal_keur = effective_base + custom_subtotal
        else:
            subtotal_keur = sum(ln.amount_keur for ln in active_lines)
        subtotal_per_mw = _safe_per_mw(subtotal_keur, capacity_mw)

        # Alias groups that are neither readonly nor contingency may hold custom
        # sub-lines persisted by the user (e.g. C.11 Audit & Legal custom rows).
        _alias_allows_custom = is_alias_group and not group_is_readonly and not group_is_contingency
        groups.append(CapexGroupVM(
            code=group_code,
            name=group_name,
            lines=tuple(lines),
            subtotal_keur=subtotal_keur,
            subtotal_per_mw=subtotal_per_mw,
            is_readonly=group_is_readonly,
            is_contingency=group_is_contingency,
            is_financing=group_is_financing,
            is_reserve=group_is_reserve,
            is_alias=is_alias_group,
            alias_allows_custom_rows=_alias_allows_custom,
        ))

    # Aggregate totals
    # R2: exclude only readonly groups (C.17, C.18) from hard_capex.
    # Alias groups (C.11) are included — their subtotal = 0 base + C.11 custom
    # sub-lines, which are real economics distinct from C.08 custom sub-lines.
    # Double-counting is prevented by Rule 1 above (alias base = 0) and by
    # Rule 2 (owner base = 0 when sub-lines exist for the shared field).
    hard_capex_keur = sum(
        g.subtotal_keur for g in groups
        if g.code not in _READONLY_GROUP_CODES
    )
    financing_keur = next(
        (g.subtotal_keur for g in groups if g.code == _FINANCING_CODE), 0.0
    )
    reserve_keur = next(
        (g.subtotal_keur for g in groups if g.code == _RESERVE_CODE), 0.0
    )
    total_capex_keur = hard_capex_keur + financing_keur + reserve_keur

    # Segmented totals across all active lines
    all_active = [ln for g in groups for ln in g.lines if ln.is_active]
    editable_total = sum(ln.amount_keur for ln in all_active if ln.is_editable)
    derived_total = sum(ln.amount_keur for ln in all_active if ln.is_derived)

    return CapexViewModel(
        project_name=project_ctx.name,
        capacity_mw=capacity_mw,
        groups=tuple(groups),
        hard_capex_keur=hard_capex_keur,
        hard_capex_per_mw=_safe_per_mw(hard_capex_keur, capacity_mw),
        financing_keur=financing_keur,
        reserve_keur=reserve_keur,
        total_capex_keur=total_capex_keur,
        total_per_mw=_safe_per_mw(total_capex_keur, capacity_mw),
        editable_total_keur=editable_total,
        derived_total_keur=derived_total,
        is_user_project=is_user_project,
    )
