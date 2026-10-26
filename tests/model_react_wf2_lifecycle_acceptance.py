"""PR #378 Correction B — unsaved-input integrity, navigation protection and Run safety.

Not collected by pytest: executed through the thin wrappers in
``tests/test_model_workspace_consolidation_browser.py`` (the existing mandatory
Chromium role).  No module-level skip lives here.

Every check drives the real server and asserts on the committed Run History: a
staged edit, a Save, a navigation, a scenario action or a rejected request never
creates a Run; only the explicit Run action does, and at most once per activation.
"""
from __future__ import annotations

import re

from tests.model_react_wf1_browser_acceptance import make_session
from tests.model_react_wf2_browser_acceptance import (
    bar, bumped, field_input_id, goto_section, history_count, numeric_bound_field, open_workspace, wait_status,
)

CIT = "tax.assumptions.cit_rate_pct"
CIT_CELL = f"[data-grid-cell='{CIT}']"
SAVE = "#rx-grid-save"
STAY = "Stay and keep editing"
DISCARD = "Discard changes and continue"


def grid_value(context, base, record, field_id=CIT):
    payload = context.request.get(f"{base}/v2/model-react/inputs?project={record.project_code}").json()
    for section in payload["grid"]["sections"]:
        for category in section["categories"]:
            for row in category["rows"]:
                if row["field_id"] == field_id:
                    return row["value"]
    raise AssertionError(field_id)


def materialize(context, base, record):
    """Open the canonical workbook once, as the legacy UI does, so the first Run is not the very first touch of a
    pristine draft (a pre-existing canonical behaviour: that first Run commits but leaves the draft STALE)."""
    assert context.request.get(f"{base}/v2/workbook?project={record.project_code}").ok


def another_value(current):
    number = float(str(current).replace(",", "").rstrip("%") or 0)
    return str(int(number) + 3) if number == int(number) else f"{number + 3:g}"


def unsaved(page):
    return int(bar(page).get_attribute("data-unsaved"))


def wait_unsaved(page, count):
    page.wait_for_function(f"() => document.querySelector(\"[data-workflow-bar='true']\").dataset.unsaved === '{count}'", timeout=10000)


def wait_navigation_complete(page, section, label):
    """A confirmed discard is complete only when the URL, the rendered section AND the shared registry agree:
    the hash changes first, then React commits the section and the unmounted editor's registry cleanup runs."""
    page.wait_for_function(
        """([section, label]) => {
            const bar = document.querySelector("[data-workflow-bar='true']");
            const active = document.querySelector('.fm-nav a.active');
            return location.hash === '#' + section && active && active.textContent.includes(label)
              && !document.querySelector('[data-input-grid]') && bar && bar.dataset.unsaved === '0' && bar.dataset.dirtyKeys === '';
        }""", arg=[section, label], timeout=15000)


def wait_dirty(page):
    page.wait_for_function("() => document.querySelector(\"[data-workflow-bar='true']\").dataset.unsaved !== '0'", timeout=10000)


def run_button(page):
    return page.locator("[data-wf-run='true']")


def watch_posts(page, fragment):
    seen = []
    page.on("request", lambda r: seen.append(r.url) if r.method == "POST" and fragment in r.url else None)
    return seen


def tab(page, label):
    return page.locator(".fm-nav a", has_text=label).first


def dialog(page):
    d = page.get_by_role("dialog")
    d.wait_for()
    return d


def stage_cit(page, value):
    page.wait_for_selector(CIT_CELL)
    cell = page.locator(CIT_CELL)
    cell.fill(value)
    return cell


# ── Test A ───────────────────────────────────────────────────────────────────


def check_grid_draft_counts_blocks_run_and_unchanged_values_are_not_dirty(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "wf2-life-a")
    base = react_enabled
    try:
        posts = watch_posts(page, "/v2/workbook/run")
        open_workspace(page, base, record, "inputs")
        original = grid_value(context, base, record)
        cell = stage_cit(page, another_value(original))
        page.wait_for_function("() => document.querySelector(\"[data-workflow-bar='true']\").dataset.unsaved === '1'")
        assert unsaved(page) == 1
        assert run_button(page).is_disabled()
        assert "unsaved" in page.locator("#wf-run-hint").inner_text()
        page.evaluate("() => document.querySelector(\"[data-wf-run='true']\").click()")   # even a scripted click cannot run
        page.wait_for_timeout(400)
        assert posts == [] and history_count(context, base, record) == 0
        # an edit typed back to the persisted value is not unsaved work
        cell.fill(str(original))
        page.wait_for_function("() => document.querySelector(\"[data-workflow-bar='true']\").dataset.unsaved === '0'")
        assert page.locator("[data-unsaved-indicator='true']").count() == 0
        assert not run_button(page).is_disabled()
        assert grid_value(context, base, record) == original, "staging never altered the canonical value"
        assert not [e for e in errors if "Failed to load resource" not in e], errors
    finally:
        context.close()


# ── Test B ───────────────────────────────────────────────────────────────────


def check_navigation_with_unsaved_edits_asks_and_keeps_the_draft(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "wf2-life-b")
    base = react_enabled
    try:
        open_workspace(page, base, record, "overview")
        tab(page, "Inputs").click()
        page.wait_for_selector(CIT_CELL)
        original = grid_value(context, base, record)
        draft = another_value(original)
        stage_cit(page, draft)

        # workspace tab: stay keeps the draft and the section
        tab(page, "Statements").click()
        d = dialog(page)
        assert "unsaved" in d.inner_text().lower() and "Assumption grid" in d.inner_text()
        d.get_by_role("button", name=STAY).click()
        assert page.locator(CIT_CELL).input_value() == draft and page.url.endswith("#inputs")
        assert unsaved(page) == 1

        # Escape means stay
        tab(page, "Financing").click()
        dialog(page)
        page.keyboard.press("Escape")
        page.get_by_role("dialog").wait_for(state="detached")
        assert page.locator(CIT_CELL).input_value() == draft

        # typed hash change: the URL is restored when the user stays
        page.evaluate("() => { window.location.hash = '#results'; }")
        dialog(page).get_by_role("button", name=STAY).click()
        page.wait_for_function("() => window.location.hash === '#inputs'")
        assert page.locator(CIT_CELL).input_value() == draft

        # Back: the stay above rewrote the typed entry to #inputs, so the first Back lands on the same
        # section (no change); the second reaches the overview, which asks.  Staying keeps draft and section.
        page.go_back()
        page.go_back()
        dialog(page).get_by_role("button", name=STAY).click()
        page.wait_for_function("() => window.location.hash === '#inputs'")
        assert page.locator(CIT_CELL).input_value() == draft

        # legacy workbook link and both Project Library links
        for locator in (page.get_by_role("link", name=re.compile("Legacy workbook")),
                        page.locator("header.rx-header").get_by_role("link", name="Project Library"),
                        page.locator("nav[aria-label='Project breadcrumb']").get_by_role("link", name="Project Library")):
            before = page.url
            locator.first.click()
            dialog(page).get_by_role("button", name=STAY).click()
            assert page.url == before and page.locator(CIT_CELL).input_value() == draft

        # nothing was saved or run by any of this
        assert grid_value(context, base, record) == original and history_count(context, base, record) == 0

        # explicit discard: navigate, and the draft is really gone when returning
        tab(page, "Statements").click()
        dialog(page).get_by_role("button", name=DISCARD).click()
        wait_navigation_complete(page, "statements", "Statements")
        assert unsaved(page) == 0
        tab(page, "Inputs").click()
        page.wait_for_selector(CIT_CELL)
        assert page.locator(CIT_CELL).input_value() == original
        assert grid_value(context, base, record) == original

        # discarding to leave through a link really leaves
        stage_cit(page, draft)
        page.locator("header.rx-header").get_by_role("link", name="Project Library").click()
        dialog(page).get_by_role("button", name=DISCARD).click()
        page.wait_for_url(re.compile(r"/v2/model-react/?$"))
        assert history_count(context, base, record) == 0
    finally:
        context.close()


# ── Test C ───────────────────────────────────────────────────────────────────


def check_verified_save_clears_dirty_updates_identity_and_enables_an_explicit_run(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "wf2-life-c")
    base = react_enabled
    try:
        materialize(context, base, record)
        open_workspace(page, base, record, "overview")
        run_button(page).click()
        page.wait_for_selector("[data-workflow-bar='true'][data-bar-freshness='CURRENT']", timeout=120000)
        assert history_count(context, base, record) == 1
        tab(page, "Inputs").click()
        page.wait_for_selector(CIT_CELL)
        before_hash = context.request.get(f"{base}/v2/model-react/workspace?project={record.project_code}").json()["workbook"]["composite_hash"]
        original = grid_value(context, base, record)
        value = another_value(original)
        stage_cit(page, value)
        assert unsaved(page) == 1 and run_button(page).is_disabled()
        page.locator(SAVE).click()
        page.wait_for_selector("[data-save-state='saved']")
        page.wait_for_function("() => document.querySelector(\"[data-workflow-bar='true']\").dataset.unsaved === '0'")
        page.wait_for_selector("[data-workflow-bar='true'][data-bar-freshness='STALE']")
        assert float(grid_value(context, base, record)) == float(value)
        after_hash = context.request.get(f"{base}/v2/model-react/workspace?project={record.project_code}").json()["workbook"]["composite_hash"]
        assert after_hash != before_hash, "the committed change moved the composite CAS identity"
        assert history_count(context, base, record) == 1, "a Save never runs the model"
        page.wait_for_function("() => !document.querySelector(\"[data-wf-run='true']\").disabled")
        run_button(page).click()
        page.wait_for_selector("[data-workflow-bar='true'][data-bar-freshness='CURRENT']", timeout=120000)
        assert history_count(context, base, record) == 2
    finally:
        context.close()


# ── Test D ───────────────────────────────────────────────────────────────────


def check_failed_stale_and_unknown_saves_keep_drafts_and_locks_without_duplicates(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "wf2-life-d")
    base = react_enabled
    try:
        posts = watch_posts(page, "/v2/workbook/grid/save")
        open_workspace(page, base, record, "inputs")
        page.wait_for_selector(CIT_CELL)
        original = grid_value(context, base, record)

        # validation rejection: draft and count stay, the editor is not locked, Run stays blocked
        stage_cit(page, "abc")
        page.locator(SAVE).click()
        page.wait_for_selector("[data-save-state='rejected']")
        assert page.locator(CIT_CELL).input_value() == "abc" and unsaved(page) == 1
        assert run_button(page).is_disabled()
        assert grid_value(context, base, record) == original

        # stale CAS: another writer commits first; the Save answers a conflict, the draft stays
        draft = another_value(original)
        page.locator(CIT_CELL).fill(draft)
        row = numeric_bound_field(context, base, record, "project_setup")
        tokens = context.request.get(f"{base}/v2/model-react/fields/project_setup?project={record.project_code}").json()["save"]
        committed = context.request.post(f"{base}/v2/workbook/update", form={
            "project": record.project_code, "field_id": row["field_id"], "value": bumped(row), "sheet_id": "project_setup",
            "workbook_version": tokens["workbook_version"], "content_hash": tokens["content_hash"], "csrf_token": tokens["csrf_token"]})
        assert committed.ok
        posts.clear()
        page.locator(SAVE).click()
        page.wait_for_selector("[data-save-state='conflict']")
        assert len(posts) == 1 and page.locator(CIT_CELL).input_value() == draft and unsaved(page) == 1
        assert run_button(page).is_disabled(), "an unresolved conflict blocks Run"
        assert grid_value(context, base, record) == original, "the stale Save overwrote nothing"
        assert history_count(context, base, record) == 0
    finally:
        context.close()

    context, page, record, errors = make_session(browser, react_enabled, "wf2-life-d2")
    try:
        posts = watch_posts(page, "/v2/workbook/grid/save")
        open_workspace(page, base, record, "inputs")
        page.wait_for_selector(CIT_CELL)
        original = grid_value(context, base, record)
        draft = another_value(original)
        stage_cit(page, draft)
        context.route("**/v2/workbook/grid/save", lambda route: route.abort())
        page.locator(SAVE).click()
        page.wait_for_selector("[data-save-state='unknown']")
        page.wait_for_timeout(1500)
        assert len(posts) == 1, f"no automatic retry: {posts}"
        assert page.locator(CIT_CELL).input_value() == draft and unsaved(page) == 1
        assert page.locator(CIT_CELL).get_attribute("readonly") is not None, "the grid stays locked"
        assert page.locator(SAVE).is_disabled() and run_button(page).is_disabled()
        context.unroute("**/v2/workbook/grid/save")
        # Reload with an unknown outcome and a draft still asks first
        page.locator("[data-wf-reload='true']").click()
        dialog(page).get_by_role("button", name=STAY).click()
        assert page.locator(CIT_CELL).input_value() == draft
        assert history_count(context, base, record) == 0
    finally:
        context.close()


# ── Test E ───────────────────────────────────────────────────────────────────


def _expect_guard_and_clear(page, section_tab, clear):
    """Navigation away is refused while dirty (stay keeps it); clearing the draft removes the guard."""
    wait_dirty(page)
    assert run_button(page).is_disabled()
    tab(page, section_tab).click()
    dialog(page).get_by_role("button", name=STAY).click()
    assert unsaved(page) >= 1
    clear()
    page.wait_for_function("() => document.querySelector(\"[data-workflow-bar='true']\").dataset.unsaved === '0'")
    assert not run_button(page).is_disabled()


def check_every_editor_reports_unsaved_work_and_guards_navigation(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "wf2-life-e")
    base = react_enabled
    try:
        open_workspace(page, base, record, "inputs")
        page.wait_for_selector("[data-sheet-editor='project_setup']")

        # Project setup
        row = numeric_bound_field(context, base, record, "project_setup")
        page.locator(f"#{field_input_id('project_setup', row['field_id'])}").fill(bumped(row))
        _expect_guard_and_clear(page, "Financing", lambda: page.get_by_role("button", name=f"Cancel edit of {row['label']}").click())

        # Tax assumptions live in the canonical grid
        original = grid_value(context, base, record)
        stage_cit(page, another_value(original))
        _expect_guard_and_clear(page, "Financing", lambda: page.locator("[data-discard='true']").click())

        # CAPEX batch edit, then the sheet switch asks too
        costs = page.locator("[data-cost-line-manager='capex']")
        costs.scroll_into_view_if_needed()
        amount = page.locator("input[aria-label^='Amount for ']").first
        amount.fill("12345")
        wait_unsaved(page, 1)
        page.locator("button[aria-pressed]", has_text="OPEX").first.click()
        dialog(page).get_by_role("button", name=STAY).click()
        assert amount.input_value() == "12345"
        page.get_by_role("button", name="Discard staged edits").first.click()
        wait_unsaved(page, 0)

        # OPEX add form draft
        page.locator("button[aria-pressed]", has_text="OPEX").first.click()
        opex = page.locator("[data-cost-line-manager='opex']")
        opex.wait_for()
        opex.get_by_label("Line label").fill("unsaved opex line")
        _expect_guard_and_clear(page, "Financing", lambda: opex.get_by_role("button", name="Clear").click())

        # PPA: defining a contract is unsaved work
        ppa = page.locator("[data-ppa-editor]")
        ppa.scroll_into_view_if_needed()
        ppa.get_by_role("button", name="Define a PPA contract").click()
        wait_dirty(page)
        assert run_button(page).is_disabled()
        tab(page, "Financing").click()
        dialog(page).get_by_role("button", name=STAY).click()
        ppa.get_by_role("button", name="Cancel edits").click()
        page.wait_for_function("() => document.querySelector(\"[data-workflow-bar='true']\").dataset.unsaved === '0'")

        # Financing
        goto_section(page, "financing")
        page.wait_for_selector("[data-sheet-editor='debt']")
        debt = numeric_bound_field(context, base, record, "debt")
        page.locator(f"#{field_input_id('debt', debt['field_id'])}").fill(bumped(debt))
        _expect_guard_and_clear(page, "Inputs", lambda: page.get_by_role("button", name=f"Cancel edit of {debt['label']}").click())

        # Scenario override drafts, and switching the override editor to another scenario
        goto_section(page, "scenarios")
        page.wait_for_selector("[data-scenario-workspace='true']")
        for name in ("Case A", "Case B"):
            page.get_by_label("New scenario name").fill(name)
            page.get_by_role("button", name="Create scenario").click()
            wait_status(page, "ok", "created", "[data-scenario-workspace='true']")
            page.wait_for_function(f"""() => document.querySelector("[data-active-scenario-banner='true']").innerText.includes('{name}')""")
        page.get_by_role("button", name="Edit overrides of Case A").click()
        override = page.locator("[data-override-editor='Case A']")
        override.wait_for()
        override.get_by_label("Tariff scenario value").fill("66")
        _expect_guard_and_clear(page, "Inputs", lambda: override.get_by_role("button", name="Cancel").first.click())
        override.get_by_label("Tariff scenario value").fill("66")
        page.get_by_role("button", name="Edit overrides of Case B").click()          # would unmount Case A's draft
        dialog(page).get_by_role("button", name=STAY).click()
        assert page.locator("[data-override-editor='Case A']").count() == 1
        assert page.locator("[data-override-editor='Case A']").get_by_label("Tariff scenario value").input_value() == "66"
        assert history_count(context, base, record) == 0
    finally:
        context.close()


# ── Test F ───────────────────────────────────────────────────────────────────


def check_rapid_repeated_activation_starts_at_most_one_run(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "wf2-life-f")
    base = react_enabled
    try:
        materialize(context, base, record)
        posts = watch_posts(page, "/v2/workbook/run")
        open_workspace(page, base, record, "overview")
        page.wait_for_function("() => !document.querySelector(\"[data-wf-run='true']\").disabled")
        # three activations inside one task: before React can re-render the disabled state
        page.evaluate("""() => { const b = document.querySelector("[data-wf-run='true']"); b.click(); b.click(); b.click(); }""")
        page.wait_for_selector("[data-workflow-bar='true'][data-bar-freshness='CURRENT']", timeout=120000)
        assert len(posts) == 1, posts
        assert history_count(context, base, record) == 1
    finally:
        context.close()

    context, page, record, errors = make_session(browser, react_enabled, "wf2-life-f2")
    try:
        materialize(context, base, record)
        posts = watch_posts(page, "/v2/workbook/run")
        open_workspace(page, base, record, "overview")
        button = run_button(page)
        page.wait_for_function("() => !document.querySelector(\"[data-wf-run='true']\").disabled")
        button.focus()
        page.keyboard.press("Enter")
        page.keyboard.press("Enter")
        page.keyboard.press("Space")
        button.dblclick(force=True)
        page.wait_for_selector("[data-workflow-bar='true'][data-bar-freshness='CURRENT']", timeout=120000)
        assert len(posts) == 1, posts
        assert history_count(context, base, record) == 1
    finally:
        context.close()


def check_run_is_blocked_while_a_save_is_in_flight(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "wf2-life-f3")
    base = react_enabled
    try:
        runs = watch_posts(page, "/v2/workbook/run")
        open_workspace(page, base, record, "inputs")
        page.wait_for_selector("[data-sheet-editor='project_setup']")
        row = numeric_bound_field(context, base, record, "project_setup")
        page.locator(f"#{field_input_id('project_setup', row['field_id'])}").fill(bumped(row))
        gate = {"release": None}

        def hold(route):
            gate["release"] = route          # keep the Save in flight
        context.route("**/v2/workbook/update", hold)
        page.get_by_role("button", name=f"Save {row['label']}").click()
        page.wait_for_function("() => document.querySelector(\"[data-wf-run='true']\").disabled")
        page.evaluate("() => document.querySelector(\"[data-wf-run='true']\").click()")
        page.wait_for_timeout(300)
        assert runs == [] and history_count(context, base, record) == 0
        gate["release"].continue_()
        context.unroute("**/v2/workbook/update")
        wait_status(page, "ok", "verified", "[data-sheet-editor='project_setup']")
        page.wait_for_function("() => !document.querySelector(\"[data-wf-run='true']\").disabled")
        assert runs == []
    finally:
        context.close()


# ── Test G ───────────────────────────────────────────────────────────────────


def check_drafts_never_transfer_to_another_scenario_or_project(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "wf2-life-g")
    base = react_enabled
    try:
        open_workspace(page, base, record, "inputs")
        page.wait_for_selector(CIT_CELL)
        original = grid_value(context, base, record)
        draft = another_value(original)
        stage_cit(page, draft)
        # a draft must be kept or discarded before the scope can change; the Scenarios tab asks
        tab(page, "Scenarios").click()
        dialog(page).get_by_role("button", name=DISCARD).click()
        page.wait_for_selector("[data-scenario-workspace='true']")
        page.get_by_label("New scenario name").fill("Isolation")
        page.get_by_role("button", name="Create scenario").click()
        wait_status(page, "ok", "created", "[data-scenario-workspace='true']")
        page.wait_for_function("""() => document.querySelector("[data-active-scenario-banner='true']").innerText.includes('Isolation')""")
        tab(page, "Inputs").click()
        page.wait_for_selector(CIT_CELL)
        wait_unsaved(page, 0)
        assert unsaved(page) == 0
        assert page.locator(CIT_CELL).input_value() == original, "the discarded draft was not applied to the new scenario"
        assert grid_value(context, base, record) == original

        # a draft staged under this scenario cannot follow a scenario switch either
        stage_cit(page, draft)
        tab(page, "Scenarios").click()
        dialog(page).get_by_role("button", name=DISCARD).click()
        page.wait_for_selector("[data-scenario-workspace='true']")
        page.get_by_role("button", name=re.compile("^Select scenario ")).first.click()
        page.wait_for_function("""() => !document.querySelector("[data-active-scenario-banner='true']").innerText.includes('Isolation')""")
        tab(page, "Inputs").click()
        page.wait_for_selector(CIT_CELL)
        wait_unsaved(page, 0)
        assert unsaved(page) == 0 and page.locator(CIT_CELL).input_value() == original
        assert history_count(context, base, record) == 0
    finally:
        context.close()

    # another project in a fresh page starts clean: drafts are per page and per project
    context, page, other, errors = make_session(browser, react_enabled, "wf2-life-g2")
    try:
        open_workspace(page, base, other, "inputs")
        page.wait_for_selector(CIT_CELL)
        assert unsaved(page) == 0
    finally:
        context.close()


def check_protected_reference_grid_cannot_stage_or_save(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "wf2-life-p")
    base = react_enabled
    try:
        from app.persistence.db import get_connection
        with get_connection() as connection:
            connection.execute("UPDATE projects SET project_role='reference', is_protected=1, project_origin='factory_template' "
                               "WHERE project_id=?", (record.project_id,))
            connection.commit()
        posts = watch_posts(page, "/v2/workbook/grid/save")
        open_workspace(page, base, record, "inputs")
        page.wait_for_selector("[data-input-grid='canonical']")
        assert page.locator("[data-input-grid='canonical'] input.rx-grid-input").count() == 0, "no editable cell on a reference"
        assert page.locator(SAVE).is_disabled()
        assert unsaved(page) == 0 and run_button(page).is_disabled()
        assert posts == [] and history_count(context, base, record) == 0
    finally:
        context.close()


# ── pending / unknown mutations cannot be walked away from ───────────────────


def pending_keys(page):
    return [k for k in (bar(page).get_attribute("data-pending-keys") or "").split(",") if k]


def seed_capex_line(context, base, record, label):
    costs = context.request.get(f"{base}/v2/model-react/costlines?sheet=capex&project={record.project_code}").json()
    group = costs["line_management"]["eligible_groups"][0]["code"]
    added = context.request.post(f"{base}/v2/capex/line/add", form={
        "project": record.project_code, "parent_category_code": group, "label": label, "amount_keur": "10", "notes": "",
        "workbook_version": costs["save"]["workbook_version"], "content_hash": costs["save"]["content_hash"]})
    assert added.ok


def open_capex_deactivate_confirm(page, label):
    costs = page.locator("[data-cost-line-manager='capex']")
    costs.scroll_into_view_if_needed()
    costs.get_by_role("button", name=f"Deactivate {label}").click()
    page.get_by_role("dialog").get_by_role("button", name="Deactivate line").click()


def check_pending_mutations_cannot_escape_their_reconciliation_contract(browser, react_enabled):
    base = react_enabled

    # (1) CAPEX deactivate in flight, zero drafts: leaving asks; staying keeps the editor and its result
    context, page, record, errors = make_session(browser, react_enabled, "wf2-life-h1")
    try:
        seed_capex_line(context, base, record, "pending line")
        open_workspace(page, base, record, "inputs")
        page.wait_for_selector("[data-cost-line-manager='capex']")
        held = {}
        context.route("**/v2/capex/line/deactivate", lambda route: held.setdefault("route", route))
        open_capex_deactivate_confirm(page, "pending line")
        page.wait_for_function("() => document.querySelector(\"[data-workflow-bar='true']\").dataset.pendingKeys.includes('cost-add-capex')")
        assert unsaved(page) == 0 and run_button(page).is_disabled(), "no draft, but a mutation is in flight"
        tab(page, "Financing").click()
        d = dialog(page)
        assert "unresolved" in d.inner_text().lower() or "in progress" in d.inner_text().lower()
        d.get_by_role("button", name=STAY).click()
        assert page.url.endswith("#inputs")
        held["route"].continue_()
        context.unroute("**/v2/capex/line/deactivate")
        page.wait_for_selector("[data-cost-line-manager='capex'] tr[data-line-state='inactive']", timeout=20000)
        page.wait_for_function("() => document.querySelector(\"[data-workflow-bar='true']\").dataset.pendingKeys === ''")
        assert history_count(context, base, record) == 0
    finally:
        context.close()

    # (2) UNKNOWN deactivate: leaving needs an explicit choice and the lock survives the editor unmounting
    context, page, record, errors = make_session(browser, react_enabled, "wf2-life-h2")
    try:
        seed_capex_line(context, base, record, "unknown line")
        open_workspace(page, base, record, "inputs")
        page.wait_for_selector("[data-cost-line-manager='capex']")
        posts = watch_posts(page, "/v2/capex/line/deactivate")
        context.route("**/v2/capex/line/deactivate", lambda route: route.abort())
        open_capex_deactivate_confirm(page, "unknown line")
        wait_status(page, "conflict", None, "[data-cost-line-manager='capex']")
        context.unroute("**/v2/capex/line/deactivate")
        assert unsaved(page) == 0 and "cost-add-capex" in pending_keys(page)
        tab(page, "Financing").click()
        dialog(page).get_by_role("button", name="Leave anyway").click()
        wait_navigation_complete(page, "financing", "Financing")
        assert "cost-add-capex" in pending_keys(page) and run_button(page).is_disabled(), "the unresolved outcome still blocks Run"
        tab(page, "Inputs").click()
        costs = page.locator("[data-cost-line-manager='capex']")
        costs.wait_for()
        assert costs.locator("[data-cost-add='capex']").is_disabled(), "a remounted editor starts locked"
        assert costs.get_by_role("button", name="Deactivate unknown line").is_disabled()
        page.wait_for_timeout(1000)
        assert len(posts) == 1, f"no duplicate mutation after navigating away and back: {posts}"
        # reload is the reconciliation: no draft, so no prompt, and the editor is usable again
        page.locator("[data-wf-reload='true']").click()
        page.wait_for_selector("[data-workflow-bar='true']")
        assert pending_keys(page) == []
        assert history_count(context, base, record) == 0
    finally:
        context.close()

    # (3) scenario action in flight
    context, page, record, errors = make_session(browser, react_enabled, "wf2-life-h3")
    try:
        open_workspace(page, base, record, "scenarios")
        page.wait_for_selector("[data-scenario-workspace='true']")
        held = {}
        context.route("**/v2/workbook/scenarios/create", lambda route: held.setdefault("route", route))
        page.get_by_label("New scenario name").fill("In flight")
        page.get_by_role("button", name="Create scenario").click()
        page.wait_for_function("() => document.querySelector(\"[data-workflow-bar='true']\").dataset.pendingKeys.includes('scenario-workspace')")
        assert run_button(page).is_disabled()
        tab(page, "Inputs").click()
        dialog(page).get_by_role("button", name=STAY).click()
        assert page.url.endswith("#scenarios")
        held["route"].continue_()
        context.unroute("**/v2/workbook/scenarios/create")
        wait_status(page, "ok", "created", "[data-scenario-workspace='true']")
        assert history_count(context, base, record) == 0
    finally:
        context.close()

    # (4) Run in flight and (5) UNKNOWN Run: leaving the page asks; staying never sends a second request
    for uid, mode in (("wf2-life-h4", "inflight"), ("wf2-life-h5", "unknown")):
        context, page, record, errors = make_session(browser, react_enabled, uid)
        try:
            materialize(context, base, record)
            posts = watch_posts(page, "/v2/workbook/run")
            open_workspace(page, base, record, "overview")
            page.wait_for_function("() => !document.querySelector(\"[data-wf-run='true']\").disabled")
            held = {}
            if mode == "inflight":
                context.route("**/v2/workbook/run", lambda route: held.setdefault("route", route))
            else:
                context.route("**/v2/workbook/run", lambda route: route.abort())
            run_button(page).click()
            if mode == "unknown":
                wait_status(page, "conflict", None, "[data-workflow-bar='true']")
            else:
                page.wait_for_function("() => document.querySelector(\"[data-workflow-bar='true']\").dataset.pendingKeys.includes('run')")
            library = page.locator("header.rx-header").get_by_role("link", name="Project Library")
            library.click()
            dialog(page).get_by_role("button", name=STAY).click()
            assert "/v2/model-react/" in page.url and page.url.split("?")[0].endswith(record.project_code)
            assert run_button(page).is_disabled()
            page.wait_for_timeout(800)
            assert len(posts) == 1, posts
            if mode == "inflight":
                held["route"].continue_()
                context.unroute("**/v2/workbook/run")
                page.wait_for_selector("[data-workflow-bar='true'][data-bar-freshness='CURRENT']", timeout=120000)
                assert len(posts) == 1 and history_count(context, base, record) == 1
            else:
                context.unroute("**/v2/workbook/run")
                assert len(posts) == 1
        finally:
            context.close()

    # (6) UNKNOWN grid Save, discard the draft and leave: the grid is locked when it returns
    context, page, record, errors = make_session(browser, react_enabled, "wf2-life-h6")
    try:
        posts = watch_posts(page, "/v2/workbook/grid/save")
        open_workspace(page, base, record, "inputs")
        page.wait_for_selector(CIT_CELL)
        stage_cit(page, "9")
        context.route("**/v2/workbook/grid/save", lambda route: route.abort())
        page.locator(SAVE).click()
        page.wait_for_selector("[data-save-state='unknown']")
        context.unroute("**/v2/workbook/grid/save")
        tab(page, "Statements").click()
        dialog(page).get_by_role("button", name=DISCARD).click()
        wait_navigation_complete(page, "statements", "Statements")
        assert "input-grid" in pending_keys(page) and run_button(page).is_disabled()
        tab(page, "Inputs").click()
        page.wait_for_selector(CIT_CELL)
        assert page.locator(CIT_CELL).get_attribute("readonly") is not None and page.locator(SAVE).is_disabled()
        assert len(posts) == 1, posts
        assert history_count(context, base, record) == 0
    finally:
        context.close()
