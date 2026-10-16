"""SAFE CORE V3.4 / Workstream B (SC-04): a rejected Save never discards what the user typed, in real Chromium under the real CSP.

Every case uses TWO real browser contexts on the same Working Copy: tab A commits first, tab B (now stale) is refused by the server compare-and-swap.
The refused tab must keep its typed draft, show the actual error once in the right place with an explicit Reload, never claim "Saved", and never
overwrite the newer persisted values. Nothing here runs the model, so Run History must stay unchanged.
"""
from __future__ import annotations

import json
import re

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")

from tests.test_rcux2_ppa_quick_add_browser import Session, browser, live_server  # noqa: F401,E402
from tests.test_rcux2_construction_timing_browser import Timing  # noqa: E402

SAVED = re.compile(r"^Saved Working Copy")


def _second_view(browser, live_server, uid, rec, sheet):
    from app.auth import COOKIE_NAME, create_session_token
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username="admin"), "url": live_server}])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "409" not in m.text
            and not str((m.location or {}).get("url", "")).endswith("/favicon.ico") else None)
    page.goto(f"{live_server}/v2/workbook?project={rec.project_code}&sheet={sheet}")
    return ctx, page, errors


def _run_count(uid, rec):
    from app.persistence.run_history_repository import get_run_history
    return len(get_run_history(uid, rec.project_id))


def _fill_instrument(page, commit, rate):
    row = page.locator("[data-f3-instrument]").first
    row.locator("[data-cs-expand]").click()
    draws = row.locator('[data-f3="draws"]')
    first = draws.input_value().splitlines()[0].split(",")[0].strip()
    row.locator('[data-f3="commitment_keur"]').fill(str(commit))
    draws.fill(f"{first}, {commit}")
    row.locator('[data-f3="rate_pct"]').fill(str(rate))
    row.locator('[data-f3="grace_months"]').fill("12")


def _persisted_instrument(uid, rec):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.input_set import ProjectInputSet
    ws = get_workspace_state(uid, rec.project_id)
    raw = ProjectInputSet.from_snapshot(ws.draft_snapshot).get("debt.financing.instruments")
    state = json.loads(raw) if isinstance(raw, str) else raw
    entry = next(iter(state["scopes"].values()))
    inst = entry["proposal"]["instruments"][0]
    return inst["commitment_keur"], inst["interest"]["fixed_rate"]


def test_debt_stale_save_keeps_the_typed_stack_and_offers_reload(live_server, browser):
    from tests.test_capital_stack_workspace_browser_v1 import _session
    uid = "sc34-debt-stale"
    rec, ctx_a, a, _ = _session(live_server, browser, uid, "generic_solar_reference")
    ctx_b, b, errors_b = _second_view(browser, live_server, uid, rec, "debt")
    b.wait_for_selector("[data-testid=capital-stack-table]")
    runs_before = _run_count(uid, rec)
    _fill_instrument(a, 1000, 4.25)
    with a.expect_response(lambda r: r.url.endswith("/v2/workbook/update")) as ra:
        a.locator("[data-f3-save]").click()
    assert ra.value.status == 200
    committed = _persisted_instrument(uid, rec)
    _fill_instrument(b, 2000, 5.5)
    with b.expect_response(lambda r: r.url.endswith("/v2/workbook/update")) as rb:
        b.locator("[data-f3-save]").click()
    assert rb.value.headers.get("hx-reswap") == "none"                                    # the persisted sheet is not swapped over the draft
    error = b.locator("[data-f3-error]").first
    error.locator("[data-conflict-reload]").wait_for()
    text = error.inner_text()
    assert "not saved" in text and "typed values are kept" in text and "Saved" not in text.replace("Saved financing", "")
    row = b.locator("[data-f3-instrument]").first
    assert row.locator('[data-f3="commitment_keur"]').input_value() == "2000"            # the draft survived
    assert row.locator('[data-f3="rate_pct"]').input_value() == "5.5"
    assert _persisted_instrument(uid, rec) == committed                                   # the newer commit was never overwritten
    assert _run_count(uid, rec) == runs_before                                            # no Run was created
    assert len(b.locator("[data-f3-error] [data-conflict-reload]").all()) == 1            # one message, one recovery action
    error.locator("[data-conflict-reload]").click()
    b.wait_for_load_state("load")
    b.wait_for_selector("[data-testid=capital-stack-table]")
    assert b.locator('[data-f3="commitment_keur"]').first.input_value() == "1000"        # Reload shows the persisted values
    assert errors_b == [], errors_b
    ctx_a.close(); ctx_b.close()


def test_ppa_stale_save_keeps_the_contract_draft_and_does_not_claim_saved(live_server, browser):
    uid = "sc34-ppa-stale"
    s = Session(live_server, browser, uid)
    ctx_b, b, errors_b = _second_view(browser, live_server, uid, s.rec, "revenue")
    b.wait_for_selector("[data-testid=ppa-quick-add]", state="attached")
    runs_before = _run_count(uid, s.rec)
    s.page.evaluate("document.getElementById('tab-revenue').click()")
    s.page.locator("[data-testid=ppa-quick-add]").scroll_into_view_if_needed()
    s.fill(price="61", share="50", ref="PPA-A"); s.use_full_window(); s.add()
    s.page.locator("[data-revenue-save]").click()
    s.page.locator("[data-revenue-feedback]").filter(has_text=SAVED).wait_for()
    committed = s.saved_book()
    # tab B (stale) drafts a different contract and tries to save
    b.evaluate("document.getElementById('tab-revenue').click()")
    b.locator("[data-testid=ppa-quick-add]").scroll_into_view_if_needed()
    b.locator('[data-testid=ppa-quick-add] [data-quick="price"]').fill("77")
    b.locator('[data-testid=ppa-quick-add] [data-quick="share"]').fill("40")
    b.locator('[data-testid=ppa-quick-add] [data-quick="ref"]').fill("PPA-B")
    b.locator('[data-testid=ppa-quick-add] [data-dd="manual"]').check()
    b.locator('[data-testid=ppa-quick-add] [data-dd="end"]').fill(b.locator("[data-testid=ppa-quick-add]").get_attribute("data-window-end"))
    b.locator("[data-quick-add]").click()
    with b.expect_response(lambda r: r.url.endswith("/v2/workbook/revenue/contracts")) as rb:
        b.locator("[data-revenue-save]").click()
    assert rb.value.status == 409
    error = b.locator("[data-revenue-error]")
    error.locator("[data-conflict-reload]").wait_for()
    assert "reload" in error.inner_text().lower() and "unsaved contract draft" in error.inner_text()
    assert not SAVED.search(b.locator("[data-revenue-feedback]").inner_text())           # no false Saved confirmation
    assert b.locator("[data-revenue-editor]").get_attribute("data-dirty") == "true"      # the draft is still there
    assert b.evaluate("""() => { const f = document.querySelector('[data-revenue-editor]');
        return f.textContent.includes('PPA-B') || Array.from(f.querySelectorAll('input,textarea')).some(i => i.value.includes('PPA-B')); }""")
    assert s.saved_book() == committed                                                    # persisted contracts are A's, untouched
    assert _run_count(uid, s.rec) == runs_before
    error.locator("[data-conflict-reload]").click()
    b.wait_for_load_state("load")
    assert errors_b == [], errors_b
    s.close(); ctx_b.close()


def test_construction_timing_stale_save_keeps_the_typed_dates(live_server, browser):
    uid = "sc34-ct-stale"
    t = Timing(live_server, browser, uid)
    ctx_b, b, errors_b = _second_view(browser, live_server, uid, t.rec, "project_setup")
    b.wait_for_selector("[data-testid=construction-timing]", state="attached")
    b.evaluate("document.getElementById('tab-project-setup').click()")
    b.wait_for_function("() => document.querySelector('[data-testid=construction-timing] [data-dd=end]').value !== ''")
    runs_before = _run_count(uid, t.rec)
    t.dd("duration").fill("18"); t.dd("unit").select_option("months")
    t.save()
    committed = t.saved()
    b.locator('[data-testid=construction-timing] [data-dd="duration"]').fill("30")
    b.locator('[data-testid=construction-timing] [data-dd="unit"]').select_option("months")
    with b.expect_response(lambda r: "/grid/save" in r.url and r.request.method == "POST") as rb:
        b.locator("[data-ct-save]").click()
    assert rb.value.status == 409
    msg = b.locator("[data-testid=construction-timing-msg]")
    msg.locator("[data-conflict-reload]").wait_for()
    assert "nothing was saved" in msg.inner_text() and "typed dates are kept" in msg.inner_text()
    assert b.locator('[data-testid=construction-timing] [data-dd="duration"]').input_value() == "30"
    assert t.saved() == committed
    assert _run_count(uid, t.rec) == runs_before
    msg.locator("[data-conflict-reload]").click()
    b.wait_for_load_state("load")
    assert errors_b == [], errors_b
    t.ctx.close(); ctx_b.close()
