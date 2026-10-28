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
    "test_rcux_compare_projects_compares_only_my_projects_and_marks_an_unrun_project_unavailable",
    "test_rcux_compare_projects_deep_link_refresh_back_and_tenant_isolation",
    "test_rcux_compare_projects_fits_every_viewport",
    "test_rcux_statements_year_zero_toggle_hides_exactly_the_first_model_period_and_changes_no_value",
    "test_rcux_construction_timing_shows_the_derived_start_plans_on_the_server_and_saves_atomically_without_a_run",
    "test_rcux_construction_timing_refuses_a_month_end_clash_with_server_suggestions",
    "test_rcux_construction_timing_templates_are_read_only",
    "test_rcux_financing_overview_shows_reserve_sponsor_returns_and_cash_rows_equal_to_the_server_projection",
    "test_rcux_financing_overview_without_a_run_marks_returns_not_available_never_zero",
    "test_rcux_credit_decision_for_the_last_run_equals_the_server_projection_and_starts_no_run",
    "test_rcux_credit_decision_for_two_selected_runs_compares_them_and_fits_every_viewport",
    "test_rcux_earlier_run_statements_open_in_react_with_the_runs_own_values_and_survive_refresh_and_back",
    "test_rcux_revenue_studio_edits_the_escalation_base_year_policy_and_indexation_start_date_without_a_run",
    "test_rcux_ppa_contract_dates_off_the_period_boundary_offer_the_nearest_accepted_dates_and_never_round",
    "test_rcux_credit_headroom_measures_the_saved_run_against_typed_hypothetical_thresholds_and_saves_nothing",
    "test_rcux_scenario_override_is_saved_verified_reset_and_never_touches_the_base_case_or_runs",
    "test_rcux_workspace_hash_navigation_never_leaves_the_project_for_the_library",
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


def _second_project(uid, kind="wind"):
    from app.services.reference_seed_service import create_reference_seeded_project
    return create_reference_seeded_project(user_id=uid, template_source=f"generic_{kind}_reference", requested_name=f"Compare {kind}", capacity_mw=18.0)


def _compare_api(context, base, *codes):
    query = "&".join(f"code={c}" for c in codes)
    response = context.request.get(f"{base}/v2/model-react/compare-projects?{query}")
    assert response.ok, response.text()[:300]
    return response.json()


def test_rcux_compare_projects_compares_only_my_projects_and_marks_an_unrun_project_unavailable(live_server, an_session):
    uid = "rcux-cmp-a"
    context, page, record, errors = an_session(uid)
    other = _second_project(uid)
    run_canonical(context, live_server, record.project_code)
    api = _compare_api(context, live_server, record.project_code, other.project_code)
    page.goto(f"{live_server}/v2/model-react/")
    page.wait_for_selector("[data-compare-projects-cta='true']", timeout=60000)
    page.locator("[data-compare-projects-cta='true']").click()
    page.wait_for_selector("[data-compare-projects='true']", timeout=60000)
    assert page.url.endswith("#compare-projects")
    picks = [e.get_attribute("data-compare-pick") for e in page.locator("[data-compare-pick]").all()]
    assert sorted(picks) == sorted([record.project_code, other.project_code])                  # no template appears as a project
    page.locator(f"[data-compare-pick='{record.project_code}']").check()
    page.locator(f"[data-compare-pick='{other.project_code}']").check()
    page.wait_for_function("() => document.querySelectorAll('[data-compare-col]').length === 2", timeout=60000)
    ran = next(c for c in api["columns"] if c["code"] == record.project_code)
    for key in ("project_irr", "min_dscr", "total_capex_keur"):
        assert page.locator(f"[data-compare-cell='{key}:{record.project_code}']").inner_text().strip() == ran["metrics"].get(key, "—")
    assert page.locator(f"[data-compare-cell='project_irr:{other.project_code}']").inner_text().strip() == "—"          # never zero
    assert page.locator(f"[data-compare-unavailable='{other.project_code}']").count() == 1
    assert page.locator(f"a[data-compare-open='{record.project_code}']").get_attribute("href") == f"/v2/model-react/{record.project_code}#results"
    page.select_option("[data-compare-sort]", "project_irr")
    page.wait_for_function(f"() => document.querySelector('[data-compare-col]')?.getAttribute('data-compare-col') === '{record.project_code}'", timeout=30000)
    first = page.locator("[data-compare-col]").first.get_attribute("data-compare-col")
    assert first == record.project_code                                                                                  # the project with a value ranks first
    _shot(page, "compare-projects-1440")
    assert [e for e in errors if "Failed to load resource" not in e] == []


def test_rcux_compare_projects_deep_link_refresh_back_and_tenant_isolation(live_server, an_session):
    uid = "rcux-cmp-b"
    context, page, record, errors = an_session(uid)
    from app.services.reference_seed_service import create_reference_seeded_project
    stranger_record = create_reference_seeded_project(user_id="rcux-cmp-stranger", template_source="generic_data_center_reference",
                                                      requested_name="Zzz Stranger Only Project", capacity_mw=12.0)
    assert stranger_record.project_code != record.project_code
    run_canonical(context, live_server, record.project_code)
    page.goto(f"{live_server}/v2/model-react/?compare={record.project_code}&compare={stranger_record.project_code}#compare-projects")
    page.reload()
    page.wait_for_selector("[data-compare-table='true']", timeout=60000)
    assert page.locator("[data-compare-col]").count() == 1                                                               # the stranger's project is not mine
    assert page.locator("[data-compare-left-out='NOT_FOUND']").count() == 1
    assert stranger_record.project_code not in page.locator("[data-compare-picker]").inner_text()
    page.goto(f"{live_server}/v2/model-react/")
    page.wait_for_selector("[data-compare-projects-cta='true']", timeout=60000)
    page.locator("[data-compare-projects-cta='true']").click()
    page.wait_for_selector("[data-compare-projects='true']", timeout=60000)
    page.go_back()
    page.wait_for_selector("[data-compare-projects-cta='true']", timeout=60000)                                          # Back returns to My Projects
    page.go_forward()
    page.wait_for_selector("[data-compare-projects='true']", timeout=60000)
    page.locator("[data-compare-back]").click()
    page.wait_for_selector("[data-compare-projects-cta='true']", timeout=60000)
    assert errors == [e for e in errors if "Failed to load resource" in e]


@__import__("pytest").mark.parametrize("width", [320, 390, 768, 1440])
def test_rcux_compare_projects_fits_every_viewport(live_server, an_session, width):
    uid = f"rcux-cmp-v{width}"
    context, page, record, errors = an_session(uid, width=width, height=900)
    other = _second_project(uid)
    run_canonical(context, live_server, record.project_code)
    page.goto(f"{live_server}/v2/model-react/?compare={record.project_code}&compare={other.project_code}#compare-projects")
    page.reload()
    page.wait_for_selector("[data-compare-table='true']", timeout=60000)
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"), "horizontal page scroll"
    box = page.locator("[data-compare-table]").locator("xpath=ancestor::div[contains(@class,'rcm-scroll')][1]").bounding_box()
    assert box["x"] >= -1 and box["x"] + box["width"] <= width + 1
    _shot(page, f"compare-projects-{width}")
    assert [e for e in errors if "Failed to load resource" not in e] == []


def test_rcux_statements_year_zero_toggle_hides_exactly_the_first_model_period_and_changes_no_value(live_server, an_session):
    context, page, record, errors = an_session("rcux-year0")
    run_canonical(context, live_server, record.project_code)
    page.goto(f"{live_server}/v2/model-react/{record.project_code}#statements")
    page.reload()
    page.wait_for_selector("#fm-sw-view", timeout=60000)
    assert page.locator(".fm-sw-period-toggle").count() == 0                                   # the annual view has no Year 0 column to hide
    page.select_option("#fm-sw-view", "model")
    toggle = page.locator(".fm-sw-period-toggle")
    toggle.wait_for()
    assert toggle.inner_text().startswith("Year 0 (initial period): shown") and toggle.get_attribute("aria-pressed") == "true"
    header = lambda: [h.inner_text().strip() for h in page.locator("table thead tr").last.locator("th").all()]
    row_values = lambda: [c.inner_text().strip() for c in page.locator("table tbody tr").first.locator("td").all()]
    shown_header, shown_values = header(), row_values()
    toggle.click()
    assert toggle.inner_text().startswith("Year 0 (initial period): hidden") and toggle.get_attribute("aria-pressed") == "false"
    hidden_header, hidden_values = header(), row_values()
    assert hidden_header == [shown_header[0]] + shown_header[2:]                               # exactly the first period column is gone
    assert hidden_values == shown_values[1:]                                                   # every remaining value is unchanged
    assert "statementShowInitial=0" in page.url                                                # the choice is in the URL (refresh / link keeps it)
    page.reload()
    page.wait_for_selector("#fm-sw-view", timeout=60000)
    assert page.locator(".fm-sw-period-toggle").inner_text().startswith("Year 0 (initial period): hidden")
    assert errors == []


def _open_timing(page, base, code):
    page.goto(f"{base}/v2/model-react/{code}#inputs")
    page.reload()
    page.locator("[data-studio-tab='construction-timing']").click()
    page.wait_for_selector("[data-timing='ready']", timeout=60000)


def _timing_api(context, base, code, **extra):
    query = "&".join(f"{k}={v}" for k, v in extra.items())
    response = context.request.get(f"{base}/v2/model-react/construction-timing?project={code}" + (f"&{query}" if query else ""))
    assert response.ok, response.text()[:300]
    return response.json()


def test_rcux_construction_timing_shows_the_derived_start_plans_on_the_server_and_saves_atomically_without_a_run(live_server, an_session):
    context, page, record, errors = an_session("rcux-timing")
    run_canonical(context, live_server, record.project_code)
    history = context.request.get(f"{live_server}/v2/model-react/runs?project={record.project_code}").json()["runs"]
    api = _timing_api(context, live_server, record.project_code)["saved"]
    _open_timing(page, live_server, record.project_code)
    assert page.locator("[data-timing-cod]").inner_text() == api["cod_date"]
    assert page.locator("[data-timing-derived]").inner_text() == api["derived_start"]
    assert page.locator("[data-timing-duration]").inner_text() == api["duration"]
    assert page.locator("[data-timing-save]").is_disabled()                                  # the saved timing is "already saved"
    page.fill("[data-timing-start]", "2029-07-01")
    page.fill("[data-timing-months]", "2")
    page.select_option("[data-timing-unit]", "years")
    page.wait_for_selector("[data-timing-plan='valid']", timeout=30000)
    planned = _timing_api(context, live_server, record.project_code, start="2029-07-01", months="24")["plan"]
    assert planned["ok"] and planned["cod_date"] == "2031-07-01"
    assert f"COD {planned['cod_date']}" in page.locator("[data-timing-plan]").inner_text()      # the page shows what the server planned, nothing else
    assert _timing_api(context, live_server, record.project_code)["saved"]["cod_date"] == api["cod_date"]      # planning saved nothing
    _shot(page, "construction-timing-plan")
    page.locator("[data-timing-save]").click()
    page.wait_for_selector("[data-timing-outcome='ok']", timeout=60000)
    after = _timing_api(context, live_server, record.project_code)["saved"]
    assert after["cod_date"] == "2031-07-01" and after["construction_months"] == 24 and after["derived_start"] == "2029-07-01"
    assert context.request.get(f"{live_server}/v2/model-react/runs?project={record.project_code}").json()["runs"] == history     # Save never runs
    freshness = context.request.get(f"{live_server}/v2/model-react/capex/profiles?project={record.project_code}").json()["last_run"]["freshness"]
    assert freshness == "STALE"
    assert [e for e in errors if "Failed to load resource" not in e] == []


def test_rcux_construction_timing_refuses_a_month_end_clash_with_server_suggestions(live_server, an_session):
    context, page, record, errors = an_session("rcux-timing-clash")
    _open_timing(page, live_server, record.project_code)
    before = _timing_api(context, live_server, record.project_code)["saved"]
    page.select_option("[data-timing-mode]", "end")
    page.fill("[data-timing-start]", "2030-02-28")
    page.fill("[data-timing-end]", "2030-03-30")
    page.wait_for_selector("[data-timing-plan='invalid']", timeout=30000)
    assert "whole number of months" in page.locator("[data-timing-plan]").inner_text() or "cannot be represented" in page.locator("[data-timing-plan]").inner_text()
    assert page.locator("[data-timing-save]").is_disabled()
    page.fill("[data-timing-start]", "2029-03-30")
    page.fill("[data-timing-end]", "2030-03-30")
    page.wait_for_selector("[data-timing-plan]", timeout=30000)
    assert _timing_api(context, live_server, record.project_code)["saved"] == before
    assert errors == []


def test_rcux_construction_timing_templates_are_read_only(live_server, an_session):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services.project_library_service import ensure_reference_models

    context, page, record, errors = an_session("rcux-timing-ref")
    ensure_reference_models()
    ref = get_reference_by_template_source("generic_solar_reference")
    page.goto(f"{live_server}/v2/model-react/{ref.project_code}#inputs")
    page.reload()
    page.locator("[data-studio-tab='construction-timing']").click()
    page.wait_for_selector("[data-timing-readonly='true']", timeout=60000)
    assert page.locator("[data-timing-start]").count() == 0 and page.locator("[data-timing-save]").count() == 0
    assert errors == []


def _open_financing_overview(page, base, code):
    page.goto(f"{base}/v2/model-react/{code}#financing")
    page.wait_for_selector("[data-financing-studio='true']", timeout=60000)
    page.locator("[data-financing-tab-button='overview']").click()
    page.wait_for_selector("[data-financing-reserve-returns='true']", timeout=60000)


def test_rcux_financing_overview_shows_reserve_sponsor_returns_and_cash_rows_equal_to_the_server_projection(live_server, an_session):
    context, page, record, errors = an_session("rcux-fin-rr")
    run_canonical(context, live_server, record.project_code)
    api = context.request.get(f"{live_server}/v2/model-react/financing/studio", params={"project": record.project_code}).json()
    _open_financing_overview(page, live_server, record.project_code)
    policy = page.locator("[data-reserve-policy='true']").inner_text()
    assert api["reserve_view"]["support"] in policy and api["reserve_view"]["requirement"]["display"] in policy
    returns = page.locator("[data-facts='sponsor-returns']")
    for metric in api["sponsor_view"]["returns"]:
        row = returns.locator(f"[data-evidence-metric='{metric['label']}']")
        assert row.count() == 1 and metric["display"] in row.inner_text()
    rows = api["financing_evidence"]["cash_rows"]
    assert rows, "a committed Run persists the Senior cash waterfall"
    table = page.locator("[data-dsra-cash='true'] tbody tr")
    assert table.count() == len(rows)
    first = table.first.inner_text()
    assert rows[0]["cfads"]["display"] in first and rows[0]["service"]["display"] in first
    assert page.locator("[data-sizing-status='true']").inner_text().startswith("Sizing and binding-constraint status")
    _shot(page, "financing-reserve-returns")
    assert [e for e in errors if "Failed to load resource" not in e] == []


def test_rcux_financing_overview_without_a_run_marks_returns_not_available_never_zero(live_server, an_session):
    context, page, record, errors = an_session("rcux-fin-rr-norun")
    _open_financing_overview(page, live_server, record.project_code)
    returns = page.locator("[data-facts='sponsor-returns']").inner_text()
    assert "Not available" in returns and "0.00%" not in returns and "0.00x" not in returns
    assert page.locator("[data-dsra-cash-empty='true']").count() == 1
    assert [e for e in errors if "Failed to load resource" not in e] == []


def _open_runs_tab(page, base, code):
    page.goto(f"{base}/v2/model-react/{code}?analysis=runs#analysis")
    page.wait_for_selector("[data-run-history-table='true']", timeout=60000)


def test_rcux_credit_decision_for_the_last_run_equals_the_server_projection_and_starts_no_run(live_server, an_session):
    context, page, record, errors = an_session("rcux-credit-last")
    run_canonical(context, live_server, record.project_code)
    history = context.request.get(f"{live_server}/v2/model-react/runs?project={record.project_code}").json()["runs"]
    api = context.request.get(f"{live_server}/v2/model-react/analysis/credit-decision", params={"project": record.project_code}).json()
    _open_runs_tab(page, live_server, record.project_code)
    page.locator("[data-credit-open='true']").click()
    page.wait_for_selector("[data-credit-ready='true']", timeout=60000)
    for section in ("structure", "capacity", "timeline", "comparison", "findings"):
        assert page.locator(f"[data-credit-section='{section}']").count() == 1
    data = api["data"]
    assert page.locator("[data-testid='cd-finding']").count() == len(data["findings"])
    run = data["runs"][0]
    capacity = page.locator("[data-credit-section='capacity']").inner_text()
    assert run["capacity"]["min_dscr"]["d"] in capacity and (run["capacity"]["min_llcr"]["d"] in capacity)
    assert run["identity"]["history_id"] not in page.locator("[data-credit-identities='true'] > table, [data-credit-identities='true'] .cd-scroll").first.inner_text()   # ids live under Advanced details
    assert page.locator("[data-credit-advanced='true']").get_attribute("open") is None
    assert "0.00x" not in page.locator("[data-credit-section='capacity']").inner_text() or run["capacity"]["min_dscr"]["d"] == "0.00x"
    page.locator("[data-credit-section='findings'] .cd-chip").nth(1).click()
    assert page.locator("[data-credit-section='findings'] .cd-chip.is-on").count() == 1
    _shot(page, "credit-decision-last-run")
    assert context.request.get(f"{live_server}/v2/model-react/runs?project={record.project_code}").json()["runs"] == history     # reviewing credit starts no Run
    assert [e for e in errors if "Failed to load resource" not in e] == []


def test_rcux_credit_decision_for_two_selected_runs_compares_them_and_fits_every_viewport(live_server, an_session):
    context, page, record, errors = an_session("rcux-credit-two")
    run_canonical(context, live_server, record.project_code)
    run_canonical(context, live_server, record.project_code)
    _open_runs_tab(page, live_server, record.project_code)
    boxes = page.locator("[data-run-select]")
    assert boxes.count() >= 2
    boxes.nth(0).check()
    boxes.nth(1).check()
    page.locator("[data-credit-open='true']").click()
    page.wait_for_selector("[data-credit-ready='true'][data-credit-runs='2']", timeout=60000)
    assert page.locator("[data-credit-section='comparison']").count() == 1
    for width in (320, 390, 768, 1440):
        page.set_viewport_size({"width": width, "height": 900})
        overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 1, (width, overflow)
    assert [e for e in errors if "Failed to load resource" not in e] == []


def test_rcux_earlier_run_statements_open_in_react_with_the_runs_own_values_and_survive_refresh_and_back(live_server, an_session):
    context, page, record, errors = an_session("rcux-hist-st")
    run_canonical(context, live_server, record.project_code)
    history_id = context.request.get(f"{live_server}/v2/model-react/insights/history?project={record.project_code}").json()["history"][0]["identity"]["history_id"]
    api = context.request.get(f"{live_server}/v2/model-react/analysis/run-statements", params={"project": record.project_code, "history_id": history_id}).json()
    _open_runs_tab(page, live_server, record.project_code)
    page.locator(f"[data-run-statements='{history_id}']").click()
    page.wait_for_selector("[data-historical-statements='true']", timeout=60000)
    assert "statements=" in page.url and page.url.startswith(live_server + "/v2/model-react/")             # a React route, not a Legacy page
    pnl = next(s for s in api["statements"]["drilldown"]["statements"] if s["id"] == "pnl")
    revenue = next(n for n in pnl["views"]["annual"]["nodes"] if n["key"] == "revenues_keur")
    row = page.locator("[data-hist-statement='pnl'] [data-hist-row='revenues_keur']")
    cells = [c.inner_text().strip() for c in row.locator("td").all()]
    assert cells == [c["text"] if c["v"] is not None else "—not available" for c in revenue["cells"]] or [c.split("\n")[0] for c in cells] == [c["text"] if c["v"] is not None else "—" for c in revenue["cells"]]
    assert page.locator("[data-hist-advanced='true']").get_attribute("open") is None
    before = page.locator("[data-hist-statement='pnl'] [data-hist-row]").count()
    toggles = page.locator("[data-hist-statement='pnl'] button[aria-expanded='true']")
    assert toggles.count() > 0
    toggles.first.click()
    assert page.locator("[data-hist-statement='pnl'] [data-hist-row]").count() < before               # collapsing hides detail rows; values are untouched
    page.select_option("[data-hist-basis]", "model")
    assert page.locator("[data-hist-statement='pnl'] thead th").count() > page.locator("[data-hist-statement='pnl'] [data-hist-row]").first.locator("td").count() - 1
    _shot(page, "historical-statements")
    page.reload()
    page.wait_for_selector("[data-historical-statements='true']", timeout=60000)
    page.locator("[data-hist-back='true']").click()
    page.wait_for_selector("[data-run-history-table='true']", timeout=60000)
    assert "statements=" not in page.url
    assert [e for e in errors if "Failed to load resource" not in e] == []


def test_rcux_revenue_studio_edits_the_escalation_base_year_policy_and_indexation_start_date_without_a_run(live_server, an_session):
    context, page, record, errors = an_session("rcux-r7")
    run_canonical(context, live_server, record.project_code)
    history = context.request.get(f"{live_server}/v2/model-react/runs?project={record.project_code}").json()["runs"]
    page.goto(f"{live_server}/v2/model-react/{record.project_code}#inputs")
    page.wait_for_selector("[data-input-studios='true']", timeout=60000)
    page.locator("[data-studio-tab='revenue-assumptions']").click()
    page.wait_for_selector("[data-revenue-assumptions='true'] [data-sheet-editor='revenue']", timeout=60000)
    editor = page.locator("[data-revenue-assumptions='true']")
    policy = editor.get_by_label("Escalation Base Year Policy")
    assert policy.count() == 1 and editor.get_by_label("Indexation Start Date").count() == 1
    labels = [o.inner_text() for o in policy.locator("option").all()]
    assert "AFTER_FIRST_FULL_OPERATING_YEAR" not in " ".join(labels) and any("Contract anniversary" in label for label in labels)     # plain labels, stored values unchanged
    current = policy.input_value()
    target = next(o.get_attribute("value") for o in policy.locator("option").all() if o.get_attribute("value") not in (current, "CONTRACT_ANNIVERSARY"))
    policy.select_option(target)
    editor.get_by_role("button", name="Save Escalation Base Year Policy").click()
    page.wait_for_selector("[data-revenue-assumptions='true'] [data-unsaved]", state="detached", timeout=60000)         # the draft is saved, nothing is pending
    after = context.request.get(f"{live_server}/v2/model-react/fields/revenue", params={"project": record.project_code}).json()
    saved = next(f for f in after["fields"] if f["field_id"] == "revenue.ppa.indexation_policy")
    assert saved["value"] == target
    assert context.request.get(f"{live_server}/v2/model-react/runs?project={record.project_code}").json()["runs"] == history     # Save never runs
    _shot(page, "revenue-indexation")
    assert [e for e in errors if "Failed to load resource" not in e] == []


def test_rcux_ppa_contract_dates_off_the_period_boundary_offer_the_nearest_accepted_dates_and_never_round(live_server, an_session):
    context, page, record, errors = an_session("rcux-r23")
    contracts = context.request.get(f"{live_server}/v2/model-react/revenue", params={"project": record.project_code}).json()
    editor = contracts["contracts"]
    boundaries = editor["operating_boundaries"]
    assert len(boundaries) > 6
    page.goto(f"{live_server}/v2/model-react/{record.project_code}#inputs")
    page.wait_for_selector("[data-ppa-editor='empty']", timeout=60000)
    panel = page.locator("[data-ppa-editor]")
    panel.get_by_role("button", name="Define a PPA contract").click()
    stream = panel.locator("[data-ppa-stream]").first
    assert stream.locator("[data-date-guidance]").count() == 0                      # the seeded window is already on the boundaries
    off = boundaries[4][:8] + ("17" if boundaries[4][8:] != "17" else "18")          # a day that is not a period boundary
    assert off not in boundaries
    stream.get_by_label("End date").fill(off)
    guidance = stream.locator("[data-date-guidance]").last
    guidance.wait_for(timeout=10000)
    assert "not an operating-period boundary" in guidance.inner_text() and "never rounded" in guidance.inner_text()
    suggestions = guidance.locator("[data-date-suggestion]")
    assert 1 <= suggestions.count() <= 2
    offered = [s.get_attribute("data-date-suggestion") for s in suggestions.all()]
    assert all(v in boundaries for v in offered)                                    # only accepted dates are ever offered
    assert stream.get_by_label("End date").input_value() == off                     # nothing changed until the user chooses
    _shot(page, "ppa-date-suggestions")
    suggestions.first.click()
    assert stream.get_by_label("End date").input_value() == offered[0] and stream.locator("[data-date-guidance]").count() == 0
    assert [e for e in errors if "Failed to load resource" not in e] == []


def test_rcux_scenario_override_is_saved_verified_reset_and_never_touches_the_base_case_or_runs(live_server, an_session):
    context, page, record, errors = an_session("rcux-r22")
    run_canonical(context, live_server, record.project_code)
    history = context.request.get(f"{live_server}/v2/model-react/runs?project={record.project_code}").json()["runs"]
    page.goto(f"{live_server}/v2/model-react/{record.project_code}#scenarios")
    page.wait_for_selector("[data-scenario-workspace='true']", timeout=60000)
    page.get_by_label("New scenario name").fill("Downside tariff")
    page.get_by_role("button", name="Create scenario").click()
    page.wait_for_function("() => document.querySelector(\"[data-active-scenario-banner='true']\")?.innerText.includes('Downside tariff')", timeout=60000)
    page.get_by_role("button", name="Edit overrides of Downside tariff").click()
    editor = page.locator("[data-override-editor='Downside tariff']")
    editor.wait_for(timeout=60000)
    row = editor.locator("[data-override-field]").first
    field_id = row.get_attribute("data-override-field")
    assert row.get_attribute("data-overridden") == "false"
    base_value = row.locator("td").nth(0).inner_text().strip()
    scenario_input = row.locator("input")
    scenario_input.fill("61.5")
    row.get_by_role("button", name="Save").click()
    page.wait_for_selector("[data-override-editor='Downside tariff'] [data-override-field][data-overridden='true']", timeout=60000)
    assert "override saved and verified" in page.locator("[data-override-editor='Downside tariff']").inner_text()
    assert row.locator("td").nth(0).inner_text().strip() == base_value                     # the project (Base Case) value is untouched
    assert row.locator("input").input_value() == "61.5"
    _shot(page, "scenario-override-saved")
    row.get_by_role("button", name="Remove override for").click()
    page.get_by_role("button", name="Remove override", exact=True).click()                 # the confirmation names what is removed
    page.wait_for_selector(f"[data-override-field='{field_id}'][data-overridden='false']", timeout=60000)
    assert context.request.get(f"{live_server}/v2/model-react/runs?project={record.project_code}").json()["runs"] == history     # overrides never run the model
    assert [e for e in errors if "Failed to load resource" not in e] == []


def test_rcux_workspace_hash_navigation_never_leaves_the_project_for_the_library(live_server, an_session):
    context, page, record, errors = an_session("rcux-r28")
    base = f"{live_server}/v2/model-react/{record.project_code}"
    visited = []
    page.on("framenavigated", lambda frame: visited.append(frame.url) if frame == page.main_frame else None)
    for _ in range(3):
        for section in ("inputs", "statements", "financing", "results", "scenarios", "analysis", "diagnostics", "trust", "inputs"):
            page.goto(f"{base}#{section}")
            page.wait_for_selector("[data-workspace-nav], nav", timeout=60000)
    for section in ("statements", "financing", "analysis", "inputs"):
        page.locator(f"[data-workspace-nav] a[href$='#{section}'], nav a[href$='#{section}']").first.click()
        page.wait_for_timeout(250)
        assert page.url.startswith(base), (section, page.url)
    page.go_back()
    page.go_back()
    page.wait_for_timeout(300)
    assert page.url.startswith(base), page.url
    assert all(u.startswith(base) for u in visited), [u for u in visited if not u.startswith(base)]
    assert [e for e in errors if "Failed to load resource" not in e] == []


def test_rcux_credit_headroom_measures_the_saved_run_against_typed_hypothetical_thresholds_and_saves_nothing(live_server, an_session):
    context, page, record, errors = an_session("rcux-headroom")
    run_canonical(context, live_server, record.project_code)
    history = context.request.get(f"{live_server}/v2/model-react/runs?project={record.project_code}").json()["runs"]
    def debt_values():
        body = context.request.get(f"{live_server}/v2/model-react/fields/debt", params={"project": record.project_code}).json()
        return [(f["field_id"], f["value"]) for f in body["fields"]]
    fields_before = debt_values()
    _open_runs_tab(page, live_server, record.project_code)
    page.locator("[data-credit-open='true']").click()
    page.wait_for_selector("[data-credit-ready='true']", timeout=60000)
    evaluate = page.locator("[data-headroom-evaluate='true']")
    assert evaluate.is_disabled()                                                      # nothing typed, nothing to evaluate
    page.fill("[data-headroom-input='min_dscr']", "1.30")
    page.fill("[data-headroom-input='max_gearing']", "0.85")
    evaluate.click()
    page.wait_for_selector("[data-headroom-run]", timeout=60000)
    api = context.request.get(f"{live_server}/v2/model-react/analysis/credit-headroom", params={"project": record.project_code, "min_dscr": "1.30", "max_gearing": "0.85"}).json()
    by_metric = {c["metric"]: c for c in api["data"]["runs"][0]["constraints"]}
    row = page.locator("[data-headroom-metric='min_dscr']")
    assert row.count() == 1
    shown = row.inner_text()
    assert "1.3" in shown and (by_metric["min_dscr"]["state"].replace("_", " ").lower() in shown.lower())
    assert page.locator("[data-headroom-metric='min_llcr']").inner_text().lower().count("not") >= 1        # no threshold typed: an honest state, never a pass
    page.fill("[data-headroom-input='max_gearing']", "1.5")
    evaluate.click()
    page.wait_for_selector("[data-headroom-error='true']", timeout=30000)
    assert "fraction" in page.locator("[data-headroom-error='true']").inner_text()
    _shot(page, "credit-headroom")
    assert context.request.get(f"{live_server}/v2/model-react/runs?project={record.project_code}").json()["runs"] == history
    assert debt_values() == fields_before                                              # nothing typed was saved
    assert [e for e in errors if "Failed to load resource" not in e] == []
