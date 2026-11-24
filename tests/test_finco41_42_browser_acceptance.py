"""FINCO41-42 multi-viewport Chromium browser acceptance (no skips; screenshots when FINCO41_42_SCREENSHOT_DIR is set)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import threading
import time

import pytest

VIEWPORTS = [
    (1440, 900),
    (1280, 800),
    (768, 1024),
    (390, 844),
    (320, 640),
]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    import uvicorn
    from app.persistence import db
    from app.runtime.model_execution import ModelExecutionConfig, ModelExecutor, reset_model_executor_for_tests

    mp = pytest.MonkeyPatch()
    db_path = tmp_path_factory.mktemp("finco41-42-browser") / "browser_acceptance.db"
    mp.setattr(db, "DB_PATH", str(db_path))
    mp.setenv("FINCO_DB_PATH", str(db_path))
    mp.setenv("FINCO_MODEL_REACT_V1", "1")
    mp.setenv("FINCO_MODEL_EXECUTION_MODE", "thread")
    db.init_db()
    executor = ModelExecutor(ModelExecutionConfig(mode="thread"))
    reset_model_executor_for_tests(executor)

    import main_web

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    instance = uvicorn.Server(uvicorn.Config(main_web.app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not instance.started:
        if time.monotonic() > deadline:
            raise RuntimeError("Local browser acceptance server did not start")
        time.sleep(0.05)

    yield f"http://127.0.0.1:{port}"

    instance.should_exit = True
    thread.join(10)
    executor.shutdown_and_join()
    reset_model_executor_for_tests(None)
    mp.undo()


def _save_shot(page, name: str) -> None:
    shot_dir = os.environ.get("FINCO41_42_SCREENSHOT_DIR", "").strip()
    if shot_dir:
        Path(shot_dir).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(shot_dir) / f"{name}.png"), full_page=True)


def _open_context(browser, server: str, user_id: str, width: int, height: int):
    from app.auth import COOKIE_NAME, create_session_token

    context = browser.new_context(viewport={"width": width, "height": height})
    context.add_cookies(
        [{"name": COOKIE_NAME, "value": create_session_token(user_id=user_id, username="admin"), "url": server}]
    )
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.on(
        "console",
        lambda msg: errors.append(msg.text)
        if msg.type == "error" and not str((msg.location or {}).get("url", "")).endswith("/favicon.ico")
        else None,
    )
    return context, page, errors


def _run_canonical(context, server: str, user_id: str, project_id: str, project_code: str) -> None:
    from bs4 import BeautifulSoup

    page = context.request.get(f"{server}/v2/workbook?project={project_code}")
    form = BeautifulSoup(page.text(), "html.parser").select_one("#v2-canonical-run-form")
    assert form is not None, "canonical run form missing"
    tokens = {f["name"]: f.get("value", "") for f in form.select("input[name]")}
    resp = context.request.post(
        f"{server}/v2/workbook/run",
        headers={"HX-Request": "true"},
        form={"project": project_code, **tokens},
    )
    assert resp.ok, resp.text()[:300]
    assert resp.headers.get("x-finco-run-outcome") != "FAILED", resp.headers


def _save_debt_cell(context, server: str, project_code: str, field_id: str, value: str) -> None:
    payload = context.request.get(
        f"{server}/v2/model-react/inputs",
        params={"project": project_code},
    ).json()
    save_meta = payload["save"]
    resp = context.request.post(
        f"{server}/v2/workbook/grid/save",
        data=json.dumps(
            {
                "project": project_code,
                "csrf_token": save_meta["csrf_token"],
                "content_hash": save_meta["content_hash"],
                "workbook_version": save_meta["workbook_version"],
                "scenario_id": save_meta["scenario_id"],
                "cells": [{"field_id": field_id, "value": value}],
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 200, resp.text()


def test_acquisition_five_viewports_and_dirty_reload(server):
    from playwright.sync_api import sync_playwright
    from app.services.reference_seed_service import create_reference_seeded_project

    uid = "finco41-acq-browser"
    rec = create_reference_seeded_project(
        user_id=uid,
        template_source="generic_solar_reference",
        requested_name="FINCO41 Acq Browser",
        capacity_mw=20.0,
    )

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            ctx, page, errors = _open_context(browser, server, uid, 1440, 900)
            _run_canonical(ctx, server, uid, rec.project_id, rec.project_code)

            page.goto(f"{server}/v2/valuation-acquisition?project={rec.project_code}")
            page.wait_for_selector("[data-testid='m6-workspace']", timeout=30000)
            cal_text = page.locator("[data-testid='m6-calendar-authority']").inner_text()
            assert "LEGACY_CALENDAR/v0" in cal_text

            # 1. C1F-C-1 invalid out-of-horizon closing date rejected (422) without persisting
            page.fill("input[name='closing_date']", "2065-01-01")
            page.fill("input[name='purchase_price_keur']", "12000")
            page.fill("input[name='transaction_costs_keur']", "200")
            page.fill("input[name='closing_adjustment_keur']", "0")
            page.fill("input[name='buyer_discount_rate']", "0.09")
            page.fill("input[name='target_buyer_irr']", "0.10")
            page.fill("input[name='bid_lower_bound_keur']", "1000")
            page.fill("input[name='bid_upper_bound_keur']", "40000")
            page.locator("[data-testid='m6-save']").click()
            page.wait_for_load_state("networkidle")
            assert "CLOSING_NOT_WITHIN_SOURCE_HORIZON" in page.content()

            # 2. Reload, fill valid terms + closing bridge, save & verify persistence after reload
            page.goto(f"{server}/v2/valuation-acquisition?project={rec.project_code}")
            page.wait_for_selector("[data-testid='m6-save-form']", timeout=30000)
            values = {
                "closing_date": "2031-07-15",
                "purchase_price_keur": "12000",
                "transaction_costs_keur": "200",
                "closing_adjustment_keur": "0",
                "buyer_discount_rate": "0.09",
                "target_buyer_irr": "0.10",
                "bid_lower_bound_keur": "1000",
                "bid_upper_bound_keur": "40000",
                "enterprise_value_keur": "41000",
                "senior_debt_keur": "26000",
                "unrestricted_cash_keur": "500",
                "restricted_cash_keur": "1900",
                "shl_balance_keur": "3500",
                "debt_like_keur": "0",
                "working_capital_adjustment_keur": "0",
                "transaction_adjustment_keur": "0",
            }
            for k, v in values.items():
                page.fill(f"input[name='{k}']", v)
            page.locator("[data-testid='m6-save']").click()
            page.wait_for_selector("[data-testid='m6-saved']", timeout=30000)
            page.reload()
            page.wait_for_selector("[data-testid='m6-workspace']", timeout=30000)
            assert page.input_value("input[name='closing_date']") == "2031-07-15"
            assert float(page.input_value("input[name='enterprise_value_keur']")) == 41000.0
            _save_shot(page, "finco41_acq_1440")
            unexpected_errs = [e for e in errors if "status of 422" not in e]
            assert unexpected_errs == [], unexpected_errs
            ctx.close()

            # 3. Check all 5 viewports for overflow
            for w, h in VIEWPORTS:
                vctx, vpage, verrors = _open_context(browser, server, uid, w, h)
                vpage.goto(f"{server}/v2/valuation-acquisition?project={rec.project_code}")
                vpage.wait_for_selector("[data-testid='m6-workspace']", timeout=30000)
                overflow = vpage.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
                assert overflow <= 2, f"Acquisition overflow {overflow}px at {w}x{h}"
                if w in (390, 320):
                    _save_shot(vpage, f"finco41_acq_{w}")
                assert verrors == [], verrors
                vctx.close()
        finally:
            browser.close()


def test_investor_f4_react_five_viewports_historical_isolation_race_and_dirty_draft(server):
    from playwright.sync_api import sync_playwright
    from app.services.reference_seed_service import create_reference_seeded_project

    uid = "finco41-inv-browser"
    rec = create_reference_seeded_project(
        user_id=uid,
        template_source="generic_solar_reference",
        requested_name="FINCO41 Inv Browser",
        capacity_mw=20.0,
    )

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            ctx, page, errors = _open_context(browser, server, uid, 1440, 900)
            page.goto(f"{server}/v2/model-react/{rec.project_code}?financing=investors#financing")
            page.wait_for_selector("[data-financing-studio='true']", timeout=30000)
            page.locator("[data-financing-tab-button='investors']").click()
            page.wait_for_selector("[data-investors-panel='true']", timeout=30000)

            # Before first Run: Save agreement with paid-in row -> SAVED_NOT_RUN + NOT_RUN (UNVERIFIED_NO_LAST_RUN) advisory (never runs model)
            page.fill("[data-inv='agreement_id']", "AGR-PRERUN")
            page.locator("[data-inv-add='holder']").click()
            pr_h0 = page.locator("[data-inv-holder='0'] input")
            pr_h0.nth(0).fill("INV-A")
            pr_h0.nth(1).fill("100")
            pr_h0.nth(2).fill("1000")
            page.locator("[data-inv-add='contribution']").click()
            pr_c0 = page.locator("[data-inv-contribution='0'] input")
            pr_c0.nth(0).fill("INV-A")
            pr_c0.nth(1).fill("2030-01-01")
            pr_c0.nth(2).fill("100")
            page.locator("[data-inv-save='true']").click()
            page.wait_for_selector("[data-investor-workflow='SAVED_NOT_RUN']", timeout=30000)
            page.wait_for_selector("[data-investor-funding-advisory='NOT_RUN']", timeout=30000)
            page.locator("[data-inv-remove='true']").click()
            page.locator("[data-inv-remove-yes='true']").click()
            page.wait_for_selector("[data-investor-workflow='NONE']", timeout=30000)

            # Execute Run A, enter 60/40 agreement AGR-RET -> Save -> Run A2 incorporates AGR-RET v1
            _run_canonical(ctx, server, uid, rec.project_id, rec.project_code)
            api1 = ctx.request.get(f"{server}/v2/model-react/investors/agreement", params={"project": rec.project_code}).json()
            funding1 = api1["funding"]
            assert funding1
            page.reload()
            page.wait_for_selector("[data-financing-tab-button='investors']", timeout=30000)
            page.locator("[data-financing-tab-button='investors']").click()
            page.wait_for_selector("[data-investors-panel='true']", timeout=30000)

            page.fill("[data-inv='agreement_id']", "AGR-RET")
            page.locator("[data-inv-add='holder']").click()
            h0 = page.locator("[data-inv-holder='0'] input")
            h0.nth(0).fill("INV-A")
            h0.nth(1).fill("60")
            h0.nth(2).fill("15000")
            page.locator("[data-inv-add='holder']").click()
            h1 = page.locator("[data-inv-holder='1'] input")
            h1.nth(0).fill("INV-B")
            h1.nth(1).fill("40")
            h1.nth(2).fill("15000")
            idx = 0
            for frow in funding1:
                for name, share in (("INV-A", 0.6), ("INV-B", 0.4)):
                    page.locator("[data-inv-add='contribution']").click()
                    crow = page.locator(f"[data-inv-contribution='{idx}'] input")
                    crow.nth(0).fill(name)
                    crow.nth(1).fill(frow["date"])
                    crow.nth(2).fill(repr(round(frow["paid_in_keur"] * share, 10)))
                    idx += 1
            page.locator("[data-inv-save='true']").click()
            page.wait_for_selector("[data-investor-workflow='SAVED_NOT_RUN']", timeout=30000)
            _save_shot(page, "finco41_inv_1440_saved_not_run")

            # Run 2 binds AGR-RET v1; capture Run 2 historical identity & sponsor returns
            _run_canonical(ctx, server, uid, rec.project_id, rec.project_code)
            curr_run2 = ctx.request.get(f"{server}/v2/model-react/investors/agreement", params={"project": rec.project_code}).json()
            assert curr_run2["workflow"]["state"] == "INCORPORATED"
            hid_run2 = curr_run2["history"][0]["history_id"]

            # Mutate gearing materially (55%), triggering STALE -> Run 3 produces materially different returns
            _save_debt_cell(ctx, server, rec.project_code, "debt.senior.gearing_pct", "55")
            page.reload()
            page.wait_for_selector("[data-financing-tab-button='investors']", timeout=30000)
            page.locator("[data-financing-tab-button='investors']").click()
            page.wait_for_selector("[data-investor-funding-advisory='STALE']", timeout=30000)
            _save_shot(page, "finco41_inv_1440_stale")

            _run_canonical(ctx, server, uid, rec.project_id, rec.project_code)
            api_after_r3 = ctx.request.get(f"{server}/v2/model-react/investors/agreement", params={"project": rec.project_code}).json()
            hid_run3 = api_after_r3["history"][0]["history_id"]
            assert hid_run3 != hid_run2

            # Verify historical Run 2 renders strictly Run 2 snapshot/returns, hides editor/save & working facts
            page.reload()
            page.wait_for_selector("[data-financing-tab-button='investors']", timeout=30000)
            page.locator("[data-financing-tab-button='investors']").click()
            page.wait_for_selector("[data-investors-panel='true']", timeout=30000)
            page.locator("[data-investor-history='true'] summary").click()
            page.locator(f"[data-inv-history-id='{hid_run2}']").click()
            page.wait_for_selector("[data-investor-workflow='HISTORICAL']", timeout=30000)
            assert page.locator("[data-investors-panel='true']").get_attribute("data-investor-scope") == "HISTORICAL"
            assert page.locator("[data-inv-save='true']").count() == 0
            assert page.locator("[data-sponsor-facts='true']").count() == 0
            assert page.locator("[data-sponsor-inputs-unavailable='true']").is_visible()
            assert "Historical" in page.locator("[data-investor-evidence-heading='true']").inner_text()
            assert "Historical" in page.locator("[data-sponsor-returns-heading='true']").inner_text()
            assert "Last Run" not in page.locator("[data-sponsor-returns-heading='true']").inner_text()
            run2_pure_eq_display = curr_run2["sponsor"]["returns"][0]["display"]
            assert run2_pure_eq_display in page.locator("[data-sponsor-returns='true']").inner_text()
            export_href = page.locator("[data-investor-binding='true'] a").get_attribute("href") or ""
            assert f"history_id={hid_run2}" in export_href
            _save_shot(page, "finco41_inv_1440_historical")

            # Return to current -> Remove working agreement -> typing AGR-RET predicts next Save version 2
            page.locator("[data-inv-history-current-banner='true']").click()
            page.wait_for_selector("[data-investor-scope='CURRENT']", timeout=30000)
            page.locator("[data-inv-remove='true']").click()
            page.locator("[data-inv-remove-yes='true']").click()
            page.wait_for_selector("[data-wf-status='ok']", timeout=30000)
            page.fill("[data-inv='agreement_id']", "AGR-RET")
            assert "next Save writes version 2" in page.locator("[data-investors-panel='true']").inner_text()

            # Dirty draft preservation prompt: Cancel keeps dirty edit, Keep preserves across history, Discard resets
            page.locator("[data-inv-history-id='" + hid_run2 + "']").click()
            page.wait_for_selector("[data-inv-history-dirty-prompt='true']", timeout=30000)
            page.locator("[data-inv-history-cancel='true']").click()
            assert page.locator("[data-inv-history-dirty-prompt='true']").count() == 0
            assert page.input_value("[data-inv='agreement_id']") == "AGR-RET"

            page.locator("[data-inv-history-id='" + hid_run2 + "']").click()
            page.wait_for_selector("[data-inv-history-dirty-prompt='true']", timeout=30000)
            page.locator("[data-inv-history-keep-draft='true']").click()
            page.wait_for_selector("[data-investor-workflow='HISTORICAL']", timeout=30000)
            assert page.locator("[data-investor-draft-parked='true']").is_visible()
            page.locator("[data-inv-history-current-banner='true']").click()
            page.wait_for_selector("[data-investor-scope='CURRENT']", timeout=30000)
            assert page.input_value("[data-inv='agreement_id']") == "AGR-RET"

            page.locator("[data-inv-history-id='" + hid_run2 + "']").click()
            page.wait_for_selector("[data-inv-history-dirty-prompt='true']", timeout=30000)
            page.locator("[data-inv-history-discard-draft='true']").click()
            page.wait_for_selector("[data-investor-workflow='HISTORICAL']", timeout=30000)
            page.locator("[data-inv-history-current-banner='true']").click()
            page.wait_for_selector("[data-investor-scope='CURRENT']", timeout=30000)
            assert page.input_value("[data-inv='agreement_id']") == ""

            # Out-of-order delayed async fetch race: hold Run 2 response until Current completes, release late
            held_routes = []

            def delay_run2(route):
                url = route.request.url
                if f"history_id={hid_run2}" in url:
                    held_routes.append(route)
                else:
                    route.continue_()

            page.route("**/v2/model-react/investors/agreement*", delay_run2)
            page.locator("[data-investor-history='true'] summary").click() if page.locator("[data-investor-history='true']").get_attribute("open") is None else None
            page.locator(f"[data-inv-history-id='{hid_run2}']").click()
            deadline = time.monotonic() + 5
            while not held_routes:
                if time.monotonic() > deadline:
                    raise AssertionError("Delayed history request was not intercepted")
                page.wait_for_timeout(20)
            # Switch quickly to Run 3, then back to Current BEFORE releasing Run 2
            page.locator(f"[data-inv-history-id='{hid_run3}']").click()
            page.wait_for_selector("[data-investor-workflow='HISTORICAL']", timeout=30000)
            page.locator("[data-inv-history-current-banner='true']").click()
            page.wait_for_selector("[data-investor-scope='CURRENT']", timeout=30000)
            # Now fulfill delayed Run 2 response cleanly (may be aborted already by AbortController, handle both)
            try:
                held_routes[0].continue_()
            except Exception:
                pass
            page.wait_for_timeout(200)
            assert page.locator("[data-investors-panel='true']").get_attribute("data-investor-scope") == "CURRENT"
            page.unroute("**/v2/model-react/investors/agreement*")

            assert [e for e in errors if "Abort" not in e] == [], errors
            ctx.close()

            # Check all 5 viewports
            for w, h in VIEWPORTS:
                vctx, vpage, verrors = _open_context(browser, server, uid, w, h)
                vpage.goto(f"{server}/v2/model-react/{rec.project_code}?financing=investors#financing")
                vpage.wait_for_selector("[data-financing-tab-button='investors']", timeout=30000)
                vpage.locator("[data-financing-tab-button='investors']").click()
                vpage.wait_for_selector("[data-investors-panel='true']", timeout=30000)
                overflow = vpage.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
                assert overflow <= 2, f"Investor F4 overflow {overflow}px at {w}x{h}"
                if w in (390, 320):
                    _save_shot(vpage, f"finco41_inv_{w}")
                assert verrors == [], verrors
                vctx.close()
        finally:
            browser.close()


def test_bess_setup_preview_five_viewports_and_declared_terms(server):
    from playwright.sync_api import sync_playwright
    from domain.bess.synthetic import example

    payload = json.dumps({"version": 1, "configuration": example(), "variable_om_eur_per_dc_mwh": 0})
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            for w, h in VIEWPORTS:
                ctx, page, errors = _open_context(browser, server, f"finco42-bess-{w}", w, h)
                page.goto(f"{server}/v2/model-react/#new-project/new")
                page.locator("[data-bess-setup='true']").wait_for(timeout=30000)
                assert page.locator("[data-tech-card='storage']").is_disabled()
                assert page.locator("[data-wizard-create]").count() == 0
                page.get_by_role("button", name="Preview standalone Storage inputs").click()
                page.locator("#bess-native-json").fill(payload)
                page.get_by_role("button", name="Validate setup on server").click()
                page.locator("[data-bess-validated='true']").wait_for(timeout=30000)
                declared = page.locator("[data-bess-declared-terms='true']")
                assert declared.is_visible()
                decl_text = declared.inner_text()
                assert "EUR/DC MWh" in decl_text and "DECLARED_INPUTS_ONLY_NOT_FINANCIAL_RESULTS" in decl_text
                overflow = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
                assert overflow <= 2, f"BESS preview overflow {overflow}px at {w}x{h}"
                if w in (1440, 390, 320):
                    _save_shot(page, f"finco42_bess_preview_{w}")
                assert errors == [], errors
                ctx.close()
        finally:
            browser.close()
