"""Provenance adapter — derived view over the WorkbookSpec / FieldSpec registry.

This module is the single point of truth for field provenance queries (F10).
It does NOT duplicate the registry; it provides typed accessors over it,
mapping internal SourceOfTruth / BindingStatus enum values to the F10
canonical vocabulary used for governance and audit purposes.

F10 vocabulary mapping
───────────────────────────────────────────────────────────
 Registry SourceOfTruth   │  F10 source_of_truth
──────────────────────────┼──────────────────────────────
 INPUT_SET                │  USER_INPUT      (user-editable project record)
 TEMPLATE                 │  FACTORY_DEFAULT (factory/Excel-extracted template)
 ENGINE                   │  ENGINE          (canonical engine-produced)
 DERIVED_UI               │  DERIVED         (derived presentation)

 Registry BindingStatus   │  F10 binding_status
──────────────────────────┼──────────────────────────────
 BOUND                    │  BOUND
 PARTIAL                  │  PARTIAL
 DISPLAY_ONLY             │  UNBOUND
 TEMPLATE_LOCKED          │  UNBOUND
 UNSUPPORTED              │  UNBOUND

 FieldSpec.excel_evidence  │  F10 excel_evidence (adapter boundary)
──────────────────────────┼──────────────────────────────
 "SOURCE_PROVEN"           │  SOURCE_PROVEN   (proven by commit fixture/doc)
 "NOT_APPLICABLE"          │  NOT_APPLICABLE  (ENGINE/DERIVED; no snapshot src)
 "UNVERIFIED"              │  UNVERIFIED      (inferred ref, no proof)
 None                      │  UNRESOLVED      (not yet formally audited)
"""
from __future__ import annotations

from typing import Literal, TypedDict

from app.workbook.registry import WORKBOOK
from app.workbook.specs import BindingStatus, FieldSpec, SourceOfTruth

# ── F10 canonical type aliases ─────────────────────────────────────────────
F10Source = Literal["USER_INPUT", "FACTORY_DEFAULT", "ENGINE", "DERIVED"]
F10Binding = Literal["BOUND", "UNBOUND", "PARTIAL"]
F10Evidence = Literal["SOURCE_PROVEN", "NOT_APPLICABLE", "UNVERIFIED", "UNRESOLVED"]


class ProvenanceRecord(TypedDict):
    field_id: str
    source_of_truth: F10Source
    binding_status: F10Binding
    excel_generic_wind_reference: str | None
    excel_generic_solar_reference: str | None
    excel_evidence: F10Evidence


# ── Enum → F10 string maps ─────────────────────────────────────────────────
_SOURCE_MAP: dict[SourceOfTruth, F10Source] = {
    SourceOfTruth.INPUT_SET:  "USER_INPUT",
    SourceOfTruth.TEMPLATE:   "FACTORY_DEFAULT",
    SourceOfTruth.ENGINE:     "ENGINE",
    SourceOfTruth.DERIVED_UI: "DERIVED",
}

_BINDING_MAP: dict[BindingStatus, F10Binding] = {
    BindingStatus.BOUND:           "BOUND",
    BindingStatus.PARTIAL:         "PARTIAL",
    BindingStatus.DISPLAY_ONLY:    "UNBOUND",
    BindingStatus.TEMPLATE_LOCKED: "UNBOUND",
    BindingStatus.UNSUPPORTED:     "UNBOUND",
}


def _field_index() -> dict[str, FieldSpec]:
    """Build a {field_id: FieldSpec} index from the singleton WorkbookSpec."""
    return {f.field_id: f for f in WORKBOOK.all_fields()}


def get_provenance(field_id: str) -> ProvenanceRecord:
    """Return F10 provenance metadata for a field_id.

    Raises KeyError if field_id is not present in the registry.
    """
    idx = _field_index()
    if field_id not in idx:
        raise KeyError(field_id)
    spec = idx[field_id]
    raw_evidence = spec.excel_evidence
    evidence: F10Evidence = raw_evidence if raw_evidence is not None else "UNRESOLVED"
    return ProvenanceRecord(
        field_id=field_id,
        source_of_truth=_SOURCE_MAP[spec.source_of_truth],
        binding_status=_BINDING_MAP[spec.binding_status],
        excel_generic_wind_reference=spec.excel_generic_wind_reference,
        excel_generic_solar_reference=spec.excel_generic_solar_reference,
        excel_evidence=evidence,
    )


def all_field_ids() -> list[str]:
    """Return all registered field_ids in registry order."""
    return [f.field_id for f in WORKBOOK.all_fields()]


def fields_by_source(source: F10Source) -> list[str]:
    """Return field_ids whose F10 source_of_truth matches *source*."""
    return [
        f.field_id
        for f in WORKBOOK.all_fields()
        if _SOURCE_MAP[f.source_of_truth] == source
    ]
