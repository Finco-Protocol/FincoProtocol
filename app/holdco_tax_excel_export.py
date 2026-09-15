"""Phase 6C.4 — Excel export helper for HoldCo tax audit results.

Pure function — no mutation, no model integration.

CAVEAT: Values-only export. No formulas. No existing excel_export.py modification.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.tax.holdco_result import HoldCoTaxResult

__all__ = ["write_holdco_tax_audit_sheets"]

# Excel invalid sheet name characters
_EXCEL_INVALID_CHARS = frozenset('/\\*?[]:')


def _make_safe_sheet_name(entity_code: str) -> str:
    """Sanitize entity_code for use as an Excel sheet name.

    Replaces all characters invalid in Excel sheet names with "_".
    Result is prefixed with "HoldCoTax_".
    Result is at most 31 characters (Excel limit).
    """
    safe = "".join("_" if c in _EXCEL_INVALID_CHARS else c for c in entity_code)
    base = f"HoldCoTax_{safe}"
    if len(base) > 31:
        base = base[:31]
    return base


def _unique_sheet_name(base: str, used: set[str]) -> str:
    """Return a unique sheet name based on base, appending _2, _3, etc. as needed."""
    if base not in used:
        return base

    suffix = 2
    while True:
        suffix_str = f"_{suffix}"
        max_base_len = 31 - len(suffix_str)
        truncated = base[:max_base_len]
        candidate = f"{truncated}{suffix_str}"
        if candidate not in used:
            return candidate
        suffix += 1


def write_holdco_tax_audit_sheets(
    writer,
    holdco_tax_results: tuple[HoldCoTaxResult, ...] | None,
) -> None:
    """Write HoldCo tax audit sheets into an open Excel workbook.

    Parameters
    ----------
    writer : pandas.ExcelWriter
        Open ExcelWriter (e.g., from pd.ExcelWriter(filepath)).
    holdco_tax_results : tuple[HoldCoTaxResult, ...] | None
        Tuple of HoldCoTaxResult objects. None or empty tuple → no-op.

    Behavior
    --------
    - If holdco_tax_results is None or empty, does nothing.
    - Writes "HoldCo Tax Summary" sheet with one row per HoldCo entity.
      Row 1 = audit note, Row 2 = headers, Row 3+ = data.
    - Writes one detail sheet per entity: "HoldCoTax_{entity_code}"
      (sanitized, truncated to 31 chars, disambiguated if needed).
      Row 1 = audit note, Row 2 = headers, Row 3+ = period data.
    - All values, no formulas.

    Notes
    -----
    - Does NOT modify existing sheets.
    - Does NOT call build_excel_export() or replace it.
    - Sheet names are sanitised for all Excel-invalid characters.
    - Duplicate names (after truncation) are disambiguated with _2, _3, ...
    """
    if not holdco_tax_results:
        return

    import pandas as pd
    from app.holdco_tax_ui import (
        build_holdco_tax_summary_table,
        build_holdco_tax_period_table,
        build_holdco_tax_audit_note,
    )

    audit_note = build_holdco_tax_audit_note()
    wb = writer.book

    # ── HoldCo Tax Summary sheet ─────────────────────────────────────
    all_rows = []
    for result in holdco_tax_results:
        all_rows.extend(build_holdco_tax_summary_table(result))

    if all_rows:
        summary_df = pd.DataFrame(all_rows)

        summary_sheet_name = "HoldCo Tax Summary"
        if summary_sheet_name in wb.sheetnames:
            ws = wb[summary_sheet_name]
        else:
            ws = wb.create_sheet(summary_sheet_name)

        ws.cell(row=1, column=1, value=audit_note)
        for col_idx, col_name in enumerate(summary_df.columns, start=1):
            ws.cell(row=2, column=col_idx, value=col_name)
        for row_idx, row_data in enumerate(summary_df.itertuples(index=False), start=3):
            for col_idx, val in enumerate(row_data, start=1):
                ws.cell(row=row_idx, column=col_idx, value=val)

    # ── Per-entity detail sheets ───────────────────────────────────
    used_sheet_names: set[str] = set()

    for result in holdco_tax_results:
        base = _make_safe_sheet_name(result.entity_code)
        sheet_name = _unique_sheet_name(base, used_sheet_names)
        used_sheet_names.add(sheet_name)

        period_rows = build_holdco_tax_period_table(result)
        period_df = pd.DataFrame(period_rows)

        if sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
        else:
            ws = wb.create_sheet(sheet_name)

        ws.cell(row=1, column=1, value=audit_note)
        for col_idx, col_name in enumerate(period_df.columns, start=1):
            ws.cell(row=2, column=col_idx, value=col_name)
        for row_idx, row_data in enumerate(period_df.itertuples(index=False), start=3):
            for col_idx, val in enumerate(row_data, start=1):
                ws.cell(row=row_idx, column=col_idx, value=val)