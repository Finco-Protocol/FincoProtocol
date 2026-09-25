"""Read-only project context builders for UI binding.

Reads from factory defaults or generic project factories.
Does NOT run model calculations.
Does NOT persist anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from app.domain.capex.source_model import CapexScope, C16_CHILD_TREATMENTS
from app.project_factories import (
    create_generic_solar_reference,
    create_default_solar_project,
    create_generic_data_center_reference,
    create_default_data_center_project,
    create_generic_wind_reference,
    create_default_wind_project,
)
from domain.opex.templates import build_generic_solar_reference_opex_template, build_generic_wind_reference_opex_template
from app.reference_detail_catalog import (
    PUBLIC_GENERIC_DETAIL_V1,
    OPEX_PARENT_BY_CANONICAL_KEY,
    OPEX_PARENT_NAMES,
    allocate_parent_amount,
    capex_children,
    opex_children,
)


MISSING = "MISSING"
NOT_AVAILABLE = "NOT_AVAILABLE"


# ---------------------------------------------------------------------------
# Phase PR2 — Realized gearing KPI helper
# ---------------------------------------------------------------------------

def _compute_realized_gearing_pct(
    senior_debt_keur: float | None,
    total_capex_keur: float | None,
    runtime_senior_debt_keur: float | None = None,
) -> float | None:
    """Compute realized gearing as senior_debt / total_capex * 100.

    Returns ``None`` when:
    - the resolved senior_debt is None or negative
    - ``total_capex_keur`` is None, zero, or negative

    Returns a float in [0, 100] (i.e. percentage) otherwise.

    This is a **read-only derived KPI** for the Scenario Matrix
    (Phase PR2). It does NOT change debt sizing semantics,
    DSCR sculpting, financial formulas, factory paths,
    or the indicative gearing_pct input. It is computed at
    snapshot build time from values that the runtime has
    already produced.

    P1-UX-FIX-1: When ``runtime_senior_debt_keur`` is provided
    AND ``senior_debt_keur`` (input-driven) is None or zero,
    the function falls back to the runtime value. This fixes
    the Generic Solar/Wind case where
    ``financing.fixed_debt_keur=0`` and the DSCR-sculpted
    senior debt amount is the authoritative value. For Generic Wind Reference
    and Generic Solar Reference the two values are bit-identical (input
    overrides runtime) so behaviour is unchanged.

    Locked by tests:
    - test_phase_pr2_realized_gearing.py
      ::TestRealizedGearingComputation
    - test_phase_p1_ux_fix_1_pilot_polish.py
      ::TestRealizedGearingForGeneric
    """
    if total_capex_keur is None or total_capex_keur <= 0:
        return None
    # Resolve senior_debt: prefer input; fall back to runtime if input is
    # None or zero. Negative values are still rejected.
    resolved_senior_debt = senior_debt_keur
    if resolved_senior_debt is None or resolved_senior_debt == 0:
        resolved_senior_debt = runtime_senior_debt_keur
    if resolved_senior_debt is None or resolved_senior_debt <= 0:
        return None
    return (resolved_senior_debt / total_capex_keur) * 100.0


@dataclass(frozen=True)
class ProjectContext:
    """Read-only UI context for one project."""

    code: str
    name: str
    company: str
    country_iso: str
    technology: str
    capacity_mw: float
    cod_date: str
    financial_close: str
    construction_months: int
    horizon_years: int
    period_frequency: str
    yield_scenario: str
    operating_hours_p50: float
    plant_availability: float
    grid_availability: float
    pv_degradation: float | None
    ppa_tariff_eur_mwh: float
    ppa_term_years: int
    ppa_index_pct: float
    co2_enabled: bool
    co2_price_eur_mwh: float | None
    revenue_items: tuple[dict[str, Any], ...] = field(default_factory=lambda: ())
    opex_items: tuple[dict[str, Any], ...] = field(default_factory=lambda: ())
    opex_detail_items: tuple[dict[str, Any], ...] = field(default_factory=lambda: ())  # hierarchical for detail OPEX tab
    opex_y1_total_keur: float = 0.0
    opex_contingency_method: str = ""
    opex_contingency_pct: float = 0.0
    total_capex_keur: float = 0.0
    epc_contract_keur: float = 0.0
    idc_keur: float = 0.0
    bank_fees_keur: float = 0.0
    capex_items: tuple[dict[str, Any], ...] = field(default_factory=lambda: ())
    capex_detail_items: tuple[dict[str, Any], ...] = field(default_factory=lambda: ())  # hierarchical for detail CAPEX tab
    capex_construction_months: int = 0
    capex_y1_total_keur: float = 0.0
    senior_debt_keur: float = 0.0
    interest_rate_pct: float = 0.0
    senior_base_rate_pct: float = 0.0   # base rate component (e.g. Euribor)
    senior_margin_bps: int = 0          # credit margin in bps (all-in = base + margin/10000)
    senior_tenor_years: int = 0
    target_dscr: float = 0.0
    lockup_dscr: float = 0.0            # cash lock-up DSCR threshold
    dsra_months: int = 0                # DSRA reserve months of debt service
    gearing_pct: float | None = None
    # Phase PR2 — read-only derived output.
    # realized_gearing_pct = senior_debt / total_capex * 100
    # (computed at snapshot build time, not bound
    # to the indicative gearing input). This is a
    # read-only derived KPI for the Scenario Matrix;
    # no financial formula / sizing logic is
    # changed by PR2.
    realized_gearing_pct: float | None = None
    shl_amount_keur: float = 0.0
    shl_rate_pct: float = 0.0
    shl_idc_keur: float = 0.0
    construction_items: tuple[dict[str, Any], ...] = field(default_factory=lambda: ())
    idc_items: tuple[dict[str, Any], ...] = field(default_factory=lambda: ())
    cit_rate_pct: float = 0.0
    loss_carryforward_years: int = 0
    g20_status: str = ""
    r99_r102_status: str = ""
    parity_status: str = ""
    data_source: str = ""
    missing_fields: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return self.code.lower()


def _slugify_code(name: str) -> str:
    """Create a URL-safe code from an item name."""
    import re
    # Lowercase, replace spaces/slashes with underscores, keep alphanumerics
    slug = re.sub(r'[^a-z0-9]+', '_', name.lower())
    slug = slug.strip('_')
    return slug or "item"


def _infer_opex_group(name: str) -> str:
    """Infer OPEX group from item name patterns (best-effort for display)."""
    n = name.lower()
    # EV Charging (V1) canonical names first: "Security / HSE" must land on
    # B.05 (the generic "security" pattern predates EV and points at B.01),
    # and the derived electricity / payment lines must not fall to "Other".
    if "site security" in n or n.startswith("security") or "hse" in n:
        return "Security"
    if "electricity" in n:
        return "Power Expenses"
    if "payment" in n or n.startswith("bank fee"):
        return "Bank Fees"
    if any(k in n for k in ["technical", "o&m", "maintain", "clean", "security", "operational"]):
        return "Technical Management"
    if any(k in n for k in ["insurance", "insur"]):
        return "Insurance"
    if any(k in n for k in ["lease", "land", "property", "rent"]):
        return "Lease & Property Tax"
    if any(k in n for k in ["power", "balancing", "grid", "transmission"]):
        return "Power Expenses"
    if any(k in n for k in ["audit", "accounting", "legal", "bank fee", "admin", "management fee"]):
        return "Audit&Accounting&Legal"
    if any(k in n for k in ["environmental", "social", "e&s", "hse"]):
        return "Environmental&Social"
    if "contingen" in n:
        return "Contingencies"
    if any(k in n for k in ["infrastructure", "maintenance"]):
        return "Infrastructure Maintenance"
    return "Other Operating Costs"



def _build_construction_items(project_inputs) -> tuple[dict[str, Any], ...]:
    """Build serialisable construction schedule items from runtime construction engine.

    Uses build_runtime_construction_schedule() for Generic Wind Reference/Generic Solar Reference.
    Returns monthly drawdown rows + funding source summary rows.
    Marked audit_only=True since monthly grid is not yet runtime-authoritative.
    """
    try:
        from domain.construction.runtime_adapter import build_runtime_construction_schedule
        result = build_runtime_construction_schedule(project_inputs)
    except Exception:
        return ()

    rows = []

    # ── Monthly Schedule Rows ────────────────────────────────────────────
    for entry in result.monthly_entries:
        rows.append({
            "type": "monthly",
            "month_index": entry.month_index,
            "label": f"Month {entry.month_index}",
            "unit": "kEUR",
            "equity_draw_keur": entry.equity_draw_keur,
            "shl_draw_keur": entry.shl_draw_keur,
            "junior_draw_keur": entry.junior_draw_keur,
            "senior_draw_keur": entry.senior_draw_keur,
            "senior_idc_keur": entry.senior_idc_keur,
            "cumulative_senior_idc_keur": entry.cumulative_senior_idc_keur,
            "total_draw_keur": entry.equity_draw_keur + entry.shl_draw_keur
                            + entry.junior_draw_keur + entry.senior_draw_keur,
            "cumulative_uses_keur": entry.cumulative_uses_keur,
            "audit_only": True,
        })

    # ── Funding Summary Rows ────────────────────────────────────────────
    rows.append({
        "type": "summary",
        "label": "Total Equity Draw",
        "unit": "kEUR",
        "value": result.equity_draw_keur,
        "audit_only": False,
    })
    rows.append({
        "type": "summary",
        "label": "Total SHL Principal Draw",
        "unit": "kEUR",
        "value": result.shl_principal_draw_keur,
        "audit_only": False,
    })
    rows.append({
        "type": "summary",
        "label": "Total Senior Principal Draw",
        "unit": "kEUR",
        "value": result.senior_principal_draw_keur,
        "audit_only": False,
    })
    rows.append({
        "type": "summary",
        "label": "Total Junior Draw",
        "unit": "kEUR",
        "value": result.junior_draw_keur,
        "audit_only": False,
    })
    rows.append({
        "type": "summary",
        "label": "Total Uses (CAPEX)",
        "unit": "kEUR",
        "value": result.total_uses_keur,
        "audit_only": False,
    })

    return tuple(rows)


def _build_idc_items(project_inputs) -> tuple[dict[str, Any], ...]:
    """Build serialisable IDC summary items from runtime construction engine.

    Uses build_runtime_construction_schedule() for Generic Wind Reference/Generic Solar Reference.
    Returns IDC summary rows + COD opening balances.
    """
    try:
        from domain.construction.runtime_adapter import build_runtime_construction_schedule
        result = build_runtime_construction_schedule(project_inputs)
    except Exception:
        return ()

    rows = []

    # ── Senior Debt IDC ────────────────────────────────────────────────
    rows.append({
        "code": "senior_principal_draw",
        "name": "Senior Debt Principal Draw",
        "value": result.senior_principal_draw_keur,
        "unit": "kEUR",
        "group": "Senior Debt",
        "editable": False,
        "hint": "Runtime computed",
    })
    rows.append({
        "code": "senior_idc",
        "name": "Senior Debt IDC",
        "value": result.senior_idc_keur,
        "unit": "kEUR",
        "group": "Senior Debt",
        "editable": False,
        "hint": "Runtime computed",
    })
    rows.append({
        "code": "opening_senior_balance",
        "name": "Opening Senior Balance (COD)",
        "value": result.opening_senior_balance_keur,
        "unit": "kEUR",
        "group": "Senior Debt",
        "editable": False,
        "hint": "Runtime computed — senior_idc_capitalized applied",
    })

    # ── SHL IDC ────────────────────────────────────────────────────────
    rows.append({
        "code": "shl_principal_draw",
        "name": "SHL Principal Draw",
        "value": result.shl_principal_draw_keur,
        "unit": "kEUR",
        "group": "SHL",
        "editable": False,
        "hint": "Runtime computed",
    })
    rows.append({
        "code": "shl_idc",
        "name": "SHL IDC",
        "value": result.shl_idc_keur,
        "unit": "kEUR",
        "group": "SHL",
        "editable": False,
        "hint": "Runtime computed",
    })
    rows.append({
        "code": "opening_shl_balance",
        "name": "Opening SHL Balance (COD)",
        "value": result.opening_shl_balance_keur,
        "unit": "kEUR",
        "group": "SHL",
        "editable": False,
        "hint": "Runtime computed — shl_idc_capitalized applied",
    })

    # ── IDC Totals ─────────────────────────────────────────────────────
    rows.append({
        "code": "total_idc",
        "name": "Total IDC",
        "value": result.shl_idc_keur + result.senior_idc_keur,
        "unit": "kEUR",
        "group": "IDC Summary",
        "editable": False,
        "hint": "SHL IDC + Senior IDC",
    })
    rows.append({
        "code": "opening_senior_excl_idc",
        "name": "Opening Senior Excl. IDC",
        "value": result.opening_senior_balance_keur - result.senior_idc_keur,
        "unit": "kEUR",
        "group": "IDC Summary",
        "editable": False,
        "hint": "Computed from runtime",
    })

    # ── Monthly IDC entries ────────────────────────────────────────────
    for entry in result.monthly_entries:
        rows.append({
            "type": "monthly_idc",
            "month_index": entry.month_index,
            "label": f"Month {entry.month_index}",
            "unit": "kEUR",
            "senior_idc_keur": entry.senior_idc_keur,
            "cumulative_senior_idc_keur": entry.cumulative_senior_idc_keur,
            "audit_only": True,
        })

    return tuple(rows)


def _build_opex_items(project_inputs, horizon_years: int = 25) -> tuple[dict[str, Any], ...]:
    items = []
    for item in project_inputs.opex:
        code = _slugify_code(item.name)
        items.append(
            {
                "code": code,
                "name": item.name,
                "y1_keur": item.y1_amount_keur,
                "inflation_pct": item.annual_inflation,
                "group": _infer_opex_group(item.name),
                "unit": "kEUR",
                "fixed_variable": "Fixed",
                "recurring_oneoff": "Recurring",
                "escalation_pct": round(item.annual_inflation * 100, 1) if item.annual_inflation else 0.0,
                "start_year": 1,
                "end_year": horizon_years,
                "notes": "",
            }
        )
    return tuple(items)


# ── Group metadata for OPEX detail mapping ──────────────────────────────────────
_OPEX_GROUP_META = {
    # Maps group name → (code, display_order)
    "Technical Management":       ("B.01", 1),
    "Infrastructure Maintenance": ("B.02", 2),
    "Maintain Site":              ("B.03", 3),
    "Clean Material":             ("B.04", 4),
    "Security":                   ("B.05", 5),
    "Insurance":                  ("B.06", 6),
    "Lease & Property Tax":       ("B.07", 7),
    "Power Expenses":             ("B.08", 8),
    "Fees":                       ("B.09", 9),
    "Audit&Accounting&Legal":      ("B.10", 10),
    "Bank Fees":                  ("B.11", 11),
    "Environmental&Social":       ("B.12", 12),
    "Contingencies":              ("B.13", 13),
}


def _build_opex_detail_items(
    project_inputs,
    code: str,
    horizon_years: int = 25,
) -> dict[str, Any]:
    """Build hierarchical OPEX detail structure for the spreadsheet-like OPEX grid.

    For Generic Solar Reference and Generic Wind Reference: uses the detailed domain.opex.templates structures.
    For other projects: falls back to flat aggregated items from project_inputs.opex.

    Adds computed yearly display values for each child and category total.
    The contingency (B.13) yearly total = contingency_pct × sum(non-contingency totals).

    Returns:
        {
          "categories": [
            {
              "code": "B.01",
              "name": "Technical Management",
              "inflation_pct": 2.0,
              "wth_rate": 0.0,
              "source": "factory",
              "is_contingency": False,
              "contingency_pct": 0.0,
              "yearly_totals": [198.0, 198.0, 201.96, ...],
              "children": [
                {
                  "code": "B.01.01",
                  "name": "Asset Management Contract",
                  "budget_y1_keur": 60.0,
                  "inflation_pct": 2.0,
                  "wth_rate": 0.0,
                  "source": "factory",
                  "notes": "",
                  "yearly_values": [60.0, 61.2, 62.424, ...],
                  "active_flags": [1, 1, 1, ...],
                },
              ],
            },
          ],
        }
    """
    # Generic Solar/Wind references use the single public-generic catalogue.
    # Its weights only decompose the canonical parent items supplied here; it
    # never supplies an economic amount or an escalation assumption.
    is_reference = code.upper() in {"GENERIC_SOLAR_REFERENCE", "GENERIC WIND REFERENCE", "REF-WIND-B"}
    if is_reference:
        reference_technology = "solar" if code.upper() == "GENERIC_SOLAR_REFERENCE" else "wind"
        canonical = {str(item.name): item for item in project_inputs.opex}
        categories = []
        for group_code, group_name in OPEX_PARENT_NAMES.items():
            parent_item = next(
                (canonical[key] for key, parent in OPEX_PARENT_BY_CANONICAL_KEY.items()
                 if parent == group_code and key in canonical),
                None,
            )
            parent_amount = float(getattr(parent_item, "y1_amount_keur", 0.0) or 0.0)
            inflation = float(getattr(parent_item, "annual_inflation", 0.0) or 0.0)
            is_contingency = group_code == "B.13"
            children = []
            for child, amount in allocate_parent_amount(parent_amount, opex_children(group_code, reference_technology)):
                yearly_values = [round(amount * ((1 + inflation) ** (year - 1)), 4) for year in range(1, horizon_years + 1)]
                children.append({
                    "code": child.code, "name": child.label, "budget_y1_keur": amount,
                    "inflation_pct": inflation * 100, "wth_rate": 0.0,
                    "source": "public_generic_detail", "notes": PUBLIC_GENERIC_DETAIL_V1,
                    "yearly_values": yearly_values, "active_flags": [1] * horizon_years,
                    "canonical_parent_reference": getattr(parent_item, "name", None),
                    "detail_catalog_authority": PUBLIC_GENERIC_DETAIL_V1,
                    "allocation_weight": float(child.weight),
                })
            categories.append({
                "code": group_code, "name": group_name, "inflation_pct": inflation * 100,
                "wth_rate": 0.0, "source": "public_generic_detail",
                "is_contingency": is_contingency,
                "contingency_pct": 0.0 if is_contingency else 0.0,
                "children": children,
                "yearly_totals": [round(sum(c["yearly_values"][i] for c in children), 4) for i in range(horizon_years)],
            })
        return {"categories": tuple(categories)}

    # Try to use detailed templates for known legacy display-only contexts.
    if code.upper() in ("GENERIC_SOLAR_REFERENCE",):
        template_groups = build_generic_solar_reference_opex_template()
    elif code.upper() in ("Generic Wind Reference", "REF-WIND-B"):
        template_groups = build_generic_wind_reference_opex_template()
    else:
        template_groups = None

    if template_groups is not None:
        categories = []
        for group in template_groups:
            is_contingency = (
                group.contingency_pct > 0
                and group.contingency_method.name == "PERCENTAGE_OF_OPEX"
            )

            cat = {
                "code": group.code,
                "name": group.name,
                "inflation_pct": group.inflation_rate * 100 if group.inflation_rate else 0.0,
                "wth_rate": group.wth_rate or 0.0,
                "source": "factory",
                "is_contingency": is_contingency,
                "contingency_pct": group.contingency_pct,
                "children": [],
                "yearly_totals": [],
            }

            for item in group.items:
                is_item_contingency = (
                    item.selected_group_codes
                    and all(
                        g.startswith("B.") and g != group.code
                        for g in item.selected_group_codes
                    )
                )

                if is_item_contingency:
                    formula_note = f"{group.contingency_pct}% x non-contingency OPEX"
                    budget_display = 0.0
                else:
                    formula_note = ""
                    budget_display = item.budget_keur

                # Compute yearly values: effective_budget × inflation^(y-1) × active_flag
                inflation_rate = item.inflation_rate or 0.0
                yearly_values = []
                active_flags = []
                for y in range(1, horizon_years + 1):
                    active = item.is_active(y)
                    active_flags.append(1 if active else 0)
                    if not active:
                        yearly_values.append(0.0)
                    else:
                        eff = item.effective_budget(y)
                        inflated = eff * ((1 + inflation_rate) ** (y - 1))
                        yearly_values.append(round(inflated, 4))

                child = {
                    "code": item.code,
                    "name": item.name,
                    "budget_y1_keur": budget_display,
                    "inflation_pct": inflation_rate * 100 if inflation_rate else 0.0,
                    "wth_rate": item.wth_rate or 0.0,
                    "source": "factory",
                    "notes": formula_note,
                    "yearly_values": yearly_values,
                    "active_flags": active_flags,
                }
                cat["children"].append(child)

            categories.append(cat)

        # ── Second pass: compute category yearly_totals ─────────────────────
        # Non-contingency categories: sum of children
        for cat in categories:
            if cat["is_contingency"]:
                continue
            totals = [0.0] * horizon_years
            for child in cat["children"]:
                for y_idx, y_val in enumerate(child["yearly_values"]):
                    totals[y_idx] += y_val
            cat["yearly_totals"] = [round(t, 4) for t in totals]

        # Contingency categories: contingency_pct × sum(non-contingency totals)
        for cat in categories:
            if not cat["is_contingency"]:
                continue
            contingency_pct = cat.get("contingency_pct", 0.0) / 100.0
            non_contingency_totals = [
                sum(
                    c["yearly_totals"][y_idx]
                    for c in categories
                    if not c["is_contingency"]
                )
                for y_idx in range(horizon_years)
            ]
            cat["yearly_totals"] = [
                round(contingency_pct * nc_total, 4)
                for nc_total in non_contingency_totals
            ]

        return {"categories": tuple(categories)}

    # Fallback: build flat structure from project_inputs.opex
    categories = []
    for item in project_inputs.opex:
        group_name = _infer_opex_group(item.name)
        code_slug = _slugify_code(item.name)
        is_contingency = item.percentage_of_opex > 0

        if is_contingency:
            budget_display = 0.0
            formula_note = f"{int(item.percentage_of_opex * 100)}% x non-contingency OPEX"
        else:
            budget_display = item.y1_amount_keur
            formula_note = ""

        inflation_rate = item.annual_inflation or 0.0
        yearly_values = []
        active_flags = []
        for y in range(1, horizon_years + 1):
            active_flags.append(1)
            inflated = budget_display * ((1 + inflation_rate) ** (y - 1))
            yearly_values.append(round(inflated, 4))

        child_item = {
            "code": code_slug,
            "name": item.name,
            "budget_y1_keur": budget_display,
            "inflation_pct": item.annual_inflation * 100 if item.annual_inflation else 0.0,
            "wth_rate": 0.0,
            "source": "factory",
            "notes": formula_note,
            "yearly_values": yearly_values,
            "active_flags": active_flags,
        }

        cat_code = _OPEX_GROUP_META.get(group_name, ("", 99))[0]
        cat_meta = next((c for c in categories if c["code"] == cat_code), None)
        if cat_meta is None:
            cat_meta = {
                "code": cat_code,
                "name": group_name,
                "inflation_pct": item.annual_inflation * 100 if item.annual_inflation else 0.0,
                "wth_rate": 0.0,
                "source": "factory",
                "is_contingency": is_contingency,
                "contingency_pct": 0.0,
                "children": [],
                "yearly_totals": [],
            }
            categories.append(cat_meta)

        cat_meta["children"].append(child_item)

    def _sort_key(c):
        return _OPEX_GROUP_META.get(c["name"], ("", 99))[1]

    categories.sort(key=_sort_key)

    # Compute yearly_totals for fallback categories
    for cat in categories:
        if cat["is_contingency"]:
            continue
        totals = [0.0] * horizon_years
        for child in cat["children"]:
            for y_idx, y_val in enumerate(child["yearly_values"]):
                totals[y_idx] += y_val
        cat["yearly_totals"] = [round(t, 4) for t in totals]

    # Handle contingency for fallback (if any)
    for cat in categories:
        if not cat["is_contingency"]:
            continue
        contingency_pct = cat.get("contingency_pct", 0.0) / 100.0
        non_contingency_totals = [
            sum(
                c["yearly_totals"][y_idx]
                for c in categories
                if not c["is_contingency"]
            )
            for y_idx in range(horizon_years)
        ]
        cat["yearly_totals"] = [
            round(contingency_pct * nc_total, 4)
            for nc_total in non_contingency_totals
        ]

    return {"categories": tuple(categories)}



def _build_revenue_items(revenue, technical, technology: str) -> tuple[dict[str, Any], ...]:
    """Build serialisable revenue item list from RevenueParams + TechnicalParams."""
    items = []

    # ── Production ────────────────────────────────────────────────────────
    items.append({
        "code": "capacity_mw",
        "name": "Installed Capacity",
        "value": technical.capacity_mw,
        "unit": "MW",
        "group": "Production",
        "editable": False,
        "hint": "Set via inputs tab",
    })
    items.append({
        "code": "operating_hours_p50",
        "name": "P50 Hours / Year",
        "value": technical.operating_hours_p50,
        "unit": "h/yr",
        "group": "Production",
        "editable": False,
        "hint": "Set via inputs tab",
    })
    items.append({
        "code": "plant_availability",
        "name": "Plant Availability",
        "value": technical.plant_availability,
        "unit": "%",
        "group": "Production",
        "editable": False,
        "hint": "Set via inputs tab",
    })
    items.append({
        "code": "grid_availability",
        "name": "Grid Availability",
        "value": technical.grid_availability,
        "unit": "%",
        "group": "Production",
        "editable": False,
        "hint": "Set via inputs tab",
    })
    if technology != "Wind":
        items.append({
            "code": "pv_degradation",
            "name": "PV Degradation",
            "value": technical.pv_degradation,
            "unit": "%/yr",
            "group": "Production",
            "editable": False,
            "hint": "Set via inputs tab",
        })

    # ── PPA / Tariff ────────────────────────────────────────────────────
    items.append({
        "code": "ppa_base_tariff",
        "name": "Base Tariff (PPA)",
        "value": revenue.ppa_base_tariff,
        "unit": "EUR/MWh",
        "group": "PPA / Tariff",
        "editable": True,
        "hint": "",
    })
    items.append({
        "code": "ppa_index",
        "name": "Tariff Escalation",
        "value": revenue.ppa_index,
        "unit": "%/yr",
        "group": "PPA / Tariff",
        "editable": False,
        "hint": "Set via inputs tab",
    })
    items.append({
        "code": "ppa_term_years",
        "name": "PPA Term",
        "value": int(revenue.ppa_term_years),
        "unit": "years",
        "group": "PPA / Tariff",
        "editable": False,
        "hint": "Set via inputs tab",
    })
    items.append({
        "code": "ppa_production_share",
        "name": "PPA Production Share",
        "value": getattr(revenue, "ppa_production_share", 1.0),
        "unit": "%",
        "group": "PPA / Tariff",
        "editable": False,
        "hint": "Set via inputs tab",
    })

    # ── Market / Merchant ───────────────────────────────────────────────
    balancing = getattr(revenue, "balancing_cost_eur_per_mwh", 0.0) or 0.0
    items.append({
        "code": "balancing_cost",
        "name": "Balancing Cost",
        "value": balancing,
        "unit": "EUR/MWh",
        "group": "Market / Merchant",
        "editable": False,
        "hint": "Set via inputs tab",
    })
    first_merchant = getattr(revenue, "first_merchant_operating_period_index", None)
    items.append({
        "code": "first_merchant_period",
        "name": "First Merchant Period",
        "value": first_merchant if first_merchant is not None else -1,
        "unit": "period index",
        "group": "Market / Merchant",
        "editable": False,
        "hint": "Set via inputs tab",
    })

    # ── CO2 / Certificates ─────────────────────────────────────────────
    items.append({
        "code": "co2_enabled",
        "name": "CO2 Certificates Enabled",
        "value": 1.0 if revenue.co2_enabled else 0.0,
        "unit": "flag",
        "group": "CO2 / Certificates",
        "editable": False,
        "hint": "Set via inputs tab",
    })
    co2_price = (
        getattr(revenue, "co2_certificate_price_eur_per_mwh", None)
        or getattr(revenue, "co2_price_eur", None)
        or 0.0
    )
    items.append({
        "code": "co2_price",
        "name": "CO2 Price (Y1)",
        "value": co2_price,
        "unit": "EUR/MWh",
        "group": "CO2 / Certificates",
        "editable": False,
        "hint": "Set via inputs tab",
    })

    return tuple(items)


def _capex_y1_total(capex) -> float:
    """Sum of all non-zero hard-capex items (excludes financing rows)."""
    total = 0.0
    for field in capex._CAPEX_ITEM_FIELDS:
        item = getattr(capex, field)
        total += item.amount_keur
    return total


def _build_capex_detail_items(
    capex,
    construction_months: int = 12,
    technology: str = "solar",
) -> dict[str, Any]:
    """Build a jurisdiction-neutral CAPEX detail projection.

    The corporate/public repository deliberately does not ship historical
    spreadsheet line-item evidence.  This view is derived only from the
    canonical ``CapexStructure`` currently supplied to the engine.

    It therefore exposes synthetic/reference inputs and backend-derived
    financing costs without any source-workbook names, cell addresses,
    calibration anchors, or client-specific line items.
    """
    from app.persistence.capex_sub_lines import CAPEX_CATEGORY_TO_FIELD

    category_names = {
        "C.01": "Production Units",
        "C.02": "EPC Contract",
        "C.03": "Grid Connection",
        "C.04": "Operations Preparation",
        "C.05": "Other EPC Costs",
        "C.06": "Construction Insurances",
        "C.07": "Lease / Construction Taxes",
        "C.08": "Audit & Legal",
        "C.09": "Construction Management A",
        "C.10": "Commissioning",
        "C.11": "Other Professional Services",
        "C.12": "Construction Management B",
        "C.13": "Contingency",
        "C.14": "Construction Taxes",
        "C.15": "Project Acquisition / Development",
        "C.16": "Project Rights",
        "C.17": "Financing Costs",
        "C.18": "Reserve Accounts",
    }

    def _blank_schedule() -> tuple[float, ...]:
        return tuple(0.0 for _ in range(max(18, construction_months)))

    def _child(
        *,
        code: str,
        name: str,
        amount: float,
        source_type: str,
        backend: bool = False,
        runtime_source_field: str | None = None,
        comments: str = "",
    ) -> dict[str, Any]:
        status = "backend_authoritative" if backend else "app_mapped"
        return {
            "code": code,
            "name": name,
            "amount_keur": float(amount or 0.0),
            "app_amount_keur": float(amount or 0.0),
            "delta_keur": 0.0,
            "per_mw": None,
            "contingency_pct": None,
            "vat_rate_pct": None,
            "wth_rate_pct": None,
            "depreciable": not backend,
            "monthly_schedule": _blank_schedule(),
            "comments": comments,
            "mapping_note": "Canonical FINCO Model projection",
            "mapping_status": "backend_calculated" if backend else "mapped",
            "authority_status": status,
            "source_type": source_type,
            "scope": "canonical_model",
            "runtime_source_field": runtime_source_field,
            "affects_runtime": True,
            "runtime_impact": "Drives model" if not backend else "Derived by engine",
            "is_backend_calculated": backend,
        }

    categories: list[dict[str, Any]] = []
    top_counts = {
        "backend_authoritative": 0,
        "app_mapped": 0,
        "excel_reference_only": 0,
        "missing_runtime_source": 0,
        "mismatch": 0,
        "deferred": 0,
        "not_applicable": 0,
        "scope_mismatch": 0,
    }

    # C.01-C.16 are a stable UI taxonomy mapped to canonical CapexStructure fields.
    # C.11 is an alias of audit_legal and intentionally carries zero base amount;
    # custom user rows may still be attached to that category in working copies.
    seen_fields: set[str] = set()
    for code, field_name in CAPEX_CATEGORY_TO_FIELD.items():
        item = getattr(capex, field_name)
        is_alias = field_name in seen_fields
        seen_fields.add(field_name)
        amount = 0.0 if is_alias else float(getattr(item, "amount_keur", 0.0) or 0.0)
        children = tuple(
            _child(
                code=detail.code,
                name=detail.label,
                amount=detail_amount,
                source_type="public_generic_detail",
                runtime_source_field=field_name,
                comments=PUBLIC_GENERIC_DETAIL_V1,
            ) | {
                "detail_catalog_authority": PUBLIC_GENERIC_DETAIL_V1,
                "allocation_weight": float(detail.weight),
                "canonical_parent_reference": field_name,
            }
            for detail, detail_amount in allocate_parent_amount(
                amount,
                capex_children(
                    "ev_charging" if technology == "EV Charging"
                    else ("wind" if technology.lower().startswith("wind") else "solar"),
                    code,
                ),
            )
        )
        summary = dict(top_counts)
        summary["app_mapped"] = len(children)
        categories.append({
            "code": code,
            "name": category_names[code],
            "is_backend_calculated": False,
            "comments": PUBLIC_GENERIC_DETAIL_V1,
            "children": children,
            "authority_summary": summary,
            "app_group_amount_keur": amount,
            "is_alias_group": is_alias,
        })
        top_counts["app_mapped"] += 1

    financing_children = (
        _child(code="C.17.01", name="Interest During Construction", amount=getattr(capex, "idc_keur", 0.0), source_type="computed_runtime", backend=True, runtime_source_field="idc_keur"),
        _child(code="C.17.02", name="Commitment Fees", amount=getattr(capex, "commitment_fees_keur", 0.0), source_type="computed_runtime", backend=True, runtime_source_field="commitment_fees_keur"),
        _child(code="C.17.03", name="Bank / Arrangement Fees", amount=getattr(capex, "bank_fees_keur", 0.0), source_type="computed_runtime", backend=True, runtime_source_field="bank_fees_keur"),
        _child(code="C.17.04", name="Other Financing Costs", amount=getattr(capex, "other_financial_keur", 0.0), source_type="computed_runtime", backend=True, runtime_source_field="other_financial_keur"),
        _child(code="C.17.05", name="VAT Facility Financing Costs", amount=getattr(capex, "vat_costs_keur", 0.0), source_type="computed_runtime", backend=True, runtime_source_field="vat_costs_keur"),
    )
    financing_summary = dict(top_counts)
    financing_summary = {k: 0 for k in top_counts}
    financing_summary["backend_authoritative"] = len(financing_children)
    categories.append({
        "code": "C.17",
        "name": category_names["C.17"],
        "is_backend_calculated": True,
        "comments": "Backend-derived financing costs",
        "children": financing_children,
        "authority_summary": financing_summary,
        "app_group_amount_keur": sum(c["app_amount_keur"] for c in financing_children),
        "is_alias_group": False,
    })
    top_counts["backend_authoritative"] += len(financing_children)

    reserve_child = _child(
        code="C.18.01",
        name="Reserve Accounts",
        amount=getattr(capex, "reserve_accounts_keur", 0.0),
        source_type="computed_runtime",
        backend=True,
        runtime_source_field="reserve_accounts_keur",
    )
    reserve_summary = {k: 0 for k in top_counts}
    reserve_summary["backend_authoritative"] = 1
    categories.append({
        "code": "C.18",
        "name": category_names["C.18"],
        "is_backend_calculated": True,
        "comments": "Backend-derived reserve requirement",
        "children": (reserve_child,),
        "authority_summary": reserve_summary,
        "app_group_amount_keur": reserve_child["app_amount_keur"],
        "is_alias_group": False,
    })
    top_counts["backend_authoritative"] += 1

    hard_total = sum(float(cat.get("app_group_amount_keur") or 0.0) for cat in categories if cat["code"] not in {"C.17", "C.18"})
    financing_total = float(categories[-2]["app_group_amount_keur"] or 0.0)
    reserve_total = float(categories[-1]["app_group_amount_keur"] or 0.0)
    top_summary = dict(top_counts)
    top_summary["_total_child_rows"] = sum(len(cat["children"]) for cat in categories)

    return {
        "categories": tuple(categories),
        "grand_total_keur": round(hard_total + financing_total + reserve_total, 2),
        "hard_capex_total_keur": round(hard_total, 2),
        "financing_total_keur": round(financing_total + reserve_total, 2),
        "construction_months": construction_months,
        "authority_summary": top_summary,
    }

def _build_capex_items(capex) -> tuple[dict[str, Any], ...]:
    """"Build serialisable CAPEX item list from CapexStructure."""
    items = []
    for field in capex._CAPEX_ITEM_FIELDS:
        item = getattr(capex, field)
        items.append(
            {
                "code": field,
                "name": item.name,
                "amount_keur": item.amount_keur,
                "y0_share": item.y0_share,
            }
        )
    # Financing/legal
    items.append({"code": "idc", "name": "IDC", "amount_keur": capex.idc_keur, "y0_share": 0.0})
    items.append({"code": "bank_fees", "name": "Bank Fees", "amount_keur": capex.bank_fees_keur, "y0_share": 0.0})
    items.append({"code": "commitment_fees", "name": "Commitment Fees", "amount_keur": capex.commitment_fees_keur, "y0_share": 0.0})
    items.append({"code": "other_financial", "name": "Other Financial", "amount_keur": capex.other_financial_keur, "y0_share": 0.0})
    items.append({"code": "vat_costs", "name": "VAT Costs", "amount_keur": capex.vat_costs_keur, "y0_share": 0.0})
    items.append({"code": "reserve_accounts", "name": "Reserve Accounts", "amount_keur": capex.reserve_accounts_keur, "y0_share": 0.0})
    return tuple(items)


def _opex_y1_total(project_inputs) -> float:
    return sum(item.y1_amount_keur for item in project_inputs.opex)


def _build_context_from_project_inputs(
    project_inputs,
    *,
    code: str,
    technology: str,
    opex_contingency_method: str,
    opex_contingency_pct: float,
    parity_status: str,
    data_source: str,
) -> ProjectContext:
    opex_items = _build_opex_items(project_inputs, horizon_years=project_inputs.info.horizon_years)
    opex_detail = _build_opex_detail_items(project_inputs, code=code, horizon_years=project_inputs.info.horizon_years)
    financing = project_inputs.financing
    revenue = project_inputs.revenue
    technical = project_inputs.technical
    capex = project_inputs.capex
    tax = project_inputs.tax
    return ProjectContext(
        code=code,
        name=project_inputs.info.name,
        company=project_inputs.info.company,
        country_iso=project_inputs.info.country_iso,
        technology=technology,
        capacity_mw=technical.capacity_mw,
        cod_date=str(project_inputs.info.cod_date),
        financial_close=str(project_inputs.info.financial_close),
        construction_months=project_inputs.info.construction_months,
        horizon_years=project_inputs.info.horizon_years,
        period_frequency=project_inputs.info.period_frequency.value,
        yield_scenario=technical.yield_scenario,
        operating_hours_p50=technical.operating_hours_p50,
        plant_availability=technical.plant_availability,
        grid_availability=technical.grid_availability,
        pv_degradation=technical.pv_degradation if technology != "Wind" else None,
        ppa_tariff_eur_mwh=revenue.ppa_base_tariff,
        ppa_term_years=int(revenue.ppa_term_years),
        ppa_index_pct=revenue.ppa_index,
        co2_enabled=revenue.co2_enabled,
        co2_price_eur_mwh=(
            getattr(revenue, "co2_certificate_price_eur_per_mwh", None)
            or getattr(revenue, "co2_price_eur", None)
        ),
        revenue_items=_build_revenue_items(revenue, technical, technology),
        opex_items=opex_items,
        opex_detail_items=opex_detail["categories"],
        opex_y1_total_keur=_opex_y1_total(project_inputs),
        opex_contingency_method=opex_contingency_method,
        opex_contingency_pct=opex_contingency_pct,
        capex_items=_build_capex_items(capex),
        capex_detail_items=_build_capex_detail_items(
        capex, construction_months=project_inputs.info.construction_months, technology=technology
        )["categories"],
        capex_construction_months=project_inputs.info.construction_months,
        capex_y1_total_keur=_capex_y1_total(capex),
        total_capex_keur=capex.total_capex,
        epc_contract_keur=capex.epc_contract.amount_keur,
        idc_keur=capex.idc_keur,
        bank_fees_keur=capex.bank_fees_keur,
        senior_debt_keur=financing.fixed_debt_keur,
        # Phase PR2: realized gearing = senior_debt / total_capex * 100.
        # Read-only derived KPI (output). Not bound to the
        # indicative gearing_pct input. None when total_capex is 0
        # (uninitialised CAPEX -> em-dash fallback in UI).
        realized_gearing_pct=_compute_realized_gearing_pct(
            financing.fixed_debt_keur, capex.total_capex
        ),
        interest_rate_pct=financing.base_rate + financing.margin_bps / 10_000,
        senior_base_rate_pct=financing.base_rate,
        senior_margin_bps=financing.margin_bps,
        senior_tenor_years=financing.senior_tenor_years,
        target_dscr=financing.target_dscr,
        lockup_dscr=getattr(financing, "lockup_dscr", 0.0) or 0.0,
        dsra_months=getattr(financing, "dsra_months", 0) or 0,
        gearing_pct=getattr(financing, "gearing_ratio", None),
        shl_amount_keur=financing.shl_amount_keur,
        shl_rate_pct=financing.shl_rate,
        shl_idc_keur=financing.shl_idc_keur,
        construction_items=_build_construction_items(project_inputs),
        idc_items=_build_idc_items(project_inputs),
        cit_rate_pct=tax.corporate_rate,
        loss_carryforward_years=tax.loss_carryforward_years,
        g20_status="BLOCKED",
        r99_r102_status="NOT APPROVED",
        parity_status=parity_status,
        data_source=data_source,
        missing_fields=(),
    )


def _build_generic_wind_reference_context() -> ProjectContext:
    return _build_context_from_project_inputs(
        create_generic_wind_reference(),
        code="Generic Wind Reference",
        technology="Wind",
        opex_contingency_method="percentage_of_opex",
        opex_contingency_pct=6.0,
        parity_status="AUDIT",
        data_source="Factory context - read-only template data",
    )


def _build_generic_solar_reference_context() -> ProjectContext:
    return _build_context_from_project_inputs(
        create_generic_solar_reference(),
        code="GENERIC_SOLAR_REFERENCE",
        technology="Solar PV",
        opex_contingency_method="fixed_amount",
        opex_contingency_pct=2.0,
        parity_status="CONVENTION",
        data_source="Factory context - read-only template data",
    )


def _build_generic_data_center_reference_context() -> ProjectContext:
    return _build_context_from_project_inputs(
        create_generic_data_center_reference(),
        code="GENERIC_DATA_CENTER_REFERENCE",
        technology="Data Center",
        opex_contingency_method="fixed_amount",
        opex_contingency_pct=0.0,
        parity_status="CONVENTION",
        data_source="Factory context - read-only template data",
    )


def _build_generic_data_center_context() -> ProjectContext:
    return _build_context_from_project_inputs(
        create_default_data_center_project(),
        code="GENERIC_DATA_CENTER",
        technology="Data Center",
        opex_contingency_method="fixed_amount",
        opex_contingency_pct=0.0,
        parity_status="ACCEPTED_CONVENTION",
        data_source="Generic data center template - user-project starter defaults",
    )


def _build_generic_wind_context() -> ProjectContext:
    return _build_context_from_project_inputs(
        create_default_wind_project(),
        code="GENERIC_WIND",
        technology="Wind",
        opex_contingency_method="percentage_of_opex",
        opex_contingency_pct=0.0,
        parity_status="ACCEPTED_CONVENTION",
        data_source="Generic wind template - user-project starter defaults",
    )


def _build_generic_solar_context() -> ProjectContext:
    return _build_context_from_project_inputs(
        create_default_solar_project(),
        code="GENERIC_SOLAR",
        technology="Solar PV",
        opex_contingency_method="percentage_of_opex",
        opex_contingency_pct=0.0,
        parity_status="ACCEPTED_CONVENTION",
        data_source="Generic solar template - user-project starter defaults",
    )


_CONTEXTS: dict[str, ProjectContext] = {
    "generic_wind_reference": _build_generic_wind_reference_context(),
    "generic_solar_reference": _build_generic_solar_reference_context(),
    "generic_data_center_reference": _build_generic_data_center_reference_context(),
    "generic_wind": _build_generic_wind_context(),
    "generic_solar": _build_generic_solar_context(),
    "generic_data_center": _build_generic_data_center_context(),
}


def get_project_context(project_id: str | None) -> ProjectContext:
    if project_id and project_id.lower() in _CONTEXTS:
        return _CONTEXTS[project_id.lower()]
    return _CONTEXTS["generic_wind_reference"]


def _snapshot_float(snapshot: dict[str, Any], key: str, default: float) -> float:
    value = snapshot.get(key)
    if value in (None, "", NOT_AVAILABLE, MISSING):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _snapshot_int(snapshot: dict[str, Any], key: str, default: int) -> int:
    value = snapshot.get(key)
    if value in (None, "", NOT_AVAILABLE, MISSING):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _scaled_opex_items(base_items: tuple[dict[str, Any], ...], target_total: float) -> tuple[dict[str, Any], ...]:
    if not base_items:
        return base_items
    current_total = sum(float(item.get("y1_keur", 0.0) or 0.0) for item in base_items)
    if current_total <= 0:
        return base_items
    ratio = target_total / current_total
    return tuple(
        {
            **item,
            "y1_keur": float(item.get("y1_keur", 0.0) or 0.0) * ratio,
        }
        for item in base_items
    )


def build_project_context_for_record(
    *,
    project_code: str,
    project_name: str,
    project_type: str | None,
    project_origin: str,
    template_source: str | None,
    baseline_snapshot: dict[str, Any] | None = None,
    effective_project_inputs=None,
    current_snapshot: dict[str, Any] | None = None,
) -> ProjectContext:
    seed_key = (template_source or "").strip().lower()
    if seed_key == "generic_wind_reference":
        base = _CONTEXTS["generic_wind_reference"]
    elif seed_key == "generic_solar_reference":
        base = _CONTEXTS["generic_solar_reference"]
    elif seed_key in ("generic_data_center_reference", "generic_data_center"):
        base = _CONTEXTS[seed_key]
    elif (project_type or "").strip().lower() in {"data center", "data_center", "datacenter"}:
        base = _CONTEXTS["generic_data_center"]
    elif (project_type or "").strip().lower() == "solar":
        base = _CONTEXTS["generic_solar"]
    else:
        base = _CONTEXTS["generic_wind"]

    if project_origin == "factory_template":
        return base

    # ── For user-created projects: preserve full OPEX detail from template origin ──
    # If seeded from generic_wind_reference/generic_solar_reference, use the full detailed opex_detail_items from
    # that base (B.01–B.13 with children) rather than falling back to flat generic.
    # For generic_wind/generic_solar without specific origin, keep existing behavior.
    opex_detail_items_for_user_project: tuple[dict[str, Any], ...] | None = None
    if seed_key in ("generic_wind_reference", "generic_solar_reference", "generic_data_center_reference"):
        opex_detail_items_for_user_project = base.opex_detail_items

    # current_snapshot (persisted draft) takes priority over baseline_snapshot for
    # user working-copy exports; baseline_snapshot remains the fallback for legacy
    # callers and factory-template references.
    snapshot = dict(current_snapshot if current_snapshot is not None else (baseline_snapshot or {}))
    resolved_project_type = (snapshot.get("project_type") or project_type or "").strip().lower()
    if resolved_project_type in {"data center", "data_center", "datacenter"}:
        technology = "Data Center"
    elif resolved_project_type in ("ev charging", "ev_charging"):
        technology = "EV Charging"
    else:
        technology = "Solar PV" if resolved_project_type == "solar" else "Wind"
    # R5/F04-A: when effective_project_inputs is provided it is the ONE causal
    # authority — the same persisted draft that drove the production run.  Read
    # every engine-bound scalar from it using explicit is-None checks (never
    # truthiness) so that valid falsy values (0.0 interest, 0 gearing) are not
    # silently replaced by the baseline.  baseline_snapshot / current_snapshot is
    # only consulted for metadata-only fields (country, COD string, project type)
    # that have no ProjectInputs representation, and as a last-resort fallback
    # when no effective inputs are supplied (legacy callers, factory-template
    # references).
    if effective_project_inputs is not None:
        _pi = effective_project_inputs
        _info = getattr(_pi, "info", None)
        _tech = getattr(_pi, "technical", None)
        _rev = getattr(_pi, "revenue", None)
        _fin = getattr(_pi, "financing", None)
        _tax_pi = getattr(_pi, "tax", None)

        _cap = getattr(_tech, "capacity_mw", None)
        capacity_mw = _cap if _cap is not None else _snapshot_float(snapshot, "capacity_mw", base.capacity_mw)

        _p50 = getattr(_tech, "operating_hours_p50", None)
        operating_hours_p50 = _p50 if _p50 is not None else _snapshot_float(snapshot, "p50_hours", base.operating_hours_p50)

        ppa_tariff_eur_mwh = getattr(_rev, "ppa_base_tariff", None) if _rev is not None else None
        if ppa_tariff_eur_mwh is None:
            ppa_tariff_eur_mwh = _snapshot_float(snapshot, "tariff_eur_mwh", base.ppa_tariff_eur_mwh)

        _ppa_term = getattr(_rev, "ppa_term_years", None) if _rev is not None else None
        ppa_term_years = int(_ppa_term) if _ppa_term is not None else _snapshot_int(snapshot, "ppa_term_years", base.ppa_term_years)

        _cm = getattr(_info, "construction_months", None)
        construction_months = _cm if _cm is not None else _snapshot_int(snapshot, "construction_months", base.construction_months)

        _hy = getattr(_info, "horizon_years", None)
        horizon_years = _hy if _hy is not None else _snapshot_int(snapshot, "horizon_years", base.horizon_years)

        cod_date_raw = getattr(_info, "cod_date", None)
        cod_date = str(cod_date_raw) if cod_date_raw is not None else ((snapshot.get("cod_date") or base.cod_date or "").strip() or base.cod_date)

        _capex_obj = getattr(_pi, "capex", None)
        try:
            total_capex_keur = float(_capex_obj.total_capex) if _capex_obj is not None else _snapshot_float(snapshot, "total_capex_keur", base.total_capex_keur)
        except Exception:
            total_capex_keur = _snapshot_float(snapshot, "total_capex_keur", base.total_capex_keur)

        opex_list = getattr(_pi, "opex", None)
        if opex_list:
            opex_y1_total_keur = sum(getattr(item, "y1_amount_keur", 0.0) or 0.0 for item in opex_list)
        else:
            opex_y1_total_keur = _snapshot_float(snapshot, "opex_y1_keur", base.opex_y1_total_keur)

        _dscr = getattr(_fin, "target_dscr", None)
        target_dscr = _dscr if _dscr is not None else _snapshot_float(snapshot, "target_dscr", base.target_dscr)

        # Explicit is-None check: 0.0 is a valid authoritative interest rate.
        _rate = getattr(_fin, "all_in_rate", None)
        interest_rate_fraction = _rate if _rate is not None else _snapshot_float(snapshot, "interest_rate_pct", base.interest_rate_pct * 100.0) / 100.0

        _tenor = getattr(_fin, "senior_tenor_years", None)
        senior_tenor_years = _tenor if _tenor is not None else _snapshot_int(snapshot, "tenor_years", base.senior_tenor_years)

        # Gearing: engine_path="financing.gearing_ratio" (fraction, not pct).
        # Explicit is-None check: 0.0 gearing is financially valid.
        _gr = getattr(_fin, "gearing_ratio", None)
        if _gr is not None:
            gearing_ratio = float(_gr)
        else:
            gearing_ratio = _snapshot_float(
                snapshot,
                "gearing_pct",
                (base.gearing_pct * 100.0) if base.gearing_pct is not None else 0.0,
            ) / 100.0

        country_market = (snapshot.get("country_market") or base.country_iso or "").strip() or base.country_iso
    else:
        capacity_mw = _snapshot_float(snapshot, "capacity_mw", base.capacity_mw)
        operating_hours_p50 = _snapshot_float(snapshot, "p50_hours", base.operating_hours_p50)
        opex_y1_total_keur = _snapshot_float(snapshot, "opex_y1_keur", base.opex_y1_total_keur)
        total_capex_keur = _snapshot_float(snapshot, "total_capex_keur", base.total_capex_keur)
        target_dscr = _snapshot_float(snapshot, "target_dscr", base.target_dscr)
        interest_rate_fraction = _snapshot_float(snapshot, "interest_rate_pct", base.interest_rate_pct * 100.0) / 100.0
        senior_tenor_years = _snapshot_int(snapshot, "tenor_years", base.senior_tenor_years)
        gearing_ratio = _snapshot_float(
            snapshot,
            "gearing_pct",
            (base.gearing_pct * 100.0) if base.gearing_pct is not None else 0.0,
        ) / 100.0
        country_market = (snapshot.get("country_market") or base.country_iso or "").strip() or base.country_iso
        ppa_term_years = _snapshot_int(snapshot, "ppa_term_years", base.ppa_term_years)
        ppa_tariff_eur_mwh = _snapshot_float(snapshot, "tariff_eur_mwh", base.ppa_tariff_eur_mwh)
        construction_months = _snapshot_int(snapshot, "construction_months", base.construction_months)
        horizon_years = _snapshot_int(snapshot, "horizon_years", base.horizon_years)
        cod_date = (snapshot.get("cod_date") or base.cod_date or "").strip() or base.cod_date
    # When the caller supplies effective ProjectInputs (per-line overrides already applied),
    # use those opex items directly — they preserve step_changes and calibrated inflation.
    # Fall back to proportional scaling from the aggregate when not provided.
    if effective_project_inputs is not None and getattr(effective_project_inputs, "opex", None):
        opex_items = tuple(effective_project_inputs.opex)
    else:
        opex_items = _scaled_opex_items(base.opex_items, opex_y1_total_keur)

    # R2: rebuild capex_detail_items from canonical pi.capex so display values
    # align with CAPEX_CATEGORY_TO_FIELD — not the factory template amounts.
    if effective_project_inputs is not None and getattr(effective_project_inputs, "capex", None):
        canonical_capex_detail_items = _build_capex_detail_items(
            effective_project_inputs.capex, construction_months=construction_months, technology=technology
        )["categories"]
    else:
        canonical_capex_detail_items = base.capex_detail_items

    return replace(
        base,
        code=project_code.upper(),
        name=(snapshot.get("project_name") or project_name),
        company="User-created project record",
        country_iso=country_market,
        technology=technology,
        capacity_mw=capacity_mw,
        cod_date=cod_date,
        construction_months=construction_months,
        horizon_years=horizon_years,
        operating_hours_p50=operating_hours_p50,
        ppa_tariff_eur_mwh=ppa_tariff_eur_mwh,
        ppa_term_years=ppa_term_years,
        opex_items=opex_items,
        opex_y1_total_keur=opex_y1_total_keur,
        capex_items=base.capex_items,
        capex_detail_items=canonical_capex_detail_items,
        total_capex_keur=total_capex_keur,
        interest_rate_pct=interest_rate_fraction,
        senior_tenor_years=senior_tenor_years,
        target_dscr=target_dscr,
        gearing_pct=gearing_ratio,
        # Phase PR2: realized gearing (read-only derived KPI).
        # In user-snapshot path the senior_debt_keur is the
        # already-computed DSCR-sculpted value from the
        # baseline ProjectInputs (financing.fixed_debt_keur);
        # we re-derive it from base.senior_debt_keur.
        realized_gearing_pct=_compute_realized_gearing_pct(
            base.senior_debt_keur, total_capex_keur
        ),
        data_source=(
            "User-created project record - runtime built from saved project assumptions. "
            "Some secondary assumptions still use system defaults until later phases."
        ),
    )


def all_project_ids() -> list[str]:
    return list(_CONTEXTS.keys())
