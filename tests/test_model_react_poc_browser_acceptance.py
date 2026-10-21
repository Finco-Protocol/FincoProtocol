"""UX-01 React PoC — real-Chromium acceptance (focused, skippable).

Black-box checks over the real server: the React shell loads from same-origin
assets, the one canonical input saves through the EXISTING grid/save authority
(stale CAS included), the persisted P&L renders the committed Run's values with
unavailable cells as em dashes (never zeros), direct refresh works, and the page
is keyboard-operable with zero console errors.

Not wired into any CI selection: run locally with
``python -m pytest tests/test_model_react_poc_browser_acceptance.py``.
Adding it to an owned browser role in ``tools/ci_browser_job.py`` is a one-line
governance decision left to the reviewer.
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")

from tests.test_workflow_c_browser_v1 import browser, live_server  # noqa: F401,E402

CIT_INPUT = "#rx-cit-rate-input"


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
                                             requested_name="React PoC browser", capacity_mw=20.0)
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
    button does), so the React page can be checked against a real persisted Run."""
    boot = context.request.get(f"{live_server}/v2/model-react/bootstrap?project={project_code}")
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
    context, page, record, errors = make_session(browser, react_enabled, "rx-off-user")
    try:
        page.goto(f"{react_enabled}/v2/model-react/{record.project_code}")
        assert page.locator(".rx-fallback").count() == 1
        assert page.locator("#finco-react-root").count() == 0
        legacy = page.locator(".rx-fallback a[href*='/v2/workbook']")
        assert legacy.count() == 1
        legacy.click()
        page.wait_for_selector("#model-workspace-main")
        assert errors == [], errors
    finally:
        context.close()


def test_react_shell_save_stale_and_statement_acceptance(browser, react_enabled):
    context, page, record, errors = make_session(browser, react_enabled, "rx-on-user")
    try:
        # ── shell loads with flag ON, direct refresh works ──────────────────
        url = f"{react_enabled}/v2/model-react/{record.project_code}"
        page.goto(url)
        page.wait_for_selector("#finco-react-root h1")
        assert "React Preview" in page.locator("#finco-react-root h1").inner_text()
        assert page.locator(f"[data-field-id='tax.assumptions.cit_rate_pct']").count() == 1
        assert page.locator("[data-freshness='NOT_RUN']").count() == 1
        assert page.locator("[data-statement='NOT_RUN']").count() == 1, \
            "without a Run there is no statement and no fabricated table"

        page.reload()  # direct browser refresh must keep working
        page.wait_for_selector("#finco-react-root h1")

        # ── keyboard: focus the input, type, submit with Enter ─────────────
        input_field = page.locator(CIT_INPUT)
        input_field.focus()
        page.keyboard.press("Control+A")
        page.keyboard.type("21.5")
        page.keyboard.press("Enter")
        page.wait_for_selector("[data-save-state='saved']")
        assert "Saved" in page.locator(".rx-status").inner_text()
        assert page.locator("[data-freshness='NOT_RUN']").count() == 1, \
            "a Save never creates or triggers a Run"
        saved_value = input_field.input_value()
        assert saved_value.startswith("21.5")

        # ── canonical Run through the existing pathway, then the P&L ───────
        run_via_canonical_path(context, react_enabled, record.project_code)
        page.reload()
        page.wait_for_selector("[data-statement='pnl']")
        post_run_state = page.locator("[data-freshness]").first.get_attribute("data-freshness")
        # Canonical parity, not a hard-coded verdict: the React view must show the
        # SAME freshness state the legacy Statements workspace shows for the same
        # workspace (CURRENT or STALE are both legitimate canonical outcomes).
        legacy_outputs = context.request.get(
            f"{react_enabled}/v2/workbook/outputs?project={record.project_code}")
        assert legacy_outputs.ok
        import re as _re

        match = _re.search(r'data-testid="outputs-state" data-state="([A-Z_]+)"', legacy_outputs.text())
        assert match, "legacy outputs page must expose its canonical state"
        assert post_run_state == match.group(1), \
            f"React freshness {post_run_state} must equal canonical {match.group(1)}"
        assert post_run_state in ("CURRENT", "STALE")
        pnl = page.locator("[data-statement='pnl']")
        assert pnl.count() == 1
        assert pnl.locator("tbody tr").count() >= 3
        for cell in pnl.locator("[data-unavailable='true']").all():
            assert cell.inner_text() == "—"

        # ── a Save after the Run flips input freshness to STALE ────────────
        # A second tab bootstraps NOW, so its identity becomes stale the moment
        # the first tab saves — the canonical CAS must reject it without retry.
        other = context.new_page()
        other.goto(url)
        other.wait_for_selector(CIT_INPUT)
        input_field = page.locator(CIT_INPUT)
        input_field.fill("22.5")
        page.locator("button[type='submit']").click()
        page.wait_for_selector("[data-freshness='STALE']")
        assert page.locator("[data-stale-banner='true']").count() == 1
        assert "not the current inputs" in page.locator("[data-stale-banner='true']").inner_text()

        # ── stale CAS: the second tab's Save is rejected, typed value kept ─
        stale_page_input = other.locator(CIT_INPUT)
        stale_page_input.fill("19")
        other.locator("button[type='submit']").click()
        other.wait_for_selector("[data-save-state='conflict']")
        assert "Reload" in other.locator("button[type='submit']").inner_text()
        assert stale_page_input.input_value() == "19", "a failed Save keeps the typed value"
        other.close()

        assert errors == [], errors
    finally:
        context.close()


def test_react_page_without_project_shows_picker_state(browser, react_enabled):
    context, page, _record, errors = make_session(browser, react_enabled, "rx-noproj-user")
    try:
        page.goto(f"{react_enabled}/v2/model-react")
        page.wait_for_selector("#finco-react-root h1")
        # No project code → bootstrap answers PROJECT_NOT_FOUND → explicit error card.
        page.wait_for_selector("[data-bootstrap-state='PROJECT_NOT_FOUND']")
        assert page.locator("a.rx-legacy-link").count() == 1
        # The deliberate, handled bootstrap 404 surfaces as a browser resource log;
        # what must stay clean is the application itself: no JS exceptions.
        assert not [e for e in errors if "Failed to load resource" not in e], errors
    finally:
        context.close()
