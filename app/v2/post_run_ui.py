"""R6/F07 — ONE post-run UI projection authority.

A completed canonical Workbook V2 Run must produce ONE coherent post-run
browser state.  ``build_post_run_ui_state`` is constructed ONLY after:

1. the canonical Run succeeded;
2. runtime evidence was persisted (``v2_atomic_run_commit``);
3. fresh workspace state was re-read (``ws_fresh``);

and renders every runtime-dependent visible surface from that single
workspace read and a single runtime projection — no partial re-runs, no
independent KPI derivation, no financial arithmetic in templates/JS:

    canonical Run
        → persisted runtime evidence (ws_fresh)
        → RuntimeResult + RuntimeProjectionBundle
        → post-run OOB fragments
        → every runtime-dependent visible surface

Surfaces refreshed (all runtime-dependent):
    #v2-run-controls            authoritative composite hash (immediate re-edit/re-run)
    #v2-status-banner           dirty/stale → current post-run state
    #v2-toolbar-runtime-state   current/stale chip + last runtime timestamp
    #v2-sheet-overview          KPI strip + decision dashboard (F07: previously stale)
    #v2-sheet-senior-debt       debt runtime bar + coverage presentation
    #v2-sheet-tax               tax runtime bar (R4 typed country-tax semantics preserved)
    #v2-sheet-financial-statements  FS runtime state (canonical unavailable stays unavailable)
    #v2-sheet-returns           persisted sponsor/distribution Last Run evidence
    #v2-sheet-scenarios         per-scenario last-run status (persisted in run step 12b)

Inputs-only sheets (project_setup, inputs, revenue, CAPEX, OPEX) are NOT
refreshed by a Run — they hold no runtime-derived values.
"""
from __future__ import annotations

from typing import Any, Optional

_NOTSET = object()  # sentinel: distinguishes "caller passed rr=None" from "caller did not pass rr"


def build_post_run_ui_state(
    *,
    request: Any,
    ws_fresh,
    project_record,
    project: str,
    workspace_owner: str,
    rr: Any = None,
) -> str:
    """Build the complete post-run HTMX response for one completed Run.

    Every fragment is rendered from the same single ``ws_fresh`` read and the
    same ``RuntimeProjectionBundle`` — one completed canonical Run produces
    one post-run UI state.
    """
    from app.workbook.runtime_projection import build_runtime_projection_bundle
    from app.workbook.service import WorkbookService
    from app.v2.overview_projection import build_overview_projection

    from app.v2.router import (  # local import: router owns template helpers
        _base_sheet_ctx,
        _build_export_controls_oob,
        _build_pis_with_composite_identity,
        _build_run_controls_oob,
        _build_toolbar_state_oob,
        _scenario_list_html,
        _templates,
        _build_debt_ctx,
        _build_tax_ctx,
        _build_financial_statements_ctx,
        _build_returns_ctx,
    )

    pis_fresh = _build_pis_with_composite_identity(
        ws_fresh, project_record, workspace_owner)
    from app.workbook.runtime_authority import resolve_runtime_freshness
    freshness = resolve_runtime_freshness(
        ws_fresh, current_composite_hash=pis_fresh.content_hash)
    # R6 Correction A/F: the router validates that a persisted RuntimeResult
    # exists and passes it in — exactly ONE RuntimeProjectionBundle is built
    # here for the whole successful Run response.
    if rr is None:
        rr = WorkbookService.get_runtime_result(ws_fresh)
    projection = (
        build_runtime_projection_bundle(rr, freshness.is_stale) if rr is not None else None
    )
    ctx = _base_sheet_ctx(request, pis_fresh, ws_fresh, project_record, project)

    fragments: list[str] = []

    # A. Run controls — authoritative composite hash for immediate re-edit.
    fragments.append(_build_run_controls_oob(ctx))

    # A'. Export controls — now that a run exists, enable the export button.
    fragments.append(_build_export_controls_oob(ctx))

    # B. Status banner — dirty/stale transitions to the post-run state.
    banner_html = _templates.get_template(
        "partials/_v2_status_banner.html").render(ctx)
    fragments.append(
        '<div id="v2-status-banner" hx-swap-oob="true">' + banner_html + "</div>")

    # D. Toolbar runtime state chip.
    fragments.append(_build_toolbar_state_oob(ctx))

    # A. Overview — runtime KPIs/status from THIS run (F07 defect surface).
    ov = build_overview_projection(
        rr, freshness.is_stale, pis_fresh,
        active_scenario_name=getattr(ws_fresh, "active_scenario_name", None) or "",
    )
    ov_ctx = {
        "overview": ov,
        "project_code": project,
        "project_name": getattr(project_record, "project_name", "") or project,
        "project_type": getattr(project_record, "project_type", "") or "",
        "ws_dirty": getattr(ws_fresh, "dirty", True),
        "runtime_is_stale": freshness.is_stale,
        "has_runtime": bool(getattr(ws_fresh, "last_runtime_snapshot_id", None)),
    }
    ov_html = _templates.get_template("partials/sheet_overview.html").render(ov_ctx)
    fragments.append(_as_oob(ov_html, "v2-sheet-overview"))

    # E. Senior Debt runtime presentation.
    ctx.update(_build_debt_ctx(pis_fresh, ws_fresh, projection=projection))
    debt_html = _templates.get_template("partials/sheet_senior_debt.html").render(ctx)
    fragments.append(_as_oob(debt_html, "v2-sheet-senior-debt"))

    # F. Tax runtime presentation (R4 typed country-tax semantics preserved).
    ctx.update(_build_tax_ctx(pis_fresh, ws_fresh, projection=projection))
    tax_html = _templates.get_template("partials/sheet_tax.html").render(ctx)
    fragments.append(_as_oob(tax_html, "v2-sheet-tax"))

    # G. Financial Statements runtime presentation (canonical unavailable
    #    stays typed-unavailable — never manufactured).
    ctx.update(_build_financial_statements_ctx(pis_fresh, ws_fresh, projection=projection))
    fs_html = _templates.get_template(
        "partials/sheet_financial_statements.html").render(ctx)
    fragments.append(_as_oob(fs_html, "v2-sheet-financial-statements"))

    # H. Returns — sponsor/distribution evidence from the same persisted run.
    ctx.update(_build_returns_ctx(
        ws_fresh, rr=rr, runtime_is_stale=freshness.is_stale))
    returns_html = _templates.get_template("partials/sheet_returns.html").render(ctx)
    fragments.append(_as_oob(returns_html, "v2-sheet-returns"))

    # I. Scenario last-run statuses (persisted during run step 12b).
    scenarios_html = _scenario_list_html(
        workspace_owner, project_record.project_id, project, ws_fresh)
    fragments.append(_as_oob(scenarios_html, "v2-sheet-scenarios"))

    return "\n".join(fragments)


def _as_oob(html: str, dom_id: str) -> str:
    """Attach ``hx-swap-oob`` to a sheet partial's own root element (the
    existing workbook convention — avoids duplicate wrapper DOM IDs)."""
    marker = f'<div id="{dom_id}"'
    if marker not in html:
        return html
    return html.replace(marker, marker + ' hx-swap-oob="true"', 1)


def build_post_save_ui_state(
    *,
    ws_fresh,
    project_record=None,
    project: str = "",
    workspace_owner: str = "",
    request: Any = None,
    include_banner_and_controls: bool = False,
    include_runtime_bars: bool = True,
    include_scenario_list: bool = True,
    projection=None,
    rr=_NOTSET,
) -> str:
    """R6 Correction A — ONE post-Save runtime-state refresh authority.

    A financially causal successful Save (workspace now dirty) must make
    every visible runtime-state surface consistently STALE in the SAME HTMX
    response, without a GET reload.  Old runtime values may remain visible
    for reference but are visibly classified stale.

    Contract: NO engine call, NO ``run_project``, NO financial calculation —
    reads only the freshly persisted dirty workspace state, reconstructs the
    persisted RuntimeResult for reference classification, and builds ONE
    RuntimeProjectionBundle.
    """
    from app.workbook.runtime_projection import build_runtime_projection_bundle
    from app.workbook.service import WorkbookService
    from app.v2.overview_projection import build_overview_projection
    from app.v2.runtime_projection_views import build_all_runtime_bar_oob

    from app.v2.router import (  # router owns the template helpers
        _build_pis_with_composite_identity,
        _build_export_controls_oob,
        _build_run_controls_oob,
        _build_toolbar_state_oob,
        _fmt_runtime_at,
        _scenario_list_html,
        _templates,
        _build_returns_ctx,
    )

    if rr is _NOTSET:
        rr = WorkbookService.get_runtime_result(ws_fresh)
    pis_fresh = None
    if project_record is not None and workspace_owner:
        pis_fresh = _build_pis_with_composite_identity(
            ws_fresh, project_record, workspace_owner)
    from app.workbook.runtime_authority import resolve_runtime_freshness
    freshness = resolve_runtime_freshness(
        ws_fresh,
        current_composite_hash=(
            pis_fresh.content_hash if pis_fresh is not None else None),
    )
    if projection is None:
        projection = build_runtime_projection_bundle(rr, freshness.is_stale)
    dirty = bool(getattr(ws_fresh, "dirty", True))
    has_runtime = bool(getattr(ws_fresh, "last_runtime_snapshot_id", None))
    fragments: list[str] = []

    if include_banner_and_controls and request is not None:
        ctx = {
            "request": request,
            "project_code": project,
            "workbook_version": pis_fresh.workbook_version,
            "content_hash": pis_fresh.content_hash,
            "template_source": pis_fresh.template_source,
            "project_editable": True,
            "ws_dirty": dirty,
            "runtime_is_stale": freshness.is_stale,
            "has_runtime": has_runtime,
            "last_runtime_at": _fmt_runtime_at(
                getattr(ws_fresh, "last_runtime_at", None) or ""),
            "field_error": "",
            "active_scenario_name": getattr(
                ws_fresh, "active_scenario_name", None) or "",
        }
        banner_html = _templates.get_template(
            "partials/_v2_status_banner.html").render(ctx)
        fragments.append(
            '<div id="v2-status-banner" hx-swap-oob="true">' + banner_html + "</div>")
        fragments.append(_build_toolbar_state_oob(ctx))
        fragments.append(_build_run_controls_oob(ctx))
        fragments.append(_build_export_controls_oob(ctx))
    else:
        # Toolbar-only OOB (banner/controls are already emitted by the sheet
        # renderer on every mutation response).
        toolbar_ctx = {
            "has_runtime": has_runtime,
            "ws_dirty": dirty,
            "runtime_is_stale": freshness.is_stale,
            "last_runtime_at": _fmt_runtime_at(
                getattr(ws_fresh, "last_runtime_at", None) or ""),
        }
        fragments.append(_build_toolbar_state_oob(toolbar_ctx))

    # Overview: KPI values stay visible for reference but are classified
    # stale while the workspace is dirty (v2-kpi-tile--stale + is_stale).
    pis = WorkbookService.build_draft_input_set_from_workspace(ws_fresh)
    ov = build_overview_projection(
        rr, freshness.is_stale, pis,
        active_scenario_name=getattr(ws_fresh, "active_scenario_name", None) or "",
    )
    ov_ctx = {
        "overview": ov,
        "project_code": project,
        "project_name": getattr(project_record, "project_name", "") or project,
        "project_type": getattr(project_record, "project_type", "") or "",
        "ws_dirty": dirty,
        "runtime_is_stale": freshness.is_stale,
        "has_runtime": has_runtime,
    }
    ov_html = _templates.get_template("partials/sheet_overview.html").render(ov_ctx)
    fragments.append(_as_oob(ov_html, "v2-sheet-overview"))

    # Debt / Tax / FS runtime bars — stale/current states from the SAME
    # projection (never substituted zeros or old "current" labels).  Callers
    # that already emitted the bars can suppress this section.
    if include_runtime_bars:
        fragments.append(build_all_runtime_bar_oob(projection))

    # Returns values remain those of the persisted Last Run while their state
    # changes to stale.  This is a presentation refresh, never a calculation.
    returns_ctx = {
        "returns": _build_returns_ctx(
            ws_fresh, rr=rr,
            runtime_is_stale=freshness.is_stale)["returns"],
        "project_code": project,
        "project_editable": True,
    }
    if project_record is not None:
        from app.ui.protected_reference_service import is_protected_reference
        returns_ctx["project_editable"] = not is_protected_reference(project_record)
    returns_html = _templates.get_template("partials/sheet_returns.html").render(returns_ctx)
    fragments.append(_as_oob(returns_html, "v2-sheet-returns"))

    # Scenario last-run statuses (persisted by the previous Run's step 12b).
    if include_scenario_list and project_record is not None and workspace_owner:
        scenarios_html = _scenario_list_html(
            workspace_owner, project_record.project_id, project, ws_fresh)
        fragments.append(_as_oob(scenarios_html, "v2-sheet-scenarios"))

    return chr(10).join(fragments)


def build_toolbar_state_oob(ws, *, runtime_is_stale=None) -> str:
    """Toolbar runtime-state chip only (Correction A: scenario-select path)."""
    from app.v2.router import _build_toolbar_state_oob, _fmt_runtime_at

    ctx = {
        "has_runtime": bool(getattr(ws, "last_runtime_snapshot_id", None)),
        "ws_dirty": bool(getattr(ws, "dirty", True)),
        "runtime_is_stale": (
            bool(getattr(ws, "dirty", True))
            if runtime_is_stale is None else runtime_is_stale
        ),
        "last_runtime_at": _fmt_runtime_at(
            getattr(ws, "last_runtime_at", None) or ""),
    }
    return _build_toolbar_state_oob(ctx)
