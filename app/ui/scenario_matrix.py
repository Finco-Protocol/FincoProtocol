"""Phase M1 — Read-Only Scenario Matrix Prototype (helper).

M1 is a UX prototype that demonstrates the
intended future Scenario Matrix layout
(Base | Downside | Upside | Custom) using
existing project inputs and existing runtime
outputs. M1 is INTENTIONALLY read-only and
INTENTIONALLY has no scenario persistence, no
scenario CRUD, and no scenario calculations.

M1 is the prototype for layout / usability /
information density / navigation / spreadsheet-like
feel. M2 will introduce actual scenario
overrides.

Hard constraints (locked by tests):

- NO scenario persistence (no
  `capex_scenario_overrides` table, no
  `add_override` / `update_override` /
  `delete_override` calls wired into routes).
- NO scenario CRUD (no create / read / update
  / delete of scenarios anywhere).
- NO scenario calculation (no new
  `_apply_scenario_overrides` engine path,
  no `ScenarioOverride` model in the runtime
  resolver).
- NO scenario save/load (no save buttons,
  no load buttons, no form posts).
- NO scenario engine.
- The matrix is rendered with placeholder
  values for non-Base columns and em-dashes
  for unset values.

The four matrix columns (locked by tests):

- BASE — populated from the current project
  inputs (live data).
- DOWNSIDE — placeholder column showing
  "inherits Base" (UI-only inheritance hint,
  no storage).
- UPSIDE — placeholder column showing
  "inherits Base" (UI-only inheritance hint,
  no storage).
- CUSTOM — placeholder column showing
  "future override" (UI-only placeholder,
  no storage).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Column registry
# ---------------------------------------------------------------------------

# The four canonical matrix columns. The order
# in this tuple is the render order in the
# table header. Locked by tests.
COLUMNS: Tuple[str, ...] = (
    "Base",
    "Downside",
    "Upside",
    "Custom",
)

# Per-column header badge / CSS class. Locked
# by tests. The Base column is the only
# "live" column. The other three columns are
# placeholders (UI-only).
COLUMN_BADGES: dict = {
    "Base": ("Live", "badge-base"),
    "Downside": ("Inherits Base", "badge-inherit"),
    "Upside": ("Inherits Base", "badge-inherit"),
    "Custom": ("Future override", "badge-future"),
}

# CSS class on the data cell in each column.
# Base cells get a slightly stronger border
# to make it obvious which column is the
# authoritative live one.
COLUMN_CELL_CLASSES: dict = {
    "Base": "matrix-cell matrix-cell-base",
    "Downside": "matrix-cell matrix-cell-inherit",
    "Upside": "matrix-cell matrix-cell-inherit",
    "Custom": "matrix-cell matrix-cell-future",
}


# ---------------------------------------------------------------------------
# Row registry
# ---------------------------------------------------------------------------

# Row kinds: an INPUT row is a project input
# (rendered from project_ctx attributes); a
# KPI row is a runtime output (rendered with
# a project_ctx attribute too, because the
# runtime swaps in the latest values via
# the same context object).
ROW_KIND_INPUT = "input"
ROW_KIND_KPI = "kpi"


@dataclass(frozen=True)
class MatrixRow:
    """One row in the scenario matrix.

    `label` is the human-readable row label
    shown in the first column.

    `kind` is ROW_KIND_INPUT or ROW_KIND_KPI.
    The matrix renders input rows before KPI
    rows and the section headers are derived
    from the kind.

    `attr` is the project_ctx attribute name
    used to populate the Base column.

    `fmt` is a callable that formats a raw
    value for display. None means render the
    raw value through `str()`. (Most rows
    pass a real formatter.)

    `unit` is the unit suffix shown in the
    label column (e.g. "EUR/MWh", "kEUR",
    "years"). None means no unit suffix.
    """

    label: str
    kind: str
    attr: str
    fmt: Optional[Callable] = None
    unit: Optional[str] = None


# Row helpers (kept tiny so tests don't have
# to import every formatter). All formatters
# return a string. None inputs render as the
# em-dash placeholder.


def _fmt_eur_mwh(val):
    """Format a tariff value as EUR/MWh."""
    if val is None:
        return "—"
    try:
        return f"{float(val):.2f} EUR/MWh"
    except (TypeError, ValueError):
        return str(val)


def _fmt_int_hours(val):
    """Format operating hours as an integer."""
    if val is None:
        return "—"
    try:
        return f"{int(round(float(val))):,} hrs/yr"
    except (TypeError, ValueError):
        return str(val)


def _fmt_mw(val):
    """Format capacity as MW."""
    if val is None:
        return "—"
    try:
        return f"{float(val):.2f} MW"
    except (TypeError, ValueError):
        return str(val)


def _fmt_keur(val):
    """Format a kEUR value with thousands separator."""
    if val is None:
        return "—"
    try:
        return f"{float(val):,.0f} kEUR"
    except (TypeError, ValueError):
        return str(val)


def _fmt_pct(val):
    """Format a fraction as a percentage."""
    if val is None:
        return "—"
    try:
        return f"{float(val) * 100:.2f}%"
    except (TypeError, ValueError):
        return str(val)


def _fmt_pct_already_pct(val):
    """Format a value that is already in percentage units (e.g. 59.4 → '59.40%').

    Used for realized_gearing_pct, which project_context.py stores as
    senior_debt / total_capex * 100 (a percentage, not a fraction).
    Using _fmt_pct here would multiply by 100 a second time (~5940%).
    """
    if val is None:
        return "—"
    try:
        return f"{float(val):.2f}%"
    except (TypeError, ValueError):
        return str(val)


def _fmt_dscr(val):
    """Format a DSCR multiplier."""
    if val is None:
        return "—"
    try:
        return f"{float(val):.2f}x"
    except (TypeError, ValueError):
        return str(val)


def _fmt_years(val):
    """Format a year count (no unit suffix; the row label carries it)."""
    if val is None:
        return "—"
    try:
        return f"{int(round(float(val)))}"
    except (TypeError, ValueError):
        return str(val)


def _fmt_months(val):
    """Format a month count (no unit suffix; the row label carries it)."""
    if val is None:
        return "—"
    try:
        return f"{int(round(float(val)))}"
    except (TypeError, ValueError):
        return str(val)


# The row inventory. The order is the render
# order. Locked by tests. The first
# `len(INPUT_ROWS)` rows are inputs; the
# remaining rows are KPIs. Tests assert this
# invariant.

INPUT_ROWS: Tuple[MatrixRow, ...] = (
    MatrixRow("Tariff", ROW_KIND_INPUT, "ppa_tariff_eur_mwh", _fmt_eur_mwh),
    MatrixRow("P50 Hours", ROW_KIND_INPUT, "operating_hours_p50", _fmt_int_hours),
    MatrixRow("Capacity", ROW_KIND_INPUT, "capacity_mw", _fmt_mw),
    MatrixRow("CAPEX", ROW_KIND_INPUT, "total_capex_keur", _fmt_keur),
    MatrixRow("OPEX (Y1)", ROW_KIND_INPUT, "opex_y1_total_keur", _fmt_keur),
    MatrixRow("Interest Rate", ROW_KIND_INPUT, "interest_rate_pct", _fmt_pct),
    MatrixRow("Senior Tenor", ROW_KIND_INPUT, "senior_tenor_years", _fmt_years, unit="years"),
    MatrixRow("Target DSCR", ROW_KIND_INPUT, "target_dscr", _fmt_dscr),
    MatrixRow("Indicative Gearing", ROW_KIND_INPUT, "gearing_pct", _fmt_pct),
    MatrixRow("PPA Term", ROW_KIND_INPUT, "ppa_term_years", _fmt_years, unit="years"),
    MatrixRow("Construction Months", ROW_KIND_INPUT, "construction_months", _fmt_months, unit="months"),
)

KPI_ROWS: Tuple[MatrixRow, ...] = (
    MatrixRow("Revenue", ROW_KIND_KPI, "total_revenue_keur", _fmt_keur),
    MatrixRow("EBITDA", ROW_KIND_KPI, "total_ebitda_keur", _fmt_keur),
    MatrixRow("Project IRR", ROW_KIND_KPI, "project_irr", _fmt_pct),
    MatrixRow("Equity IRR", ROW_KIND_KPI, "equity_irr", _fmt_pct),
    MatrixRow("Senior Debt", ROW_KIND_KPI, "senior_debt_amount_keur", _fmt_keur),
    # Phase PR2 — read-only realized gearing KPI.
    # realized_gearing_pct = senior_debt / total_capex * 100.
    # Read-only derived output (NOT a binding driver).
    # Distinct from the indicative gearing input above.
    MatrixRow("Realized Gearing", ROW_KIND_KPI, "realized_gearing_pct", _fmt_pct_already_pct),
    # U4: Avg DSCR added alongside the existing Min DSCR row. Reads the
    # same pre-existing "avg_dscr" kpi key already produced by the
    # runtime summary builder -- no new modelling, no math changes.
    MatrixRow("Avg DSCR", ROW_KIND_KPI, "avg_dscr", _fmt_dscr),
    MatrixRow("Min DSCR", ROW_KIND_KPI, "min_dscr", _fmt_dscr),
)

ALL_ROWS: Tuple[MatrixRow, ...] = INPUT_ROWS + KPI_ROWS


# ---------------------------------------------------------------------------
# Cell rendering
# ---------------------------------------------------------------------------


# Placeholder text shown in the non-Base
# columns. The text explicitly says the cell
# is a future prototype placeholder so the
# pilot user cannot mistake it for live data.
NON_BASE_PLACEHOLDER = "—"
NON_BASE_INHERIT_NOTE = "inherits Base"


def get_base_value(project_ctx, row: MatrixRow):
    """Read the Base column value from a
    project_ctx-like object.

    Returns None if the attribute is missing
    or has a None value. The cell renderer
    formats None as the em-dash placeholder.
    """
    if project_ctx is None:
        return None
    return getattr(project_ctx, row.attr, None)


def format_cell_value(row: MatrixRow, value) -> str:
    """Format a raw value for a row using the
    row's `fmt` callable. None values are
    formatted as the em-dash placeholder.
    """
    if row.fmt is None:
        return str(value) if value is not None else NON_BASE_PLACEHOLDER
    return row.fmt(value)


def build_matrix_rows(
    project_ctx,
    rows: Sequence[MatrixRow] = ALL_ROWS,
) -> list:
    """Build the render-ready matrix rows.

    Each returned entry is a dict:
      {
        "row": MatrixRow,
        "kind": str,
        "section": str,        # "Inputs" or "Outputs (KPIs)"
        "base": str,           # formatted value, "—" if missing
        "downside": str,       # NON_BASE_INHERIT_NOTE
        "upside": str,         # NON_BASE_INHERIT_NOTE
        "custom": str,         # NON_BASE_PLACEHOLDER
        "is_kpi": bool,
      }

    Locked by tests: input rows come first
    (section "Inputs"), then KPI rows (section
    "Outputs (KPIs)"). The base column reads
    from project_ctx; the other three columns
    are placeholders.
    """
    out = []
    for row in rows:
        base_value = get_base_value(project_ctx, row)
        base_str = format_cell_value(row, base_value)
        section = "Inputs" if row.kind == ROW_KIND_INPUT else "Outputs (KPIs)"
        out.append({
            "row": row,
            "kind": row.kind,
            "section": section,
            "base": base_str,
            "downside": NON_BASE_INHERIT_NOTE,
            "upside": NON_BASE_INHERIT_NOTE,
            "custom": NON_BASE_PLACEHOLDER,
            "is_kpi": row.kind == ROW_KIND_KPI,
        })
    return out


# ---------------------------------------------------------------------------
# Inheritance / override notes (UI-only, no storage)
# ---------------------------------------------------------------------------


# Inheritance note shown in the matrix card
# header. UI-only: explains that Downside and
# Upside are placeholders that visually
# inherit from Base, but no inheritance is
# actually computed (M2 will implement
# inheritance with storage).
INHERITANCE_NOTE = (
    "Inheritance shown here is a UI prototype "
    "only. Downside / Upside columns display "
    "placeholder values; no scenario overrides "
    "are stored. Custom column is reserved for "
    "future override support in M2."
)


# ---------------------------------------------------------------------------
# M2: Live scenario column helpers
# ---------------------------------------------------------------------------


def _get_scenario_input_value(scenario_record, row: MatrixRow) -> str:
    """Read a row's input value from a scenario's snapshot.

    Checks `overrides` first (scenario-specific delta), then
    `snapshot` (full saved input set), then `base_input_set`.
    Returns formatted string; em-dash if not found.
    """
    if scenario_record is None:
        return NON_BASE_PLACEHOLDER

    for src in (
        getattr(scenario_record, "overrides", None) or {},
        getattr(scenario_record, "snapshot", None) or {},
        getattr(scenario_record, "base_input_set", None) or {},
    ):
        val = src.get(row.attr)
        if val is not None:
            return format_cell_value(row, val)
    return NON_BASE_PLACEHOLDER


def _get_scenario_kpi_value(scenario_record, row: MatrixRow) -> str:
    """Read a KPI value from a scenario's last_run_summary.

    Returns formatted string; em-dash if no run exists.
    """
    if scenario_record is None:
        return NON_BASE_PLACEHOLDER
    summary = getattr(scenario_record, "last_run_summary", None) or {}
    kpis = summary.get("kpis") or summary
    val = kpis.get(row.attr)
    if val is None:
        return NON_BASE_PLACEHOLDER
    return format_cell_value(row, val)


def get_scenario_cell_value(scenario_record, row: MatrixRow) -> str:
    """Return the formatted cell value for a non-Base scenario column.

    For input rows: reads from the scenario's saved snapshot/overrides.
    For KPI rows: reads from the scenario's last_run_summary.
    Falls back to em-dash when data is absent.
    """
    if row.kind == ROW_KIND_INPUT:
        return _get_scenario_input_value(scenario_record, row)
    return _get_scenario_kpi_value(scenario_record, row)


def build_matrix_context(
    project_ctx,
    scenario_records=None,
    rows: Sequence[MatrixRow] = ALL_ROWS,
    runtime_kpis: dict | None = None,
) -> dict:
    """Build the full matrix rendering context for M2.

    Returns a dict suitable for passing directly to the
    scenario_matrix.html template:

      {
        "matrix_rows": [...],   # render-ready rows (M1 shape + m2 columns)
        "col_downside": ScenarioRecord | None,
        "col_upside":   ScenarioRecord | None,
        "col_custom":   ScenarioRecord | None,
        "m2_live": bool,        # True when at least one non-Base column is live
      }

    Column assignment: the first non-base-case scenario goes in
    Downside, the second in Upside, the third in Custom. Scenarios
    beyond three are ignored in the matrix (accessible via the
    Scenarios tab as before).

    No new persistence: reads existing ScenarioRecord objects passed
    in from the index route context.
    """
    records = list(scenario_records or [])
    non_base = [s for s in records if not getattr(s, "is_base_case", False)]

    col_downside = non_base[0] if len(non_base) > 0 else None
    col_upside   = non_base[1] if len(non_base) > 1 else None
    col_custom   = non_base[2] if len(non_base) > 2 else None

    out = []
    for row in rows:
        # For KPI rows, prefer runtime_kpis (last run result) over project_ctx
        if row.kind == ROW_KIND_KPI and runtime_kpis:
            base_value = runtime_kpis.get(row.attr)
        else:
            base_value = get_base_value(project_ctx, row)
        base_str = format_cell_value(row, base_value)
        section = "Inputs" if row.kind == ROW_KIND_INPUT else "Outputs (KPIs)"
        out.append({
            "row": row,
            "kind": row.kind,
            "section": section,
            "base": base_str,
            "downside": get_scenario_cell_value(col_downside, row),
            "upside":   get_scenario_cell_value(col_upside,   row),
            "custom":   get_scenario_cell_value(col_custom,   row),
            "is_kpi": row.kind == ROW_KIND_KPI,
            # Per-column live flags (True when the scenario has run data
            # for this KPI row, or has snapshot data for input rows)
            "downside_live": col_downside is not None,
            "upside_live":   col_upside   is not None,
            "custom_live":   col_custom   is not None,
        })

    m2_live = any(c is not None for c in (col_downside, col_upside, col_custom))

    return {
        "matrix_rows": out,
        "col_downside": col_downside,
        "col_upside":   col_upside,
        "col_custom":   col_custom,
        "m2_live": m2_live,
    }

