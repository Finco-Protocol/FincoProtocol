"""Q4 read-only preview, signed confirmation, and immutable Run comparison."""
from __future__ import annotations

from html import escape as e
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.auth import resolve_request_session
from app.persistence.projects_repository import resolve_accessible_project
from app.services.project_library_service import is_protected_reference
from app.utils.workbook_flag import require_v2_active
from app.v2.whatif import Q4Rejected, preview, commit

router = APIRouter()


def _scope(request, project: str):
    user = resolve_request_session(request)
    if not user:
        raise Q4Rejected("Q4_UNAUTHENTICATED", 401)
    record, owner = resolve_accessible_project(user.user_id, project)
    if not record:
        raise Q4Rejected("Q4_PROJECT_NOT_FOUND", 404)
    # This first version never writes through a shared project.
    if owner != user.user_id or is_protected_reference(record):
        raise Q4Rejected("Q4_PROJECT_READ_ONLY", 403)
    return record, owner


def _error(exc: Q4Rejected):
    return HTMLResponse(
        '<p class="v2-sp-q4-error" role="alert" data-testid="q4-rejected">'
        + e(exc.code) + " — Nothing was changed. Reopen Findings to refresh.</p>",
        status_code=exc.status)


@router.post("/workbook/whatif/preview", response_class=HTMLResponse)
async def q4_preview(request: Request,
                     project: str = Form(...), check_id: str = Form(...),
                     proposed_value: str = Form(...),
                     scenario_name: str = Form(...),
                     _: None = Depends(require_v2_active)):
    try:
        record, owner = _scope(request, project)
        if len(proposed_value) > 100 or len(check_id) > 50:
            raise Q4Rejected("Q4_INPUT_TOO_LONG", 422)
        result = preview(
            owner=owner, project_id=record.project_id,
            project_type=record.project_type or "",
            check_id=check_id, proposed_raw=proposed_value,
            scenario_name=scenario_name)
    except Q4Rejected as exc:
        return _error(exc)
    except Exception:
        return _error(Q4Rejected("Q4_PREVIEW_AUTHORITY_UNAVAILABLE"))

    warning = ('<p role="alert">STALE: the cited finding describes an earlier committed Run. '
               'This candidate is based on the CURRENT Working Copy input, not on recalculated financials.</p>'
               if result["stale"] else "")
    return HTMLResponse(
        '<section class="v2-sp-q4-preview" data-testid="q4-preview">'
        '<h4>What-if assumption preview — NOT A RUN</h4>'
        + warning
        + "<dl class=\"v2-sp-facts\">"
        + "<dt>Q1 finding</dt><dd>" + e(result["finding_id"]) + " · " + e(result["finding_status"]) + "</dd>"
        + "<dt>Source</dt><dd>" + e(result["evidence_source"]) + "</dd>"
        + "<dt>Last Run snapshot</dt><dd>" + e(str(result["snapshot_id"] or "UNAVAILABLE")) + "</dd>"
        + "<dt>New scenario</dt><dd>" + e(result["name"]) + " (not created)</dd>"
        + "<dt>Canonical field</dt><dd>" + e(result["field_id"]) + "</dd>"
        + "<dt>Override key</dt><dd>" + e(result["override_key"]) + "</dd>"
        + "<dt>Original input</dt><dd>" + e(str(result["original"])) + " " + e(result["unit"]) + "</dd>"
        + "<dt>Proposed input</dt><dd>" + e(str(result["proposed"])) + " " + e(result["unit"]) + "</dd>"
        + "<dt>Assumption delta</dt><dd>" + e(str(result["delta"])) + " " + e(result["unit"]) + "</dd>"
        + "<dt>Workspace identity</dt><dd><code>" + e(result["content_hash"]) + "</code></dd></dl>"
        + "<p>Not an optimized result or lender decision. No projected KPI, "
          "covenant compliance, Quality score or engine output exists until Run.</p>"
        + '<form hx-post="/v2/workbook/whatif/commit" hx-target="#q4-action-result" hx-swap="innerHTML" method="post">'
        + '<input type="hidden" name="project" value="' + e(project, quote=True) + '">'
        + '<input type="hidden" name="token" value="' + e(result["token"], quote=True) + '">'
        + '<label><input type="checkbox" name="confirmed" value="yes" required> '
          "I confirm creation of this independent What-if scenario with the exact assumptions above.</label>"
        + '<button class="v2-sp-action" type="submit">Confirm and create What-if</button></form>'
        + "</section>")


@router.post("/workbook/whatif/commit", response_class=HTMLResponse)
async def q4_commit(request: Request, project: str = Form(...),
                    token: str = Form(...), confirmed: str = Form(""),
                    _: None = Depends(require_v2_active)):
    try:
        if confirmed != "yes":
            raise Q4Rejected("Q4_EXPLICIT_CONFIRMATION_REQUIRED", 422)
        record, owner = _scope(request, project)
        if len(token) > 8192:
            raise Q4Rejected("Q4_CONFIRMATION_INVALID_OR_EXPIRED", 422)
        result = commit(owner=owner, project_id=record.project_id,
                        project_type=record.project_type or "", token=token)
    except Q4Rejected as exc:
        return _error(exc)
    except Exception:
        return _error(Q4Rejected("Q4_TRANSACTION_ROLLED_BACK"))

    workbook = "/v2/workbook?project=" + quote(project, safe="")
    compare = ("/v2/workbook/whatif/compare?project=" + quote(project, safe="")
               + "&scenario_id=" + quote(result["scenario_id"], safe=""))
    return HTMLResponse(
        '<section data-testid="q4-created" role="status"><h4>What-if scenario created — NOT_RUN</h4>'
        "<p>" + e(result["scenario_name"]) + " · ID " + e(result["scenario_id"]) + "</p>"
        "<p>The Base Case, selected scenario and Last Run are unchanged. "
        "No KPI comparison exists yet. Select the new scenario and explicitly press Run.</p>"
        '<p><a href="' + e(workbook, quote=True) + '">Open Scenarios workspace</a>'
        ' · <a href="' + e(compare, quote=True) + '">View committed comparison</a></p>'
        "</section>")


@router.get("/workbook/whatif/compare", response_class=HTMLResponse)
async def q4_compare(request: Request, project: str, scenario_id: str,
                     _: None = Depends(require_v2_active)):
    try:
        record, owner = _scope(request, project)
        from app.persistence.scenarios_repository import get_base_case_scenario, get_scenario
        from app.persistence.scenario_insight_reads import newest_committed_runs, HISTORY_UNAVAILABLE
        from app.model_quality import evaluate_model_quality
        from app.model_quality.evidence import evidence_from_history_entry
        from app.v2.insight_scenario_projection import COMPARE_KEYS
        from app.v2.run_history_projection import _enriched_kpis
        from app.v2.scenario_kpi_projection import build_compare_rows, build_scenario_projection

        base = get_base_case_scenario(user_id=owner, project_id=record.project_id)
        child = get_scenario(scenario_id=scenario_id, user_id=owner)
        if not base or not child or child.project_id != record.project_id or child.is_base_case:
            raise Q4Rejected("Q4_SCENARIO_UNAVAILABLE", 404)
        runs = newest_committed_runs(owner, record.project_id, [base, child])
        old, new = runs.get(base.scenario_id, HISTORY_UNAVAILABLE), runs.get(child.scenario_id, HISTORY_UNAVAILABLE)
        if old == HISTORY_UNAVAILABLE or new == HISTORY_UNAVAILABLE:
            raise Q4Rejected("Q4_RUN_HISTORY_UNAVAILABLE")
        if new is None:
            return HTMLResponse('<section data-testid="q4-compare-not-run">'
                                '<h3>What-if NOT_RUN</h3><p>Run the selected scenario explicitly. '
                                "No projected KPI or Quality result is available.</p></section>")
        if old is None:
            return HTMLResponse('<section data-testid="q4-compare-no-base">'
                                '<h3>Base committed Run UNAVAILABLE</h3>'
                                '<p>Comparison needs a committed Base Run; nothing is estimated.</p></section>')
        if (old.user_id != owner or new.user_id != owner or
                old.project_id != record.project_id or new.project_id != record.project_id):
            raise Q4Rejected("Q4_RUN_OWNER_PROVENANCE_INVALID", 403)
        if new.last_runtime_scenario_id != child.scenario_id or old.last_runtime_scenario_id not in (None, base.scenario_id):
            raise Q4Rejected("Q4_RUN_SCENARIO_PROVENANCE_INVALID")

        old_proj = build_scenario_projection(base.scenario_name, _enriched_kpis(old), old.ran_at, True)
        new_proj = build_scenario_projection(child.scenario_name, _enriched_kpis(new), new.ran_at, True)
        rows = [r for r in build_compare_rows([old_proj, new_proj]) if r.key in COMPARE_KEYS]
        old_q = evaluate_model_quality(evidence_from_history_entry(old, active_scenario_id=base.scenario_id,
                                                                    scenario_known=True))
        new_q = evaluate_model_quality(evidence_from_history_entry(new, active_scenario_id=child.scenario_id,
                                                                    scenario_known=True))
        checks_old = {c.check_id: c.status.value for c in old_q.checks}
        quality_rows = [(c.check_id, checks_old.get(c.check_id, "UNAVAILABLE"), c.status.value)
                        for c in new_q.checks if checks_old.get(c.check_id) != c.status.value]
        def identity(entry, label):
            return ("<li><b>" + e(label) + "</b> · history " + e(str(entry.history_id))
                    + " · snapshot " + e(str(entry.runtime_snapshot_id))
                    + " · composite " + e(str(entry.composite_hash))
                    + " · run " + e(str(entry.ran_at))
                    + " · engine " + e(str(entry.engine_version)) + "</li>")
        html = ('<section data-testid="q4-committed-compare"><h2>Base vs What-if — committed Runs only</h2>'
                '<p>Both columns are historical immutable Run evidence. No current contractual'
                ' threshold is imputed to either Run.</p><ul>'
                + identity(old, "Base") + identity(new, "What-if") + "</ul>"
                '<table><thead><tr><th>Metric</th><th>Base</th><th>What-if</th><th>Delta</th></tr></thead><tbody>'
                + "".join("<tr><th>" + e(r.label) + "</th><td>" + e(r.values[0])
                           + "</td><td>" + e(r.values[1]) + "</td><td>" + e(r.deltas[1]) + "</td></tr>"
                           for r in rows) + "</tbody></table>"
                '<h3>Model Quality advisory</h3>'
                '<p>Base score: ' + e(str(old_q.summary.score) if old_q.summary.score is not None else "NOT SCORED")
                + ' · What-if score: ' + e(str(new_q.summary.score) if new_q.summary.score is not None else "NOT SCORED") + '</p>'
                '<p>Evidence coverage: Base ' + e(str(old_q.summary.coverage_weighted))
                + ' · What-if ' + e(str(new_q.summary.coverage_weighted)) + '</p>'
                '<h3>Changed check statuses</h3><ul>'
                + "".join("<li>" + e(cid) + ": " + e(prior) + " → " + e(after) + "</li>"
                          for cid, prior, after in quality_rows)
                + '</ul><p>Q1 advisory does not certify lender compliance. '
                  'Check Run History for underlying canonical Integrity evidence.</p></section>')
        return HTMLResponse(html)
    except Q4Rejected as exc:
        return _error(exc)
    except Exception:
        return _error(Q4Rejected("Q4_COMPARISON_UNAVAILABLE"))
