"""Phase 7C-5 — Excel export helpers for sponsor waterfall audit sheets.

Audit-only Excel export for:
  - WaterfallAllocationResult  → "Sponsor Waterfall Allocation" sheet
  - PreferredReturnResult        → "Preferred Return Accrual" sheet
  - TierAnnotatedSponsorCapitalAccount → "Tier Capital Account" sheet

Pure function — no mutation, no model integration, no formulas.
All values are pre-computed domain results. No recalculation in export.
"""
from __future__ import annotations

import pandas as pd

__all__ = [
    "write_sponsor_waterfall_audit_sheets",
    "build_waterfall_allocation_table",
    "build_preferred_return_table",
    "build_tier_capital_account_table",
]


_AUDIT_NOTE = (
    "AUDIT-ONLY: sponsor waterfall audit sheet — read-only export artifact, "
    "not a distribution commitment or financial advice."
)


# ── Sheet name helpers ─────────────────────────────────────────────────────

_EXCEL_INVALID_CHARS = frozenset("/\\*?[]:")


def _safe_sheet_name(name: str) -> str:
    """Sanitize a string for use as an Excel sheet name (max 31 chars)."""
    safe = "".join("_" if c in _EXCEL_INVALID_CHARS else c for c in name)
    if len(safe) > 31:
        safe = safe[:31]
    return safe


# ── Table builders ──────────────────────────────────────────────────────────

def build_waterfall_allocation_table(result) -> pd.DataFrame:
    """Build a DataFrame from WaterfallAllocationResult.

    One row per (period_index, tier_index) pair.
    Per-sponsor allocations are flattened into separate columns.
    """
    rows = []
    for period_result in result.period_results:
        p = period_result.period_index
        for tier_entry in period_result.tier_entries:
            row = {
                "period_index": p,
                "tier_index": tier_entry.tier_index,
                "tier_type": tier_entry.tier_type.value,
                "available_cash_before_tier_keur": tier_entry.available_cash_before_tier_keur,
                "allocated_amount_keur": tier_entry.allocated_amount_keur,
                "remaining_cash_after_tier_keur": tier_entry.remaining_cash_after_tier_keur,
            }
            # Flatten per-sponsor allocations
            for code, amt in tier_entry.allocated_per_sponsor_keur:
                col = f"alloc_{code}_keur"
                row[col] = amt
            rows.append(row)

    if not rows:
        return pd.DataFrame(columns=[
            "period_index", "tier_index", "tier_type",
            "available_cash_before_tier_keur", "allocated_amount_keur",
            "remaining_cash_after_tier_keur",
        ])

    df = pd.DataFrame(rows)

    # Collect all sponsor codes across ALL periods for cumulative distribution columns
    all_cum_codes = set()
    for pr in result.period_results:
        for code, _ in pr.cumulative_distributions_by_sponsor_keur:
            all_cum_codes.add(code)

    # Add cumdist_* columns for the full union of sponsor codes (initialized to 0.0)
    for code in sorted(all_cum_codes):
        col = f"cumdist_{code}_keur"
        if col not in df.columns:
            df[col] = 0.0

    # Fill each period's rows from that period's cumulative distributions
    for period_result in result.period_results:
        mask = df["period_index"] == period_result.period_index
        for code, amt in period_result.cumulative_distributions_by_sponsor_keur:
            col = f"cumdist_{code}_keur"
            if col in df.columns:
                df.loc[mask, col] = amt

    return df


def build_preferred_return_table(result) -> pd.DataFrame:
    """Build a DataFrame from PreferredReturnResult.

    One row per accrual entry (period).
    """
    rows = []
    for entry in result.entries:
        rows.append({
            "period_index": entry.period_index,
            "opening_invested_capital_keur": entry.opening_invested_capital_keur,
            "invested_capital_delta_keur": entry.invested_capital_delta_keur,
            "hurdle_rate_pa": entry.hurdle_rate_pa,
            "compounding_convention": entry.compounding_convention,
            "accrual_periods": entry.accrual_periods,
            "accrued_pref_keur": entry.accrued_pref_keur,
            "cumulative_accrued_pref_keur": entry.cumulative_accrued_pref_keur,
            "cumulative_distributions_keur": entry.cumulative_distributions_keur,
            "unpaid_pref_balance_keur": entry.unpaid_pref_balance_keur,
            "hurdle_satisfied": entry.hurdle_satisfied,
        })
    if not rows:
        return pd.DataFrame(columns=[
            "period_index", "opening_invested_capital_keur", "invested_capital_delta_keur",
            "hurdle_rate_pa", "compounding_convention", "accrual_periods",
            "accrued_pref_keur", "cumulative_accrued_pref_keur",
            "cumulative_distributions_keur", "unpaid_pref_balance_keur", "hurdle_satisfied",
        ])
    return pd.DataFrame(rows)


def build_tier_capital_account_table(
    accounts: tuple,
) -> pd.DataFrame:
    """Build a combined DataFrame from a tuple of TierAnnotatedSponsorCapitalAccount.

    One row per annotated entry. Tier annotation fields are flattened alongside
    base capital account fields.
    """
    rows = []
    for account in accounts:
        for ae in account.entries:
            e = ae.entry
            ann = ae.annotation
            row = {
                "investor_id": e.investor_id,
                "entity_code": account.entity_code,
                "period_index": e.period_index,
                "entry_type": e.entry_type,
                "amount_keur": e.amount_keur,
                "running_balance_keur": e.running_balance_keur,
                "source": e.source,
                # Tier annotation fields
                "tier_index": ann.tier_index,
                "tier_type": ann.tier_type.value if ann.tier_type else None,
                "tier_sponsor_code": ann.sponsor_code,
                "tier_allocated_amount_keur": ann.allocated_amount_keur,
                "tier_source_note": ann.source_note,
            }
            rows.append(row)

    if not rows:
        return pd.DataFrame(columns=[
            "investor_id", "entity_code", "period_index", "entry_type",
            "amount_keur", "running_balance_keur", "source",
            "tier_index", "tier_type", "tier_sponsor_code",
            "tier_allocated_amount_keur", "tier_source_note",
        ])
    return pd.DataFrame(rows)


# ── Core writer ─────────────────────────────────────────────────────────────

def write_sponsor_waterfall_audit_sheets(
    writer,
    waterfall_result=None,
    preferred_return_result=None,
    tier_annotated_accounts=None,
) -> None:
    """Write sponsor waterfall audit sheets into an open Excel workbook.

    Parameters
    ----------
    writer : pandas.ExcelWriter
        Open ExcelWriter with an active openpyxl workbook.
    waterfall_result : WaterfallAllocationResult | None
        Waterfall allocation result from Phase 7C-3 runner.
    preferred_return_result : PreferredReturnResult | None
        Preferred return accrual result from Phase 7C-2 calculator.
    tier_annotated_accounts : tuple[TierAnnotatedSponsorCapitalAccount, ...] | None
        Tuple of tier-annotated capital accounts from Phase 7C-4 converter.

    Behavior
    --------
    - All arguments are optional. Missing results → no-op for that sheet.
    - Each sheet gets an audit note in row 1.
    - Headers are in row 2. Data starts at row 3.
    - Sheet names are deterministic (no duplicates).
    - No existing sheets are modified or removed.
    - No recalculation — all values come from pre-computed domain results.
    """
    if not waterfall_result and not preferred_return_result and not tier_annotated_accounts:
        return

    _write_waterfall_sheet(writer, waterfall_result)
    _write_preferred_return_sheet(writer, preferred_return_result)
    _write_tier_capital_account_sheet(writer, tier_annotated_accounts)


def _write_waterfall_sheet(writer, result) -> None:
    """Write 'Sponsor Waterfall Allocation' sheet."""
    if result is None:
        return

    df = build_waterfall_allocation_table(result)
    sheet_name = "Sponsor Waterfall Allocation"

    wb = writer.book
    if sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
    else:
        ws = wb.create_sheet(sheet_name)

    _write_audit_header(ws, df, _AUDIT_NOTE)


def _write_preferred_return_sheet(writer, result) -> None:
    """Write 'Preferred Return Accrual' sheet."""
    if result is None:
        return

    df = build_preferred_return_table(result)
    sheet_name = "Preferred Return Accrual"

    wb = writer.book
    if sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
    else:
        ws = wb.create_sheet(sheet_name)

    _write_audit_header(ws, df, _AUDIT_NOTE)


def _write_tier_capital_account_sheet(writer, accounts) -> None:
    """Write 'Tier Capital Account' sheet."""
    if not accounts:
        return

    df = build_tier_capital_account_table(accounts)
    sheet_name = "Tier Capital Account"

    wb = writer.book
    if sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
    else:
        ws = wb.create_sheet(sheet_name)

    _write_audit_header(ws, df, _AUDIT_NOTE)


def _write_audit_header(ws, df: pd.DataFrame, audit_note: str) -> None:
    """Write audit note (row 1), headers (row 2), then data (row 3+)."""
    # Row 1: audit note
    ws.cell(row=1, column=1, value=audit_note)

    # Row 2: column headers
    for col_idx, col_name in enumerate(df.columns, start=1):
        ws.cell(row=2, column=col_idx, value=col_name)

    # Row 3+: data
    for row_idx, (_, row_data) in enumerate(df.iterrows(), start=3):
        for col_idx, val in enumerate(row_data, start=1):
            ws.cell(row=row_idx, column=col_idx, value=val)
