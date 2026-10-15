"""UX-027: an unknown or inaccessible project gives one clear, non-revealing message instead of an unexplained redirect."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app.persistence import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "nav.db"))
    db.init_db()
    import main_web
    with TestClient(main_web.app, follow_redirects=False) as c:
        yield c


def _login(client, uid):
    from app.auth import COOKIE_NAME, create_session_token
    client.cookies.set(COOKIE_NAME, create_session_token(user_id=uid, username=uid))


def test_unknown_project_redirects_to_the_library_with_a_fixed_notice(client):
    _login(client, "nav-a")
    r = client.get("/v2/workbook", params={"project": "no-such-project"})
    assert r.status_code == 302 and r.headers["location"] == "/library?notice=project-unavailable"
    page = client.get("/library", params={"notice": "project-unavailable"})
    assert page.status_code == 200 and 'data-testid="library-notice"' in page.text and "not available" in page.text


def test_another_users_project_gets_exactly_the_same_response_as_an_unknown_one(client):
    from app.services.reference_seed_service import create_reference_seeded_project
    record = create_reference_seeded_project(user_id="nav-owner", template_source="generic_solar_reference", requested_name="Private", capacity_mw=10.0)
    _login(client, "nav-intruder")
    mine = client.get("/v2/workbook", params={"project": record.project_code})
    unknown = client.get("/v2/workbook", params={"project": "no-such-project"})
    assert (mine.status_code, mine.headers["location"]) == (unknown.status_code, unknown.headers["location"])    # no way to tell them apart


def test_the_notice_is_a_fixed_vocabulary_never_echoed_text(client):
    _login(client, "nav-c")
    page = client.get("/library", params={"notice": "<script>alert(1)</script>"})
    assert page.status_code == 200 and 'data-testid="library-notice"' not in page.text and "<script>alert(1)" not in page.text
