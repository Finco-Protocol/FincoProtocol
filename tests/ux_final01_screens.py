"""UX-FINAL-01 reusable screenshot / smoke harness (NOT collected by default; run it explicitly).

    PYTHONPATH=. UX_FINAL01_SCREENSHOT_DIR=/some/private/dir pytest -q tests/ux_final01_screens.py [-k run] [--no-header]

Synthetic generated projects only (generic reference templates); no client data. For every viewport 1440/1024/768/390/320 it opens each route in
ROUTES against a TEMPORARY frontend build (never replaces served assets), asserts no page-level horizontal scroll and no console error, and saves
a PNG per route when UX_FINAL01_SCREENSHOT_DIR is set. The ``run`` mode first commits one real Run through the canonical route so Run-dependent
screens (Overview, Results, Statements, Debt metrics) are exercised with an authoritative Last Run; the ``norun`` mode shows the NOT_RUN state.
"""
from pathlib import Path
import os
import subprocess

import pytest

from tests.test_workflow_c_browser_v1 import live_server, browser  # noqa: F401
from tests.model_react_rcm_support import rcm_react_flag  # noqa: F401
from tests.model_react_rcm_financing_acceptance import fin_session, no_page_overflow, unexpected  # noqa: F401
from tests.model_react_wf1_browser_acceptance import run_canonical

WIDTHS = (1440, 1024, 768, 390, 320)
ROUTES = tuple((os.environ.get("UX_FINAL01_ROUTES") or
                "overview,inputs,inputs/capex,inputs/capex/monthly,inputs/opex,inputs/opex/years,inputs/revenue,financing,statements,results,debt-metrics"
                ).split(","))


@pytest.fixture(scope="module")
def ux_build(tmp_path_factory):
    root = Path(__file__).resolve().parents[1]
    build = tmp_path_factory.mktemp("ux-final01-screens-build")
    subprocess.run(["npm", "run", "build", "--", "--outDir", str(build)], cwd=root / "frontend", check=True, capture_output=True)
    return build


def _assets(context, build):
    for ext, mime in (("js", "application/javascript"), ("css", "text/css")):
        context.route(f"**/static/react/finco-react.{ext}*", lambda route, request, ext=ext, mime=mime:
                      route.fulfill(path=str(build / f"finco-react.{ext}"), content_type=mime))


def no_vertical_wrap(page, where=''):
    """No visible label/heading/control breaks into a column of single characters (the defect that hid Revenue field names)."""
    bad = page.evaluate("""() => { const out = [];
      for (const el of document.querySelectorAll('label, th, summary, h1, h2, h3, legend, .fm-field-label, button, a')) {
        const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
        if (el.querySelector('input, select, textarea, table, div, section, ul, ol')) continue;      // a container, not a text label
        const t = (el.textContent || '').trim(); if (t.length < 8) continue;
        const cs = getComputedStyle(el); const lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.3;
        if (r.height / lh > Math.max(6, t.length / 4)) out.push(t.slice(0, 40) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height));
      } return out.slice(0, 5); }""")
    assert not bad, (where, bad)


@pytest.mark.parametrize("mode", ["norun", "run"])
@pytest.mark.parametrize("width", WIDTHS)
def test_screens(live_server, fin_session, ux_build, mode, width):  # noqa: F811
    context, page, record, errors = fin_session(f"ux-screens-{mode}-{width}", width=width, height=900)
    _assets(context, ux_build)
    if mode == "run":
        run_canonical(context, live_server, record.project_code)
    out = os.environ.get("UX_FINAL01_SCREENSHOT_DIR")
    all_failures = []
    for route in ROUTES:
        page.goto(f"{live_server}/v2/model-react/{record.project_code}#{route}")
        page.reload()
        page.wait_for_selector("[data-react-workspace-version]", timeout=30000)
        page.wait_for_timeout(1500)
        if out:
            Path(out).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(out) / f"{mode}_{route.replace('/', '_')}_{width}.png"), full_page=bool(os.environ.get("UX_FINAL01_FULLPAGE")))
        failures = []
        try:
            no_page_overflow(page)
            no_vertical_wrap(page, f'{mode} {width} #{route}')
        except AssertionError as exc:          # keep capturing every route; report all offenders at the end
            failures.append(str(exc)[:300])
        all_failures.extend(failures)
    assert not all_failures, all_failures
    # HTTP status lines are expected (e.g. 404 of the OPEX run projection while FINCO_G10_RUN_OPEX_PANEL is OFF); any script error is a failure
    assert not unexpected(errors, allow=(404,))
