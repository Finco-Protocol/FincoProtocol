"""FINCO 36 Correction G — production React R04 editor acceptance (real Chromium against the BUILT, SERVED bundle, real persisted state).

Not collected by pytest: executed through the thin wrappers in ``tests/test_model_workspace_consolidation_browser.py`` (the existing
mandatory Chromium role and its Playwright fixtures).  No mocked network, no candidate-only component: the editor under test is the one
served from ``/static/react/finco-react.js``; every number asserted comes from the persisted contract book or the server review.
"""
from __future__ import annotations

import json
from decimal import Decimal, ROUND_FLOOR

from playwright.sync_api import expect

from tests.model_react_wf1_browser_acceptance import make_session
from tests.model_react_wf2_browser_acceptance import history_count, open_workspace, ppa_panel, wait_status

WIDTHS = (320, 390, 768, 1440)


def _saved(context, base, record):
    payload = context.request.get(f"{base}/v2/model-react/revenue?project={record.project_code}").json()
    raw = payload["contracts"]["raw"]
    return (json.loads(raw) if raw else None), payload["save"]["content_hash"]


def _cap_mwh(record, user):
    from app.input_adapter import build_projectinputs_from_snapshot
    from app.persistence.workspace_repository import get_workspace_state
    t = build_projectinputs_from_snapshot(dict(get_workspace_state(user, record.project_id).draft_snapshot)).technical
    return Decimal(repr(t.capacity_mw)) * Decimal(repr(t.operating_hours_p50)) * Decimal(repr(t.combined_availability))


def _no_overflow(page):
    return page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")


def _stream(page, n=0):
    return ppa_panel(page).locator("[data-ppa-stream]").nth(n)


def _fill_annual(stream, amount, unit, start, end, price="70"):
    stream.get_by_label("Contract volume basis").select_option("annual")
    stream.get_by_label("Start date").fill(start)
    stream.get_by_label("End date").fill(end)
    stream.locator("[data-ppa-annual-amount]").fill(str(amount))
    stream.locator("[data-ppa-annual-unit]").select_option(unit)
    stream.get_by_label("Tariff").fill(price)


def _review_state(page):
    page.locator("[data-r04-review]").wait_for()
    page.wait_for_function("() => document.querySelector('[data-r04-review]').getAttribute('data-r04-review') !== 'pending'", timeout=20000)
    return page.locator("[data-r04-review]").get_attribute("data-r04-review")


def check_r04_editor_cap_review_save_refusal_reload_run_and_responsive(browser, react_enabled):
    user = "g-r04-editor-user"
    context, page, record, errors = make_session(browser, react_enabled, user)
    base = react_enabled
    cap = _cap_mwh(record, user).quantize(Decimal("0.001"), rounding=ROUND_FLOOR)
    try:
        open_workspace(page, base, record, "inputs")
        page.wait_for_selector("[data-ppa-editor='empty']")
        ppa_panel(page).get_by_role("button", name="Define a PPA contract").click()
        stream = _stream(page)
        # an absolute contract's dates are canonical half-open dates: a mid-period start/end is NOT refused by boundary guidance
        _fill_annual(stream, "1000000", "MWh", "2031-03-01", "2032-03-01")
        assert _review_state(page) == "ok"
        expect(page.locator("[data-r04-blocked='true']")).to_be_visible()
        row = page.locator("[data-r04-table='years'] [data-r04-year='2031']")
        expect(row).to_have_attribute("data-r04-exceeded", "true")
        assert stream.locator("[data-date-guidance]").count() == 0
        # server refusal on Save, typed, with the local draft kept and nothing persisted
        before = _saved(context, base, record)
        h0 = history_count(context, base, record)
        ppa_panel(page).locator("[data-ppa-save='true']").click()
        wait_status(page, "error", "R04_GLOBAL_P50_CAP_EXCEEDED", "[data-ppa-editor]")
        expect(stream.locator("[data-ppa-annual-amount]")).to_have_value("1000000")
        assert _saved(context, base, record) == before == (None, before[1]) or _saved(context, base, record)[0] == before[0]
        assert history_count(context, base, record) == h0
        # exact boundary accepted by the server; +0.001 MWh refused (display of the very number the server computed)
        stream.locator("[data-ppa-annual-amount]").fill(str(cap + Decimal("0.001")))
        assert _review_state(page) == "ok"
        expect(page.locator("[data-r04-blocked='true']")).to_be_visible()
        stream.locator("[data-ppa-annual-amount]").fill(str(cap))
        assert _review_state(page) == "ok"
        expect(page.locator("[data-r04-blocked='true']")).to_have_count(0)
        # MWh and GWh are equivalent (1 GWh = 1000 MWh): the same quantity in GWh stays unblocked
        gwh = (cap / 1000).quantize(Decimal("0.000001"), rounding=ROUND_FLOOR)
        stream.locator("[data-ppa-annual-unit]").select_option("GWh")
        stream.locator("[data-ppa-annual-amount]").fill(format(gwh, "f"))
        assert _review_state(page) == "ok"
        expect(page.locator("[data-r04-blocked='true']")).to_have_count(0)
        # save the valid book, then reload and read the persisted terms
        ppa_panel(page).locator("[data-ppa-save='true']").click()
        wait_status(page, "ok", "saved", "[data-ppa-editor]")
        book, _hash = _saved(context, base, record)
        s0 = book["streams"][0]
        assert s0["annual_quantity"] == {"mode": "ABSOLUTE_ANNUAL", "amount": format(gwh, "f"), "unit": "GWh"} and s0["volume_share"] is None
        assert (s0["start_date"], s0["end_date"], s0["price_eur_mwh"]) == ("2031-03-01", "2032-03-01", 70)
        page.reload()
        page.wait_for_selector("[data-ppa-editor='guided']")
        page.evaluate("() => { window.location.hash = '#inputs'; }")
        again = _stream(page)
        expect(again.locator("[data-ppa-annual-amount]")).to_have_value(format(gwh, "f"))
        expect(again.locator("[data-ppa-annual-unit]")).to_have_value("GWh")
        # a second independently priced contract: committed quantity is summed against the ONE envelope
        ppa_panel(page).locator("[data-ppa-add='true']").click()
        second = _stream(page, 1)
        _fill_annual(second, "1", "GWh", "2031-03-01", "2032-03-01", price="65")
        assert _review_state(page) == "ok"
        expect(page.locator("[data-r04-blocked='true']")).to_be_visible()                  # cap + 1 GWh in the shared year: over the single envelope
        second.locator("[data-ppa-annual-amount]").fill("0.001")                           # 1 MWh more than the cap: still over
        assert _review_state(page) == "ok"
        expect(page.locator("[data-r04-blocked='true']")).to_be_visible()
        # Cancel returns to the saved book (nothing was saved)
        ppa_panel(page).get_by_role("button", name="Cancel edits").click()
        assert _saved(context, base, record)[0]["streams"][0]["annual_quantity"]["amount"] == format(gwh, "f")
        # responsive: no document-level horizontal overflow, controls labelled, at every contract width
        for width in WIDTHS:
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_timeout(150)
            assert _no_overflow(page), f"document overflows at {width}px"
            for label in ("Annual quantity", "Quantity unit", "Contract volume basis"):
                expect(_stream(page).get_by_label(label)).to_be_visible()
            region = page.locator("[data-r04-table='years']").locator("xpath=ancestor::div[@role='region']")
            assert region.get_attribute("aria-label") == "P50 envelope by calendar year"
        page.set_viewport_size({"width": 1440, "height": 1000})
        # the ONLY console error allowed is the browser's own line for the deliberately refused Save (HTTP 422)
        assert not [e for e in errors if "favicon" not in e and "422" not in e], errors
    finally:
        context.close()


def check_r04_share_only_legacy_flow_is_unchanged(browser, react_enabled):
    user = "g-r04-share-user"
    context, page, record, errors = make_session(browser, react_enabled, user)
    base = react_enabled
    try:
        open_workspace(page, base, record, "inputs")
        page.wait_for_selector("[data-ppa-editor='empty']")
        ppa_panel(page).get_by_role("button", name="Define a PPA contract").click()
        stream = _stream(page)
        stream.get_by_label("Tariff").fill("55")
        stream.get_by_label("Contracted volume share").fill("80")
        expect(page.locator("[data-r04-review]")).to_have_count(0)                         # no annual quantity: no cap panel, legacy rules
        ppa_panel(page).locator("[data-ppa-save='true']").click()
        wait_status(page, "ok", "saved", "[data-ppa-editor]")
        s0 = _saved(context, base, record)[0]["streams"][0]
        assert s0["volume_share"] == 0.8 and "annual_quantity" not in s0
    finally:
        context.close()


def check_r04_persisted_invalid_book_recovery_in_the_real_react_workspace(browser, react_enabled):
    """Forged over-cap book (fixture only) with a prior legitimate sealed Run: the React workspace offers the canonical repair, refuses bad
    repairs without any change, and a valid replacement restores a normal workspace; the prior Run and History stay as they were."""
    import sqlite3
    from app.persistence import db
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.workspace_repository import get_workspace_state
    user = "g-r04-recovery-user"
    context, page, record, errors = make_session(browser, react_enabled, user)
    base = react_enabled
    # a quantity every case can deliver (the P90 lender case generates less than the P50 cap: a fixed quantity above it is refused at Run)
    cap = Decimal("1000")

    def doc(amount):
        return json.dumps({"version": 2, "technology": "solar", "indexation_basis": "OPERATING_YEAR", "streams": [
            {"id": "ppa_1", "type": "ppa", "start_date": "2031-03-01", "end_date": "2032-03-01", "volume_share": None,
             "annual_quantity": {"mode": "ABSOLUTE_ANNUAL", "amount": str(amount), "unit": "MWh"}, "price_eur_mwh": 70.0,
             "indexation_rate": 0.0, "settlement": "SAME_PERIOD", "source_ref": "RECOVERY"},
            {"id": "merchant", "type": "merchant", "start_date": "2031-03-01", "end_date": "2056-03-01", "volume_share": None,
             "price_eur_mwh": 55.0, "indexation_rate": 0.0, "settlement": "SAME_PERIOD", "source_ref": "RECOVERY_M", "capture_rate": 1.0}]},
            separators=(",", ":"))
    try:
        # the initial valid book (PPA + the merchant residual a Run needs) goes through the canonical writer, as an API client / import would
        tok = context.request.get(f"{base}/v2/model-react/revenue?project={record.project_code}").json()["save"]
        saved = context.request.post(f"{base}/v2/workbook/revenue/contracts", form={
            "project": record.project_code, "csrf_token": tok["csrf_token"], "content_hash": tok["content_hash"], "contracts": doc(cap), "action": "save"},
            max_redirects=0)
        assert saved.status in (200, 303), saved.text()[:300]
        # a prior legitimate sealed Run through the canonical Run form
        from tests.model_react_wf1_browser_acceptance import run_canonical
        run_canonical(context, base, record.project_code)
        sealed = [e.history_id for e in get_run_history(user, record.project_id)]
        assert len(sealed) == 1
        # fixture-only forgery below the validators
        snap = dict(get_workspace_state(user, record.project_id).draft_snapshot)
        snap["rev_multistream_config_json"] = doc(10 ** 9)
        with db.get_cursor() as cur:
            cur.execute("UPDATE workspace_states SET draft_snapshot_json=? WHERE project_id=?", (json.dumps(snap), record.project_id))
        forged_state = dict(get_workspace_state(user, record.project_id).draft_snapshot)
        page.goto(f"{base}/v2/model-react/{record.project_code}#inputs")
        page.wait_for_selector("[data-working-copy-recovery='true']")
        expect(page.locator("[data-recovery-issue='revenue.multistream.contracts']")).to_contain_text("R04_GLOBAL_P50_CAP_EXCEEDED")
        assert page.locator("[data-ppa-editor]").count() == 0 and page.locator("[data-grid-cell]").count() == 0     # no editor, no financial grid
        assert dict(get_workspace_state(user, record.project_id).draft_snapshot) == forged_state                    # viewing mutated nothing
        form = page.locator("[data-recovery-book-form='true']")
        # refused repair: still over the cap -> typed refusal, draft stays, nothing changed
        form.locator("textarea").fill(doc(10 ** 8))
        form.get_by_role("button", name="Replace contract book").click()
        page.wait_for_selector("[data-working-copy-recovery='true'] [role='alert'], [data-working-copy-recovery='true'] .rx-status-error")
        expect(page.locator("[data-working-copy-recovery='true']")).to_contain_text("R04_GLOBAL_P50_CAP_EXCEEDED")
        assert dict(get_workspace_state(user, record.project_id).draft_snapshot) == forged_state
        assert [e.history_id for e in get_run_history(user, record.project_id)] == sealed
        # valid replacement restores a normal workspace
        form.locator("textarea").fill(doc(cap))
        form.get_by_role("button", name="Replace contract book").click()
        page.wait_for_selector("[data-ppa-editor='guided']", timeout=30000)
        assert page.locator("[data-working-copy-recovery='true']").count() == 0
        saved = json.loads(get_workspace_state(user, record.project_id).draft_snapshot["rev_multistream_config_json"])
        assert saved["streams"][0]["annual_quantity"]["amount"] == str(cap)
        assert [e.history_id for e in get_run_history(user, record.project_id)] == sealed               # prior sealed Run identity unchanged
        assert not [e for e in errors if "favicon" not in e and "422" not in e and "409" not in e], errors
    finally:
        context.close()
