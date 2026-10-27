"""RC-UX A3 (Audit A GAP-R10) — real-Chromium acceptance of the React Excel/CSV import (Inputs > Studios > Import).

Real server, synthetic users, real committed Runs.  Not collected by pytest: the existing mandatory consolidation role imports the tests below
and supplies ``live_server`` / ``browser`` / ``rcm_react_flag`` / ``an_session``.  No module-level skip lives here.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.model_react_wf1_browser_acceptance import run_canonical

__all__ = (
    "test_rcux_import_csv_flow_reviews_confirms_and_saves_without_running_the_model",
    "test_rcux_import_after_a_run_marks_results_stale_and_never_adds_a_run",
    "test_rcux_import_unmatched_rows_cannot_be_selected_and_nothing_is_saved",
    "test_rcux_import_a_lost_apply_response_locks_the_step_and_a_reload_shows_the_truth",
    "test_rcux_import_templates_are_read_only",
    "test_rcux_import_fits_every_viewport",
)
FIELD = "project_setup.technical.p50_hours"
SHOTS = os.environ.get("RCM_SCREENSHOT_DIR") or os.environ.get("WF05_SCREENSHOT_DIR", "")


def _shot(page, name):
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / f"rcux-import-{name}.png"), full_page=True)


def _csv(*rows):
    return ("Assumption,Value,Unit\n" + "".join(",".join(r) + "\n" for r in rows)).encode("utf-8")


def _open(page, base, code):
    page.goto(f"{base}/v2/model-react/{code}#inputs")
    page.reload()                                                       # a same-URL goto is a hash navigation; reload re-reads every projection
    page.locator("[data-studio-tab='import']").click()
    page.wait_for_selector("[data-import-workspace='true']", timeout=60000)


def _choose(page, data, name="plan.csv"):
    page.set_input_files("[data-import-file='true']", files=[{"name": name, "mimeType": "text/csv", "buffer": data}])
    page.locator("[data-import-upload='true']").click()
    page.wait_for_selector("[data-import-panel='review']", timeout=60000)


def _draft(record):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.input_set import ProjectInputSet
    from app.workbook.registry import WORKBOOK
    ws = get_workspace_state(record.user_id, record.project_id)
    return ProjectInputSet.from_snapshot(ws.draft_snapshot, workbook=WORKBOOK).get(FIELD)


def _runs(context, base, code):
    return context.request.get(f"{base}/v2/model-react/runs?project={code}").json()["runs"]


def test_rcux_import_csv_flow_reviews_confirms_and_saves_without_running_the_model(live_server, an_session):
    context, page, record, errors = an_session("rcux-import-flow")
    before = _draft(record)
    writes = []
    page.on("request", lambda r: writes.append(r.url) if r.method == "POST" and "/import/" in r.url else None)
    _open(page, live_server, record.project_code)
    assert page.locator("[data-import-workspace]").get_attribute("data-import-step") == "upload"
    assert page.locator("[data-import-upload='true']").is_disabled()                         # no file, no step
    _choose(page, _csv((FIELD, "1850", "")))
    row = page.locator("[data-import-row]").first
    assert row.get_attribute("data-import-status") == "ready" and row.get_attribute("data-import-field") == FIELD
    assert _draft(record) == before                                                          # review writes nothing
    assert page.locator("[data-import-confirm='true']").is_enabled() and "1 selected" in page.locator("[data-import-selected]").inner_text()
    _shot(page, "review-1440")
    page.locator("[data-import-confirm='true']").click()
    page.wait_for_selector("[data-import-panel='confirm']", timeout=60000)
    assert page.locator("[data-import-approved-field]").get_attribute("data-import-approved-field") == FIELD
    assert _draft(record) == before                                                          # confirm writes nothing either
    page.locator("[data-import-apply='true']").click()
    page.wait_for_selector("[data-import-result='true']", timeout=60000)
    assert float(_draft(record)) == 1850.0
    assert "out of date" in page.locator("[data-import-result]").inner_text()
    assert page.locator(f"[data-import-saved-field='{FIELD}']").count() == 1
    assert [u.rsplit("/", 1)[-1].split("?")[0] for u in writes] == ["preview", "confirm", "apply"]
    _shot(page, "saved-1440")
    assert errors == []


def test_rcux_import_after_a_run_marks_results_stale_and_never_adds_a_run(live_server, an_session):
    context, page, record, errors = an_session("rcux-import-stale")
    run_canonical(context, live_server, record.project_code)
    history = _runs(context, live_server, record.project_code)
    _open(page, live_server, record.project_code)
    _choose(page, _csv((FIELD, "1777", "")))
    page.locator("[data-import-confirm='true']").click()
    page.wait_for_selector("[data-import-panel='confirm']", timeout=60000)
    assert "STALE" in page.locator("[data-import-confirm-summary]").inner_text()
    page.locator("[data-import-apply='true']").click()
    page.wait_for_selector("[data-import-result='true']", timeout=60000)
    assert "STALE" in page.locator("[data-import-result]").inner_text()
    assert _runs(context, live_server, record.project_code) == history                       # Save never runs
    freshness = context.request.get(f"{live_server}/v2/model-react/capex/profiles?project={record.project_code}").json()["last_run"]["freshness"]
    assert freshness == "STALE"
    run_canonical(context, live_server, record.project_code)                                 # the next explicit Run applies the imported value
    assert len(_runs(context, live_server, record.project_code)) == len(history) + 1
    assert errors == []


def test_rcux_import_unmatched_rows_cannot_be_selected_and_nothing_is_saved(live_server, an_session):
    context, page, record, errors = an_session("rcux-import-blocked")
    before = _draft(record)
    _open(page, live_server, record.project_code)
    _choose(page, _csv(("A line that matches nothing", "12", "")))
    row = page.locator("[data-import-row]").first
    assert row.get_attribute("data-import-status") != "ready"
    assert page.locator("[data-import-confirm='true']").is_disabled() and "0 selected" in page.locator("[data-import-selected]").inner_text()
    page.locator("[data-import-restart='true']").click()
    assert page.locator("[data-import-workspace]").get_attribute("data-import-step") == "upload"
    assert _draft(record) == before
    assert errors == []


def test_rcux_import_a_lost_apply_response_locks_the_step_and_a_reload_shows_the_truth(live_server, an_session):
    context, page, record, errors = an_session("rcux-import-lost")
    _open(page, live_server, record.project_code)
    _choose(page, _csv((FIELD, "1666", "")))
    page.locator("[data-import-confirm='true']").click()
    page.wait_for_selector("[data-import-panel='confirm']", timeout=60000)
    page.route("**/model-react/import/apply**", lambda route: route.fulfill(status=502, content_type="application/json", body="{}"))
    page.locator("[data-import-apply='true']").click()
    page.wait_for_function("() => /could not confirm/i.test(document.body.innerText)", timeout=30000)
    assert page.locator("[data-import-apply='true']").is_disabled()                         # never retried blindly
    page.unroute("**/model-react/import/apply**")
    page.reload()
    page.locator("[data-studio-tab='import']").click()
    page.wait_for_selector("[data-import-workspace='true']", timeout=60000)
    assert page.locator("[data-import-workspace]").get_attribute("data-import-step") == "upload"
    assert errors == [e for e in errors if "502" in e or "status of 502" in e]


def test_rcux_import_templates_are_read_only(live_server, an_session):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services.project_library_service import ensure_reference_models

    context, page, record, errors = an_session("rcux-import-ref")
    ensure_reference_models()
    ref = get_reference_by_template_source("generic_solar_reference")
    page.goto(f"{live_server}/v2/model-react/{ref.project_code}#inputs")
    page.locator("[data-studio-tab='import']").click()
    page.wait_for_selector("[data-import-state='read-only']", timeout=60000)
    assert page.locator("[data-import-file]").count() == 0
    assert errors == [], errors


@pytest.mark.parametrize("width", [320, 390, 768, 1440])
def test_rcux_import_fits_every_viewport(live_server, an_session, width):
    context, page, record, errors = an_session(f"rcux-import-resp-{width}", width=width, height=900)
    _open(page, live_server, record.project_code)
    _choose(page, _csv((FIELD, "1850", "")))
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"), "horizontal page scroll"
    box = page.locator("[data-import-table]").locator("xpath=ancestor::div[contains(@class,'rcm-scroll')][1]").bounding_box()
    assert box["x"] >= -1 and box["x"] + box["width"] <= width + 1
    _shot(page, f"review-{width}")
    assert errors == []
