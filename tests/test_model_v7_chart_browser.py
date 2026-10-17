"""Workbook SVG initialization is node-local, not a financial result cache."""
import pytest

pytest.importorskip('playwright', reason='playwright not installed in this workflow')
from tests.test_rcux2_ppa_quick_add_browser import live_server, browser, Session  # noqa: E402,F401
from tests.test_model_v7_diagnostics_browser import _run  # noqa: E402
from tests.model_workspace_navigation import activate_destination  # noqa: E402


def test_unchanged_chart_survives_unrelated_swaps_but_new_run_and_changed_data_render(live_server, browser):
    s = Session(live_server, browser, 'v7-chart-node')
    try:
        page = s.page; _run(page)
        page.wait_for_selector('.v2-overview-chart svg', state='attached')
        page.evaluate("""() => {
          window.__v7ChartNode = document.querySelector('.v2-overview-chart');
          window.__v7SvgNode = window.__v7ChartNode.querySelector('svg');
          window.__v7ChartTitles = [...window.__v7SvgNode.querySelectorAll('title')].map(n=>n.textContent);
        }""")
        activate_destination(page, 'tab-capex')
        page.wait_for_function("() => document.querySelector('#v2-sheet-capex').dataset.modelViewState === 'loaded'")
        assert page.evaluate("() => window.__v7SvgNode === window.__v7ChartNode.querySelector('svg')")
        assert page.evaluate("() => JSON.stringify(window.__v7ChartTitles) === JSON.stringify([...window.__v7SvgNode.querySelectorAll('title')].map(n=>n.textContent))")
        _run(page)
        page.wait_for_function("() => document.querySelector('.v2-overview-chart') !== window.__v7ChartNode")
        assert page.evaluate("() => document.querySelector('.v2-overview-chart svg') !== window.__v7SvgNode")
        # Only presentation attributes are varied in this final render test.
        # No input Save, financial calculation or persisted evidence is changed.
        assert page.evaluate("""() => {
          const node=document.querySelector('.v2-overview-chart'), old=node.querySelector('svg');
          const periods=JSON.parse(node.dataset.periods);node.dataset.periods=JSON.stringify(periods.slice(0,2));
          window.FoCharts.renderAll();return node.querySelector('svg') !== old;
        }""")
        assert not s.errors, s.errors
    finally:
        s.close()
