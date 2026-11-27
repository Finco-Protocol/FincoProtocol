"""FABLE-SEC-01 real-Chromium checks of the React New Project CSRF boundary (FINCO 34 -> FINCO48).

* a valid wizard submission sends the bound CSRF token and creates the project (200 JSON + navigation);
* a forged CSRF token is refused with 403 CSRF_INVALID, displays a visible alert, and creates nothing.
"""
from __future__ import annotations

import json

from tests.test_workflow_c_browser_v1 import live_server, browser  # noqa: F401


USER = "sec01-browser"


def _context(browser, live_server):  # noqa: F811
    from app.auth import COOKIE_NAME, create_session_token
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    context.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=USER, username="admin"),
                          "url": live_server}])
    return context


def _projects(name):
    from app.persistence.projects_repository import list_projects_paged
    records, _ = list_projects_paged(user_id=USER, page_size=500)
    return [r for r in records if r.project_name == name]


def _advance_to_review(page, live_server, name):
    page.goto(f"{live_server}/v2/model-react/#new-project/template", wait_until="load")
    card = page.locator('[data-template-card="solar"][data-creatable="true"]')
    card.wait_for(timeout=20000)
    card.click()
    page.locator('[data-wizard-next="true"]').click()
    page.locator('[data-wizard-panel="details"]').wait_for(timeout=15000)
    page.locator("#rcm-name").fill(name)
    page.locator('[data-wizard-next="true"]').click()
    create_btn = page.locator('[data-wizard-create="true"]')
    create_btn.wait_for(timeout=15000)
    return create_btn


def test_forged_token_shows_a_visible_refusal_and_creates_nothing(live_server, browser):  # noqa: F811
    context = _context(browser, live_server)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    create_btn = _advance_to_review(page, live_server, "SEC01 browser forged")

    def _forge_csrf(route):
        req = route.request
        payload = json.loads(req.post_data or "{}")
        payload["csrf_token"] = "forged.token"
        route.continue_(post_data=json.dumps(payload))

    page.route("**/v2/model-react/new-project/create", _forge_csrf)
    with page.expect_response(lambda r: "/v2/model-react/new-project/create" in r.url) as resp:
        create_btn.click()
    assert resp.value.status == 403
    assert resp.value.json()["code"] == "CSRF_INVALID"
    alert = page.locator("[data-wizard-error='true']")
    alert.wait_for(timeout=10000)
    assert alert.get_attribute("role") == "alert"
    assert _projects("SEC01 browser forged") == []
    assert not errors
    context.close()


def test_rendered_token_creates_the_project(live_server, browser):  # noqa: F811
    context = _context(browser, live_server)
    page = context.new_page()
    create_btn = _advance_to_review(page, live_server, "SEC01 browser valid")
    with page.expect_response(lambda r: "/v2/model-react/new-project/create" in r.url) as resp:
        create_btn.click()
    assert resp.value.status == 200
    page.wait_for_url(
        lambda url: "/v2/model-react/" in url and "new-project" not in url,
        timeout=30000,
    )
    assert len(_projects("SEC01 browser valid")) == 1
    assert page.locator("[data-wizard-error='true']").count() == 0
    context.close()
