"""Explicit real-browser runner; ordinary CI collection does not import Playwright fixtures."""
from tests.model_react_rcm_support import rcm_react_flag
from tests.test_workflow_c_browser_v1 import live_server,browser

def test_dense_responsive_comments_and_default_off(live_server,browser,rcm_react_flag):
    from tests.model_react_ux_pr1_acceptance import check_dense_comments_and_responsive
    check_dense_comments_and_responsive(browser,live_server)

def test_real_browser_clipboard_keyboard(live_server,browser,rcm_react_flag):
    from tests.model_react_ux_pr1_acceptance import check_real_clipboard
    check_real_clipboard(browser,live_server)
