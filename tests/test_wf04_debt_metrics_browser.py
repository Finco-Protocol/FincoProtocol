"""WF-04 Debt Metrics in a REAL Chromium against a live server (synthetic working copies only).

Weak coverage is the seeded Wind working copy at 85 % gearing under GEARING_CAP (the engine completes; raw minimum DSCR 0.9925…).  Every
number asserted is read from the committed Run's own API payload; no threshold is hard-coded as a canonical contractual value.
Set ``WF04_SCREENSHOT_DIR`` to keep screenshots (private/local evidence only — never committed).
"""
from __future__ import annotations

import os
import socket
import threading
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")
from playwright.sync_api import sync_playwright  # noqa: E402

from tests.test_model_financing_f2 import run  # noqa: E402
from tests.test_wf04_credit_debt_metrics import COV, EOD, update, weak_wind  # noqa: E402

PORT = 8813
USER = "decision-user"
SHOTS = os.environ.get("WF04_SCREENSHOT_DIR", "")
VIEWPORTS = ((1440, 1000), (1366, 900), (768, 1000), (390, 844))


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    import uvicorn
    from app.persistence import db

    mp = pytest.MonkeyPatch()
    mp.setattr(db, "DB_PATH", str(tmp_path_factory.mktemp("dm") / "dm.db"))
    db.init_db()
    import main_web

    server = uvicorn.Server(uvicorn.Config(main_web.app, host="127.0.0.1", port=PORT, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(180):
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=1).close()
            break
        except OSError:
            time.sleep(1)
    os.environ["FINCO_MODEL_REACT_V1"] = "1"
    yield f"http://127.0.0.1:{PORT}"
    os.environ.pop("FINCO_MODEL_REACT_V1", None)
    server.should_exit = True
    thread.join(timeout=10)
    from app.runtime import model_execution as me
    me.reset_model_executor_for_tests(None)
    mp.undo()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        options = {"args": ["--no-sandbox"]}
        if os.environ.get("FINCO_TEST_CHROMIUM_PATH"):
            options["executable_path"] = os.environ["FINCO_TEST_CHROMIUM_PATH"]
        try:
            instance = pw.chromium.launch(**options)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium unavailable: {exc}")
        yield instance
        instance.close()


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
def test_weak_coverage_eod_triggered_covenant_breached_and_run_completed(world, live_server, browser):
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


def test_no_terms_configured_is_not_configured_never_a_pass(world, live_server, browser):
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


def test_a_run_without_a_recorded_contract_is_unavailable_not_judged_by_todays_inputs(world, live_server, browser):
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


def test_healthy_run_shows_honest_neutral_ok_states_without_inventing_a_pass(world, live_server, browser):
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
def test_chart_plots_only_persisted_periods_has_a_data_table_and_is_keyboard_operable(world, live_server, browser):
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


def test_schedule_scrolls_horizontally_by_keyboard_and_period_links_jump_to_the_column(world, live_server, browser):
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


def test_csv_export_downloads_raw_persisted_values(world, live_server, browser):
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
def test_picker_shows_each_runs_own_terms_stale_banner_and_historical_note(world, live_server, browser):
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


def test_editing_terms_in_debt_terms_saves_without_running_and_never_rewrites_the_saved_run(world, live_server, browser):
    context, page, errors = context_for(browser, live_server)
    try:
        record = world.healthy
        before = len(history_rows(record))
        page.goto(f"{live_server}/v2/model-react/{record.project_code}#financing")
        page.wait_for_selector("[data-sheet-editor='debt']", timeout=30000)
        field = page.locator("#wf-debt-debt-contract-min-dscr-eod")
        assert float(field.input_value()) == 1.0
        field.fill("1.30")
        page.get_by_role("button", name="Save Minimum DSCR (EoD threshold)").click()
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


def test_overview_results_and_credit_link_to_the_same_view_without_a_document_reload(world, live_server, browser):
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
def test_every_viewport_and_theme_stays_legible_without_page_overflow(world, live_server, browser):
    from tests.model_react_overnight_b_acceptance import CONTRAST_JS, THEMES
    selector = ".dm-root :is(h2,h3,h4,label,p,li,button,a,th,td,dt,dd,summary,select,.dm-status,.dm-chip)"
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
                if theme == THEMES[0]:
                    shot(page, f"weak-{width}")
            assert errors == []
        finally:
            context.close()
