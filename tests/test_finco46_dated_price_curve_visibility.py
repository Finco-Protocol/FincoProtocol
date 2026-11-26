"""FINCO46: calendar compatibility of explicit per-row price curves is visible BEFORE Save.

FINCO45B made new ordinary Solar/Wind projects ``OD-TIME-01/v1``. On that dated grid an explicit per-row ``price_curve``
is a typed refusal (``REVENUE_V2_DATED_CURVE_UNSUPPORTED``) at Save; the legacy grid keeps the released feature. Before
FINCO46 the editors still offered "Scheduled / price curve" on a dated project and the user only learnt of the refusal
after Save. The editor projection now carries ``price_curve_supported`` derived from the SAME engine admission the Save
validator uses, so the editor can disable the option with the reason; the server refusal is unchanged (defence in depth).

Real HTTP stack, synthetic data only; no financial-engine change.
"""
from __future__ import annotations

import json

import pytest

from app.persistence.run_history_repository import get_run_history
from app.persistence.workspace_repository import get_workspace_state
from app.services import new_project_calendar as npc
from tests.test_model_react_wf2_projections_v1 import OWNER, env  # noqa: F401  (shared real-app fixture)

DATED = "OD-TIME-01/v1"


def _editor(env, record):
    response = env.client.get("/v2/model-react/revenue", params={"project": record.project_code})
    assert response.status_code == 200, response.text[:500]
    return response.json()


def _curve_book(contracts, kind):
    starts = contracts["operating_starts"]
    window = contracts["operating_window"]
    assert starts and window
    return {"version": 2, "technology": kind, "indexation_basis": "OPERATING_YEAR", "streams": [
        {"id": "alpha", "type": "ppa", "volume_share": 0.5, "price_eur_mwh": 50, "indexation_rate": 0,
         "start_date": window["start"], "end_date": window["end"], "settlement": "SAME_PERIOD",
         "source_ref": "synthetic-independent-contract",
         "price_curve": [{"period_start": day, "price_eur_mwh": 55} for day in starts]},
        {"id": "market", "type": "merchant", "volume_share": None, "price_eur_mwh": 80, "indexation_rate": 0,
         "start_date": window["start"], "end_date": window["end"], "settlement": "SAME_PERIOD",
         "source_ref": "synthetic-independent-contract"}]}


def _save(env, record, payload, projection):
    return env.client.post(projection["save"]["url"], data={
        "project": record.project_code, "csrf_token": projection["save"]["csrf_token"],
        "content_hash": projection["save"]["content_hash"], "contracts": json.dumps(payload),
        "contracts_base_token": projection["contracts"].get("base_token") or ""}, follow_redirects=False)


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_dated_project_editor_declares_curves_unsupported_and_save_stays_a_typed_refusal(env, monkeypatch, kind):
    monkeypatch.delenv(npc.ENV, raising=False)            # the released DEFAULT: new Solar/Wind are dated
    record = env.create(kind)
    ws = get_workspace_state(OWNER, record.project_id)
    assert ws.draft_snapshot.get("date_authority_version") == DATED
    projection = _editor(env, record)
    contracts = projection["contracts"]
    # Visible before Save: the projection says curves are not available on this calendar and why.
    assert contracts["price_curve_supported"] is False
    assert contracts["date_authority_version"] == DATED
    assert "REVENUE_V2_DATED_CURVE_UNSUPPORTED" in contracts["price_curve_unsupported_reason"]
    # The legacy HTMX workbook shows the same notice and offers the quick "Scheduled" type disabled.
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")
    html = env.client.get("/v2/workbook", params={"project": record.project_code}).text
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    assert 'data-price-curve-supported="false"' in html and 'data-testid="revenue-curve-calendar-notice"' in html
    assert '<option value="scheduled_ppa" disabled>' in html
    # The server refusal is unchanged (defence in depth): typed 422, nothing written, no history.
    before = dict(get_workspace_state(OWNER, record.project_id).draft_snapshot)
    response = _save(env, record, _curve_book(contracts, kind), projection)
    assert response.status_code == 422 and "REVENUE_V2_DATED_CURVE_UNSUPPORTED" in response.json()["error"]
    assert get_workspace_state(OWNER, record.project_id).draft_snapshot == before
    assert get_run_history(OWNER, record.project_id) == []
    # The supported dated equivalent (fixed / indexed contract, no per-row curve) saves.
    plain = _curve_book(contracts, kind)
    plain["streams"][0].pop("price_curve")
    plain["streams"][0]["indexation_rate"] = 0.02
    saved = _save(env, record, plain, projection)
    assert saved.status_code == 303, saved.text[:500]
    assert json.loads(get_workspace_state(OWNER, record.project_id).draft_snapshot["rev_multistream_config_json"])["streams"][0]["id"] == "alpha"


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_legacy_project_keeps_the_released_curve_feature(env, monkeypatch, kind):
    monkeypatch.setenv(npc.ENV, "legacy")                 # explicit creation rollback = LEGACY_CALENDAR/v0
    record = env.create(kind)
    assert get_workspace_state(OWNER, record.project_id).draft_snapshot.get("date_authority_version") != DATED
    projection = _editor(env, record)
    contracts = projection["contracts"]
    assert contracts["price_curve_supported"] is True
    assert contracts["price_curve_unsupported_reason"] == ""
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")
    html = env.client.get("/v2/workbook", params={"project": record.project_code}).text
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    assert 'data-price-curve-supported="true"' in html and 'revenue-curve-calendar-notice' not in html
    response = _save(env, record, _curve_book(contracts, kind), projection)
    assert response.status_code == 303, response.text[:500]
    saved = json.loads(get_workspace_state(OWNER, record.project_id).draft_snapshot["rev_multistream_config_json"])
    assert saved["streams"][0]["price_curve"]
