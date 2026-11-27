"""Real Chromium Option C acceptance, with CSP enabled and isolated synthetic projects."""
import os
from pathlib import Path

import pytest

from tests.test_project_lifecycle_browser import wf03_servers, wf03_browser as _wf03_browser  # noqa: F401


@pytest.fixture
def wf03_browser(request):
    # Keep the helper module unchanged and the selected cases individually attributable.
    pytest.importorskip("playwright.sync_api", reason="playwright not installed in this workflow")
    return request.getfixturevalue("_wf03_browser")


@pytest.mark.parametrize('template',['generic_solar_reference','generic_wind_reference','generic_data_center_reference','generic_ev_charging_reference'])
@pytest.mark.parametrize('width',[320,390,768,1440])
@pytest.mark.parametrize('theme',[None,'b-slate-teal','d-high-contrast','g-forest-green-white'])
def test_wf03_https_visible_archive_restore_matrix(wf03_servers,wf03_browser,template,width,theme):
    from tests.test_project_lifecycle_browser import check_visible_https_archive_restore_matrix
    check_visible_https_archive_restore_matrix(wf03_servers,wf03_browser,template,width,theme)


def test_wf03_stale_library_refresh_cannot_overwrite_archived_view_browser(wf03_servers,wf03_browser):
    from tests.test_project_lifecycle_browser import check_stale_library_refresh_cannot_overwrite_the_archived_view
    check_stale_library_refresh_cannot_overwrite_the_archived_view(wf03_servers,wf03_browser)


def test_wf03_reload_after_lost_response_reads_authoritative_state_browser(wf03_servers,wf03_browser):
    from tests.test_project_lifecycle_browser import check_reload_after_lost_response_reads_authoritative_state_and_persists_nothing
    check_reload_after_lost_response_reads_authoritative_state_and_persists_nothing(wf03_servers,wf03_browser)


def test_wf03_blank_setup_durable_non_runnable_browser(wf03_servers,wf03_browser):
    from tests.test_project_lifecycle_browser import check_blank_setup_is_durable_explicit_and_non_runnable
    check_blank_setup_is_durable_explicit_and_non_runnable(wf03_servers,wf03_browser)


def test_wf03_lost_response_restore_original_replay_browser(wf03_servers,wf03_browser):
    from tests.test_project_lifecycle_browser import check_lost_archive_response_then_restore_and_original_replay
    check_lost_archive_response_then_restore_and_original_replay(wf03_servers,wf03_browser)

from tests.test_workflow_c_browser_v1 import live_server, browser  # noqa: F401
from tests.test_model_mutation_cookie_policy_acceptance import mutation_browser_servers  # noqa: F401


def test_model_mutation_secure_cookie_policy(mutation_browser_servers, tmp_path):
    from tests.test_model_mutation_cookie_policy_acceptance import (
        test_verified_secure_lax_policy_same_origin_same_site_and_cross_site,
    )
    test_verified_secure_lax_policy_same_origin_same_site_and_cross_site(mutation_browser_servers, tmp_path)


def assert_unique_dom_ids(page):
    duplicates = page.evaluate("""() => {
        const ids = Array.from(document.querySelectorAll('[id]'), node => node.id);
        return [...new Set(ids.filter((id, index) => ids.indexOf(id) !== index))];
    }""")
    assert duplicates == [], duplicates


def test_trust_diagnostics_and_history_render_exact_contracts_without_automatic_actions(browser, tmp_path):
    import json
    from urllib.parse import urlparse
    ROOT = Path(__file__).resolve().parents[1]

    integrity = {"overall": "INCOMPLETE", "counts": {"PASS": 0, "UNAVAILABLE": 9},
                 "run_identity": {"snapshot_id": "snapshot-contract-123"},
                 "checks": [{"check_id": "balance", "title": "Balance reconciliation",
                             "status": "UNAVAILABLE", "detail": "Evidence is absent"}]}
    payloads = {
        "workspace": {"ok": True, "react_workspace": {"version": "ux02-v1"}, "project": {"code": "p", "name": "Contract replay", "project_type": "solar", "protected_reference": False},
                      "workbook": {"version": "2.0", "composite_hash": "hash-contract", "scenario_id": "scenario-b", "scenario_name": "Scenario B"},
                      "freshness": {"state": "CURRENT", "basis": "canonical", "has_runtime": True, "is_stale": False},
                      "identity": {"snapshot_id": "snapshot-contract-123", "ran_at": "2026-10-25", "scenario": "Scenario B", "scenario_proven": True},
                      "integrity": {"status": "INCOMPLETE", "counts": {}, "failures": []}, "integrity_available": True,
                      "engine": {"currency": "CURRENT_ENGINE"}},
        "trust": {"ok": True, "run_state": "CURRENT", "identity": {"snapshot_id": "snapshot-contract-123"}, "integrity": integrity,
                  "validation": {"state": "DEFERRED", "scope": "Pinned reference only; not validation of this Working Copy", "load_url": "/v2/workbook/trust/validation?project=p"},
                  "certificate": {"state": "DEFERRED", "scope": "Provenance only; availability not established", "load_url": "/v2/workbook/trust/certificate?project=p"}},
        "diagnostics": {"ok": True, "run_state": "CURRENT", "integrity": integrity,
                        "insight": {"run_state": "CURRENT", "context_note": "Committed Run", "not_claims": "Not Verify"},
                        "diagnostics": {"state": "CURRENT", "checks": [{"check_id": "balance", "label": "Balance reconciliation", "status": "UNAVAILABLE", "note": "Evidence is absent"}]}},
        "statements": {"ok": True, "project": {"name": "Contract replay"}, "state": "CURRENT", "snapshot": None,
                       "status": {"runId": "snapshot-contract-123", "freshness": "current", "integrity": "not evaluated", "engineVersion": "engine-contract", "dataOrigin": "caller-provided"},
                       "results": {"available": False}, "integrity_available": True, "integrity": {"status": "INCOMPLETE"}},
        "runs": {"ok": True, "project": {"protected_reference": False}, "run_contract": {"url": "/v2/workbook/run"},
                 "runs": [{"history_id": "history-contract", "runtime_snapshot_id": "snapshot-contract-123", "runtime_origin": "canonical-v2", "ran_at": "2026-10-25", "active_scenario_id": "scenario-b", "active_scenario_name": "Scenario B", "engine_version": "engine-contract", "composite_hash": "hash-contract"}]},
    }
    actions = []
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    def route(request_route):
        request = request_route.request
        path = urlparse(request.url).path
        if request.method not in ("GET", "HEAD"):
            actions.append(request.url)
            return request_route.abort()
        if path.startswith("/v2/workbook/"):
            actions.append(request.url)
            return request_route.abort()
        if path.startswith("/static/"):
            target = ROOT / path.lstrip("/")
            if target.is_file():
                return request_route.fulfill(path=str(target), content_type="application/javascript" if target.suffix == ".js" else "text/css")
            return request_route.fulfill(status=404, body="")
        key = path.rsplit("/", 1)[-1]
        if key in payloads:
            return request_route.fulfill(content_type="application/json", body=json.dumps(payloads[key]))
        return request_route.fulfill(content_type="text/html", body='''<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="/static/react/finco-react.css"><div id="finco-react-root" data-project="p" data-bootstrap-url="/v2/model-react/bootstrap" data-save-url="/v2/workbook/grid/save" data-validate-url="/v2/workbook/grid/validate" data-legacy-url="/v2/workbook?project=p"></div><script src="/static/react/finco-react.js"></script>''')
    context.route("**/*", route)
    try:
        page.goto("http://rc-ux-b.invalid/v2/model-react/p#trust")
        section = page.get_by_role("region", name="Trust and integrity evidence", exact=True)
        section.wait_for()
        assert "INCOMPLETE" in section.inner_text()
        assert "snapshot-contract-123" in section.inner_text()
        assert "not validation of this project" in section.inner_text()
        # Addendum A: the evidence is requested from React (an explicit button, never a link to a classic page) and nothing runs on load
        assert page.locator("[data-trust-load='validation']").is_enabled() and page.locator("[data-trust-load='certificate']").is_enabled()
        assert page.locator("section[aria-label='Trust and integrity evidence'] a[href*='/v2/workbook']").count() == 0
        assert len(actions) == 0
        page.screenshot(path=str(tmp_path / "trust-contract-replay.png"), full_page=True)
        page.goto("http://rc-ux-b.invalid/v2/model-react/p#diagnostics")
        checks = page.get_by_role("region", name="Model checks and diagnostics", exact=True)
        checks.wait_for()
        assert "Run state: CURRENT" in checks.inner_text()
        assert "Balance reconciliation" in checks.inner_text()
        assert "Evidence is absent" in checks.inner_text()
        page.screenshot(path=str(tmp_path / "diagnostics-contract-replay.png"), full_page=True)
        page.goto("http://rc-ux-b.invalid/v2/model-react/p#results")
        history = page.get_by_role("region", name="Run history", exact=True)
        history.wait_for()
        assert "Scenario B" in history.inner_text()
        assert "canonical-v2" in history.inner_text()
        assert "hash-contract" in history.inner_text()
        assert "snapshot-contract-123" in history.inner_text()
        page.screenshot(path=str(tmp_path / "history-contract-replay.png"), full_page=True)
        assert not errors
        assert not actions
    except Exception:
        print("Browser errors:", errors)
        print("Rendered body:", page.locator("body").inner_text())
        raise
    finally:
        context.close()


# ── WF-React-1 (PR #377): Product Truth & Financial Workspace acceptance ───────────────
# Additive acceptance in the EXISTING mandatory consolidation role (shared Playwright
# fixture lifecycle; no module-level skip of its own).  The bodies live in
# tests/model_react_wf1_browser_acceptance.py, like the diagnostics acceptance above.

@pytest.fixture
def react_enabled(live_server):
    """The flag is read per request inside the server process, so setting it here
    switches the already-running live server onto the React surface."""
    old = os.environ.get('FINCO_MODEL_REACT_V1')
    os.environ['FINCO_MODEL_REACT_V1'] = '1'
    yield live_server
    if old is None:
        os.environ.pop('FINCO_MODEL_REACT_V1', None)
    else:
        os.environ['FINCO_MODEL_REACT_V1'] = old


@pytest.fixture
def seeded(browser, react_enabled):
    from tests.model_react_wf1_browser_acceptance import make_session
    context, page, record, errors = make_session(browser, react_enabled, 'wf1-user')
    try:
        yield context, page, record, errors, react_enabled
    finally:
        context.close()


def test_product_truth_no_prototype_or_synthetic_content_in_any_section(seeded):
    from tests.model_react_wf1_browser_acceptance import check_product_truth_no_prototype_or_synthetic_content_in_any_section
    check_product_truth_no_prototype_or_synthetic_content_in_any_section(seeded)


def test_statement_units_ratios_negatives_and_rounding_match_canonical_api(seeded):
    from tests.model_react_wf1_browser_acceptance import check_statement_units_ratios_negatives_and_rounding_match_canonical_api
    check_statement_units_ratios_negatives_and_rounding_match_canonical_api(seeded)


def test_results_and_analysis_values_are_the_canonical_values_of_the_same_run(seeded):
    from tests.model_react_wf1_browser_acceptance import check_results_and_analysis_values_are_the_canonical_values_of_the_same_run
    check_results_and_analysis_values_are_the_canonical_values_of_the_same_run(seeded)


def test_current_stale_not_run_are_consistent_across_every_surface(seeded):
    from tests.model_react_wf1_browser_acceptance import check_current_stale_not_run_are_consistent_across_every_surface
    check_current_stale_not_run_are_consistent_across_every_surface(seeded)


def test_library_search_pagination_and_reference_working_copy_status(browser, react_enabled):
    from tests.model_react_wf1_browser_acceptance import check_library_search_pagination_and_reference_working_copy_status
    check_library_search_pagination_and_reference_working_copy_status(browser, react_enabled)


def test_results_analysis_navigation_and_back_forward(seeded):
    from tests.model_react_wf1_browser_acceptance import check_results_analysis_navigation_and_back_forward
    check_results_analysis_navigation_and_back_forward(seeded)


@pytest.mark.parametrize('name,viewport', [('desktop', {'width': 1440, 'height': 1000}),
                                           ('tablet', {'width': 820, 'height': 1100}),
                                           ('mobile', {'width': 390, 'height': 844})])
def test_responsive_layout_has_no_page_level_horizontal_overflow(browser, react_enabled, name, viewport):
    from tests.model_react_wf1_browser_acceptance import check_responsive_layout_has_no_page_level_horizontal_overflow
    check_responsive_layout_has_no_page_level_horizontal_overflow(browser, react_enabled, name, viewport)


# ── WF-React-2 (PR #378): editable model workflow acceptance ───────────────────────────
# Additive acceptance in the EXISTING mandatory consolidation role (shared Playwright
# fixture lifecycle; no module-level skip of its own).  The bodies live in
# tests/model_react_wf2_browser_acceptance.py, like the WF-React-1 acceptance above.

def test_wf2_workflow_bar_and_sections_render_without_errors(browser, react_enabled):
    from tests.model_react_wf2_browser_acceptance import check_workflow_bar_and_sections_render_without_errors
    check_workflow_bar_and_sections_render_without_errors(browser, react_enabled)


def test_wf2_end_to_end_supported_workflow_save_never_runs_and_run_only_when_explicit(browser, react_enabled):
    from tests.model_react_wf2_browser_acceptance import check_end_to_end_supported_workflow_save_never_runs_and_run_only_when_explicit
    check_end_to_end_supported_workflow_save_never_runs_and_run_only_when_explicit(browser, react_enabled)


def test_wf2_guided_ppa_editor_creates_edits_and_schedules_a_contract_book(browser, react_enabled):
    from tests.model_react_wf2_browser_acceptance import check_guided_ppa_editor_creates_edits_and_schedules_a_contract_book
    check_guided_ppa_editor_creates_edits_and_schedules_a_contract_book(browser, react_enabled)


def test_r1_stale_ppa_document_is_never_replayed_by_a_second_tab(browser, react_enabled):
    from tests.model_react_r1_ppa_two_tab_acceptance import check_r1_stale_ppa_document_is_never_replayed_by_a_second_tab
    check_r1_stale_ppa_document_is_never_replayed_by_a_second_tab(browser, react_enabled)


def test_g_r04_editor_cap_review_save_refusal_reload_and_responsive(browser, react_enabled):
    from tests.model_react_r04_acceptance import check_r04_editor_cap_review_save_refusal_reload_run_and_responsive
    check_r04_editor_cap_review_save_refusal_reload_run_and_responsive(browser, react_enabled)


def test_g_r04_persisted_invalid_book_recovery_in_the_real_react_workspace(browser, react_enabled):
    from tests.model_react_r04_acceptance import check_r04_persisted_invalid_book_recovery_in_the_real_react_workspace
    check_r04_persisted_invalid_book_recovery_in_the_real_react_workspace(browser, react_enabled)


def test_g_r04_share_only_legacy_flow_is_unchanged(browser, react_enabled):
    from tests.model_react_r04_acceptance import check_r04_share_only_legacy_flow_is_unchanged
    check_r04_share_only_legacy_flow_is_unchanged(browser, react_enabled)


def test_wf2_stale_cas_cannot_overwrite_and_keeps_the_draft(browser, react_enabled):
    from tests.model_react_wf2_browser_acceptance import check_stale_cas_cannot_overwrite_and_keeps_the_draft
    check_stale_cas_cannot_overwrite_and_keeps_the_draft(browser, react_enabled)


def test_wf2_rejected_csrf_token_changes_nothing_and_keeps_the_draft(browser, react_enabled):
    from tests.model_react_wf2_browser_acceptance import check_rejected_csrf_token_changes_nothing_and_keeps_the_draft
    check_rejected_csrf_token_changes_nothing_and_keeps_the_draft(browser, react_enabled)


@pytest.mark.parametrize('scenario', ['field-save', 'cost-add', 'run'])
def test_wf2_unknown_outcomes_are_reconciled_never_retried(browser, react_enabled, scenario):
    from tests.model_react_wf2_browser_acceptance import check_unknown_outcomes_are_reconciled_never_retried
    check_unknown_outcomes_are_reconciled_never_retried(browser, react_enabled, scenario)


def test_wf2_protected_reference_workspace_is_read_only_in_every_editor(browser, react_enabled):
    from tests.model_react_wf2_browser_acceptance import check_protected_reference_workspace_is_read_only_in_every_editor
    check_protected_reference_workspace_is_read_only_in_every_editor(browser, react_enabled)


def test_wf2_scenario_selection_compare_and_overrides_are_isolated_and_never_run(browser, react_enabled):
    from tests.model_react_wf2_browser_acceptance import check_scenario_selection_compare_and_overrides_are_isolated_and_never_run
    check_scenario_selection_compare_and_overrides_are_isolated_and_never_run(browser, react_enabled)


@pytest.mark.parametrize('width,height', [(1440, 900), (900, 1000), (390, 844)])
def test_wf2_editable_sections_fit_desktop_tablet_and_mobile(browser, react_enabled, width, height):
    from tests.model_react_wf2_browser_acceptance import check_editable_sections_fit_desktop_tablet_and_mobile
    check_editable_sections_fit_desktop_tablet_and_mobile(browser, react_enabled, width, height)


# ── PR #378 Correction B: unsaved-input integrity, navigation protection, Run safety ───
# Bodies in tests/model_react_wf2_lifecycle_acceptance.py (no module-level skip there).

@pytest.mark.parametrize('check', [
    'check_grid_draft_counts_blocks_run_and_unchanged_values_are_not_dirty',
    'check_navigation_with_unsaved_edits_asks_and_keeps_the_draft',
    'check_verified_save_clears_dirty_updates_identity_and_enables_an_explicit_run',
    'check_failed_stale_and_unknown_saves_keep_drafts_and_locks_without_duplicates',
    'check_every_editor_reports_unsaved_work_and_guards_navigation',
    'check_rapid_repeated_activation_starts_at_most_one_run',
    'check_run_is_blocked_while_a_save_is_in_flight',
    'check_drafts_never_transfer_to_another_scenario_or_project',
    'check_protected_reference_grid_cannot_stage_or_save',
    'check_pending_mutations_cannot_escape_their_reconciliation_contract',
])
def test_wf2_lifecycle_acceptance(browser, react_enabled, check):
    import tests.model_react_wf2_lifecycle_acceptance as lifecycle
    getattr(lifecycle, check)(browser, react_enabled)


# ── RC-REACT-MVP: integrated Financial Insights + Internal MVP acceptance ───────────────
# Bodies in tests/model_react_mvp_acceptance.py (no module-level skip there).

def test_mvp_library_clone_creates_an_openable_unprotected_working_copy(browser, react_enabled):
    from tests.model_react_mvp_acceptance import check_library_clone_creates_an_openable_unprotected_working_copy
    check_library_clone_creates_an_openable_unprotected_working_copy(browser, react_enabled)


@pytest.mark.parametrize('kind', ['solar', 'wind'])
def test_mvp_internal_path_with_financial_intelligence(browser, react_enabled, kind):
    from tests.model_react_mvp_acceptance import check_internal_mvp_path_with_financial_intelligence
    check_internal_mvp_path_with_financial_intelligence(browser, react_enabled, kind)


def test_mvp_responsive_insights_and_touch_targets(browser, react_enabled):
    from tests.model_react_mvp_acceptance import check_responsive_insights_and_touch_targets
    check_responsive_insights_and_touch_targets(browser, react_enabled)


# ── D-029: Run intent (idempotency), React + Legacy ────────────────────────────────────
# Bodies in tests/model_d029_run_intent_browser_acceptance.py (no module-level skip there).

@pytest.mark.parametrize('check', [
    'check_react_run_sends_a_uuid_intent_and_consumes_it_on_commit',
    'check_react_lost_response_survives_reload_and_resumes_the_original_run',
    'check_react_resume_after_the_draft_changed_never_runs_against_the_new_draft',
    'check_react_typed_outcomes_keep_or_consume_the_intent',
])
def test_d029_react_run_intent_acceptance(browser, react_enabled, check):
    import tests.model_d029_run_intent_browser_acceptance as d029
    getattr(d029, check)(browser, react_enabled)


@pytest.mark.parametrize('check', [
    'check_legacy_run_carries_a_uuid_and_consumes_it_on_commit',
    'check_legacy_lost_response_reload_and_oob_refresh_keep_the_same_run',
    'check_legacy_queued_run_after_pending_save_keeps_one_key_and_the_saved_binding',
])
def test_d029_legacy_run_intent_acceptance(browser, live_server, check):
    import tests.model_d029_run_intent_browser_acceptance as d029
    getattr(d029, check)(browser, live_server)


# ── Overnight B: React Institutional Model MVP correction ───────────────────────────────────────────────
# Bodies in tests/model_react_overnight_b_acceptance.py (no module-level skip there).  Additive: no existing node id changes.

@pytest.mark.parametrize('kind', ['solar', 'wind', 'data_center', 'ev_charging'])
def test_onb_statement_identity_is_the_authorized_project_in_every_vertical(browser, react_enabled, kind):
    from tests.model_react_overnight_b_acceptance import check_statement_identity_is_the_authorized_project_in_every_vertical
    check_statement_identity_is_the_authorized_project_in_every_vertical(browser, react_enabled, kind)


def test_onb_hostile_or_stale_query_cannot_change_the_statement_identity(browser, react_enabled):
    from tests.model_react_overnight_b_acceptance import check_hostile_or_stale_query_cannot_change_the_statement_identity
    check_hostile_or_stale_query_cannot_change_the_statement_identity(browser, react_enabled)


def test_onb_switching_projects_never_carries_the_previous_statement_identity(browser, react_enabled):
    from tests.model_react_overnight_b_acceptance import check_switching_projects_never_carries_the_previous_statement_identity
    check_switching_projects_never_carries_the_previous_statement_identity(browser, react_enabled)


def test_onb_missing_or_conflicting_identity_fails_visibly(browser, react_enabled):
    from tests.model_react_overnight_b_acceptance import check_missing_or_conflicting_identity_fails_visibly
    check_missing_or_conflicting_identity_fails_visibly(browser, react_enabled)


def test_onb_two_runs_in_the_same_hour_are_distinguishable_everywhere(browser, react_enabled):
    from tests.model_react_overnight_b_acceptance import check_two_runs_in_the_same_hour_are_distinguishable_everywhere
    check_two_runs_in_the_same_hour_are_distinguishable_everywhere(browser, react_enabled)


def test_onb_scenario_comparison_and_results_refer_to_the_intended_run(browser, react_enabled):
    from tests.model_react_overnight_b_acceptance import check_scenario_comparison_and_results_refer_to_the_intended_run
    check_scenario_comparison_and_results_refer_to_the_intended_run(browser, react_enabled)


def test_onb_inputs_save_scope_language_is_accurate(browser, react_enabled):
    from tests.model_react_overnight_b_acceptance import check_inputs_save_scope_language_is_accurate_and_free_of_engineering_copy
    check_inputs_save_scope_language_is_accurate_and_free_of_engineering_copy(browser, react_enabled)


def test_onb_scalar_save_persists_after_reload_and_never_saves_another_editor(browser, react_enabled):
    from tests.model_react_overnight_b_acceptance import check_scalar_save_persists_after_reload_and_never_saves_another_editor
    check_scalar_save_persists_after_reload_and_never_saves_another_editor(browser, react_enabled)


@pytest.mark.parametrize('kind,width,limit', [('solar', 1440, 6000), ('solar', 390, 10000), ('data_center', 390, 8000), ('ev_charging', 320, 9000)])
def test_onb_inputs_are_compact_complete_and_navigable(browser, react_enabled, kind, width, limit):
    from tests.model_react_overnight_b_acceptance import check_inputs_are_compact_complete_and_navigable
    check_inputs_are_compact_complete_and_navigable(browser, react_enabled, kind, width, limit)


def test_onb_protected_reference_inputs_stay_visible_and_read_only(browser, react_enabled):
    from tests.model_react_overnight_b_acceptance import check_protected_reference_inputs_stay_visible_and_read_only
    check_protected_reference_inputs_stay_visible_and_read_only(browser, react_enabled)


def test_onb_workspace_navigation_is_discoverable_and_keyboard_operable(browser, react_enabled):
    from tests.model_react_overnight_b_acceptance import check_workspace_navigation_is_discoverable_keyboard_operable_and_never_overflows_the_page
    check_workspace_navigation_is_discoverable_keyboard_operable_and_never_overflows_the_page(browser, react_enabled)


@pytest.mark.parametrize('kind', ['solar', 'data_center', 'ev_charging'])
def test_onb_labels_and_typography_have_no_duplicated_units_or_literal_escapes(browser, react_enabled, kind):
    from tests.model_react_overnight_b_acceptance import check_labels_and_typography_have_no_duplicated_units_or_literal_escapes
    check_labels_and_typography_have_no_duplicated_units_or_literal_escapes(browser, react_enabled, kind)


@pytest.mark.parametrize('kind', ['solar', 'wind', 'data_center', 'ev_charging'])
def test_onb_returns_lender_metrics_and_vertical_scope_are_truthful(browser, react_enabled, kind):
    from tests.model_react_overnight_b_acceptance import check_returns_lender_metrics_and_vertical_scope_are_truthful
    check_returns_lender_metrics_and_vertical_scope_are_truthful(browser, react_enabled, kind)


def test_onb_scenario_override_boundary_matches_the_canonical_capability(browser, react_enabled):
    from tests.model_react_overnight_b_acceptance import check_scenario_override_boundary_matches_the_canonical_capability
    check_scenario_override_boundary_matches_the_canonical_capability(browser, react_enabled)


def test_onb_every_theme_keeps_the_corrected_surfaces_legible(browser, react_enabled):
    from tests.model_react_overnight_b_acceptance import check_every_theme_keeps_the_corrected_surfaces_legible
    check_every_theme_keeps_the_corrected_surfaces_legible(browser, react_enabled)


# RC-M integrated React acceptance (New Project wizard, Analysis, Financing, Investors, all-theme legibility).
# The bodies live in non-collected modules (each ``__all__`` lists its tests and fixture), so the mandatory consolidation role
# executes them with its own fail-closed inventory / JUnit verifier and no collection-time skip is introduced.
from tests.model_react_rcm_support import rcm_react_flag  # noqa: E402,F401
from tests.model_react_rcm_new_project_acceptance import *  # noqa: E402,F401,F403
from tests.model_react_rcm_analysis_acceptance import *  # noqa: E402,F401,F403
from tests.model_react_rcm_financing_acceptance import *  # noqa: E402,F401,F403
from tests.model_react_rcm_investors_acceptance import *  # noqa: E402,F401,F403
from tests.model_react_rcm_themes_acceptance import *  # noqa: E402,F401,F403


# RC-UX Completion V1 (Audit A GAP-R13): React Analysis > Run history & compare.  Same pattern as RC-M: a non-collected acceptance module
# executed by this existing mandatory role, so no collection-time skip is introduced.
from tests.model_react_rcux_runs_acceptance import *  # noqa: E402,F401,F403
from tests.model_react_rcux_capex_acceptance import *  # noqa: E402,F401,F403
from tests.model_react_rcux_product_acceptance import *  # noqa: E402,F401,F403
from tests.model_react_rcux_whatif_acceptance import *  # noqa: E402,F401,F403
from tests.model_react_rcux_import_acceptance import *  # noqa: E402,F401,F403
from tests.model_react_rcux_navigation_acceptance import *  # noqa: E402,F401,F403
from tests.model_react_rcux_analysis_acceptance import *  # noqa: E402,F401,F403


# WS1 Workspace V2: approved mandatory acceptance; additive import only.
from tests.model_react_wsv2_acceptance import *  # noqa: E402,F401,F403


# WF-04 Debt Metrics: Owner-authorised mandatory acceptance; additive import only.
from tests.model_react_wf04_debt_metrics_acceptance import *  # noqa: E402,F401,F403

# UX-PR2b: additive real Chromium acceptance; existing mandatory cases remain intact.
from tests.model_react_ux_pr2b_acceptance import *  # noqa: E402,F401,F403

# PR3b-1: mounted one-screen read layer, compatibility editors and refusal acceptance.
from tests.model_react_pr3b1_acceptance import *  # noqa: E402,F401,F403

# PR3b-2: additive canonical block Save lifecycle acceptance.
from tests.model_react_pr3b2_acceptance import *  # noqa: E402,F401,F403


@pytest.fixture(autouse=True)
def _legacy_calendar_creation(monkeypatch):
    """FINCO45B: this module proves legacy 54-period matrix layout (the dated grid adds the final contractual stub); new Solar/Wind projects now default to OD-TIME-01/v1,
    where those semantics differ by design. Its projects are created through the explicit LEGACY creation rollback
    (FINCO_NEW_PROJECT_DATE_AUTHORITY=legacy), so the retained LEGACY_CALENDAR/v0 contract stays proved."""
    monkeypatch.setenv("FINCO_NEW_PROJECT_DATE_AUTHORITY", "legacy")

