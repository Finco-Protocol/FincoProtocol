"""Authorized read-only presentation refreshes; no writer or financial authority."""
from fastapi.responses import HTMLResponse

from app.v2.post_run_context import PostRunContextChanged, PostRunRequestContext
from app.workbook.workbook_identity import WorkbookIdentityError
from app.services.model_performance import span

PRESENTATION_SHEETS = frozenset({"capex", "opex", "revenue", "project_setup", "tax", "debt",
                                 "investor", "returns", "fs", "inputs", "run_history"})


def _capture(record, owner, expected_hash):
    with span("snapshot_capture"):
        context = PostRunRequestContext.capture(owner_id=owner, project_id=record.project_id)
    if not expected_hash or context.inputs.content_hash != expected_hash:
        raise PostRunContextChanged("Presentation identity changed")
    return context


def _finish(context, response):
    with span("coherence_check"):
        context.validate_current()
    response.headers.update({"Cache-Control": "no-store", "X-Finco-View-Hash": context.inputs.content_hash})
    return response


def _changed():
    return HTMLResponse('<p role="alert">The model changed while this view loaded. Reload the view to continue.</p>',
                        status_code=409, headers={"Cache-Control": "no-store"})


def render_saved_grid(request, record, owner, project, expected_hash, *, include_shared_state=True):
    from app.v2 import router as views
    from app.v2.post_run_ui import build_post_save_ui_state
    try:
        context = _capture(record, owner, expected_hash)
        ws, pis = context.workspace, context.inputs
        ctx = views._base_sheet_ctx(request, pis, ws, context.project_record, project, freshness=context.freshness)
        ctx.update(views._build_input_grid_ctx(context.project_record, pis, ws, owner,
                                              project_editable=ctx["project_editable"]))
        with span("template_render"):
            html = views._templates.get_template("partials/sheet_input_grid.html").render(ctx)
        if include_shared_state:
            html += build_post_save_ui_state(ws_fresh=ws, project_record=context.project_record,
                project=project, workspace_owner=owner, request=request, context=context,
                include_banner_and_controls=True, include_heavy_sheets=False)
        return _finish(context, HTMLResponse(html))
    except (PostRunContextChanged, WorkbookIdentityError, PermissionError):
        return _changed()


def render_sheet(request, record, owner, project, sheet, expected_hash):
    from app.v2 import router as views
    try:
        context = _capture(record, owner, expected_hash)
        ws, pis, record = context.workspace, context.inputs, context.project_record
        renderers = {"capex": views._render_capex_htmx_sheet, "opex": views._render_opex_htmx_sheet,
            "revenue": views._render_revenue_htmx_sheet, "project_setup": views._render_htmx_sheet,
            "tax": views._render_tax_htmx_sheet, "debt": views._render_debt_htmx_sheet,
            "fs": views._render_financial_statements_htmx_sheet, "inputs": views._render_inputs_htmx_sheet}
        with span("template_render"):
            if sheet in renderers:
                kwargs = {"workspace_owner": owner} if sheet == "capex" else {}
                response = renderers[sheet](request, pis, ws, record, project, **kwargs)
            else:
                ctx = views._base_sheet_ctx(request, pis, ws, record, project, freshness=context.freshness)
                if sheet == "returns":
                    ctx.update(views._build_returns_ctx(ws, rr=context.runtime_result,
                                                       runtime_is_stale=context.freshness.is_stale))
                    template = "sheet_returns.html"
                elif sheet == "investor":
                    ctx.update(views._build_debt_ctx(pis, ws, projection=context.projection, context=context))
                    template = "sheet_investor.html"
                else:
                    ctx.update(views._run_history_listing_ctx(record, ws, pis, freshness=context.freshness))
                    template = "sheet_run_history.html"
                response = HTMLResponse(views._templates.get_template("partials/" + template).render(ctx))
        return _finish(context, response)
    except (PostRunContextChanged, WorkbookIdentityError, PermissionError):
        return _changed()
