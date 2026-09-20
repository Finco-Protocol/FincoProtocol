"""
OPEX View Model — spreadsheet-style display layer for OPEX grids.

Transforms ProjectContext.opex_detail_items into template-ready dataclasses.
No engine logic, no persistence, no routes.

canonical source: B.01–B.13 structure (Generic Wind Reference + Generic Solar Reference mapping, PR #849).

Year value contract:
  Year escalation formula (simple lines):
      Yn = Y1_budget × (1 + inflation_pct / 100)^(n-1)

  Pre-computed `yearly_values` from opex_detail_items are used when present
  (they correctly handle step schedules and conditional activation).
  `compute_year_values()` is exposed for the simple formula case.

  Optional step schedules and conditional lines are represented by canonical line-item metadata.
  via the pre-computed yearly_values field. Custom schedule editing is out of
  scope for v1 but must be a future extension point.

Editability contract:
  - Group header rows (B.01, B.02, …)   → display only
  - B.13 Contingencies sub-lines         → is_contingency=True, is_derived=True, read-only
  - All other sub-lines, user project    → is_editable=True, is_read_only=False
  - All other sub-lines, non-user        → is_editable=False, is_read_only=True
  - WHT flag                             → display only, set by project template
  - Year columns Y2–YN                   → always derived, never submitted

KPI denominator contract:
  - opex_per_mw_y1 = None when capacity_mw is missing or zero
  - opex_per_mwh_y1 = None when p50_annual_mwh is missing or zero
  Do not return 0.0 for unavailable KPIs.

Mutation contract:
  See AddOpexLineCommand / UpdateOpexLineCommand / DeactivateOpexLineCommand.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Sequence

if TYPE_CHECKING:
    from app.ui.project_context import ProjectContext
    from app.persistence.opex_sub_lines import OpexSubLine

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DISPLAY_YEARS = 30
MAX_DISPLAY_YEARS = 30

_CONTINGENCY_CODE = "B.13"


# ---------------------------------------------------------------------------
# Pure formula — exposed for testing and future template use
# ---------------------------------------------------------------------------

def compute_year_values(
    y1_keur: float,
    inflation_pct: float,
    n_years: int,
) -> list[float]:
    """
    Compute year values for a simple escalating OPEX line.

    Yn = Y1 × (1 + inflation_pct/100)^(n-1)

    Index 0 = Y1, index 1 = Y2, …, index n_years-1 = Yn.
    """
    rate = 1.0 + inflation_pct / 100.0
    return [y1_keur * (rate ** (yr - 1)) for yr in range(1, n_years + 1)]


# ---------------------------------------------------------------------------
# Dataclasses — Line
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OpexLineVM:
    """Single sub-line row in the OPEX spreadsheet grid."""

    # Identity
    row_id: str          # Deterministic: "{project_code}:{parent_code}:{code}"
    code: str
    parent_code: str
    name: str

    # Provenance
    source: str          # "factory" | "excel_reference" | "app_input" | …
    unit: str            # Always "kEUR" for OPEX
    notes: str           # Notes or formula description from source data
    display_order: int   # 1-based position within parent group
    validation_status: str  # "ok" | "unknown" (OPEX source is factory-generated)

    # Y1 budget (user-editable for editable lines)
    y1_keur: float

    # Group-level escalation rate applied to this line
    inflation_pct: float

    # Withholding Tax flag — display column only, set by project template
    wht_flag: bool

    # Structural flags
    is_group: bool         # True = group header row
    is_editable: bool      # True iff user may change y1_keur
    is_read_only: bool     # True iff value must never be changed by user
    is_derived: bool       # True iff value is computed (contingency lines)
    is_contingency: bool   # True for B.13 sub-lines
    is_fixed: bool         # True for fixed-cost lines (default: True for all v1 template lines)
    is_variable: bool      # True for variable-cost lines (default: False for v1 template lines)

    # Future: user-managed line items
    is_custom: bool   # True = user-added line (not in reference template)
    is_active: bool   # False = user has deactivated this line (excluded from totals)

    # Pre-computed year values (index 0 = Y1, index 1 = Y2, …)
    # Length = display_years (from OpexViewModel).
    year_values: tuple[float, ...]

    # Custom-row identity — empty strings for factory / template lines.
    sub_line_id: str = ""     # UUID; populated for user-added custom rows
    row_version: str = ""     # updated_at token; populated for custom rows


# ---------------------------------------------------------------------------
# Dataclasses — Group
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OpexGroupVM:
    """Group header (B.01, B.02, …) with its sub-lines."""

    code: str
    name: str
    inflation_pct: float   # group-level default escalation rate
    is_contingency: bool
    contingency_pct: float  # 0.0 unless is_contingency

    lines: tuple[OpexLineVM, ...]

    # Derived: sum of active non-contingency sub-lines per display year (index 0 = Y1)
    subtotal_per_year: tuple[float, ...]


# ---------------------------------------------------------------------------
# Dataclasses — ViewModel
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OpexViewModel:
    """Full OPEX sheet view model, ready for template iteration."""

    project_name: str
    capacity_mw: float
    p50_annual_mwh: float   # operating_hours_p50 × capacity_mw

    groups: tuple[OpexGroupVM, ...]  # B.01–B.13 in canonical order

    # Contingency rate (from project_ctx.opex_contingency_pct)
    contingency_rate: float

    # Per-year totals (index 0 = Y1, …, index display_years-1)
    total_excl_contingency: tuple[float, ...]
    contingency_by_year: tuple[float, ...]       # contingency_rate/100 × total_excl per year
    total_incl_contingency: tuple[float, ...]    # total_excl + contingency_by_year

    # Convenience scalars
    y1_total_opex: float          # total_incl_contingency[0]
    final_year_total_opex: float  # total_incl_contingency[-1]

    # Number of year columns being displayed (1 ≤ display_years ≤ 30)
    display_years: int

    # Y1 KPI metrics — None when denominator is missing/zero
    opex_per_mw_y1: float | None    # y1_total_opex / capacity_mw
    opex_per_mwh_y1: float | None   # y1_total_opex × 1000 / p50_annual_mwh

    is_user_project: bool


# ---------------------------------------------------------------------------
# Mutation contract
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AddOpexLineCommand:
    """
    Intent to add a custom sub-line under an existing OPEX group.

    Persistence is out of scope — this dataclass documents the mutation surface
    for future storage and validation layers.
    """
    project_code: str
    parent_group_code: str   # e.g. "B.06"
    name: str
    y1_keur: float
    inflation_pct: float = 0.0
    wht_flag: bool = False
    notes: str = ""


@dataclass(frozen=True)
class UpdateOpexLineCommand:
    """Intent to update an existing editable OPEX sub-line Y1 amount."""
    project_code: str
    line_code: str           # e.g. "B.06.01"
    new_y1_keur: float
    notes: str = ""


@dataclass(frozen=True)
class DeactivateOpexLineCommand:
    """
    Intent to deactivate a custom OPEX sub-line (excluded from totals).
    Only is_custom=True lines may be deactivated.
    """
    project_code: str
    line_code: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clamp_display_years(n: int) -> int:
    return max(1, min(n, MAX_DISPLAY_YEARS))


def _make_row_id(project_code: str, parent_code: str, line_code: str) -> str:
    """Deterministic, stable row identity — safe for HTML id attributes."""
    return f"{project_code}:{parent_code}:{line_code}"


def _get_year_values(
    child: dict,
    n_years: int,
) -> tuple[float, ...]:
    """
    Return display-year values for a child line.

    Prefers pre-computed yearly_values from the data source (correctly handles
    step schedules and conditional activation). Falls back to simple escalation.
    """
    source_values: list[float] | None = child.get("yearly_values")
    y1: float = float(child.get("budget_y1_keur") or 0.0)
    inflation: float = float(child.get("inflation_pct") or 0.0)

    if source_values and len(source_values) >= n_years:
        return tuple(float(v) for v in source_values[:n_years])

    return tuple(compute_year_values(y1, inflation, n_years))


def group_escalation_display(group: "OpexGroupVM") -> str:
    """F06 Correction A: authoritative escalation display for a group.

    The group row's escalation cell must reflect the escalation actually
    consumed by the group's effective lines.  When every line shares one
    rate, that rate is displayed; when injected/effective lines carry
    heterogeneous rates, the cell shows ``mixed`` so no single rate is
    presented as governing.  Context only — the frozen engine consumes
    each line's own escalation regardless of this label."""
    rates = {line.inflation_pct for line in group.lines}
    if len(rates) == 1:
        return f"{next(iter(rates)):.1f}%"
    return "mixed"


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def _build_custom_line_vm(
    sl: "OpexSubLine",
    project_code: str,
    display_years: int,
    is_user_project: bool,
) -> OpexLineVM:
    """Build an OpexLineVM from a user-added OpexSubLine."""
    year_values = tuple(
        compute_year_values(sl.amount_keur, sl.inflation_pct, display_years)
    )
    return OpexLineVM(
        row_id=_make_row_id(project_code, sl.parent_group_code, sl.business_code),
        code=sl.business_code,
        parent_code=sl.parent_group_code,
        name=sl.label,
        source=sl.source or "user",
        unit="kEUR",
        notes=sl.comments or "",
        display_order=sl.display_order,
        validation_status="ok",
        y1_keur=sl.amount_keur,
        inflation_pct=sl.inflation_pct,
        wht_flag=False,
        is_group=False,
        is_editable=is_user_project,
        is_read_only=not is_user_project,
        is_derived=False,
        is_contingency=False,
        is_fixed=True,
        is_variable=False,
        is_custom=True,
        is_active=sl.is_active,
        year_values=year_values,
        sub_line_id=sl.sub_line_id,
        row_version=sl.updated_at or "",
    )


def build_opex_view_model(
    project_ctx: "ProjectContext",
    is_user_project: bool = False,
    display_years: int = DEFAULT_DISPLAY_YEARS,
    sub_lines: Optional[Sequence["OpexSubLine"]] = None,
) -> OpexViewModel:
    """
    Build an OpexViewModel from ProjectContext.opex_detail_items.

    Args:
        project_ctx:     Populated ProjectContext (frozen dataclass).
        is_user_project: True iff the current session user owns this project.
        display_years:   How many year columns to render (default 30, max 30).
        sub_lines:       Active OpexSubLine records to inject as custom rows.
                         When provided, custom rows are merged into their
                         parent groups in display_order sequence. For groups
                         absent from opex_detail_items (e.g. B.09 "Fees" when
                         no fee lines were modelled in the template), a
                         synthetic OpexGroupVM is created so custom lines are
                         visible in the sheet and ViewModel totals.

    Returns:
        Fully populated OpexViewModel — all derived fields computed here.
    """
    display_years = _clamp_display_years(display_years)
    capacity_mw: float = project_ctx.capacity_mw
    p50_annual_mwh: float = project_ctx.operating_hours_p50 * capacity_mw
    contingency_rate: float = float(getattr(project_ctx, "opex_contingency_pct", 0.0))
    project_code: str = project_ctx.code

    # Index active custom sub-lines by parent group code for O(1) injection.
    active_custom: dict[str, list["OpexSubLine"]] = {}
    if sub_lines:
        for sl in sub_lines:
            if sl.is_active:
                active_custom.setdefault(sl.parent_group_code, []).append(sl)
        # Ensure sub-lists are sorted by display_order
        for grp_list in active_custom.values():
            grp_list.sort(key=lambda s: (s.display_order, s.business_code))

    groups: list[OpexGroupVM] = []
    seen_group_codes: set[str] = set()

    for cat in project_ctx.opex_detail_items:
        group_code: str = cat["code"]
        group_name: str = cat["name"]
        group_inflation: float = float(cat.get("inflation_pct") or 0.0)
        is_contingency_group: bool = cat.get("is_contingency", False)
        cat_contingency_pct: float = float(cat.get("contingency_pct") or 0.0)
        seen_group_codes.add(group_code)

        lines: list[OpexLineVM] = []
        for order, child in enumerate(cat.get("children", []), start=1):
            child_code: str = child["code"]
            y1_keur: float = float(child.get("budget_y1_keur") or 0.0)
            inflation_pct: float = float(child.get("inflation_pct") or group_inflation)
            wht_flag: bool = float(child.get("wth_rate") or 0.0) > 0

            is_derived = is_contingency_group
            is_read_only = is_derived or not is_user_project
            is_editable = is_user_project and not is_derived

            year_values = _get_year_values(child, display_years)

            lines.append(OpexLineVM(
                row_id=_make_row_id(project_code, group_code, child_code),
                code=child_code,
                parent_code=group_code,
                name=child["name"],
                source=child.get("source", "factory") or "factory",
                unit="kEUR",
                notes=child.get("notes", "") or "",
                display_order=order,
                validation_status="ok",
                y1_keur=y1_keur,
                inflation_pct=inflation_pct,
                wht_flag=wht_flag,
                is_group=False,
                is_editable=is_editable,
                is_read_only=is_read_only,
                is_derived=is_derived,
                is_contingency=is_contingency_group,
                is_fixed=True,
                is_variable=False,
                is_custom=False,
                is_active=True,
                year_values=year_values,
            ))

        # Inject custom sub-lines for this group (non-contingency only).
        if not is_contingency_group and group_code in active_custom:
            for sl in active_custom[group_code]:
                lines.append(_build_custom_line_vm(sl, project_code, display_years, is_user_project))
            # Re-sort: factory lines first (display_order from enumeration),
            # then custom lines (their own display_order), all by display_order ASC.
            lines.sort(key=lambda ln: (ln.display_order, ln.code))

        active_lines = [ln for ln in lines if ln.is_active]
        subtotal_per_year = tuple(
            sum(
                ln.year_values[yr]
                for ln in active_lines
                if not ln.is_contingency
            )
            for yr in range(display_years)
        )

        groups.append(OpexGroupVM(
            code=group_code,
            name=group_name,
            inflation_pct=group_inflation,
            is_contingency=is_contingency_group,
            contingency_pct=cat_contingency_pct if is_contingency_group else 0.0,
            lines=tuple(lines),
            subtotal_per_year=subtotal_per_year,
        ))

    # Create synthetic groups for custom sub-lines in groups absent from opex_detail_items
    # (e.g. B.09 "Fees" when the project template has no fee lines).
    if active_custom:
        from app.ui.opex_sheet_projection import CANONICAL_OPEX_GROUP_BY_CODE
        for group_code, sl_list in active_custom.items():
            if group_code in seen_group_codes:
                continue
            canonical = CANONICAL_OPEX_GROUP_BY_CODE.get(group_code)
            group_name = canonical.name if canonical else group_code
            custom_lines = [
                _build_custom_line_vm(sl, project_code, display_years, is_user_project)
                for sl in sl_list
            ]
            subtotal_per_year = tuple(
                sum(ln.year_values[yr] for ln in custom_lines if ln.is_active)
                for yr in range(display_years)
            )
            groups.append(OpexGroupVM(
                code=group_code,
                name=group_name,
                inflation_pct=0.0,
                is_contingency=False,
                contingency_pct=0.0,
                lines=tuple(custom_lines),
                subtotal_per_year=subtotal_per_year,
            ))

    # Aggregate per-year totals
    non_contingency_groups = [g for g in groups if not g.is_contingency]
    total_excl = tuple(
        sum(g.subtotal_per_year[yr] for g in non_contingency_groups)
        for yr in range(display_years)
    )
    contingency_by_year = tuple(
        total_excl[yr] * contingency_rate / 100.0
        for yr in range(display_years)
    )
    total_incl = tuple(
        total_excl[yr] + contingency_by_year[yr]
        for yr in range(display_years)
    )

    y1_total = total_incl[0] if total_incl else 0.0
    final_year_total = total_incl[-1] if total_incl else 0.0

    # KPIs — None when denominator is missing or zero
    opex_per_mw_y1: float | None = (
        y1_total / capacity_mw if capacity_mw > 0 else None
    )
    opex_per_mwh_y1: float | None = (
        y1_total * 1000.0 / p50_annual_mwh if p50_annual_mwh > 0 else None
    )

    return OpexViewModel(
        project_name=project_ctx.name,
        capacity_mw=capacity_mw,
        p50_annual_mwh=p50_annual_mwh,
        groups=tuple(groups),
        contingency_rate=contingency_rate,
        total_excl_contingency=total_excl,
        contingency_by_year=contingency_by_year,
        total_incl_contingency=total_incl,
        y1_total_opex=y1_total,
        final_year_total_opex=final_year_total,
        display_years=display_years,
        opex_per_mw_y1=opex_per_mw_y1,
        opex_per_mwh_y1=opex_per_mwh_y1,
        is_user_project=is_user_project,
    )
