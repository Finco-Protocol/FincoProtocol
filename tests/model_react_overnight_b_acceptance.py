"""Overnight B — React Institutional Model MVP correction: real-Chromium acceptance bodies.

Not collected by pytest: executed through the thin wrappers in
``tests/test_model_workspace_consolidation_browser.py`` (the existing mandatory Chromium role).  No
module-level skip lives here.  Every project is a disposable local Working Copy; nothing touches a
deployed environment.

F02 statement identity · F03 Run identity · F04 Save scope · F05/F06 label and escape defects ·
U01 Inputs layout · U02 plain language · U03 responsive navigation · model-truth presentation.
Screenshots go under ``$ONB_SCREENSHOT_DIR`` as ``onb-*.png``.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

from tests.model_react_mvp_acceptance import session as vertical_session
from tests.model_react_wf1_browser_acceptance import SECTIONS, api, open_section, run_canonical
from tests.react_run_identity import text as run_text

SHOTS = os.environ.get("ONB_SCREENSHOT_DIR", "")
KINDS = ("solar", "wind", "data_center", "ev_charging")
WIDTHS = (320, 390, 768, 1440)
SHEET_LABELS = ("Profit & Loss", "Balance Sheet", "Cash Flow (PF waterfall)", "CFADS", "Debt", "Distributions")
ESCAPE = re.compile(r"\\u[0-9a-fA-F]{4}")
DOUBLE_UNIT = re.compile(r"\(([^()\s]+)\)\s*\(\1\)")


def shot(page, name, full=True):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, f"onb-{name}.png"), full_page=full)


def settle_inputs(page):
    """Inputs is fully loaded: every editor has replaced its loading note."""
    page.wait_for_selector("[data-react-workspace-version]")
    page.wait_for_function("""() => !/Loading/.test(document.body.innerText)
        && document.querySelector("[data-sheet-editor='project_setup']") && document.querySelector("[data-input-grid]")
        && document.querySelector("[aria-label$='line items']") && document.querySelector("[data-ppa-editor]")""", timeout=30000)


def project_identity(context, base, record):
    return api(context, base, "workspace", record.project_code)["project"]


def horizontal_overflow(page):
    return page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 1")


# ── F02: authoritative statement identity ────────────────────────────────────────────────────────────────────

def check_statement_identity_is_the_authorized_project_in_every_vertical(browser, base, kind):
    context, page, record, errors = vertical_session(browser, base, f"onb-id-{kind}", kind)
    try:
        run_canonical(context, base, record.project_code)
        project = project_identity(context, base, record)
        open_section(page, base, record.project_code, "statements")        # direct link, NO query metadata
        assert "?" not in page.url.split("#")[0] or "projectId" not in page.url, page.url
        page.wait_for_selector("[data-statement-project]")
        assert page.locator("[data-statement-project-code]").first.get_attribute("data-statement-project-code") == project["code"]
        subtitle = page.locator("[data-statement-project-name]").first
        assert subtitle.get_attribute("data-statement-project-name") == project["name"]
        assert project["project_type"] and project["project_type"] in subtitle.inner_text(), (kind, subtitle.inner_text())
        body = page.inner_text("body")
        for placeholder in ("PRJ-0241", "FINCO Model project", "Solar PV", "Adriatic"):
            assert placeholder not in body, f"{placeholder!r} is demo content, never a live Run identity ({kind})"
        # all six destinations keep the identity and the persisted values
        canonical = api(context, base, "statements", record.project_code)
        assert canonical["project"]["code"] == project["code"] and canonical["project"]["project_type"] == project["project_type"]
        for label in SHEET_LABELS:
            page.get_by_role("tab", name=label, exact=True).click()
            assert page.locator("[data-statement-project-code]").first.get_attribute("data-statement-project-code") == project["code"], label
            assert page.locator("[data-statement-project-name]").first.get_attribute("data-statement-project-name") == project["name"], label
            assert page.locator("[data-statement-project]").count() == 1, label
        shot(page, f"statement-identity-{kind}")
        # reload keeps the identity
        page.reload()
        page.wait_for_selector("[data-statement-project-code]")
        assert page.locator("[data-statement-project-code]").first.get_attribute("data-statement-project-code") == project["code"]
        assert errors == [], errors
    finally:
        context.close()


def check_hostile_or_stale_query_cannot_change_the_statement_identity(browser, base):
    context, page, record, errors = vertical_session(browser, base, "onb-hostile", "wind")
    try:
        run_canonical(context, base, record.project_code)
        project = project_identity(context, base, record)
        hostile = "?project=EVIL%20CORP&projectId=PRJ-0241&technology=Solar%20PV&mode=reference&statement=cfads&parentReferenceId=PRJ-0219"
        page.goto(f"{base}/v2/model-react/{record.project_code}{hostile}#statements")
        page.wait_for_selector("[data-statement-project-code]")
        assert page.locator("[data-statement-project-code]").first.get_attribute("data-statement-project-code") == project["code"]
        assert page.locator("[data-statement-project-name]").first.get_attribute("data-statement-project-name") == project["name"]
        body = page.inner_text("body")
        for hostile_text in ("EVIL CORP", "PRJ-0241", "Solar PV", "PRJ-0219"):
            assert hostile_text not in body, hostile_text
        # the query still selects a VIEW (the CFADS sheet) but never identity or mode
        assert page.get_by_role("tab", name="CFADS", exact=True).get_attribute("aria-selected") == "true"
        assert "REFERENCE" not in page.locator("h1").first.inner_text().upper()
        page.reload()
        page.wait_for_selector("[data-statement-project-code]")
        assert page.locator("[data-statement-project-code]").first.get_attribute("data-statement-project-code") == project["code"]
        # a stale/hostile query on the Results and Analysis destinations also changes no identity
        for section in ("results", "analysis"):
            page.goto(f"{base}/v2/model-react/{record.project_code}{hostile}#{section}")
            page.wait_for_selector(f"[data-{section}-view]")
            assert project["name"] in page.locator(f"[data-{section}-view]").first.inner_text() if section == "results" else True
            assert "EVIL CORP" not in page.inner_text("body")
        assert errors == [], errors
    finally:
        context.close()


def check_switching_projects_never_carries_the_previous_statement_identity(browser, base):
    context, page, first, errors = vertical_session(browser, base, "onb-switch", "solar")
    try:
        from app.services.reference_seed_service import create_reference_seeded_project

        second = create_reference_seeded_project(user_id="onb-switch", template_source="generic_data_center_reference",
                                                 requested_name="Switch target", capacity_mw=20.0)
        run_canonical(context, base, first.project_code)
        run_canonical(context, base, second.project_code)
        a, b = project_identity(context, base, first), project_identity(context, base, second)
        open_section(page, base, first.project_code, "statements")
        page.wait_for_selector("[data-statement-project-code]")
        assert page.locator("[data-statement-project-code]").first.get_attribute("data-statement-project-code") == a["code"]
        # in-app switch through My Projects, then a direct link to the other project
        page.get_by_role("link", name="My Projects").first.click()
        page.wait_for_selector("[data-library-view='true']")
        page.goto(f"{base}/v2/model-react/{second.project_code}#statements")
        page.wait_for_selector("[data-statement-project-code]")
        assert page.locator("[data-statement-project-code]").first.get_attribute("data-statement-project-code") == b["code"]
        text = page.inner_text("body")
        assert a["name"] not in text and a["code"] not in text, "the previous project identity must not survive"
        page.go_back()
        page.go_back()
        assert errors == [], errors
    finally:
        context.close()


def check_missing_or_conflicting_identity_fails_visibly(browser, base):
    context, page, record, errors = vertical_session(browser, base, "onb-fail", "wind")
    try:
        run_canonical(context, base, record.project_code)
        # (1) statements that name ANOTHER project: nothing is shown under the wrong identity
        def conflicting(route):
            response = route.fetch()
            body = response.json()
            body["project"]["code"] = "another-project"
            body["project"]["name"] = "Another Project"
            route.fulfill(response=response, json=body)

        page.route("**/v2/model-react/statements*", conflicting)
        page.goto(f"{base}/v2/model-react/{record.project_code}#statements")
        page.wait_for_selector("[data-statement-identity='conflict']")
        assert page.locator("[data-statement-identity='conflict']").get_attribute("role") == "alert"
        assert page.locator("td[data-canonical], button.fm-sw-cell-button").count() == 0, "no statement cell may render"
        assert "Another Project" in page.inner_text("[data-statement-identity='conflict']")
        for section in ("results", "analysis"):
            page.goto(f"{base}/v2/model-react/{record.project_code}#{section}")
            page.reload()
            page.wait_for_selector("[data-statement-identity='conflict']")
            assert page.locator("[data-metric-label]").count() == 0
        page.unroute("**/v2/model-react/statements*")
        # (2) a workspace that carries no usable identity: the statement fails visibly, never as a Solar demo project
        def nameless(route):
            response = route.fetch()
            body = response.json()
            body["project"]["name"] = ""
            body["project"]["code"] = ""
            route.fulfill(response=response, json=body)

        page.route("**/v2/model-react/workspace*", nameless)
        page.goto(f"{base}/v2/model-react/{record.project_code}#statements")
        page.reload()
        page.wait_for_selector("[data-statement-identity]")
        assert page.locator("[data-statement-identity='missing'], [data-statement-identity='conflict']").count() >= 1
        body_text = page.inner_text("body")
        for placeholder in ("PRJ-0241", "Solar PV", "FINCO Model project"):
            assert placeholder not in body_text
        shot(page, "statement-identity-missing")
    finally:
        context.close()


# ── F03: Run identity ────────────────────────────────────────────────────────────────────────────────────

def two_runs(context, base, record):
    """Two committed Runs created within the same minute (and therefore the same hour)."""
    run_canonical(context, base, record.project_code)
    run_canonical(context, base, record.project_code)
    rows = api(context, base, "runs", record.project_code)["runs"]
    assert len(rows) >= 2, rows
    return rows[0], rows[1]


def check_two_runs_in_the_same_hour_are_distinguishable_everywhere(browser, base):
    context, page, record, errors = vertical_session(browser, base, "onb-runs", "solar")
    try:
        latest, earlier = two_runs(context, base, record)
        a, b = latest["runtime_snapshot_id"], earlier["runtime_snapshot_id"]
        assert a != b and a[:12] == b[:12], "the audit collision: truncated snapshot ids are identical"
        assert run_text(a) != run_text(b), "the presented identity distinguishes the two Runs"
        # Results: the Last Run is the latest one, bound to its exact canonical identifiers
        open_section(page, base, record.project_code, "results")
        context_card = page.locator("[data-run-context]")
        assert context_card.locator("[data-run-identity]").get_attribute("data-run-identity") == a
        assert run_text(a) in context_card.inner_text() and run_text(b) not in context_card.inner_text()
        # Run History: one row per committed Run, every row bound to its own history id and snapshot id
        rows = page.locator("[data-run-history-row]")
        assert rows.count() == len(api(context, base, "runs", record.project_code)["runs"])
        shown = {}
        for index in range(rows.count()):
            row = rows.nth(index)
            identity = row.locator("[data-run-identity]")
            shown[row.get_attribute("data-run-history-row")] = (identity.get_attribute("data-run-identity"), row.inner_text())
        assert shown[latest["history_id"]][0] == a and shown[earlier["history_id"]][0] == b
        assert run_text(a) in shown[latest["history_id"]][1] and run_text(b) in shown[earlier["history_id"]][1]
        texts = [re.sub(r"\s+", " ", v[1]) for v in shown.values()]
        assert len({run_text(v[0]) for v in shown.values()}) == len(shown), "no two history rows may read the same"
        # the full identifier and the history id are available through an accessible disclosure + copy control
        first = rows.nth(0)
        # keyboard: the disclosure is a native details/summary — focus it, Enter opens, Enter closes, Copy is reachable by Tab
        first.locator("summary").focus()
        page.keyboard.press("Enter")
        assert first.locator("details").evaluate("d => d.open") is True
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.getAttribute('aria-label')") == "Copy the full snapshot identifier"
        first.locator("summary").focus()
        page.keyboard.press("Enter")
        assert first.locator("details").evaluate("d => d.open") is False
        first.locator("summary").click()
        assert a in first.locator("[data-run-full-snapshot]").inner_text() or first.locator("[data-run-full-snapshot]").get_attribute("data-run-full-snapshot") == a
        assert first.locator("[data-run-full-history]").get_attribute("data-run-full-history") == latest["history_id"]
        copy = first.get_by_role("button", name=re.compile("Copy the full snapshot identifier"))
        assert copy.count() == 1
        shot(page, "run-history-two-runs")
        # Statements, Overview, Export and Scenarios use the same presentation
        open_section(page, base, record.project_code, "statements")
        assert page.locator(".fm-sw-run [data-run-identity]").first.get_attribute("data-run-identity") == a
        assert run_text(a) in page.locator(".fm-sw-run").first.inner_text()
        open_section(page, base, record.project_code, "overview")
        assert page.locator("[data-workspace-status] [data-run-identity]").get_attribute("data-run-identity") == a
        open_section(page, base, record.project_code, "results")
        export = page.locator("[data-export-view]")
        assert export.locator("[data-run-identity]").first.get_attribute("data-run-identity") == a
        for row_id, (snapshot, _text) in shown.items():
            assert export.locator(f"[data-run-identity='{snapshot}']").count() >= 1
        assert "Ran at" not in export.inner_text(), "the Run label already carries the time"
        open_section(page, base, record.project_code, "scenarios")
        evidence = page.locator("[data-scenario-row]", has=page.locator("text=Base Case")).first.locator("[data-run-evidence]")
        assert evidence.locator("[data-run-identity]").get_attribute("data-run-identity") in (a, b)
        # a project with committed Runs shows them in the Library by the same contract
        page.goto(f"{base}/v2/model-react/")
        page.wait_for_selector("[data-library-view='true']")
        assert page.locator(f"[data-run-identity='{a}']").count() >= 1
        # Run History ids are unchanged canonical values
        after = api(context, base, "runs", record.project_code)["runs"]
        assert [r["history_id"] for r in after][:2] == [latest["history_id"], earlier["history_id"]]
        assert errors == [], errors
    finally:
        context.close()


def check_scenario_comparison_and_results_refer_to_the_intended_run(browser, base):
    context, page, record, errors = vertical_session(browser, base, "onb-compare", "solar")
    try:
        latest, earlier = two_runs(context, base, record)
        open_section(page, base, record.project_code, "scenarios")
        page.wait_for_selector("[data-kpi-compare='committed-runs']")
        page.wait_for_function("() => document.querySelectorAll(\"[data-kpi-compare='committed-runs'] .fi-run-option\").length >= 2", timeout=30000)
        options = page.locator("[data-kpi-compare='committed-runs'] .fi-run-option")
        # each selectable Run reads by its formatted identity; the two are visibly different
        labels = [options.nth(i).inner_text() for i in range(options.count())]
        assert run_text(latest["runtime_snapshot_id"]) in labels[0] and run_text(earlier["runtime_snapshot_id"]) in labels[1]
        assert labels[0].split("\n")[0] != labels[1].split("\n")[0]
        options.nth(1).locator("input").check()
        page.get_by_role("button", name="Read selected Run evidence").click()
        comparison = page.locator("[aria-label='Scenario KPI comparison']")
        comparison.wait_for(timeout=30000)
        text = comparison.inner_text()
        assert earlier["history_id"] in text and run_text(earlier["runtime_snapshot_id"]) in text, "the comparison reads the selected Run"
            assert comparison.locator(f"[data-snapshot-id='{earlier['runtime_snapshot_id']}']").count() == 1
        assert latest["history_id"] not in text, "and only the selected Run"
        assert errors == [], errors
    finally:
        context.close()


# ── F04: Save scope + U01: Inputs workspace ─────────────────────────────────────────────────────────────────

OBSOLETE = ("out of this PR", "PR's scope", "NOT saved through the scalar grid writer", "grid/cost-lines/save",
            "composite CAS", "Composite", "RuntimeResult", "Partial path", "PARTIAL path", "R8/N02", "inputs_section")


def check_inputs_save_scope_language_is_accurate_and_free_of_engineering_copy(browser, base):
    context, page, record, errors = vertical_session(browser, base, "onb-scope", "solar")
    try:
        open_section(page, base, record.project_code, "inputs")
        settle_inputs(page)
        body = page.inner_text("body")
        for obsolete in OBSOLETE:
            assert obsolete not in body, f"obsolete or engineering copy still visible: {obsolete!r}"
        # the in-page guide names every writer and Run separately
        guide = page.locator("[data-save-scope-guide]")
        guide.locator("summary").click()
        text = guide.inner_text()
        for editor in ("Project setup", "Assumptions", "CAPEX line items", "OPEX line items", "Revenue & PPA contracts",
                       "Financing", "Scenario overrides", "Run"):
            assert editor in text, editor
        assert "Nothing saves automatically" in text and "no Save runs the model" in text
        # every editor declares its own scope next to its controls
        for marker in ("project_setup", "grid", "cost-lines"):
            assert page.locator(f"[data-save-scope='{marker}']").count() == 1, marker
        assert page.locator("[data-save-scope='cost-lines']").inner_text().count("CAPEX") >= 1
        # there is no global Save: the only Save buttons are the editors' own
        assert page.get_by_role("button", name=re.compile(r"^Save all", re.I)).count() == 0
        # the CAPEX/OPEX scope follows the sheet that is open
        page.locator("[data-inputs-jump] [data-jump-label='OPEX']").click()
        page.wait_for_function("() => /OPEX line below/.test(document.querySelector(\"[data-save-scope='cost-lines']\")?.innerText)")
        page.locator("[data-inputs-jump] [data-jump-label='CAPEX']").click()
        page.wait_for_function("() => /CAPEX line below/.test(document.querySelector(\"[data-save-scope='cost-lines']\")?.innerText)")
        open_section(page, base, record.project_code, "financing")
        assert page.locator("[data-save-scope='debt']").count() == 1
        open_section(page, base, record.project_code, "scenarios")
        assert errors == [], errors
    finally:
        context.close()


def check_scalar_save_persists_after_reload_and_never_saves_another_editor(browser, base):
    context, page, record, errors = vertical_session(browser, base, "onb-save", "solar")
    try:
        from tests.model_react_wf1_browser_acceptance import CIT_CELL, SAVE_BUTTON
        open_section(page, base, record.project_code, "inputs")
        settle_inputs(page)
        cell = page.locator(CIT_CELL)
        before = cell.input_value()
        value = "21" if before != "21" else "22"
        cell.fill(value)
        # an unsaved draft in ANOTHER editor (Project setup) is never saved by the grid Save
        setup = page.locator("[data-sheet-editor='project_setup'] input[type='text']").nth(0)
        setup_before = setup.input_value()
        setup.fill(setup_before + " draft")
        page.locator(SAVE_BUTTON).click()
        page.wait_for_function("() => document.querySelector('#rx-grid-save').dataset.saveState === 'saved'")
        assert setup.input_value() == setup_before + " draft", "the setup draft is untouched by the grid Save"
        persisted = api(context, base, "fields/project_setup", record.project_code)
        assert not any(f.get("value") == setup_before + " draft" for f in persisted["fields"]), "nothing from the other editor was saved"
        page.reload()
        settle_inputs(page)
        assert page.locator(CIT_CELL).input_value() == value, "the scalar Save survives a reload"
        grid = api(context, base, "inputs", record.project_code)["grid"]
        cit = next(r for s in grid["sections"] for c in s["categories"] for r in c["rows"] if r["field_id"] == "tax.assumptions.cit_rate_pct")
        assert float(cit["value"]) == float(value)
        assert len(api(context, base, "runs", record.project_code)["runs"]) == 0, "Save never runs the model"
        assert errors == [], errors
    finally:
        context.close()


def check_inputs_are_compact_complete_and_navigable(browser, base, kind, width, max_height):
    context, page, record, errors = vertical_session(browser, base, f"onb-inputs-{kind}-{width}", kind)
    try:
        page.set_viewport_size({"width": width, "height": 900 if width > 500 else 844})
        open_section(page, base, record.project_code, "inputs")
        settle_inputs(page)
        height = page.evaluate("document.documentElement.scrollHeight")
        assert height <= max_height, f"{kind} Inputs at {width}px is {height}px tall (limit {max_height}; audit baseline 11,889 / 15,199)"
        assert not horizontal_overflow(page), "Inputs must not scroll the document sideways"
        # no editable control was lost to grouping: every editable canonical cell and bound field has its input
        grid = api(context, base, "inputs", record.project_code)["grid"]
        editable = [r["field_id"] for s in grid["sections"] for c in s["categories"] for r in c["rows"] if r["editable"] and grid["editable"]]
        present = set(page.locator("[data-grid-cell]").evaluate_all("els => els.map(e => e.dataset.gridCell)"))
        assert set(editable) <= present and len(present) == len(editable), (sorted(set(editable) - present), sorted(present - set(editable)))
        for cell_id in editable[:5]:
            assert page.locator(f"[data-grid-cell='{cell_id}']").is_enabled()
        setup_fields = api(context, base, "fields/project_setup", record.project_code)["fields"]
        bound = [f for f in setup_fields if f["binding_label"] == "bound"]
        assert page.locator("[data-sheet-editor='project_setup'] input, [data-sheet-editor='project_setup'] select").count() >= len(bound)
        # derived rows are separate from editable ones and still show their authority label
        derived = page.locator("[data-row-state='derived']")
        assert derived.count() > 0 and all(derived.nth(i).locator(".rx-state-reason").count() == 1
                                           for i in range(min(derived.count(), 6)))
        assert page.locator("[data-row-state='editable'] input").count() == len(editable)
        # keyboard: a section summary toggles with Space/Enter and an editable cell is reachable by Tab from it
        summary = page.locator("details.rx-input-section > summary").first
        was_open = summary.evaluate("s => s.parentElement.open")
        summary.focus()
        page.keyboard.press("Enter")
        assert summary.evaluate("s => s.parentElement.open") is (not was_open)
        page.keyboard.press("Enter")
        assert summary.evaluate("s => s.parentElement.open") is was_open
        # Expand all reveals every section; the collapsed ones hold only non-editable rows
        page.locator("[data-grid-expand-all]").click()
        assert page.locator("details.rx-input-section:not([open])").count() == 0
        page.locator("[data-grid-collapse-derived]").click()
        for section in page.locator("details.rx-input-section:not([open])").all():
            assert section.locator("[data-row-state='editable']").count() == 0
        # anchored navigation reaches every group; Financing is its own destination
        for label, target in (("Project setup", "wf-inputs-setup"), ("Assumptions", "wf-inputs-grid"), ("CAPEX", "wf-inputs-costs"),
                              ("OPEX", "wf-inputs-costs"), ("Revenue & PPA", "wf-inputs-revenue")):
            page.locator(f"[data-inputs-jump] [data-jump-label='{label}']").click()
            assert page.locator(f"#{target}").bounding_box()["y"] < 900 + 50
            assert page.evaluate("id => document.activeElement && document.activeElement.id", target) == target
        # a section holding an unsaved edit cannot be collapsed and says so on its summary
        first_cell = page.locator("details.rx-input-section[open] [data-grid-cell]").first
        section_of_cell = first_cell.locator("xpath=ancestor::details[contains(@class,'rx-input-section')]")
        first_cell.fill("7")
        section_of_cell.locator("[data-staged-in-section]").wait_for(timeout=10000)          # the badge renders one React tick after the edit
        section_of_cell.locator("summary").click()
        page.wait_for_timeout(300)                                                          # the toggle handler re-opens the section
        assert section_of_cell.evaluate("d => d.open") is True, "a section with a staged edit stays open"
        assert section_of_cell.locator("[data-staged-in-section]").count() == 1
        page.locator("#wf-inputs-grid [data-discard='true']").click()
        page.wait_for_function("() => !document.querySelector('[data-staged-in-section]')")
        # the OPEX jump request is not replayed when Inputs is entered again later
        page.locator("[data-inputs-jump] [data-jump-label='OPEX']").click()
        page.wait_for_function("() => /OPEX line below/.test(document.querySelector(\"[data-save-scope='cost-lines']\")?.innerText)")
        page.locator("[data-workspace-nav] a", has_text="Statements").click()
        page.locator("[data-workspace-nav] a", has_text="Inputs").click()
        settle_inputs(page)
        assert "CAPEX line below" in page.locator("[data-save-scope='cost-lines']").inner_text(), "Inputs re-opens on CAPEX, not on a past click"
        page.locator("[data-inputs-jump] [data-jump-label='Financing']").click()
        page.wait_for_selector("[data-sheet-editor='debt']")
        assert page.url.endswith("#financing")
        if kind == "solar" or width == 390:
            shot(page, f"inputs-{kind}-{width}")
        assert errors == [], errors
    finally:
        context.close()


def check_protected_reference_inputs_stay_visible_and_read_only(browser, base):
    context, page, record, errors = vertical_session(browser, base, "onb-ref", "solar")
    try:
        library = context.request.get(f"{base}/v2/model-react/library").json()
        reference = next(p for p in library["references"] if "solar" in (p["template_source"] + p["project_type"]).lower())
        page.goto(f"{base}/v2/model-react/{reference['code']}#inputs")
        page.reload()
        page.wait_for_selector("[data-input-grid]")
        page.wait_for_function("() => !/Loading/.test(document.body.innerText)")
        assert page.locator("[data-grid-cell]").count() == 0, "a protected reference exposes no editable cell"
        assert page.locator("[data-locked-value]").count() > 0
        assert page.locator("details.rx-input-section:not([open])").count() == 0, "a read-only grid starts fully expanded"
        assert "REFERENCE" in page.inner_text("h1").upper()
        assert page.locator("#rx-grid-save").is_disabled()
        assert errors == [], errors
    finally:
        context.close()


# ── U03: responsive navigation ─────────────────────────────────────────────────────────────────────────────────

NAV_LABELS = ("Inputs", "Statements", "Financing", "Results", "Scenarios", "Analysis", "Model checks", "Trust")


def nav_state(page):
    return page.evaluate("""() => {
        const nav = document.querySelector('[data-workspace-nav]');
        const box = nav.getBoundingClientRect();
        const links = Array.from(nav.querySelectorAll('a')).map(a => { const r = a.getBoundingClientRect();
          return { text: a.innerText.replace(/\\s+/g, ' ').trim(), inView: r.left >= box.left - 1 && r.right <= box.right + 1,
                   height: r.height, current: a.getAttribute('aria-current') === 'page' }; });
        return { scroll: nav.scrollLeft, canScroll: nav.scrollWidth > nav.clientWidth + 1, links,
                 docOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1 };
    }""")


FOCUS_IN_VIEW = """() => { const a = document.activeElement, n = document.querySelector('[data-workspace-nav]');
  if (!a || !n.contains(a)) return false; const r = a.getBoundingClientRect(), b = n.getBoundingClientRect();
  return r.left >= b.left - 1 && r.right <= b.right + 1; }"""


ACTIVE_IN_VIEW = """() => { const n = document.querySelector('[data-workspace-nav]'), a = n && n.querySelector('a[aria-current="page"]');
  if (!a) return false; const r = a.getBoundingClientRect(), b = n.getBoundingClientRect(); return r.left >= b.left - 1 && r.right <= b.right + 1; }"""


def check_workspace_navigation_is_discoverable_keyboard_operable_and_never_overflows_the_page(browser, base):
    context, page, record, errors = vertical_session(browser, base, "onb-nav", "solar")
    try:
        for width in WIDTHS:
            page.set_viewport_size({"width": width, "height": 844})
            open_section(page, base, record.project_code, "inputs")
            page.wait_for_function(ACTIVE_IN_VIEW, timeout=3000)
            state = nav_state(page)
            assert [l["text"].split(" ", 1)[-1] for l in state["links"]] == list(NAV_LABELS), (width, state["links"])
            assert not state["docOverflow"], f"document-level horizontal overflow at {width}px"
            current = [l for l in state["links"] if l["current"]]
            assert len(current) == 1 and current[0]["inView"], f"the active destination must stay visible at {width}px"
            if width <= 820:
                assert all(l["height"] >= 43.5 for l in state["links"]), f"touch targets at {width}px: {[l['height'] for l in state['links']]}"
            if state["canScroll"]:
                assert page.locator(".rx-nav-wrap[data-nav-overflow-right]").count() == 1, "overflow must be signalled"
                assert page.locator("[data-nav-position]").is_visible() and "more" in page.locator("[data-nav-position]").inner_text()
            else:
                assert width >= 768 and all(l["inView"] for l in state["links"])
            # later destinations are reachable by keyboard and scroll into view when focused
            page.locator("[data-workspace-nav] a").first.focus()
            page.keyboard.press("End")
            focused = page.evaluate("document.activeElement.innerText.replace(/\\s+/g,' ').trim()")
            assert focused.endswith("Trust"), focused
            page.wait_for_function(FOCUS_IN_VIEW, timeout=3000)        # the focused link scrolls into view (the row settles within a frame)
            page.keyboard.press("ArrowLeft")
            assert page.evaluate("document.activeElement.innerText.replace(/\\s+/g,' ').trim()").endswith("Model checks")
            page.wait_for_function(FOCUS_IN_VIEW, timeout=3000)
            page.keyboard.press("ArrowLeft")
            assert page.evaluate("document.activeElement.innerText.replace(/\\s+/g,' ').trim()").endswith("Analysis")
            page.wait_for_function(FOCUS_IN_VIEW, timeout=3000)
            page.keyboard.press("Enter")
            page.wait_for_function("() => location.hash === '#analysis'")
            page.wait_for_function(ACTIVE_IN_VIEW, timeout=3000)
            after = nav_state(page)
            assert [l for l in after["links"] if l["current"]][0]["text"].endswith("Analysis") and [l for l in after["links"] if l["current"]][0]["inView"]
            assert not after["docOverflow"]
            if width in (320, 1440):
                shot(page, f"nav-{width}", full=False)
        # every destination can be activated and keeps the active item visible, at the narrowest width
        page.set_viewport_size({"width": 320, "height": 844})
        for hash_id, label in (("scenarios", "Scenarios"), ("analysis", "Analysis"), ("trust", "Trust"), ("diagnostics", "Model checks")):
            open_section(page, base, record.project_code, hash_id)
            page.wait_for_function(ACTIVE_IN_VIEW, timeout=3000)
            state = nav_state(page)
            active = [l for l in state["links"] if l["current"]]
            assert active and active[0]["text"].endswith(label) and active[0]["inView"], (hash_id, active)
            assert not state["docOverflow"]
        assert errors == [], errors
    finally:
        context.close()


# ── F05 / F06 / U02 ────────────────────────────────────────────────────────────────────────────────────────────

def check_labels_and_typography_have_no_duplicated_units_or_literal_escapes(browser, base, kind):
    context, page, record, errors = vertical_session(browser, base, f"onb-typo-{kind}", kind)
    try:
        run_canonical(context, base, record.project_code)
        for section in SECTIONS:
            open_section(page, base, record.project_code, section)
            if section == "inputs":
                settle_inputs(page)
            body = page.inner_text("body")
            assert not ESCAPE.search(body), f"literal unicode escape in {section}: {ESCAPE.search(body).group(0)}"
            assert not DOUBLE_UNIT.search(body), f"duplicated unit in {section}: {DOUBLE_UNIT.search(body).group(0)}"
            labels = page.evaluate("() => Array.from(document.querySelectorAll('label, [aria-label]')).map(e => (e.getAttribute('aria-label') || e.innerText || '').trim())")
            assert not [l for l in labels if DOUBLE_UNIT.search(l)], [l for l in labels if DOUBLE_UNIT.search(l)]
        open_section(page, base, record.project_code, "results")
        assert "Analysis → Financial intelligence" in page.inner_text("[data-dscr-note]")
        assert errors == [], errors
    finally:
        context.close()


# ── model truth ────────────────────────────────────────────────────────────────────────────────────────────

def check_returns_lender_metrics_and_vertical_scope_are_truthful(browser, base, kind):
    context, page, record, errors = vertical_session(browser, base, f"onb-truth-{kind}", kind)
    try:
        run_canonical(context, base, record.project_code)
        payload = api(context, base, "statements", record.project_code)
        workspace = api(context, base, "workspace", record.project_code)
        open_section(page, base, record.project_code, "results")
        view = page.locator("[data-results-view]")
        # three different returns, each its own labelled figure, with the share-capital vs total-sponsor explanation
        for label in ("Project IRR", "Pure Equity IRR", "Total Sponsor IRR"):
            assert view.locator(f"[data-metric-label='{label}']").count() == 1, label
        explainer = view.locator("[data-returns-explainer]").inner_text()
        assert "share-capital return" in explainer and "all sponsor capital" in explainer and "none is derived from another" in explainer
        values = {l: view.locator(f"[data-metric-label='{l}'] .rx-live-kpi-value").inner_text()
                  for l in ("Project IRR", "Pure Equity IRR", "Total Sponsor IRR")}
        canonical = {m["label"]: m for m in payload["results"]["metrics"]}
        for label, shown in values.items():
            assert shown == (canonical[label]["display"] if canonical[label]["available"] else "Not available"), label
        # lender / valuation metrics: exactly what the committed Run published; the rest explicitly unavailable, never zero
        lender = payload["results"]["lender_metrics"]
        assert {m["key"] for m in lender} >= {"min_llcr", "plcr", "project_npv_keur", "equity_npv_keur", "min_dscr", "avg_dscr"}
        for metric in lender:
            card = view.locator(f"[data-lender-metric='{metric['key']}']")
            assert card.count() == 1
            shown = card.locator(".rx-live-kpi-value").inner_text()
            assert card.get_attribute("data-lender-metric-available") == ("true" if metric["available"] else "false")
            if metric["available"]:
                assert shown == metric["display"]
            else:
                assert shown == "Not available" and shown not in ("0", "0.0", "0.00x", "—"), metric["key"]
                assert metric["reason"] in card.inner_text()
        assert next(m for m in lender if m["key"] == "plcr")["available"] is False
        assert "not a full set of lender-grade metrics" in view.locator("[data-lender-note]").inner_text()
        # vertical scope comes from the canonical capability registry
        vertical = workspace["vertical"]
        banner = view.locator("[data-vertical]").first
        assert banner.get_attribute("data-vertical") == vertical["key"] == kind
        banner_text = banner.inner_text()
        if kind in ("solar", "wind"):
            assert vertical["pilot_tier"] == "PILOT_CANDIDATE" and "PILOT CANDIDATE" in banner_text
            assert "preview" not in banner_text.lower()
        else:
            assert vertical["pilot_tier"] == "PREVIEW" and "PREVIEW VERTICAL" in banner_text
            assert "narrower than Solar and Wind" in banner_text and "not as a validated full-vertical" in banner_text
            assert "validated full-vertical financial model" in banner_text and "not" in banner_text.lower()
        for limitation in vertical["limitations"]:
            assert banner.locator("li", has_text=limitation[:40]).count() == 1
        shot(page, f"results-{kind}")
        for section in ("statements", "analysis"):                     # the caveat follows the user to every results surface
            open_section(page, base, record.project_code, section)
            assert page.locator("[data-vertical]").first.get_attribute("data-pilot-tier") == vertical["pilot_tier"], section
        open_section(page, base, record.project_code, "results")
        page.select_option("select[data-control='unit']", "mEUR")        # lender money metrics follow the unit control
        for metric in lender:
            if metric["available"] and metric["display"] and re.search(r"(kEUR|EUR)$", metric["display"]):
                page.wait_for_function("key => (document.querySelector(`[data-lender-metric='${key}'] .rx-live-kpi-value`)?.innerText || '').endsWith('mEUR')",
                                       arg=metric["key"], timeout=5000)
        # the Project Library carries the same release tier next to the project's type
        page.goto(f"{base}/v2/model-react/")
        page.wait_for_selector("[data-library-view='true']")
        row = page.locator("[data-project-code]", has_text=workspace["project"]["name"]).first
        tier = row.locator("[data-vertical-tier]")
        if kind in ("solar", "wind"):
            assert tier.count() == 0
        else:
            assert tier.get_attribute("data-vertical-tier") == "PREVIEW" and "narrower validation" in tier.inner_text()
        assert errors == [], errors
    finally:
        context.close()


def check_scenario_override_boundary_matches_the_canonical_capability(browser, base):
    context, page, record, errors = vertical_session(browser, base, "onb-boundary", "solar")
    try:
        run_canonical(context, base, record.project_code)
        capability = api(context, base, "scenarios", record.project_code)["override_capability"]["supported"]
        open_section(page, base, record.project_code, "scenarios")
        page.wait_for_selector("[data-override-boundary]")
        boundary = page.locator("[data-override-boundary]")
        assert int(boundary.get_attribute("data-override-supported-count")) == len(capability)
        text = boundary.inner_text()
        for field in capability:
            assert field["label"] in text, field
        assert "inherited from the project" in text and "cannot differ between scenarios" in text
        # the override editor offers exactly the supported fields and no others
        page.locator("#wf-new-scenario").fill("ONB boundary")
        page.get_by_role("button", name="Create scenario").click()
        page.wait_for_selector("[data-scenario-row='ONB boundary']")
        page.get_by_role("button", name="Edit overrides of ONB boundary").click()
        page.wait_for_selector("[data-override-editor]")
        offered = page.locator("[data-override-field]").evaluate_all("els => els.map(e => e.dataset.overrideField)")
        assert sorted(offered) == sorted(f["field_id"] for f in capability)
        assert page.locator("[data-save-scope='scenario-override']").count() == 1
        assert not DOUBLE_UNIT.search(page.inner_text("[data-override-editor]"))
        assert len(api(context, base, "runs", record.project_code)["runs"]) == 1, "creating a scenario and opening its overrides never runs the model"
        assert errors == [], errors
    finally:
        context.close()


# ── themes ──────────────────────────────────────────────────────────────────────────────────────────────────

THEMES = ("FINCO default", "Slate & Teal", "High-Contrast", "Forest Green / White Workbook")

CONTRAST_JS = """(selector) => {
  const lum = (c) => { const v = c.map(x => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); }); return 0.2126*v[0] + 0.7152*v[1] + 0.0722*v[2]; };
  const parse = (s) => { const m = s.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(',').map(Number); return { rgb: p.slice(0,3), a: p.length > 3 ? p[3] : 1 }; };
  const bg = (el) => { for (let n = el; n; n = n.parentElement) { const c = parse(getComputedStyle(n).backgroundColor); if (c && c.a > 0.5) return c.rgb; } return [255,255,255]; };
  const opacity = (el) => { let o = 1; for (let n = el; n; n = n.parentElement) o *= Number(getComputedStyle(n).opacity); return o; };
  const out = [];
  for (const el of document.querySelectorAll(selector)) {
    if (!el.offsetParent && getComputedStyle(el).position !== 'fixed') continue;
    if (!(el.innerText || '').trim()) continue;
    const fg = parse(getComputedStyle(el).color); if (!fg) continue;
    const back = bg(el), o = opacity(el);
    const eff = fg.rgb.map((x, i) => x * o + back[i] * (1 - o));      // text composited over its background at its real opacity
    const a = lum(eff), b = lum(back); const ratio = (Math.max(a,b) + 0.05) / (Math.min(a,b) + 0.05);
    out.push({ text: (el.innerText || '').trim().slice(0, 40), cls: el.className && el.className.baseVal === undefined ? el.className : '', ratio });
  }
  return out;
}"""


def check_every_theme_keeps_the_corrected_surfaces_legible(browser, base):
    context, page, record, errors = vertical_session(browser, base, "onb-theme", "data_center")
    try:
        run_canonical(context, base, record.project_code)
        seen = []
        for theme in THEMES:
            for section in ("inputs", "results", "statements"):
                open_section(page, base, record.project_code, section)
                if section == "inputs":
                    settle_inputs(page)
                page.locator("[data-testid='finco-theme-select']").select_option(label=theme)
                page.wait_for_timeout(150)
                selector = (".rx-save-scope, .rx-state, .rx-run-id, .rx-run-suffix, .rx-vertical, .rx-section-meta, .rx-nav-position, .fm-nav a, "
                            ".fm-top-right > *, .fm-live-label, .fm-theme-select-caption, .fm-brand-name, .fm-brand-caption, "
                            ".fm-workspace-bar a, .fm-crumb-current, .fm-mark")
                sampled = page.evaluate(CONTRAST_JS, selector)
                assert sampled, (theme, section)
                weak = [s for s in sampled if s["ratio"] < 4.5]
                assert not weak, f"{theme} / {section}: contrast below 4.5:1 for {weak[:4]}"
                assert not horizontal_overflow(page), (theme, section)
                if section == "results":
                    assert page.locator("[data-vertical='data_center']").first.is_visible()
            shot(page, "theme-" + re.sub(r"[^a-z]+", "-", theme.lower()).strip("-"), full=False)
            seen.append(theme)
        assert seen == list(THEMES)
        assert errors == [], errors
    finally:
        context.close()
