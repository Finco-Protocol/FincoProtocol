"""WF-04 Debt Metrics in a REAL Chromium against a live server (synthetic working copies only).

Weak coverage is the seeded Wind working copy at 85 % gearing under GEARING_CAP (the engine completes; raw minimum DSCR 0.9925…).  Every
number asserted is read from the committed Run's own API payload; no threshold is hard-coded as a canonical contractual value.
Set ``WF04_SCREENSHOT_DIR`` to keep screenshots (private/local evidence only — never committed).

Not collected by pytest on its own: the bodies are imported by ``tests/test_model_workspace_consolidation_browser.py`` - the existing
mandatory Chromium role - so no collection-time skip lives in this module (CI V3 collection governance), exactly like the WS1/RC-M bodies.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from tests.model_react_rcm_support import rcm_react_flag  # noqa: F401
from tests.test_model_financing_f2 import run
from tests.test_wf04_credit_debt_metrics import COV, EOD, update, weak_wind
from tests.test_workflow_c_browser_v1 import live_server, browser  # noqa: F401

USER = "decision-user"  # the shared Run helpers (tests.test_model_financing_f2) are bound to this user id
SHOTS = os.environ.get("WF04_SCREENSHOT_DIR", "")
VIEWPORTS = ((1440, 1000), (1366, 900), (768, 1000), (390, 844))


@pytest.fixture(scope="module")
def world(live_server):
    """Committed Runs for every UI state, created through the real writer and Run routes of the SAME app."""
    from fastapi.testclient import TestClient
    import main_web
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.workbook import dscr_contract_terms as terms_module

    with TestClient(main_web.app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=USER, username="admin"))
        counter = {"n": 0}

        def create(kind="wind"):
            counter["n"] += 1
            return create_reference_seeded_project(user_id=USER, requested_name=f"DM {kind} {counter['n']}",
                                                   template_source=f"generic_{kind}_reference", capacity_mw=16)
        env = SimpleNamespace(client=client, create=create)
        out = SimpleNamespace(env=env)

        out.weak = weak_wind(env)                                   # EoD triggered, covenant breached, DSCR < 1.00x
        update(env, out.weak, EOD, "1.05")
        update(env, out.weak, COV, "1.20")
        run(env, out.weak)

        out.bare = weak_wind(env)                                   # no term configured
        run(env, out.bare)

        out.healthy = env.create("wind")                            # default sizing: coverage adequate
        update(env, out.healthy, EOD, "1.00")
        update(env, out.healthy, COV, "1.10")
        run(env, out.healthy)

        out.legacy = weak_wind(env)                                 # a Run committed before the terms were recorded
        update(env, out.legacy, EOD, "1.05")
        original = terms_module.IDENTITY_KEY
        terms_module.IDENTITY_KEY = "legacy_terms_not_recorded_by_this_run"
        try:
            run(env, out.legacy)
        finally:
            terms_module.IDENTITY_KEY = original

        out.history = weak_wind(env)                                # two Runs with different terms, then a stale Last Run
        update(env, out.history, EOD, "1.05")
        run(env, out.history)
        update(env, out.history, EOD, "0.50")
        run(env, out.history)
        update(env, out.history, EOD, "0.40")                       # edited after the Last Run: STALE
        yield out


def context_for(browser, live_server, viewport=(1440, 1000), scheme="light"):
    from app.auth import COOKIE_NAME, create_session_token
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, color_scheme=scheme)
    context.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=USER, username="admin"), "url": live_server}])
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and not str((m.location or {}).get("url", "")).endswith("/favicon.ico") else None)
    return context, page, errors


def open_metrics(page, live_server, record, run_id=None):
    query = "financing=debt-metrics" + (f"&dm_run={run_id}" if run_id else "")
    page.goto(f"{live_server}/v2/model-react/{record.project_code}?{query}#financing")
    page.wait_for_selector("[data-debt-metrics='true']", timeout=30000)


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, f"wf04-{name}.png"), full_page=True)


def row(page, row_id):
    return page.locator(f"[data-dm-row='{row_id}']")


def history_rows(record):
    from app.persistence.run_history_repository import get_run_history
    return list(get_run_history(USER, record.project_id))


# ── states ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_weak_coverage_eod_triggered_covenant_breached_and_run_completed(world, live_server, browser, rcm_react_flag):
    context, page, errors = context_for(browser, live_server)
    try:
        open_metrics(page, live_server, world.weak)
        chips = page.locator("[data-dm-chips='true']").inner_text().lower()
        assert "completed · current last run" in chips and "integrity" in chips and "coverage: deficiency" in chips
        assert row(page, "EOD_FLOOR").get_attribute("data-dm-status") == "TRIGGERED"
        assert "EVENT_OF_DEFAULT: TRIGGERED" in row(page, "EOD_FLOOR").inner_text()
        assert row(page, "CONTRACTUAL_DSCR").get_attribute("data-dm-status") == "BREACHED"
        assert row(page, "COVERAGE_1X").get_attribute("data-dm-status") == "DEFICIENCY"
        assert row(page, "SIZING_TARGET").get_attribute("data-dm-status") in ("BELOW_TARGET", "AT_OR_ABOVE_TARGET")
        assert "Sizing assumption · not a covenant" in row(page, "SIZING_TARGET").inner_text().replace("SIZING ASSUMPTION · NOT A COVENANT", "Sizing assumption · not a covenant")
        assert page.locator("[data-dm-row='EOD_FLOOR'] [data-dm-cell='headroom']").inner_text().strip().startswith("-")      # negative headroom
        assert page.locator("[data-dm-term='eod']").inner_text() == "1.05x" and page.locator("[data-dm-term='contractual']").inner_text() == "1.2x"
        assert "run result" in page.locator("[data-dm-terms='true']").inner_text().lower()
        body = page.evaluate("""() => { const root = document.querySelector("[data-debt-metrics='true']").cloneNode(true);
            root.querySelectorAll("[data-dm-integrity-fail], [data-dm-chip='integrity']").forEach((n) => n.remove());   // existing Run Integrity check text is not this view's wording
            return root.innerText; }""").lower()
        assert not any(w in body for w in ("unprofitable", "bankable", "feasible", "defaulted", "acceleration"))
        assert body.count("payment default") == body.count("not by itself a payment default")               # only the required negation, never a claim
        assert len(history_rows(world.weak)) == 1                                                # opening the view committed nothing
        gaps = page.locator("[data-dm-gaps='true']")                                             # reserve draw / unpaid service: UNAVAILABLE + exact missing evidence
        assert "RESERVE_DRAW" in gaps.inner_html() and "UNPAID_DEBT_SERVICE" in gaps.inner_html()
        assert gaps.locator("[data-dm-gap='RESERVE_DRAW']").inner_text().count("UNAVAILABLE") == 1 and "DSRA draw per period" in gaps.inner_text()
        assert "Debt service actually paid per period" in gaps.locator("[data-dm-gap='UNPAID_DEBT_SERVICE']").inner_text()
        assert errors == []
        shot(page, "weak-1440")
    finally:
        context.close()


def test_no_terms_configured_is_not_configured_never_a_pass(world, live_server, browser, rcm_react_flag):
    context, page, errors = context_for(browser, live_server)
    try:
        open_metrics(page, live_server, world.bare)
        for rid in ("EOD_FLOOR", "CONTRACTUAL_DSCR"):
            assert row(page, rid).get_attribute("data-dm-status") == "NOT_CONFIGURED" and "NOT CONFIGURED" in row(page, rid).inner_text()
            assert row(page, rid).locator("[data-dm-cell='required']").inner_text().strip() != ""
        assert page.locator("[data-dm-term='eod']").inner_text() == "Not configured"
        assert row(page, "COVERAGE_1X").get_attribute("data-dm-status") == "DEFICIENCY"          # coverage needs no configured term
        assert errors == []
    finally:
        context.close()


def test_a_run_without_a_recorded_contract_is_unavailable_not_judged_by_todays_inputs(world, live_server, browser, rcm_react_flag):
    context, page, errors = context_for(browser, live_server)
    try:
        open_metrics(page, live_server, world.legacy)
        for rid in ("EOD_FLOOR", "CONTRACTUAL_DSCR"):
            assert row(page, rid).get_attribute("data-dm-status") == "UNAVAILABLE"
        assert "NOT_RECORDED" in page.locator("[data-dm-terms-unrecorded='true']").inner_text()
        assert page.locator("[data-dm-term='eod']").inner_text() == "Not recorded"           # the Working Copy now holds 1.05 — not used
        assert errors == []
    finally:
        context.close()


def test_healthy_run_shows_honest_neutral_ok_states_without_inventing_a_pass(world, live_server, browser, rcm_react_flag):
    context, page, errors = context_for(browser, live_server)
    try:
        open_metrics(page, live_server, world.healthy)
        assert row(page, "EOD_FLOOR").get_attribute("data-dm-status") == "NOT_TRIGGERED_UNDER_THIS_FLOOR"
        assert row(page, "CONTRACTUAL_DSCR").get_attribute("data-dm-status") == "COMPLIANT"
        assert row(page, "COVERAGE_1X").get_attribute("data-dm-status") == "NO_DEFICIENCY_FOUND"
        assert "NOT TRIGGERED UNDER THIS FLOOR" in row(page, "EOD_FLOOR").inner_text()
        assert "No default" not in page.locator("[data-debt-metrics='true']").inner_text()      # never a universal "no default" verdict
        assert row(page, "LLCR").get_attribute("data-dm-status") == "UNAVAILABLE"                # no LLCR persisted: not 0, not a pass
        assert errors == []
        shot(page, "healthy-1440")
    finally:
        context.close()


# ── chart, schedule, keyboard ───────────────────────────────────────────────────────────────────────────────────────────────────────
def test_chart_plots_only_persisted_periods_has_a_data_table_and_is_keyboard_operable(world, live_server, browser, rcm_react_flag):
    context, page, errors = context_for(browser, live_server)
    try:
        open_metrics(page, live_server, world.weak)
        payload = context.request.get(f"{live_server}/v2/model-react/analysis/credit-decision?project={world.weak.project_code}").json()
        periods = payload["data"]["runs"][0]["debt_metrics"]["periods"]
        serviced = [p for p in periods if p["has_debt_service"]]
        assert 0 < len(serviced) < len(periods)                                                 # post-maturity periods exist and carry no service
        assert page.locator("svg.dm-chart circle.dm-pt").count() == len(serviced)               # one mark per serviced period, none for the rest
        assert page.locator("svg.dm-chart path[data-dm-series='dscr']").get_attribute("d")
        assert page.locator("[data-dm-breach]").count() >= 1                                    # breached periods are highlighted
        assert "no per-period LLCR series" in page.locator("[data-dm-llcr-note='true']").inner_text()
        page.locator("[data-dm-chart-focus='true']").focus()
        before = page.locator("[data-dm-readout='true']").inner_text()
        page.keyboard.press("ArrowRight")
        after = page.locator("[data-dm-readout='true']").inner_text()
        assert before != after and "DSCR" in after
        page.locator("[data-dm-chart-data='true'] summary").click()
        assert page.locator("[data-dm-chart-data='true'] tbody tr").count() == len(periods)
        assert errors == []
    finally:
        context.close()


def test_schedule_scrolls_horizontally_by_keyboard_and_period_links_jump_to_the_column(world, live_server, browser, rcm_react_flag):
    context, page, errors = context_for(browser, live_server)
    try:
        open_metrics(page, live_server, world.weak)
        scroller = page.locator("[data-dm-sched-scroll='true']")
        assert scroller.evaluate("el => el.scrollWidth > el.clientWidth + 50")                  # many periods: scrolls inside its own box
        assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")   # never the page
        scroller.focus()
        for _ in range(6):
            page.keyboard.press("ArrowRight")                                                   # a focused scroll region scrolls with the arrow keys
        assert scroller.evaluate("el => el.scrollLeft") > 0
        scroller.evaluate("el => { el.scrollLeft = 0; }")
        row(page, "EOD_FLOOR").locator("summary").click()
        link = row(page, "EOD_FLOOR").locator(".dm-periods button").first
        index = link.inner_text().split("·")[0].strip()[1:]
        link.click()
        assert page.evaluate("() => document.activeElement && document.activeElement.getAttribute('data-dm-col')") == index.strip()
        lines = page.locator("[data-dm-line]").evaluate_all("els => els.map(e => e.getAttribute('data-dm-line'))")
        assert {"debt_service_keur", "dscr", "eod_breach", "dsra_balance_keur"} <= set(lines)
        assert errors == []
    finally:
        context.close()


def test_csv_export_downloads_raw_persisted_values(world, live_server, browser, rcm_react_flag):
    context, page, errors = context_for(browser, live_server)
    try:
        open_metrics(page, live_server, world.weak)
        with page.expect_download() as info:
            page.locator("[data-dm-export='csv']").click()
        path = info.value.path()
        text = open(path, encoding="utf-8").read()
        assert text.splitlines()[0].startswith("Group,Line,Unit,") and "DSCR (base case)" in text and "n/a" in text
        from app.persistence.run_history_repository import get_run_history
        entry = get_run_history(USER, world.weak.project_id)[0]
        raw = min(p["reported_dscr"] for p in entry.integrity_evidence["senior_debt"]["periods"] if p["debt_service"] > 1e-6 and p["reported_dscr"] is not None)
        assert repr(raw) in text                                                                # full precision, not the displayed 2 decimals
        assert errors == []
    finally:
        context.close()


# ── Run picker, historical and stale Runs, Save never runs ───────────────────────────────────────────────────────────────────────────
def test_picker_shows_each_runs_own_terms_stale_banner_and_historical_note(world, live_server, browser, rcm_react_flag):
    context, page, errors = context_for(browser, live_server)
    try:
        open_metrics(page, live_server, world.history)
        assert page.locator("[data-dm-stale='true']").count() == 1                              # the Working Copy was edited after the Last Run
        assert page.locator("[data-dm-term='eod']").inner_text() == "0.5x"                       # the Last Run's OWN term, not today's 0.40
        assert row(page, "EOD_FLOOR").get_attribute("data-dm-status") == "NOT_TRIGGERED_UNDER_THIS_FLOOR"
        options = page.locator("[data-dm-picker='true'] option")
        assert options.count() == 2
        older = options.nth(1).get_attribute("value")
        page.locator("[data-dm-picker='true']").select_option(older)
        page.wait_for_selector(f"[data-dm-run='{older}']")
        assert page.locator("[data-dm-historical='true']").count() == 1
        assert page.locator("[data-dm-term='eod']").inner_text() == "1.05x"
        assert row(page, "EOD_FLOOR").get_attribute("data-dm-status") == "TRIGGERED"
        assert "dm_run=" + older in page.url
        assert len(history_rows(world.history)) == 2                                             # looking at Runs commits nothing
        assert errors == []
    finally:
        context.close()


def test_editing_terms_in_debt_terms_saves_without_running_and_never_rewrites_the_saved_run(world, live_server, browser, rcm_react_flag):
    context, page, errors = context_for(browser, live_server)
    try:
        record = world.healthy
        before = len(history_rows(record))
        page.goto(f"{live_server}/v2/model-react/{record.project_code}#financing")
        page.wait_for_selector("[data-sheet-editor='debt']", timeout=30000)
        field = page.locator("#wf-debt-debt-contract-min-dscr-eod")
        assert float(field.input_value()) == 1.0
        field.fill("1.30")
        page.get_by_role("button", name="Save Minimum DSCR").click()
        page.wait_for_selector("[data-wf-status='ok']", timeout=20000)
        assert len(history_rows(record)) == before                                               # Save is not Run
        page.locator("[data-financing-tab-button='debt-metrics']").click()
        page.wait_for_selector("[data-debt-metrics='true']")
        assert page.locator("[data-dm-stale='true']").count() == 1
        assert page.locator("[data-dm-term='eod']").inner_text() in ("1.0x", "1.00x")             # the saved Run keeps the value it was committed with
        assert row(page, "EOD_FLOOR").get_attribute("data-dm-status") == "NOT_TRIGGERED_UNDER_THIS_FLOOR"   # the saved Run is unchanged
        page.locator("[data-dm-edit-terms='true']").click()
        page.wait_for_selector("[data-sheet-editor='debt']")
        assert errors == []
    finally:
        context.close()


def test_save_all_commits_both_terms_with_another_pending_edit_in_one_request_and_never_runs(world, live_server, browser, rcm_react_flag):
    """WS-2 x WF-04: both contractual terms are staged in the shared pending-change store beside another financing edit, listed in the Changes
    panel, saved by ONE all-or-none Save All request, never run the model and leave the Last Run STALE; a malformed term makes the server refuse the WHOLE request (nothing saved)."""
    record = world.env.create("wind")
    run(world.env, record)
    runs_before = len(history_rows(record))
    context, page, errors = context_for(browser, live_server)
    try:
        page.goto(f"{live_server}/v2/model-react/{record.project_code}#financing")
        page.wait_for_selector("[data-sheet-editor='debt']", timeout=30000)
        from app.persistence import db
        from app.persistence.workspace_repository import get_workspace_state

        def ledger_rows():
            with db.get_cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM save_all_requests WHERE project_id=?", (record.project_id,))
                return cur.fetchone()["n"]

        before = dict(get_workspace_state(USER, record.project_id).draft_snapshot)
        page.locator("#wf-debt-debt-contract-min-dscr-eod").fill("1.15")
        page.locator("#wf-debt-debt-contract-contractual-dscr").fill("abc")             # malformed: the server refuses the WHOLE request
        page.locator("#wf-debt-debt-senior-gearing-pct").fill("70")
        page.locator("[data-changes-toggle='true']").click()
        page.wait_for_selector("[data-changes-drawer='open']")
        assert page.locator("[data-changes-count]").first.get_attribute("data-changes-count") == "3"
        page.locator("[data-save-all='true']").click()
        page.wait_for_selector("[data-save-all-message='error']", timeout=30000)
        assert "Nothing was saved" in page.locator("[data-save-all-message='error']").inner_text()
        assert dict(get_workspace_state(USER, record.project_id).draft_snapshot) == before and ledger_rows() == 0      # all-or-nothing
        page.locator("[data-changes-toggle='true']").click()
        page.locator("#wf-debt-debt-contract-contractual-dscr").fill("1.25")
        panel = page.get_by_role("region", name="Pending changes")
        assert page.locator("[data-changes-count]").first.get_attribute("data-changes-count") == "3"
        text = panel.inner_text()
        assert "Minimum DSCR" in text and "Contractual DSCR" in text
        assert page.locator("[data-save-all='true']").is_enabled()
        page.locator("[data-save-all='true']").click()
        page.wait_for_selector("[data-save-all-message='ok']", timeout=30000)
        draft = dict(get_workspace_state(USER, record.project_id).draft_snapshot)
        assert draft["dscr_min_eod_x"] == "1.15" and draft["dscr_contractual_x"] == "1.25" and float(draft["gearing_pct"]) == 70.0     # exact, as entered
        assert ledger_rows() == 1                                                                # ONE successful request, ONE ledger row
        assert len(history_rows(record)) == runs_before                                          # Save All never runs the model
        page.evaluate("() => { window.location.hash = '#financing'; }")
        page.locator("[data-financing-tab-button='debt-metrics']").click()
        page.wait_for_selector("[data-debt-metrics='true']")
        assert page.locator("[data-dm-stale='true']").count() == 1                                # the committed Run is now outdated, not rewritten
        assert errors == []
    finally:
        context.close()


def test_overview_results_and_credit_link_to_the_same_view_without_a_document_reload(world, live_server, browser, rcm_react_flag):
    context, page, errors = context_for(browser, live_server)
    try:
        page.goto(f"{live_server}/v2/model-react/{world.weak.project_code}#overview")
        page.wait_for_selector("[data-overview-debt-metrics='true']", timeout=30000)
        page.evaluate("() => { window.__wf04_marker = 'same-document'; }")
        page.locator("[data-overview-debt-metrics='true'] a").click()
        page.wait_for_selector("[data-debt-metrics='true']", timeout=30000)
        assert page.evaluate("() => window.__wf04_marker") == "same-document"                    # no full reload
        page.evaluate("() => { window.location.hash = '#results'; }")
        page.wait_for_selector("[data-results-debt-metrics='true']", timeout=30000)
        page.locator("[data-results-debt-metrics='true'] a").click()
        page.wait_for_selector("[data-debt-metrics='true']", timeout=30000)
        assert page.evaluate("() => window.__wf04_marker") == "same-document"
        assert errors == []
    finally:
        context.close()


# ── responsive and themes ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_every_viewport_and_theme_stays_legible_without_page_overflow(world, live_server, browser, rcm_react_flag):
    from tests.model_react_overnight_b_acceptance import CONTRAST_JS, THEMES
    selector = ".dm-root :is(h2,h3,h4,label,p,li,button,a,th,td,dt,dd,summary,select,.dm-status,.dm-chip,.dm-dot)"
    for width, height in VIEWPORTS:
        context, page, errors = context_for(browser, live_server, (width, height))
        try:
            open_metrics(page, live_server, world.weak)
            for theme in THEMES:
                page.locator("[data-testid='finco-theme-select']").select_option(label=theme)
                page.wait_for_timeout(150)
                assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"), f"{width}px / {theme}: page overflows horizontally"
                weak = [s for s in page.evaluate(CONTRAST_JS, selector) if s["ratio"] < 4.5]
                assert not weak, f"{width}px / {theme}: contrast below 4.5:1 for {weak[:4]}"
                assert page.locator("[data-dm-covenants='true']").is_visible() and page.locator("[data-dm-schedule='true']").count() == 1
                matrix = page.locator("[data-dm-matrix='true']")
                assert matrix.is_visible() and matrix.locator("td[data-s]").count() == 5 * 54
                assert page.locator("[data-dm-mx-scroll='true']").evaluate("el => el.scrollWidth > el.clientWidth + 50"), "the matrix scrolls inside its own box"
                if SHOTS:
                    matrix.screenshot(path=os.path.join(SHOTS, f"wf04-matrix-{width}-{theme.replace(' ', '_')}.png"))
                if theme == THEMES[0]:
                    shot(page, f"weak-{width}")
            assert errors == []
        finally:
            context.close()


def test_period_status_matrix_is_a_compact_keyboard_grid_that_jumps_to_the_schedule_and_never_writes(world, live_server, browser, rcm_react_flag):
    context, page, errors = context_for(browser, live_server)
    posts: list[str] = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    try:
        open_metrics(page, live_server, world.weak)
        matrix = page.locator("[data-dm-matrix='true']")
        assert matrix.is_visible()
        assert [r.get_attribute("data-dm-mx-row") for r in matrix.locator("tbody tr").all()] == ["LOCKUP", "MIN_DSCR", "CONTRACTUAL_DSCR", "COVERAGE_1X", "CASH_SHORTFALL"]
        assert matrix.locator("th[scope='row']").count() == 5 and matrix.locator("td[data-s]").count() == 5 * 54
        assert matrix.locator("thead th[scope='colgroup']").count() >= 20 and matrix.locator("thead tr").count() == 2        # year hierarchy over 54 semiannual periods
        text = matrix.inner_text()
        assert "OPEN" not in text and "LOCKED" not in text                                                                     # dots, not comparator-style tiles
        summary = page.locator("[data-dm-mx-summary='true']").inner_text()
        assert "54" in summary and "Below Minimum DSCR" in summary and "Covenant breaches" in summary and "Coverage below 1.00x" in summary
        # every status has its own glyph; an unrecorded figure would be a dash, never a tick
        for status, glyph in (("OK", "✓"), ("ALERT", "×"), ("WARN", "!"), ("NA", "—")):
            cells = matrix.locator(f"td[data-s='{status}'] .dm-dot")
            if cells.count():
                assert cells.first.inner_text() == glyph
        assert matrix.locator("td[data-s='OK'] .dm-dot").count() > 0 and matrix.locator("td[data-s='ALERT'] .dm-dot").count() > 0
        # roving focus: exactly one tab stop; arrows move; the selected-period panel and aria labels carry the text alternative
        assert matrix.locator("td[tabindex='0']").count() == 1
        first = matrix.locator("td[data-r='1'][data-c='0']")
        first.focus()
        label = first.get_attribute("aria-label")
        assert label.startswith(matrix.locator("thead tr").nth(1).locator("th").first.get_attribute("title").split(" · ")[0]) and "Minimum DSCR" in label
        page.keyboard.press("ArrowRight")
        assert page.evaluate("() => document.activeElement.getAttribute('data-c')") == "1"
        page.keyboard.press("ArrowDown")
        assert page.evaluate("() => document.activeElement.getAttribute('data-r')") == "2"
        page.keyboard.press("End")
        assert page.evaluate("() => document.activeElement.getAttribute('data-c')") == "53"
        assert matrix.locator("[data-dm-mx-detail='true']").inner_text().count("—") >= 5
        # Enter on a period shows the same column in the debt schedule; nothing is written or re-run
        page.keyboard.press("Home")
        page.keyboard.press("ArrowRight")
        page.keyboard.press("ArrowRight")
        page.keyboard.press("Enter")
        col = matrix.locator("td[data-r='2'][data-c='2']").get_attribute("data-dm-period")
        assert page.evaluate("() => document.activeElement?.getAttribute('data-dm-col')") == col
        assert not [u for u in posts if "/v2/workbook/" in u]
        # the DSRA requirement is disclosed outside the matrix, never as a synthetic green row
        gap = matrix.locator("[data-dm-mx-gap='DSRA_REQUIRED']").inner_text()
        assert "UNAVAILABLE" in gap and "required DSRA" in gap
        assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")
        assert len(history_rows(world.weak)) == 1 and errors == []
        shot(page, "matrix-1440")
    finally:
        context.close()


def test_the_visible_labels_say_minimum_dscr_and_keep_the_model_condition_disclosure(world, live_server, browser, rcm_react_flag):
    context, page, errors = context_for(browser, live_server)
    try:
        open_metrics(page, live_server, world.weak)
        root = page.locator("[data-debt-metrics='true']")
        visible = root.inner_text()
        assert "EoD threshold" not in visible and "EoD floor" not in visible                                  # not a primary label anywhere on the screen
        terms = page.locator("[data-dm-terms='true']").inner_text()
        assert "Minimum DSCR" in terms and "Contractual DSCR" in terms and "Achieved Minimum DSCR" in terms
        assert page.locator("[data-dm-terms='true'] dt").count() == 3                                          # exactly two inputs + one read-only result
        assert "Minimum DSCR: Triggered" in page.locator("[data-dm-credit='eod']").inner_text()
        assert "not a legally adjudicated Event of Default" in page.locator("[data-dm-model-condition='true']").inner_text()
        assert "legally adjudicated" in page.locator("[data-dm-credit='eod']").get_attribute("title")
        assert "EVENT_OF_DEFAULT: TRIGGERED" in page.locator("[data-dm-row='EOD_FLOOR']").inner_text()        # the canonical verdict is unchanged
        assert "Minimum DSCR" in page.locator("[data-dm-row='EOD_FLOOR']").inner_text()
        assert "(EoD threshold)" not in page.locator("[data-dm-row='EOD_FLOOR']").inner_text()
        assert errors == []
    finally:
        context.close()


__all__ = [
    'world',
    'test_weak_coverage_eod_triggered_covenant_breached_and_run_completed',
    'test_no_terms_configured_is_not_configured_never_a_pass',
    'test_a_run_without_a_recorded_contract_is_unavailable_not_judged_by_todays_inputs',
    'test_healthy_run_shows_honest_neutral_ok_states_without_inventing_a_pass',
    'test_chart_plots_only_persisted_periods_has_a_data_table_and_is_keyboard_operable',
    'test_schedule_scrolls_horizontally_by_keyboard_and_period_links_jump_to_the_column',
    'test_csv_export_downloads_raw_persisted_values',
    'test_picker_shows_each_runs_own_terms_stale_banner_and_historical_note',
    'test_editing_terms_in_debt_terms_saves_without_running_and_never_rewrites_the_saved_run',
    'test_save_all_commits_both_terms_with_another_pending_edit_in_one_request_and_never_runs',
    'test_overview_results_and_credit_link_to_the_same_view_without_a_document_reload',
    'test_every_viewport_and_theme_stays_legible_without_page_overflow',
    'test_period_status_matrix_is_a_compact_keyboard_grid_that_jumps_to_the_schedule_and_never_writes',
    'test_the_visible_labels_say_minimum_dscr_and_keep_the_model_condition_disclosure',
]
