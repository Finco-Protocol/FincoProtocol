"""RC-UX B1 (Audit A GAP-R4) — real-Chromium acceptance of React Analysis > What-if.

Preview -> create (NOT RUN) -> explicit Run in Scenarios -> compare in Run history, on a real Solar Run.  Not collected by pytest: the
existing mandatory consolidation role imports the tests below.  No module-level skip lives here.
"""
from __future__ import annotations

import os
from pathlib import Path

from tests.model_react_wf1_browser_acceptance import run_canonical

__all__ = (
    "test_rcux_whatif_requires_a_run_then_previews_without_writing_and_creates_a_not_run_scenario",
    "test_rcux_whatif_outdated_preview_cannot_be_confirmed_and_templates_are_read_only",
)
SHOTS = os.environ.get("RCM_SCREENSHOT_DIR") or os.environ.get("WF05_SCREENSHOT_DIR", "")


def _shot(page, name):
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / f"rcux-whatif-{name}.png"), full_page=True)


def _open(page, base, code):
    page.goto(f"{base}/v2/model-react/{code}?analysis=whatif#analysis")
    page.reload()
    page.wait_for_selector("[data-whatif-state='ready'], [data-whatif-state='error']", timeout=60000)      # not the transient "loading" state


def _scenarios(context, base, code):
    return context.request.get(f"{base}/v2/model-react/scenarios?project={code}").json()["scenarios"]


def test_rcux_whatif_requires_a_run_then_previews_without_writing_and_creates_a_not_run_scenario(live_server, an_session):
    context, page, record, errors = an_session("rcux-whatif-flow")
    requests = []
    page.on("request", lambda r: requests.append((r.method, r.url)) if "/v2/" in r.url and "/static/" not in r.url else None)
    _open(page, live_server, record.project_code)
    assert page.locator("[data-whatif-unavailable='not-run']").count() == 1                    # nothing to start from before a Run
    run_canonical(context, live_server, record.project_code)
    _open(page, live_server, record.project_code)
    page.wait_for_selector("[data-whatif-finding='true']")
    assert "currently" in page.locator("[data-whatif-assumption='true']").inner_text()
    before = _scenarios(context, live_server, record.project_code)
    page.fill("[data-whatif-value='true']", "1.35")
    page.fill("[data-whatif-name='true']", "DSCR 1.35 browser")
    page.locator("[data-whatif-preview='true']").click()
    page.wait_for_selector("[data-whatif-preview-result='current']", timeout=30000)
    assert page.locator("[data-whatif-proposed='true']").inner_text().startswith("1.35")
    assert "not created yet" in page.locator("[data-whatif-preview-result]").inner_text()
    assert "No projected KPI" in page.locator("[data-whatif-limits='true']").inner_text()
    assert _scenarios(context, live_server, record.project_code) == before                       # the preview created nothing
    assert page.locator("[data-whatif-create='true']").is_disabled()                              # explicit confirmation is required
    page.locator("[data-whatif-confirm='true']").check()
    page.locator("[data-whatif-create='true']").click()
    page.wait_for_selector("[data-whatif-outcome='ok']", timeout=60000)
    assert "has not been run" in page.locator("[data-whatif-outcome='ok']").inner_text()
    after = _scenarios(context, live_server, record.project_code)
    created = [s for s in after if s["name"] == "DSCR 1.35 browser"]
    assert len(created) == 1 and not created[0]["is_base_case"] and len(after) == len(before) + 1
    history = context.request.get(f"{live_server}/v2/model-react/runs?project={record.project_code}").json()["runs"]
    assert len(history) == 1                                                                      # creating the scenario ran nothing
    posts = [u for m, u in requests if m != "GET"]
    assert [u.split("/v2/")[1] for u in posts] == ["workbook/whatif/commit"]                       # the single write is the signed commit
    _shot(page, "created-1440")
    assert errors == []


def test_rcux_whatif_outdated_preview_cannot_be_confirmed_and_templates_are_read_only(live_server, an_session):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services.project_library_service import ensure_reference_models

    context, page, record, errors = an_session("rcux-whatif-outdated")
    run_canonical(context, live_server, record.project_code)
    _open(page, live_server, record.project_code)
    page.wait_for_selector("[data-whatif-finding='true']")
    page.fill("[data-whatif-value='true']", "1.3")
    page.fill("[data-whatif-name='true']", "Outdated what-if")
    page.locator("[data-whatif-preview='true']").click()
    page.wait_for_selector("[data-whatif-preview-result='current']", timeout=30000)
    page.locator("[data-whatif-confirm='true']").check()
    page.fill("[data-whatif-value='true']", "1.4")                                                 # the draft changes after the preview
    page.wait_for_selector("[data-whatif-outdated='true']")
    assert page.locator("[data-whatif-create='true']").is_disabled() and page.locator("[data-whatif-confirm='true']").is_disabled()
    ensure_reference_models()
    ref = get_reference_by_template_source("generic_solar_reference")
    page.goto(f"{live_server}/v2/model-react/{ref.project_code}?analysis=whatif#analysis")
    page.reload()
    page.wait_for_selector("[data-whatif-unavailable='protected']", timeout=60000)
    assert page.locator("[data-whatif-preview='true']").count() == 0
