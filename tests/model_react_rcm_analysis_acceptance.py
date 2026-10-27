"""RC-M Lane B — real-Chromium acceptance of React Analysis > Sensitivity and Goal Seek.

Real server, synthetic users.  Every figure the UI shows is compared with the adapter's own canonical read and, for the write path,
with the persisted Working Copy and the committed Run.  Screenshots go to ``$RCM_SCREENSHOT_DIR`` as ``rcm-analysis-*.png``.


Not collected by pytest: ``tests/test_model_workspace_consolidation_browser.py`` (the existing mandatory Chromium role) imports the
tests and fixtures below and supplies ``live_server`` / ``browser`` / ``rcm_react_flag``.  No module-level skip lives here.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from tests.model_react_wf1_browser_acceptance import run_canonical

__all__ = (
    "test_analysis_hub_keeps_the_last_run_view_and_adds_the_two_tools",
    "test_five_point_tariff_sensitivity_shows_the_canonical_results_and_writes_nothing",
    "test_csv_download_is_the_displayed_table",
    "test_two_driver_matrix_renders_nine_cells_with_threshold_labels",
    "test_matrix_5x5_runs_twenty_five_points",
    "test_busy_engine_is_reported_once_and_never_retried_automatically",
    "test_cancel_stops_a_running_analysis_and_shows_no_result",
    "test_reference_models_cannot_run_sensitivity_or_goal_seek",
    "test_sensitivity_and_goal_seek_fit_every_viewport",
    "test_goal_seek_preview_apply_stale_then_deliberate_run",
    "test_goal_seek_unreachable_target_is_typed_and_offers_no_apply",
    "test_goal_seek_invalid_target_and_missing_target_are_refused_before_any_engine_work",
    "test_a_lost_apply_response_is_unknown_never_retried_and_applied_once",
    "test_a_stale_binding_is_refused_and_the_working_copy_is_kept",
    "an_session",
)
SHOTS = os.environ.get("RCM_SCREENSHOT_DIR", "")
HDR = {"X-Finco-React-Request": "1"}


@pytest.fixture
def an_session(live_server, browser, rcm_react_flag):
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project

    contexts = []

    def open_session(uid, kind="solar", width=1440, height=1000, capacity=20.0):
        record = create_reference_seeded_project(user_id=uid, template_source=f"generic_{kind}_reference", requested_name=f"RCM {kind}", capacity_mw=capacity)
        context = browser.new_context(viewport={"width": width, "height": height})
        contexts.append(context)
        context.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username="admin"), "url": live_server}])
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error"
                and not str((m.location or {}).get("url", "")).endswith("/favicon.ico") else None)
        return context, page, record, errors

    yield open_session
    for context in contexts:
        context.close()


def shot(page, name):
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / f"rcm-analysis-{name}.png"), full_page=True)


def open_tool(page, base, code, tool):
    page.goto(f"{base}/v2/model-react/{code}#analysis")
    page.wait_for_selector("[data-analysis-tools='true']", timeout=30000)
    page.locator(f"[data-analysis-tab='{tool}']").click()
    page.wait_for_selector("[data-sensitivity-panel='true']" if tool == "sensitivity" else "[data-goal-seek-panel='true']", timeout=30000)


def no_page_overflow(page):
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"), "horizontal page scroll"


def unexpected(errors, allow=()):
    return [e for e in errors if not any(f"status of {code}" in e for code in allow)]


def tariff_of(record):
    from app.persistence.workspace_repository import get_workspace_state

    return float(get_workspace_state(record.user_id, record.project_id).draft_snapshot["rev_ppa_base_tariff"])


def draft_of(record):
    from app.persistence.workspace_repository import get_workspace_state

    ws = get_workspace_state(record.user_id, record.project_id)
    return dict(ws.draft_snapshot), ws.last_runtime_snapshot_id


# ── Sensitivity ────────────────────────────────────────────────────────────

def test_analysis_hub_keeps_the_last_run_view_and_adds_the_two_tools(live_server, an_session):
    context, page, record, errors = an_session("rcm-an-hub")
    page.goto(f"{live_server}/v2/model-react/{record.project_code}#analysis")
    page.wait_for_selector("[data-analysis-tools='true']")
    assert [t.inner_text() for t in page.locator("[role='tab']").all()] == ["Last Run charts", "Sensitivity", "Goal Seek"]
    assert page.locator("[data-analysis-view='true']").count() == 1          # the existing analysis is still the first tab
    page.locator("[data-analysis-tab='sensitivity']").click()
    page.wait_for_selector("[data-sensitivity-panel='true']")
    assert "analysis=sensitivity" in page.url                                # the tool is linkable
    page.reload()
    page.wait_for_selector("[data-sensitivity-panel='true']")                # and survives a refresh
    page.keyboard.press("Tab")
    page.locator("[data-analysis-tab='sensitivity']").focus()
    page.keyboard.press("ArrowRight")
    page.wait_for_selector("[data-goal-seek-panel='true']")                  # keyboard tab navigation
    assert errors == []


def test_five_point_tariff_sensitivity_shows_the_canonical_results_and_writes_nothing(live_server, an_session):
    context, page, record, errors = an_session("rcm-an-strip")
    before = draft_of(record)
    open_tool(page, live_server, record.project_code, "sensitivity")
    assert "NOT A RUN" in page.locator("[data-ephemeral-badge='true']").inner_text()
    assert page.input_value("[data-sens-driver='true']") == "tariff" and page.input_value("[data-sens-levels='true']") == "-20, -10, 0, 10, 20"
    page.locator("[data-sens-run='true']").click()
    page.wait_for_selector("[data-strip-table='true']", timeout=240000)
    api = context.request.get(f"{live_server}/v2/model-react/analysis/sensitivity/strip", params={"project": record.project_code, "driver": "tariff"}, headers=HDR).json()
    rows = page.locator("[data-strip-row]")
    assert rows.count() == 5 == len(api["rows"])
    for i, row in enumerate(api["rows"]):
        shown = rows.nth(i)
        assert shown.get_attribute("data-strip-row") == row["label"]
        for key in ("project_irr", "equity_irr", "sponsor_irr", "min_dscr"):
            assert shown.locator(f"[data-kpi='{key}']").inner_text().startswith(row["values"][key]["display"]), (row["label"], key)
    assert page.locator("[data-strip-row='Base']").get_attribute("class") == "is-base"
    assert "not a committed Run" in page.locator("[data-run-footer='true']").inner_text()
    assert page.locator("[data-copy-table='true']").count() == 1 and page.locator("[data-download-csv='true']").count() == 1
    shot(page, "strip-1440")
    assert draft_of(record) == before                                         # nothing saved, no Run recorded
    assert errors == []


def test_csv_download_is_the_displayed_table(live_server, an_session, tmp_path):
    context, page, record, errors = an_session("rcm-an-csv")
    open_tool(page, live_server, record.project_code, "sensitivity")
    page.locator("[data-sens-run='true']").click()
    page.wait_for_selector("[data-strip-table='true']", timeout=240000)
    with page.expect_download() as info:
        page.locator("[data-download-csv='true']").click()
    path = tmp_path / "strip.csv"
    info.value.save_as(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 6 and lines[0].startswith("Case,") and lines[3].startswith("Base,OK,")
    assert errors == []


def test_two_driver_matrix_renders_nine_cells_with_threshold_labels(live_server, an_session):
    context, page, record, errors = an_session("rcm-an-matrix")
    open_tool(page, live_server, record.project_code, "sensitivity")
    page.locator("[data-sens-mode='matrix']").click()
    page.select_option("[data-sens-driver-a='true']", "tariff")
    page.select_option("[data-sens-driver-b='true']", "capex")
    page.select_option("[data-sens-metric='true']", "project_irr")
    page.fill("[data-sens-threshold='true']", "9")
    page.locator("[data-sens-run='true']").click()
    page.wait_for_selector("[data-matrix-table='true']", timeout=240000)
    cells = page.locator("[data-matrix-cell]")
    assert cells.count() == 9
    api = context.request.get(f"{live_server}/v2/model-react/analysis/sensitivity/matrix", headers=HDR,
                              params={"project": record.project_code, "driver_a": "tariff", "driver_b": "capex", "metric": "project_irr", "threshold": "9"}).json()
    for cell in api["matrix"]["cells"]:
        shown = page.locator(f"[data-matrix-cell='{cell['i']},{cell['j']}']")
        assert shown.inner_text().startswith(cell["display"])
        if cell["threshold_status"] in ("PASS", "FAIL"):
            assert cell["threshold_status"] in shown.inner_text()            # state is text, not colour alone
    assert "not a lender covenant" in page.locator("[data-matrix-threshold='true']").inner_text()
    shot(page, "matrix-1440")
    assert errors == []


def test_matrix_5x5_runs_twenty_five_points(live_server, an_session):
    context, page, record, errors = an_session("rcm-an-matrix5")
    open_tool(page, live_server, record.project_code, "sensitivity")
    page.locator("[data-sens-mode='matrix']").click()
    page.select_option("[data-sens-grid='true']", "5")
    page.locator("[data-sens-run='true']").click()
    page.wait_for_selector("[data-matrix-table='true']", timeout=300000)
    assert page.locator("[data-matrix-cell]").count() == 25
    assert "25 canonical evaluations" in page.locator("[data-run-footer='true']").inner_text()
    assert errors == []


def test_busy_engine_is_reported_once_and_never_retried_automatically(live_server, an_session):
    context, page, record, errors = an_session("rcm-an-busy")
    calls = []

    def busy(route):
        calls.append(1)
        route.fulfill(status=429, headers={"Retry-After": "5", "Content-Type": "application/json"},
                      body=json.dumps({"ok": False, "code": "MODEL_BUSY", "message": "busy. Nothing was changed."}))

    page.route("**/analysis/sensitivity/strip*", busy)
    open_tool(page, live_server, record.project_code, "sensitivity")
    page.locator("[data-sens-run='true']").click()
    page.wait_for_selector("[data-sens-error='MODEL_BUSY']")
    page.wait_for_timeout(1500)
    assert len(calls) == 1 and page.locator("[data-sens-run='true']").is_enabled()
    assert page.locator("[data-strip-table='true']").count() == 0
    assert unexpected(errors, allow=(429,)) == []


def test_cancel_stops_a_running_analysis_and_shows_no_result(live_server, an_session):
    context, page, record, errors = an_session("rcm-an-cancel")
    page.route("**/analysis/sensitivity/strip*", lambda route: None)        # never answered: the request hangs
    open_tool(page, live_server, record.project_code, "sensitivity")
    page.locator("[data-sens-run='true']").click()
    page.wait_for_selector("[data-sens-cancel='true']")
    assert page.locator("[data-sens-run='true']").is_disabled()
    page.locator("[data-sens-cancel='true']").click()
    page.wait_for_selector("[data-sens-error='CANCELLED']")
    assert page.locator("[data-sens-run='true']").is_enabled() and page.locator("[data-strip-table='true']").count() == 0


def test_reference_models_cannot_run_sensitivity_or_goal_seek(live_server, an_session):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services.project_library_service import ensure_reference_models

    context, page, record, errors = an_session("rcm-an-ref")
    ensure_reference_models()
    ref = get_reference_by_template_source("generic_solar_reference")
    page.goto(f"{live_server}/v2/model-react/{ref.project_code}#analysis")
    page.wait_for_selector("[data-analysis-tools='true']")
    for tab, marker in (("sensitivity", "data-sensitivity-unavailable"), ("goal-seek", "data-goal-seek-unavailable")):
        page.locator(f"[data-analysis-tab='{tab}']").click()
        page.wait_for_selector(f"[{marker}='true']")
        assert page.locator("[data-sens-run='true'], [data-gs-solve='true']").count() == 0
    # the only console error is the EXISTING read-only Insights history call (409 for a reference) of the Overview tab
    assert unexpected(errors, allow=(409,)) == []


@pytest.mark.parametrize("width", [320, 390, 768, 1440])
def test_sensitivity_and_goal_seek_fit_every_viewport(live_server, an_session, width):
    context, page, record, errors = an_session(f"rcm-an-resp-{width}", width=width, height=900)
    open_tool(page, live_server, record.project_code, "sensitivity")
    page.locator("[data-sens-run='true']").click()
    page.wait_for_selector("[data-strip-table='true']", timeout=240000)
    no_page_overflow(page)
    box = page.locator(".rcm-scroll").first.bounding_box()
    assert box["x"] >= -1 and box["x"] + box["width"] <= width + 1          # the table scrolls inside its own region
    shot(page, f"sensitivity-{width}")
    if width <= 820:
        controls = page.evaluate("""() => Array.from(document.querySelectorAll('.rcm-analysis button, .rcm-analysis select, .rcm-analysis input'))
            .filter(n => n.offsetParent !== null).map(n => n.getBoundingClientRect().height)""")
        assert min(controls) >= 43
    page.locator("[data-analysis-tab='goal-seek']").click()
    page.wait_for_selector("[data-goal-seek-panel='true']")
    no_page_overflow(page)
    shot(page, f"goal-seek-{width}")
    assert errors == []


# ── Goal Seek ──────────────────────────────────────────────────────────────

def base_irr_pct(context, live_server, record):
    body = context.request.get(f"{live_server}/v2/model-react/analysis/sensitivity/strip", params={"project": record.project_code, "driver": "tariff"}, headers=HDR).json()
    return body["base"]["values"]["project_irr"]["raw"] * 100


def solve_in_ui(page, target):
    page.locator("[data-gs-target='true']").fill(str(target))
    page.locator("[data-gs-solve='true']").click()
    page.wait_for_selector("[data-gs-result]", timeout=300000)


def test_goal_seek_preview_apply_stale_then_deliberate_run(live_server, an_session):
    context, page, record, errors = an_session("rcm-an-gs")
    run_canonical(context, live_server, record.project_code)                       # a committed Run exists -> CURRENT
    open_tool(page, live_server, record.project_code, "goal-seek")
    target = round(base_irr_pct(context, live_server, record) + 0.5, 2)
    before_draft, before_snapshot = draft_of(record)
    solve_in_ui(page, target)
    assert page.locator("[data-gs-status='true']").inner_text() == "SOLVED"
    assert "PREVIEW" in page.locator("[data-gs-committed='false']").inner_text()
    solved = float(re.search(r"\d+\.\d+", page.locator("[data-gs-solved='true']").inner_text()).group(0))
    achieved = float(re.search(r"\d+\.\d+", page.locator("[data-gs-achieved='true']").inner_text()).group(0))
    assert abs(achieved - target) <= 0.011 and solved > float(re.search(r"\d+\.\d+", page.locator("[data-gs-started='true']").inner_text()).group(0))
    assert draft_of(record) == (before_draft, before_snapshot)                      # PREVIEW did not mutate anything
    shot(page, "goal-seek-preview-1440")
    # Apply needs an explicit confirmation, then writes only through the canonical CAS
    page.locator("[data-gs-apply='true']").click()
    page.wait_for_selector("[data-gs-confirm='true']")
    page.locator("[data-gs-confirm-apply='true']").click()
    page.wait_for_selector("[data-gs-applied='true']", timeout=60000)
    assert page.locator("[data-gs-applied='true']").get_attribute("data-run-state") == "STALE"
    assert tariff_of(record) == pytest.approx(float(context.request.get(f"{live_server}/v2/model-react/analysis/goal-seek/catalog", params={"project": record.project_code}, headers=HDR).json()["current_tariff"]), rel=1e-12)
    assert abs(tariff_of(record) - solved) <= 0.006                                  # the solved tariff, at display precision
    after_draft, after_snapshot = draft_of(record)
    assert after_snapshot == before_snapshot                                         # Apply recorded no Run
    page.wait_for_selector("[data-workflow-bar='true'][data-bar-freshness='STALE']", timeout=30000)
    shot(page, "goal-seek-applied-stale-1440")
    # deliberate Run -> CURRENT -> the committed Project IRR is the proven target
    page.locator("[data-wf-run='true']").click()
    page.wait_for_function("""() => { const b = document.querySelector("[data-workflow-bar='true']");
        return b && (b.dataset.barFreshness === 'CURRENT' || /Draft changed|run again/i.test(b.innerText)); }""", timeout=240000)
    if page.locator("[data-workflow-bar='true']").get_attribute("data-bar-freshness") != "CURRENT":
        page.reload()
        page.wait_for_selector("[data-wf-run='true']")
        page.locator("[data-wf-run='true']").click()
        page.wait_for_selector("[data-workflow-bar='true'][data-bar-freshness='CURRENT']", timeout=240000)
    results = context.request.get(f"{live_server}/v2/model-react/statements", params={"project": record.project_code}).json()["results"]
    irr = next(m["display"] for m in results["metrics"] if m["label"] == "Project IRR")
    assert abs(float(irr.rstrip("%")) - target) <= 0.015, (irr, target)
    assert errors == []


def test_goal_seek_unreachable_target_is_typed_and_offers_no_apply(live_server, an_session):
    context, page, record, errors = an_session("rcm-an-gs-unreach")
    open_tool(page, live_server, record.project_code, "goal-seek")
    solve_in_ui(page, 95)
    assert page.locator("[data-gs-status='true']").inner_text() != "SOLVED"
    assert page.locator("[data-gs-apply='true']").count() == 0 and page.locator("[data-gs-message='true']").inner_text()
    assert errors == []


def test_goal_seek_invalid_target_and_missing_target_are_refused_before_any_engine_work(live_server, an_session):
    context, page, record, errors = an_session("rcm-an-gs-invalid")
    open_tool(page, live_server, record.project_code, "goal-seek")
    assert page.locator("[data-gs-solve='true']").is_disabled()                      # no target, no solve
    page.locator("[data-gs-target='true']").fill("abc")
    page.locator("[data-gs-solve='true']").click()
    page.wait_for_selector("[data-gs-error='INVALID_REQUEST']")
    assert "not a valid number" in page.locator("[data-gs-error='INVALID_REQUEST']").inner_text()
    assert unexpected(errors, allow=(422,)) == []


def test_a_lost_apply_response_is_unknown_never_retried_and_applied_once(live_server, an_session):
    context, page, record, errors = an_session("rcm-an-gs-lost")
    open_tool(page, live_server, record.project_code, "goal-seek")
    target = round(base_irr_pct(context, live_server, record) + 0.5, 2)
    solve_in_ui(page, target)
    calls = []

    def lose(route):
        calls.append(1)
        route.fetch()                       # the server really commits ...
        route.abort("connectionreset")      # ... and the browser never sees the answer

    page.route("**/goal-seek/apply", lose)
    original = tariff_of(record)
    page.locator("[data-gs-apply='true']").click()
    page.locator("[data-gs-confirm-apply='true']").click()
    issue = page.locator("[data-gs-apply-issue='unknown']")
    issue.wait_for(timeout=60000)
    assert "Result unknown" in issue.inner_text()
    assert page.locator("[data-gs-apply='true']").is_disabled()                       # no blind retry
    page.wait_for_timeout(1000)
    assert len(calls) == 1 and tariff_of(record) > original                           # the one write did happen, exactly once
    assert page.locator("[data-gs-applied='true']").count() == 0


def test_a_stale_binding_is_refused_and_the_working_copy_is_kept(live_server, an_session):
    """The Working Copy changes (another tab) between the solve and the Apply: the CAS refuses and nothing is overwritten."""
    context, page, record, errors = an_session("rcm-an-gs-stale")
    open_tool(page, live_server, record.project_code, "goal-seek")
    target = round(base_irr_pct(context, live_server, record) + 0.5, 2)
    solve_in_ui(page, target)
    cat = context.request.get(f"{live_server}/v2/model-react/analysis/goal-seek/catalog", params={"project": record.project_code}, headers=HDR).json()
    # a second writer changes the draft through the canonical Apply of its own solve
    other = context.request.get(f"{live_server}/v2/model-react/analysis/goal-seek/solve", headers=HDR,
                                params={"project": record.project_code, "target_metric": "project_irr", "target_value": str(target - 0.2)}).json()
    assert context.request.post(f"{live_server}/v2/model-react/analysis/goal-seek/apply", data=json.dumps({
        "project": record.project_code, **{k: other["apply"][k] for k in ("field_id", "value", "content_hash", "workbook_version", "csrf_token")}}),
        headers={"Content-Type": "application/json"}).ok
    changed = tariff_of(record)
    page.locator("[data-gs-apply='true']").click()
    page.locator("[data-gs-confirm-apply='true']").click()
    issue = page.locator("[data-gs-apply-issue='refused']")
    issue.wait_for(timeout=60000)
    assert "NOT applied" in issue.inner_text() or "not applied" in issue.inner_text().lower()
    assert tariff_of(record) == changed                                               # the newer draft was not overwritten
    assert unexpected(errors, allow=(409,)) == []
