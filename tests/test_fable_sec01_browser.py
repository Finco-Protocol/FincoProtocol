"""FABLE-SEC-01 real-Chromium checks of the legacy New Project form (FINCO 34 batch 1).

* the rendered form carries the bound token and a normal Create succeeds (HX-Redirect followed);
* a stale/forged token is refused with 403 and the user SEES an inline alert (HTMX does not swap 4xx), nothing is created.
"""
from __future__ import annotations

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


def _fill(page, name):
    page.locator("#new-project-minimal-form input[name='template_source']").first.check()
    page.fill("#new-project-minimal-form input[name='project_name']", name)
    page.fill("#new-project-minimal-form input[name='capacity_mw']", "20")


def test_forged_token_shows_a_visible_refusal_and_creates_nothing(live_server, browser):  # noqa: F811
    context = _context(browser, live_server)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{live_server}/projects/new")
    token = page.locator("#new-project-minimal-form input[name='csrf_token']")
    assert token.get_attribute("value")
    token.evaluate("(el) => { el.value = 'forged.token'; }")
    _fill(page, "SEC01 browser forged")
    with page.expect_response(lambda r: r.url.endswith("/projects/create")) as resp:
        page.locator("#new-project-minimal-form [type='submit']").first.click()
    assert resp.value.status == 403
    alert = page.locator("[data-testid='create-csrf-refused']")
    alert.wait_for(timeout=10000)
    assert alert.get_attribute("role") == "alert"
    assert "Nothing was created" in alert.inner_text()
    assert _projects("SEC01 browser forged") == []
    assert not errors
    context.close()


def test_rendered_token_creates_the_project(live_server, browser):  # noqa: F811
    context = _context(browser, live_server)
    page = context.new_page()
    page.goto(f"{live_server}/projects/new")
    _fill(page, "SEC01 browser valid")
    with page.expect_response(lambda r: r.url.endswith("/projects/create")) as resp:
        page.locator("#new-project-minimal-form [type='submit']").first.click()
    assert resp.value.status == 200
    assert resp.value.headers.get("hx-redirect")
    page.wait_for_url(lambda url: "/projects/new" not in url, timeout=30000)
    assert len(_projects("SEC01 browser valid")) == 1
    assert page.locator("[data-testid='create-csrf-refused']").count() == 0
    context.close()
