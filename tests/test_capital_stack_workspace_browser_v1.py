"""F3.6 Capital Stack Workspace in a REAL Chromium against a live server (synthetic working copies)."""
from __future__ import annotations

import os
import socket
import threading
import time

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")
from playwright.sync_api import expect, sync_playwright  # noqa: E402

PORT = 8797
VERTICALS = ["generic_solar_reference", "generic_wind_reference",
             "generic_data_center_reference", "generic_ev_charging_reference"]
SHOTS = os.environ.get("F36_SCREENSHOT_DIR")


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    import uvicorn
    from app.persistence import db

    mp = pytest.MonkeyPatch()
    mp.setattr(db, "DB_PATH", str(tmp_path_factory.mktemp("cs") / "cs.db"))
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
    yield f"http://127.0.0.1:{PORT}"
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
        except Exception as exc:
            pytest.skip(f"chromium unavailable: {exc}")
        yield instance
        instance.close()


def _session(live_server, browser, uid, template, viewport=None, scheme="light"):
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project

    rec = create_reference_seeded_project(user_id=uid, template_source=template, requested_name="CS", capacity_mw=16)
    ctx = browser.new_context(viewport=viewport or {"width": 1440, "height": 1000}, color_scheme=scheme)
    ctx.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username="admin"), "url": live_server}])
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{live_server}/v2/workbook?project={rec.project_code}&sheet=debt")
    page.wait_for_selector("[data-testid=capital-stack-table]")
    return rec, ctx, page, errors


def _shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name), full_page=False)


def _ws(uid, rec):
    from app.persistence.workspace_repository import get_workspace_state
    return get_workspace_state(uid, rec.project_id)


@pytest.mark.parametrize("template", VERTICALS)
def test_table_draft_status_unsupported_and_no_run_on_open(live_server, browser, template):
    uid = "cs-" + template[8:14]
    rec, ctx, page, errors = _session(live_server, browser, uid, template)
    before = _ws(uid, rec)
    assert page.locator("[data-testid=cs-row]").count() == 2
    expect(page.locator("[data-testid=cs-stack-status]")).to_have_text("DRAFT")
    assert page.locator("[data-testid=cs-row-status]").all_inner_texts() == ["DRAFT", "DRAFT"]
    page.locator("[data-testid=cs-unsupported] button[data-accordion-target]").click()                       # Flowbite accordion (was a <details> summary)
    text = page.locator("[data-testid=cs-unsupported]").inner_text()
    assert "UNSUPPORTED" in text and "Junior" in text and "Mezzanine" in text
    assert page.locator("[data-testid=cs-unsupported] input").count() == 0
    expect(page.locator("[data-testid=cs-summary-working]")).to_contain_text("not a calculated result")
    assert page.locator("[data-testid=cs-summary-last-run]").count() == 0
    _shot(page, f"{template}-01-draft.png")
    after = _ws(uid, rec)
    assert (before.dirty, before.last_runtime_snapshot_id) == (after.dirty, after.last_runtime_snapshot_id)
    assert not errors
    ctx.close()


def test_keyboard_dirty_markers_expand_escape(live_server, browser):
    rec, ctx, page, errors = _session(live_server, browser, "cs-kbd", VERTICALS[0])
    rates = page.locator('[data-f3="rate_pct"]')
    rates.nth(0).focus()
    rates.nth(0).fill("5.5")
    expect(page.locator("[data-cs-dirty]")).to_be_visible()
    assert page.locator("[data-cs-mod]:visible").count() == 1
    rates.nth(0).press("Enter")                       # commit + move to the same column, next row
    assert page.evaluate("document.activeElement === document.querySelectorAll('[data-f3=rate_pct]')[1]")
    page.keyboard.press("ArrowUp")
    assert page.evaluate("document.activeElement === document.querySelectorAll('[data-f3=rate_pct]')[0]")
    rates.nth(0).press("Escape")                      # revert the cell
    expect(page.locator("[data-cs-dirty]")).to_be_hidden()
    toggle = page.locator("[data-cs-expand]").first
    expect(page.locator("[data-cs-detail]").first).to_be_hidden()
    toggle.click()
    expect(page.locator("[data-cs-detail]").first).to_be_visible()
    assert toggle.get_attribute("aria-expanded") == "true"
    _shot(page, "solar-02-expanded.png")
    toggle.click()
    expect(page.locator("[data-cs-detail]").first).to_be_hidden()
    assert not errors
    ctx.close()


@pytest.mark.parametrize("template", VERTICALS[:2])
def test_save_marks_saved_proposal_persists_and_runs_nothing(live_server, browser, template):
    uid = "cs-save-" + template[8:12]
    rec, ctx, page, errors = _session(live_server, browser, uid, template)
    before = _ws(uid, rec)
    row = page.locator("[data-f3-instrument]").first
    row.locator("[data-cs-expand]").click()
    draws = row.locator('[data-f3="draws"]')
    first_date = draws.input_value().splitlines()[0].split(",")[0].strip()
    row.locator('[data-f3="commitment_keur"]').fill("1000")
    draws.fill(f"{first_date}, 1000")
    row.locator('[data-f3="rate_pct"]').fill("4.25")
    row.locator('[data-f3="grace_months"]').fill("12")
    with page.expect_response(lambda r: r.url.endswith("/v2/workbook/update")) as resp:
        page.locator("[data-f3-save]").click()
    assert resp.value.status == 200
    page.wait_for_selector("[data-testid=cs-stack-status]")
    expect(page.locator("[data-testid=cs-stack-status]")).to_have_text("SAVED PROPOSAL")
    expect(page.locator('[data-f3="commitment_keur"]').first).to_have_value("1000")
    ws = _ws(uid, rec)
    assert ws.dirty and ws.last_runtime_snapshot_id == before.last_runtime_snapshot_id   # no Run, no history
    assert page.locator("[data-testid=cs-summary-last-run]").count() == 0                 # proposal != calculated
    page.reload()
    page.wait_for_selector("[data-testid=capital-stack-table]")
    expect(page.locator('[data-f3="rate_pct"]').first).to_have_value("4.25")
    expect(page.locator("[data-testid=cs-stack-status]")).to_have_text("SAVED PROPOSAL")
    _shot(page, f"{template}-03-saved-proposal.png")
    assert not errors
    ctx.close()


def test_invalid_input_is_rejected_by_backend_and_nothing_is_persisted(live_server, browser):
    uid = "cs-bad"
    rec, ctx, page, errors = _session(live_server, browser, uid, VERTICALS[0])
    before = _ws(uid, rec)
    row = page.locator("[data-f3-instrument]").first
    row.locator('[data-f3="maturity_date"]').fill("1999-01-01")      # well-formed, but before the operating period
    with page.expect_response(lambda r: r.url.endswith("/v2/workbook/update")) as resp:
        page.locator("[data-f3-save]").click()
    after = _ws(uid, rec)
    expect(page.locator("[role=alert]").first).to_contain_text("F3_INVALID_TERM")
    assert "financing_instruments_json" not in str(after.draft_snapshot)      # rejected atomically
    assert after.draft_snapshot == before.draft_snapshot and after.dirty == before.dirty
    ctx.close()


@pytest.mark.parametrize("scheme,width", [("dark", 1440), ("light", 390), ("dark", 390)])
def test_theme_and_narrow_layout_without_page_overflow(live_server, browser, scheme, width):
    rec, ctx, page, errors = _session(live_server, browser, f"cs-lay-{scheme}-{width}", VERTICALS[1],
                                      viewport={"width": width, "height": 900}, scheme=scheme)
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 1
    _shot(page, f"wind-04-{scheme}-{width}.png")
    assert not errors
    ctx.close()


def test_editing_senior_cells_preserves_a_saved_junior_proposal(live_server, browser):
    import json
    from dataclasses import replace
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook import multisenior_config as config
    from app.workbook.input_set import ProjectInputSet
    from app.workbook.registry import WORKBOOK
    from app.workbook.update_service import WorkbookUpdateService
    from finco_core.inputs.financing_instruments import FinancingCollection, InstrumentType
    from tests.test_model_financing_f3_workspace import collection_for_inputs
    uid = "cs-junior"
    rec, ctx, page, errors = _session(live_server, browser, uid, VERTICALS[0])
    ws = get_workspace_state(uid, rec.project_id)
    pi = ProjectInputSet.from_snapshot(ws.draft_snapshot).to_projectinputs()
    s, j = collection_for_inputs(pi).instruments
    j = replace(j, instrument_type=InstrumentType.JUNIOR_DEBT, seniority_rank=2, fees=(), name="Junior Debt")
    raw = json.dumps({"schema_version": config.SCHEMA, "scopes": {"base": {
        "proposal": FinancingCollection((s, j)).to_dict(), "activation": None}}})
    WorkbookUpdateService.apply_draft_update(ws=ws, project_record=rec, field_id=config.FIELD_ID, raw_value=raw,
        workbook_version=WORKBOOK.version, content_hash=page.locator("[name=content_hash]").first.input_value())
    page.reload()
    page.wait_for_selector("[data-testid=capital-stack-table]")
    assert page.locator("[data-f3-instrument]").count() == 1 and page.locator("[data-cs-readonly-instrument]").count() == 1
    expect(page.locator("[data-testid=cs-junior-readiness]")).to_contain_text("Activation closed")
    page.locator('[data-f3="rate_pct"]').first.fill("6.5")
    with page.expect_response(lambda r: r.url.endswith("/v2/workbook/update")) as resp:
        page.locator("[data-f3-save]").click()
    assert resp.value.status == 200
    entry = json.loads(_ws(uid, rec).draft_snapshot[config.SNAPSHOT_KEY])["scopes"]["base"]
    kinds = {i["instrument_type"]: i for i in entry["proposal"]["instruments"]}
    assert kinds["JUNIOR_DEBT"] == FinancingCollection((s, j)).to_dict()["instruments"][1]     # untouched
    assert abs(kinds["SENIOR_TERM_LOAN"]["interest"]["fixed_rate"] - 0.065) < 1e-12 and entry["activation"] is None
    _shot(page, "solar-05-junior-proposal.png")
    assert not errors
    ctx.close()
