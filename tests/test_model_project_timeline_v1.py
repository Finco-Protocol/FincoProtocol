"""WF-10 Project Timeline V1: read-only server contract (persisted values, no mutation, no Run) for Solar, Wind, Data Center and EV Charging."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from tests.test_model_decision_workspace_v2 import env  # noqa: F401  (fixture)

USER = "decision-user"
ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("project_setup.technical.cod_date", "project_setup.technical.construction_months", "project_setup.technical.horizon_years")


def _persisted(record):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.input_set import ProjectInputSet
    ws = get_workspace_state(USER, record.project_id)
    pis = ProjectInputSet.from_snapshot(ws.draft_snapshot)
    return {f: pis.get(f) for f in FIELDS}


def _timeline(html):
    return BeautifulSoup(html, "html.parser").select_one("[data-project-timeline]")


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_timeline_carries_exactly_the_persisted_values_for_every_vertical(env, kind):
    record = env.create(kind)
    persisted = _persisted(record)
    html = env.client.get("/v2/workbook", params={"project": record.project_code, "sheet": "project_setup"}).text
    node = _timeline(html)
    assert node is not None
    assert node["data-cod"] == str(persisted[FIELDS[0]]) and node["data-months"] == str(persisted[FIELDS[1]])
    assert node["data-horizon"] == str(persisted[FIELDS[2]])
    fallback = node.select_one('[data-testid="project-timeline-fallback"]').get_text(" ", strip=True)
    assert str(persisted[FIELDS[0]]) in fallback                         # understandable without JavaScript


def test_the_timeline_section_exists_once_and_has_no_duplicate_ids(env):
    record = env.create("solar")
    html = env.client.get("/v2/workbook", params={"project": record.project_code}).text
    soup = BeautifulSoup(html, "html.parser")
    assert len(soup.select("[data-project-timeline]")) == 1
    ids = [n["id"] for n in soup.select("[id]")]
    assert len(ids) == len(set(ids)), sorted({i for i in ids if ids.count(i) > 1})
    assert html.count("/static/js/model_project_timeline.js") == 1


def test_viewing_the_timeline_never_runs_the_model_or_mutates_inputs_or_history(env, monkeypatch):
    import app.api.project_runner as runner
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create("solar")
    env.client.get("/v2/workbook", params={"project": record.project_code})
    before = get_workspace_state(USER, record.project_id)
    history = get_run_history(USER, record.project_id)
    monkeypatch.setattr(runner, "run_project", lambda *a, **k: (_ for _ in ()).throw(AssertionError("viewing must not run the model")))
    for _ in range(2):
        for url in ("/v2/workbook", "/v2/workbook/grid/sheet"):
            params = {"project": record.project_code, "sheet": "project_setup"}
            assert env.client.get(url, params=params).status_code in (200, 404)
    after = get_workspace_state(USER, record.project_id)
    assert after == before and get_run_history(USER, record.project_id) == history


def test_timeline_renders_for_a_read_only_reference_and_shows_no_editing_affordance():
    from app.v2.router import _templates
    fields = [{"field_id": FIELDS[0], "value": "2031-03-01", "label": "COD", "section_id": "t", "section_label": "T", "field_type": "date"},
              {"field_id": FIELDS[1], "value": 14, "label": "Months", "section_id": "t", "section_label": "T", "field_type": "number"},
              {"field_id": FIELDS[2], "value": 25, "label": "Horizon", "section_id": "t", "section_label": "T", "field_type": "number"}]
    html = _templates.get_template("partials/sheet_project_setup.html").render(
        {"ps_fields": fields, "project_code": "ref", "workbook_version": "v", "content_hash": "h", "project_editable": False, "field_error": ""})
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one("[data-project-timeline]")
    assert node["data-cod"] == "2031-03-01" and node["data-months"] == "14" and node["data-horizon"] == "25"
    assert not node.select("input, button, select, textarea, form, [hx-post]")
    assert soup.select_one("[data-construction-timing]") is None          # the editor stays editable-only; the timeline is read-only everywhere


def test_missing_values_render_as_unavailable_not_as_dates():
    from app.v2.router import _templates
    fields = [{"field_id": FIELDS[2], "value": None, "label": "Horizon", "section_id": "t", "section_label": "T", "field_type": "number"}]
    html = _templates.get_template("partials/sheet_project_setup.html").render(
        {"ps_fields": fields, "project_code": "p", "workbook_version": "v", "content_hash": "h", "project_editable": True, "field_error": ""})
    node = BeautifulSoup(html, "html.parser").select_one("[data-project-timeline]")
    assert node["data-cod"] == "" and node["data-months"] == "" and node["data-horizon"] == ""
    assert node.get_text(" ", strip=True).count("Not available") == 3


def test_unavailable_milestones_are_listed_and_never_given_dates():
    from app.v2.router import _templates
    html = _templates.get_template("partials/sheet_project_setup.html").render(
        {"ps_fields": [{"field_id": FIELDS[0], "value": "2031-03-01", "label": "c", "section_id": "t", "section_label": "T", "field_type": "date"}],
         "project_code": "p", "workbook_version": "v", "content_hash": "h", "project_editable": True, "field_error": ""})
    block = BeautifulSoup(html, "html.parser").select_one('[data-testid="project-timeline-unavailable"]').get_text(" ", strip=True)
    for name in ("Financial Close", "Notice to Proceed", "Debt drawdown dates", "Refinancing date", "Financing maturity", "Decommissioning"):
        assert name in block
    assert not re.search(r"\d{4}-\d{2}-\d{2}", block)


def test_workstream_touches_no_forbidden_file_and_adds_no_second_date_authority():
    js = (ROOT / "static/js/model_project_timeline.js").read_text()
    assert "fetch(" not in js and "XMLHttpRequest" not in js and "htmx.ajax" not in js            # read-only: never saves, never fetches
    assert "FincoDates.addMonths" in js or "dates.addMonths" in js                                  # the existing calendar convention is reused
    assert "365" not in js and "* 30" not in js
