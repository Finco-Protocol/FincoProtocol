"""RC-UX — real-Chromium acceptance of the Analysis surfaces added by RC-UX: typed Goal Seek targets and the diagnostics period heatmap.

Real server, synthetic users, real committed Runs.  Not collected by pytest: the existing mandatory consolidation role imports the tests below and
supplies ``live_server`` / ``browser`` / ``rcm_react_flag`` / ``an_session``.  No module-level skip lives here.
"""
from __future__ import annotations

import os
from pathlib import Path

from tests.model_react_wf1_browser_acceptance import run_canonical

__all__ = (
    "test_rcux_goal_seek_minimum_dscr_is_typed_in_multiples_solved_and_applied_without_a_run",
    "test_rcux_goal_seek_npv_without_a_valuation_policy_is_unavailable_and_offers_no_apply",
    "test_rcux_goal_seek_switching_metric_resets_the_target_and_shows_the_declared_unit",
)
SHOTS = os.environ.get("RCM_SCREENSHOT_DIR") or os.environ.get("WF05_SCREENSHOT_DIR", "")


def _shot(page, name):
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / f"rcux-analysis-{name}.png"), full_page=True)


def _open_goal_seek(page, base, code):
    page.goto(f"{base}/v2/model-react/{code}?analysis=goal-seek#analysis")
    page.reload()
    page.wait_for_selector("[data-goal-seek-panel='true']", timeout=60000)


def test_rcux_goal_seek_minimum_dscr_is_typed_in_multiples_solved_and_applied_without_a_run(live_server, an_session):
    context, page, record, errors = an_session("rcux-gs-dscr")
    run_canonical(context, live_server, record.project_code)
    history = context.request.get(f"{live_server}/v2/model-react/runs?project={record.project_code}").json()["runs"]
    _open_goal_seek(page, live_server, record.project_code)
    options = [o.get_attribute("value") for o in page.locator("[data-gs-metric] option").all()]
    assert options == ["project_irr", "pure_equity_irr", "total_sponsor_irr", "min_dscr", "project_npv", "sponsor_npv"]
    page.select_option("[data-gs-metric]", "min_dscr")
    assert page.locator("[data-goal-seek-form] label", has_text="Target (x)").count() == 1
    assert page.locator("[data-gs-target]").get_attribute("data-gs-target-unit") == "multiple"
    page.fill("[data-gs-target]", "1.30")
    page.locator("[data-gs-solve]").click()
    page.wait_for_selector("[data-gs-result]", timeout=240000)
    assert page.locator("[data-gs-status]").inner_text().strip().upper() == "SOLVED"
    facts = page.locator(".rcm-facts").inner_text()
    assert "1.30x" in facts and "Minimum" in facts                                  # a multiple, never "130.00%" or "1.30%"
    assert page.locator("[data-gs-achieved]").inner_text().endswith("x")
    assert "%" not in page.locator("[data-gs-achieved]").inner_text()
    _shot(page, "goal-seek-dscr")
    page.locator("[data-gs-apply]").click()
    page.locator("[data-gs-confirm-apply]").click()
    page.wait_for_selector("[data-gs-applied]", timeout=60000)
    assert page.locator("[data-gs-applied]").get_attribute("data-run-state") == "STALE"
    assert context.request.get(f"{live_server}/v2/model-react/runs?project={record.project_code}").json()["runs"] == history     # Apply never runs
    assert [e for e in errors if "Failed to load resource" not in e] == []


def test_rcux_goal_seek_npv_without_a_valuation_policy_is_unavailable_and_offers_no_apply(live_server, an_session):
    context, page, record, errors = an_session("rcux-gs-npv")
    _open_goal_seek(page, live_server, record.project_code)
    page.select_option("[data-gs-metric]", "project_npv")
    assert page.locator("[data-goal-seek-form] label", has_text="Target (kEUR)").count() == 1
    page.fill("[data-gs-target]", "20000")
    page.locator("[data-gs-solve]").click()
    page.wait_for_selector("[data-gs-result]", timeout=240000)
    assert "UNAVAILABLE" in page.locator("[data-gs-status]").inner_text().upper()
    assert page.locator("[data-gs-apply]").count() == 0 and page.locator("[data-gs-solved]").count() == 0       # never zero, never a solved tariff
    assert "kEUR" in page.locator(".rcm-facts").inner_text()
    _shot(page, "goal-seek-npv-unavailable")
    assert [e for e in errors if "Failed to load resource" not in e] == []


def test_rcux_goal_seek_switching_metric_resets_the_target_and_shows_the_declared_unit(live_server, an_session):
    context, page, record, errors = an_session("rcux-gs-units")
    _open_goal_seek(page, live_server, record.project_code)
    labels = {}
    for key in ("project_irr", "min_dscr", "sponsor_npv"):
        page.select_option("[data-gs-metric]", key)
        page.fill("[data-gs-target]", "5")
        page.select_option("[data-gs-metric]", "project_irr" if key != "project_irr" else "min_dscr")     # switching clears the typed value
        assert page.locator("[data-gs-target]").input_value() == ""
        page.select_option("[data-gs-metric]", key)
        labels[key] = (page.locator("[data-gs-target]").get_attribute("data-gs-target-unit"), page.locator("[data-gs-target]").get_attribute("placeholder"))
    assert labels == {"project_irr": ("percent", "e.g. 8.5"), "min_dscr": ("multiple", "e.g. 1.35"), "sponsor_npv": ("keur", "e.g. 5000")}
    assert errors == []
