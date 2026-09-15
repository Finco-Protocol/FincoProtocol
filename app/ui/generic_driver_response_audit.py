"""Phase P1-A — Generic Driver Response Audit.

Pure read-side audit helper module. Tests whether
each editable Generic Solar / Generic Wind form
field actually changes the runtime KPIs when the
form value is changed.

This is a CAPTURE-ONLY audit. The helper does NOT
mutate any production code, does NOT call any
runtime paths that are not already in the
exploratory Generic path, and does NOT touch any
formulas.

The 11 editable Generic form fields audited (per
the Phase P1-A brief):

  1. tariff_eur_mwh
  2. p50_hours
  3. total_capex_keur
  4. opex_y1_keur
  5. capacity_mw
  6. gearing_pct
  7. interest_rate_pct
  8. tenor_years
  9. target_dscr
  10. ppa_term_years (UI only, no schema field)
  11. construction_months (UI only, not in run path)

For each field, the helper computes:
  - baseline_kpis
  - changed_kpis
  - per_kpi_delta
  - status: WIRED | NOT_WIRED | METADATA_ONLY
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Status vocabulary
# ---------------------------------------------------------------------------


STATUS_WIRED = "WIRED"
STATUS_NOT_WIRED = "NOT_WIRED"
STATUS_METADATA_ONLY = "METADATA_ONLY"
STATUS_WIRED_PARTIAL = "WIRED_PARTIAL"

ALL_STATUSES: tuple[str, ...] = (
    STATUS_WIRED,
    STATUS_NOT_WIRED,
    STATUS_METADATA_ONLY,
    STATUS_WIRED_PARTIAL,
)


# ---------------------------------------------------------------------------
# KPI vocabulary
# ---------------------------------------------------------------------------


KPI_PROJECT_IRR = "project_irr"
KPI_EQUITY_IRR = "equity_irr"
KPI_MIN_DSCR = "min_dscr"
KPI_AVG_DSCR = "avg_dscr"
KPI_TOTAL_REVENUE = "total_revenue_keur"
KPI_TOTAL_OPEX = "total_opex_keur"
KPI_TOTAL_EBITDA = "total_ebitda_keur"
KPI_SENIOR_DEBT = "senior_debt_keur"

ALL_KPIS: tuple[str, ...] = (
    KPI_PROJECT_IRR,
    KPI_EQUITY_IRR,
    KPI_MIN_DSCR,
    KPI_AVG_DSCR,
    KPI_TOTAL_REVENUE,
    KPI_TOTAL_OPEX,
    KPI_TOTAL_EBITDA,
    KPI_SENIOR_DEBT,
)


@dataclass(frozen=True)
class DriverEntry:
    """A single driver field's audit results."""

    #: Field name (e.g. "tariff_eur_mwh").
    field: str

    #: Baseline value used in the run.
    baseline_value: Any

    #: Changed value used in the run.
    changed_value: Any

    #: Per-KPI delta dict: kpi -> (baseline, changed).
    kpi_deltas: dict[str, tuple[Any, Any]]

    #: Status: WIRED | NOT_WIRED | METADATA_ONLY.
    status: str

    #: Human-readable note.
    note: str = ""


@dataclass(frozen=True)
class DriverResponseAudit:
    """The full audit report."""

    project_type: str
    entries: tuple[DriverEntry, ...]
    field_count: int
    wired_count: int
    not_wired_count: int
    metadata_only_count: int

    def to_table_rows(self) -> tuple[tuple[str, str, str, str], ...]:
        """Return a flat tuple of (field, status, summary, note) rows."""
        rows: list[tuple[str, str, str, str]] = []
        for e in self.entries:
            summary = f"baseline={e.baseline_value!r} -> changed={e.changed_value!r}"
            rows.append((e.field, e.status, summary, e.note))
        return tuple(rows)


__all__ = [
    "DriverEntry",
    "DriverResponseAudit",
    "STATUS_WIRED",
    "STATUS_NOT_WIRED",
    "STATUS_METADATA_ONLY",
    "ALL_STATUSES",
    "KPI_PROJECT_IRR",
    "KPI_EQUITY_IRR",
    "KPI_MIN_DSCR",
    "KPI_AVG_DSCR",
    "KPI_TOTAL_REVENUE",
    "KPI_TOTAL_OPEX",
    "KPI_TOTAL_EBITDA",
    "KPI_SENIOR_DEBT",
    "ALL_KPIS",
    "compute_kpi_deltas",
    "summarize_status",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def compute_kpi_deltas(
    baseline_result: Any, changed_result: Any, kpis: tuple[str, ...]
) -> dict[str, tuple[Any, Any]]:
    """Return per-KPI (baseline, changed) tuple from two
    WaterfallResult objects."""
    deltas: dict[str, tuple[Any, Any]] = {}
    for kpi in kpis:
        baseline_val = getattr(baseline_result, kpi, None)
        changed_val = getattr(changed_result, kpi, None)
        deltas[kpi] = (baseline_val, changed_val)
    return deltas


def summarize_status(
    deltas: dict[str, tuple[Any, Any]],
    *,
    tolerance: float = 1e-6,
) -> str:
    """Return WIRED if any KPI changed beyond the
    tolerance, otherwise NOT_WIRED.

    Use a finer-grained approach to also flag
    WIRED_PARTIAL when project_irr does not change
    but other KPIs do.

    The tolerance is a relative tolerance: the delta
    must be at least ``tolerance * max(|baseline|, 1.0)``
    for the status to be WIRED.
    """
    any_change = False
    project_irr_changed = False
    for kpi, (baseline, changed) in deltas.items():
        if baseline is None and changed is None:
            continue
        if baseline is None or changed is None:
            any_change = True
            continue
        try:
            base_f = float(baseline)
            chg_f = float(changed)
        except (TypeError, ValueError):
            # Non-numeric KPI; if values differ, WIRED.
            if baseline != changed:
                any_change = True
            continue
        if abs(base_f - chg_f) > tolerance * max(abs(base_f), 1.0):
            any_change = True
            if kpi == "project_irr":
                project_irr_changed = True
    if not any_change:
        return STATUS_NOT_WIRED
    if project_irr_changed:
        return STATUS_WIRED
    return STATUS_WIRED_PARTIAL
