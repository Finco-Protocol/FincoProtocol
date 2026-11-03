"""PR-U1 real-Chromium runner (supplies fixtures to the acceptance bodies). Deliberately NOT ``test_*.py``: importing the shared browser fixtures
skips the whole module when Playwright is absent, which would add a collection skip to the accepted-source skip inventory. Run explicitly:
``FINCO_TEST_CHROMIUM_PATH=<chrome> FINCO_AXE_CORE_PATH=<axe.min.js> pytest tests/u1_browser_role.py``.
"""
import os

import pytest

from tests.model_react_rcm_support import rcm_react_flag  # noqa: F401
from tests.test_workflow_c_browser_v1 import live_server, browser  # noqa: F401


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_u1_a01_one_editable_money_authority_and_no_codes(live_server, browser, rcm_react_flag, kind):
    from tests.model_react_u1_acceptance import check_A01_one_editable_money_authority_and_no_codes
    check_A01_one_editable_money_authority_and_no_codes(browser, live_server, kind)


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_u1_a02_totals_agree_with_the_server(live_server, browser, rcm_react_flag, kind):
    from tests.model_react_u1_acceptance import check_A02_totals_agree_with_the_server_and_opex_includes_the_bases
    check_A02_totals_agree_with_the_server_and_opex_includes_the_bases(browser, live_server, kind)


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_u1_a14_opex_base_plus_line(live_server, browser, rcm_react_flag, kind):
    from tests.model_react_u1_acceptance import check_A14_opex_base_plus_line_is_one_group_one_save_and_reconciles
    check_A14_opex_base_plus_line_is_one_group_one_save_and_reconciles(browser, live_server, kind)


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_u1_decimals_default_to_zero(live_server, browser, rcm_react_flag, kind):
    from tests.model_react_u1_acceptance import check_decimals_default_to_zero_everywhere_and_exact_text_stays
    check_decimals_default_to_zero_everywhere_and_exact_text_stays(browser, live_server, kind)


def test_u1_routes_aliases_back_forward_protected(live_server, browser, rcm_react_flag):
    from tests.model_react_u1_acceptance import check_routes_aliases_back_forward_and_protected_read_only
    check_routes_aliases_back_forward_and_protected_read_only(browser, live_server)


def test_u1_moved_studio_tools_reachable(live_server, browser, rcm_react_flag):
    from tests.model_react_u1_acceptance import check_moved_studio_tools_are_reachable_in_their_new_homes
    check_moved_studio_tools_are_reachable_in_their_new_homes(browser, live_server)


def test_u1_viewports_and_axe(live_server, browser, rcm_react_flag):
    axe = os.environ.get("FINCO_AXE_CORE_PATH")
    if not axe:
        pytest.skip("set FINCO_AXE_CORE_PATH to a local axe-core build to run the accessibility audit")
    from tests.model_react_u1_acceptance import check_viewports_and_axe_on_the_new_pages
    check_viewports_and_axe_on_the_new_pages(browser, live_server, axe)
