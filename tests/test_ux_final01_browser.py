"""UX-FINAL-01 local browser proof (synthetic project, temporary build; never replaces served assets).

Five viewports; no horizontal page scroll; Financing units sit beside their labels; the NOT_RUN banner is plain; the phone project bar keeps
every control reachable at touch size; nothing is written. Screenshots go to $UX_FINAL01_SCREENSHOT_DIR when set.
"""
from pathlib import Path
import os
import subprocess

import pytest

from tests.test_workflow_c_browser_v1 import live_server, browser  # noqa: F401
from tests.model_react_rcm_support import rcm_react_flag  # noqa: F401
from tests.model_react_rcm_financing_acceptance import fin_session, no_page_overflow  # noqa: F401


@pytest.fixture(scope="module")
def ux_build(tmp_path_factory):
    root = Path(__file__).resolve().parents[1]
    build = tmp_path_factory.mktemp("ux-final01-build")
    subprocess.run(["npm", "run", "build", "--", "--outDir", str(build)], cwd=root / "frontend", check=True, capture_output=True)
    return build


def _assets(context, build):
    for ext, mime in (("js", "application/javascript"), ("css", "text/css")):
        context.route(f"**/static/react/finco-react.{ext}*", lambda route, request, ext=ext, mime=mime:
                      route.fulfill(path=str(build / f"finco-react.{ext}"), content_type=mime))


def _shot(page, name):
    if folder := os.environ.get("UX_FINAL01_SCREENSHOT_DIR"):
        Path(folder).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(folder) / f"{name}.png"), full_page=False)


@pytest.mark.parametrize("width", [1440, 1024, 768, 390, 320])
def test_financing_no_run_layout_units_and_bar(live_server, fin_session, ux_build, width):  # noqa: F811
    context, page, record, errors = fin_session(f"ux-final01-{width}", width=width, height=900)
    _assets(context, ux_build)
    writes = []
    page.on("request", lambda r: writes.append(r.url) if r.method not in ("GET", "HEAD") else None)
    page.goto(f"{live_server}/v2/model-react/{record.project_code}#financing")
    page.wait_for_selector('[data-run-state="NOT_RUN"]', timeout=30000)
    page.wait_for_selector("[data-financing-editing='true'] .pr3b2-cap", timeout=30000)

    banner = page.locator(".pr3b1-state").first.inner_text()
    assert "No committed Run for this project yet." in banner and "NOT_RUN — " not in banner
    # every Financing input shows its unit on the same line as its label (the caption is one flex row of at most a wrapped pair, never a stacked row)
    caps = page.locator("[data-financing-editing='true'] .pr3b2-cap")
    assert caps.count() >= 3
    for i in range(caps.count()):
        label_h = caps.nth(i).evaluate("(el) => el.getBoundingClientRect().height")
        assert label_h < 48, f"caption {i} is {label_h}px tall"
    # the project bar keeps Reload, Save changes and Run model reachable at touch size on phones
    for selector in ("[data-wf-reload]", "[data-bar-save-all]", "[data-wf-run]"):
        box = page.locator(selector).bounding_box()
        assert box, selector
        if width <= 820:        # the existing touch-target rule (rc-react-mvp.css) applies at tablet and phone widths
            assert box["width"] >= 44 and box["height"] >= 44, (selector, box)
        assert 0 <= box["x"] and box["x"] + box["width"] <= width + 1, (selector, box)
    no_page_overflow(page)
    _shot(page, f"financing-no-run-{width}")
    assert not writes
    assert not errors
