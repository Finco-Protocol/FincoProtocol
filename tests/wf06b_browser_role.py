"""WF-06B real-Chromium runner (supplies fixtures to the acceptance bodies; also re-runs the WF-06A cost-grid body unchanged).

Deliberately NOT named ``test_*.py``: importing the shared browser fixtures skips the whole module when Playwright is absent, which would add a
collection skip to the accepted-source skip inventory in the Public Safety plan (``collection skip change``). Run it explicitly where Chromium
exists:  ``FINCO_TEST_CHROMIUM_PATH=<chrome> pytest tests/wf06b_browser_role.py``.  Wiring it into the mandatory browser role means editing
``tools/ci_browser_job.py`` / the consolidation module, which this PR does not own (ON-09B / owner decision).
"""
import pytest

from tests.model_react_rcm_support import rcm_react_flag  # noqa: F401
from tests.test_workflow_c_browser_v1 import live_server, browser  # noqa: F401


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_wf06b_workbench_matches_projection_and_hides_provenance(live_server, browser, rcm_react_flag, kind):
    from tests.model_react_wf06b_acceptance import check_cost_workbench_matches_the_server_projection_and_hides_provenance
    check_cost_workbench_matches_the_server_projection_and_hides_provenance(browser, live_server, kind)


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_wf06b_density_and_viewports(live_server, browser, rcm_react_flag, kind):
    from tests.model_react_wf06b_acceptance import check_density_toggle_and_viewports
    check_density_toggle_and_viewports(browser, live_server, kind)


def test_wf06b_workflow_bar_scope_and_no_invented_last_run(live_server, browser, rcm_react_flag):
    from tests.model_react_wf06b_acceptance import check_workflow_bar_discloses_save_scope_and_has_no_stale_without_a_run
    check_workflow_bar_discloses_save_scope_and_has_no_stale_without_a_run(browser, live_server)


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_wf06a_cost_grid_body_still_holds_at_every_width(live_server, browser, rcm_react_flag, kind):
    from tests.model_react_wf06a_acceptance import check_cost_lines_show_group_context_without_changing_keyboard_or_layout
    check_cost_lines_show_group_context_without_changing_keyboard_or_layout(browser, live_server, kind)


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_wf06b_compact_inputs_overview_two_column(live_server, browser, rcm_react_flag, kind):
    from tests.model_react_wf06b_acceptance import check_compact_inputs_overview_is_server_owned_and_two_column
    check_compact_inputs_overview_is_server_owned_and_two_column(browser, live_server, kind)


def test_wf06b_overview_committed_run_only_and_stale(live_server, browser, rcm_react_flag):
    from tests.model_react_wf06b_acceptance import check_overview_shows_only_the_committed_run_and_marks_stale
    check_overview_shows_only_the_committed_run_and_marks_stale(browser, live_server)


def test_wf06b_back_forward_keeps_staged_text(live_server, browser, rcm_react_flag):
    from tests.model_react_wf06b_acceptance import check_back_forward_keeps_staged_text_and_never_crosses_projects
    check_back_forward_keeps_staged_text_and_never_crosses_projects(browser, live_server)


def test_wf06b_keyboard_focus_and_live_status(live_server, browser, rcm_react_flag):
    from tests.model_react_wf06b_acceptance import check_keyboard_focus_and_live_status
    check_keyboard_focus_and_live_status(browser, live_server)


def test_wf06b_axe_no_serious_or_critical(live_server, browser, rcm_react_flag):
    import os
    axe = os.environ.get("FINCO_AXE_CORE_PATH")
    if not axe:
        pytest.skip("set FINCO_AXE_CORE_PATH to a local axe-core build to run the accessibility audit")
    from tests.model_react_wf06b_acceptance import check_axe_has_no_serious_or_critical_violations
    check_axe_has_no_serious_or_critical_violations(browser, live_server, axe)


def test_wf06b_top_bar_save_all_is_the_real_save(live_server, browser, rcm_react_flag):
    from tests.model_react_wf06b_acceptance import check_top_bar_save_all_is_the_real_save_and_never_runs
    check_top_bar_save_all_is_the_real_save_and_never_runs(browser, live_server)


def test_wf06b_search_and_cost_filters(live_server, browser, rcm_react_flag):
    from tests.model_react_wf06b_acceptance import check_search_and_cost_filters_narrow_what_is_shown
    check_search_and_cost_filters_narrow_what_is_shown(browser, live_server)


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_wf06b_one_amount_per_mw_unit_precision_preview(live_server, browser, rcm_react_flag, kind):
    from tests.model_react_wf06b_acceptance import check_amount_only_per_mw_unit_precision_preview_and_full_precision_save
    check_amount_only_per_mw_unit_precision_preview_and_full_precision_save(browser, live_server, kind)


def test_wf06b_per_mw_unavailable_when_capacity_is_zero(live_server, browser, rcm_react_flag):
    from tests.model_react_wf06b_acceptance import check_per_mw_is_unavailable_with_a_reason_when_the_capacity_is_zero
    check_per_mw_is_unavailable_with_a_reason_when_the_capacity_is_zero(browser, live_server)


def test_wf06b_group_plus_line_preselects_group(live_server, browser, rcm_react_flag):
    from tests.model_react_wf06b_acceptance import check_group_plus_line_preselects_the_group_and_keeps_typed_text
    check_group_plus_line_preselects_the_group_and_keeps_typed_text(browser, live_server)


def test_wf06b_row_menu_retire_reactivate_real_routes(live_server, browser, rcm_react_flag):
    from tests.model_react_wf06b_acceptance import check_row_menu_retires_and_reactivates_through_the_real_routes_without_a_run
    check_row_menu_retires_and_reactivates_through_the_real_routes_without_a_run(browser, live_server)


def test_wf06b_add_line_waits_for_the_fresh_identity(live_server, browser, rcm_react_flag):
    from tests.model_react_wf06b_acceptance import check_add_line_waits_for_the_fresh_identity_after_a_save_and_never_sends_a_stale_token
    check_add_line_waits_for_the_fresh_identity_after_a_save_and_never_sends_a_stale_token(browser, live_server)
