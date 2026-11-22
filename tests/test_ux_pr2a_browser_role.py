"""Explicit real-browser runner for UX-PR2a; ordinary CI collection does not import Playwright fixtures."""
from tests.model_react_rcm_support import rcm_react_flag
from tests.test_workflow_c_browser_v1 import live_server, browser


def test_capex_inline_months(live_server, browser, rcm_react_flag):
    from tests.model_react_ux_pr2a_acceptance import check_capex_inline_months
    check_capex_inline_months(browser, live_server)


def test_opex_inline_years(live_server, browser, rcm_react_flag):
    from tests.model_react_ux_pr2a_acceptance import check_opex_inline_years
    check_opex_inline_years(browser, live_server)
