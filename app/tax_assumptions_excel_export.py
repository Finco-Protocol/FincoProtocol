"""Phase 6D.1 — Excel export helper for tax assumptions audit results.

Pure function — no mutation, no model integration.

CAVEAT: Values-only export. No formulas. No existing excel_export.py modification.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.tax.templates.inputs import TaxTemplate, TaxTemplateOverride, ResolvedTaxConfig

__all__ = ["write_tax_assumptions_audit_sheets"]

_EXCEL_INVALID_CHARS = frozenset('/\\*?[]:')


def _sanitize_sheet_name(name: str, max_len: int = 31) -> str:
    """Sanitize a sheet name for Excel, replacing invalid characters with _."""
    safe = "".join("_" if c in _EXCEL_INVALID_CHARS else c for c in name)
    if len(safe) > max_len:
        safe = safe[:max_len]
    return safe


def _unique_sheet_name(base: str, used: set[str]) -> str:
    """Return a unique sheet name, appending _2, _3, etc. as needed."""
    if base not in used:
        return base
    suffix = 2
    while True:
        candidate = f"{base[:31 - len(str(suffix))]}_{suffix}"
        if candidate not in used:
            return candidate
        suffix += 1


def write_tax_assumptions_audit_sheets(
    writer,
    templates: tuple[TaxTemplate, ...] = (),
    resolved_configs: tuple[ResolvedTaxConfig, ...] = (),
    overrides: tuple[TaxTemplateOverride, ...] = (),
) -> None:
    """Write tax assumptions audit sheets into an open Excel workbook.

    Parameters
    ----------
    writer : pandas.ExcelWriter
        Open ExcelWriter (e.g., from pd.ExcelWriter(filepath)).
    templates : tuple[TaxTemplate, ...]
        Tax templates to export. If empty, sheet is skipped.
    resolved_configs : tuple[ResolvedTaxConfig, ...]
        Resolved tax configs to export. If empty, sheet is skipped.
    overrides : tuple[TaxTemplateOverride, ...]
        Overrides to export. If empty, sheet is skipped.

    Behavior
    --------
    - No-op if all inputs are empty.
    - Creates "Tax Templates" sheet (always, if templates provided).
    - Creates "Tax Tiers" sheet (always, if templates provided with tiers).
    - Creates "Tax Dep Rules" sheet (always, if templates with rules provided).
    - Creates "Tax Overrides" sheet (only if overrides provided).
    - Creates "Resolved Tax Config" sheet (only if resolved_configs provided).
    - Row 1 = audit note, Row 2 = headers, Row 3+ = data.
    - Values only, no formulas.

    Notes
    -----
    - Does NOT modify existing sheets.
    - Does NOT call build_excel_export() or replace it.
    - Sheet names are sanitised for Excel-invalid characters.
    - Duplicate names are disambiguated with _2, _3, ...
    """
    if not templates and not resolved_configs and not overrides:
        return

    import pandas as pd
    from app.tax_assumptions_ui import (
        build_tax_template_summary_table,
        build_tax_template_tiers_table,
        build_tax_depreciation_rules_table,
        build_tax_override_table,
        build_resolved_tax_config_summary,
        build_tax_assumptions_audit_note,
    )

    audit_note = build_tax_assumptions_audit_note()
    wb = writer.book
    used_sheet_names: set[str] = set()

    def _write_sheet(sheet_name: str, df: pd.DataFrame | pd.Series) -> None:
        safe_name = _unique_sheet_name(_sanitize_sheet_name(sheet_name), used_sheet_names)
        used_sheet_names.add(safe_name)

        if safe_name in wb.sheetnames:
            ws = wb[safe_name]
        else:
            ws = wb.create_sheet(safe_name)

        ws.cell(row=1, column=1, value=audit_note)
        for col_idx, col_name in enumerate(df.columns, start=1):
            ws.cell(row=2, column=col_idx, value=col_name)
        for row_idx, row_data in enumerate(df.itertuples(index=False), start=3):
            for col_idx, val in enumerate(row_data, start=1):
                # Serialize dict/list to JSON string for Excel compatibility
                if isinstance(val, (dict, list)):
                    import json
                    serialized = json.dumps(val)
                    ws.cell(row=row_idx, column=col_idx, value=serialized)
                else:
                    ws.cell(row=row_idx, column=col_idx, value=val)

    # ── Tax Templates sheet ──────────────────────────────────────────
    if templates:
        summary_df = build_tax_template_summary_table(templates)
        if not summary_df.empty:
            _write_sheet("Tax Templates", summary_df)

        # ── Tax Tiers sheet ─────────────────────────────────────────
        tier_frames = []
        for tmpl in templates:
            frame = build_tax_template_tiers_table(tmpl)
            if not frame.empty:
                tier_frames.append(frame.assign(Template=tmpl.template_name))

        if tier_frames:
            tiers_df = pd.concat(tier_frames, ignore_index=True)
            cols = ["Template"] + [c for c in tiers_df.columns if c != "Template"]
            _write_sheet("Tax Tiers", tiers_df[cols])

        # ── Tax Dep Rules sheet ────────────────────────────────────
        dep_frames = []
        for tmpl in templates:
            frame = build_tax_depreciation_rules_table(tmpl)
            if not frame.empty:
                dep_frames.append(frame.assign(Template=tmpl.template_name))

        if dep_frames:
            dep_df = pd.concat(dep_frames, ignore_index=True)
            dep_df = dep_df.dropna(axis=1, how="all")
            cols = ["Template"] + [c for c in dep_df.columns if c != "Template"]
            _write_sheet("Tax Dep Rules", dep_df[cols])

    # ── Tax Overrides sheet (optional) ───────────────────────────────
    if overrides:
        override_df = build_tax_override_table(overrides)
        if not override_df.empty:
            _write_sheet("Tax Overrides", override_df)

    # ── Resolved Tax Config sheet (optional) ────────────────────────
    if resolved_configs:
        resolved_frames = []
        for cfg in resolved_configs:
            frame = build_resolved_tax_config_summary(cfg)
            if not frame.empty:
                resolved_frames.append(frame)

        if resolved_frames:
            resolved_df = pd.concat(resolved_frames, ignore_index=True)
            _write_sheet("Resolved Tax Config", resolved_df)