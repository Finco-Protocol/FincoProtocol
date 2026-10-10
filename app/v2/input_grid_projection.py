"""app.v2.input_grid_projection — presentation projection of the Hybrid Inputs grid.

Pure, read-only composition of values and editability rules that the CAPEX / OPEX sheets
already resolve.  It owns NO economics and NO persistence:

* a row is editable ONLY when the CAPEX / OPEX sheet itself offers a registry-bound scalar
  editor for that category (same predicates as ``sheet_capex.html`` / ``sheet_opex.html``);
  categories whose cost comes from line items, linked/shared categories and engine /
  derived categories are rendered read-only with an explicit reason — no toggle is invented;
* values come from the canonical ``ProjectInputSet`` (``pis.get(field_id)``) or the sheets'
  already-built view models;
* the "modified since Last Run" marker compares the current Working Copy value with the value
  in the Last Run input snapshot (``ws.last_runtime_snapshot``) for the SAME scenario.  When
  that baseline is unavailable or not comparable, no marker is shown and the reason is stated —
  a marker is never fabricated.

Persistence of grid edits goes exclusively through the C0 batch writer (``grid_router``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class GridRow:
    code: str
    label: str
    unit: str
    field_id: str = ""            # "" ⇒ not an input
    value: str = ""               # editable text / formatted read-only value
    editable: bool = False
    reason: str = ""              # why read-only (empty when editable)
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    step: str = "any"
    modified_since_run: bool = False
    baseline: str = ""            # Last Run value (display) when modified_since_run


@dataclass(frozen=True)
class GridSection:
    section_id: str               # "capex" | "opex"
    title: str
    categories: tuple["GridCategory", ...] = ()
    sheet_tab_id: str = ""


@dataclass(frozen=True)
class GridCategory:
    code: str
    label: str
    total_display: str
    rows: tuple[GridRow, ...] = ()
    editable_count: int = 0
    modified_count: int = 0


@dataclass(frozen=True)
class InputGridProjection:
    sections: tuple[GridSection, ...] = ()
    editable: bool = False
    editable_count: int = 0
    modified_since_run_count: int = 0
    baseline_note: str = ""       # non-empty ⇒ explains why markers are unavailable
    content_hash: str = ""
    workbook_version: str = ""
    scenario_id: str = ""


_NUMERIC_TYPES = frozenset({"float", "mw", "mwh", "keur", "pct", "bps", "int", "months", "years"})
# Cascading / collection fields the C0 batch writer refuses; shown read-only, never editable here.
_CASCADE_BLOCKED = frozenset({"project_setup.technical.capacity_mw", "project_setup.identity.project_name"})
_COLLECTION_FIELDS = frozenset({"debt.financing.instruments"})


def _plain(value: Any) -> str:
    """Shortest exact text for a numeric value (no separators, no trailing zeros)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        text = f"{value:.10f}".rstrip("0").rstrip(".")
        return text or "0"
    return str(value)


def _thousands(value: Any) -> str:
    try:
        return f"{float(value):,.1f}"
    except (TypeError, ValueError):
        return "—"


def _same(a: Any, b: Any) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)


def baseline_pis(ws: Any, workbook: Any, input_set_cls: Any) -> tuple[Any, str]:
    """(ProjectInputSet of the Last Run inputs | None, note).  Fail-closed: None + reason."""
    if not getattr(ws, "last_runtime_snapshot_id", None):
        return None, "No Last Run yet — nothing to compare against."
    if (getattr(ws, "last_runtime_scenario_id", None) or None) != (getattr(ws, "active_scenario_id", None) or None):
        return None, "Last Run belongs to a different scenario — change markers are not comparable."
    snap = getattr(ws, "last_runtime_snapshot", None)
    if not isinstance(snap, dict) or not snap:
        return None, "Last Run input snapshot unavailable."
    try:
        return input_set_cls.from_snapshot(snap, workbook=workbook), ""
    except Exception:  # noqa: BLE001 — presentation helper must never break the page
        return None, "Last Run input snapshot could not be read."


def _row_from_field(code: str, label: str, f: dict, pis: Any, base: Any, *,
                    editable: bool, reason: str) -> GridRow:
    fid = f["field_id"]
    cur = pis.get(fid)
    modified = False
    baseline = ""
    if base is not None:
        b = base.get(fid)
        modified = not _same(cur, b)
        baseline = _plain(b) if modified else ""
    return GridRow(
        code=code, label=label, unit=f.get("unit") or "kEUR", field_id=fid,
        value=_plain(cur), editable=editable, reason="" if editable else reason,
        min_value=f.get("min_value"), max_value=f.get("max_value"),
        step=str(f.get("step") or "any"),
        modified_since_run=modified and editable, baseline=baseline if editable else "",
    )


def _readonly(code: str, label: str, total: Any, reason: str, unit: str = "kEUR") -> GridRow:
    return GridRow(code=code, label=label, unit=unit, value=_thousands(total) if total is not None else "—",
                   editable=False, reason=reason)


def build_input_grid_projection(
    *,
    capex_ctx: dict,
    opex_ctx: dict,
    pis: Any,
    base_pis: Any,
    baseline_note: str,
    project_editable: bool,
    content_hash: str,
    workbook_version: str,
    scenario_id: str,
    registry_sheets: tuple[tuple[str, str, str, list[dict], dict[str, str]], ...] = (),
) -> InputGridProjection:
    # ── CAPEX ───────────────────────────────────────────────────────────────────────
    capex_vm = capex_ctx.get("capex_vm")
    g2f = capex_ctx.get("capex_group_to_field") or {}
    aliases = capex_ctx.get("capex_alias_groups") or {}
    cx_cats: list[GridCategory] = []
    for group in getattr(capex_vm, "groups", ()) or ():
        gf = g2f.get(group.code)
        has_custom = any(getattr(ln, "is_custom", False) for ln in group.lines)
        if group.code in aliases:
            row = _readonly(group.code, group.name, group.subtotal_keur, "Linked to Audit & Legal")
        elif getattr(group, "is_readonly", False) or getattr(group, "is_financing", False) \
                or getattr(group, "is_reserve", False):
            row = _readonly(group.code, group.name, group.subtotal_keur, "Calculated by the model")
        elif getattr(group, "is_contingency", False):
            row = _readonly(group.code, group.name, group.subtotal_keur, "Calculated contingency")
        elif gf and gf.get("binding_label") == "bound" and has_custom:
            row = _readonly(group.code, group.name, group.subtotal_keur, "Sum of line items — edit on the CAPEX sheet")
        elif gf and gf.get("binding_label") == "bound":
            row = _row_from_field(group.code, group.name, gf, pis, base_pis,
                                  editable=project_editable, reason="Reference project is read-only")
        else:
            row = _readonly(group.code, group.name, group.subtotal_keur, "Calculated")
        cx_cats.append(GridCategory(
            code=group.code, label=group.name, total_display=_thousands(group.subtotal_keur),
            rows=(row,), editable_count=int(row.editable), modified_count=int(row.modified_since_run)))

    # ── OPEX ────────────────────────────────────────────────────────────────────────
    inactive = opex_ctx.get("opex_inactive_lines") or {}
    ox_cats: list[GridCategory] = []
    for sg in opex_ctx.get("opex_sheet_groups") or ():
        name = sg.display_name
        total = sg.subtotal_y1 if sg.has_vm_data else None
        if sg.is_derived:
            row = _readonly(sg.code, name, total, "Calculated contingency")
        elif sg.is_engine or not sg.has_vm_data:
            row = _readonly(sg.code, name, total, "Calculated by the model")
        elif sg.is_bound and (sg.custom_lines or inactive.get(sg.code)):
            row = _readonly(sg.code, name, total, "Sum of line items — edit on the OPEX sheet")
        elif sg.is_bound:
            row = _row_from_field(sg.code, name, sg.field, pis, base_pis,
                                  editable=project_editable, reason="Reference project is read-only")
        else:
            row = _readonly(sg.code, name, total, "Calculated")
        ox_cats.append(GridCategory(
            code=sg.code, label=name, total_display=_thousands(total) if total is not None else "—",
            rows=(row,), editable_count=int(row.editable), modified_count=int(row.modified_since_run)))

    sections = [
        GridSection("capex", "CAPEX", tuple(cx_cats), "tab-capex"),
        GridSection("opex", "OPEX (Year 1)", tuple(ox_cats), "tab-opex"),
    ]
    # Registry-bound scalar inputs of the other input sheets (same editors the sheets offer).
    for sheet_id, sheet_title, tab_id, fields, section_titles in registry_sheets:
        by_section: dict[str, list[dict]] = {}
        for f in fields:
            by_section.setdefault(f.get("section_id") or sheet_id, []).append(f)
        for section_id, rows_f in by_section.items():
            rows: list[GridRow] = []
            for f in rows_f:
                fid = f["field_id"]
                numeric = f.get("field_type") in _NUMERIC_TYPES
                if f.get("binding_label") != "bound":
                    row = GridRow(code="", label=f["label"], unit=f.get("unit") or "",
                                  value=_plain(f.get("display_value", f.get("value"))) or "—",
                                  reason="Calculated / locked by the model")
                elif fid in _CASCADE_BLOCKED or fid in _COLLECTION_FIELDS:
                    row = GridRow(code="", label=f["label"], unit=f.get("unit") or "",
                                  value=_plain(f.get("value")) or "—",
                                  reason=f"Edit on the {sheet_title} sheet (dependent values update together)")
                elif not numeric:
                    row = GridRow(code="", label=f["label"], unit=f.get("unit") or "",
                                  value=_plain(f.get("value")) or "—",
                                  reason=f"Choice / text field — edit on the {sheet_title} sheet")
                else:
                    row = _row_from_field("", f["label"], f, pis, base_pis,
                                          editable=project_editable, reason="Reference project is read-only")
                    row = GridRow(**{**row.__dict__, "value": _plain(f.get("value")), "unit": f.get("unit") or ""})
                rows.append(row)
            cats = tuple(GridCategory(code="", label=r.label, total_display="", rows=(r,),
                                      editable_count=int(r.editable), modified_count=int(r.modified_since_run))
                         for r in rows)
            title = f"{sheet_title} · {section_titles.get(section_id, section_id.replace('_', ' ').title())}"
            sections.append(GridSection(f"{sheet_id}-{section_id}", title, cats, tab_id))
    sections = tuple(sections)
    editable_count = sum(c.editable_count for s in sections for c in s.categories)
    modified = sum(c.modified_count for s in sections for c in s.categories)
    return InputGridProjection(
        sections=sections, editable=project_editable, editable_count=editable_count,
        modified_since_run_count=modified, baseline_note=baseline_note,
        content_hash=content_hash, workbook_version=workbook_version, scenario_id=scenario_id or "",
    )
