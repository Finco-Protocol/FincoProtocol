"""
Workbook V2 — structural spec dataclasses.

Hierarchy: WorkbookSpec → SheetSpec → SectionSpec → FieldSpec

FieldSpec is the single source of truth for a workable field:
  - stable semantic ID (e.g. "project_setup.technical.capacity_mw")
  - legacy snapshot key (form field name used today)
  - canonical contract metadata: kind, persisted, source_of_truth, engine_path,
    scenario_policy, binding_status, excel mappings, dependencies

Nothing here touches the engine, the DB, or the web layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional


class FieldType(str, Enum):
    FLOAT = "float"
    INT = "int"
    TEXT = "text"
    DATE = "date"
    SELECT = "select"
    BOOL = "bool"
    KEUR = "keur"       # monetary amount in kEUR
    PCT = "pct"         # percentage (0–100 stored, 0.0–1.0 domain)
    BPS = "bps"         # basis points
    YEARS = "years"     # integer duration in years
    MONTHS = "months"   # integer duration in months
    MWH = "mwh"         # energy-specific numeric (hours or yield)
    MW = "mw"           # power capacity


class FieldKind(str, Enum):
    """Functional role of a field in the workbook lifecycle."""
    INPUT = "input"
    # User-entered; persisted in the snapshot; drives the engine on every Run.

    TEMPLATE_INPUT = "template_input"
    # Value originates from the Excel/factory template.  Users cannot change it
    # from the UI.  Frozen in the CapexStructure (bank_fees, commitment_fees, etc.)
    # or project metadata.

    DERIVED_DISPLAY = "derived_display"
    # Computed from other fields in the UI layer or by the engine; never a direct
    # user input.  Shown for information only (subtotals, IDC, capacity_factor).

    RUNTIME_OUTPUT = "runtime_output"
    # Produced by WaterfallRunner.run() and returned in WaterfallResult.  Populated
    # after a successful model Run; cleared on page reload unless OOB re-render fires.

    AUDIT_ONLY = "audit_only"
    # Visible in audit/diagnostic panels.  Never submitted, never drives the engine.


class SourceOfTruth(str, Enum):
    """Where the authoritative value for this field lives."""
    INPUT_SET = "input_set"
    # The user-editable project record (snapshot dict / ProjectInputs).

    TEMPLATE = "template"
    # The factory / Excel-extracted template (frozen CapexStructure scalars,
    # project_type, template_source).

    ENGINE = "engine"
    # Computed inside WaterfallRunner / IDC engine / depreciation engine.
    # Value is determined by the model run, not direct user entry.

    DERIVED_UI = "derived_ui"
    # Computed in the Python view layer (ProjectContext) or in JS/Jinja from
    # other persisted fields.  Not stored independently.


class ScenarioPolicy(str, Enum):
    """How this field behaves across scenarios."""
    NOT_ALLOWED = "not_allowed"
    # Cannot vary between scenarios.  Identity fields, dates, project structure.

    OVERRIDE = "override"
    # A scalar override can be set per scenario (single value replaces default).
    # Technical params, tariff, debt inputs.

    FULL_SERIES_OVERRIDE = "full_series_override"
    # A complete period-by-period series can be provided per scenario.
    # Currently used for merchant price curves.


class BindingStatus(str, Enum):
    """
    End-to-end wiring status: from HTML surface → snapshot → engine → output.

    BOUND           Fully wired.  HTML input → snapshot_key persisted →
                    engine_path consumed by WaterfallRunner → output reflected.

    PARTIAL         Partially wired.  The field is persisted in the snapshot and
                    visible in the UI, but the path to the engine is incomplete
                    (legacy key superseded by a newer key, derived total that the
                    engine recomputes, or workspace-draft that is not yet
                    submitted through the canonical form path).

    DISPLAY_ONLY    Read-only computed value.  Not a user input; not persisted
                    via the form snapshot.  C.17/C.18 financing rows, subtotals,
                    derived ratios.

    TEMPLATE_LOCKED Value is set from the Excel/factory template and frozen.
                    Shown to the user but cannot be changed.  bank_fees_keur,
                    commitment_fees_keur, project_type after creation.

    UNSUPPORTED     Field exists in the HTML form name-space but has no known
                    engine effect and is not persisted in any meaningful way.
    """
    BOUND = "BOUND"
    PARTIAL = "PARTIAL"
    DISPLAY_ONLY = "DISPLAY_ONLY"
    TEMPLATE_LOCKED = "TEMPLATE_LOCKED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class FieldSpec:
    """Descriptor for a single workbook field — full canonical contract."""

    # ── Identity ──────────────────────────────────────────────────────────── #

    field_id: str
    # Stable semantic identifier — never changes once shipped.
    # Convention: <sheet_id>.<section_id>.<name>

    label: str
    # Human-readable label for UI and Excel headers.

    snapshot_key: str
    # Legacy HTML form `name` attribute and `_collect_form_snapshot()` key.

    field_type: FieldType
    sheet_id: str
    section_id: str

    # ── Canonical contract ─────────────────────────────────────────────────── #

    kind: FieldKind = FieldKind.INPUT

    persisted: bool = True
    # True  → snapshot_key appears in _collect_form_snapshot() and is saved to DB.
    # False → value is computed at runtime / display-only / not in snapshot dict.

    runtime_only: bool = False
    # True  → value lives only in sessionStorage post-Run; cleared on page reload.
    #         (All WaterfallResult-derived outputs.)
    # False → value is available before / independent of a model Run.

    source_of_truth: SourceOfTruth = SourceOfTruth.INPUT_SET

    engine_path: Optional[str] = None
    # Dotted path into ProjectInputs consumed by WaterfallRunner, e.g.
    # "technical.capacity_mw" or "capex.epc_contract.amount_keur".
    # None for display-only and template-locked fields with no direct engine binding.

    engine_path_conditional: Optional[str] = None
    # R4/F06: conditional engine binding, used ONLY when the unconditional
    # engine_path is not the sole authority for every project state.
    # Format: "<dotted path> (when <typed condition>; <unit note>)".
    # None for fields whose engine_path is unconditional.

    scenario_policy: ScenarioPolicy = ScenarioPolicy.NOT_ALLOWED

    binding_status: BindingStatus = BindingStatus.BOUND

    # ── Excel mappings ─────────────────────────────────────────────────────── #

    excel_generic_wind_reference: Optional[str] = None
    # external reference locator in the Generic Wind Reference reference methodology.
    # Format: "<SheetName>!<CellRef>" or "<C.XX.YY>" for CAPEX line items.

    excel_generic_solar_reference: Optional[str] = None
    # Same for the Generic Solar Reference reference methodology.

    excel_evidence: Optional[Literal["SOURCE_PROVEN", "NOT_APPLICABLE", "UNVERIFIED"]] = None
    # Provenance audit result for excel_generic_wind_reference / excel_generic_solar_reference mappings.
    # SOURCE_PROVEN: commit fixture, extraction script, or authoritative documentation proves the exact cell.
    # NOT_APPLICABLE: field is ENGINE/DERIVED — no snapshot canonical source applies.
    # UNVERIFIED: no proof available; reference was inferred from naming convention.
    # None: not yet audited (pre-existing fields not yet classified).

    export_mapping: Optional[str] = None
    # Column header used in the generated Excel export (runtime summary / institutional).

    # ── Dependencies ──────────────────────────────────────────────────────── #

    dependencies: tuple[str, ...] = ()
    # field_ids of fields this field is derived from (for DERIVED_DISPLAY fields).

    # ── Display / validation ───────────────────────────────────────────────── #

    unit: Optional[str] = None
    description: Optional[str] = None
    editable: bool = True
    required: bool = False
    options: tuple[str, ...] = ()
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    decimals: Optional[int] = None
    order: int = 0


@dataclass(frozen=True)
class SectionSpec:
    """A named group of fields within a sheet."""
    section_id: str
    label: str
    sheet_id: str
    order: int = 0
    fields: tuple[FieldSpec, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SheetSpec:
    """One workbook tab / sheet."""
    sheet_id: str
    label: str
    icon: Optional[str] = None
    order: int = 0
    sections: tuple[SectionSpec, ...] = field(default_factory=tuple)

    def all_fields(self) -> tuple[FieldSpec, ...]:
        return tuple(f for s in self.sections for f in s.fields)


@dataclass(frozen=True)
class WorkbookSpec:
    """Root registry object for the entire workbook."""
    version: str
    sheets: tuple[SheetSpec, ...] = field(default_factory=tuple)

    # ── Lookup helpers ─────────────────────────────────────────────────────── #

    def sheet(self, sheet_id: str) -> SheetSpec:
        for s in self.sheets:
            if s.sheet_id == sheet_id:
                return s
        raise KeyError(f"No sheet '{sheet_id}' in WorkbookSpec")

    def field(self, field_id: str) -> FieldSpec:
        for s in self.sheets:
            for f in s.all_fields():
                if f.field_id == field_id:
                    return f
        raise KeyError(f"No field '{field_id}' in WorkbookSpec")

    def field_by_snapshot_key(self, snapshot_key: str) -> FieldSpec:
        for s in self.sheets:
            for f in s.all_fields():
                if f.snapshot_key == snapshot_key:
                    return f
        raise KeyError(f"No field with snapshot_key='{snapshot_key}' in WorkbookSpec")

    def all_fields(self) -> tuple[FieldSpec, ...]:
        return tuple(f for s in self.sheets for f in s.all_fields())

    def snapshot_key_to_field_id(self) -> dict[str, str]:
        """Map legacy snapshot keys → semantic field IDs."""
        return {f.snapshot_key: f.field_id for f in self.all_fields()}

    def field_id_to_snapshot_key(self) -> dict[str, str]:
        """Map semantic field IDs → legacy snapshot keys."""
        return {f.field_id: f.snapshot_key for f in self.all_fields()}

    def fields_by_binding_status(self, status: BindingStatus) -> tuple[FieldSpec, ...]:
        return tuple(f for f in self.all_fields() if f.binding_status == status)

    def editable_fields(self) -> tuple[FieldSpec, ...]:
        return tuple(f for f in self.all_fields() if f.editable)
