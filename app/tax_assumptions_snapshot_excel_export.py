"""Phase 6D.2 — Excel export from TaxAssumptionSnapshot dataclasses.

Direct export — no reconstruction of TaxTemplate / ResolvedTaxConfig / TaxTemplateOverride.
All data comes from immutable snapshot dataclasses.

Pure function — no mutation, no active model wiring.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.tax.assumptions_snapshot import TaxAssumptionSnapshot

__all__ = ["write_tax_assumption_snapshot_sheets"]

AUDIT_NOTE = (
    "AUDIT-ONLY: This snapshot is a read-only governance artifact. "
    "It does not modify active model outputs or trigger any workflow."
)

_EXCEL_INVALID_CHARS = frozenset('/\\*?[]:')


def _sanitize_sheet_name(name: str, max_len: int = 31) -> str:
    safe = "".join("_" if c in _EXCEL_INVALID_CHARS else c for c in name)
    if len(safe) > max_len:
        safe = safe[:max_len]
    return safe


def _unique_sheet_name(base: str, used: set[str]) -> str:
    if base not in used:
        return base
    suffix = 2
    while True:
        candidate = f"{base[:31 - len(str(suffix))]}_{suffix}"
        if candidate not in used:
            return candidate
        suffix += 1


def _serialize(val):
    """Serialize non-primitive values to JSON strings for Excel compatibility."""
    if val is None:
        return None
    if isinstance(val, (str, int, float, bool)):
        return val
    if isinstance(val, tuple):
        return json.dumps(val)
    if isinstance(val, dict):
        return json.dumps(val)
    return str(val)


def _write_snapshot_sheet(writer, sheet_name: str, rows, columns):
    """Write a snapshot sheet: row 1=audit note, row 2=headers, row 3+=data."""
    wb = writer.book
    safe_name = _sanitize_sheet_name(sheet_name)
    if safe_name in wb.sheetnames:
        ws = wb[safe_name]
    else:
        ws = wb.create_sheet(safe_name)

    ws.cell(row=1, column=1, value=AUDIT_NOTE)
    for col_idx, col_name in enumerate(columns, start=1):
        ws.cell(row=2, column=col_idx, value=col_name)

    for row_idx, row_data in enumerate(rows, start=3):
        for col_idx, val in enumerate(row_data, start=1):
            serialized = _serialize(val)
            ws.cell(row=row_idx, column=col_idx, value=serialized)


def write_tax_assumption_snapshot_sheets(writer, snapshot: "TaxAssumptionSnapshot") -> None:
    """Write all tax assumption snapshot sheets into an open Excel workbook.

    Direct export from TaxAssumptionSnapshot dataclasses — no TaxTemplate
    reconstruction. Values only. No formulas.

    Parameters
    ----------
    writer : pandas.ExcelWriter
        Open ExcelWriter (e.g., from pd.ExcelWriter(filepath)).
    snapshot : TaxAssumptionSnapshot
        Immutable snapshot artifact. Not mutated.

    Behavior
    --------
    - No-op if all three collections are empty.
    - Row 1 = audit note
    - Row 2 = headers
    - Row 3+ = data
    - Tuple values serialized to JSON strings for Excel compatibility
    - Sheet names sanitized and deduplicated (31-char limit)

    Notes
    -----
    - Does NOT call write_tax_assumptions_audit_sheets().
    - Does NOT reconstruct TaxTemplate / ResolvedTaxConfig / TaxTemplateOverride objects.
    """
    if (not snapshot.has_templates
            and not snapshot.has_overrides
            and not snapshot.has_resolved_configs):
        return

    # ── Tax Snapshot Templates ────────────────────────────────────────
    if snapshot.has_templates:
        template_columns = [
            "Template Code", "Country Code", "Tax Year",
            "CIT Structure", "CIT Tiers Summary",
            "Loss Carryforward Years",
            "Has Interest Limitation", "Has WHT Dividend", "Has WHT Interest",
            "Depreciation Rules Summary",
            "Metadata", "Snapshot Label", "Created At", "Audit Note",
        ]
        template_rows = []
        for ts in snapshot.template_snapshots:
            template_rows.append((
                ts.template_name,
                ts.country_code,
                ts.tax_year,
                ts.cit_structure,
                ", ".join(ts.cit_tiers_summary),
                ts.loss_carryforward_years,
                ts.has_interest_limitation,
                ts.has_wht_dividend,
                ts.has_wht_interest,
                "; ".join(ts.depreciation_rules_summary),
                ts.metadata,
                ts.snapshot_label,
                ts.created_at.isoformat() if ts.created_at else "",
                ts.audit_note,
            ))
        _write_snapshot_sheet(writer, "Tax Snapshot Templates", template_rows, template_columns)

    # ── Tax Snapshot Overrides ─────────────────────────────────────────
    if snapshot.has_overrides:
        override_columns = [
            "Override Name", "Field Path", "Override Value",
            "Reason", "Created At", "Audit Note",
        ]
        override_rows = []
        for os_ in snapshot.override_snapshots:
            override_rows.append((
                os_.override_name,
                os_.field_path,
                os_.override_value,
                os_.reason,
                os_.created_at.isoformat() if os_.created_at else "",
                os_.audit_note,
            ))
        _write_snapshot_sheet(writer, "Tax Snapshot Overrides", override_rows, override_columns)

    # ── Tax Snapshot Resolved ─────────────────────────────────────────
    if snapshot.has_resolved_configs:
        resolved_columns = [
            "Template Code", "Country Code", "Tax Year",
            "Effective CIT Structure", "Override Count",
            "Overrides Summary", "Resolved Metadata",
            "Snapshot Label", "Created At", "Audit Note",
        ]
        resolved_rows = []
        for rs in snapshot.resolved_config_snapshots:
            resolved_rows.append((
                rs.template_name,
                rs.country_code,
                rs.tax_year,
                rs.effective_cit_structure,
                rs.override_count,
                "; ".join(rs.overrides_summary),
                rs.resolved_metadata,
                rs.snapshot_label,
                rs.created_at.isoformat() if rs.created_at else "",
                rs.audit_note,
            ))
        _write_snapshot_sheet(writer, "Tax Snapshot Resolved", resolved_rows, resolved_columns)
