"""Phase 6B.5 — Excel export helper for SPV tax engine audit results.

Pure function — no mutation, no model integration.

CAVEAT: Values-only export. No formulas. No existing excel_export.py modification.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.tax import SPVTaxResult

__all__ = ["write_spv_tax_audit_sheets"]

# Excel invalid sheet name characters
_EXCEL_INVALID_CHARS = frozenset('/\\*?[]:')


def _make_safe_sheet_name(entity_code: str) -> str:
    """Sanitize entity_code for use as an Excel sheet name.

    Replaces all characters invalid in Excel sheet names with "_".
    Result is prefixed with "Tax_".
    Result is at most 31 characters (Excel limit).
    """
    # Sanitize: replace all invalid Excel characters
    safe = "".join("_" if c in _EXCEL_INVALID_CHARS else c for c in entity_code)
    base = f"Tax_{safe}"
    if len(base) > 31:
        base = base[:31]
    return base


def _unique_sheet_name(base: str, used: set[str]) -> str:
    """Return a unique sheet name based on base.

    If base is already in used, append _2, _3, ... until unique.
    Respects the 31-character Excel sheet name limit.
    """
    if base not in used:
        return base

    # Need disambiguation suffix
    candidate = base
    suffix = 2
    while candidate in used:
        suffix_str = f"_{suffix}"
        # Truncate base to fit suffix while keeping "Tax_" prefix
        max_base_len = 31 - len(suffix_str)
        truncated = base[:max_base_len]
        candidate = f"{truncated}{suffix_str}"
        suffix += 1
        # Safeguard: if base itself is too long to ever fit a suffix, use raw truncated
        if len(base) <= 31 - len(suffix_str):
            candidate = f"{base[:max_base_len]}{suffix_str}"
    return candidate


def write_spv_tax_audit_sheets(
    writer,
    tax_results: tuple[SPVTaxResult, ...],
) -> None:
    """Write SPV tax audit sheets into an open Excel workbook.

    Parameters
    ----------
    writer : pandas.ExcelWriter
        Open ExcelWriter (e.g., from pd.ExcelWriter(filepath)).
        Sheet "Tax Summary" is created/overwritten.
        Per-SPV sheets are named "Tax_{entity_code}" (max 31 chars).
    tax_results : tuple[SPVTaxResult, ...]
        Tuple of SPVTaxResult objects. Empty tuple → no-op.

    Behavior
    --------
    - If tax_results is empty, does nothing.
    - Writes "Tax Summary" sheet with one row per SPV (summary table).
      First row of Tax Summary sheet is the audit-only note.
    - Writes one detail sheet per SPV: "Tax_{entity_code}" truncated to 31 chars
      and made unique via disambiguation suffix if needed.
    - First row of each per-SPV sheet is the audit-only note.
    - All values, no formulas.

    Notes
    -----
    - Does NOT modify existing sheets (e.g., dashboard, waterfall).
    - Does NOT call build_excel_export() or replace it.
    - Sheet names are sanitised for all Excel-invalid characters.
    - Duplicate names (after truncation) are disambiguated with _2, _3, ...
    """
    if not tax_results:
        return

    import pandas as pd
    from app.tax_ui import (
        build_spv_tax_summary_table,
        build_spv_tax_period_table,
        build_tax_audit_note,
    )

    audit_note = build_tax_audit_note()

    # ── Tax Summary sheet ────────────────────────────────────────────
    summary_frames = []
    for result in tax_results:
        summary_frames.append(build_spv_tax_summary_table(result))

    if summary_frames:
        summary_df = pd.concat(summary_frames, ignore_index=True)

        # Write Tax Summary sheet (audit note in row 1, headers in row 2, data from row 3)
        summary_sheet_name = "Tax Summary"
        wb = writer.book
        if summary_sheet_name in wb.sheetnames:
            ws = wb[summary_sheet_name]
        else:
            ws = wb.create_sheet(summary_sheet_name)

        # Row 1: audit note
        ws.cell(row=1, column=1, value=audit_note)

        # Row 2: column headers
        for col_idx, col_name in enumerate(summary_df.columns, start=1):
            ws.cell(row=2, column=col_idx, value=col_name)

        # Row 3+: data
        for row_idx, (_, row_data) in enumerate(summary_df.iterrows(), start=3):
            for col_idx, val in enumerate(row_data, start=1):
                ws.cell(row=row_idx, column=col_idx, value=val)

    # ── Per-SPV detail sheets ───────────────────────────────────────
    used_sheet_names: set[str] = set()

    for result in tax_results:
        entity_code = result.entity_code
        base = _make_safe_sheet_name(entity_code)
        sheet_name = _unique_sheet_name(base, used_sheet_names)
        used_sheet_names.add(sheet_name)

        period_df = build_spv_tax_period_table(result)

        wb = writer.book
        if sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
        else:
            ws = wb.create_sheet(sheet_name)

        # Row 1: audit note
        ws.cell(row=1, column=1, value=audit_note)

        # Row 2: column headers
        for col_idx, col_name in enumerate(period_df.columns, start=1):
            ws.cell(row=2, column=col_idx, value=col_name)

        # Row 3+: period data
        for row_idx, (_, row_data) in enumerate(period_df.iterrows(), start=3):
            for col_idx, val in enumerate(row_data, start=1):
                ws.cell(row=row_idx, column=col_idx, value=val)