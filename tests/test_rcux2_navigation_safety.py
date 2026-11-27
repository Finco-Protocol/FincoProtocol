"""UX-027: an unknown or inaccessible project gives one clear, non-revealing message instead of an unexplained redirect.

FINCO47: React is the default product. The canonical witnesses are the default-mode redirect to
``/v2/model-react/?notice=project-unavailable`` and the fixed notice the React My Projects view renders after the
browser follows it. The legacy ``/library`` behaviour is still pinned, but only under the explicit rollback flag.
"""
import pytest
from fastapi.testclient import TestClient

from tests.test_workflow_c_browser_v1 import live_server, browser  # noqa: F401  (real-Chromium fixtures)

NOTICE_TEXT = "That project is not available. It may have been removed or you may not have access to it."
REACT_UNAVAILABLE = "/v2/model-react/?notice=project-unavailable"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app.persistence import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "nav.db"))
    db.init_db()
    monkeypatch.delenv("FINCO_MODEL_REACT_V1", raising=False)  # production default: React ON
    import main_web
    with TestClient(main_web.app, follow_redirects=False) as c:
        yield c


def _login(client, uid):
    from app.auth import COOKIE_NAME, create_session_token
    client.cookies.set(COOKIE_NAME, create_session_token(user_id=uid, username=uid))


def test_default_unknown_project_redirects_to_react_my_projects_with_a_fixed_notice(client):
    _login(client, "nav-a")
    r = client.get("/v2/workbook", params={"project": "no-such-project"})
    assert r.status_code == 302 and r.headers["location"] == REACT_UNAVAILABLE
    landing = client.get(r.headers["location"], follow_redirects=True)
    assert landing.status_code == 200 and "text/html" in landing.headers["content-type"]
    assert 'id="root"' in landing.text or "finco-react" in landing.text  # the React shell, not a legacy page


def test_flag_zero_unknown_project_still_redirects_to_react_with_fixed_notice(client, monkeypatch):
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")
    _login(client, "nav-a")
    r = client.get("/v2/workbook", params={"project": "no-such-project"})
    assert r.status_code == 302 and r.headers["location"] == REACT_UNAVAILABLE
    landing = client.get(r.headers["location"], follow_redirects=True)
    assert landing.status_code == 200 and ('id="root"' in landing.text or "finco-react" in landing.text)


@pytest.mark.parametrize("flag", [None, "0"])
def test_another_users_project_gets_exactly_the_same_response_as_an_unknown_one(client, monkeypatch, flag):
    from app.services.reference_seed_service import create_reference_seeded_project
    if flag is not None:
        monkeypatch.setenv("FINCO_MODEL_REACT_V1", flag)
    record = create_reference_seeded_project(user_id="nav-owner", template_source="generic_solar_reference", requested_name="Private", capacity_mw=10.0)
    _login(client, "nav-intruder")
    mine = client.get("/v2/workbook", params={"project": record.project_code})
    unknown = client.get("/v2/workbook", params={"project": "no-such-project"})
    assert (mine.status_code, mine.headers["location"]) == (unknown.status_code, unknown.headers["location"])  # no way to tell them apart
    assert "notice=project-unavailable" in mine.headers["location"]


def test_default_notice_query_is_a_whitelist_and_never_reflected_or_an_open_redirect(client):
    _login(client, "nav-c")
    for hostile in ("<script>alert(1)</script>", "https://evil.example/", "//evil.example", "project-unavailable%0d%0aSet-Cookie:x=1"):
        r = client.get("/library", params={"notice": hostile})
        loc = r.headers.get("location", "")
        assert r.status_code in (200, 302)
        assert "evil.example" not in loc and "<script>" not in loc and "Set-Cookie" not in loc, (hostile, loc)
        if r.status_code == 302:
            assert loc.startswith("/v2/model-react/") or loc.startswith("/library"), loc
        page = client.get(loc, follow_redirects=True) if r.status_code == 302 else r
        assert "<script>alert(1)" not in page.text and 'data-testid="library-notice"' not in page.text


def test_flag_zero_notice_is_never_echoed_in_redirect_or_shell(client, monkeypatch):
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")
    _login(client, "nav-c")
    r = client.get("/library", params={"notice": "<script>alert(1)</script>"})
    assert r.status_code == 302
    loc = r.headers.get("location", "")
    assert loc.startswith("/v2/model-react/") and "<script>" not in loc
    page = client.get(loc, follow_redirects=True)
    assert page.status_code == 200 and "<script>alert(1)" not in page.text


def _cookie(context, base, uid):
    from app.auth import COOKIE_NAME, create_session_token
    context.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username=uid), "url": base}])


def test_browser_shows_the_fixed_notice_after_following_the_redirect_and_never_echoes_text(live_server, browser):
    # live_server is the in-process app with the production default (React ON): no per-test flag override here.
    import os
    assert os.environ.get("FINCO_MODEL_REACT_V1") != "0"
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    try:
        _cookie(context, live_server, "nav-browser")
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(live_server + "/v2/workbook?project=no-such-project", wait_until="load")
        assert page.url.startswith(live_server + "/v2/model-react"), page.url
        notice = page.locator('[data-testid="library-notice"]')
        notice.wait_for(timeout=20000)
        assert notice.inner_text().strip() == NOTICE_TEXT
        assert page.locator('[data-library-view="true"]').count() == 1  # canonical My Projects, not a legacy page
        # hostile text in the query is never rendered
        page.goto(live_server + "/v2/model-react/?notice=%3Cb%3Eowned%3C/b%3E", wait_until="load")
        page.locator('[data-library-view="true"]').wait_for(timeout=20000)
        assert page.locator('[data-testid="library-notice"]').count() == 0
        assert "owned" not in page.locator("body").inner_text()
        assert not errors, errors
    finally:
        context.close()
