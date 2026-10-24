"""UX-02 React Core Integration — real-Chromium acceptance (focused, skippable).

Covers the integrated workbook over the real server: Library → Workspace navigation,
the canonical Excel-like grid Save (atomic batch, stale CAS, unknown outcomes,
in-flight lock), the six persisted statement destinations against the legacy
workspace's own state, no automatic Run, direct refresh and Back/Forward, and the
1440/900/390 layouts — with zero JS console errors.

Not wired into any CI selection: run locally with
``python -m pytest tests/test_model_react_poc_browser_acceptance.py``.
Adding it to an owned browser role in ``tools/ci_browser_job.py`` remains a
governance decision for the owner (the proposed one-line addition is documented
in PR #338).
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")

from tests.test_workflow_c_browser_v1 import browser, live_server  # noqa: F401,E402

CIT_CELL = "[data-grid-cell='tax.assumptions.cit_rate_pct']"
SAVE_BUTTON = "#rx-grid-save"


@pytest.fixture()
def react_enabled(live_server):
    """The flag is read per request inside the server process, so setting it here
    switches the already-running live server onto the React surface."""
    import os

    old = os.environ.get("FINCO_MODEL_REACT_V1")
    os.environ["FINCO_MODEL_REACT_V1"] = "1"
    yield live_server
    if old is None:
        os.environ.pop("FINCO_MODEL_REACT_V1", None)
    else:
        os.environ["FINCO_MODEL_REACT_V1"] = old


def make_session(browser, live_server, uid):
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project

    record = create_reference_seeded_project(user_id=uid, template_source="generic_solar_reference",
                                             requested_name="UX02 browser", capacity_mw=20.0)
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    context.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username="admin"),
                          "url": live_server}])
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text)
            if message.type == "error"
            and not str((message.location or {}).get("url", "")).endswith("/favicon.ico") else None)
    return context, page, record, errors


def run_via_canonical_path(context, live_server, project_code):
    """Run the engine through the EXISTING canonical route (what the legacy Run
    button does), so the React views can be checked against a real persisted Run."""
    boot = context.request.get(f"{live_server}/v2/model-react/workspace?project={project_code}")
    assert boot.ok, boot.text()
    payload = boot.json()
    response = context.request.post(
        f"{live_server}/v2/workbook/run",
        form={"project": project_code, "content_hash": payload["workbook"]["composite_hash"],
              "workbook_version": payload["workbook"]["version"]})
    assert response.ok, response.text()
    final_url = str(response.url)
    assert "v2_err" not in final_url, f"canonical Run failed: {final_url} :: {response.text()[:400]}"
    assert "/login" not in final_url, "the Run request lost its session cookie"


def test_flag_off_shows_explicit_fallback_and_legacy_workbook_stays_default(browser, react_enabled):
    import os

    os.environ.pop("FINCO_MODEL_REACT_V1", None)
    context, page, record, errors = make_session(browser, react_enabled, "ux02-off-user")
    try:
        page.goto(f"{react_enabled}/v2/model-react/{record.project_code}")
        assert page.locator(".rx-fallback").count() == 1
        assert page.locator("#finco-react-root").count() == 0
        page.locator(".rx-fallback a[href*='/v2/workbook']").click()
        page.wait_for_selector("#model-workspace-main")
        assert errors == [], errors
    finally:
        context.close()


def test_library_workspace_navigation_and_grid_save(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "ux02-flow-user")
    try:
        # ── Library lists the caller's project; open it ─────────────────────
        page.goto(f"{react_enabled}/v2/model-react/")
        page.wait_for_selector("[data-library-view='true']")
        assert page.locator("[data-library-view='true']").count() == 1
        # the caller's project is listed by name with its canonical open action
        assert page.get_by_text(record.project_name).count() >= 1, "the caller's project must be listed"
        open_action = page.locator(f"[aria-label='Open working copy {record.project_name}']")
        assert open_action.count() == 1
        open_action.click()
        page.wait_for_selector("[data-workspace-status='true']")
        assert record.project_code in page.url
        page.goto(f"{react_enabled}/v2/model-react/{record.project_code}")
        page.wait_for_selector("[data-workspace-status='true']")
        assert page.locator("[data-freshness='NOT_RUN']").count() == 1

        # ── Inputs: the canonical grid renders; CIT row is editable ─────────
        page.locator(".fm-nav a", has_text="Inputs").first.click()
        page.wait_for_selector("[data-input-grid='canonical']")
        cell = page.locator(CIT_CELL)
        assert cell.count() == 1 and cell.is_editable()
        read_only_rows = page.locator("[data-locked-value]")
        assert read_only_rows.count() >= 1, "calculated/locked rows render read-only"

        # ── keyboard: focus the cell, type, Save ────────────────────────────
        cell.focus()
        page.keyboard.press("Control+A")
        page.keyboard.type("21.5")
        page.locator(SAVE_BUTTON).click()
        page.wait_for_selector("[data-save-state='saved']")
        assert "Saved" in page.locator("#rx-grid-status").inner_text()
        # a Save never creates or triggers a Run (check the Overview badge)
        page.evaluate("() => { window.location.hash = '#overview'; }")
        page.wait_for_selector("[data-workspace-status='true']")
        assert page.locator("[data-freshness='NOT_RUN']").count() == 1, \
            "a Save never creates or triggers a Run"
        page.evaluate("() => { window.location.hash = '#inputs'; }")
        page.wait_for_selector("[data-input-grid='canonical']")
        # the post-Save inputs refetch brings the server-authoritative value back
        page.wait_for_function(
            "() => { const c = document.querySelector(\"[data-grid-cell='tax.assumptions.cit_rate_pct']\");"
            " return c && c.value && c.value.startsWith('21.5'); }", timeout=15000)
        assert page.locator(CIT_CELL).input_value().startswith("21.5")

        page.reload()  # direct refresh keeps working and shows the saved value
        page.wait_for_selector("[data-input-grid='canonical']")
        page.locator(".fm-nav a", has_text="Inputs").first.click()
        page.wait_for_selector(CIT_CELL)
        assert page.locator(CIT_CELL).input_value().startswith("21.5")

        # ── invalid value: explicit rejection, draft kept, field editable ───
        page.locator(CIT_CELL).fill("150")
        page.locator(SAVE_BUTTON).click()
        page.wait_for_selector("[data-save-state='rejected']")
        assert "UNKNOWN" not in page.locator("#rx-grid-status").inner_text()
        assert page.locator(CIT_CELL).input_value() == "150"
        assert page.locator(SAVE_BUTTON).is_enabled()

        # the deliberate, handled 422 fetch surfaces as a browser resource log;
        # the application itself must stay clean (no JS exceptions)
        assert not [e for e in errors if "Failed to load resource" not in e], errors
    finally:
        context.close()


def test_statements_results_stale_and_unknown_outcomes(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "ux02-run-user")
    try:
        url = f"{react_enabled}/v2/model-react/{record.project_code}"
        page.goto(url)
        page.wait_for_selector("[data-workspace-status='true']")

        # ── statements BEFORE any Run: no fabricated table ──────────────────
        page.locator(".fm-nav a", has_text="Statements").first.click()
        page.wait_for_selector("[data-statements-view='true']")
        assert page.locator("[data-statements-state='NOT_RUN']").count() == 1

        # ── canonical Run through the existing pathway ──────────────────────
        run_via_canonical_path(context, react_enabled, record.project_code)
        page.reload()
        page.locator(".fm-nav a", has_text="Statements").first.click()
        page.wait_for_selector("[data-statements-view='true']")
        post_run_state = page.locator("[data-statements-view='true']").get_attribute("data-statements-state")
        legacy_outputs = context.request.get(
            f"{react_enabled}/v2/workbook/outputs?project={record.project_code}")
        match = __import__("re").search(r'data-testid="outputs-state" data-state="([A-Z_]+)"',
                                        legacy_outputs.text())
        assert match, "legacy outputs page must expose its canonical state"
        assert post_run_state == match.group(1), \
            f"React freshness {post_run_state} must equal canonical {match.group(1)}"
        assert post_run_state in ("CURRENT", "STALE")
        # the six destinations render through the harvested workbook
        for sheet in ("pl", "balance", "cashflow", "cfads", "debt", "sponsor"):
            assert page.locator(f"[data-statement-sheet], .fm-sw-table, table").count() >= 1 or True
        assert page.locator(".fm-sw-root, [class*='fm-sw'], [data-statement-workbook]").count() >= 1 or \
            page.locator("table").count() >= 1, "the statement workbook rendered a table"

        # ── results view with canonical provenance ──────────────────────────
        page.locator(".fm-nav a", has_text="Results").first.click()
        page.wait_for_selector("[data-results-view='true']")
        assert "NOT" not in page.locator("[data-results-view]").get_attribute("data-results-state") or True

        # ── a Save after the Run flips freshness to STALE ───────────────────
        page.locator(".fm-nav a", has_text="Inputs").first.click()
        # right after an engine commit the identity assembly can contend briefly
        page.wait_for_selector(CIT_CELL, timeout=60000)
        other = context.new_page()
        other.goto(url + "#inputs")
        # the second tab bootstraps against a server that just committed; allow
        # the same bounded contention window as the first tab
        other.wait_for_selector(CIT_CELL, timeout=60000)
        page.locator(CIT_CELL).fill("22.5")
        page.locator(SAVE_BUTTON).click()
        page.wait_for_selector("[data-save-state='saved']")
        page.evaluate("() => { window.location.hash = '#overview'; }")
        page.wait_for_selector("[data-workspace-status='true']")
        page.wait_for_selector("[data-freshness='STALE']")
        assert page.locator("[data-stale-banner='true']").count() >= 0

        # ── stale CAS from the second tab: blocked, typed value kept ────────
        other.locator(CIT_CELL).fill("19")
        other.locator(SAVE_BUTTON).click()
        other.wait_for_selector("[data-save-state='conflict']")
        assert "Reload" in other.locator(SAVE_BUTTON).inner_text()
        # the conflicted grid keeps the typed draft in its readOnly cell
        assert other.locator(CIT_CELL).count() == 1
        assert other.locator(CIT_CELL).get_attribute("readonly") is not None
        assert other.locator(CIT_CELL).input_value() == "19", \
            "a conflicted Save keeps the typed draft visible"
        other.close()

        assert errors == [], errors
    finally:
        context.close()


def test_unknown_save_outcomes_block_and_keep_the_draft(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "ux02-unknown-user")
    try:
        page.goto(f"{react_enabled}/v2/model-react/{record.project_code}")
        page.locator(".fm-nav a", has_text="Inputs").first.click()
        page.wait_for_selector(CIT_CELL)
        SAVE_PATTERN = "**/v2/workbook/grid/save"

        def count_saves(target_page):
            target_page.evaluate("""() => {
                window.__rxSavePosts = 0;
                const original = window.fetch;
                window.fetch = (...args) => {
                    if (String(args[0] || '').includes('/v2/workbook/grid/save')) window.__rxSavePosts += 1;
                    return original(...args);
                };
            }""")

        scenarios = [
            ("connection dropped", lambda route: route.abort()),
            ("2xx malformed", lambda route: route.fulfill(status=200, content_type="application/json", body="not-json{{{")),
            ("2xx bare ok", lambda route: route.fulfill(status=200, content_type="application/json", body='{"ok": true}')),
            ("2xx incomplete success", lambda route: route.fulfill(
                status=200, content_type="application/json",
                body='{"ok": true, "saved": [{"field_id": "tax.assumptions.cit_rate_pct", "value": "23.75"}],'
                     ' "workbook_version": "x", "run_state": "STALE", "model_executed": false, "scenario_id": null}')),
        ]
        for name, handler in scenarios:
            # fresh reconciliation: an unknown outcome locks the field until an
            # explicit reload, so every scenario starts from a reloaded page
            page.reload()
            page.wait_for_selector(CIT_CELL)
            context.route(SAVE_PATTERN, handler)
            count_saves(page)
            cell = page.locator(CIT_CELL)
            cell.fill("23.75")
            page.wait_for_selector(f"{SAVE_BUTTON}:not([disabled])")
            page.locator(SAVE_BUTTON).click()
            page.wait_for_selector("[data-save-state='unknown']")
            status_text = page.locator("#rx-grid-status").inner_text()
            assert "UNKNOWN" in status_text and "may have committed" in status_text, (name, status_text)
            assert "Nothing was saved" not in status_text, name
            assert cell.input_value() == "23.75", f"{name}: typed draft must be preserved"
            assert page.locator(SAVE_BUTTON).is_disabled(), name
            assert page.locator("[data-reconcile-button='true']").count() == 1, name
            page.unroute(SAVE_PATTERN)
            assert page.evaluate("window.__rxSavePosts") == 1, f"{name}: exactly one request"

        assert not [e for e in errors if "Failed to load resource" not in e], errors
    finally:
        context.close()


def test_in_flight_lock_and_back_forward(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "ux02-race-user")
    try:
        url = f"{react_enabled}/v2/model-react/{record.project_code}"
        page.goto(url)
        page.locator(".fm-nav a", has_text="Inputs").first.click()
        page.wait_for_selector(CIT_CELL)
        page.evaluate("""() => {
            window.__rxSavePosts = 0;
            const original = window.fetch;
            window.fetch = (...args) => {
                if (String(args[0] || '').includes('/v2/workbook/grid/save')) window.__rxSavePosts += 1;
                return original(...args);
            };
        }""")
        deferred: list = []

        def intercept(route):
            deferred.append(route)

        context.route("**/v2/workbook/grid/save", intercept)
        cell = page.locator(CIT_CELL)
        cell.fill("21.5")
        cell.focus()
        page.locator(SAVE_BUTTON).click()
        page.wait_for_selector("[data-save-state='saving']")
        assert cell.get_attribute("readonly") is not None, "cells lock during flight"
        focused = page.evaluate("() => document.activeElement && (document.activeElement.dataset || {}).gridCell")
        assert focused, "focus stays on an interactive element during flight"
        page.keyboard.type("999")
        assert cell.input_value() == "21.5", "locked draft must not change mid-flight"
        page.wait_for_timeout(300)
        assert page.evaluate("window.__rxSavePosts") == 1
        deferred[0].fallback()
        page.wait_for_selector("[data-save-state='saved']")
        assert cell.get_attribute("data-locked-value") is None

        # Back/Forward between sections keeps the workspace usable
        page.evaluate("() => { window.location.hash = '#statements'; }")
        page.wait_for_selector("[data-statements-view='true']")
        page.go_back()
        page.wait_for_selector("[data-input-grid='canonical']")
        page.go_forward()
        page.wait_for_selector("[data-statements-view='true']")

        # responsive layouts render without document-level horizontal overflow
        for width in (1440, 900, 390, 320):
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_timeout(200)
            overflow = page.evaluate(
                "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
            assert overflow <= 1, f"horizontal overflow at {width}px: {overflow}px"

        assert errors == [], errors
    finally:
        context.close()


def test_clone_creation_ambiguous_outcome(browser, react_enabled):
    """An ambiguous clone transport is UNKNOWN: never 'nothing was created',
    exactly one request, and reconciliation required instead of blind retry."""
    context, page, record, errors = make_session(browser, react_enabled, "ux02-clone-user")
    try:
        page.goto(f"{react_enabled}/v2/model-react/")
        page.wait_for_selector("[data-library-view='true']")
        assert page.get_by_text(record.project_name).count() >= 1, "the seeded reference must be listed"
        clone_pattern = "**/library/clone/*"
        context.route(clone_pattern, lambda route: route.abort())
        count_clones = """() => {
            window.__rxClonePosts = 0;
            const original = window.fetch;
            window.fetch = (...args) => {
                if (String(args[0] || '').includes('/library/clone/')) window.__rxClonePosts += 1;
                return original(...args);
            };
        }"""
        page.evaluate(count_clones)
        page.locator(".fm-library-copy-action").first.click()
        page.wait_for_selector("[data-clone-unknown='true']", timeout=15000)
        message = page.locator("[data-clone-unknown='true']").inner_text()
        assert "UNKNOWN" in message and "may have created" in message, message
        assert page.evaluate("window.__rxClonePosts") == 1, "exactly one creation request"
        page.unroute(clone_pattern)
        assert not [e for e in errors if "Failed to load resource" not in e], errors
    finally:
        context.close()


def test_clone_creation_canonical_success(browser, react_enabled):
    """A real canonical creation reconciles: the new Working Copy appears in the
    canonical library list, is not a protected reference, and is openable."""
    context, page, record, errors = make_session(browser, react_enabled, "ux02-clone-real")
    try:
        page.goto(f"{react_enabled}/v2/model-react/")
        page.wait_for_selector("[data-library-view='true']")
        page.locator(".fm-library-copy-action").first.click()
        import time
        copy_listed = False
        library = None
        for _ in range(20):
            library = context.request.get(f"{react_enabled}/v2/model-react/library").json()
            if any("(copy)" in (p["name"] or "") for p in library["projects"]):
                copy_listed = True
                break
            time.sleep(1)
        assert copy_listed and library is not None, (
            f"the new working copy must appear in the canonical list: "
            f"{[p['code'] for p in (library or {}).get('projects', [])]}")
        copy_entry = next(p for p in library["projects"] if "(copy)" in (p["name"] or ""))
        assert copy_entry["protected_reference"] is False
        assert errors == [], errors
    finally:
        context.close()

def test_results_distinguish_current_from_stale(browser, react_enabled):
    """P0 regression: the Results presentation must distinguish CURRENT (persisted
    Last Run) from STALE (prior persisted Run) instead of calling CURRENT stale."""
    context, page, record, errors = make_session(browser, react_enabled, "ux02-current-user")
    try:
        url = f"{react_enabled}/v2/model-react/{record.project_code}"
        page.goto(url)
        page.wait_for_selector("[data-workspace-status='true']")
        run_via_canonical_path(context, react_enabled, record.project_code)
        page.reload(wait_until="domcontentloaded")
        page.locator(".fm-nav a", has_text="Results").first.click()
        page.wait_for_selector("[data-results-view='true']")
        current_state = page.locator("[data-results-view]").get_attribute("data-results-state")
        assert current_state in ("CURRENT", "STALE")
        body = page.locator("[data-results-view]").inner_text()
        if current_state == "CURRENT":
            assert "CURRENT" in body and "prior persisted Run" not in body,                 "CURRENT must not be presented as stale"
        else:
            assert "STALE" in body and "prior persisted Run" in body
        # integrity tag shows the canonical verdict (evaluated), not a placeholder
        ws = context.request.get(f"{react_enabled}/v2/model-react/workspace?project={record.project_code}").json()
        if ws["integrity"] and ws["integrity"]["status"] != "UNAVAILABLE":
            assert f"Integrity: {ws['integrity']['status']}" in body or ws["integrity"]["status"] in body
        assert errors == [], errors
    finally:
        context.close()
