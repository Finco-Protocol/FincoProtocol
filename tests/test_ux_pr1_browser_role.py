"""Explicit real-browser runner; ordinary CI collection does not import Playwright fixtures."""
from tests.model_react_rcm_support import rcm_react_flag
from tests.test_workflow_c_browser_v1 import live_server,browser

def test_dense_responsive_comments_and_default_off(live_server,browser,rcm_react_flag):
    from tests.model_react_ux_pr1_acceptance import check_dense_comments_and_responsive
    check_dense_comments_and_responsive(browser,live_server)

def test_real_browser_clipboard_keyboard(live_server,browser,rcm_react_flag):
    from tests.model_react_ux_pr1_acceptance import check_real_clipboard
    check_real_clipboard(browser,live_server)

import pytest

@pytest.mark.parametrize('width', [320, 390, 768, 1440])
def test_mobile_route_lifecycle(live_server, browser, rcm_react_flag, width):
    from tests.model_react_ux_pr1_acceptance import check_mobile_route_lifecycle
    check_mobile_route_lifecycle(browser, live_server, width)

def test_truthful_tax_navigation_fallback(live_server, browser, rcm_react_flag):
    from tests.model_react_ux_pr1_acceptance import check_tax_fallback
    check_tax_fallback(browser, live_server)
