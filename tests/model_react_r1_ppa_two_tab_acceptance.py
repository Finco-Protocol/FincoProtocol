"""R1 — two-tab PPA Save All acceptance (real Chromium, synthetic disposable working copy).

Not collected by pytest: executed through the thin wrapper in ``tests/test_model_workspace_consolidation_browser.py`` (the existing mandatory
Chromium role and its Playwright fixtures), like the WF-React-2 bodies.  No module-level skip lives here.

Tab A stages a PPA tariff edit against saved version H1.  Tab B saves a DIFFERENT PPA term (indexation) and advances the project to H2.
Tab A's Save All is refused as stale (409, nothing written); after the workspace refresh Tab A keeps its unsaved intent visible as a conflict,
can NOT replay the H1 document under H2 (no second request), never shows "All changes were saved together", and leaves Tab B's saved term
intact.  The visible "Discard my PPA changes and load the saved contract" action restores the saved H2 contract; an explicit fresh edit then
saves exactly that one term and keeps Tab B's.
"""
from __future__ import annotations

import json

from playwright.sync_api import expect

from tests.model_react_wf1_browser_acceptance import make_session
from tests.model_react_wf2_browser_acceptance import history_count, open_workspace, ppa_panel, wait_status


def _saved_stream(context, base, record):
    payload = context.request.get(f"{base}/v2/model-react/revenue?project={record.project_code}").json()
    return json.loads(payload["contracts"]["raw"])["streams"][0], payload["save"]["content_hash"]


def _stream_panel(page):
    return ppa_panel(page).locator("[data-ppa-stream]").first


def _open_changes(page):
    if page.locator("[data-changes-drawer='open']").count() == 0:
        page.locator("[data-changes-toggle='true']").click()
        page.wait_for_selector("[data-changes-drawer='open']")


def check_r1_stale_ppa_document_is_never_replayed_by_a_second_tab(browser, react_enabled):
    context, page_a, record, errors = make_session(browser, react_enabled, "r1-two-tab-user")
    base = react_enabled
    page_b = context.new_page()
    saves: list[dict] = []

    def on_response(response):
        if response.url.endswith("/v2/workbook/save-all") and response.request.method == "POST":
            saves.append({"status": response.status, "body": json.loads(response.request.post_data or "{}"),
                          "reply": response.json() if response.status in (200, 409, 422) else None})

    page_a.on("response", on_response)
    try:
        # H1: one saved contract (tariff 55, indexation 2 %, volume 80 %)
        open_workspace(page_a, base, record, "inputs")
        page_a.wait_for_selector("[data-ppa-editor='empty']")
        panel = ppa_panel(page_a)
        panel.get_by_role("button", name="Define a PPA contract").click()
        stream = _stream_panel(page_a)
        stream.locator("[data-ppa-advanced] summary").click()
        stream.get_by_label("Source reference").fill("Signed PPA 2026")
        stream.get_by_label("Tariff").fill("55")
        stream.get_by_label("Contracted volume share").fill("80")
        panel.locator("[data-ppa-save='true']").click()
        page_a.wait_for_selector("[data-ppa-editor='guided']", timeout=20000)
        page_a.locator("[data-unsaved-indicator='true']").wait_for(state="detached")
        _stream_panel(page_a).get_by_label("Indexation rate").fill("2")
        ppa_panel(page_a).locator("[data-ppa-save='true']").click()
        wait_status(page_a, "ok", "verified", "[data-ppa-editor]")
        page_a.locator("[data-unsaved-indicator='true']").wait_for(state="detached")
        expect(ppa_panel(page_a).locator("[data-ppa-save='true']")).to_be_disabled(timeout=20000)
        h1_stream, h1_hash = _saved_stream(context, base, record)
        assert (h1_stream["price_eur_mwh"], h1_stream["indexation_rate"], h1_stream["volume_share"]) == (55, 0.02, 0.8)

        # Tab B opens the same project; Tab A stages a TARIFF edit authored against H1
        open_workspace(page_b, base, record, "inputs")
        page_b.wait_for_selector("[data-ppa-editor='guided']")
        _stream_panel(page_a).get_by_label("Tariff").fill("60")
        expect(page_a.locator("[data-changes-count]").first).to_have_attribute("data-changes-count", "1")

        # Tab B saves a DIFFERENT term (indexation 3 %): H2
        _stream_panel(page_b).get_by_label("Indexation rate").fill("3")
        ppa_panel(page_b).locator("[data-ppa-save='true']").click()
        wait_status(page_b, "ok", "verified", "[data-ppa-editor]")
        h2_stream, h2_hash = _saved_stream(context, base, record)
        assert h2_hash != h1_hash
        assert (h2_stream["price_eur_mwh"], h2_stream["indexation_rate"]) == (55, 0.03)

        # Tab A Save All under H1: the legitimate stale refusal, nothing written
        _open_changes(page_a)
        page_a.locator("[data-save-all='true']").click()
        page_a.wait_for_selector("[data-save-all-message='error']", timeout=30000)
        assert [s["status"] for s in saves] == [409] and saves[0]["reply"].get("reload") is True, saves
        assert page_a.locator("[data-save-all-message='ok']").count() == 0
        still, _ = _saved_stream(context, base, record)
        assert (still["price_eur_mwh"], still["indexation_rate"]) == (55, 0.03)

        # after the refresh Tab A keeps its intent as a visible conflict and cannot replay the H1 document
        page_a.wait_for_selector("[data-ppa-stale='true']", timeout=30000)
        assert _stream_panel(page_a).get_by_label("Tariff").input_value() == "60"          # the unsaved intent is still on screen
        _open_changes(page_a)
        page_a.wait_for_selector("[data-change-id] [data-conflict-code], [data-change-id][data-conflict]", timeout=10000)
        assert page_a.locator("[data-changes-count]").first.get_attribute("data-changes-count") == "1"
        save_all = page_a.locator("[data-save-all='true']")
        if save_all.is_enabled():
            save_all.click()                                  # even when pressed, the builder fails closed locally
        page_a.wait_for_timeout(1500)
        assert [s["status"] for s in saves] == [409], f"no second Save All request may be sent: {saves}"
        assert page_a.locator("[data-save-all-message='ok']").count() == 0
        assert "All changes were saved together" not in page_a.locator("body").inner_text()
        persisted, _ = _saved_stream(context, base, record)
        assert (persisted["price_eur_mwh"], persisted["indexation_rate"]) == (55, 0.03), "Tab B's saved term stays intact"
        assert _stream_panel(page_a).get_by_label("Indexation rate").input_value() in ("2", "3")   # read-only stale draft, never saved

        # the explicit action loads the saved H2 contract and clears the staged intent
        page_a.locator("[data-ppa-stale-discard='true']").click()
        page_a.wait_for_selector("[data-ppa-stale='true']", state="detached", timeout=10000)
        expect(_stream_panel(page_a).get_by_label("Tariff")).to_have_value("55", timeout=20000)
        expect(_stream_panel(page_a).get_by_label("Indexation rate")).to_have_value("3", timeout=20000)
        expect(page_a.locator("[data-changes-count]").first).to_have_attribute("data-changes-count", "0")

        # an explicit fresh edit against H2 saves exactly that term, keeping Tab B's
        _stream_panel(page_a).get_by_label("Tariff").fill("61")
        expect(page_a.locator("[data-changes-count]").first).to_have_attribute("data-changes-count", "1")
        _open_changes(page_a)
        page_a.locator("[data-save-all='true']").click()
        page_a.wait_for_selector("[data-save-all-message='ok']", timeout=30000)
        assert [s["status"] for s in saves] == [409, 200], saves
        assert saves[1]["body"]["content_hash"] == h2_hash and saves[1]["reply"]["model_executed"] is False
        final, _ = _saved_stream(context, base, record)
        assert (final["price_eur_mwh"], final["indexation_rate"], final["volume_share"]) == (61, 0.03, 0.8)
        assert history_count(context, base, record) == 0, "Save All never runs the model"
        assert not [e for e in errors if "Failed to load resource" not in e], errors
    finally:
        context.close()
