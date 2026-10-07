"""Shared rendering harness for the Model workspace productivity suites.

Renders the REAL ``field_editor.html`` macro (fed by the router's own
``_build_sheet_fields``), real sheet-style wrappers, and the REAL Smart Panel
partial, then inlines the REAL ``workbook_v2.css`` / ``workbook_v2.js`` and the
C1 interaction modules in the production load order.  No app server, database
or engine is involved.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
_ENV = Environment(
    loader=FileSystemLoader(str(ROOT / "app" / "templates" / "v2")),
    autoescape=select_autoescape(["html"]),
)

# (registry sheet_id, DOM id, C1 grid id, panel id, tab id, tab label)
SHEETS = (
    ("project_setup", "v2-sheet-project-setup", "project_setup",
     "panel-project-setup", "tab-project-setup", "Project Setup"),
    ("revenue", "v2-sheet-revenue", "revenue",
     "panel-revenue", "tab-revenue", "Revenue"),
    ("debt", "v2-sheet-senior-debt", "senior_debt",
     "panel-debt", "tab-debt", "Senior Debt"),
    ("tax", "v2-sheet-tax", "tax",
     "panel-tax", "tab-tax", "Tax"),
)

# Load order mirrors app/templates/v2/workbook.html.
INTERACTION_SCRIPTS = (
    "grid-registry.js", "engine.js", "active-cell.js", "swap-lifecycle.js",
    "focus-manager.js", "keyboard-router.js", "selection-manager.js",
)

_SHEET_TEMPLATE = _ENV.from_string("""
{% from "partials/field_editor.html" import render_field %}
<div id="{{ dom_id }}" data-sheet="{{ sheet_id }}" data-fc-grid="{{ grid_id }}" data-fc-scroll-container>
  {% for section in sections %}
  <details class="v2-inputs-section"{% if not collapsed %} open{% endif %} data-section="{{ section.id }}">
    <summary class="v2-inputs-section-summary">{{ section.label }}</summary>
    <div class="v2-section-fields">
      {% for f in section.rows %}
      {{ render_field(f, "demo", workbook_version, content_hash, project_editable,
                      hx_target="#" ~ dom_id, sheet_id=sheet_id) }}
      {% endfor %}
    </div>
  </details>
  {% endfor %}
</div>
""")


def sheet_fields(sheet_id: str, values: Optional[dict[str, Any]] = None) -> list[dict]:
    """Real router-built field dicts, optionally overriding displayed values."""
    from app.v2.router import _build_sheet_fields
    from app.workbook.input_set import ProjectInputSet
    from app.workbook.registry import WORKBOOK

    pis = ProjectInputSet.from_snapshot({}, workbook=WORKBOOK)
    rows = _build_sheet_fields(sheet_id, pis)
    for row in rows:
        if values and row["field_id"] in values:
            row["value"] = values[row["field_id"]]
    return rows


def render_sheet(sheet_id: str, *, project_editable: bool = True,
                 collapsed: bool = False, values: Optional[dict[str, Any]] = None,
                 content_hash: str = "hash-0") -> str:
    meta = next(s for s in SHEETS if s[0] == sheet_id)
    sections: list[dict] = []
    for row in sheet_fields(sheet_id, values):
        if not sections or sections[-1]["id"] != row["section_id"]:
            sections.append({"id": row["section_id"], "label": row["section_label"], "rows": []})
        sections[-1]["rows"].append(row)
    from app.workbook.registry import WORKBOOK
    return _SHEET_TEMPLATE.render(
        dom_id=meta[1], sheet_id=sheet_id, grid_id=meta[2], sections=sections,
        collapsed=collapsed, project_editable=project_editable,
        workbook_version=WORKBOOK.version, content_hash=content_hash,
    )


_ROW_TEMPLATE = """{% from "partials/field_editor.html" import render_field %}
{{ render_field(f, "demo", workbook_version, "hash-0", project_editable,
                hx_target="#" ~ dom_id, sheet_id=sheet_id) }}"""

# Tricky canonical values: bit-identical rendering is part of the contract.
TRICKY_VALUES = {
    "project_setup.technical.capacity_mw": 33.333333333333336,
    "project_setup.technical.p50_hours": 2750.5,
    "project_setup.technical.construction_months": 18,
    "project_setup.technical.horizon_years": 25,
    "revenue.ppa.base_tariff": 0.1 + 0.2,
    "revenue.ppa.index": 1e-07,
    "revenue.ppa.production_share": 100.0,
    "debt.senior.tenor_years": 18,
}


def render_macro_rows(sheet_id: str, *, project_editable: bool = True,
                      values: Optional[dict[str, Any]] = None,
                      env: Optional[Environment] = None) -> dict[str, str]:
    """field_id -> rendered ``render_field`` HTML for every row of a sheet."""
    from app.workbook.registry import WORKBOOK
    meta = next(s for s in SHEETS if s[0] == sheet_id)
    template = (env or _ENV).from_string(_ROW_TEMPLATE)
    return {
        f["field_id"]: template.render(
            f=f, workbook_version=WORKBOOK.version, project_editable=project_editable,
            dom_id=meta[1], sheet_id=sheet_id)
        for f in sheet_fields(sheet_id, values)
    }


def render_panel(smart_panel) -> str:
    return _ENV.get_template("partials/_model_smart_panel.html").render(
        {"smart_panel": smart_panel})


def default_panel(**overrides):
    from app.v2.smart_panel_projection import build_smart_panel_projection
    kwargs: dict[str, Any] = dict(
        trust_pack=None, runtime_state="CURRENT", has_runtime=True, project_key="")
    kwargs.update(overrides)
    return build_smart_panel_projection(**kwargs)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def build_page(*, project_editable: bool = True, collapsed_sheets: tuple[str, ...] = ("revenue",),
               panel=None, values: Optional[dict[str, Any]] = None) -> str:
    """Full workbook-like page: tabs, panels, shell, Smart Panel, real CSS/JS."""
    tabs, panels = [], []
    for index, (sheet_id, _dom, _grid, panel_id, tab_id, label) in enumerate(SHEETS):
        tabs.append(
            f'<button class="v2-tab" role="tab" aria-selected="{"true" if index == 0 else "false"}" '
            f'tabindex="{0 if index == 0 else -1}" aria-controls="{panel_id}" id="{tab_id}">{label}</button>')
        body = render_sheet(sheet_id, project_editable=project_editable,
                            collapsed=sheet_id in collapsed_sheets, values=values)
        hidden = "" if index == 0 else " hidden"
        panels.append(
            f'<div class="v2-sheet-panel" role="tabpanel" id="{panel_id}" '
            f'aria-labelledby="{tab_id}"{hidden}><div class="v2-sheet-body">{body}</div></div>')
    smart = render_panel(panel if panel is not None else default_panel())
    scripts = "\n".join(
        f"<script>{_read('static/interaction/' + name)}</script>"
        for name in INTERACTION_SCRIPTS)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>harness</title>
<style>{_read('static/css/workbook_v2.css')}</style></head>
<body>
<div id="harness-header-stack" style="height:170px" aria-hidden="true"></div>  <!-- real page: toolbar + workspace header stack -->
<div class="v2-workspace-body"><div id="model-workspace-main" class="v2-workspace-main">
<nav class="v2-tabs v2-tabs--secondary" role="tablist" id="v2-sheet-tabs">{''.join(tabs)}</nav>
<div id="v2-status-banner"></div>
<div id="v2-workbook-shell" data-project="demo" data-content-hash="hash-0">{''.join(panels)}</div>
{smart}
</div></div>
<script>{_read('static/js/workbook_v2.js')}</script>
{scripts}
</body></html>"""
