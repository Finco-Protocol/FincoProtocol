"""WF-06B real-Chromium role (supplies fixtures to the acceptance bodies; also re-runs the WF-06A cost-grid body unchanged)."""
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
