"""UX-021: a save from a stale view is refused by the server's compare-and-swap and reported once, clearly, with a recovery route (real Chromium, real CSP)."""
from __future__ import annotations

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")

from tests.test_rcux2_ppa_quick_add_browser import browser, live_server  # noqa: F401,E402

FIELD = "project_setup.technical.p50_hours"


def _open(browser, live_server, uid, rec):
    from app.auth import COOKIE_NAME, create_session_token
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username="admin"), "url": live_server}])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "409" not in m.text
            and not str((m.location or {}).get("url", "")).endswith("/favicon.ico") else None)   # the 409 itself is the refusal under test
    page.goto(f"{live_server}/v2/workbook?project={rec.project_code}&sheet=project_setup")
    page.evaluate("document.getElementById('tab-project-setup').click()")
    page.wait_for_selector(f'[data-field-id="{FIELD}"] input[name="value"]', state="attached")
    return ctx, page, errors


def _persisted(uid, rec):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.input_set import ProjectInputSet
    ws = get_workspace_state(uid, rec.project_id)
    return float(ProjectInputSet.from_snapshot(ws.draft_snapshot).get(FIELD))


def test_a_stale_tab_save_is_rejected_once_clearly_without_overwriting_newer_data(live_server, browser):
    from app.services.reference_seed_service import create_reference_seeded_project
    uid = "rcux2-stale-1"
    rec = create_reference_seeded_project(user_id=uid, template_source="generic_solar_reference", requested_name="Stale", capacity_mw=40.0)
    ctx_a, a, errors_a = _open(browser, live_server, uid, rec)
    ctx_b, b, errors_b = _open(browser, live_server, uid, rec)                      # a second, soon stale, view of the same project
    original = _persisted(uid, rec)
    field_a = a.locator(f'[data-field-id="{FIELD}"] input[name="value"]').first
    field_a.fill("1611"); field_a.press("Tab")
    a.wait_for_selector(".v2-field-saved, [data-saved]", timeout=15000) if False else a.wait_for_timeout(2500)
    assert _persisted(uid, rec) == 1611.0                                           # view A saved
    field_b = b.locator(f'[data-field-id="{FIELD}"] input[name="value"]').first
    field_b.fill("1622"); field_b.press("Tab")
    row_b = b.locator(f'[data-field-id="{FIELD}"]').first
    row_b.locator(".v2-field-error-msg").wait_for(timeout=15000)
    messages = row_b.locator(".v2-field-error-msg")
    assert messages.count() == 1                                                     # one inline message at the field
    text = messages.inner_text()
    assert "not saved" in text and "Reload" in text and "values refreshed" not in text   # truthful, with a recovery action
    assert b.locator("[data-testid=banner-error]:visible").count() == 0               # the status banner does not show it a second time
    assert _persisted(uid, rec) == 1611.0 and _persisted(uid, rec) != original       # server-side CAS: the newer value was never overwritten
    assert errors_a == [] and errors_b == [], (errors_a, errors_b)
    row_b.locator("[data-conflict-reload]").click()                                  # explicit reload shows the current value
    b.wait_for_load_state("load")
    b.evaluate("document.getElementById('tab-project-setup').click()")
    assert float(b.locator(f'[data-field-id="{FIELD}"] input[name="value"]').first.input_value()) == 1611.0
    ctx_a.close(); ctx_b.close()
