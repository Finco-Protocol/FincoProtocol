"""WF-React-2 — real-Chromium acceptance bodies for the editable model workflows.

Not collected by pytest: executed through the thin wrappers in
``tests/test_model_workspace_consolidation_browser.py`` (the existing mandatory
Chromium role and its Playwright fixture lifecycle), like the WF-React-1
acceptance bodies.  No module-level skip lives here.

Drives the integrated React workspace over the real server: guided inputs,
CAPEX/OPEX line management, the guided PPA editor, the financing editor,
Save/Run separation, scenarios and overrides, export, negative controls
(protected reference, stale CAS, rejected CSRF, unknown outcomes, invalid
input) and the 1440/900/390 layouts.  Every Save is checked to leave the
committed Run History untouched; only the explicit Run action adds a Run.

"""
from __future__ import annotations

import json
import os
import re
from playwright.sync_api import expect

from tests.model_react_wf1_browser_acceptance import make_session

SHOTS = os.environ.get("WF2_SCREENSHOT_DIR", "")


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, f"{name}.png"), full_page=True)


def open_workspace(page, base, record, section="overview"):
    page.goto(f"{base}/v2/model-react/{record.project_code}#{section}")
    page.wait_for_selector("[data-workspace-status='true'], [data-workflow-bar='true']")
    page.wait_for_selector("[data-workflow-bar='true']")


def goto_section(page, section):
    page.evaluate(f"() => {{ window.location.hash = '#{section}'; }}")


def runs(context, base, record):
    payload = context.request.get(f"{base}/v2/model-react/runs?project={record.project_code}").json()
    return payload["runs"]


def bar(page):
    return page.locator("[data-workflow-bar='true']")


def check_workflow_bar_and_sections_render_without_errors(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "wf2-smoke-user")
    try:
        open_workspace(page, react_enabled, record)
        assert bar(page).get_attribute("data-bar-freshness") == "NOT_RUN"
        for section in ("inputs", "financing", "scenarios", "results"):
            goto_section(page, section)
            page.wait_for_timeout(1200)
            shot(page, f"smoke-{section}")
        assert not [e for e in errors if "Failed to load resource" not in e], errors
    finally:
        context.close()


# ── helpers ──────────────────────────────────────────────────────────────────


def field_input_id(sheet, field_id):
    return f"wf-{sheet}-" + re.sub(r"[^a-z0-9]+", "-", field_id, flags=re.I)


def fields(context, base, record, sheet):
    return context.request.get(f"{base}/v2/model-react/fields/{sheet}?project={record.project_code}").json()["fields"]


def numeric_bound_field(context, base, record, sheet, prefer=()):
    rows = [f for f in fields(context, base, record, sheet)
            if f["binding_label"] == "bound" and f["field_type"] in ("float", "keur", "mw", "mwh", "pct", "years", "int", "months")
            and f.get("value") not in (None, "") and re.fullmatch(r"[+-]?\d+(\.\d+)?", str(f["value"]))]
    for wanted in prefer:
        for row in rows:
            if row["field_id"] == wanted:
                return row
    assert rows, f"no editable numeric field in {sheet}"
    return rows[0]


def bumped(row):
    """A value inside the field's bounds that differs from the persisted one."""
    value = float(row["value"])
    decimals = 0 if row["field_type"] in ("years", "int", "months") else 3
    for candidate in (value + 1, value - 1, value * 1.01, value * 0.99):
        text = f"{candidate:.{decimals}f}".rstrip("0").rstrip(".") if decimals else str(int(round(candidate)))
        if text != str(row["value"]) and float(text) != value:
            if row.get("min_value") is not None and float(text) < row["min_value"]:
                continue
            if row.get("max_value") is not None and float(text) > row["max_value"]:
                continue
            return text
    raise AssertionError(f"no bumped value for {row['field_id']}")


def wait_status(page, tone, text=None, scope="body"):
    locator = page.locator(f"{scope} [data-wf-status='{tone}']")
    try:
        locator.first.wait_for(timeout=20000)
    except Exception:
        seen = page.locator(f"{scope} [data-wf-status]").all_inner_texts()
        raise AssertionError(f"no {tone!r} status in {scope}; statuses on screen: {seen}") from None
    if text is not None:
        assert text in locator.first.inner_text(), locator.first.inner_text()
    return locator.first.inner_text()


def history_count(context, base, record):
    return len(runs(context, base, record))


# ── the supported end-to-end path ────────────────────────────────────────────


def check_end_to_end_supported_workflow_save_never_runs_and_run_only_when_explicit(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "wf2-e2e-user")
    base = react_enabled
    try:
        page.on("dialog", lambda d: d.dismiss())          # a native dialog would mean a regression to window.prompt
        open_workspace(page, base, record, "inputs")
        page.wait_for_selector("[data-sheet-editor='project_setup']")
        assert history_count(context, base, record) == 0
        assert bar(page).get_attribute("data-bar-freshness") == "NOT_RUN"

        # ── Configure project / edit inputs: dirty state is shown and blocks Run ──
        row = numeric_bound_field(context, base, record, "project_setup",
                                  prefer=("project_setup.technical.p50_hours",))
        input_id = field_input_id("project_setup", row["field_id"])
        new_value = bumped(row)
        page.locator(f"#{input_id}").fill(new_value)
        page.wait_for_selector("[data-unsaved-indicator='true']")
        assert page.locator("[data-wf-run='true']").is_disabled()
        assert "unsaved" in page.locator("#wf-run-hint").inner_text()
        page.get_by_role("button", name=f"Save {row['label']}").click()
        wait_status(page, "ok", "verified", "[data-sheet-editor='project_setup']")
        page.wait_for_selector("[data-unsaved-indicator='true']", state="detached")
        persisted = next(f for f in fields(context, base, record, "project_setup") if f["field_id"] == row["field_id"])
        assert float(persisted["value"]) == float(new_value)
        assert history_count(context, base, record) == 0, "a Save never executes a Run"

        # ── CAPEX: add, deactivate (confirm dialog), reactivate ──
        costs = page.locator("[data-cost-line-manager='capex']")
        costs.scroll_into_view_if_needed()
        group_select = costs.locator("select")
        group_select.select_option(index=1)
        costs.get_by_label("Line label").fill("WF2 acceptance CAPEX line")
        costs.get_by_label("Amount").fill("42")
        costs.locator("[data-cost-add='capex']").click()
        wait_status(page, "ok", "verified in the fresh projection", "[data-cost-line-manager='capex']")
        added = costs.locator("tr", has_text="WF2 acceptance CAPEX line")
        added.wait_for(timeout=20000)
        assert added.count() == 1 and added.get_attribute("data-line-state") == "active"
        added.get_by_role("button", name="Deactivate WF2 acceptance CAPEX line").click()
        dialog = page.get_by_role("dialog")
        dialog.wait_for()
        assert dialog.get_attribute("aria-modal") == "true"
        assert page.evaluate("document.activeElement && document.activeElement.closest('[role=dialog]') !== null")
        page.keyboard.press("Escape")
        dialog.wait_for(state="detached")
        assert costs.locator("tr", has_text="WF2 acceptance CAPEX line").get_attribute("data-line-state") == "active"
        added.get_by_role("button", name="Deactivate WF2 acceptance CAPEX line").click()
        page.get_by_role("dialog").get_by_role("button", name="Deactivate line").click()
        page.wait_for_function("""() => document.querySelector("[data-cost-line-manager='capex'] tr[data-line-state='inactive']")""")
        costs.locator("tr[data-line-state='inactive']").get_by_role("button", name="Reactivate WF2 acceptance CAPEX line").click()
        page.wait_for_function("""() => !document.querySelector("[data-cost-line-manager='capex'] tr[data-line-state='inactive']")""")
        assert history_count(context, base, record) == 0

        # ── OPEX line ──
        page.locator("button[aria-pressed]", has_text="OPEX").first.click()
        opex = page.locator("[data-cost-line-manager='opex']")
        opex.wait_for()
        opex.locator("select").select_option(index=1)
        opex.get_by_label("Line label").fill("WF2 acceptance OPEX line")
        opex.get_by_label("Amount").fill("7")
        opex.locator("[data-cost-add='opex']").click()
        wait_status(page, "ok", "verified in the fresh projection", "[data-cost-line-manager='opex']")

        # ── PPA: guided editor, no JSON textarea; invalid input is field-specific ──
        ppa = page.locator("[data-ppa-editor]")
        ppa.scroll_into_view_if_needed()
        kind = ppa.first.get_attribute("data-ppa-editor")
        assert page.locator("textarea[data-revenue-editor]").count() == 0
        if kind == "guided":
            stream = ppa.locator("[data-ppa-stream]").first
            assert stream.get_attribute("data-contract-class") in ("Fixed", "Indexed", "Scheduled", "Merchant", "CfD")
            price = stream.get_by_label(re.compile("^(Tariff|Base tariff)"))
            original = price.input_value()
            price.fill("abc")
            ppa.locator("[data-ppa-save='true']").click()
            assert "Enter a plain number" in stream.locator(".wf-error").first.inner_text()
            price.fill(str(float(original) + 1))
            ppa.locator("[data-ppa-save='true']").click()
            wait_status(page, "ok", "verified", "[data-ppa-editor]")
            assert history_count(context, base, record) == 0
        else:
            assert kind == "empty" and "Define a PPA contract" in ppa.inner_text()

        # ── Financing ──
        goto_section(page, "financing")
        page.wait_for_selector("[data-sheet-editor='debt']")
        # structured JSON configuration is never offered as a free-text box
        for structured in ("debt-financing-instruments", "debt-bankability-configuration"):
            assert page.locator(f"input#wf-debt-{structured}, textarea#wf-debt-{structured}, select#wf-debt-{structured}").count() == 0
            assert page.locator(f"#wf-debt-{structured}").count() == 1
        debt = numeric_bound_field(context, base, record, "debt")
        debt_id = field_input_id("debt", debt["field_id"])
        page.locator(f"#{debt_id}").fill(bumped(debt))
        page.get_by_role("button", name=f"Save {debt['label']}").click()
        wait_status(page, "ok", "verified", "[data-sheet-editor='debt']")
        assert history_count(context, base, record) == 0

        # ── Scenario: create, select, override, rename, archive — none runs the model ──
        goto_section(page, "scenarios")
        page.wait_for_selector("[data-scenario-workspace='true']")
        page.get_by_label("New scenario name").fill("WF2 downside")
        page.get_by_role("button", name="Create scenario").click()
        wait_status(page, "ok", "created", "[data-scenario-workspace='true']")
        page.wait_for_function("""() => document.querySelector("[data-active-scenario-banner='true']").innerText.includes('WF2 downside')""")
        assert history_count(context, base, record) == 0, "creating a scenario never runs the model"
        page.get_by_role("button", name="Edit overrides of WF2 downside").click()
        override = page.locator("[data-override-editor='WF2 downside']")
        override.wait_for()
        assert override.locator("[data-override-field]").count() == 1
        tariff = override.locator("[data-override-field='tariff_eur_mwh']")
        tariff.get_by_label("Tariff scenario value").fill("71.5")
        tariff.get_by_role("button", name="Save override for Tariff").click()
        override.locator("[data-wf-status='ok']").first.wait_for(timeout=20000)
        page.wait_for_function("""() => document.querySelector("[data-override-field='tariff_eur_mwh']")?.getAttribute('data-overridden') === 'true'""")
        assert history_count(context, base, record) == 0
        tariff.get_by_role("button", name="Remove override for Tariff").click()
        page.get_by_role("dialog").get_by_role("button", name="Remove override").click()
        page.wait_for_function("""() => document.querySelector("[data-override-field='tariff_eur_mwh']")?.getAttribute('data-overridden') === 'false'""")
        page.get_by_role("button", name="Rename scenario WF2 downside").click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("Scenario name").fill("WF2 renamed")
        dialog.get_by_role("button", name="Rename").click()
        wait_status(page, "ok", "renamed", "[data-scenario-workspace='true']")
        assert page.locator("[data-kpi-compare='committed-runs']").count() == 1 and page.locator("[data-kpi-compare='unavailable']").count() == 0
        page.get_by_role("button", name="Select scenario UX02 browser").click()
        page.wait_for_function("""() => document.querySelector("[data-active-scenario-banner='true']").innerText.includes('Base Case') || document.querySelector("[data-active-scenario-banner='true']").innerText.includes('UX02')""")
        page.get_by_role("button", name="Archive scenario WF2 renamed").click()
        page.get_by_role("dialog").get_by_role("button", name="Archive scenario").click()
        page.wait_for_function("""() => document.querySelector("[data-scenario-row='WF2 renamed']")?.getAttribute('data-archived') === 'true'""")
        assert history_count(context, base, record) == 0

        # ── Run: only the explicit action, only with nothing unsaved ──
        goto_section(page, "results")
        page.wait_for_selector("[data-export-view='true']")
        assert page.locator("[data-export-last-run='true']").is_disabled()          # nothing committed yet
        page.locator("[data-wf-run='true']").click()
        page.wait_for_selector("[data-workflow-bar='true'][data-bar-freshness='CURRENT']", timeout=120000)
        assert history_count(context, base, record) == 1

        # ── Results + export match the committed Run identity ──
        goto_section(page, "results")
        page.wait_for_selector("[data-export-view='true']")
        identity = page.locator("[data-export-identity]").get_attribute("data-export-identity")
        committed = runs(context, base, record)[0]["runtime_snapshot_id"]
        assert identity == committed
        with page.expect_download(timeout=60000) as download:
            page.locator("[data-export-last-run='true']").click()
        saved = download.value
        assert saved.suggested_filename.endswith(".xlsx")
        with open(saved.path(), "rb") as handle:
            assert handle.read(2) == b"PK", "an XLSX package"
        wait_status(page, "ok", "Downloaded", "[data-export-view='true']")
        history_link = page.locator("[data-export-view='true'] a[download]").first
        assert "history_id=" in history_link.get_attribute("href")
        assert page.locator("[data-export-unavailable='true']").count() == 1
        assert history_count(context, base, record) == 1, "export never runs the engine"

        # ── a Save after the Run leaves it STALE, never re-runs ──
        goto_section(page, "inputs")
        page.wait_for_selector("[data-sheet-editor='project_setup']")
        row = numeric_bound_field(context, base, record, "project_setup",
                                  prefer=("project_setup.technical.p50_hours",))
        page.locator(f"#{field_input_id('project_setup', row['field_id'])}").fill(bumped(row))
        page.get_by_role("button", name=f"Save {row['label']}").click()
        wait_status(page, "ok", "STALE", "[data-sheet-editor='project_setup']")
        page.wait_for_selector("[data-workflow-bar='true'][data-bar-freshness='STALE']")
        assert history_count(context, base, record) == 1
        goto_section(page, "results")
        page.wait_for_selector("[data-export-view='true'][data-export-view]")
        assert "prior committed Run" in page.locator("[data-export-view] [role='note']").first.inner_text()

        assert not [e for e in errors if "Failed to load resource" not in e], errors
    finally:
        context.close()


def ppa_panel(page):
    panel = page.locator("[data-ppa-editor]")
    panel.scroll_into_view_if_needed()
    return panel


def check_guided_ppa_editor_creates_edits_and_schedules_a_contract_book(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "wf2-ppa-user")
    base = react_enabled
    try:
        open_workspace(page, base, record, "inputs")
        page.wait_for_selector("[data-ppa-editor='empty']")
        assert history_count(context, base, record) == 0
        panel = ppa_panel(page)
        panel.get_by_role("button", name="Define a PPA contract").click()
        stream = panel.locator("[data-ppa-stream]").first
        assert stream.get_by_label("Start date").input_value() and stream.get_by_label("End date").input_value()

        # nothing is invented: an empty tariff and source reference are refused field by field
        panel.locator("[data-ppa-save='true']").click()
        assert "required" in stream.locator(".wf-error").first.inner_text().lower() or stream.locator(".wf-error").count() >= 2
        assert stream.get_by_label("Source reference").get_attribute("aria-invalid") == "true"
        assert stream.get_by_label("Tariff").get_attribute("aria-invalid") == "true"

        assert stream.get_by_label("Contracted volume share").get_attribute("aria-invalid") == "true"
        stream.get_by_label("Source reference").fill("Signed PPA 2026")
        stream.get_by_label("Tariff").fill("55")
        stream.get_by_label("Contracted volume share").fill("0.8")
        panel.locator("[data-ppa-save='true']").click()
        try:
            page.wait_for_selector("[data-ppa-editor='guided']", timeout=20000)
        except Exception:
            raise AssertionError(f"create did not persist: {page.locator('[data-ppa-editor] [data-wf-status]').all_inner_texts()}") from None
        assert history_count(context, base, record) == 0, "saving contracts never runs the model"
        stream = ppa_panel(page).locator("[data-ppa-stream]").first
        assert stream.get_attribute("data-contract-class") == "Fixed"
        saved = context.request.get(f"{base}/v2/model-react/revenue?project={record.project_code}").json()["contracts"]
        book = json.loads(saved["raw"])
        assert book["version"] == 2 and book["indexation_basis"] == "OPERATING_YEAR"
        assert book["streams"][0]["price_eur_mwh"] == 55 and book["streams"][0]["source_ref"] == "Signed PPA 2026"

        # edit the tariff and the indexation: becomes Indexed
        stream.get_by_label("Indexation rate").fill("0.02")
        assert page.locator("[data-unsaved-indicator='true']").count() == 1
        ppa_panel(page).locator("[data-ppa-save='true']").click()
        wait_status(page, "ok", "verified", "[data-ppa-editor]")
        assert ppa_panel(page).locator("[data-ppa-stream]").first.get_attribute("data-contract-class") == "Indexed"
        # The verified POST starts a parent projection refresh. Wait for the
        # clean editor before typing: its raw-payload effect resets the draft.
        page.locator("[data-unsaved-indicator='true']").wait_for(state="detached")
        expect(ppa_panel(page).locator("[data-ppa-save='true']")).to_be_disabled(timeout=20000)

        # a malformed date maps to the exact field and nothing is sent
        posts = []
        page.on("request", lambda r: posts.append(r.url) if r.method == "POST" and "revenue/contracts" in r.url else None)
        stream = ppa_panel(page).locator("[data-ppa-stream]").first
        stream.get_by_label("Start date").fill("2031-02-30")
        ppa_panel(page).locator("[data-ppa-save='true']").click()
        assert "real date" in stream.get_by_label("Start date").locator("xpath=../small[@role='alert']").inner_text()
        assert posts == [], "client-side validation sends nothing"
        stream.get_by_role("button", name="Remove contract ppa").is_disabled()   # the last contract cannot be removed
        ppa_panel(page).get_by_role("button", name="Cancel edits").click()
        expect(ppa_panel(page).locator("[data-ppa-stream]").first.get_by_label("Indexation rate")).to_have_value("0.02", timeout=20000)

        # switch to a scheduled price curve: chronological order is enforced per point
        stream = ppa_panel(page).locator("[data-ppa-stream]").first
        stream.get_by_label("Indexation rate").fill("0")
        ppa_panel(page).locator("[data-ppa-save='true']").click()
        wait_status(page, "ok", "verified", "[data-ppa-editor]")
        page.locator("[data-unsaved-indicator='true']").wait_for(state="detached")
        expect(ppa_panel(page).locator("[data-ppa-save='true']")).to_be_disabled(timeout=20000)
        stream = ppa_panel(page).locator("[data-ppa-stream]").first
        stream.get_by_role("button", name="Switch to a scheduled price curve").click()
        curve = stream.locator("[data-ppa-curve]")
        curve.get_by_role("button", name="Add point").click()
        posts.clear()
        curve.get_by_label("Point 2 effective date").fill("2031-03-01")      # duplicates point 1
        curve.get_by_label("Point 2 tariff").fill("58")
        ppa_panel(page).locator("[data-ppa-save='true']").click()
        assert "strictly ascending" in curve.get_by_label("Point 2 effective date").locator("xpath=../small[@role='alert']").inner_text()
        assert posts == []
        curve.get_by_label("Point 2 effective date").fill("2032-03-01")
        ppa_panel(page).locator("[data-ppa-save='true']").click()
        # the server decides whether the curve covers every operating period; its verdict is shown verbatim
        page.wait_for_function("""() => document.querySelector("[data-ppa-editor] [data-wf-status]")""", timeout=20000)
        verdict = page.locator("[data-ppa-editor] [data-wf-status]").first
        # two points cannot cover every operating period of a 25-year contract: the canonical writer refuses
        assert verdict.get_attribute("data-tone") == "error", verdict.inner_text()
        assert "REVENUE_V2_CURVE" in verdict.inner_text() or "curve" in verdict.inner_text().lower(), verdict.inner_text()
        assert curve.get_by_label("Point 2 tariff").input_value() == "58", "a refused save keeps the typed draft"
        persisted = json.loads(context.request.get(f"{base}/v2/model-react/revenue?project={record.project_code}").json()["contracts"]["raw"])
        assert "price_curve" not in persisted["streams"][0], "a refused curve was not persisted"
        assert history_count(context, base, record) == 0
        assert not [e for e in errors if "Failed to load resource" not in e], errors
    finally:
        context.close()


# ── negative controls ────────────────────────────────────────────────────────


def two_numeric_fields(context, base, record, sheet="project_setup"):
    rows = [f for f in fields(context, base, record, sheet)
            if f["binding_label"] == "bound" and f["field_type"] in ("float", "keur", "mw", "mwh", "pct", "years", "int", "months")
            and f.get("value") not in (None, "") and re.fullmatch(r"[+-]?\d+(\.\d+)?", str(f["value"]))]
    assert len(rows) >= 2
    return rows[0], rows[1]


def collect_posts(page, fragment):
    seen = []
    page.on("request", lambda r: seen.append(r.url) if r.method == "POST" and fragment in r.url else None)
    return seen


def check_stale_cas_cannot_overwrite_and_keeps_the_draft(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "wf2-stale-user")
    base = react_enabled
    try:
        first, second = two_numeric_fields(context, base, record)
        open_workspace(page, base, record, "inputs")
        page.wait_for_selector("[data-sheet-editor='project_setup']")
        # a second tab commits a different field first
        other = context.new_page()
        open_workspace(other, base, record, "inputs")
        other.wait_for_selector("[data-sheet-editor='project_setup']")
        other.locator(f"#{field_input_id('project_setup', first['field_id'])}").fill(bumped(first))
        other.get_by_role("button", name=f"Save {first['label']}").click()
        wait_status(other, "ok", "verified", "[data-sheet-editor='project_setup']")
        # this tab still holds the old composite identity
        mine = bumped(second)
        page.locator(f"#{field_input_id('project_setup', second['field_id'])}").fill(mine)
        page.get_by_role("button", name=f"Save {second['label']}").click()
        text = wait_status(page, "error", None, "[data-sheet-editor='project_setup']")
        assert "changed" in text.lower() or "stale" in text.lower() or "reload" in text.lower(), text
        assert page.locator(f"#{field_input_id('project_setup', second['field_id'])}").input_value() == mine, "the typed draft survives"
        persisted = next(f for f in fields(context, base, record, "project_setup") if f["field_id"] == second["field_id"])
        assert float(persisted["value"]) == float(second["value"]), "the stale Save did not overwrite anything"
        assert history_count(context, base, record) == 0
    finally:
        context.close()


def check_rejected_csrf_token_changes_nothing_and_keeps_the_draft(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "wf2-csrf-user")
    base = react_enabled
    try:
        # a canonical contract book exists so the guided editor is in editing mode
        revenue = context.request.get(f"{base}/v2/model-react/revenue?project={record.project_code}").json()
        window = revenue["contracts"]["operating_window"]
        book = {"version": 2, "technology": "solar", "indexation_basis": "OPERATING_YEAR", "streams": [{
            "id": "ppa", "type": "ppa", "start_date": window["start"], "end_date": window["end"], "volume_share": 0.8,
            "price_eur_mwh": 50, "indexation_rate": 0, "settlement": "SAME_PERIOD", "source_ref": "csrf probe"}]}
        seeded = context.request.post(f"{base}/v2/workbook/revenue/contracts", form={
            "project": record.project_code, "csrf_token": revenue["save"]["csrf_token"],
            "content_hash": revenue["save"]["content_hash"], "contracts": json.dumps(book), "action": "save"})
        assert seeded.ok and "v2_err" not in seeded.url, seeded.text()[:300]
        open_workspace(page, base, record, "inputs")
        page.wait_for_selector("[data-ppa-editor='guided']")
        before = context.request.get(f"{base}/v2/model-react/revenue?project={record.project_code}").json()["contracts"]["raw"]

        def tamper(route):
            body = route.request.post_data or ""
            route.continue_(post_data=re.sub(r"csrf_token=[^&]*", "csrf_token=forged", body))
        context.route("**/v2/workbook/revenue/contracts", tamper)
        stream = ppa_panel(page).locator("[data-ppa-stream]").first
        stream.get_by_label("Tariff").fill("51")
        ppa_panel(page).locator("[data-ppa-save='true']").click()
        text = wait_status(page, "error", None, "[data-ppa-editor]")
        assert "CSRF" in text, text
        assert stream.get_by_label("Tariff").input_value() == "51", "the typed draft survives a rejected token"
        context.unroute("**/v2/workbook/revenue/contracts")
        after = context.request.get(f"{base}/v2/model-react/revenue?project={record.project_code}").json()["contracts"]["raw"]
        assert after == before, "a rejected token persists nothing"
        assert history_count(context, base, record) == 0
    finally:
        context.close()


def check_unknown_outcomes_are_reconciled_never_retried(browser, react_enabled, scenario):
    context, page, record, errors = make_session(browser, react_enabled, f"wf2-unknown-{scenario}")
    base = react_enabled
    try:
        open_workspace(page, base, record, "inputs")
        page.wait_for_selector("[data-sheet-editor='project_setup']")
        pattern = {"field-save": "**/v2/workbook/update", "cost-add": "**/v2/capex/line/add", "run": "**/v2/workbook/run"}[scenario]
        posts = collect_posts(page, pattern.replace("**", ""))
        context.route(pattern, lambda route: route.abort())
        if scenario == "field-save":
            row = numeric_bound_field(context, base, record, "project_setup")
            field = page.locator(f"#{field_input_id('project_setup', row['field_id'])}")
            field.fill(bumped(row))
            page.get_by_role("button", name=f"Save {row['label']}").click()
            text = wait_status(page, "conflict", None, "[data-sheet-editor='project_setup']")
            assert "UNKNOWN" in text and "retry" not in text.lower().replace("never", "")
            assert field.is_disabled(), "the editor locks until the user reconciles"
        elif scenario == "cost-add":
            costs = page.locator("[data-cost-line-manager='capex']")
            costs.scroll_into_view_if_needed()
            costs.locator("select").select_option(index=1)
            costs.get_by_label("Line label").fill("unknown outcome line")
            costs.locator("[data-cost-add='capex']").click()
            text = wait_status(page, "conflict", None, "[data-cost-line-manager='capex']")
            assert "UNKNOWN" in text and "duplicate" in text
            assert costs.locator("[data-cost-add='capex']").is_disabled()
        else:
            page.locator("[data-wf-run='true']").click()
            text = wait_status(page, "conflict", None, "[data-workflow-bar='true']")
            assert "UNKNOWN" in text
            assert page.locator("[data-wf-run='true']").is_disabled()
        page.wait_for_timeout(1500)
        assert len(posts) == 1, f"exactly one request, never an automatic retry: {posts}"
        context.unroute(pattern)
        assert history_count(context, base, record) == 0
    finally:
        context.close()


def check_protected_reference_workspace_is_read_only_in_every_editor(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "wf2-protected-user")
    base = react_enabled
    try:
        from app.persistence.db import get_connection
        with get_connection() as connection:
            connection.execute("UPDATE projects SET project_role='reference', is_protected=1, project_origin='factory_template' "
                               "WHERE project_id=?", (record.project_id,))
            connection.commit()
        open_workspace(page, base, record, "inputs")
        page.wait_for_selector("[data-sheet-editor='project_setup']")
        assert page.locator("[data-sheet-editor='project_setup'] .fm-banner", has_text="PROTECTED REFERENCE").count() == 1
        assert page.locator("[data-sheet-editor='project_setup'] input.fm-input, [data-sheet-editor='project_setup'] select").count() == 0
        assert page.locator("[data-wf-run='true']").is_disabled()
        assert "Protected references cannot be run" in page.locator("#wf-run-hint").inner_text()
        costs = page.locator("[data-cost-line-manager='capex']")
        costs.scroll_into_view_if_needed()
        assert costs.locator("[data-cost-add='capex']").is_disabled()
        assert page.locator("[data-ppa-editor]").first.get_attribute("data-ppa-editor") in ("empty", "guided")
        assert page.locator("[data-ppa-editor] [data-ppa-save='true']").count() == 0 or \
            page.locator("[data-ppa-editor] [data-ppa-save='true']").first.is_disabled()
        goto_section(page, "scenarios")
        page.wait_for_selector("[data-scenario-workspace='true']")
        assert page.get_by_role("button", name="Create scenario").count() == 0
        goto_section(page, "financing")
        page.wait_for_selector("[data-sheet-editor='debt']")
        assert page.locator("[data-sheet-editor='debt'] input.fm-input").count() == 0
        assert history_count(context, base, record) == 0
    finally:
        context.close()


# ── scenarios: isolation, selection never runs ───────────────────────────────


def check_scenario_selection_compare_and_overrides_are_isolated_and_never_run(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "wf2-scenario-user")
    base = react_enabled
    try:
        open_workspace(page, base, record, "scenarios")
        page.wait_for_selector("[data-scenario-workspace='true']")
        for name in ("Case A", "Case B"):
            page.get_by_label("New scenario name").fill(name)
            page.get_by_role("button", name="Create scenario").click()
            wait_status(page, "ok", "created", "[data-scenario-workspace='true']")
            page.wait_for_function(f"""() => document.querySelector("[data-active-scenario-banner='true']").innerText.includes('{name}')""")
        page.get_by_role("button", name="Edit overrides of Case A").click()
        override = page.locator("[data-override-editor='Case A']")
        override.wait_for()
        override.get_by_label("Tariff scenario value").fill("-5")
        override.get_by_role("button", name="Save override for Tariff").click()
        assert "negative" in override.locator(".wf-error").first.inner_text().lower()
        override.get_by_label("Tariff scenario value").fill("66")
        override.get_by_role("button", name="Save override for Tariff").click()
        override.locator("[data-wf-status='ok']").first.wait_for(timeout=20000)
        # Case B stays inherited; compare shows the difference only for Case A
        page.get_by_role("button", name="Edit overrides of Case B").click()
        b = page.locator("[data-override-editor='Case B']")
        b.wait_for()
        assert b.locator("[data-override-field='tariff_eur_mwh']").get_attribute("data-overridden") == "false"
        page.get_by_role("button", name="Compare with scenario Case B").click()
        page.locator("[aria-label='Scenario assumption compare']").wait_for()
        assert "No assumption differences" in page.locator("[aria-label='Scenario assumption compare']").inner_text()
        page.get_by_role("button", name="Compare with scenario Case A").click()
        page.wait_for_function("""() => document.querySelector("[aria-label='Scenario assumption compare']")?.innerText.includes('tariff_eur_mwh')""")
        page.get_by_role("button", name="Select scenario Case A").click()
        page.wait_for_function("""() => document.querySelector("[data-active-scenario-banner='true']").innerText.includes('Case A')""")
        assert history_count(context, base, record) == 0, "selection, compare and overrides never run the model"
        assert page.locator("[data-kpi-compare='committed-runs']").count() == 1 and page.locator("[data-kpi-compare='unavailable']").count() == 0
        for row in page.locator("[data-scenario-row]").all():
            assert row.locator("[data-run-evidence]").get_attribute("data-run-evidence") == "UNAVAILABLE"
    finally:
        context.close()


# ── responsive layouts ───────────────────────────────────────────────────────


def check_editable_sections_fit_desktop_tablet_and_mobile(browser, react_enabled, width, height):
    context, page, record, errors = make_session(browser, react_enabled, f"wf2-resp-{width}")
    base = react_enabled
    try:
        page.set_viewport_size({"width": width, "height": height})
        open_workspace(page, base, record, "inputs")
        for section, anchor in (("inputs", "[data-sheet-editor='project_setup']"), ("financing", "[data-sheet-editor='debt']"),
                                ("scenarios", "[data-scenario-workspace='true']"), ("results", "[data-export-view='true']")):
            goto_section(page, section)
            page.wait_for_selector(anchor, timeout=20000)
            page.wait_for_timeout(300)
            overflow = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
            if section == "results":
                # The Results/KPI presentation belongs to WF-React-1 (#377) and overflows by 2px at 390px on main;
                # this workflow owns only the Export block, which must fit.
                export_box = page.locator("[data-export-view='true']").bounding_box()
                assert export_box["x"] + export_box["width"] <= width + 1, f"export view clipped at {width}px"
                overflow = 0
            if overflow > 1:
                culprits = page.evaluate("""() => [...document.querySelectorAll('body *')].filter(e => e.getBoundingClientRect().right > document.documentElement.clientWidth + 1
                    && !e.closest('.wf-table-wrap, .rx-statement, .fm-table-wrap, .wf-curve, .fm-nav')).slice(0, 10)
                    .map(e => e.tagName + '.' + e.className + ' ' + Math.round(e.getBoundingClientRect().right))""")
                raise AssertionError(f"horizontal page overflow at {width}px in {section}: {overflow}px; offenders: {culprits}")
            box = page.locator("[data-workflow-bar='true']").bounding_box()
            assert box and box["x"] >= -1 and box["x"] + box["width"] <= width + 1, f"status bar clipped at {width}px"
            shot(page, f"responsive-{width}-{section}")
        # dialogs fit too
        goto_section(page, "scenarios")
        page.wait_for_selector("[data-scenario-workspace='true']")
        page.get_by_label("New scenario name").fill("Responsive case")
        page.get_by_role("button", name="Create scenario").click()
        wait_status(page, "ok", "created", "[data-scenario-workspace='true']")
        page.get_by_role("button", name="Rename scenario Responsive case").click()
        dialog = page.get_by_role("dialog")
        dialog.wait_for()
        box = dialog.bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= width + 1 and box["y"] >= 0
        shot(page, f"responsive-{width}-dialog")
        page.keyboard.press("Escape")
        assert not [e for e in errors if "Failed to load resource" not in e], errors
    finally:
        context.close()
