"""
app.v2.runtime_projection_views — thin OOB HTML helpers.

Renders the three runtime bar partials as hx-swap-oob fragments.
Called from every HTMX mutation success path so that all three state bars
update without a full page reload.
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi.templating import Jinja2Templates

from app.workbook.runtime_projection import WorkbookRuntimeProjection

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_templates = Jinja2Templates(
    directory=os.path.join(_BASE_DIR, "app", "templates", "v2")
)


def _render_bar(partial: str, ctx: dict) -> str:
    return _templates.get_template(partial).render(ctx)


def build_all_runtime_bar_oob(projection: WorkbookRuntimeProjection) -> str:
    """Return combined OOB HTML for all three runtime bars.

    Each fragment targets its named div (debt-runtime-bar, tax-runtime-bar,
    fs-runtime-bar) via hx-swap-oob="true".  Append to any HTMX success
    response to keep all three bars in sync without re-rendering the sheets.
    """
    debt_html = _render_bar(
        "partials/_debt_runtime_bar.html",
        {"debt_state": projection.debt.state.value},
    )
    tax_html = _render_bar(
        "partials/_tax_runtime_bar.html",
        {"tax_state": projection.tax.state.value},
    )
    # The FS bar partial uses "FS_UNAVAILABLE" as the key for the unavailable
    # state to preserve backward compatibility with existing templates.
    fs_state_key = (
        "FS_UNAVAILABLE" if projection.fs.state.value == "UNAVAILABLE"
        else projection.fs.state.value
    )
    fs_html = _render_bar(
        "partials/_fs_runtime_bar.html",
        {"fs_state": fs_state_key},
    )
    return (
        f'<div id="debt-runtime-bar" hx-swap-oob="true">{debt_html}</div>\n'
        f'<div id="tax-runtime-bar" hx-swap-oob="true">{tax_html}</div>\n'
        f'<div id="fs-runtime-bar" hx-swap-oob="true">{fs_html}</div>'
    )


def build_fs_bar_oob(projection: WorkbookRuntimeProjection) -> str:
    """Return OOB HTML for the FS runtime bar only (legacy helper)."""
    fs_state_key = (
        "FS_UNAVAILABLE" if projection.fs.state.value == "UNAVAILABLE"
        else projection.fs.state.value
    )
    fs_html = _render_bar(
        "partials/_fs_runtime_bar.html",
        {"fs_state": fs_state_key},
    )
    return f'<div id="fs-runtime-bar" hx-swap-oob="true">{fs_html}</div>'
