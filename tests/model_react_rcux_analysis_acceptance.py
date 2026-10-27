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
    "test_rcux_diagnostics_score_coverage_and_period_heatmap_equal_the_server_projection",
    "test_rcux_diagnostics_without_a_run_shows_no_score_and_no_heatmap",
    "test_rcux_diagnostics_heatmap_fits_every_viewport",
    "test_rcux_opex_projection_studio_shows_the_server_projection_and_nothing_else",
    "test_rcux_opex_projection_fits_every_viewport",
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


def _diag(context, base, code):
    response = context.request.get(f"{base}/v2/model-react/diagnostics?project={code}")
    assert response.ok, response.text()[:300]
    return response.json()["diagnostics"]


def _open_diagnostics(page, base, code):
    page.goto(f"{base}/v2/model-react/{code}#diagnostics")
    page.reload()
    page.wait_for_selector("[data-react-workspace-version]", timeout=60000)
    page.wait_for_selector("[data-diagnostics-heatmap='true']", timeout=60000)


def test_rcux_diagnostics_score_coverage_and_period_heatmap_equal_the_server_projection(live_server, an_session):
    context, page, record, errors = an_session("rcux-diag-heat")
    run_canonical(context, live_server, record.project_code)
    api = _diag(context, live_server, record.project_code)
    score, heatmap = api["score"], api["v2"]["heatmap"]
    _open_diagnostics(page, live_server, record.project_code)
    assert page.locator("[data-score-value]").inner_text() == score["score_display"]
    assert page.locator("[data-coverage-weighted]").inner_text() == f"{score['coverage_weighted_pct']:.1f}%"
    assert page.locator("[data-coverage-count]").inner_text() == f"{score['coverage_count_pct']:.1f}%"
    assert "not a validation" in page.locator("[data-diagnostics-score]").inner_text()
    assert page.locator("[data-hm-period]").count() == len(heatmap["cells"]) == api["total_periods"]
    assert page.locator("[data-hm-cell]").count() == len(heatmap["cells"]) * len(heatmap["groups"])
    # every rendered cell state is derived from the server's counts for that group and period
    for cell in heatmap["cells"][:6] + heatmap["cells"][-3:]:
        for group, g in cell["groups"].items():
            shown = page.locator(f"[data-hm-cell='{group}:{cell['index']}']").get_attribute("data-hm-status")
            expected = ("fail" if g["fail"] else "warning" if g["warning"] else "pass" if g["pass"] and not g["unavailable"]
                        else ("warning" if g["pass"] else "unavailable") if g["unavailable"] else "none")
            assert shown == expected, (group, cell["index"], g, shown)
    assert page.locator("[data-hm-cell] .rx-sr-only").first.inner_text() in ("Passed", "Failed", "Warning", "Not evaluated", "Not applicable")   # not colour alone
    page.locator("[data-hm-period='3']").click()
    detail = page.locator("[data-hm-detail='3']")
    detail.wait_for()
    chosen = heatmap["cells"][3]
    assert f"{chosen['applicable']} check" in detail.inner_text() and f"{chosen['pass']} passed" in detail.inner_text()
    page.locator("[data-hm-period='3']").click()
    assert page.locator("[data-hm-detail]").count() == 0
    page.locator("[data-diagnostics-heatmap] details summary").click()
    assert "no new calendar" in page.locator("[data-diagnostics-heatmap] details").inner_text()
    _shot(page, "diagnostics-heatmap-1440")
    assert [e for e in errors if "Failed to load resource" not in e] == []


def test_rcux_diagnostics_without_a_run_shows_no_score_and_no_heatmap(live_server, an_session):
    context, page, record, errors = an_session("rcux-diag-none")
    page.goto(f"{live_server}/v2/model-react/{record.project_code}#diagnostics")
    page.reload()
    page.wait_for_selector("[data-react-workspace-version]", timeout=60000)
    page.wait_for_selector("[aria-label='Model checks and diagnostics']", timeout=60000)
    assert page.locator("[data-diagnostics-heatmap]").count() == 0 and page.locator("[data-score-value]").count() == 0   # no Run -> nothing invented
    assert errors == [e for e in errors if "Failed to load resource" in e]


@__import__("pytest").mark.parametrize("width", [320, 390, 768, 1440])
def test_rcux_diagnostics_heatmap_fits_every_viewport(live_server, an_session, width):
    context, page, record, errors = an_session(f"rcux-diag-view-{width}", width=width, height=900)
    run_canonical(context, live_server, record.project_code)
    _open_diagnostics(page, live_server, record.project_code)
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"), "horizontal page scroll"
    box = page.locator("[data-diagnostics-heatmap] .rcm-scroll").bounding_box()
    assert box["x"] >= -1 and box["x"] + box["width"] <= width + 1                       # the wide matrix scrolls inside its own region
    assert page.locator("[data-diagnostics-heatmap] .rcm-scroll").evaluate("(el) => el.scrollWidth > el.clientWidth") or width >= 1440
    _shot(page, f"diagnostics-heatmap-{width}")
    assert [e for e in errors if "Failed to load resource" not in e] == []


def _open_opex_projection(page, base, code):
    page.goto(f"{base}/v2/model-react/{code}#inputs")
    page.reload()
    page.locator("[data-studio-tab='opex-projection']").click()
    page.wait_for_selector("[data-opex-projection='ready']", timeout=60000)


def test_rcux_opex_projection_studio_shows_the_server_projection_and_nothing_else(live_server, an_session):
    context, page, record, errors = an_session("rcux-opex-proj")
    api = context.request.get(f"{live_server}/v2/model-react/opex-projection?project={record.project_code}").json()
    assert api["ok"]
    _open_opex_projection(page, live_server, record.project_code)
    assert page.locator("[data-opex-row]").count() == len(api["rows"]) + 2                    # 13 groups + contingency + total
    assert page.locator("[data-opex-projection-table] thead th").count() == len(api["years"]) + 2
    for row in api["rows"][:4]:
        for year, value in list(zip(api["years"], row["values"]))[:3]:
            shown = page.locator(f"[data-opex-cell='{row['code']}:{year}']").inner_text().strip()
            assert shown == ("—" if value is None else f"{round(value):,}"), (row["code"], year, value, shown)
    for year, value in zip(api["years"], api["totals"]["including_contingency"]):
        assert page.locator(f"[data-opex-total='{year}']").inner_text().strip() == ("—" if value is None else f"{round(value):,}")
    assert page.locator("[data-opex-y1]").inner_text().startswith(f"{round(api['kpis']['year1_total_keur']):,}")
    assert "Not a Run result" in page.locator("[data-opex-projection='ready']").inner_text()
    _shot(page, "opex-projection-1440")
    assert [e for e in errors if "Failed to load resource" not in e] == []


@__import__("pytest").mark.parametrize("width", [320, 390, 768, 1440])
def test_rcux_opex_projection_fits_every_viewport(live_server, an_session, width):
    context, page, record, errors = an_session(f"rcux-opex-view-{width}", width=width, height=900)
    _open_opex_projection(page, live_server, record.project_code)
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"), "horizontal page scroll"
    box = page.locator("[data-opex-projection='ready'] .rcm-scroll").bounding_box()
    assert box["x"] >= -1 and box["x"] + box["width"] <= width + 1
    _shot(page, f"opex-projection-{width}")
    assert [e for e in errors if "Failed to load resource" not in e] == []
