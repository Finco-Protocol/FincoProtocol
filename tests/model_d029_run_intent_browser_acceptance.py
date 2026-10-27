"""D-029 real-Chromium acceptance for the Run intent (React + Legacy/HTMX).

Not collected by pytest: executed through the thin wrappers in
``tests/test_model_workspace_consolidation_browser.py`` (the existing mandatory Chromium role).  No
module-level skip lives here.  Every check drives the REAL server, real Run route, real engine and asserts
on the committed Run History: one logical Run is one history row, however the response is lost.
"""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs

from tests.model_react_wf1_browser_acceptance import make_session
from tests.model_react_wf2_browser_acceptance import bar, history_count, open_workspace, runs, wait_status

UUID_V4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
RUN_PATH = "**/v2/workbook/run"
INTENT_PREFIXES = ("finco.run-intent.v1:", "finco.legacy-run-intent.v1:")


def stored_intents(page):
    return page.evaluate("""(prefixes) => Object.entries(localStorage).filter(([k]) => prefixes.some(p => k.startsWith(p)))
                              .map(([k, v]) => [k, JSON.parse(v)])""", list(INTENT_PREFIXES))


def storage_dump(page):
    return page.evaluate("() => JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)])")


def record_run_posts(page):
    posts = []

    def capture(request):
        if request.method == "POST" and request.url.endswith("/v2/workbook/run"):
            posts.append({k: v[0] for k, v in parse_qs(request.post_data or "").items()})
    page.on("request", capture)
    return posts


def lose_first_response(context):
    """The server completes the Run (commit included); the browser never sees the answer."""
    state = {"lost": 0}

    def handler(route):
        if state["lost"] == 0:
            state["lost"] = 1
            route.fetch()
            route.abort()
        else:
            route.continue_()
    context.route(RUN_PATH, handler)
    return state


def materialize(context, base, record):
    assert context.request.get(f"{base}/v2/workbook?project={record.project_code}").ok


def wait_intent_consumed(page):
    page.wait_for_function(
        """(prefixes) => !Object.keys(localStorage).some(k => prefixes.some(p => k.startsWith(p)))""",
        arg=list(INTENT_PREFIXES), timeout=60000)


def db_history_count(uid, record):
    """Committed Run History straight from the shared database (the Legacy surface has no React API)."""
    from app.persistence.run_history_repository import get_run_history
    return len(get_run_history(uid, record.project_id))


def click_run(page):
    page.locator("[data-wf-run='true']").click()


# ── React ────────────────────────────────────────────────────────────────────


def check_react_run_sends_a_uuid_intent_and_consumes_it_on_commit(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "d029-react-commit")
    base = react_enabled
    try:
        materialize(context, base, record)
        posts = record_run_posts(page)
        open_workspace(page, base, record, "overview")
        page.wait_for_function("() => { const run = document.querySelector(\"[data-wf-run='true']\"); return Boolean(run) && !run.disabled; }")
        click_run(page)
        page.wait_for_selector("[data-workflow-bar='true'][data-bar-freshness='CURRENT']", timeout=120000)
        assert len(posts) == 1 and UUID_V4.match(posts[0]["run_intent_id"]), posts
        assert history_count(context, base, record) == 1
        assert stored_intents(page) == [], "a committed Run consumes its intent"
        assert posts[0]["csrf_token"] not in storage_dump(page), "no token is ever stored"
        # the next deliberate Run uses a NEW key
        page.wait_for_function("() => { const run = document.querySelector(\"[data-wf-run='true']\"); return Boolean(run) && !run.disabled; }")
        click_run(page)
        page.wait_for_function("() => document.querySelector(\"[data-wf-run='true']\")?.textContent.includes('in progress')", timeout=15000)
        page.wait_for_function("() => { const run = document.querySelector(\"[data-wf-run='true']\"); return Boolean(run) && !run.disabled; }", timeout=120000)
        assert len(posts) == 2 and posts[1]["run_intent_id"] != posts[0]["run_intent_id"]
        assert not [e for e in errors if "Failed to load resource" not in e], errors
    finally:
        context.close()


def check_react_lost_response_survives_reload_and_resumes_the_original_run(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "d029-react-lost")
    base = react_enabled
    try:
        materialize(context, base, record)
        posts = record_run_posts(page)
        open_workspace(page, base, record, "overview")
        page.wait_for_function("() => { const run = document.querySelector(\"[data-wf-run='true']\"); return Boolean(run) && !run.disabled; }")
        lose_first_response(context)
        click_run(page)
        text = wait_status(page, "conflict", None, "[data-workflow-bar='true']")
        assert "UNKNOWN" in text
        assert page.locator("[data-wf-run='true']").is_disabled(), "a NEW Run stays locked while one is unconfirmed"
        assert history_count(context, base, record) == 1, "the server committed even though the response was lost"
        kept = stored_intents(page)
        assert len(kept) == 1 and kept[0][1]["id"] == posts[0]["run_intent_id"]
        assert kept[0][1]["contentHash"] == posts[0]["content_hash"]
        assert set(kept[0][1]) == {"id", "contentHash", "workbookVersion", "createdAt"}
        # Other work happens meanwhile: the draft hash moves on.  The resume must still use the ORIGINAL binding.
        first_history = runs(context, base, record)[0]["history_id"]
        page.reload()
        page.wait_for_selector("[data-workflow-bar='true']")
        page.wait_for_selector("[data-wf-resume='true']")
        page.locator("[data-wf-resume='true']").click()
        wait_intent_consumed(page)
        assert len(posts) == 2
        assert posts[1]["run_intent_id"] == posts[0]["run_intent_id"] and posts[1]["content_hash"] == posts[0]["content_hash"]
        assert history_count(context, base, record) == 1 and runs(context, base, record)[0]["history_id"] == first_history
        assert stored_intents(page) == []
        assert not [e for e in errors if "Failed to load resource" not in e], errors
    finally:
        context.close()


def current_draft_hash(context, base, record):
    payload = context.request.get(f"{base}/v2/model-react/fields/project_setup?project={record.project_code}").json()
    return payload["save"]["content_hash"]


def check_react_resume_after_the_draft_changed_never_runs_against_the_new_draft(browser, react_enabled):
    """A REAL committed edit moves the composite hash; the unresolved intent is then resumed with its ORIGINAL
    binding and must return the original history row without a second financial execution."""
    from tests.model_react_wf2_browser_acceptance import bumped, field_input_id, goto_section, numeric_bound_field
    context, page, record, errors = make_session(browser, react_enabled, "d029-react-edit")
    base = react_enabled
    try:
        page.on("dialog", lambda d: d.accept())
        materialize(context, base, record)
        posts = record_run_posts(page)
        open_workspace(page, base, record, "overview")
        page.wait_for_function("() => { const run = document.querySelector(\"[data-wf-run='true']\"); return Boolean(run) && !run.disabled; }")
        lose_first_response(context)
        click_run(page)
        wait_status(page, "conflict", None, "[data-workflow-bar='true']")
        before = runs(context, base, record)
        assert len(before) == 1, "the server committed exactly once although the response was lost"
        original_hash = posts[0]["content_hash"]
        assert current_draft_hash(context, base, record) == original_hash

        # A genuine, verified Save through the real editor (not a second tab simulation, not a mock).
        goto_section(page, "inputs")
        page.wait_for_selector("[data-sheet-editor='project_setup']")
        row = numeric_bound_field(context, base, record, "project_setup", prefer=("project_setup.technical.p50_hours",))
        new_value = bumped(row)
        page.locator(f"#{field_input_id('project_setup', row['field_id'])}").fill(new_value)
        page.get_by_role("button", name=f"Save {row['label']}").click()
        wait_status(page, "ok", "verified", "[data-sheet-editor='project_setup']")
        changed_hash = current_draft_hash(context, base, record)
        assert changed_hash != original_hash, "the composite hash must have moved"
        persisted = next(f for f in context.request.get(
            f"{base}/v2/model-react/fields/project_setup?project={record.project_code}").json()["fields"] if f["field_id"] == row["field_id"])
        assert float(persisted["value"]) == float(new_value)
        assert runs(context, base, record) == before, "Save never creates or changes a Run"

        page.reload()
        page.wait_for_selector("[data-wf-resume='true']")
        sent_before = len(posts)
        page.locator("[data-wf-resume='true']").click()
        wait_intent_consumed(page)
        assert len(posts) == sent_before + 1
        assert posts[-1]["run_intent_id"] == posts[0]["run_intent_id"]
        assert posts[-1]["content_hash"] == original_hash != changed_hash, "resume uses the ORIGINAL binding"
        after = runs(context, base, record)
        assert [r["history_id"] for r in after] == [r["history_id"] for r in before], "no second Run, same history row"
        assert after[0]["runtime_snapshot_id"] == before[0]["runtime_snapshot_id"]
        assert current_draft_hash(context, base, record) == changed_hash, "the replay did not touch the edited draft"
        assert not [e for e in errors if "Failed to load resource" not in e], errors
    finally:
        context.close()


def check_react_typed_outcomes_keep_or_consume_the_intent(browser, react_enabled):
    """Typed server outcomes are mapped exactly: ambiguous keeps the intent, definitive consumes it."""
    context, page, record, errors = make_session(browser, react_enabled, "d029-react-typed")
    base = react_enabled
    try:
        materialize(context, base, record)
        posts = record_run_posts(page)
        open_workspace(page, base, record, "overview")
        page.wait_for_function("() => { const run = document.querySelector(\"[data-wf-run='true']\"); return Boolean(run) && !run.disabled; }")
        mode = {"outcome": "IN_PROGRESS", "status": 409}

        def typed(route):
            route.fulfill(status=mode["status"], content_type="application/json",
                          body=json.dumps({"ok": False, "outcome": mode["outcome"], "message": "typed " + mode["outcome"]}))
        context.route(RUN_PATH, typed)
        click_run(page)
        wait_status(page, "conflict", "typed IN_PROGRESS", "[data-workflow-bar='true']")
        assert len(stored_intents(page)) == 1, "IN_PROGRESS keeps the intent"
        kept = stored_intents(page)[0][1]["id"]
        page.locator("[data-wf-resume='true']").click()
        wait_status(page, "conflict", "typed IN_PROGRESS", "[data-workflow-bar='true']")
        assert posts[1]["run_intent_id"] == kept == posts[0]["run_intent_id"]
        mode.update(outcome="FAILED", status=409)
        page.locator("[data-wf-resume='true']").click()
        wait_status(page, "error", "typed FAILED", "[data-workflow-bar='true']")
        assert stored_intents(page) == [], "FAILED is terminal and consumes the intent"
        assert not page.locator("[data-wf-resume='true']").count()
        page.wait_for_function("() => { const run = document.querySelector(\"[data-wf-run='true']\"); return Boolean(run) && !run.disabled; }")
        mode.update(outcome="HISTORY_UNAVAILABLE", status=409)
        click_run(page)
        wait_status(page, "conflict", "typed HISTORY_UNAVAILABLE", "[data-workflow-bar='true']")
        assert posts[-1]["run_intent_id"] not in (kept,), "a new deliberate Run gets a new key"
        assert history_count(context, base, record) == 0
    finally:
        context.close()


# ── Legacy / HTMX ────────────────────────────────────────────────────────────


def legacy_open(page, base, record):
    page.goto(f"{base}/v2/workbook?project={record.project_code}")
    page.wait_for_selector("[data-testid='v2-run-btn']")


def check_legacy_run_carries_a_uuid_and_consumes_it_on_commit(browser, live_server):
    UID = "d029-legacy-commit"
    context, page, record, errors = make_session(browser, live_server, UID)
    base = live_server
    try:
        posts = record_run_posts(page)
        legacy_open(page, base, record)
        page.locator("[data-testid='v2-run-btn']").click()
        page.wait_for_function("() => document.querySelector('[data-testid=\"v2-run-btn\"]') && !document.querySelector('[data-testid=\"v2-run-btn\"]').disabled")
        page.wait_for_timeout(1500)
        assert len(posts) == 1 and UUID_V4.match(posts[0]["run_intent_id"]), posts
        assert posts[0].get("run_csrf_token"), "Run CSRF is kept"
        assert db_history_count(UID, record) == 1
        assert stored_intents(page) == []
        assert posts[0]["run_csrf_token"] not in storage_dump(page)
    finally:
        context.close()


def check_legacy_lost_response_reload_and_oob_refresh_keep_the_same_run(browser, live_server):
    UID = "d029-legacy-lost"
    context, page, record, errors = make_session(browser, live_server, UID)
    base = live_server
    try:
        posts = record_run_posts(page)
        legacy_open(page, base, record)
        lose_first_response(context)
        page.locator("[data-testid='v2-run-btn']").click()
        page.wait_for_function("() => localStorage.length > 0")
        page.wait_for_timeout(1500)
        assert db_history_count(UID, record) == 1, "the server committed; only the response was lost"
        kept = stored_intents(page)
        assert len(kept) == 1 and kept[0][1]["id"] == posts[0]["run_intent_id"]
        page.reload()
        page.wait_for_selector("[data-testid='v2-run-btn']")
        assert page.locator(".v2-run-form").first.get_attribute("data-run-intent-pending") == "true"
        assert "Resume Run" in page.locator(".v2-run-label").first.inner_text()
        page.locator("[data-testid='v2-run-btn']").click()
        page.wait_for_timeout(2500)
        assert len(posts) == 2
        assert posts[1]["run_intent_id"] == posts[0]["run_intent_id"] and posts[1]["content_hash"] == posts[0]["content_hash"]
        assert db_history_count(UID, record) == 1, "the retry returned the original result; nothing was recalculated"
        assert stored_intents(page) == []
    finally:
        context.close()


def check_legacy_queued_run_after_pending_save_keeps_one_key_and_the_saved_binding(browser, live_server):
    UID = "d029-legacy-queued"
    context, page, record, errors = make_session(browser, live_server, UID)
    base = live_server
    try:
        posts = record_run_posts(page)
        legacy_open(page, base, record)
        page.evaluate("""() => {
            const input = document.querySelector('.v2-field-row[data-field-id="revenue.ppa.base_tariff"] .v2-field-input');
            input.value = String(Number(input.value || 0) + 3);
            input.dispatchEvent(new Event('input', { bubbles: true }));
        }""")
        hash_before = page.locator("#v2-canonical-run-form input[name='content_hash']").input_value()
        page.locator("[data-testid='v2-run-btn']").click()      # queued behind the pending save
        page.wait_for_timeout(5000)
        assert len(posts) == 1, posts
        assert UUID_V4.match(posts[0]["run_intent_id"])
        assert posts[0]["content_hash"] != hash_before, "the queued Run is bound to the SAVED draft, not the stale form value"
        assert db_history_count(UID, record) == 1
        assert stored_intents(page) == []
    finally:
        context.close()
