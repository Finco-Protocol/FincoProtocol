"""PR-U2 real-Chromium runner (fixtures for ``tests/model_react_u2_acceptance.py``). Deliberately NOT ``test_*.py`` (see ``u1_browser_role``).
Run explicitly: ``FINCO_TEST_CHROMIUM_PATH=<chrome> pytest tests/u2_browser_role.py``.
"""
import pytest

from tests.model_react_rcm_support import rcm_react_flag  # noqa: F401
from tests.test_workflow_c_browser_v1 import live_server, browser  # noqa: F401


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_u2_import_percent_exact_check_and_save(live_server, browser, rcm_react_flag, kind):
    from tests.model_react_u2_acceptance import check_import_percent_exact_check_and_save
    check_import_percent_exact_check_and_save(browser, live_server, kind)


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_u2_opex_lines_by_year(live_server, browser, rcm_react_flag, kind):
    from tests.model_react_u2_acceptance import check_opex_lines_by_year
    check_opex_lines_by_year(browser, live_server, kind)


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_u2_lines_profile_link_focuses_the_item(live_server, browser, rcm_react_flag, kind):
    from tests.model_react_u2_acceptance import check_lines_profile_link_focuses_the_item
    check_lines_profile_link_focuses_the_item(browser, live_server, kind)
