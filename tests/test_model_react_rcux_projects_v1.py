"""RC-UX Addendum B — "My Projects" Library and Project Template catalogue (read-only adapters over the canonical authorities).

Real projects, real Runs, real timestamps.  The Library never contains system reference models; templates are never modified by creating
a project from them; a missing value is ``None`` (never a placeholder).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from tests.run_clone_csrf import post_valid_csrf
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401  (fixture)

OWNER = "decision-user"
LIST = "/v2/model-react/my-projects"
TEMPLATES = "/v2/model-react/templates"


@pytest.fixture
def lib(env, monkeypatch):  # noqa: F811
    from app.v2.react_projects import router
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    env.client.app.include_router(router, prefix="/v2")
    return env


def make(name, kind="solar", capacity=16, country=None, user=OWNER):
    from app.services.reference_seed_service import create_reference_seeded_project
    return create_reference_seeded_project(user_id=user, requested_name=name, template_source=f"generic_{kind}_reference",
                                           capacity_mw=capacity, country_market=country)


def listing(env, **params):
    response = env.client.get(LIST, params=params)
    assert response.status_code == 200, response.text[:500]
    return response.json()


def run(env, record):
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    assert post_valid_csrf(env.client, "/v2/workbook/run", headers={"HX-Request": "true"},
                           data={"project": record.project_code, **tokens(page.text)}).status_code == 200


def db_dump():
    from app.persistence import db
    with sqlite3.connect(db.DB_PATH) as conn:
        return "\n".join(conn.iterdump())


def test_router_is_mounted_before_the_project_catch_all():
    from app.v2.router import router
    paths = [getattr(route, "path", "") for route in router.routes]
    for path in ("/model-react/my-projects", "/model-react/templates"):
        assert paths.count(path) == 1 and paths.index(path) < paths.index("/model-react/{project_code}")


def test_an_account_without_projects_gets_an_empty_library_and_no_system_references(lib):
    from app.services.project_library_service import ensure_reference_models
    from app.persistence.projects_repository import get_reference_projects
    ensure_reference_models()
    assert get_reference_projects(), "reference models exist in the database"
    data = listing(lib)
    assert data["projects"] == [] and data["total"] == 0 and data["total_all"] == 0
    assert data["facets"] == {"technologies": [], "countries": []}


def test_my_projects_lists_only_own_editable_projects_with_real_business_fields(lib):
    from app.persistence.workspace_repository import get_workspace_state
    solar = make("Alpha Solar", "solar", 20, "XA")
    wind = make("Beta Wind", "wind", 48, None)
    foreign = make("Foreign Solar", "solar", 10, "XA", user="someone-else")
    data = listing(lib)
    assert {p["name"] for p in data["projects"]} == {"Alpha Solar", "Beta Wind"} and data["total"] == 2
    by = {p["name"]: p for p in data["projects"]}
    a = by["Alpha Solar"]
    assert a["technology"]["label"] == "Solar PV" and a["capacity_mw"] == 20.0 and a["country"] == {"code": "XA", "label": "Generic / World — Solar"}
    assert by["Beta Wind"]["technology"]["label"] == "Onshore Wind" and by["Beta Wind"]["country"]["code"] == "XB"     # the creator stores the template's default market when none is chosen
    ws = get_workspace_state(OWNER, solar.project_id)
    assert datetime.fromisoformat(a["last_updated"]) == max(ws.updated_at, solar.updated_at)                 # the real saved activity time
    assert a["last_run"] == {"available": False, "at": None, "snapshot_id": None} and a["has_runs"] is False
    assert a["freshness"] == "NOT_RUN" and a["status"] == "Not run yet"
    assert a["links"]["open"] == f"/v2/model-react/{solar.project_code}" and a["links"]["run_history"].endswith("?analysis=runs#analysis")
    assert foreign.project_code not in json.dumps(data)
    assert all("reference" not in json.dumps(p).lower() for p in data["projects"])


def test_run_state_labels_follow_the_canonical_freshness_and_the_last_run_time_is_real(lib):
    from app.persistence.workspace_repository import get_workspace_state
    record = make("Run Me")
    run(lib, record)
    p = listing(lib)["projects"][0]
    ws = get_workspace_state(OWNER, record.project_id)
    assert p["freshness"] == "CURRENT" and p["status"] == "Results up to date" and p["has_runs"] is True
    assert datetime.fromisoformat(p["last_run"]["at"]) == ws.last_runtime_at and p["last_run"]["available"] is True
    page = lib.client.get("/v2/workbook", params={"project": record.project_code})
    r = post_valid_mutation_update(lib, record, page.text)
    assert r.status_code == 200
    after = listing(lib)["projects"][0]
    assert after["freshness"] == "STALE" and after["status"] == "Results outdated"
    assert datetime.fromisoformat(after["last_updated"]) > datetime.fromisoformat(p["last_updated"])           # a Save moves "last updated"
    assert after["last_run"]["at"] == p["last_run"]["at"]                                                      # and never the last Run


def post_valid_mutation_update(env, record, html):
    from tests.model_mutation_csrf import post_valid_mutation
    return post_valid_mutation(env.client, "/v2/workbook/update", headers={"HX-Request": "true"},
                               data={"project": record.project_code, "field_id": "debt.senior.target_dscr", "value": "1.25", **tokens(html)})


def test_filters_sort_search_and_pagination(lib):
    from app.persistence import db
    a = make("Alpha Solar", "solar", 20, "XA")
    b = make("Beta Wind", "wind", 48, "XB")
    c = make("Gamma Data", "data_center", 20, "XD")
    run(lib, b)
    assert [p["name"] for p in listing(lib, technology="wind")["projects"]] == ["Beta Wind"]
    assert [p["name"] for p in listing(lib, country="XD")["projects"]] == ["Gamma Data"]
    assert [p["name"] for p in listing(lib, has_runs="1")["projects"]] == ["Beta Wind"]
    assert [p["name"] for p in listing(lib, status="current")["projects"]] == ["Beta Wind"]
    assert {p["name"] for p in listing(lib, status="not_run")["projects"]} == {"Alpha Solar", "Gamma Data"}
    searched = listing(lib, search="gamma")
    assert [p["name"] for p in searched["projects"]] == ["Gamma Data"] and searched["total_all"] == 3          # the search never hides that projects exist
    assert listing(lib, search="no-such-name")["total_all"] == 3 and listing(lib, search="no-such-name")["total"] == 0
    assert {t["key"] for t in searched["facets"]["technologies"]} == {"solar", "wind", "data_center"}
    assert listing(lib, search="%")["projects"] == [] and listing(lib, search="_")["projects"] == []        # wildcards are literals
    names = [p["name"] for p in listing(lib, sort="name")["projects"]]
    assert names == sorted(names, key=str.casefold)
    assert listing(lib, sort="last_run")["projects"][0]["name"] == "Beta Wind"                                # Runs first, never-run last
    assert listing(lib)["projects"][0]["name"] == "Beta Wind"                                                # the Run touched it last: most recent first
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    with sqlite3.connect(db.DB_PATH) as conn:
        conn.execute("UPDATE workspace_states SET updated_at=? WHERE project_id=?", (old, a.project_id))
        conn.execute("UPDATE projects SET updated_at=? WHERE project_id=?", (old, a.project_id))
    assert "Alpha Solar" not in [p["name"] for p in listing(lib, edited="30")["projects"]]
    assert "Alpha Solar" in [p["name"] for p in listing(lib, edited="90")["projects"]]
    facets = listing(lib)["facets"]
    assert {t["key"]: t["count"] for t in facets["technologies"]} == {"solar": 1, "wind": 1, "data_center": 1}
    assert {c["code"] for c in facets["countries"]} == {"XA", "XB", "XD"}
    data = listing(lib)
    assert data["total"] == data["total_all"] == 3 and data["page"] == 1 and data["total_pages"] == 1
    for bad in ({"status": "nope"}, {"edited": "5"}, {"sort": "random"}, {"search": "x" * 200}):
        assert lib.client.get(LIST, params=bad).status_code == 422
    assert c  # silence unused


def test_archived_projects_are_listed_only_on_request_and_pages_are_bounded(lib):
    from app.persistence import db
    live, gone = make("Live"), make("Gone")
    with sqlite3.connect(db.DB_PATH) as conn:
        conn.execute("UPDATE projects SET archived=1 WHERE project_id=?", (gone.project_id,))
    assert [p["name"] for p in listing(lib)["projects"]] == ["Live"]
    arch = listing(lib, archived="1")
    assert [p["name"] for p in arch["projects"]] == ["Gone"] and arch["archived"] is True and arch["projects"][0]["archived"] is True
    for i in range(14):
        make(f"Many {i}")
    page2 = listing(lib, page=2)
    assert page2["page"] == 2 and page2["total_pages"] == 2 and len(page2["projects"]) == 3 and page2["total"] == 15
    assert listing(lib, page=99)["page"] == 2 and live


def test_templates_are_system_templates_with_registry_starting_assumptions_and_are_never_modified_by_creation(lib):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.workbook.input_set import ProjectInputSet
    from app.workbook.registry import WORKBOOK
    before_cards = lib.client.get(TEMPLATES)
    assert before_cards.status_code == 200
    cards = before_cards.json()["templates"]
    assert [c["key"] for c in cards] == ["solar", "wind", "data_center", "ev_charging"]            # storage is not released: no card
    assert all(c["creatable"] for c in cards)
    text = json.dumps(before_cards.json())
    assert "generic_" not in text and "template_source" not in text and "-reference" not in text      # no internal identifiers
    ref = get_reference_by_template_source("generic_solar_reference")
    snapshot_before, updated_before = json.dumps(ref.baseline_snapshot, sort_keys=True), ref.updated_at
    solar = next(c for c in cards if c["key"] == "solar")
    pis = ProjectInputSet.from_snapshot(ref.baseline_snapshot)
    assert solar["capacity_mw"] == float(pis.get("project_setup.technical.capacity_mw")) == 64.0
    shown = {a["label"]: a for a in solar["starting_assumptions"]}
    assert shown["PPA tariff"]["value"] == "50" and shown["PPA tariff"]["unit"] == WORKBOOK.field("revenue.ppa.base_tariff").unit
    assert shown["Target DSCR"]["value"] == "1.2" and shown["Target DSCR"]["unit"] == "x"
    assert shown["All-in Interest Rate"]["value"] == "5.5" and shown["All-in Interest Rate"]["unit"] == "%"
    assert solar["timeline"]["construction_months"] == 14 and "Generic Tax Template" in solar["market_note"]
    assert next(c for c in cards if c["key"] == "data_center")["capacity_label"] == "IT capacity"
    assert next(c for c in cards if c["key"] == "wind")["pilot_tier"] == "PILOT_CANDIDATE"
    assert next(c for c in cards if c["key"] == "ev_charging")["preview_acknowledgement_required"] is True
    make("From template", "solar", 30)                                                              # creation never touches the template
    again = get_reference_by_template_source("generic_solar_reference")
    assert json.dumps(again.baseline_snapshot, sort_keys=True) == snapshot_before and again.updated_at == updated_before
    assert [p["name"] for p in listing(lib)["projects"]] == ["From template"]                     # and the template is not a project


def test_reads_never_write_and_security_flag_auth(lib, monkeypatch):
    from app.auth import COOKIE_NAME, create_session_token
    make("Mine")
    listing(lib)
    lib.client.get(TEMPLATES)
    before = db_dump()
    for _ in range(2):
        listing(lib)
        lib.client.get(TEMPLATES)
    assert db_dump() == before
    for path in (LIST, TEMPLATES):
        assert lib.client.post(path).status_code == 405
        with lib.client.__class__(lib.client.app) as anon:
            assert anon.get(path, follow_redirects=False).status_code == 401
        with lib.client.__class__(lib.client.app) as other:
            other.cookies.set(COOKIE_NAME, create_session_token(user_id="foreign-user", username="x"))
            if path == LIST:
                assert other.get(path).json()["projects"] == []                                   # another account sees none of Mine
    monkeypatch.delenv("FINCO_MODEL_REACT_V1")
    assert lib.client.get(LIST).status_code == 404 and lib.client.get(TEMPLATES).status_code == 404
