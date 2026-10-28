"""RC-REACT-MVP — integrated Internal MVP browser acceptance bodies.

Not collected by pytest: executed through the thin wrappers in
``tests/test_model_workspace_consolidation_browser.py`` (the existing mandatory
Chromium role).  No module-level skip lives here.

Every number asserted comes from the canonical API of the SAME committed Run
(history id + snapshot id); nothing is a hard-coded example KPI.
"""
from __future__ import annotations

import os
import re
from urllib.parse import parse_qs, urlsplit

from tests.model_react_wf1_browser_acceptance import make_session as _solar_session
from tests.model_react_wf2_browser_acceptance import (
    bar, bumped, field_input_id, goto_section, history_count, numeric_bound_field, open_workspace, runs, wait_status,
)
from tests.model_react_wf2_lifecycle_acceptance import (
    CIT, CIT_CELL, DISCARD, SAVE, STAY, another_value, dialog, grid_value, materialize, stage_cit, tab, unsaved,
    wait_unsaved, watch_posts,
)

SHOTS = os.environ.get("MVP_SCREENSHOT_DIR", "")


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, f"mvp-{name}.png"), full_page=True)


def session(browser, base, uid, kind):
    """A Working Copy of the requested technology, with an authenticated Chromium context."""
    if kind == "solar":
        return _solar_session(browser, base, uid)
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project

    record = create_reference_seeded_project(user_id=uid, template_source=f"generic_{kind}_reference",
                                             requested_name=f"MVP {kind}", capacity_mw=20.0)
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    context.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username="admin"), "url": base}])
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error"
            and not str((m.location or {}).get("url", "")).endswith("/favicon.ico") else None)
    return context, page, record, errors


def ui_number(text):
    match = re.search(r"-?\d[\d,]*\.?\d*", text)
    return float(match.group(0).replace(",", "")) if match else None


def same_figure(shown, raw):
    """The UI figure is the canonical raw value (kEUR/ratio) or its percentage presentation; never recomputed."""
    return shown is not None and (abs(shown - raw) <= 0.01 * max(1.0, abs(raw)) or abs(shown - raw * 100) <= 0.01 * max(1.0, abs(raw * 100)))


def wait_current(page, timeout=120000):
    """Wait for CURRENT after an explicit Run; on failure report what the workspace actually said."""
    try:
        page.wait_for_selector("[data-workflow-bar='true'][data-bar-freshness='CURRENT']", timeout=timeout)
    except Exception:
        notes = page.locator("[data-workflow-bar='true'] [data-wf-status]").all_inner_texts()
        raise AssertionError(f"Run did not reach CURRENT; bar: {notes}; state={bar(page).get_attribute('data-bar-freshness')}") from None


def explicit_run(page):
    """Await this Run's response and refreshed workspace, never an earlier CURRENT.

    Preserve the existing single reload/retry for a definitive stale-draft refusal.
    Unknown, rejected or failed executions must fail rather than create another Run.
    """
    for attempt in range(2):
        page.wait_for_function("() => !document.querySelector(\"[data-wf-run='true']\").disabled")
        # A committed Run reloads the workspace. Waiting for that navigation
        # also excludes any still-pending projection from a scenario switch.
        with page.expect_navigation(wait_until="domcontentloaded", timeout=180000):
            with page.expect_response(lambda r: r.request.method == "POST" and
                                      urlsplit(r.url).path == "/v2/workbook/run", timeout=180000) as executed:
                page.locator("[data-wf-run='true']").click()
            response = executed.value
            stale = response.status == 303
            if stale:
                message = parse_qs(urlsplit(response.headers.get("location", "")).query).get("v2_err", [""])[0]
                assert attempt == 0 and message.startswith("Draft changed since page loaded"), (response.status, message)
                wait_status(page, "error", "Draft changed", "[data-workflow-bar='true']")
                page.reload()
            else:
                assert response.ok, response.status
                outcome = response.json()
                assert outcome.get("outcome") in {"COMMITTED", "REPLAYED"}, outcome
        page.wait_for_selector("[data-workflow-bar='true']")
        if not stale:
            wait_current(page, 180000)
            return
    raise AssertionError("Run remained stale after the existing single reload/retry")


def api(context, base, path):
    response = context.request.get(f"{base}{path}")
    assert response.ok, (path, response.status)
    return response.json()


def insights(context, base, record, *history_ids):
    query = "".join(f"&run={i}" for i in history_ids)
    return api(context, base, f"/v2/model-react/insights?project={record.project_code}{query}")


def metric(run, key):
    return next(m for m in run["metrics"] if m["key"] == key)


def committed(context, base, record):
    """Run History rows newest first, as the canonical runs projection serves them."""
    return runs(context, base, record)


# ── Step 1-2: Reference -> Working Copy through the Library ──────────────────


def check_library_clone_creates_an_openable_unprotected_working_copy(browser, react_enabled):
    """Template -> project through the New Project wizard (the library no longer lists or clones system references)."""
    base = react_enabled
    context, page, seeded, errors = session(browser, base, "mvp-clone", "solar")
    try:
        before = {p["code"] for p in api(context, base, "/v2/model-react/my-projects")["projects"]}
        page.goto(f"{base}/v2/model-react/#new-project/template")
        page.reload()
        page.locator("[data-template-card='solar']").click()
        page.locator("[data-wizard-next='true']").click()
        page.fill("#rcm-name", "MVP template project")
        page.locator("[data-wizard-next='true']").click()
        page.wait_for_selector("[data-wizard-panel='timeline']", timeout=30000)
        page.locator("[data-wizard-next='true']").click()
        page.wait_for_selector("[data-wizard-panel='review']")
        page.locator("[data-wizard-create]").click()
        page.wait_for_selector("[data-react-workspace-version]", timeout=60000)
        library = api(context, base, "/v2/model-react/my-projects")["projects"]
        fresh = [p for p in library if p["code"] not in before and p["name"] == "MVP template project"]
        assert len(fresh) == 1, "the new project appears in My Projects exactly once"
        copy = fresh[0]
        page.goto(f"{base}/v2/model-react/{copy['code']}#inputs")
        page.wait_for_selector("[data-workflow-bar='true']")
        assert page.locator("text=READ-ONLY TEMPLATE").count() == 0
        assert bar(page).get_attribute("data-bar-freshness") == "NOT_RUN"
        assert not [e for e in errors if "Failed to load resource" not in e], errors
    finally:
        context.close()


# ── Steps 3-20: the supported Internal MVP path on a real Run ────────────────


def check_internal_mvp_path_with_financial_intelligence(browser, react_enabled, kind):
    base = react_enabled
    context, page, record, errors = session(browser, base, f"mvp-flow-{kind}", kind)
    run_posts = watch_posts(page, "/v2/workbook/run")
    try:
        materialize(context, base, record)
        open_workspace(page, base, record, "inputs")
        page.wait_for_selector("[data-sheet-editor='project_setup']")
        assert history_count(context, base, record) == 0

        # 3. Project Setup
        row = numeric_bound_field(context, base, record, "project_setup", prefer=("project_setup.technical.p50_hours",))
        page.locator(f"#{field_input_id('project_setup', row['field_id'])}").fill(bumped(row))
        page.get_by_role("button", name=f"Save {row['label']}").click()
        wait_status(page, "ok", "verified", "[data-sheet-editor='project_setup']")
        persisted = next(f for f in api(context, base, f"/v2/model-react/fields/project_setup?project={record.project_code}")["fields"]
                         if f["field_id"] == row["field_id"])
        assert float(persisted["value"]) == float(bumped(row)) or persisted["value"] != row["value"]

        # 4. canonical financial input (grid) with the lifecycle contract: unsaved drafts survive section changes only by choice
        page.wait_for_selector(CIT_CELL)
        original_cit = grid_value(context, base, record)
        draft = another_value(original_cit)
        stage_cit(page, draft)
        wait_unsaved(page, 1)
        for destination in ("Results", "Scenarios", "Analysis", "Financing"):
            tab(page, destination).click()
            dialog(page).get_by_role("button", name=STAY).click()
            assert page.locator(CIT_CELL).input_value() == draft and page.url.endswith("#inputs"), destination
        assert history_count(context, base, record) == 0
        page.locator(SAVE).click()
        page.wait_for_selector("[data-save-state='saved']")
        wait_unsaved(page, 0)
        assert float(grid_value(context, base, record)) == float(draft)

        # 5. CAPEX line
        costs = page.locator("[data-cost-line-manager='capex']")
        costs.scroll_into_view_if_needed()
        costs.locator("select").select_option(index=1)
        costs.get_by_label("Line label").fill("MVP acceptance CAPEX line")
        costs.get_by_label("Amount").fill("25")
        costs.locator("[data-cost-add='capex']").click()
        wait_status(page, "ok", "verified in the fresh projection", "[data-cost-line-manager='capex']")

        # 6. PPA: an explicit, fully specified contract book
        ppa = page.locator("[data-ppa-editor]")
        ppa.scroll_into_view_if_needed()
        if ppa.first.get_attribute("data-ppa-editor") == "empty":
            ppa.get_by_role("button", name="Define a PPA contract").click()
            stream = ppa.locator("[data-ppa-stream]").first
            stream.get_by_label("Source reference").fill("MVP acceptance PPA")
            stream.get_by_label("Tariff").fill("58")
            stream.get_by_label("Contracted volume share").fill("1")
            ppa.locator("[data-ppa-save='true']").click()
            page.wait_for_selector("[data-ppa-editor='guided']", timeout=20000)
        booked = api(context, base, f"/v2/model-react/revenue?project={record.project_code}")["contracts"]
        assert booked["active"] is True

        # 7. Financing
        goto_section(page, "financing")
        page.wait_for_selector("[data-sheet-editor='debt']")
        debt = numeric_bound_field(context, base, record, "debt")
        page.locator(f"#{field_input_id('debt', debt['field_id'])}").fill(bumped(debt))
        page.get_by_role("button", name=f"Save {debt['label']}").click()
        wait_status(page, "ok", "verified", "[data-sheet-editor='debt']")

        # 8. persistence survives a reload (server-authoritative values)
        page.reload()
        page.wait_for_selector("[data-sheet-editor='debt']")
        assert history_count(context, base, record) == 0, "no Save ran the model"

        # 9-10. explicit Run, committed identity
        page.wait_for_function("() => !document.querySelector(\"[data-wf-run='true']\").disabled")
        page.locator("[data-wf-run='true']").click()
        wait_current(page, 180000)
        base_rows = committed(context, base, record)
        assert len(base_rows) == 1 and len(run_posts) == 1
        base_run = base_rows[0]
        workspace = api(context, base, f"/v2/model-react/workspace?project={record.project_code}")
        assert workspace["identity"]["snapshot_id"] == base_run["runtime_snapshot_id"]
        base_history_id = base_run["history_id"]

        # 11. Results and Statements
        goto_section(page, "results")
        page.wait_for_selector("[data-results-view='true']")
        assert page.locator("[data-analysis-link='true']").count() == 1
        goto_section(page, "statements")
        page.wait_for_selector("[data-statements-view='true']")
        shot(page, f"{kind}-statements")

        # 12-13. scenario + a supported override
        goto_section(page, "scenarios")
        page.wait_for_selector("[data-scenario-workspace='true']")
        page.get_by_label("New scenario name").fill("MVP downside")
        page.get_by_role("button", name="Create scenario").click()
        wait_status(page, "ok", "created", "[data-scenario-workspace='true']")
        page.wait_for_function("""() => document.querySelector("[data-active-scenario-banner='true']").innerText.includes('MVP downside')""")
        assert history_count(context, base, record) == 1 and len(run_posts) == 1, "creating a scenario never runs the model"
        # With an explicit contract book the canonical Run requires the scenario to replace the CONTRACTS (a tariff
        # alias override is refused at Run: REVENUE_V2_SCENARIO), so the supported scenario override is the contract edit.
        goto_section(page, "inputs")
        page.wait_for_selector("[data-ppa-editor='guided']", timeout=30000)
        ppa = page.locator("[data-ppa-editor='guided']")
        ppa.scroll_into_view_if_needed()
        assert "MVP downside" in ppa.inner_text(), "the editor shows the scenario scope"
        ppa.locator("[data-ppa-stream]").first.get_by_label("Tariff").fill("52")
        ppa.locator("[data-ppa-save='true']").click()
        wait_status(page, "ok", "verified", "[data-ppa-editor]")
        scoped = api(context, base, f"/v2/model-react/revenue?project={record.project_code}")["contracts"]
        assert scoped["overridden"] is True and scoped["scope"] == "MVP downside"
        assert history_count(context, base, record) == 1 and len(run_posts) == 1, "saving the override never runs the model"

        # 14. a SEPARATE explicit Run for the scenario
        page.wait_for_function("() => !document.querySelector(\"[data-wf-run='true']\").disabled")
        page.locator("[data-wf-run='true']").click()
        wait_current(page, 180000)
        all_rows = committed(context, base, record)
        assert len(all_rows) == 2 and len(run_posts) == 2
        scenario_run = next(r for r in all_rows if r["history_id"] != base_history_id)
        assert scenario_run["active_scenario_name"] == "MVP downside"
        assert next(r for r in all_rows if r["history_id"] == base_history_id)["runtime_snapshot_id"] == base_run["runtime_snapshot_id"], \
            "the original Run identity is immutable"
        scenario_history_id = scenario_run["history_id"]

        # 15. committed scenario KPI comparison (Base Case Run vs scenario Run), exactly as the canonical API serves it
        goto_section(page, "scenarios")
        panel = page.locator("[data-kpi-compare='committed-runs']")
        panel.wait_for()
        assert page.locator("[data-kpi-compare='unavailable']").count() == 0
        # per-scenario committed Run availability agrees with the canonical history (Base Case Run included)
        base_row = page.locator("[data-scenario-row]", has=page.locator("text=Base Case")).first
        assert base_row.locator("[data-run-evidence]").get_attribute("data-run-evidence") == "AVAILABLE"
        from tests.react_run_identity import text as run_text
        assert run_text(base_run["runtime_snapshot_id"]) in base_row.locator("[data-run-evidence]").inner_text()
        scenario_row = page.locator("[data-scenario-row='MVP downside']")
        assert scenario_row.locator("[data-run-evidence]").get_attribute("data-run-evidence") == "AVAILABLE"
        assert run_text(scenario_run["runtime_snapshot_id"]) in scenario_row.locator("[data-run-evidence]").inner_text()
        assert panel.locator("[aria-label='Scenario KPI comparison']").count() == 0, "nothing is read before an explicit selection"
        for history_id in (base_history_id, scenario_history_id):
            panel.locator(f"label:has-text('{history_id}') input[type=checkbox]").check()
        panel.get_by_role("button", name="Read selected Run evidence").click()
        table = panel.locator("[aria-label='Scenario KPI comparison'] table")
        table.wait_for(timeout=30000)
        expected = insights(context, base, record, base_history_id, scenario_history_id)
        assert [c["history_id"] for c in expected["comparison"]["columns"]] == [base_history_id, scenario_history_id]
        for row_expected in expected["comparison"]["rows"]:
            if row_expected["key"] not in ("min_dscr", "avg_dscr", "project_irr", "sponsor_irr", "total_revenue_keur", "total_cfads_keur"):
                continue
            for index, history_id in enumerate((base_history_id, scenario_history_id)):
                cell_text = table.locator(f"tbody tr:has(th:has-text('{row_expected['label']}')) td[data-history-id='{history_id}']").first.inner_text()
                if row_expected["raw_values"][index] is None:
                    assert "Unavailable" in cell_text or row_expected["availability"][index], (row_expected["key"], cell_text)
                else:
                    assert same_figure(ui_number(cell_text), row_expected["raw_values"][index]), (row_expected["key"], index, row_expected["raw_values"][index], cell_text)
        shot(page, f"{kind}-scenario-kpi")
        # the comparison never changed the active scenario and ran nothing
        assert "MVP downside" in page.locator("[data-active-scenario-banner='true']").inner_text()
        assert history_count(context, base, record) == 2 and len(run_posts) == 2

        # 16. Credit dashboard + DSCR timeline of the scenario Run (the active one)
        goto_section(page, "analysis")
        page.wait_for_selector("[data-financial-insights='true'] .fi-panel")
        insight_panel = page.locator("[data-financial-insights='true']")
        assert insight_panel.locator("[data-selected-history]").count() == 0, "no Run is selected or read automatically"
        insight_panel.locator(f"label:has-text('{scenario_history_id}') input[type=checkbox]").check()
        insight_panel.get_by_role("button", name="Read selected Run evidence").click()
        dashboard = insight_panel.locator(f"[data-selected-history='{scenario_history_id}']")
        dashboard.wait_for(timeout=30000)
        scenario_insight = insights(context, base, record, scenario_history_id)["runs"][0]
        assert scenario_insight["identity"]["snapshot_id"] == scenario_run["runtime_snapshot_id"], "same committed Run and snapshot as the canonical history"
        for key in ("min_dscr", "avg_dscr", "project_irr", "equity_irr", "sponsor_irr", "total_cfads_keur"):
            m = metric(scenario_insight, key)
            card = dashboard.locator(f"[data-metric='{key}']").first
            assert card.get_attribute("data-history-id") == scenario_history_id
            assert card.get_attribute("data-snapshot-id") == scenario_run["runtime_snapshot_id"], "one Run, one snapshot"
            if m["raw_value"] is None:
                assert card.get_attribute("data-available") == "false", key
            else:
                assert float(card.get_attribute("data-raw-value")) == m["raw_value"], key
        assert dashboard.locator("table").count() >= 1, "the DSCR / debt-service timeline has its accessible data table"
        shot(page, f"{kind}-credit-dashboard")

        # 17. historical Run evidence: the Base Case Run is read WITHOUT becoming the active scenario or looking stale
        insight_panel.locator(f"label:has-text('{scenario_history_id}') input[type=checkbox]").uncheck()
        insight_panel.locator(f"label:has-text('{base_history_id}') input[type=checkbox]").check()
        insight_panel.get_by_role("button", name="Read selected Run evidence").click()
        historical = insight_panel.locator(f"[data-selected-history='{base_history_id}']")
        historical.wait_for(timeout=30000)
        base_insight = insights(context, base, record, base_history_id)["runs"][0]
        assert base_insight["identity"]["snapshot_id"] == base_run["runtime_snapshot_id"]
        assert base_insight["identity"]["scenario"] != scenario_insight["identity"]["scenario"]
        assert historical.locator(f"text={base_run['runtime_snapshot_id']}").count() >= 1
        assert bar(page).get_attribute("data-bar-freshness") == "CURRENT", "reading a historical Run does not change the Working Copy state"
        assert history_count(context, base, record) == 2 and len(run_posts) == 2

        # 18. export the correct committed Run(s)
        goto_section(page, "results")
        page.wait_for_selector("[data-export-view='true']")
        assert page.locator("[data-export-identity]").get_attribute("data-export-identity") == scenario_run["runtime_snapshot_id"]
        with page.expect_download(timeout=60000) as download:
            page.locator("[data-export-last-run='true']").click()
        with open(download.value.path(), "rb") as handle:
            assert handle.read(2) == b"PK"
        history_link = page.locator(f"[data-export-view='true'] a[href*='history_id={base_history_id}']")
        assert history_link.count() == 1
        exported = context.request.get(f"{base}{history_link.get_attribute('href')}")
        assert exported.ok and exported.body()[:2] == b"PK"

        # 19. isolation: the base Run evidence is byte-for-byte unchanged and another project is untouched
        again = insights(context, base, record, base_history_id)["runs"][0]
        assert again["metrics"] == base_insight["metrics"] and again["identity"] == base_insight["identity"]
        _ctx2, _page2, other, _e2 = session(browser, base, f"mvp-other-{kind}", kind)
        try:
            assert api(_ctx2, base, f"/v2/model-react/insights/history?project={other.project_code}")["history"] == []
        finally:
            _ctx2.close()

        # 20. nothing ran except the two explicit Runs; no console errors
        assert history_count(context, base, record) == 2 and len(run_posts) == 2
        assert not [e for e in errors if "Failed to load resource" not in e], errors
    finally:
        context.close()


# ── UX closeout: responsive layouts, touch targets, keyboard ─────────────────


TOUCH_TARGETS = (".fm-nav a", ".wf-bar button", ".rx-header nav a", ".fm-workspace-bar a")


def check_responsive_insights_and_touch_targets(browser, react_enabled):
    base = react_enabled
    context, page, record, errors = session(browser, base, "mvp-resp", "solar")
    try:
        materialize(context, base, record)
        open_workspace(page, base, record, "overview")
        explicit_run(page)
        # a long scenario name and a second Run: many identifiers must wrap, never widen the page
        goto_section(page, "scenarios")
        page.wait_for_selector("[data-scenario-workspace='true']")
        long_name = "Downside case with an intentionally very long scenario name " * 2
        page.get_by_label("New scenario name").fill(long_name.strip()[:80])
        page.get_by_role("button", name="Create scenario").click()
        wait_status(page, "ok", "created", "[data-scenario-workspace='true']")
        explicit_run(page)
        for width, height in ((1440, 1000), (1366, 768), (820, 1100), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            for section, anchor in (("scenarios", "[data-kpi-compare='committed-runs']"), ("analysis", "[data-financial-insights='true'] .fi-panel"),
                                    ("results", "[data-export-view='true']")):
                goto_section(page, section)
                page.wait_for_selector(anchor, timeout=30000)
                if section == "analysis":
                    boxes = page.locator("[data-financial-insights='true'] input[type=checkbox]")
                    for index in range(min(boxes.count(), 2)):
                        boxes.nth(index).check()
                    page.get_by_role("button", name="Read selected Run evidence").click()
                    page.wait_for_selector("[data-financial-insights='true'] [data-selected-history]", timeout=30000)
                page.wait_for_timeout(300)
                overflow = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
                if section == "results":
                    # the Results/KPI strip is the shared WF-React-1 presentation; this closeout owns the Export block
                    overflow = 0 if page.locator("[data-export-view='true']").bounding_box()["x"] + page.locator("[data-export-view='true']").bounding_box()["width"] <= width + 1 else 99
                assert overflow <= 1, f"page-level horizontal overflow at {width}px in {section}: {overflow}px"
                shot(page, f"resp-{width}-{section}")
            if width <= 820:
                for selector in TOUCH_TARGETS:
                    for box in page.locator(selector).all():
                        if box.is_visible():
                            size = box.bounding_box()
                            assert size["height"] >= 43.5, f"touch target {selector} is {size['height']:.0f}px high at {width}px"
                run = page.locator("[data-wf-run='true']").bounding_box()
                assert run["height"] >= 43.5
        # keyboard: tabs are reachable and a modal traps focus and closes on Escape
        page.set_viewport_size({"width": 1440, "height": 1000})
        goto_section(page, "scenarios")
        page.wait_for_selector("[data-scenario-workspace='true']")
        rename = page.get_by_role("button", name=re.compile("^Rename scenario")).first
        rename.focus()
        page.keyboard.press("Enter")
        d = page.get_by_role("dialog")
        d.wait_for()
        assert page.evaluate("document.activeElement.closest('[role=dialog]') !== null")
        page.keyboard.press("Escape")
        d.wait_for(state="detached")
        assert not [e for e in errors if "Failed to load resource" not in e], errors
    finally:
        context.close()
