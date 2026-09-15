"""
app.ui.opex_sheet_projection — canonical OPEX worksheet structure.

Owns the authoritative B.01–B.13 canonical group definitions and merges
them with OpexViewModel values so the worksheet always renders all 13
groups in fixed order regardless of what a particular project's ViewModel
contains.

This is the single canonical owner of:
  - B-code order (B.01–B.13)
  - registry field suffix for each group
  - group display name fallback
  - editability / badge type per group

The HTTP router delegates to build_opex_sheet_projection(); it must not
duplicate any of these mappings.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Sequence

if TYPE_CHECKING:
    from app.ui.opex_view_model import OpexGroupVM, OpexViewModel

# ---------------------------------------------------------------------------
# Canonical B.01–B.13 group definitions (single source of truth)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CanonicalOpexGroup:
    """Static metadata for one canonical OPEX group."""
    code: str
    name: str
    field_suffix: Optional[str]   # registry field suffix; None = no BOUND field (B.09)
    is_always_derived: bool       # True for B.13 — always DERIVED/read-only


# Ordered list — this order is the worksheet column order and must not be changed.
CANONICAL_OPEX_GROUPS: tuple[CanonicalOpexGroup, ...] = (
    CanonicalOpexGroup("B.01", "Technical Management",         "technical_management",           False),
    CanonicalOpexGroup("B.02", "O&M Preventive & Corrective",  "om_preventive",                  False),
    CanonicalOpexGroup("B.03", "Site Maintenance",             "site_maintenance",               False),
    CanonicalOpexGroup("B.04", "Cleaning & Materials",         "cleaning_materials",             False),
    CanonicalOpexGroup("B.05", "Security",                     "security",                       False),
    CanonicalOpexGroup("B.06", "Insurance",                    "insurance",                      False),
    CanonicalOpexGroup("B.07", "Lease & Property Tax",         "lease_property_tax",             False),
    CanonicalOpexGroup("B.08", "Power Expenses",               "power_expenses",                 False),
    CanonicalOpexGroup("B.09", "Fees",                         None,                             False),
    CanonicalOpexGroup("B.10", "Audit, Accounting & Legal",    "audit_accounting_legal",         False),
    CanonicalOpexGroup("B.11", "Bank Fees",                    "bank_fees",                      False),
    CanonicalOpexGroup("B.12", "Environmental & Social",       "environmental_social",           False),
    CanonicalOpexGroup("B.13", "Contingencies",                "contingencies",                  True),
)

# Convenient lookup: code → CanonicalOpexGroup
CANONICAL_OPEX_GROUP_BY_CODE: dict[str, CanonicalOpexGroup] = {
    g.code: g for g in CANONICAL_OPEX_GROUPS
}


# ---------------------------------------------------------------------------
# Projected sheet group — merge of canonical definition + optional VM values
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OpexSheetGroup:
    """One B.XX row in the projected OPEX worksheet.

    Always present for each of B.01–B.13 regardless of ViewModel coverage.
    """
    # Canonical identity
    code: str
    canonical_name: str
    field_suffix: Optional[str]     # None → ENGINE (no registry field)
    is_always_derived: bool         # True for B.13

    # Registry field dict (or None if suffix is None / field not found)
    field: Optional[dict]

    # ViewModel-derived values (None when the group has no VM row for this project)
    vm_group: Optional["OpexGroupVM"]

    # Convenience: is the VM row present?
    @property
    def has_vm_data(self) -> bool:
        return self.vm_group is not None

    @property
    def subtotal_y1(self) -> float:
        if self.vm_group and self.vm_group.subtotal_per_year:
            return self.vm_group.subtotal_per_year[0]
        return 0.0

    @property
    def inflation_pct(self) -> float:
        return self.vm_group.inflation_pct if self.vm_group else 0.0

    @property
    def display_name(self) -> str:
        """Use VM name when available (may be more specific than canonical)."""
        if self.vm_group:
            return self.vm_group.name
        return self.canonical_name

    # Badge / editability semantics
    @property
    def is_engine(self) -> bool:
        """True iff this group must always render ENGINE/read-only (no BOUND field)."""
        return self.field_suffix is None and not self.is_always_derived

    @property
    def is_derived(self) -> bool:
        return self.is_always_derived

    @property
    def is_bound(self) -> bool:
        return (
            self.field is not None
            and self.field.get("binding_label") == "bound"
            and not self.is_always_derived
        )

    @property
    def is_custom_eligible(self) -> bool:
        """True iff this group accepts user-added custom rows.

        All groups except B.13 (Contingencies, always DERIVED) are eligible.
        B.09 (Fees, no registry BOUND field) is explicitly custom-eligible:
        users create their own fee lines rather than editing a scalar value.
        """
        return not self.is_always_derived

    @property
    def custom_lines(self) -> tuple:
        """Active custom (user-added) lines from the VM group, in display order."""
        if not self.vm_group:
            return ()
        return tuple(ln for ln in self.vm_group.lines if ln.is_custom and ln.is_active)

    @property
    def year_rows(self) -> tuple[float, ...]:
        """Per-year subtotals for the projection table (empty if no VM data)."""
        if self.vm_group:
            return self.vm_group.subtotal_per_year
        return ()


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_opex_sheet_projection(
    opex_vm: "OpexViewModel",
    opex_fields: Sequence[dict],
) -> tuple["OpexSheetGroup", ...]:
    """Merge canonical B.01–B.13 definitions with OpexViewModel + registry fields.

    Always returns exactly 13 OpexSheetGroup objects in canonical order.
    Groups absent from the ViewModel are represented with vm_group=None and
    display ENGINE / DERIVED / zero values — no group is silently omitted.

    Args:
        opex_vm:      Fully built OpexViewModel (may have 0..13 groups).
        opex_fields:  Output of _build_sheet_fields("opex", pis) — all registry
                      fields for the opex sheet.

    Returns:
        Tuple of 13 OpexSheetGroup objects in B.01–B.13 order.
    """
    # Index VM groups by code for O(1) lookup
    vm_by_code: dict[str, "OpexGroupVM"] = {g.code: g for g in opex_vm.groups}

    # Index registry fields by suffix for lookup
    fields_by_suffix: dict[str, dict] = {
        f["field_id"].split(".")[-1]: f
        for f in opex_fields
    }

    result: list[OpexSheetGroup] = []
    for canonical in CANONICAL_OPEX_GROUPS:
        field = (
            fields_by_suffix.get(canonical.field_suffix)
            if canonical.field_suffix
            else None
        )
        result.append(OpexSheetGroup(
            code=canonical.code,
            canonical_name=canonical.name,
            field_suffix=canonical.field_suffix,
            is_always_derived=canonical.is_always_derived,
            field=field,
            vm_group=vm_by_code.get(canonical.code),
        ))

    return tuple(result)
